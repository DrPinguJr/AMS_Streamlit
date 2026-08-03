"""Google-Sheet-first daily roster loading with a local workbook fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import WEEKDAY_SHEETS
from Flexar.BlueSG.vehicle_route_optimiser_v2 import normalise_v2_roster


DEFAULT_LOCAL_ROSTER = (
    Path(__file__).resolve().parent
    / "data"
    / "weekday_rider_availability_and_capacity_roster.xlsx"
)
GOOGLE_ROSTER_URL_ENV = "BLUESG_ROSTER_GOOGLE_SHEET_CSV_URL"


@dataclass(frozen=True)
class DailyRosterLoad:
    dataframe: pd.DataFrame
    source: str
    warning: str = ""


def _google_csv_url(day: str, configured_url: str) -> str:
    if "{day}" in configured_url:
        return configured_url.format(day=quote(day))
    return configured_url


def load_daily_v2_roster(
    day: str,
    *,
    google_csv_url: str | None = None,
    local_path: Path = DEFAULT_LOCAL_ROSTER,
) -> DailyRosterLoad:
    if day not in WEEKDAY_SHEETS:
        raise ValueError(f"Unknown roster day: {day}")
    configured = str(google_csv_url or os.getenv(GOOGLE_ROSTER_URL_ENV, "")).strip()
    google_error = ""
    if configured:
        try:
            # Let pandas preserve numeric sheet cells as numbers. Forcing every
            # CSV field to object/string would make valid Maximum values look
            # like prohibited free-form text to the strict validator.
            dataframe = pd.read_csv(_google_csv_url(day, configured))
            if "Day" in dataframe.columns:
                dataframe = dataframe[
                    dataframe["Day"].astype(str).str.casefold() == day.casefold()
                ]
            for numeric_column in ("Preferred", "Maximum"):
                if numeric_column in dataframe:
                    parsed = pd.to_numeric(dataframe[numeric_column], errors="coerce")
                    dataframe[numeric_column] = dataframe[numeric_column].where(
                        parsed.isna(), parsed
                    )
            return DailyRosterLoad(normalise_v2_roster(dataframe), "Google Sheets")
        except Exception as exc:
            google_error = f"Google Sheets roster could not be loaded: {exc}"

    if not local_path.exists():
        empty = normalise_v2_roster(pd.DataFrame())
        return DailyRosterLoad(
            empty,
            "Local fallback",
            google_error or "No Google Sheets URL or local roster is configured.",
        )
    dataframe = pd.read_excel(local_path, sheet_name=day)
    warning = google_error
    if not configured:
        warning = (
            "Google Sheets roster is not configured; using the local weekday workbook. "
            f"Set {GOOGLE_ROSTER_URL_ENV} to a published CSV export URL."
        )
    return DailyRosterLoad(normalise_v2_roster(dataframe), "Local fallback", warning)


def save_local_v2_roster(
    day: str,
    rider_df: pd.DataFrame,
    *,
    local_path: Path = DEFAULT_LOCAL_ROSTER,
) -> Path:
    """Persist only the fallback workbook; Google Sheets remains source-owned."""

    if day not in WEEKDAY_SHEETS:
        raise ValueError(f"Unknown roster day: {day}")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    sheets: dict[str, pd.DataFrame] = {}
    if local_path.exists():
        workbook = pd.ExcelFile(local_path)
        for sheet_name in WEEKDAY_SHEETS:
            if sheet_name in workbook.sheet_names:
                sheets[sheet_name] = normalise_v2_roster(
                    pd.read_excel(local_path, sheet_name=sheet_name)
                )
    sheets[day] = normalise_v2_roster(rider_df)
    with pd.ExcelWriter(local_path, engine="openpyxl") as writer:
        for sheet_name in WEEKDAY_SHEETS:
            sheets.get(sheet_name, normalise_v2_roster(pd.DataFrame())).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
            )
    return local_path
