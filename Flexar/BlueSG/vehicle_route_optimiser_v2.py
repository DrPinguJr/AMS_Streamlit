"""Vehicle Route Optimiser V2.

V2 is deliberately independent of the V1 scoring tower.  It uses a completed
travel matrix, hard feasibility, assignment severity, Area Lead ownership,
required-end direction, complete coverage, and lexicographic burden fairness.
"""

from __future__ import annotations

import math
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock_time, timedelta
from enum import Enum, IntEnum
from typing import Any, Callable, Iterable

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import (
    ROUTE_COLUMNS,
    SUMMARY_COLUMNS,
    TravelCost,
    adjust_empty_travel_for_public_transport,
    clean_text,
    format_route_output,
    format_summary_output,
    get_empty_travel_cost,
    get_travel_cost,
    infer_zone,
)
from Flexar.BlueSG.regional_capacity_and_cross_region_assignment_rules import (
    ZONE_ADJACENCY,
    normalize_operational_zone,
)
from Flexar.BlueSG.convert_results_to_output_safe_values import sanitize_for_output
from Flexar.BlueSG.route_operation_time_window_settings import OperationContext


AREA_LEAD_OVERRIDE_ADVANTAGE_MINUTES = 12.0
END_REQUIREMENT_BUFFER_MINUTES = 10.0
SHIFT_END_ASSIGNMENT_BUFFER_MINUTES = 10.0
LONG_REPOSITIONING_MINUTES = 35.0
LONG_DISTANCE_CROSS_ZONE_MINUTES = 45.0
OPERATIONALLY_EXTREME_MINUTES = 75.0
DEFAULT_V2_BEAM_WIDTH = 120
DEFAULT_V2_TIME_LIMIT_SECONDS = 45.0
V2_ALGORITHM_NAME = "severity_area_lead_beam_search"
V2_ALGORITHM_VERSION = "2.1.0-rolling-dispatch"
V2ProgressCallback = Callable[[dict[str, Any]], None]

LOCATION_ALIASES = {
    "cck": "Choa Chu Kang",
    "amk": "Ang Mo Kio",
    "je": "Jurong East",
    "jw": "Jurong West",
}

RECOGNISED_ZONES = {
    "west": "West",
    "north_west": "North-West",
    "north": "North",
    "north_east": "North-East",
    "east": "East",
    "central": "Central",
    "south_west": "South-West",
}


class WorkStyle(str, Enum):
    LOCAL = "Local"
    FLEXIBLE = "Flexible"
    AREA_LEAD = "Area Lead"


class AssignmentSeverity(IntEnum):
    PREFERRED = 0
    ACCEPTABLE = 1
    DISLIKED = 2
    LONG_DISTANCE_CROSS_ZONE = 3
    OPERATIONALLY_EXTREME = 4


@dataclass(frozen=True)
class EndRequirement:
    location_text: str
    required_by: datetime
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class Rider:
    name: str
    start_location: str
    start_zone: str
    preferred_jobs: int
    maximum_jobs: int
    work_style: WorkStyle | str
    end_requirement: EndRequirement | None = None
    preferred_areas: frozenset[str] = field(default_factory=frozenset)
    acceptable_areas: frozenset[str] = field(default_factory=frozenset)
    available_from: datetime | None = None
    available_until: datetime | None = None
    last_completion_at: datetime | None = None

    def __post_init__(self) -> None:
        style = self.work_style if isinstance(self.work_style, WorkStyle) else WorkStyle(str(self.work_style))
        object.__setattr__(self, "work_style", style)
        home = normalize_operational_zone(self.start_zone or self.start_location)
        preferred = set(self.preferred_areas) or ({home} if home != "unknown" else set())
        acceptable = set(self.acceptable_areas)
        if home in ZONE_ADJACENCY:
            acceptable.update(ZONE_ADJACENCY[home])
        object.__setattr__(self, "preferred_areas", frozenset(preferred))
        object.__setattr__(self, "acceptable_areas", frozenset(acceptable))

    @property
    def max_jobs(self) -> int:
        """Compatibility property used by existing summaries and exports."""

        return self.maximum_jobs

    @property
    def load_level(self) -> str:
        """Compatibility label used by existing progress and export code."""

        return {
            WorkStyle.LOCAL: "Low",
            WorkStyle.FLEXIBLE: "Medium",
            WorkStyle.AREA_LEAD: "Priority",
        }[self.work_style]


@dataclass(frozen=True)
class FeasibilityResult:
    feasible: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiderBurden:
    disliked_assignments: int = 0
    preferred_job_overage: int = 0
    long_repositioning_trips: int = 0
    long_distance_cross_zone_assignments: int = 0
    operationally_extreme_assignments: int = 0
    empty_travel_minutes: float = 0.0

    @property
    def score(self) -> int:
        return (
            self.disliked_assignments
            + self.preferred_job_overage
            + self.long_repositioning_trips * 3
            + self.long_distance_cross_zone_assignments * 10
            + self.operationally_extreme_assignments * 25
        )


@dataclass(frozen=True)
class PlanMetrics:
    unassigned_jobs: int
    hard_violations: int
    extreme_assignments: int
    cross_zone_assignments: int
    area_lead_violations: int
    fragmented_clusters: int
    maximum_rider_burden: float
    burden_spread: float
    disliked_assignments: int
    preferred_overage: int
    empty_minutes: float
    total_duration: float
    wait_time_penalty: float = 0.0

    def objective(self) -> tuple[float | int, ...]:
        return (
            self.unassigned_jobs,
            self.hard_violations,
            self.extreme_assignments,
            self.cross_zone_assignments,
            self.area_lead_violations,
            self.fragmented_clusters,
            round(self.wait_time_penalty, 6),
            self.maximum_rider_burden,
            self.burden_spread,
            self.disliked_assignments,
            self.preferred_overage,
            round(self.empty_minutes, 6),
            round(self.total_duration, 6),
        )


@dataclass(frozen=True)
class AssignmentExplanation:
    rider_name: str
    job_id: str
    severity: AssignmentSeverity
    empty_travel_minutes: float
    loaded_travel_minutes: float
    projected_job_count: int
    preferred_jobs: int
    maximum_jobs: int
    area_lead_match: bool
    end_progress_minutes: float | None
    estimated_end_arrival: datetime | None
    selected_reasons: tuple[str, ...]
    rejected_alternatives: tuple[dict[str, Any], ...]
    soft_exceptions: tuple[str, ...]
    travel_source: str
    cache_status: str


@dataclass(frozen=True)
class CapacitySummary:
    job_count: int
    rider_count: int
    preferred_capacity: int
    maximum_capacity: int
    required_average: float
    feasible_by_job_count: bool
    shortfall: int = 0


@dataclass
class V2RosterValidationResult:
    is_valid: bool
    riders: list[Rider]
    errors: list[str]
    dataframe: pd.DataFrame


@dataclass(frozen=True)
class V2Job:
    job_id: str
    uploaded_row: int
    original_order: int
    car_plate: str
    pickup_address: str
    pickup_lot: str
    dropoff_address: str
    pickup_zone: str
    dropoff_zone: str
    raw: dict[str, Any]


@dataclass
class TravelMatrix:
    empty: dict[tuple[str, str], TravelCost]
    loaded: dict[tuple[str, str], TravelCost]
    cache_hits: int = 0
    cache_misses: int = 0
    onemap_requests: int = 0
    fallback_routes: int = 0
    failed_routes: int = 0
    runtime_seconds: float = 0.0

    @staticmethod
    def _key(origin: str, destination: str) -> tuple[str, str]:
        return (clean_text(origin).casefold(), clean_text(destination).casefold())

    def empty_cost(self, origin: str, destination: str) -> TravelCost:
        return self.empty.get(
            self._key(origin, destination),
            TravelCost(None, None, "missing precomputed route", "Empty route was not precomputed"),
        )

    def loaded_cost(self, origin: str, destination: str) -> TravelCost:
        return self.loaded.get(
            self._key(origin, destination),
            TravelCost(None, None, "missing precomputed route", "Loaded route was not precomputed"),
        )

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 1.0

    def metrics(self) -> dict[str, float | int]:
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "onemap_requests": self.onemap_requests,
            "fallback_routes": self.fallback_routes,
            "failed_routes": self.failed_routes,
            "runtime_seconds": round(self.runtime_seconds, 3),
        }


@dataclass(frozen=True)
class RouteEvaluation:
    feasibility: FeasibilityResult
    rows: tuple[dict[str, Any], ...]
    burden: RiderBurden
    total_duty_min: float
    adjusted_duty_min: float
    final_location: str
    estimated_end_arrival: datetime | None


@dataclass(frozen=True)
class _Plan:
    routes: tuple[tuple[str, ...], ...]
    evaluations: tuple[RouteEvaluation, ...]
    metrics: PlanMetrics


@dataclass
class V2OptimisationResult:
    route_df: pd.DataFrame
    summary_df: pd.DataFrame
    status: str
    capacity: CapacitySummary
    explanations: list[AssignmentExplanation]
    unassigned_jobs: list[dict[str, Any]]
    infeasible_reasons: list[str]
    objective: tuple[float | int, ...]
    cache_metrics: dict[str, float | int]
    runtime_seconds: float
    algorithm_name: str = V2_ALGORITHM_NAME
    algorithm_version: str = V2_ALGORITHM_VERSION


def _emit_progress(
    callback: V2ProgressCallback | None,
    **event: Any,
) -> None:
    """Keep UI reporting optional and unable to invalidate an optimisation."""

    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        return


def _normalise_space(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return " ".join(str(value or "").strip().split())


def _parse_requirement_time(value: str) -> tuple[int, int]:
    text = _normalise_space(value).upper().replace(".", "")
    for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    raise ValueError(f'Invalid end-requirement time: "{value}".')


def parse_end_requirement(value: str, operation_date: date) -> EndRequirement | None:
    text = _normalise_space(value)
    if not text:
        return None
    match = re.fullmatch(
        r"(?:(?:end\s+in|return\s+to)\s+)?(?P<location>.+?)\s+by\s+(?P<time>.+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(
            f'Could not understand End Requirement: "{text}". '
            "Use a format such as: Woodlands by 4:00 PM"
        )
    location = _normalise_space(match.group("location"))
    if not location:
        raise ValueError(f'End Requirement is missing a location: "{text}".')
    location = LOCATION_ALIASES.get(location.casefold(), location)
    hour, minute = _parse_requirement_time(match.group("time"))
    required_by = datetime.combine(operation_date, datetime.min.time()).replace(hour=hour, minute=minute)
    return EndRequirement(location, required_by)


def _legacy_work_style(value: Any) -> str:
    text = _normalise_space(value).casefold()
    if text in {"low", "local"}:
        return WorkStyle.LOCAL.value
    if text in {"priority", "piority", "area lead"}:
        return WorkStyle.AREA_LEAD.value
    return WorkStyle.FLEXIBLE.value


def normalise_v2_roster(rider_df: pd.DataFrame | None) -> pd.DataFrame:
    """Migrate legacy roster columns without weakening strict V2 validation."""

    source = rider_df.copy(deep=True) if rider_df is not None else pd.DataFrame()
    if "Maximum" not in source:
        source["Maximum"] = source.get("Maximum Jobs", source.get("Max Jobs"))
    if "Preferred" not in source:
        source["Preferred"] = source["Maximum"]
    if "Work Style" not in source:
        load = source.get("Rider Load", pd.Series("Medium", index=source.index))
        source["Work Style"] = load.map(_legacy_work_style)
    if "End Requirement" not in source:
        source["End Requirement"] = ""
    if "Active" not in source:
        if "Active Status" in source:
            source["Active"] = source["Active Status"].apply(
                lambda value: _normalise_space(value).casefold()
                in {"active", "yes", "true", "1", "on"}
            )
        else:
            source["Active"] = True
    if "Shift Start" not in source:
        source["Shift Start"] = source.get("Available From", "")
    if "Shift End" not in source:
        source["Shift End"] = source.get("Available Until", "")
    defaults = {
        "Rider Name": "",
        "Start Location": "",
        "Start Zone": "",
        "Preferred": None,
        "Maximum": None,
        "Work Style": WorkStyle.FLEXIBLE.value,
        "End Requirement": "",
        "Active": True,
        "Shift Start": "",
        "Shift End": "",
    }
    for column, default in defaults.items():
        if column not in source:
            source[column] = default
    return source.loc[:, list(defaults)].reset_index(drop=True)


def _strict_integer(value: Any, label: str, rider_name: str, minimum: int) -> tuple[int | None, str | None]:
    if isinstance(value, bool) or isinstance(value, str):
        return None, f"{rider_name}: {label} must be entered as a number, not text."
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{rider_name}: {label} must be a whole number."
    if not math.isfinite(number) or not number.is_integer():
        return None, f"{rider_name}: {label} must be a whole number."
    parsed = int(number)
    if parsed < minimum:
        return None, f"{rider_name}: {label} must be at least {minimum}."
    return parsed, None


def _parse_shift_time(value: Any, operation_date: date, label: str) -> datetime | None:
    """Parse roster clocks while keeping the public sheet format human-friendly."""

    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        parsed_time = value.time()
    elif isinstance(value, clock_time):
        parsed_time = value
    else:
        text = _normalise_space(value).upper().replace(".", "")
        if not text:
            return None
        parsed_time = None
        for pattern in ("%I:%M %p", "%I %p", "%H:%M", "%H%M"):
            try:
                parsed_time = datetime.strptime(text, pattern).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            raise ValueError(
                f'{label} "{value}" is invalid. Use a time such as 1:00 PM or 16:00.'
            )
    zone = OperationContext().operation_start.tzinfo
    return datetime.combine(operation_date, parsed_time).replace(tzinfo=zone)


def validate_v2_roster(rider_df: pd.DataFrame, operation_date: date) -> V2RosterValidationResult:
    dataframe = normalise_v2_roster(rider_df)
    active = dataframe[dataframe["Active"].fillna(True).astype(bool)].copy()
    errors: list[str] = []
    riders: list[Rider] = []
    names_seen: dict[str, str] = {}
    for row_number, row in active.iterrows():
        row_errors: list[str] = []
        name = _normalise_space(row.get("Rider Name"))
        display_name = name or f"Row {row_number + 1}"
        start = _normalise_space(row.get("Start Location"))
        zone_text = _normalise_space(row.get("Start Zone"))
        if not name:
            row_errors.append(f"Row {row_number + 1}: Rider Name is required.")
        if not start:
            row_errors.append(f"{display_name}: Start Location is required.")
        zone = normalize_operational_zone(zone_text)
        if zone == "unknown":
            row_errors.append(f'{display_name}: Unrecognised Start Zone "{zone_text}".')
        preferred, preferred_error = _strict_integer(row.get("Preferred"), "Preferred Jobs", display_name, 0)
        maximum, maximum_error = _strict_integer(row.get("Maximum"), "Maximum Jobs", display_name, 1)
        if preferred_error:
            row_errors.append(preferred_error)
        if maximum_error:
            row_errors.append(maximum_error)
        if preferred is not None and maximum is not None and preferred > maximum:
            row_errors.append(
                f"{display_name}: Preferred Jobs cannot exceed Maximum Jobs. "
                f"Preferred = {preferred}; Maximum = {maximum}."
            )
        style_text = _normalise_space(row.get("Work Style"))
        try:
            style = WorkStyle(style_text)
        except ValueError:
            style = None
            row_errors.append(
                f'{display_name}: Unknown Work Style "{style_text}". '
                "Use Local, Flexible, or Area Lead."
            )
        end_requirement = None
        try:
            end_requirement = parse_end_requirement(_normalise_space(row.get("End Requirement")), operation_date)
        except ValueError as exc:
            row_errors.append(f"{display_name}: {exc}")
        available_from = available_until = None
        try:
            available_from = _parse_shift_time(row.get("Shift Start"), operation_date, "Shift Start")
            available_until = _parse_shift_time(row.get("Shift End"), operation_date, "Shift End")
            if (available_from is None) != (available_until is None):
                row_errors.append(
                    f"{display_name}: Shift Start and Shift End must either both be entered or both be blank."
                )
            elif available_from is not None and available_until is not None:
                if available_until <= available_from:
                    available_until += timedelta(days=1)
                if available_until - available_from < timedelta(minutes=20):
                    row_errors.append(f"{display_name}: Shift Window must be at least 20 minutes.")
        except ValueError as exc:
            row_errors.append(f"{display_name}: {exc}")
        folded = name.casefold()
        if folded and folded in names_seen:
            row_errors.append(f"Duplicate rider name: {name}.")
        elif folded:
            names_seen[folded] = name
        errors.extend(row_errors)
        if (
            name
            and start
            and zone != "unknown"
            and preferred is not None
            and maximum is not None
            and preferred <= maximum
            and style is not None
            and not row_errors
        ):
            required = end_requirement
            if required is not None:
                required = EndRequirement(
                    required.location_text,
                    required.required_by.replace(tzinfo=OperationContext().operation_start.tzinfo),
                )
            riders.append(
                Rider(
                    name=name,
                    start_location=start,
                    start_zone=RECOGNISED_ZONES[zone],
                    preferred_jobs=preferred,
                    maximum_jobs=maximum,
                    work_style=style,
                    end_requirement=required,
                    available_from=available_from,
                    available_until=available_until,
                )
            )
    if active.empty:
        errors.append("At least one rider must be active.")
    return V2RosterValidationResult(not errors, riders if not errors else [], errors, dataframe)


def capacity_summary(jobs: int | Iterable[Any], riders: Iterable[Rider]) -> CapacitySummary:
    job_count = jobs if isinstance(jobs, int) else len(list(jobs))
    rider_list = list(riders)
    preferred = sum(rider.preferred_jobs for rider in rider_list)
    maximum = sum(rider.maximum_jobs for rider in rider_list)
    shortfall = max(0, int(job_count) - maximum)
    return CapacitySummary(
        int(job_count),
        len(rider_list),
        preferred,
        maximum,
        round(int(job_count) / len(rider_list), 2) if rider_list else math.inf,
        maximum >= int(job_count),
        shortfall,
    )


def _job_zone(value: Any, address: str) -> str:
    return normalize_operational_zone(value or infer_zone(address) or address)


def jobs_from_dataframe(jobs_df: pd.DataFrame) -> list[V2Job]:
    jobs: list[V2Job] = []
    for index, row in jobs_df.reset_index(drop=True).iterrows():
        raw = row.to_dict()
        pickup = clean_text(row.get("Pickup Address"))
        dropoff = clean_text(row.get("Drop-off Address"))
        uploaded = pd.to_numeric(row.get("Uploaded Row", row.get("_uploaded_row", index + 2)), errors="coerce")
        uploaded_row = index + 2 if pd.isna(uploaded) else int(uploaded)
        original = pd.to_numeric(row.get("_original_order", index), errors="coerce")
        original_order = index if pd.isna(original) else int(original)
        job_id = clean_text(row.get("Job ID")) or f"row-{uploaded_row}"
        jobs.append(
            V2Job(
                job_id=job_id,
                uploaded_row=uploaded_row,
                original_order=original_order,
                car_plate=clean_text(row.get("Car Plate")),
                pickup_address=pickup,
                pickup_lot=clean_text(row.get("Pickup Lot")),
                dropoff_address=dropoff,
                pickup_zone=_job_zone(row.get("Pickup Zone"), pickup),
                dropoff_zone=_job_zone(row.get("Drop-off Zone"), dropoff),
                raw=raw,
            )
        )
    return jobs


def _record_matrix_source(matrix: TravelMatrix, cost: TravelCost) -> None:
    source = clean_text(cost.source).casefold()
    if "cache" in source:
        matrix.cache_hits += 1
    else:
        matrix.cache_misses += 1
    if "onemap" in source and "cache" not in source:
        matrix.onemap_requests += 1
    if "fallback" in source or "estimate" in source:
        matrix.fallback_routes += 1
    # A fallback may carry the provider error that caused the fallback while
    # still containing a usable duration. Count only unusable matrix entries as
    # failed routes.
    if cost.duration_min is None:
        matrix.failed_routes += 1


def build_v2_travel_matrix(
    jobs: list[V2Job],
    riders: list[Rider],
    operation_context: OperationContext,
    *,
    use_onemap: bool = True,
    token: str | None = None,
    empty_duration_multiplier: float = 1.5,
    empty_wait_buffer_min: float = 6.0,
    max_workers: int = 4,
    progress_callback: V2ProgressCallback | None = None,
) -> TravelMatrix:
    """Fetch every solver route before search; the search performs no I/O."""

    started = time.monotonic()
    matrix = TravelMatrix({}, {})
    origins = {rider.start_location for rider in riders} | {job.dropoff_address for job in jobs}
    pickups = {job.pickup_address for job in jobs}
    end_locations = {
        rider.end_requirement.location_text
        for rider in riders
        if rider.end_requirement is not None
    }
    empty_pairs = {
        (origin, destination)
        for origin in origins
        for destination in pickups | end_locations
        if clean_text(origin) and clean_text(destination)
    }
    loaded_pairs = {
        (job.pickup_address, job.dropoff_address)
        for job in jobs
        if job.pickup_address and job.dropoff_address
    }

    def fetch_empty(pair: tuple[str, str]) -> tuple[str, tuple[str, str], TravelCost]:
        origin, destination = pair
        cost = get_empty_travel_cost(
            origin,
            destination,
            infer_zone(origin),
            infer_zone(destination),
            use_onemap=use_onemap,
            token=token,
            allow_walk=False,
            operation_context=operation_context,
        )
        cost = adjust_empty_travel_for_public_transport(
            cost,
            duration_multiplier=empty_duration_multiplier,
            wait_buffer_min=empty_wait_buffer_min,
        )
        return "empty", pair, cost

    def fetch_loaded(pair: tuple[str, str]) -> tuple[str, tuple[str, str], TravelCost]:
        origin, destination = pair
        return (
            "loaded",
            pair,
            get_travel_cost(
                origin,
                destination,
                infer_zone(origin),
                infer_zone(destination),
                use_onemap=use_onemap,
                token=token,
                route_type="drive",
                operation_context=operation_context,
            ),
        )

    calls = [(fetch_empty, pair) for pair in sorted(empty_pairs)] + [
        (fetch_loaded, pair) for pair in sorted(loaded_pairs)
    ]
    total_calls = len(calls)
    _emit_progress(
        progress_callback,
        phase="Travel matrix",
        event_type="v2_matrix",
        status=f"Preparing {total_calls:,} distinct travel routes...",
        progress=0.03,
        matrix_completed=0,
        matrix_total=total_calls,
        comparison_count=0,
        estimated_comparisons=total_calls,
    )
    report_every = max(1, total_calls // 50)
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="bluesg-v2-matrix") as pool:
        futures = [pool.submit(function, pair) for function, pair in calls]
        for completed, future in enumerate(as_completed(futures), start=1):
            kind, pair, cost = future.result()
            target = matrix.empty if kind == "empty" else matrix.loaded
            target[TravelMatrix._key(*pair)] = cost
            _record_matrix_source(matrix, cost)
            if completed == 1 or completed == total_calls or completed % report_every == 0:
                _emit_progress(
                    progress_callback,
                    phase="Travel matrix",
                    event_type="v2_matrix",
                    status=f"Loaded {completed:,} of {total_calls:,} travel routes.",
                    progress=0.03 + (0.42 * completed / max(1, total_calls)),
                    matrix_completed=completed,
                    matrix_total=total_calls,
                    comparison_count=completed,
                    estimated_comparisons=total_calls,
                    cache_hits=matrix.cache_hits,
                    cache_misses=matrix.cache_misses,
                    onemap_requests=matrix.onemap_requests,
                    fallback_routes=matrix.fallback_routes,
                    current_origin=pair[0],
                    current_destination=pair[1],
                    current_route_kind=kind,
                )
    matrix.runtime_seconds = time.monotonic() - started
    return matrix


def _minutes(cost: TravelCost) -> float:
    return float(cost.duration_min) if cost.duration_min is not None else math.inf


def _display_time(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _is_adjacent(left: str, right: str) -> bool:
    return left in ZONE_ADJACENCY and right in ZONE_ADJACENCY[left]


def _severity_for_assignment(
    rider: Rider,
    current_zone: str,
    job: V2Job,
    empty_minutes: float,
    end_progress_minutes: float | None,
    minutes_to_requirement: float | None,
) -> AssignmentSeverity:
    home = normalize_operational_zone(rider.start_zone)
    current = normalize_operational_zone(current_zone)
    pickup = job.pickup_zone
    adjacent = _is_adjacent(current, pickup) and _is_adjacent(home, pickup)
    if empty_minutes >= OPERATIONALLY_EXTREME_MINUTES:
        severity = AssignmentSeverity.OPERATIONALLY_EXTREME
    elif (not adjacent and empty_minutes >= LONG_REPOSITIONING_MINUTES) or empty_minutes >= LONG_DISTANCE_CROSS_ZONE_MINUTES:
        severity = AssignmentSeverity.LONG_DISTANCE_CROSS_ZONE
    elif rider.work_style == WorkStyle.AREA_LEAD:
        severity = AssignmentSeverity.PREFERRED if pickup == home and empty_minutes <= 30 else AssignmentSeverity.ACCEPTABLE if adjacent and empty_minutes <= 25 else AssignmentSeverity.DISLIKED
    elif rider.work_style == WorkStyle.LOCAL:
        severity = AssignmentSeverity.PREFERRED if pickup == home and current == pickup and empty_minutes <= 25 else AssignmentSeverity.ACCEPTABLE if adjacent and empty_minutes <= 25 else AssignmentSeverity.DISLIKED
    else:
        severity = AssignmentSeverity.PREFERRED if current == pickup and empty_minutes <= 30 else AssignmentSeverity.ACCEPTABLE if adjacent and empty_minutes <= 35 else AssignmentSeverity.DISLIKED
    if end_progress_minutes is not None and end_progress_minutes < 0 and minutes_to_requirement is not None:
        if minutes_to_requirement <= 30:
            severity = AssignmentSeverity(min(int(severity) + 2, int(AssignmentSeverity.OPERATIONALLY_EXTREME)))
        elif minutes_to_requirement <= 60:
            severity = AssignmentSeverity(min(int(severity) + 1, int(AssignmentSeverity.OPERATIONALLY_EXTREME)))
        elif end_progress_minutes <= -10 and severity <= AssignmentSeverity.DISLIKED:
            # Direction is a soft preference throughout route construction, not
            # merely a final return check. It never masks an already severe
            # cross-zone classification.
            severity = AssignmentSeverity(int(severity) + 1)
    elif (
        end_progress_minutes is not None
        and end_progress_minutes >= 10
        and severity == AssignmentSeverity.DISLIKED
    ):
        severity = AssignmentSeverity.ACCEPTABLE
    return severity


def _job_exclusion_reasons(rider: Rider, job: V2Job) -> list[str]:
    reasons: list[str] = []
    fixed = clean_text(job.raw.get("Fixed Rider") or job.raw.get("Required Rider"))
    if fixed and fixed.casefold() != rider.name.casefold():
        reasons.append(f"Job is fixed to {fixed}.")
    excluded_text = clean_text(job.raw.get("Excluded Riders") or job.raw.get("Rider Exclusions"))
    excluded = {part.strip().casefold() for part in re.split(r"[,;|]", excluded_text) if part.strip()}
    if rider.name.casefold() in excluded:
        reasons.append("Rider is explicitly excluded from this job.")
    return reasons


def evaluate_v2_route(
    rider: Rider,
    sequence: tuple[str, ...],
    jobs_by_id: dict[str, V2Job],
    matrix: TravelMatrix,
    operation_context: OperationContext,
) -> RouteEvaluation:
    reasons: list[str] = []
    if len(sequence) > rider.maximum_jobs:
        reasons.append(f"Maximum Jobs hard limit is {rider.maximum_jobs}.")
    current_location = rider.start_location
    current_zone = normalize_operational_zone(rider.start_zone or rider.start_location)
    start_at = operation_context.operation_start
    if rider.available_from is not None and rider.available_from > start_at:
        start_at = rider.available_from
    elapsed = max(0.0, (start_at - operation_context.operation_start).total_seconds() / 60.0)
    rows: list[dict[str, Any]] = []
    severities: list[AssignmentSeverity] = []
    empty_total = 0.0
    end_arrival: datetime | None = None
    for position, job_id in enumerate(sequence, start=1):
        job = jobs_by_id[job_id]
        reasons.extend(_job_exclusion_reasons(rider, job))
        if not job.pickup_address or not job.dropoff_address:
            reasons.append(f"{job_id} is missing a pickup or drop-off address.")
            break
        empty = matrix.empty_cost(current_location, job.pickup_address)
        loaded = matrix.loaded_cost(job.pickup_address, job.dropoff_address)
        empty_min = _minutes(empty)
        loaded_min = _minutes(loaded)
        if not math.isfinite(empty_min) or not math.isfinite(loaded_min):
            reasons.append(f"No complete travel route is available for {job_id}.")
            break
        before_to_end = after_to_end = None
        end_progress = None
        if rider.end_requirement is not None:
            before_to_end = _minutes(matrix.empty_cost(current_location, rider.end_requirement.location_text))
            after_to_end = _minutes(matrix.empty_cost(job.dropoff_address, rider.end_requirement.location_text))
            if math.isfinite(before_to_end) and math.isfinite(after_to_end):
                end_progress = before_to_end - after_to_end
        minutes_to_requirement = None
        if rider.end_requirement is not None:
            now = operation_context.at_minutes(elapsed)
            minutes_to_requirement = (rider.end_requirement.required_by - now).total_seconds() / 60.0
        severity = _severity_for_assignment(
            rider,
            current_zone,
            job,
            empty_min,
            end_progress,
            minutes_to_requirement,
        )
        elapsed += empty_min + operation_context.pickup_handling_min + operation_context.unlock_wait_min
        pickup_eta = operation_context.at_minutes(elapsed)
        elapsed += loaded_min + operation_context.dropoff_handling_min
        completion = operation_context.at_minutes(elapsed)
        if completion > operation_context.operation_end:
            reasons.append(f"{job_id} would complete after the operation end.")
        if rider.available_until is not None:
            assignment_cutoff = rider.available_until - timedelta(
                minutes=SHIFT_END_ASSIGNMENT_BUFFER_MINUTES
            )
            if completion > assignment_cutoff:
                reasons.append(
                    f"{job_id} would complete within the {SHIFT_END_ASSIGNMENT_BUFFER_MINUTES:.0f}-minute "
                    f"shift-end buffer for {rider.name}."
                )
        empty_total += empty_min
        severities.append(severity)
        source = f"{empty.source} / {loaded.source}"
        rows.append(
            {
                "Rider": rider.name,
                "Sequence": position,
                "Uploaded Row": job.uploaded_row,
                "Start From": current_location,
                "Empty Travel To Pickup": f"{current_location} -> {job.pickup_address}",
                "Empty PT Instructions": empty.route_text,
                "Empty Route Path": "[]",
                "Car Plate": job.car_plate,
                "Pickup Address": job.pickup_address,
                "Pickup Lot": job.pickup_lot,
                "Drop-off Address": job.dropoff_address,
                "Loaded Travel / Car Movement": f"{job.pickup_address} -> {job.dropoff_address}",
                "Loaded Drive Instructions": loaded.route_text,
                "Loaded Route Path": "[]",
                "Empty Distance KM": empty.distance_km,
                "Empty Duration Min": round(empty_min, 1),
                "Loaded Distance KM": loaded.distance_km,
                "Loaded Duration Min": round(loaded_min, 1),
                "Total Distance KM": round(float(empty.distance_km or 0) + float(loaded.distance_km or 0), 2),
                "Total Duration Min": round(empty_min + loaded_min, 1),
                "Assignment Score": int(severity),
                "Zone Adjustment": 0,
                "Same Zone Pickup": "Yes" if current_zone == job.pickup_zone else "No",
                "Same Zone Route": "Yes" if job.pickup_zone == job.dropoff_zone else "No",
                "Route Zone Priority": int(severity),
                "Projected Rider Duration Min": round(elapsed, 1),
                "Projected Adjusted Duration Min": round(elapsed * (1 + operation_context.default_operational_buffer_pct), 1),
                "First Positioning PT Duration Min": round(empty_total if position == 1 else float(rows[0]["Empty Duration Min"]), 1),
                "First Pickup ETA": pickup_eta.isoformat(timespec="minutes") if position == 1 else rows[0]["First Pickup ETA"],
                "Latest Departure Time": operation_context.operation_start.isoformat(timespec="minutes"),
                "In-Window Route Duration Min": round(elapsed, 1),
                "Final Completion ETA": completion.isoformat(timespec="minutes"),
                "Cluster Name / Zone": job.pickup_zone,
                "Cluster Job Count": sum(jobs_by_id[item].pickup_zone == job.pickup_zone for item in sequence),
                "Feasibility Status": "OK",
                "Reason if Unassigned": "",
                "Cost Source": source,
                "Empty Confidence": empty.confidence,
                "Loaded Confidence": loaded.confidence,
                "Travel Warning": " | ".join(filter(None, [empty.warning, loaded.warning])),
                "Pickup Handling Min": operation_context.pickup_handling_min,
                "Drop-off Handling Min": operation_context.dropoff_handling_min,
                "Unlock Wait Min": operation_context.unlock_wait_min,
                "Route Time Min": round(elapsed, 1),
                "Total Duty Time Min": round(elapsed, 1),
                "Adjusted Duty Time Min": round(elapsed * (1 + operation_context.default_operational_buffer_pct), 1),
                "Route Validation Status": "OK",
                "Rider Home Zone": normalize_operational_zone(rider.start_zone),
                "Current Operational Zone": current_zone,
                "Pickup Operational Zone": job.pickup_zone,
                "Geographic Assignment Rank": int(severity),
                "Geographic Assignment Status": severity.name.casefold(),
                "Geographic Exception Reason": "" if severity < AssignmentSeverity.LONG_DISTANCE_CROSS_ZONE else "Required by V2 complete-assignment search.",
                "Job Region": job.pickup_zone,
                "Operational Subregion": job.pickup_zone,
                "Region Confidence": "v2_normalised",
                "Assigned Rider Home Region": normalize_operational_zone(rider.start_zone),
                "Assigned Rider Current Region Before Job": current_zone,
                "Assignment Tier": severity.name.casefold(),
                "Regional Specificity Score": 0,
                "Regional Support Penalty": 0,
                "Scarce Driver Protection Penalty": 0,
                "Unsupported Region Penalty": 0,
                "Reason for Regional Assignment": severity.name.replace("_", " ").title(),
                "V2 Job ID": job.job_id,
                "Assignment Severity": severity.name,
                "Work Style": rider.work_style.value,
                "Preferred Jobs": rider.preferred_jobs,
                "Maximum Jobs": rider.maximum_jobs,
                "Area Lead Match": rider.work_style == WorkStyle.AREA_LEAD and job.pickup_zone == normalize_operational_zone(rider.start_zone),
                "End Progress Min": round(end_progress, 1) if end_progress is not None else None,
                "Estimated Required-End Arrival": "",
                "Empty Cache Status": "hit" if "cache" in empty.source.casefold() else "miss",
                "Loaded Cache Status": "hit" if "cache" in loaded.source.casefold() else "miss",
            }
        )
        current_location = job.dropoff_address
        current_zone = job.dropoff_zone
    if not reasons and rider.end_requirement is not None:
        return_cost = matrix.empty_cost(current_location, rider.end_requirement.location_text)
        return_min = _minutes(return_cost)
        if not math.isfinite(return_min):
            reasons.append("Required end destination has no valid return route.")
        else:
            end_elapsed = elapsed + return_min + END_REQUIREMENT_BUFFER_MINUTES
            end_arrival = operation_context.at_minutes(end_elapsed)
            if end_arrival > rider.end_requirement.required_by:
                reasons.append(
                    f"Required destination arrival would be {_display_time(end_arrival)}, "
                    f"after {_display_time(rider.end_requirement.required_by)}."
                )
            if rider.available_until is not None and end_arrival > rider.available_until:
                reasons.append(
                    f"Required destination arrival would be after {rider.name}'s shift end."
                )
            if rows:
                rows[-1]["Estimated Required-End Arrival"] = end_arrival.isoformat(timespec="minutes")
    overage = max(0, len(sequence) - rider.preferred_jobs)
    burden = RiderBurden(
        disliked_assignments=sum(value == AssignmentSeverity.DISLIKED for value in severities),
        preferred_job_overage=overage,
        long_repositioning_trips=sum(float(row["Empty Duration Min"]) >= LONG_REPOSITIONING_MINUTES for row in rows),
        long_distance_cross_zone_assignments=sum(value == AssignmentSeverity.LONG_DISTANCE_CROSS_ZONE for value in severities),
        operationally_extreme_assignments=sum(value == AssignmentSeverity.OPERATIONALLY_EXTREME for value in severities),
        empty_travel_minutes=empty_total,
    )
    return RouteEvaluation(
        FeasibilityResult(not reasons, tuple(dict.fromkeys(reasons))),
        tuple(rows),
        burden,
        elapsed,
        elapsed * (1 + operation_context.default_operational_buffer_pct),
        current_location,
        end_arrival,
    )


def check_hard_feasibility(
    rider: Rider,
    route: tuple[str, ...],
    candidate_job: V2Job,
    travel_matrix: TravelMatrix,
    *,
    jobs_by_id: dict[str, V2Job],
    operation_context: OperationContext,
    insert_at: int | None = None,
) -> FeasibilityResult:
    position = len(route) if insert_at is None else int(insert_at)
    candidate = route[:position] + (candidate_job.job_id,) + route[position:]
    return evaluate_v2_route(rider, candidate, jobs_by_id, travel_matrix, operation_context).feasibility


def _lead_by_zone(riders: list[Rider]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for index, rider in enumerate(riders):
        if rider.work_style == WorkStyle.AREA_LEAD:
            result.setdefault(normalize_operational_zone(rider.start_zone), []).append(index)
    return result


def _area_lead_violation_count(
    routes: tuple[tuple[str, ...], ...],
    evaluations: tuple[RouteEvaluation, ...],
    riders: list[Rider],
    jobs_by_id: dict[str, V2Job],
    matrix: TravelMatrix,
    operation_context: OperationContext,
) -> int:
    leads = _lead_by_zone(riders)
    assigned_to = {job_id: rider_index for rider_index, route in enumerate(routes) for job_id in route}
    violations = 0
    for job_id, rider_index in assigned_to.items():
        job = jobs_by_id[job_id]
        zone_leads = leads.get(job.pickup_zone, [])
        if not zone_leads or rider_index in zone_leads:
            continue
        available_leads = [index for index in zone_leads if len(routes[index]) < riders[index].maximum_jobs]
        if not available_leads:
            continue
        assigned_row = next((row for row in evaluations[rider_index].rows if row.get("V2 Job ID") == job_id), {})
        assigned_value = assigned_row.get("Empty Duration Min")
        assigned_empty = math.inf if assigned_value is None or pd.isna(assigned_value) else float(assigned_value)
        lead_empty = math.inf
        for lead_index in available_leads:
            lead_route = routes[lead_index]
            for position in range(len(lead_route) + 1):
                candidate_route = (
                    lead_route[:position] + (job_id,) + lead_route[position:]
                )
                if not evaluate_v2_route(
                    riders[lead_index],
                    candidate_route,
                    jobs_by_id,
                    matrix,
                    operation_context,
                ).feasibility.feasible:
                    continue
                candidate_location = riders[lead_index].start_location if position == 0 else jobs_by_id[lead_route[position - 1]].dropoff_address
                lead_empty = min(
                    lead_empty,
                    _minutes(matrix.empty_cost(candidate_location, job.pickup_address)),
                )
        if assigned_empty + AREA_LEAD_OVERRIDE_ADVANTAGE_MINUTES > lead_empty:
            violations += 1
    return violations


def _fragmented_lead_clusters(routes: tuple[tuple[str, ...], ...], riders: list[Rider], jobs_by_id: dict[str, V2Job]) -> int:
    fragments = 0
    for index, rider in enumerate(riders):
        if rider.work_style != WorkStyle.AREA_LEAD:
            continue
        home = normalize_operational_zone(rider.start_zone)
        flags = [jobs_by_id[job_id].pickup_zone == home for job_id in routes[index]]
        fragments += sum(flags[position - 1] and not flags[position] for position in range(1, len(flags)))
    return fragments


def _plan_metrics(
    routes: tuple[tuple[str, ...], ...],
    evaluations: tuple[RouteEvaluation, ...],
    riders: list[Rider],
    jobs_by_id: dict[str, V2Job],
    total_jobs: int,
    matrix: TravelMatrix,
    operation_context: OperationContext,
) -> PlanMetrics:
    burdens = [evaluation.burden.score for evaluation in evaluations]
    assigned = sum(len(route) for route in routes)
    now = operation_context.operation_start
    wait_minutes: list[float] = []
    for rider in riders:
        anchor = rider.last_completion_at or rider.available_from or now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=now.tzinfo)
        else:
            anchor = anchor.astimezone(now.tzinfo)
        wait_minutes.append(max(0.0, (now - anchor).total_seconds() / 60.0))
    return PlanMetrics(
        unassigned_jobs=total_jobs - assigned,
        hard_violations=sum(not evaluation.feasibility.feasible for evaluation in evaluations),
        extreme_assignments=sum(evaluation.burden.operationally_extreme_assignments for evaluation in evaluations),
        cross_zone_assignments=sum(evaluation.burden.long_distance_cross_zone_assignments for evaluation in evaluations),
        area_lead_violations=_area_lead_violation_count(
            routes, evaluations, riders, jobs_by_id, matrix, operation_context
        ),
        fragmented_clusters=_fragmented_lead_clusters(routes, riders, jobs_by_id),
        # Minimising the wait remaining on unassigned riders gives the next
        # available job to the rider who has been idle longest. Once every
        # rider has work, the existing burden objectives resume control.
        wait_time_penalty=sum(
            wait_minutes[index] for index, route in enumerate(routes) if not route
        ),
        maximum_rider_burden=max(burdens, default=0),
        burden_spread=max(burdens, default=0) - min(burdens, default=0),
        disliked_assignments=sum(evaluation.burden.disliked_assignments for evaluation in evaluations),
        preferred_overage=sum(evaluation.burden.preferred_job_overage for evaluation in evaluations),
        empty_minutes=sum(evaluation.burden.empty_travel_minutes for evaluation in evaluations),
        total_duration=sum(evaluation.total_duty_min for evaluation in evaluations),
    )


def _ordered_jobs(jobs: list[V2Job], riders: list[Rider]) -> list[V2Job]:
    leads = set(_lead_by_zone(riders))
    demand: dict[str, int] = {}
    for job in jobs:
        demand[job.pickup_zone] = demand.get(job.pickup_zone, 0) + 1
    return sorted(
        jobs,
        key=lambda job: (
            0 if job.pickup_zone in leads else 1,
            -demand.get(job.pickup_zone, 0),
            job.original_order,
            job.job_id,
        ),
    )


def _preserve_area_lead_capacity(
    rider: Rider,
    route: tuple[str, ...],
    job: V2Job,
    remaining_jobs: list[V2Job],
) -> bool:
    if rider.work_style != WorkStyle.AREA_LEAD:
        return True
    home = normalize_operational_zone(rider.start_zone)
    if job.pickup_zone == home:
        return True
    remaining_capacity = rider.maximum_jobs - len(route)
    remaining_priority = sum(item.pickup_zone == home for item in remaining_jobs)
    return remaining_capacity > remaining_priority


def _dedupe_plans(plans: list[_Plan], beam_width: int) -> list[_Plan]:
    unique: dict[tuple[tuple[str, ...], ...], _Plan] = {}
    for plan in sorted(plans, key=lambda item: item.metrics.objective()):
        unique.setdefault(plan.routes, plan)
        if len(unique) >= beam_width:
            break
    return list(unique.values())


def _build_explanations(
    best: _Plan,
    riders: list[Rider],
    jobs_by_id: dict[str, V2Job],
    matrix: TravelMatrix,
) -> list[AssignmentExplanation]:
    explanations: list[AssignmentExplanation] = []
    for rider_index, route in enumerate(best.routes):
        rider = riders[rider_index]
        evaluation = best.evaluations[rider_index]
        for row in evaluation.rows:
            job_id = clean_text(row.get("V2 Job ID"))
            job = jobs_by_id[job_id]
            severity = AssignmentSeverity[clean_text(row.get("Assignment Severity"))]
            projected = int(row.get("Sequence", 0) or 0)
            lead_match = bool(row.get("Area Lead Match"))
            reasons = []
            if lead_match:
                reasons.append(f"{rider.name} is the {rider.start_zone} Area Lead.")
                reasons.append(f"The job remains in a coherent {rider.start_zone} route cluster.")
            elif severity == AssignmentSeverity.PREFERRED:
                reasons.append("This is a preferred local assignment for the rider's current route.")
            elif severity == AssignmentSeverity.ACCEPTABLE:
                reasons.append("This is a reasonable nearby assignment.")
            else:
                reasons.append("This softer preference was relaxed to protect complete job coverage.")
            reasons.append(f"Pickup is {float(row.get('Empty Duration Min', 0) or 0):.1f} minutes from the preceding location.")
            reasons.append(f"Job count after assignment: {projected} / {rider.maximum_jobs}.")
            reasons.append("No hard constraints are violated.")
            if row.get("End Progress Min") is not None:
                progress = float(row["End Progress Min"])
                reasons.append(
                    f"This job moves the rider {abs(progress):.1f} minutes "
                    f"{'closer to' if progress >= 0 else 'farther from'} the required destination."
                )
            alternatives = []
            for other in riders:
                if other.name == rider.name:
                    continue
                cost = matrix.empty_cost(other.start_location, job.pickup_address)
                alternatives.append(
                    {
                        "rider": other.name,
                        "empty_travel_minutes": _minutes(cost),
                        "reason_rejected": "The complete-plan lexicographic objective was worse.",
                    }
                )
            alternatives.sort(key=lambda item: item["empty_travel_minutes"])
            soft = []
            if severity >= AssignmentSeverity.DISLIKED:
                soft.append(severity.name.replace("_", " ").title())
            if projected > rider.preferred_jobs:
                soft.append("Preferred workload exceeded within Maximum Jobs")
            source = clean_text(row.get("Cost Source"))
            explanations.append(
                AssignmentExplanation(
                    rider.name,
                    job_id,
                    severity,
                    float(row.get("Empty Duration Min", 0) or 0),
                    float(row.get("Loaded Duration Min", 0) or 0),
                    projected,
                    rider.preferred_jobs,
                    rider.maximum_jobs,
                    lead_match,
                    float(row["End Progress Min"]) if row.get("End Progress Min") is not None else None,
                    evaluation.estimated_end_arrival,
                    tuple(reasons),
                    tuple(alternatives[:3]),
                    tuple(soft),
                    source,
                    "hit" if "cache" in source.casefold() else "miss",
                )
            )
    return explanations


def _compatible_outputs(best: _Plan, riders: list[Rider]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_rows = [dict(row) for evaluation in best.evaluations for row in evaluation.rows]
    raw = pd.DataFrame(raw_rows)
    compatibility = format_route_output(raw.reindex(columns=ROUTE_COLUMNS), riders)
    v2_columns = [column for column in raw.columns if column not in compatibility.columns]
    if not raw.empty:
        lookup = raw.set_index(["Rider", "Uploaded Row"])
        for column in v2_columns:
            compatibility[column] = [
                lookup.at[(row["Rider"], row["Uploaded Row"]), column]
                for _, row in compatibility.iterrows()
            ]
    compatibility.attrs["rider_max_jobs"] = {rider.name: rider.maximum_jobs for rider in riders}
    compatibility.attrs["v2_preferred_jobs"] = {rider.name: rider.preferred_jobs for rider in riders}
    compatibility.attrs["v2_work_styles"] = {rider.name: rider.work_style.value for rider in riders}
    base_summary = pd.DataFrame(
        [{"Rider": rider.name, "Total Jobs": len(best.routes[index]), "Final Location": best.evaluations[index].final_location} for index, rider in enumerate(riders)],
        columns=SUMMARY_COLUMNS,
    )
    summary = format_summary_output(base_summary, compatibility)
    return compatibility, summary


def run_optimiser_v2(
    jobs_df: pd.DataFrame,
    riders: list[Rider],
    *,
    operation_context: OperationContext | None = None,
    travel_matrix: TravelMatrix | None = None,
    use_onemap: bool = True,
    token: str | None = None,
    beam_width: int = DEFAULT_V2_BEAM_WIDTH,
    time_limit_seconds: float = DEFAULT_V2_TIME_LIMIT_SECONDS,
    empty_duration_multiplier: float = 1.5,
    empty_wait_buffer_min: float = 6.0,
    progress_callback: V2ProgressCallback | None = None,
    allow_partial_assignment: bool = False,
) -> V2OptimisationResult:
    """Solve for the best hard-feasible plan.

    By default every job must be placed or the whole run reports INFEASIBLE
    (unchanged behaviour for the main optimiser page). When
    ``allow_partial_assignment`` is True, a job that cannot be placed in any
    rider's route is skipped instead of aborting the search: the search
    continues to place the remaining jobs, and the skipped jobs come back on
    the result as ``unassigned_jobs``/``infeasible_reasons`` alongside a
    genuine ``route_df`` for everything that *could* be placed, with status
    ``"PARTIAL"``. This exists for flows (e.g. the hourly standby-driver
    review) that want to see "N of M placed" rather than nothing at all.
    """

    started = time.monotonic()
    context = operation_context or OperationContext()
    jobs = jobs_from_dataframe(jobs_df)
    capacity = capacity_summary(jobs, riders)
    _emit_progress(
        progress_callback,
        phase="Capacity check",
        event_type="v2_capacity",
        status=(
            f"Checking {capacity.job_count} jobs against "
            f"{capacity.maximum_capacity} maximum rider slots."
        ),
        progress=0.01,
        assigned_jobs=0,
        total_jobs=len(jobs),
        remaining_jobs=len(jobs),
        comparison_count=0,
        estimated_comparisons=0,
    )
    if not capacity.feasible_by_job_count and not allow_partial_assignment:
        reason = (
            f"{capacity.job_count} jobs must be completed. The current riders can perform at most "
            f"{capacity.maximum_capacity} jobs. Capacity shortfall: {capacity.shortfall} jobs."
        )
        result = V2OptimisationResult(
            pd.DataFrame(columns=ROUTE_COLUMNS),
            pd.DataFrame(columns=SUMMARY_COLUMNS),
            "INFEASIBLE",
            capacity,
            [],
            [job.raw for job in jobs],
            [reason],
            (len(jobs), 0),
            {},
            time.monotonic() - started,
        )
        _emit_progress(
            progress_callback,
            phase="Finished",
            event_type="v2_finished",
            status=reason,
            progress=1.0,
            assigned_jobs=0,
            total_jobs=len(jobs),
            remaining_jobs=len(jobs),
            comparison_count=0,
            estimated_comparisons=0,
            result_status=result.status,
        )
        return result
    if not jobs:
        return V2OptimisationResult(
            pd.DataFrame(columns=ROUTE_COLUMNS),
            pd.DataFrame(columns=SUMMARY_COLUMNS),
            "COMPLETE",
            capacity,
            [],
            [],
            [],
            (0,) * 13,
            {},
            time.monotonic() - started,
        )
    matrix = travel_matrix or build_v2_travel_matrix(
        jobs,
        riders,
        context,
        use_onemap=use_onemap,
        token=token,
        empty_duration_multiplier=empty_duration_multiplier,
        empty_wait_buffer_min=empty_wait_buffer_min,
        progress_callback=progress_callback,
    )
    jobs_by_id = {job.job_id: job for job in jobs}
    empty_routes = tuple(() for _ in riders)
    empty_evaluations = tuple(
        evaluate_v2_route(rider, (), jobs_by_id, matrix, context) for rider in riders
    )
    initial_metrics = _plan_metrics(
        empty_routes,
        empty_evaluations,
        riders,
        jobs_by_id,
        len(jobs),
        matrix,
        context,
    )
    beam = [_Plan(empty_routes, empty_evaluations, initial_metrics)]
    ordered_jobs = _ordered_jobs(jobs, riders)
    search_deadline = time.monotonic() + max(1.0, float(time_limit_seconds))
    failure_reasons: list[str] = []
    partial_unassigned: list[dict[str, Any]] = []
    partial_reasons: list[str] = []
    candidate_evaluations = 0
    estimated_evaluations = max(
        1,
        len(jobs) * max(1, len(riders)) * min(max(1, int(beam_width)), 60) * 2,
    )
    _emit_progress(
        progress_callback,
        phase="Plan search",
        event_type="v2_search",
        status=f"Searching complete assignments for {len(jobs)} jobs...",
        progress=0.45,
        assigned_jobs=0,
        total_jobs=len(jobs),
        remaining_jobs=len(jobs),
        comparison_count=0,
        estimated_comparisons=estimated_evaluations,
        retained_plans=1,
    )
    for job_position, job in enumerate(ordered_jobs):
        remaining_jobs = ordered_jobs[job_position:]
        job_reason_start = len(failure_reasons)
        next_plans: list[_Plan] = []
        for plan in beam:
            for rider_index, rider in enumerate(riders):
                route = plan.routes[rider_index]
                if len(route) >= rider.maximum_jobs:
                    continue
                if not _preserve_area_lead_capacity(rider, route, job, remaining_jobs):
                    continue
                for insert_at in range(len(route) + 1):
                    candidate_evaluations += 1
                    candidate_route = route[:insert_at] + (job.job_id,) + route[insert_at:]
                    evaluation = evaluate_v2_route(rider, candidate_route, jobs_by_id, matrix, context)
                    if not evaluation.feasibility.feasible:
                        failure_reasons.extend(evaluation.feasibility.reasons)
                        continue
                    routes = list(plan.routes)
                    evaluations = list(plan.evaluations)
                    routes[rider_index] = candidate_route
                    evaluations[rider_index] = evaluation
                    route_tuple = tuple(routes)
                    evaluation_tuple = tuple(evaluations)
                    metrics = _plan_metrics(
                        route_tuple,
                        evaluation_tuple,
                        riders,
                        jobs_by_id,
                        len(jobs),
                        matrix,
                        context,
                    )
                    next_plans.append(_Plan(route_tuple, evaluation_tuple, metrics))
        if not next_plans:
            if allow_partial_assignment:
                # Skip this job and keep searching for the rest; it comes back
                # as an explicit unassigned entry on the final result instead
                # of aborting the whole plan. Reasons are scoped to just this
                # job's failed candidates, not the whole search's history.
                job_reasons = list(dict.fromkeys(failure_reasons[job_reason_start:]))[:10] or [
                    f"No hard-feasible route could accept {job.job_id}."
                ]
                partial_unassigned.append(job.raw)
                partial_reasons.extend(job_reasons)
                _emit_progress(
                    progress_callback,
                    phase="Plan search",
                    event_type="v2_search",
                    status=f"No hard-feasible route could accept {job.job_id}; leaving it unassigned.",
                    progress=0.45 + (0.50 * (job_position + 1) / max(1, len(jobs))),
                    assigned_jobs=job_position - len(partial_unassigned) + 1,
                    total_jobs=len(jobs),
                    remaining_jobs=len(jobs) - job_position - 1,
                    comparison_count=candidate_evaluations,
                    estimated_comparisons=estimated_evaluations,
                    retained_plans=len(beam),
                )
                continue
            assigned_ids = {job_id for plan in beam for route in plan.routes for job_id in route}
            unassigned = [item.raw for item in jobs if item.job_id not in assigned_ids]
            reasons = list(dict.fromkeys(failure_reasons))[:10] or [
                f"No hard-feasible route could accept {job.job_id}."
            ]
            result = V2OptimisationResult(
                pd.DataFrame(columns=ROUTE_COLUMNS),
                pd.DataFrame(columns=SUMMARY_COLUMNS),
                "INFEASIBLE",
                capacity,
                [],
                unassigned,
                reasons,
                beam[0].metrics.objective(),
                matrix.metrics(),
                time.monotonic() - started,
            )
            _emit_progress(
                progress_callback,
                phase="Finished",
                event_type="v2_finished",
                status=f"No complete hard-feasible plan could place {job.job_id}.",
                progress=1.0,
                assigned_jobs=job_position,
                total_jobs=len(jobs),
                remaining_jobs=len(jobs) - job_position,
                comparison_count=candidate_evaluations,
                estimated_comparisons=estimated_evaluations,
                result_status=result.status,
            )
            return result
        effective_width = min(max(1, int(beam_width)), 60 if len(jobs) > 20 else int(beam_width))
        beam = _dedupe_plans(next_plans, effective_width)
        _emit_progress(
            progress_callback,
            phase="Plan search",
            event_type="v2_search",
            status=(
                f"Placed {job_position + 1} of {len(jobs)} jobs; "
                f"retained {len(beam)} best complete-plan candidates."
            ),
            progress=0.45 + (0.50 * (job_position + 1) / max(1, len(jobs))),
            assigned_jobs=job_position + 1,
            total_jobs=len(jobs),
            remaining_jobs=len(jobs) - job_position - 1,
            comparison_count=candidate_evaluations,
            estimated_comparisons=max(estimated_evaluations, candidate_evaluations),
            retained_plans=len(beam),
            current_car_plate=job.car_plate,
            current_pickup=job.pickup_address,
            current_dropoff=job.dropoff_address,
        )
        if time.monotonic() >= search_deadline:
            # Continue deterministically with the best retained plan. Coverage remains mandatory.
            beam = beam[:1]
    best = min(beam, key=lambda plan: plan.metrics.objective())
    route_df, summary_df = _compatible_outputs(best, riders)
    explanations = _build_explanations(best, riders, jobs_by_id, matrix)
    has_soft_exceptions = bool(
        best.metrics.extreme_assignments
        or best.metrics.cross_zone_assignments
        or best.metrics.disliked_assignments
        or best.metrics.preferred_overage
        or best.metrics.area_lead_violations
    )
    if partial_unassigned:
        status = "PARTIAL"
    elif has_soft_exceptions:
        status = "COMPLETE_WITH_EXCEPTIONS"
    else:
        status = "COMPLETE"
    assigned_job_count = len(jobs) - len(partial_unassigned)
    route_df.attrs.update(
        sanitize_for_output(
            {
            "v2_status": status,
            "v2_objective": list(best.metrics.objective()),
            "v2_explanations": explanations,
            "v2_cache_metrics": matrix.metrics(),
            "v2_capacity": capacity,
            "algorithm_name": V2_ALGORITHM_NAME,
            "algorithm_version": V2_ALGORITHM_VERSION,
            "hard_constraint_validation": {
                "is_valid": True,
                "hard_violation_count": 0,
                "assigned_job_count": assigned_job_count,
                "unique_job_count": len(jobs),
                "violations": [],
            },
            "operation_context": context.to_settings(),
            }
        )
    )
    result = V2OptimisationResult(
        route_df,
        summary_df,
        status,
        capacity,
        explanations,
        list(partial_unassigned),
        list(dict.fromkeys(partial_reasons))[:10],
        best.metrics.objective(),
        matrix.metrics(),
        time.monotonic() - started,
    )
    finished_status = (
        f"{status}: assigned {assigned_job_count} of {len(jobs)} jobs, "
        f"{len(partial_unassigned)} left unassigned."
        if partial_unassigned
        else f"{status}: assigned all {len(jobs)} jobs."
    )
    _emit_progress(
        progress_callback,
        phase="Finished",
        event_type="v2_finished",
        status=finished_status,
        progress=1.0,
        assigned_jobs=assigned_job_count,
        total_jobs=len(jobs),
        remaining_jobs=len(partial_unassigned),
        comparison_count=candidate_evaluations,
        estimated_comparisons=max(estimated_evaluations, candidate_evaluations),
        retained_plans=len(beam),
        result_status=status,
    )
    return result
