from pathlib import Path

import pandas as pd

from Flexar.BlueSG import vehicle_route_optimizer as optimizer
from Flexar.BlueSG.vehicle_route_optimizer import RiderState, TravelCost


APP = Path(__file__).parents[1] / "Flexar" / "BlueSG" / "Vehicle_Route_Optimiser.py"


def test_progress_terminal_keeps_explanatory_scrollable_history() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "Live progress in plain English." in source
    assert '"\\n\\n".join(reversed(terminal_entries))' in source
    assert "terminal_output.code(" in source
    assert "del terminal_entries[:-40]" in source
    assert "height=560" in source
    assert '"Writing new location into memory"' in source
    assert '"Looking for the best driver"' in source
    assert "geocode_completed % 10 == 0" in source
    assert "comparison_count % 100 == 0" in source
    assert 'f"Why this driver: {simple_reason}"' in source
    assert 'detail_parts.append(("Why this driver", simple_reason))' in source
    assert 'if not hasattr(_route_optimizer_backend, "cache_unique_geocodes")' in source
    assert 'batch_geocoder = getattr(_route_optimizer_backend, "cache_unique_geocodes", None)' in source


def test_assignment_progress_events_include_car_and_final_rider(monkeypatch) -> None:
    jobs = pd.DataFrame(
        [
            {
                "Uploaded Row": 2,
                "_original_order": 0,
                "Car Plate": "SBA1234A",
                "Pickup Address": "Tampines",
                "Pickup Lot": "A1",
                "Drop-off Address": "Bedok",
                "Pickup Zone": "East",
                "Drop-off Zone": "East",
            }
        ]
    )
    monkeypatch.setattr(
        optimizer,
        "get_empty_travel_cost",
        lambda *args, **kwargs: TravelCost(1, 5, "test"),
    )
    monkeypatch.setattr(
        optimizer,
        "get_travel_cost",
        lambda *args, **kwargs: TravelCost(2, 8, "test"),
    )
    events = []

    optimizer.optimise_vehicle_routes(
        jobs,
        [RiderState("Rider One", "Tampines", "East")],
        use_onemap=False,
        progress_callback=events.append,
    )

    assignment = next(event for event in events if event.get("event_type") == "assignment")
    final = next(event for event in events if event.get("event_type") == "final_assignment")
    assert assignment["current_car_plate"] == "SBA1234A"
    assert assignment["assigned_jobs"] == 1
    assert assignment["assignment_reason"]
    assert assignment["current_region"] == "east_core"
    assert final["current_car_plate"] == "SBA1234A"
    assert final["current_rider"] == "Rider One"
