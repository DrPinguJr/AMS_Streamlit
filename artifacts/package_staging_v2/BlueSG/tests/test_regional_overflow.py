from __future__ import annotations

from datetime import date, time
import json
import math

import pandas as pd

from Flexar.BlueSG.local_improvement import improve_assigned_routes
from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.output_sanitizer import sanitize_for_output
from Flexar.BlueSG.regional_overflow import (
    REGIONAL_SUPPORT_RULES,
    RegionalOverflowConfig,
    build_regional_overflow_context,
    classify_job_region,
    determine_east_affinity,
    support_candidate_is_reasonable,
)
from Flexar.BlueSG.vehicle_route_optimizer import RiderState, TravelCost, optimise_vehicle_routes


def _job(index: int, subregion: str) -> dict:
    primary = REGIONAL_SUPPORT_RULES[subregion]["primary_regions"][0]
    return {
        "_original_order": index,
        "Car Plate": f"CAR{index:02d}",
        "Pickup Address": f"{subregion.upper()}_P{index}",
        "Pickup Lot": str(index),
        "Drop-off Address": f"{subregion.upper()}_D{index}",
        "Pickup Zone": primary.replace("_", " ").title(),
        "Drop-off Zone": primary.replace("_", " ").title(),
        "Operational Subregion": subregion,
    }


def _riders() -> list[RiderState]:
    return [
        RiderState("West 1", "WEST_HOME", "West", max_jobs=5, load_level="Very High"),
        RiderState("North 1", "NORTH_HOME", "North", max_jobs=4),
        RiderState("North 2", "NORTH_HOME_2", "North", max_jobs=4),
        RiderState("Central 1", "CENTRAL_HOME", "Central", max_jobs=4),
        RiderState("Central 2", "CENTRAL_HOME_2", "Central", max_jobs=4),
        RiderState("East 1", "EAST_CENTRAL_HOME", "East", max_jobs=4),
        RiderState("East 2", "EAST_NE_HOME", "East", max_jobs=4),
        RiderState("NE 1", "NE_HOME", "North-East", max_jobs=4),
        RiderState("North Core 1", "NORTH_CORE_HOME", "North", max_jobs=4),
    ]


def _area(value: str) -> str:
    text = str(value).upper()
    if "WEST_CORE" in text or text.startswith("WEST_HOME"):
        return "west"
    if "NORTH_WEST" in text:
        return "north_west"
    if "SOUTH_WEST" in text:
        return "south_west"
    if "CENTRAL_EAST" in text:
        return "central_east"
    if "EAST_NORTH_EAST" in text:
        return "east_ne"
    if "NORTH_EAST_CORE" in text or text.startswith("NE_HOME"):
        return "north_east"
    if "NORTH_CORE" in text or text.startswith("NORTH_HOME"):
        return "north"
    if "EAST_CORE" in text or text.startswith("EAST_"):
        return "east"
    if "CENTRAL_CORE" in text or text.startswith("CENTRAL_HOME") or "DHOBY" in text:
        return "central"
    if "SERANGOON" in text:
        return "north_east"
    return "unknown"


def _duration(origin: str, destination: str) -> float:
    left, right = _area(origin), _area(destination)
    if left == right:
        return 2.0
    preferred = {
        ("north", "north_west"): 3.0,
        ("central", "south_west"): 3.0,
        ("east", "central_east"): 4.0,
        ("east", "east_ne"): 4.0,
        ("north_east", "east_ne"): 3.0,
        ("west", "north_west"): 30.0,
        ("west", "south_west"): 30.0,
    }
    if (left, right) in preferred:
        return preferred[(left, right)]
    if right == "west":
        return 35.0 if left in {"north", "central"} else 60.0
    if left == "west" and right not in {"west", "north_west", "south_west"}:
        return 90.0
    return 18.0


def _patch_travel(monkeypatch) -> None:
    def empty(origin, destination, *_args, **_kwargs):
        duration = _duration(origin, destination)
        return TravelCost(duration / 4, duration, "fake verified", origin=origin, destination=destination, confidence="verified")

    def loaded(origin, destination, *_args, **_kwargs):
        return TravelCost(1.0, 2.0, "fake verified", origin=origin, destination=destination, confidence="verified")

    monkeypatch.setattr("Flexar.BlueSG.vehicle_route_optimizer.get_empty_travel_cost", empty)
    monkeypatch.setattr("Flexar.BlueSG.vehicle_route_optimizer.get_travel_cost", loaded)


def _thirty_jobs() -> pd.DataFrame:
    subregions = (
        ["west_core"] * 5
        + ["north_west"] * 5
        + ["south_west"] * 5
        + ["central_core"] * 3
        + ["central_east"] * 3
        + ["east_core"] * 3
        + ["east_north_east"] * 3
        + ["north_east_core"] * 3
    )
    return pd.DataFrame([_job(index, subregion) for index, subregion in enumerate(subregions)])


def _run_scenario(monkeypatch):
    _patch_travel(monkeypatch)
    context = OperationContext.for_window(date(2026, 7, 17), time(14), time(17))
    route, summary, warnings = optimise_vehicle_routes(
        _thirty_jobs(),
        _riders(),
        use_onemap=False,
        operation_context=context,
        max_adjusted_duration_min=180,
    )
    return route, summary, warnings


def test_west_scarcity_protects_west_rider_for_deep_west_jobs(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    west = route[route["Rider"] == "West 1"]
    assert not west.empty
    assert west["Operational Subregion"].eq("west_core").all()


def test_north_riders_support_north_west_overflow(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    rows = route[route["Operational Subregion"] == "north_west"]
    assert ((rows["Assigned Rider Home Region"] == "north") & (rows["Assignment Tier"] == "support")).any()


def test_central_riders_support_south_west_overflow(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    rows = route[route["Operational Subregion"] == "south_west"]
    assert ((rows["Assigned Rider Home Region"] == "central") & (rows["Assignment Tier"] == "support")).any()


def test_east_rider_affinity_supports_nearest_boundary() -> None:
    costs = {("east", "central"): 8, ("east", "ne"): 20}
    assert determine_east_affinity("east", lambda a, b: costs[(a, "central" if "Dhoby" in b else "ne")], "Dhoby", "Serangoon") == "central_east"


def test_east_rider_is_not_normal_west_support() -> None:
    assert "east" not in REGIONAL_SUPPORT_RULES["west_core"]["support_regions"]
    assert "east" not in REGIONAL_SUPPORT_RULES["north_west"]["support_regions"]
    assert "east" not in REGIONAL_SUPPORT_RULES["south_west"]["support_regions"]


def test_support_rule_does_not_override_actual_current_location() -> None:
    assert support_candidate_is_reasonable(12, 10, tolerance_min=15, tolerance_ratio=1.25)
    assert not support_candidate_is_reasonable(40, 10, tolerance_min=15, tolerance_ratio=1.25)


def test_unsupported_candidate_used_only_as_exception(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    west_by_east = route[
        route["Operational Subregion"].isin(["west_core", "north_west", "south_west"])
        & route["Assigned Rider Home Region"].eq("east")
    ]
    assert west_by_east.empty or west_by_east["Assignment Tier"].eq("exceptional").all()


def test_regional_protection_recalculates_after_assignment() -> None:
    jobs = [_job(0, "west_core"), _job(1, "west_core")]
    riders = [RiderState("W", "WEST_HOME", "West", max_jobs=1), RiderState("N", "NORTH_HOME", "North", max_jobs=3)]
    context = build_regional_overflow_context(jobs, riders, operation_window_min=180)
    context.update_round(jobs, {2: {"W": 2, "N": 40}, 3: {"W": 3, "N": 20}})
    assert context.protected_job_ids_by_region["west"] == {2}
    riders[0].assigned_count = 1
    context.update_round(jobs[1:], {3: {"W": 3, "N": 20}})
    assert not context.protected_job_ids_by_region["west"]


def test_rescue_insertion_respects_scarce_driver_protection(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    assert not ((route["Rider"] == "West 1") & (route["Operational Subregion"] != "west_core")).any()


def test_local_improvement_does_not_create_bad_cross_island_route() -> None:
    context = OperationContext.for_window(date(2026, 7, 17), time(14), time(17))
    sequences = {
        "West": [{"_original_order": 0, "Uploaded Row": 2}],
        "East": [{"_original_order": 1, "Uploaded Row": 3}],
    }

    def evaluator(candidate):
        bad = int(any(job["_original_order"] == 0 for job in candidate["East"]))
        return {
            "objective_tuple": (0, 0, 10 - bad),
            "jobs_assigned": 2,
            "unassigned_job_count": 0,
            "hard_constraint_violation_count": 0,
            "fallback_leg_count": 0,
            "regional_exception_count": bad,
            "protected_job_misassignment_count": bad,
            "validation": {"is_valid": True},
            "rider_metrics": {},
        }

    _, audit = improve_assigned_routes(
        sequences,
        [],
        context,
        {"_candidate_evaluator": evaluator},
        [],
        time_limit_seconds=2,
        max_iterations=1,
    )
    assert not any(move["accepted"] and move["protected_job_misassignment_count_after"] for move in audit)


def test_regional_overflow_never_reduces_job_coverage(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    assert len(route) == 30
    assert route["Uploaded Row"].nunique() == 30


def test_regional_diagnostics_are_finite_and_serialisable(monkeypatch) -> None:
    route, _, _ = _run_scenario(monkeypatch)
    payload = sanitize_for_output({
        "capacity": route.attrs["regional_capacity"],
        "audit": route[["Regional Specificity Score", "Regional Support Penalty", "Unsupported Region Penalty"]].to_dict("records"),
    })
    encoded = json.dumps(payload, allow_nan=False)
    assert encoded
    assert all(math.isfinite(float(value)) for value in route["Regional Specificity Score"])


def test_classification_prefers_explicit_and_coordinates_over_address() -> None:
    assert classify_job_region({"Operational Subregion": "north-west", "Pickup Address": "Tuas"})[1] == "north_west"
    assert classify_job_region({"Pickup Latitude": 1.40, "Pickup Longitude": 103.76, "Pickup Address": "Tuas"})[1] == "north_west"


def test_regional_fixture_beats_unprotected_baseline(monkeypatch) -> None:
    _patch_travel(monkeypatch)
    context = OperationContext.for_window(date(2026, 7, 17), time(14), time(17))
    jobs = _thirty_jobs()
    baseline, baseline_summary, _ = optimise_vehicle_routes(
        jobs, _riders(), use_onemap=False, operation_context=context,
        regional_overflow_config={"enabled": False},
    )
    regional, regional_summary, _ = optimise_vehicle_routes(
        jobs, _riders(), use_onemap=False, operation_context=context,
        regional_overflow_config={"enabled": True},
    )
    baseline_max = float(baseline_summary["Total Duty Time Min"].max())
    regional_max = float(regional_summary["Total Duty Time Min"].max())
    baseline_empty = float(baseline["Empty Duration Min"].sum())
    regional_empty = float(regional["Empty Duration Min"].sum())
    assert len(regional) == len(baseline) == 30
    assert regional_max <= baseline_max
    assert regional_empty <= baseline_empty
    assert int(regional.attrs["regional_exception_count"]) <= 1
