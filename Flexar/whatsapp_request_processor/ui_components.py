"""Reusable Streamlit UI components for the request processor page."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st


STATE_COLOURS = {
    "COLLECTING": "#f59e0b",
    "READY_WAITING_QUIET": "#3b82f6",
    "DISPATCHING": "#2563eb",
    "COMPLETED": "#22c55e",
    "PAUSED": "#64748b",
    "NEEDS_REVIEW": "#ef4444",
    "FAILED": "#ef4444",
    "CANCELLED": "#64748b",
    "READY_FOR_APPROVAL": "#22c55e",
    "READY_TO_SEND": "#3b82f6",
    "WAITING_FOR_IMAGES": "#f59e0b",
    "WAITING_FOR_LP": "#f59e0b",
    "WAITING_FOR_ACTION": "#f59e0b",
    "MANUAL_REVIEW": "#ef4444",
    "INACTIVE": "#64748b",
    "EXPIRED": "#ef4444",
}


def relative_time(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    seconds = int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    return f"{hours} hours ago"


def simulation_badge(simulation_mode: bool, waapi_enabled: bool) -> None:
    label = "SIMULATION MODE - no WhatsApp messages are sent" if simulation_mode or not waapi_enabled else "WAAPI ENABLED"
    colour = "#3b82f6" if simulation_mode or not waapi_enabled else "#22c55e"
    st.markdown(
        f"""
        <div style="border:1px solid {colour}; color:#fff; background:rgba(59,130,246,.12);
        padding:.55rem .8rem; border-radius:8px; margin:.25rem 0 1rem 0;">
        <strong>{label}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def automation_badge(enabled: bool) -> None:
    label = "AUTOMATION ON" if enabled else "AUTOMATION OFF"
    explanation = (
        "Complete requests are processed automatically. Manual review is used only when the system cannot make a safe decision."
        if enabled
        else "Complete requests require operator action."
    )
    colour = "#22c55e" if enabled else "#f59e0b"
    st.markdown(
        f"""
        <div style="border:1px solid {colour}; color:#fff; background:{colour}1f;
        padding:.55rem .8rem; border-radius:8px; margin:.25rem 0 1rem 0;">
        <strong>{label}</strong><br><span style="color:#d1d5db">{explanation}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def state_badge(state: str, display_label: str | None = None) -> None:
    colour = STATE_COLOURS.get(state, "#64748b")
    st.markdown(
        f"""
        <span style="display:inline-block;border:1px solid {colour};background:{colour}22;color:#fff;
        padding:.2rem .45rem;border-radius:6px;font-size:.82rem;font-weight:700;">
        {display_label or state}
        </span>
        """,
        unsafe_allow_html=True,
    )


def status_legend() -> None:
    with st.expander("Status legend", expanded=False):
        st.write("Amber means collecting rider messages. Blue means complete and waiting for the quiet window or dispatching.")
        st.write("Green means completed. Grey means paused or cancelled. Red means review or failed send.")


def flow_explainer() -> None:
    cols = st.columns(3)
    cols[0].markdown("**1. Rider sends**\n\nText, images, or both arrive in any order.")
    cols[1].markdown("**2. System assembles**\n\nThe engine keeps one live request row per rider and vehicle.")
    cols[2].markdown("**3. Quiet dispatch**\n\nComplete requests wait briefly, then the backend sends rider and OPS updates.")


def event_card(event: dict[str, Any]) -> None:
    with st.container(border=True):
        st.caption(f"{relative_time(event.get('created_at') or event.get('received_at'))} | {event.get('classification')} | {event.get('match_reason') or '-'}")
        st.write(event.get("text_content") or event.get("event_type"))
        if event.get("processing_status") == "IGNORED":
            st.info("No container changed.")
        elif event.get("processing_status") == "MANUAL_REVIEW":
            st.warning("Needs operator review.")
        elif event.get("processing_status") == "PROCESSED":
            st.success("Processed.")
        with st.expander("Technical event details", expanded=False):
            st.json(event)


def _validation_icon(status: str) -> str:
    return {
        "PASSED": "[ok]",
        "MISSING": "[missing]",
        "WARNING": "[warning]",
        "BLOCKED": "[blocked]",
        "OPTIONAL": "[optional]",
        "NOT_APPLICABLE": "[n/a]",
    }.get(status, "[-]")


def _headline(report: dict[str, Any], container: dict[str, Any]) -> str:
    if container["state"] == "COMPLETED":
        return "Completed automatically"
    if report.get("blockers"):
        return "Needs manual review"
    missing = report.get("missing_required_fields") or []
    if "MISSING_IMAGES" in missing:
        image_item = next((item for item in report["items"] if item["key"] == "MISSING_IMAGES"), {})
        return image_item.get("explanation", "Waiting for more images")
    if "MISSING_LICENCE_PLATE" in missing:
        return "Waiting for licence plate"
    if "MISSING_ACTION" in missing:
        return "Waiting for lock/unlock instruction"
    if "MISSING_LOCATION_REFERENCE" in missing:
        return "Waiting for parking location"
    if "MISSING_PARKING_POSITION" in missing:
        return "Waiting for parking position"
    if "MISSING_MSCP_DECK" in missing:
        return "Waiting for deck or level"
    if report.get("auto_dispatch_eligible"):
        return "Automatically processing"
    return report.get("summary") or container.get("display_state") or container["state"]


def container_card(container: dict[str, Any], required_images: int) -> None:
    with st.container(border=True):
        report = container.get("validation_report") or {}
        items = report.get("items") or []
        location = ", ".join(
            part
            for part in [
                container.get("detected_location"),
                container.get("detected_deck"),
                container.get("detected_level"),
                container.get("detected_lot"),
                container.get("detected_lot_range"),
                container.get("detected_bay"),
                container.get("detected_zone"),
            ]
            if part
        )
        top = st.columns([1.1, 1, 1])
        top[0].markdown(f"**{container.get('request_reference') or container['container_uuid'][:8]}**")
        top[1].metric("Images", f"{container.get('image_count', 0)} / {required_images}")
        top[2].metric("Plate", container.get("detected_licence_plate") or "-")
        state_badge(container["state"], container.get("display_state"))
        st.markdown(f"### {_headline(report, container)}")
        st.caption(f"Rider `{container['sender_id']}` | Updated {relative_time(container.get('updated_at'))}")

        summary_cols = st.columns(4)
        summary_cols[0].write(f"Vehicle: **{container.get('detected_licence_plate') or '-'}**")
        summary_cols[1].write(f"Action: **{container.get('detected_action') or '-'}**")
        summary_cols[2].write(f"Images: **{container.get('image_count', 0)} / {required_images}**")
        summary_cols[3].write(f"Location: **{location or '-'}**")

        missing = report.get("missing_required_fields") or []
        blockers = report.get("blockers") or []
        if blockers:
            st.error("AUTOMATION STOPPED")
            st.write(report.get("next_action"))
        elif missing:
            st.warning("WHAT IS STILL NEEDED")
            for item in items:
                if item["key"] in missing:
                    st.write(f"- {item['explanation']}")
        else:
            st.success("All required information received")

        passed = sum(1 for item in items if item["required"] and item["status"] == "PASSED")
        required = sum(1 for item in items if item["required"])
        if required:
            st.caption(f"{passed} of {required} required checks passed")

        st.markdown("**CHECKLIST**")
        for section in ["Request identity", "Evidence received", "Operational information", "Automation safety"]:
            section_items = [item for item in items if item.get("section") == section]
            if not section_items:
                continue
            with st.expander(section, expanded=section in {"Request identity", "Evidence received", "Operational information"}):
                for item in section_items:
                    st.write(f"{_validation_icon(item['status'])} **{item['label']}**")
                    if item.get("value"):
                        st.caption(str(item["value"]))
                    st.caption(item["explanation"])

        st.markdown("**WHAT HAPPENS NEXT**")
        st.write(report.get("next_action") or container.get("what_next") or "")

        st.markdown("**REQUEST STORY**")
        story = report.get("story_steps") or []
        for index, step in enumerate(story[-3:], start=max(1, len(story) - 2)):
            st.write(f"{index}. {step}")
        with st.expander("View full story", expanded=False):
            for index, step in enumerate(story, start=1):
                st.write(f"{index}. {step}")

        with st.expander("Why did this happen?", expanded=False):
            st.write(f"Matched events: {container.get('matched_event_ids') or '-'}")
            st.write(f"Manual review reason: {container.get('manual_review_reason') or '-'}")
            st.write(report.get("summary") or "")
            if container.get("action_explanation"):
                st.caption(container["action_explanation"])
            if container.get("useful_text"):
                st.write(container["useful_text"])
        with st.expander("Technical details", expanded=False):
            st.json(container)


def outbound_card(action: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(f"**{action['action_type'].replace('_', ' ').title()}**")
        state_badge(action["status"], action["status"])
        st.write(action["message_text"])
        st.caption(f"Destination: `{action.get('destination_id') or '-'}`")
        with st.expander("Technical outbound details", expanded=False):
            st.json(action)
