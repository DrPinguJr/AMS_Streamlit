from pathlib import Path

import pandas as pd

from Flexar.BlueSG import vehicle_route_optimizer as optimizer
from Flexar.BlueSG.vehicle_route_optimizer import RiderState, TravelCost


APP = Path(__file__).parents[1] / "Flexar" / "BlueSG" / "Vehicle_Route_Optimiser.py"


def test_progress_terminal_keeps_explanatory_scrollable_history() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "ASSIGN explains each routing decision. Latest 60 events." in source
    assert "del terminal_lines[:-60]" in source
    assert "height:520px; overflow-y:auto" in source
    assert 'detail_parts.append(("Why routed", event["assignment_reason"]))' in source


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
