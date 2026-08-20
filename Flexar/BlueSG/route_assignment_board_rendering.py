"""Shared drag-and-drop assignment board rendering.

Extracted from the full Route Planner page
(`pages/review_map_and_manually_adjust_route_assignments_page.py`) so any other
page - the hourly dispatch page included - can seed and render the same
HTML5-drag Kanban board (`components/drag_and_drop_route_assignment_board`)
without duplicating the label-encoding logic. Everything here is a thin
Streamlit-facing wrapper: the actual board data model (`Assignment`,
`assignment_from_routes`, `validate_assignment_board`, ...) lives in
`manual_route_assignment_editing_and_recalculation.py` and stays
Streamlit-free.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import pandas as pd
import streamlit as st

from .build_optimised_vehicle_routes import clean_text
from .components.register_drag_and_drop_route_assignment_board import ROUTE_BOARD_COMPONENT
from .manual_route_assignment_editing_and_recalculation import (
    RESHUFFLE_POOL_LANE,
    UNASSIGNED_LANE,
    clone_assignment,
    normalise_assignment_board,
)

LOGGER = logging.getLogger(__name__)


def assignment_signature(assignment: dict[str, list[str]]) -> str:
    return hashlib.sha1(json.dumps(assignment, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def short_location(value: object, limit: int = 34) -> str:
    text = clean_text(value)
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


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
    reshuffle_pool_job_ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], list[str]]:
    """Build display-only strings with exact reversible mappings to stable IDs."""

    rider_names = rider_df["Rider Name"].apply(clean_text).dropna().tolist()
    pool = [job_id for job_id in reshuffle_pool_job_ids or [] if job_id in jobs_by_id]
    display_assignment = clone_assignment(assignment)
    if pool:
        pool_set = set(pool)
        for lane in display_assignment:
            display_assignment[lane] = [job_id for job_id in display_assignment[lane] if job_id not in pool_set]
    display_assignment[RESHUFFLE_POOL_LANE] = pool
    lane_order = [RESHUFFLE_POOL_LANE, *rider_names, UNASSIGNED_LANE]
    max_jobs_by_rider = {
        clean_text(row.get("Rider Name")): pd.to_numeric(pd.Series([row.get("Max Jobs")]), errors="coerce").iloc[0]
        for _, row in rider_df.iterrows()
    }
    starts_by_rider = {
        clean_text(row.get("Rider Name")): clean_text(row.get("Start Location"))
        for _, row in rider_df.iterrows()
    }
    board: list[dict[str, Any]] = []
    header_to_lane: dict[str, str] = {}
    card_to_job_id: dict[str, str] = {}
    locked = set(locked_rider_ids or [])
    for lane_index, lane in enumerate(lane_order, start=1):
        jobs = display_assignment.get(lane, [])
        display_name = "Reshuffle Pool" if lane == RESHUFFLE_POOL_LANE else ("Unassigned" if lane == UNASSIGNED_LANE else lane)
        duration = 0.0 if lane in {UNASSIGNED_LANE, RESHUFFLE_POOL_LANE} else lane_duration(summary_df, lane)
        max_jobs = max_jobs_by_rider.get(lane)
        over_jobs = lane != UNASSIGNED_LANE and pd.notna(max_jobs) and float(max_jobs) > 0 and len(jobs) > int(max_jobs)
        warning = " ⚠" if over_jobs or duration > 180 or lane == UNASSIGNED_LANE and jobs else ""
        duration_label = "drop orders here" if lane == RESHUFFLE_POOL_LANE else ("not routed" if lane == UNASSIGNED_LANE else f"{duration:.0f} confirmed min")
        lock_icon = " 🔒" if lane in locked else (" 🔓" if lane not in {UNASSIGNED_LANE, RESHUFFLE_POOL_LANE} else "")
        header = f"{display_name} · {len(jobs)} orders · {duration_label}{warning} · lane-{lane_index:02d}{lock_icon}"
        start_line = f"\nStart: {starts_by_rider.get(lane) or 'Address unavailable'}" if lane not in {UNASSIGNED_LANE, RESHUFFLE_POOL_LANE} else ""
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
        board.append(
            {
                "header": header,
                "display_header": f"{display_name} · {len(jobs)} orders · {duration_label}{warning}{start_line}",
                "lane_id": lane,
                "is_pool": lane == RESHUFFLE_POOL_LANE,
                "items": cards,
            }
        )
    return board, header_to_lane, card_to_job_id, lane_order


def render_route_assignment_board(
    assignment: dict[str, list[str]],
    jobs_by_id: dict[str, dict[str, Any]],
    summary_df: pd.DataFrame,
    rider_df: pd.DataFrame,
    *,
    dark_mode: bool = False,
    locked_rider_ids: list[str] | None = None,
    reshuffle_pool_job_ids: list[str] | None = None,
    board_revision: int = 0,
    return_metadata: bool = False,
    can_reshuffle_from_pool: bool = False,
    highlighted_rider_ids: list[str] | None = None,
) -> dict[str, list[str]] | tuple[dict[str, list[str]] | None, list[str] | None, list[str] | None, str] | None:
    board, header_to_lane, card_to_job_id, lane_order = build_sortable_board(
        assignment, jobs_by_id, summary_df, rider_df, locked_rider_ids, reshuffle_pool_job_ids
    )
    component_value = ROUTE_BOARD_COMPONENT(
        board=board,
        locked_rider_ids=sorted(locked_rider_ids or []),
        highlighted_rider_ids=sorted(highlighted_rider_ids or []),
        can_reshuffle=bool(can_reshuffle_from_pool),
        key=f"route_planner_board_{assignment_signature(assignment)}_{assignment_signature({'locked': sorted(locked_rider_ids or []), 'pool': sorted(reshuffle_pool_job_ids or [])})}_{board_revision}",
        default=None,
    )
    if not isinstance(component_value, dict):
        return (None, None, None, "") if return_metadata else None
    raw_board = component_value.get("board")
    returned_locks = [clean_text(rider) for rider in component_value.get("locked_rider_ids", []) if clean_text(rider)]
    returned_highlights = [clean_text(rider) for rider in component_value.get("highlighted_rider_ids", []) if clean_text(rider)]
    component_event = clean_text(component_value.get("event"))
    try:
        normalised = normalise_assignment_board(raw_board, header_to_lane, card_to_job_id, lane_order)
        return (normalised, returned_locks, returned_highlights, component_event) if return_metadata else normalised
    except ValueError as exc:
        LOGGER.warning("Route assignment board validation failed: %s", exc)
        st.error(str(exc))
        return (None, returned_locks, returned_highlights, component_event) if return_metadata else None
