"""Shared, deployment-safe Streamlit router for the BlueSG tools."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

from Flexar.BlueSG.cloud_access_control import require_cloud_access
from Flexar.BlueSG.cloud_deployment_preflight import check_deployment_imports


BLUESG_DIRECTORY = Path(__file__).resolve().parent
OPTIMISER_PAGE = BLUESG_DIRECTORY / "pages" / "create_optimised_vehicle_routes_page.py"
PLANNER_PAGE = (
    BLUESG_DIRECTORY
    / "pages"
    / "review_map_and_manually_adjust_route_assignments_page.py"
)
DEPLOYMENT_GUARD_VERSION = "2026.08.03.1"


def _stop_for_preflight_failures() -> None:
    failures = check_deployment_imports()
    if not failures:
        return

    st.error("The BlueSG deployment did not pass its startup checks.")
    st.caption(
        "The complete exception is in Manage app -> Cloud logs. The checks below "
        "identify the dependency or source-module area that needs attention."
    )
    for failure in failures:
        st.code(
            f"{failure.error_type}: {failure.display_detail}",
            language="text",
        )
    st.stop()


def run_bluesg_cloud_app() -> None:
    """Configure and run the authenticated BlueSG-only application."""

    st.set_page_config(
        page_title="BlueSG Route Optimiser",
        page_icon=":material/route:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    require_cloud_access()
    _stop_for_preflight_failures()

    st.sidebar.caption("BlueSG operations")
    st.sidebar.info(
        "Cloud storage is temporary. Download completed workbooks and roster "
        "changes before a reboot or redeployment."
    )
    st.sidebar.caption(
        f"Deployment guard {DEPLOYMENT_GUARD_VERSION} - Python "
        f"{sys.version_info.major}.{sys.version_info.minor}"
    )

    optimiser_page = st.Page(
        OPTIMISER_PAGE,
        title="Create optimised routes",
        icon=":material/route:",
        url_path="optimise",
        default=True,
    )
    planner_page = st.Page(
        PLANNER_PAGE,
        title="Review and adjust routes",
        icon=":material/edit_road:",
        url_path="review",
    )

    st.navigation(
        {
            "BlueSG route tools": [
                optimiser_page,
                planner_page,
            ]
        }
    ).run()
