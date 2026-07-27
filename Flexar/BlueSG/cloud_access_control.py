"""Access control for the dedicated BlueSG Streamlit Community Cloud app."""

from __future__ import annotations

import hmac
import os

import streamlit as st


_FALSE_VALUES = {"0", "false", "no", "off"}
_AUTHENTICATED_SESSION_KEY = "bluesg_cloud_user_authenticated"


def _read_secret(name: str) -> str:
    """Read a root-level Streamlit secret without exposing it to a widget."""

    environment_value = os.getenv(name, "").strip()
    if environment_value:
        return environment_value

    try:
        value = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(value).strip()


def cloud_login_required() -> bool:
    """Return whether the dedicated app should display its password gate.

    Community Cloud runs on Linux, so login is secure-by-default there.
    Windows development remains convenient unless login is explicitly enabled
    or an ``APP_PASSWORD`` is configured.
    """

    configured = os.getenv("BLUESG_REQUIRE_LOGIN", "").strip().casefold()
    if configured:
        return configured not in _FALSE_VALUES
    return os.name != "nt" or bool(_read_secret("APP_PASSWORD"))


def require_cloud_access() -> None:
    """Stop the Streamlit run until the configured app password is supplied."""

    if not cloud_login_required():
        return

    expected_password = _read_secret("APP_PASSWORD")
    if not expected_password:
        st.error("This Cloud deployment is locked until APP_PASSWORD is configured.")
        st.caption(
            "Add APP_PASSWORD in the app's Streamlit Community Cloud Advanced "
            "settings, then reboot the app."
        )
        st.stop()

    if st.session_state.get(_AUTHENTICATED_SESSION_KEY, False):
        if st.sidebar.button("Sign out", key="bluesg_cloud_sign_out"):
            st.session_state[_AUTHENTICATED_SESSION_KEY] = False
            st.rerun()
        return

    st.title("BlueSG Route Optimiser")
    st.caption("Enter the shared deployment password to continue.")
    with st.form("bluesg_cloud_sign_in", clear_on_submit=True):
        supplied_password = st.text_input(
            "App password",
            type="password",
            value="",
            autocomplete="current-password",
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if submitted:
        if hmac.compare_digest(supplied_password, expected_password):
            st.session_state[_AUTHENTICATED_SESSION_KEY] = True
            st.rerun()
        st.error("Incorrect password.")

    st.stop()
