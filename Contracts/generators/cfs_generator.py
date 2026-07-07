from __future__ import annotations

import datetime
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
from docxtpl import DocxTemplate

from Contracts.shared.file_utils import create_zip_from_paths, sanitize_filename
from Contracts.shared.pdf_utils import convert_docx_to_pdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CFS_TEMPLATE_PATH = PROJECT_ROOT / "Contracts" / "templates" / "CFS" / "AMS - CFS - REB - Template.docx"


def format_contract_date(value: datetime.date) -> str:
    """Format date as e.g. '30 June 2026' or '1 July 2026' (no leading zeros)."""
    if not value:
        return ""
    return f"{value.day} {value.strftime('%B %Y')}"


def format_contract_time(value: datetime.time) -> str:
    """Format time as e.g. '2:00 p.m.' or '5:00 p.m.' matching legal document styles."""
    if not value:
        return ""
    hour = str(value.hour % 12 or 12)
    minute = value.strftime("%M")
    ampm = "a.m." if value.hour < 12 else "p.m."
    return f"{hour}:{minute} {ampm}"


def build_contract_context(
    agreement_date: datetime.date,
    contractor_name: str,
    nric: str,
    residential_address: str,
    start_date: datetime.date,
    end_date: datetime.date,
    service_start_time: datetime.time,
    service_end_time: datetime.time,
    service_fee: float,
) -> dict:
    """Build the dictionary of values to render into the contract template."""
    return {
        "agreement_date": format_contract_date(agreement_date),
        "contractor_name": contractor_name.strip().upper(),
        "nric": nric.strip().upper(),
        "residential_address": residential_address.strip(),
        "start_date": format_contract_date(start_date),
        "end_date": format_contract_date(end_date),
        "service_start_time": format_contract_time(service_start_time),
        "service_end_time": format_contract_time(service_end_time),
        "service_fee": f"{service_fee:.2f}",
    }


def generate_cfs_docx(context: dict, template_path: Path = CFS_TEMPLATE_PATH) -> BytesIO:
    """Render the CFS Word template and return the file bytes in memory."""
    if not template_path.exists():
        raise FileNotFoundError("The base contract template file could not be found.")

    output = BytesIO()
    template = DocxTemplate(str(template_path))
    template.render(context)
    template.save(output)
    output.seek(0)
    return output


def ensure_no_unresolved_placeholders(docx_bytes: bytes) -> None:
    """Fail fast if rendered DOCX XML still contains Jinja markers."""
    with zipfile.ZipFile(BytesIO(docx_bytes)) as docx_zip:
        for name in docx_zip.namelist():
            if not name.endswith(".xml"):
                continue
            xml = docx_zip.read(name).decode("utf-8", errors="ignore")
            if "{{" in xml or "{%" in xml or "{#" in xml:
                raise RuntimeError("Rendered contract still contains unresolved template placeholders.")


def generate_cfs_pdf(data: dict, output_path: Path | None = None) -> bytes:
    """Render one CFS contract and return PDF bytes."""
    with tempfile.TemporaryDirectory(prefix="ams_cfs_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        docx_path = temp_dir / "contract.docx"
        pdf_path = output_path or temp_dir / "contract.pdf"
        docx_bytes = generate_cfs_docx(data).getvalue()
        ensure_no_unresolved_placeholders(docx_bytes)
        docx_path.write_bytes(docx_bytes)
        convert_docx_to_pdf(docx_path, pdf_path)
        return pdf_path.read_bytes()


def build_bulk_contract_zip(
    contractors: pd.DataFrame,
    agreement_date: datetime.date,
    start_date: datetime.date,
    end_date: datetime.date,
    service_start_time: datetime.time,
    service_end_time: datetime.time,
    service_fee: float,
    progress,
) -> bytes:
    total = len(contractors)

    with tempfile.TemporaryDirectory(prefix="ams_contracts_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        pdf_paths = []

        for position, (row_index, contractor) in enumerate(contractors.iterrows(), start=1):
            progress.progress((position - 1) / total, text=f"Generating contract {position} of {total}")
            context = build_contract_context(
                agreement_date=agreement_date,
                contractor_name=contractor["Full Name"],
                nric=contractor["NRIC"],
                residential_address=contractor["Residential Address"],
                start_date=start_date,
                end_date=end_date,
                service_start_time=service_start_time,
                service_end_time=service_end_time,
                service_fee=service_fee,
            )

            docx_bytes = generate_cfs_docx(context).getvalue()
            ensure_no_unresolved_placeholders(docx_bytes)

            safe_name = sanitize_filename(contractor["Full Name"])
            docx_path = temp_dir / f"contract_{position}.docx"
            pdf_filename = f"AMS - CFS - REB - {safe_name}.pdf"
            pdf_path = temp_dir / f"contract_{position}.pdf"
            docx_path.write_bytes(docx_bytes)

            try:
                convert_docx_to_pdf(docx_path, pdf_path)
            except Exception as exc:
                raise RuntimeError(f"Row {row_index + 1} failed during PDF generation: {exc}") from exc

            pdf_paths.append((pdf_path, pdf_filename))
            progress.progress(position / total, text=f"Generating contract {position} of {total}")

        return create_zip_from_paths(pdf_paths)
