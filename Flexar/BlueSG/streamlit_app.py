"""Dedicated Streamlit Community Cloud entry point for BlueSG."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from Flexar.BlueSG.cloud_access_control import require_cloud_access


st.set_page_config(
    page_title="BlueSG Route Optimiser",
    page_icon="🚙",
    layout="wide",
    initial_sidebar_state="expanded",
)

require_cloud_access()

st.sidebar.caption("BlueSG operations")
st.sidebar.info(
    "Cloud storage is temporary. Download completed workbooks and roster "
    "changes before a reboot or redeployment."
)

optimiser_page = st.Page(
    "pages/create_optimised_vehicle_routes_page.py",
    title="Create Optimised Routes",
    icon=":material/route:",
    url_path="optimise",
    default=True,
)
planner_page = st.Page(
    "pages/review_map_and_manually_adjust_route_assignments_page.py",
    title="Review and Adjust Routes",
    icon=":material/edit_road:",
    url_path="review",
)

st.navigation(
    {
        "BlueSG Route Tools": [
            optimiser_page,
            planner_page,
        ]
    }
).run()
