from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PDF_CONVERTER_NAME = "Microsoft Word"
MISSING_PDF_CONVERTER_MESSAGE = (
    "Contract PDF generation requires Microsoft Word on Windows. "
    "Microsoft Word was not found; use a DOCX download where one is offered."
)
MISSING_WORD_AUTOMATION_MESSAGE = (
    "Contract PDF generation requires the Windows Word automation package. "
    "Install the project requirements and restart the app."
)


class PdfConverterUnavailableError(RuntimeError):
    """Raised when Microsoft Word PDF conversion is unavailable."""


class DocxToPdfConversionError(RuntimeError):
    """Raised when Microsoft Word cannot produce a valid PDF from a DOCX file."""


@dataclass(frozen=True)
class PdfConverterStatus:
    """Availability details for the configured PDF converter."""

    available: bool
    converter: str
    executable: str | None
    error: str | None = None


def _standard_microsoft_word_paths() -> tuple[Path, ...]:
    """Return common Microsoft Word executable locations."""
    roots = [
        os.getenv("ProgramFiles", ""),
        os.getenv("ProgramFiles(x86)", ""),
        os.getenv("ProgramW6432", ""),
    ]
    office_directories = (
        Path("Microsoft Office") / "root" / "Office16",
        Path("Microsoft Office") / "Office16",
        Path("Microsoft Office") / "Office15",
        Path("Microsoft Office") / "Office14",
    )

    candidates: list[Path] = []
    for root in roots:
        if not root:
            continue
        for office_directory in office_directories:
            candidates.append(Path(root) / office_directory / "WINWORD.EXE")
    return tuple(dict.fromkeys(candidates))


def _registered_microsoft_word_paths() -> tuple[Path, ...]:
    """Return Word paths registered with Windows, when available."""
    if os.name != "nt":
        return ()

    try:
        import winreg
    except ImportError:
        return ()

    key_names = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE",
    )
    candidates: list[Path] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_name in key_names:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            if value:
                candidates.append(Path(str(value).strip().strip('"')))
    return tuple(dict.fromkeys(candidates))


def find_microsoft_word() -> str | None:
    """Find the Microsoft Word executable without starting another process."""
    configured_path = os.getenv("MICROSOFT_WORD_PATH", "").strip()
    if configured_path:
        configured_command = shutil.which(configured_path)
        configured_candidate = Path(configured_command or configured_path).expanduser()
        if configured_candidate.is_file():
            return str(configured_candidate.resolve())

    executable = shutil.which("winword")
    if executable:
        return str(Path(executable).resolve())

    for candidate in (
        *_registered_microsoft_word_paths(),
        *_standard_microsoft_word_paths(),
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def _load_word_automation() -> tuple[Any, Any]:
    """Load pywin32 lazily so DOCX generation remains cross-platform."""
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise PdfConverterUnavailableError(MISSING_WORD_AUTOMATION_MESSAGE) from exc
    return pythoncom, win32com.client


def get_pdf_converter_status() -> PdfConverterStatus:
    """Report Word PDF-conversion availability without launching Word."""
    if os.name != "nt":
        return PdfConverterStatus(
            available=False,
            converter=PDF_CONVERTER_NAME,
            executable=None,
            error=MISSING_PDF_CONVERTER_MESSAGE,
        )

    try:
        _load_word_automation()
    except PdfConverterUnavailableError as exc:
        return PdfConverterStatus(
            available=False,
            converter=PDF_CONVERTER_NAME,
            executable=find_microsoft_word(),
            error=str(exc),
        )

    executable = find_microsoft_word()
    if executable is None:
        return PdfConverterStatus(
            available=False,
            converter=PDF_CONVERTER_NAME,
            executable=None,
            error=MISSING_PDF_CONVERTER_MESSAGE,
        )

    return PdfConverterStatus(
        available=True,
        converter=PDF_CONVERTER_NAME,
        executable=executable,
    )


def convert_docx_to_pdf(
    docx_path: str | Path,
    output_directory: str | Path | None = None,
) -> Path:
    """Convert one DOCX to PDF through an invisible Microsoft Word instance."""
    source = Path(docx_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"DOCX file was not found: {source}")
    if not source.is_file():
        raise ValueError(f"DOCX path is not a file: {source}")
    if source.suffix.lower() != ".docx":
        raise ValueError(f"Expected a .docx file, received: {source.name}")

    output_dir = (
        Path(output_directory).expanduser().resolve()
        if output_directory is not None
        else source.parent
    )
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"PDF output directory is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    status = get_pdf_converter_status()
    if not status.available:
        raise PdfConverterUnavailableError(status.error or MISSING_PDF_CONVERTER_MESSAGE)

    expected_pdf = output_dir / f"{source.stem}.pdf"
    if expected_pdf.exists():
        try:
            expected_pdf.unlink()
        except OSError as exc:
            raise DocxToPdfConversionError(
                f"Could not replace the existing PDF file: {expected_pdf}"
            ) from exc

    pythoncom, word_client = _load_word_automation()
    word = None
    document = None
    pythoncom.CoInitialize()
    try:
        word = word_client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(
            str(source),
            ReadOnly=True,
            AddToRecentFiles=False,
            Visible=False,
        )
        document.ExportAsFixedFormat(str(expected_pdf), 17)
    except Exception as exc:
        raise DocxToPdfConversionError(
            f"Microsoft Word could not convert {source.name}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if document is not None:
            try:
                document.Close(False)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit(False)
            except Exception:
                pass
        pythoncom.CoUninitialize()

    if not expected_pdf.is_file():
        raise DocxToPdfConversionError(
            f"Microsoft Word did not create the expected PDF: {expected_pdf}"
        )
    if expected_pdf.stat().st_size == 0:
        raise DocxToPdfConversionError(
            f"Microsoft Word created an empty PDF file: {expected_pdf}"
        )
    with expected_pdf.open("rb") as pdf_file:
        signature = pdf_file.read(4)
    if signature != b"%PDF":
        raise DocxToPdfConversionError(
            f"Microsoft Word output is not a valid PDF file: {expected_pdf}"
        )
    return expected_pdf
