"""Importable registration point for the Route Planner custom component."""

from pathlib import Path

import streamlit.components.v1 as components


ROUTE_BOARD_COMPONENT = components.declare_component(
    "route_planner_assignment_board",
    path=str(Path(__file__).resolve().parent / "route_board_component"),
)
