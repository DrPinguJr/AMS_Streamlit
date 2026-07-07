from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def find_libreoffice() -> str | None:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if executable:
        return executable

    candidates = [
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def convert_docx_to_pdf(input_path: Path, output_path: Path) -> None:
    """Convert a DOCX file to PDF using Microsoft Word or LibreOffice."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    word_error_message = ""
    try:
        import win32com.client  # type: ignore

        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        document = None
        try:
            document = word.Documents.Open(str(input_path.resolve()))
            document.SaveAs(str(output_path.resolve()), FileFormat=17)
        finally:
            if document is not None:
                document.Close(False)
            word.Quit()
    except Exception as word_error:
        word_error_message = f"{type(word_error).__name__}: {word_error}"
        soffice = find_libreoffice()
        if not soffice:
            raise RuntimeError(
                "PDF conversion requires Microsoft Word automation or LibreOffice. "
                "Word conversion failed and LibreOffice was not found. "
                f"Word error: {word_error_message}"
            ) from word_error

        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_path.parent),
                str(input_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        converted_path = output_path.parent / f"{input_path.stem}.pdf"
        if result.returncode != 0 or not converted_path.exists():
            message = result.stderr.strip() or result.stdout.strip() or "LibreOffice conversion failed."
            raise RuntimeError(message) from word_error
        if converted_path != output_path:
            converted_path.replace(output_path)

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("PDF conversion did not produce a valid file.")
