import importlib
import json
import sys
import time
import copy
import hashlib
from datetime import time as clock_time
from io import BytesIO
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Flexar.BlueSG import build_optimised_vehicle_routes as _route_optimizer_backend

# Streamlit can keep the backend module from an earlier hot-reload while
# re-running only this page. Refresh it when a newly added helper is missing.
if not hasattr(_route_optimizer_backend, "cache_unique_geocodes"):
    _route_optimizer_backend = importlib.reload(_route_optimizer_backend)
if not hasattr(_route_optimizer_backend, "RIDER_LOAD_INPUT_OPTIONS"):
    _route_optimizer_backend = importlib.reload(_route_optimizer_backend)

from Flexar.BlueSG import cloud_deployment_preflight as _deployment_preflight

if not hasattr(_deployment_preflight, "import_module_with_required_exports"):
    _deployment_preflight = importlib.reload(_deployment_preflight)

REQUIRED_MODULE_EXPORTS = _deployment_preflight.REQUIRED_MODULE_EXPORTS
import_module_with_required_exports = (
    _deployment_preflight.import_module_with_required_exports
)

# Streamlit hot updates can retain an older imported module even when the page
# file has already updated. Verify the exact symbols used below and refresh any
# stale module before Python evaluates the named imports.
for _module_name in (
    "Flexar.BlueSG.optimiser_config",
    "Flexar.BlueSG.vehicle_route_optimiser_v2",
    "Flexar.BlueSG.v2_daily_roster_source",
    "Flexar.BlueSG.optimiser_workflow_state",
):
    import_module_with_required_exports(
        _module_name,
        REQUIRED_MODULE_EXPORTS[_module_name],
    )

from Flexar.BlueSG.build_optimised_vehicle_routes import (
    DEFAULT_DURATION_BUFFER_MULTIPLIER,
    DEFAULT_DURATION_PENALTY_PER_MIN,
    DEFAULT_EMPTY_WEIGHT,
    DEFAULT_LOADED_WEIGHT,
    DEFAULT_MAX_ADJUSTED_DURATION_MIN,
    DEFAULT_MAX_JOB_OVERAGE_PENALTY,
    DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
    DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
    DEFAULT_CLUSTER_PRESSURE_BONUS_PER_JOB,
    DEFAULT_FALLBACK_PENALTY,
    DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
    DEFAULT_SOFT_WORKLOAD_MIN,
    DEFAULT_WORKLOAD_PENALTY_PER_MIN,
    DEFAULT_SELECTIVE_CHANGED_RIDER_PENALTY,
    DEFAULT_SELECTIVE_MOVED_JOB_PENALTY,
    DEFAULT_SELECTIVE_SEQUENCE_CHANGE_PENALTY,
    RIDER_COLUMNS,
    RIDER_LOAD_INPUT_OPTIONS,
    RIDER_LOAD_LEVELS,
    SUMMARY_COLUMNS,
    build_jobs_by_stable_id,
    build_rider_sequences_from_route_df,
    find_best_selective_reshuffle,
    rebuild_outputs_from_sequences,
    stable_job_id_from_route_row,
    clean_text,
    WEEKDAY_SHEETS,
    dedupe_rider_roster,
    ensure_rider_roster_workbook,
    export_routes_to_excel,
    format_summary_output,
    build_unassigned_jobs_df,
    get_cost_explanation,
    get_cached_geocode,
    load_rider_roster,
    normalise_rider_load_level,
    optimisation_integrity_report,
    optimise_vehicle_routes,
    improve_route_dataframe,
    read_rider_roster_file,
    save_rider_roster,
    validate_riders,
)
from Flexar.BlueSG.manual_route_assignment_editing_and_recalculation import (
    UNASSIGNED_LANE,
    assignment_from_routes,
    clone_assignment,
    incremental_recalculate,
)
from Flexar.BlueSG.validate_route_assignment_hard_constraints import Constraint
from Flexar.BlueSG.route_operation_time_window_settings import EMPTY_TRAVEL_MODES, OperationContext
from Flexar.BlueSG.convert_results_to_output_safe_values import sanitize_for_output
from Flexar.BlueSG.route_optimisation_metrics_and_run_summary import (
    create_run_result,
    save_run_artifact,
)
from Flexar.BlueSG.job_import_staging import (
    ImportResult,
    parse_job_source,
    validate_staged_jobs,
)
from Flexar.BlueSG.optimiser_workflow_state import (
    begin_rider_draft,
    cancel_rider_draft,
    clear_import,
    commit_optimiser_result,
    initialise_workflow_state,
    normalise_riders,
    refresh_stale_flag,
    riders_for_optimizer,
    riders_for_v2,
    save_rider_draft,
    normalise_assignment_sequences,
    streamlit_key_value_table,
    validate_and_commit_job_import,
    validate_assignment_draft,
    validate_rider_draft,
)
from Flexar.BlueSG.optimiser_config import OPTIMISER_VERSION
from Flexar.BlueSG.vehicle_route_optimiser_v2 import (
    V2OptimisationResult,
    WorkStyle,
    capacity_summary,
    run_optimiser_v2,
    validate_v2_roster,
)
from Flexar.BlueSG.v2_daily_roster_source import (
    DEFAULT_LOCAL_ROSTER,
    load_daily_v2_roster,
    save_local_v2_roster,
)

try:
    st.set_page_config(page_title="Vehicle Route Optimiser — Version 2.0", layout="wide")
except st.errors.StreamlitAPIException:
    pass


@st.cache_data(show_spinner=False)
def cached_cost_explanation() -> pd.DataFrame:
    return get_cost_explanation()


@st.cache_data(show_spinner=False)
def cached_route_map_geocodes(addresses: tuple[str, ...], token: str | None) -> dict[str, dict[str, object]]:
    batch_geocoder = getattr(_route_optimizer_backend, "cache_unique_geocodes", None)
    if callable(batch_geocoder):
        results = batch_geocoder(addresses, token=token, use_onemap=True)
    else:
        # Compatibility fallback for a partially reloaded Streamlit session.
        results = {
            address: get_cached_geocode(address, token=token, use_onemap=True)
            for address in addresses
        }
    geocodes: dict[str, dict[str, object]] = {}
    for address, result in results.items():
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


def normalise_map_sequence(value: object) -> str:
    if value is None or pd.isna(value):
        return "Missing"
    text = clean_text(value)
    if not text:
        return "Missing"
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if number.is_integer():
        return str(int(number))
    return str(number).rstrip("0").rstrip(".")


def route_sequence_options(route_df: pd.DataFrame) -> list[str]:
    if route_df.empty or "Sequence" not in route_df.columns:
        return []
    options = []
    seen = set()
    for value in route_df["Sequence"].tolist():
        sequence = normalise_map_sequence(value)
        if sequence in seen:
            continue
        seen.add(sequence)
        options.append(sequence)
    return options


def map_sequence_sort_value(value: object) -> tuple[int, float | str]:
    sequence = normalise_map_sequence(value)
    try:
        return (0, float(sequence))
    except (TypeError, ValueError):
        return (1, sequence)


def sort_routes_for_map(route_df: pd.DataFrame) -> pd.DataFrame:
    if route_df.empty:
        return route_df.copy()
    sorted_df = route_df.copy()
    sorted_df["_map_sequence_sort"] = sorted_df["Sequence"].apply(map_sequence_sort_value)
    sorted_df["_map_original_order"] = range(len(sorted_df))
    sorted_df = sorted_df.sort_values(
        ["Rider", "_map_sequence_sort", "_map_original_order"],
        kind="stable",
    )
    return sorted_df.drop(columns=["_map_sequence_sort", "_map_original_order"], errors="ignore")


def format_route_metric(value: object, suffix: str) -> str:
    if value is None or pd.isna(value) or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value} {suffix}"
    return f"{round(number, 1)} {suffix}"


def add_map_point(
    point_rows: list[dict[str, object]],
    geocodes: dict[str, dict[str, object]],
    address: str,
    location_type: str,
    tooltip: str,
    radius: int,
    fill_color: list[int],
    is_background: bool = False,
) -> None:
    address = clean_text(address)
    result = geocodes.get(address, {})
    if result.get("lat") is None or result.get("lon") is None:
        return
    point_rows.append(
        {
            "Address": address,
            "Location Type": location_type,
            "tooltip": tooltip,
            "lat": result["lat"],
            "lon": result["lon"],
            "radius": radius,
            "fill_color": fill_color,
            "is_background": is_background,
        }
    )


def map_view_state(point_df: pd.DataFrame, individual_job_selected: bool) -> pdk.ViewState:
    if point_df.empty:
        return pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=11, pitch=0)

    latitudes = pd.to_numeric(point_df["lat"], errors="coerce").dropna()
    longitudes = pd.to_numeric(point_df["lon"], errors="coerce").dropna()
    if latitudes.empty or longitudes.empty:
        return pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=11, pitch=0)

    view_lat = float(latitudes.mean())
    view_lon = float(longitudes.mean())
    spread = max(float(latitudes.max() - latitudes.min()), float(longitudes.max() - longitudes.min()))

    if len(point_df) <= 1:
        zoom = 13.5 if individual_job_selected else 12.5
    elif individual_job_selected:
        if spread <= 0.01:
            zoom = 13.4
        elif spread <= 0.03:
            zoom = 12.7
        elif spread <= 0.08:
            zoom = 11.8
        else:
            zoom = 10.9
    else:
        if spread <= 0.03:
            zoom = 12.1
        elif spread <= 0.08:
            zoom = 11.3
        elif spread <= 0.15:
            zoom = 10.6
        else:
            zoom = 10.0

    return pdk.ViewState(latitude=view_lat, longitude=view_lon, zoom=zoom, pitch=0)


def add_session_rider_load_column(rider_df: pd.DataFrame) -> pd.DataFrame:
    rider_df = rider_df.copy() if rider_df is not None else pd.DataFrame()
    if "Rider Load" not in rider_df.columns:
        rider_df["Rider Load"] = "Medium"
    rider_df["Rider Load"] = rider_df["Rider Load"].apply(
        normalise_rider_load_level
    )
    return rider_df


def persistent_roster_columns(rider_df: pd.DataFrame) -> pd.DataFrame:
    rider_df = rider_df.copy() if rider_df is not None else pd.DataFrame()
    for column in RIDER_COLUMNS:
        if column not in rider_df.columns:
            rider_df[column] = None
    return rider_df.loc[:, RIDER_COLUMNS].copy()


def configured_google_roster_url() -> str:
    """Return the optional published Google-Sheet CSV URL without requiring secrets."""

    try:
        return clean_text(st.secrets.get("BLUESG_ROSTER_GOOGLE_SHEET_CSV_URL", ""))
    except Exception:
        return ""


def build_route_map_data(
    route_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    token: str | None,
    visible_route_df: pd.DataFrame | None = None,
    selected_rider: str = "",
    show_other_jobs: bool = False,
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
    visible_route_df = visible_route_df.copy() if visible_route_df is not None else pd.DataFrame()
    relevant_addresses = set()
    if selected_rider and not visible_route_df.empty:
        for _, route in visible_route_df.iterrows():
            sequence = normalise_map_sequence(route.get("Sequence"))
            start_address = clean_text(route.get("Start From"))
            pickup_address = clean_text(route.get("Pickup Address"))
            dropoff_address = clean_text(route.get("Drop-off Address"))
            for address in [start_address, pickup_address, dropoff_address]:
                if address:
                    relevant_addresses.add(address.casefold())

            add_map_point(
                point_rows,
                geocodes,
                start_address,
                "Start from",
                f"{selected_rider}<br/>Job {sequence} start<br/>{start_address}",
                74,
                [17, 24, 39],
            )
            add_map_point(
                point_rows,
                geocodes,
                pickup_address,
                "Pickup",
                f"{selected_rider}<br/>Job {sequence} pickup<br/>{pickup_address}",
                70,
                [14, 165, 233],
            )
            add_map_point(
                point_rows,
                geocodes,
                dropoff_address,
                "Drop-off",
                f"{selected_rider}<br/>Job {sequence} drop-off<br/>{dropoff_address}",
                70,
                [249, 115, 22],
            )

        if show_other_jobs:
            for _, job in jobs_df.iterrows():
                for location_type, column in [
                    ("Other pickup", "Pickup Address"),
                    ("Other drop-off", "Drop-off Address"),
                ]:
                    address = clean_text(job.get(column))
                    if not address or address.casefold() in relevant_addresses:
                        continue
                    add_map_point(
                        point_rows,
                        geocodes,
                        address,
                        location_type,
                        f"{location_type}<br/>{address}",
                        42,
                        [156, 163, 175, 95],
                        is_background=True,
                    )
    else:
        for _, rider in rider_df.iterrows():
            address = clean_text(rider.get("Start Location"))
            rider_name = clean_text(rider.get("Rider Name")) or "Rider"
            add_map_point(
                point_rows,
                geocodes,
                address,
                "Rider start",
                f"{rider_name}<br/>Rider start<br/>{address}",
                74,
                [17, 24, 39],
            )

        for _, job in jobs_df.iterrows():
            for location_type, column, colour in [
                ("Given pickup", "Pickup Address", [14, 165, 233]),
                ("Given drop-off", "Drop-off Address", [249, 115, 22]),
            ]:
                address = clean_text(job.get(column))
                add_map_point(
                    point_rows,
                    geocodes,
                    address,
                    location_type,
                    f"{location_type}<br/>{address}",
                    62,
                    colour,
                )

    leg_rows = []
    for _, row in sort_routes_for_map(route_df).iterrows():
        rider = str(row["Rider"])
        sequence = normalise_map_sequence(row.get("Sequence"))
        public_colour = [220, 38, 38, 210]
        car_colour = [22, 163, 74, 230]
        legs = [
            {
                "Mode": "Public transport / empty travel",
                "Mode Label": "PT",
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
                "Mode Label": "DRIVE",
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
                    "Sequence": row.get("Sequence"),
                    "sequence_key": sequence,
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
                    "label": f"J{sequence} · {leg['Mode Label']}",
                    "tooltip": (
                        f"{rider}<br/>Job {sequence}: {leg['Mode']}<br/>"
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
    st.subheader("Singapore Route Map")
    rider_names = list(route_df["Rider"].dropna().astype(str).drop_duplicates())
    selected_key = "bluesg_selected_map_rider"
    sequence_key = "bluesg_selected_map_sequence"
    labels_key = "bluesg_show_route_labels"
    labels_context_key = "bluesg_show_route_labels_context"
    show_other_jobs_key = "bluesg_show_other_jobs"
    selected_rider = st.session_state.get(selected_key, "")
    if selected_rider not in rider_names:
        selected_rider = ""
        st.session_state[selected_key] = ""
        st.session_state[sequence_key] = "All"

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
                width="stretch",
            ):
                if selected_rider != rider_name:
                    st.session_state[sequence_key] = "All"
                    st.session_state[labels_context_key] = ""
                selected_rider = rider_name
                st.session_state[selected_key] = rider_name
            if selected_rider == rider_name:
                st.caption(f"{len(rider_routes)} job(s)")
                st.caption(f"{round(total_distance, 2)} km")
                st.caption(f"{round(total_duration, 1)} min")

        if selected_rider and st.button("Clear route", key="map_clear_rider", width="stretch"):
            selected_rider = ""
            st.session_state[selected_key] = ""
            st.session_state[sequence_key] = "All"
            st.session_state[labels_context_key] = ""

    selected_rider_route_df = pd.DataFrame()
    visible_route_df = pd.DataFrame()
    sequence_options: list[str] = []
    selected_sequence = "All"
    show_route_labels = False
    show_other_jobs = False
    if selected_rider:
        selected_rider_route_df = sort_routes_for_map(
            route_df[route_df["Rider"].astype(str) == selected_rider]
        )
        sequence_options = route_sequence_options(selected_rider_route_df)
        route_options = ["All"] + sequence_options
        if st.session_state.get(sequence_key, "All") not in route_options:
            st.session_state[sequence_key] = "All"

        with map_col:
            st.caption("Showing route for:")
            st.write(f"**{selected_rider}**")
            if hasattr(st, "segmented_control"):
                selected_sequence = st.segmented_control(
                    "Route",
                    route_options,
                    key=sequence_key,
                )
            else:
                selected_sequence = st.radio(
                    "Route",
                    route_options,
                    key=sequence_key,
                    horizontal=True,
                )
            selected_sequence = selected_sequence or "All"

            label_context = f"{selected_rider}|{selected_sequence}|{','.join(sequence_options)}"
            default_show_labels = selected_sequence != "All" or len(sequence_options) <= 3
            if st.session_state.get(labels_context_key) != label_context:
                st.session_state[labels_key] = default_show_labels
                st.session_state[labels_context_key] = label_context
            if show_other_jobs_key not in st.session_state:
                st.session_state[show_other_jobs_key] = False

            control_cols = st.columns(2)
            toggle_fn = st.toggle if hasattr(st, "toggle") else st.checkbox
            with control_cols[0]:
                show_route_labels = toggle_fn("Show route labels", key=labels_key)
            with control_cols[1]:
                show_other_jobs = toggle_fn("Show other jobs", key=show_other_jobs_key)

        if selected_sequence == "All":
            visible_route_df = selected_rider_route_df.copy()
        else:
            visible_route_df = selected_rider_route_df[
                selected_rider_route_df["Sequence"].apply(normalise_map_sequence) == selected_sequence
            ].copy()

    point_df, leg_df, missing_locations = build_route_map_data(
        route_df,
        jobs_df,
        rider_df,
        token,
        visible_route_df=visible_route_df,
        selected_rider=selected_rider,
        show_other_jobs=show_other_jobs,
    )

    if leg_df.empty and point_df.empty:
        st.warning("No map locations could be geocoded. Check the addresses or OneMap token.")
        return

    if missing_locations:
        with st.expander("Map locations not found", expanded=False):
            for warning in missing_locations[:80]:
                st.warning(warning)
            if len(missing_locations) > 80:
                st.info(f"Showing first 80 of {len(missing_locations)} missing location(s).")

    if selected_rider and "Rider" in leg_df.columns:
        visible_leg_df = leg_df[leg_df["Rider"] == selected_rider].copy()
        if selected_sequence != "All" and "sequence_key" in visible_leg_df.columns:
            visible_leg_df = visible_leg_df[visible_leg_df["sequence_key"] == selected_sequence].copy()
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
    if show_route_labels and not visible_leg_df.empty:
        layers.append(
            pdk.Layer(
                "TextLayer",
                visible_leg_df,
                get_position="label_position",
                get_text="label",
                get_color=[17, 24, 39],
                get_size=12,
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
        background_point_df = point_df[point_df["is_background"].fillna(False)].copy()
        active_point_df = point_df[~point_df["is_background"].fillna(False)].copy()
        if not background_point_df.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    background_point_df,
                    get_position="[lon, lat]",
                    get_fill_color="fill_color",
                    get_radius="radius",
                    radius_min_pixels=3,
                    radius_max_pixels=8,
                    stroked=True,
                    get_line_color=[255, 255, 255, 120],
                    line_width_min_pixels=1,
                    pickable=True,
                )
            )
        if not active_point_df.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    active_point_df,
                    get_position="[lon, lat]",
                    get_fill_color="fill_color",
                    get_radius="radius",
                    radius_min_pixels=6,
                    radius_max_pixels=14,
                    stroked=True,
                    get_line_color=[255, 255, 255],
                    line_width_min_pixels=1,
                    pickable=True,
                )
            )

    viewport_points = point_df[~point_df["is_background"].fillna(False)].copy() if not point_df.empty else point_df
    if viewport_points.empty:
        viewport_points = point_df
    deck = pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        initial_view_state=map_view_state(viewport_points, selected_sequence != "All"),
        layers=layers,
        tooltip={
            "html": "{tooltip}",
            "style": {"backgroundColor": "#111827", "color": "white"},
        },
    )
    with map_col:
        if selected_rider:
            if visible_leg_df.empty:
                st.warning("This route selection has no drawable route legs. Check whether the route addresses were geocoded.")
        else:
            st.caption("Select a rider on the right to show their route.")
        st.pydeck_chart(deck, width="stretch")

        if selected_rider and selected_sequence != "All" and not visible_route_df.empty:
            selected_job = visible_route_df.iloc[0]
            st.caption(f"JOB {selected_sequence}")
            summary_cols = st.columns(3)
            summary_cols[0].metric("Car Plate", clean_text(selected_job.get("Car Plate")) or "-")
            summary_cols[1].metric("Travel to Pickup", format_route_metric(selected_job.get("Empty Distance KM"), "km"))
            summary_cols[2].metric("Vehicle Movement", format_route_metric(selected_job.get("Loaded Distance KM"), "km"))
            detail_cols = st.columns(2)
            with detail_cols[0]:
                st.caption("Travel to Pickup")
                st.write(f"{clean_text(selected_job.get('Start From')) or '-'} -> {clean_text(selected_job.get('Pickup Address')) or '-'}")
                st.caption(
                    f"{format_route_metric(selected_job.get('Empty Distance KM'), 'km')} / "
                    f"{format_route_metric(selected_job.get('Empty Duration Min'), 'min')}"
                )
            with detail_cols[1]:
                st.caption("Vehicle Movement")
                st.write(f"{clean_text(selected_job.get('Pickup Address')) or '-'} -> {clean_text(selected_job.get('Drop-off Address')) or '-'}")
                st.caption(
                    f"{format_route_metric(selected_job.get('Loaded Distance KM'), 'km')} / "
                    f"{format_route_metric(selected_job.get('Loaded Duration Min'), 'min')}"
                )

        legend_cols = st.columns(4)
        legend_cols[0].caption("Red: public transport to pickup")
        legend_cols[1].caption("Green: driving/car movement")
        legend_cols[2].caption("Blue/orange dots: pickups/drop-offs")
        legend_cols[3].caption("Dark dot: job start")


def safe_widget_id(value: object) -> str:
    text = clean_text(value)
    return "".join(ch if ch.isalnum() else "_" for ch in text)[:80] or "item"


def route_editor_source_signature(route_df: pd.DataFrame) -> str:
    if route_df is None or route_df.empty:
        return ""
    rows = []
    for _, row in route_df.sort_values(["Rider", "Sequence"], kind="stable").iterrows():
        rows.append(
            "|".join(
                [
                    clean_text(row.get("Rider")),
                    clean_text(row.get("Sequence")),
                    clean_text(row.get("Uploaded Row")),
                    clean_text(row.get("Car Plate")),
                    clean_text(row.get("Pickup Address")),
                    clean_text(row.get("Drop-off Address")),
                ]
            )
        )
    return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()


def initialise_route_editor_state(route_df: pd.DataFrame) -> dict:
    signature = route_editor_source_signature(route_df)
    state = st.session_state.get("bluesg_route_editor_state")
    if state and state.get("source_signature") == signature:
        return state
    state = {
        "version": 1,
        "source_signature": signature,
        "rider_sequences": build_rider_sequences_from_route_df(route_df),
        "locked_riders": set(),
        "locked_job_ids": set(),
        "reshuffle_job_ids": set(),
        "eligible_receiver_riders": set(),
    }
    st.session_state.bluesg_route_editor_state = state
    st.session_state.bluesg_selective_reshuffle_result = None
    st.session_state.bluesg_selective_option_index = 0
    return state


def selected_job_lookup(route_df: pd.DataFrame) -> dict[str, dict[str, object]]:
    lookup = {}
    if route_df is None or route_df.empty:
        return lookup
    for _, row in route_df.iterrows():
        job_id = stable_job_id_from_route_row(row)
        lookup[job_id] = {
            "rider": clean_text(row.get("Rider")),
            "sequence": int(float(row.get("Sequence") or 0)),
            "car_plate": clean_text(row.get("Car Plate")),
            "pickup": clean_text(row.get("Pickup Address")),
            "dropoff": clean_text(row.get("Drop-off Address")),
            "duration": row.get("Total Duration Min", ""),
            "adjusted": row.get("Projected Adjusted Duration Min", ""),
            "uploaded_row": row.get("Uploaded Row", ""),
        }
    return lookup


def push_route_history() -> None:
    history = list(st.session_state.get("bluesg_route_history", []))
    snapshot = {
        "latest_optimisation": copy.deepcopy(st.session_state.get("bluesg_latest_optimisation")),
        "editor_state": copy.deepcopy(st.session_state.get("bluesg_route_editor_state")),
    }
    history.append(snapshot)
    st.session_state.bluesg_route_history = history[-10:]


def restore_last_route_history() -> bool:
    history = list(st.session_state.get("bluesg_route_history", []))
    if not history:
        return False
    snapshot = history.pop()
    st.session_state.bluesg_route_history = history
    st.session_state.bluesg_latest_optimisation = snapshot.get("latest_optimisation")
    st.session_state.bluesg_route_editor_state = snapshot.get("editor_state")
    st.session_state.bluesg_selective_reshuffle_result = None
    st.session_state.bluesg_selective_option_index = 0
    return True


def apply_sequence_proposal_to_latest(proposed_sequences: dict[str, list[str]]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    latest = st.session_state.get("bluesg_latest_optimisation")
    if not latest:
        raise RuntimeError("No optimisation result is available.")
    previous_editor_state = st.session_state.get("bluesg_route_editor_state") or {}
    locked_riders = set(previous_editor_state.get("locked_riders", set()))
    rider_df = latest["rider_df"]
    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        raise RuntimeError("; ".join(rider_errors))
    jobs_df = latest["jobs_df"]
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    settings = latest.get("optimisation_settings", {})
    route_df, summary_df, lookup_warnings = rebuild_outputs_from_sequences(
        proposed_sequences,
        riders,
        jobs_by_id,
        jobs_df=jobs_df,
        **settings,
    )
    latest["route_df"] = route_df.copy()
    latest["summary_df"] = summary_df.copy()
    latest["lookup_warnings"] = lookup_warnings
    latest["integrity_report"] = optimisation_integrity_report(route_df, jobs_df)
    st.session_state.bluesg_latest_optimisation = latest
    st.session_state.bluesg_route_editor_state = {
        "version": 1,
        "source_signature": route_editor_source_signature(route_df),
        "rider_sequences": {rider: list(jobs) for rider, jobs in proposed_sequences.items()},
        "locked_riders": locked_riders,
        "locked_job_ids": set(),
        "reshuffle_job_ids": set(),
        "eligible_receiver_riders": set(proposed_sequences) - locked_riders,
    }
    st.session_state.bluesg_selective_reshuffle_result = None
    st.session_state.bluesg_selective_option_index = 0
    return route_df, summary_df, lookup_warnings


def sequence_display_df(sequences: dict[str, list[str]], job_info: dict[str, dict[str, object]], riders: list[str]) -> pd.DataFrame:
    rows = []
    for rider in riders:
        for index, job_id in enumerate(sequences.get(rider, []), start=1):
            info = job_info.get(job_id, {})
            rows.append(
                {
                    "Rider": rider,
                    "Sequence": index,
                    "Car Plate": info.get("car_plate", job_id),
                    "Pickup": info.get("pickup", ""),
                    "Drop-off": info.get("dropoff", ""),
                    "Job ID": job_id,
                }
            )
    return pd.DataFrame(rows)


def render_route_editor(route_df: pd.DataFrame, summary_df: pd.DataFrame, result_jobs_df: pd.DataFrame, result_rider_df: pd.DataFrame) -> None:
    st.subheader("Route Reshuffle")
    editor_state = initialise_route_editor_state(route_df)
    job_info = selected_job_lookup(route_df)
    rider_names = list(editor_state["rider_sequences"].keys())

    if st.session_state.get("bluesg_route_editor_last_message"):
        st.success(st.session_state.bluesg_route_editor_last_message)
        if st.button("Undo last reshuffle", key="reshuffle_undo_after_apply"):
            st.session_state.bluesg_route_editor_last_message = ""
            if restore_last_route_history():
                st.rerun()

    summary_by_rider = summary_df.set_index("Rider") if not summary_df.empty and "Rider" in summary_df.columns else pd.DataFrame()

    st.markdown("**1. Lock Good Routes**")
    card_cols = st.columns(4)
    for index, rider in enumerate(rider_names):
        rider_routes = route_df[route_df["Rider"].astype(str) == rider]
        rider_locked = rider in editor_state["locked_riders"]
        if rider in summary_by_rider.index:
            rider_summary = summary_by_rider.loc[rider]
            adjusted_duration = float(rider_summary.get("Adjusted Route Duration Min", 0) or 0)
        else:
            adjusted_duration = float(rider_routes["Total Duration Min"].fillna(0).sum()) if "Total Duration Min" in rider_routes.columns else 0.0
        label = f"{'🔒' if rider_locked else '👤'} {rider}"
        card = card_cols[index % 4]
        if card.button(label, key=f"toggle_rider_lock_{safe_widget_id(rider)}", width="stretch"):
            if rider_locked:
                editor_state["locked_riders"].discard(rider)
            else:
                editor_state["locked_riders"].add(rider)
                for job_id in editor_state["rider_sequences"].get(rider, []):
                    editor_state["reshuffle_job_ids"].discard(job_id)
            editor_state["eligible_receiver_riders"] = set(rider_names) - set(editor_state["locked_riders"])
            st.session_state.bluesg_selective_reshuffle_result = None
            st.session_state.bluesg_route_editor_last_message = ""
            st.rerun()
        card.caption(f"{len(rider_routes)} jobs · {adjusted_duration:.0f} min")

    st.markdown("**2. Select Orders to Fix**")
    for rider in rider_names:
        rider_routes = route_df[route_df["Rider"].astype(str) == rider].sort_values("Sequence")
        rider_locked = rider in editor_state["locked_riders"]
        header = f"{'🔒 ' if rider_locked else ''}{rider}"
        with st.expander(header, expanded=bool(set(editor_state["reshuffle_job_ids"]) & set(editor_state["rider_sequences"].get(rider, [])))):
            if rider_locked:
                st.caption("Route locked. Unlock this rider above before selecting one of their orders.")
            for _, route in rider_routes.iterrows():
                job_id = stable_job_id_from_route_row(route)
                sequence = clean_text(route.get("Sequence"))
                car_plate = clean_text(route.get("Car Plate"))
                pickup = clean_text(route.get("Pickup Address"))
                dropoff = clean_text(route.get("Drop-off Address"))
                selected = job_id in editor_state["reshuffle_job_ids"]
                order_label = f"{'🔄 ' if selected else ''}{sequence}. {car_plate}"
                order_caption = f"{pickup} → {dropoff}"
                row_cols = st.columns([2, 5])
                if row_cols[0].button(
                    order_label,
                    key=f"toggle_reshuffle_order_{safe_widget_id(job_id)}",
                    disabled=rider_locked,
                    width="stretch",
                    type="primary" if selected else "secondary",
                ):
                    if selected:
                        editor_state["reshuffle_job_ids"].discard(job_id)
                    else:
                        editor_state["reshuffle_job_ids"].add(job_id)
                    editor_state["locked_job_ids"] = set()
                    st.session_state.bluesg_selective_reshuffle_result = None
                    st.session_state.bluesg_route_editor_last_message = ""
                    st.rerun()
                row_cols[1].caption(
                    f"{order_caption}" + (" · selected for reshuffle" if selected else "")
                )

    selected_pool = [
        {
            "Car Plate": job_info.get(job_id, {}).get("car_plate", job_id),
            "Current Rider": job_info.get(job_id, {}).get("rider", ""),
            "Current Sequence": job_info.get(job_id, {}).get("sequence", ""),
            "Pickup": job_info.get(job_id, {}).get("pickup", ""),
            "Drop-off": job_info.get(job_id, {}).get("dropoff", ""),
        }
        for job_id in sorted(editor_state["reshuffle_job_ids"])
    ]
    st.write(f"Selected: {len(selected_pool)} order{'s' if len(selected_pool) != 1 else ''}")
    if selected_pool:
        for item in selected_pool:
            st.caption(
                f"{item['Car Plate']} — {item['Current Rider']} · Job {item['Current Sequence']}"
            )
    else:
        st.caption("Click an order under an unlocked rider to add it here.")

    with st.expander("Advanced reshuffle scoring", expanded=False):
        score_cols = st.columns(3)
        changed_rider_penalty = score_cols[0].number_input(
            "Changed rider penalty",
            value=DEFAULT_SELECTIVE_CHANGED_RIDER_PENALTY,
            min_value=0.0,
            max_value=200.0,
            step=5.0,
        )
        moved_job_penalty = score_cols[1].number_input(
            "Moved job penalty",
            value=DEFAULT_SELECTIVE_MOVED_JOB_PENALTY,
            min_value=0.0,
            max_value=100.0,
            step=5.0,
        )
        sequence_change_penalty = score_cols[2].number_input(
            "Sequence change penalty",
            value=DEFAULT_SELECTIVE_SEQUENCE_CHANGE_PENALTY,
            min_value=0.0,
            max_value=100.0,
            step=5.0,
        )

    eligible_receivers = set(rider_names) - set(editor_state["locked_riders"])
    editor_state["eligible_receiver_riders"] = eligible_receivers
    find_clicked = st.button("🔀 Find Best Reshuffle", type="primary", disabled=not editor_state["reshuffle_job_ids"], width="stretch")
    if find_clicked:
        riders, rider_errors = validate_riders(result_rider_df)
        if rider_errors:
            st.error("; ".join(rider_errors))
        else:
            with st.spinner("Searching selected route changes..."):
                result = find_best_selective_reshuffle(
                    editor_state["rider_sequences"],
                    build_jobs_by_stable_id(result_jobs_df),
                    riders,
                    jobs_df=result_jobs_df,
                    locked_riders=set(editor_state["locked_riders"]),
                    locked_job_ids=set(),
                    reshuffle_job_ids=set(editor_state["reshuffle_job_ids"]),
                    eligible_receiver_riders=eligible_receivers,
                    changed_rider_penalty=changed_rider_penalty,
                    moved_job_penalty=moved_job_penalty,
                    sequence_change_penalty=sequence_change_penalty,
                    **st.session_state.bluesg_latest_optimisation.get("optimisation_settings", {}),
                )
            st.session_state.bluesg_selective_reshuffle_result = result
            st.session_state.bluesg_selective_option_index = 0
            st.rerun()

    result = st.session_state.get("bluesg_selective_reshuffle_result")
    if not result:
        return
    if not result.get("success"):
        st.warning(result.get("reason", "No proposal was found."))
        if result.get("search_limited"):
            st.info("Candidate search hit the safety limit before all plans were evaluated.")
        return

    alternatives = result.get("alternatives", [])
    if not alternatives:
        return
    option_index = int(st.session_state.get("bluesg_selective_option_index", 0))
    option_index = max(0, min(option_index, len(alternatives) - 1))
    option = alternatives[option_index]

    st.markdown("**3. Best Outcome**")
    affected_riders = option.get("changed_riders", []) or sorted({
        item.get("from_rider", "")
        for item in option.get("moved_jobs", [])
        if item.get("from_rider")
    } | {
        item.get("to_rider", "")
        for item in option.get("moved_jobs", [])
        if item.get("to_rider")
    })
    before_col, after_col = st.columns(2)
    with before_col:
        st.write("Before")
        for rider in affected_riders:
            st.caption(rider)
            for index, job_id in enumerate(option["original_sequences"].get(rider, []), start=1):
                info = job_info.get(job_id, {})
                st.write(f"{index}. {info.get('car_plate', job_id)}")
    with after_col:
        st.write("Best Outcome" if option_index == 0 else f"Option {option_index + 1}")
        move_notes = {item["job_id"]: item for item in option.get("moved_jobs", [])}
        for rider in affected_riders:
            st.caption(rider)
            for index, job_id in enumerate(option["proposed_sequences"].get(rider, []), start=1):
                info = job_info.get(job_id, {})
                note = move_notes.get(job_id)
                st.write(f"{index}. {info.get('car_plate', job_id)}")
                if note and note.get("from_rider") != rider:
                    st.caption(f"Moved from {note.get('from_rider')}")

    locked_changed = len(set(option.get("changed_riders", [])) & set(editor_state["locked_riders"]))
    reassigned = sum(1 for item in option.get("moved_jobs", []) if item.get("changed_rider"))
    improvement = -float(option.get("duration_delta", 0) or 0)
    metric_cols = st.columns(5)
    metric_cols[0].metric("Locked Routes Changed", locked_changed)
    metric_cols[1].metric("Problem Orders Reassigned", reassigned)
    metric_cols[2].metric("Estimated Improvement", f"{improvement:.1f} min")
    metric_cols[3].metric("Latest Before", option.get("latest_completion_before", "-"))
    metric_cols[4].metric("Latest After", option.get("latest_completion_after", "-"))

    with st.expander("Advanced result details", expanded=False):
        st.caption(
            f"Option {option_index + 1} of {len(alternatives)}. "
            f"Candidates evaluated: {option.get('candidate_count', 0):,}. "
            f"Plan score: {float(option.get('plan_score', 0)):.1f}."
        )
        if option.get("search_limited"):
            st.info("Search hit the safety limit; showing the best candidates found before stopping.")
        if len(alternatives) > 1 and st.button("Show another option", key="reshuffle_next_option"):
            st.session_state.bluesg_selective_option_index = (option_index + 1) % len(alternatives)
            st.rerun()

    action_cols = st.columns(2)
    if action_cols[0].button("✓ Apply Reshuffle", type="primary", width="stretch"):
        try:
            push_route_history()
            apply_sequence_proposal_to_latest(option["proposed_sequences"])
        except Exception as exc:
            st.error(f"Could not accept proposal: {exc}")
        else:
            st.session_state.bluesg_route_editor_last_message = "Reshuffle applied."
            st.rerun()
    if action_cols[1].button("Cancel", width="stretch"):
        st.session_state.bluesg_selective_reshuffle_result = None
        st.session_state.bluesg_selective_option_index = 0
        st.rerun()


@st.cache_data(show_spinner=False)
def cached_parse_job_upload(payload: bytes, filename: str) -> ImportResult:
    class NamedBytesIO(BytesIO):
        pass

    uploaded = NamedBytesIO(payload)
    uploaded.name = filename
    return parse_job_source(uploaded_file=uploaded)


@st.cache_data(show_spinner=False)
def cached_parse_pasted_jobs(pasted_text: str) -> ImportResult:
    return parse_job_source(pasted_text=pasted_text)


def show_import_report(report) -> None:
    labels = [
        ("Rows detected", report.rows_detected),
        ("Rows accepted", report.rows_accepted),
        ("Need correction", report.rows_requiring_correction),
        ("Rows excluded", report.rows_excluded),
        ("Duplicate rows", report.duplicate_rows),
        ("Missing locations", report.missing_location_rows),
    ]
    for column, (label, value) in zip(st.columns(6), labels):
        column.metric(label, value)


def render_job_importer() -> None:
    st.subheader("1. Upload jobs")
    upload_epoch = int(st.session_state.setdefault("bluesg_upload_epoch", 0))
    source_columns = st.columns([1, 1.4])
    uploaded = source_columns[0].file_uploader(
        "Upload Excel or CSV",
        type=["xlsx", "xls", "xlsm", "csv"],
        key=f"bluesg_jobs_upload_{upload_epoch}",
        help="Flexar workbooks with title rows and repeated lot columns remain supported.",
    )
    pasted = source_columns[1].text_area(
        "Paste Flexar data",
        height=100,
        key=f"bluesg_jobs_paste_{upload_epoch}",
        placeholder="Paste a Flexar table, tab-separated rows, CSV text, or HTML.",
    )

    source_signature = ""
    parse_source = None
    if uploaded is not None:
        payload = uploaded.getvalue()
        source_signature = hashlib.sha256(
            b"upload|" + uploaded.name.encode("utf-8", errors="replace") + b"|" + payload
        ).hexdigest()
        parse_source = lambda: cached_parse_job_upload(payload, uploaded.name)
    elif pasted.strip():
        source_signature = hashlib.sha256(
            ("paste|" + pasted.strip()).encode("utf-8")
        ).hexdigest()
        parse_source = lambda: cached_parse_pasted_jobs(pasted)

    if source_signature and source_signature != st.session_state.get("bluesg_import_source_signature"):
        try:
            parsed = parse_source()
            validation, changed = validate_and_commit_job_import(
                st.session_state,
                parsed.dataframe,
            )
        except Exception as exc:
            st.session_state.bluesg_import_error = f"Could not import jobs: {exc}"
            st.session_state.bluesg_job_validation = None
        else:
            st.session_state.imported_source_data = parsed
            st.session_state.bluesg_job_validation = validation
            st.session_state.bluesg_import_error = ""
            if validation.is_valid and changed and st.session_state.result_is_stale:
                st.session_state.bluesg_import_notice = "The previous optimisation is now stale."
            else:
                st.session_state.bluesg_import_notice = ""
        finally:
            st.session_state.bluesg_import_source_signature = source_signature

    if st.session_state.get("bluesg_import_error"):
        st.error(st.session_state.bluesg_import_error)

    validation = st.session_state.get("bluesg_job_validation")
    if validation is None:
        st.caption("Upload a file or paste Flexar data. Valid jobs are committed automatically.")
        return

    report = validation.report
    if validation.is_valid:
        committed_count = len(st.session_state.committed_jobs)
        st.success(f"{committed_count} jobs uploaded successfully")
        st.caption(
            f"{committed_count} accepted · 0 rejected · {report.duplicate_rows} duplicates"
        )
        if st.session_state.get("bluesg_import_notice"):
            st.warning(st.session_state.bluesg_import_notice)
        with st.expander("View imported jobs", expanded=False, icon=":material/table_view:"):
            st.dataframe(validation.dataframe, width="stretch", hide_index=True, height=300)
    else:
        st.error(
            f"{report.rows_requiring_correction} row(s) require correction. "
            "This source was not committed."
        )
        affected_rows = sorted(
            {row for issue in validation.errors for row in issue.rows}
        )
        for issue in validation.issues:
            row_suffix = f" Rows: {', '.join(map(str, issue.rows[:12]))}" if issue.rows else ""
            if issue.severity == "error":
                st.error(issue.message + row_suffix)
            else:
                st.warning(issue.message + row_suffix)
        if affected_rows:
            affected_index = [row - 1 for row in affected_rows if 0 < row <= len(validation.dataframe)]
            st.dataframe(
                validation.dataframe.iloc[affected_index],
                width="stretch",
                hide_index=True,
                height=min(300, 70 + 35 * len(affected_index)),
            )
        if isinstance(st.session_state.get("committed_jobs"), pd.DataFrame) and not st.session_state.committed_jobs.empty:
            st.caption("The previously committed job list remains unchanged.")

    if st.button("Replace file", icon=":material/refresh:", type="tertiary"):
        clear_import(st.session_state)
        st.session_state.bluesg_job_validation = None
        st.session_state.bluesg_import_source_signature = ""
        st.session_state.bluesg_import_error = ""
        st.session_state.bluesg_upload_epoch = upload_epoch + 1
        st.rerun()


@st.dialog("Today's riders", width="large")
def configure_riders_dialog(default_roster_day: str) -> None:
    default_index = (
        WEEKDAY_SHEETS.index(default_roster_day)
        if default_roster_day in WEEKDAY_SHEETS
        else 0
    )
    roster_day = st.selectbox(
        "Roster day",
        WEEKDAY_SHEETS,
        index=default_index,
        key="bluesg_drawer_roster_day",
    )
    source = clean_text(st.session_state.get("bluesg_roster_source")) or "Local fallback"
    st.caption(f"Roster source: {source}")
    if st.session_state.get("bluesg_roster_warning"):
        st.info(st.session_state.bluesg_roster_warning)
    if st.button("Reload daily roster", icon=":material/refresh:"):
        loaded = load_daily_v2_roster(
            roster_day,
            google_csv_url=configured_google_roster_url() or None,
        )
        st.session_state.rider_draft = normalise_riders(loaded.dataframe)
        st.session_state.bluesg_roster_source = loaded.source
        st.session_state.bluesg_roster_warning = loaded.warning
        st.rerun(scope="fragment")

    if st.session_state.get("rider_draft") is None:
        begin_rider_draft(st.session_state)
    draft = normalise_riders(st.session_state.rider_draft)
    display_draft = draft.copy()
    operation_date = pd.Timestamp.now(tz="Asia/Singapore").date()
    display_draft["Validation Status"] = [
        (
            "Inactive"
            if not bool(row.get("Active", True))
            else (
                "Valid"
                if validate_v2_roster(pd.DataFrame([row]), operation_date).is_valid
                else "Needs attention"
            )
        )
        for row in display_draft.to_dict("records")
    ]
    with st.form("bluesg_v2_rider_form", border=False):
        edited = st.data_editor(
            display_draft,
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            height=360,
            disabled=["Validation Status"],
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
                    help="Optional, for example: CCK by 4:30 PM"
                ),
                "Active": st.column_config.CheckboxColumn(),
                "Validation Status": st.column_config.TextColumn(width="small"),
                "Maximum Jobs": None,
                "Rider Load": None,
            },
        )
        action_columns = st.columns(2)
        save_clicked = action_columns[0].form_submit_button("Save riders", type="primary")
        cancel_clicked = action_columns[1].form_submit_button("Cancel")

    if cancel_clicked:
        cancel_rider_draft(st.session_state)
        st.rerun()
    if save_clicked:
        validation = validate_rider_draft(edited)
        if not validation.is_valid:
            for error in validation.errors:
                st.error(error)
        else:
            try:
                changed = save_rider_draft(st.session_state, edited)
                if clean_text(st.session_state.get("bluesg_roster_source")) != "Google Sheets":
                    save_local_v2_roster(roster_day, st.session_state.committed_riders)
            except Exception as exc:
                st.error(f"Could not save riders: {exc}")
            else:
                st.session_state.bluesg_rider_save_message = (
                    "Riders saved for this session."
                    + (" The previous optimisation is now stale." if changed and st.session_state.result_is_stale else "")
                )
                st.rerun()


def build_summary_from_route_rows(route_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if route_df is None or route_df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    working = sort_routes_for_map(route_df)
    for rider, rider_routes in working.groupby("Rider", sort=False):
        numeric = lambda column: float(
            pd.to_numeric(rider_routes.get(column), errors="coerce").fillna(0).sum()
        )
        total_duration = numeric("Total Duration Min")
        adjusted_values = pd.to_numeric(
            rider_routes.get("Projected Adjusted Duration Min"), errors="coerce"
        ).dropna()
        adjusted = (
            float(adjusted_values.iloc[-1])
            if not adjusted_values.empty
            else total_duration * DEFAULT_DURATION_BUFFER_MULTIPLIER
        )
        rows.append(
            {
                "Rider": clean_text(rider),
                "Total Jobs": len(rider_routes),
                "Total Empty Distance KM": round(numeric("Empty Distance KM"), 2),
                "Total Empty Duration Min": round(numeric("Empty Duration Min"), 1),
                "Total Loaded Distance KM": round(numeric("Loaded Distance KM"), 2),
                "Total Loaded Duration Min": round(numeric("Loaded Duration Min"), 1),
                "Total Route Distance KM": round(numeric("Total Distance KM"), 2),
                "Total Route Duration Min": round(total_duration, 1),
                "Adjusted Route Duration Min": round(adjusted, 1),
                "Within 3 Hours": "OK" if adjusted <= 180 else "Fail",
                "Final Location": clean_text(rider_routes.iloc[-1].get("Drop-off Address")),
            }
        )
    summary = pd.DataFrame(rows)
    for column in SUMMARY_COLUMNS:
        if column not in summary.columns:
            summary[column] = 0 if any(token in column for token in ("Distance", "Duration", "Count", "Jobs")) else ""
    return format_summary_output(summary[SUMMARY_COLUMNS], route_df)


def assignment_review_table(route_df: pd.DataFrame, jobs_df: pd.DataFrame) -> pd.DataFrame:
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    rows: list[dict[str, object]] = []
    for _, route in sort_routes_for_map(route_df).iterrows():
        stable_id = stable_job_id_from_route_row(route)
        job = jobs_by_id.get(stable_id, {})
        rows.append(
            {
                "Rider": clean_text(route.get("Rider")),
                "Sequence": route.get("Sequence"),
                "Car Plate": clean_text(route.get("Car Plate")),
                "Job ID": clean_text(job.get("Job ID")) or stable_id,
                "Pickup": clean_text(route.get("Pickup Address")),
                "Pickup Lot": clean_text(route.get("Pickup Lot")),
                "Drop-off": clean_text(route.get("Drop-off Address")),
                "Drop-off Lot": clean_text(job.get("Drop-off Lot")),
                "Deadline": job.get("Deadline", ""),
                "Empty Travel Min": route.get("Empty Duration Min"),
                "Loaded Travel Min": route.get("Loaded Duration Min"),
                "Pickup Zone": clean_text(job.get("Pickup Zone")),
                "Drop-off Zone": clean_text(job.get("Drop-off Zone")),
            }
        )
    return pd.DataFrame(rows)


def build_v2_archive_table(
    route_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    explanations: list[dict[str, object]],
    *,
    operation_date: str,
    completion_status: str,
    runtime_seconds: float,
    cache_hit_rate: float,
) -> pd.DataFrame:
    """Build the operations-facing daily archive without changing rider defaults."""

    explanation_df = pd.DataFrame(explanations)
    rows: list[dict[str, object]] = []
    for rider in normalise_riders(rider_df).to_dict("records"):
        rider_name = clean_text(rider.get("Rider Name"))
        rider_routes = route_df[
            route_df.get("Rider", pd.Series(index=route_df.index, dtype=str))
            .astype(str)
            .eq(rider_name)
        ].copy()
        if not rider_routes.empty:
            rider_routes["_sequence"] = pd.to_numeric(
                rider_routes.get("Sequence"), errors="coerce"
            ).fillna(0)
            last_route = rider_routes.sort_values("_sequence", kind="stable").iloc[-1]
            final_location = clean_text(last_route.get("Drop-off Address"))
        else:
            final_location = clean_text(rider.get("Start Location"))
        rider_explanations = (
            explanation_df[
                explanation_df.get(
                    "rider_name", pd.Series(index=explanation_df.index, dtype=str)
                )
                .astype(str)
                .eq(rider_name)
            ]
            if not explanation_df.empty
            else pd.DataFrame()
        )
        severities = pd.to_numeric(
            rider_explanations.get("severity", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0)
        end_arrivals = [
            value
            for value in rider_explanations.get(
                "estimated_end_arrival", pd.Series(dtype=object)
            ).tolist()
            if value not in (None, "")
        ]
        rows.append(
            {
                "Date": operation_date,
                "Rider": rider_name,
                "Start location": clean_text(rider.get("Start Location")),
                "Work Style": clean_text(rider.get("Work Style")),
                "Preferred Jobs": int(rider.get("Preferred") or 0),
                "Maximum Jobs": int(rider.get("Maximum") or 0),
                "Jobs assigned": len(rider_routes),
                "Final job location": final_location,
                "Required end destination": clean_text(rider.get("End Requirement")),
                "Estimated required-end arrival": str(end_arrivals[-1]) if end_arrivals else "",
                "Disliked assignments": int(severities.eq(2).sum()),
                "Cross-zone assignments": int(severities.eq(3).sum()),
                "Completion status": completion_status,
                "Runtime seconds": round(float(runtime_seconds), 3),
                "Cache hit rate": round(float(cache_hit_rate), 4),
            }
        )
    return pd.DataFrame(rows)


def render_operator_assignment_review(
    route_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    unassigned_jobs_df: pd.DataFrame,
) -> None:
    st.subheader("Who takes each car")
    assignment_table = assignment_review_table(route_df, jobs_df)
    rider_options = ["All riders"] + sorted(assignment_table["Rider"].dropna().unique().tolist())
    with st.container(horizontal=True, vertical_alignment="bottom"):
        rider_filter = st.selectbox(
            "Rider",
            rider_options,
            key="bluesg_v2_result_rider_filter",
            width=220,
        )
        plate_search = st.text_input(
            "Licence plate",
            key="bluesg_v2_plate_search",
            placeholder="Search LP",
            icon=":material/search:",
            width=280,
        ).strip()
    filtered = assignment_table.copy()
    if rider_filter != "All riders":
        filtered = filtered[filtered["Rider"] == rider_filter]
    if plate_search:
        filtered = filtered[
            filtered["Car Plate"].str.contains(plate_search, case=False, regex=False, na=False)
        ]
    visible = pd.DataFrame(
        {
            "Rider": filtered["Rider"].apply(clean_text),
            "Job": pd.to_numeric(filtered["Sequence"], errors="coerce").astype("Int64"),
            "Licence plate": filtered["Car Plate"].apply(clean_text),
            "Task ID": filtered["Job ID"].apply(clean_text),
            "Pickup → drop-off": filtered.apply(
                lambda row: f"{clean_text(row['Pickup'])} → {clean_text(row['Drop-off'])}",
                axis=1,
            ),
            "Deadline": filtered["Deadline"].apply(clean_text),
        }
    )
    st.caption(
        f"{len(visible)} assignment(s). Copy an LP from the Licence plate column, search it in Flexar, then assign it to the rider in the first column."
    )
    table_height = min(1100, 42 + max(1, len(visible)) * 34)
    st.dataframe(
        visible,
        width="stretch",
        height=table_height,
        row_height=32,
        hide_index=True,
        column_config={
            "Rider": st.column_config.TextColumn(pinned=True, width="small"),
            "Job": st.column_config.NumberColumn(pinned=True, width="small", format="%d"),
            "Licence plate": st.column_config.TextColumn(pinned=True, width="small"),
            "Task ID": st.column_config.TextColumn(width="small"),
            "Pickup → drop-off": st.column_config.TextColumn(width="large"),
            "Deadline": st.column_config.TextColumn(width="medium"),
        },
    )

    if unassigned_jobs_df is not None and not unassigned_jobs_df.empty:
        st.subheader("Unassigned jobs")
        st.dataframe(unassigned_jobs_df, width="stretch", hide_index=True)
    else:
        st.caption("All committed jobs are assigned.")


def render_v2_rider_cards(
    route_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    explanations: list[dict[str, object]],
) -> None:
    st.subheader("Rider routes")
    explanation_df = pd.DataFrame(explanations)
    card_columns = st.columns(2)
    active_riders = normalise_riders(rider_df)
    active_riders = active_riders[active_riders["Active"]].reset_index(drop=True)
    for index, rider in active_riders.iterrows():
        rider_name = clean_text(rider.get("Rider Name"))
        rider_routes = route_df[
            route_df.get("Rider", pd.Series(index=route_df.index, dtype=str))
            .astype(str)
            .eq(rider_name)
        ].copy()
        final_location = clean_text(rider.get("Start Location"))
        route_valid = True
        if not rider_routes.empty:
            rider_routes["_sequence"] = pd.to_numeric(
                rider_routes.get("Sequence"), errors="coerce"
            ).fillna(0)
            final_location = clean_text(
                rider_routes.sort_values("_sequence", kind="stable").iloc[-1].get(
                    "Drop-off Address"
                )
            )
            if "Route Validation Status" in rider_routes:
                route_valid = rider_routes["Route Validation Status"].astype(str).eq("OK").all()
        end_requirement = clean_text(rider.get("End Requirement"))
        estimated_arrival = ""
        if end_requirement and not explanation_df.empty and "rider_name" in explanation_df:
            rider_explanations = explanation_df[
                explanation_df["rider_name"].astype(str).eq(rider_name)
            ]
            arrivals = [
                value
                for value in rider_explanations.get(
                    "estimated_end_arrival", pd.Series(dtype=object)
                ).tolist()
                if value not in (None, "")
            ]
            if arrivals:
                try:
                    estimated_arrival = pd.Timestamp(arrivals[-1]).strftime("%-I:%M %p")
                except ValueError:
                    estimated_arrival = pd.Timestamp(arrivals[-1]).strftime("%I:%M %p").lstrip("0")
        with card_columns[index % 2].container(border=True):
            st.markdown(f"**{rider_name}**")
            st.caption(
                f"{len(rider_routes)} / {int(rider.get('Maximum') or 0)} jobs  \n"
                f"{clean_text(rider.get('Work Style'))} — {clean_text(rider.get('Start Zone'))}  \n"
                f"Final location: {final_location or 'Not assigned'}  \n"
                f"Status: {'Valid' if route_valid else 'Needs review'}"
            )
            if end_requirement:
                st.caption(
                    f"Required destination: {end_requirement}  \n"
                    f"Estimated arrival: {estimated_arrival or 'Not available'}"
                )


def build_assignment_editor_dataframe(
    route_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    rider_names: list[str],
) -> pd.DataFrame:
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    assignment = assignment_from_routes(route_df, jobs_df, rider_names)
    route_lookup = {
        stable_job_id_from_route_row(row): row
        for _, row in route_df.iterrows()
    }
    rows: list[dict[str, object]] = []
    for rider, job_ids in assignment.items():
        display_rider = "Unassigned" if rider == UNASSIGNED_LANE else rider
        for sequence, stable_id in enumerate(job_ids, start=1):
            job = jobs_by_id[stable_id]
            original = route_lookup.get(stable_id, {})
            rows.append(
                {
                    "_Stable Job Key": stable_id,
                    "Job ID": clean_text(job.get("Job ID")) or stable_id,
                    "Car Plate": clean_text(job.get("Car Plate")),
                    "Pickup": clean_text(job.get("Pickup Address")),
                    "Drop-off": clean_text(job.get("Drop-off Address")),
                    "Original Rider": clean_text(original.get("Rider")) or "Unassigned",
                    "Original Sequence": original.get("Sequence", sequence),
                    "Rider": display_rider,
                    "Sequence": sequence,
                }
            )
    return pd.DataFrame(rows)


@st.dialog("Edit Assignments", width="large")
def edit_assignments_dialog() -> None:
    latest = st.session_state.get("optimiser_result")
    if not latest:
        st.error("Run the optimiser before editing assignments.")
        return
    route_df = latest["route_df"]
    jobs_df = latest["jobs_df"]
    rider_df = latest["rider_df"]
    rider_names = rider_df["Rider Name"].apply(clean_text).tolist()
    if st.session_state.get("assignment_draft") is None:
        st.session_state.assignment_draft = build_assignment_editor_dataframe(
            route_df, jobs_df, rider_names
        )
    with st.form("bluesg_v2_assignment_form"):
        edited = st.data_editor(
            st.session_state.assignment_draft,
            hide_index=True,
            width="stretch",
            height=430,
            disabled=[
                "_Stable Job Key",
                "Job ID",
                "Car Plate",
                "Pickup",
                "Drop-off",
                "Original Rider",
                "Original Sequence",
            ],
            column_config={
                "_Stable Job Key": None,
                "Rider": st.column_config.SelectboxColumn(
                    options=[*rider_names, "Unassigned"], required=True
                ),
                "Sequence": st.column_config.NumberColumn(min_value=1, step=1, required=True),
            },
        )
        action_columns = st.columns(2)
        apply_clicked = action_columns[0].form_submit_button(
            "Apply Assignment Changes", type="primary"
        )
        cancel_clicked = action_columns[1].form_submit_button("Cancel")
    if cancel_clicked:
        st.session_state.assignment_draft = None
        st.rerun()
    if apply_clicked:
        expected = list(build_jobs_by_stable_id(jobs_df))
        validation_frame = edited[["_Stable Job Key", "Rider", "Sequence"]].rename(
            columns={"_Stable Job Key": "Job ID"}
        ).copy()
        validation_frame["Rider"] = validation_frame["Rider"].replace(
            {"Unassigned": UNASSIGNED_LANE}
        )
        validation = validate_assignment_draft(
            validation_frame,
            expected,
            [*rider_names, UNASSIGNED_LANE],
        )
        if not validation.is_valid:
            for error in validation.errors:
                st.error(error)
            return
        normalised = normalise_assignment_sequences(validation_frame)
        proposed = {
            rider: group["Job ID"].tolist()
            for rider, group in normalised.groupby("Rider", sort=False)
        }
        proposed = {rider: proposed.get(rider, []) for rider in rider_names} | {
            UNASSIGNED_LANE: proposed.get(UNASSIGNED_LANE, [])
        }
        confirmed = assignment_from_routes(route_df, jobs_df, rider_names)
        if latest.get("v2_status"):
            if proposed.get(UNASSIGNED_LANE):
                st.error(
                    "V2 manual changes must keep every committed job assigned. "
                    "Use Run Optimiser V2.0 if a complete alternative is needed."
                )
                return
            v2_roster = normalise_riders(rider_df)
            maximum_by_rider = {
                clean_text(row.get("Rider Name")): int(row.get("Maximum") or 0)
                for row in v2_roster.to_dict("records")
            }
            for rider_name, job_ids in proposed.items():
                if rider_name == UNASSIGNED_LANE:
                    continue
                if len(job_ids) > maximum_by_rider.get(rider_name, 0):
                    st.error(
                        f"{rider_name}: manual assignment has {len(job_ids)} jobs, above "
                        f"Maximum Jobs {maximum_by_rider.get(rider_name, 0)}."
                    )
                    return
            end_requirement_by_rider = {
                clean_text(row.get("Rider Name")): clean_text(row.get("End Requirement"))
                for row in v2_roster.to_dict("records")
            }
            changed_end_riders = [
                rider_name
                for rider_name, requirement in end_requirement_by_rider.items()
                if requirement
                and list(proposed.get(rider_name, []))
                != list(confirmed.get(rider_name, []))
            ]
            if changed_end_riders:
                st.error(
                    "Routes with a required end destination must be rebuilt by V2 so the final "
                    f"return journey remains a hard constraint: {', '.join(changed_end_riders)}."
                )
                return
            jobs_by_stable_id = build_jobs_by_stable_id(jobs_df)
            for rider_name, job_ids in proposed.items():
                if rider_name == UNASSIGNED_LANE:
                    continue
                for stable_id in job_ids:
                    job = jobs_by_stable_id[stable_id]
                    fixed = clean_text(job.get("Fixed Rider") or job.get("Required Rider"))
                    if fixed and fixed.casefold() != rider_name.casefold():
                        st.error(f"{clean_text(job.get('Job ID')) or stable_id} is fixed to {fixed}.")
                        return
                    excluded = {
                        part.strip().casefold()
                        for part in clean_text(
                            job.get("Excluded Riders") or job.get("Rider Exclusions")
                        ).replace(";", ",").replace("|", ",").split(",")
                        if part.strip()
                    }
                    if rider_name.casefold() in excluded:
                        st.error(
                            f"{rider_name} is explicitly excluded from "
                            f"{clean_text(job.get('Job ID')) or stable_id}."
                        )
                        return
        try:
            with st.status("Recalculating affected rider routes", expanded=True):
                result = incremental_recalculate(
                    confirmed_routes=route_df,
                    confirmed_assignment=confirmed,
                    draft_assignment=proposed,
                    rider_df=rider_df,
                    jobs_df=jobs_df,
                    settings=latest.get("optimisation_settings", {}),
                    summary_builder=build_summary_from_route_rows,
                )
        except Exception as exc:
            st.error(f"No changes were committed: {exc}")
            return
        operation_context = latest.get("optimisation_settings", {}).get("operation_context")
        if latest.get("v2_status") and operation_context is not None:
            completion = pd.to_datetime(
                result.route_df.get("Final Completion ETA"), errors="coerce", utc=True
            )
            operation_end = pd.Timestamp(operation_context.operation_end).tz_convert("UTC")
            if completion.notna().any() and completion.gt(operation_end).any():
                st.error(
                    "No changes were committed: the manual route would finish after the "
                    "operation window."
                )
                return
        st.session_state.setdefault("v2_assignment_undo", []).append(copy.deepcopy(latest))
        st.session_state.v2_assignment_undo = st.session_state.v2_assignment_undo[-10:]
        updated = copy.deepcopy(latest)
        updated["route_df"] = result.route_df.copy()
        updated["summary_df"] = result.summary_df.copy()
        updated["lookup_warnings"] = sorted(set([*updated.get("lookup_warnings", []), *result.warnings]))
        updated["integrity_report"] = optimisation_integrity_report(result.route_df, jobs_df)
        updated["run_result"] = None
        if updated.get("v2_status"):
            updated["v2_status"] = "COMPLETE_WITH_EXCEPTIONS"
            updated["v2_objective"] = []
            updated["v2_explanations"] = []
            updated["lookup_warnings"] = sorted(
                set(
                    [
                        *updated.get("lookup_warnings", []),
                        "Manual reassignment applied; rerun V2 for a fresh global objective and explanations.",
                    ]
                )
            )
        st.session_state.setdefault("original_optimiser_result", copy.deepcopy(latest))
        commit_optimiser_result(
            st.session_state,
            updated,
            jobs=st.session_state.committed_jobs,
            riders=st.session_state.committed_riders,
        )
        st.session_state.bluesg_latest_optimisation = updated
        st.session_state.assignment_draft = None
        st.session_state.bluesg_assignment_message = (
            f"Assignment changes applied atomically; recalculated {len(result.affected_riders)} rider(s)."
        )
        st.rerun()


selected_job_date = pd.Timestamp.now(tz="Asia/Singapore").date()
input_filename = ""
input_sha256 = ""
validation_warnings: list[str] = []
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
    "fallback_penalty": DEFAULT_FALLBACK_PENALTY,
}

today_name = pd.Timestamp.now(tz="Asia/Singapore").day_name()
if "committed_riders" not in st.session_state:
    initial_roster_load = load_daily_v2_roster(
        today_name,
        google_csv_url=configured_google_roster_url() or None,
    )
    initial_riders = initial_roster_load.dataframe
    st.session_state.bluesg_roster_source = initial_roster_load.source
    st.session_state.bluesg_roster_warning = initial_roster_load.warning
else:
    initial_riders = st.session_state.committed_riders
initialise_workflow_state(st.session_state, initial_riders)
refresh_stale_flag(st.session_state)

header_columns = st.columns([5, 1.25], vertical_alignment="center")
header_columns[0].title("Vehicle Route Optimiser — Version 2.0")
if header_columns[1].button(
    "Today's riders",
    icon=":material/menu:",
    width="stretch",
):
    begin_rider_draft(st.session_state)
    configure_riders_dialog(today_name)

active_count = int(normalise_riders(st.session_state.committed_riders)["Active"].sum())
st.caption(
    f"{active_count} active rider{'s' if active_count != 1 else ''} · "
    f"{clean_text(st.session_state.get('bluesg_roster_source')) or 'Local fallback'} roster"
)
if st.session_state.get("bluesg_rider_save_message"):
    st.success(st.session_state.pop("bluesg_rider_save_message"))

with st.expander("How the route optimiser works", expanded=False):
    st.write(
        "Every valid job is mandatory whenever a hard-feasible plan exists. Version 2 checks "
        "rider maximums, the operating window, availability and end-location deadlines first, "
        "then minimises serious geographic exceptions, cross-zone work, disliked work, preferred "
        "capacity overage, rider burden and travel. Area Leads retain first claim on local jobs "
        "when their travel advantage is at least 12 minutes."
    )

render_job_importer()

jobs_df = st.session_state.committed_jobs.copy(deep=True)
rider_df = riders_for_optimizer(st.session_state.committed_riders)
file_is_valid = not jobs_df.empty and validate_staged_jobs(jobs_df).is_valid
source_result = st.session_state.get("imported_source_data")
if source_result is not None:
    input_filename = clean_text(source_result.metadata.get("filename")) or f"{source_result.source_type}-jobs"
input_sha256 = hashlib.sha256(
    jobs_df.astype("string").fillna("").to_csv(index=False).encode("utf-8")
).hexdigest()
date_values = None
for date_column in ("Date", "Created At"):
    if date_column in jobs_df.columns:
        candidate = pd.to_datetime(jobs_df[date_column], errors="coerce")
        if candidate.notna().any():
            date_values = candidate
            break
if date_values is not None:
    selected_job_date = date_values.dropna().max().date()

if st.session_state.result_is_stale:
    st.warning(
        "The committed jobs or riders changed. The displayed optimisation is stale; run it again before dispatch or export."
    )

action_col = st.container()
review_col = st.container()

with action_col:
    st.subheader("2. Run optimiser")
    optimise_by = "duration"
    use_onemap = True
    onemap_token = ""
    operation_date = selected_job_date
    operation_start_time = clock_time(14, 0)
    operation_end_time = clock_time(17, 0)
    empty_travel_mode_label = next(iter(EMPTY_TRAVEL_MODES))
    operation_context = OperationContext.for_window(
        operation_date,
        operation_start_time,
        operation_end_time,
        empty_travel_mode=EMPTY_TRAVEL_MODES[empty_travel_mode_label],
    )
    roster_preview_errors: list[str] = []
    try:
        preview_riders = riders_for_v2(st.session_state.committed_riders, operation_date)
    except ValueError as exc:
        preview_riders = []
        roster_preview_errors = [part.strip() for part in str(exc).split(";") if part.strip()]
    preview_capacity = capacity_summary(len(jobs_df), preview_riders)
    with st.container(border=True):
        st.markdown(
            f"**{len(jobs_df)} committed jobs · {active_count} active riders**  \n"
            "Operating window: 2:00 PM–5:00 PM  \n"
            f"Travel mode: {empty_travel_mode_label}"
        )

        capacity_cols = st.columns(4)
        capacity_cols[0].metric("Jobs", preview_capacity.job_count)
        capacity_cols[1].metric("Preferred capacity", preview_capacity.preferred_capacity)
        capacity_cols[2].metric("Maximum capacity", preview_capacity.maximum_capacity)
        capacity_cols[3].metric(
            "Average required",
            f"{preview_capacity.required_average:.2f}" if preview_riders else "—",
        )
        for error in roster_preview_errors:
            st.error(error)
        if jobs_df.shape[0] and not preview_capacity.feasible_by_job_count:
            st.error(
                f"INFEASIBLE — {preview_capacity.job_count} jobs must be completed, but the "
                f"current riders can perform at most {preview_capacity.maximum_capacity}. "
                f"Capacity shortfall: {preview_capacity.shortfall} jobs."
            )
        available_rider_minutes = max(0.0, operation_context.window_duration_min) * len(preview_riders)
        if jobs_df.shape[0] and len(jobs_df) * 35 > available_rider_minutes:
            st.warning(
                "The coarse time-capacity estimate is tight. V2 will use the complete travel "
                "matrix to determine whether a physically feasible plan exists."
            )

        ready_to_optimise = (
            file_is_valid
            and active_count > 0
            and not roster_preview_errors
            and preview_capacity.feasible_by_job_count
        )
        if not file_is_valid:
            st.warning("Upload at least one valid job before running the optimiser.")
        elif active_count <= 0:
            st.warning("Activate at least one rider in Today's riders before running the optimiser.")
        optimise_clicked = st.button(
            "Run Optimiser V2.0",
            type="primary",
            icon=":material/play_arrow:",
            disabled=not ready_to_optimise,
        )
        optimise_new_route_clicked = False
        if optimise_clicked:
            st.session_state.bluesg_route_variant_index = 0
        route_variant_index = 0

    with st.expander("Advanced settings", expanded=False, icon=":material/tune:"):
        st.caption("Travel times use OneMap where available and fallback estimates when needed.")
        st.write("Fallback travel cost table")
        st.dataframe(cached_cost_explanation(), width="stretch", hide_index=True, height=180)

        st.markdown("**Duty time and hard constraints**")
        handling_cols = st.columns(3)
        pickup_handling_min = handling_cols[0].number_input("Pickup handling min", min_value=0.0, max_value=30.0, value=3.0, step=0.5)
        dropoff_handling_min = handling_cols[1].number_input("Drop-off handling min", min_value=0.0, max_value=30.0, value=3.0, step=0.5)
        unlock_wait_min = handling_cols[2].number_input("Unlock wait min/job", min_value=0.0, max_value=30.0, value=0.0, step=0.5)
        operational_buffer_pct = st.number_input("Operational buffer %", min_value=0.0, max_value=100.0, value=20.0, step=5.0)
        hard_max_jobs_enabled = st.checkbox(
            "Enforce each rider's Max Jobs as a hard cap",
            value=False,
            help="Off by default: Max Jobs remains a soft preference.",
        )
        hard_duty_enabled = st.checkbox("Enforce maximum total duty time", value=True)
        hard_max_duty_min = st.number_input(
            "Maximum total duty min",
            min_value=30.0,
            max_value=720.0,
            value=float(operation_context.window_duration_min),
            step=15.0,
            disabled=not hard_duty_enabled,
        )

        st.markdown("**Capacity-aware regional overflow**")
        enable_regional_overflow = st.checkbox(
            "Protect scarce-region riders and enable approved overflow support",
            value=True,
            help="Uses current route position, regional demand/capacity and soft support penalties. It never blocks coverage.",
        )
        regional_cols = st.columns(3)
        support_tolerance_min = regional_cols[0].number_input(
            "Support tolerance min", min_value=0.0, max_value=120.0, value=15.0, step=5.0,
            disabled=not enable_regional_overflow,
        )
        protected_job_advantage_min = regional_cols[1].number_input(
            "Protected-job advantage min", min_value=0.0, max_value=120.0, value=15.0, step=5.0,
            disabled=not enable_regional_overflow,
        )
        unsupported_region_penalty = regional_cols[2].number_input(
            "Unsupported-region penalty", min_value=0.0, max_value=500.0, value=180.0, step=10.0,
            disabled=not enable_regional_overflow,
        )
        regional_overflow_config = {
            "enabled": enable_regional_overflow,
            "support_tolerance_min": support_tolerance_min,
            "support_tolerance_ratio": 1.25,
            "protected_job_advantage_min": protected_job_advantage_min,
            "approved_support_penalty": 5.0,
            "unsupported_region_penalty": unsupported_region_penalty,
            "clustered_trip_penalty": 0.0,
            "clustered_trip_min_jobs": 3,
            "scarce_driver_small_escape_penalty": 40.0,
            "scarce_driver_large_escape_penalty": 180.0,
        }

        st.markdown("**Bounded local improvement**")
        enable_local_improvement = st.checkbox(
            "Evaluate local improvement after the complete baseline",
            value=False,
            help="The stable greedy baseline remains the default until benchmark promotion criteria pass.",
        )
        local_cols = st.columns(2)
        local_time_limit_seconds = int(local_cols[0].number_input("Local-search seconds", min_value=1, max_value=120, value=30, step=1))
        local_max_iterations = int(local_cols[1].number_input("Local-search iterations", min_value=1, max_value=500, value=100, step=10))
        experimental_cluster_first = st.checkbox(
            "Experimental cluster-first flag",
            value=False,
            help="Disabled by default. Production assignment remains state-aware and job-by-job.",
        )

        st.markdown("**Public Transport Empty Leg**")
        pt_col_a, pt_col_b = st.columns(2)
        with pt_col_a:
            empty_travel_duration_multiplier = st.number_input(
                "Empty duration multiplier",
                value=scoring_defaults["empty_travel_duration_multiplier"],
                min_value=1.0,
                max_value=3.0,
                step=0.1,
                key="bluesg_empty_travel_duration_multiplier",
            )
        with pt_col_b:
            empty_travel_wait_buffer_min = st.number_input(
                "Wait/walk buffer min",
                value=scoring_defaults["empty_travel_wait_buffer_min"],
                min_value=0.0,
                max_value=30.0,
                step=1.0,
                key="bluesg_empty_travel_wait_buffer_min",
            )

        st.markdown("**Assignment Scoring**")
        force_complete_assignment = st.checkbox(
            "Force complete assignment where possible",
            value=True,
            help="If enabled, the optimiser retries unassigned jobs in different route positions, but never exceeds the max adjusted minutes cap.",
        )

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
        workload_col_a, workload_col_b = st.columns(2)
        with workload_col_a:
            soft_workload_min = st.number_input(
                "Soft workload min",
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
        duration_col_a, duration_col_b = st.columns(2)
        with duration_col_a:
            soft_adjusted_duration_min = st.number_input(
                "Soft adjusted min",
                value=scoring_defaults["soft_adjusted_duration_min"],
                min_value=60.0,
                max_value=240.0,
                step=5.0,
                key="bluesg_soft_adjusted_duration_min",
            )
        with duration_col_b:
            duration_penalty_per_min = st.number_input(
                "Duration penalty/min",
                value=scoring_defaults["duration_penalty_per_min"],
                min_value=0.0,
                max_value=15.0,
                step=0.5,
                key="bluesg_duration_penalty_per_min",
            )
        cap_col_a, cap_col_b = st.columns(2)
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
            max_value=100.0,
            step=5.0,
            key="bluesg_cluster_pressure_bonus_per_job",
        )
        fallback_penalty = st.number_input(
            "Fallback quality penalty",
            value=scoring_defaults["fallback_penalty"],
            min_value=0.0,
            max_value=1000.0,
            step=25.0,
            key="bluesg_fallback_penalty",
            help="Affects assignment quality only; reported travel minutes remain unchanged.",
        )

    operation_context = OperationContext.for_window(
        operation_date,
        operation_start_time,
        operation_end_time,
        empty_travel_mode=EMPTY_TRAVEL_MODES[empty_travel_mode_label],
        pickup_handling_min=pickup_handling_min,
        dropoff_handling_min=dropoff_handling_min,
        unlock_wait_min=unlock_wait_min,
        default_operational_buffer_pct=operational_buffer_pct / 100.0,
    )

if optimise_clicked or optimise_new_route_clicked:
    rider_source = (
        normalise_riders(st.session_state.committed_riders)
        if OPTIMISER_VERSION == "v2"
        else rider_df
    )
    rider_df_for_optimise, duplicate_rider_rows_removed = dedupe_rider_roster(rider_source)
    if duplicate_rider_rows_removed:
        st.warning(f"Duplicate rider rows removed before optimisation: {duplicate_rider_rows_removed}")
    if OPTIMISER_VERSION == "v2":
        try:
            riders = riders_for_v2(rider_df_for_optimise, operation_date)
            rider_errors = []
        except ValueError as exc:
            riders = []
            rider_errors = [part.strip() for part in str(exc).split(";") if part.strip()]
    else:
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
            st.markdown("**Building the routes**")
            metric_cols = st.columns(5)
            phase_metric = metric_cols[0].empty()
            assigned_metric = metric_cols[1].empty()
            remaining_metric = metric_cols[2].empty()
            elapsed_metric = metric_cols[3].empty()
            checks_metric = metric_cols[4].empty()
            progress_bar = st.progress(0, text="Getting ready...")
            activity_text = st.empty()
            detail_text = st.empty()
            st.caption(
                "Live progress in plain English. Newest update appears first. "
                "Saved locations are summarised to keep this readable."
            )
            terminal_output = st.empty()
        started_at = time.monotonic()
        last_progress_event: dict = {}
        terminal_entries = ["[   0.0s] Getting everything ready..."]
        terminal_state = {"last_signature": None}

        def render_terminal() -> None:
            terminal_output.code(
                "\n\n".join(reversed(terminal_entries)),
                language=None,
                wrap_lines=True,
                height=560,
            )

        render_terminal()

        def simple_area_name(region: str) -> str:
            area = region.replace("_core", "").replace("_", " ").strip()
            return area.title() if area else "this area"

        def simple_routing_reason(reason: str, load_level: str, region: str) -> str:
            reason_lower = reason.casefold()
            area = simple_area_name(region)
            if load_level.casefold() == "priority" or "priority rider" in reason_lower:
                return f"They are the Priority driver for {area}."
            if "primary" in reason_lower:
                return f"They normally cover {area}."
            if "support" in reason_lower:
                return f"They are helping a nearby area because its usual drivers need support."
            if "cluster" in reason_lower:
                return "This keeps nearby jobs together and reduces extra travel."
            return "This driver was the best available match."

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

            car_plate = clean_text(event.get("current_car_plate"))
            rider_name = clean_text(event.get("current_rider"))
            pickup = clean_text(event.get("current_pickup"))
            dropoff = clean_text(event.get("current_dropoff"))
            address = clean_text(event.get("current_address"))
            event_type = clean_text(event.get("event_type"))
            region = clean_text(event.get("current_region"))
            assignment_reason = clean_text(event.get("assignment_reason"))
            rider_load_level = clean_text(event.get("rider_load_level"))
            driver_order_number = int(event.get("driver_order_number", 0) or 0)
            driver_total_orders = int(event.get("driver_total_orders", 0) or 0)
            driver_orders_before_this = int(
                event.get("driver_orders_before_this", 0) or 0
            )
            driver_location_before_order = clean_text(
                event.get("driver_location_before_order")
            )
            driver_location_source = clean_text(event.get("driver_location_source"))
            simple_reason = simple_routing_reason(
                assignment_reason, rider_load_level, region
            )
            show_terminal_entry = True
            if event_type == "v2_capacity":
                terminal_message = "\n".join(
                    [
                        "Checking rider capacity",
                        status,
                        f"Jobs waiting: {remaining_jobs}",
                    ]
                )
            elif event_type == "v2_matrix":
                matrix_completed = int(event.get("matrix_completed", 0) or 0)
                matrix_total = int(event.get("matrix_total", 0) or 0)
                terminal_message = "\n".join(
                    [
                        f"Loading travel routes ({matrix_completed:,} of {matrix_total:,})",
                        f"Saved-route hits: {int(event.get('cache_hits', 0) or 0):,}",
                        f"New OneMap requests: {int(event.get('onemap_requests', 0) or 0):,}",
                        f"Fallback estimates: {int(event.get('fallback_routes', 0) or 0):,}",
                    ]
                )
            elif event_type == "v2_search":
                retained_plans = int(event.get("retained_plans", 0) or 0)
                terminal_message = "\n".join(
                    [
                        f"Building complete plans ({assigned_jobs} of {total_jobs} jobs placed)",
                        f"Candidate routes checked: {comparison_count:,}",
                        f"Best plans still retained: {retained_plans:,}",
                        f"Jobs still left: {remaining_jobs}",
                        f"Current car: {car_plate or 'Preparing next job'}",
                    ]
                )
            elif event_type == "v2_finished":
                terminal_message = "\n".join(
                    [
                        status,
                        f"Jobs assigned: {assigned_jobs} of {total_jobs}",
                        f"Candidate routes checked: {comparison_count:,}",
                    ]
                )
            elif event_type in {"assignment", "final_assignment"}:
                first_line = (
                    "Final route confirmed"
                    if event_type == "final_assignment"
                    else "Planning this route"
                )
                terminal_message = "\n".join(
                    [
                        f"{first_line} ({assigned_jobs} of {total_jobs})",
                        f"Driver: {rider_name or 'Not selected yet'}",
                        f"Car: {car_plate or 'No plate provided'}",
                        (
                            "Driver's route order: "
                            f"{driver_order_number} of {driver_total_orders}"
                            if driver_order_number
                            else "Driver's route order: Not available"
                        ),
                        f"Orders before this: {driver_orders_before_this}",
                        (
                            "Driver starts this order from: "
                            f"{driver_location_before_order or 'Unknown location'}"
                        ),
                        f"Starting point type: {driver_location_source or 'Unknown'}",
                        f"Pick up from: {pickup or 'Unknown location'}",
                        f"Drop off at: {dropoff or 'Unknown location'}",
                        f"Why this driver: {simple_reason}",
                        f"Jobs still left: {remaining_jobs}",
                    ]
                )
            elif event_type == "geocode" or address:
                geocode_completed = int(event.get("geocode_completed", 0) or 0)
                geocode_unique = int(event.get("geocode_unique_count", 0) or 0)
                geocode_remaining = int(event.get("geocode_remaining", 0) or 0)
                geocode_source = clean_text(event.get("geocode_source")) or "unknown"
                if "cache" in geocode_source.casefold():
                    # Do not print one block for every cache hit. A summary every
                    # ten locations is enough to show that work is progressing.
                    show_terminal_entry = (
                        geocode_completed == 1
                        or geocode_completed == geocode_unique
                        or geocode_completed % 10 == 0
                    )
                    location_action = "Reading locations already saved"
                elif "fallback" in geocode_source.casefold():
                    location_action = "Could not confirm this location yet"
                else:
                    location_action = "Writing new location into memory"
                location_lines = [location_action]
                if "cache" not in geocode_source.casefold():
                    location_lines.append(f"Location: {address}")
                location_lines.extend(
                    [
                        f"Locations ready: {geocode_completed} of {geocode_unique}",
                        f"Locations still left: {geocode_remaining}",
                    ]
                )
                terminal_message = "\n".join(location_lines)
            elif rider_name or pickup:
                show_terminal_entry = (
                    comparison_count <= 1 or comparison_count % 100 == 0
                )
                terminal_message = "\n".join(
                    [
                        "Looking for the best driver",
                        f"Routes checked: {comparison_count:,} of about {estimated_comparisons:,}",
                        f"Jobs still left: {remaining_jobs}",
                    ]
                )
            else:
                simple_phase_status = {
                    "Geocoding": "Saving locations into memory...",
                    "Comparing": "Checking who should receive each job...",
                    "Routing": "Checking possible routes...",
                    "Assigning": "Giving jobs to drivers...",
                    "Finalising": "Confirming the final routes...",
                    "Finished": "All routes are ready.",
                    "Fallback": "Estimating travel times...",
                }.get(phase, "Working on the routes...")
                terminal_message = simple_phase_status

            signature = (
                event_type, phase, status, car_plate, rider_name, pickup, dropoff,
                address, assignment_reason, driver_order_number,
                driver_location_before_order, event.get("geocode_completed"),
                event.get("matrix_completed"), assigned_jobs,
                event.get("retained_plans"), event.get("result_status"),
            )
            if show_terminal_entry and signature != terminal_state["last_signature"]:
                terminal_state["last_signature"] = signature
                message_lines = terminal_message.splitlines()
                terminal_entry = f"[{elapsed:6.1f}s] {message_lines[0]}"
                if len(message_lines) > 1:
                    terminal_entry += "\n" + "\n".join(
                        f"          {line}" for line in message_lines[1:]
                    )
                terminal_entries.append(terminal_entry)
                del terminal_entries[:-40]
                render_terminal()

            phase_name = {
                "Geocoding": "Saving locations",
                "Comparing": "Choosing drivers",
                "Routing": "Checking routes",
                "Assigning": "Building routes",
                "Finalising": "Confirming routes",
                "Finished": "Done",
                "Fallback": "Estimating travel",
                "Capacity check": "Checking capacity",
                "Travel matrix": "Loading travel",
                "Plan search": "Building complete plans",
            }.get(phase, "Working")
            phase_metric.metric("What is happening", phase_name)
            assigned_metric.metric("Jobs given", f"{assigned_jobs}/{total_jobs}")
            remaining_metric.metric("Jobs left", remaining_jobs)
            elapsed_metric.metric("Time used", f"{elapsed:,.1f}s")
            checks_metric.metric(
                "Routes checked",
                (
                    f"{comparison_count:,}/{estimated_comparisons:,}"
                    if estimated_comparisons
                    else f"{comparison_count:,}"
                ),
            )
            progress_bar.progress(
                progress_value,
                text=f"{phase_name} ({progress_value * 100:.0f}% done)",
            )
            activity_text.info(terminal_message.splitlines()[0])

            detail_parts = []
            if event.get("current_address"):
                detail_parts.append(("Address", event["current_address"]))
            if event.get("current_rider"):
                detail_parts.append(("Rider", event["current_rider"]))
            if driver_order_number:
                detail_parts.append(
                    (
                        "Driver's route order",
                        f"{driver_order_number} of {driver_total_orders}",
                    )
                )
                detail_parts.append(("Orders before this", driver_orders_before_this))
            if driver_location_before_order:
                detail_parts.append(
                    ("Driver starts this order from", driver_location_before_order)
                )
            if driver_location_source:
                detail_parts.append(("Starting point type", driver_location_source))
            if event.get("current_pickup"):
                detail_parts.append(("Pickup", event["current_pickup"]))
            if event.get("current_dropoff"):
                detail_parts.append(("Drop-off", event["current_dropoff"]))
            if event.get("current_origin"):
                detail_parts.append(("Travel from", event["current_origin"]))
            if event.get("current_destination"):
                detail_parts.append(("Travel to", event["current_destination"]))
            if event.get("retained_plans") is not None:
                detail_parts.append(("Best plans retained", event["retained_plans"]))
            if event.get("current_region"):
                detail_parts.append(("Area", event["current_region"]))
            if event.get("rider_load_level"):
                detail_parts.append(("Rider mode", event["rider_load_level"]))
            if event.get("assignment_reason"):
                detail_parts.append(("Why this driver", simple_reason))

            if detail_parts:
                detail_text.dataframe(
                    streamlit_key_value_table(detail_parts),
                    width="stretch",
                    hide_index=True,
                )
            else:
                detail_text.caption("Getting locations and routes ready...")

        hard_constraints: list[Constraint] = []
        if hard_max_jobs_enabled:
            hard_constraints.append(
                Constraint(
                    "hard_max_jobs",
                    {"rider_caps": {rider.name: rider.max_jobs for rider in riders if rider.max_jobs is not None}},
                    constraint_id="ui_hard_max_jobs",
                )
            )
        if hard_duty_enabled:
            hard_constraints.append(
                Constraint(
                    "max_total_duty_time",
                    {"minutes": hard_max_duty_min},
                    constraint_id="ui_max_total_duty",
                )
            )
        canonical_settings = {
            "jobs_uploaded": int(jobs_df.attrs.get("uploaded_count", len(jobs_df))),
            "use_onemap": use_onemap,
            "onemap_token_configured": bool(onemap_token),
            "optimise_by": optimise_by,
            "empty_weight": empty_weight,
            "loaded_weight": loaded_weight,
            "soft_workload_min": soft_workload_min,
            "workload_penalty_per_min": workload_penalty_per_min,
            "soft_adjusted_duration_min": soft_adjusted_duration_min,
            "duration_penalty_per_min": duration_penalty_per_min,
            "max_job_overage_penalty": max_job_overage_penalty,
            "duration_buffer_multiplier": duration_buffer_multiplier,
            "max_adjusted_duration_min": max_adjusted_duration_min,
            "max_total_duty_time_min": hard_max_duty_min if hard_duty_enabled else None,
            "empty_travel_duration_multiplier": empty_travel_duration_multiplier,
            "empty_travel_wait_buffer_min": empty_travel_wait_buffer_min,
            "fallback_penalty": fallback_penalty,
            "force_complete_assignment": force_complete_assignment,
            "cluster_pressure_bonus_per_job": cluster_pressure_bonus_per_job,
            "experimental_cluster_first": experimental_cluster_first,
            "local_improvement_enabled": enable_local_improvement,
            "local_search_time_limit_seconds": local_time_limit_seconds,
            "local_search_max_iterations": local_max_iterations,
            "constraints": [constraint.to_dict() for constraint in hard_constraints],
            "regional_overflow_config": regional_overflow_config,
        }

        v2_result: V2OptimisationResult | None = None
        baseline_run_result = None
        move_audit: list[dict] = []
        try:
            if OPTIMISER_VERSION == "v2":
                activity_text.info("Precomputing the travel matrix, then searching complete plans...")
                v2_result = run_optimiser_v2(
                    jobs_df,
                    riders,
                    operation_context=operation_context,
                    use_onemap=use_onemap,
                    token=onemap_token or None,
                    beam_width=120,
                    time_limit_seconds=45.0,
                    empty_duration_multiplier=empty_travel_duration_multiplier,
                    empty_wait_buffer_min=empty_travel_wait_buffer_min,
                    progress_callback=show_progress,
                )
                route_df = v2_result.route_df
                summary_df = v2_result.summary_df
                lookup_warnings = []
                for warning_column in (
                    "Travel Warning",
                    "Empty Travel Warning",
                    "Loaded Travel Warning",
                ):
                    if warning_column in route_df:
                        lookup_warnings.extend(
                            clean_text(value)
                            for value in route_df[warning_column].tolist()
                            if clean_text(value)
                        )
                lookup_warnings = sorted(set(lookup_warnings))
                canonical_settings.update(
                    {
                        "optimiser_version": OPTIMISER_VERSION,
                        "v2_status": v2_result.status,
                        "v2_objective": list(v2_result.objective),
                        "v2_capacity": sanitize_for_output(v2_result.capacity.__dict__),
                        "v2_cache_metrics": sanitize_for_output(v2_result.cache_metrics),
                    }
                )
            else:
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
                    route_variant_index=route_variant_index,
                    fallback_penalty=fallback_penalty,
                    operation_context=operation_context,
                    constraints=hard_constraints,
                    experimental_cluster_first=experimental_cluster_first,
                    max_total_duty_time_min=hard_max_duty_min if hard_duty_enabled else None,
                    regional_overflow_config=regional_overflow_config,
                )
            integrity_report = optimisation_integrity_report(route_df, jobs_df)
            if not integrity_report["is_valid"] and not (
                v2_result is not None and v2_result.status == "INFEASIBLE"
            ):
                st.error(integrity_report["message"])
                if integrity_report["duplicate_details"]:
                    st.dataframe(pd.DataFrame(integrity_report["duplicate_details"]), width="stretch", hide_index=True)
                st.stop()
            baseline_route_df = route_df.copy()
            baseline_summary_df = summary_df.copy()
            baseline_integrity = {key: value for key, value in integrity_report.items() if key != "unassigned_df"}
            baseline_integrity.update(route_df.attrs.get("hard_constraint_validation", {}))
            if not route_df.empty:
                baseline_run_result = create_run_result(
                    route_df=baseline_route_df,
                    unassigned_df=integrity_report["unassigned_df"],
                    riders=riders,
                    context=operation_context,
                    settings={**canonical_settings, "wall_clock_seconds": time.monotonic() - started_at},
                    input_filename=input_filename,
                    input_sha256=input_sha256,
                    selected_job_date=str(selected_job_date),
                    warnings=[
                        {"severity": "manual_review" if "fallback" in warning.casefold() or "low-confidence" in warning.casefold() else "warning", "message": warning}
                        for warning in lookup_warnings
                    ],
                    validation=baseline_integrity,
                    algorithm_name=v2_result.algorithm_name if v2_result else "state_aware_greedy_insertion",
                    algorithm_version=v2_result.algorithm_version if v2_result else "1.0.0-v1",
                )
            if OPTIMISER_VERSION != "v2" and enable_local_improvement and integrity_report["unassigned_jobs"] == 0:
                route_df, summary_df, improvement_warnings, move_audit = improve_route_dataframe(
                    baseline_route_df,
                    jobs_df,
                    riders,
                    operation_context,
                    {**canonical_settings, "token": onemap_token or None},
                    hard_constraints,
                    time_limit_seconds=local_time_limit_seconds,
                    max_iterations=local_max_iterations,
                )
                lookup_warnings = sorted(set([*lookup_warnings, *improvement_warnings]))
                integrity_report = optimisation_integrity_report(route_df, jobs_df)
                if not integrity_report["is_valid"] or integrity_report["assigned_unique_jobs"] < baseline_integrity["assigned_unique_jobs"]:
                    route_df, summary_df = baseline_route_df, baseline_summary_df
                    move_audit.append(
                        {"move_id": "safety_revert", "move_type": "safety_revert", "accepted": False, "rejection_reason": "Improved result failed coverage/integrity safety checks; baseline retained."}
                    )
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        finally:
            progress_bar.progress(1.0, text="Finished optimisation.")
            activity_text.success("Finished optimisation.")
        elapsed_total = time.monotonic() - started_at
        if route_df.empty:
            st.session_state.bluesg_latest_optimisation = None
            st.session_state.optimiser_result = None
            st.session_state.result_is_stale = False
            if v2_result is not None and v2_result.status == "INFEASIBLE":
                st.error("INFEASIBLE — no complete plan satisfies all hard constraints.")
                capacity = v2_result.capacity
                st.write(
                    f"Capacity check: {capacity.job_count} jobs, "
                    f"{capacity.preferred_capacity} preferred slots and "
                    f"{capacity.maximum_capacity} maximum slots."
                )
                for reason in v2_result.infeasible_reasons:
                    st.error(reason)
            else:
                st.warning("No jobs could be assigned. Check rider roster and input data.")
        else:
            integrity_json = {key: value for key, value in integrity_report.items() if key != "unassigned_df"}
            integrity_json.update(route_df.attrs.get("hard_constraint_validation", {}))
            run_result = create_run_result(
                route_df=route_df,
                unassigned_df=integrity_report["unassigned_df"],
                riders=riders,
                context=operation_context,
                settings={
                    **canonical_settings,
                    "wall_clock_seconds": elapsed_total,
                    "baseline_summary": baseline_run_result.summary if baseline_run_result else {},
                },
                input_filename=input_filename,
                input_sha256=input_sha256,
                selected_job_date=str(selected_job_date),
                warnings=[
                    {"severity": "manual_review" if "fallback" in warning.casefold() or "low-confidence" in warning.casefold() else "warning", "message": warning}
                    for warning in lookup_warnings
                ],
                move_audit=move_audit,
                validation=integrity_json,
                algorithm_name=(
                    v2_result.algorithm_name
                    if v2_result is not None
                    else (
                        "state_aware_greedy_insertion+bounded_local_improvement"
                        if any(move.get("accepted") for move in move_audit)
                        else "state_aware_greedy_insertion"
                    )
                ),
                algorithm_version=(
                    v2_result.algorithm_version if v2_result is not None else "1.0.0-v1"
                ),
            )
            run_artifact_path = save_run_artifact(run_result)
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
                "route_variant_index": route_variant_index,
                "run_result": run_result,
                "baseline_summary": (
                    baseline_run_result.summary
                    if baseline_run_result is not None and v2_result is None
                    else {}
                ),
                "move_audit": move_audit,
                "run_artifact_path": str(run_artifact_path),
                "v2_status": v2_result.status if v2_result else "",
                "v2_objective": list(v2_result.objective) if v2_result else [],
                "v2_explanations": (
                    [explanation.__dict__ for explanation in v2_result.explanations]
                    if v2_result
                    else []
                ),
                "v2_capacity": (
                    sanitize_for_output(v2_result.capacity.__dict__) if v2_result else {}
                ),
                "v2_cache_metrics": (
                    sanitize_for_output(v2_result.cache_metrics) if v2_result else {}
                ),
                "optimisation_settings": {
                    "use_onemap": use_onemap,
                    "optimise_by": optimise_by,
                    "token": onemap_token or None,
                    "empty_weight": empty_weight,
                    "loaded_weight": loaded_weight,
                    "soft_workload_min": soft_workload_min,
                    "workload_penalty_per_min": workload_penalty_per_min,
                    "soft_adjusted_duration_min": soft_adjusted_duration_min,
                    "duration_penalty_per_min": duration_penalty_per_min,
                    "max_job_overage_penalty": max_job_overage_penalty,
                    "duration_buffer_multiplier": duration_buffer_multiplier,
                    "empty_travel_duration_multiplier": empty_travel_duration_multiplier,
                    "empty_travel_wait_buffer_min": empty_travel_wait_buffer_min,
                    "fallback_penalty": fallback_penalty,
                    "operation_context": operation_context,
                },
                "diagnostics": sanitize_for_output({
                    "rider_job_checks": int(last_progress_event.get("comparison_count", 0)),
                    "estimated_checks": int(last_progress_event.get("estimated_comparisons", estimated_checks)),
                    "elapsed_seconds": elapsed_total,
                    "v2_runtime_seconds": v2_result.runtime_seconds if v2_result else None,
                }),
            }
            commit_optimiser_result(
                st.session_state,
                st.session_state.bluesg_latest_optimisation,
                jobs=jobs_df,
                riders=st.session_state.committed_riders,
            )
            st.session_state.original_optimiser_result = copy.deepcopy(
                st.session_state.bluesg_latest_optimisation
            )
            st.session_state.v2_assignment_undo = []
            st.session_state.assignment_draft = None

latest_optimisation = st.session_state.get("optimiser_result")
if latest_optimisation:
    route_df = latest_optimisation["route_df"]
    summary_df = latest_optimisation["summary_df"]
    result_jobs_df = latest_optimisation["jobs_df"]
    result_rider_df = latest_optimisation["rider_df"]
    result_validation_warnings = latest_optimisation["validation_warnings"]
    result_lookup_warnings = latest_optimisation["lookup_warnings"]
    result_token = latest_optimisation["token"]
    result_diagnostics = latest_optimisation.get("diagnostics", {})
    result_v2_status = clean_text(latest_optimisation.get("v2_status"))
    result_v2_objective = list(latest_optimisation.get("v2_objective", []))
    result_v2_explanations = list(latest_optimisation.get("v2_explanations", []))
    result_v2_capacity = dict(latest_optimisation.get("v2_capacity", {}))
    result_v2_cache = dict(latest_optimisation.get("v2_cache_metrics", {}))
    result_integrity = latest_optimisation.get("integrity_report") or optimisation_integrity_report(route_df, result_jobs_df)
    duplicate_rider_rows_removed = int(latest_optimisation.get("duplicate_rider_rows_removed", 0))
    result_route_variant_index = int(latest_optimisation.get("route_variant_index", 0))
    result_run = latest_optimisation.get("run_result")
    baseline_run_summary = latest_optimisation.get("baseline_summary", {})
    result_move_audit = latest_optimisation.get("move_audit", [])
    run_artifact_path = latest_optimisation.get("run_artifact_path", "")
    unassigned_jobs_df = result_integrity["unassigned_df"]
    result_is_stale = bool(st.session_state.get("result_is_stale"))

    if not result_integrity["is_valid"]:
        st.error(result_integrity["message"])
        if result_integrity["duplicate_details"]:
            st.dataframe(pd.DataFrame(result_integrity["duplicate_details"]), width="stretch", hide_index=True)
        st.stop()

    with review_col:
        st.subheader("3. Review results")
        if result_is_stale:
            st.error("Stale result — shown for reference only. Run the optimiser again before assigning jobs.")
        if result_v2_status == "COMPLETE":
            st.success("COMPLETE — every job is assigned with no soft exceptions.")
        elif result_v2_status == "COMPLETE_WITH_EXCEPTIONS":
            st.warning(
                "COMPLETE WITH EXCEPTIONS — every job is assigned, with the soft exceptions shown below."
            )
        canonical_summary = result_run.summary if result_run is not None else {}
        assigned_jobs = int(canonical_summary.get("jobs_assigned", result_integrity["assigned_unique_jobs"]))
        assigned_route_rows = int(result_integrity["assigned_route_rows"])
        total_jobs_uploaded = int(result_integrity["total_valid_jobs"])
        unassigned_jobs = int(result_integrity["unassigned_jobs"])
        active_riders = len(result_rider_df)
        empty_travel = float(pd.to_numeric(route_df.get("Empty Duration Min"), errors="coerce").fillna(0).sum())
        loaded_travel = float(pd.to_numeric(route_df.get("Loaded Duration Min"), errors="coerce").fillna(0).sum())
        warning_count = len(result_lookup_warnings) + len(result_validation_warnings)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Total jobs", total_jobs_uploaded)
        metric_cols[1].metric("Assigned", assigned_jobs)
        metric_cols[2].metric("Unassigned", unassigned_jobs)
        metric_cols[3].metric("Riders", active_riders)
        st.caption(
            f"Empty travel {empty_travel:.1f} min\n\n"
            f"Loaded travel {loaded_travel:.1f} min\n\n"
            f"Warnings {warning_count}"
        )

        if result_v2_status:
            capacity_cols = st.columns(4)
            capacity_cols[0].metric(
                "Preferred capacity", int(result_v2_capacity.get("preferred_capacity", 0))
            )
            capacity_cols[1].metric(
                "Maximum capacity", int(result_v2_capacity.get("maximum_capacity", 0))
            )
            capacity_cols[2].metric(
                "Cache hit rate",
                f"{float(result_v2_cache.get('cache_hit_rate', 0.0)) * 100:.0f}%",
            )
            capacity_cols[3].metric(
                "V2 runtime",
                f"{float(result_diagnostics.get('v2_runtime_seconds') or 0.0):.1f}s",
            )
            if len(result_v2_objective) >= 12:
                exception_table = pd.DataFrame(
                    [
                        ["Extreme assignments", result_v2_objective[2]],
                        ["Cross-zone assignments", result_v2_objective[3]],
                        ["Area Lead ownership exceptions", result_v2_objective[4]],
                        ["Fragmented clusters", result_v2_objective[5]],
                        ["Disliked assignments", result_v2_objective[8]],
                        ["Jobs above preferred capacity", result_v2_objective[9]],
                    ],
                    columns=["Exception", "Count"],
                )
                with st.expander("V2 objective and soft exceptions", expanded=False):
                    st.dataframe(exception_table, width="stretch", hide_index=True)
                    st.caption(
                        "Lexicographic order: mandatory coverage, hard feasibility, extreme travel, "
                        "cross-zone work, Area Lead ownership, cluster continuity, maximum burden, "
                        "burden spread, disliked work, preferred overage, empty travel, total duration."
                    )

            if result_v2_explanations:
                explanation_rows = []
                for explanation in result_v2_explanations:
                    explanation_rows.append(
                        {
                            "Rider": explanation.get("rider_name", ""),
                            "Job": explanation.get("job_id", ""),
                            "Severity": int(explanation.get("severity", 0)),
                            "Empty min": explanation.get("empty_travel_minutes", 0),
                            "Loaded min": explanation.get("loaded_travel_minutes", 0),
                            "Projected jobs": explanation.get("projected_job_count", 0),
                            "Why selected": "; ".join(explanation.get("selected_reasons", ())),
                            "Soft exceptions": "; ".join(explanation.get("soft_exceptions", ())),
                            "Travel source": explanation.get("travel_source", ""),
                            "Cache": explanation.get("cache_status", ""),
                        }
                    )
                with st.expander("Why each job was assigned", expanded=False):
                    st.dataframe(
                        pd.DataFrame(explanation_rows),
                        width="stretch",
                        hide_index=True,
                        height=min(900, 42 + len(explanation_rows) * 34),
                    )

        if baseline_run_summary:
            comparison_fields = [
                ("Jobs assigned", "jobs_assigned"),
                ("Maximum duty min", "longest_rider_duty_min"),
                ("Duty spread min", "duty_time_spread_min"),
                ("Empty travel min", "total_empty_travel_min"),
                ("Fallback legs", "fallback_leg_count"),
                ("Hard violations", "hard_violation_count"),
            ]
            comparison_df = pd.DataFrame(
                [
                    {
                        "Metric": label,
                        "Baseline": baseline_run_summary.get(key, 0),
                        "Final": canonical_summary.get(key, 0),
                    }
                    for label, key in comparison_fields
                ]
            )
            with st.expander("Baseline vs bounded local improvement", expanded=False):
                st.dataframe(comparison_df, width="stretch", hide_index=True)
                accepted_moves = sum(1 for move in result_move_audit if move.get("accepted"))
                if accepted_moves:
                    st.success(f"Accepted {accepted_moves} safe improving move(s).")
                else:
                    st.info("No safe lexicographic improvement was found; the baseline was retained.")
                if run_artifact_path:
                    st.caption(f"Run artifact: {run_artifact_path}")

        with st.expander("Optimisation Integrity Checks", expanded=False):
            integrity_rows = [
                ["Total valid jobs", total_jobs_uploaded],
                ["Unique assigned jobs", assigned_jobs],
                ["Assigned route rows", assigned_route_rows],
                ["Unassigned jobs", unassigned_jobs],
                ["Duplicate assigned Uploaded Rows", ", ".join(map(str, result_integrity["duplicate_uploaded_rows"])) or "None"],
                ["Jobs in both assigned and unassigned", ", ".join(map(str, result_integrity["overlap_uploaded_rows"])) or "None"],
                ["Duplicate rider rows removed", duplicate_rider_rows_removed],
                ["Route variant", f"Alternate #{result_route_variant_index}" if result_route_variant_index else "Default"],
            ]
            integrity_df = pd.DataFrame(integrity_rows, columns=["Check", "Value"]).astype(str)
            st.dataframe(integrity_df, width="stretch", hide_index=True)
            if result_integrity["duplicate_details"]:
                st.write("Duplicate assignment details")
                st.dataframe(pd.DataFrame(result_integrity["duplicate_details"]), width="stretch", hide_index=True)

        if unassigned_jobs:
            st.warning(
                f"Assigned {assigned_jobs} of {total_jobs_uploaded} job(s). "
                "Some jobs were left unassigned because no rider route satisfied the configured overnight window and hard constraints."
            )
            if not unassigned_jobs_df.empty:
                st.write("Unassigned jobs")
                st.dataframe(unassigned_jobs_df, width="stretch", hide_index=True, height=160)

        failed_validation = route_df["Route Validation Status"].ne("OK")
        if failed_validation.any():
            st.warning("Some rider route rows did not chain correctly. Open Data and route warnings for details.")

        with st.expander("Data and route warnings", expanded=False):
            geographic_validation = route_df.attrs.get("geographic_validation", {})
            for issue in geographic_validation.get("issues", []):
                st.warning(
                    f"{issue.get('car_plate') or issue.get('job_id')}: {issue.get('reason')}"
                )
            if result_lookup_warnings:
                st.write("Travel and assignment warnings:")
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
                st.dataframe(route_df.loc[failed_validation, validation_cols], width="stretch", hide_index=True)

        with st.expander("Optimisation diagnostics", expanded=False):
            diag_cols = st.columns(3)
            diag_cols[0].metric("Rider-job checks", f"{int(result_diagnostics.get('rider_job_checks', 0)):,}")
            diag_cols[1].metric("Estimated checks", f"{int(result_diagnostics.get('estimated_checks', 0)):,}")
            diag_cols[2].metric("Elapsed time", f"{float(result_diagnostics.get('elapsed_seconds', 0.0)):.1f}s")

        with st.expander("Regional capacity and assignment audit", expanded=False):
            regional_capacity = route_df.attrs.get("regional_capacity", [])
            if regional_capacity:
                st.write("Demand, primary capacity and approved directional support")
                st.dataframe(pd.DataFrame(regional_capacity), width="stretch", hide_index=True)
                regional_columns = [
                    "Uploaded Row", "Car Plate", "Rider", "Pickup Address", "Job Region",
                    "Operational Subregion", "Assigned Rider Home Region",
                    "Assigned Rider Current Region Before Job", "Assignment Tier",
                    "Regional Specificity Score", "Regional Support Penalty",
                    "Scarce Driver Protection Penalty", "Unsupported Region Penalty",
                    "Reason for Regional Assignment",
                ]
                regional_columns = [column for column in regional_columns if column in route_df.columns]
                st.write("Per-job regional decisions")
                st.dataframe(route_df[regional_columns], width="stretch", hide_index=True, height=280)
            else:
                st.caption("Regional overflow diagnostics were not enabled for this run.")

    if result_v2_status:
        render_v2_rider_cards(route_df, result_rider_df, result_v2_explanations)

    render_operator_assignment_review(
        route_df,
        summary_df,
        result_jobs_df,
        result_rider_df,
        unassigned_jobs_df,
    )

    st.subheader("Batch Manual Reassignment")
    if st.session_state.get("bluesg_assignment_message"):
        st.success(st.session_state.pop("bluesg_assignment_message"))
    assignment_actions = st.columns(3)
    if assignment_actions[0].button(
        "Edit Assignments",
        type="primary",
        disabled=result_is_stale,
        width="stretch",
    ):
        st.session_state.assignment_draft = build_assignment_editor_dataframe(
            route_df,
            result_jobs_df,
            result_rider_df["Rider Name"].apply(clean_text).tolist(),
        )
        edit_assignments_dialog()
    if assignment_actions[1].button(
        "Undo Assignment Change",
        disabled=not st.session_state.get("v2_assignment_undo") or result_is_stale,
        width="stretch",
    ):
        history = st.session_state.get("v2_assignment_undo", [])
        restored = history.pop()
        st.session_state.v2_assignment_undo = history
        commit_optimiser_result(
            st.session_state,
            restored,
            jobs=st.session_state.committed_jobs,
            riders=st.session_state.committed_riders,
        )
        st.session_state.bluesg_latest_optimisation = restored
        st.session_state.bluesg_assignment_message = "Previous assignment restored."
        st.rerun()
    if assignment_actions[2].button(
        "Reset to Optimiser Result",
        disabled=not st.session_state.get("original_optimiser_result") or result_is_stale,
        width="stretch",
    ):
        restored = copy.deepcopy(st.session_state.original_optimiser_result)
        commit_optimiser_result(
            st.session_state,
            restored,
            jobs=st.session_state.committed_jobs,
            riders=st.session_state.committed_riders,
        )
        st.session_state.bluesg_latest_optimisation = restored
        st.session_state.v2_assignment_undo = []
        st.session_state.bluesg_assignment_message = "Original optimiser result restored."
        st.rerun()

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
    st.dataframe(route_df[dispatch_columns], width="stretch", hide_index=True)

    with st.expander("Technical route details", expanded=False):
        st.dataframe(route_df, width="stretch", hide_index=True)

    st.subheader("Summary")
    summary_columns = [
        "Rider",
        "Total Jobs",
        "Total Route Distance KM",
        "Total Route Duration Min",
        "First Positioning Min",
        "Total Duty Time Min",
        "Adjusted Duty Time Min",
        "Fallback Leg Count",
        "Max Jobs Overage",
        "Within 3 Hours",
        "Final Location",
        "Workload Comment",
    ]
    summary_columns = [column for column in summary_columns if column in summary_df.columns]
    st.dataframe(summary_df[summary_columns], width="stretch", hide_index=True)

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
        st.dataframe(summary_df[detail_summary_columns], width="stretch", hide_index=True)

    st.subheader("Download")
    export_bytes = None
    archive_bytes = None
    if not result_is_stale:
        export_bytes = export_routes_to_excel(
            route_df,
            summary_df,
            jobs_df=result_jobs_df,
            validation_warnings=result_validation_warnings,
            lookup_warnings=result_lookup_warnings,
            run_result=result_run,
            move_audit=result_move_audit,
        )
        archive_table = build_v2_archive_table(
            route_df,
            result_rider_df,
            result_v2_explanations,
            operation_date=(result_run.selected_job_date if result_run is not None else str(selected_job_date)),
            completion_status=result_v2_status or "COMPLETE_WITH_EXCEPTIONS",
            runtime_seconds=float(result_diagnostics.get("v2_runtime_seconds") or 0.0),
            cache_hit_rate=float(result_v2_cache.get("cache_hit_rate", 0.0)),
        )
        archive_bytes = archive_table.to_csv(index=False).encode("utf-8")
    download_cols = st.columns(2)
    download_cols[0].download_button(
        "Download Excel Output",
        data=export_bytes or b"",
        file_name="vehicle_route_optimisation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=export_bytes is None,
        width="stretch",
    )
    download_cols[1].download_button(
        "Archive Daily Result",
        data=archive_bytes or b"",
        file_name=f"vehicle_route_archive_{selected_job_date}.csv",
        mime="text/csv",
        disabled=archive_bytes is None,
        width="stretch",
    )
else:
    with review_col:
        st.subheader("3. Review results")
        st.caption("Optimised routes will appear here after the optimiser is run.")
