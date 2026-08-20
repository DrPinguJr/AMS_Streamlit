"""Local Excel ledger so the hourly dispatch page can resume same-day state
after a Streamlit rerun or a mid-shift container restart.

Cloud caveat: Streamlit Community Cloud's filesystem is wiped on redeploy and
on a full container restart (not just a rerun) - this is why the Cloud
entrypoint already warns "Cloud storage is temporary. Download completed
workbooks..." (see `cloud_streamlit_router.py`). This ledger is therefore a
same-day, best-effort convenience for surviving reruns/brief restarts within
one running container, not durable storage across a redeploy. It exists
because the spec explicitly asked for a local-Excel design; a Google-Sheet
backed ledger (mirroring `v2_daily_roster_source.py`'s Sheet-first, local
fallback pattern) would be the way to get real cross-restart durability if
that becomes necessary.

Kept free of Streamlit imports so it is unit-testable with a temp path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent / "data" / "hourly_dispatch_ledger.xlsx"

_ROUTE_SHEETS = ("Committed_Jobs", "Committed_Riders", "Open_Routes", "Archived_Routes")


@dataclass(frozen=True)
class HourlyLedgerState:
    committed_jobs: pd.DataFrame
    committed_riders: pd.DataFrame
    open_routes: pd.DataFrame
    archived_routes: pd.DataFrame
    dispatch_at: datetime | None
    business_day: date | None = None


def _read_ledger_sheets(path: Path) -> dict[str, pd.DataFrame] | None:
    if not path.exists():
        return None
    try:
        return pd.read_excel(path, sheet_name=None, engine="openpyxl")
    except Exception:
        return None


def _state_from_sheets(sheets: dict[str, pd.DataFrame]) -> tuple[HourlyLedgerState, str] | None:
    """Parse a ledger workbook's sheets into a state plus its raw
    `Last_Accessed_Date` string, or None if the Meta sheet is unusable.
    Shared by both the gated and staleness-ignoring readers below."""

    meta = sheets.get("Meta")
    if meta is None or meta.empty:
        return None
    last_date = str(meta.iloc[0].get("Last_Accessed_Date", ""))
    dispatch_at_raw = str(meta.iloc[0].get("Dispatch_At", "") or "")
    parsed_dispatch_at = pd.to_datetime(dispatch_at_raw, errors="coerce")
    business_day_raw = str(meta.iloc[0].get("Business_Day", "") or "")
    parsed_business_day = pd.to_datetime(business_day_raw, errors="coerce")
    state = HourlyLedgerState(
        committed_jobs=sheets.get("Committed_Jobs", pd.DataFrame()),
        committed_riders=sheets.get("Committed_Riders", pd.DataFrame()),
        open_routes=sheets.get("Open_Routes", pd.DataFrame()),
        archived_routes=sheets.get("Archived_Routes", pd.DataFrame()),
        dispatch_at=None if pd.isna(parsed_dispatch_at) else parsed_dispatch_at.to_pydatetime(),
        business_day=None if pd.isna(parsed_business_day) else parsed_business_day.date(),
    )
    return state, last_date


def load_hourly_ledger(today: date, path: Path = DEFAULT_LEDGER_PATH) -> HourlyLedgerState | None:
    """Return the saved ledger only if it was last written on `today`.

    Returns None for a missing file, an unreadable/corrupt file, or a ledger
    left over from a previous day - all three mean "start with an empty
    canvas," matching the state-refresh rule the operator expects.
    """

    sheets = _read_ledger_sheets(path)
    if sheets is None:
        return None
    parsed = _state_from_sheets(sheets)
    if parsed is None:
        return None
    state, last_date = parsed
    if last_date != today.isoformat():
        return None
    return state


def load_hourly_ledger_ignoring_staleness(path: Path = DEFAULT_LEDGER_PATH) -> HourlyLedgerState | None:
    """Read whatever the ledger file holds, regardless of `Last_Accessed_Date`.

    `load_hourly_ledger` deliberately hides a previous day's file so the page
    starts clean each day - but that means it also hides the exact data the
    11am business-day rollover needs in order to export it first. This is
    for that rollover path only: it needs yesterday's (or an even older)
    saved state even though the normal same-day resume gate would reject it.
    """

    sheets = _read_ledger_sheets(path)
    if sheets is None:
        return None
    parsed = _state_from_sheets(sheets)
    return parsed[0] if parsed is not None else None


def save_hourly_ledger(
    state: HourlyLedgerState,
    today: date,
    path: Path = DEFAULT_LEDGER_PATH,
) -> None:
    """Persist the day's rolling state, overwriting any previous snapshot.

    Route/job/roster frames are expected to already be Excel-safe (the same
    contract `export_routes_to_excel` relies on) - datetimes belong in string
    form, not tz-aware `Timestamp` columns, which `openpyxl` cannot write.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    meta = pd.DataFrame(
        [
            {
                "Last_Accessed_Date": today.isoformat(),
                "Dispatch_At": state.dispatch_at.isoformat() if state.dispatch_at else "",
                "Business_Day": state.business_day.isoformat() if state.business_day else "",
            }
        ]
    )
    frames = {
        "Committed_Jobs": state.committed_jobs,
        "Committed_Riders": state.committed_riders,
        "Open_Routes": state.open_routes,
        "Archived_Routes": state.archived_routes,
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name in _ROUTE_SHEETS:
            frame = frames[sheet_name]
            frame = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
        meta.to_excel(writer, sheet_name="Meta", index=False)


def clear_hourly_ledger(path: Path = DEFAULT_LEDGER_PATH) -> None:
    """Remove the ledger file, e.g. when the operator deliberately starts fresh."""

    if path.exists():
        path.unlink()
