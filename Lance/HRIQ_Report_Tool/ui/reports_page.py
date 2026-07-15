from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from Lance.HRIQ_Report_Tool.config.settings import Settings
from Lance.HRIQ_Report_Tool.parser.batch_parser import parse_new_or_changed, parse_zip_new_or_changed
from Lance.HRIQ_Report_Tool.parser.sources import ZipLimits, ZipRdlSource
from Lance.HRIQ_Report_Tool.services.archive_service import stage_uploaded_zip
from Lance.HRIQ_Report_Tool.services.cache_service import clear_file_cache
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary


def _search_cached(library: ReportLibrary, query: str) -> list[dict]:
    version = st.session_state.get("hriq_library_version", 0)
    key = (version, query.casefold().strip())
    cache = st.session_state.setdefault("hriq_report_search_cache", {})
    if key not in cache:
        cache.clear()
        cache[key] = library.search(query)
    return cache[key]


def _limits(settings: Settings) -> ZipLimits:
    return ZipLimits(
        max_entries=settings.zip_max_entries,
        max_rdl_size_bytes=settings.zip_max_rdl_size_mb * 1024 * 1024,
        max_total_uncompressed_bytes=settings.zip_max_total_uncompressed_mb * 1024 * 1024,
        max_compression_ratio=settings.zip_max_compression_ratio,
    )


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _selected_zip(settings: Settings, upload, selected_name: str | None) -> Path | None:
    if upload is not None:
        return stage_uploaded_zip(upload.getvalue(), upload.name, settings.archive_dir)
    if selected_name:
        candidate = settings.archive_dir / selected_name
        if candidate.is_file() and candidate.suffix.casefold() == ".zip":
            return candidate
    staged = st.session_state.get("hriq_staged_zip")
    return Path(staged) if staged else None


def _report_summary(summary) -> None:
    if summary.errors:
        st.warning(f"Parsed {summary.parsed}; skipped {summary.skipped}; errors {len(summary.errors)}.")
        for error in summary.errors[:20]:
            st.error(error)
    else:
        st.success(
            f"Found {summary.found}; parsed {summary.parsed}; skipped {summary.skipped}; removed {summary.removed}."
        )


def render_reports(settings: Settings, library: ReportLibrary) -> None:
    st.subheader("Reports")
    source_mode = st.segmented_control("Source", ["RDL Folder", "ZIP Archive"], default="RDL Folder")
    zip_path: Path | None = None
    upload = None
    selected_archive = None
    if source_mode == "ZIP Archive":
        archives = sorted(settings.archive_dir.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        source_controls = st.columns(2)
        selected_archive = source_controls[0].selectbox(
            "Archive", [path.name for path in archives], index=None, placeholder="Select an existing ZIP",
        )
        upload = source_controls[1].file_uploader("Upload ZIP", type=["zip"], accept_multiple_files=False)
        actions = st.columns([1, 1, 6])
        if actions[0].button("Inspect", width="stretch"):
            try:
                zip_path = _selected_zip(settings, upload, selected_archive)
                if zip_path is None:
                    st.warning("Select or upload a ZIP archive.")
                else:
                    inspection = ZipRdlSource(zip_path, _limits(settings)).inspect()
                    st.session_state.hriq_staged_zip = str(zip_path)
                    st.session_state.hriq_zip_inspection = inspection
            except Exception as exc:
                st.error(f"ZIP validation failed: {exc}")
        if actions[1].button("Parse", type="primary", width="stretch"):
            try:
                zip_path = _selected_zip(settings, upload, selected_archive)
                if zip_path is None:
                    st.warning("Select or upload a ZIP archive.")
                else:
                    with st.spinner("Parsing changed RDL members directly from ZIP..."):
                        summary = parse_zip_new_or_changed(
                            zip_path, settings.parsed_dir, library, limits=_limits(settings),
                        )
                    st.session_state.hriq_staged_zip = str(zip_path)
                    _report_summary(summary)
                    st.session_state.hriq_library_version = st.session_state.get("hriq_library_version", 0) + 1
                    st.session_state.pop("hriq_report_search_cache", None)
            except Exception as exc:
                st.error(f"ZIP parsing failed: {exc}")
        inspection = st.session_state.get("hriq_zip_inspection")
        if inspection:
            st.caption(
                f"{inspection.archive_name} · RDLs: {inspection.rdl_count} · Folders: {inspection.folder_count} · "
                f"Uncompressed: {_format_bytes(inspection.total_uncompressed_bytes)} · "
                f"Manifest: {'present' if inspection.manifest_present else 'absent'} · "
                f"Validation: {'valid' if inspection.valid else 'invalid'}"
            )
            for warning in inspection.warnings[:5]:
                st.warning(warning)
    else:
        if st.button("Parse Changes", type="primary"):
            with st.spinner("Checking RDL files..."):
                summary = parse_new_or_changed(settings.raw_rdl_dir, settings.parsed_dir, library)
            _report_summary(summary)
            st.session_state.hriq_library_version = st.session_state.get("hriq_library_version", 0) + 1
            st.session_state.pop("hriq_report_search_cache", None)

    search_controls = st.columns([5, 1])
    search = search_controls[0].text_input("Search", placeholder="Report name or folder", label_visibility="collapsed")
    if search_controls[1].button("Refresh", width="stretch"):
        st.session_state.hriq_library_version = st.session_state.get("hriq_library_version", 0) + 1
        st.session_state.pop("hriq_report_search_cache", None)
        clear_file_cache()
        st.rerun()

    reports = _search_cached(library, search)
    if not reports:
        st.info("No indexed reports. Select Parse Changes.")
        return
    st.dataframe(
        pd.DataFrame([
            {
                "Report": item["report_name"], "Datasets": item["dataset_count"],
                "Fields": item["field_count"], "Source": item["source_path"],
                "Source type": item.get("source_type", "directory"), "Last parsed": item["parsed_at"],
            } for item in reports
        ]),
        hide_index=True, width="stretch",
    )
    labels = {f"{item['report_name']} — {item['source_path']}": item["source_path"] for item in reports}
    selected_label = st.selectbox("Report", list(labels))
    report = library.get_report(labels[selected_label])
    if not report:
        return
    dataset_names = [item["dataset_name"] for item in report["datasets"]]
    dataset_name = st.selectbox("Dataset", dataset_names) if dataset_names else None
    dataset = next((item for item in report["datasets"] if item["dataset_name"] == dataset_name), None)

    details = st.columns(4)
    details[0].metric("Datasets", len(report["datasets"]))
    details[1].metric("Fields", len(dataset["fields"]) if dataset else 0)
    details[2].metric("Query parameters", len(dataset["query_parameters"]) if dataset else 0)
    details[3].metric("Report parameters", len(report["report_parameters"]))
    st.caption(
        f"Source: {report['source_path']} · Type: {report.get('source_type', 'directory')} · Last parsed: {report['parsed_at']}"
    )

    if report["warnings"]:
        st.warning("; ".join(report["warnings"]))
    if dataset:
        left, right = st.columns(2)
        with left:
            st.markdown("**Fields**")
            st.dataframe(pd.DataFrame(dataset["fields"]), hide_index=True, width="stretch")
        with right:
            st.markdown("**Parameters**")
            combined = dataset["query_parameters"] + report["report_parameters"]
            st.dataframe(pd.DataFrame(combined), hide_index=True, width="stretch")
        if dataset.get("sql_path") and st.button("Load SQL", type="primary"):
            sql_path = settings.parsed_dir / Path(dataset["sql_path"])
            loaded_sql = sql_path.read_text(encoding="utf-8")
            st.session_state.hriq_sql_editor = loaded_sql
            st.session_state.hriq_sql_editor_widget = loaded_sql
            st.session_state.hriq_section = "SQL"
            st.rerun()
