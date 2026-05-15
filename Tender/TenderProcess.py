import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "Tender" / "Excel Sheets"
OUTPUT_NAME = "TenderBoard"

CSV_FIELDS = [
    "tender_title",
    "tender_link",
    "industry",
    "company_organisation_name",
    "tender_reference_number",
    "published_date",
    "closing_date",
]


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


def output_excel_path(name: str = OUTPUT_NAME) -> Path:
    timestamp = datetime.now().strftime("%d%H%M")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "TenderBoard"
    return OUTPUT_DIR / f"{timestamp}_{safe_name}.xlsx"


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
