from __future__ import annotations

from pathlib import Path

import streamlit as st

from Lance.HRIQ_Report_Tool.config.settings import Settings
from Lance.HRIQ_Report_Tool.query_engine.executor import execute_query
from Lance.HRIQ_Report_Tool.query_engine.safety import UnsafeQueryError, detect_parameters
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary


def render_sql(settings: Settings, library: ReportLibrary) -> None:
    st.subheader("SQL")
    entries = library.sql_entries()
    labels = {
        f"{item['report_name']} — {item['dataset_name']}": item for item in entries
    }
    selector = st.columns([4, 1])
    selected = selector[0].selectbox("Report SQL", ["Select report SQL..."] + list(labels))
    if selector[1].button("Load SQL", disabled=selected not in labels, width="stretch"):
        item = labels[selected]
        loaded_sql = (settings.parsed_dir / Path(item["sql_path"])).read_text(
            encoding="utf-8"
        )
        st.session_state.hriq_sql_editor = loaded_sql
        st.session_state.hriq_sql_editor_widget = loaded_sql
        st.rerun()

    sql = st.text_area(
        "SQL editor", value=st.session_state.get("hriq_sql_editor", ""),
        height=300, key="hriq_sql_editor_widget",
    )
    st.session_state.hriq_sql_editor = sql
    parameter_names = detect_parameters(sql)
    parameters = {}
    if parameter_names:
        st.caption("Parameters")
        columns = st.columns(min(3, len(parameter_names)))
        for index, name in enumerate(parameter_names):
            parameters[name] = columns[index % len(columns)].text_input(name, key=f"hriq_param_{name}")

    run_col, clear_col, status_col = st.columns([1, 1, 4])
    if not settings.database_configured:
        status_col.info("Database not configured")
    if clear_col.button("Clear", width="stretch"):
        st.session_state.hriq_sql_editor = ""
        st.session_state.hriq_sql_editor_widget = ""
        st.session_state.pop("hriq_query_result", None)
        st.rerun()
    if run_col.button("Run", type="primary", disabled=not settings.database_configured, width="stretch"):
        try:
            result = execute_query(sql, parameters, settings)
            st.session_state.hriq_query_result = result
            log = st.session_state.setdefault("hriq_query_log", [])
            log.append(f"OK • {len(result.data)} rows • {result.elapsed_seconds:.2f}s")
        except (UnsafeQueryError, ValueError, RuntimeError) as exc:
            st.error(str(exc))
            st.session_state.setdefault("hriq_query_log", []).append(f"ERROR • {exc}")
        except Exception as exc:
            del exc
            st.error("Query failed. Check the database settings and SQL, then try again.")
            st.session_state.setdefault("hriq_query_log", []).append("ERROR • Query execution failed")

    result = st.session_state.get("hriq_query_result")
    if result:
        info = f"{len(result.data)} rows • {result.elapsed_seconds:.2f}s"
        if result.truncated:
            info += f" • limited to {settings.sql_row_limit}"
        st.caption(info)
        st.dataframe(result.data, hide_index=True, width="stretch")
        st.download_button(
            "Download CSV", result.data.to_csv(index=False).encode("utf-8-sig"),
            "hriq_query_results.csv", "text/csv",
        )
    with st.expander("Query log"):
        st.code("\n".join(st.session_state.get("hriq_query_log", [])[-50:]) or "No queries run.")
