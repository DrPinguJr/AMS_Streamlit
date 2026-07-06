import re
import datetime
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from io import BytesIO
import pandas as pd
import streamlit as st
from docxtpl import DocxTemplate

# Ensure page configuration is set (if not already set by app.py)
try:
    st.set_page_config(page_title="Contract Generator", layout="wide")
except st.errors.StreamlitAPIException:
    pass

# Helper to locate template file robustly
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "templates" / "contracts" / "AMS - CFS - REB - Template.docx"

# Form state helper callback
def clear_generated_contract():
    """Callback to clear cached contract bytes when form fields change to prevent outdated downloads."""
    if "contract_gen_bytes" in st.session_state:
        del st.session_state["contract_gen_bytes"]
    if "contract_gen_filename" in st.session_state:
        del st.session_state["contract_gen_filename"]

def clear_bulk_contracts():
    """Clear cached bulk ZIP output when bulk inputs change."""
    st.session_state.pop("bulk_contract_gen_zip_bytes", None)
    st.session_state.pop("bulk_contract_gen_zip_filename", None)

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

def sanitize_filename(name: str, replacement: str = " ") -> str:
    """Sanitize a display name so it is safe as a single filename segment."""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, str(name))
    sanitized = re.sub(r"\.\.+", replacement, sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.strip(" .")
    return sanitized or "Contractor"

def sanitize_filename_for_legacy_docx(name: str) -> str:
    """Preserve the existing individual DOCX underscore filename style."""
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\s]', '', str(name))
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized.strip('_')

def build_contract_context(
    agreement_date: datetime.date,
    contractor_name: str,
    nric: str,
    residential_address: str,
    start_date: datetime.date,
    end_date: datetime.date,
    service_start_time: datetime.time,
    service_end_time: datetime.time,
    service_fee: float
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
        "service_fee": f"{service_fee:.2f}"
    }

def generate_contract(template_path: Path, context: dict) -> BytesIO:
    """Render the Word template and return the file bytes in-memory."""
    if not template_path.exists():
        raise FileNotFoundError("The base contract template file could not be found.")
    
    output = BytesIO()
    template = DocxTemplate(str(template_path))
    template.render(context)
    template.save(output)
    output.seek(0)
    return output

def convert_docx_to_pdf(input_path: Path, output_path: Path) -> None:
    """Convert a DOCX file to PDF using Microsoft Word or LibreOffice."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import win32com.client  # type: ignore

        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        document = None
        try:
            document = word.Documents.Open(str(input_path.resolve()))
            document.SaveAs(str(output_path.resolve()), FileFormat=17)
        finally:
            if document is not None:
                document.Close(False)
            word.Quit()
    except Exception as word_error:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            raise RuntimeError(
                "PDF conversion requires Microsoft Word or LibreOffice on this machine."
            ) from word_error

        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_path.parent),
                str(input_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        converted_path = output_path.parent / f"{input_path.stem}.pdf"
        if result.returncode != 0 or not converted_path.exists():
            message = result.stderr.strip() or result.stdout.strip() or "LibreOffice conversion failed."
            raise RuntimeError(message) from word_error
        if converted_path != output_path:
            converted_path.replace(output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("PDF conversion did not produce a valid file.")

def ensure_no_unresolved_placeholders(docx_bytes: bytes) -> None:
    """Fail fast if rendered DOCX XML still contains Jinja markers."""
    with zipfile.ZipFile(BytesIO(docx_bytes)) as docx_zip:
        for name in docx_zip.namelist():
            if not name.endswith(".xml"):
                continue
            xml = docx_zip.read(name).decode("utf-8", errors="ignore")
            if "{{" in xml or "{%" in xml or "{#" in xml:
                raise RuntimeError("Rendered contract still contains unresolved template placeholders.")

def initial_bulk_contractors() -> pd.DataFrame:
    return pd.DataFrame(
        [{"Full Name": "", "NRIC": "", "Residential Address": ""} for _ in range(10)]
    )

def clean_bulk_contractors(data: object) -> pd.DataFrame:
    columns = ["Full Name", "NRIC", "Residential Address"]
    df = pd.DataFrame(data if data is not None else [], columns=columns)
    df = df.reindex(columns=columns)
    df = df.fillna("").astype(str)
    for column in columns:
        df[column] = df[column].str.strip()
    return df[~(df[columns] == "").all(axis=1)].copy()

def validate_bulk_contractors(contractors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    errors = []
    valid_indexes = set(contractors.index)

    for idx, row in contractors.iterrows():
        missing = [field for field in ["Full Name", "NRIC", "Residential Address"] if not row[field]]
        if missing:
            errors.append(
                {
                    "Row Number": idx + 1,
                    "Full Name": row["Full Name"],
                    "Issue": f"Missing {', '.join(missing)}.",
                }
            )
            valid_indexes.discard(idx)

    complete_contractors = contractors[
        (contractors["Full Name"] != "")
        & (contractors["NRIC"] != "")
        & (contractors["Residential Address"] != "")
    ]
    duplicate_mask = complete_contractors.assign(
        _full_name=complete_contractors["Full Name"].str.casefold().str.replace(r"\s+", " ", regex=True),
        _nric=complete_contractors["NRIC"].str.casefold().str.replace(r"\s+", "", regex=True),
    ).duplicated(subset=["_full_name", "_nric"], keep=False)

    for idx, row in complete_contractors[duplicate_mask].iterrows():
        errors.append(
            {
                "Row Number": idx + 1,
                "Full Name": row["Full Name"],
                "Issue": "Duplicate contractor with the same Full Name and NRIC.",
            }
        )
        valid_indexes.discard(idx)

    valid_contractors = contractors.loc[sorted(valid_indexes)].copy()
    return valid_contractors, pd.DataFrame(errors, columns=["Row Number", "Full Name", "Issue"])

def validate_bulk_shared_terms(
    agreement_date: datetime.date,
    start_date: datetime.date,
    end_date: datetime.date,
    service_start_time: datetime.time,
    service_end_time: datetime.time,
    service_fee: float,
) -> list[str]:
    errors = []
    if not agreement_date:
        errors.append("Agreement Date is required.")
    if not start_date:
        errors.append("Service Start Date is required.")
    if not end_date:
        errors.append("Service End Date is required.")
    if not service_start_time:
        errors.append("Service Start Time is required.")
    if not service_end_time:
        errors.append("Service End Time is required.")
    if start_date and end_date and end_date < start_date:
        errors.append("Service End Date cannot be earlier than Service Start Date.")
    if service_fee is None or service_fee <= 0:
        errors.append("Service Fee Per Completed Job must be greater than zero.")
    return errors

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
    zip_buffer = BytesIO()
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

            docx_bytes = generate_contract(TEMPLATE_PATH, context).getvalue()
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

        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for pdf_path, pdf_filename in pdf_paths:
                zip_file.write(pdf_path, arcname=pdf_filename)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

# Injected CSS for premium aesthetics matching the platform
st.markdown(
    """
    <style>
    .contract-title {
        background: linear-gradient(135deg, #1e90ff 0%, #ff1493 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2.8rem;
        font-weight: 800;
        margin-bottom: 0.1rem;
    }
    .contract-subtitle {
        font-size: 1.1rem;
        color: gray;
        margin-bottom: 1.5rem;
    }
    .section-title {
        font-size: 1.25rem;
        font-weight: 600;
        margin-bottom: 1rem;
        color: #1e90ff;
        border-bottom: 1px solid rgba(128, 128, 128, 0.2);
        padding-bottom: 0.3rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<div class="contract-title">Contract Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="contract-subtitle">Generate individual Contract for Service documents for vehicle rebalancing contractors.</div>', unsafe_allow_html=True)

def render_individual_contract_generator() -> None:
    # Main container for form layout
    with st.container(border=True):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown('<div class="section-title">SECTION 1 — Contractor Details</div>', unsafe_allow_html=True)
            contractor_name = st.text_input(
                "Contractor Full Name",
                placeholder="e.g. Name Middle Name Surname",
                key="c_name",
                on_change=clear_generated_contract
            )
            
            nric = st.text_input(
                "NRIC",
                placeholder="e.g. T0000000A",
                key="c_nric",
                on_change=clear_generated_contract
            )
            
            residential_address = st.text_area(
                "Residential Address",
                placeholder="e.g. Blk [Block Number] [Street Name], #[Floor]-[Unit], Singapore [Postal Code]",
                key="c_address",
                on_change=clear_generated_contract,
                height=100
            )
            
            st.markdown('<div class="section-title">SECTION 3 — Service Terms</div>', unsafe_allow_html=True)
            time_cols = st.columns(2)
            with time_cols[0]:
                service_start_time = st.time_input(
                    "Service Start Time",
                    value=datetime.time(14, 0),
                    key="c_start_time",
                    on_change=clear_generated_contract
                )
            with time_cols[1]:
                service_end_time = st.time_input(
                    "Service End Time",
                    value=datetime.time(17, 0),
                    key="c_end_time",
                    on_change=clear_generated_contract
                )
                
            service_fee = st.number_input(
                "Service Fee Per Completed Job (SGD)",
                min_value=0.0,
                value=20.00,
                step=0.50,
                format="%.2f",
                key="c_fee",
                on_change=clear_generated_contract
            )
    
        with col2:
            st.markdown('<div class="section-title">SECTION 2 — Contract Period</div>', unsafe_allow_html=True)
            agreement_date = st.date_input(
                "Agreement Date",
                value=datetime.date.today(),
                key="c_agreement_date",
                on_change=clear_generated_contract
            )
            
            start_date = st.date_input(
                "Service Start Date",
                value=datetime.date.today(),
                key="c_start_date",
                on_change=clear_generated_contract
            )
            
            end_date = st.date_input(
                "Service End Date",
                value=datetime.date.today() + datetime.timedelta(days=30),
                key="c_end_date",
                on_change=clear_generated_contract
            )
            
            st.markdown('<div class="section-title">Actions & Verification</div>', unsafe_allow_html=True)
            st.write("Ensure all details are correct. Generating a contract will render a printable Word (.docx) document instantly in memory.")
            
            # Validation checks
            validation_error = None
            if not contractor_name.strip():
                validation_error = "Contractor Full Name cannot be blank."
            elif not nric.strip():
                validation_error = "NRIC cannot be blank."
            elif not residential_address.strip():
                validation_error = "Residential Address cannot be blank."
            elif end_date < start_date:
                validation_error = "Service End Date cannot be earlier than Service Start Date."
            elif service_fee < 0.0:
                validation_error = "Service Fee must be a positive number."
    
            # Generate Button
            if st.button("Generate Contract", type="primary", use_container_width=True):
                if validation_error:
                    st.error(validation_error)
                else:
                    try:
                        # In-memory generation
                        context = build_contract_context(
                            agreement_date=agreement_date,
                            contractor_name=contractor_name,
                            nric=nric,
                            residential_address=residential_address,
                            start_date=start_date,
                            end_date=end_date,
                            service_start_time=service_start_time,
                            service_end_time=service_end_time,
                            service_fee=service_fee
                        )
                        
                        # Generate the document into a BytesIO stream
                        output = generate_contract(TEMPLATE_PATH, context)
                        
                        # Prepare file name
                        sanitized_name = sanitize_filename_for_legacy_docx(contractor_name)
                        start_date_str = start_date.strftime("%Y-%m-%d")
                        filename = f"CFS_{sanitized_name}_{start_date_str}.docx"
                        
                        # Save to session state
                        st.session_state["contract_gen_bytes"] = output.getvalue()
                        st.session_state["contract_gen_filename"] = filename
                        
                        st.success("Contract generated successfully! Click the button below to download the file.")
                    except Exception as e:
                        # Generic clean user error without full traceback exposure
                        st.error(f"Failed to generate contract: {str(e)}")
    
            # Display download button if document is generated in memory
            if "contract_gen_bytes" in st.session_state:
                st.download_button(
                    label="📥 Download Generated Contract",
                    data=st.session_state["contract_gen_bytes"],
                    file_name=st.session_state["contract_gen_filename"],
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )

def render_bulk_contract_generator() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title">Contractors</div>', unsafe_allow_html=True)
        st.caption("Paste rows copied from Google Sheets or Excel into the first cell under Full Name.")

        edited_contractors = st.data_editor(
            initial_bulk_contractors(),
            key="bulk_contract_gen_contractors",
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            on_change=clear_bulk_contracts,
            column_config={
                "Full Name": st.column_config.TextColumn("Full Name", required=False),
                "NRIC": st.column_config.TextColumn("NRIC", required=False),
                "Residential Address": st.column_config.TextColumn("Residential Address", required=False),
            },
        )

        st.markdown('<div class="section-title">Shared Contract Terms</div>', unsafe_allow_html=True)
        date_cols = st.columns(3)
        with date_cols[0]:
            bulk_agreement_date = st.date_input(
                "Agreement Date",
                value=datetime.date.today(),
                key="bulk_contract_gen_agreement_date",
                on_change=clear_bulk_contracts,
            )
        with date_cols[1]:
            bulk_start_date = st.date_input(
                "Service Start Date",
                value=datetime.date.today(),
                key="bulk_contract_gen_start_date",
                on_change=clear_bulk_contracts,
            )
        with date_cols[2]:
            bulk_end_date = st.date_input(
                "Service End Date",
                value=datetime.date.today() + datetime.timedelta(days=30),
                key="bulk_contract_gen_end_date",
                on_change=clear_bulk_contracts,
            )

        term_cols = st.columns(3)
        with term_cols[0]:
            bulk_service_start_time = st.time_input(
                "Service Start Time",
                value=datetime.time(14, 0),
                key="bulk_contract_gen_start_time",
                on_change=clear_bulk_contracts,
            )
        with term_cols[1]:
            bulk_service_end_time = st.time_input(
                "Service End Time",
                value=datetime.time(17, 0),
                key="bulk_contract_gen_end_time",
                on_change=clear_bulk_contracts,
            )
        with term_cols[2]:
            bulk_service_fee = st.number_input(
                "Service Fee Per Completed Job",
                min_value=0.0,
                value=20.00,
                step=0.50,
                format="%.2f",
                key="bulk_contract_gen_fee",
                on_change=clear_bulk_contracts,
            )

        contractors = clean_bulk_contractors(edited_contractors)
        valid_contractors, row_errors = validate_bulk_contractors(contractors)
        shared_errors = validate_bulk_shared_terms(
            agreement_date=bulk_agreement_date,
            start_date=bulk_start_date,
            end_date=bulk_end_date,
            service_start_time=bulk_service_start_time,
            service_end_time=bulk_service_end_time,
            service_fee=bulk_service_fee,
        )
        has_errors = not row_errors.empty or bool(shared_errors)
        ready_count = len(valid_contractors) if not has_errors else 0

        summary_cols = st.columns(2)
        summary_cols[0].metric("Contractors ready", ready_count)
        summary_cols[1].metric("Rows with errors", len(row_errors))

        if shared_errors:
            for issue in shared_errors:
                st.error(issue)

        if row_errors.empty:
            st.success(f"{ready_count} contractors ready\n\n0 rows with errors")
        else:
            st.warning(f"{ready_count} contractors ready\n\n{len(row_errors)} rows need attention")
            st.dataframe(row_errors, hide_index=True, use_container_width=True)

        generate_disabled = has_errors or contractors.empty
        if contractors.empty:
            st.info("Paste at least one contractor row to generate bulk PDF contracts.")

        if st.button(
            f"Generate {ready_count} PDF Contracts",
            type="primary",
            use_container_width=True,
            disabled=generate_disabled,
        ):
            clear_bulk_contracts()
            progress = st.progress(0, text=f"Generating contract 0 of {len(valid_contractors)}")
            try:
                zip_bytes = build_bulk_contract_zip(
                    contractors=valid_contractors,
                    agreement_date=bulk_agreement_date,
                    start_date=bulk_start_date,
                    end_date=bulk_end_date,
                    service_start_time=bulk_service_start_time,
                    service_end_time=bulk_service_end_time,
                    service_fee=bulk_service_fee,
                    progress=progress,
                )
                st.session_state["bulk_contract_gen_zip_bytes"] = zip_bytes
                st.session_state["bulk_contract_gen_zip_filename"] = "AMS - CFS - REB - Contracts.zip"
                progress.progress(1.0, text=f"Generated {len(valid_contractors)} PDF contracts")
                st.success("Bulk PDF contracts generated successfully.")
            except Exception as exc:
                clear_bulk_contracts()
                progress.empty()
                st.error(f"Bulk generation stopped. {exc}")

        if "bulk_contract_gen_zip_bytes" in st.session_state:
            st.download_button(
                "Download All PDF Contracts",
                data=st.session_state["bulk_contract_gen_zip_bytes"],
                file_name=st.session_state["bulk_contract_gen_zip_filename"],
                mime="application/zip",
                use_container_width=True,
            )

mode = st.radio(
    "Contract generation mode",
    ["Individual Contract", "Paste Multiple Contractors"],
    horizontal=True,
    key="contract_gen_mode",
)

if mode == "Individual Contract":
    render_individual_contract_generator()
else:
    render_bulk_contract_generator()
