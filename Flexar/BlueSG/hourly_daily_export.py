"""Per-business-day Excel export for the hourly rolling dispatch ledger.

`hourly_dispatch_ledger.py` is deliberately same-day-only - it overwrites in
place so a rerun/restart can resume today's state, but keeps no history of
finished days. This module is the missing "hand a finished day to a manager"
piece: one dated workbook per business day (the 11am-boundary day the page's
rollover check computes via `hourly_route_dispatch.business_day_for`),
written once and never overwritten by a later day.

Kept free of Streamlit imports so it is unit-testable with a temp directory,
matching the rest of this package's pure-module convention.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import export_routes_to_excel

DEFAULT_DAILY_EXPORTS_DIR = Path(__file__).resolve().parent / "data" / "daily_exports"


def daily_export_path(business_day: date, directory: Path = DEFAULT_DAILY_EXPORTS_DIR) -> Path:
    return directory / f"dispatch_{business_day.isoformat()}.xlsx"


def export_daily_dispatch_excel(
    route_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    business_day: date,
    *,
    jobs_df: pd.DataFrame | None = None,
    directory: Path = DEFAULT_DAILY_EXPORTS_DIR,
) -> Path:
    """Write one business day's finished dispatch to its own dated workbook.

    `route_df`/`summary_df` are expected to be the day's combined
    archived+open routes (whatever the page has by rollover time) - this
    does not filter or interpret "finished" itself, it just archives
    whatever it is handed under that day's filename.
    """

    directory.mkdir(parents=True, exist_ok=True)
    path = daily_export_path(business_day, directory)
    workbook_bytes = export_routes_to_excel(route_df, summary_df, jobs_df=jobs_df)
    path.write_bytes(workbook_bytes)
    return path


def list_daily_exports(directory: Path = DEFAULT_DAILY_EXPORTS_DIR) -> list[Path]:
    """Most-recent-first list of every daily export written so far."""

    if not directory.exists():
        return []
    return sorted(directory.glob("dispatch_*.xlsx"), reverse=True)
