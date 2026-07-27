"""Canonical data models shared by the BlueSG optimiser and its outputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


TravelConfidence = Literal["verified", "cached_verified", "fallback", "manual"]


@dataclass(frozen=True)
class TravelLegResult:
    origin: str
    destination: str
    mode: str
    distance_km: float
    duration_min: float
    source: str
    confidence: TravelConfidence
    instructions: str | None = None
    route_path: list[list[float]] = field(default_factory=list)
    warning: str | None = None


@dataclass
class RiderRouteMetrics:
    rider_name: str
    assigned_jobs: int
    first_positioning_min: float
    empty_travel_min: float
    loaded_travel_min: float
    pickup_handling_min: float
    dropoff_handling_min: float
    route_time_min: float
    total_duty_time_min: float
    adjusted_duty_time_min: float
    empty_travel_pct: float
    fallback_leg_count: int
    max_jobs_target: int | None
    max_jobs_overage: int
    hard_violation_count: int
    final_location: str
    zone_jump_count: int = 0


@dataclass
class OptimisationRunResult:
    run_id: str
    generated_at: datetime
    algorithm_name: str
    algorithm_version: str
    input_filename: str
    input_sha256: str
    selected_job_date: str
    settings: dict[str, Any]
    assigned_rows: list[dict[str, Any]]
    unassigned_rows: list[dict[str, Any]]
    rider_metrics: list[RiderRouteMetrics]
    warnings: list[dict[str, Any]]
    move_audit: list[dict[str, Any]]
    validation: dict[str, Any]
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a serialisable representation; output sanitisation happens at the boundary."""

        return asdict(self)

