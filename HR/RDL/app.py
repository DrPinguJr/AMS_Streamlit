from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from HR.RDL.rdl_editor import update_textbox_values
from HR.RDL.rdl_parser import parse_rdl
from HR.RDL.rdl_storage import (
    ensure_directories,
    list_uploaded_reports,
    load_json,
    parsed_json_path,
    save_json,
    save_uploaded_rdl,
)


try:
    st.set_page_config(page_title="RDL Management Studio", layout="wide")
except st.errors.StreamlitAPIException:
    pass


ensure_directories()

st.title("RDL Management Studio")
st.caption("Upload SSRS RDL files, inspect their report structure, and safely edit textbox values.")


def parse_and_store_rdl(rdl_file) -> tuple[str, bool, str]:
    rdl_path = save_uploaded_rdl(rdl_file)
    try:
        parsed = parse_rdl(rdl_path)
        save_json(parsed["report_name"], parsed)
        return rdl_file.name, True, "Parsed successfully."
    except Exception as exc:
        return rdl_file.name, False, f"Could not parse this RDL file. {exc}"


with st.container(border=True):
    st.subheader("Upload RDL Files")
    uploaded_files = st.file_uploader(
        "Choose one or more .rdl files",
        type=["rdl"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        results = [parse_and_store_rdl(file) for file in uploaded_files]
        for filename, ok, message in results:
            if ok:
                st.success(f"{filename}: {message}")
            else:
                st.error(f"{filename}: {message}")


reports = list_uploaded_reports()

st.subheader("Uploaded Reports")
if not reports:
    st.info("No RDL files uploaded yet.")
    st.stop()

dashboard = pd.DataFrame(
    [
        {
            "Report": report["report_name"],
            "File": report["file_name"],
            "Parsed JSON": "Yes" if report["parsed"] else "No",
            "Size KB": report["size_kb"],
            "Modified": dt.datetime.fromtimestamp(report["modified"]).strftime("%Y-%m-%d %H:%M"),
        }
        for report in reports
    ]
)
st.dataframe(dashboard, hide_index=True, use_container_width=True)

report_names = [report["report_name"] for report in reports]
selected_report = st.selectbox("Select an RDL file", report_names)

if not parsed_json_path(selected_report).exists():
    st.warning("This RDL has not been parsed yet. Re-upload it or check whether the XML is valid.")
    st.stop()

try:
    parsed_json = load_json(selected_report)
except Exception as exc:
    st.error(f"Could not load parsed JSON for {selected_report}. {exc}")
    st.stop()

st.divider()
st.subheader(selected_report)

summary_cols = st.columns(4)
summary_cols[0].metric("Textboxes", len(parsed_json.get("textboxes", [])))
summary_cols[1].metric("Datasets", len(parsed_json.get("datasets", [])))
summary_cols[2].metric("Parameters", len(parsed_json.get("parameters", [])))
summary_cols[3].metric("Namespace", "Detected" if parsed_json.get("namespace") else "None")

tab_textboxes, tab_datasets, tab_parameters, tab_json = st.tabs(
    ["Textboxes", "Datasets", "Report Parameters", "JSON"]
)

with tab_textboxes:
    textboxes = parsed_json.get("textboxes", [])
    if not textboxes:
        st.info("No textboxes were found in this report.")
    else:
        editable_textboxes = []
        for index, textbox in enumerate(textboxes):
            with st.container(border=True):
                label = textbox.get("name") or f"Textbox {index + 1}"
                st.markdown(f"**{label}**")
                edited_value = st.text_area(
                    "Value",
                    value=textbox.get("value", ""),
                    key=f"rdl_textbox_{selected_report}_{index}",
                    height=110,
                )
                editable_textbox = dict(textbox)
                editable_textbox["value"] = edited_value
                editable_textboxes.append(editable_textbox)

        if st.button("Save Textbox Edits", type="primary", use_container_width=True):
            try:
                json_path, version_path, edited_path = update_textbox_values(
                    selected_report,
                    editable_textboxes,
                )
                st.success(
                    "Textbox edits saved. The original RDL remains untouched, "
                    f"and a version copy was created at {version_path}."
                )
                st.caption(f"Updated JSON: {json_path}")
                st.caption(f"Edited RDL copy: {edited_path}")
            except Exception as exc:
                st.error(f"Could not save textbox edits. {exc}")

with tab_datasets:
    datasets = parsed_json.get("datasets", [])
    if not datasets:
        st.info("No datasets were found in this report.")
    else:
        for dataset in datasets:
            with st.container(border=True):
                st.markdown(f"**{dataset.get('name') or 'Unnamed dataset'}**")
                cols = st.columns(2)
                cols[0].write(f"Data source: `{dataset.get('data_source_name') or 'Not specified'}`")
                cols[1].write(f"Command type: `{dataset.get('command_type') or 'Text'}`")
                command_text = dataset.get("command_text") or ""
                if command_text:
                    st.code(command_text, language="sql")
                else:
                    st.caption("No SQL command text found for this dataset.")

with tab_parameters:
    parameters = parsed_json.get("parameters", [])
    if not parameters:
        st.info("No report parameters were found in this report.")
    else:
        st.dataframe(
            pd.DataFrame(parameters)[["name", "data_type", "nullable", "allow_blank", "prompt"]],
            hide_index=True,
            use_container_width=True,
        )

with tab_json:
    st.json(parsed_json, expanded=False)
