from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd
from bs4 import BeautifulSoup


CANONICAL_JOB_COLUMNS = [
    "Job ID",
    "Car Plate",
    "Pickup Address",
    "Pickup Lot",
    "Drop-off Address",
    "Drop-off Lot",
    "Created At",
    "Deadline",
    "Status",
    "Source",
    "_original_order",
]

REQUIRED_ROUTE_FIELDS = ["Car Plate", "Pickup Address", "Drop-off Address"]


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"
    rows: tuple[int, ...] = ()
    column: str | None = None


@dataclass(frozen=True)
class ImportReport:
    rows_detected: int = 0
    rows_accepted: int = 0
    rows_requiring_correction: int = 0
    rows_excluded: int = 0
    duplicate_rows: int = 0
    missing_location_rows: int = 0


@dataclass
class JobValidationResult:
    dataframe: pd.DataFrame
    issues: list[ValidationIssue] = field(default_factory=list)
    ready_mask: pd.Series = field(default_factory=lambda: pd.Series(dtype=bool))
    report: ImportReport = field(default_factory=ImportReport)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity != "error"]


@dataclass
class ImportResult:
    dataframe: pd.DataFrame
    source_type: str
    report: ImportReport
    issues: list[ValidationIssue] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _clean(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalise_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean(value).casefold())


HEADER_ALIASES: dict[str, set[str]] = {
    "Job ID": {"id", "jobid", "taskid", "orderid"},
    "Car Plate": {
        "carplate",
        "carplates",
        "carno",
        "carnumber",
        "vehicle",
        "vehiclenumber",
        "vehicleplate",
        "licenceplate",
        "licenseplate",
        "lp",
    },
    "Pickup Address": {
        "pickup",
        "pickupaddress",
        "pickuplocation",
        "pickuplocationaddress",
        "pickupstation",
        "startstation",
        "startlocation",
        "origin",
    },
    "Pickup Lot": {
        "pickuplot",
        "pickuplotnumber",
        "pickuplotsnumber",
        "pickupparkinglot",
    },
    "Drop-off Address": {
        "dropoff",
        "dropoffaddress",
        "dropofflocation",
        "dropoffstation",
        "endstation",
        "endlocation",
        "destination",
    },
    "Drop-off Lot": {
        "dropofflot",
        "dropofflotnumber",
        "destinationlot",
        "endlot",
    },
    "Created At": {"created", "createdat", "creationtime"},
    "Deadline": {"deadline", "deadlinesgt", "due", "duetime", "completeby"},
    "Status": {"status", "jobstatus", "taskstatus"},
    "Worker": {"worker", "driver", "assignedworker", "assignedto"},
    "Date": {"date", "jobdate"},
    "Fuel %": {"fuel", "fuelpercent", "fuelpercentage"},
    "Pickup Time": {"pickuptime", "starttime"},
    "Notes": {"notes", "note", "remarks", "remark"},
}

_AMBIGUOUS_LOT_HEADERS = {"lot", "lots", "lotnumber", "lotsnumber"}


def canonical_header(value: Any) -> str | None:
    key = normalise_header(value)
    for canonical, aliases in HEADER_ALIASES.items():
        if key in aliases:
            return canonical
    return None


def _recognised_header_score(values: list[Any]) -> int:
    recognised = {canonical_header(value) for value in values}
    score = sum(
        canonical in recognised
        for canonical in ("Car Plate", "Pickup Address", "Drop-off Address", "Job ID", "Status")
    )
    if any(normalise_header(value) in _AMBIGUOUS_LOT_HEADERS for value in values):
        score += 1
    return score


def find_header_row(raw: pd.DataFrame, max_rows: int = 30) -> int:
    if raw.empty:
        return 0
    scores = [
        (_recognised_header_score(raw.iloc[index].tolist()), index)
        for index in range(min(max_rows, len(raw)))
    ]
    return max(scores, key=lambda item: (item[0], -item[1]))[1]


def _lot_mapping(headers: list[Any]) -> dict[int, str]:
    pickup_index = next(
        (index for index, value in enumerate(headers) if canonical_header(value) == "Pickup Address"),
        -1,
    )
    dropoff_index = next(
        (index for index, value in enumerate(headers) if canonical_header(value) == "Drop-off Address"),
        len(headers),
    )
    ambiguous = [
        index for index, value in enumerate(headers)
        if normalise_header(value) in _AMBIGUOUS_LOT_HEADERS
    ]
    mapping: dict[int, str] = {}
    for index in ambiguous:
        if pickup_index < index < dropoff_index and "Pickup Lot" not in mapping.values():
            mapping[index] = "Pickup Lot"
        elif index > dropoff_index and "Drop-off Lot" not in mapping.values():
            mapping[index] = "Drop-off Lot"
    for index in ambiguous:
        if index in mapping:
            continue
        if "Pickup Lot" not in mapping.values():
            mapping[index] = "Pickup Lot"
        elif "Drop-off Lot" not in mapping.values():
            mapping[index] = "Drop-off Lot"
    return mapping


def _stable_fallback_job_id(row: pd.Series) -> str:
    original_order = pd.to_numeric(row.get("_original_order"), errors="coerce")
    original_order = 0 if pd.isna(original_order) else int(original_order)
    parts = [
        normalise_header(row.get("Car Plate")),
        normalise_header(row.get("Pickup Address")),
        normalise_header(row.get("Pickup Lot")),
        normalise_header(row.get("Drop-off Address")),
        normalise_header(row.get("Drop-off Lot")),
        str(original_order),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12].upper()
    return f"AUTO-{digest}"


def normalise_job_dataframe(
    df: pd.DataFrame,
    *,
    source: str = "Manual",
    headers_are_normalised: bool = False,
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=CANONICAL_JOB_COLUMNS)

    raw = df.copy()
    headers = list(raw.columns)
    lot_mapping = _lot_mapping(headers)
    output = pd.DataFrame(index=raw.index)
    used_source_columns: set[int] = set()

    for index, header in enumerate(headers):
        canonical = header if headers_are_normalised and header in HEADER_ALIASES else canonical_header(header)
        if index in lot_mapping:
            canonical = lot_mapping[index]
        if canonical is None or canonical in output.columns:
            continue
        output[canonical] = raw.iloc[:, index]
        used_source_columns.add(index)

    for index, header in enumerate(headers):
        if index in used_source_columns:
            continue
        name = _clean(header) or f"Source Column {index + 1}"
        if name in output.columns:
            name = f"{name} ({index + 1})"
        output[name] = raw.iloc[:, index]

    for column in CANONICAL_JOB_COLUMNS:
        if column not in output.columns:
            output[column] = ""
    if "_original_order" not in raw.columns:
        output["_original_order"] = range(len(output))
    else:
        output["_original_order"] = pd.to_numeric(raw["_original_order"], errors="coerce")
        output["_original_order"] = output["_original_order"].fillna(pd.Series(range(len(output)), index=output.index))
    output["_original_order"] = output["_original_order"].astype(int)
    output["Source"] = output["Source"].apply(_clean).replace("", source)

    text_columns = [column for column in CANONICAL_JOB_COLUMNS if column != "_original_order"]
    for column in text_columns:
        output[column] = output[column].apply(_clean)
    missing_ids = output["Job ID"].eq("")
    output.loc[missing_ids, "Job ID"] = output.loc[missing_ids].apply(_stable_fallback_job_id, axis=1)

    ordered = [*CANONICAL_JOB_COLUMNS, *[column for column in output.columns if column not in CANONICAL_JOB_COLUMNS]]
    return output.loc[:, ordered].reset_index(drop=True)


def _frame_from_raw_rows(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    if raw.empty:
        return normalise_job_dataframe(raw, source=source)
    header_row = find_header_row(raw)
    headers = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = headers
    data = data.dropna(how="all")
    data["_original_order"] = range(len(data))
    return normalise_job_dataframe(data, source=source)


def _bytes_from_file(uploaded_file: Any) -> tuple[bytes, str]:
    name = _clean(getattr(uploaded_file, "name", ""))
    if isinstance(uploaded_file, (bytes, bytearray)):
        return bytes(uploaded_file), name
    if isinstance(uploaded_file, (str, Path)):
        path = Path(uploaded_file)
        return path.read_bytes(), path.name
    if hasattr(uploaded_file, "getvalue"):
        return bytes(uploaded_file.getvalue()), name
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    payload = uploaded_file.read()
    return payload.encode("utf-8") if isinstance(payload, str) else bytes(payload), name


def parse_excel_jobs(uploaded_file: BinaryIO | bytes | str | Path) -> ImportResult:
    payload, name = _bytes_from_file(uploaded_file)
    try:
        raw = pd.read_excel(BytesIO(payload), header=None)
    except Exception as exc:
        raise ValueError(f"Unable to read the Excel job source: {exc}") from exc
    dataframe = _frame_from_raw_rows(raw, "Excel")
    result = validate_staged_jobs(dataframe)
    return ImportResult(dataframe, "excel", result.report, result.issues, {"filename": name})


def parse_csv_jobs(uploaded_file: BinaryIO | bytes | str | Path) -> ImportResult:
    payload, name = _bytes_from_file(uploaded_file)
    try:
        raw = pd.read_csv(BytesIO(payload), header=None, dtype=object, keep_default_na=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(
            BytesIO(payload), header=None, dtype=object, keep_default_na=False, encoding="cp1252"
        )
    except Exception as exc:
        raise ValueError(f"Unable to read the CSV job source: {exc}") from exc
    dataframe = _frame_from_raw_rows(raw, "CSV")
    result = validate_staged_jobs(dataframe)
    return ImportResult(dataframe, "csv", result.report, result.issues, {"filename": name})


def parse_html_job_list(html: str) -> ImportResult:
    soup = BeautifulSoup(html or "", "html.parser")
    tables = soup.find_all("table")
    frames: list[pd.DataFrame] = []
    if tables:
        try:
            frames = pd.read_html(StringIO(str(soup)))
        except ValueError:
            frames = []
    if frames:
        best = max(frames, key=lambda frame: _recognised_header_score(frame.columns.tolist()))
        dataframe = normalise_job_dataframe(best, source="Flexar HTML")
    else:
        rows: list[list[str]] = []
        for row in soup.select("tr"):
            values = [_clean(cell.get_text(" ", strip=True)) for cell in row.select("th, td")]
            if values:
                rows.append(values)
        if not rows:
            raise ValueError("No job-list table was found in the pasted HTML.")
        raw = pd.DataFrame(rows)
        dataframe = _frame_from_raw_rows(raw, "Flexar HTML")
    result = validate_staged_jobs(dataframe)
    return ImportResult(
        dataframe,
        "html",
        result.report,
        result.issues,
        {"locations_present": not bool(result.report.missing_location_rows)},
    )


def _detect_delimiter(text: str) -> str:
    sample = next((line for line in text.splitlines() if line.strip()), "")
    candidates = ["\t", "|", ";", ","]
    return max(candidates, key=lambda delimiter: sample.count(delimiter))


def parse_delimited_text(text: str) -> ImportResult:
    cleaned = (text or "").strip()
    if not cleaned:
        return ImportResult(
            pd.DataFrame(columns=CANONICAL_JOB_COLUMNS),
            "text",
            ImportReport(),
        )
    delimiter = _detect_delimiter(cleaned)
    if delimiter not in cleaned.splitlines()[0]:
        raise ValueError("Could not detect tab, comma, semicolon, or pipe-delimited job columns.")
    raw = pd.read_csv(
        StringIO(cleaned),
        sep=delimiter,
        header=None,
        dtype=object,
        keep_default_na=False,
        engine="python",
    )
    dataframe = _frame_from_raw_rows(raw, "Pasted text")
    result = validate_staged_jobs(dataframe)
    return ImportResult(dataframe, "text", result.report, result.issues)


def parse_job_source(
    uploaded_file: Any = None,
    pasted_text: str | None = None,
) -> ImportResult:
    if uploaded_file is not None:
        payload, name = _bytes_from_file(uploaded_file)
        suffix = Path(name).suffix.casefold()
        if suffix in {".xlsx", ".xls", ".xlsm"} or payload[:2] == b"PK":
            return parse_excel_jobs(payload)
        if suffix == ".csv":
            return parse_csv_jobs(payload)
        try:
            decoded = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = payload.decode("cp1252")
        return parse_html_job_list(decoded) if "<table" in decoded.casefold() else parse_delimited_text(decoded)

    text = pasted_text or ""
    if re.search(r"<(?:table|tr|td|th)\b", text, flags=re.IGNORECASE):
        return parse_html_job_list(text)
    return parse_delimited_text(text)


_PLATE_PATTERN = re.compile(r"^[A-Z]{1,3}\d{1,4}[A-Z]$")


def validate_staged_jobs(df: pd.DataFrame) -> JobValidationResult:
    dataframe = normalise_job_dataframe(df, source="Manual", headers_are_normalised=True)
    if dataframe.empty:
        return JobValidationResult(
            dataframe,
            [ValidationIssue("no_jobs", "Add or import at least one job.")],
            pd.Series(dtype=bool),
            ImportReport(),
        )

    issues: list[ValidationIssue] = []
    missing_by_field: dict[str, pd.Series] = {
        column: dataframe[column].apply(_clean).eq("") for column in REQUIRED_ROUTE_FIELDS
    }
    for column, mask in missing_by_field.items():
        if mask.any():
            rows = tuple((dataframe.index[mask] + 1).tolist())
            issues.append(
                ValidationIssue(
                    f"missing_{normalise_header(column)}",
                    f"{len(rows)} row(s) need {column}.",
                    rows=rows,
                    column=column,
                )
            )

    malformed = dataframe["Car Plate"].apply(_clean).str.upper().map(
        lambda value: bool(value) and _PLATE_PATTERN.fullmatch(value) is None
    )
    if malformed.any():
        rows = tuple((dataframe.index[malformed] + 1).tolist())
        issues.append(
            ValidationIssue(
                "malformed_car_plate",
                f"{len(rows)} car plate value(s) have an unusual format; verify them before dispatch.",
                severity="warning",
                rows=rows,
                column="Car Plate",
            )
        )

    duplicate_ids = dataframe["Job ID"].apply(_clean).duplicated(keep=False)
    if duplicate_ids.any():
        rows = tuple((dataframe.index[duplicate_ids] + 1).tolist())
        issues.append(
            ValidationIssue(
                "duplicate_job_id",
                "Job IDs must be unique.",
                rows=rows,
                column="Job ID",
            )
        )

    duplicate_plates = dataframe["Car Plate"].apply(_clean).str.upper().loc[
        lambda series: series.ne("")
    ].duplicated(keep=False)
    duplicate_plate_rows = tuple((duplicate_plates.index[duplicate_plates] + 1).tolist())
    if duplicate_plate_rows:
        issues.append(
            ValidationIssue(
                "duplicate_car_plate",
                "The same car plate appears on multiple jobs. Different job IDs are retained, but verify the rows.",
                severity="warning",
                rows=duplicate_plate_rows,
                column="Car Plate",
            )
        )

    identity_columns = ["Car Plate", "Pickup Address", "Drop-off Address", "Deadline"]
    identity = dataframe[identity_columns].map(lambda value: normalise_header(value)).agg("|".join, axis=1)
    duplicate_jobs = identity.duplicated(keep=False)
    if duplicate_jobs.any():
        rows = tuple((dataframe.index[duplicate_jobs] + 1).tolist())
        issues.append(
            ValidationIssue(
                "duplicate_job",
                "Duplicate committed job identities are not allowed.",
                rows=rows,
            )
        )

    ready_mask = ~pd.concat(missing_by_field.values(), axis=1).any(axis=1)
    correction_mask = ~ready_mask | duplicate_ids | duplicate_jobs
    missing_location_mask = (
        dataframe["Pickup Address"].apply(_clean).eq("")
        | dataframe["Drop-off Address"].apply(_clean).eq("")
    )
    report = ImportReport(
        rows_detected=len(dataframe),
        rows_accepted=int(ready_mask.sum()),
        rows_requiring_correction=int(correction_mask.sum()),
        rows_excluded=0,
        duplicate_rows=int(duplicate_jobs.sum()),
        missing_location_rows=int(missing_location_mask.sum()),
    )
    return JobValidationResult(dataframe, issues, ready_mask, report)


def commit_staged_jobs(df: pd.DataFrame) -> pd.DataFrame:
    validation = validate_staged_jobs(df)
    if not validation.is_valid:
        raise ValueError("; ".join(issue.message for issue in validation.errors))
    committed = validation.dataframe.copy(deep=True)
    committed["Car Plate"] = committed["Car Plate"].str.upper()
    # Compatibility fields consumed by the existing optimiser and integrity checker.
    committed["_uploaded_row"] = committed["_original_order"].astype(int) + 2
    committed["Uploaded Row"] = committed["_uploaded_row"]
    return committed
