import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "Tender" / "Excel Sheets"
OUTPUT_NAME = "TenderBoard"
DATABASE_PATH = OUTPUT_DIR / "Database.xlsx"
PROCESSED_OUTPUT_NAME = "ProcessedTenderBoard"
REJECTED_OUTPUT_NAME = "RejectedTenderBoard"
MIN_DAYS_TO_CLOSE = 14

GROUP_KEYWORDS = [
    "Coaching",
    "Consult",
    "Consultancy",
    "Contract",
    "Facilities",
    "Fitness",
    "Gym",
    "lifestyle",
    "doctor",
    "pilates",
    "wellness",
    "Health",
    "Healthcare",
    "Human resource",
    "Instructor",
    "Manpower",
    "Managed services",
    "Management",
    "Outsourcing",
    "Procure",
    "Procurement",
    "Provision",
    "Process",
    "Recruitment",
    "Services",
    "Staff",
    "Staffing",
    "Trainer",
    "Nurse",
]
BRIEFING_PATTERN = re.compile(r"\b(briefing|showround|show\s+round)\b", re.IGNORECASE)

CSV_FIELDS = [
    "tender_title",
    "tender_link",
    "industry",
    "company_organisation_name",
    "tender_reference_number",
    "published_date",
    "closing_date",
]
PROCESSED_FIELDS = CSV_FIELDS + ["duration_days", "keyword_group"]
REJECTED_FIELDS = PROCESSED_FIELDS + ["rejection_reason"]


@dataclass
class SaveSummary:
    database_path: Path
    new_output_path: Path | None
    scraped_count: int
    new_count: int
    updated_count: int
    database_count: int


@dataclass
class ProcessedTenderSummary:
    source_path: Path | None
    processed_path: Path | None
    rejected_path: Path | None
    processed_count: int = 0
    rejected_count: int = 0


@dataclass
class RawTenderResult:
    tender_title: str = ""
    tender_link: str = ""
    raw_text: str = ""


@dataclass
class TenderResult:
    tender_title: str = ""
    tender_link: str = ""
    industry: str = ""
    company_organisation_name: str = ""
    tender_reference_number: str = ""
    published_date: str = ""
    closing_date: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "tender_title": self.tender_title,
            "tender_link": self.tender_link,
            "industry": self.industry,
            "company_organisation_name": self.company_organisation_name,
            "tender_reference_number": self.tender_reference_number,
            "published_date": self.published_date,
            "closing_date": self.closing_date,
        }


def clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" :-\t\r\n")


def clean_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()

    for field in CSV_FIELDS:
        if field not in dataframe.columns:
            dataframe[field] = ""

    dataframe = dataframe[CSV_FIELDS]
    dataframe = dataframe.fillna("")
    for field in CSV_FIELDS:
        dataframe[field] = dataframe[field].map(clean_value)

    return dataframe


def tender_identity(row: pd.Series | dict[str, str]) -> str:
    tender_link = clean_value(row.get("tender_link", "")).lower()
    if tender_link:
        return f"link:{tender_link.rstrip('/')}"

    reference = clean_value(row.get("tender_reference_number", "")).lower()
    if reference:
        return f"reference:{reference}"

    title = clean_value(row.get("tender_title", "")).lower()
    company = clean_value(row.get("company_organisation_name", "")).lower()
    closing_date = clean_value(row.get("closing_date", "")).lower()
    return f"fallback:{title}|{company}|{closing_date}"


def output_excel_path(name: str = OUTPUT_NAME, output_dir: Path = OUTPUT_DIR) -> Path:
    timestamp = datetime.now().strftime("%d%H%M")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "TenderBoard"
    return output_dir / f"{timestamp}_{safe_name}.xlsx"


def output_excel_path_for_prefix(prefix: str, name: str, output_dir: Path = OUTPUT_DIR) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or name
    return output_dir / f"{prefix}_{safe_name}.xlsx"


def find_latest_unprocessed_tenderboard(output_dir: Path = OUTPUT_DIR) -> Path | None:
    if not output_dir.exists():
        return None

    candidates = []
    for path in output_dir.glob("*_TenderBoard.xlsx"):
        name_lower = path.name.lower()
        if any(blocked in name_lower for blocked in ["database", "processed", "rejected"]):
            continue
        candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_tender_date(value: str) -> datetime | None:
    value = clean_value(value)
    if not value:
        return None

    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def keyword_group(row: pd.Series | dict[str, str]) -> str:
    searchable_text = " ".join(clean_value(row.get(field, "")) for field in CSV_FIELDS).lower()
    matches = [keyword for keyword in GROUP_KEYWORDS if keyword.lower() in searchable_text]
    if not matches:
        return ""
    return sorted(matches, key=str.lower)[0]


def has_briefing(row: pd.Series | dict[str, str]) -> bool:
    searchable_text = " ".join(clean_value(row.get(field, "")) for field in CSV_FIELDS)
    return bool(BRIEFING_PATTERN.search(searchable_text))


def process_latest_tenderboard_file(
    output_dir: Path = OUTPUT_DIR,
    today: datetime | None = None,
) -> ProcessedTenderSummary:
    source_path = find_latest_unprocessed_tenderboard(output_dir=output_dir)
    if source_path is None:
        return ProcessedTenderSummary(
            source_path=None,
            processed_path=None,
            rejected_path=None,
        )

    today = today or datetime.now()
    today_start = datetime(today.year, today.month, today.day)
    source_dataframe = clean_dataframe(pd.read_excel(source_path))

    processed_rows: list[dict[str, str | int]] = []
    rejected_rows: list[dict[str, str | int]] = []

    for row in source_dataframe.to_dict("records"):
        closing_date = parse_tender_date(row.get("closing_date", ""))
        duration_days = (closing_date - today_start).days if closing_date else ""
        reasons: list[str] = []

        if closing_date is None:
            reasons.append("Missing or unreadable closing date")
        elif duration_days < MIN_DAYS_TO_CLOSE:
            reasons.append(f"Less than {MIN_DAYS_TO_CLOSE} days to closing")

        if has_briefing(row):
            reasons.append("Tender has briefing/showround")

        enriched_row = {
            **row,
            "duration_days": duration_days,
            "keyword_group": keyword_group(row),
        }

        if reasons:
            rejected_rows.append({**enriched_row, "rejection_reason": "; ".join(reasons)})
        else:
            processed_rows.append(enriched_row)

    processed_dataframe = pd.DataFrame(processed_rows, columns=PROCESSED_FIELDS)
    rejected_dataframe = pd.DataFrame(rejected_rows, columns=REJECTED_FIELDS)

    sort_columns = ["duration_days"]
    if not processed_dataframe.empty:
        processed_dataframe = processed_dataframe.sort_values(
            by=sort_columns,
            ascending=[False],
            kind="stable",
        )
    if not rejected_dataframe.empty:
        rejected_dataframe = rejected_dataframe.sort_values(
            by=sort_columns,
            ascending=[False],
            kind="stable",
        )

    prefix = source_path.name.split("_", 1)[0]
    processed_path = output_excel_path_for_prefix(prefix, PROCESSED_OUTPUT_NAME, output_dir=source_path.parent)
    rejected_path = output_excel_path_for_prefix(prefix, REJECTED_OUTPUT_NAME, output_dir=source_path.parent)

    processed_dataframe.to_excel(processed_path, index=False)
    rejected_dataframe.to_excel(rejected_path, index=False)
    source_path.unlink()

    return ProcessedTenderSummary(
        source_path=source_path,
        processed_path=processed_path,
        rejected_path=rejected_path,
        processed_count=len(processed_dataframe),
        rejected_count=len(rejected_dataframe),
    )


def parse_date_range(text: str) -> tuple[str, str]:
    year = datetime.now().year
    range_pattern = re.compile(
        r"\b(\d{1,2}\s+[A-Za-z]{3,9})(?:\s+\d{2,4})?\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9})(?:\s+\d{2,4})?\b"
    )
    match = range_pattern.search(text)
    if match:
        return f"{match.group(1)} {year}", f"{match.group(2)} {year}"

    full_date_pattern = re.compile(
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    )
    dates = full_date_pattern.findall(text)
    published = dates[0] if dates else ""
    closing = dates[1] if len(dates) > 1 else ""
    return published, closing


def normalize_short_date(value: str) -> str:
    value = clean_value(value)
    if re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3,9}", value):
        return f"{value} {datetime.now().year}"
    return value


def is_date_line(value: str) -> bool:
    value = clean_value(value)
    return bool(
        re.fullmatch(r"\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{2,4})?", value)
        or re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", value)
    )


def process_line_based_result(raw: RawTenderResult) -> TenderResult | None:
    lines = [clean_value(line) for line in raw.raw_text.splitlines() if clean_value(line)]
    title = clean_value(raw.tender_title)

    if title and lines and lines[0].lower() == title.lower():
        lines = lines[1:]

    date_lines: list[str] = []
    while lines and is_date_line(lines[-1]) and len(date_lines) < 2:
        date_lines.insert(0, normalize_short_date(lines.pop()))

    if len(date_lines) < 2 or len(lines) < 3:
        return None

    return TenderResult(
        tender_title=title,
        tender_link=raw.tender_link,
        industry=lines[0],
        company_organisation_name=lines[1],
        tender_reference_number=lines[2],
        published_date=date_lines[0],
        closing_date=date_lines[1],
    )


def remove_noise(text: str) -> str:
    text = re.sub(r"There is a tender briefing/showround\.", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"Registration Closes On:\s*.*?(?=\d{1,2}\s+[A-Za-z]{3,9}\s*-|$)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"You have viewed this deal", " ", text, flags=re.IGNORECASE)
    return clean_value(text)


def reference_from_link(link: str) -> str:
    if not link:
        return ""
    slug = link.rstrip("/").split("/")[-1]
    return slug.upper() if slug else ""


def split_reference(text: str, link: str) -> tuple[str, str]:
    reference = reference_from_link(link)
    if not reference:
        reference = ""

    if reference:
        match = re.search(re.escape(reference), text, flags=re.IGNORECASE)
        if match:
            before = clean_value(text[: match.start()])
            return before, clean_value(text[match.start() : match.end()])

    trailing_reference = re.search(
        r"([A-Z]{2,}[A-Z0-9]*[/-][A-Z0-9/_-]*\d[A-Z0-9/_-]*|[A-Z]{2,}\d[A-Z0-9/_-]*)$",
        text,
    )
    if trailing_reference:
        return clean_value(text[: trailing_reference.start()]), trailing_reference.group(1)

    if reference:
        compact_reference = reference.replace("-", "").replace("/", "")
        compact_text = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        if compact_reference and compact_reference in compact_text:
            return text, reference

    return text, reference


def split_industry_and_company(text: str) -> tuple[str, str]:
    known_prefixes = [
        "Administration & Training",
        "Cleaning Services",
        "Event Organising, Food & Beverages",
        "Horticulture Works",
        "IT&Telecommunication",
        "Not Specified",
        "Others",
        "Professional Services",
        "Security Services",
    ]

    for prefix in known_prefixes:
        if text.lower().startswith(prefix.lower()):
            remainder = clean_value(text[len(prefix) :])
            if remainder.startswith(":"):
                remainder = clean_value(remainder[1:])
                spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", remainder)
                return prefix, spaced
            return prefix, remainder

    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return "", clean_value(spaced)


def process_raw_result(raw: RawTenderResult) -> TenderResult:
    line_based = process_line_based_result(raw)
    if line_based is not None:
        return line_based

    text = clean_value(raw.raw_text)
    title = clean_value(raw.tender_title)

    if title and text.lower().startswith(title.lower()):
        text = clean_value(text[len(title) :])

    published_date, closing_date = parse_date_range(text)
    text = re.sub(
        r"\b\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{2,4})?\s*-\s*\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{2,4})?\b",
        " ",
        text,
    )
    text = remove_noise(text)

    before_reference, tender_reference_number = split_reference(text, raw.tender_link)
    industry, company = split_industry_and_company(before_reference)

    return TenderResult(
        tender_title=title,
        tender_link=raw.tender_link,
        industry=industry,
        company_organisation_name=company,
        tender_reference_number=tender_reference_number,
        published_date=published_date,
        closing_date=closing_date,
    )


def process_raw_results(raw_results: list[RawTenderResult]) -> list[TenderResult]:
    return [process_raw_result(raw) for raw in raw_results]


def process_existing_csv(input_path: Path, output_path: Path | None = None) -> Path:
    raw_results: list[RawTenderResult] = []

    with input_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            raw_text = row.get("raw_text") or " ".join(
                [
                    row.get("tender_title", ""),
                    row.get("industry", ""),
                    row.get("company_organisation_name", ""),
                    row.get("tender_reference_number", ""),
                    row.get("published_date", ""),
                    row.get("closing_date", ""),
                ]
            )
            raw_results.append(
                RawTenderResult(
                    tender_title=row.get("tender_title", ""),
                    tender_link=row.get("tender_link", ""),
                    raw_text=raw_text,
                )
            )

    return save_results(process_raw_results(raw_results), output_path=output_path)


def save_results(results: list[TenderResult], output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = output_excel_path()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = pd.DataFrame([result.as_dict() for result in results], columns=CSV_FIELDS)
    dataframe.to_excel(output_path, index=False)
    return output_path


def save_results_to_database(
    results: list[TenderResult],
    database_path: Path = DATABASE_PATH,
) -> SaveSummary:
    database_path.parent.mkdir(parents=True, exist_ok=True)

    scraped_dataframe = clean_dataframe(pd.DataFrame([result.as_dict() for result in results]))
    if database_path.exists():
        database_dataframe = clean_dataframe(pd.read_excel(database_path))
    else:
        database_dataframe = clean_dataframe(pd.DataFrame(columns=CSV_FIELDS))

    database_rows = database_dataframe.to_dict("records")
    row_indexes_by_key = {
        tender_identity(row): index
        for index, row in enumerate(database_rows)
        if tender_identity(row) != "fallback:||"
    }

    new_rows: list[dict[str, str]] = []
    updated_count = 0

    for row in scraped_dataframe.to_dict("records"):
        key = tender_identity(row)
        existing_index = row_indexes_by_key.get(key)

        if existing_index is None:
            row_indexes_by_key[key] = len(database_rows)
            database_rows.append(row)
            new_rows.append(row)
            continue

        existing_row = database_rows[existing_index]
        merged_row = {
            field: clean_value(row.get(field, "")) or clean_value(existing_row.get(field, ""))
            for field in CSV_FIELDS
        }
        if merged_row != existing_row:
            database_rows[existing_index] = merged_row
            updated_count += 1

    merged_database = clean_dataframe(pd.DataFrame(database_rows, columns=CSV_FIELDS))
    merged_database.to_excel(database_path, index=False)

    new_output_path = None
    if new_rows:
        new_output_path = output_excel_path(output_dir=database_path.parent)
        clean_dataframe(pd.DataFrame(new_rows, columns=CSV_FIELDS)).to_excel(
            new_output_path,
            index=False,
        )

    return SaveSummary(
        database_path=database_path,
        new_output_path=new_output_path,
        scraped_count=len(scraped_dataframe),
        new_count=len(new_rows),
        updated_count=updated_count,
        database_count=len(merged_database),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Process an existing TenderBoard CSV file into Excel.")
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output_path = process_existing_csv(args.input_csv, output_path=args.output)
    print(f"Saved processed Excel file to {output_path.resolve()}")


if __name__ == "__main__":
    main()
