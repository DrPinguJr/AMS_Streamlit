from __future__ import annotations

from datetime import date, time

import pandas as pd
import pytest

from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.vehicle_route_optimizer import RiderState


@pytest.fixture
def overnight_context() -> OperationContext:
    return OperationContext.for_window(date(2026, 7, 17), time(23, 0), time(3, 0))


@pytest.fixture
def regression_jobs() -> pd.DataFrame:
    rows = []
    specifications = [
        ("A1", "Tampines", "Bedok", "East", "East"),
        ("A2", "Bedok", "Jurong", "East", "West"),
        ("A3", "Jurong", "Clementi", "West", "West"),
        ("A4", "Hougang", "Bishan", "North-East", "Central"),
    ]
    for index, (plate, pickup, dropoff, pickup_zone, dropoff_zone) in enumerate(specifications):
        rows.append(
            {
                "_uploaded_row": index + 2,
                "_original_order": index,
                "Car Plate": plate,
                "Pickup Address": pickup,
                "Pickup Lot": f"L{index + 1}",
                "Drop-off Address": dropoff,
                "Pickup Zone": pickup_zone,
                "Drop-off Zone": dropoff_zone,
                "Date": pd.Timestamp("2026-07-17"),
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def regression_riders() -> list[RiderState]:
    return [
        RiderState("East Rider", "Tampines", "East", max_jobs=1),
        RiderState("West Rider", "Jurong", "West", max_jobs=1),
    ]

