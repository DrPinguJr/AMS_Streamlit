import os
import html
import json
import sys
import time
import copy
import hashlib
from datetime import time as clock_time
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Flexar.BlueSG.vehicle_route_optimizer import (
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
    REQUIRED_JOB_HEADERS,
    RIDER_COLUMNS,
    RIDER_LOAD_LEVELS,
    ROSTER_FILE,
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
    build_unassigned_jobs_df,
    get_cost_explanation,
    get_cached_geocode,
    get_onemap_token,
    load_and_validate_jobs,
    load_rider_roster,
    normalise_rider_load_level,
    onemap_credentials_configured,
    optimisation_integrity_report,
    optimise_vehicle_routes,
    improve_route_dataframe,
    read_rider_roster_file,
    save_rider_roster,
    validate_riders,
)
from Flexar.BlueSG.constraints import Constraint
from Flexar.BlueSG.operation_context import EMPTY_TRAVEL_MODES, OperationContext
from Flexar.BlueSG.output_sanitizer import sanitize_for_output
from Flexar.BlueSG.run_metrics import create_run_result, save_run_artifact, sha256_bytes

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


def get_onemap_token_from_env() -> str:
    refreshed_token = st.session_state.get("onemap_token", "")
    if refreshed_token:
        return refreshed_token
    return get_onemap_token()


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

jobs_df = pd.DataFrame()
selected_job_date = pd.Timestamp.now(tz="Asia/Singapore").date()
input_filename = ""
input_sha256 = ""
file_is_valid = False
missing_headers: list[str] = []
validation_warnings: list[str] = []
upload_error = ""
roster_path = ensure_rider_roster_workbook()
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

upload_col, riders_col = st.columns(2, gap="large")

with upload_col:
    st.subheader("1. Upload Job List")
    uploaded_file = st.file_uploader("Upload vehicle jobs Excel file", type=["xlsx", "xls"])

    if uploaded_file is None:
        st.caption("Upload an Excel file to begin.")
    else:
        try:
            input_filename = clean_text(getattr(uploaded_file, "name", "uploaded_jobs.xlsx"))
            input_sha256 = sha256_bytes(uploaded_file.getvalue())
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
                if "Date" in jobs_df.columns:
                    parsed_dates = pd.to_datetime(jobs_df["Date"], errors="coerce").dt.date
                    available_dates = sorted(parsed_dates.dropna().unique())
                    if available_dates:
                        today = pd.Timestamp.now(tz="Asia/Singapore").date()
                        default_date_index = (
                            available_dates.index(today)
                            if today in available_dates
                            else len(available_dates) - 1
                        )
                        selected_job_date = st.selectbox(
                            "Job date",
                            available_dates,
                            index=default_date_index,
                            format_func=lambda value: value.strftime("%d/%m/%Y"),
                            help="Only jobs for the selected date are sent into the optimiser.",
                        )
                        all_date_jobs_count = len(jobs_df)
                        jobs_df = jobs_df.loc[parsed_dates == selected_job_date].copy()
                        jobs_df.attrs.update(
                            {
                                "uploaded_count": all_date_jobs_count,
                                "blank_address_rows_dropped": skipped_rows,
                            }
                        )
                        st.caption(
                            f"Showing {len(jobs_df)} of {all_date_jobs_count} valid job(s) "
                            f"for {selected_job_date.strftime('%d/%m/%Y')}."
                        )
                status_cols = st.columns(2)
                status_cols[0].metric("Valid Jobs", len(jobs_df))
                status_cols[1].metric("Skipped Rows", skipped_rows)
                preview_columns = [
                    "Date",
                    "Car Plate",
                    "Pickup Address",
                    "Pickup Lot",
                    "Drop-off Address",
                    "Pickup Zone",
                    "Drop-off Zone",
                ]
                preview_columns = [column for column in preview_columns if column in jobs_df.columns]
                with st.expander("Preview uploaded jobs", expanded=True):
                    st.dataframe(
                        jobs_df[preview_columns],
                        width="stretch",
                        hide_index=True,
                        height=220,
                    )

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

with riders_col:
    st.subheader("2. Confirm Riders")
    roster_header_cols = st.columns([2, 1])
    with roster_header_cols[0]:
        selected_roster_day = st.selectbox("Roster day", WEEKDAY_SHEETS)
    with roster_header_cols[1]:
        st.caption("Max Jobs is a soft guide.")

    if st.session_state.get("bluesg_roster_day") != selected_roster_day:
        st.session_state.bluesg_roster_day = selected_roster_day
        st.session_state.bluesg_riders = add_session_rider_load_column(load_rider_roster(selected_roster_day))

    if "bluesg_riders" not in st.session_state:
        st.session_state.bluesg_riders = add_session_rider_load_column(load_rider_roster(selected_roster_day))
    else:
        st.session_state.bluesg_riders = add_session_rider_load_column(st.session_state.bluesg_riders)

    rider_df = st.data_editor(
        st.session_state.bluesg_riders,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        height=330,
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
            "Rider Load": st.column_config.SelectboxColumn(
                options=RIDER_LOAD_LEVELS,
                help=(
                    "Session-only priority. Low keeps PT/empty travel and area changes low; "
                    "Medium is balanced; High and Very High are preferred for clustered work."
                ),
            ),
        },
    )
    rider_df = add_session_rider_load_column(rider_df)
    st.session_state.bluesg_riders = rider_df

    roster_action_cols = st.columns([1, 1, 1])
    with roster_action_cols[0]:
        if st.button("Save Roster", type="secondary", width="stretch"):
            try:
                saved_path = save_rider_roster(selected_roster_day, persistent_roster_columns(rider_df))
            except PermissionError:
                st.error("Could not save roster. Close the Excel workbook if it is open, then try again.")
            except Exception as exc:
                st.error(f"Could not save roster: {exc}")
            else:
                st.success(f"Saved {selected_roster_day} roster to {saved_path}")
    with roster_action_cols[1]:
        if st.button("Reload From Excel", width="stretch"):
            try:
                st.session_state.bluesg_riders = add_session_rider_load_column(load_rider_roster(selected_roster_day))
            except Exception as exc:
                st.error(f"Could not reload roster: {exc}")
            else:
                st.rerun()
    with roster_action_cols[2]:
        if hasattr(os, "startfile"):
            if st.button("Open Excel File", width="stretch"):
                try:
                    os.startfile(ROSTER_FILE)
                except Exception as exc:
                    st.error(f"Could not open roster workbook: {exc}")
        else:
            st.caption("Download the workbook below to edit it locally.")

    with st.expander("Roster file options", expanded=False):
        st.caption(f"Persistent roster workbook: {roster_path}")
        st.download_button(
            "Download Roster Workbook",
            data=read_rider_roster_file(),
            file_name="rider_roster.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

action_col, review_col = st.columns([1, 2], gap="large")

with action_col:
    st.subheader("3. Optimise Routes")
    with st.container(border=True):
        optimise_by_label = st.radio(
            "Optimise by",
            ["Duration", "Distance"],
            horizontal=True,
            captions=["Lowest total minutes", "Lowest total kilometres"],
        )
        optimise_by = optimise_by_label.lower()

        use_onemap = st.toggle("Use OneMap distance/time", value=True)
        onemap_token = st.text_input(
            "OneMap access token",
            value=get_onemap_token_from_env(),
            type="password",
            help="Required for OneMap routing distance/time. If blank or invalid, the app will use fallback estimates.",
            disabled=not use_onemap,
        )

        if use_onemap and not onemap_token and not onemap_credentials_configured():
            st.warning(
                "OneMap is enabled but no token or OneMap credentials are configured. "
                "Fallback estimates will be used where needed."
            )

        st.markdown("**Overnight operating window**")
        operation_date = st.date_input(
            "Operation date",
            value=selected_job_date,
            help="The date on which rider duty begins.",
        )
        window_cols = st.columns(2)
        operation_start_time = window_cols[0].time_input("Duty start", value=clock_time(14, 0))
        operation_end_time = window_cols[1].time_input("Duty end", value=clock_time(17, 0))
        empty_travel_mode_label = st.selectbox(
            "Empty-travel mode",
            list(EMPTY_TRAVEL_MODES),
            index=0,
            help="Stored in the run record and route-cache context. Overnight transit is not reused from daytime.",
        )
        operation_context = OperationContext.for_window(
            operation_date,
            operation_start_time,
            operation_end_time,
            empty_travel_mode=EMPTY_TRAVEL_MODES[empty_travel_mode_label],
        )
        st.caption(
            f"Window: {operation_context.operation_start.isoformat(timespec='minutes')} → "
            f"{operation_context.operation_end.isoformat(timespec='minutes')} "
            f"({operation_context.window_duration_min:.0f} min)"
        )

        ready_text = "Ready to optimise" if file_is_valid else "Upload a valid job file first"
        st.caption(ready_text)
        optimise_cols = st.columns(2)
        with optimise_cols[0]:
            optimise_clicked = st.button(
                "Optimise Routes",
                type="primary",
                disabled=not file_is_valid,
                width="stretch",
            )
        with optimise_cols[1]:
            optimise_new_route_clicked = st.button(
                "Optimise New Route",
                disabled=not file_is_valid,
                width="stretch",
                help="Generate an alternate valid route plan by nudging assignment choices.",
            )

        if optimise_clicked:
            st.session_state.bluesg_route_variant_index = 0
        elif optimise_new_route_clicked:
            st.session_state.bluesg_route_variant_index = int(
                st.session_state.get("bluesg_route_variant_index", 0)
            ) + 1
        route_variant_index = int(st.session_state.get("bluesg_route_variant_index", 0))
        if route_variant_index > 0:
            st.caption(f"Alternate route variant #{route_variant_index}")

    with st.expander("Advanced Settings", expanded=False):
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
        if st.button("Reset to Recommended Defaults", width="stretch"):
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
            st.caption("Live activity terminal · latest 23 lines")
            terminal_output = st.empty()
        started_at = time.monotonic()
        last_progress_event: dict = {}
        terminal_lines = ["[   0.0s] START  Preparing route optimisation..."]
        terminal_state = {"last_signature": None}

        def render_terminal() -> None:
            safe_output = html.escape("\n".join(terminal_lines))
            terminal_output.markdown(
                (
                    '<pre style="margin:0; height:428px; overflow:hidden; box-sizing:border-box; '
                    'padding:12px 14px; border:1px solid #334155; border-radius:8px; '
                    'background:#07111f; color:#d1fae5; font:13px/1.35 Consolas, Monaco, monospace; '
                    f'white-space:pre;">{safe_output}</pre>'
                ),
                unsafe_allow_html=True,
            )

        render_terminal()

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
            if event_type in {"assignment", "final_assignment"}:
                label = "FINAL" if event_type == "final_assignment" else "GIVE "
                terminal_message = (
                    f"{label}  Car {car_plate or '(no plate)'} -> {rider_name or '(no rider)'}"
                    f" | {pickup or '?'} -> {dropoff or '?'}"
                )
            elif address:
                terminal_message = f"GEO    {status}: {address}"
            elif rider_name or pickup:
                terminal_message = (
                    f"CHECK  {comparison_count:,}/{estimated_comparisons:,}"
                    f" | rider={rider_name or '?'} | pickup={pickup or '?'}"
                )
            else:
                terminal_message = f"{phase.upper()[:6]:<6} {status}"

            signature = (event_type, phase, status, car_plate, rider_name, pickup, dropoff, address)
            if signature != terminal_state["last_signature"]:
                terminal_state["last_signature"] = signature
                terminal_lines.append(f"[{elapsed:6.1f}s] {terminal_message}")
                del terminal_lines[:-23]
                render_terminal()

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
                    width="stretch",
                    hide_index=True,
                )
            else:
                detail_text.caption("Warming up caches and preparing route checks...")

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
                route_variant_index=route_variant_index,
                fallback_penalty=fallback_penalty,
                operation_context=operation_context,
                constraints=hard_constraints,
                experimental_cluster_first=experimental_cluster_first,
                max_total_duty_time_min=hard_max_duty_min if hard_duty_enabled else None,
                regional_overflow_config=regional_overflow_config,
            )
            integrity_report = optimisation_integrity_report(route_df, jobs_df)
            if not integrity_report["is_valid"]:
                st.error(integrity_report["message"])
                if integrity_report["duplicate_details"]:
                    st.dataframe(pd.DataFrame(integrity_report["duplicate_details"]), width="stretch", hide_index=True)
                st.stop()
            baseline_route_df = route_df.copy()
            baseline_summary_df = summary_df.copy()
            baseline_integrity = {key: value for key, value in integrity_report.items() if key != "unassigned_df"}
            baseline_integrity.update(route_df.attrs.get("hard_constraint_validation", {}))
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
            )
            move_audit: list[dict] = []
            if enable_local_improvement and integrity_report["unassigned_jobs"] == 0:
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
                    "baseline_summary": baseline_run_result.summary,
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
                    "state_aware_greedy_insertion+bounded_local_improvement"
                    if any(move.get("accepted") for move in move_audit)
                    else "state_aware_greedy_insertion"
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
                "baseline_summary": baseline_run_result.summary,
                "move_audit": move_audit,
                "run_artifact_path": str(run_artifact_path),
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
                }),
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
    result_route_variant_index = int(latest_optimisation.get("route_variant_index", 0))
    result_run = latest_optimisation.get("run_result")
    baseline_run_summary = latest_optimisation.get("baseline_summary", {})
    result_move_audit = latest_optimisation.get("move_audit", [])
    run_artifact_path = latest_optimisation.get("run_artifact_path", "")
    unassigned_jobs_df = result_integrity["unassigned_df"]

    if not result_integrity["is_valid"]:
        st.error(result_integrity["message"])
        if result_integrity["duplicate_details"]:
            st.dataframe(pd.DataFrame(result_integrity["duplicate_details"]), width="stretch", hide_index=True)
        st.stop()

    with review_col:
        st.subheader("4. Review Results")
        canonical_summary = result_run.summary if result_run is not None else {}
        assigned_jobs = int(canonical_summary.get("jobs_assigned", result_integrity["assigned_unique_jobs"]))
        assigned_route_rows = int(result_integrity["assigned_route_rows"])
        total_jobs_uploaded = int(result_integrity["total_valid_jobs"])
        unassigned_jobs = int(result_integrity["unassigned_jobs"])
        riders_used = int(canonical_summary.get("riders_used", 0)) or (
            int((summary_df["Total Jobs"].fillna(0).astype(int) > 0).sum())
            if "Total Jobs" in summary_df.columns
            else 0
        )
        total_duration = float(canonical_summary.get("total_duty_time_min", 0.0))
        metric_cols = st.columns(5)
        metric_cols[0].metric("Jobs Assigned", f"{assigned_jobs}/{total_jobs_uploaded}")
        metric_cols[1].metric("Riders Used", riders_used)
        metric_cols[2].metric("Total Rider Duty", f"{total_duration:.1f} min")
        metric_cols[3].metric("Unassigned Jobs", unassigned_jobs)
        metric_cols[4].metric("Fallback Legs", int(canonical_summary.get("fallback_leg_count", 0)))

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

    render_route_editor(route_df, summary_df, result_jobs_df, result_rider_df)

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

    st.subheader("5. Download")
    st.download_button(
        "Download Excel Output",
        data=export_routes_to_excel(
            route_df,
            summary_df,
            jobs_df=result_jobs_df,
            validation_warnings=result_validation_warnings,
            lookup_warnings=result_lookup_warnings,
            run_result=result_run,
            move_audit=result_move_audit,
        ),
        file_name="vehicle_route_optimisation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    with review_col:
        st.subheader("4. Review Results")
        st.caption("Optimised routes will appear here after you run step 3.")
