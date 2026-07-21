"""Capacity-aware regional overflow policy for the state-aware route solver.

This module deliberately contains policy and diagnostics, not a second solver.
The caller supplies the route-aware incremental costs from the production
greedy/insertion evaluator on every assignment round.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import math
import re
from typing import Any, Callable, Literal


OperationalSubregion = Literal[
    "west_core",
    "north_west",
    "south_west",
    "central_core",
    "central_east",
    "east_core",
    "east_north_east",
    "north_east_core",
    "north_core",
    "unknown",
]


REGIONAL_SUPPORT_RULES: dict[str, dict[str, list[str]]] = {
    "west_core": {"primary_regions": ["west"], "support_regions": []},
    "north_west": {"primary_regions": ["west"], "support_regions": ["north"]},
    "south_west": {"primary_regions": ["west"], "support_regions": ["central"]},
    "central_core": {"primary_regions": ["central"], "support_regions": []},
    "central_east": {"primary_regions": ["central"], "support_regions": ["east"]},
    "east_core": {"primary_regions": ["east"], "support_regions": []},
    "east_north_east": {"primary_regions": ["north_east"], "support_regions": ["east"]},
    "north_east_core": {"primary_regions": ["north_east"], "support_regions": []},
    "north_core": {"primary_regions": ["north"], "support_regions": []},
    "unknown": {"primary_regions": [], "support_regions": []},
}


@dataclass(frozen=True)
class RegionalOverflowConfig:
    enabled: bool = True
    support_tolerance_min: float = 15.0
    support_tolerance_ratio: float = 1.25
    protected_job_advantage_min: float = 15.0
    approved_support_penalty: float = 5.0
    unsupported_region_penalty: float = 180.0
    clustered_trip_penalty: float = 0.0
    clustered_trip_min_jobs: int = 3
    scarce_driver_small_escape_penalty: float = 40.0
    scarce_driver_large_escape_penalty: float = 180.0
    estimated_job_duration_min: float = 45.0
    central_reference: str = "Dhoby Ghaut MRT, Singapore"
    northeast_reference: str = "Serangoon MRT, Singapore"

    @classmethod
    def from_value(cls, value: "RegionalOverflowConfig | dict[str, Any] | None") -> "RegionalOverflowConfig":
        if isinstance(value, cls):
            return value
        if not value:
            return cls()
        known = {item.name for item in cls.__dataclass_fields__.values()}
        return cls(**{key: val for key, val in value.items() if key in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RegionalCapacitySummary:
    subregion: str
    job_demand: int
    primary_rider_count: int
    support_rider_count: int
    primary_soft_capacity: int
    support_soft_capacity: int
    demand_over_primary_capacity: int
    demand_over_total_supported_capacity: int
    primary_hard_capacity: int | None = None
    support_hard_capacity: int | None = None
    jobs_protected_for_primary_riders: int = 0
    jobs_assigned_to_primary_riders: int = 0
    jobs_assigned_to_support_riders: int = 0
    exceptional_unsupported_assignments: int = 0

    @property
    def overflow_required(self) -> int:
        return self.demand_over_primary_capacity

    def to_dict(self) -> dict[str, Any]:
        return {
            "Operational subregion": self.subregion,
            "Job demand": self.job_demand,
            "Primary riders": self.primary_rider_count,
            "Approved support riders": self.support_rider_count,
            "Primary soft capacity": self.primary_soft_capacity,
            "Supported soft capacity": self.primary_soft_capacity + self.support_soft_capacity,
            "Primary hard capacity": self.primary_hard_capacity,
            "Supported hard capacity": (
                None
                if self.primary_hard_capacity is None and self.support_hard_capacity is None
                else int(self.primary_hard_capacity or 0) + int(self.support_hard_capacity or 0)
            ),
            "Overflow required": self.overflow_required,
            "Demand over supported capacity": self.demand_over_total_supported_capacity,
            "Jobs protected for primary riders": self.jobs_protected_for_primary_riders,
            "Jobs assigned to primary riders": self.jobs_assigned_to_primary_riders,
            "Jobs assigned to support riders": self.jobs_assigned_to_support_riders,
            "Exceptional unsupported assignments": self.exceptional_unsupported_assignments,
        }


@dataclass(frozen=True)
class RegionalCandidateAssessment:
    tier: str
    specificity_score: float
    support_penalty: float
    scarce_driver_protection_penalty: float
    unsupported_region_penalty: float
    reason: str

    @property
    def total_penalty(self) -> float:
        return (
            self.support_penalty
            + self.scarce_driver_protection_penalty
            + self.unsupported_region_penalty
        )


def normalize_region(value: Any) -> str:
    text = re.sub(r"[^a-z]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "north_east": "north_east",
        "northeast": "north_east",
        "north_eastern": "north_east",
        "centre": "central",
        "center": "central",
        "central_region": "central",
        "west_region": "west",
        "east_region": "east",
        "north_region": "north",
    }
    if text in aliases:
        return aliases[text]
    for region in ("north_east", "central", "west", "east", "north"):
        if region in text:
            return region
    return "unknown"


_SUBREGION_ALIASES = {
    "west_core": "west_core",
    "deep_west": "west_core",
    "north_west": "north_west",
    "northwest": "north_west",
    "south_west": "south_west",
    "southwest": "south_west",
    "central_core": "central_core",
    "central_east": "central_east",
    "east_core": "east_core",
    "east_north_east": "east_north_east",
    "north_east_boundary": "east_north_east",
    "north_east_core": "north_east_core",
    "northeast_core": "north_east_core",
    "north_core": "north_core",
}


_ADDRESS_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("west_core", ("tuas", "pioneer", "boon lay", "jurong west", "jurong island", "gul circle", "joo koon", "teban", "toh guan")),
    ("north_west", ("choa chu kang", "bukit panjang", "hillview", "dairy farm", "cashew", "segar", "senja", "keat hong", "bukit batok")),
    ("south_west", ("clementi", "west coast", "dover", "buona vista", "queenstown", "pasir panjang", "telok blangah", "one north")),
    ("east_north_east", ("punggol", "sengkang", "buangkok", "hougang", "serangoon", "kovan")),
    ("north_east_core", ("seletar", "anchorvale", "rivervale", "fernvale")),
    ("central_east", ("geylang", "paya lebar", "macpherson", "kallang", "aljunied", "ubi", "eunos")),
    ("east_core", ("tampines", "pasir ris", "changi", "bedok", "simei", "tanah merah")),
    ("north_core", ("woodlands", "yishun", "sembawang", "admiralty", "marsiling", "mandai")),
    ("central_core", ("orchard", "novena", "newton", "bishan", "toa payoh", "dhoby", "city hall", "bugis", "marina")),
]


def _first_value(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None and str(value).strip() and str(value).lower() != "nan":
            return value
    return None


def classify_job_region(job: dict[str, Any]) -> tuple[str, str, str]:
    """Return broad region, operational subregion and confidence.

    Explicit subregion/coordinates/region data win over address text. Coordinates
    use conservative Singapore partitions and are only a fallback when an
    operational polygon result has not already been supplied.
    """

    explicit = _first_value(job, ("Operational Subregion", "operational_subregion", "Subregion"))
    if explicit:
        key = re.sub(r"[^a-z]+", "_", str(explicit).lower()).strip("_")
        subregion = _SUBREGION_ALIASES.get(key)
        if subregion:
            primary = REGIONAL_SUPPORT_RULES[subregion]["primary_regions"]
            return (primary[0] if primary else "unknown", subregion, "explicit")

    latitude = _first_value(job, ("Pickup Latitude", "pickup_latitude", "Latitude", "lat"))
    longitude = _first_value(job, ("Pickup Longitude", "pickup_longitude", "Longitude", "lng", "lon"))
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        lat = lon = math.nan
    if math.isfinite(lat) and math.isfinite(lon) and 1.15 <= lat <= 1.48 and 103.55 <= lon <= 104.10:
        if lon < 103.72:
            subregion = "west_core"
        elif lon < 103.79 and lat >= 1.35:
            subregion = "north_west"
        elif lon < 103.79:
            subregion = "south_west"
        elif lon > 103.91 and lat >= 1.36:
            subregion = "east_north_east"
        elif lon > 103.91:
            subregion = "east_core"
        elif lat >= 1.385:
            subregion = "north_core"
        elif lon >= 103.86:
            subregion = "central_east"
        else:
            subregion = "central_core"
        primary = REGIONAL_SUPPORT_RULES[subregion]["primary_regions"]
        return primary[0], subregion, "coordinates"

    region_value = _first_value(job, ("Job Region", "Pickup Region", "Region", "Pickup Zone", "Cluster Name / Zone"))
    region = normalize_region(region_value)
    address = str(_first_value(job, ("Pickup Address", "pickup_address", "Address")) or "").lower()
    for subregion, keywords in _ADDRESS_KEYWORDS:
        if any(keyword in address for keyword in keywords):
            primary = REGIONAL_SUPPORT_RULES[subregion]["primary_regions"]
            return primary[0], subregion, "address_fallback"

    default = {
        "west": "west_core",
        "central": "central_core",
        "east": "east_core",
        "north_east": "north_east_core",
        "north": "north_core",
    }.get(region, "unknown")
    return region, default, "existing_region" if region != "unknown" else "unknown"


def support_candidate_is_reasonable(
    support_cost_min: float,
    best_feasible_cost_min: float,
    *,
    tolerance_min: float,
    tolerance_ratio: float,
) -> bool:
    return bool(
        support_cost_min <= best_feasible_cost_min + tolerance_min
        or support_cost_min <= best_feasible_cost_min * tolerance_ratio
    )


def determine_east_affinity(
    rider_start_location: str,
    estimator: Callable[[str, str], float],
    central_reference: str,
    northeast_reference: str,
) -> str:
    central_min = float(estimator(rider_start_location, central_reference))
    northeast_min = float(estimator(rider_start_location, northeast_reference))
    return "central_east" if central_min <= northeast_min else "east_north_east"


def calculate_regional_specificity_score(best_primary_cost: float, best_support_cost: float) -> float:
    if not math.isfinite(best_primary_cost):
        return 0.0
    if not math.isfinite(best_support_cost):
        return 1_000_000.0
    return best_support_cost - best_primary_cost


@dataclass
class RegionalOverflowContext:
    support_rules: dict[str, dict[str, list[str]]]
    capacity_summary: dict[str, RegionalCapacitySummary]
    rider_affinities: dict[str, str]
    config: RegionalOverflowConfig
    job_metadata: dict[int, dict[str, str]]
    rider_home_regions: dict[str, str]
    protected_job_ids_by_region: dict[str, set[int]] = field(default_factory=dict)
    ever_protected_job_ids_by_region: dict[str, set[int]] = field(default_factory=dict)
    specificity_by_job_id: dict[int, float] = field(default_factory=dict)
    max_specificity_by_job_id: dict[int, float] = field(default_factory=dict)
    assignments: dict[int, dict[str, Any]] = field(default_factory=dict)

    def metadata(self, job: dict[str, Any]) -> dict[str, str]:
        return self.job_metadata[_job_identifier(job)]

    def is_scarce_primary_region(self, region: str) -> bool:
        region = normalize_region(region)
        relevant = [
            item for subregion, item in self.capacity_summary.items()
            if region in self.support_rules[subregion]["primary_regions"]
        ]
        # A rider may be primary for several subregions; count that regional
        # capacity once instead of duplicating it for every support-rule row.
        regional_riders = [
            rider for rider in getattr(self, "_riders", [])
            if self.rider_home_regions.get(str(getattr(rider, "name", ""))) == region
        ]
        regional_capacity = sum(
            int(getattr(rider, "max_jobs", None) or max(1, item.primary_soft_capacity // max(1, item.primary_rider_count)))
            for rider in regional_riders
            for item in relevant[:1]
        )
        if not regional_riders:
            regional_capacity = max((item.primary_soft_capacity for item in relevant), default=0)
        return bool(relevant and sum(item.job_demand for item in relevant) > regional_capacity)

    def update_round(
        self,
        remaining_jobs: list[dict[str, Any]],
        candidate_costs: dict[int, dict[str, float]],
    ) -> None:
        """Recalculate specificity and protected jobs from current route states."""

        self.protected_job_ids_by_region = {}
        self.specificity_by_job_id = {}
        for job in remaining_jobs:
            job_id = _job_identifier(job)
            meta = self.metadata(job)
            rules = self.support_rules[meta["operational_subregion"]]
            costs = candidate_costs.get(job_id, {})
            primary_costs = [cost for rider, cost in costs.items() if self.rider_home_regions.get(rider) in rules["primary_regions"]]
            support_costs = [cost for rider, cost in costs.items() if self.rider_home_regions.get(rider) in rules["support_regions"]]
            best_primary = min(primary_costs, default=math.inf)
            best_support = min(support_costs, default=math.inf)
            specificity = calculate_regional_specificity_score(best_primary, best_support)
            self.specificity_by_job_id[job_id] = specificity
            self.max_specificity_by_job_id[job_id] = max(
                specificity,
                self.max_specificity_by_job_id.get(job_id, -math.inf),
            )

        for region in sorted(set(self.rider_home_regions.values())):
            if not self.is_scarce_primary_region(region):
                continue
            eligible = [
                job for job in remaining_jobs
                if region in self.support_rules[self.metadata(job)["operational_subregion"]]["primary_regions"]
                and self.specificity_by_job_id.get(_job_identifier(job), 0.0) >= self.config.protected_job_advantage_min
            ]
            remaining_capacity = sum(
                max(
                    0,
                    int(getattr(rider, "max_jobs", None) or getattr(self, "_default_capacity", 0))
                    - int(getattr(rider, "assigned_count", 0) or 0),
                )
                for rider in getattr(self, "_riders", [])
                if self.rider_home_regions.get(str(getattr(rider, "name", ""))) == region
            )
            eligible.sort(key=lambda job: (-self.specificity_by_job_id[_job_identifier(job)], _job_identifier(job)))
            self.protected_job_ids_by_region[region] = {_job_identifier(job) for job in eligible[:remaining_capacity]}
            self.ever_protected_job_ids_by_region.setdefault(region, set()).update(
                self.protected_job_ids_by_region[region]
            )

        for summary in self.capacity_summary.values():
            primary_regions = self.support_rules[summary.subregion]["primary_regions"]
            protected = set().union(*(self.ever_protected_job_ids_by_region.get(region, set()) for region in primary_regions))
            summary.jobs_protected_for_primary_riders = sum(
                1 for job_id in protected
                if self.job_metadata.get(job_id, {}).get("operational_subregion") == summary.subregion
            )

    def assess_candidate(
        self,
        job: dict[str, Any],
        rider_name: str,
        rider_current_region: str,
        candidate_cost: float,
        best_feasible_cost: float,
        best_primary_or_support_cost: float,
        *,
        remaining_cluster_jobs: int = 1,
        rider_has_assignments: bool = True,
        continues_cluster: bool = False,
    ) -> RegionalCandidateAssessment:
        job_id = _job_identifier(job)
        meta = self.metadata(job)
        rules = self.support_rules[meta["operational_subregion"]]
        home = self.rider_home_regions.get(rider_name, "unknown")
        specificity = self.specificity_by_job_id.get(job_id, 0.0)
        support_penalty = scarce_penalty = unsupported_penalty = 0.0

        if home in rules["primary_regions"]:
            tier = "primary"
        elif home in rules["support_regions"] and support_candidate_is_reasonable(
            candidate_cost,
            best_feasible_cost,
            tolerance_min=self.config.support_tolerance_min,
            tolerance_ratio=self.config.support_tolerance_ratio,
        ):
            tier = "support"
            support_penalty = self.config.approved_support_penalty
        else:
            tier = "exceptional"
            materially_closer = math.isfinite(best_primary_or_support_cost) and (
                candidate_cost + self.config.protected_job_advantage_min < best_primary_or_support_cost
            )
            starts_clustered_trip = (
                not rider_has_assignments
                and remaining_cluster_jobs >= max(1, int(self.config.clustered_trip_min_jobs))
                and not math.isfinite(best_primary_or_support_cost)
            )
            clustered_trip = starts_clustered_trip or continues_cluster
            unsupported_penalty = (
                0.0
                if materially_closer
                else self.config.clustered_trip_penalty
                if clustered_trip
                else self.config.unsupported_region_penalty
            )

        protected = self.protected_job_ids_by_region.get(home, set())
        if protected and job_id not in protected:
            home_supports_job = home in rules["support_regions"]
            scarce_penalty = (
                self.config.scarce_driver_small_escape_penalty
                if home_supports_job
                else self.config.scarce_driver_large_escape_penalty
            )

        if tier == "primary":
            reason = f"Primary {home} rider for {meta['operational_subregion']} demand."
        elif tier == "support":
            reason = (
                f"Approved {home} support for {meta['operational_subregion']} overflow; "
                f"route-aware cost {candidate_cost:.1f} min was within support tolerance."
            )
        else:
            reason = (
                f"Exceptional unsupported {home} assignment retained for coverage/current-route efficiency; "
                f"route-aware cost {candidate_cost:.1f} min."
            )
            if clustered_trip and not unsupported_penalty:
                reason += " Cross-region penalty was zero because this is a clustered trip."
        if scarce_penalty:
            reason += f" Scarce {home} capacity was protected while higher-specificity regional work remained."
        return RegionalCandidateAssessment(
            tier=tier,
            specificity_score=specificity,
            support_penalty=support_penalty,
            scarce_driver_protection_penalty=scarce_penalty,
            unsupported_region_penalty=unsupported_penalty,
            reason=reason,
        )

    def record_assignment(self, job: dict[str, Any], rider_name: str, audit: dict[str, Any]) -> None:
        job_id = _job_identifier(job)
        self.assignments[job_id] = dict(audit)
        subregion = self.metadata(job)["operational_subregion"]
        summary = self.capacity_summary[subregion]
        tier = audit.get("Assignment Tier")
        if tier == "primary":
            summary.jobs_assigned_to_primary_riders += 1
        elif tier == "support":
            summary.jobs_assigned_to_support_riders += 1
        else:
            summary.exceptional_unsupported_assignments += 1

    def capacity_rows(self) -> list[dict[str, Any]]:
        return [self.capacity_summary[name].to_dict() for name in self.support_rules if name in self.capacity_summary]


def _job_identifier(job: dict[str, Any]) -> int:
    for key in ("_job_id", "Uploaded Row"):
        try:
            return int(job[key])
        except (KeyError, TypeError, ValueError):
            continue
    try:
        return int(job["_original_order"]) + 2
    except (KeyError, TypeError, ValueError):
        pass
    return id(job)


def build_regional_overflow_context(
    jobs: list[dict[str, Any]],
    riders: list[Any],
    *,
    operation_window_min: float,
    config: RegionalOverflowConfig | dict[str, Any] | None = None,
    east_affinity_estimator: Callable[[str, str], float] | None = None,
) -> RegionalOverflowContext:
    cfg = RegionalOverflowConfig.from_value(config)
    job_metadata: dict[int, dict[str, str]] = {}
    demand = Counter()
    for job in jobs:
        region, subregion, confidence = classify_job_region(job)
        job_metadata[_job_identifier(job)] = {
            "region": region,
            "operational_subregion": subregion,
            "region_confidence": confidence,
        }
        demand[subregion] += 1

    rider_home_regions = {
        str(getattr(rider, "name", "")): normalize_region(
            getattr(rider, "start_zone", None) or getattr(rider, "start_location", "")
        )
        for rider in riders
    }
    default_capacity = max(1, int(max(0.0, operation_window_min) // max(1.0, cfg.estimated_job_duration_min)))

    capacity: dict[str, RegionalCapacitySummary] = {}
    for subregion, rules in REGIONAL_SUPPORT_RULES.items():
        primary = [rider for rider in riders if rider_home_regions.get(str(getattr(rider, "name", ""))) in rules["primary_regions"]]
        support = [rider for rider in riders if rider_home_regions.get(str(getattr(rider, "name", ""))) in rules["support_regions"]]

        def soft(items: list[Any]) -> int:
            return sum(int(getattr(item, "max_jobs", None) or default_capacity) for item in items)

        def hard(items: list[Any]) -> int | None:
            values = [getattr(item, "hard_max_jobs", None) for item in items]
            return sum(int(value) for value in values if value is not None) if any(value is not None for value in values) else None

        primary_soft, support_soft = soft(primary), soft(support)
        count = int(demand[subregion])
        capacity[subregion] = RegionalCapacitySummary(
            subregion=subregion,
            job_demand=count,
            primary_rider_count=len(primary),
            support_rider_count=len(support),
            primary_soft_capacity=primary_soft,
            support_soft_capacity=support_soft,
            demand_over_primary_capacity=max(0, count - primary_soft),
            demand_over_total_supported_capacity=max(0, count - primary_soft - support_soft),
            primary_hard_capacity=hard(primary),
            support_hard_capacity=hard(support),
        )

    affinities: dict[str, str] = {}
    if east_affinity_estimator:
        for rider in riders:
            name = str(getattr(rider, "name", ""))
            if rider_home_regions.get(name) == "east":
                affinities[name] = determine_east_affinity(
                    str(getattr(rider, "start_location", "")),
                    east_affinity_estimator,
                    cfg.central_reference,
                    cfg.northeast_reference,
                )

    context = RegionalOverflowContext(
        support_rules=REGIONAL_SUPPORT_RULES,
        capacity_summary=capacity,
        rider_affinities=affinities,
        config=cfg,
        job_metadata=job_metadata,
        rider_home_regions=rider_home_regions,
    )
    context._riders = riders  # Runtime state used to recalculate remaining regional capacity.
    context._default_capacity = default_capacity
    return context


def regional_audit_fields(
    context: RegionalOverflowContext,
    job: dict[str, Any],
    rider_name: str,
    current_region: str,
    assessment: RegionalCandidateAssessment,
) -> dict[str, Any]:
    meta = context.metadata(job)
    return {
        "Job Region": meta["region"],
        "Operational Subregion": meta["operational_subregion"],
        "Region Confidence": meta["region_confidence"],
        "Assigned Rider Home Region": context.rider_home_regions.get(rider_name, "unknown"),
        "Assigned Rider Current Region Before Job": normalize_region(current_region),
        "Assignment Tier": assessment.tier,
        "Regional Specificity Score": round(float(assessment.specificity_score), 3),
        "Regional Support Penalty": round(float(assessment.support_penalty), 3),
        "Scarce Driver Protection Penalty": round(float(assessment.scarce_driver_protection_penalty), 3),
        "Unsupported Region Penalty": round(float(assessment.unsupported_region_penalty), 3),
        "Reason for Regional Assignment": assessment.reason,
    }
