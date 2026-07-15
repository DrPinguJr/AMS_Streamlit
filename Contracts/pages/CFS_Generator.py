import datetime
import os

import pandas as pd
import streamlit as st

from Contracts.generators.cfs_generator import (
    build_bulk_contract_batch,
    build_contract_context,
    end_of_month,
    generate_blank_cfs_docx,
    generate_cfs_docx,
)
from Contracts.shared.batch_utils import normalize_dataframe
from Contracts.shared.file_utils import sanitize_filename_for_legacy_docx
from Contracts.shared.pdf_utils import get_libreoffice_status

# Ensure page configuration is set (if not already set by app.py)
try:
    st.set_page_config(page_title="Contract Generator", layout="wide")
except st.errors.StreamlitAPIException:
    pass

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
    st.session_state.pop("bulk_contract_gen_failures", None)
    st.session_state.pop("bulk_contract_gen_success_count", None)


def initial_bulk_contractors() -> pd.DataFrame:
    return pd.DataFrame(
        [{"Full Name": "", "NRIC": "", "Residential Address": ""} for _ in range(10)]
    )

def clean_bulk_contractors(data: object) -> pd.DataFrame:
    columns = ["Full Name", "NRIC", "Residential Address"]
    return normalize_dataframe(data, columns)

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
                on_change=clear_generated_contract,
            )
            
            individual_end_date_options = {}
            if "c_end_date" not in st.session_state:
                individual_end_date_options["value"] = end_of_month(datetime.date.today())
            end_date = st.date_input(
                "Service End Date",
                key="c_end_date",
                on_change=clear_generated_contract,
                **individual_end_date_options,
            )
            st.caption("Defaults to the end of this month; you can select any other date.")
            
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
            if st.button("Generate Contract", type="primary", width="stretch"):
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
                        output = generate_cfs_docx(context)
                        
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
                    width="stretch"
                )

            st.divider()
            st.caption(
                "Need a paper copy to complete by hand? Download the same CFS "
                "template with writing lines in every fill-in field."
            )
            try:
                blank_contract = generate_blank_cfs_docx().getvalue()
                st.download_button(
                    label="Download Empty CFS Form",
                    data=blank_contract,
                    file_name="AMS - CFS - REB - Empty Form.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    width="stretch",
                )
            except Exception as exc:
                st.error(f"The empty CFS form could not be prepared: {exc}")

def render_bulk_contract_generator() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title">Contractors</div>', unsafe_allow_html=True)
        st.caption("Paste rows copied from Google Sheets or Excel into the first cell under Full Name.")

        edited_contractors = st.data_editor(
            initial_bulk_contractors(),
            key="bulk_contract_gen_contractors",
            num_rows="dynamic",
            width="stretch",
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
            bulk_end_date_options = {}
            if "bulk_contract_gen_end_date" not in st.session_state:
                bulk_end_date_options["value"] = end_of_month(datetime.date.today())
            bulk_end_date = st.date_input(
                "Service End Date",
                key="bulk_contract_gen_end_date",
                on_change=clear_bulk_contracts,
                **bulk_end_date_options,
            )
            st.caption("Defaults to the end of this month; you can select any other date.")

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
        ready_count = len(valid_contractors)

        summary_cols = st.columns(2)
        summary_cols[0].metric("Contractors ready", ready_count)
        summary_cols[1].metric("Rows with errors", len(row_errors))

        if shared_errors:
            for issue in shared_errors:
                st.error(issue)

        if row_errors.empty:
            st.success(f"{ready_count} contractors ready\n\n0 rows with errors")
        else:
            st.warning(
                f"{ready_count} contractors ready\n\n"
                f"{len(row_errors)} invalid rows will be skipped"
            )
            st.dataframe(row_errors, hide_index=True, width="stretch")

        converter_status = get_libreoffice_status()
        debug_converter = os.getenv("PDF_CONVERTER_DEBUG", "").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not converter_status.available:
            st.error(converter_status.error)
        if debug_converter or not converter_status.available:
            with st.expander("PDF converter diagnostics", expanded=False):
                st.write(f"Available: {'Yes' if converter_status.available else 'No'}")
                st.write(f"Executable: {converter_status.executable or 'Not found'}")
                st.write(f"Version: {converter_status.version or 'Unavailable'}")
                if converter_status.error:
                    st.write(f"Diagnostic: {converter_status.error}")

        generate_disabled = bool(shared_errors) or valid_contractors.empty or not converter_status.available
        if contractors.empty:
            st.info("Paste at least one contractor row to generate bulk PDF contracts.")
        elif valid_contractors.empty:
            st.info("Correct at least one contractor row before generating PDF contracts.")

        if st.button(
            f"Generate {ready_count} PDF Contracts",
            type="primary",
            width="stretch",
            disabled=generate_disabled,
        ):
            clear_bulk_contracts()
            progress = st.progress(0, text=f"Generating contract 0 of {len(valid_contractors)}")
            try:
                result = build_bulk_contract_batch(
                    contractors=valid_contractors,
                    agreement_date=bulk_agreement_date,
                    start_date=bulk_start_date,
                    end_date=bulk_end_date,
                    service_start_time=bulk_service_start_time,
                    service_end_time=bulk_service_end_time,
                    service_fee=bulk_service_fee,
                    progress=progress,
                )
                st.session_state["bulk_contract_gen_failures"] = [
                    failure.as_dict() for failure in result.failures
                ]
                st.session_state["bulk_contract_gen_success_count"] = result.successful_count

                if result.zip_bytes is None:
                    progress.empty()
                    st.error(
                        "No PDF contracts were generated. Review the failure summary below "
                        "and the LibreOffice diagnostics above."
                    )
                else:
                    st.session_state["bulk_contract_gen_zip_bytes"] = result.zip_bytes
                    st.session_state["bulk_contract_gen_zip_filename"] = (
                        "AMS - CFS - REB - Contracts.zip"
                    )
                    progress.progress(
                        1.0,
                        text=f"Generated {result.successful_count} PDF contracts",
                    )
                    if not result.failures:
                        st.success("Bulk PDF contracts generated successfully.")
            except Exception as exc:
                clear_bulk_contracts()
                progress.empty()
                st.error(f"Bulk generation could not prepare a download: {type(exc).__name__}: {exc}")

        generation_failures = st.session_state.get("bulk_contract_gen_failures", [])
        if generation_failures:
            success_count = st.session_state.get("bulk_contract_gen_success_count", 0)
            st.warning(
                f"PDF generation summary: {success_count} succeeded and "
                f"{len(generation_failures)} failed."
            )
            with st.expander("Failed row diagnostics", expanded=False):
                st.dataframe(generation_failures, hide_index=True, width="stretch")

        if "bulk_contract_gen_zip_bytes" in st.session_state:
            st.download_button(
                "Download All PDF Contracts",
                data=st.session_state["bulk_contract_gen_zip_bytes"],
                file_name=st.session_state["bulk_contract_gen_zip_filename"],
                mime="application/zip",
                width="stretch",
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
