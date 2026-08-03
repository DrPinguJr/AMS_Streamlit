from __future__ import annotations

import pandas as pd

from Flexar.BlueSG import build_optimised_vehicle_routes as optimiser
from Flexar.BlueSG.build_optimised_vehicle_routes import RiderState, TravelCost
from Flexar.BlueSG.regional_capacity_and_cross_region_assignment_rules import (
    MAX_ADJACENT_ZONE_TRAVEL_MINUTES,
    SIDE_BY_SIDE_MAX_MINUTES,
    ZONE_ADJACENCY,
    assess_geographic_assignment,
)


def _job(index: int, plate: str, pickup: str, pickup_zone: str) -> dict:
    return {
        "_original_order": index,
        "Car Plate": plate,
        "Pickup Address": pickup,
        "Pickup Lot": f"P{index}",
        "Drop-off Address": pickup,
        "Drop-off Zone": pickup_zone,
        "Pickup Zone": pickup_zone,
    }


def _patch_travel(monkeypatch, durations: dict[tuple[str, str], float] | None = None) -> None:
    durations = durations or {}

    def empty_cost(origin, destination, *_args, **_kwargs):
        duration = durations.get((str(origin), str(destination)), 10.0)
        return TravelCost(1.0, duration, "test verified")

    monkeypatch.setattr(optimiser, "get_empty_travel_cost", empty_cost)
    monkeypatch.setattr(
        optimiser,
        "get_travel_cost",
        lambda *_args, **_kwargs: TravelCost(2.0, 5.0, "test verified"),
    )


def _optimise(jobs: list[dict], riders: list[RiderState]):
    return optimiser.optimise_vehicle_routes(
        pd.DataFrame(jobs),
        riders,
        use_onemap=False,
        empty_travel_duration_multiplier=1.0,
        empty_travel_wait_buffer_min=0.0,
        regional_overflow_config={"enabled": False},
    )[0]


def test_east_rider_cannot_take_north_west_job(monkeypatch) -> None:
    _patch_travel(monkeypatch)
    route = _optimise(
        [_job(0, "NW100", "Bukit Panjang", "North-West")],
        [
            RiderState("East rider", "Tampines", "East", max_jobs=5),
            RiderState("North-West rider", "Choa Chu Kang", "North-West", max_jobs=5),
        ],
    )
    assert route.iloc[0]["Rider"] == "North-West rider"


def test_punggol_rider_cannot_take_choa_chu_kang_job(monkeypatch) -> None:
    _patch_travel(monkeypatch)
    route = _optimise(
        [_job(0, "NW101", "Choa Chu Kang", "North-West")],
        [
            RiderState("Punggol rider", "Punggol", "North-East", max_jobs=5),
            RiderState("CCK rider", "Bukit Panjang", "North-West", max_jobs=5),
        ],
    )
    assert route.iloc[0]["Rider"] == "CCK rider"


def test_north_west_rider_is_preferred_for_north_west_job(monkeypatch) -> None:
    _patch_travel(
        monkeypatch,
        {
            ("Yishun", "Bukit Panjang"): 4.0,
            ("Choa Chu Kang", "Bukit Panjang"): 12.0,
        },
    )
    route = _optimise(
        [_job(0, "NW102", "Bukit Panjang", "North-West")],
        [
            RiderState("Nearby North rider", "Yishun", "North", max_jobs=5),
            RiderState("Home-zone rider", "Choa Chu Kang", "North-West", max_jobs=5),
        ],
    )
    assert route.iloc[0]["Rider"] == "Home-zone rider"
    assert route.iloc[0]["Geographic Assignment Rank"] == 0


def test_adjacent_zone_allowed_when_travel_time_is_short(monkeypatch) -> None:
    _patch_travel(monkeypatch, {("Yishun", "Bukit Panjang"): 10.0})
    route = _optimise(
        [_job(0, "NW103", "Bukit Panjang", "North-West")],
        [RiderState("North rider", "Yishun", "North", max_jobs=5)],
    )
    assert route.iloc[0]["Rider"] == "North rider"
    assert route.iloc[0]["Geographic Assignment Status"] == "side_by_side"
    assert route.iloc[0]["Geographic Assignment Rank"] == 1


def test_adjacent_zone_rejected_when_travel_time_is_too_long() -> None:
    assessment = assess_geographic_assignment(
        "North",
        "North",
        "North-West",
        MAX_ADJACENT_ZONE_TRAVEL_MINUTES + 1,
    )
    assert not assessment.is_normal
    assert assessment.status == "adjacent_too_far"
    assert assessment.rank == 3


def test_final_re_evaluation_moves_job_to_closer_rider(monkeypatch) -> None:
    _patch_travel(
        monkeypatch,
        {
            ("Tampines", "Bukit Panjang"): 3.0,
            ("Choa Chu Kang", "Bukit Panjang"): 12.0,
        },
    )
    route = _optimise(
        [_job(0, "NW104", "Bukit Panjang", "North-West")],
        [
            RiderState("Distant but quick East rider", "Tampines", "East", max_jobs=5),
            RiderState("Closer-zone rider", "Choa Chu Kang", "North-West", max_jobs=5),
        ],
    )
    assert route.iloc[0]["Rider"] == "Closer-zone rider"
    assert route.iloc[0]["Geographic Assignment Rank"] == 0
    assert "geographic_re_evaluation_moves" in route.attrs


def test_cross_zone_assignment_allowed_only_when_no_local_feasible_rider(monkeypatch) -> None:
    _patch_travel(monkeypatch, {("Tampines", "Bukit Panjang"): 8.0})
    route = _optimise(
        [_job(0, "NW105", "Bukit Panjang", "North-West")],
        [RiderState("Only rider", "Tampines", "East", max_jobs=5)],
    )
    row = route.iloc[0]
    assert row["Rider"] == "Only rider"
    assert row["Geographic Assignment Status"] == "exceptional_no_local_feasible"
    assert "No same-zone or short adjacent-zone rider" in row["Geographic Exception Reason"]
    assert route.attrs["geographic_validation"]["warning_count"] >= 1


def test_route_does_not_alternate_between_distant_zones(monkeypatch) -> None:
    _patch_travel(monkeypatch)
    route = _optimise(
        [
            _job(0, "E100", "Tampines", "East"),
            _job(1, "NW106", "Bukit Panjang", "North-West"),
            _job(2, "E101", "Bedok", "East"),
        ],
        [
            RiderState("East rider", "Tampines", "East", max_jobs=5),
            RiderState("North-West rider", "Choa Chu Kang", "North-West", max_jobs=5),
        ],
    )
    for _, rider_route in route.groupby("Rider"):
        zones = rider_route.sort_values("Sequence")["Pickup Operational Zone"].tolist()
        assert not any(
            zones[index - 2] == zones[index] != zones[index - 1]
            for index in range(2, len(zones))
        )
    assert not any(
        "alternates between operational zones" in issue["reason"]
        for issue in route.attrs["geographic_validation"]["issues"]
    )


def test_zone_policy_constants_are_centralised() -> None:
    assert "north_west" not in ZONE_ADJACENCY["east"]
    assert "north_west" in ZONE_ADJACENCY["north"]
    assert SIDE_BY_SIDE_MAX_MINUTES < MAX_ADJACENT_ZONE_TRAVEL_MINUTES
