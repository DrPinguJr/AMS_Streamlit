"""Single-page Streamlit dashboard for the Flexar WhatsApp request processor."""

from __future__ import annotations

from typing import Any, Callable

import httpx
import pandas as pd
import streamlit as st

from Flexar.whatsapp_request_processor.config import Settings, get_settings
from Flexar.whatsapp_request_processor.database import Database
from Flexar.whatsapp_request_processor.models import ContainerState
from Flexar.whatsapp_request_processor.simulator_service import (
    GUIDED_SCENARIOS,
    build_guided_scenario,
    build_payload,
    build_stress_payloads,
)
from Flexar.whatsapp_request_processor.ui_components import (
    container_card,
    event_card,
    flow_explainer,
    automation_badge,
    simulation_badge,
    status_legend,
)


@st.cache_resource
def get_database() -> Database:
    return Database(get_settings())


def _fragment_decorator() -> Callable[..., Callable[[Callable[..., None]], Callable[..., None]]]:
    fragment = getattr(st, "fragment", None)
    if fragment:
        return fragment

    def passthrough(**_: object) -> Callable[[Callable[..., None]], Callable[..., None]]:
        def decorator(func: Callable[..., None]) -> Callable[..., None]:
            return func

        return decorator

    return passthrough


fragment = _fragment_decorator()


@st.dialog("How to read this page")
def help_dialog() -> None:
    st.write("This page shows one row per vehicle request.")
    st.write("Rider messages and images may arrive separately; FastAPI and the request engine assemble them into the active request row.")
    st.write("A request dispatches only after the checklist passes and the quiet window finishes in the backend worker.")


def post_payload_to_fastapi(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = f"{settings.api_base_url}/test/payload"
    with httpx.Client(timeout=10) as client:
        response = client.post(endpoint, json=payload)
        response.raise_for_status()
        return response.json()


def send_payload(settings: Settings, payload_name: str, overrides: dict[str, Any]) -> None:
    try:
        payload = build_payload(payload_name, **overrides)
        result = post_payload_to_fastapi(settings, payload)
        st.session_state["last_result"] = result
        if result.get("duplicate"):
            st.toast("Duplicate ignored - this message was already processed.")
        elif result.get("container_state") in {ContainerState.NEEDS_REVIEW.value, ContainerState.MANUAL_REVIEW.value}:
            st.toast("Payload needs manual review.")
        elif result.get("container_state") == ContainerState.COMPLETED.value:
            st.toast("Request automatically completed.")
        else:
            st.toast(result.get("explanation") or "Payload sent to FastAPI.")
    except (httpx.HTTPError, ValueError) as exc:
        st.session_state["last_error"] = str(exc)
        st.error(f"Payload could not be sent to FastAPI at {settings.api_base_url}: {exc}")


def simulator_overrides() -> dict[str, Any]:
    return {
        "sender_id": st.session_state.get("sim_sender", "6591234567"),
        "chat_id": st.session_state.get("sim_chat", "6598765432@c.us"),
        "sender_display_name": st.session_state.get("sim_sender_name", "Rider A"),
        "licence_plate": st.session_state.get("sim_lp", "SMP3890P"),
    }


def render_simulator(settings: Settings) -> None:
    st.subheader("Test payload controls")
    controls = st.columns([1, 1, 1, 1])
    st.session_state["sim_sender"] = controls[0].text_input("Rider phone", value=st.session_state.get("sim_sender", "6591234567"))
    st.session_state["sim_chat"] = controls[1].text_input("Chat ID", value=st.session_state.get("sim_chat", "6598765432@c.us"))
    st.session_state["sim_sender_name"] = controls[2].text_input("Rider name", value=st.session_state.get("sim_sender_name", "Rider A"))
    st.session_state["sim_lp"] = controls[3].text_input("Licence plate", value=st.session_state.get("sim_lp", "SMP3890P"))

    payload_labels = [
        ("Payload A: complete request", "A"),
        ("Payload B: images and location, no LP", "B"),
        ("Payload C: text with LP and action", "C"),
        ("Payload D: seven images", "D"),
        ("Payload E: filler only", "E"),
        ("Payload F: duplicate of A", "F"),
        ("Payload G: conflicting LP/action data", "G"),
        ("Payload H: three images", "H"),
        ("Payload I: four images", "I"),
        ("Payload J: second vehicle", "J"),
        ("Payload K: MSCP no deck", "K"),
        ("Payload L: surface lot", "L"),
        ("Payload M: white lots", "M"),
        ("Payload N: no action", "N"),
    ]
    button_cols = st.columns(5)
    overrides = simulator_overrides()
    for index, (label, payload_name) in enumerate(payload_labels):
        if button_cols[index % 5].button(label, use_container_width=True):
            send_payload(settings, payload_name, overrides)
            st.rerun()

    st.markdown("**Guided scenarios**")
    scenario_cols = st.columns([1.5, 1, 1, 1])
    scenario_name = scenario_cols[0].selectbox("Scenario", list(GUIDED_SCENARIOS.keys()))
    scenario_cols[1].selectbox("Processing speed", ["instant", "normal", "slow"], index=0, disabled=True)
    if scenario_cols[2].button("Play Scenario", use_container_width=True):
        payloads = build_guided_scenario(scenario_name, **overrides)
        with st.status(f"Playing {scenario_name}", expanded=True) as status:
            for payload in payloads:
                post_payload_to_fastapi(settings, payload)
                st.write(f"Sent {payload['external_message_id']} to FastAPI")
            status.update(label="Scenario complete", state="complete")
        st.rerun()
    if scenario_cols[3].button("Pause/Cancel Demo", use_container_width=True):
        st.toast("No queued demo is running.")

    with st.expander("Random and stress testing", expanded=False):
        stress_cols = st.columns(6)
        count = stress_cols[0].selectbox("Count", [10, 50, 100, 500], index=0)
        seed = stress_cols[1].number_input("Seed", min_value=0, value=42)
        sender_count = stress_cols[2].number_input("Senders", min_value=1, max_value=20, value=3)
        chat_count = stress_cols[3].number_input("Chats", min_value=1, max_value=20, value=3)
        duplicate_probability = stress_cols[4].slider("Duplicate probability", 0.0, 1.0, 0.1)
        if stress_cols[5].button("Run Stress Test", use_container_width=True):
            payloads = build_stress_payloads(
                int(count),
                int(seed),
                int(sender_count),
                int(chat_count),
                float(duplicate_probability),
                **overrides,
            )
            posted = 0
            errors = 0
            for payload in payloads:
                try:
                    post_payload_to_fastapi(settings, payload)
                    posted += 1
                except httpx.HTTPError:
                    errors += 1
            st.session_state["stress_metrics"] = {"posted_to_fastapi": posted, "errors": errors, "endpoint": f"{settings.api_base_url}/test/payload"}
        if "stress_metrics" in st.session_state:
            st.json(st.session_state["stress_metrics"])


@fragment(run_every="0.5s")
def render_live_sections(db: Database, required_images: int) -> None:
    if st.session_state.get("pause_live_refresh"):
        st.info("Live visual refresh is paused. FastAPI and the request engine continue processing webhooks.")
        return

    snapshot = db.get_dashboard_snapshot()
    previous_revision = st.session_state.get("dashboard_revision")
    has_previous_snapshot = previous_revision is not None
    revision_changed = previous_revision is not None and previous_revision != snapshot["revision"]
    previous_container_activity = st.session_state.get("dashboard_container_activity") or {}
    st.session_state["dashboard_revision"] = snapshot["revision"]
    if revision_changed:
        st.markdown(
            """
            <div style="border:1px solid #3b82f6;background:rgba(59,130,246,.18);padding:.35rem .6rem;border-radius:6px;margin-bottom:.5rem;">
            Dashboard updated from SQLite.
            </div>
            """,
            unsafe_allow_html=True,
        )
    snapshot = snapshot or {}

    active_requests = snapshot.get("active_requests", [])
    paused_requests = snapshot.get("paused_requests", [])
    review_requests = snapshot.get("review_requests", [])
    completed_requests = snapshot.get("completed_requests", [])
    metrics_data = snapshot["metrics"]

    st.subheader("System status")
    metrics = st.columns(6)
    metrics[0].metric("Events", metrics_data["events"])
    metrics[1].metric("Active requests", metrics_data["active_requests"])
    metrics[2].metric("Paused", metrics_data["inactive"])
    metrics[3].metric("Needs review", metrics_data["manual_review"])
    metrics[4].metric("Completed", metrics_data["completed"])
    metrics[5].metric("Outbound actions", metrics_data["outbound_actions"])

    def table_rows(rows: list[dict[str, Any]], completed: bool = False) -> list[dict[str, Any]]:
        output = []
        for row in rows:
            changed = has_previous_snapshot and previous_container_activity.get(row["container_uuid"], 0) < int(row.get("latest_activity_id") or row.get("latest_revision") or 0)
            if completed:
                output.append(
                    {
                        "Completion Time": row.get("completed_at") or "-",
                        "Request": row.get("request_reference") or row["container_uuid"][:8],
                        "Rider": row.get("sender_display_name") or row.get("sender_id"),
                        "Vehicle": row.get("detected_licence_plate") or "Waiting for LP",
                        "Images Sent": row.get("approved_image_count") or row.get("image_count") or 0,
                        "Action": row.get("detected_action") or "Unknown",
                        "Rider Reply": row.get("rider_reply_status") or "-",
                        "OPS Update": row.get("ops_update_status") or "-",
                        "Supplemental Media": row.get("supplemental_media_count") or 0,
                        "Processing Duration": row.get("completed_at") or "-",
                    }
                )
            else:
                output.append(
                    {
                        "Request": ("* " if changed else "") + (row.get("request_reference") or row["container_uuid"][:8]),
                        "Rider": row.get("sender_display_name") or row.get("sender_id"),
                        "Vehicle": row.get("detected_licence_plate") or "Waiting for LP",
                        "Images": f"{row.get('image_count') or 0} / {required_images}",
                        "Action": row.get("detected_action") or "Unknown",
                        "Last Message": row.get("last_useful_activity_at") or row.get("updated_at") or "-",
                        "Status": row.get("friendly_status") or row.get("state"),
                        "Waiting For": row.get("waiting_for") or "-",
                        "Quiet Timer": "-" if row.get("quiet_seconds_remaining") is None else f"{row['quiet_seconds_remaining']} sec",
                        "Rider Reply": row.get("rider_reply_status") or "-",
                        "OPS Update": row.get("ops_update_status") or "-",
                    }
                )
        return output

    st.subheader("Active Requests")
    if active_requests:
        st.dataframe(pd.DataFrame(table_rows(active_requests)), use_container_width=True, hide_index=True)
    else:
        st.info("No active requests. New rider messages will create request rows here.")

    detail_options = {
        f"{row.get('request_reference') or row['container_uuid'][:8]} - {row.get('sender_display_name') or row.get('sender_id')}": row
        for row in active_requests + review_requests + paused_requests + completed_today
    }
    if detail_options:
        selected_label = st.selectbox("Request details", ["None", *detail_options.keys()])
        if selected_label != "None":
            selected = detail_options[selected_label]
            container_card(selected, required_images)

    if review_requests:
        st.subheader("Needs Review")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Request": row.get("request_reference") or row["container_uuid"][:8],
                        "Rider": row.get("sender_display_name") or row.get("sender_id"),
                        "Issue": row.get("manual_review_reason") or row.get("waiting_for"),
                        "Detected LPs": row.get("detected_licence_plate") or "-",
                        "Images": f"{row.get('image_count') or 0} / {required_images}",
                        "Action": row.get("detected_action") or "Unknown",
                        "Required Fix": row.get("waiting_for") or "Review request",
                    }
                    for row in review_requests
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander(f"Paused Requests ({len(paused_requests)})", expanded=False):
        if paused_requests:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Request": row.get("request_reference") or row["container_uuid"][:8],
                            "Rider": row.get("sender_display_name") or row.get("sender_id"),
                            "Vehicle": row.get("detected_licence_plate") or "Waiting for LP",
                            "Images": f"{row.get('image_count') or 0} / {required_images}",
                            "Missing": row.get("waiting_for") or "-",
                            "Last Activity": row.get("last_useful_activity_at") or row.get("updated_at"),
                            "Paused For": row.get("paused_at") or "-",
                        }
                        for row in paused_requests
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("No paused requests.")

    st.subheader("Completed Today")
    completed_filters = st.columns(4)
    rider_filter = completed_filters[0].text_input("Filter rider", value="")
    lp_filter = completed_filters[1].text_input("Filter LP", value="")
    action_filter = completed_filters[2].selectbox("Filter action", ["", "LOCKED", "UNLOCKED"])
    status_filter = completed_filters[3].selectbox("Filter output status", ["", "SIMULATED_SENT", "SENT", "FAILED", "PENDING"])
    filtered_completed = completed_today
    if rider_filter:
        filtered_completed = [row for row in filtered_completed if rider_filter.lower() in str(row.get("sender_display_name") or row.get("sender_id") or "").lower()]
    if lp_filter:
        filtered_completed = [row for row in filtered_completed if lp_filter.upper() in str(row.get("detected_licence_plate") or "").upper()]
    if action_filter:
        filtered_completed = [row for row in filtered_completed if row.get("detected_action") == action_filter]
    if status_filter:
        filtered_completed = [row for row in filtered_completed if status_filter in {row.get("rider_reply_status"), row.get("ops_update_status"), row.get("supplemental_status")}]
    if filtered_completed:
        st.dataframe(pd.DataFrame(table_rows(filtered_completed, completed=True)), use_container_width=True, hide_index=True)
    else:
        st.write("No completed requests match the current filters.")

    with st.expander("Technical Event Log", expanded=False):
        for event in snapshot["recent_events"]:
            event_card(event)

    st.session_state["dashboard_latest_event_id"] = snapshot["latest_event_id"]
    st.session_state["dashboard_latest_outbound_action_id"] = snapshot["latest_outbound_action_id"]
    st.session_state["dashboard_container_activity"] = {
        row["container_uuid"]: int(row.get("latest_activity_id") or row.get("latest_revision") or 0)
        for row in active_requests + review_requests + paused_requests + completed_today
    }


db = get_database()
settings = get_settings()

st.title("Flexar WhatsApp Request Processor")
simulation_badge(settings.simulation_mode, settings.waapi_enabled)
automation_badge(settings.automation_mode)

top_cols = st.columns([1, 1, 1])
if top_cols[0].button("Open Guided Walkthrough"):
    help_dialog()
top_cols[1].caption("FastAPI/request_engine handles webhook processing independently.")
if top_cols[2].button("Reset Simulator Data"):
    st.session_state["confirm_reset"] = True

if st.checkbox("Pause live visual refresh", value=st.session_state.get("pause_live_refresh", False)):
    st.session_state["pause_live_refresh"] = True
else:
    st.session_state["pause_live_refresh"] = False

if st.session_state.get("confirm_reset"):
    with st.container(border=True):
        st.warning("This resets simulator data in the configured local database. It does not call WAAPI.")
        confirm_text = st.text_input("Type RESET to confirm")
        if st.button("Confirm Reset", disabled=confirm_text != "RESET"):
            db.reset_all()
            st.session_state["confirm_reset"] = False
            st.success("Simulator data reset.")
            st.rerun()
        if st.button("Cancel Reset"):
            st.session_state["confirm_reset"] = False
            st.rerun()

flow_explainer()
status_legend()
render_simulator(settings)
st.divider()
render_live_sections(db, settings.min_required_images)

with st.expander("Completed requests and diagnostics", expanded=False):
    snapshot = db.get_dashboard_snapshot()
    completed = snapshot["recent_completed_requests"]
    outbound_actions = snapshot["outbound_actions"]
    st.markdown("**Completed containers**")
    st.dataframe(pd.DataFrame(completed), use_container_width=True) if completed else st.write("No completed containers yet.")
    st.markdown("**Outbound actions**")
    st.dataframe(pd.DataFrame(outbound_actions), use_container_width=True) if outbound_actions else st.write("No outbound actions yet.")
    st.markdown("**System diagnostics**")
    health = db.health()
    st.json(
        {
            "database_path": str(settings.database_path),
            "database_connection_status": "ok" if health["ok"] else "error",
            "waapi_enabled": settings.waapi_enabled,
            "simulation_mode": settings.simulation_mode,
            "minimum_required_image_count": settings.min_required_images,
            "container_inactive_seconds": settings.container_inactive_seconds,
            "container_expiry_seconds": settings.container_expiry_seconds,
            "fastapi_local_endpoint": f"{settings.api_base_url}/webhooks/waapi",
            "last_application_error": st.session_state.get("last_error"),
            "last_result": st.session_state.get("last_result"),
            "health_checks": {"sqlite": health},
        }
    )
