import copy
import hashlib
import json
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


st.title("Route Map Viewer")
st.caption("Upload an optimiser export, move orders between riders, recalculate, and inspect the route map.")

uploaded_file = st.file_uploader(
    "Upload vehicle_route_optimisation.xlsx",
    type=["xlsx", "xls"],
    help="Use the Excel file downloaded from the Vehicle Route Optimiser.",
)

if uploaded_file is None:
    st.info("Upload an exported route workbook to load the map viewer.")
    st.stop()

file_bytes = uploaded_file.getvalue()
signature = file_signature(file_bytes)
if st.session_state.get("bluesg_map_viewer_file_signature") != signature:
    try:
        st.session_state.bluesg_map_viewer_state = load_route_workbook(file_bytes)
    except Exception as exc:
        st.error(f"Could not load exported route workbook: {exc}")
        st.stop()
    st.session_state.bluesg_map_viewer_file_signature = signature
    st.session_state.bluesg_map_viewer_history = []
    st.session_state.bluesg_map_viewer_selected_rider = "All riders"
    st.session_state.bluesg_map_viewer_selected_sequence = "All"

state = st.session_state.bluesg_map_viewer_state
route_df = state["route_df"]
jobs_df = state["jobs_df"]
rider_df = state["rider_df"]
summary_df = state["summary_df"]

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
        help="Used for geocoding the map and for route recalculation.",
    )
    if not map_token and not onemap_credentials_configured():
        st.warning("No OneMap token or credentials found. Map geocoding may fail.")

render_summary(route_df, summary_df)

editor_col, map_col = st.columns([1, 1.45], gap="large")

with editor_col:
    st.subheader("Move Orders")
    st.caption("Change Rider and Sequence, then apply. Recalculation updates Start From, travel legs, and the map.")

    rider_names = rider_df["Rider Name"].apply(clean_text).dropna().tolist()
    editor_df = assignment_editor_df(route_df)
    editor_key = f"bluesg_map_assignment_editor_{route_source_signature(route_df)[:12]}"
    edited_assignments = st.data_editor(
        editor_df,
        key=editor_key,
        hide_index=True,
        width="stretch",
        height=420,
        disabled=["Job Key", "Uploaded Row", "Car Plate", "Pickup", "Drop-off"],
        column_config={
            "Job Key": st.column_config.TextColumn(),
            "Rider": st.column_config.SelectboxColumn(options=rider_names, required=True),
            "Sequence": st.column_config.NumberColumn(min_value=1, step=1, required=True),
            "Uploaded Row": st.column_config.NumberColumn(),
            "Car Plate": st.column_config.TextColumn(),
            "Pickup": st.column_config.TextColumn(),
            "Drop-off": st.column_config.TextColumn(),
        },
    )

    settings_cols = st.columns(2)
    with settings_cols[0]:
        use_onemap_recalc = st.toggle("Use OneMap recalculation", value=True)
    with settings_cols[1]:
        optimise_by_label = st.radio("Optimise metric", ["Duration", "Distance"], horizontal=True)

    action_cols = st.columns(3)
    apply_clicked = action_cols[0].button("Apply Changes", type="primary", width="stretch")
    undo_clicked = action_cols[1].button("Undo", width="stretch")
    reset_clicked = action_cols[2].button("Reset", width="stretch")

    if apply_clicked:
        history = list(st.session_state.get("bluesg_map_viewer_history", []))
        history.append(copy.deepcopy(state))
        st.session_state.bluesg_map_viewer_history = history[-10:]
        settings = recalculation_settings(
            use_onemap=use_onemap_recalc,
            token=map_token or None,
            optimise_by=optimise_by_label.lower(),
        )
        try:
            started_at = time.monotonic()
            with st.spinner("Recalculating edited route plan..."):
                new_route_df, new_summary_df, lookup_warnings = recalculate_routes_from_editor(
                    edited_assignments,
                    rider_df,
                    jobs_df,
                    settings,
                )
            integrity = optimisation_integrity_report(new_route_df, jobs_df)
            if not integrity["is_valid"]:
                st.error(integrity["message"])
                st.stop()
        except Exception as exc:
            st.error(f"Could not apply route changes: {exc}")
        else:
            state["route_df"] = new_route_df.copy()
            state["summary_df"] = new_summary_df.copy()
            state["lookup_warnings"] = lookup_warnings
            state["last_recalculated_at"] = f"{time.monotonic() - started_at:.1f}s recalculation"
            st.session_state.bluesg_map_viewer_state = state
            st.success("Route plan updated.")
            st.rerun()

    if undo_clicked:
        history = list(st.session_state.get("bluesg_map_viewer_history", []))
        if history:
            st.session_state.bluesg_map_viewer_state = history.pop()
            st.session_state.bluesg_map_viewer_history = history
            st.rerun()
        else:
            st.info("No previous map edit to undo.")

    if reset_clicked:
        state["route_df"] = state["original_route_df"].copy()
        state["summary_df"] = build_summary_from_routes(state["route_df"])
        state["lookup_warnings"] = []
        state["last_recalculated_at"] = ""
        st.session_state.bluesg_map_viewer_state = state
        st.session_state.bluesg_map_viewer_history = []
        st.rerun()

    if state.get("lookup_warnings"):
        with st.expander("Recalculation warnings", expanded=False):
            for warning in state["lookup_warnings"][:80]:
                st.warning(warning)
            if len(state["lookup_warnings"]) > 80:
                st.info(f"Showing first 80 of {len(state['lookup_warnings'])} warning(s).")

    st.download_button(
        "Download Current Route Workbook",
        data=export_routes_to_excel(
            state["route_df"],
            state["summary_df"],
            jobs_df=state["jobs_df"],
            lookup_warnings=state.get("lookup_warnings", []),
        ),
        file_name="vehicle_route_map_viewer_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with map_col:
    st.subheader("Map")
    render_map(state["route_df"], state["rider_df"], map_token or None)

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
