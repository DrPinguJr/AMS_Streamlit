import os
import re
import datetime
from pathlib import Path
from io import BytesIO
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

def sanitize_filename(name: str) -> str:
    """Sanitize the contractor name to be safe for a filename."""
    # Keep only alphanumeric characters, spaces, hyphens, and underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\s]', '', name)
    # Replace spaces and multiple whitespace sequences with underscores
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

# Main container for form layout
with st.container(border=True):
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="section-title">SECTION 1 — Contractor Details</div>', unsafe_allow_html=True)
        contractor_name = st.text_input(
            "Contractor Full Name",
            placeholder="e.g. LIM CHOON YONG LESTER",
            key="c_name",
            on_change=clear_generated_contract
        )
        
        nric = st.text_input(
            "NRIC",
            placeholder="e.g. S1234567A",
            key="c_nric",
            on_change=clear_generated_contract
        )
        
        residential_address = st.text_area(
            "Residential Address",
            placeholder="e.g. Blk 123 Test Road, #01-01, Singapore 123123",
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
                    sanitized_name = sanitize_filename(contractor_name)
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
