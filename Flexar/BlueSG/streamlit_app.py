"""Dedicated Streamlit Community Cloud entry point for BlueSG."""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = BASE_DIR.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from Flexar.BlueSG.cloud_streamlit_router import run_bluesg_cloud_app


run_bluesg_cloud_app()
