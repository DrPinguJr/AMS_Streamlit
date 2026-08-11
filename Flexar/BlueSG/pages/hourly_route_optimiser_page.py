"""Rolling-window dispatch page for hourly BlueSG job releases."""

from __future__ import annotations

import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Flexar.BlueSG.build_optimised_vehicle_routes import (
    clean_text,
    get_cached_geocode,
    stable_job_id_from_route_row,
)
from Flexar.BlueSG.hourly_dispatch_ledger import (
    HourlyLedgerState,
    load_hourly_ledger,
    save_hourly_ledger,
)
from Flexar.BlueSG.hourly_route_dispatch import (
    active_riders_for_dispatch,
    append_hourly_jobs,
    archive_completed_prefix,
    live_shift_timeline,
    open_jobs_for_dispatch,
    operation_context_for_riders,
    run_hourly_dispatch,
    solve_with_standby_options,
    standby_riders_for_dispatch,
)
from Flexar.BlueSG.job_import_staging import ImportResult, parse_job_source, validate_staged_jobs
from Flexar.BlueSG.optimiser_workflow_state import (
    initialise_workflow_state,
    normalise_riders,
    save_rider_draft,
    validate_rider_draft,
)
from Flexar.BlueSG.v2_daily_roster_source import load_daily_v2_roster
from Flexar.BlueSG.vehicle_route_optimiser_v2 import WorkStyle


@st.cache_data(show_spinner=False)
def _parse_upload(payload: bytes, filename: str) -> ImportResult:
    class NamedBytesIO(BytesIO):
        pass

    source = NamedBytesIO(payload)
    source.name = filename
    return parse_job_source(uploaded_file=source)


@st.cache_data(show_spinner=False)
def _parse_paste(text: str) -> ImportResult:
    return parse_job_source(pasted_text=text)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=1024)
def _map_geocode(address: str) -> dict[str, object]:
    result = get_cached_geocode(address, token=None, use_onemap=True)
    return {
        "lat": result.latitude,
        "lon": result.longitude,
        "source": result.source,
        "error": result.error,
    }


def render_job_importer(dispatch_at: datetime) -> None:
    """Render the existing import pattern in append mode for an hourly release."""

    st.subheader("Hourly job release")
    with st.form("hourly_job_release_form"):
        source_columns = st.columns([1, 1.4])
        uploaded = source_columns[0].file_uploader(
            "Upload Excel or CSV",
            type=["xlsx", "xls", "xlsm", "csv"],
            key="hourly_jobs_upload",
        )
        pasted = source_columns[1].text_area(
            "Paste Flexar data",
            height=100,
            key="hourly_jobs_paste",
            placeholder="Paste this hour's Flexar rows.",
        )
        stage_clicked = st.form_submit_button(
            "Stage hourly release",
            icon=":material/upload_file:",
        )

    if stage_clicked:
        if uploaded is None and not pasted.strip():
            st.session_state.hourly_import_error = "Upload a file or paste job rows first."
        else:
            try:
                parsed = (
                    _parse_upload(uploaded.getvalue(), uploaded.name)
                    if uploaded is not None
                    else _parse_paste(pasted)
                )
                validation = validate_staged_jobs(parsed.dataframe)
            except Exception as exc:
                st.session_state.hourly_import_error = f"Could not stage jobs: {exc}"
            else:
                st.session_state.hourly_staged_jobs = validation.dataframe
                st.session_state.hourly_staged_validation = validation
                st.session_state.hourly_import_error = ""

    if st.session_state.get("hourly_import_error"):
        st.error(st.session_state.hourly_import_error)
    validation = st.session_state.get("hourly_staged_validation")
    if validation is None:
        st.caption("Stage the new release, verify it, then commit and append it to the shared job list.")
        return
    if not validation.is_valid:
        for issue in validation.issues:
            (st.error if issue.severity == "error" else st.warning)(issue.message)
        return

    st.success(f"{len(validation.dataframe)} valid job(s) ready to append")
    st.dataframe(validation.dataframe, hide_index=True, height=240)
    if st.button(
        "Commit and append",
        type="primary",
        icon=":material/add_task:",
        key="hourly_commit_append",
    ):
        try:
            result = append_hourly_jobs(
                st.session_state.committed_jobs,
                validation.dataframe,
                released_at=dispatch_at,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.committed_jobs = result.dataframe
            st.session_state.job_draft = result.dataframe.copy(deep=True)
            st.session_state.hourly_staged_jobs = pd.DataFrame()
            st.session_state.hourly_staged_validation = None
            message = f"Appended {len(result.appended_job_ids)} job(s)."
            if result.ignored_job_ids:
                message += f" Ignored {len(result.ignored_job_ids)} already-committed job(s)."
            st.session_state.hourly_notice = message
            persist_hourly_ledger()
            st.rerun()


def show_route_map(route_df: pd.DataFrame) -> None:
    """Use the optimiser's cached OneMap geocodes in a live dispatch map."""

    if route_df is None or route_df.empty:
        return
    riders = list(route_df["Rider"].dropna().astype(str).drop_duplicates())
    selected = st.selectbox("Map rider", ["All riders", *riders], key="hourly_map_rider")
    visible = route_df if selected == "All riders" else route_df[route_df["Rider"] == selected]
    palette = [
        [37, 99, 235],
        [5, 150, 105],
        [217, 119, 6],
        [147, 51, 234],
        [220, 38, 38],
    ]
    colours = {rider: palette[index % len(palette)] for index, rider in enumerate(riders)}
    point_rows: list[dict[str, object]] = []
    path_rows: list[dict[str, object]] = []
    for _, route in visible.iterrows():
        rider = clean_text(route.get("Rider"))
        colour = colours.get(rider, [37, 99, 235])
        locations = [
            ("Start", clean_text(route.get("Start From"))),
            ("Pickup", clean_text(route.get("Pickup Address"))),
            ("Drop-off", clean_text(route.get("Drop-off Address"))),
        ]
        coordinates: list[list[float]] = []
        for kind, address in locations:
            if not address:
                continue
            geocode = _map_geocode(address)
            if geocode.get("lat") is None or geocode.get("lon") is None:
                continue
            coordinate = [float(geocode["lon"]), float(geocode["lat"])]
            coordinates.append(coordinate)
            point_rows.append(
                {
                    "position": coordinate,
                    "color": colour,
                    "tooltip": f"{rider}<br/>{kind}: {address}",
                }
            )
        if len(coordinates) >= 2:
            path_rows.append(
                {
                    "path": coordinates,
                    "color": colour,
                    "tooltip": f"{rider} · job {route.get('Sequence')}",
                }
            )
    if not point_rows:
        st.warning("No route locations could be geocoded for the live map.")
        return
    point_df = pd.DataFrame(point_rows)
    path_df = pd.DataFrame(path_rows)
    mean_lon = sum(row["position"][0] for row in point_rows) / len(point_rows)
    mean_lat = sum(row["position"][1] for row in point_rows) / len(point_rows)
    layers = []
    if not path_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                path_df,
                get_path="path",
                get_color="color",
                width_min_pixels=4,
                pickable=True,
            )
        )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            point_df,
            get_position="position",
            get_fill_color="color",
            get_radius=80,
            radius_min_pixels=5,
            pickable=True,
        )
    )
    deck = pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        initial_view_state=pdk.ViewState(latitude=mean_lat, longitude=mean_lon, zoom=10.5),
        layers=layers,
        tooltip={"html": "{tooltip}"},
    )
    st.pydeck_chart(deck, width="stretch")


def configured_gemini_api_key() -> str:
    """Return the optional Gemini API key without requiring secrets to exist."""

    try:
        return clean_text(st.secrets.get("GEM_KEY", ""))
    except Exception:
        return ""


def persist_hourly_ledger() -> None:
    """Best-effort same-day save. A write failure never blocks the operator;
    it only means the next rerun/restart won't resume from this point."""

    try:
        save_hourly_ledger(
            HourlyLedgerState(
                committed_jobs=st.session_state.committed_jobs,
                committed_riders=st.session_state.committed_riders,
                open_routes=st.session_state.hourly_open_routes,
                archived_routes=st.session_state.hourly_archived_routes,
                dispatch_at=st.session_state.hourly_dispatch_at,
            ),
            st.session_state.hourly_dispatch_at.date(),
        )
    except Exception as exc:
        st.session_state.hourly_ledger_error = f"Could not save the local dispatch ledger: {exc}"
    else:
        st.session_state.hourly_ledger_error = ""


now = pd.Timestamp.now(tz="Asia/Singapore").to_pydatetime()
default_dispatch = now.replace(minute=0, second=0, microsecond=0)
default_day = default_dispatch.strftime("%A")
loaded_roster = load_daily_v2_roster(default_day)
initialise_workflow_state(st.session_state, loaded_roster.dataframe)
st.session_state.setdefault("hourly_dispatch_at", default_dispatch)
st.session_state.setdefault("hourly_staged_jobs", pd.DataFrame())
st.session_state.setdefault("hourly_staged_validation", None)
st.session_state.setdefault("hourly_import_error", "")
st.session_state.setdefault("hourly_notice", "")
st.session_state.setdefault("hourly_open_routes", pd.DataFrame())
st.session_state.setdefault("hourly_archived_routes", pd.DataFrame())
st.session_state.setdefault("hourly_dispatch_result", None)
st.session_state.setdefault("hourly_standby_options", None)
st.session_state.setdefault("hourly_ledger_error", "")
st.session_state.setdefault("hourly_ledger_resumed", False)

if not st.session_state.hourly_ledger_resumed:
    st.session_state.hourly_ledger_resumed = True
    try:
        saved_ledger = load_hourly_ledger(now.date())
    except Exception:
        saved_ledger = None
    if saved_ledger is not None:
        if isinstance(saved_ledger.committed_jobs, pd.DataFrame) and not saved_ledger.committed_jobs.empty:
            st.session_state.committed_jobs = saved_ledger.committed_jobs
            st.session_state.job_draft = saved_ledger.committed_jobs.copy(deep=True)
        if isinstance(saved_ledger.committed_riders, pd.DataFrame) and not saved_ledger.committed_riders.empty:
            st.session_state.committed_riders = saved_ledger.committed_riders
            st.session_state.rider_draft = saved_ledger.committed_riders.copy(deep=True)
        st.session_state.hourly_open_routes = saved_ledger.open_routes
        st.session_state.hourly_archived_routes = saved_ledger.archived_routes
        if saved_ledger.dispatch_at is not None:
            st.session_state.hourly_dispatch_at = saved_ledger.dispatch_at
        st.session_state.hourly_notice = "Resumed today's saved dispatch state from the local ledger."

st.title("Hourly Route Optimiser")
st.caption(
    "Append each hourly release, activate the riders currently on shift, and rerun only unfinished work."
)

time_columns = st.columns(2)
dispatch_date = time_columns[0].date_input(
    "Dispatch date",
    value=st.session_state.hourly_dispatch_at.date(),
    key="hourly_dispatch_date",
)
dispatch_time = time_columns[1].time_input(
    "Run time",
    value=st.session_state.hourly_dispatch_at.timetz().replace(tzinfo=None),
    step=3600,
    key="hourly_dispatch_time",
)
dispatch_at = datetime.combine(dispatch_date, dispatch_time, tzinfo=now.tzinfo)
st.session_state.hourly_dispatch_at = dispatch_at

if st.session_state.hourly_notice:
    st.success(st.session_state.hourly_notice)
    st.session_state.hourly_notice = ""
if st.session_state.hourly_ledger_error:
    st.warning(st.session_state.hourly_ledger_error)

render_job_importer(dispatch_at)

st.subheader("Shift roster and live timeline")
with st.form("hourly_roster_form"):
    roster = normalise_riders(st.session_state.committed_riders)
    edited_roster = st.data_editor(
        roster,
        key="hourly_roster_editor",
        hide_index=True,
        num_rows="dynamic",
        height=320,
        column_config={
            "Rider Name": st.column_config.TextColumn(required=True),
            "Start Location": st.column_config.TextColumn(required=True),
            "Start Zone": st.column_config.SelectboxColumn(
                options=["", "North", "North-West", "North-East", "East", "Central", "West", "South/CBD"]
            ),
            "Preferred": st.column_config.NumberColumn(min_value=0, step=1, required=True),
            "Maximum": st.column_config.NumberColumn(min_value=1, step=1, required=True),
            "Work Style": st.column_config.SelectboxColumn(
                options=[style.value for style in WorkStyle], required=True
            ),
            "End Requirement": st.column_config.TextColumn(
                help="Optional final movement, for example Woodlands by 6:00 PM"
            ),
            "Active": st.column_config.CheckboxColumn(
                help="Activate this rider for rolling dispatch runs."
            ),
            "Shift Start": st.column_config.TextColumn(help="For example 1:00 PM or 13:00"),
            "Shift End": st.column_config.TextColumn(help="Hard stop, for example 4:00 PM or 16:00"),
            "Maximum Jobs": None,
            "Rider Load": None,
        },
    )
    save_roster = st.form_submit_button("Save shift roster", icon=":material/badge:")
if save_roster:
    validation = validate_rider_draft(edited_roster)
    if not validation.is_valid:
        for error in validation.errors:
            st.error(error)
    else:
        st.session_state.rider_draft = edited_roster
        save_rider_draft(st.session_state, edited_roster)
        persist_hourly_ledger()
        st.success("Shift roster saved for this session.")

timeline = live_shift_timeline(st.session_state.committed_riders, dispatch_at)
status_counts = timeline["Status"].value_counts().to_dict() if not timeline.empty else {}
metric_columns = st.columns(3)
metric_columns[0].metric("Active", status_counts.get("Active", 0))
metric_columns[1].metric("Pending shift start", status_counts.get("Pending shift start", 0))
metric_columns[2].metric(
    "Unavailable",
    status_counts.get("Inactive", 0)
    + status_counts.get("Shift ended", 0)
    + status_counts.get("Shift ending", 0),
)
st.dataframe(
    timeline,
    hide_index=True,
    column_config={
        "Shift start": st.column_config.DatetimeColumn(format="h:mm a"),
        "Shift end": st.column_config.DatetimeColumn(format="h:mm a"),
    },
)

open_routes = st.session_state.hourly_open_routes
if isinstance(open_routes, pd.DataFrame) and not open_routes.empty:
    st.subheader("Commit completed work")
    completion_table = open_routes.copy()
    completion_table["Stable Job ID"] = completion_table.apply(
        stable_job_id_from_route_row, axis=1
    )
    completion_table["Completed"] = False
    completion_table = completion_table[
        ["Completed", "Stable Job ID", "Rider", "Sequence", "Car Plate", "Pickup Address", "Drop-off Address"]
    ]
    with st.form("hourly_completion_form"):
        completed_edit = st.data_editor(
            completion_table,
            hide_index=True,
            disabled=[
                "Stable Job ID",
                "Rider",
                "Sequence",
                "Car Plate",
                "Pickup Address",
                "Drop-off Address",
            ],
            column_config={"Completed": st.column_config.CheckboxColumn()},
        )
        archive_clicked = st.form_submit_button(
            "Commit completed jobs",
            icon=":material/task_alt:",
        )
    if archive_clicked:
        selected_ids = set(
            completed_edit.loc[completed_edit["Completed"], "Stable Job ID"].astype(str)
        )
        try:
            archive, remaining = archive_completed_prefix(
                st.session_state.hourly_open_routes,
                st.session_state.hourly_archived_routes,
                selected_ids,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.hourly_archived_routes = archive
            st.session_state.hourly_open_routes = remaining
            st.session_state.hourly_standby_options = None
            persist_hourly_ledger()
            st.success(f"Committed {len(selected_ids)} completed job(s).")
            st.rerun()

st.subheader("Run rolling optimisation")
committed_count = len(st.session_state.committed_jobs)
archived_count = len(st.session_state.hourly_archived_routes)
run_metrics = st.columns(3)
run_metrics[0].metric("Committed jobs", committed_count)
run_metrics[1].metric("Completed and locked", archived_count)
run_metrics[2].metric("Waiting or in route", max(0, committed_count - archived_count))

with st.expander("Run settings", expanded=False):
    use_onemap = st.checkbox("Use OneMap routing", value=True, key="hourly_use_onemap")
    beam_width = st.number_input(
        "Beam width",
        min_value=10,
        max_value=200,
        value=80,
        step=10,
        key="hourly_beam_width",
    )
    time_limit = st.number_input(
        "Search time limit (seconds)",
        min_value=5,
        max_value=120,
        value=30,
        step=5,
        key="hourly_time_limit",
    )

if st.button(
    "Append state and solve this hour",
    type="primary",
    icon=":material/route:",
    disabled=committed_count == 0,
    key="hourly_run_dispatch",
):
    try:
        with st.status("Running rolling dispatch…", expanded=True) as status:
            st.write("Locking completed route prefixes and validating shift windows.")
            result = run_hourly_dispatch(
                committed_jobs=st.session_state.committed_jobs,
                roster_df=st.session_state.committed_riders,
                dispatch_at=dispatch_at,
                archived_routes=st.session_state.hourly_archived_routes,
                confirmed_open_routes=st.session_state.hourly_open_routes,
                use_onemap=use_onemap,
                beam_width=int(beam_width),
                time_limit_seconds=float(time_limit),
            )
            if result.solver_result.status == "INFEASIBLE":
                status.update(label="No hard-feasible rolling plan", state="error")
            else:
                st.write(
                    f"Incrementally recalculated {len(result.recalculation.affected_riders)} rider route(s)."
                )
                status.update(label="Rolling dispatch complete", state="complete")
    except Exception as exc:
        st.error(f"Hourly dispatch failed: {exc}")
    else:
        st.session_state.hourly_dispatch_result = result
        st.session_state.hourly_standby_options = None
        if result.solver_result.status != "INFEASIBLE":
            st.session_state.hourly_open_routes = result.open_route_df
        persist_hourly_ledger()
        st.rerun()

latest = st.session_state.hourly_dispatch_result
if latest is not None:
    st.subheader("Current dispatch plan")
    if latest.solver_result.status == "INFEASIBLE":
        st.error("No hard-feasible plan was found.")
        for reason in latest.solver_result.infeasible_reasons:
            st.warning(reason)

        st.subheader("Standby driver review")
        st.caption(
            "See how much of the shortfall the active roster can actually cover, and "
            "whether a Gemini-reviewed standby rider (Active unticked above, shift "
            "window set) is worth activating for the rest."
        )
        if st.button(
            "Check partial coverage + standby options",
            icon=":material/support_agent:",
            key="hourly_standby_check",
        ):
            try:
                standby_open_jobs = open_jobs_for_dispatch(
                    st.session_state.committed_jobs, st.session_state.hourly_archived_routes
                )
                active_for_standby = active_riders_for_dispatch(
                    st.session_state.committed_riders, dispatch_at
                )
                standby_pool = standby_riders_for_dispatch(
                    st.session_state.committed_riders, dispatch_at
                )
                standby_context = operation_context_for_riders(
                    active_for_standby + standby_pool, dispatch_at
                )
                with st.spinner("Checking partial coverage and standby options…"):
                    options = solve_with_standby_options(
                        open_jobs=standby_open_jobs,
                        active_riders=active_for_standby,
                        standby_riders=standby_pool,
                        dispatch_at=dispatch_at,
                        operation_context=standby_context,
                        use_onemap=use_onemap,
                        beam_width=int(beam_width),
                        time_limit_seconds=float(time_limit),
                        gemini_api_key=configured_gemini_api_key(),
                    )
            except Exception as exc:
                st.error(f"Standby review failed: {exc}")
            else:
                st.session_state.hourly_standby_options = options
                st.rerun()

        standby_options = st.session_state.hourly_standby_options
        if standby_options is not None:
            partial = standby_options.partial_result
            assigned_count = len(partial.route_df)
            unassigned_count = len(standby_options.unassigned_jobs)
            total = assigned_count + unassigned_count
            option_columns = st.columns(2)
            with option_columns[0]:
                st.markdown(f"**Option A · Dispatch now — {assigned_count} of {total} covered**")
                if unassigned_count:
                    st.warning(f"{unassigned_count} job(s) would stay unassigned this hour.")
                    for job in standby_options.unassigned_jobs:
                        st.caption(
                            f"• {clean_text(job.get('Car Plate'))}: "
                            f"{clean_text(job.get('Pickup Address'))} → "
                            f"{clean_text(job.get('Drop-off Address'))}"
                        )
                else:
                    st.success("Every open job can be covered by the active roster.")
                if not partial.route_df.empty:
                    st.dataframe(partial.route_df, hide_index=True, height=220)
            with option_columns[1]:
                st.markdown("**Option B · Activate a standby driver**")
                recommendation = standby_options.standby_recommendation
                if recommendation is None:
                    st.info(
                        "No standby riders are available to consider (need Active "
                        "unticked with a shift window set)."
                    )
                elif recommendation.activate_driver:
                    st.success(
                        f"Gemini recommends activating "
                        f"**{recommendation.recommended_driver_name or 'a standby rider'}** "
                        f"for job {recommendation.recommended_job_id or '-'}."
                    )
                    st.caption(recommendation.business_reasoning)
                else:
                    st.info("Gemini does not recommend activating a standby rider right now.")
                    st.caption(recommendation.business_reasoning)
            st.caption(
                "This review does not change the committed plan by itself. To act on "
                "Option A, rerun the solve after clearing the unassigned job(s); to act "
                "on Option B, tick Active for the recommended rider above and rerun."
            )
    else:
        st.success(
            f"{latest.solver_result.status.replace('_', ' ').title()} · "
            f"{len(latest.active_rider_names)} active rider(s)"
        )
        st.caption(
            "Objective: coverage → feasibility → severe travel → zone ownership → "
            "cluster continuity → idle waiting → rider burden → travel."
        )
        st.dataframe(latest.route_df, hide_index=True, height=420)
        show_route_map(latest.route_df)
