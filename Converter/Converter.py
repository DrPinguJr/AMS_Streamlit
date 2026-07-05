from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

import streamlit as st


try:
    st.set_page_config(layout="wide", page_title="PDF to Word Converter")
except st.errors.StreamlitAPIException:
    pass


BASE_DIR = Path("Converter")
OUTPUT_DIR = BASE_DIR / "outputs"
SUPPORTED_INPUTS = {".pdf"}


def ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def safe_filename(text: str) -> str:
    value = str(text or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value)
    value = re.sub(r"[^A-Za-z0-9._ -]", " ", value)
    value = re.sub(r"[\s_]+", "_", value).strip("._- ")
    return value[:120].strip("._- ") or "File"


def safe_prefix(text: str) -> str:
    value = str(text or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value)
    value = re.sub(r"[^A-Za-z0-9._ -]", " ", value)
    value = re.sub(r"\s+", "_", value).strip(" .")
    return value[:80]


def unique_path(folder: Path, filename: str) -> Path:
    path = folder / filename
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = folder / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def output_name(original_name: str, starting_name: str) -> str:
    original_stem = safe_filename(Path(original_name).stem)
    prefix = safe_prefix(starting_name)
    return f"{prefix}{original_stem}.docx" if prefix else f"{original_stem}.docx"


def convert_pdf_to_docx(input_path: Path, output_path: Path) -> None:
    try:
        from pdf2docx import Converter  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "PDF conversion needs the `pdf2docx` package. Run `pip install -r requirements.txt` and restart Streamlit."
        ) from exc

    converter = Converter(str(input_path))
    try:
        converter.convert(str(output_path), start=0, end=None)
    finally:
        converter.close()


def save_uploaded_pdf(uploaded_file: object, temp_dir: Path) -> Path:
    filename = safe_filename(getattr(uploaded_file, "name", "uploaded.pdf"))
    if Path(filename).suffix.lower() != ".pdf":
        filename = f"{Path(filename).stem}.pdf"
    path = unique_path(temp_dir, filename)
    path.write_bytes(uploaded_file.getbuffer())  # type: ignore[attr-defined]
    return path


def scan_pdf_folder(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in SUPPORTED_INPUTS and path.is_file())


def create_zip(paths: Iterable[Path]) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_file:
        zip_path = Path(temp_file.name)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, arcname=path.name)
        return zip_path.read_bytes()
    finally:
        zip_path.unlink(missing_ok=True)


def render_results(results: list[dict[str, str]]) -> None:
    successful = [item for item in results if item["status"] == "Converted"]
    failed = [item for item in results if item["status"] != "Converted"]

    if successful:
        st.success(f"Converted {len(successful)} PDF file(s).")
        st.caption(f"Saved to: {OUTPUT_DIR.resolve()}")

        for item in successful:
            output_path = Path(item["output_path"])
            with st.container(border=True):
                cols = st.columns([2, 3, 1], vertical_alignment="center")
                cols[0].markdown(f"**{item['source']}**")
                cols[1].code(str(output_path.resolve()))
                cols[2].download_button(
                    "Download",
                    data=output_path.read_bytes(),
                    file_name=output_path.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"download_{output_path.name}_{output_path.stat().st_mtime_ns}",
                )

        if len(successful) > 1:
            zip_bytes = create_zip(Path(item["output_path"]) for item in successful)
            zip_name = f"converted_docs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            st.download_button("Download all as ZIP", data=zip_bytes, file_name=zip_name, mime="application/zip")

    if failed:
        st.error(f"{len(failed)} file(s) could not be converted.")
        for item in failed:
            st.warning(f"{item['source']}: {item['message']}")


def convert_selected_files(selected_files: list[Path], starting_name: str) -> list[dict[str, str]]:
    ensure_output_dir()
    results: list[dict[str, str]] = []

    for input_path in selected_files:
        target_name = output_name(input_path.name, starting_name)
        output_path = unique_path(OUTPUT_DIR, target_name)
        try:
            convert_pdf_to_docx(input_path, output_path)
            results.append(
                {
                    "source": input_path.name,
                    "status": "Converted",
                    "output_path": str(output_path),
                    "message": "",
                }
            )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            results.append(
                {
                    "source": input_path.name,
                    "status": "Failed",
                    "output_path": "",
                    "message": str(exc),
                }
            )

    return results


def render_uploaded_flow(starting_name: str) -> None:
    uploaded_files = st.file_uploader(
        "Select PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        help="Choose multiple PDFs from your folder.",
    )
    if not uploaded_files:
        st.info("Choose one or more PDFs to convert.")
        return

    st.caption(f"{len(uploaded_files)} PDF file(s) selected")
    preview_rows = [
        {"Original": uploaded_file.name, "Word output": output_name(uploaded_file.name, starting_name)}
        for uploaded_file in uploaded_files
    ]
    st.dataframe(preview_rows, width="stretch", hide_index=True)

    if not st.button("Convert uploaded PDFs", type="primary"):
        return

    with st.spinner("Converting PDFs to Word..."):
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            input_paths = [save_uploaded_pdf(uploaded_file, temp_dir) for uploaded_file in uploaded_files]
            st.session_state["converter_results"] = convert_selected_files(input_paths, starting_name)


def render_folder_flow(starting_name: str) -> None:
    folder_value = st.text_input("Folder path", placeholder=r"C:\Users\HRteam\Desktop\PDFs")
    folder = Path(folder_value.strip().strip('"')) if folder_value.strip() else None
    if folder is None:
        st.info("Paste a local folder path to scan for PDF files.")
        return

    pdf_paths = scan_pdf_folder(folder)
    if not pdf_paths:
        st.warning("No PDF files found in that folder.")
        return

    labels = {f"{path.name} ({path.stat().st_size / 1024:.1f} KB)": path for path in pdf_paths}
    selected_labels = st.multiselect("Select PDFs to convert", list(labels.keys()), default=list(labels.keys()))
    selected_paths = [labels[label] for label in selected_labels]

    preview_rows = [
        {"Original": path.name, "Word output": output_name(path.name, starting_name)}
        for path in selected_paths
    ]
    st.dataframe(preview_rows, width="stretch", hide_index=True)

    if st.button("Convert selected folder PDFs", type="primary", disabled=not selected_paths):
        with st.spinner("Converting PDFs to Word..."):
            st.session_state["converter_results"] = convert_selected_files(selected_paths, starting_name)


def main() -> None:
    ensure_output_dir()

    st.title("PDF to Word Converter")
    st.caption("Select multiple PDF files, set a starting name, and convert them into DOCX files.")

    settings_cols = st.columns([1, 2], vertical_alignment="bottom")
    starting_name = settings_cols[0].text_input("Starting name", value="AMS_")
    settings_cols[1].write(f"Example output: `{output_name('Candidate Resume.pdf', starting_name)}`")

    tab_upload, tab_folder, tab_outputs = st.tabs(["Upload PDFs", "Use Folder Path", "Outputs"])
    with tab_upload:
        render_uploaded_flow(starting_name)
    with tab_folder:
        render_folder_flow(starting_name)
    with tab_outputs:
        st.subheader("Converted files")
        outputs = sorted(OUTPUT_DIR.glob("*.docx"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not outputs:
            st.info("No converted Word files yet.")
        else:
            if st.button("Clear all converted files"):
                shutil.rmtree(OUTPUT_DIR)
                ensure_output_dir()
                st.session_state.pop("converter_results", None)
                st.rerun()
            for path in outputs:
                cols = st.columns([2, 3, 1], vertical_alignment="center")
                cols[0].markdown(f"**{path.name}**")
                cols[1].code(str(path.resolve()))
                cols[2].download_button(
                    "Download",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"output_download_{path.name}_{path.stat().st_mtime_ns}",
                )

    results = st.session_state.get("converter_results", [])
    if results:
        st.divider()
        render_results(results)


if __name__ == "__main__":
    main()
