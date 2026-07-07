import os
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

try:
    from TenderProcess import process_latest_tenderboard_file
    from TenderScrape import log, scrape_tenderboard
except ModuleNotFoundError:
    from Lance.Tender.TenderProcess import process_latest_tenderboard_file
    from Lance.Tender.TenderScrape import log, scrape_tenderboard


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
                extracted_results, save_summary = scrape_tenderboard(headless=headless, log_fn=ui_log)
            except Exception as exc:
                st.exception(exc)
            else:
                dataframe = pd.DataFrame([result.as_dict() for result in extracted_results])
                if save_summary.new_output_path is None:
                    st.success(
                        f"Extracted {len(dataframe)} tender rows. "
                        f"No new tenders found. Database has {save_summary.database_count} rows."
                    )
                else:
                    st.success(
                        f"Extracted {len(dataframe)} tender rows. "
                        f"Added {save_summary.new_count} new and updated {save_summary.updated_count}. "
                        f"Saved {save_summary.new_output_path.name}."
                    )
                st.dataframe(dataframe, width="stretch")
                if save_summary.new_output_path is not None:
                    st.download_button(
                        "Download New Excel",
                        save_summary.new_output_path.read_bytes(),
                        file_name=save_summary.new_output_path.name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

    st.divider()
    process_latest = st.button("Process latest TenderBoard Excel")

    if process_latest:
        summary = process_latest_tenderboard_file()
        if summary.source_path is None:
            st.info("Nothing is detected.")
        else:
            st.success(
                f"Processed {summary.source_path.name}: "
                f"{summary.processed_count} accepted, {summary.rejected_count} rejected."
            )
            st.write(f"Created {summary.processed_path.name}")
            st.write(f"Created {summary.rejected_path.name}")


def running_inside_streamlit() -> bool:
    return get_script_run_ctx() is not None or "streamlit" in Path(sys.argv[0]).name.lower()


def main() -> None:
    headless = os.getenv("TENDERBOARD_HEADLESS", "0") == "1"
    scrape_tenderboard(headless=headless)


if running_inside_streamlit():
    render_streamlit_page()
elif __name__ == "__main__":
    main()
