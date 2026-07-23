from __future__ import annotations

from threading import Lock
import time

import pandas as pd

from Flexar.BlueSG import vehicle_route_optimizer as optimizer
from Flexar.BlueSG.vehicle_route_optimizer import GeocodeResult, RiderState, TravelCost


def _east_jobs(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Uploaded Row": index + 2,
                "_original_order": index,
                "Car Plate": f"EAST{index}",
                "Pickup Address": f"Tampines {index}",
                "Pickup Lot": "A",
                "Drop-off Address": f"Bedok {index}",
                "Pickup Zone": "East",
                "Drop-off Zone": "East",
            }
            for index in range(count)
        ]
    )


def _patch_short_travel(monkeypatch) -> None:
    def cost(origin, destination, *_args, **_kwargs):
        return TravelCost(
            1,
            5,
            "test verified",
            origin=str(origin),
            destination=str(destination),
            confidence="verified",
        )

    monkeypatch.setattr(optimizer, "get_empty_travel_cost", cost)
    monkeypatch.setattr(optimizer, "get_travel_cost", cost)


def test_one_priority_rider_receives_all_matching_area_jobs(monkeypatch) -> None:
    _patch_short_travel(monkeypatch)
    riders = [
        RiderState("Priority East", "Tampines", "East", load_level="Priority"),
        RiderState("Normal East 1", "Tampines", "East"),
        RiderState("Normal East 2", "Bedok", "East"),
    ]

    routes, _, _ = optimizer.optimise_vehicle_routes(
        _east_jobs(3), riders, use_onemap=False, regional_overflow_config={"enabled": False}
    )

    assert routes.groupby("Rider").size().to_dict() == {"Priority East": 3}


def test_two_priority_riders_evenly_split_matching_area_jobs(monkeypatch) -> None:
    _patch_short_travel(monkeypatch)
    riders = [
        RiderState("Priority East 1", "Tampines", "East", load_level="Priority"),
        RiderState("Priority East 2", "Bedok", "East", load_level="Priority"),
        RiderState("Normal East", "Tampines", "East"),
    ]

    routes, _, _ = optimizer.optimise_vehicle_routes(
        _east_jobs(4), riders, use_onemap=False, regional_overflow_config={"enabled": False}
    )

    assert routes.groupby("Rider").size().to_dict() == {
        "Priority East 1": 2,
        "Priority East 2": 2,
    }


def test_geocode_batch_deduplicates_places_and_runs_distinct_places_in_parallel(monkeypatch) -> None:
    state_lock = Lock()
    active = 0
    peak_active = 0
    calls: list[str] = []

    def fake_lookup(address, token=None, use_onemap=True):
        nonlocal active, peak_active
        with state_lock:
            calls.append(address)
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.02)
        with state_lock:
            active -= 1
        return GeocodeResult(address, 1.3, 103.8, "OneMap")

    monkeypatch.setattr(optimizer, "get_cached_geocode", fake_lookup)
    addresses = [
        "313@somerset, L6 [Regular Lots]",
        "313@somerset, L7 [Lot 107-108]",
        "Tampines Mall",
        "Yishun MRT",
    ]

    results = optimizer.cache_unique_geocodes(addresses, max_workers=4)

    assert len(calls) == 3
    assert len(results) == 4
    assert peak_active > 1
    assert sum("313@somerset" in address for address in calls) == 1


def test_north_west_is_available_as_a_rider_zone() -> None:
    app_source = (
        optimizer.BASE_DIR / "Vehicle_Route_Optimiser.py"
    ).read_text(encoding="utf-8")

    assert '"North-West"' in app_source
    rider = RiderState("NW", "Bukit Panjang", "North-West", load_level="Priority")
    job = {
        "Pickup Address": "Bukit Panjang Plaza",
        "Pickup Zone": "West",
        "Operational Subregion": "north_west",
    }
    assert optimizer._priority_rider_matches_job(rider, job)
