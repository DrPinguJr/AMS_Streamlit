import streamlit as st

from Contracts.generators.service_agreement_generator import (
    SERVICE_AGREEMENT_TEMPLATE_PATH,
    generate_service_agreement_docx,
    generate_service_agreement_pdf,
    get_template_placeholders,
    template_exists,
)


try:
    st.set_page_config(page_title="Service Agreement", layout="wide")
except st.errors.StreamlitAPIException:
    pass


st.title("Permanent Placement Service Agreement")
st.caption("Generate AMS Permanent Placement Service Agreements from the DOCX template.")

if template_exists():
    st.success("Template found.")
else:
    st.warning(
        "Template not found. Place permanent_placement_service_agreement_template.docx "
        "in Contracts/templates/Service_Agreement/."
    )

st.code(str(SERVICE_AGREEMENT_TEMPLATE_PATH), language="text")

placeholders = get_template_placeholders()
if placeholders:
    with st.expander("Template fields", expanded=False):
        st.dataframe({"Placeholder": placeholders}, hide_index=True, use_container_width=True)


def format_contract_date(value) -> str:
    if hasattr(value, "strftime"):
        return f"{value.day} {value.strftime('%B %Y')}"
    return str(value or "")


def clear_generated_outputs() -> None:
    for key in [
        "service_agreement_docx_bytes",
        "service_agreement_docx_filename",
        "service_agreement_pdf_bytes",
        "service_agreement_pdf_filename",
    ]:
        st.session_state.pop(key, None)


def collect_form_data() -> dict:
    return {
        "client_name": st.session_state["sa_client_name"],
        "client_address": st.session_state["sa_client_address"],
        "client_uen": st.session_state["sa_client_uen"],
        "effective_date": format_contract_date(st.session_state["sa_effective_date"]),
        "payment_terms_days": st.session_state["sa_payment_terms_days"],
        "candidate_protection_months": st.session_state["sa_candidate_protection_months"],
        "replacement_request_days": st.session_state["sa_replacement_request_days"],
        "replacement_search_months": st.session_state["sa_replacement_search_months"],
        "termination_notice_days": st.session_state["sa_termination_notice_days"],
        "post_termination_months": st.session_state["sa_post_termination_months"],
        "fee_band_1_salary": st.session_state["sa_fee_band_1_salary"],
        "fee_band_1_fee": st.session_state["sa_fee_band_1_fee"],
        "fee_band_1_guarantee": st.session_state["sa_fee_band_1_guarantee"],
        "fee_band_2_salary": st.session_state["sa_fee_band_2_salary"],
        "fee_band_2_fee": st.session_state["sa_fee_band_2_fee"],
        "fee_band_2_guarantee": st.session_state["sa_fee_band_2_guarantee"],
        "fee_band_3_salary": st.session_state["sa_fee_band_3_salary"],
        "fee_band_3_fee": st.session_state["sa_fee_band_3_fee"],
        "fee_band_3_guarantee": st.session_state["sa_fee_band_3_guarantee"],
        "fee_band_4_salary": st.session_state["sa_fee_band_4_salary"],
        "fee_band_4_fee": st.session_state["sa_fee_band_4_fee"],
        "fee_band_4_guarantee": st.session_state["sa_fee_band_4_guarantee"],
        "agency_signatory_name": st.session_state["sa_agency_signatory_name"],
        "agency_signatory_title": st.session_state["sa_agency_signatory_title"],
        "client_signatory_name": st.session_state["sa_client_signatory_name"],
        "client_signatory_title": st.session_state["sa_client_signatory_title"],
        "signing_date": format_contract_date(st.session_state["sa_signing_date"]),
    }


manual_tab, batch_tab = st.tabs(["Manual Entry", "Batch / Paste"])
with manual_tab:
    client_col, terms_col = st.columns(2)
    with client_col:
        st.subheader("Client")
        st.text_input("Client Name", key="sa_client_name", on_change=clear_generated_outputs)
        st.text_area("Client Address", key="sa_client_address", on_change=clear_generated_outputs)
        st.text_input("Client UEN", key="sa_client_uen", on_change=clear_generated_outputs)
        st.date_input("Effective Date", key="sa_effective_date", on_change=clear_generated_outputs)
        st.date_input("Signing Date", key="sa_signing_date", on_change=clear_generated_outputs)

    with terms_col:
        st.subheader("Terms")
        st.number_input("Payment Terms Days", min_value=1, value=14, step=1, key="sa_payment_terms_days", on_change=clear_generated_outputs)
        st.number_input("Candidate Protection Months", min_value=1, value=12, step=1, key="sa_candidate_protection_months", on_change=clear_generated_outputs)
        st.number_input("Replacement Request Days", min_value=1, value=7, step=1, key="sa_replacement_request_days", on_change=clear_generated_outputs)
        st.number_input("Replacement Search Months", min_value=1, value=3, step=1, key="sa_replacement_search_months", on_change=clear_generated_outputs)
        st.number_input("Termination Notice Days", min_value=1, value=30, step=1, key="sa_termination_notice_days", on_change=clear_generated_outputs)
        st.number_input("Post-Termination Months", min_value=1, value=12, step=1, key="sa_post_termination_months", on_change=clear_generated_outputs)

    st.subheader("Placement Fee Bands")
    fee_defaults = [
        ("Up to S$3,000", "One month salary", "30 days"),
        ("S$3,001 to S$6,000", "One month salary", "60 days"),
        ("S$6,001 to S$10,000", "One month salary", "90 days"),
        ("Above S$10,000", "One month salary", "90 days"),
    ]
    for index, defaults in enumerate(fee_defaults, start=1):
        cols = st.columns(3)
        cols[0].text_input("Monthly Salary", value=defaults[0], key=f"sa_fee_band_{index}_salary", on_change=clear_generated_outputs)
        cols[1].text_input("Placement Fee", value=defaults[1], key=f"sa_fee_band_{index}_fee", on_change=clear_generated_outputs)
        cols[2].text_input("Guarantee", value=defaults[2], key=f"sa_fee_band_{index}_guarantee", on_change=clear_generated_outputs)

    sign_col_a, sign_col_b = st.columns(2)
    with sign_col_a:
        st.subheader("Agency Signatory")
        st.text_input("Agency Signatory Name", value="Lance", key="sa_agency_signatory_name", on_change=clear_generated_outputs)
        st.text_input("Agency Signatory Title", value="Director", key="sa_agency_signatory_title", on_change=clear_generated_outputs)
    with sign_col_b:
        st.subheader("Client Signatory")
        st.text_input("Client Signatory Name", key="sa_client_signatory_name", on_change=clear_generated_outputs)
        st.text_input("Client Signatory Title", key="sa_client_signatory_title", on_change=clear_generated_outputs)

    generate_col, pdf_col = st.columns(2)
    with generate_col:
        if st.button("Generate DOCX", type="primary", use_container_width=True):
            try:
                docx_bytes, filename = generate_service_agreement_docx(collect_form_data())
                st.session_state["service_agreement_docx_bytes"] = docx_bytes
                st.session_state["service_agreement_docx_filename"] = filename
                st.success("DOCX generated successfully.")
            except Exception as exc:
                st.error(f"Failed to generate DOCX: {exc}")

    with pdf_col:
        if st.button("Generate PDF", use_container_width=True):
            try:
                pdf_bytes, filename = generate_service_agreement_pdf(collect_form_data())
                st.session_state["service_agreement_pdf_bytes"] = pdf_bytes
                st.session_state["service_agreement_pdf_filename"] = filename
                st.success("PDF generated successfully.")
            except Exception as exc:
                st.error(f"Failed to generate PDF: {exc}")

    if "service_agreement_docx_bytes" in st.session_state:
        st.download_button(
            "Download DOCX",
            data=st.session_state["service_agreement_docx_bytes"],
            file_name=st.session_state["service_agreement_docx_filename"],
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    if "service_agreement_pdf_bytes" in st.session_state:
        st.download_button(
            "Download PDF",
            data=st.session_state["service_agreement_pdf_bytes"],
            file_name=st.session_state["service_agreement_pdf_filename"],
            mime="application/pdf",
            use_container_width=True,
        )

with batch_tab:
    st.info("Batch generation can be added after confirming the final client data columns.")
