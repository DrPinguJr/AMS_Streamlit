"""Shared per-session OneMap token override.

Any BlueSG page can offer a manual token entry as a fallback for an operator
whose app isn't configured with OneMap secrets/credentials. State lives in
``st.session_state["onemap_token"]`` and is mirrored into the backend
module's in-memory token cache so `get_cached_geocode`/route lookups pick it
up immediately - the same mechanism the main optimiser page established
first. Kept here so a second page (the hourly page) can reuse it without
duplicating the dialog.
"""

from __future__ import annotations

import streamlit as st

from Flexar.BlueSG import build_optimised_vehicle_routes as _route_optimizer_backend
from Flexar.BlueSG.build_optimised_vehicle_routes import (
    clean_text,
    get_onemap_token,
    onemap_credentials_configured,
)


def current_onemap_token() -> str:
    return clean_text(st.session_state.get("onemap_token", ""))


def onemap_access_configured(session_token: str | None = None) -> bool:
    return bool(
        clean_text(session_token)
        or get_onemap_token()
        or onemap_credentials_configured()
    )


def store_onemap_session_token(token: str) -> None:
    token = clean_text(token)
    st.session_state["onemap_token"] = token
    st.session_state["onemap_token_expiry"] = None
    store_active_token = getattr(_route_optimizer_backend, "_store_active_onemap_token", None)
    if callable(store_active_token):
        store_active_token(token, None)
        return
    _route_optimizer_backend.ONEMAP_MEMORY_TOKEN = token
    _route_optimizer_backend.ONEMAP_MEMORY_TOKEN_EXPIRY = None


def clear_onemap_session_token() -> None:
    st.session_state.pop("onemap_token", None)
    st.session_state.pop("onemap_token_expiry", None)
    _route_optimizer_backend.ONEMAP_MEMORY_TOKEN = ""
    _route_optimizer_backend.ONEMAP_MEMORY_TOKEN_EXPIRY = None


@st.dialog("OneMap token", width="small")
def configure_onemap_token_dialog() -> None:
    session_token = current_onemap_token()
    if session_token:
        st.success("A OneMap token is saved for this browser session.")
    elif onemap_access_configured():
        st.info("OneMap access is already configured for this app.")
    else:
        st.warning("No OneMap token or credentials are configured.")

    with st.form("bluesg_shared_onemap_token_form", border=False):
        token_input = st.text_input(
            "OneMap API token",
            type="password",
            placeholder="Paste OneMap access token",
            help="Stored only in this Streamlit browser session.",
        )
        action_columns = st.columns(2)
        save_clicked = action_columns[0].form_submit_button("Save token", type="primary")
        clear_clicked = action_columns[1].form_submit_button("Clear token")

    if save_clicked:
        token = clean_text(token_input)
        if not token:
            st.error("Paste a OneMap token before saving.")
            return
        store_onemap_session_token(token)
        st.session_state.bluesg_onemap_token_message = "OneMap token saved for this session."
        st.rerun()

    if clear_clicked:
        clear_onemap_session_token()
        st.session_state.bluesg_onemap_token_message = "OneMap token cleared."
        st.rerun()
