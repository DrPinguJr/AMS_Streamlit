"""Central hard-constraint validation for baseline and local-search candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from Flexar.BlueSG.operation_context import OperationContext


@dataclass(frozen=True)
class Constraint:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    constraint_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "params": dict(self.params),
            "enabled": self.enabled,
            "constraint_id": self.constraint_id,
        }


@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    assigned_job_count: int = 0
    unique_job_count: int = 0

    @property
    def hard_violation_count(self) -> int:
        return len(self.violations)

    def add(self, kind: str, message: str, **details: Any) -> None:
        self.violations.append({"kind": kind, "message": message, **details})
        self.is_valid = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "hard_violation_count": self.hard_violation_count,
            "assigned_job_count": self.assigned_job_count,
            "unique_job_count": self.unique_job_count,
            "violations": list(self.violations),
        }


def _job_id(job: dict[str, Any]) -> str:
    for key in ("Stable Job ID", "stable_job_id", "Uploaded Row", "_uploaded_row", "Car Plate"):
        value = job.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"anonymous:{id(job)}"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _constraints_by_kind(constraints: Iterable[Constraint | dict[str, Any]]) -> dict[str, list[Constraint]]:
    grouped: dict[str, list[Constraint]] = {}
    for item in constraints:
        constraint = item if isinstance(item, Constraint) else Constraint(**item)
        if constraint.enabled:
            grouped.setdefault(constraint.kind, []).append(constraint)
    return grouped


def validate_candidate_routes(
    rider_sequences: dict[str, list[dict[str, Any]]],
    context: OperationContext,
    constraints: list[Constraint | dict[str, Any]],
) -> ValidationResult:
    """Validate all enabled hard constraints in one deterministic pass."""

    grouped = _constraints_by_kind(constraints)
    all_jobs = [(rider, index, job) for rider in sorted(rider_sequences) for index, job in enumerate(rider_sequences[rider])]
    ids = [_job_id(job) for _, _, job in all_jobs]
    result = ValidationResult(True, assigned_job_count=len(ids), unique_job_count=len(set(ids)))

    for rider, index, job in all_jobs:
        job_id = _job_id(job)
        pickup = _clean(job.get("Pickup Address"))
        dropoff = _clean(job.get("Drop-off Address"))
        if not pickup or not dropoff:
            result.add("invalid_address", "Pickup and drop-off are required.", rider=rider, job_id=job_id)
        if index and "Start From" in job:
            prior_dropoff = _clean(rider_sequences[rider][index - 1].get("Drop-off Address"))
            if _clean(job.get("Start From")).casefold() != prior_dropoff.casefold():
                result.add("broken_route_chain", "Route does not start from the previous drop-off.", rider=rider, job_id=job_id)
        if bool(job.get("Reserved Recovery Vehicle")) and not bool(job.get("Recovery Assignment")):
            result.add("reserved_recovery_vehicle", "Reserved recovery vehicle used as a normal job.", rider=rider, job_id=job_id)

    if len(ids) != len(set(ids)):
        duplicates = sorted({job_id for job_id in ids if ids.count(job_id) > 1})
        result.add("duplicate_job_assignment", "A job is assigned more than once.", job_ids=duplicates)

    for constraint in grouped.get("hard_max_jobs", []):
        caps = constraint.params.get("rider_caps", {})
        default_cap = constraint.params.get("max_jobs")
        rider_name = constraint.params.get("rider")
        for rider, jobs in sorted(rider_sequences.items()):
            cap = caps.get(rider, default_cap if not rider_name or rider_name == rider else None)
            if cap is not None and len(jobs) > int(cap):
                result.add("hard_max_jobs", f"{rider} exceeds the hard maximum of {cap} jobs.", rider=rider, actual=len(jobs), maximum=int(cap))

    for constraint in grouped.get("max_total_duty_time", []):
        maximum = float(constraint.params.get("minutes", 0))
        rider_name = constraint.params.get("rider")
        for rider, jobs in sorted(rider_sequences.items()):
            if rider_name and rider != rider_name:
                continue
            duty = max([float(job.get("Projected Total Duty Time Min", job.get("Total Duty Time Min", 0)) or 0) for job in jobs] or [0.0])
            if maximum and duty > maximum:
                result.add("max_total_duty_time", f"{rider} exceeds maximum total duty time.", rider=rider, actual=duty, maximum=maximum)

    positions = {_job_id(job): (rider, index) for rider, index, job in all_jobs}
    for kind in ("fixed_rider_assignment", "rider_cannot_take_job", "job_must_be_first", "job_must_be_last"):
        for constraint in grouped.get(kind, []):
            job_id = str(constraint.params.get("job_id", ""))
            position = positions.get(job_id)
            if position is None:
                continue
            rider, index = position
            target_rider = str(constraint.params.get("rider", ""))
            invalid = (
                (kind == "fixed_rider_assignment" and rider != target_rider)
                or (kind == "rider_cannot_take_job" and rider == target_rider)
                or (kind == "job_must_be_first" and index != 0)
                or (kind == "job_must_be_last" and index != len(rider_sequences[rider]) - 1)
            )
            if invalid:
                result.add(kind, f"Constraint {kind} failed for job {job_id}.", rider=rider, job_id=job_id)

    for constraint in grouped.get("jobs_together", []):
        requested = [str(value) for value in constraint.params.get("job_ids", [])]
        assigned_riders = {positions[job_id][0] for job_id in requested if job_id in positions}
        if len(assigned_riders) > 1:
            result.add("jobs_together", "Jobs that must remain together use different riders.", job_ids=requested)

    for constraint in grouped.get("jobs_separate", []):
        requested = [str(value) for value in constraint.params.get("job_ids", [])]
        assigned = [positions[job_id][0] for job_id in requested if job_id in positions]
        if len(assigned) != len(set(assigned)):
            result.add("jobs_separate", "Jobs that must remain separate use the same rider.", job_ids=requested)

    for constraint in grouped.get("rider_unavailable", []):
        rider = str(constraint.params.get("rider", ""))
        unavailable_start = _as_datetime(constraint.params.get("start"), context)
        unavailable_end = _as_datetime(constraint.params.get("end"), context)
        if rider_sequences.get(rider) and unavailable_start < context.operation_end and unavailable_end > context.operation_start:
            result.add("rider_unavailable", f"{rider} is unavailable during the operating window.", rider=rider)

    for constraint in grouped.get("required_final_location", []):
        rider = str(constraint.params.get("rider", ""))
        expected = _clean(constraint.params.get("location"))
        jobs = rider_sequences.get(rider, [])
        actual = _clean(jobs[-1].get("Drop-off Address")) if jobs else _clean(constraint.params.get("empty_route_location"))
        if expected and actual.casefold() != expected.casefold():
            result.add("required_final_location", f"{rider} does not finish at the required location.", rider=rider, expected=expected, actual=actual)

    for constraint in grouped.get("required_completion_deadline", []):
        deadline = _as_datetime(constraint.params.get("deadline"), context)
        rider = str(constraint.params.get("rider", ""))
        riders = [rider] if rider else sorted(rider_sequences)
        for name in riders:
            jobs = rider_sequences.get(name, [])
            duty = max([float(job.get("Projected Total Duty Time Min", job.get("Total Duty Time Min", 0)) or 0) for job in jobs] or [0.0])
            if context.at_minutes(duty) > deadline:
                result.add("required_completion_deadline", f"{name} completes after the deadline.", rider=name, deadline=deadline.isoformat())

    return result


def _as_datetime(value: Any, context: OperationContext) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=context.operation_start.tzinfo)
    if value:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=context.operation_start.tzinfo)
    return context.operation_start

