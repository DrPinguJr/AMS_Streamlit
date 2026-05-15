import os
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

try:
    from TenderScrape import log, scrape_tenderboard
except ModuleNotFoundError:
    from Tender.TenderScrape import log, scrape_tenderboard


LogFn = Callable[[str], None]


def streamlit_logger(log_box: Any) -> LogFn:
    messages: list[str] = []

    def write(message: str) -> None:
        log(message)
        messages.append(message)
        log_box.code("\n".join(messages[-80:]), language="text")

    return write


def render_streamlit_page() -> None:
    st.title("TenderBoard Tender Search")
    st.caption("Scrapes TenderBoard, processes the rows, and saves a clean Excel file for analysis.")

    headless = st.checkbox("Run browser headless", value=False)
    run = st.button("Run TenderBoard search", type="primary")

    if run:
        log_box = st.empty()
        ui_log = streamlit_logger(log_box)
        with st.spinner("Logging in, scraping, and processing tender rows..."):
            try:
                extracted_results, saved_path = scrape_tenderboard(headless=headless, log_fn=ui_log)
            except Exception as exc:
                st.exception(exc)
            else:
                dataframe = pd.DataFrame([result.as_dict() for result in extracted_results])
                st.success(f"Extracted {len(dataframe)} tender rows and saved {saved_path.name}.")
                st.dataframe(dataframe, use_container_width=True)
                st.download_button(
                    "Download Excel",
                    saved_path.read_bytes(),
                    file_name=saved_path.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


def running_inside_streamlit() -> bool:
    return get_script_run_ctx() is not None or "streamlit" in Path(sys.argv[0]).name.lower()


def main() -> None:
    headless = os.getenv("TENDERBOARD_HEADLESS", "0") == "1"
    scrape_tenderboard(headless=headless)


if running_inside_streamlit():
    render_streamlit_page()
elif __name__ == "__main__":
    main()
