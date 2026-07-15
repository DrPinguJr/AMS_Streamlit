from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from Lance.HRIQ_Report_Tool.config.settings import Settings
from Lance.HRIQ_Report_Tool.services.archive_service import create_rdl_archive
from Lance.HRIQ_Report_Tool.services.crawl_state import CrawlStateStore
from Lance.HRIQ_Report_Tool.services.job_manager import DownloadJobManager
from Lance.HRIQ_Report_Tool.ui.components import terminal_log


AUTH_LABELS = {
    "Automatic": "automatic",
    "Current Windows session": "current windows session",
    "Interactive browser session": "interactive browser session",
    "Form login": "form login",
}


def _manager(settings: Settings) -> DownloadJobManager:
    if "hriq_download_manager" not in st.session_state:
        st.session_state.hriq_download_manager = DownloadJobManager(settings.state_path)
    return st.session_state.hriq_download_manager


def _store(settings: Settings) -> CrawlStateStore:
    return CrawlStateStore(settings.state_path)


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@st.fragment(run_every="2s")
def _status_panel(manager: DownloadJobManager) -> None:
    status = manager.snapshot()
    metrics = st.columns(4)
    metrics[0].metric("Found", status["files_found"])
    metrics[1].metric("Downloaded", status["downloaded"])
    metrics[2].metric("Skipped", status["skipped"])
    metrics[3].metric("Failed", status["errors"])
    st.caption(f"Current folder: {status['current_folder'] or 'Idle'}")
    completed = status["downloaded"] + status["skipped"] + status["errors"]
    denominator = max(status["files_found"], completed, 1)
    st.progress(min(completed / denominator, 1.0))
    terminal_log(status["logs"])


def _create_archive(settings: Settings, manager: DownloadJobManager) -> None:
    with st.spinner("Creating and verifying ZIP..."):
        result = create_rdl_archive(settings.raw_rdl_dir, settings.archive_dir)
    store = _store(settings)
    store.set_value("latest_archive", str(result.archive_path))
    store.set_value("latest_archive_result", json.dumps(asdict(result), default=str))
    manager.set_latest_archive(result.archive_path)
    st.session_state.hriq_latest_archive_result = asdict(result)
    st.success(f"Reports: {result.report_count} · Archive: {_format_bytes(result.archive_size)} · Status: Ready")


def render_download(settings: Settings) -> None:
    manager = _manager(settings)
    store = _store(settings)
    st.subheader("Download")
    portal_url = st.text_input("Portal", value=settings.portal_url, placeholder="https://server/Reports/")
    default_auth = next((label for label, value in AUTH_LABELS.items() if value == settings.auth_mode), "Automatic")
    authentication = st.selectbox("Authentication", list(AUTH_LABELS), index=list(AUTH_LABELS).index(default_auth))
    auth_mode = AUTH_LABELS[authentication]
    username = password = ""
    with st.expander("Authentication details and development controls", expanded=False):
        if auth_mode == "form login":
            credentials = st.columns(2)
            username = credentials[0].text_input("Username")
            password = credentials[1].text_input("Password", type="password")
        st.caption("Interactive login never captures or stores your password.")
        create_after = st.checkbox("Create ZIP after download", value=False)
        visible_browser = st.checkbox(
            "Visible Chrome", value=not settings.browser_headless,
            disabled=auth_mode == "interactive browser session",
        )

    status = manager.snapshot()
    buttons = st.columns(6)
    start_args = dict(
        auth_mode=auth_mode, headless=not visible_browser,
        development_mode=settings.development_mode, root_segment=settings.ssrs_root_folder,
        state_path=settings.state_path, create_zip_after=create_after,
        archive_dir=settings.archive_dir,
    )
    if buttons[0].button("Start", type="primary", disabled=status["running"], width="stretch"):
        if not portal_url.strip():
            st.error("Portal URL is required.")
        elif manager.start(portal_url.strip(), username, password, settings.raw_rdl_dir, settings.download_workers, **start_args):
            st.rerun()
    if buttons[1].button("Stop", disabled=not status["running"], width="stretch"):
        manager.stop()
    if buttons[2].button("Resume", disabled=status["running"], width="stretch"):
        if not portal_url.strip():
            st.error("Portal URL is required.")
        else:
            manager.start(portal_url.strip(), username, password, settings.raw_rdl_dir, settings.download_workers, **start_args)
            st.rerun()
    if buttons[3].button("Create ZIP", disabled=status["running"], width="stretch"):
        try:
            _create_archive(settings, manager)
        except Exception as exc:
            st.error(f"ZIP creation failed: {exc}")
    if buttons[4].button("Open Folder", width="stretch"):
        os.startfile(settings.raw_rdl_dir)  # type: ignore[attr-defined]
    if buttons[5].button("Open Archives", width="stretch"):
        os.startfile(settings.archive_dir)  # type: ignore[attr-defined]

    latest = Path(store.get_value("latest_archive")) if store.get_value("latest_archive") else None
    if latest and latest.exists():
        metadata_raw = store.get_value("latest_archive_result")
        metadata = json.loads(metadata_raw) if metadata_raw else {}
        st.caption(
            f"Reports: {metadata.get('report_count', '?')} · Archive: {_format_bytes(latest.stat().st_size)} · "
            f"Status: {metadata.get('validation_status', 'Ready')}"
        )
        with latest.open("rb") as archive_stream:
            st.download_button(
                "Download ZIP", data=archive_stream, file_name=latest.name,
                mime="application/zip", width="content",
            )

    _status_panel(manager)
    with st.expander("Diagnostics", expanded=False):
        values = {
            "Portal detected": store.get_value("portal_detected", "false"),
            "SSRS version marker": "SQL Server 2019 Reporting Services",
            "Authentication mode": store.get_value("authentication_mode", auth_mode),
            "REST API status": store.get_value("rest_status", "Not tested"),
            "REST base URL": store.get_value("rest_base_url", ""),
            "Catalog access": store.get_value("catalog_access", "false"),
            "Report-content access": store.get_value("report_content_access", "false"),
            "Local RDL path": str(settings.raw_rdl_dir),
            "Latest ZIP path": str(latest or ""),
        }
        for label, value in values.items():
            st.text(f"{label}: {value}")
