from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import re

from docxtpl import DocxTemplate

from Contracts.shared.file_utils import sanitize_filename
from Contracts.shared.pdf_utils import convert_docx_to_pdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOA_TEMPLATE_PATH = PROJECT_ROOT / "Contracts" / "templates" / "LOA" / "gbh_loa_template.docx"

LOA_FIELDS = [
    "letter_date",
    "employee_name",
    "nric_fin",
    "address_line_1",
    "address_line_2",
    "salutation_name",
    "job_title",
    "department",
    "commencement_date",
    "basic_salary",
    "basic_salary_words",
    "mobile_allowance",
    "mobile_allowance_words",
    "probation_period",
    "probation_notice_period",
    "confirmed_notice_period",
    "supervisor_job_title",
    "primary_location",
    "weekday_hours",
    "saturday_status",
    "sunday_status",
    "lunch_time",
    "annual_leave_category",
    "annual_leave_1_to_lt5",
    "annual_leave_5_to_lt10",
    "annual_leave_10_to_lt15",
    "annual_leave_15_to_lt20",
    "annual_leave_20_plus",
    "flexi_career_category",
    "flexi_amount",
    "signatory_name",
    "signatory_job_title",
    "signatory_company",
    "entity",
    "appendix_job_title",
    "working_days_hours",
    "job_duty_1",
    "job_duty_2",
    "job_duty_3",
    "job_duty_4",
    "job_duty_5",
    "job_duty_6",
    "job_duty_7",
]

REQUIRED_LOA_FIELDS = [
    "letter_date",
    "employee_name",
    "nric_fin",
    "address_line_1",
    "salutation_name",
    "job_title",
    "department",
    "commencement_date",
    "basic_salary",
    "basic_salary_words",
    "mobile_allowance",
    "mobile_allowance_words",
    "probation_period",
    "probation_notice_period",
    "confirmed_notice_period",
    "supervisor_job_title",
    "primary_location",
    "weekday_hours",
    "saturday_status",
    "sunday_status",
    "lunch_time",
    "annual_leave_category",
    "flexi_career_category",
    "flexi_amount",
    "signatory_name",
    "signatory_job_title",
    "signatory_company",
    "entity",
    "appendix_job_title",
    "working_days_hours",
    "job_duty_1",
]


def template_exists() -> bool:
    return LOA_TEMPLATE_PATH.exists()


def get_template_placeholders(template_path: Path = LOA_TEMPLATE_PATH) -> list[str]:
    if not template_path.exists():
        return []

    with ZipFile(template_path) as archive:
        xml = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml") and name.startswith("word/")
        )
    return sorted(set(re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", xml)))


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
    if value < 1000000:
        thousands, remainder = divmod(value, 1000)
        if remainder:
            return f"{number_to_words(thousands)} thousand {number_to_words(remainder)}"
        return f"{number_to_words(thousands)} thousand"
    return str(value)


def money_to_words(value: float) -> str:
    dollars = int(round(float(value)))
    return number_to_words(dollars).title()


def build_loa_context(data: dict) -> dict:
    context = {field: str(data.get(field, "") or "").strip() for field in LOA_FIELDS}
    if data.get("basic_salary") not in [None, ""]:
        basic_salary = float(data["basic_salary"])
        context["basic_salary"] = f"{basic_salary:,.2f}"
        context["basic_salary_words"] = str(data.get("basic_salary_words") or money_to_words(basic_salary)).strip()
    if data.get("mobile_allowance") not in [None, ""]:
        mobile_allowance = float(data["mobile_allowance"])
        context["mobile_allowance"] = f"{mobile_allowance:,.2f}"
        context["mobile_allowance_words"] = str(
            data.get("mobile_allowance_words") or money_to_words(mobile_allowance)
        ).strip()
    return context


def validate_loa_context(context: dict) -> list[str]:
    template_fields = set(get_template_placeholders())
    unknown_fields = sorted(template_fields - set(LOA_FIELDS))
    missing = [field for field in REQUIRED_LOA_FIELDS if not str(context.get(field, "")).strip()]
    errors = []
    if unknown_fields:
        errors.append(f"Template contains unsupported fields: {', '.join(unknown_fields)}.")
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}.")
    return errors


def ensure_no_unresolved_placeholders(docx_bytes: bytes) -> None:
    with ZipFile(BytesIO(docx_bytes)) as docx_zip:
        xml = "\n".join(
            docx_zip.read(name).decode("utf-8", errors="ignore")
            for name in docx_zip.namelist()
            if name.endswith(".xml") and name.startswith("word/")
        )
    if "{{" in xml or "{%" in xml or "{#" in xml:
        raise RuntimeError("Rendered LOA still contains unresolved template placeholders.")


def generate_loa_docx(data: dict) -> tuple[bytes, str]:
    if not LOA_TEMPLATE_PATH.exists():
        raise FileNotFoundError("Template not found. Place gbh_loa_template.docx in Contracts/templates/LOA/.")

    context = build_loa_context(data)
    errors = validate_loa_context(context)
    if errors:
        raise ValueError(" ".join(errors))

    output = BytesIO()
    template = DocxTemplate(str(LOA_TEMPLATE_PATH))
    template.render(context)
    template.save(output)
    output.seek(0)
    docx_bytes = output.getvalue()
    ensure_no_unresolved_placeholders(docx_bytes)

    employee_name = sanitize_filename(context["employee_name"])
    return docx_bytes, f"GBH Letter of Appointment - {employee_name}.docx"


def generate_loa_pdf(data: dict) -> tuple[bytes, str]:
    docx_bytes, docx_filename = generate_loa_docx(data)
    pdf_filename = f"{Path(docx_filename).stem}.pdf"

    with TemporaryDirectory(prefix="gbh_loa_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        docx_path = temp_dir / docx_filename
        docx_path.write_bytes(docx_bytes)
        pdf_path = convert_docx_to_pdf(docx_path, temp_dir)
        return pdf_path.read_bytes(), pdf_filename
