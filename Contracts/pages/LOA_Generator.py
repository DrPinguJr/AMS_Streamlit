import streamlit as st

from Contracts.generators.loa_generator import (
    LOA_TEMPLATE_PATH,
    generate_loa_docx,
    generate_loa_pdf,
    get_template_placeholders,
    template_exists,
)


try:
    st.set_page_config(page_title="Letter of Appointment", layout="wide")
except st.errors.StreamlitAPIException:
    pass


st.title("GB Helios Letter of Appointment")
st.caption("Generate GB Helios Letter of Appointment documents from the DOCX template.")

if template_exists():
    st.success("Template found.")
else:
    st.warning("Template not found. Place gbh_loa_template.docx in Contracts/templates/LOA/.")

st.code(str(LOA_TEMPLATE_PATH), language="text")

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
        "loa_docx_bytes",
        "loa_docx_filename",
        "loa_pdf_bytes",
        "loa_pdf_filename",
    ]:
        st.session_state.pop(key, None)


def collect_form_data() -> dict:
    duties = st.session_state.get("loa_job_duties", [])
    if hasattr(duties, "to_dict"):
        duties = duties.to_dict("records")
    duty_values = []
    for row in duties:
        if isinstance(row, dict):
            duty_values.append(str(row.get("Duty", "") or "").strip())
        else:
            duty_values.append(str(row or "").strip())
    duty_values = (duty_values + [""] * 7)[:7]

    return {
        "letter_date": format_contract_date(st.session_state["loa_letter_date"]),
        "employee_name": st.session_state["loa_employee_name"],
        "nric_fin": st.session_state["loa_nric_fin"],
        "address_line_1": st.session_state["loa_address_line_1"],
        "address_line_2": st.session_state["loa_address_line_2"],
        "salutation_name": st.session_state["loa_salutation_name"],
        "job_title": st.session_state["loa_job_title"],
        "department": st.session_state["loa_department"],
        "commencement_date": format_contract_date(st.session_state["loa_commencement_date"]),
        "basic_salary": st.session_state["loa_basic_salary"],
        "basic_salary_words": st.session_state["loa_basic_salary_words"],
        "mobile_allowance": st.session_state["loa_mobile_allowance"],
        "mobile_allowance_words": st.session_state["loa_mobile_allowance_words"],
        "probation_period": st.session_state["loa_probation_period"],
        "probation_notice_period": st.session_state["loa_probation_notice_period"],
        "confirmed_notice_period": st.session_state["loa_confirmed_notice_period"],
        "supervisor_job_title": st.session_state["loa_supervisor_job_title"],
        "primary_location": st.session_state["loa_primary_location"],
        "weekday_hours": st.session_state["loa_weekday_hours"],
        "saturday_status": st.session_state["loa_saturday_status"],
        "sunday_status": st.session_state["loa_sunday_status"],
        "lunch_time": st.session_state["loa_lunch_time"],
        "annual_leave_category": st.session_state["loa_annual_leave_category"],
        "annual_leave_1_to_lt5": st.session_state["loa_annual_leave_1_to_lt5"],
        "annual_leave_5_to_lt10": st.session_state["loa_annual_leave_5_to_lt10"],
        "annual_leave_10_to_lt15": st.session_state["loa_annual_leave_10_to_lt15"],
        "annual_leave_15_to_lt20": st.session_state["loa_annual_leave_15_to_lt20"],
        "annual_leave_20_plus": st.session_state["loa_annual_leave_20_plus"],
        "flexi_career_category": st.session_state["loa_flexi_career_category"],
        "flexi_amount": st.session_state["loa_flexi_amount"],
        "signatory_name": st.session_state["loa_signatory_name"],
        "signatory_job_title": st.session_state["loa_signatory_job_title"],
        "signatory_company": st.session_state["loa_signatory_company"],
        "entity": st.session_state["loa_entity"],
        "appendix_job_title": st.session_state["loa_appendix_job_title"],
        "working_days_hours": st.session_state["loa_working_days_hours"],
        "job_duty_1": duty_values[0],
        "job_duty_2": duty_values[1],
        "job_duty_3": duty_values[2],
        "job_duty_4": duty_values[3],
        "job_duty_5": duty_values[4],
        "job_duty_6": duty_values[5],
        "job_duty_7": duty_values[6],
    }


manual_tab, batch_tab = st.tabs(["Manual Entry", "Batch / Paste"])
with manual_tab:
    employee_col, appointment_col = st.columns(2)
    with employee_col:
        st.subheader("Employee")
        st.date_input("Letter Date", key="loa_letter_date", on_change=clear_generated_outputs)
        st.text_input("Employee Name", key="loa_employee_name", on_change=clear_generated_outputs)
        st.text_input("NRIC / FIN", key="loa_nric_fin", on_change=clear_generated_outputs)
        st.text_input("Address Line 1", key="loa_address_line_1", on_change=clear_generated_outputs)
        st.text_input("Address Line 2", key="loa_address_line_2", on_change=clear_generated_outputs)
        st.text_input("Salutation Name", key="loa_salutation_name", on_change=clear_generated_outputs)

    with appointment_col:
        st.subheader("Appointment")
        st.text_input("Job Title", key="loa_job_title", on_change=clear_generated_outputs)
        st.text_input("Department", key="loa_department", on_change=clear_generated_outputs)
        st.date_input("Commencement Date", key="loa_commencement_date", on_change=clear_generated_outputs)
        st.text_input("Supervisor Job Title", key="loa_supervisor_job_title", on_change=clear_generated_outputs)
        st.text_input("Entity", value="GB Helios Pte Ltd", key="loa_entity", on_change=clear_generated_outputs)

    remuneration_col, terms_col = st.columns(2)
    with remuneration_col:
        st.subheader("Remuneration")
        st.number_input("Basic Salary", min_value=0.0, value=0.0, step=100.0, format="%.2f", key="loa_basic_salary", on_change=clear_generated_outputs)
        st.text_input("Basic Salary Words", key="loa_basic_salary_words", help="Leave blank to auto-fill from the amount.", on_change=clear_generated_outputs)
        st.number_input("Mobile Allowance", min_value=0.0, value=60.0, step=10.0, format="%.2f", key="loa_mobile_allowance", on_change=clear_generated_outputs)
        st.text_input("Mobile Allowance Words", value="Sixty", key="loa_mobile_allowance_words", on_change=clear_generated_outputs)
        st.text_input("Flexi Career Category", value="Executive", key="loa_flexi_career_category", on_change=clear_generated_outputs)
        st.text_input("Flexi Amount", value="S$800", key="loa_flexi_amount", on_change=clear_generated_outputs)

    with terms_col:
        st.subheader("Terms")
        st.text_input("Probation Period", value="six (6) months", key="loa_probation_period", on_change=clear_generated_outputs)
        st.text_input("Probation Notice Period", value="two (2) weeks", key="loa_probation_notice_period", on_change=clear_generated_outputs)
        st.text_input("Confirmed Notice Period", value="one (1) month", key="loa_confirmed_notice_period", on_change=clear_generated_outputs)
        st.text_input("Primary Location", value="47 Scotts Road #12-01/02 Goldbell Towers Singapore 228233", key="loa_primary_location", on_change=clear_generated_outputs)
        st.text_input("Weekday Hours", value="8:30 am to 5:30 pm", key="loa_weekday_hours", on_change=clear_generated_outputs)
        st.text_input("Saturday Status", value="Off Day", key="loa_saturday_status", on_change=clear_generated_outputs)
        st.text_input("Sunday Status", value="Rest Day", key="loa_sunday_status", on_change=clear_generated_outputs)
        st.text_input("Lunch Time", value="12:30 pm to 1:15 pm", key="loa_lunch_time", on_change=clear_generated_outputs)

    st.subheader("Annual Leave")
    leave_cols = st.columns(3)
    leave_cols[0].text_input("Annual Leave Category", value="Executive/Senior Executive", key="loa_annual_leave_category", on_change=clear_generated_outputs)
    leave_cols[1].text_input("1 to less than 5 years", value="14 working days", key="loa_annual_leave_1_to_lt5", on_change=clear_generated_outputs)
    leave_cols[2].text_input("5 to less than 10 years", value="16 working days", key="loa_annual_leave_5_to_lt10", on_change=clear_generated_outputs)
    leave_cols = st.columns(3)
    leave_cols[0].text_input("10 to less than 15 years", value="17 working days", key="loa_annual_leave_10_to_lt15", on_change=clear_generated_outputs)
    leave_cols[1].text_input("15 to less than 20 years", value="18 working days", key="loa_annual_leave_15_to_lt20", on_change=clear_generated_outputs)
    leave_cols[2].text_input("20 years and above", value="19 working days", key="loa_annual_leave_20_plus", on_change=clear_generated_outputs)

    st.subheader("Signatory and Appendix")
    sign_col, appendix_col = st.columns(2)
    with sign_col:
        st.text_input("Signatory Name", key="loa_signatory_name", on_change=clear_generated_outputs)
        st.text_input("Signatory Job Title", key="loa_signatory_job_title", on_change=clear_generated_outputs)
        st.text_input("Signatory Company", value="GB Helios Pte Ltd", key="loa_signatory_company", on_change=clear_generated_outputs)
    with appendix_col:
        st.text_input("Appendix Job Title", key="loa_appendix_job_title", on_change=clear_generated_outputs)
        st.text_input("Working Days / Hours", value="5 days, Monday to Friday: 8:30 am to 5:30 pm", key="loa_working_days_hours", on_change=clear_generated_outputs)

    st.subheader("Job Duties")
    st.data_editor(
        [{"Duty": ""} for _ in range(7)],
        key="loa_job_duties",
        num_rows="fixed",
        hide_index=True,
        use_container_width=True,
        on_change=clear_generated_outputs,
        column_config={"Duty": st.column_config.TextColumn("Duty", required=False)},
    )

    generate_col, pdf_col = st.columns(2)
    with generate_col:
        if st.button("Generate DOCX", type="primary", use_container_width=True):
            try:
                docx_bytes, filename = generate_loa_docx(collect_form_data())
                st.session_state["loa_docx_bytes"] = docx_bytes
                st.session_state["loa_docx_filename"] = filename
                st.success("DOCX generated successfully.")
            except Exception as exc:
                st.error(f"Failed to generate DOCX: {exc}")

    with pdf_col:
        if st.button("Generate PDF", use_container_width=True):
            try:
                pdf_bytes, filename = generate_loa_pdf(collect_form_data())
                st.session_state["loa_pdf_bytes"] = pdf_bytes
                st.session_state["loa_pdf_filename"] = filename
                st.success("PDF generated successfully.")
            except Exception as exc:
                st.error(f"Failed to generate PDF: {exc}")

    if "loa_docx_bytes" in st.session_state:
        st.download_button(
            "Download DOCX",
            data=st.session_state["loa_docx_bytes"],
            file_name=st.session_state["loa_docx_filename"],
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    if "loa_pdf_bytes" in st.session_state:
        st.download_button(
            "Download PDF",
            data=st.session_state["loa_pdf_bytes"],
            file_name=st.session_state["loa_pdf_filename"],
            mime="application/pdf",
            use_container_width=True,
        )

with batch_tab:
    st.info("Batch generation can be added after confirming the final LOA spreadsheet columns.")
