import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "Sesami" / "Excel Sheets"
OUTPUT_NAME = "SesamiBusinessOpportunities"

SESAMI_FIELDS = [
    "action_status_text",
    "s_no",
    "calling_entity",
    "ref_no",
    "document_type",
    "products_services_category",
    "description",
    "submission",
    "starting_date",
    "closing_date",
]


@dataclass
class RawSesamiRow:
    action_status_text: str = ""
    s_no: str = ""
    calling_entity: str = ""
    ref_no: str = ""
    document_type: str = ""
    products_services_category: str = ""
    description: str = ""
    submission: str = ""
    starting_date: str = ""
    closing_date: str = ""


@dataclass
class SesamiRow:
    action_status_text: str = ""
    s_no: str = ""
    calling_entity: str = ""
    ref_no: str = ""
    document_type: str = ""
    products_services_category: str = ""
    description: str = ""
    submission: str = ""
    starting_date: str = ""
    closing_date: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "action_status_text": self.action_status_text,
            "s_no": self.s_no,
            "calling_entity": self.calling_entity,
            "ref_no": self.ref_no,
            "document_type": self.document_type,
            "products_services_category": self.products_services_category,
            "description": self.description,
            "submission": self.submission,
            "starting_date": self.starting_date,
            "closing_date": self.closing_date,
        }


def clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" :-\t\r\n")


def output_excel_path(name: str = OUTPUT_NAME) -> Path:
    timestamp = datetime.now().strftime("%d%H%M")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or OUTPUT_NAME
    return OUTPUT_DIR / f"{timestamp}_{safe_name}.xlsx"


def sesami_identity(row: RawSesamiRow | SesamiRow | dict[str, str]) -> str:
    if isinstance(row, dict):
        ref_no = clean_value(row.get("ref_no", "")).lower()
        calling_entity = clean_value(row.get("calling_entity", "")).lower()
        closing_date = clean_value(row.get("closing_date", "")).lower()
    else:
        ref_no = clean_value(row.ref_no).lower()
        calling_entity = clean_value(row.calling_entity).lower()
        closing_date = clean_value(row.closing_date).lower()

    return f"{ref_no}|{calling_entity}|{closing_date}"


def normalize_sesami_rows(raw_rows: list[RawSesamiRow]) -> list[SesamiRow]:
    normalized_rows: list[SesamiRow] = []
    seen_keys: set[str] = set()

    for raw in raw_rows:
        row = SesamiRow(
            action_status_text=clean_value(raw.action_status_text),
            s_no=clean_value(raw.s_no),
            calling_entity=clean_value(raw.calling_entity),
            ref_no=clean_value(raw.ref_no),
            document_type=clean_value(raw.document_type),
            products_services_category=clean_value(raw.products_services_category),
            description=clean_value(raw.description),
            submission=clean_value(raw.submission),
            starting_date=clean_value(raw.starting_date),
            closing_date=clean_value(raw.closing_date),
        )
        key = sesami_identity(row)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        normalized_rows.append(row)

    return normalized_rows


def save_sesami_results(rows: list[SesamiRow], output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = output_excel_path()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = pd.DataFrame([row.as_dict() for row in rows], columns=SESAMI_FIELDS)
    dataframe.to_excel(output_path, index=False)
    return output_path


def latest_sesami_excel(output_dir: Path = OUTPUT_DIR) -> Path | None:
    if not output_dir.exists():
        return None

    candidates = list(output_dir.glob("*_SesamiBusinessOpportunities.xlsx"))
    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_sesami_data(path: Path | None = None) -> pd.DataFrame:
    excel_path = path or latest_sesami_excel()
    if excel_path is None or not excel_path.exists():
        return pd.DataFrame(columns=SESAMI_FIELDS)

    dataframe = pd.read_excel(excel_path).fillna("")
    for field in SESAMI_FIELDS:
        if field not in dataframe.columns:
            dataframe[field] = ""

    dataframe = dataframe[SESAMI_FIELDS]
    for field in SESAMI_FIELDS:
        dataframe[field] = dataframe[field].map(clean_value)

    return dataframe
