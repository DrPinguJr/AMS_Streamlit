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


def load_hourly_ledger(today: date, path: Path = DEFAULT_LEDGER_PATH) -> HourlyLedgerState | None:
    """Return the saved ledger only if it was last written on `today`.

    Returns None for a missing file, an unreadable/corrupt file, or a ledger
    left over from a previous day - all three mean "start with an empty
    canvas," matching the state-refresh rule the operator expects.
    """

    if not path.exists():
        return None
    try:
        sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    except Exception:
        return None
    meta = sheets.get("Meta")
    if meta is None or meta.empty:
        return None
    last_date = str(meta.iloc[0].get("Last_Accessed_Date", ""))
    if last_date != today.isoformat():
        return None
    dispatch_at_raw = str(meta.iloc[0].get("Dispatch_At", "") or "")
    parsed_dispatch_at = pd.to_datetime(dispatch_at_raw, errors="coerce")
    return HourlyLedgerState(
        committed_jobs=sheets.get("Committed_Jobs", pd.DataFrame()),
        committed_riders=sheets.get("Committed_Riders", pd.DataFrame()),
        open_routes=sheets.get("Open_Routes", pd.DataFrame()),
        archived_routes=sheets.get("Archived_Routes", pd.DataFrame()),
        dispatch_at=None if pd.isna(parsed_dispatch_at) else parsed_dispatch_at.to_pydatetime(),
    )


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
