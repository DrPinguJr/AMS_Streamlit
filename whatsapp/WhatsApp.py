from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    from whatsapp.whatsapp_driver import (
        PROFILE_DIR,
        get_whatsapp_driver,
        has_qr_login,
        is_whatsapp_logged_in,
        open_whatsapp_web,
    )
    from whatsapp.whatsapp_monitor import WhatsAppMonitor, select_whatsapp_chat
    from whatsapp.whatsapp_storage import DB_PATH, IMAGE_ROOT, load_recent_messages
except Exception:
    MODULE_DIR = Path(__file__).resolve().parent
    if str(MODULE_DIR) not in sys.path:
        sys.path.insert(0, str(MODULE_DIR))

    from whatsapp_driver import (  # type: ignore[no-redef]
        PROFILE_DIR,
        get_whatsapp_driver,
        has_qr_login,
        is_whatsapp_logged_in,
        open_whatsapp_web,
    )
    from whatsapp_monitor import WhatsAppMonitor, select_whatsapp_chat  # type: ignore[no-redef]
    from whatsapp_storage import DB_PATH, IMAGE_ROOT, load_recent_messages  # type: ignore[no-redef]


@st.cache_resource(show_spinner=False)
def get_monitor() -> WhatsAppMonitor:
    return WhatsAppMonitor()


def render_status(label: str, value: str) -> None:
    st.metric(label, value or "-")


def render_recent_messages(chat_name: str) -> None:
    rows = load_recent_messages(limit=100, chat_name=chat_name or None)
    if not rows:
        st.info("No captured WhatsApp messages saved yet.")
        return

    dataframe = pd.DataFrame(rows)
    visible_columns = [
        "captured_at",
        "chat_name",
        "sender",
        "direction",
        "timestamp",
        "text",
        "has_image",
        "image_path",
    ]
    st.dataframe(dataframe[visible_columns], width="stretch", hide_index=True)


def render_streamlit_page() -> None:
    st.title("WhatsApp Monitor")
    st.caption("Open an authorised WhatsApp Web session, select a chat, and capture visible messages locally.")

    with st.sidebar:
        st.subheader("WhatsApp Monitor")
        chat_name = st.text_input(
            "Exact group/chat name",
            value=st.session_state.get("whatsapp_chat_name", ""),
            placeholder="Paste the chat name exactly",
        )
        st.session_state["whatsapp_chat_name"] = chat_name

        open_chat = st.button("Open/select chat", type="primary")
        start_monitoring = st.button("Start monitoring")
        stop_monitoring = st.button("Stop monitoring")

    monitor = get_monitor()

    try:
        driver = get_whatsapp_driver()
        open_whatsapp_web(driver)
    except Exception as exc:
        st.error(f"Could not start the dedicated WhatsApp Chrome session: {exc}")
        st.stop()

    logged_in = is_whatsapp_logged_in(driver)
    qr_visible = has_qr_login(driver)
    snapshot = monitor.snapshot()

    status_cols = st.columns(4)
    with status_cols[0]:
        render_status("Browser", "Ready")
    with status_cols[1]:
        render_status("Login", "Logged in" if logged_in else "QR required" if qr_visible else "Loading")
    with status_cols[2]:
        render_status("Monitor", snapshot["status"])
    with status_cols[3]:
        render_status("Seen", str(snapshot["seen_count"]))

    if not logged_in:
        st.info(
            "First-time setup: scan the QR code in the opened Chrome window. "
            f"The session is stored in `{PROFILE_DIR}` so it can persist across Streamlit restarts."
        )

    if open_chat:
        ok, message = select_whatsapp_chat(driver, chat_name)
        (st.success if ok else st.error)(message)

    if start_monitoring:
        if not chat_name.strip():
            st.error("Enter the exact group/chat name before starting the monitor.")
        else:
            ok, message = monitor.start(driver, chat_name.strip())
            (st.success if ok else st.warning)(message)

    if stop_monitoring:
        st.success(monitor.stop())

    snapshot = monitor.snapshot()
    if snapshot["last_error"]:
        st.warning(f"Last monitor error: {snapshot['last_error']}")

    st.subheader("Recent Captured Messages")
    render_recent_messages(chat_name.strip())

    st.divider()
    st.subheader("Local Storage")
    st.write(f"Message database: `{DB_PATH.resolve()}`")
    st.write(f"Image folder: `{IMAGE_ROOT.resolve()}`")
    st.caption(
        "WhatsApp Web changes its DOM often. The monitor uses multiple selectors and message metadata where available, "
        "but selector maintenance may be needed after WhatsApp UI updates."
    )


render_streamlit_page()
