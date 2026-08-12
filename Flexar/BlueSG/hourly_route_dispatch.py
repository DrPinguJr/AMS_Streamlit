"""Pure rolling-dispatch helpers used by the hourly Streamlit page.

The module deliberately keeps Streamlit out of the dispatch engine so merge,
shift, archive, and incremental-recalculation behaviour can be tested without a
browser session.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import (
    ROUTE_COLUMNS,
    SUMMARY_COLUMNS,
    clean_text,
    format_summary_output,
    stable_job_id_from_job,
    stable_job_id_from_route_row,
)
from Flexar.BlueSG.gemini_standby_advisor import (
    StandbyAdvisorResult,
    build_standby_context,
    recommend_standby_activation,
)
from Flexar.BlueSG.job_import_staging import commit_staged_jobs, validate_staged_jobs
from Flexar.BlueSG.manual_route_assignment_editing_and_recalculation import (
    RecalculationResult,
    assignment_from_routes,
    incremental_recalculate,
)
from Flexar.BlueSG.optimiser_workflow_state import normalise_riders
from Flexar.BlueSG.route_operation_time_window_settings import OperationContext
from Flexar.BlueSG.vehicle_route_optimiser_v2 import (
    Rider,
    V2OptimisationResult,
    WorkStyle,
    build_v2_travel_matrix,
    jobs_from_dataframe,
    normalise_v2_roster,
    run_optimiser_v2,
    validate_v2_roster,
)


class RouteSchemaAdapter:
    """Centralises the ROUTE_COLUMNS field names this module reads.

    `residual_riders` and `archive_completed_prefix` used to reach into route
    rows with scattered string literals ("Rider", "Drop-off Address", "Final
    Completion ETA", ...). A `ROUTE_COLUMNS` rename would silently break them
    one at a time. Routing every read through this adapter makes a schema
    change a one-place edit, and gives each lookup a documented purpose.
    """

    RIDER_FIELD = "Rider"
    SEQUENCE_FIELD = "Sequence"
    DROPOFF_ADDRESS_FIELD = "Drop-off Address"
    COMPLETION_ETA_FIELD = "Final Completion ETA"

    @classmethod
    def rider_name(cls, route_row: object) -> str:
        return clean_text(route_row.get(cls.RIDER_FIELD))

    @classmethod
    def sequence(cls, route_row: object) -> object:
        return route_row.get(cls.SEQUENCE_FIELD)

    @classmethod
    def dropoff_address(cls, route_row: object) -> str:
        return clean_text(route_row.get(cls.DROPOFF_ADDRESS_FIELD))

    @classmethod
    def completion_eta(cls, route_row: object) -> object:
        return route_row.get(cls.COMPLETION_ETA_FIELD)


@dataclass(frozen=True)
class HourlyAppendResult:
    dataframe: pd.DataFrame
    appended_job_ids: tuple[str, ...]
    ignored_job_ids: tuple[str, ...]


@dataclass(frozen=True)
class HourlyDispatchResult:
    route_df: pd.DataFrame
    summary_df: pd.DataFrame
    open_route_df: pd.DataFrame
    solver_result: V2OptimisationResult
    recalculation: RecalculationResult
    active_rider_names: tuple[str, ...]


def _aware(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=reference.tzinfo)
    return value.astimezone(reference.tzinfo)


def _with_dispatch_identity(dataframe: pd.DataFrame) -> pd.DataFrame:
    output = dataframe.copy(deep=True).reset_index(drop=True)
    if "_original_order" not in output:
        output["_original_order"] = range(len(output))
    output["_original_order"] = pd.to_numeric(
        output["_original_order"], errors="coerce"
    ).fillna(pd.Series(range(len(output)), index=output.index)).astype(int)
    if "Uploaded Row" not in output:
        output["Uploaded Row"] = output["_original_order"] + 2
    else:
        uploaded = pd.to_numeric(output["Uploaded Row"], errors="coerce")
        output["Uploaded Row"] = uploaded.fillna(output["_original_order"] + 2).astype(int)
    return output


def append_hourly_jobs(
    committed_jobs: pd.DataFrame | None,
    released_jobs: pd.DataFrame,
    *,
    released_at: datetime,
) -> HourlyAppendResult:
    """Validate and append one release without mutating existing job identities."""

    validation = validate_staged_jobs(released_jobs)
    if not validation.is_valid:
        messages = [issue.message for issue in validation.errors]
        raise ValueError(" ".join(messages) or "The hourly release is invalid.")

    existing = (
        _with_dispatch_identity(committed_jobs)
        if isinstance(committed_jobs, pd.DataFrame) and not committed_jobs.empty
        else pd.DataFrame()
    )
    incoming = commit_staged_jobs(validation.dataframe)
    incoming = _with_dispatch_identity(incoming)
    existing_ids = {
        clean_text(value): row
        for value, row in zip(
            existing.get("Job ID", pd.Series(dtype="string")),
            existing.to_dict("records"),
        )
        if clean_text(value)
    }
    accepted: list[dict[str, Any]] = []
    ignored: list[str] = []
    next_order = (
        int(pd.to_numeric(existing["_original_order"], errors="coerce").max()) + 1
        if not existing.empty
        else 0
    )
    identity_fields = ("Car Plate", "Pickup Address", "Drop-off Address")
    for row in incoming.to_dict("records"):
        job_id = clean_text(row.get("Job ID"))
        previous = existing_ids.get(job_id)
        if previous is not None:
            same = all(
                clean_text(previous.get(field)).casefold()
                == clean_text(row.get(field)).casefold()
                for field in identity_fields
            )
            if not same:
                raise ValueError(
                    f"Job ID {job_id} already exists with different route details."
                )
            ignored.append(job_id)
            continue
        row["_original_order"] = next_order
        row["Uploaded Row"] = next_order + 2
        row["Release At"] = released_at.isoformat(timespec="minutes")
        accepted.append(row)
        existing_ids[job_id] = row
        next_order += 1

    appended = pd.DataFrame(accepted)
    if existing.empty:
        combined = appended
    elif appended.empty:
        combined = existing
    else:
        combined = pd.concat([existing, appended], ignore_index=True, sort=False)
    combined = _with_dispatch_identity(combined) if not combined.empty else combined
    return HourlyAppendResult(
        combined.reset_index(drop=True),
        tuple(clean_text(row.get("Job ID")) for row in accepted),
        tuple(ignored),
    )


def live_shift_timeline(roster_df: pd.DataFrame, dispatch_at: datetime) -> pd.DataFrame:
    """Return operator-facing Active/Pending/Ended states for every roster row."""

    roster = normalise_v2_roster(roster_df)
    rows: list[dict[str, Any]] = []
    for source in roster.to_dict("records"):
        name = clean_text(source.get("Rider Name")) or "Unnamed rider"
        if not bool(source.get("Active", True)):
            status = "Inactive"
            shift_start = shift_end = None
        else:
            validation = validate_v2_roster(pd.DataFrame([source]), dispatch_at.date())
            if not validation.is_valid:
                status = "Needs attention"
                shift_start = shift_end = None
            else:
                rider = validation.riders[0]
                shift_start = rider.available_from
                shift_end = rider.available_until
                if shift_start is not None and dispatch_at < _aware(shift_start, dispatch_at):
                    status = "Pending shift start"
                elif shift_end is not None and dispatch_at >= _aware(shift_end, dispatch_at):
                    status = "Shift ended"
                elif shift_end is not None and dispatch_at >= _aware(shift_end, dispatch_at) - timedelta(minutes=10):
                    status = "Shift ending"
                else:
                    status = "Active"
        rows.append(
            {
                "Rider": name,
                "Status": status,
                "Shift start": shift_start,
                "Shift end": shift_end,
                "Start zone": clean_text(source.get("Start Zone")),
                "Work style": clean_text(source.get("Work Style")),
            }
        )
    return pd.DataFrame(rows)


def standby_riders_for_dispatch(roster_df: pd.DataFrame, dispatch_at: datetime) -> list[Rider]:
    """Riders left un-ticked (`Active=False`) but with a parseable shift
    window: the pool a dispatcher can choose to activate for leftover jobs.

    Reuses `validate_v2_roster`'s parsing by temporarily flipping `Active` to
    True, since that function only returns `Rider` objects for active rows.
    A row with no Shift Start/End is excluded rather than treated as
    "always available" - a standby candidate needs a declared window for the
    shift-end buffer check to mean anything.
    """

    roster = normalise_riders(roster_df)
    if "Active" not in roster:
        return []
    inactive = roster[~roster["Active"].fillna(False).astype(bool)].copy()
    if inactive.empty:
        return []
    inactive["Active"] = True
    validation = validate_v2_roster(inactive, dispatch_at.date())
    if not validation.is_valid:
        return []
    return [rider for rider in validation.riders if rider.available_from is not None]


def active_riders_for_dispatch(roster_df: pd.DataFrame, dispatch_at: datetime) -> list[Rider]:
    validation = validate_v2_roster(normalise_riders(roster_df), dispatch_at.date())
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    active: list[Rider] = []
    for rider in validation.riders:
        if rider.available_from is not None and dispatch_at < _aware(rider.available_from, dispatch_at):
            continue
        if rider.available_until is not None and dispatch_at >= _aware(rider.available_until, dispatch_at):
            continue
        active.append(rider)
    return active


def archive_completed_prefix(
    open_routes: pd.DataFrame | None,
    archived_routes: pd.DataFrame | None,
    completed_job_ids: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Move only contiguous completed route prefixes into the immutable archive."""

    current = open_routes.copy(deep=True) if isinstance(open_routes, pd.DataFrame) else pd.DataFrame()
    archive = archived_routes.copy(deep=True) if isinstance(archived_routes, pd.DataFrame) else pd.DataFrame()
    if current.empty or not completed_job_ids:
        return archive, current
    move_indices: list[Any] = []
    for rider, routes in current.groupby(RouteSchemaAdapter.RIDER_FIELD, sort=False):
        ordered = routes.assign(
            _dispatch_seq=pd.to_numeric(
                routes[RouteSchemaAdapter.SEQUENCE_FIELD], errors="coerce"
            )
        ).sort_values("_dispatch_seq", kind="stable")
        seen_open = False
        for index, row in ordered.iterrows():
            completed = stable_job_id_from_route_row(row) in completed_job_ids
            if completed and seen_open:
                raise ValueError(
                    f"Completed jobs for {rider} must be selected in route order."
                )
            if completed:
                move_indices.append(index)
            else:
                seen_open = True
    moved = current.loc[move_indices].copy() if move_indices else pd.DataFrame(columns=current.columns)
    remaining = current.drop(index=move_indices).reset_index(drop=True)
    archive = pd.concat([archive, moved], ignore_index=True, sort=False)
    return archive.reset_index(drop=True), remaining


def _completion_time(row: pd.Series, dispatch_at: datetime) -> datetime:
    parsed = pd.to_datetime(RouteSchemaAdapter.completion_eta(row), errors="coerce")
    if pd.isna(parsed):
        return dispatch_at
    value = parsed.to_pydatetime()
    return _aware(value, dispatch_at)


def residual_riders(
    riders: list[Rider],
    archived_routes: pd.DataFrame | None,
    dispatch_at: datetime,
) -> list[Rider]:
    archive = archived_routes if isinstance(archived_routes, pd.DataFrame) else pd.DataFrame()
    residual: list[Rider] = []
    for rider in riders:
        rows = (
            archive[archive[RouteSchemaAdapter.RIDER_FIELD].apply(clean_text) == rider.name].copy()
            if not archive.empty and RouteSchemaAdapter.RIDER_FIELD in archive
            else pd.DataFrame()
        )
        completed = len(rows)
        if completed >= rider.maximum_jobs:
            continue
        start_location = rider.start_location
        last_completion = rider.last_completion_at
        if not rows.empty:
            rows["_completion"] = rows.apply(
                lambda row: _completion_time(row, dispatch_at), axis=1
            )
            last = rows.sort_values("_completion", kind="stable").iloc[-1]
            start_location = RouteSchemaAdapter.dropoff_address(last) or start_location
            last_completion = last["_completion"]
        available_from = max(
            dispatch_at,
            *(
                [_aware(rider.available_from, dispatch_at)]
                if rider.available_from is not None
                else []
            ),
            *(
                [_aware(last_completion, dispatch_at)]
                if last_completion is not None
                else []
            ),
        )
        if rider.available_until is not None and available_from >= _aware(rider.available_until, dispatch_at):
            continue
        residual.append(
            replace(
                rider,
                start_location=start_location,
                preferred_jobs=max(0, rider.preferred_jobs - completed),
                maximum_jobs=max(1, rider.maximum_jobs - completed),
                available_from=available_from,
                last_completion_at=last_completion,
            )
        )
    return residual


def _summary_from_routes(route_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if route_df is not None and not route_df.empty:
        for rider, routes in route_df.groupby("Rider", sort=False):
            total = float(
                pd.to_numeric(routes["Total Duration Min"], errors="coerce").fillna(0).sum()
            )
            rows.append(
                {
                    "Rider": rider,
                    "Total Jobs": len(routes),
                    "Total Route Duration Min": total,
                    "Adjusted Route Duration Min": total * 1.2,
                    "Within 3 Hours": "OK" if total * 1.2 <= 180 else "Review",
                    "Final Location": clean_text(routes.iloc[-1].get("Drop-off Address")),
                }
            )
    frame = pd.DataFrame(rows)
    for column in SUMMARY_COLUMNS:
        if column not in frame:
            frame[column] = 0 if any(
                token in column for token in ("Distance", "Duration", "Count", "Jobs")
            ) else ""
    return format_summary_output(frame[SUMMARY_COLUMNS], route_df)


def _v1_rider_frame(riders: list[Rider]) -> pd.DataFrame:
    load = {
        WorkStyle.LOCAL: "Low",
        WorkStyle.FLEXIBLE: "Medium",
        WorkStyle.AREA_LEAD: "Priority",
    }
    return pd.DataFrame(
        [
            {
                "Rider Name": rider.name,
                "Start Location": rider.start_location,
                "Start Zone": rider.start_zone,
                "Max Jobs": rider.maximum_jobs,
                "Rider Load": load[rider.work_style],
            }
            for rider in riders
        ]
    )


def combine_dispatch_routes(
    archived_routes: pd.DataFrame | None,
    open_routes: pd.DataFrame | None,
) -> pd.DataFrame:
    parts = [
        frame
        for frame in (archived_routes, open_routes)
        if isinstance(frame, pd.DataFrame) and not frame.empty
    ]
    if not parts:
        return pd.DataFrame(columns=ROUTE_COLUMNS)
    combined = pd.concat(parts, ignore_index=True, sort=False)
    combined["_dispatch_order"] = range(len(combined))
    combined = combined.sort_values(["Rider", "_dispatch_order"], kind="stable")
    combined["Sequence"] = combined.groupby("Rider").cumcount() + 1
    return combined.drop(columns="_dispatch_order").reset_index(drop=True)


def open_jobs_for_dispatch(
    committed_jobs: pd.DataFrame,
    archived_routes: pd.DataFrame | None,
) -> pd.DataFrame:
    """Committed jobs minus whatever is already archived (locked, completed)."""

    archive = archived_routes.copy(deep=True) if isinstance(archived_routes, pd.DataFrame) else pd.DataFrame()
    completed_ids = {stable_job_id_from_route_row(row) for _, row in archive.iterrows()}
    jobs = _with_dispatch_identity(committed_jobs)
    open_mask = jobs.apply(
        lambda row: stable_job_id_from_job(row.to_dict()) not in completed_ids,
        axis=1,
    )
    return jobs[open_mask].reset_index(drop=True)


def operation_context_for_riders(
    riders: list[Rider],
    dispatch_at: datetime,
    *,
    operation_end: datetime | None = None,
    fallback_hours: float = 3.0,
) -> OperationContext:
    """An operation window running from now to the latest rider shift end."""

    latest_shift_end = max(
        (
            _aware(rider.available_until, dispatch_at)
            for rider in riders
            if rider.available_until is not None
        ),
        default=dispatch_at + timedelta(hours=fallback_hours),
    )
    return OperationContext(
        operation_start=dispatch_at,
        operation_end=operation_end or latest_shift_end,
    )


def run_hourly_dispatch(
    *,
    committed_jobs: pd.DataFrame,
    roster_df: pd.DataFrame,
    dispatch_at: datetime,
    archived_routes: pd.DataFrame | None = None,
    confirmed_open_routes: pd.DataFrame | None = None,
    operation_end: datetime | None = None,
    use_onemap: bool = True,
    token: str | None = None,
    beam_width: int = 80,
    time_limit_seconds: float = 30.0,
) -> HourlyDispatchResult:
    """Solve all unfinished jobs, then incrementally rebuild changed open routes."""

    archive = archived_routes.copy(deep=True) if isinstance(archived_routes, pd.DataFrame) else pd.DataFrame()
    confirmed = (
        confirmed_open_routes.copy(deep=True)
        if isinstance(confirmed_open_routes, pd.DataFrame)
        else pd.DataFrame(columns=ROUTE_COLUMNS)
    )
    open_jobs = open_jobs_for_dispatch(committed_jobs, archive)
    active = active_riders_for_dispatch(roster_df, dispatch_at)
    residual = residual_riders(active, archive, dispatch_at)
    if not open_jobs.empty and not residual:
        raise ValueError("No activated rider is currently inside an available shift window.")

    context = operation_context_for_riders(residual, dispatch_at, operation_end=operation_end)
    solver = run_optimiser_v2(
        open_jobs,
        residual,
        operation_context=context,
        use_onemap=use_onemap,
        token=token,
        beam_width=beam_width,
        time_limit_seconds=time_limit_seconds,
    )
    if open_jobs.empty:
        combined = combine_dispatch_routes(archive, pd.DataFrame(columns=ROUTE_COLUMNS))
        recalculation = RecalculationResult(
            pd.DataFrame(columns=ROUTE_COLUMNS),
            _summary_from_routes(pd.DataFrame(columns=ROUTE_COLUMNS)),
            [],
            [],
            {"reused_legs": 0, "reused_loaded": 0, "reused_connectors": 0, "cache_hits": 0, "onemap_requests": 0},
        )
        return HourlyDispatchResult(
            combined,
            _summary_from_routes(combined),
            recalculation.route_df,
            solver,
            recalculation,
            tuple(rider.name for rider in residual),
        )
    if solver.status == "INFEASIBLE":
        empty_recalc = RecalculationResult(
            confirmed,
            _summary_from_routes(confirmed),
            list(solver.infeasible_reasons),
            [],
            {"reused_legs": 0, "reused_loaded": 0, "reused_connectors": 0, "cache_hits": 0, "onemap_requests": 0},
        )
        return HourlyDispatchResult(
            combine_dispatch_routes(archive, confirmed),
            _summary_from_routes(combine_dispatch_routes(archive, confirmed)),
            confirmed,
            solver,
            empty_recalc,
            tuple(rider.name for rider in residual),
        )

    rider_names = [rider.name for rider in residual]
    confirmed_assignment = assignment_from_routes(confirmed, open_jobs, rider_names)
    draft_assignment = assignment_from_routes(solver.route_df, open_jobs, rider_names)
    recalculation = incremental_recalculate(
        confirmed_routes=confirmed,
        confirmed_assignment=confirmed_assignment,
        draft_assignment=draft_assignment,
        rider_df=_v1_rider_frame(residual),
        jobs_df=open_jobs,
        settings={
            "operation_context": context,
            "use_onemap": use_onemap,
            "token": token,
        },
        summary_builder=_summary_from_routes,
        matching_preview_routes=solver.route_df,
    )
    combined = combine_dispatch_routes(archive, recalculation.route_df)
    return HourlyDispatchResult(
        combined,
        _summary_from_routes(combined),
        recalculation.route_df,
        solver,
        recalculation,
        tuple(rider.name for rider in residual),
    )


@dataclass(frozen=True)
class StandbyDispatchOptions:
    """Two comparable views of the same shortfall, for a dual-option UI.

    Option A is `partial_result`: whatever the active roster could place,
    with the rest explicitly listed in `unassigned_jobs`. Option B is
    `standby_recommendation`: Gemini's read on whether to activate a standby
    rider for those leftovers, or None if there was nothing to decide (no
    leftovers, or no standby riders to consider).
    """

    partial_result: V2OptimisationResult
    unassigned_jobs: tuple[dict[str, Any], ...]
    standby_recommendation: StandbyAdvisorResult | None


def idle_minutes_for_rider(rider: Rider, dispatch_at: datetime) -> float:
    """Minutes since a rider's shift started, floored at zero.

    Public (not just an internal helper of `solve_with_standby_options`)
    because the hourly page's backup-pool panel shows this per standby rider
    too, independent of whether a standby review has been run.
    """

    if rider.available_from is None:
        return 0.0
    elapsed = (dispatch_at - _aware(rider.available_from, dispatch_at)).total_seconds() / 60
    return max(0.0, elapsed)


def solve_with_standby_options(
    *,
    open_jobs: pd.DataFrame,
    active_riders: list[Rider],
    standby_riders: list[Rider],
    dispatch_at: datetime,
    operation_context: OperationContext,
    use_onemap: bool = True,
    token: str | None = None,
    beam_width: int = 80,
    time_limit_seconds: float = 30.0,
    gemini_api_key: str | None = None,
) -> StandbyDispatchOptions:
    """Solve the active roster allowing partial coverage ("N of M placed"),
    then - only if jobs are left over and standby riders exist - ask the
    Gemini advisor whether activating one of them is worth it.

    This is deliberately separate from `run_hourly_dispatch`: the rolling
    lock-and-archive path stays all-or-nothing (coverage is mandatory there),
    while this is an explicit, operator-triggered "what if" review.
    """

    partial_result = run_optimiser_v2(
        open_jobs,
        active_riders,
        operation_context=operation_context,
        use_onemap=use_onemap,
        token=token,
        beam_width=beam_width,
        time_limit_seconds=time_limit_seconds,
        allow_partial_assignment=True,
    )
    unassigned = tuple(partial_result.unassigned_jobs)
    if not unassigned or not standby_riders:
        return StandbyDispatchOptions(partial_result, unassigned, None)

    leftover_jobs = jobs_from_dataframe(pd.DataFrame(list(unassigned)))
    travel_matrix = build_v2_travel_matrix(
        leftover_jobs,
        standby_riders,
        operation_context,
        use_onemap=use_onemap,
        token=token,
    )
    travel_minutes: dict[str, dict[str, float]] = {}
    standby_payload: list[dict[str, Any]] = []
    for rider in standby_riders:
        shift_window = (
            f"{rider.available_from:%H:%M}-{rider.available_until:%H:%M}"
            if rider.available_from and rider.available_until
            else "unspecified"
        )
        standby_payload.append(
            {
                "name": rider.name,
                "home_zone": rider.start_zone,
                "shift_window": shift_window,
                "idle_minutes": round(idle_minutes_for_rider(rider, dispatch_at), 1),
            }
        )
        travel_minutes[rider.name] = {
            job.job_id: (
                travel_matrix.empty_cost(rider.start_location, job.pickup_address).duration_min or 0.0
            )
            for job in leftover_jobs
        }

    context = build_standby_context(
        dispatch_at=dispatch_at,
        leftover_jobs=list(unassigned),
        standby_riders=standby_payload,
        travel_minutes=travel_minutes,
    )
    recommendation = recommend_standby_activation(context, api_key=gemini_api_key)
    return StandbyDispatchOptions(partial_result, unassigned, recommendation)
