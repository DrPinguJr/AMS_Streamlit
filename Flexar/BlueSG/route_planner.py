"""Pure assignment and incremental-recalculation helpers for the BlueSG planner."""

from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
from typing import Any, Callable, Iterable

import pandas as pd

from .vehicle_route_optimizer import (
    ROUTE_COLUMNS,
    TravelCost,
    adjust_empty_travel_for_public_transport,
    build_jobs_by_stable_id,
    clean_text,
    get_stored_geocode,
    get_empty_travel_cost,
    find_best_selective_reshuffle,
    optimisation_integrity_report,
    rebuild_outputs_from_sequences,
    stable_job_id_from_route_row,
    validate_riders,
)


UNASSIGNED_LANE = "__UNASSIGNED__"
RESHUFFLE_POOL_LANE = "__RESHUFFLE_POOL__"
HISTORY_LIMIT = 15
Assignment = dict[str, list[str]]


@dataclass(frozen=True)
class AssignmentValidation:
    is_valid: bool
    errors: tuple[str, ...]
    missing_job_ids: tuple[str, ...] = ()
    duplicate_job_ids: tuple[str, ...] = ()
    unknown_job_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecalculationResult:
    route_df: pd.DataFrame
    summary_df: pd.DataFrame
    warnings: list[str]
    affected_riders: list[str]
    stats: dict[str, int]


@dataclass(frozen=True)
class FocusMapResult:
    route_df: pd.DataFrame
    marker_df: pd.DataFrame
    pending_job_ids: tuple[str, ...]
    visible_job_count: int


@dataclass(frozen=True)
class RedPreviewResult:
    route_df: pd.DataFrame
    assignment_signature: str
    stale_riders: tuple[str, ...]
    stats: dict[str, int]


@dataclass(frozen=True)
class DraftConnectorResult:
    route_df: pd.DataFrame
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RiderAccessResult:
    route_df: pd.DataFrame
    cache: dict[str, dict[str, Any]]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ReshuffleResult:
    assignment: Assignment
    changed: bool
    message: str
    stats: dict[str, Any]


def clone_assignment(assignment: Assignment) -> Assignment:
    return {str(lane): [str(job_id) for job_id in jobs] for lane, jobs in assignment.items()}


def assignment_from_routes(route_df: pd.DataFrame, jobs_df: pd.DataFrame, rider_names: Iterable[str]) -> Assignment:
    """Build a complete board, including jobs absent from assigned route rows."""

    assignment: Assignment = {clean_text(rider): [] for rider in rider_names if clean_text(rider)}
    assigned: set[str] = set()
    if route_df is not None and not route_df.empty:
        working = route_df.copy()
        working["_seq"] = pd.to_numeric(working.get("Sequence"), errors="coerce")
        working["_seq"] = working["_seq"].fillna(pd.Series(range(1, len(working) + 1), index=working.index))
        for rider, rows in working.sort_values(["Rider", "_seq"], kind="stable").groupby("Rider", sort=False):
            rider_name = clean_text(rider)
            assignment.setdefault(rider_name, [])
            for _, row in rows.iterrows():
                job_id = stable_job_id_from_route_row(row)
                assignment[rider_name].append(job_id)
                assigned.add(job_id)
    all_jobs = list(build_jobs_by_stable_id(jobs_df))
    assignment[UNASSIGNED_LANE] = [job_id for job_id in all_jobs if job_id not in assigned]
    return assignment


def build_planner_session_state(
    route_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    rider_names: Iterable[str],
    workbook_id: str,
) -> dict[str, Any]:
    """Return a fresh planner session payload with no stale history."""

    rider_list = [clean_text(rider) for rider in rider_names if clean_text(rider)]
    assignment = assignment_from_routes(route_df, jobs_df, rider_list)
    return {
        "route_planner_workbook_id": workbook_id,
        "route_planner_confirmed_routes": route_df.copy(),
        "route_planner_confirmed_assignment": clone_assignment(assignment),
        "route_planner_draft_assignment": clone_assignment(assignment),
        "route_planner_original_assignment": clone_assignment(assignment),
        "route_planner_is_dirty": False,
        "route_planner_undo_stack": [],
        "route_planner_redo_stack": [],
        "route_planner_affected_riders": [],
        "route_planner_selected_job_id": None,
        "route_planner_focus_mode": False,
        "route_planner_visible_riders": list(rider_list),
        "route_planner_focus_notice": "",
        "route_planner_show_red_preview": False,
        "route_planner_preview_routes": pd.DataFrame(),
        "route_planner_preview_assignment_signature": "",
        "route_planner_preview_stale_riders": list(rider_list),
        "route_planner_preview_error": "",
        "route_planner_preview_stats": {},
        "route_planner_locked_rider_ids": list(rider_list),
        "route_planner_locked_rider_baselines": {
            clean_text(rider): list(assignment.get(clean_text(rider), []))
            for rider in rider_list
        },
        "route_planner_manual_move_history": {},
        "route_planner_rider_access_cache": {},
        "route_planner_draft_connectors": pd.DataFrame(),
        "route_planner_reshuffle_notice": "",
        "route_planner_reshuffle_pool_job_ids": [],
        "route_planner_highlighted_rider_ids": [],
        "route_planner_board_revision": 0,
    }


def enter_focus_mode_state(state: dict[str, Any], rider_names: Iterable[str]) -> dict[str, Any]:
    """Return focus-mode state updates without touching route or assignment data."""

    riders = [clean_text(rider) for rider in rider_names if clean_text(rider)]
    current_visible = [rider for rider in state.get("route_planner_visible_riders", []) if rider in riders]
    return {
        "route_planner_focus_mode": True,
        "route_planner_visible_riders": current_visible or riders,
    }


def exit_focus_mode_state(state: dict[str, Any]) -> dict[str, Any]:
    """Exit focus mode while deliberately preserving the draft and history."""

    return {"route_planner_focus_mode": False}


def focus_apply_success_state(draft_assignment: Assignment, result: RecalculationResult) -> dict[str, Any]:
    """Session updates for an atomic successful apply."""

    return {
        "route_planner_confirmed_routes": result.route_df.copy(),
        "route_planner_confirmed_assignment": clone_assignment(draft_assignment),
        "route_planner_draft_assignment": clone_assignment(draft_assignment),
        "route_planner_is_dirty": False,
        "route_planner_redo_stack": [],
        "route_planner_affected_riders": [],
        "route_planner_last_apply_stats": dict(result.stats),
        "route_planner_focus_mode": False,
        "route_planner_preview_routes": pd.DataFrame(),
        "route_planner_preview_assignment_signature": "",
        "route_planner_preview_stale_riders": [],
        "route_planner_preview_error": "",
        "route_planner_preview_stats": {},
        "route_planner_manual_move_history": {},
        "route_planner_draft_connectors": pd.DataFrame(),
        "route_planner_reshuffle_notice": "",
        "route_planner_reshuffle_pool_job_ids": [],
        "route_planner_highlighted_rider_ids": [],
    }


def focus_apply_failure_state(state: dict[str, Any]) -> dict[str, Any]:
    """Failure updates intentionally preserve the current draft and confirmed plan."""

    return {
        "route_planner_focus_mode": True,
        "route_planner_draft_assignment": clone_assignment(state["route_planner_draft_assignment"]),
        "route_planner_confirmed_routes": state["route_planner_confirmed_routes"].copy(),
        "route_planner_is_dirty": bool(state.get("route_planner_is_dirty")),
    }


def normalise_assignment_board(
    raw_board: object,
    header_to_lane: dict[str, str],
    card_to_job_id: dict[str, str],
    lane_order: Iterable[str],
) -> Assignment:
    """Convert component output through exact opaque mappings, never label parsing."""

    if raw_board is None:
        raise ValueError("The drag-and-drop board returned no data.")
    if not isinstance(raw_board, list):
        raise ValueError("The drag-and-drop board returned malformed data.")
    output: Assignment = {lane: [] for lane in lane_order}
    seen_lanes: set[str] = set()
    for container in raw_board:
        if not isinstance(container, dict) or not isinstance(container.get("items"), list):
            raise ValueError("The drag-and-drop board returned a malformed lane.")
        header = str(container.get("header") or "")
        if header not in header_to_lane:
            raise ValueError("The drag-and-drop board returned an unknown rider lane.")
        lane = header_to_lane[header]
        if lane in seen_lanes:
            raise ValueError("The drag-and-drop board returned a rider lane more than once.")
        seen_lanes.add(lane)
        jobs: list[str] = []
        for card in container["items"]:
            card_key = str(card)
            if card_key not in card_to_job_id:
                raise ValueError("The drag-and-drop board returned an unknown order card.")
            jobs.append(card_to_job_id[card_key])
        output[lane] = jobs
    return output


def validate_assignment_board(
    assignment: object,
    known_job_ids: Iterable[str],
    rider_names: Iterable[str],
    *,
    require_all_jobs: bool = True,
) -> AssignmentValidation:
    known = set(known_job_ids)
    valid_lanes = {clean_text(rider) for rider in rider_names if clean_text(rider)} | {UNASSIGNED_LANE}
    errors: list[str] = []
    seen: dict[str, int] = {}
    unknown: set[str] = set()
    if not isinstance(assignment, dict):
        return AssignmentValidation(False, ("Assignment must be a rider-to-orders mapping.",))
    for lane, jobs in assignment.items():
        if lane not in valid_lanes:
            errors.append(f"Unknown rider lane: {lane}")
        if not isinstance(jobs, list):
            errors.append(f"Lane {lane} does not contain an ordered list.")
            continue
        for job_id in jobs:
            if not isinstance(job_id, str):
                errors.append(f"Lane {lane} contains an invalid order identity.")
                continue
            seen[job_id] = seen.get(job_id, 0) + 1
            if job_id not in known:
                unknown.add(job_id)
    duplicates = sorted(job_id for job_id, count in seen.items() if count > 1)
    missing = sorted(known - set(seen)) if require_all_jobs else []
    if duplicates:
        errors.append(f"Duplicate orders detected: {', '.join(duplicates[:5])}")
    if missing:
        errors.append(f"Missing orders detected: {', '.join(missing[:5])}")
    if unknown:
        errors.append(f"Unknown orders detected: {', '.join(sorted(unknown)[:5])}")
    return AssignmentValidation(
        not errors,
        tuple(errors),
        tuple(missing),
        tuple(duplicates),
        tuple(sorted(unknown)),
    )


def validate_locked_rider_change(
    baseline_assignment: Assignment,
    proposed_assignment: Assignment,
    locked_rider_ids: Iterable[str],
) -> AssignmentValidation:
    """Reject any sequence or ownership change to a locked rider lane."""

    changed = sorted(
        rider
        for rider in {clean_text(value) for value in locked_rider_ids if clean_text(value)}
        if list(baseline_assignment.get(rider, [])) != list(proposed_assignment.get(rider, []))
    )
    errors = () if not changed else (f"Locked rider routes changed: {', '.join(changed)}",)
    return AssignmentValidation(not changed, errors)


def record_manual_job_moves(
    previous_assignment: Assignment,
    proposed_assignment: Assignment,
    existing_history: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Record rider-to-rider manual moves while preserving the first origin rider."""

    history = copy.deepcopy(existing_history or {})

    def positions(assignment: Assignment) -> dict[str, tuple[str, int]]:
        return {
            job_id: (rider, index)
            for rider, job_ids in assignment.items()
            for index, job_id in enumerate(job_ids)
        }

    before = positions(previous_assignment)
    after = positions(proposed_assignment)
    for job_id in sorted(set(before) & set(after)):
        from_rider, from_index = before[job_id]
        to_rider, to_index = after[job_id]
        if from_rider == to_rider:
            continue
        entry = dict(history.get(job_id, {}))
        entry.setdefault("origin_rider_id", from_rider)
        entry.update(
            {
                "last_from_rider_id": from_rider,
                "last_to_rider_id": to_rider,
                "last_from_index": from_index,
                "last_to_index": to_index,
            }
        )
        history[job_id] = entry
    return history


def normalise_rider_locks(
    locked_rider_ids: Iterable[str],
    rider_names: Iterable[str],
    draft_assignment: Assignment,
    existing_baselines: dict[str, list[str]] | None = None,
) -> tuple[list[str], dict[str, list[str]]]:
    """Remove stale locks and capture the exact draft sequence when a rider is locked."""

    valid = {clean_text(rider) for rider in rider_names if clean_text(rider)}
    locked = sorted({clean_text(rider) for rider in locked_rider_ids if clean_text(rider) in valid})
    old = existing_baselines or {}
    baselines = {
        rider: list(old[rider]) if rider in old else list(draft_assignment.get(rider, []))
        for rider in locked
    }
    return locked, baselines


def reconcile_reshuffle_pool_board(
    current_assignment: Assignment,
    board_assignment: Assignment,
) -> tuple[Assignment, list[str]]:
    """Keep pooled jobs frozen in their current routes while exposing a UI-only drop lane."""

    pool = list(board_assignment.get(RESHUFFLE_POOL_LANE, []))
    proposed = {
        lane: list(job_ids)
        for lane, job_ids in board_assignment.items()
        if lane != RESHUFFLE_POOL_LANE
    }
    positions = {
        job_id: (lane, index)
        for lane, job_ids in current_assignment.items()
        for index, job_id in enumerate(job_ids)
    }
    by_lane: dict[str, list[tuple[int, str]]] = {}
    for job_id in pool:
        if job_id not in positions:
            continue
        lane, index = positions[job_id]
        by_lane.setdefault(lane, []).append((index, job_id))
    for lane, entries in by_lane.items():
        jobs = proposed.setdefault(lane, [])
        for index, job_id in sorted(entries):
            if job_id not in jobs:
                jobs.insert(min(index, len(jobs)), job_id)
    for lane in current_assignment:
        proposed.setdefault(lane, [])
    return proposed, pool


def detect_affected_riders(
    confirmed: Assignment,
    draft: Assignment,
    confirmed_start_locations: dict[str, str] | None = None,
    draft_start_locations: dict[str, str] | None = None,
) -> list[str]:
    """Return only assigned rider lanes whose jobs/order or start input changed."""

    starts_before = confirmed_start_locations or {}
    starts_after = draft_start_locations or starts_before
    riders = (set(confirmed) | set(draft) | set(starts_before) | set(starts_after)) - {UNASSIGNED_LANE}
    return sorted(
        rider
        for rider in riders
        if confirmed.get(rider, []) != draft.get(rider, [])
        or clean_text(starts_before.get(rider)) != clean_text(starts_after.get(rider))
    )


def draft_assignment_signature(assignment: Assignment) -> str:
    """Deterministic signature for associating asynchronous preview data with a draft."""

    canonical = {str(lane): [str(job_id) for job_id in jobs] for lane, jobs in sorted(assignment.items())}
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def invalidate_red_preview(
    previous_assignment: Assignment,
    draft_assignment: Assignment,
    existing_stale_riders: Iterable[str] = (),
) -> tuple[str, ...]:
    """Mark only riders whose connector chain changed; no route lookup occurs."""

    affected = set(detect_affected_riders(previous_assignment, draft_assignment))
    return tuple(sorted(set(existing_stale_riders) | affected))


def derive_sequences_from_assignment(assignment: Assignment, rider_names: Iterable[str]) -> Assignment:
    """List position is the sole source of consecutive route sequence."""

    return {clean_text(rider): list(assignment.get(clean_text(rider), [])) for rider in rider_names if clean_text(rider)}


def build_route_leg_signatures(
    assignment: Assignment,
    jobs_by_id: dict[str, dict[str, Any]],
    rider_start_locations: dict[str, str],
) -> dict[str, tuple[str, str, str]]:
    signatures: dict[str, tuple[str, str, str]] = {}
    for rider, job_ids in assignment.items():
        if rider == UNASSIGNED_LANE:
            continue
        origin = clean_text(rider_start_locations.get(rider))
        for job_id in job_ids:
            job = jobs_by_id.get(job_id, {})
            pickup = clean_text(job.get("Pickup Address"))
            dropoff = clean_text(job.get("Drop-off Address"))
            signatures[f"empty::{rider}::{job_id}"] = ("pt", origin.casefold(), pickup.casefold())
            signatures[f"loaded::{job_id}"] = ("drive", pickup.casefold(), dropoff.casefold())
            origin = dropoff
    return signatures


def detect_changed_route_legs(
    confirmed_signatures: dict[str, tuple[str, str, str]],
    draft_signatures: dict[str, tuple[str, str, str]],
) -> dict[str, list[str]]:
    keys = set(confirmed_signatures) | set(draft_signatures)
    changed = sorted(key for key in keys if confirmed_signatures.get(key) != draft_signatures.get(key))
    unchanged = sorted(key for key in keys if key in confirmed_signatures and confirmed_signatures.get(key) == draft_signatures.get(key))
    return {"changed": changed, "unchanged": unchanged}


def update_draft_history(
    current: Assignment,
    proposed: Assignment,
    undo_stack: list[Assignment],
    redo_stack: list[Assignment],
    limit: int = HISTORY_LIMIT,
) -> tuple[Assignment, list[Assignment], list[Assignment], bool]:
    if current == proposed:
        return clone_assignment(current), copy.deepcopy(undo_stack), copy.deepcopy(redo_stack), False
    undo = copy.deepcopy(undo_stack)
    if not undo or undo[-1] != current:
        undo.append(clone_assignment(current))
    return clone_assignment(proposed), undo[-limit:], [], True


def undo_draft(current: Assignment, undo_stack: list[Assignment], redo_stack: list[Assignment]) -> tuple[Assignment, list[Assignment], list[Assignment], bool]:
    if not undo_stack:
        return clone_assignment(current), [], copy.deepcopy(redo_stack), False
    undo = copy.deepcopy(undo_stack)
    previous = undo.pop()
    redo = copy.deepcopy(redo_stack)
    if not redo or redo[-1] != current:
        redo.append(clone_assignment(current))
    return clone_assignment(previous), undo, redo[-HISTORY_LIMIT:], True


def redo_draft(current: Assignment, undo_stack: list[Assignment], redo_stack: list[Assignment]) -> tuple[Assignment, list[Assignment], list[Assignment], bool]:
    if not redo_stack:
        return clone_assignment(current), copy.deepcopy(undo_stack), [], False
    redo = copy.deepcopy(redo_stack)
    next_assignment = redo.pop()
    undo = copy.deepcopy(undo_stack)
    if not undo or undo[-1] != current:
        undo.append(clone_assignment(current))
    return clone_assignment(next_assignment), undo[-HISTORY_LIMIT:], redo, True


def reset_draft(original: Assignment, current: Assignment) -> tuple[Assignment, list[Assignment], list[Assignment], bool]:
    if original == current:
        return clone_assignment(current), [], [], False
    return clone_assignment(original), [clone_assignment(current)], [], True


def reshuffle_unlocked_assignments(
    draft_assignment: Assignment,
    locked_rider_ids: Iterable[str],
    manual_move_history: dict[str, dict[str, Any]],
    rider_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    *,
    eligible_job_ids: Iterable[str] | None = None,
    max_candidates: int = 600,
    beam_width: int = 40,
    origin_return_penalty: float = 15.0,
    search_fn: Callable[..., dict[str, Any]] = find_best_selective_reshuffle,
) -> ReshuffleResult:
    """Run a bounded, cache-friendly reshuffle while treating locked routes as immutable."""

    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        return ReshuffleResult(clone_assignment(draft_assignment), False, "; ".join(rider_errors), {})
    rider_names = [rider.name for rider in riders]
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
    if not validation.is_valid:
        return ReshuffleResult(clone_assignment(draft_assignment), False, "; ".join(validation.errors), {})
    locked = {clean_text(rider) for rider in locked_rider_ids if clean_text(rider) in rider_names}
    unlocked = [rider for rider in rider_names if rider not in locked]
    unlocked_jobs = {job_id for rider in unlocked for job_id in draft_assignment.get(rider, [])}
    requested_jobs = {clean_text(job_id) for job_id in eligible_job_ids or [] if clean_text(job_id)}
    movable = unlocked_jobs & requested_jobs if eligible_job_ids is not None else unlocked_jobs
    if len(unlocked) < 2:
        return ReshuffleResult(clone_assignment(draft_assignment), False, "Unlock at least two riders before reshuffling.", {})
    if not movable:
        return ReshuffleResult(clone_assignment(draft_assignment), False, "Drop at least one unlocked order into the reshuffle pool.", {})
    sequences = {rider: list(draft_assignment.get(rider, [])) for rider in rider_names}
    origins = {
        job_id: clean_text(entry.get("origin_rider_id"))
        for job_id, entry in (manual_move_history or {}).items()
        if job_id in movable and clean_text(entry.get("origin_rider_id"))
    }
    result = search_fn(
        sequences,
        jobs_by_id,
        riders,
        jobs_df=jobs_df,
        locked_riders=locked,
        reshuffle_job_ids=movable,
        eligible_receiver_riders=set(unlocked),
        top_n=3,
        beam_width=max(1, int(beam_width)),
        max_candidates=max(1, int(max_candidates)),
        changed_rider_penalty=2.0,
        moved_job_penalty=1.0,
        sequence_change_penalty=0.5,
        origin_rider_by_job=origins,
        origin_return_penalty=max(0.0, float(origin_return_penalty)),
        use_onemap=False,
    )
    stats = {
        "candidate_count": int(result.get("candidate_count", 0)),
        "search_limited": bool(result.get("search_limited", False)),
        "origin_return_count": int(result.get("origin_return_count", 0)),
    }
    if not result.get("success"):
        return ReshuffleResult(clone_assignment(draft_assignment), False, clean_text(result.get("reason")) or "No feasible reshuffle was found.", stats)
    proposed = clone_assignment(draft_assignment)
    for rider in rider_names:
        proposed[rider] = list(result.get("proposed_sequences", {}).get(rider, []))
    post_validation = validate_assignment_board(proposed, jobs_by_id, rider_names)
    lock_validation = validate_locked_rider_change(draft_assignment, proposed, locked)
    if not post_validation.is_valid or not lock_validation.is_valid:
        errors = post_validation.errors + lock_validation.errors
        return ReshuffleResult(clone_assignment(draft_assignment), False, "; ".join(errors), stats)
    if proposed == draft_assignment:
        return ReshuffleResult(proposed, False, "The current unlocked routes are already the best bounded result.", stats)
    changed_count = len(detect_affected_riders(draft_assignment, proposed))
    stats.update({"changed_riders": changed_count, "plan_score": result.get("plan_score")})
    return ReshuffleResult(proposed, True, f"Reshuffled {changed_count} unlocked rider route(s).", stats)


def _travel_cost_from_row(row: pd.Series, prefix: str) -> TravelCost:
    path_value = row.get(f"{prefix} Route Path")
    try:
        path = json.loads(str(path_value)) if clean_text(path_value) else []
    except (TypeError, json.JSONDecodeError):
        path = []
    instruction_column = "Empty PT Instructions" if prefix == "Empty" else "Loaded Drive Instructions"
    return TravelCost(
        distance_km=float(row.get(f"{prefix} Distance KM") or 0),
        duration_min=float(row.get(f"{prefix} Duration Min") or 0),
        source=f"reused confirmed {prefix.casefold()} leg",
        route_text=clean_text(row.get(instruction_column)),
        route_path=path,
    )


def _parsed_route_path(value: object) -> list[list[float]]:
    if isinstance(value, list):
        parsed = value
    else:
        try:
            parsed = json.loads(str(value)) if clean_text(value) else []
        except (TypeError, json.JSONDecodeError):
            return []
    path: list[list[float]] = []
    for point in parsed if isinstance(parsed, list) else []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            path.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            continue
    return path


def _stored_coordinate(address: str) -> list[float] | None:
    geocode = get_stored_geocode(clean_text(address))
    if not geocode.is_available:
        return None
    return [float(geocode.longitude), float(geocode.latitude)]


def _coordinate(
    address: str,
    coordinate_lookup: Callable[[str], object] | None,
) -> list[float] | None:
    value = (coordinate_lookup or _stored_coordinate)(clean_text(address))
    if value is None:
        return None
    if hasattr(value, "is_available"):
        if not bool(getattr(value, "is_available")):
            return None
        return [float(getattr(value, "longitude")), float(getattr(value, "latitude"))]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return [float(value[0]), float(value[1])]
        except (TypeError, ValueError):
            return None
    return None


def build_rider_start_markers(
    visible_riders: Iterable[str],
    rider_starts: dict[str, str],
    *,
    coordinate_lookup: Callable[[str], object] | None = None,
) -> pd.DataFrame:
    """Return bright white start markers using stored coordinates only."""

    rows: list[dict[str, Any]] = []
    for rider in visible_riders:
        address = clean_text(rider_starts.get(rider))
        point = _coordinate(address, coordinate_lookup)
        if point is None:
            continue
        rows.append(
            {
                "Rider": rider,
                "lon": point[0],
                "lat": point[1],
                "fill_color": [255, 255, 255, 255],
                "tooltip": f"{rider}<br/>Starting location<br/>{address}",
            }
        )
    return pd.DataFrame(rows)


def _draft_connector_specs(
    assignment: Assignment,
    jobs_by_id: dict[str, dict[str, Any]],
    rider_starts: dict[str, str],
) -> dict[tuple[str, str], tuple[str, str, int]]:
    specs: dict[tuple[str, str], tuple[str, str, int]] = {}
    for rider, job_ids in assignment.items():
        if rider == UNASSIGNED_LANE:
            continue
        origin = clean_text(rider_starts.get(rider))
        for sequence, job_id in enumerate(job_ids, start=1):
            pickup = clean_text(jobs_by_id.get(job_id, {}).get("Pickup Address"))
            specs[(rider, job_id)] = (origin, pickup, sequence)
            origin = clean_text(jobs_by_id.get(job_id, {}).get("Drop-off Address"))
    return specs


def build_draft_connector_lines(
    confirmed_assignment: Assignment,
    draft_assignment: Assignment,
    jobs_df: pd.DataFrame,
    rider_starts: dict[str, str],
    *,
    coordinate_lookup: Callable[[str], object] | None = None,
) -> DraftConnectorResult:
    """Build immediate straight purple lines only for changed draft connector legs."""

    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    before = _draft_connector_specs(confirmed_assignment, jobs_by_id, rider_starts)
    after = _draft_connector_specs(draft_assignment, jobs_by_id, rider_starts)
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for (rider, job_id), (start, end, sequence) in after.items():
        prior = before.get((rider, job_id))
        if prior and prior[:2] == (start, end):
            continue
        start_point = _coordinate(start, coordinate_lookup)
        end_point = _coordinate(end, coordinate_lookup)
        if start_point is None or end_point is None:
            warnings.append(f"Draft connector unavailable for {rider} job {sequence}: cached coordinates are missing.")
            continue
        rows.append(
            {
                "Rider": rider,
                "Sequence": sequence,
                "Job ID": job_id,
                "path": [start_point, end_point],
                "color": [168, 85, 247, 235],
                "geometry_source": "draft_straight_line",
                "tooltip": f"{rider}<br/>Draft connector to job {sequence}<br/>{start} → {end}",
            }
        )
    return DraftConnectorResult(pd.DataFrame(rows), tuple(dict.fromkeys(warnings)))


def _matching_access_path(
    routes: pd.DataFrame | None,
    rider: str,
    job_id: str,
    start: str,
    end: str,
    *,
    preview: bool,
) -> tuple[list[list[float]], str] | None:
    if routes is None or routes.empty:
        return None
    for _, row in routes.iterrows():
        row_rider = clean_text(row.get("Rider"))
        if row_rider != rider:
            continue
        try:
            row_job_id = clean_text(row.get("Job ID")) if preview else stable_job_id_from_route_row(row)
        except (KeyError, TypeError, ValueError):
            continue
        start_column = "Start Label" if preview else "Start From"
        end_column = "End Label" if preview else "Pickup Address"
        path_column = "Route Path" if preview else "Empty Route Path"
        if (
            row_job_id != job_id
            or clean_text(row.get(start_column)).casefold() != start.casefold()
            or clean_text(row.get(end_column)).casefold() != end.casefold()
        ):
            continue
        path = _parsed_route_path(row.get(path_column))
        if len(path) < 2:
            continue
        source = clean_text(row.get("Source")) if preview else "reused confirmed public transport"
        geometry_source = "cached_public_transport" if "cache" in source.casefold() or not preview else "calculated_public_transport"
        return path, geometry_source
    return None


def rider_access_cache_key(
    rider: str,
    job_id: str,
    start_point: list[float],
    end_point: list[float],
) -> str:
    payload = [rider, job_id, [round(value, 6) for value in start_point], [round(value, 6) for value in end_point], "public_transport"]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode("utf-8")).hexdigest()


def _access_path_matches_coordinates(
    path: list[list[float]],
    start_point: list[float],
    end_point: list[float],
    tolerance_degrees: float = 0.03,
) -> bool:
    if len(path) < 2:
        return False
    return all(abs(path[0][index] - start_point[index]) <= tolerance_degrees for index in (0, 1)) and all(
        abs(path[-1][index] - end_point[index]) <= tolerance_degrees for index in (0, 1)
    )


def build_rider_access_paths(
    draft_assignment: Assignment,
    visible_riders: Iterable[str],
    confirmed_routes: pd.DataFrame,
    preview_routes: pd.DataFrame | None,
    jobs_df: pd.DataFrame,
    rider_starts: dict[str, str],
    route_cache: dict[str, dict[str, Any]] | None,
    *,
    coordinate_lookup: Callable[[str], object] | None = None,
) -> RiderAccessResult:
    """Build red rider-start access routes without initiating routing or geocoding."""

    visible = set(visible_riders)
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    cache = copy.deepcopy(route_cache or {})
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for rider, job_ids in draft_assignment.items():
        if rider == UNASSIGNED_LANE or rider not in visible or not job_ids:
            continue
        job_id = job_ids[0]
        start = clean_text(rider_starts.get(rider))
        end = clean_text(jobs_by_id.get(job_id, {}).get("Pickup Address"))
        start_point = _coordinate(start, coordinate_lookup)
        end_point = _coordinate(end, coordinate_lookup)
        candidate = _matching_access_path(preview_routes, rider, job_id, start, end, preview=True)
        if candidate is None:
            candidate = _matching_access_path(confirmed_routes, rider, job_id, start, end, preview=False)
        if start_point is None and candidate:
            start_point = candidate[0][0]
        if end_point is None and candidate:
            end_point = candidate[0][-1]
        if start_point is None or end_point is None:
            warnings.append(f"Rider access unavailable for {rider}: cached coordinates are missing.")
            continue
        cache_key = rider_access_cache_key(rider, job_id, start_point, end_point)
        cached = cache.get(cache_key, {})
        cached_path = _parsed_route_path(cached.get("path"))
        if _access_path_matches_coordinates(cached_path, start_point, end_point):
            path = cached_path
            geometry_source = clean_text(cached.get("geometry_source")) or "cached_public_transport"
        elif candidate:
            if cached:
                warnings.append(f"Stale rider-access geometry was ignored for {rider}.")
            path, geometry_source = candidate
            cache[cache_key] = {"path": path, "geometry_source": geometry_source}
        else:
            if cached:
                warnings.append(f"Stale rider-access geometry was ignored for {rider}.")
            path = [start_point, end_point]
            geometry_source = "fallback_straight_line"
            cache[cache_key] = {"path": path, "geometry_source": geometry_source}
        rows.append(
            {
                "Rider": rider,
                "Sequence": 0,
                "Job ID": job_id,
                "path": path,
                "color": [239, 68, 68, 235],
                "geometry_source": geometry_source,
                "tooltip": f"{rider}<br/>Start → first pickup<br/>{geometry_source.replace('_', ' ')}",
            }
        )
    return RiderAccessResult(pd.DataFrame(rows), cache, tuple(dict.fromkeys(warnings)))


def confirmed_loaded_route_is_valid(row: pd.Series | dict[str, Any], job: dict[str, Any]) -> bool:
    """Validate that cached loaded geometry still describes this job's drive leg."""

    return (
        clean_text(row.get("Pickup Address")).casefold() == clean_text(job.get("Pickup Address")).casefold()
        and clean_text(row.get("Drop-off Address")).casefold() == clean_text(job.get("Drop-off Address")).casefold()
        and len(_parsed_route_path(row.get("Loaded Route Path"))) >= 2
    )


def build_green_geometry_by_job_id(
    confirmed_routes: pd.DataFrame,
    jobs_df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Build the lightweight, no-network loaded-route lookup used while dragging."""

    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    geometry: dict[str, dict[str, Any]] = {}
    if confirmed_routes is None or confirmed_routes.empty:
        return geometry
    for _, row in confirmed_routes.iterrows():
        job_id = stable_job_id_from_route_row(row)
        job = jobs_by_id.get(job_id)
        if job is None or not confirmed_loaded_route_is_valid(row, job):
            continue
        geometry[job_id] = {
            "path": _parsed_route_path(row.get("Loaded Route Path")),
            "distance_km": row.get("Loaded Distance KM"),
            "duration_min": row.get("Loaded Duration Min"),
            "pickup": clean_text(job.get("Pickup Address")),
            "dropoff": clean_text(job.get("Drop-off Address")),
            "car_plate": clean_text(job.get("Car Plate")),
            "routing_mode": "drive",
        }
    return geometry


def build_focus_map_data(
    draft_assignment: Assignment,
    visible_riders: Iterable[str],
    confirmed_routes: pd.DataFrame,
    jobs_df: pd.DataFrame,
) -> FocusMapResult:
    """Render-ready green job routes only; this function never geocodes or routes."""

    visible = set(visible_riders)
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    green_by_job = build_green_geometry_by_job_id(confirmed_routes, jobs_df)
    green_shades = ([22, 163, 74, 225], [5, 150, 105, 225], [21, 128, 61, 225], [4, 120, 87, 225])
    route_rows: list[dict[str, Any]] = []
    marker_rows: list[dict[str, Any]] = []
    pending: list[str] = []
    visible_jobs = 0
    for rider_index, (rider, job_ids) in enumerate(
        (item for item in draft_assignment.items() if item[0] != UNASSIGNED_LANE)
    ):
        if rider not in visible:
            continue
        colour = green_shades[rider_index % len(green_shades)]
        for sequence, job_id in enumerate(job_ids, start=1):
            visible_jobs += 1
            job = jobs_by_id.get(job_id, {})
            cached = green_by_job.get(job_id)
            if cached is None:
                pending.append(job_id)
                for marker_type, address, marker_colour in (
                    ("Pickup", clean_text(job.get("Pickup Address")), [14, 165, 233, 235]),
                    ("Drop-off", clean_text(job.get("Drop-off Address")), [249, 115, 22, 235]),
                ):
                    geocode = get_stored_geocode(address)
                    if not geocode.is_available:
                        continue
                    marker_rows.append(
                        {
                            "Rider": rider,
                            "Sequence": sequence,
                            "Job ID": job_id,
                            "type": marker_type,
                            "lon": geocode.longitude,
                            "lat": geocode.latitude,
                            "fill_color": marker_colour,
                            "tooltip": f"{rider}<br/>Job {sequence} {marker_type.lower()} · Route pending<br/>{address}",
                        }
                    )
                continue
            path = cached["path"]
            tooltip = (
                f"{rider}<br/>Job {sequence} · {cached['car_plate']}<br/>"
                f"{cached['pickup']} → {cached['dropoff']}<br/>"
                f"{cached['distance_km']} km, {cached['duration_min']} min"
            )
            route_rows.append(
                {
                    "Rider": rider,
                    "Sequence": sequence,
                    "Job ID": job_id,
                    "Car Plate": cached["car_plate"],
                    "path": path,
                    "color": colour,
                    "tooltip": tooltip,
                    "leg_type": "loaded",
                }
            )
            for marker_type, point, marker_colour in (
                ("Pickup", path[0], [14, 165, 233, 235]),
                ("Drop-off", path[-1], [249, 115, 22, 235]),
            ):
                marker_rows.append(
                    {
                        "Rider": rider,
                        "Sequence": sequence,
                        "Job ID": job_id,
                        "type": marker_type,
                        "lon": point[0],
                        "lat": point[1],
                        "fill_color": marker_colour,
                        "tooltip": f"{rider}<br/>Job {sequence} {marker_type.lower()}<br/>{clean_text(job.get(marker_type + ' Address'))}",
                    }
                )
    return FocusMapResult(
        pd.DataFrame(route_rows),
        pd.DataFrame(marker_rows),
        tuple(pending),
        visible_jobs,
    )


def build_precomputed_costs(
    confirmed_routes: pd.DataFrame,
    confirmed_assignment: Assignment,
    draft_assignment: Assignment,
    jobs_by_id: dict[str, dict[str, Any]],
    rider_starts: dict[str, str],
) -> tuple[dict[str, TravelCost], dict[tuple[str, str], TravelCost]]:
    """Reuse every loaded leg and only connectors whose origin remains identical."""

    loaded: dict[str, TravelCost] = {}
    empty: dict[tuple[str, str], TravelCost] = {}
    if confirmed_routes is None or confirmed_routes.empty:
        return loaded, empty
    before = build_route_leg_signatures(confirmed_assignment, jobs_by_id, rider_starts)
    after = build_route_leg_signatures(draft_assignment, jobs_by_id, rider_starts)
    for _, row in confirmed_routes.iterrows():
        job_id = stable_job_id_from_route_row(row)
        job = jobs_by_id.get(job_id)
        if job is not None and confirmed_loaded_route_is_valid(row, job):
            loaded[job_id] = _travel_cost_from_row(row, "Loaded")
        rider = clean_text(row.get("Rider"))
        key = f"empty::{rider}::{job_id}"
        if before.get(key) == after.get(key):
            empty[(rider, job_id)] = _travel_cost_from_row(row, "Empty")
    return loaded, empty


RED_PREVIEW_COLUMNS = [
    "Rider",
    "Sequence",
    "Job ID",
    "Start Label",
    "End Label",
    "Distance KM",
    "Duration Min",
    "Route Path",
    "Source",
]


def refresh_red_connector_preview(
    *,
    confirmed_routes: pd.DataFrame,
    confirmed_assignment: Assignment,
    draft_assignment: Assignment,
    existing_preview_routes: pd.DataFrame | None,
    stale_riders: Iterable[str],
    rider_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    use_onemap: bool,
    token: str | None,
    duration_multiplier: float = 1.0,
    wait_buffer_min: float = 0.0,
    connector_lookup: Callable[..., TravelCost] = get_empty_travel_cost,
) -> RedPreviewResult:
    """Refresh exact red connectors for stale riders only using the existing route cache path."""

    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        raise ValueError("; ".join(rider_errors))
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    rider_names = [rider.name for rider in riders]
    validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    stale = set(stale_riders) & set(rider_names)
    existing = existing_preview_routes.copy() if existing_preview_routes is not None else pd.DataFrame(columns=RED_PREVIEW_COLUMNS)
    if not existing.empty:
        existing = existing[~existing["Rider"].apply(clean_text).isin(stale)].copy()
    confirmed_signatures = build_route_leg_signatures(
        confirmed_assignment,
        jobs_by_id,
        {rider.name: rider.start_location for rider in riders},
    )
    draft_signatures = build_route_leg_signatures(
        draft_assignment,
        jobs_by_id,
        {rider.name: rider.start_location for rider in riders},
    )
    confirmed_rows = {
        (clean_text(row.get("Rider")), stable_job_id_from_route_row(row)): row
        for _, row in confirmed_routes.iterrows()
    }
    rows: list[dict[str, Any]] = []
    stats = {"confirmed_reused": 0, "cache_hits": 0, "onemap_requests": 0, "refreshed_riders": len(stale)}
    rider_by_name = {rider.name: rider for rider in riders}
    for rider_name in sorted(stale):
        rider = rider_by_name[rider_name]
        origin = rider.start_location
        origin_zone = rider.start_zone
        for sequence, job_id in enumerate(draft_assignment.get(rider_name, []), start=1):
            job = jobs_by_id[job_id]
            pickup = clean_text(job.get("Pickup Address"))
            pickup_zone = clean_text(job.get("Pickup Zone")) or None
            signature_key = f"empty::{rider_name}::{job_id}"
            confirmed_row = confirmed_rows.get((rider_name, job_id))
            if (
                confirmed_row is not None
                and confirmed_signatures.get(signature_key) == draft_signatures.get(signature_key)
                and len(_parsed_route_path(confirmed_row.get("Empty Route Path"))) >= 2
            ):
                cost = _travel_cost_from_row(confirmed_row, "Empty")
                source = "confirmed connector reused"
                stats["confirmed_reused"] += 1
            else:
                cost = connector_lookup(
                    origin,
                    pickup,
                    origin_zone,
                    pickup_zone,
                    use_onemap=use_onemap,
                    token=token,
                    allow_walk=sequence > 1,
                )
                cost = adjust_empty_travel_for_public_transport(
                    cost,
                    duration_multiplier=duration_multiplier,
                    wait_buffer_min=wait_buffer_min,
                )
                source = clean_text(cost.source)
                if "cache" in source.casefold():
                    stats["cache_hits"] += 1
                elif "onemap" in source.casefold():
                    stats["onemap_requests"] += 1
            path = _parsed_route_path(cost.route_path)
            if len(path) < 2:
                raise ValueError(f"No exact connector geometry was available for {rider_name}, job {sequence}.")
            rows.append(
                {
                    "Rider": rider_name,
                    "Sequence": sequence,
                    "Job ID": job_id,
                    "Start Label": origin,
                    "End Label": pickup,
                    "Distance KM": cost.distance_km,
                    "Duration Min": cost.duration_min,
                    "Route Path": json.dumps(path),
                    "Source": source,
                }
            )
            origin = clean_text(job.get("Drop-off Address"))
            origin_zone = clean_text(job.get("Drop-off Zone")) or None
    refreshed = pd.concat([existing, pd.DataFrame(rows, columns=RED_PREVIEW_COLUMNS)], ignore_index=True)
    if not refreshed.empty:
        refreshed = refreshed.sort_values(["Rider", "Sequence"], kind="stable").reset_index(drop=True)
    return RedPreviewResult(refreshed, draft_assignment_signature(draft_assignment), (), stats)


def red_preview_costs(preview_routes: pd.DataFrame | None) -> dict[tuple[str, str], TravelCost]:
    """Convert an exact matching preview into precomputed evaluator connector costs."""

    costs: dict[tuple[str, str], TravelCost] = {}
    if preview_routes is None or preview_routes.empty:
        return costs
    for _, row in preview_routes.iterrows():
        costs[(clean_text(row.get("Rider")), clean_text(row.get("Job ID")))] = TravelCost(
            row.get("Distance KM"),
            row.get("Duration Min"),
            "reused red preview",
            route_path=_parsed_route_path(row.get("Route Path")),
        )
    return costs


def matching_red_preview_routes(
    preview_routes: pd.DataFrame | None,
    stored_signature: str,
    draft_assignment: Assignment,
    stale_riders: Iterable[str],
) -> pd.DataFrame | None:
    """Return preview data only when it exactly belongs to the current complete draft."""

    if preview_routes is None or set(stale_riders):
        return None
    if stored_signature != draft_assignment_signature(draft_assignment):
        return None
    return preview_routes.copy()


def renderable_red_preview_routes(
    preview_routes: pd.DataFrame | None,
    visible_riders: Iterable[str],
    stale_riders: Iterable[str],
) -> pd.DataFrame:
    """Hide stale rider connectors while retaining unaffected preview rows."""

    if preview_routes is None or preview_routes.empty:
        return pd.DataFrame(columns=RED_PREVIEW_COLUMNS)
    visible = set(visible_riders)
    stale = set(stale_riders)
    return preview_routes[
        preview_routes["Rider"].apply(clean_text).isin(visible)
        & ~preview_routes["Rider"].apply(clean_text).isin(stale)
    ].copy()


def build_compact_rider_summary(
    confirmed_routes: pd.DataFrame,
    rider_df: pd.DataFrame,
    *,
    duration_limit_min: float | None,
) -> pd.DataFrame:
    """Manager-facing workload totals derived exclusively from confirmed rows."""

    max_jobs = {
        clean_text(row.get("Rider Name")): pd.to_numeric(pd.Series([row.get("Max Jobs")]), errors="coerce").iloc[0]
        for _, row in rider_df.iterrows()
    }
    rows: list[dict[str, Any]] = []
    for rider, routes in confirmed_routes.groupby(confirmed_routes["Rider"].apply(clean_text), sort=False):
        job_count = len(routes)
        loaded = float(pd.to_numeric(routes["Loaded Duration Min"], errors="coerce").fillna(0).sum())
        connector = float(pd.to_numeric(routes["Empty Duration Min"], errors="coerce").fillna(0).sum())
        total = loaded + connector
        distance = float(pd.to_numeric(routes["Total Distance KM"], errors="coerce").fillna(0).sum())
        job_limit = max_jobs.get(clean_text(rider))
        ratios: list[float] = []
        if pd.notna(job_limit) and float(job_limit) > 0:
            ratios.append(job_count / float(job_limit))
        if duration_limit_min is not None and duration_limit_min > 0:
            ratios.append(total / duration_limit_min)
        if ratios:
            load_ratio = max(ratios)
            workload = "Heavy" if load_ratio > 1 else "Light" if load_ratio < 0.70 else "Balanced"
            status = "Over limit" if load_ratio > 1 else "OK"
        else:
            workload = ""
            status = "Limits unavailable"
        rows.append(
            {
                "Rider": clean_text(rider),
                "Job count": job_count,
                "Loaded-route minutes": round(loaded, 1),
                "Connector minutes": round(connector, 1),
                "Total minutes": round(total, 1),
                "Total distance KM": round(distance, 2),
                "Status": status,
                "Workload": workload,
            }
        )
    return pd.DataFrame(rows)


def incremental_recalculate(
    *,
    confirmed_routes: pd.DataFrame,
    confirmed_assignment: Assignment,
    draft_assignment: Assignment,
    rider_df: pd.DataFrame,
    jobs_df: pd.DataFrame,
    settings: dict[str, Any],
    summary_builder: Callable[[pd.DataFrame], pd.DataFrame],
    rebuild: Callable[..., tuple[pd.DataFrame, pd.DataFrame, list[str]]] = rebuild_outputs_from_sequences,
    matching_preview_routes: pd.DataFrame | None = None,
) -> RecalculationResult:
    """Rebuild affected riders only and commit nothing outside this pure result."""

    riders, rider_errors = validate_riders(rider_df)
    if rider_errors:
        raise ValueError("; ".join(rider_errors))
    rider_names = [rider.name for rider in riders]
    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    validation = validate_assignment_board(draft_assignment, jobs_by_id, rider_names)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    starts = {rider.name: rider.start_location for rider in riders}
    affected = detect_affected_riders(confirmed_assignment, draft_assignment, starts, starts)
    if not affected:
        return RecalculationResult(
            confirmed_routes.copy(),
            summary_builder(confirmed_routes.copy()),
            [],
            [],
            {
                "reused_legs": len(confirmed_routes) * 2,
                "reused_loaded": len(confirmed_routes),
                "reused_connectors": len(confirmed_routes),
                "cache_hits": 0,
                "onemap_requests": 0,
            },
        )

    sequences = derive_sequences_from_assignment(draft_assignment, rider_names)
    affected_riders = [rider for rider in riders if rider.name in affected]
    affected_sequences = {rider: sequences.get(rider, []) for rider in affected}
    loaded_costs, empty_costs = build_precomputed_costs(
        confirmed_routes, confirmed_assignment, draft_assignment, jobs_by_id, starts
    )
    empty_costs.update(red_preview_costs(matching_preview_routes))
    lookup_stats = {"reused_loaded": 0, "reused_empty": 0, "cache_hits": 0, "onemap_requests": 0}
    rebuild_settings = dict(settings)
    rebuild_settings.update(
        precomputed_loaded_costs=loaded_costs,
        precomputed_empty_costs=empty_costs,
        route_lookup_stats=lookup_stats,
    )
    rebuilt, _, warnings = rebuild(
        affected_sequences,
        affected_riders,
        jobs_by_id,
        jobs_df=None,
        **rebuild_settings,
    )
    unaffected = confirmed_routes[~confirmed_routes["Rider"].apply(clean_text).isin(affected)].copy()
    combined = pd.concat([unaffected, rebuilt], ignore_index=True)
    for column in ROUTE_COLUMNS:
        if column not in combined.columns:
            combined[column] = ""
    combined = combined.loc[:, ROUTE_COLUMNS]
    if not combined.empty:
        combined["_seq"] = pd.to_numeric(combined["Sequence"], errors="coerce").fillna(0)
        combined = combined.sort_values(["Rider", "_seq"], kind="stable").drop(columns="_seq").reset_index(drop=True)
    integrity = optimisation_integrity_report(combined, jobs_df)
    if not integrity["is_valid"]:
        raise ValueError(integrity["message"])
    _validate_route_chaining(combined, starts)
    summary = summary_builder(combined)
    assigned_summary = summary[summary.get("Total Jobs", pd.Series(dtype=float)).fillna(0).astype(int) > 0]
    if int(assigned_summary["Total Jobs"].sum()) != len(combined):
        raise ValueError("Rider summary job counts do not match the recalculated route rows.")
    stats = {
        "reused_legs": int(lookup_stats["reused_loaded"] + lookup_stats["reused_empty"]),
        "reused_loaded": int(lookup_stats["reused_loaded"]),
        "reused_connectors": int(lookup_stats["reused_empty"]),
        "cache_hits": int(lookup_stats["cache_hits"]),
        "onemap_requests": int(lookup_stats["onemap_requests"]),
    }
    return RecalculationResult(combined, summary, warnings, affected, stats)


def _validate_route_chaining(route_df: pd.DataFrame, rider_starts: dict[str, str]) -> None:
    for rider, rows in route_df.groupby("Rider", sort=False):
        expected = clean_text(rider_starts.get(clean_text(rider)))
        ordered = rows.sort_values("Sequence", kind="stable")
        for expected_sequence, (_, row) in enumerate(ordered.iterrows(), start=1):
            if int(float(row["Sequence"])) != expected_sequence:
                raise ValueError(f"Route sequence for {rider} is not consecutive.")
            if clean_text(row.get("Start From")).casefold() != expected.casefold():
                raise ValueError(f"Route chaining failed for {rider} at sequence {expected_sequence}.")
            expected = clean_text(row.get("Drop-off Address"))


def build_draft_preview_routes(
    confirmed_routes: pd.DataFrame,
    confirmed_assignment: Assignment,
    draft_assignment: Assignment,
    jobs_df: pd.DataFrame,
    rider_start_locations: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Create a no-network draft view using confirmed legs and pending connectors."""

    jobs_by_id = build_jobs_by_stable_id(jobs_df)
    confirmed_rows = {stable_job_id_from_route_row(row): row for _, row in confirmed_routes.iterrows()}
    before = build_route_leg_signatures(confirmed_assignment, jobs_by_id, rider_start_locations)
    after = build_route_leg_signatures(draft_assignment, jobs_by_id, rider_start_locations)
    rows: list[dict[str, Any]] = []
    known_duration = 0.0
    pending = 0
    for rider, job_ids in draft_assignment.items():
        if rider == UNASSIGNED_LANE:
            continue
        origin = clean_text(rider_start_locations.get(rider))
        for sequence, job_id in enumerate(job_ids, start=1):
            source_row = confirmed_rows.get(job_id)
            job = jobs_by_id[job_id]
            row = source_row.to_dict() if source_row is not None else {column: "" for column in ROUTE_COLUMNS}
            row.update(
                Rider=rider,
                Sequence=sequence,
                **{
                    "Start From": origin,
                    "Uploaded Row": job.get("Uploaded Row", int(job.get("_original_order", 0)) + 2),
                    "Car Plate": clean_text(job.get("Car Plate")),
                    "Pickup Address": clean_text(job.get("Pickup Address")),
                    "Pickup Lot": clean_text(job.get("Pickup Lot")),
                    "Drop-off Address": clean_text(job.get("Drop-off Address")),
                },
            )
            empty_key = f"empty::{rider}::{job_id}"
            connector_known = before.get(empty_key) == after.get(empty_key) and source_row is not None
            if not connector_known:
                row["Empty Route Path"] = "[]"
                row["Empty Distance KM"] = None
                row["Empty Duration Min"] = None
                row["Empty PT Instructions"] = "Pending recalculation"
                pending += 1
            else:
                known_duration += float(row.get("Empty Duration Min") or 0)
            known_duration += float(row.get("Loaded Duration Min") or 0)
            row["Total Duration Min"] = None if not connector_known else float(row.get("Empty Duration Min") or 0) + float(row.get("Loaded Duration Min") or 0)
            origin = clean_text(job.get("Drop-off Address"))
            rows.append(row)
    preview = pd.DataFrame(rows, columns=ROUTE_COLUMNS)
    return preview, {"known_duration_min": round(known_duration, 1), "pending_route_legs": pending}
