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
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert '#board { width: 100%' in component
    assert '.lane { width: 100%' in component
    assert "boardElement.appendChild(laneElement)" in component


def test_sortable_panel_uses_parent_scroll_without_resize_feedback_loop() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert "height: calc(100dvh - 238px)" not in component
    assert "window.parent.innerHeight - top" in component
    assert "React" not in component
    assert ".st-key-route_planner_focus_panel > div" in viewer
    assert "overflow-y: auto" in component
    assert "overscroll-behavior: contain" in viewer
    assert "scrollbar-gutter: stable" in viewer


def test_focus_layout_exposes_locking_reshuffle_and_three_route_colours() -> None:
    source = current_focus_source()
    assert "Riders start locked" in source
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert 'label.className = "lock"' in component
    assert 'checkbox.type = "checkbox"' in component
    assert "reshuffle_unlocked_assignments" in source
    assert "Reshuffle {len(pool_job_ids)}" in source
    viewer = VIEWER.read_text(encoding="utf-8")
    assert "focus-green-loaded-routes" in viewer
    assert "focus-red-rider-access" in viewer
    assert "focus-purple-draft-connectors" in viewer
    assert "focus-rider-start-markers" in viewer
    assert "RESHUFFLE_POOL_LANE" in viewer


def test_rider_panel_is_wide_and_pool_has_local_reshuffle_action() -> None:
    source = current_focus_source()
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert "st.columns([1.2, 1]" in source
    assert "Reshuffle into unlocked riders" in component
    assert 'emit("reshuffle")' in component
    assert "Pool cleared; orders returned unchanged." in source
    assert 'route_planner_reshuffle_pool_job_ids"] = []' in source
    assert "font-size: .88rem" in component
    assert "font-size: .82rem" in component


def test_rider_headers_include_exact_start_location() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    board_builder = viewer.split("def build_sortable_board", 1)[1].split("def render_route_assignment_board", 1)[0]
    assert 'row.get("Start Location")' in board_builder
    assert 'Start: {starts_by_rider.get(lane)' in board_builder


def test_clicking_unlocked_order_adds_it_to_pool_without_scrolling() -> None:
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert 'card.addEventListener("click"' in component
    assert "poolLane.items.push(selected)" in component
    assert 'locked.has(lane.lane_id)' in component
    assert 'emit("board")' in component


def test_rider_header_has_default_off_view_highlight_control() -> None:
    component = (VIEWER.parent / "route_board_component" / "index.html").read_text(encoding="utf-8")
    assert 'focusCheckbox.type = "checkbox"' in component
    assert "focusCheckbox.checked = highlighted.has(lane.lane_id)" in component
    assert 'emit("highlight")' in component
    assert 'focusIcon.textContent = "View"' in component


def test_focused_routes_have_glow_start_arrow_and_animated_direction_arrows() -> None:
    viewer = VIEWER.read_text(encoding="utf-8")
    assert 'id="focus-highlight-route-glow"' in viewer
    assert 'id="focus-rider-start-arrows"' in viewer
    assert 'id="focus-moving-direction-arrows"' in viewer
    assert '@st.fragment(run_every=0.8)' in viewer
    assert 'geometry_source": "highlight_straight_line_fallback"' in viewer


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
