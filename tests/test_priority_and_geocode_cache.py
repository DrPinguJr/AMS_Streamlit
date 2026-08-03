from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

import pandas as pd
from streamlit.runtime import scriptrunner

from Flexar.BlueSG import build_optimised_vehicle_routes as optimizer
from Flexar.BlueSG.build_optimised_vehicle_routes import GeocodeResult, RiderState, TravelCost


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


def test_full_pasted_roster_load_aliases_are_accepted_and_normalised() -> None:
    pasted_roster = """\
Chen Yen Zong (El-Tian)\tWhampoa\tCentral\t4\tPiority
Raihan\tCommon Wealth\tCentral\t2\tNormal
Zhi Ming\tTampaines\tEast\t3\tPiority
Matthias Laurence\tTampaines\tEast\t2\tNormal
Chean Zheng Tao Clifford\tTampaines\tEast\t1\tLow
Safuwan\tWoodlands\tNorth\t4\tPiority
Ooi Kin Soon\tWoodlands\tNorth\t2\tNormal
Syed Muhammad Faiq Bin Bagal\tMarsiling \tNorth\t2\tNormal
Sufi\tYishun\tNorth\t2\tNormal
Chong Zhen Yang (Michael)\tCompassvale\tNorth-East\t2\tNormal
Asiah\tSkengkang\tNorth-East\t2\tNormal
Arin Joshua Daniel\tAng Mo Kio\tNorth-East\t2\tNormal
Gary Koh Foo Choy \tSkengkang\tNorth-East\t3\tPiority
Raymond\tYew Tee\tNorth-West\t2\tNormal
Lim Choon Yong Lester\tJurong\tWest\t5\tPiority"""
    rider_df = pd.DataFrame(
        [line.split("\t") for line in pasted_roster.splitlines()],
        columns=optimizer.RIDER_COLUMNS,
    )

    riders, errors = optimizer.validate_riders(rider_df)

    assert errors == []
    assert [rider.load_level for rider in riders] == [
        "Priority",
        "Medium",
        "Priority",
        "Medium",
        "Low",
        "Priority",
        "Medium",
        "Medium",
        "Medium",
        "Medium",
        "Medium",
        "Medium",
        "Priority",
        "Medium",
        "Priority",
    ]
    assert {"Normal", "Piority"} <= set(optimizer.RIDER_LOAD_INPUT_OPTIONS)
    assert all(
        optimizer.normalise_rider_load_level(value) in optimizer.RIDER_LOAD_LEVELS
        for value in optimizer.RIDER_LOAD_INPUT_OPTIONS
    )
    assert optimizer.normalise_rider_load_level(" PIORITY ") == "Priority"

    app_source = (
        optimizer.BASE_DIR / "pages" / "create_optimised_vehicle_routes_page.py"
    ).read_text(encoding="utf-8")
    assert "options=RIDER_LOAD_INPUT_OPTIONS" in app_source


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


def test_streamlit_context_probe_is_silent_in_geocode_workers(monkeypatch) -> None:
    suppress_warning_values: list[bool] = []
    state_lock = Lock()

    def fake_get_script_run_ctx(suppress_warning: bool = False):
        with state_lock:
            suppress_warning_values.append(suppress_warning)
        return None

    monkeypatch.setattr(
        scriptrunner,
        "get_script_run_ctx",
        fake_get_script_run_ctx,
    )

    with ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="bluesg-geocode",
    ) as pool:
        context_available = list(
            pool.map(lambda _: optimizer._streamlit_context_available(), range(4))
        )

    assert context_available == [False, False, False, False]
    assert suppress_warning_values == [True, True, True, True]


def test_north_west_is_available_as_a_rider_zone() -> None:
    app_source = (
        optimizer.BASE_DIR / "pages" / "create_optimised_vehicle_routes_page.py"
    ).read_text(encoding="utf-8")

    assert '"North-West"' in app_source
    rider = RiderState("NW", "Bukit Panjang", "North-West", load_level="Priority")
    job = {
        "Pickup Address": "Bukit Panjang Plaza",
        "Pickup Zone": "West",
        "Operational Subregion": "north_west",
    }
    assert optimizer._priority_rider_matches_job(rider, job)
