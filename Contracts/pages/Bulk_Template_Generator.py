"""Bulk Template Generator: pick any {{ placeholder }} Word template and mass-generate PDFs."""

import datetime
import hashlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from Contracts.generators.dynamic_generator import (
    FIELD_TYPES,
    TYPE_DATE,
    TYPE_MONEY,
    TYPE_TIME,
    FieldSetting,
    blank_rows,
    build_dynamic_bulk_batch,
    build_row_contexts,
    build_shared_context,
    default_date_for,
    default_filename_pattern,
    default_settings,
    library_label,
    list_library_templates,
    match_uploaded_columns,
    per_row_settings,
    post_processor_for,
    render_filename,
    validate_filename_pattern,
)
from Contracts.shared.batch_utils import normalize_dataframe
from Contracts.shared.pdf_utils import get_pdf_converter_status
from Contracts.shared.template_lint import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    PreparedTemplate,
    prepare_template,
)

try:
    st.set_page_config(page_title="Bulk Template Generator", layout="wide")
except st.errors.StreamlitAPIException:
    pass

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
    .contract-subtitle { font-size: 1.1rem; color: gray; margin-bottom: 1.5rem; }
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
    unsafe_allow_html=True,
)

st.markdown('<div class="contract-title">Bulk Template Generator</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="contract-subtitle">Pick any Word template with {{ placeholders }}, '
    "fill the fields, and generate a ZIP of PDF contracts.</div>",
    unsafe_allow_html=True,
)


def section(title: str) -> None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=32)
def cached_prepare(template_bytes: bytes, keep_ids: tuple[str, ...]) -> PreparedTemplate:
    return prepare_template(template_bytes, keep_ids)


def read_uploaded_rows(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded, dtype=str, keep_default_na=False)
    return pd.read_excel(uploaded, dtype=str)


# --------------------------------------------------------------------------- #
# 1. Template
# --------------------------------------------------------------------------- #

uploads: dict[str, bytes] = st.session_state.setdefault("dyn_uploaded_templates", {})

with st.container(border=True):
    section("1 · Choose a template")
    uploaded_template = st.file_uploader("Upload a new template (.docx)", type=["docx"], key="dyn_template_upload")
    if uploaded_template is not None:
        upload_label = f"Uploaded: {uploaded_template.name}"
        if st.session_state.get("dyn_last_upload_id") != uploaded_template.file_id:
            uploads[upload_label] = uploaded_template.getvalue()
            st.session_state["dyn_last_upload_id"] = uploaded_template.file_id
            st.session_state["dyn_template_choice"] = upload_label

    library = {library_label(path): path for path in list_library_templates()}
    options = list(library) + list(uploads)
    if not options:
        st.info("No templates found. Upload a .docx with {{ placeholders }} to begin.")
        st.stop()
    if st.session_state.get("dyn_template_choice") not in options:
        st.session_state.pop("dyn_template_choice", None)

    choice = st.selectbox("Template", options, key="dyn_template_choice")
    st.caption(
        "Uploaded templates only last for this session. To keep one permanently, "
        "commit the .docx into `Contracts/templates/<Folder>/` and it will appear here."
    )

if choice in library:
    template_bytes = library[choice].read_bytes()
    template_filename = library[choice].name
else:
    template_bytes = uploads[choice]
    template_filename = choice.removeprefix("Uploaded: ")

template_id = hashlib.sha1(template_bytes).hexdigest()[:12]
post_processor = post_processor_for(template_filename)

# --------------------------------------------------------------------------- #
# 2. Template check
# --------------------------------------------------------------------------- #

try:
    base_scan = cached_prepare(template_bytes, ())
except Exception as exc:
    st.error(f"This file could not be opened as a Word template: {type(exc).__name__}: {exc}")
    st.stop()

keepable: dict[str, str] = {}
for issue in base_scan.issues:
    if not issue.can_keep:
        continue
    label = f"{issue.found_text}  —  {issue.location}"
    while label in keepable:
        label += " "
    keepable[label] = issue.issue_id

with st.container(border=True):
    section("2 · Template check")
    keep_labels = []
    if keepable:
        keep_labels = st.multiselect(
            "Not an error: keep these exactly as written",
            list(keepable),
            key=f"dyn_keep_{template_id}",
            help=(
                "Use this when something was flagged by mistake. A valid field such as "
                "{{ Name }} keeps its own spelling; broken text is printed exactly as typed."
            ),
        )
    kept_ids = tuple(sorted(keepable[label] for label in keep_labels))
    prepared = cached_prepare(template_bytes, kept_ids)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Fields found", len(prepared.fields))
    metric_cols[1].metric("🔴 Errors", prepared.count(SEVERITY_ERROR))
    metric_cols[2].metric("🟡 Warnings", prepared.count(SEVERITY_WARNING))
    metric_cols[3].metric("🔵 Info", prepared.count(SEVERITY_INFO))

    needs_review = prepared.count(SEVERITY_ERROR) + prepared.count(SEVERITY_WARNING) > 0
    if not prepared.issues:
        st.success("No problems found: every placeholder is a clean {{ field_name }}.")
    else:
        st.dataframe(
            pd.DataFrame([issue.as_dict() for issue in prepared.issues]),
            hide_index=True,
            width="stretch",
        )
        report = pd.DataFrame(
            [
                {
                    "Template": template_filename,
                    "Checked At": datetime.datetime.now().isoformat(timespec="seconds"),
                    **issue.as_dict(),
                }
                for issue in prepared.issues
            ]
        )
        st.download_button(
            "Download issue report (CSV)",
            data=report.to_csv(index=False).encode("utf-8"),
            file_name=f"{Path(template_filename).stem} - Template Issues.csv",
            mime="text/csv",
            help="Send this file in if something was flagged by mistake.",
        )

    for issue in prepared.blocking_issues:
        st.error(f"#{issue.number} {issue.found_text} ({issue.location}): {issue.problem}. {issue.action}")

    acknowledged = True
    if needs_review:
        acknowledged = st.checkbox(
            "I've checked the list above and it looks right",
            key=f"dyn_ack_{template_id}_{'-'.join(kept_ids)}",
        )

if not prepared.fields:
    st.warning("This template has no {{ fields }} to fill.")
    st.stop()

# --------------------------------------------------------------------------- #
# 3. Fields
# --------------------------------------------------------------------------- #

defaults = default_settings(prepared.fields)
fields_signature = hashlib.sha1("|".join(f.name for f in prepared.fields).encode()).hexdigest()[:8]

with st.container(border=True):
    section("3 · Fields")
    st.caption(
        "Same for all = one value for the whole batch. Untick it to make the field a column "
        "in the rows table. Types are guessed from the name and can be changed."
    )
    field_table = pd.DataFrame(
        [
            {
                "Field": setting.label,
                "In template as": ", ".join(f.spellings),
                "Type": setting.field_type,
                "Same for all": setting.shared,
                "Required": setting.required,
            }
            for setting, f in zip(defaults, prepared.fields)
        ],
        index=[setting.name for setting in defaults],
    )
    edited_fields = st.data_editor(
        field_table,
        key=f"dyn_fields_{template_id}_{fields_signature}",
        hide_index=True,
        width="stretch",
        disabled=["Field", "In template as"],
        column_config={
            "Type": st.column_config.SelectboxColumn("Type", options=list(FIELD_TYPES), required=True),
            "Same for all": st.column_config.CheckboxColumn("Same for all"),
            "Required": st.column_config.CheckboxColumn("Required"),
        },
    )

settings = [
    FieldSetting(
        name=setting.name,
        label=setting.label,
        field_type=str(edited_fields.loc[setting.name, "Type"] or setting.field_type),
        shared=bool(edited_fields.loc[setting.name, "Same for all"]),
        required=bool(edited_fields.loc[setting.name, "Required"]),
    )
    for setting in defaults
]
settings_key = hashlib.sha1(
    repr([(s.name, s.field_type, s.shared) for s in settings]).encode()
).hexdigest()[:8]

# --------------------------------------------------------------------------- #
# 4. Same-for-all values
# --------------------------------------------------------------------------- #

shared_values: dict[str, object] = {}
shared_settings = [setting for setting in settings if setting.shared]
if shared_settings:
    with st.container(border=True):
        section("4 · Same for every contract")
        columns = st.columns(3)
        for position, setting in enumerate(shared_settings):
            key = f"dyn_shared_{template_id}_{setting.name}_{setting.field_type}"
            label = setting.label + ("" if setting.required else " (optional)")
            with columns[position % 3]:
                if setting.field_type == TYPE_DATE:
                    shared_values[setting.name] = st.date_input(
                        label, value=default_date_for(setting.name), key=key, format="DD/MM/YYYY"
                    )
                elif setting.field_type == TYPE_TIME:
                    shared_values[setting.name] = st.time_input(label, value=None, key=key)
                elif setting.field_type == TYPE_MONEY:
                    shared_values[setting.name] = st.number_input(
                        label, value=None, min_value=0.0, step=0.5, format="%.2f", key=key
                    )
                else:
                    shared_values[setting.name] = st.text_input(label, key=key)

shared_context, shared_errors = build_shared_context(settings, shared_values)

# --------------------------------------------------------------------------- #
# 5. Rows
# --------------------------------------------------------------------------- #

row_settings = per_row_settings(settings)
row_labels = [setting.label for setting in row_settings]

with st.container(border=True):
    section("5 · One row per contract")
    if not row_settings:
        st.info("Every field is 'Same for all'. Untick at least one field in step 3 to add rows.")
        st.stop()

    st.download_button(
        "Download blank CSV with the right columns",
        data=pd.DataFrame(columns=row_labels).to_csv(index=False).encode("utf-8"),
        file_name=f"{Path(template_filename).stem} - Rows.csv",
        mime="text/csv",
    )
    source = st.radio(
        "How do you want to add rows?",
        ["Paste into a table", "Upload CSV / Excel"],
        horizontal=True,
        key=f"dyn_row_source_{template_id}",
    )

    initial_rows = blank_rows(settings)
    source_id = "paste"
    if source == "Upload CSV / Excel":
        rows_file = st.file_uploader(
            "Rows file (.csv or .xlsx)", type=["csv", "xlsx", "xls"], key=f"dyn_rows_upload_{template_id}"
        )
        if rows_file is not None:
            try:
                initial_rows, unmatched, missing = match_uploaded_columns(read_uploaded_rows(rows_file), settings)
                source_id = rows_file.file_id
                if unmatched:
                    st.info(f"Ignored columns that don't match any field: {', '.join(unmatched)}")
                if missing:
                    st.warning(f"No column found for: {', '.join(missing)}. You can fill them in below.")
            except Exception as exc:
                st.error(f"The rows file could not be read: {type(exc).__name__}: {exc}")
    st.caption("Paste rows copied from Google Sheets or Excel into the first cell, or edit the uploaded rows.")

    edited_rows = st.data_editor(
        initial_rows,
        key=f"dyn_rows_{template_id}_{settings_key}_{source_id}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={label: st.column_config.TextColumn(label) for label in row_labels},
    )
    rows = normalize_dataframe(edited_rows, row_labels).reset_index(drop=True)
    ready_rows, row_errors = build_row_contexts(rows, settings, shared_context)

    summary = st.columns(2)
    summary[0].metric("Contracts ready", len(ready_rows))
    summary[1].metric("Rows with errors", len(row_errors))
    if not row_errors.empty:
        st.warning(f"{len(row_errors)} rows with errors will be skipped.")
        st.dataframe(row_errors, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- #
# 6. Generate
# --------------------------------------------------------------------------- #

with st.container(border=True):
    section("6 · Generate PDFs")
    pattern = st.text_input(
        "File name pattern",
        value=default_filename_pattern(template_filename, settings),
        key=f"dyn_filename_{template_id}",
        help="Use {{ Field }} to insert a value, e.g. AMS - CFS - {{ contractor_name }}",
    )
    pattern_errors = validate_filename_pattern(pattern, settings)
    if ready_rows and not pattern_errors:
        st.caption(f"Example: {render_filename(pattern, ready_rows[0].context, settings)}")
    if post_processor is not None:
        st.caption("This template's own page-layout rules will be applied.")

    for issue in shared_errors + pattern_errors:
        st.error(issue)

    converter_status = get_pdf_converter_status()
    if not converter_status.available:
        st.error(converter_status.error)
    if not converter_status.available or os.getenv("PDF_CONVERTER_DEBUG", "").strip().casefold() in {"1", "true", "yes", "on"}:
        with st.expander("PDF converter diagnostics", expanded=False):
            st.write(f"Available: {'Yes' if converter_status.available else 'No'}")
            st.write(f"Converter: {converter_status.converter}")
            st.write(f"Executable: {converter_status.executable or 'Not found'}")
            if converter_status.error:
                st.write(f"Diagnostic: {converter_status.error}")

    blockers = []
    if prepared.blocking_issues:
        blockers.append("Fix or keep the red template errors in step 2.")
    elif not acknowledged:
        blockers.append("Tick 'looks right' in step 2.")
    if not ready_rows:
        blockers.append("Add at least one complete row in step 5.")
    for blocker in blockers:
        st.info(blocker)

    signature = hashlib.sha256(
        repr(
            (
                template_id,
                kept_ids,
                settings,
                sorted(shared_context.items()),
                [sorted(row.context.items()) for row in ready_rows],
                pattern,
            )
        ).encode()
    ).hexdigest()

    disabled = bool(blockers or shared_errors or pattern_errors or not converter_status.available)
    if st.button(f"Generate {len(ready_rows)} PDF Contracts", type="primary", width="stretch", disabled=disabled):
        st.session_state.pop("dyn_result", None)
        progress = st.progress(0, text=f"Generating contract 0 of {len(ready_rows)}")
        try:
            result = build_dynamic_bulk_batch(
                prepared,
                ready_rows,
                pattern,
                settings,
                progress=progress,
                post_processor=post_processor,
            )
            st.session_state["dyn_result"] = {
                "signature": signature,
                "zip": result.zip_bytes,
                "success": result.successful_count,
                "failures": [failure.as_dict() for failure in result.failures],
                "zip_name": f"{Path(template_filename).stem} - Contracts.zip",
            }
            if result.zip_bytes is None:
                progress.empty()
            else:
                progress.progress(1.0, text=f"Generated {result.successful_count} PDF contracts")
        except Exception as exc:
            progress.empty()
            st.error(f"Bulk generation could not prepare a download: {type(exc).__name__}: {exc}")

    result_state = st.session_state.get("dyn_result")
    if result_state and result_state["signature"] == signature:
        failures = result_state["failures"]
        if result_state["zip"] is None:
            st.error("No PDF contracts were generated. See the failed rows below.")
        elif not failures:
            st.success(f"{result_state['success']} PDF contracts generated.")
        if failures:
            st.warning(f"{result_state['success']} succeeded and {len(failures)} failed.")
            with st.expander("Failed rows", expanded=True):
                st.dataframe(failures, hide_index=True, width="stretch")
        if result_state["zip"] is not None:
            st.download_button(
                "Download All PDF Contracts",
                data=result_state["zip"],
                file_name=result_state["zip_name"],
                mime="application/zip",
                width="stretch",
            )
    elif result_state:
        st.caption("Inputs changed since the last run. Generate again to download.")
