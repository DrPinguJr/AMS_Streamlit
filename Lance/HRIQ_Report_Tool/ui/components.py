from __future__ import annotations

import streamlit as st


def apply_compact_style() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; max-width: 1500px;}
        div[data-testid="stMetric"] {padding: .65rem; border: 1px solid rgba(128,128,128,.2); border-radius: .5rem;}
        div[data-testid="stCode"] pre {max-height: 260px; background: #111827; color: #d1fae5;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def terminal_log(lines: list[str]) -> None:
    st.code("\n".join(lines[-100:]) if lines else "No activity yet.", language="text")
