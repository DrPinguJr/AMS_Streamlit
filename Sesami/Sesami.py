import os
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

try:
    from SesamiProcess import load_sesami_data
    from SesamiScrape import log, scrape_sesami_business_opportunities
except ModuleNotFoundError:
    from Sesami.SesamiProcess import load_sesami_data
    from Sesami.SesamiScrape import log, scrape_sesami_business_opportunities


LogFn = Callable[[str], None]


def streamlit_logger(log_box: Any) -> LogFn:
    messages: list[str] = []

    def write(message: str) -> None:
        log(message)
        messages.append(message)
        log_box.code("\n".join(messages[-80:]), language="text")

    return write


@st.cache_data(show_spinner=False)
def cached_sesami_data(path_text: str | None = None) -> pd.DataFrame:
    return load_sesami_data(Path(path_text) if path_text else None)


def render_sesami_tab() -> None:
    st.title("Sesami Business Opportunities")
    st.caption("Scrapes Sesami Business Opportunities and saves a clean Excel file for analysis.")

    headless = st.checkbox("Run browser headless", value=False)
    run = st.button("Run Sesami search", type="primary")

    if run:
        log_box = st.empty()
        ui_log = streamlit_logger(log_box)
        with st.spinner("Logging in, scraping, and saving Sesami business opportunities..."):
            try:
                rows, saved_path = scrape_sesami_business_opportunities(headless=headless, log_fn=ui_log)
            except Exception as exc:
                st.exception(exc)
            else:
                cached_sesami_data.clear()
                dataframe = pd.DataFrame([row.as_dict() for row in rows])
                st.success(f"Extracted {len(dataframe)} Sesami rows and saved {saved_path.name}.")
                st.dataframe(dataframe, use_container_width=True)
                st.download_button(
                    "Download Excel",
                    saved_path.read_bytes(),
                    file_name=saved_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

    st.divider()
    st.subheader("Latest Saved Sesami Data")
    latest_dataframe = cached_sesami_data()
    if latest_dataframe.empty:
        st.info("No saved Sesami Excel file found yet.")
    else:
        st.dataframe(latest_dataframe, use_container_width=True)


def running_inside_streamlit() -> bool:
    return get_script_run_ctx() is not None or "streamlit" in Path(sys.argv[0]).name.lower()


def main() -> None:
    headless = os.getenv("SESAMI_HEADLESS", "0") == "1"
    scrape_sesami_business_opportunities(headless=headless)


if running_inside_streamlit():
    render_sesami_tab()
elif __name__ == "__main__":
    main()
