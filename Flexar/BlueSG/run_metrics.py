"""Single-source run metrics and machine-readable artifact persistence."""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from Flexar.BlueSG.models import OptimisationRunResult, RiderRouteMetrics
from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.output_sanitizer import sanitize_for_output
from Flexar.BlueSG.travel_costs import confidence_from_source


ALGORITHM_VERSION = "2.0.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(series: pd.Series | Any) -> pd.Series:
    if isinstance(series, pd.Series):
        return pd.to_numeric(series, errors="coerce").fillna(0.0)
    return pd.Series(dtype=float)


def build_rider_metrics(
    route_df: pd.DataFrame,
    riders: list[Any],
    context: OperationContext,
    validation: dict[str, Any] | None = None,
) -> list[RiderRouteMetrics]:
    rider_by_name = {str(getattr(rider, "name", "")): rider for rider in riders}
    metrics: list[RiderRouteMetrics] = []
    rider_names = sorted(set(rider_by_name) | set(route_df.get("Rider", pd.Series(dtype=str)).dropna().astype(str)))
    violations = list((validation or {}).get("violations", []))
    for rider_name in rider_names:
        rows = route_df[route_df.get("Rider", pd.Series(index=route_df.index, dtype=str)).astype(str) == rider_name].copy()
        if not rows.empty and "Sequence" in rows:
            rows = rows.sort_values("Sequence", kind="stable")
        jobs = len(rows)
        first_positioning = float(_number(rows.get("Empty Duration Min", pd.Series(dtype=float))).iloc[0]) if jobs else 0.0
        all_empty = float(_number(rows.get("Empty Duration Min", pd.Series(dtype=float))).sum())
        empty = max(0.0, all_empty - first_positioning)
        loaded = float(_number(rows.get("Loaded Duration Min", pd.Series(dtype=float))).sum())
        pickup_handling = context.pickup_handling_min * jobs
        dropoff_handling = context.dropoff_handling_min * jobs
        handling = pickup_handling + dropoff_handling + (context.unlock_wait_min * jobs)
        route_time = empty + loaded + handling
        duty = first_positioning + route_time
        adjusted = duty * (1.0 + context.default_operational_buffer_pct)
        movement = empty + loaded
        empty_pct = (empty / movement * 100.0) if movement else 0.0
        fallback_count = 0
        if not rows.empty:
            if "Empty Confidence" in rows:
                fallback_count += int(rows["Empty Confidence"].astype(str).eq("fallback").sum())
            if "Loaded Confidence" in rows:
                fallback_count += int(rows["Loaded Confidence"].astype(str).eq("fallback").sum())
            if "Empty Confidence" not in rows and "Loaded Confidence" not in rows:
                fallback_count = int(rows.get("Cost Source", pd.Series(dtype=str)).apply(confidence_from_source).eq("fallback").sum())
        rider = rider_by_name.get(rider_name)
        max_jobs = getattr(rider, "max_jobs", None)
        final_location = (
            str(rows.iloc[-1].get("Drop-off Address", ""))
            if jobs
            else str(getattr(rider, "start_location", ""))
        )
        zone_values = rows.get("Cluster Name / Zone", pd.Series(dtype=str)).fillna("").astype(str).tolist()
        zone_jumps = sum(1 for left, right in zip(zone_values, zone_values[1:]) if left and right and left != right)
        hard_count = sum(1 for item in violations if not item.get("rider") or str(item.get("rider")) == rider_name)
        metrics.append(
            RiderRouteMetrics(
                rider_name=rider_name,
                assigned_jobs=jobs,
                first_positioning_min=round(first_positioning, 3),
                empty_travel_min=round(empty, 3),
                loaded_travel_min=round(loaded, 3),
                pickup_handling_min=round(pickup_handling, 3),
                dropoff_handling_min=round(dropoff_handling, 3),
                route_time_min=round(route_time, 3),
                total_duty_time_min=round(duty, 3),
                adjusted_duty_time_min=round(adjusted, 3),
                empty_travel_pct=round(empty_pct, 3),
                fallback_leg_count=fallback_count,
                max_jobs_target=max_jobs,
                max_jobs_overage=max(0, jobs - max_jobs) if max_jobs is not None else 0,
                hard_violation_count=hard_count,
                final_location=final_location,
                zone_jump_count=zone_jumps,
            )
        )
    return metrics


def objective_tuple(result: OptimisationRunResult) -> tuple[float | int, ...]:
    """Lexicographic objective: coverage and hard feasibility always dominate quality."""

    used = [metric for metric in result.rider_metrics if metric.assigned_jobs]
    duties = [metric.adjusted_duty_time_min for metric in used]
    maximum = max(duties, default=0.0)
    spread = maximum - min(duties, default=0.0)
    variance = statistics.pvariance(duties) if duties else 0.0
    return (
        len(result.unassigned_rows),
        int(result.validation.get("hard_violation_count", 0)),
        round(maximum, 6),
        round(spread, 6),
        round(variance, 6),
        round(sum(metric.empty_travel_min for metric in used), 6),
        sum(metric.fallback_leg_count for metric in used),
        round(sum(metric.adjusted_duty_time_min for metric in used), 6),
        sum(metric.max_jobs_overage for metric in used),
        sum(metric.zone_jump_count for metric in used),
    )


def build_run_summary(result: OptimisationRunResult) -> dict[str, Any]:
    """Compute every run-level metric from the canonical result object."""

    used = [metric for metric in result.rider_metrics if metric.assigned_jobs > 0]
    duties = [metric.total_duty_time_min for metric in used]
    adjusted = [metric.adjusted_duty_time_min for metric in used]
    total_empty = sum(metric.empty_travel_min for metric in used)
    total_loaded = sum(metric.loaded_travel_min for metric in used)
    movement = total_empty + total_loaded
    regional_exception_count = sum(
        1 for row in result.assigned_rows if str(row.get("Assignment Tier", "")).casefold() == "exceptional"
    )
    regional_support_assignment_count = sum(
        1 for row in result.assigned_rows if str(row.get("Assignment Tier", "")).casefold() == "support"
    )
    summary = {
        "run_id": result.run_id,
        "generated_at": result.generated_at.isoformat(),
        "input_filename": result.input_filename,
        "input_sha256": result.input_sha256,
        "selected_job_date": result.selected_job_date,
        "algorithm_name": result.algorithm_name,
        "algorithm_version": result.algorithm_version,
        "jobs_uploaded": int(result.settings.get("jobs_uploaded", len(result.assigned_rows) + len(result.unassigned_rows))),
        "jobs_selected": len(result.assigned_rows) + len(result.unassigned_rows),
        "jobs_assigned": len(result.assigned_rows),
        "jobs_unassigned": len(result.unassigned_rows),
        "riders_available": len(result.rider_metrics),
        "riders_used": len(used),
        "total_route_time_min": round(sum(metric.route_time_min for metric in used), 1),
        "total_duty_time_min": round(sum(duties), 1),
        "total_adjusted_duty_time_min": round(sum(adjusted), 1),
        "longest_rider_duty_min": round(max(duties, default=0.0), 1),
        "median_rider_duty_min": round(statistics.median(duties), 1) if duties else 0.0,
        "shortest_rider_duty_min": round(min(duties, default=0.0), 1),
        "duty_time_spread_min": round(max(duties, default=0.0) - min(duties, default=0.0), 1),
        "duty_time_variance": round(statistics.pvariance(duties), 3) if duties else 0.0,
        "total_first_positioning_min": round(sum(metric.first_positioning_min for metric in used), 1),
        "total_empty_travel_min": round(total_empty, 1),
        "empty_travel_pct": round(total_empty / movement * 100.0, 1) if movement else 0.0,
        "total_loaded_travel_min": round(total_loaded, 1),
        "fallback_leg_count": sum(metric.fallback_leg_count for metric in used),
        "hard_violation_count": int(result.validation.get("hard_violation_count", 0)),
        "max_jobs_overage_total": sum(metric.max_jobs_overage for metric in used),
        "zone_jump_count": sum(metric.zone_jump_count for metric in used),
        "regional_support_assignment_count": regional_support_assignment_count,
        "unsupported_regional_assignment_count": regional_exception_count,
        "wall_clock_seconds": round(float(result.settings.get("wall_clock_seconds", 0.0)), 3),
        "accepted_local_search_moves": sum(1 for move in result.move_audit if move.get("accepted")),
        "manual_review_warning_count": sum(1 for warning in result.warnings if warning.get("severity") == "manual_review"),
        "settings": result.settings,
        "objective_tuple": list(objective_tuple(result)),
        "manual_feedback": {
            "manual_rider_reassignment_count": None,
            "manual_sequence_change_count": None,
            "jobs_rejected_by_riders": None,
            "incorrect_travel_estimate_count": None,
            "late_completion_count": None,
            "actual_completion_time": None,
            "estimated_completion_time": None,
            "dispatched_without_edits": None,
        },
    }
    result.summary = sanitize_for_output(summary)
    return result.summary


def create_run_result(
    *,
    route_df: pd.DataFrame,
    unassigned_df: pd.DataFrame,
    riders: list[Any],
    context: OperationContext,
    settings: dict[str, Any],
    input_filename: str,
    input_sha256: str,
    selected_job_date: str,
    warnings: list[dict[str, Any]] | None = None,
    move_audit: list[dict[str, Any]] | None = None,
    validation: dict[str, Any] | None = None,
    algorithm_name: str = "state_aware_greedy_insertion",
    algorithm_version: str = ALGORITHM_VERSION,
) -> OptimisationRunResult:
    generated = datetime.now(context.operation_start.tzinfo)
    suffix = "greedy_local_search" if any(move.get("accepted") for move in (move_audit or [])) else "greedy_insertion"
    result = OptimisationRunResult(
        run_id=f"{generated:%Y%m%d_%H%M%S}_{suffix}",
        generated_at=generated,
        algorithm_name=algorithm_name,
        algorithm_version=algorithm_version,
        input_filename=input_filename,
        input_sha256=input_sha256,
        selected_job_date=selected_job_date,
        settings={**settings, "operation_context": context.to_settings()},
        assigned_rows=sanitize_for_output(route_df.to_dict("records")),
        unassigned_rows=sanitize_for_output(unassigned_df.to_dict("records")),
        rider_metrics=[],
        warnings=sanitize_for_output(warnings or []),
        move_audit=sanitize_for_output(move_audit or []),
        validation=sanitize_for_output(validation or {"is_valid": True, "hard_violation_count": 0, "violations": []}),
    )
    result.rider_metrics = build_rider_metrics(route_df, riders, context, result.validation)
    build_run_summary(result)
    return result


def save_run_artifact(result: OptimisationRunResult, root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parents[2] / "runs"
    output_dir = root / result.generated_at.strftime("%Y-%m-%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{result.generated_at:%H%M%S}_{result.algorithm_name}_run_summary.json"
    payload = sanitize_for_output(result.to_dict())
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return output
