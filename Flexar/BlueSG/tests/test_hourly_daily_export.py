from __future__ import annotations

from datetime import date

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import ROUTE_COLUMNS
from Flexar.BlueSG.hourly_daily_export import (
    daily_export_path,
    export_daily_dispatch_excel,
    list_daily_exports,
)


def _route_df() -> pd.DataFrame:
    row = {column: "" for column in ROUTE_COLUMNS}
    row.update(
        {
            "Rider": "Rider A",
            "Sequence": 1,
            "Start From": "Tampines",
            "Car Plate": "SPE1001A",
            "Pickup Address": "Tampines",
            "Drop-off Address": "Bedok",
            "Total Duration Min": 20,
            "Total Distance KM": 5,
        }
    )
    return pd.DataFrame([row])


def test_export_daily_dispatch_excel_writes_a_dated_file(tmp_path) -> None:
    business_day = date(2026, 8, 18)

    path = export_daily_dispatch_excel(
        _route_df(), pd.DataFrame(), business_day, directory=tmp_path
    )

    assert path == tmp_path / "dispatch_2026-08-18.xlsx"
    assert path.exists()
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    assert "Optimised Routes" in sheets


def test_export_daily_dispatch_excel_handles_an_empty_day(tmp_path) -> None:
    path = export_daily_dispatch_excel(
        pd.DataFrame(), pd.DataFrame(), date(2026, 8, 18), directory=tmp_path
    )

    assert path.exists()


def test_daily_export_path_is_stable_for_a_given_business_day(tmp_path) -> None:
    business_day = date(2026, 8, 18)
    assert daily_export_path(business_day, tmp_path) == tmp_path / "dispatch_2026-08-18.xlsx"


def test_list_daily_exports_is_most_recent_first(tmp_path) -> None:
    export_daily_dispatch_excel(_route_df(), pd.DataFrame(), date(2026, 8, 17), directory=tmp_path)
    export_daily_dispatch_excel(_route_df(), pd.DataFrame(), date(2026, 8, 19), directory=tmp_path)
    export_daily_dispatch_excel(_route_df(), pd.DataFrame(), date(2026, 8, 18), directory=tmp_path)

    names = [path.name for path in list_daily_exports(tmp_path)]

    assert names == [
        "dispatch_2026-08-19.xlsx",
        "dispatch_2026-08-18.xlsx",
        "dispatch_2026-08-17.xlsx",
    ]


def test_list_daily_exports_returns_empty_for_a_missing_directory(tmp_path) -> None:
    assert list_daily_exports(tmp_path / "does_not_exist") == []
