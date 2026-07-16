from __future__ import annotations

import inspect
from pathlib import Path

import streamlit as st


VIEWER = Path(__file__).parents[1] / "Flexar" / "BlueSG" / "Route_Map_Viewer.py"


def current_focus_source() -> str:
    source = VIEWER.read_text(encoding="utf-8")
    return source.rsplit("def render_map_planner_focus(", 1)[1].split("def render_route_results_summary", 1)[0]


def test_streamlit_supports_keyed_stretch_containers_and_pydeck() -> None:
    assert "height" in inspect.signature(st.container).parameters
    assert "key" in inspect.signature(st.container).parameters
    assert "height" in inspect.signature(st.pydeck_chart).parameters
    assert "key" in inspect.signature(st.pydeck_chart).parameters


def test_focus_css_uses_one_keyed_dynamic_viewport_height_chain() -> None:
    source = current_focus_source()
    assert "height: 100dvh" in source
    assert "grid-template-rows: 56px minmax(0, 1fr)" in source
    assert "route_planner_focus_shell" in source
    assert "route_planner_focus_workspace" in source
    assert "route_planner_focus_map" in source
    assert "route_planner_focus_panel" in source
    assert "calc(100vh" not in source


def test_focus_map_and_panel_use_stretch_height_and_stable_keys() -> None:
    source = current_focus_source()
    assert 'key="route_planner_focus_workspace", height="stretch"' in source
    assert 'key="route_planner_focus_map", height="stretch"' in source
    assert 'key="route_planner_focus_panel", height="stretch"' in source
    viewer = VIEWER.read_text(encoding="utf-8")
    assert 'key="route_planner_focus_map_chart"' in viewer
    assert 'height="stretch"' in viewer


def test_sortable_focus_styles_force_one_full_width_vertical_stack() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    assert "flex-direction: column !important" in viewer
    assert "flex-wrap: nowrap !important" in viewer
    assert "min-width: 100% !important" in viewer
    assert "max-width: 100% !important" in viewer


def test_sortable_panel_has_internal_viewport_scroll_for_cross_lane_dragging() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    assert "height: calc(100dvh - 238px)" in viewer
    assert "overflow-y: auto !important" in viewer
    assert "overscroll-behavior: contain" in viewer
    assert "scrollbar-gutter: stable" in viewer


def test_focus_layout_exposes_locking_reshuffle_and_three_route_colours() -> None:
    source = current_focus_source()
    assert '"Locked riders"' in source
    assert "reshuffle_unlocked_assignments" in source
    assert "Reshuffle ·" in source
    viewer = VIEWER.read_text(encoding="utf-8")
    assert "focus-green-loaded-routes" in viewer
    assert "focus-red-rider-access" in viewer
    assert "focus-purple-draft-connectors" in viewer


def test_loaded_workbook_enters_focus_and_reruns_before_summary() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    flow = viewer.split("def run_route_planner_screen_flow()", 1)[1].split("run_route_planner_screen_flow()", 1)[0]
    assert 'initialise_route_planner(loaded_state, workbook_id)' in flow
    assert 'st.session_state["route_planner_focus_mode"] = True' in flow
    assert "st.rerun()" in flow


def test_focus_controller_stops_before_results_summary() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    flow = viewer.split("def run_route_planner_screen_flow()", 1)[1].split("run_route_planner_screen_flow()", 1)[0]
    focus_call = flow.index("render_map_planner_focus")
    stop_call = flow.index("st.stop()", focus_call)
    summary_call = flow.index("render_route_results_summary", stop_call)
    assert focus_call < stop_call < summary_call


def test_results_export_is_guarded_by_dirty_state() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    summary = viewer.split("def render_route_results_summary", 1)[1].split("def run_route_planner_screen_flow", 1)[0]
    assert "if not dirty:" in summary
    assert "confirmed_routes" in summary
    assert "disabled=dirty" in summary
