"""Bounded, auditable local improvement around the production greedy solution."""

from __future__ import annotations

import copy
import math
import statistics
import time
from typing import Any, Callable, Iterable

from Flexar.BlueSG.constraints import Constraint, validate_candidate_routes
from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.travel_costs import confidence_from_source


CandidateEvaluator = Callable[[dict[str, list[dict[str, Any]]]], dict[str, Any]]


def _job_id(job: dict[str, Any]) -> str:
    for key in ("Stable Job ID", "stable_job_id", "Uploaded Row", "_uploaded_row", "Car Plate"):
        value = job.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    raise ValueError("Every local-search job requires a stable ID, Uploaded Row, or Car Plate.")


def _job_signature(sequences: dict[str, list[dict[str, Any]]]) -> tuple[str, ...]:
    return tuple(sorted(_job_id(job) for jobs in sequences.values() for job in jobs))


def _default_evaluator(
    sequences: dict[str, list[dict[str, Any]]],
    riders: list[Any],
    context: OperationContext,
    settings: dict[str, Any],
    constraints: list[Constraint | dict[str, Any]],
) -> dict[str, Any]:
    validation = validate_candidate_routes(sequences, context, constraints)
    rider_by_name = {str(getattr(rider, "name", "")): rider for rider in riders}
    adjusted_duties: list[float] = []
    total_empty = 0.0
    total_adjusted = 0.0
    fallbacks = 0
    overage = 0
    zone_jumps = 0
    for rider_name in sorted(sequences):
        jobs = sequences[rider_name]
        first = float(jobs[0].get("Empty Duration Min", 0) or 0) if jobs else 0.0
        empty = sum(float(job.get("Empty Duration Min", 0) or 0) for job in jobs[1:])
        loaded = sum(float(job.get("Loaded Duration Min", 0) or 0) for job in jobs)
        handling = len(jobs) * (context.pickup_handling_min + context.dropoff_handling_min + context.unlock_wait_min)
        duty = first + empty + loaded + handling
        adjusted = duty * (1.0 + context.default_operational_buffer_pct)
        if jobs:
            adjusted_duties.append(adjusted)
        total_empty += empty
        total_adjusted += adjusted
        for job in jobs:
            if "Empty Confidence" in job:
                fallbacks += int(str(job.get("Empty Confidence")) == "fallback")
                fallbacks += int(str(job.get("Loaded Confidence")) == "fallback")
            else:
                fallbacks += int(confidence_from_source(job.get("Cost Source")) == "fallback")
        rider = rider_by_name.get(rider_name)
        max_jobs = getattr(rider, "max_jobs", None)
        overage += max(0, len(jobs) - max_jobs) if max_jobs is not None else 0
        zones = [str(job.get("Pickup Zone") or job.get("Cluster Name / Zone") or "") for job in jobs]
        zone_jumps += sum(1 for left, right in zip(zones, zones[1:]) if left and right and left != right)
    maximum = max(adjusted_duties, default=0.0)
    spread = maximum - min(adjusted_duties, default=0.0)
    variance = statistics.pvariance(adjusted_duties) if adjusted_duties else 0.0
    assigned = sum(len(jobs) for jobs in sequences.values())
    objective = (
        0,
        validation.hard_violation_count,
        round(maximum, 6),
        round(spread, 6),
        round(variance, 6),
        round(total_empty, 6),
        fallbacks,
        round(total_adjusted, 6),
        overage,
        zone_jumps,
    )
    return {
        "objective_tuple": objective,
        "jobs_assigned": assigned,
        "unassigned_job_count": 0,
        "hard_constraint_violation_count": validation.hard_violation_count,
        "fallback_leg_count": fallbacks,
        "validation": validation.to_dict(),
    }


def _flagged_riders(
    sequences: dict[str, list[dict[str, Any]]],
    evaluation: dict[str, Any],
    settings: dict[str, Any],
) -> list[str]:
    per_rider = evaluation.get("rider_metrics", {})
    if not per_rider:
        return sorted(sequences)
    duties = [float(value.get("adjusted_duty_time_min", 0) or 0) for value in per_rider.values() if value.get("assigned_jobs", 0)]
    median = statistics.median(duties) if duties else 0.0
    top_cutoff = sorted(duties)[max(0, math.floor(len(duties) * 0.75) - 1)] if duties else 0.0
    duty_threshold = float(settings.get("improvement_duty_threshold_min", 90.0))
    empty_threshold = float(settings.get("improvement_empty_leg_threshold_min", 30.0))
    flagged = []
    for rider in sorted(sequences):
        metric = per_rider.get(rider, {})
        jobs = sequences[rider]
        duty = float(metric.get("adjusted_duty_time_min", 0) or 0)
        if (
            duty > duty_threshold
            or duty > 1.25 * median
            or duty >= top_cutoff
            or metric.get("fallback_leg_count", 0)
            or metric.get("max_jobs_overage", 0)
            or any(float(job.get("Empty Duration Min", 0) or 0) > empty_threshold for job in jobs)
            or int(metric.get("zone_jump_count", 0) or 0) > 1
        ):
            flagged.append(rider)
    return flagged or sorted(sequences)


def _candidate_moves(
    current: dict[str, list[dict[str, Any]]],
    flagged: Iterable[str],
) -> Iterable[tuple[str, str, dict[str, list[dict[str, Any]]], dict[str, Any]]]:
    riders = sorted(current)
    flagged_set = set(flagged)
    for rider in riders:
        if rider not in flagged_set:
            continue
        jobs = current[rider]
        for source in range(len(jobs)):
            for target in range(len(jobs)):
                if source == target:
                    continue
                candidate = copy.deepcopy(current)
                job = candidate[rider].pop(source)
                candidate[rider].insert(target, job)
                yield "intra_rider_reinsertion", _job_id(job), candidate, {"from_rider": rider, "to_rider": rider, "from_position": source, "to_position": target}
        for index in range(len(jobs) - 1):
            candidate = copy.deepcopy(current)
            candidate[rider][index], candidate[rider][index + 1] = candidate[rider][index + 1], candidate[rider][index]
            yield "adjacent_swap", f"{_job_id(jobs[index])},{_job_id(jobs[index + 1])}", candidate, {"from_rider": rider, "to_rider": rider, "from_position": index, "to_position": index + 1}

    for source_rider in riders:
        if source_rider not in flagged_set:
            continue
        for source_index, job in enumerate(current[source_rider]):
            for target_rider in riders:
                if target_rider == source_rider:
                    continue
                for target_index in range(len(current[target_rider]) + 1):
                    candidate = copy.deepcopy(current)
                    moved = candidate[source_rider].pop(source_index)
                    candidate[target_rider].insert(target_index, moved)
                    yield "inter_rider_relocation", _job_id(job), candidate, {"from_rider": source_rider, "to_rider": target_rider, "from_position": source_index, "to_position": target_index}

    for left_index, left_rider in enumerate(riders):
        for right_rider in riders[left_index + 1 :]:
            if left_rider not in flagged_set and right_rider not in flagged_set:
                continue
            for left_pos, left_job in enumerate(current[left_rider]):
                for right_pos, right_job in enumerate(current[right_rider]):
                    candidate = copy.deepcopy(current)
                    candidate[left_rider][left_pos], candidate[right_rider][right_pos] = (
                        candidate[right_rider][right_pos],
                        candidate[left_rider][left_pos],
                    )
                    yield "inter_rider_swap", f"{_job_id(left_job)},{_job_id(right_job)}", candidate, {"from_rider": left_rider, "to_rider": right_rider, "from_position": left_pos, "to_position": right_pos}


def improve_assigned_routes(
    rider_sequences: dict[str, list[dict[str, Any]]],
    riders: list[Any],
    operation_context: OperationContext,
    settings: dict[str, Any],
    constraints: list[Constraint | dict[str, Any]],
    *,
    time_limit_seconds: int = 30,
    max_iterations: int = 100,
    objective: str = "balanced",
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Return improved sequences and a complete audit of evaluated/accepted moves."""

    del objective  # The acceptance rule is intentionally lexicographic for all supported modes.
    evaluator: CandidateEvaluator | None = settings.get("_candidate_evaluator")
    evaluate = evaluator or (lambda candidate: _default_evaluator(candidate, riders, operation_context, settings, constraints))
    current = copy.deepcopy(rider_sequences)
    expected_jobs = _job_signature(current)
    current_evaluation = evaluate(current)
    audit: list[dict[str, Any]] = []
    started = time.monotonic()
    move_number = 0
    iteration = 0
    cancellation_requested: Callable[[], bool] | None = settings.get("_cancellation_requested")

    while iteration < max_iterations and time.monotonic() - started < time_limit_seconds:
        if cancellation_requested and cancellation_requested():
            break
        iteration += 1
        improved = False
        flagged = _flagged_riders(current, current_evaluation, settings)
        for move_type, job_ids, candidate, details in _candidate_moves(current, flagged):
            if time.monotonic() - started >= time_limit_seconds or (cancellation_requested and cancellation_requested()):
                break
            move_number += 1
            before = tuple(current_evaluation["objective_tuple"])
            valid_job_set = _job_signature(candidate) == expected_jobs
            candidate_evaluation = evaluate(candidate) if valid_job_set else {
                "objective_tuple": before,
                "jobs_assigned": -1,
                "unassigned_job_count": 1,
                "hard_constraint_violation_count": 1,
                "fallback_leg_count": math.inf,
                "validation": {"is_valid": False, "violations": [{"kind": "job_set_changed"}]},
            }
            after = tuple(candidate_evaluation["objective_tuple"])
            accepted = bool(
                valid_job_set
                and candidate_evaluation.get("jobs_assigned") == current_evaluation.get("jobs_assigned")
                and candidate_evaluation.get("unassigned_job_count", 0) <= current_evaluation.get("unassigned_job_count", 0)
                and candidate_evaluation.get("hard_constraint_violation_count", 0) == 0
                and candidate_evaluation.get("fallback_leg_count", 0) <= current_evaluation.get("fallback_leg_count", 0)
                and candidate_evaluation.get("regional_exception_count", 0) <= current_evaluation.get("regional_exception_count", 0)
                and candidate_evaluation.get("protected_job_misassignment_count", 0) <= current_evaluation.get("protected_job_misassignment_count", 0)
                and after < before
            )
            reasons = []
            if not valid_job_set:
                reasons.append("job set changed")
            if candidate_evaluation.get("hard_constraint_violation_count", 0):
                reasons.append("hard constraint violation")
            if candidate_evaluation.get("fallback_leg_count", 0) > current_evaluation.get("fallback_leg_count", 0):
                reasons.append("would replace verified travel with fallback")
            if candidate_evaluation.get("regional_exception_count", 0) > current_evaluation.get("regional_exception_count", 0):
                reasons.append("would create an additional unsupported regional exception")
            if candidate_evaluation.get("protected_job_misassignment_count", 0) > current_evaluation.get("protected_job_misassignment_count", 0):
                reasons.append("would move protected West Core work away from a primary rider")
            if after >= before:
                reasons.append("lexicographic objective did not improve")
            audit.append(
                {
                    "move_id": f"M{move_number:06d}",
                    "iteration": iteration,
                    "move_type": move_type,
                    "job_ids": job_ids,
                    **details,
                    "objective_before": list(before),
                    "objective_after": list(after),
                    "accepted": accepted,
                    "rejection_reason": "; ".join(reasons) if not accepted else "",
                    "hard_constraint_status": candidate_evaluation.get("validation", {}),
                    "regional_exception_count_before": current_evaluation.get("regional_exception_count", 0),
                    "regional_exception_count_after": candidate_evaluation.get("regional_exception_count", 0),
                    "protected_job_misassignment_count_before": current_evaluation.get("protected_job_misassignment_count", 0),
                    "protected_job_misassignment_count_after": candidate_evaluation.get("protected_job_misassignment_count", 0),
                    "elapsed_seconds": round(time.monotonic() - started, 6),
                }
            )
            if accepted:
                current = candidate
                current_evaluation = candidate_evaluation
                improved = True
                break
        if not improved:
            break
    return current, audit
