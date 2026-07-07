from __future__ import annotations

from pathlib import Path
from io import BytesIO
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import re

from docxtpl import DocxTemplate

from Contracts.shared.file_utils import sanitize_filename
from Contracts.shared.pdf_utils import convert_docx_to_pdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_AGREEMENT_TEMPLATE_PATH = (
    PROJECT_ROOT
    / "Contracts"
    / "templates"
    / "Service_Agreement"
    / "permanent_placement_service_agreement_template.docx"
)


def template_exists() -> bool:
    return SERVICE_AGREEMENT_TEMPLATE_PATH.exists()


SERVICE_AGREEMENT_FIELDS = [
    "client_name",
    "client_address",
    "client_uen",
    "effective_date",
    "payment_terms_days_words",
    "payment_terms_days",
    "candidate_protection_months_words",
    "candidate_protection_months",
    "replacement_request_days_words",
    "replacement_request_days",
    "replacement_search_months_words",
    "replacement_search_months",
    "termination_notice_days_words",
    "termination_notice_days",
    "post_termination_months_words",
    "post_termination_months",
    "fee_band_1_salary",
    "fee_band_1_fee",
    "fee_band_1_guarantee",
    "fee_band_2_salary",
    "fee_band_2_fee",
    "fee_band_2_guarantee",
    "fee_band_3_salary",
    "fee_band_3_fee",
    "fee_band_3_guarantee",
    "fee_band_4_salary",
    "fee_band_4_fee",
    "fee_band_4_guarantee",
    "agency_signatory_name",
    "agency_signatory_title",
    "client_signatory_name",
    "client_signatory_title",
    "signing_date",
]


def number_to_words(value: int) -> str:
    words = {
        0: "zero",
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
        13: "thirteen",
        14: "fourteen",
        15: "fifteen",
        16: "sixteen",
        17: "seventeen",
        18: "eighteen",
        19: "nineteen",
        20: "twenty",
        30: "thirty",
        40: "forty",
        50: "fifty",
        60: "sixty",
        70: "seventy",
        80: "eighty",
        90: "ninety",
    }
    if value in words:
        return words[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        return f"{words[tens * 10]}-{words[ones]}"
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        if remainder:
            return f"{words[hundreds]} hundred and {number_to_words(remainder)}"
        return f"{words[hundreds]} hundred"
    return str(value)


def build_service_agreement_context(data: dict) -> dict:
    context = {field: str(data.get(field, "") or "").strip() for field in SERVICE_AGREEMENT_FIELDS}
    for field in [
        "payment_terms_days",
        "candidate_protection_months",
        "replacement_request_days",
        "replacement_search_months",
        "termination_notice_days",
        "post_termination_months",
    ]:
        number = int(data.get(field) or 0)
        context[field] = str(number)
        context[f"{field}_words"] = number_to_words(number)
    return context


def get_template_placeholders(template_path: Path = SERVICE_AGREEMENT_TEMPLATE_PATH) -> list[str]:
    if not template_path.exists():
        return []

    with ZipFile(template_path) as archive:
        xml = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml") and name.startswith("word/")
        )
    return sorted(set(re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", xml)))


def validate_service_agreement_context(context: dict) -> list[str]:
    missing = [field for field in SERVICE_AGREEMENT_FIELDS if not str(context.get(field, "")).strip()]
    template_fields = set(get_template_placeholders())
    unknown_fields = sorted(template_fields - set(SERVICE_AGREEMENT_FIELDS))
    errors = []
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}.")
    if unknown_fields:
        errors.append(f"Template contains unsupported fields: {', '.join(unknown_fields)}.")
    return errors


def generate_service_agreement_docx(data: dict) -> tuple[bytes, str]:
    if not SERVICE_AGREEMENT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            "Template not found. Place permanent_placement_service_agreement_template.docx "
            "in Contracts/templates/Service_Agreement/."
        )

    context = build_service_agreement_context(data)
    errors = validate_service_agreement_context(context)
    if errors:
        raise ValueError(" ".join(errors))

    output = BytesIO()
    template = DocxTemplate(str(SERVICE_AGREEMENT_TEMPLATE_PATH))
    template.render(context)
    template.save(output)
    output.seek(0)

    client_name = sanitize_filename(context["client_name"])
    return output.getvalue(), f"Permanent Placement Service Agreement - {client_name}.docx"


def generate_service_agreement_pdf(data: dict) -> tuple[bytes, str]:
    docx_bytes, docx_filename = generate_service_agreement_docx(data)
    pdf_filename = f"{Path(docx_filename).stem}.pdf"

    with TemporaryDirectory(prefix="service_agreement_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        docx_path = temp_dir / docx_filename
        pdf_path = temp_dir / pdf_filename
        docx_path.write_bytes(docx_bytes)
        convert_docx_to_pdf(docx_path, pdf_path)
        return pdf_path.read_bytes(), pdf_filename
