import copy
import hashlib
import json
import logging
import math
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

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
    DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
    DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
    DEFAULT_EMPTY_WEIGHT,
    DEFAULT_LOADED_WEIGHT,
    DEFAULT_MAX_JOB_OVERAGE_PENALTY,
    DEFAULT_MAX_ADJUSTED_DURATION_MIN,
    DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
    DEFAULT_SOFT_WORKLOAD_MIN,
    DEFAULT_WORKLOAD_PENALTY_PER_MIN,
    ROUTE_COLUMNS,
    SUMMARY_COLUMNS,
    build_jobs_by_stable_id,
    clean_text,
    export_routes_to_excel,
    format_summary_output,
    get_cached_geocode,
    get_onemap_token,
    infer_zone,
    onemap_credentials_configured,
    optimisation_integrity_report,
    rebuild_outputs_from_sequences,
    stable_job_id_from_route_row,
    validate_riders,
)
from Flexar.BlueSG.route_planner import (
    HISTORY_LIMIT,
    UNASSIGNED_LANE,
    assignment_from_routes,
    build_focus_map_data,
    build_draft_connector_lines,
    build_rider_access_paths,
    build_compact_rider_summary,
    build_planner_session_state,
    build_draft_preview_routes,
    build_route_leg_signatures,
    clone_assignment,
    detect_affected_riders,
    detect_changed_route_legs,
    incremental_recalculate,
    enter_focus_mode_state,
    exit_focus_mode_state,
    focus_apply_failure_state,
    focus_apply_success_state,
    invalidate_red_preview,
    matching_red_preview_routes,
    normalise_assignment_board,
    normalise_rider_locks,
    record_manual_job_moves,
    refresh_red_connector_preview,
    redo_draft,
    reset_draft,
    reshuffle_unlocked_assignments,
    undo_draft,
    update_draft_history,
    validate_assignment_board,
    validate_locked_rider_change,
)

try:
    from streamlit_sortables import sort_items
except ImportError:  # Displayed as an actionable page error below.
    sort_items = None


LOGGER = logging.getLogger(__name__)

try:
    st.set_page_config(page_title="Route Map Viewer", layout="wide")
except st.errors.StreamlitAPIException:
    pass


REQUIRED_ROUTE_COLUMNS = {"Rider", "Car Plate", "Pickup Address", "Drop-off Address"}


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


def file_signature(file_bytes: bytes) -> str:
    return hashlib.sha1(file_bytes).hexdigest()


def parse_route_path(value: object) -> list[list[float]]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def normalise_map_sequence(value: object) -> str:
    if value is None:
        return "Missing"
    try:
        if pd.isna(value):
            return "Missing"
    except (TypeError, ValueError):
        pass
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


def numeric_sum(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def first_clean_value(values: pd.Series) -> str:
    for value in values.tolist():
        text = clean_text(value)
        if text:
            return text
    return ""


def normalise_export_route_df(route_df: pd.DataFrame) -> pd.DataFrame:
    route_df = route_df.copy()
    route_df = route_df.loc[:, [column for column in route_df.columns if not str(column).startswith("Unnamed:")]]
    route_df.columns = [clean_text(column) for column in route_df.columns]
    route_df = route_df.dropna(how="all")
    for column in REQUIRED_ROUTE_COLUMNS:
        if column not in route_df.columns:
            raise ValueError(f"Missing exported route column: {column}")
    route_df = route_df[
        route_df["Car Plate"].apply(clean_text).ne("")
        & route_df["Pickup Address"].apply(clean_text).ne("")
        & route_df["Drop-off Address"].apply(clean_text).ne("")
    ].copy()
    if route_df.empty:
        raise ValueError("The exported route file has no route rows.")
    if "Uploaded Row" not in route_df.columns:
        route_df["Uploaded Row"] = range(2, len(route_df) + 2)
    if "Sequence" not in route_df.columns:
        route_df["Sequence"] = route_df.groupby(route_df["Rider"].apply(clean_text)).cumcount() + 1
    for column in ROUTE_COLUMNS:
        if column not in route_df.columns:
            route_df[column] = ""
    return route_df.loc[:, ROUTE_COLUMNS].reset_index(drop=True)


def read_sheet_candidate(excel: pd.ExcelFile, sheet_name: str, header: int) -> pd.DataFrame | None:
    try:
        candidate = pd.read_excel(excel, sheet_name=sheet_name, header=header)
    except Exception:
        return None
    candidate.columns = [clean_text(column) for column in candidate.columns]
    if REQUIRED_ROUTE_COLUMNS.issubset(set(candidate.columns)):
        return candidate
    return None


def read_exported_route_df(file_bytes: bytes) -> tuple[pd.DataFrame, str]:
    excel = pd.ExcelFile(BytesIO(file_bytes))
    try:
        if "Optimised Routes" in excel.sheet_names:
            candidate = read_sheet_candidate(excel, "Optimised Routes", 4)
            if candidate is not None:
                return normalise_export_route_df(candidate), "Optimised Routes"
        if "Map Loader" in excel.sheet_names:
            candidate = read_sheet_candidate(excel, "Map Loader", 0)
            if candidate is not None:
                return normalise_export_route_df(candidate), "Map Loader"
        for sheet_name in excel.sheet_names:
            for header in (0, 4):
                candidate = read_sheet_candidate(excel, sheet_name, header)
                if candidate is not None:
                    return normalise_export_route_df(candidate), sheet_name
    finally:
        excel.close()
    raise ValueError("Could not find an exported route sheet. Upload the optimiser Excel output.")


def build_jobs_df_from_routes(route_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    seen: set[str] = set()
    for _, route in route_df.iterrows():
        job_key = stable_job_id_from_route_row(route)
        if job_key in seen:
            continue
        seen.add(job_key)
        uploaded_row = route.get("Uploaded Row")
        try:
            original_order = int(float(clean_text(uploaded_row))) - 2
        except (TypeError, ValueError):
            original_order = len(rows)
            uploaded_row = original_order + 2
        pickup = clean_text(route.get("Pickup Address"))
        dropoff = clean_text(route.get("Drop-off Address"))
        rows.append(
            {
                "Uploaded Row": uploaded_row,
                "_original_order": original_order,
                "Car Plate": clean_text(route.get("Car Plate")),
                "Pickup Address": pickup,
                "Pickup Lot": clean_text(route.get("Pickup Lot")),
                "Drop-off Address": dropoff,
                "Pickup Zone": infer_zone(pickup),
                "Drop-off Zone": infer_zone(dropoff),
            }
        )
    jobs_df = pd.DataFrame(rows)
    jobs_df.attrs["uploaded_count"] = len(jobs_df)
    return jobs_df


def build_rider_df_from_routes(route_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    sorted_routes = sort_routes_for_map(route_df)
    sorted_routes["_rider_key"] = sorted_routes["Rider"].apply(clean_text)
    for rider, rider_routes in sorted_routes.groupby("_rider_key", sort=False):
        rider_name = clean_text(rider)
        if not rider_name:
            continue
        start_location = first_clean_value(rider_routes["Start From"])
        if not start_location:
            start_location = first_clean_value(rider_routes["Pickup Address"])
        rows.append(
            {
                "Rider Name": rider_name,
                "Start Location": start_location,
                "Start Zone": infer_zone(start_location) or "",
                "Max Jobs": "",
                "Rider Load": "Medium",
            }
        )
    return pd.DataFrame(rows, columns=["Rider Name", "Start Location", "Start Zone", "Max Jobs", "Rider Load"])


def build_summary_from_routes(route_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    sorted_routes = sort_routes_for_map(route_df)
    sorted_routes["_rider_key"] = sorted_routes["Rider"].apply(clean_text)
    for rider, rider_routes in sorted_routes.groupby("_rider_key", sort=False):
        rider_routes = rider_routes.copy()
        total_duration = numeric_sum(rider_routes, "Total Duration Min")
        adjusted = pd.to_numeric(rider_routes.get("Projected Adjusted Duration Min"), errors="coerce")
        adjusted_duration = float(adjusted.dropna().iloc[-1]) if adjusted is not None and not adjusted.dropna().empty else total_duration * DEFAULT_DURATION_BUFFER_MULTIPLIER
        final_location = clean_text(rider_routes.iloc[-1].get("Drop-off Address")) if not rider_routes.empty else ""
        rows.append(
            {
                "Rider": clean_text(rider),
                "Total Jobs": len(rider_routes),
                "Total Empty Distance KM": round(numeric_sum(rider_routes, "Empty Distance KM"), 2),
                "Total Empty Duration Min": round(numeric_sum(rider_routes, "Empty Duration Min"), 1),
                "Total Loaded Distance KM": round(numeric_sum(rider_routes, "Loaded Distance KM"), 2),
                "Total Loaded Duration Min": round(numeric_sum(rider_routes, "Loaded Duration Min"), 1),
                "Total Route Distance KM": round(numeric_sum(rider_routes, "Total Distance KM"), 2),
                "Total Route Duration Min": round(total_duration, 1),
                "Adjusted Route Duration Min": round(adjusted_duration, 1),
                "Within 3 Hours": "OK" if adjusted_duration <= 180 else "Fail",
                "Final Location": final_location,
            }
        )
    summary_df = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    return format_summary_output(summary_df, route_df)


def load_route_workbook(file_bytes: bytes) -> dict[str, Any]:
    route_df, source_sheet = read_exported_route_df(file_bytes)
    jobs_df = build_jobs_df_from_routes(route_df)
    rider_df = build_rider_df_from_routes(route_df)
    summary_df = build_summary_from_routes(route_df)
    return {
        "source_sheet": source_sheet,
        "original_route_df": route_df.copy(),
        "route_df": route_df.copy(),
        "jobs_df": jobs_df,
        "rider_df": rider_df,
        "summary_df": summary_df,
        "lookup_warnings": [],
        "last_recalculated_at": "",
    }


def route_source_signature(route_df: pd.DataFrame) -> str:
    if route_df is None or route_df.empty:
        return ""
    rows = []
    for _, row in sort_routes_for_map(route_df).iterrows():
        rows.append(
            "|".join(
                [
                    clean_text(row.get("Rider")),
                    normalise_map_sequence(row.get("Sequence")),
                    clean_text(row.get("Uploaded Row")),
                    clean_text(row.get("Car Plate")),
                    clean_text(row.get("Pickup Address")),
                    clean_text(row.get("Drop-off Address")),
                ]
            )
        )
    return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()


def assignment_editor_df(route_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, route in sort_routes_for_map(route_df).iterrows():
        try:
            sequence = int(float(clean_text(route.get("Sequence"))))
        except (TypeError, ValueError):
            sequence = len(rows) + 1
        rows.append(
            {
                "Job Key": stable_job_id_from_route_row(route),
                "Rider": clean_text(route.get("Rider")),
                "Sequence": sequence,
                "Uploaded Row": route.get("Uploaded Row"),
                "Car Plate": clean_text(route.get("Car Plate")),
                "Pickup": clean_text(route.get("Pickup Address")),
                "Drop-off": clean_text(route.get("Drop-off Address")),
            }
        )
    return pd.DataFrame(rows)


def build_sequences_from_editor(editor_df: pd.DataFrame, rider_names: list[str]) -> dict[str, list[str]]:
    editor_df = editor_df.copy()
    editor_df["_row_order"] = range(len(editor_df))
    editor_df["Rider"] = editor_df["Rider"].apply(clean_text)
    editor_df = editor_df[editor_df["Rider"].ne("") & editor_df["Job Key"].apply(clean_text).ne("")]
    editor_df["_sequence_sort"] = pd.to_numeric(editor_df["Sequence"], errors="coerce")
    editor_df["_sequence_sort"] = editor_df["_sequence_sort"].fillna(editor_df["_row_order"] + 1)
    sequences = {rider: [] for rider in rider_names}
    for rider, rider_jobs in editor_df.sort_values(["Rider", "_sequence_sort", "_row_order"], kind="stable").groupby("Rider", sort=False):
        sequences.setdefault(rider, [])
        sequences[rider] = [clean_text(job_id) for job_id in rider_jobs["Job Key"].tolist()]
    return sequences


def recalculation_settings(use_onemap: bool, token: str | None, optimise_by: str) -> dict[str, Any]:
    return {
        "use_onemap": use_onemap,
        "optimise_by": optimise_by,
        "token": token or None,
        "empty_weight": DEFAULT_EMPTY_WEIGHT,
        "loaded_weight": DEFAULT_LOADED_WEIGHT,
        "soft_workload_min": DEFAULT_SOFT_WORKLOAD_MIN,
        "workload_penalty_per_min": DEFAULT_WORKLOAD_PENALTY_PER_MIN,
        "soft_adjusted_duration_min": DEFAULT_SOFT_ADJUSTED_DURATION_MIN,
        "duration_penalty_per_min": DEFAULT_DURATION_PENALTY_PER_MIN,
        "max_job_overage_penalty": DEFAULT_MAX_JOB_OVERAGE_PENALTY,
        "duration_buffer_multiplier": DEFAULT_DURATION_BUFFER_MULTIPLIER,
        "empty_travel_duration_multiplier": DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
        "empty_travel_wait_buffer_min": DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
    }


def recalculate_routes_from_editor(
    editor_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    settings: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        raise ValueError("; ".join(rider_errors))
    rider_names = [rider.name for rider in riders]
    sequences = build_sequences_from_editor(editor_df, rider_names)
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    missing_jobs = sorted(
        {
            job_id
            for rider_jobs in sequences.values()
            for job_id in rider_jobs
            if job_id not in jobs_by_id
        }
    )
    if missing_jobs:
        raise ValueError(f"Some edited jobs could not be matched back to the exported file: {', '.join(missing_jobs[:5])}")
    route_df, summary_df, lookup_warnings = rebuild_outputs_from_sequences(
        sequences,
        riders,
        jobs_by_id,
        jobs_df=jobs_df,
        **settings,
    )
    return route_df, summary_df, lookup_warnings


def map_view_state(point_df: pd.DataFrame) -> pdk.ViewState:
    if point_df.empty:
        return pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=11, pitch=0)
    latitudes = pd.to_numeric(point_df["lat"], errors="coerce").dropna()
    longitudes = pd.to_numeric(point_df["lon"], errors="coerce").dropna()
    if latitudes.empty or longitudes.empty:
        return pdk.ViewState(latitude=1.3521, longitude=103.8198, zoom=11, pitch=0)
    spread = max(float(latitudes.max() - latitudes.min()), float(longitudes.max() - longitudes.min()))
    if spread <= 0.03:
        zoom = 12.1
    elif spread <= 0.08:
        zoom = 11.3
    elif spread <= 0.15:
        zoom = 10.6
    else:
        zoom = 10.0
    return pdk.ViewState(latitude=float(latitudes.mean()), longitude=float(longitudes.mean()), zoom=zoom, pitch=0)


def add_point(
    rows: list[dict[str, object]],
    geocodes: dict[str, dict[str, object]],
    address: str,
    location_type: str,
    tooltip: str,
    colour: list[int],
) -> None:
    address = clean_text(address)
    result = geocodes.get(address, {})
    if result.get("lat") is None or result.get("lon") is None:
        return
    rows.append(
        {
            "Address": address,
            "Location Type": location_type,
            "tooltip": tooltip,
            "lat": result["lat"],
            "lon": result["lon"],
            "fill_color": colour,
        }
    )


def build_map_data(route_df: pd.DataFrame, rider_df: pd.DataFrame, token: str | None, selected_rider: str, selected_sequence: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    addresses = []
    for column in ["Start Location"]:
        if column in rider_df.columns:
            addresses.extend(rider_df[column].apply(clean_text).tolist())
    for column in ["Start From", "Pickup Address", "Drop-off Address"]:
        if column in route_df.columns:
            addresses.extend(route_df[column].apply(clean_text).tolist())
    unique_addresses = tuple(sorted({address for address in addresses if address}))
    geocodes = cached_route_map_geocodes(unique_addresses, token)

    visible_route_df = sort_routes_for_map(route_df)
    if selected_rider != "All riders":
        visible_route_df = visible_route_df[visible_route_df["Rider"].apply(clean_text) == selected_rider].copy()
    if selected_sequence != "All":
        visible_route_df = visible_route_df[
            visible_route_df["Sequence"].apply(normalise_map_sequence) == selected_sequence
        ].copy()

    point_rows: list[dict[str, object]] = []
    leg_rows: list[dict[str, object]] = []
    for _, row in visible_route_df.iterrows():
        rider = clean_text(row.get("Rider"))
        sequence = normalise_map_sequence(row.get("Sequence"))
        start_from = clean_text(row.get("Start From"))
        pickup = clean_text(row.get("Pickup Address"))
        dropoff = clean_text(row.get("Drop-off Address"))
        car_plate = clean_text(row.get("Car Plate"))

        add_point(point_rows, geocodes, start_from, "Start", f"{rider}<br/>Job {sequence} start<br/>{start_from}", [17, 24, 39])
        add_point(point_rows, geocodes, pickup, "Pickup", f"{rider}<br/>Job {sequence} pickup<br/>{pickup}", [14, 165, 233])
        add_point(point_rows, geocodes, dropoff, "Drop-off", f"{rider}<br/>Job {sequence} drop-off<br/>{dropoff}", [249, 115, 22])

        legs = [
            {
                "Mode": "Public transport / empty travel",
                "Mode Label": "PT",
                "From": start_from,
                "To": pickup,
                "Distance KM": row.get("Empty Distance KM"),
                "Duration Min": row.get("Empty Duration Min"),
                "Route Path": parse_route_path(row.get("Empty Route Path")),
                "color": [220, 38, 38, 210],
            },
            {
                "Mode": "Car movement",
                "Mode Label": "DRIVE",
                "From": pickup,
                "To": dropoff,
                "Distance KM": row.get("Loaded Distance KM"),
                "Duration Min": row.get("Loaded Duration Min"),
                "Route Path": parse_route_path(row.get("Loaded Route Path")),
                "color": [22, 163, 74, 230],
            },
        ]
        for leg in legs:
            start = geocodes.get(leg["From"], {})
            end = geocodes.get(leg["To"], {})
            if start.get("lat") is None or start.get("lon") is None or end.get("lat") is None or end.get("lon") is None:
                continue
            path = leg["Route Path"] or [[start["lon"], start["lat"]], [end["lon"], end["lat"]]]
            leg_rows.append(
                {
                    "Rider": rider,
                    "Sequence": sequence,
                    "Car Plate": car_plate,
                    "Mode": leg["Mode"],
                    "From": leg["From"],
                    "To": leg["To"],
                    "Distance KM": leg["Distance KM"],
                    "Duration Min": leg["Duration Min"],
                    "path": path,
                    "color": leg["color"],
                    "label_position": [
                        (float(start["lon"]) + float(end["lon"])) / 2,
                        (float(start["lat"]) + float(end["lat"])) / 2,
                    ],
                    "label": f"{rider} J{sequence} {leg['Mode Label']}",
                    "tooltip": (
                        f"{rider}<br/>Job {sequence}: {leg['Mode']}<br/>"
                        f"{leg['From']} -> {leg['To']}<br/>"
                        f"{leg['Distance KM']} km, {leg['Duration Min']} min<br/>"
                        f"{car_plate}"
                    ),
                }
            )

    missing = [
        f"{address}: {result.get('error') or 'No coordinates returned'}"
        for address, result in geocodes.items()
        if result.get("lat") is None or result.get("lon") is None
    ]
    return pd.DataFrame(point_rows), pd.DataFrame(leg_rows), missing


def render_map(route_df: pd.DataFrame, rider_df: pd.DataFrame, token: str | None) -> None:
    rider_names = [clean_text(rider) for rider in route_df["Rider"].dropna().astype(str).drop_duplicates().tolist()]
    route_options = ["All riders"] + rider_names
    if st.session_state.get("bluesg_map_viewer_selected_rider") not in route_options:
        st.session_state.bluesg_map_viewer_selected_rider = "All riders"
    selected_rider = st.selectbox("Map rider", route_options, key="bluesg_map_viewer_selected_rider")

    selected_sequence = "All"
    if selected_rider != "All riders":
        rider_routes = sort_routes_for_map(route_df[route_df["Rider"].apply(clean_text) == selected_rider])
        sequence_options = ["All"] + [
            sequence
            for sequence in dict.fromkeys(rider_routes["Sequence"].apply(normalise_map_sequence).tolist())
            if sequence
        ]
        if st.session_state.get("bluesg_map_viewer_selected_sequence") not in sequence_options:
            st.session_state.bluesg_map_viewer_selected_sequence = "All"
        selected_sequence = st.selectbox("Route step", sequence_options, key="bluesg_map_viewer_selected_sequence")

    show_labels = st.toggle("Show route labels", value=selected_rider != "All riders")
    point_df, leg_df, missing_locations = build_map_data(route_df, rider_df, token, selected_rider, selected_sequence)
    if point_df.empty and leg_df.empty:
        st.warning("No map locations could be geocoded. Check the addresses or OneMap token.")
        return

    layers = []
    if not leg_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                leg_df,
                get_path="path",
                get_color="color",
                width_min_pixels=4,
                pickable=True,
            )
        )
    if show_labels and not leg_df.empty:
        layers.append(
            pdk.Layer(
                "TextLayer",
                leg_df,
                get_position="label_position",
                get_text="label",
                get_color=[17, 24, 39],
                get_size=12,
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
                get_radius=70,
                radius_min_pixels=5,
                radius_max_pixels=13,
                stroked=True,
                get_line_color=[255, 255, 255],
                line_width_min_pixels=1,
                pickable=True,
            )
        )

    deck = pdk.Deck(
        map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
        initial_view_state=map_view_state(point_df),
        layers=layers,
        tooltip={
            "html": "{tooltip}",
            "style": {"backgroundColor": "#111827", "color": "white"},
        },
    )
    st.pydeck_chart(deck, width="stretch")

    if missing_locations:
        with st.expander("Map locations not found", expanded=False):
            for warning in missing_locations[:80]:
                st.warning(warning)
            if len(missing_locations) > 80:
                st.info(f"Showing first 80 of {len(missing_locations)} missing location(s).")


def render_summary(route_df: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    assigned_jobs = len(route_df)
    rider_count = int(route_df["Rider"].apply(clean_text).nunique()) if "Rider" in route_df.columns else 0
    total_duration = numeric_sum(summary_df, "Total Route Duration Min")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Route Rows", assigned_jobs)
    metric_cols[1].metric("Riders", rider_count)
    metric_cols[2].metric("Total Duration", f"{total_duration:.1f} min")


def assignment_signature(assignment: dict[str, list[str]]) -> str:
    return hashlib.sha1(json.dumps(assignment, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def short_location(value: object, limit: int = 34) -> str:
    text = clean_text(value)
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def initialise_route_planner(state: dict[str, Any], workbook_id: str) -> None:
    """Reset every planner-specific state when a different workbook is loaded."""

    rider_names = state["rider_df"]["Rider Name"].apply(clean_text).dropna().tolist()
    payload = build_planner_session_state(state["route_df"], state["jobs_df"], rider_names, workbook_id)
    for key, value in payload.items():
        st.session_state[key] = value
    st.session_state["route_planner_last_apply_stats"] = {}
    st.session_state["route_planner_map_focus"] = False
    LOGGER.info("Route planner initialised workbook=%s jobs=%s", workbook_id[:12], len(state["jobs_df"]))


def lane_duration(summary_df: pd.DataFrame, rider: str) -> float:
    if summary_df is None or summary_df.empty:
        return 0.0
    matches = summary_df[summary_df["Rider"].apply(clean_text) == rider]
    return float(matches.iloc[0].get("Total Route Duration Min") or 0) if not matches.empty else 0.0


def build_sortable_board(
    assignment: dict[str, list[str]],
    jobs_by_id: dict[str, dict[str, Any]],
    summary_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    locked_rider_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], list[str]]:
    """Build display-only strings with exact reversible mappings to stable IDs."""

    rider_names = rider_df["Rider Name"].apply(clean_text).dropna().tolist()
    lane_order = [*rider_names, UNASSIGNED_LANE]
    max_jobs_by_rider = {
        clean_text(row.get("Rider Name")): pd.to_numeric(pd.Series([row.get("Max Jobs")]), errors="coerce").iloc[0]
        for _, row in rider_df.iterrows()
    }
    board: list[dict[str, Any]] = []
    header_to_lane: dict[str, str] = {}
    card_to_job_id: dict[str, str] = {}
    locked = set(locked_rider_ids or [])
    for lane_index, lane in enumerate(lane_order, start=1):
        jobs = assignment.get(lane, [])
        display_name = "Unassigned" if lane == UNASSIGNED_LANE else lane
        duration = 0.0 if lane == UNASSIGNED_LANE else lane_duration(summary_df, lane)
        max_jobs = max_jobs_by_rider.get(lane)
        over_jobs = lane != UNASSIGNED_LANE and pd.notna(max_jobs) and float(max_jobs) > 0 and len(jobs) > int(max_jobs)
        warning = " ⚠" if over_jobs or duration > 180 or lane == UNASSIGNED_LANE and jobs else ""
        duration_label = "not routed" if lane == UNASSIGNED_LANE else f"{duration:.0f} confirmed min"
        lock_icon = " 🔒" if lane in locked else (" 🔓" if lane != UNASSIGNED_LANE else "")
        header = f"{display_name} · {len(jobs)} jobs · {duration_label}{warning} · lane-{lane_index:02d}{lock_icon}"
        header_to_lane[header] = lane
        cards: list[str] = []
        for job_id in jobs:
            job = jobs_by_id[job_id]
            token = hashlib.sha1(job_id.encode("utf-8")).hexdigest()[:7]
            card = f"{clean_text(job.get('Car Plate')) or 'No plate'} · {token}\n{short_location(job.get('Pickup Address'), 27)} → {short_location(job.get('Drop-off Address'), 27)}"
            while card in card_to_job_id:
                card += "·"
            card_to_job_id[card] = job_id
            cards.append(card)
        board.append({"header": header, "items": cards})
    return board, header_to_lane, card_to_job_id, lane_order


def render_route_assignment_board(
    assignment: dict[str, list[str]],
    jobs_by_id: dict[str, dict[str, Any]],
    summary_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    *,
    dark_mode: bool = False,
    locked_rider_ids: list[str] | None = None,
    board_revision: int = 0,
) -> dict[str, list[str]] | None:
    if sort_items is None:
        st.error("Drag-and-drop planner dependency is missing. Install project requirements and restart Streamlit.")
        st.code(r".\.venv\Scripts\python.exe -m pip install -r requirements.txt")
        return None
    board, header_to_lane, card_to_job_id, lane_order = build_sortable_board(
        assignment, jobs_by_id, summary_df, rider_df, locked_rider_ids
    )
    custom_style = """
    .sortable-component { padding: 0; }
    .sortable-container { border: 1px solid #d8dee9; border-radius: 9px; margin-bottom: .55rem; background: #f8fafc; }
    .sortable-container-header { padding: .48rem .65rem; background: #e8eef7; color: #172033; font-weight: 700; font-size: .85rem; }
    .sortable-container-body { min-height: 38px; padding: .35rem; }
    .sortable-item, .sortable-item:hover { white-space: pre-line; border: 1px solid #cbd5e1; border-radius: 7px; background: white; color: #172033; padding: .45rem .55rem; margin: .28rem 0; font-size: .78rem; line-height: 1.25; cursor: grab; counter-increment: item; }
    .sortable-container-body { counter-reset: item; }
    .sortable-item::before { content: counter(item) ". "; font-weight: 800; color: #2563eb; }
    """
    if dark_mode:
        custom_style = """
        html, body { height: 100%; margin: 0; overflow: hidden; background: #111827; }
        .sortable-component { display: flex !important; flex-direction: column !important; flex-wrap: nowrap !important; align-items: stretch !important; width: 100% !important; height: calc(100dvh - 238px) !important; min-height: 210px; overflow-y: auto !important; overflow-x: hidden !important; overscroll-behavior: contain; scrollbar-gutter: stable; padding: 0 .2rem .8rem 0; background: #111827; color: #e5e7eb; }
        .sortable-container { display: block !important; flex: 0 0 auto !important; width: 100% !important; min-width: 100% !important; max-width: 100% !important; box-sizing: border-box !important; border: 1px solid #374151; border-radius: 9px; margin: 0 0 .55rem 0 !important; background: #111827; overflow: hidden; }
        .sortable-container-header { padding: .48rem .6rem; background: #1f2937; color: #f9fafb; font-weight: 700; font-size: .78rem; line-height: 1.2; }
        .sortable-container-body { display: flex !important; flex-direction: column !important; flex-wrap: nowrap !important; width: 100% !important; min-height: 38px; padding: .3rem; box-sizing: border-box !important; background: #111827; counter-reset: item; }
        .sortable-item, .sortable-item:hover { display: block !important; flex: 0 0 auto !important; width: 100% !important; max-width: 100% !important; box-sizing: border-box !important; white-space: pre-line; border: 1px solid #4b5563; border-radius: 7px; background: #182235; color: #e5e7eb; padding: .34rem .45rem; margin: .2rem 0; font-size: .72rem; line-height: 1.2; cursor: grab; counter-increment: item; box-shadow: none; touch-action: none; }
        .sortable-item:hover { border-color: #10b981; background: #1d2b3f; }
        .sortable-item::before { content: counter(item) ". "; font-weight: 800; color: #34d399; }
        """
    raw_board = sort_items(
        board,
        multi_containers=True,
        direction="vertical",
        custom_style=custom_style,
        key=f"route_planner_board_{assignment_signature(assignment)}_{assignment_signature({'locked': sorted(locked_rider_ids or [])})}_{board_revision}",
    )
    try:
        return normalise_assignment_board(raw_board, header_to_lane, card_to_job_id, lane_order)
    except ValueError as exc:
        LOGGER.warning("Route planner component validation failed: %s", exc)
        st.error(str(exc))
        return None


def _assignment_positions(assignment: dict[str, list[str]]) -> dict[str, tuple[str, int]]:
    return {
        job_id: (lane, position)
        for lane, job_ids in assignment.items()
        for position, job_id in enumerate(job_ids, start=1)
    }


def _store_draft_change(
    before: dict[str, list[str]],
    proposed: dict[str, list[str]],
    confirmed: dict[str, list[str]],
    rider_starts: dict[str, str],
    *,
    record_manual: bool = True,
) -> bool:
    updated, undo_stack, redo_stack, changed = update_draft_history(
        before,
        proposed,
        st.session_state.get("route_planner_undo_stack", []),
        st.session_state.get("route_planner_redo_stack", []),
        HISTORY_LIMIT,
    )
    if not changed:
        return False
    affected = detect_affected_riders(confirmed, updated, rider_starts, rider_starts)
    st.session_state["route_planner_draft_assignment"] = updated
    st.session_state["route_planner_undo_stack"] = undo_stack
    st.session_state["route_planner_redo_stack"] = redo_stack
    st.session_state["route_planner_is_dirty"] = updated != confirmed
    st.session_state["route_planner_affected_riders"] = affected
    st.session_state["route_planner_preview_stale_riders"] = list(
        invalidate_red_preview(
            before,
            updated,
            st.session_state.get("route_planner_preview_stale_riders", []),
        )
    )
    st.session_state["route_planner_preview_error"] = ""
    if record_manual:
        st.session_state["route_planner_manual_move_history"] = record_manual_job_moves(
            before,
            updated,
            st.session_state.get("route_planner_manual_move_history", {}),
        )
    st.session_state["route_planner_board_revision"] = int(
        st.session_state.get("route_planner_board_revision", 0)
    ) + 1
    before_positions = _assignment_positions(before)
    after_positions = _assignment_positions(updated)
    for job_id in sorted(set(before_positions) | set(after_positions)):
        old = before_positions.get(job_id)
        new = after_positions.get(job_id)
        if old == new:
            continue
        event = "moved" if old and new and old[0] != new[0] else "reordered"
        LOGGER.info("Route planner draft job %s job_id=%s before=%s after=%s", event, job_id, old, new)
    LOGGER.info("Route planner draft changed affected_riders=%s", affected)
    return True


def render_focus_green_map(
    draft_assignment: dict[str, list[str]],
    visible_riders: list[str],
    confirmed_routes: pd.DataFrame,
    jobs_df: pd.DataFrame,
    confirmed_assignment: dict[str, list[str]] | None = None,
    rider_starts: dict[str, str] | None = None,
    preview_routes: pd.DataFrame | None = None,
    rider_access_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[int, int, tuple[str, ...]]:
    """Render green jobs, red rider access, and immediate purple draft connectors."""

    focus_data = build_focus_map_data(draft_assignment, visible_riders, confirmed_routes, jobs_df)
    starts = rider_starts or {}
    access = build_rider_access_paths(
        draft_assignment, visible_riders, confirmed_routes, preview_routes, jobs_df, starts, rider_access_cache
    )
    connectors = build_draft_connector_lines(
        confirmed_assignment or draft_assignment, draft_assignment, jobs_df, starts
    )
    st.session_state["route_planner_rider_access_cache"] = access.cache
    connector_df = connectors.route_df
    if not connector_df.empty:
        connector_df = connector_df[connector_df["Rider"].isin(set(visible_riders))].copy()
    st.session_state["route_planner_draft_connectors"] = connector_df
    layers: list[pdk.Layer] = []
    if not focus_data.route_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                focus_data.route_df,
                id="focus-green-loaded-routes",
                get_path="path",
                get_color="color",
                width_min_pixels=5,
                pickable=True,
            )
        )
    if not access.route_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                access.route_df,
                id="focus-red-rider-access",
                get_path="path",
                get_color="color",
                width_min_pixels=4,
                pickable=True,
            )
        )
    if not connector_df.empty:
        layers.append(
            pdk.Layer(
                "PathLayer",
                connector_df,
                id="focus-purple-draft-connectors",
                get_path="path",
                get_color="color",
                width_min_pixels=3,
                pickable=True,
            )
        )
    if not focus_data.marker_df.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                focus_data.marker_df,
                id="focus-job-markers",
                get_position="[lon, lat]",
                get_fill_color="fill_color",
                get_radius=65,
                radius_min_pixels=5,
                radius_max_pixels=12,
                stroked=True,
                get_line_color=[255, 255, 255],
                line_width_min_pixels=2,
                pickable=True,
            )
        )
    if not layers:
        st.info("No cached loaded routes are available for the visible riders.")
    else:
        deck = pdk.Deck(
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            initial_view_state=map_view_state(focus_data.marker_df),
            layers=layers,
            tooltip={"html": "{tooltip}", "style": {"backgroundColor": "#111827", "color": "white"}},
        )
        st.pydeck_chart(
            deck,
            height="stretch",
            width="stretch",
            key="route_planner_focus_map_chart",
        )
    warnings = tuple(dict.fromkeys([*access.warnings, *connectors.warnings]))
    return len(focus_data.pending_job_ids), len(focus_data.route_df), warnings


def _commit_recalculation_result(state: dict[str, Any], draft_assignment: dict[str, list[str]], result: Any) -> None:
    for key, value in focus_apply_success_state(draft_assignment, result).items():
        st.session_state[key] = value
    state["route_df"] = result.route_df.copy()
    state["summary_df"] = result.summary_df.copy()
    state["lookup_warnings"] = result.warnings
    st.session_state.bluesg_map_viewer_state = state


def _render_map_planner_focus_legacy(
    state: dict[str, Any],
    jobs_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    rider_names: list[str],
    rider_starts: dict[str, str],
    jobs_by_id: dict[str, dict[str, Any]],
) -> None:
    """Dedicated manager view sharing the normal planner's draft and confirmed state."""

    st.markdown(
        """
        <style>
        [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stAppViewContainer"] { position: fixed; inset: 0; width: 100vw; height: 100vh; z-index: 9990; overflow: hidden; background: #080d16; color: #e5e7eb; }
        [data-testid="stMain"] { height: 100vh; overflow: hidden; background: #080d16; color: #e5e7eb; }
        .block-container { max-width: 100vw !important; height: 100vh; padding: .65rem .9rem !important; overflow: hidden; }
        [data-testid="stVerticalBlock"] { gap: .45rem; }
        .block-container > [data-testid="stVerticalBlock"] { height: 100%; }
        [data-testid="stHorizontalBlock"]:has([data-testid="stDeckGlJsonChart"]) { height: calc(100vh - 4.7rem) !important; min-height: 0 !important; align-items: stretch !important; }
        [data-testid="stHorizontalBlock"]:has([data-testid="stDeckGlJsonChart"]) > [data-testid="stColumn"] { height: 100% !important; min-height: 0 !important; overflow: hidden !important; }
        [data-testid="stDeckGlJsonChart"] { height: calc(100vh - 7.1rem) !important; min-height: 0 !important; }
        [data-testid="stDeckGlJsonChart"] > div { height: 100% !important; }
        [data-testid="stDeckGlJsonChart"] canvas { height: 100% !important; }
        [data-testid="stAppViewContainer"] p,
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3,
        [data-testid="stAppViewContainer"] h4 { color: #e5e7eb !important; }
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stVerticalBlockBorderWrapper"] > div { height: calc(100vh - 5.2rem) !important; max-height: calc(100vh - 5.2rem) !important; min-height: 0 !important; background: #111827 !important; border-color: #374151 !important; }
        [data-testid="stCheckbox"] label span { color: #e5e7eb !important; }
        [data-testid="stCheckbox"] input { accent-color: #10b981; }
        [data-testid="stAlert"] { background: #422006 !important; color: #fde68a !important; border: 1px solid #a16207; }
        [data-testid="stAlert"] p { color: inherit !important; }
        [data-testid="stIFrame"] { background: #111827; border-radius: 8px; }
        .stButton > button { background: #151d2b; color: #f9fafb; border-color: #4b5563; }
        .stButton > button:hover { background: #1f2937; color: #ffffff; border-color: #10b981; }
        .stButton > button:disabled { background: #111827; color: #6b7280; border-color: #273244; }
        @media (max-width: 1150px) { .block-container { padding: .5rem !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
    confirmed_routes = st.session_state["route_planner_confirmed_routes"]
    confirmed_assignment = clone_assignment(st.session_state["route_planner_confirmed_assignment"])
    draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
    dirty = bool(st.session_state.get("route_planner_is_dirty"))
    total_jobs = sum(len(job_ids) for lane, job_ids in draft_assignment.items() if lane != UNASSIGNED_LANE)

    title_col, status_col, undo_col, redo_col, apply_col, exit_col = st.columns([3.2, 1.3, .7, .7, 1.8, 1.65])
    title_col.markdown(f"### Route Planner  ·  {total_jobs} jobs  ·  {len(rider_names)} riders")
    status_col.markdown("**Draft changes**" if dirty else "Plan up to date")
    undo_clicked = undo_col.button("Undo", disabled=not st.session_state.get("route_planner_undo_stack"), width="stretch")
    redo_clicked = redo_col.button("Redo", disabled=not st.session_state.get("route_planner_redo_stack"), width="stretch")
    apply_clicked = apply_col.button("Apply & Recalculate", type="primary", disabled=not dirty, width="stretch")
    exit_clicked = exit_col.button("Exit Without Applying", width="stretch")

    if exit_clicked:
        for key, value in exit_focus_mode_state(st.session_state).items():
            st.session_state[key] = value
        st.session_state["route_planner_focus_notice"] = (
            "Map Planner closed. Your unapplied draft is still saved." if dirty else "Map Planner closed."
        )
        LOGGER.info("Route planner exited focus mode dirty=%s", dirty)
        st.rerun()

    if undo_clicked or redo_clicked:
        operation = undo_draft if undo_clicked else redo_draft
        updated, undo_stack, redo_stack, changed = operation(
            draft_assignment,
            st.session_state.get("route_planner_undo_stack", []),
            st.session_state.get("route_planner_redo_stack", []),
        )
        if changed:
            st.session_state["route_planner_draft_assignment"] = updated
            st.session_state["route_planner_undo_stack"] = undo_stack
            st.session_state["route_planner_redo_stack"] = redo_stack
            st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
            st.session_state["route_planner_affected_riders"] = detect_affected_riders(confirmed_assignment, updated)
            LOGGER.info("Route planner focus %s", "undo" if undo_clicked else "redo")
            st.rerun()

    if apply_clicked:
        validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
        if not validation.is_valid:
            st.error("Routes could not be updated because the draft contains an invalid assignment. Your changes have not been applied.")
            LOGGER.warning("Route planner focus apply validation failed errors=%s", validation.errors)
        else:
            affected = detect_affected_riders(confirmed_assignment, draft_assignment, rider_starts, rider_starts)
            LOGGER.info("Route planner focus apply requested affected_riders=%s", affected)
            try:
                with st.spinner(f"Recalculating {len(affected)} affected rider(s)..."):
                    result = incremental_recalculate(
                        confirmed_routes=confirmed_routes,
                        confirmed_assignment=confirmed_assignment,
                        draft_assignment=draft_assignment,
                        rider_df=rider_df,
                        jobs_df=jobs_df,
                        settings=recalculation_settings(
                            True,
                            st.session_state.get("route_planner_onemap_token") or get_onemap_token() or None,
                            "duration",
                        ),
                        summary_builder=build_summary_from_routes,
                    )
            except Exception:
                LOGGER.exception("Route planner focus apply failed")
                for key, value in focus_apply_failure_state(st.session_state).items():
                    st.session_state[key] = value
                st.error("Routes could not be updated because one or more journeys could not be routed. Your changes have not been applied.")
            else:
                _commit_recalculation_result(state, draft_assignment, result)
                st.session_state["route_planner_focus_notice"] = (
                    f"Routes updated successfully. {len(result.affected_riders)} riders recalculated. "
                    f"{result.stats['reused_legs']} cached legs reused. "
                    f"{result.stats['onemap_requests']} new OneMap routes requested."
                )
                LOGGER.info(
                    "Route planner focus apply succeeded affected=%s green_reused=%s red_reused=%s onemap=%s",
                    result.affected_riders,
                    result.stats.get("reused_loaded", 0),
                    result.stats.get("reused_connectors", 0),
                    result.stats.get("onemap_requests", 0),
                )
                st.rerun()

    map_col, panel_col = st.columns([3, 1], gap="small")
    with panel_col:
        with st.container(height=720, border=True):
            st.markdown("#### Riders")
            show_col, hide_col = st.columns(2)
            show_all = show_col.button("Show All", width="stretch")
            hide_all = hide_col.button("Hide All", width="stretch")
            if show_all or hide_all:
                selected = rider_names if show_all else []
                st.session_state["route_planner_visible_riders"] = selected
                for rider in rider_names:
                    st.session_state[f"route_planner_visible_{hashlib.sha1(rider.encode()).hexdigest()[:10]}"] = rider in selected
                LOGGER.info("Route planner rider visibility changed visible=%s", selected)
                st.rerun()
            current_visible = set(st.session_state.get("route_planner_visible_riders", rider_names))
            selected_riders: list[str] = []
            for rider in rider_names:
                key = f"route_planner_visible_{hashlib.sha1(rider.encode()).hexdigest()[:10]}"
                if key not in st.session_state:
                    st.session_state[key] = rider in current_visible
                count = len(draft_assignment.get(rider, []))
                if st.checkbox(f"{rider} · {count} jobs", key=key):
                    selected_riders.append(rider)
            if selected_riders != list(st.session_state.get("route_planner_visible_riders", [])):
                st.session_state["route_planner_visible_riders"] = selected_riders
                LOGGER.info("Route planner rider visibility changed visible=%s", selected_riders)
            st.caption("Visibility changes the map only.")
            proposed = render_route_assignment_board(
                draft_assignment,
                jobs_by_id,
                state["summary_df"],
                rider_df,
                dark_mode=True,
            )
            if proposed is not None and proposed != draft_assignment:
                validation = validate_assignment_board(proposed, jobs_by_id, rider_names)
                if validation.is_valid and _store_draft_change(
                    draft_assignment, proposed, confirmed_assignment, rider_starts
                ):
                    st.rerun()
                if not validation.is_valid:
                    st.error("That move would create an invalid assignment.")
                    LOGGER.warning("Route planner focus drag validation failed errors=%s", validation.errors)
            if st.button("Reset Draft to Confirmed", width="stretch"):
                updated, undo_stack, redo_stack, changed = reset_draft(confirmed_assignment, draft_assignment)
                if changed:
                    st.session_state["route_planner_draft_assignment"] = updated
                    st.session_state["route_planner_undo_stack"] = undo_stack
                    st.session_state["route_planner_redo_stack"] = redo_stack
                    st.session_state["route_planner_is_dirty"] = False
                    st.session_state["route_planner_affected_riders"] = []
                    LOGGER.info("Route planner focus draft reset to confirmed")
                    st.rerun()

    with map_col:
        st.caption("Loaded job routes only · blue pickup · orange drop-off · connectors hidden while editing")
        pending_count, reused_count, _ = render_focus_green_map(
            draft_assignment,
            list(st.session_state.get("route_planner_visible_riders", rider_names)),
            confirmed_routes,
            jobs_df,
        )
        if pending_count:
            st.warning(f"{pending_count} visible job route(s) pending. They will be calculated when you apply.")
        LOGGER.debug("Route planner focus map green_reused=%s pending=%s", reused_count, pending_count)


def load_latest_optimiser_state(latest: dict[str, Any]) -> dict[str, Any]:
    route_df = latest["route_df"].copy()
    return {
        "source_sheet": "Latest optimiser result",
        "original_route_df": route_df.copy(),
        "route_df": route_df,
        "jobs_df": latest["jobs_df"].copy(),
        "rider_df": latest["rider_df"].copy(),
        "summary_df": latest["summary_df"].copy(),
        "lookup_warnings": list(latest.get("lookup_warnings", [])),
        "last_recalculated_at": "",
    }


def render_map_planner_focus(
    state: dict[str, Any],
    jobs_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    rider_names: list[str],
    rider_starts: dict[str, str],
    jobs_by_id: dict[str, dict[str, Any]],
) -> None:
    """Render the keyed 100dvh manager workspace and its on-demand connector preview."""

    st.markdown(
        """
        <style>
        html, body { overflow: hidden !important; }
        [data-testid="stSidebar"], [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
        [data-testid="stAppViewContainer"], [data-testid="stMain"], .block-container { width: 100vw !important; max-width: none !important; height: 100dvh !important; min-height: 0 !important; overflow: hidden !important; background: #080d16; color: #e5e7eb; }
        .block-container { padding: 0 !important; }
        .st-key-route_planner_focus_shell { position: fixed !important; inset: 0 !important; z-index: 9990; width: 100vw !important; height: 100dvh !important; min-height: 0 !important; overflow: hidden !important; background: #080d16; }
        .st-key-route_planner_focus_shell > div[data-testid="stVerticalBlock"] { display: grid !important; grid-template-rows: 56px minmax(0, 1fr) !important; gap: 0 !important; width: 100% !important; height: 100% !important; min-height: 0 !important; }
        .st-key-route_planner_focus_toolbar, .st-key-route_planner_focus_toolbar > div[data-testid="stVerticalBlock"] { height: 56px !important; min-height: 0 !important; overflow: hidden !important; }
        .st-key-route_planner_focus_toolbar { padding: 8px 10px; border-bottom: 1px solid #273244; background: #0c1320; }
        .st-key-route_planner_focus_workspace, .st-key-route_planner_focus_workspace > div[data-testid="stVerticalBlock"], .st-key-route_planner_focus_workspace [data-testid="stHorizontalBlock"], .st-key-route_planner_focus_workspace [data-testid="stColumn"] { width: 100% !important; height: 100% !important; min-height: 0 !important; overflow: hidden !important; }
        .st-key-route_planner_focus_workspace [data-testid="stHorizontalBlock"] { gap: 8px !important; padding: 8px; align-items: stretch !important; }
        .st-key-route_planner_focus_map, .st-key-route_planner_focus_map > div[data-testid="stVerticalBlock"], .st-key-route_planner_focus_map [data-testid="stDeckGlJsonChart"], .st-key-route_planner_focus_map [data-testid="stDeckGlJsonChart"] > div { width: 100% !important; height: 100% !important; min-height: 0 !important; overflow: hidden !important; }
        .st-key-route_planner_focus_panel { width: 100% !important; height: 100% !important; min-height: 0 !important; overflow: hidden !important; background: #111827 !important; border-color: #374151 !important; }
        .st-key-route_planner_focus_panel > div[data-testid="stVerticalBlock"] { width: 100% !important; height: 100% !important; min-height: 0 !important; overflow-y: auto !important; overflow-x: hidden !important; overscroll-behavior: contain; scrollbar-gutter: stable; padding-bottom: .5rem; }
        .st-key-route_planner_focus_panel iframe { display: block !important; width: 100% !important; min-width: 100% !important; overflow: visible !important; }
        .st-key-route_planner_focus_shell p, .st-key-route_planner_focus_shell label, .st-key-route_planner_focus_shell h1, .st-key-route_planner_focus_shell h2, .st-key-route_planner_focus_shell h3, .st-key-route_planner_focus_shell h4 { color: #e5e7eb !important; }
        .st-key-route_planner_focus_shell [data-testid="stCheckbox"] input { accent-color: #10b981; }
        .st-key-route_planner_focus_shell [data-testid="stAlert"] { background: #422006 !important; color: #fde68a !important; border: 1px solid #a16207; }
        .st-key-route_planner_focus_shell .stButton > button { background: #151d2b; color: #f9fafb; border-color: #4b5563; }
        .st-key-route_planner_focus_shell .stButton > button:hover { background: #1f2937; border-color: #10b981; }
        .st-key-route_planner_focus_shell .stButton > button:disabled { background: #111827; color: #6b7280; border-color: #273244; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    confirmed_routes = st.session_state["route_planner_confirmed_routes"]
    confirmed_assignment = clone_assignment(st.session_state["route_planner_confirmed_assignment"])
    draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
    dirty = bool(st.session_state.get("route_planner_is_dirty"))
    stale_riders = list(st.session_state.get("route_planner_preview_stale_riders", rider_names))
    locked_riders, locked_baselines = normalise_rider_locks(
        st.session_state.get("route_planner_locked_rider_ids", []),
        rider_names,
        draft_assignment,
        st.session_state.get("route_planner_locked_rider_baselines", {}),
    )
    st.session_state["route_planner_locked_rider_ids"] = locked_riders
    st.session_state["route_planner_locked_rider_baselines"] = locked_baselines
    preview_routes = st.session_state.get("route_planner_preview_routes", pd.DataFrame())
    total_jobs = sum(len(job_ids) for lane, job_ids in draft_assignment.items() if lane != UNASSIGNED_LANE)
    unlocked_riders = [rider for rider in rider_names if rider not in set(locked_riders)]
    can_reshuffle = len(unlocked_riders) >= 2 and any(draft_assignment.get(rider) for rider in unlocked_riders)

    with st.container(key="route_planner_focus_shell", height="stretch", width="stretch"):
        with st.container(key="route_planner_focus_toolbar", height=56, width="stretch"):
            bar = st.columns([1.95, 2.45, .5, .5, 1.1, 1.25, 1.55, 1.25], gap="small")
            bar[0].markdown(f"**Route Planner · {total_jobs} jobs · {len(rider_names)} riders**")
            bar[1].markdown(
                '<span style="font-size:.72rem"><b style="color:#22a34a">●</b> job '
                '<b style="color:#ef4444">●</b> access <b style="color:#a855f7">●</b> draft '
                '<b style="color:#0ea5e9">●</b> pickup <b style="color:#f97316">●</b> drop</span>',
                unsafe_allow_html=True,
            )
            undo_clicked = bar[2].button("Undo", disabled=not st.session_state.get("route_planner_undo_stack"), width="stretch")
            redo_clicked = bar[3].button("Redo", disabled=not st.session_state.get("route_planner_redo_stack"), width="stretch")
            refresh_clicked = bar[4].button("Refresh Exact", width="stretch", help="Refresh cached public-transport connector routes.")
            reshuffle_clicked = bar[5].button(
                f"Reshuffle · {len(locked_riders)} 🔒",
                disabled=not can_reshuffle,
                width="stretch",
                help="Bounded search across unlocked riders only.",
            )
            apply_clicked = bar[6].button("Apply Routes & Return", type="primary", disabled=not dirty, width="stretch")
            exit_clicked = bar[7].button("Exit With Draft Saved", width="stretch")

        if exit_clicked:
            st.session_state["route_planner_focus_mode"] = False
            st.session_state["route_planner_focus_notice"] = "Map Planner closed. Your unapplied draft is still saved." if dirty else "Map Planner closed."
            LOGGER.info("Route planner exited focus mode dirty=%s", dirty)
            st.rerun()

        if undo_clicked or redo_clicked:
            operation = undo_draft if undo_clicked else redo_draft
            updated, undo_stack, redo_stack, changed = operation(draft_assignment, st.session_state.get("route_planner_undo_stack", []), st.session_state.get("route_planner_redo_stack", []))
            if changed:
                lock_validation = validate_locked_rider_change(locked_baselines, updated, locked_riders)
                if not lock_validation.is_valid:
                    st.warning("Undo/redo was skipped because it would change a locked rider route.")
                    updated = draft_assignment
                    changed = False
            if changed:
                st.session_state["route_planner_draft_assignment"] = updated
                st.session_state["route_planner_undo_stack"] = undo_stack
                st.session_state["route_planner_redo_stack"] = redo_stack
                st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
                st.session_state["route_planner_affected_riders"] = detect_affected_riders(confirmed_assignment, updated)
                st.session_state["route_planner_preview_stale_riders"] = list(invalidate_red_preview(draft_assignment, updated, stale_riders))
                st.session_state["route_planner_board_revision"] = int(st.session_state.get("route_planner_board_revision", 0)) + 1
                LOGGER.info("Route planner focus %s", "undo" if undo_clicked else "redo")
                st.rerun()

        if reshuffle_clicked:
            with st.spinner("Searching bounded unlocked-rider alternatives..."):
                reshuffle = reshuffle_unlocked_assignments(
                    draft_assignment,
                    locked_riders,
                    st.session_state.get("route_planner_manual_move_history", {}),
                    rider_df,
                    jobs_df,
                )
            st.session_state["route_planner_reshuffle_notice"] = reshuffle.message
            if reshuffle.changed and _store_draft_change(
                draft_assignment,
                reshuffle.assignment,
                confirmed_assignment,
                rider_starts,
                record_manual=False,
            ):
                LOGGER.info("Route planner reshuffle stats=%s", reshuffle.stats)
                st.rerun()

        if refresh_clicked:
            try:
                refreshed = refresh_red_connector_preview(
                    confirmed_routes=confirmed_routes,
                    confirmed_assignment=confirmed_assignment,
                    draft_assignment=draft_assignment,
                    existing_preview_routes=preview_routes,
                    stale_riders=stale_riders,
                    rider_df=rider_df,
                    jobs_df=jobs_df,
                    use_onemap=True,
                    token=st.session_state.get("route_planner_onemap_token") or get_onemap_token() or None,
                    duration_multiplier=DEFAULT_EMPTY_TRAVEL_DURATION_MULTIPLIER,
                    wait_buffer_min=DEFAULT_EMPTY_TRAVEL_WAIT_BUFFER_MIN,
                )
            except (ValueError, TimeoutError, OSError) as exc:
                st.session_state["route_planner_preview_error"] = str(exc)
                LOGGER.exception("Route planner red preview refresh failed stale_riders=%s", stale_riders)
            else:
                st.session_state["route_planner_preview_routes"] = refreshed.route_df
                st.session_state["route_planner_preview_assignment_signature"] = refreshed.assignment_signature
                st.session_state["route_planner_preview_stale_riders"] = []
                st.session_state["route_planner_preview_stats"] = refreshed.stats
                st.session_state["route_planner_preview_error"] = ""
                st.session_state["route_planner_show_red_preview"] = True
                LOGGER.info("Route planner red preview refreshed stats=%s", refreshed.stats)
                st.rerun()

        if apply_clicked:
            validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
            lock_validation = validate_locked_rider_change(locked_baselines, draft_assignment, locked_riders)
            if not validation.is_valid or not lock_validation.is_valid:
                st.error("Routes could not be updated because the draft contains an invalid assignment.")
            else:
                affected = detect_affected_riders(confirmed_assignment, draft_assignment, rider_starts, rider_starts)
                matching_preview = matching_red_preview_routes(
                    preview_routes,
                    st.session_state.get("route_planner_preview_assignment_signature", ""),
                    draft_assignment,
                    stale_riders,
                )
                try:
                    with st.spinner(f"Recalculating {len(affected)} affected rider(s)..."):
                        result = incremental_recalculate(
                            confirmed_routes=confirmed_routes,
                            confirmed_assignment=confirmed_assignment,
                            draft_assignment=draft_assignment,
                            rider_df=rider_df,
                            jobs_df=jobs_df,
                            settings=recalculation_settings(True, st.session_state.get("route_planner_onemap_token") or get_onemap_token() or None, "duration"),
                            summary_builder=build_summary_from_routes,
                            matching_preview_routes=matching_preview,
                        )
                except (ValueError, TimeoutError, OSError):
                    LOGGER.exception("Route planner focus apply failed")
                    for key, value in focus_apply_failure_state(st.session_state).items():
                        st.session_state[key] = value
                    st.error("Routes could not be updated. Your changes have not been applied.")
                else:
                    _commit_recalculation_result(state, draft_assignment, result)
                    st.session_state["route_planner_focus_notice"] = f"Routes updated successfully. {len(result.affected_riders)} riders recalculated. {result.stats['reused_legs']} cached legs reused. {result.stats['onemap_requests']} new OneMap routes requested."
                    LOGGER.info("Route planner focus apply succeeded affected=%s stats=%s", result.affected_riders, result.stats)
                    st.rerun()

        with st.container(key="route_planner_focus_workspace", height="stretch", width="stretch"):
            map_col, panel_col = st.columns([3, 1], gap="small")
            with map_col:
                with st.container(key="route_planner_focus_map", height="stretch", width="stretch"):
                    if st.session_state.get("route_planner_preview_error"):
                        st.error("Red connector preview could not be refreshed. Your draft is unchanged.")
                    pending_count, reused_count, map_warnings = render_focus_green_map(
                        draft_assignment,
                        list(st.session_state.get("route_planner_visible_riders", rider_names)),
                        confirmed_routes,
                        jobs_df,
                        confirmed_assignment=confirmed_assignment,
                        rider_starts=rider_starts,
                        preview_routes=preview_routes,
                        rider_access_cache=st.session_state.get("route_planner_rider_access_cache", {}),
                    )
                    if pending_count:
                        st.warning(f"{pending_count} visible job route(s) pending. They will be calculated when you apply.")
                    if map_warnings:
                        st.warning(map_warnings[0] + (f" (+{len(map_warnings) - 1} more)" if len(map_warnings) > 1 else ""))
                    LOGGER.debug("Route planner focus map green_reused=%s pending=%s", reused_count, pending_count)
            with panel_col:
                with st.container(key="route_planner_focus_panel", height="stretch", width="stretch", border=True):
                    if st.session_state.get("route_planner_lock_warning"):
                        st.warning(st.session_state.pop("route_planner_lock_warning"))
                    notice = clean_text(st.session_state.get("route_planner_reshuffle_notice"))
                    if notice:
                        st.caption(notice)
                    st.multiselect(
                        "Locked riders",
                        options=rider_names,
                        key="route_planner_locked_rider_ids",
                        help="Locked rider sequences cannot be changed by drag, undo/redo, reset, reshuffle, or apply.",
                    )
                    show_col, hide_col = st.columns(2)
                    show_all = show_col.button("Show All", width="stretch")
                    hide_all = hide_col.button("Hide All", width="stretch")
                    if show_all or hide_all:
                        selected = rider_names if show_all else []
                        st.session_state["route_planner_visible_riders"] = selected
                        for rider in rider_names:
                            st.session_state[f"route_planner_visible_{hashlib.sha1(rider.encode()).hexdigest()[:10]}"] = rider in selected
                        st.rerun()
                    current_visible = set(st.session_state.get("route_planner_visible_riders", rider_names))
                    selected_riders: list[str] = []
                    for rider in rider_names:
                        key = f"route_planner_visible_{hashlib.sha1(rider.encode()).hexdigest()[:10]}"
                        if key not in st.session_state:
                            st.session_state[key] = rider in current_visible
                        if st.checkbox(f"{rider} · {len(draft_assignment.get(rider, []))} jobs", key=key):
                            selected_riders.append(rider)
                    st.session_state["route_planner_visible_riders"] = selected_riders
                    proposed = render_route_assignment_board(
                        draft_assignment,
                        jobs_by_id,
                        state["summary_df"],
                        rider_df,
                        dark_mode=True,
                        locked_rider_ids=locked_riders,
                        board_revision=int(st.session_state.get("route_planner_board_revision", 0)),
                    )
                    if proposed is not None and proposed != draft_assignment:
                        validation = validate_assignment_board(proposed, jobs_by_id, rider_names)
                        lock_validation = validate_locked_rider_change(locked_baselines, proposed, locked_riders)
                        if validation.is_valid and lock_validation.is_valid and _store_draft_change(draft_assignment, proposed, confirmed_assignment, rider_starts):
                            st.rerun()
                        if not validation.is_valid:
                            st.error("That move would create an invalid assignment.")
                        elif not lock_validation.is_valid:
                            st.session_state["route_planner_lock_warning"] = "That move was rejected because a locked rider route must stay unchanged."
                            st.session_state["route_planner_board_revision"] = int(st.session_state.get("route_planner_board_revision", 0)) + 1
                            LOGGER.warning("Route planner rejected locked drag errors=%s", lock_validation.errors)
                            st.rerun()
                    if st.button("Reset Draft to Confirmed", width="stretch"):
                        updated, undo_stack, redo_stack, changed = reset_draft(confirmed_assignment, draft_assignment)
                        if changed and not validate_locked_rider_change(locked_baselines, updated, locked_riders).is_valid:
                            st.warning("Reset was skipped because it would change a locked rider route.")
                            changed = False
                        if changed:
                            st.session_state["route_planner_draft_assignment"] = updated
                            st.session_state["route_planner_undo_stack"] = undo_stack
                            st.session_state["route_planner_redo_stack"] = redo_stack
                            st.session_state["route_planner_is_dirty"] = False
                            st.session_state["route_planner_affected_riders"] = []
                            st.session_state["route_planner_manual_move_history"] = {}
                            st.session_state["route_planner_draft_connectors"] = pd.DataFrame()
                            st.session_state["route_planner_board_revision"] = int(st.session_state.get("route_planner_board_revision", 0)) + 1
                            st.session_state["route_planner_preview_stale_riders"] = list(invalidate_red_preview(draft_assignment, updated, stale_riders))
                            st.rerun()


def render_route_results_summary(state: dict[str, Any]) -> None:
    """Compact confirmed-results screen; no map or assignment editor is rendered."""

    confirmed_routes = st.session_state["route_planner_confirmed_routes"]
    confirmed_assignment = clone_assignment(st.session_state["route_planner_confirmed_assignment"])
    draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
    dirty = bool(st.session_state.get("route_planner_is_dirty"))
    notice = clean_text(st.session_state.pop("route_planner_focus_notice", ""))
    st.title("Route Planner Results")
    if notice:
        st.success(notice)
    header, action = st.columns([3, 1])
    with header:
        if dirty:
            changed_riders = detect_affected_riders(confirmed_assignment, draft_assignment)
            before = _assignment_positions(confirmed_assignment)
            after = _assignment_positions(draft_assignment)
            changed_jobs = sum(before.get(job_id) != after.get(job_id) for job_id in set(before) | set(after))
            st.warning(
                f"Confirmed-route summary shown. An unapplied draft is saved with "
                f"{len(changed_riders)} changed rider(s) and {changed_jobs} changed order position(s)."
            )
        else:
            st.info("Confirmed routes are up to date and ready to export.")
    if action.button("Reopen Map Planner", type="primary", width="stretch"):
        for key, value in enter_focus_mode_state(st.session_state, state["rider_df"]["Rider Name"].apply(clean_text).tolist()).items():
            st.session_state[key] = value
        LOGGER.info("Route planner reopened from results summary")
        st.rerun()

    summary = build_compact_rider_summary(
        confirmed_routes,
        state["rider_df"],
        duration_limit_min=DEFAULT_MAX_ADJUSTED_DURATION_MIN,
    )
    if summary.empty:
        st.info("No confirmed rider routes are available.")
    else:
        def workload_style(row: pd.Series) -> list[str]:
            colour = {"Heavy": "#5f1d24", "Balanced": "#153f35", "Light": "#1e3555"}.get(clean_text(row.get("Workload")), "")
            return [f"background-color: {colour}" if colour else "" for _ in row]

        st.dataframe(summary.style.apply(workload_style, axis=1), width="stretch", hide_index=True)

    export_bytes = None
    if not dirty:
        export_bytes = export_routes_to_excel(
            confirmed_routes,
            state["summary_df"],
            jobs_df=state["jobs_df"],
            lookup_warnings=state.get("lookup_warnings", []),
        )
    st.download_button(
        "Export Updated Workbook",
        data=export_bytes or b"",
        file_name="vehicle_route_optimisation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=dirty,
        width="stretch",
        on_click=lambda: LOGGER.info("Route planner confirmed workbook exported rows=%s", len(confirmed_routes)),
    )


def run_route_planner_screen_flow() -> None:
    """State A load screen, State B focus planner, or State C confirmed summary."""

    existing_state = st.session_state.get("bluesg_map_viewer_state")
    if existing_state is None:
        st.title("Route Planner")
        st.caption("Load a completed optimizer workbook to begin map planning.")
        latest = st.session_state.get("bluesg_latest_optimisation")
        token = st.text_input(
            "OneMap token",
            value=get_onemap_token(),
            type="password",
            key="route_planner_onemap_token",
            help="Used only when you explicitly refresh connectors or apply routes.",
        )
        if not token and not onemap_credentials_configured():
            st.warning("Configure a OneMap token or credentials before refreshing route previews.")
        uploaded = st.file_uploader("Upload vehicle_route_optimisation.xlsx", type=["xlsx", "xls"])
        if uploaded is not None:
            st.caption(f"Selected workbook: {uploaded.name}")
        load_cols = st.columns(2)
        load_uploaded = load_cols[0].button("Load uploaded workbook", disabled=uploaded is None, type="primary", width="stretch")
        open_latest = load_cols[1].button("Open latest optimizer result", disabled=not bool(latest), width="stretch")
        loaded_state: dict[str, Any] | None = None
        workbook_id = ""
        if load_uploaded and uploaded is not None:
            file_bytes = uploaded.getvalue()
            workbook_id = file_signature(file_bytes)
            try:
                loaded_state = load_route_workbook(file_bytes)
            except (ValueError, KeyError, OSError) as exc:
                LOGGER.exception("Route planner workbook load failed")
                st.error(f"The workbook could not be loaded: {exc}")
        elif open_latest and latest:
            loaded_state = load_latest_optimiser_state(latest)
            workbook_id = f"session-{route_source_signature(loaded_state['route_df'])}"
        if loaded_state is None:
            st.info("No route workbook is currently loaded.")
            return
        st.session_state.bluesg_map_viewer_state = loaded_state
        st.session_state.bluesg_map_viewer_file_signature = workbook_id
        initialise_route_planner(loaded_state, workbook_id)
        st.session_state["route_planner_focus_mode"] = True
        st.session_state["route_planner_preview_stale_riders"] = loaded_state["rider_df"]["Rider Name"].apply(clean_text).tolist()
        LOGGER.info("Route planner workbook loaded and focus mode entered signature=%s", workbook_id[:12])
        st.rerun()

    state = st.session_state.bluesg_map_viewer_state
    workbook_id = str(st.session_state.get("bluesg_map_viewer_file_signature") or "active-workbook")
    if st.session_state.get("route_planner_workbook_id") != workbook_id:
        initialise_route_planner(state, workbook_id)
        st.session_state["route_planner_focus_mode"] = True
        st.session_state["route_planner_preview_stale_riders"] = state["rider_df"]["Rider Name"].apply(clean_text).tolist()
    jobs_df = state["jobs_df"]
    rider_df = state["rider_df"]
    rider_names = rider_df["Rider Name"].apply(clean_text).dropna().tolist()
    rider_starts = {
        clean_text(row.get("Rider Name")): clean_text(row.get("Start Location"))
        for _, row in rider_df.iterrows()
    }
    if st.session_state.get("route_planner_focus_mode"):
        render_map_planner_focus(state, jobs_df, rider_df, rider_names, rider_starts, build_jobs_by_stable_id(jobs_df))
        st.stop()
    render_route_results_summary(state)


run_route_planner_screen_flow()
st.stop()


focus_mode_requested = bool(
    st.session_state.get("route_planner_focus_mode")
    and st.session_state.get("bluesg_map_viewer_state")
)
latest_optimisation = st.session_state.get("bluesg_latest_optimisation")
uploaded_file = None
load_latest_clicked = False
if not focus_mode_requested:
    st.title("Route Planner")
    st.caption("Drag orders between riders, preview the change, then recalculate and export.")
    load_cols = st.columns([2, 1])
    with load_cols[0]:
        uploaded_file = st.file_uploader(
            "Upload vehicle_route_optimisation.xlsx",
            type=["xlsx", "xls"],
            help="Use the Excel file downloaded from the Vehicle Route Optimiser.",
        )
    with load_cols[1]:
        load_latest_clicked = st.button(
            "Open latest optimiser result",
            disabled=not bool(latest_optimisation),
            width="stretch",
            help="Uses the result from this Streamlit session without downloading and uploading it again.",
        )

workbook_id = ""
if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    workbook_id = file_signature(file_bytes)
    if st.session_state.get("bluesg_map_viewer_file_signature") != workbook_id:
        try:
            st.session_state.bluesg_map_viewer_state = load_route_workbook(file_bytes)
        except Exception as exc:
            st.error(f"Could not load exported route workbook: {exc}")
            st.stop()
        st.session_state.bluesg_map_viewer_file_signature = workbook_id
        LOGGER.info("Route planner workbook loaded source=upload signature=%s", workbook_id[:12])
elif load_latest_clicked and latest_optimisation:
    latest_signature = route_source_signature(latest_optimisation["route_df"])
    workbook_id = f"session-{latest_signature}"
    st.session_state.bluesg_map_viewer_state = load_latest_optimiser_state(latest_optimisation)
    st.session_state.bluesg_map_viewer_file_signature = workbook_id
    LOGGER.info("Route planner workbook loaded source=session signature=%s", latest_signature[:12])
elif st.session_state.get("bluesg_map_viewer_state"):
    workbook_id = str(st.session_state.get("bluesg_map_viewer_file_signature") or "legacy-session")
else:
    st.info("Upload an optimiser workbook or open the latest optimiser result.")
    st.stop()

state = st.session_state.bluesg_map_viewer_state
if st.session_state.get("route_planner_workbook_id") != workbook_id:
    initialise_route_planner(state, workbook_id)
    st.session_state.bluesg_map_viewer_selected_rider = "All riders"
    st.session_state.bluesg_map_viewer_selected_sequence = "All"

route_df = st.session_state["route_planner_confirmed_routes"]
state["route_df"] = route_df
jobs_df = state["jobs_df"]
rider_df = state["rider_df"]
summary_df = state["summary_df"]

jobs_by_id = build_jobs_by_stable_id(jobs_df)
rider_names = rider_df["Rider Name"].apply(clean_text).dropna().tolist()
rider_starts = {
    clean_text(row.get("Rider Name")): clean_text(row.get("Start Location"))
    for _, row in rider_df.iterrows()
}

if st.session_state.get("route_planner_focus_mode"):
    render_map_planner_focus(state, jobs_df, rider_df, rider_names, rider_starts, jobs_by_id)
    st.stop()

notice = clean_text(st.session_state.pop("route_planner_focus_notice", ""))
if notice:
    st.success(notice)

top_cols = st.columns([2, 1])
with top_cols[0]:
    st.caption(f"Loaded sheet: {state.get('source_sheet', '-')}")
    if state.get("last_recalculated_at"):
        st.caption(f"Last recalculated: {state['last_recalculated_at']}")
with top_cols[1]:
    map_token = st.text_input(
        "OneMap token",
        value=get_onemap_token(),
        type="password",
        key="route_planner_onemap_token",
        help="Used for geocoding the map and for route recalculation.",
    )
    if not map_token and not onemap_credentials_configured():
        st.warning("No OneMap token or credentials found. Map geocoding may fail.")

render_summary(route_df, summary_df)

draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
confirmed_assignment = clone_assignment(st.session_state["route_planner_confirmed_assignment"])

open_planner_col, _ = st.columns([1, 2.2])
if open_planner_col.button("Open Map Planner", type="primary", width="stretch"):
    for key, value in enter_focus_mode_state(st.session_state, rider_names).items():
        st.session_state[key] = value
    visible = set(st.session_state["route_planner_visible_riders"])
    for rider in rider_names:
        st.session_state[f"route_planner_visible_{hashlib.sha1(rider.encode()).hexdigest()[:10]}"] = rider in visible
    LOGGER.info("Route planner entered focus mode visible_riders=%s", sorted(visible))
    st.rerun()

planner_col, map_col = st.columns([1, 1.85], gap="large")

with planner_col:
        st.subheader("Assign Orders")
        st.caption("Drag cards within a rider to reorder, or between lanes to reassign. Sequence follows card position.")
        proposed = render_route_assignment_board(draft_assignment, jobs_by_id, summary_df, rider_df)
        if proposed is not None and proposed != draft_assignment:
            validation = validate_assignment_board(proposed, jobs_by_id, rider_names)
            if validation.is_valid:
                updated, undo_stack, redo_stack, changed = update_draft_history(
                    draft_assignment,
                    proposed,
                    st.session_state.get("route_planner_undo_stack", []),
                    st.session_state.get("route_planner_redo_stack", []),
                    HISTORY_LIMIT,
                )
                if changed:
                    affected = detect_affected_riders(confirmed_assignment, updated, rider_starts, rider_starts)
                    st.session_state["route_planner_draft_assignment"] = updated
                    st.session_state["route_planner_undo_stack"] = undo_stack
                    st.session_state["route_planner_redo_stack"] = redo_stack
                    st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
                    st.session_state["route_planner_affected_riders"] = affected
                    LOGGER.info("Route planner draft changed affected_riders=%s", affected)
                    before_positions = {
                        job_id: (lane, position)
                        for lane, job_ids in draft_assignment.items()
                        for position, job_id in enumerate(job_ids, start=1)
                    }
                    after_positions = {
                        job_id: (lane, position)
                        for lane, job_ids in updated.items()
                        for position, job_id in enumerate(job_ids, start=1)
                    }
                    for job_id in sorted(set(before_positions) | set(after_positions)):
                        before = before_positions.get(job_id)
                        after = after_positions.get(job_id)
                        if before == after:
                            continue
                        if before and after and before[0] != after[0]:
                            LOGGER.info(
                                "Route planner job moved job_id=%s from=%s[%s] to=%s[%s]",
                                job_id,
                                before[0],
                                before[1],
                                after[0],
                                after[1],
                            )
                        else:
                            LOGGER.info(
                                "Route planner sequence changed job_id=%s before=%s after=%s",
                                job_id,
                                before,
                                after,
                            )
                    st.rerun()
            else:
                LOGGER.warning("Route planner draft validation failed errors=%s", validation.errors)
                st.error("; ".join(validation.errors))

        action_cols = st.columns(3)
        undo_clicked = action_cols[0].button("Undo", disabled=not st.session_state.get("route_planner_undo_stack"), width="stretch")
        redo_clicked = action_cols[1].button("Redo", disabled=not st.session_state.get("route_planner_redo_stack"), width="stretch")
        reset_clicked = action_cols[2].button("Reset to Original", width="stretch")
        if undo_clicked:
            updated, undo_stack, redo_stack, changed = undo_draft(
                draft_assignment,
                st.session_state.get("route_planner_undo_stack", []),
                st.session_state.get("route_planner_redo_stack", []),
            )
            if changed:
                st.session_state["route_planner_draft_assignment"] = updated
                st.session_state["route_planner_undo_stack"] = undo_stack
                st.session_state["route_planner_redo_stack"] = redo_stack
                st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
                st.session_state["route_planner_affected_riders"] = detect_affected_riders(confirmed_assignment, updated)
                LOGGER.info("Route planner undo")
                st.rerun()
        if redo_clicked:
            updated, undo_stack, redo_stack, changed = redo_draft(
                draft_assignment,
                st.session_state.get("route_planner_undo_stack", []),
                st.session_state.get("route_planner_redo_stack", []),
            )
            if changed:
                st.session_state["route_planner_draft_assignment"] = updated
                st.session_state["route_planner_undo_stack"] = undo_stack
                st.session_state["route_planner_redo_stack"] = redo_stack
                st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
                st.session_state["route_planner_affected_riders"] = detect_affected_riders(confirmed_assignment, updated)
                LOGGER.info("Route planner redo")
                st.rerun()
        if reset_clicked:
            updated, undo_stack, redo_stack, changed = reset_draft(
                st.session_state["route_planner_original_assignment"], draft_assignment
            )
            st.session_state["route_planner_draft_assignment"] = updated
            st.session_state["route_planner_undo_stack"] = undo_stack
            st.session_state["route_planner_redo_stack"] = redo_stack
            st.session_state["route_planner_is_dirty"] = updated != confirmed_assignment
            st.session_state["route_planner_affected_riders"] = detect_affected_riders(confirmed_assignment, updated)
            LOGGER.info("Route planner reset to original changed=%s", changed)
            st.rerun()

        use_onemap_recalc = st.toggle("Use OneMap recalculation", value=True)
        optimise_by_label = st.radio("Optimise metric", ["Duration", "Distance"], horizontal=True)
        dirty = bool(st.session_state.get("route_planner_is_dirty"))
        apply_clicked = st.button("Apply & Recalculate", type="primary", disabled=not dirty, width="stretch")
        if apply_clicked:
            draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
            validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
            if not validation.is_valid:
                LOGGER.warning("Route planner apply validation failed errors=%s", validation.errors)
                st.error("; ".join(validation.errors))
            else:
                affected = detect_affected_riders(confirmed_assignment, draft_assignment, rider_starts, rider_starts)
                LOGGER.info("Route planner recalculation started affected_riders=%s", affected)
                started_at = time.monotonic()
                try:
                    with st.status(f"Recalculating {len(affected)} affected rider(s)", expanded=True) as progress:
                        st.write("Reusing confirmed loaded journeys and unchanged connectors...")
                        result = incremental_recalculate(
                            confirmed_routes=route_df,
                            confirmed_assignment=confirmed_assignment,
                            draft_assignment=draft_assignment,
                            rider_df=rider_df,
                            jobs_df=jobs_df,
                            settings=recalculation_settings(use_onemap_recalc, map_token or None, optimise_by_label.lower()),
                            summary_builder=build_summary_from_routes,
                        )
                        st.write(f"Reused {result.stats['reused_legs']} confirmed route legs")
                        st.write(f"Used {result.stats['cache_hits']} cached route lookups")
                        st.write(f"Requested {result.stats['onemap_requests']} new OneMap routes")
                        st.write("Validation passed")
                        progress.update(label="Route plan recalculated", state="complete")
                except Exception as exc:
                    LOGGER.exception("Route planner apply failed")
                    st.error(f"Could not apply route changes: {exc}")
                else:
                    st.session_state["route_planner_confirmed_routes"] = result.route_df.copy()
                    st.session_state["route_planner_confirmed_assignment"] = clone_assignment(draft_assignment)
                    st.session_state["route_planner_draft_assignment"] = clone_assignment(draft_assignment)
                    st.session_state["route_planner_is_dirty"] = False
                    st.session_state["route_planner_redo_stack"] = []
                    st.session_state["route_planner_affected_riders"] = []
                    st.session_state["route_planner_last_apply_stats"] = result.stats
                    state["route_df"] = result.route_df.copy()
                    state["summary_df"] = result.summary_df.copy()
                    state["lookup_warnings"] = result.warnings
                    state["last_recalculated_at"] = f"{time.monotonic() - started_at:.1f}s recalculation"
                    st.session_state.bluesg_map_viewer_state = state
                    LOGGER.info("Route planner apply succeeded affected_riders=%s stats=%s", result.affected_riders, result.stats)
                    st.success("Route plan updated and validated.")
                    st.rerun()

        if st.session_state.get("route_planner_is_dirty"):
            st.warning("Draft changes are not yet recalculated. Apply & Recalculate before exporting.")
        export_bytes = None
        if not st.session_state.get("route_planner_is_dirty"):
            export_bytes = export_routes_to_excel(
                state["route_df"], state["summary_df"], jobs_df=jobs_df, lookup_warnings=state.get("lookup_warnings", [])
            )
        st.download_button(
            "Export Updated Workbook",
            data=export_bytes or b"",
            file_name="vehicle_route_optimisation.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=export_bytes is None,
            width="stretch",
            on_click=lambda: LOGGER.info(
                "Route planner export downloaded rows=%s", len(state["route_df"])
            ),
        )
        if export_bytes is not None:
            LOGGER.debug("Route planner export prepared rows=%s", len(state["route_df"]))

draft_assignment = clone_assignment(st.session_state["route_planner_draft_assignment"])
if st.session_state.get("route_planner_is_dirty"):
    preview_routes, preview_stats = build_draft_preview_routes(
        route_df, confirmed_assignment, draft_assignment, jobs_df, rider_starts
    )
    confirmed_signatures = build_route_leg_signatures(confirmed_assignment, jobs_by_id, rider_starts)
    draft_signatures = build_route_leg_signatures(draft_assignment, jobs_by_id, rider_starts)
    changed_legs = detect_changed_route_legs(confirmed_signatures, draft_signatures)["changed"]
else:
    preview_routes = route_df
    preview_stats = {"known_duration_min": round(numeric_sum(route_df, "Total Duration Min"), 1), "pending_route_legs": 0}
    changed_legs = []

with map_col:
    control_cols = st.columns([2, 1, 1])
    control_cols[0].subheader("Map")
    if st.session_state.get("route_planner_is_dirty"):
        control_cols[1].metric("Known duration", f"{preview_stats['known_duration_min']:.1f} min")
        control_cols[2].metric("Pending legs", preview_stats["pending_route_legs"])
        st.warning("Draft preview — accurate routing has not been recalculated. Straight pending connectors are not OneMap routes.")
        if changed_legs:
            st.caption(f"{len(changed_legs)} route-leg signature(s) changed. Confirmed loaded paths are reused in this preview.")
    render_map(preview_routes, state["rider_df"], map_token or None)

with st.expander("Current route rows", expanded=False):
    visible_columns = [
        "Rider",
        "Sequence",
        "Car Plate",
        "Start From",
        "Pickup Address",
        "Drop-off Address",
        "Total Distance KM",
        "Total Duration Min",
        "Cost Source",
        "Route Validation Status",
    ]
    visible_columns = [column for column in visible_columns if column in state["route_df"].columns]
    st.dataframe(state["route_df"][visible_columns], width="stretch", hide_index=True)

with st.expander("Rider summary", expanded=False):
    summary_columns = [column for column in SUMMARY_COLUMNS if column in state["summary_df"].columns]
    st.dataframe(state["summary_df"][summary_columns], width="stretch", hide_index=True)
