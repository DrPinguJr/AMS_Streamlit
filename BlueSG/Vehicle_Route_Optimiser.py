import os
import json
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
    DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
    DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
    DEFAULT_CLUSTER_PRESSURE_BONUS_PER_JOB,
    DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
    DEFAULT_SOFT_WORKLOAD_MIN,
    DEFAULT_WORKLOAD_PENALTY_PER_MIN,
    REQUIRED_JOB_HEADERS,
    ROSTER_FILE,
    clean_text,
    WEEKDAY_SHEETS,
    dedupe_rider_roster,
    ensure_rider_roster_workbook,
    export_routes_to_excel,
    build_unassigned_jobs_df,
    get_cost_explanation,
    get_cached_geocode,
    load_and_validate_jobs,
    load_rider_roster,
    optimisation_integrity_report,
    optimise_vehicle_routes,
    read_rider_roster_file,
    save_rider_roster,
    validate_riders,
)

try:
    st.set_page_config(page_title="Vehicle Route Optimiser", layout="wide")
except st.errors.StreamlitAPIException:
    pass


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


def parse_route_path(value: object) -> list[list[float]]:
    if isinstance(value, list):
        return value
    if value is None or pd.isna(value) or value == "":
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return parsed


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
                "Instructions": clean_text(row.get("Empty PT Instructions")),
                "Route Path": parse_route_path(row.get("Empty Route Path")),
                "color": public_colour,
            },
            {
                "Mode": "Car movement",
                "From": clean_text(row["Pickup Address"]),
                "To": clean_text(row["Drop-off Address"]),
                "Distance KM": row["Loaded Distance KM"],
                "Duration Min": row["Loaded Duration Min"],
                "Instructions": clean_text(row.get("Loaded Drive Instructions")),
                "Route Path": parse_route_path(row.get("Loaded Route Path")),
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
            path = leg["Route Path"] or [[start["lon"], start["lat"]], [end["lon"], end["lat"]]]
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
                    "path": path,
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
                        f"{leg['Instructions']}<br/>"
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
st.caption("Upload vehicle relocation jobs, confirm riders, optimise routes, and download dispatch instructions.")

st.info(
    "How to use:\n"
    "1. Upload the job Excel file.\n"
    "2. Check the rider roster.\n"
    "3. Click Optimise Routes.\n"
    "4. Review the map and download the output."
)

with st.expander("How the route optimiser works", expanded=False):
    st.write(
        "Each job is a fixed pickup-to-drop-off vehicle relocation. The rider first travels "
        "to the pickup location without the car, then drives the car to the drop-off location. "
        "The empty travel duration is adjusted upward to allow for public transport, walking, and waiting time. "
        "After each drop-off, that drop-off becomes the rider's next starting point. OneMap is "
        "used where available; fallback zone estimates are used when a lookup is unavailable."
    )

st.subheader("1. Upload Job List")
uploaded_file = st.file_uploader("Upload vehicle jobs Excel file", type=["xlsx", "xls"])

jobs_df = pd.DataFrame()
file_is_valid = False
missing_headers: list[str] = []
validation_warnings: list[str] = []
upload_error = ""

if uploaded_file is None:
    st.caption("Upload an Excel file to begin.")
else:
    try:
        jobs_df, missing_headers, validation_warnings = load_and_validate_jobs(uploaded_file)
    except ValueError as exc:
        upload_error = str(exc)
        st.error(upload_error)
    else:
        if missing_headers:
            st.error("Missing required header(s): " + ", ".join(missing_headers))
        else:
            file_is_valid = True
            skipped_rows = int(jobs_df.attrs.get("blank_address_rows_dropped", 0))
            status_cols = st.columns(2)
            status_cols[0].metric("Valid Jobs", len(jobs_df))
            status_cols[1].metric("Skipped Rows", skipped_rows)
            preview_columns = [
                "Car Plate",
                "Pickup Address",
                "Pickup Lot",
                "Drop-off Address",
                "Pickup Zone",
                "Drop-off Zone",
            ]
            st.dataframe(jobs_df[preview_columns], use_container_width=True, hide_index=True)

with st.expander("Excel format and data checks", expanded=False):
    st.write("Required headers:")
    st.write(", ".join(REQUIRED_JOB_HEADERS))
    st.write("Optional headers: Date, Fuel %, Pickup Time, Notes")
    if upload_error:
        st.error(upload_error)
    if missing_headers:
        st.error("Missing required header(s): " + ", ".join(missing_headers))
    for warning in validation_warnings:
        st.warning(warning)

st.subheader("2. Confirm Riders")
roster_path = ensure_rider_roster_workbook()

selected_roster_day = st.selectbox("Roster day", WEEKDAY_SHEETS)
st.caption("Max Jobs is a soft guide. The optimiser may exceed it only when the route still makes operational sense.")

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

if st.button("Save Roster", type="secondary"):
    try:
        saved_path = save_rider_roster(selected_roster_day, rider_df)
    except PermissionError:
        st.error("Could not save roster. Close the Excel workbook if it is open, then try again.")
    except Exception as exc:
        st.error(f"Could not save roster: {exc}")
    else:
        st.success(f"Saved {selected_roster_day} roster to {saved_path}")

with st.expander("Roster file options", expanded=False):
    st.caption(f"Persistent roster workbook: {roster_path}")
    roster_actions = st.columns(3)
    with roster_actions[0]:
        if st.button("Reload From Excel"):
            try:
                st.session_state.bluesg_riders = load_rider_roster(selected_roster_day)
            except Exception as exc:
                st.error(f"Could not reload roster: {exc}")
            else:
                st.rerun()
    with roster_actions[1]:
        if st.button("Open Excel File"):
            try:
                os.startfile(ROSTER_FILE)
            except Exception as exc:
                st.error(f"Could not open roster workbook: {exc}")
    with roster_actions[2]:
        st.download_button(
            "Download Roster Workbook",
            data=read_rider_roster_file(),
            file_name="rider_roster.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

scoring_defaults = {
    "empty_weight": DEFAULT_EMPTY_WEIGHT,
    "loaded_weight": DEFAULT_LOADED_WEIGHT,
    "soft_workload_min": DEFAULT_SOFT_WORKLOAD_MIN,
    "workload_penalty_per_min": DEFAULT_WORKLOAD_PENALTY_PER_MIN,
    "soft_adjusted_duration_min": DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
    "duration_penalty_per_min": DEFAULT_DURATION_PENALTY_PER_MIN,
    "max_job_overage_penalty": DEFAULT_MAX_JOB_OVERAGE_PENALTY,
    "duration_buffer_multiplier": DEFAULT_DURATION_BUFFER_MULTIPLIER,
    "max_adjusted_duration_min": DEFAULT_MAX_ADJUSTED_DURATION_MIN,
    "empty_travel_duration_multiplier": DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
    "empty_travel_wait_buffer_min": DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
    "cluster_pressure_bonus_per_job": DEFAULT_CLUSTER_PRESSURE_BONUS_PER_JOB,
}

with st.expander("Advanced Settings", expanded=False):
    st.markdown("**Routing Engine**")
    use_onemap = st.toggle("Use OneMap distance/time if available", value=True)
    onemap_token = st.text_input(
        "OneMap access token",
        value=get_onemap_token_from_env(),
        type="password",
        help="Required for OneMap routing distance/time. If blank or invalid, the app will use fallback estimates.",
        disabled=not use_onemap,
    )
    st.write("Fallback travel cost table")
    st.dataframe(cached_cost_explanation(), use_container_width=True, hide_index=True)

    st.markdown("**Public Transport Empty Leg**")
    st.caption("Empty travel is rider movement to the car, so it includes walking, waiting, and transfer buffer.")
    pt_col_a, pt_col_b = st.columns(2)
    with pt_col_a:
        empty_travel_duration_multiplier = st.number_input(
            "Empty travel duration multiplier",
            value=scoring_defaults["empty_travel_duration_multiplier"],
            min_value=1.0,
            max_value=3.0,
            step=0.1,
            key="bluesg_empty_travel_duration_multiplier",
        )
    with pt_col_b:
        empty_travel_wait_buffer_min = st.number_input(
            "Empty travel wait/walk buffer min",
            value=scoring_defaults["empty_travel_wait_buffer_min"],
            min_value=0.0,
            max_value=30.0,
            step=1.0,
            key="bluesg_empty_travel_wait_buffer_min",
        )

    st.markdown("**Assignment Scoring**")
    st.caption("Recommended defaults prioritise shorter rider-to-car travel while preventing routes from becoming too long.")
    force_complete_assignment = st.checkbox(
        "Force complete assignment where possible",
        value=True,
        help="If enabled, the optimiser retries unassigned jobs in different route positions, but never exceeds the max adjusted minutes cap.",
    )
    if st.button("Reset to Recommended Defaults"):
        for key, value in scoring_defaults.items():
            st.session_state[f"bluesg_{key}"] = value

    score_col_a, score_col_b = st.columns(2)
    with score_col_a:
        empty_weight = st.number_input(
            "Empty leg weight",
            value=scoring_defaults["empty_weight"],
            min_value=1.0,
            max_value=10.0,
            step=0.5,
            key="bluesg_empty_weight",
        )
    with score_col_b:
        loaded_weight = st.number_input(
            "Loaded leg weight",
            value=scoring_defaults["loaded_weight"],
            min_value=0.5,
            max_value=5.0,
            step=0.5,
            key="bluesg_loaded_weight",
        )
    workload_col_a, workload_col_b, workload_col_c, workload_col_d = st.columns(4)
    with workload_col_a:
        soft_workload_min = st.number_input(
            "Soft workload minutes",
            value=scoring_defaults["soft_workload_min"],
            min_value=30.0,
            max_value=180.0,
            step=5.0,
            key="bluesg_soft_workload_min",
        )
    with workload_col_b:
        workload_penalty_per_min = st.number_input(
            "Workload penalty/min",
            value=scoring_defaults["workload_penalty_per_min"],
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            key="bluesg_workload_penalty_per_min",
        )
    with workload_col_c:
        soft_adjusted_duration_min = st.number_input(
            "Soft adjusted minutes",
            value=scoring_defaults["soft_adjusted_duration_min"],
            min_value=60.0,
            max_value=240.0,
            step=5.0,
            key="bluesg_soft_adjusted_duration_min",
        )
    with workload_col_d:
        duration_penalty_per_min = st.number_input(
            "Duration penalty/min",
            value=scoring_defaults["duration_penalty_per_min"],
            min_value=0.0,
            max_value=15.0,
            step=0.5,
            key="bluesg_duration_penalty_per_min",
        )
    cap_col_a, cap_col_b, cap_col_c = st.columns(3)
    with cap_col_a:
        max_job_overage_penalty = st.number_input(
            "Max jobs overage penalty",
            value=scoring_defaults["max_job_overage_penalty"],
            min_value=0.0,
            max_value=300.0,
            step=10.0,
            key="bluesg_max_job_overage_penalty",
        )
    with cap_col_b:
        duration_buffer_multiplier = st.number_input(
            "Duration buffer multiplier",
            value=scoring_defaults["duration_buffer_multiplier"],
            min_value=1.0,
            max_value=2.0,
            step=0.1,
            key="bluesg_duration_buffer_multiplier",
        )
    with cap_col_c:
        max_adjusted_duration_min = st.number_input(
            "Max adjusted minutes",
            value=scoring_defaults["max_adjusted_duration_min"],
            min_value=60.0,
            max_value=360.0,
            step=15.0,
            key="bluesg_max_adjusted_duration_min",
        )
    cluster_pressure_bonus_per_job = st.number_input(
        "Cluster pressure bonus per remaining pickup",
        value=scoring_defaults["cluster_pressure_bonus_per_job"],
        min_value=0.0,
        max_value=30.0,
        step=1.0,
        key="bluesg_cluster_pressure_bonus_per_job",
    )

st.subheader("3. Optimise Routes")
optimise_by_label = st.radio(
    "Optimise by",
    ["Duration", "Distance"],
    horizontal=True,
    captions=["Lowest total minutes", "Lowest total kilometres"],
)
optimise_by = optimise_by_label.lower()

if use_onemap and not onemap_token:
    st.warning("OneMap is enabled but no token is entered. The app will use fallback estimates where needed.")

if st.button("Optimise Routes", type="primary", disabled=not file_is_valid):
    rider_df_for_optimise, duplicate_rider_rows_removed = dedupe_rider_roster(rider_df)
    if duplicate_rider_rows_removed:
        st.warning(f"Duplicate rider rows removed before optimisation: {duplicate_rider_rows_removed}")
    riders, rider_errors = validate_riders(rider_df_for_optimise)
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
                f"{estimated_checks:,} rider-job combinations. Cached addresses and routes are reused, "
                "and OneMap PT is only called for distinct empty-leg pairs where needed."
            )

        progress_panel = st.container(border=True)
        with progress_panel:
            st.markdown("**Optimisation in progress**")
            metric_cols = st.columns(5)
            phase_metric = metric_cols[0].empty()
            assigned_metric = metric_cols[1].empty()
            remaining_metric = metric_cols[2].empty()
            elapsed_metric = metric_cols[3].empty()
            checks_metric = metric_cols[4].empty()
            progress_bar = st.progress(0, text="Preparing optimisation...")
            activity_text = st.empty()
            detail_text = st.empty()
        started_at = time.monotonic()
        last_progress_event: dict = {}

        def show_progress(event: dict) -> None:
            last_progress_event.clear()
            last_progress_event.update(event)
            elapsed = time.monotonic() - started_at
            progress_value = max(0.0, min(1.0, float(event.get("progress", 0))))
            assigned_jobs = int(event.get("assigned_jobs", 0) or 0)
            total_jobs = int(event.get("total_jobs", 0) or 0)
            remaining_jobs = int(event.get("remaining_jobs", 0) or 0)
            comparison_count = int(event.get("comparison_count", 0) or 0)
            estimated_comparisons = int(event.get("estimated_comparisons", 0) or 0)
            phase = str(event.get("phase", "Working"))
            status = str(event.get("status", "Optimising routes..."))

            phase_metric.metric("Phase", phase)
            assigned_metric.metric("Assigned", f"{assigned_jobs}/{total_jobs}")
            remaining_metric.metric("Remaining", remaining_jobs)
            elapsed_metric.metric("Elapsed", f"{elapsed:,.1f}s")
            checks_metric.metric("Checks", f"{comparison_count:,}/{estimated_comparisons:,}")
            progress_bar.progress(progress_value, text=f"{status} ({progress_value * 100:.0f}%)")
            activity_text.info(status)

            detail_parts = []
            if event.get("current_address"):
                detail_parts.append(("Address", event["current_address"]))
            if event.get("current_rider"):
                detail_parts.append(("Rider", event["current_rider"]))
            if event.get("current_pickup"):
                detail_parts.append(("Pickup", event["current_pickup"]))
            if event.get("current_dropoff"):
                detail_parts.append(("Drop-off", event["current_dropoff"]))

            if detail_parts:
                detail_text.dataframe(
                    pd.DataFrame(detail_parts, columns=["Current item", "Value"]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                detail_text.caption("Warming up caches and preparing route checks...")

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
                empty_travel_duration_multiplier=empty_travel_duration_multiplier,
                empty_travel_wait_buffer_min=empty_travel_wait_buffer_min,
                force_complete_assignment=force_complete_assignment,
                cluster_pressure_bonus_per_job=cluster_pressure_bonus_per_job,
            )
            integrity_report = optimisation_integrity_report(route_df, jobs_df)
            if not integrity_report["is_valid"]:
                st.error(integrity_report["message"])
                if integrity_report["duplicate_details"]:
                    st.dataframe(pd.DataFrame(integrity_report["duplicate_details"]), use_container_width=True, hide_index=True)
                st.stop()
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        finally:
            progress_bar.progress(1.0, text="Finished optimisation.")
            activity_text.success("Finished optimisation.")
        elapsed_total = time.monotonic() - started_at
        if route_df.empty:
            st.session_state.bluesg_latest_optimisation = None
            st.warning("No jobs could be assigned. Check rider roster and input data.")
        else:
            st.session_state.bluesg_selected_map_rider = ""
            st.session_state.bluesg_latest_optimisation = {
                "route_df": route_df.copy(),
                "summary_df": summary_df.copy(),
                "jobs_df": jobs_df.copy(),
                "rider_df": rider_df_for_optimise.copy(),
                "validation_warnings": list(validation_warnings),
                "lookup_warnings": list(lookup_warnings),
                "token": onemap_token or None,
                "integrity_report": integrity_report,
                "duplicate_rider_rows_removed": duplicate_rider_rows_removed,
                "diagnostics": {
                    "rider_job_checks": int(last_progress_event.get("comparison_count", 0)),
                    "estimated_checks": int(last_progress_event.get("estimated_comparisons", estimated_checks)),
                    "elapsed_seconds": elapsed_total,
                },
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
    result_diagnostics = latest_optimisation.get("diagnostics", {})
    result_integrity = latest_optimisation.get("integrity_report") or optimisation_integrity_report(route_df, result_jobs_df)
    duplicate_rider_rows_removed = int(latest_optimisation.get("duplicate_rider_rows_removed", 0))
    unassigned_jobs_df = result_integrity["unassigned_df"]

    if not result_integrity["is_valid"]:
        st.error(result_integrity["message"])
        if result_integrity["duplicate_details"]:
            st.dataframe(pd.DataFrame(result_integrity["duplicate_details"]), use_container_width=True, hide_index=True)
        st.stop()

    st.subheader("4. Review Results")
    assigned_jobs = int(result_integrity["assigned_unique_jobs"])
    assigned_route_rows = int(result_integrity["assigned_route_rows"])
    total_jobs_uploaded = int(result_integrity["total_valid_jobs"])
    unassigned_jobs = int(result_integrity["unassigned_jobs"])
    riders_used = (
        int((summary_df["Total Jobs"].fillna(0).astype(int) > 0).sum())
        if "Total Jobs" in summary_df.columns
        else 0
    )
    total_duration = (
        float(summary_df["Total Route Duration Min"].fillna(0).sum())
        if "Total Route Duration Min" in summary_df.columns
        else 0.0
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("Jobs Assigned", f"{assigned_jobs}/{total_jobs_uploaded}")
    metric_cols[1].metric("Riders Used", riders_used)
    metric_cols[2].metric("Total Estimated Duration", f"{total_duration:.1f} min")
    metric_cols[3].metric("Unassigned Jobs", unassigned_jobs)

    with st.expander("Optimisation Integrity Checks", expanded=False):
        integrity_rows = [
            ["Total valid jobs", total_jobs_uploaded],
            ["Unique assigned jobs", assigned_jobs],
            ["Assigned route rows", assigned_route_rows],
            ["Unassigned jobs", unassigned_jobs],
            ["Duplicate assigned Uploaded Rows", ", ".join(map(str, result_integrity["duplicate_uploaded_rows"])) or "None"],
            ["Jobs in both assigned and unassigned", ", ".join(map(str, result_integrity["overlap_uploaded_rows"])) or "None"],
            ["Duplicate rider rows removed", duplicate_rider_rows_removed],
        ]
        st.dataframe(pd.DataFrame(integrity_rows, columns=["Check", "Value"]), use_container_width=True, hide_index=True)
        if result_integrity["duplicate_details"]:
            st.write("Duplicate assignment details")
            st.dataframe(pd.DataFrame(result_integrity["duplicate_details"]), use_container_width=True, hide_index=True)

    if unassigned_jobs:
        st.warning(
            f"Assigned {assigned_jobs} of {total_jobs_uploaded} job(s). "
            "Some jobs were left unassigned because no rider route could fit them inside the 14:00-17:00 job window."
        )
        if not unassigned_jobs_df.empty:
            st.write("Unassigned jobs")
            st.dataframe(unassigned_jobs_df, use_container_width=True, hide_index=True)

    failed_validation = route_df["Route Validation Status"].ne("OK")
    if failed_validation.any():
        st.warning("Some rider route rows did not chain correctly. Open Data and route warnings for details.")

    with st.expander("Data and route warnings", expanded=False):
        if result_lookup_warnings:
            st.write("OneMap lookups that used fallback estimates:")
            for warning in result_lookup_warnings[:100]:
                st.warning(warning)
            if len(result_lookup_warnings) > 100:
                st.info(f"Showing first 100 of {len(result_lookup_warnings)} lookup warning(s).")
        else:
            st.caption("No OneMap fallback warnings for the latest run.")

        for warning in result_validation_warnings:
            st.warning(warning)

        if failed_validation.any():
            st.write("Route validation rows to review:")
            validation_cols = [
                column
                for column in ["Rider", "Sequence", "Start From", "Drop-off Address", "Route Validation Status"]
                if column in route_df.columns
            ]
            st.dataframe(route_df.loc[failed_validation, validation_cols], use_container_width=True, hide_index=True)

    with st.expander("Optimisation diagnostics", expanded=False):
        diag_cols = st.columns(3)
        diag_cols[0].metric("Rider-job checks", f"{int(result_diagnostics.get('rider_job_checks', 0)):,}")
        diag_cols[1].metric("Estimated checks", f"{int(result_diagnostics.get('estimated_checks', 0)):,}")
        diag_cols[2].metric("Elapsed time", f"{float(result_diagnostics.get('elapsed_seconds', 0.0)):.1f}s")

    show_route_map(route_df, result_jobs_df, result_rider_df, result_token)

    st.subheader("Dispatch View")
    dispatch_columns = [
        "Rider",
        "Sequence",
        "Car Plate",
        "Pickup Address",
        "Pickup Lot",
        "Drop-off Address",
        "Empty Travel To Pickup",
        "Loaded Travel / Car Movement",
        "Total Distance KM",
        "Total Duration Min",
    ]
    dispatch_columns = [column for column in dispatch_columns if column in route_df.columns]
    st.dataframe(route_df[dispatch_columns], use_container_width=True, hide_index=True)

    with st.expander("Technical route details", expanded=False):
        st.dataframe(route_df, use_container_width=True, hide_index=True)

    st.subheader("Summary")
    summary_columns = [
        "Rider",
        "Total Jobs",
        "Total Route Distance KM",
        "Total Route Duration Min",
        "Adjusted Route Duration Min",
        "Within 3 Hours",
        "Final Location",
        "Workload Comment",
    ]
    summary_columns = [column for column in summary_columns if column in summary_df.columns]
    st.dataframe(summary_df[summary_columns], use_container_width=True, hide_index=True)

    detail_summary_columns = [
        "Rider",
        "Total Empty Distance KM",
        "Total Empty Duration Min",
        "Total Loaded Distance KM",
        "Total Loaded Duration Min",
        "Empty Travel %",
        "Loaded Travel %",
    ]
    detail_summary_columns = [column for column in detail_summary_columns if column in summary_df.columns]
    with st.expander("Detailed summary columns", expanded=False):
        st.dataframe(summary_df[detail_summary_columns], use_container_width=True, hide_index=True)

    st.subheader("5. Download")
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
