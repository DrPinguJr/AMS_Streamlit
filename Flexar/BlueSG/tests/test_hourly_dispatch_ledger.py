from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from Flexar.BlueSG.hourly_dispatch_ledger import (
    HourlyLedgerState,
    clear_hourly_ledger,
    load_hourly_ledger,
    save_hourly_ledger,
)

ZONE = ZoneInfo("Asia/Singapore")


def _state(dispatch_at: datetime) -> HourlyLedgerState:
    return HourlyLedgerState(
        committed_jobs=pd.DataFrame([{"Job ID": "J1", "Car Plate": "SPE1001A"}]),
        committed_riders=pd.DataFrame([{"Rider Name": "Rider A", "Active": True}]),
        open_routes=pd.DataFrame([{"Rider": "Rider A", "Sequence": 1}]),
        archived_routes=pd.DataFrame(columns=["Rider", "Sequence"]),
        dispatch_at=dispatch_at,
    )


def test_save_then_load_round_trips_same_day_state(tmp_path) -> None:
    path = tmp_path / "ledger.xlsx"
    today = date(2026, 8, 11)
    dispatch_at = datetime(2026, 8, 11, 14, tzinfo=ZONE)
    save_hourly_ledger(_state(dispatch_at), today, path)

    loaded = load_hourly_ledger(today, path)

    assert loaded is not None
    assert loaded.committed_jobs["Job ID"].tolist() == ["J1"]
    assert loaded.committed_riders["Rider Name"].tolist() == ["Rider A"]
    assert loaded.open_routes["Rider"].tolist() == ["Rider A"]
    assert loaded.dispatch_at is not None
    assert loaded.dispatch_at.replace(tzinfo=None) == dispatch_at.replace(tzinfo=None)


def test_load_returns_none_for_a_previous_days_ledger(tmp_path) -> None:
    path = tmp_path / "ledger.xlsx"
    dispatch_at = datetime(2026, 8, 10, 14, tzinfo=ZONE)
    save_hourly_ledger(_state(dispatch_at), date(2026, 8, 10), path)

    assert load_hourly_ledger(date(2026, 8, 11), path) is None


def test_load_returns_none_when_no_file_exists(tmp_path) -> None:
    assert load_hourly_ledger(date(2026, 8, 11), tmp_path / "missing.xlsx") is None


def test_clear_hourly_ledger_removes_the_file(tmp_path) -> None:
    path = tmp_path / "ledger.xlsx"
    today = date(2026, 8, 11)
    save_hourly_ledger(_state(datetime(2026, 8, 11, 14, tzinfo=ZONE)), today, path)
    assert path.exists()

    clear_hourly_ledger(path)

    assert not path.exists()
    assert load_hourly_ledger(today, path) is None
