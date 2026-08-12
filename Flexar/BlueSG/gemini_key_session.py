"""Shared per-session Gemini API key override.

Mirrors `onemap_token_session.py`'s pattern for a second secret: a page can
offer a manual key entry for an operator who cannot set the app's
`GEM_KEY` secret directly. Session state always wins over the configured
secret, so a pasted key can override a stale/wrong one without redeploying.
Nothing here is written to disk.
"""

from __future__ import annotations

import streamlit as st

from Flexar.BlueSG.build_optimised_vehicle_routes import clean_text


def configured_gemini_api_key() -> str:
    """The app-secrets-configured key, without requiring secrets to exist."""

    try:
        return clean_text(st.secrets.get("GEM_KEY", ""))
    except Exception:
        return ""


def current_gemini_session_key() -> str:
    return clean_text(st.session_state.get("gemini_api_key", ""))


def resolved_gemini_api_key() -> str:
    """Session override takes precedence over the configured secret."""

    return current_gemini_session_key() or configured_gemini_api_key()


def store_gemini_session_key(key: str) -> None:
    st.session_state["gemini_api_key"] = clean_text(key)


def clear_gemini_session_key() -> None:
    st.session_state.pop("gemini_api_key", None)


@st.dialog("Gemini API key", width="small")
def configure_gemini_key_dialog() -> None:
    session_key = current_gemini_session_key()
    if session_key:
        st.success("A Gemini API key is saved for this browser session.")
    elif configured_gemini_api_key():
        st.info("A Gemini API key is already configured in this app's secrets.")
    else:
        st.warning(
            "No Gemini API key is configured. The standby-driver advisor stays "
            "off until one is set."
        )

    with st.form("bluesg_gemini_key_form", border=False):
        key_input = st.text_input(
            "Gemini API key",
            type="password",
            placeholder="Paste your Gemini API key",
            help="Stored only in this Streamlit browser session, never written to disk.",
        )
        action_columns = st.columns(2)
        save_clicked = action_columns[0].form_submit_button("Save key", type="primary")
        clear_clicked = action_columns[1].form_submit_button("Clear key")

    if save_clicked:
        key = clean_text(key_input)
        if not key:
            st.error("Paste a Gemini API key before saving.")
            return
        store_gemini_session_key(key)
        st.session_state.hourly_gemini_key_message = "Gemini API key saved for this session."
        st.rerun()

    if clear_clicked:
        clear_gemini_session_key()
        st.session_state.hourly_gemini_key_message = "Gemini API key cleared."
        st.rerun()
