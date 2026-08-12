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
from Flexar.BlueSG.gemini_key_session import (
    configure_gemini_key_dialog,
    resolved_gemini_api_key,
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
    idle_minutes_for_rider,
    live_shift_timeline,
    open_jobs_for_dispatch,
    operation_context_for_riders,
    run_hourly_dispatch,
    solve_with_standby_options,
    standby_riders_for_dispatch,
)
from Flexar.BlueSG.job_import_staging import ImportResult, parse_job_source, validate_staged_jobs
from Flexar.BlueSG.onemap_token_session import configure_onemap_token_dialog
from Flexar.BlueSG.optimiser_workflow_state import (
    initialise_workflow_state,
    normalise_riders,
    save_rider_draft,
    validate_rider_draft,
)
from Flexar.BlueSG.v2_daily_roster_source import load_daily_v2_roster
from Flexar.BlueSG.vehicle_route_optimiser_v2 import WorkStyle


STATUS_EMOJI = {
    "Active": "\U0001F7E2",
    "Pending shift start": "\U0001F55B",
    "Shift ending": "\U0001F7E0",
    "Shift ended": "⚪",
    "Needs attention": "⚠️",
}


@st.cache_data(show_spinner=False)
def _parse_upload(payload: bytes, filename: str) -> ImportResult:
    class NamedBytesIO(BytesIO):
        pass

    source = NamedBytesIO(payload)
    source.name = filename
    return parse_job_source(uploaded_file=source)


@st.cache_data(show_spinner=False, ttl=3600, max_entries=1024)
def _map_geocode(address: str) -> dict[str, object]:
    result = get_cached_geocode(address, token=None, use_onemap=True)
    return {
        "lat": result.latitude,
        "lon": result.longitude,
        "source": result.source,
        "error": result.error,
    }


def log_line(message: str) -> None:
    """Append one line to the on-page run log ("terminal")."""

    stamp = pd.Timestamp.now(tz="Asia/Singapore").strftime("%H:%M:%S")
    log = list(st.session_state.get("hourly_run_log", []))
    log.append(f"[{stamp}] {message}")
    st.session_state.hourly_run_log = log[-16:]


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


@st.dialog("Upload jobs", width="large")
def upload_jobs_dialog() -> None:
    st.caption("Upload this hour's Flexar export (Excel or CSV). Already-committed jobs are ignored automatically.")
    uploaded = st.file_uploader(
        "Job file",
        type=["xlsx", "xls", "xlsm", "csv"],
        key="hourly_jobs_upload",
    )

    if uploaded is not None:
        try:
            parsed = _parse_upload(uploaded.getvalue(), uploaded.name)
            validation = validate_staged_jobs(parsed.dataframe)
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")
            return

        if not validation.is_valid:
            for issue in validation.issues:
                (st.error if issue.severity == "error" else st.warning)(issue.message)
            return

        st.success(f"{len(validation.dataframe)} valid job(s) ready to add")
        st.dataframe(validation.dataframe, hide_index=True, height=240)
        if st.button("Add to today's jobs", type="primary", icon=":material/add_task:"):
            try:
                result = append_hourly_jobs(
                    st.session_state.committed_jobs,
                    validation.dataframe,
                    released_at=st.session_state.hourly_dispatch_at,
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state.committed_jobs = result.dataframe
            st.session_state.job_draft = result.dataframe.copy(deep=True)
            message = f"Appended {len(result.appended_job_ids)} job(s)."
            if result.ignored_job_ids:
                message += f" Ignored {len(result.ignored_job_ids)} already-committed job(s)."
            log_line(message)
            st.session_state.hourly_notice = message
            persist_hourly_ledger()
            st.rerun()
    else:
        st.caption("Waiting for a file.")


@st.dialog("Today's riders", width="large")
def configure_hourly_riders_dialog() -> None:
    st.caption(
        "Full day drivers get considered for every hourly solve. Ad hoc / half day "
        "riders stay out of the solve until you check standby options for them - "
        "put them here with a shift window so the advisor can see them."
    )
    if st.session_state.get("rider_draft") is None:
        st.session_state.rider_draft = normalise_riders(st.session_state.committed_riders)
    draft = normalise_riders(st.session_state.rider_draft)
    active_mask = draft["Active"].fillna(True).astype(bool)
    full_day_source = draft[active_mask].drop(columns=["Active"]).reset_index(drop=True)
    pool_source = draft[~active_mask].drop(columns=["Active"]).reset_index(drop=True)

    column_config = {
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
        "Shift Start": st.column_config.TextColumn(help="For example 1:00 PM or 13:00"),
        "Shift End": st.column_config.TextColumn(help="Hard stop, for example 4:00 PM or 16:00"),
        "Maximum Jobs": None,
        "Rider Load": None,
    }

    full_day_tab, pool_tab = st.tabs(["Full day drivers", "Half day / Ad hoc pool"])
    with full_day_tab:
        full_day_edit = st.data_editor(
            full_day_source,
            key="hourly_full_day_editor",
            hide_index=True,
            num_rows="dynamic",
            height=320,
            column_config=column_config,
        )
    with pool_tab:
        st.caption("Set a Shift Start/End so idle time and the shift-end buffer can be checked for these riders.")
        pool_edit = st.data_editor(
            pool_source,
            key="hourly_pool_editor",
            hide_index=True,
            num_rows="dynamic",
            height=320,
            column_config=column_config,
        )

    action_columns = st.columns(2)
    save_clicked = action_columns[0].button("Save riders", type="primary", icon=":material/badge:")
    cancel_clicked = action_columns[1].button("Cancel")

    if cancel_clicked:
        st.session_state.rider_draft = None
        st.rerun()
    if save_clicked:
        combined = pd.concat(
            [full_day_edit.assign(Active=True), pool_edit.assign(Active=False)],
            ignore_index=True,
        )
        validation = validate_rider_draft(combined)
        if not validation.is_valid:
            for error in validation.errors:
                st.error(error)
        else:
            st.session_state.rider_draft = combined
            save_rider_draft(st.session_state, combined)
            persist_hourly_ledger()
            log_line(
                f"Saved riders: {len(full_day_edit)} full day, {len(pool_edit)} ad hoc pool."
            )
            st.success("Riders saved for this session.")
            st.rerun()


def driver_route_snapshot(rider_name: str, open_routes: pd.DataFrame) -> dict[str, object]:
    """Where a rider currently stands and what's left on their solved route."""

    if not isinstance(open_routes, pd.DataFrame) or open_routes.empty or "Rider" not in open_routes.columns:
        return {"location": None, "stops": []}
    rows = open_routes[open_routes["Rider"].astype(str) == rider_name]
    if rows.empty:
        return {"location": None, "stops": []}
    ordered = rows.assign(
        _seq=pd.to_numeric(rows["Sequence"], errors="coerce")
    ).sort_values("_seq", kind="stable")
    location = clean_text(ordered.iloc[0].get("Start From"))
    stops = [
        {
            "pickup": clean_text(row.get("Pickup Address")),
            "dropoff": clean_text(row.get("Drop-off Address")),
        }
        for _, row in ordered.iterrows()
    ]
    return {"location": location, "stops": stops}


@st.dialog("Standby coverage options", width="large")
def standby_options_dialog(dispatch_at: datetime, use_onemap: bool, beam_width: int, time_limit: float) -> None:
    try:
        standby_open_jobs = open_jobs_for_dispatch(
            st.session_state.committed_jobs, st.session_state.hourly_archived_routes
        )
        active_for_standby = active_riders_for_dispatch(st.session_state.committed_riders, dispatch_at)
        standby_pool = standby_riders_for_dispatch(st.session_state.committed_riders, dispatch_at)
        standby_context = operation_context_for_riders(active_for_standby + standby_pool, dispatch_at)
        with st.spinner("Checking partial coverage and standby options..."):
            options = solve_with_standby_options(
                open_jobs=standby_open_jobs,
                active_riders=active_for_standby,
                standby_riders=standby_pool,
                dispatch_at=dispatch_at,
                operation_context=standby_context,
                use_onemap=use_onemap,
                beam_width=int(beam_width),
                time_limit_seconds=float(time_limit),
                gemini_api_key=resolved_gemini_api_key(),
            )
    except Exception as exc:
        st.error(f"Standby review failed: {exc}")
        return

    partial = options.partial_result
    assigned_count = len(partial.route_df)
    unassigned_count = len(options.unassigned_jobs)
    total = assigned_count + unassigned_count

    option_columns = st.columns(2)
    with option_columns[0]:
        st.markdown(f"**Option A - Dispatch now: {assigned_count} of {total} covered**")
        if unassigned_count:
            st.warning(f"{unassigned_count} job(s) would stay unassigned this hour.")
            for job in options.unassigned_jobs:
                st.caption(
                    f"- {clean_text(job.get('Car Plate'))}: "
                    f"{clean_text(job.get('Pickup Address'))} -> "
                    f"{clean_text(job.get('Drop-off Address'))}"
                )
        else:
            st.success("Every open job can be covered by the active roster.")
        if not partial.route_df.empty:
            st.dataframe(partial.route_df, hide_index=True, height=220)
    with option_columns[1]:
        st.markdown("**Option B - Activate a standby driver**")
        recommendation = options.standby_recommendation
        if recommendation is None:
            st.info(
                "No standby riders are available to consider - add someone to the "
                "Half day / Ad hoc pool tab with a shift window set."
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
        "Option A, resolve the shortfall and rerun Optimise; to act on Option B, "
        "move the recommended rider to the Full day tab and rerun."
    )


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
                    "tooltip": f"{rider} - job {route.get('Sequence')}",
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


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------

now = pd.Timestamp.now(tz="Asia/Singapore").to_pydatetime()
default_dispatch = now.replace(minute=0, second=0, microsecond=0)
default_day = default_dispatch.strftime("%A")
loaded_roster = load_daily_v2_roster(default_day)
initialise_workflow_state(st.session_state, loaded_roster.dataframe)
st.session_state.setdefault("hourly_dispatch_at", default_dispatch)
st.session_state.setdefault("hourly_notice", "")
st.session_state.setdefault("hourly_open_routes", pd.DataFrame())
st.session_state.setdefault("hourly_archived_routes", pd.DataFrame())
st.session_state.setdefault("hourly_dispatch_result", None)
st.session_state.setdefault("hourly_ledger_error", "")
st.session_state.setdefault("hourly_ledger_resumed", False)
st.session_state.setdefault("hourly_run_log", [])

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

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

header_columns = st.columns([4.4, 1, 1, 1.2], vertical_alignment="center")
header_columns[0].title("Hourly Route Optimiser")
if header_columns[1].button("Today's riders", icon=":material/menu:", width="stretch"):
    configure_hourly_riders_dialog()
if header_columns[2].button("OneMap key", icon=":material/key:", width="stretch"):
    configure_onemap_token_dialog()
if header_columns[3].button("Gemini key", icon=":material/smart_toy:", width="stretch"):
    configure_gemini_key_dialog()

roster = normalise_riders(st.session_state.committed_riders)
full_day_count = int(roster["Active"].fillna(True).astype(bool).sum())
pool_count = len(roster) - full_day_count
st.caption(f"{full_day_count} full day driver(s) · {pool_count} ad hoc pool driver(s)")

for message_key in ("hourly_notice", "hourly_gemini_key_message", "bluesg_onemap_token_message"):
    if st.session_state.get(message_key):
        st.success(st.session_state.pop(message_key))
if st.session_state.hourly_ledger_error:
    st.warning(st.session_state.hourly_ledger_error)

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

# ---------------------------------------------------------------------------
# Primary actions
# ---------------------------------------------------------------------------

open_jobs_now = open_jobs_for_dispatch(st.session_state.committed_jobs, st.session_state.hourly_archived_routes)
action_columns = st.columns([1, 1, 1.4])
if action_columns[0].button("Upload", icon=":material/upload_file:", width="stretch"):
    upload_jobs_dialog()

with action_columns[2]:
    with st.popover("Settings", icon=":material/tune:", width="stretch"):
        use_onemap = st.checkbox("Use OneMap routing", value=True, key="hourly_use_onemap")
        beam_width = st.number_input(
            "Beam width", min_value=10, max_value=200, value=80, step=10, key="hourly_beam_width"
        )
        time_limit = st.number_input(
            "Search time limit (seconds)", min_value=5, max_value=120, value=30, step=5, key="hourly_time_limit"
        )

optimise_clicked = action_columns[1].button(
    "Optimise",
    type="primary",
    icon=":material/route:",
    width="stretch",
    disabled=len(st.session_state.committed_jobs) == 0,
)
st.caption(f"{len(open_jobs_now)} job(s) waiting to be planned this hour.")

if optimise_clicked:
    try:
        log_line(f"Solving {len(open_jobs_now)} open job(s)...")
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
    except Exception as exc:
        st.error(f"Hourly dispatch failed: {exc}")
        log_line(f"Dispatch failed: {exc}")
    else:
        st.session_state.hourly_dispatch_result = result
        if result.solver_result.status == "INFEASIBLE":
            log_line("Result: INFEASIBLE - no hard-feasible plan found.")
        else:
            st.session_state.hourly_open_routes = result.open_route_df
            log_line(
                f"Result: {result.solver_result.status} - "
                f"{len(result.active_rider_names)} active rider(s), "
                f"{len(result.recalculation.affected_riders)} route(s) recalculated."
            )
        persist_hourly_ledger()
        st.rerun()

# ---------------------------------------------------------------------------
# Two-column body: terminal/output on the left, driver overview on the right
# ---------------------------------------------------------------------------

left_col, right_col = st.columns([2.1, 1], gap="large")

with left_col:
    st.subheader("Run log")
    log_text = "\n".join(st.session_state.hourly_run_log) or "No activity yet this session."
    st.code(log_text, language="text")

    latest = st.session_state.hourly_dispatch_result
    if latest is not None:
        st.subheader("Dispatch output")
        if latest.solver_result.status == "INFEASIBLE":
            st.error("No hard-feasible plan was found.")
            for reason in latest.solver_result.infeasible_reasons:
                st.warning(reason)
            st.caption("Check standby options in the Backup pool panel on the right to see what's coverable now.")
        else:
            st.success(
                f"{latest.solver_result.status.replace('_', ' ').title()} · "
                f"{len(latest.active_rider_names)} active rider(s)"
            )
            st.dataframe(latest.route_df, hide_index=True, height=360)
            show_route_map(latest.route_df)

    open_routes = st.session_state.hourly_open_routes
    if isinstance(open_routes, pd.DataFrame) and not open_routes.empty:
        with st.expander("Mark jobs complete", expanded=False):
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
                        "Stable Job ID", "Rider", "Sequence", "Car Plate", "Pickup Address", "Drop-off Address",
                    ],
                    column_config={"Completed": st.column_config.CheckboxColumn()},
                )
                archive_clicked = st.form_submit_button("Commit completed jobs", icon=":material/task_alt:")
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
                    log_line(f"Archived {len(selected_ids)} completed job(s).")
                    persist_hourly_ledger()
                    st.success(f"Committed {len(selected_ids)} completed job(s).")
                    st.rerun()

with right_col:
    st.subheader("Current drivers")
    timeline = live_shift_timeline(st.session_state.committed_riders, dispatch_at)
    full_day_timeline = timeline[timeline["Status"] != "Inactive"].reset_index(drop=True)
    if full_day_timeline.empty:
        st.caption("No full day drivers on today's roster yet.")
    else:
        for _, row in full_day_timeline.iterrows():
            rider_name = clean_text(row["Rider"])
            status = clean_text(row["Status"])
            snapshot = driver_route_snapshot(rider_name, st.session_state.hourly_open_routes)
            with st.container(border=True):
                st.markdown(f"**{rider_name}** {STATUS_EMOJI.get(status, '')} {status}")
                location = snapshot["location"] or clean_text(row.get("Start zone")) or "Roster start"
                st.caption(f"\U0001F4CD {location}")
                stops = snapshot["stops"]
                if stops:
                    chain = " -> ".join(
                        clean_text(stop["dropoff"]) or clean_text(stop["pickup"]) for stop in stops
                    )
                    st.caption(f"{len(stops)} stop(s): {chain}")
                else:
                    st.caption("No jobs assigned yet this hour.")

    st.subheader("Backup pool")
    standby = standby_riders_for_dispatch(st.session_state.committed_riders, dispatch_at)
    if not standby:
        st.caption("No ad hoc riders with a shift window set. Add them in Today's riders.")
    else:
        for rider in standby:
            with st.container(border=True):
                st.markdown(f"**{rider.name}**")
                window = (
                    f"{rider.available_from:%H:%M}-{rider.available_until:%H:%M}"
                    if rider.available_from and rider.available_until
                    else "No window set"
                )
                idle = idle_minutes_for_rider(rider, dispatch_at)
                st.caption(f"\U0001F55B {window} · idle {idle:.0f} min · {rider.start_zone}")
    if st.button(
        "Check standby options",
        icon=":material/support_agent:",
        width="stretch",
        disabled=len(st.session_state.committed_jobs) == 0,
    ):
        standby_options_dialog(dispatch_at, use_onemap, int(beam_width), float(time_limit))
