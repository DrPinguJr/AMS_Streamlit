import os
import time

import pandas as pd
import pydeck as pdk
import streamlit as st

from BlueSG.vehicle_route_optimizer import (
    DEFAULT_DURATION_BUFFER_MULTIPLIER,
    DEFAULT_DURATION_PENALTY_PER_MIN,
    DEFAULT_EMPTY_WEIGHT,
    DEFAULT_LOADED_WEIGHT,
    DEFAULT_MAX_ADJUSTED_DURATION_MIN,
    DEFAULT_MAX_JOB_OVERAGE_PENALTY,
    DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
    DEFAULT_SOFT_WORKLOAD_MIN,
    DEFAULT_WORKLOAD_PENALTY_PER_MIN,
    REQUIRED_JOB_HEADERS,
    ROSTER_FILE,
    clean_text,
    WEEKDAY_SHEETS,
    ensure_rider_roster_workbook,
    export_routes_to_excel,
    get_cost_explanation,
    get_cached_geocode,
    load_and_validate_jobs,
    load_rider_roster,
    optimise_vehicle_routes,
    read_rider_roster_file,
    save_rider_roster,
    validate_riders,
)


@st.cache_data(show_spinner=False)
def cached_cost_explanation() -> pd.DataFrame:
    return get_cost_explanation()


@st.cache_data(show_spinner=False)
def cached_route_map_geocodes(addresses: tuple[str, ...], token: str | None) -> dict[str, dict[str, object]]:
    geocodes: dict[str, dict[str, object]] = {}
    for address in addresses:
        result = get_cached_geocode(address, token=token, use_onemap=True)
        geocodes[address] = {
            "lat": result.latitude,
            "lon": result.longitude,
            "source": result.source,
            "error": result.error,
        }
    return geocodes


def rider_colour(index: int) -> list[int]:
    colours = [
        [37, 99, 235],
        [220, 38, 38],
        [5, 150, 105],
        [147, 51, 234],
        [217, 119, 6],
        [8, 145, 178],
        [190, 24, 93],
        [77, 124, 15],
    ]
    return colours[index % len(colours)]


def build_route_map_data(
    route_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    token: str | None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    addresses = []
    for column in ["Start Location"]:
        if column in rider_df.columns:
            addresses.extend(rider_df[column].apply(clean_text).tolist())
    for column in ["Start From", "Pickup Address", "Drop-off Address"]:
        if column in route_df.columns:
            addresses.extend(route_df[column].apply(clean_text).tolist())
    for column in ["Pickup Address", "Drop-off Address"]:
        if column in jobs_df.columns:
            addresses.extend(jobs_df[column].apply(clean_text).tolist())

    unique_addresses = tuple(sorted({address for address in addresses if address}))
    geocodes = cached_route_map_geocodes(unique_addresses, token)

    point_rows = []
    for _, rider in rider_df.iterrows():
        address = clean_text(rider.get("Start Location"))
        result = geocodes.get(address, {})
        if result.get("lat") is not None and result.get("lon") is not None:
            point_rows.append(
                    {
                        "Address": address,
                        "Location Type": "Rider start",
                        "Rider": clean_text(rider.get("Rider Name")) or "Rider",
                        "tooltip": f"{clean_text(rider.get('Rider Name')) or 'Rider'}<br/>Rider start<br/>{address}",
                        "lat": result["lat"],
                        "lon": result["lon"],
                        "radius": 90,
                        "fill_color": [17, 24, 39],
                }
            )

    for _, job in jobs_df.iterrows():
        for location_type, column, colour in [
            ("Given pickup", "Pickup Address", [14, 165, 233]),
            ("Given drop-off", "Drop-off Address", [249, 115, 22]),
        ]:
            address = clean_text(job.get(column))
            result = geocodes.get(address, {})
            if result.get("lat") is not None and result.get("lon") is not None:
                point_rows.append(
                    {
                        "Address": address,
                        "Location Type": location_type,
                        "Rider": "",
                        "tooltip": f"{location_type}<br/>{address}",
                        "lat": result["lat"],
                        "lon": result["lon"],
                        "radius": 70,
                        "fill_color": colour,
                    }
                )

    leg_rows = []
    for _, row in route_df.sort_values(["Rider", "Sequence"]).iterrows():
        rider = str(row["Rider"])
        public_colour = [220, 38, 38, 210]
        car_colour = [22, 163, 74, 230]
        legs = [
            {
                "Mode": "Public transport / empty travel",
                "From": clean_text(row["Start From"]),
                "To": clean_text(row["Pickup Address"]),
                "Distance KM": row["Empty Distance KM"],
                "Duration Min": row["Empty Duration Min"],
                "color": public_colour,
            },
            {
                "Mode": "Car movement",
                "From": clean_text(row["Pickup Address"]),
                "To": clean_text(row["Drop-off Address"]),
                "Distance KM": row["Loaded Distance KM"],
                "Duration Min": row["Loaded Duration Min"],
                "color": car_colour,
            },
        ]
        for leg in legs:
            start = geocodes.get(leg["From"], {})
            end = geocodes.get(leg["To"], {})
            if (
                start.get("lat") is None
                or start.get("lon") is None
                or end.get("lat") is None
                or end.get("lon") is None
            ):
                continue
            leg_rows.append(
                {
                    "Rider": rider,
                    "Sequence": int(row["Sequence"]),
                    "Car Plate": clean_text(row["Car Plate"]),
                    "Mode": leg["Mode"],
                    "From": leg["From"],
                    "To": leg["To"],
                    "Distance KM": leg["Distance KM"],
                    "Duration Min": leg["Duration Min"],
                    "Cost Source": clean_text(row["Cost Source"]),
                    "path": [[start["lon"], start["lat"]], [end["lon"], end["lat"]]],
                    "color": leg["color"],
                    "label_position": [
                        (float(start["lon"]) + float(end["lon"])) / 2,
                        (float(start["lat"]) + float(end["lat"])) / 2,
                    ],
                    "label": f"{rider} S{int(row['Sequence'])} - {'PT' if leg['Mode'].startswith('Public') else 'Drive'}",
                    "tooltip": (
                        f"{rider}<br/>Step {int(row['Sequence'])}: {leg['Mode']}<br/>"
                        f"{leg['From']} -> {leg['To']}<br/>"
                        f"{leg['Distance KM']} km, {leg['Duration Min']} min<br/>"
                        f"{clean_text(row['Car Plate'])}"
                    ),
                }
            )

    missing = [
        f"{address}: {result.get('error') or 'No coordinates returned'}"
        for address, result in geocodes.items()
        if result.get("lat") is None or result.get("lon") is None
    ]
    return pd.DataFrame(point_rows), pd.DataFrame(leg_rows), missing


def show_route_map(route_df: pd.DataFrame, jobs_df: pd.DataFrame, rider_df: pd.DataFrame, token: str | None) -> None:
    point_df, leg_df, missing_locations = build_route_map_data(route_df, jobs_df, rider_df, token)

    st.subheader("Singapore Route Map")
    if leg_df.empty and point_df.empty:
        st.warning("No map locations could be geocoded. Check the addresses or OneMap token.")
        return

    if missing_locations:
        with st.expander("Map locations not found", expanded=False):
            for warning in missing_locations[:80]:
                st.warning(warning)
            if len(missing_locations) > 80:
                st.info(f"Showing first 80 of {len(missing_locations)} missing location(s).")

    rider_names = list(route_df["Rider"].dropna().astype(str).drop_duplicates())
    selected_key = "bluesg_selected_map_rider"
    selected_rider = st.session_state.get(selected_key, "")
    if selected_rider not in rider_names:
        selected_rider = ""
        st.session_state[selected_key] = ""

    map_col, rider_col = st.columns([4, 1])
    with rider_col:
        st.caption("Riders")
        for rider_name in rider_names:
            rider_routes = route_df[route_df["Rider"].astype(str) == rider_name]
            total_distance = float(rider_routes["Total Distance KM"].fillna(0).sum())
            total_duration = float(rider_routes["Total Duration Min"].fillna(0).sum())
            button_type = "primary" if selected_rider == rider_name else "secondary"
            if st.button(
                f"{rider_name}",
                key=f"map_rider_{rider_name}",
                type=button_type,
                use_container_width=True,
            ):
                selected_rider = rider_name
                st.session_state[selected_key] = rider_name
            if selected_rider == rider_name:
                st.caption(f"{len(rider_routes)} job(s)")
                st.caption(f"{round(total_distance, 2)} km")
                st.caption(f"{round(total_duration, 1)} min")

        if selected_rider and st.button("Clear route", key="map_clear_rider", use_container_width=True):
            selected_rider = ""
            st.session_state[selected_key] = ""

    if selected_rider and "Rider" in leg_df.columns:
        visible_leg_df = leg_df[leg_df["Rider"] == selected_rider].copy()
    else:
        visible_leg_df = pd.DataFrame()

    layers = []
    if not visible_leg_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                visible_leg_df,
                get_path="path",
                get_color="color",
                width_min_pixels=4,
                pickable=True,
            )
        )
        layers.append(
            pdk.Layer(
                "TextLayer",
                visible_leg_df,
                get_position="label_position",
                get_text="label",
                get_color=[17, 24, 39],
                get_size=13,
                get_angle=0,
                get_text_anchor="'middle'",
                get_alignment_baseline="'center'",
                background=True,
                get_background_color=[255, 255, 255, 215],
                background_padding=[4, 3],
                pickable=True,
            )
        )
    if not point_df.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                point_df,
                get_position="[lon, lat]",
                get_fill_color="fill_color",
                get_radius="radius",
                radius_min_pixels=6,
                radius_max_pixels=16,
                stroked=True,
                get_line_color=[255, 255, 255],
                line_width_min_pixels=1,
                pickable=True,
            )
        )

    view_lat = float(point_df["lat"].mean()) if not point_df.empty else 1.3521
    view_lon = float(point_df["lon"].mean()) if not point_df.empty else 103.8198
    deck = pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        initial_view_state=pdk.ViewState(latitude=view_lat, longitude=view_lon, zoom=11, pitch=0),
        layers=layers,
        tooltip={
            "html": "{tooltip}",
            "style": {"backgroundColor": "#111827", "color": "white"},
        },
    )
    with map_col:
        if selected_rider:
            st.caption(f"Showing route for {selected_rider}")
            if visible_leg_df.empty:
                st.warning("This rider has no drawable route legs. Check whether the route addresses were geocoded.")
        else:
            st.caption("Select a rider on the right to show their route.")
        st.pydeck_chart(deck, use_container_width=True)

        legend_cols = st.columns(4)
        legend_cols[0].caption("Red: public transport to pickup")
        legend_cols[1].caption("Green: driving/car movement")
        legend_cols[2].caption("Blue/orange dots: pickups/drop-offs")
        legend_cols[3].caption("Labels: rider and step")


def get_onemap_token_from_env() -> str:
    value = os.getenv("ONEMAP_TOKEN", "")
    if value:
        return value

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        return ""

    try:
        with open(env_path, "r", encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, raw_value = stripped.split("=", 1)
                if key.strip() == "ONEMAP_TOKEN":
                    return raw_value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


st.title("Vehicle Route Optimiser")
st.caption("Assign fixed pickup-to-drop-off vehicle relocation jobs across multiple riders.")

st.info(
    "This optimiser treats each vehicle as a fixed pickup-to-drop-off job. Before every pickup, "
    "the rider's empty travel from their current location is counted. After each drop-off, that "
    "drop-off becomes the rider's new current location for the next assignment. OneMap is used "
    "for Singapore distance/time estimates where available; fallback estimates are used only when "
    "OneMap lookup fails."
)

with st.expander("Required Excel format", expanded=False):
    st.write("Required headers:")
    st.write(", ".join(REQUIRED_JOB_HEADERS))
    st.write("Optional headers: Date, Fuel %, Pickup Time, Notes")

uploaded_file = st.file_uploader("Upload vehicle jobs Excel file", type=["xlsx", "xls"])

jobs_df = pd.DataFrame()
file_is_valid = False

if uploaded_file is not None:
    try:
        jobs_df, missing_headers, validation_warnings = load_and_validate_jobs(uploaded_file)
    except ValueError as exc:
        st.error(str(exc))
    else:
        if missing_headers:
            st.error("Missing required header(s): " + ", ".join(missing_headers))
        else:
            file_is_valid = True
            for warning in validation_warnings:
                st.warning(warning)
            st.success(f"Loaded {len(jobs_df)} valid job(s).")
            preview_columns = [
                "Car Plate",
                "Pickup Address",
                "Pickup Lot",
                "Drop-off Address",
                "Pickup Zone",
                "Drop-off Zone",
            ]
            st.dataframe(jobs_df[preview_columns], use_container_width=True, hide_index=True)

st.subheader("Riders")
roster_path = ensure_rider_roster_workbook()
st.caption(f"Persistent roster workbook: {roster_path}")

roster_left, roster_right = st.columns([1, 2])
with roster_left:
    selected_roster_day = st.selectbox("Roster day", WEEKDAY_SHEETS)
with roster_right:
    st.write("Edit the roster below, then save it back to the Excel workbook.")

if st.session_state.get("bluesg_roster_day") != selected_roster_day:
    st.session_state.bluesg_roster_day = selected_roster_day
    st.session_state.bluesg_riders = load_rider_roster(selected_roster_day)

if "bluesg_riders" not in st.session_state:
    st.session_state.bluesg_riders = load_rider_roster(selected_roster_day)

rider_df = st.data_editor(
    st.session_state.bluesg_riders,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "Rider Name": st.column_config.TextColumn(required=True),
        "Start Location": st.column_config.TextColumn(required=True),
        "Start Zone": st.column_config.SelectboxColumn(
            options=["", "North", "North-East", "East", "Central", "West", "South/CBD"],
            help="Used as an initial fallback estimate and tie-breaker.",
        ),
        "Max Jobs": st.column_config.NumberColumn(
            min_value=1,
            step=1,
            help="Soft preference only. A rider can exceed it if they are still the best nearby match.",
        ),
    },
)
st.session_state.bluesg_riders = rider_df

roster_actions = st.columns([1, 1, 1, 2])
with roster_actions[0]:
    if st.button("Save Roster", type="secondary"):
        try:
            saved_path = save_rider_roster(selected_roster_day, rider_df)
        except PermissionError:
            st.error("Could not save roster. Close the Excel workbook if it is open, then try again.")
        except Exception as exc:
            st.error(f"Could not save roster: {exc}")
        else:
            st.success(f"Saved {selected_roster_day} roster to {saved_path}")
with roster_actions[1]:
    if st.button("Reload From Excel"):
        try:
            st.session_state.bluesg_riders = load_rider_roster(selected_roster_day)
        except Exception as exc:
            st.error(f"Could not reload roster: {exc}")
        else:
            st.rerun()
with roster_actions[2]:
    if st.button("Open Excel File"):
        try:
            os.startfile(ROSTER_FILE)
        except Exception as exc:
            st.error(f"Could not open roster workbook: {exc}")
with roster_actions[3]:
    st.download_button(
        "Download Roster Workbook",
        data=read_rider_roster_file(),
        file_name="rider_roster.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.subheader("Optimisation Settings")
settings_left, settings_right = st.columns(2)
with settings_left:
    use_onemap = st.toggle("Use OneMap distance/time if available", value=True)
    onemap_token = st.text_input(
        "OneMap access token",
        value=get_onemap_token_from_env(),
        type="password",
        help="Required for OneMap routing distance/time. If blank or invalid, the app will use fallback estimates.",
        disabled=not use_onemap,
    )
with settings_right:
    optimise_by_label = st.radio(
        "Optimise by",
        ["Duration", "Distance"],
        horizontal=True,
        captions=["Lowest total minutes", "Lowest total kilometres"],
    )
optimise_by = optimise_by_label.lower()

if use_onemap and not onemap_token:
    st.warning(
        "OneMap is enabled, but no OneMap access token is set. Address lookup may work, "
        "but route distance/time calls will return 401 Unauthorized and use fallback estimates."
    )

with st.expander("Fallback travel cost table", expanded=False):
    st.write(
        "Exact address matches cost 0. Known zone-to-zone pairs use this table for distance and duration. "
        "Unknown zones use a higher default fallback cost."
    )
    st.dataframe(cached_cost_explanation(), use_container_width=True, hide_index=True)

with st.expander("Advanced assignment scoring", expanded=False):
    st.caption(
        "Zone is a strong score adjustment, not an absolute first sort. "
        "Workload is based on projected route time, and Max Jobs is a progressive soft cap."
    )
    score_col_a, score_col_b = st.columns(2)
    with score_col_a:
        empty_weight = st.number_input(
            "Empty leg weight",
            value=DEFAULT_EMPTY_WEIGHT,
            min_value=1.0,
            max_value=10.0,
            step=0.5,
        )
    with score_col_b:
        loaded_weight = st.number_input(
            "Loaded leg weight",
            value=DEFAULT_LOADED_WEIGHT,
            min_value=0.5,
            max_value=5.0,
            step=0.5,
        )
    workload_col_a, workload_col_b, workload_col_c, workload_col_d = st.columns(4)
    with workload_col_a:
        soft_workload_min = st.number_input(
            "Soft workload minutes",
            value=DEFAULT_SOFT_WORKLOAD_MIN,
            min_value=30.0,
            max_value=180.0,
            step=5.0,
        )
    with workload_col_b:
        workload_penalty_per_min = st.number_input(
            "Workload penalty/min",
            value=DEFAULT_WORKLOAD_PENALTY_PER_MIN,
            min_value=0.0,
            max_value=10.0,
            step=0.5,
        )
    with workload_col_c:
        soft_adjusted_duration_min = st.number_input(
            "Soft adjusted minutes",
            value=DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
            min_value=60.0,
            max_value=240.0,
            step=5.0,
        )
    with workload_col_d:
        duration_penalty_per_min = st.number_input(
            "Duration penalty/min",
            value=DEFAULT_DURATION_PENALTY_PER_MIN,
            min_value=0.0,
            max_value=15.0,
            step=0.5,
        )
    cap_col_a, cap_col_b, cap_col_c = st.columns(3)
    with cap_col_a:
        max_job_overage_penalty = st.number_input(
            "Max jobs overage penalty",
            value=DEFAULT_MAX_JOB_OVERAGE_PENALTY,
            min_value=0.0,
            max_value=300.0,
            step=10.0,
        )
    with cap_col_b:
        duration_buffer_multiplier = st.number_input(
            "Duration buffer multiplier",
            value=DEFAULT_DURATION_BUFFER_MULTIPLIER,
            min_value=1.0,
            max_value=2.0,
            step=0.1,
        )
    with cap_col_c:
        max_adjusted_duration_min = st.number_input(
            "Max adjusted minutes",
            value=DEFAULT_MAX_ADJUSTED_DURATION_MIN,
            min_value=60.0,
            max_value=360.0,
            step=15.0,
        )

if st.button("Optimise Routes", type="primary", disabled=not file_is_valid):
    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        for error in rider_errors:
            st.error(error)
    elif jobs_df.empty:
        st.error("Upload at least one valid job before optimising.")
    else:
        estimated_checks = max(1, len(riders) * len(jobs_df) * (len(jobs_df) + 1) // 2)
        if use_onemap:
            st.info(
                f"OneMap mode may take a while: this run can compare up to about "
                f"{estimated_checks:,} rider-job combinations, and each comparison has an empty leg "
                "plus a loaded leg. Cached addresses and routes are reused."
            )

        progress_bar = st.progress(0, text="Preparing optimisation...")
        status_text = st.empty()
        detail_text = st.empty()
        metrics_slot = st.empty()
        started_at = time.monotonic()

        def show_progress(event: dict) -> None:
            elapsed = time.monotonic() - started_at
            progress_bar.progress(float(event.get("progress", 0)), text=str(event.get("status", "")))
            status_text.write(
                f"Phase: {event.get('phase', 'Working')} | "
                f"Assigned {event.get('assigned_jobs', 0)} of {event.get('total_jobs', 0)} jobs | "
                f"Remaining {event.get('remaining_jobs', 0)} | "
                f"Elapsed {elapsed:,.1f}s"
            )
            detail_parts = []
            if event.get("current_address"):
                detail_parts.append(f"Address: {event['current_address']}")
            if event.get("current_rider"):
                detail_parts.append(f"Rider: {event['current_rider']}")
            if event.get("current_pickup"):
                detail_parts.append(f"Pickup: {event['current_pickup']}")
            if event.get("current_dropoff"):
                detail_parts.append(f"Drop-off: {event['current_dropoff']}")
            detail_text.caption(" | ".join(detail_parts) if detail_parts else "Waiting for first lookup...")
            with metrics_slot.container():
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Rider-job checks", f"{event.get('comparison_count', 0):,}")
                col_b.metric("Estimated checks", f"{event.get('estimated_comparisons', estimated_checks):,}")
                col_c.metric("Elapsed", f"{elapsed:,.1f}s")

        try:
            route_df, summary_df, lookup_warnings = optimise_vehicle_routes(
                jobs_df,
                riders,
                use_onemap=use_onemap,
                optimise_by=optimise_by,
                token=onemap_token or None,
                progress_callback=show_progress,
                empty_weight=empty_weight,
                loaded_weight=loaded_weight,
                soft_workload_min=soft_workload_min,
                workload_penalty_per_min=workload_penalty_per_min,
                soft_adjusted_duration_min=soft_adjusted_duration_min,
                duration_penalty_per_min=duration_penalty_per_min,
                max_job_overage_penalty=max_job_overage_penalty,
                duration_buffer_multiplier=duration_buffer_multiplier,
                max_adjusted_duration_min=max_adjusted_duration_min,
            )
        finally:
            progress_bar.progress(1.0, text="Finished optimisation.")
        if route_df.empty:
            st.session_state.bluesg_latest_optimisation = None
            st.warning("No jobs could be assigned. Check rider roster and input data.")
        else:
            st.session_state.bluesg_selected_map_rider = ""
            st.session_state.bluesg_latest_optimisation = {
                "route_df": route_df.copy(),
                "summary_df": summary_df.copy(),
                "jobs_df": jobs_df.copy(),
                "rider_df": rider_df.copy(),
                "validation_warnings": list(validation_warnings),
                "lookup_warnings": list(lookup_warnings),
                "token": onemap_token or None,
            }

latest_optimisation = st.session_state.get("bluesg_latest_optimisation")
if latest_optimisation:
    route_df = latest_optimisation["route_df"]
    summary_df = latest_optimisation["summary_df"]
    result_jobs_df = latest_optimisation["jobs_df"]
    result_rider_df = latest_optimisation["rider_df"]
    result_validation_warnings = latest_optimisation["validation_warnings"]
    result_lookup_warnings = latest_optimisation["lookup_warnings"]
    result_token = latest_optimisation["token"]

    if len(route_df) < len(result_jobs_df):
        st.warning(
            f"Assigned {len(route_df)} of {len(result_jobs_df)} job(s). "
            "Some jobs were left unassigned because assigning them would break the adjusted 3-hour cap "
            "or no suitable rider was available."
        )

    if result_lookup_warnings:
        with st.expander("OneMap lookup fallbacks", expanded=False):
            st.write("These lookups used fallback estimates instead of OneMap results:")
            for warning in result_lookup_warnings[:100]:
                st.warning(warning)
            if len(result_lookup_warnings) > 100:
                st.info(f"Showing first 100 of {len(result_lookup_warnings)} lookup warning(s).")

    failed_validation = route_df["Route Validation Status"].ne("OK")
    if failed_validation.any():
        st.warning("Some rider route rows did not chain correctly. Check the validation status column.")

    show_route_map(route_df, result_jobs_df, result_rider_df, result_token)

    st.subheader("Optimised Rider Routes")
    st.dataframe(route_df, use_container_width=True, hide_index=True)

    st.subheader("Summary")
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    st.download_button(
        "Download Excel Output",
        data=export_routes_to_excel(
            route_df,
            summary_df,
            jobs_df=result_jobs_df,
            validation_warnings=result_validation_warnings,
            lookup_warnings=result_lookup_warnings,
        ),
        file_name="vehicle_route_optimisation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
