"""Generic bulk generator for any ``{{ placeholder }}`` Word template.

No Streamlit imports here: the page in ``Contracts/pages/Bulk_Template_Generator.py``
drives this module. The existing CFS generator is reused, never modified.
"""

from __future__ import annotations

import datetime
import logging
import re
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd
from docx import Document
from docxtpl import DocxTemplate

from Contracts.generators.cfs_generator import (
    BulkContractFailure,
    BulkContractResult,
    _apply_cfs_pagination,
    _display_row_number,
    _unique_archive_filename,
    format_contract_date,
    format_contract_time,
)
from Contracts.shared.file_utils import create_zip_from_bytes, sanitize_filename
from Contracts.shared.pdf_utils import convert_docx_to_pdf
from Contracts.shared.template_lint import (
    PreparedTemplate,
    TemplateField,
    canonical_key,
    find_leftover_template_text,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "Contracts" / "templates"
LOGGER = logging.getLogger(__name__)

TYPE_TEXT = "Text"
TYPE_UPPER = "UPPERCASE"
TYPE_DATE = "Date"
TYPE_TIME = "Time"
TYPE_MONEY = "Money"
FIELD_TYPES = (TYPE_TEXT, TYPE_UPPER, TYPE_DATE, TYPE_TIME, TYPE_MONEY)

MONEY_WORDS = {"fee", "fees", "amount", "salary", "price", "cost", "pay", "rate", "allowance", "sgd"}
UPPER_WORDS = {"nric", "fin", "passport", "uen"}

# Template-specific post-processing, keyed by template filename. The CFS
# template keeps its existing pagination rules when used from the bulk page.
PostProcessor = Callable[[object], None]
POST_PROCESSORS: dict[str, PostProcessor] = {
    "AMS - CFS - REB - Template.docx": _apply_cfs_pagination,
}


@dataclass(frozen=True)
class FieldSetting:
    """How the user wants one template field filled."""

    name: str
    label: str
    field_type: str
    shared: bool
    required: bool = True


@dataclass(frozen=True)
class RowContext:
    row_number: int
    identifier: str
    context: dict[str, str]


# --------------------------------------------------------------------------- #
# Template library
# --------------------------------------------------------------------------- #


def list_library_templates(root: Path = TEMPLATES_DIR) -> list[Path]:
    """Every committed ``.docx`` template (Word lock files excluded)."""
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*.docx") if path.is_file() and not path.name.startswith("~$")
    )


def library_label(path: Path, root: Path = TEMPLATES_DIR) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def post_processor_for(template_filename: str) -> PostProcessor | None:
    return POST_PROCESSORS.get(Path(template_filename).name)


# --------------------------------------------------------------------------- #
# Field types
# --------------------------------------------------------------------------- #


def _name_words(name: str) -> set[str]:
    return set(filter(None, re.split(r"[^0-9a-z]+", name.lower())))


def infer_field_type(name: str) -> str:
    """Guess a field type from its name: ``*_date`` -> Date, ``*_fee`` -> Money, ..."""
    words = _name_words(name)
    if "date" in words or "dob" in words:
        return TYPE_DATE
    if "time" in words:
        return TYPE_TIME
    if words & MONEY_WORDS:
        return TYPE_MONEY
    if words & UPPER_WORDS:
        return TYPE_UPPER
    return TYPE_TEXT


def default_settings(fields: Iterable[TemplateField]) -> list[FieldSetting]:
    """Dates, times and money default to "same for all"; text defaults to per row."""
    settings = []
    for template_field in fields:
        field_type = infer_field_type(template_field.name)
        settings.append(
            FieldSetting(
                name=template_field.name,
                label=template_field.label,
                field_type=field_type,
                shared=field_type in {TYPE_DATE, TYPE_TIME, TYPE_MONEY},
            )
        )
    return settings


def default_date_for(name: str, today: datetime.date | None = None) -> datetime.date:
    from Contracts.generators.cfs_generator import end_of_month

    today = today or datetime.date.today()
    return end_of_month(today) if "end" in _name_words(name) else today


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d-%b-%Y",
    "%d %B, %Y",
    "%B %d, %Y",
)
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M%p", "%I%p", "%I:%M:%S%p", "%H%M")


def parse_date(value: object) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a date I can read (use e.g. 1/7/2026 or 2026-07-01)")


def parse_time(value: object) -> datetime.time:
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    text = str(value).strip()
    compact = text.lower().replace(".", "").replace(" ", "")
    for time_format in TIME_FORMATS:
        try:
            return datetime.datetime.strptime(compact, time_format).time()
        except ValueError:
            continue
    raise ValueError(f"'{text}' is not a time I can read (use e.g. 14:00 or 2:00 pm)")


def parse_money(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = re.sub(r"(?i)sgd|s\$|\$|,|\s", "", str(value))
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"'{value}' is not an amount I can read (use e.g. 20 or 1,234.50)") from None


def format_value(value: object, field_type: str) -> str:
    """Turn a raw cell or widget value into the text placed in the contract."""
    if field_type == TYPE_DATE:
        return format_contract_date(parse_date(value))
    if field_type == TYPE_TIME:
        return format_contract_time(parse_time(value))
    if field_type == TYPE_MONEY:
        return f"{parse_money(value):,.2f}"
    text = str(value).strip()
    return text.upper() if field_type == TYPE_UPPER else text


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


# --------------------------------------------------------------------------- #
# Row data
# --------------------------------------------------------------------------- #


def per_row_settings(settings: Iterable[FieldSetting]) -> list[FieldSetting]:
    return [setting for setting in settings if not setting.shared]


def blank_rows(settings: Iterable[FieldSetting], count: int = 10) -> pd.DataFrame:
    columns = [setting.label for setting in per_row_settings(settings)]
    return pd.DataFrame([{column: "" for column in columns} for _ in range(count)], columns=columns)


def match_uploaded_columns(
    data: pd.DataFrame, settings: Iterable[FieldSetting]
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Map uploaded headers onto per-row fields, forgiving case/space/underscore.

    Returns ``(dataframe with field-label columns, unmatched upload headers,
    per-row field labels with no matching column)``.
    """
    rows = per_row_settings(settings)
    by_key: dict[str, str] = {}
    for setting in rows:
        for candidate in (setting.label, setting.name):
            key = canonical_key(candidate)
            if key:
                by_key.setdefault(key, setting.label)

    renamed: dict[str, str] = {}
    unmatched: list[str] = []
    for column in data.columns:
        target = by_key.get(canonical_key(str(column)) or "")
        if target and target not in renamed.values():
            renamed[column] = target
        else:
            unmatched.append(str(column))

    matched = data.rename(columns=renamed)
    labels = [setting.label for setting in rows]
    missing = [label for label in labels if label not in matched.columns]
    for label in missing:
        matched[label] = ""
    matched = matched[labels].fillna("").astype(str)
    for label in labels:
        matched[label] = matched[label].str.strip()
    matched = matched[~(matched == "").all(axis=1)].reset_index(drop=True)
    return matched, unmatched, missing


def build_shared_context(
    settings: Iterable[FieldSetting], shared_values: dict[str, object]
) -> tuple[dict[str, str], list[str]]:
    context: dict[str, str] = {}
    errors: list[str] = []
    for setting in settings:
        if not setting.shared:
            continue
        value = shared_values.get(setting.name)
        if _is_blank(value):
            if setting.required:
                errors.append(f"{setting.label} is required.")
            context[setting.name] = ""
            continue
        try:
            context[setting.name] = format_value(value, setting.field_type)
        except ValueError as exc:
            errors.append(f"{setting.label}: {exc}")
    return context, errors


def build_row_contexts(
    rows: pd.DataFrame,
    settings: Iterable[FieldSetting],
    shared_context: dict[str, str],
) -> tuple[list[RowContext], pd.DataFrame]:
    """Validate each row; return ready rows and a table of row errors."""
    settings = list(settings)
    row_fields = per_row_settings(settings)
    identifier_field = next(
        (s for s in row_fields if s.field_type in {TYPE_TEXT, TYPE_UPPER}),
        row_fields[0] if row_fields else None,
    )
    ready: list[RowContext] = []
    errors: list[dict[str, object]] = []

    for position, (index, row) in enumerate(rows.iterrows(), start=1):
        row_number = _display_row_number(index, position)
        context = dict(shared_context)
        problems: list[str] = []
        for setting in row_fields:
            value = row.get(setting.label, "")
            if _is_blank(value):
                if setting.required:
                    problems.append(f"Missing {setting.label}")
                context[setting.name] = ""
                continue
            try:
                context[setting.name] = format_value(value, setting.field_type)
            except ValueError as exc:
                problems.append(f"{setting.label}: {exc}")

        identifier = ""
        if identifier_field is not None:
            identifier = str(row.get(identifier_field.label, "") or "").strip()
        identifier = identifier or f"Row {row_number}"

        if problems:
            errors.append({"Row Number": row_number, "Row": identifier, "Issue": "; ".join(problems)})
        else:
            ready.append(RowContext(row_number=row_number, identifier=identifier, context=context))

    return ready, pd.DataFrame(errors, columns=["Row Number", "Row", "Issue"])


# --------------------------------------------------------------------------- #
# File names
# --------------------------------------------------------------------------- #

FILENAME_TOKEN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def default_filename_pattern(template_filename: str, settings: Iterable[FieldSetting]) -> str:
    stem = Path(template_filename).stem
    stem = re.sub(r"[\s_-]*template$", "", stem, flags=re.IGNORECASE).strip(" -_") or stem
    rows = per_row_settings(settings)
    first = next((s for s in rows if s.field_type in {TYPE_TEXT, TYPE_UPPER}), rows[0] if rows else None)
    return f"{stem} - {{{{ {first.label} }}}}" if first else stem


def _resolve_token(token: str, settings: Iterable[FieldSetting]) -> FieldSetting | None:
    key = canonical_key(token)
    for setting in settings:
        if token in {setting.name, setting.label} or key in {
            canonical_key(setting.name),
            canonical_key(setting.label),
        }:
            return setting
    return None


def validate_filename_pattern(pattern: str, settings: Iterable[FieldSetting]) -> list[str]:
    settings = list(settings)
    errors = []
    if not pattern.strip():
        errors.append("File name pattern cannot be blank.")
    for token in FILENAME_TOKEN.findall(pattern):
        if _resolve_token(token, settings) is None:
            errors.append(f"File name uses {{{{ {token} }}}}, which is not a field in this template.")
    return errors


def render_filename(pattern: str, context: dict[str, str], settings: Iterable[FieldSetting]) -> str:
    settings = list(settings)

    def substitute(match: re.Match) -> str:
        setting = _resolve_token(match.group(1), settings)
        return context.get(setting.name, "") if setting else ""

    name = sanitize_filename(FILENAME_TOKEN.sub(substitute, pattern))
    if name.lower().endswith(".pdf"):
        name = name[:-4].rstrip(" .") or "Contract"
    return f"{name}.pdf"


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render_contract_docx(
    prepared: PreparedTemplate,
    context: dict[str, str],
    post_processor: PostProcessor | None = None,
) -> bytes:
    """Render one contract and fail loudly if any template text survived."""
    template = DocxTemplate(BytesIO(prepared.cleaned_bytes))
    # autoescape keeps values such as "Blk 1 & 2" from corrupting the Word XML.
    template.render(context, autoescape=True)
    rendered = BytesIO()
    template.save(rendered)

    if post_processor is not None:
        rendered.seek(0)
        document = Document(rendered)
        post_processor(document)
        rendered = BytesIO()
        document.save(rendered)

    docx_bytes = rendered.getvalue()
    leftovers = find_leftover_template_text(docx_bytes, prepared.literal_texts)
    if leftovers:
        shown = ", ".join(f"'{text}'" for text in leftovers[:5])
        raise RuntimeError(f"Leftover template text in the output: {shown}")
    return docx_bytes


def build_dynamic_bulk_batch(
    prepared: PreparedTemplate,
    rows: list[RowContext],
    filename_pattern: str,
    settings: Iterable[FieldSetting],
    progress=None,
    post_processor: PostProcessor | None = None,
) -> BulkContractResult:
    """Generate one PDF per row independently; one bad row never stops the rest."""
    settings = list(settings)
    total = len(rows)
    generated_files: list[tuple[str, bytes]] = []
    generated_filenames: list[str] = []
    failures: list[BulkContractFailure] = []
    used_archive_names: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="ams_dynamic_contracts_") as operation_dir_name:
        for position, row in enumerate(rows, start=1):
            if progress is not None:
                progress.progress((position - 1) / total, text=f"Generating contract {position} of {total}")
            try:
                with tempfile.TemporaryDirectory(prefix=f"row_{position}_", dir=operation_dir_name) as row_dir_name:
                    row_dir = Path(row_dir_name)
                    docx_bytes = render_contract_docx(prepared, row.context, post_processor)
                    docx_path = row_dir / f"contract_{position}.docx"
                    docx_path.write_bytes(docx_bytes)
                    pdf_bytes = convert_docx_to_pdf(docx_path, row_dir).read_bytes()

                archive_name = _unique_archive_filename(
                    render_filename(filename_pattern, row.context, settings),
                    used_archive_names,
                )
                generated_files.append((archive_name, pdf_bytes))
                generated_filenames.append(archive_name)
            except Exception as exc:
                LOGGER.exception("Bulk template generation failed for row %s (%s)", row.row_number, row.identifier)
                failures.append(
                    BulkContractFailure(
                        row_number=row.row_number,
                        identifier=row.identifier,
                        exception_type=type(exc).__name__,
                        message=str(exc).strip() or "No error details were returned.",
                    )
                )
            if progress is not None:
                progress.progress(position / total, text=f"Generating contract {position} of {total}")

    return BulkContractResult(
        zip_bytes=create_zip_from_bytes(generated_files) if generated_files else None,
        generated_filenames=tuple(generated_filenames),
        failures=tuple(failures),
    )
