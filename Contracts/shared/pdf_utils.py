from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MISSING_LIBREOFFICE_MESSAGE = (
    'LibreOffice was not found. Add "libreoffice" to packages.txt and reboot the Streamlit app.'
)


class LibreOfficeNotFoundError(RuntimeError):
    """Raised when no supported LibreOffice executable is available."""


class DocxToPdfConversionError(RuntimeError):
    """Raised when LibreOffice cannot produce a valid PDF from a DOCX file."""


@dataclass(frozen=True)
class LibreOfficeStatus:
    """Availability and version details for the configured PDF converter."""

    available: bool
    executable: str | None
    version: str | None
    error: str | None = None


def _standard_libreoffice_paths() -> tuple[Path, ...]:
    """Return common LibreOffice locations not normally covered by PATH."""
    return (
        Path("/usr/bin/libreoffice"),
        Path("/usr/bin/soffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
        Path("/snap/bin/libreoffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
        PROJECT_ROOT
        / "tools"
        / "LibreOfficePortable"
        / "App"
        / "libreoffice"
        / "program"
        / "soffice.exe",
        PROJECT_ROOT
        / "tools"
        / "LibreOfficePortable"
        / "LibreOfficePortable"
        / "App"
        / "libreoffice"
        / "program"
        / "soffice.exe",
        PROJECT_ROOT
        / "tools"
        / "PortableApps"
        / "LibreOfficePortable"
        / "App"
        / "libreoffice"
        / "program"
        / "soffice.exe",
    )


def find_libreoffice() -> str | None:
    """Find a usable LibreOffice executable, preferring normal system installs."""
    configured_path = os.getenv("LIBREOFFICE_PATH", "").strip()
    if configured_path:
        configured_command = shutil.which(configured_path)
        configured_candidate = Path(configured_command or configured_path).expanduser()
        if configured_candidate.is_file():
            return str(configured_candidate.resolve())

    for executable_name in ("libreoffice", "soffice"):
        executable = shutil.which(executable_name)
        if executable:
            return str(Path(executable).resolve())

    for candidate in _standard_libreoffice_paths():
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def get_libreoffice_status(timeout_seconds: float = 10) -> LibreOfficeStatus:
    """Report LibreOffice availability, executable path, and installed version."""
    executable = find_libreoffice()
    if executable is None:
        return LibreOfficeStatus(
            available=False,
            executable=None,
            version=None,
            error=MISSING_LIBREOFFICE_MESSAGE,
        )

    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return LibreOfficeStatus(
            available=True,
            executable=executable,
            version=None,
            error=f"LibreOffice version check failed: {type(exc).__name__}: {exc}",
        )

    version = (result.stdout.strip() or result.stderr.strip()) if result.returncode == 0 else None
    error = None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "No diagnostic output was returned."
        error = f"LibreOffice version check exited with code {result.returncode}: {detail}"
    return LibreOfficeStatus(
        available=True,
        executable=executable,
        version=version,
        error=error,
    )


def _conversion_failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    details = []
    if result.stdout.strip():
        details.append(f"stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        details.append(f"stderr: {result.stderr.strip()}")
    return " | ".join(details) or "LibreOffice returned no diagnostic output."


def convert_docx_to_pdf(
    docx_path: str | Path,
    output_directory: str | Path | None = None,
    *,
    timeout_seconds: float = 120,
) -> Path:
    """Convert one DOCX to PDF with headless LibreOffice and an isolated profile."""
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

    executable = find_libreoffice()
    if executable is None:
        raise LibreOfficeNotFoundError(MISSING_LIBREOFFICE_MESSAGE)

    expected_pdf = output_dir / f"{source.stem}.pdf"
    if expected_pdf.exists():
        try:
            expected_pdf.unlink()
        except OSError as exc:
            raise DocxToPdfConversionError(
                f"Could not replace the existing PDF file: {expected_pdf}"
            ) from exc

    with tempfile.TemporaryDirectory(prefix="libreoffice_profile_") as profile_dir_name:
        profile_dir = Path(profile_dir_name).resolve()
        profile_uri = profile_dir.as_uri()
        command = [
            executable,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(output_dir),
            str(source),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocxToPdfConversionError(
                f"LibreOffice timed out after {timeout_seconds:g} seconds while converting {source.name}."
            ) from exc
        except OSError as exc:
            raise DocxToPdfConversionError(
                f"LibreOffice could not be started from {executable}: {type(exc).__name__}: {exc}"
            ) from exc

    if result.returncode != 0:
        raise DocxToPdfConversionError(
            f"LibreOffice failed to convert {source.name} (exit code {result.returncode}). "
            f"{_conversion_failure_detail(result)}"
        )
    if not expected_pdf.is_file():
        raise DocxToPdfConversionError(
            f"LibreOffice reported success but did not create the expected PDF: {expected_pdf}"
        )
    if expected_pdf.stat().st_size == 0:
        raise DocxToPdfConversionError(
            f"LibreOffice created an empty PDF file: {expected_pdf}"
        )
    with expected_pdf.open("rb") as pdf_file:
        signature = pdf_file.read(4)
    if signature != b"%PDF":
        raise DocxToPdfConversionError(
            f"LibreOffice output is not a valid PDF file: {expected_pdf}"
        )
    return expected_pdf
