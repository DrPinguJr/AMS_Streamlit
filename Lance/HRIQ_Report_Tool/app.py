from __future__ import annotations

import streamlit as st

from Lance.HRIQ_Report_Tool.config.settings import get_settings
from Lance.HRIQ_Report_Tool.services.log_service import configure_logging
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary
from Lance.HRIQ_Report_Tool.ui.components import apply_compact_style
from Lance.HRIQ_Report_Tool.ui.download_page import render_download
from Lance.HRIQ_Report_Tool.ui.reports_page import render_reports
from Lance.HRIQ_Report_Tool.ui.sql_page import render_sql


try:
    st.set_page_config(page_title="HRIQ Report Tool", layout="wide")
except st.errors.StreamlitAPIException:
    pass

settings = get_settings()
configure_logging(settings.log_dir)
library = ReportLibrary(settings.index_path)
apply_compact_style()

st.title("HRIQ Report Tool")
section = st.segmented_control(
    "Section", ["Download", "Reports", "SQL"],
    default=st.session_state.get("hriq_section", "Download"), key="hriq_section",
    label_visibility="collapsed",
)

if section == "Reports":
    render_reports(settings, library)
elif section == "SQL":
    render_sql(settings, library)
else:
    render_download(settings)
