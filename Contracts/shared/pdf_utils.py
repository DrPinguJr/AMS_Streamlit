from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


WORD_CONVERTER_NAME = "Microsoft Word"
LIBREOFFICE_CONVERTER_NAME = "LibreOffice"
PDF_CONVERTER_NAME = f"{WORD_CONVERTER_NAME} or {LIBREOFFICE_CONVERTER_NAME}"
MISSING_PDF_CONVERTER_MESSAGE = (
    "Contract PDF generation requires Microsoft Word on Windows or LibreOffice "
    "on Linux/Cloud. No PDF converter was found; use a DOCX download where one "
    "is offered."
)
MISSING_WORD_AUTOMATION_MESSAGE = (
    "Microsoft Word PDF generation requires the Windows Word automation package. "
    "Install the project requirements and restart the app."
)


class PdfConverterUnavailableError(RuntimeError):
    """Raised when DOCX-to-PDF conversion is unavailable."""


class DocxToPdfConversionError(RuntimeError):
    """Raised when the configured converter cannot produce a valid PDF."""


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


def _standard_libreoffice_paths() -> tuple[Path, ...]:
    """Return common LibreOffice executable locations."""
    candidates = [
        Path("/usr/bin/soffice"),
        Path("/usr/bin/libreoffice"),
        Path("/usr/local/bin/soffice"),
        Path("/usr/local/bin/libreoffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]

    roots = [
        os.getenv("ProgramFiles", ""),
        os.getenv("ProgramFiles(x86)", ""),
        os.getenv("ProgramW6432", ""),
    ]
    for root in roots:
        if root:
            candidates.append(Path(root) / "LibreOffice" / "program" / "soffice.exe")

    return tuple(dict.fromkeys(candidates))


def find_libreoffice() -> str | None:
    """Find LibreOffice for headless DOCX-to-PDF conversion."""
    configured_path = os.getenv("LIBREOFFICE_PATH", "").strip()
    if configured_path:
        configured_command = shutil.which(configured_path)
        configured_candidate = Path(configured_command or configured_path).expanduser()
        if configured_candidate.is_file():
            return str(configured_candidate.resolve())

    for executable_name in ("soffice", "libreoffice"):
        executable = shutil.which(executable_name)
        if executable:
            return str(Path(executable).resolve())

    for candidate in _standard_libreoffice_paths():
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


def _get_word_converter_status() -> PdfConverterStatus:
    """Report Microsoft Word availability without launching Word."""
    if os.name != "nt":
        return PdfConverterStatus(
            available=False,
            converter=WORD_CONVERTER_NAME,
            executable=None,
            error="Microsoft Word PDF conversion is only available on Windows.",
        )

    executable = find_microsoft_word()
    if executable is None:
        return PdfConverterStatus(
            available=False,
            converter=WORD_CONVERTER_NAME,
            executable=None,
            error="Microsoft Word was not found.",
        )

    try:
        _load_word_automation()
    except PdfConverterUnavailableError as exc:
        return PdfConverterStatus(
            available=False,
            converter=WORD_CONVERTER_NAME,
            executable=executable,
            error=str(exc),
        )

    return PdfConverterStatus(
        available=True,
        converter=WORD_CONVERTER_NAME,
        executable=executable,
    )


def get_pdf_converter_status() -> PdfConverterStatus:
    """Report DOCX-to-PDF converter availability without launching a converter."""
    word_status = _get_word_converter_status()
    if word_status.available:
        return word_status

    libreoffice_executable = find_libreoffice()
    if libreoffice_executable is not None:
        return PdfConverterStatus(
            available=True,
            converter=LIBREOFFICE_CONVERTER_NAME,
            executable=libreoffice_executable,
        )

    error = (
        word_status.error
        if word_status.executable and word_status.error
        else MISSING_PDF_CONVERTER_MESSAGE
    )
    return PdfConverterStatus(
        available=False,
        converter=PDF_CONVERTER_NAME,
        executable=None,
        error=error,
    )


def _expected_pdf_path(source: Path, output_dir: Path) -> Path:
    return output_dir / f"{source.stem}.pdf"


def _remove_existing_pdf(expected_pdf: Path) -> None:
    if expected_pdf.exists():
        try:
            expected_pdf.unlink()
        except OSError as exc:
            raise DocxToPdfConversionError(
                f"Could not replace the existing PDF file: {expected_pdf}"
            ) from exc


def _validate_pdf_output(expected_pdf: Path, converter: str) -> None:
    if not expected_pdf.is_file():
        raise DocxToPdfConversionError(
            f"{converter} did not create the expected PDF: {expected_pdf}"
        )
    if expected_pdf.stat().st_size == 0:
        raise DocxToPdfConversionError(
            f"{converter} created an empty PDF file: {expected_pdf}"
        )
    with expected_pdf.open("rb") as pdf_file:
        signature = pdf_file.read(4)
    if signature != b"%PDF":
        raise DocxToPdfConversionError(
            f"{converter} output is not a valid PDF file: {expected_pdf}"
        )


def _convert_docx_to_pdf_with_word(source: Path, output_dir: Path) -> Path:
    expected_pdf = _expected_pdf_path(source, output_dir)
    _remove_existing_pdf(expected_pdf)

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

    _validate_pdf_output(expected_pdf, WORD_CONVERTER_NAME)
    return expected_pdf


def _convert_docx_to_pdf_with_libreoffice(
    source: Path,
    output_dir: Path,
    executable: str,
) -> Path:
    expected_pdf = _expected_pdf_path(source, output_dir)
    _remove_existing_pdf(expected_pdf)

    command = [
        executable,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source),
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except OSError as exc:
        raise DocxToPdfConversionError(
            f"LibreOffice could not start: {type(exc).__name__}: {exc}"
        ) from exc
    except subprocess.TimeoutExpired:
        raise DocxToPdfConversionError(
            f"LibreOffice timed out while converting {source.name}."
        )

    if result.returncode != 0:
        details = "\n".join(
            part.strip()
            for part in (result.stdout, result.stderr)
            if part and part.strip()
        )
        if not details:
            details = f"exit code {result.returncode}"
        raise DocxToPdfConversionError(
            f"LibreOffice could not convert {source.name}: {details}"
        )

    _validate_pdf_output(expected_pdf, LIBREOFFICE_CONVERTER_NAME)
    return expected_pdf


def convert_docx_to_pdf(
    docx_path: str | Path,
    output_directory: str | Path | None = None,
) -> Path:
    """Convert one DOCX to PDF through Microsoft Word or LibreOffice."""
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

    if status.converter == WORD_CONVERTER_NAME:
        return _convert_docx_to_pdf_with_word(source, output_dir)
    if status.converter == LIBREOFFICE_CONVERTER_NAME and status.executable:
        return _convert_docx_to_pdf_with_libreoffice(
            source,
            output_dir,
            status.executable,
        )

    raise PdfConverterUnavailableError(status.error or MISSING_PDF_CONVERTER_MESSAGE)
