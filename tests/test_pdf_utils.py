from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from Contracts.shared import pdf_utils


def _profile_path(profile_argument: str) -> Path:
    profile_uri = profile_argument.split("=", 1)[1]
    parsed = urlparse(profile_uri)
    path = unquote(parsed.path)
    if os.name == "nt":
        path = path.lstrip("/")
    return Path(path)


def test_convert_docx_to_pdf_builds_headless_command_and_cleans_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Sample Contract.docx"
    source.write_bytes(b"test docx")
    output_dir = tmp_path / "pdfs"
    captured: dict[str, object] = {}

    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: "/opt/libreoffice")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        profile_argument = next(item for item in command if item.startswith("-env:UserInstallation="))
        profile_path = _profile_path(profile_argument)
        assert profile_path.is_dir()
        captured["profile_path"] = profile_path

        outdir = Path(command[command.index("--outdir") + 1])
        input_path = Path(command[-1])
        (outdir / f"{input_path.stem}.pdf").write_bytes(b"%PDF-1.7\ntest")
        return subprocess.CompletedProcess(command, 0, "converted", "")

    monkeypatch.setattr(pdf_utils.subprocess, "run", fake_run)

    result = pdf_utils.convert_docx_to_pdf(source, output_dir, timeout_seconds=37)

    assert result == output_dir.resolve() / "Sample Contract.pdf"
    assert result.read_bytes().startswith(b"%PDF")
    assert not Path(captured["profile_path"]).exists()

    command = captured["command"]
    assert command[0] == "/opt/libreoffice"
    assert "--headless" in command
    assert "--nologo" in command
    assert "--nodefault" in command
    assert "--nofirststartwizard" in command
    assert command[command.index("--convert-to") + 1] == "pdf:writer_pdf_Export"
    assert command[command.index("--outdir") + 1] == str(output_dir.resolve())
    assert command[-1] == str(source.resolve())

    kwargs = captured["kwargs"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 37
    assert "shell" not in kwargs


def test_convert_docx_to_pdf_reports_missing_libreoffice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "contract.docx"
    source.write_bytes(b"test docx")
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: None)

    with pytest.raises(pdf_utils.LibreOfficeNotFoundError) as exc_info:
        pdf_utils.convert_docx_to_pdf(source)

    assert str(exc_info.value) == pdf_utils.MISSING_LIBREOFFICE_MESSAGE


def test_convert_docx_to_pdf_reports_process_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "contract.docx"
    source.write_bytes(b"test docx")
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: "/opt/libreoffice")
    monkeypatch.setattr(
        pdf_utils.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            2,
            "",
            "source document could not be loaded",
        ),
    )

    with pytest.raises(pdf_utils.DocxToPdfConversionError) as exc_info:
        pdf_utils.convert_docx_to_pdf(source)

    message = str(exc_info.value)
    assert "exit code 2" in message
    assert "source document could not be loaded" in message


def test_convert_docx_to_pdf_validates_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="DOCX file was not found"):
        pdf_utils.convert_docx_to_pdf(tmp_path / "missing.docx")

    wrong_extension = tmp_path / "contract.txt"
    wrong_extension.write_text("not a docx", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Expected a \.docx file"):
        pdf_utils.convert_docx_to_pdf(wrong_extension)


def test_libreoffice_status_includes_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: "/opt/libreoffice")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["/opt/libreoffice", "--version"]
        assert kwargs["timeout"] == 4
        return subprocess.CompletedProcess(command, 0, "LibreOffice 26.2.1\n", "")

    monkeypatch.setattr(pdf_utils.subprocess, "run", fake_run)

    status = pdf_utils.get_libreoffice_status(timeout_seconds=4)

    assert status.available is True
    assert status.executable == "/opt/libreoffice"
    assert status.version == "LibreOffice 26.2.1"
    assert status.error is None


def test_find_libreoffice_checks_libreoffice_then_soffice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr(pdf_utils, "_standard_libreoffice_paths", lambda: ())

    def fake_which(name: str) -> str | None:
        calls.append(name)
        return "/opt/soffice" if name == "soffice" else None

    monkeypatch.setattr(pdf_utils.shutil, "which", fake_which)

    executable = pdf_utils.find_libreoffice()

    assert calls == ["libreoffice", "soffice"]
    assert executable == str(Path("/opt/soffice").resolve())


def test_libreoffice_status_reports_actionable_missing_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: None)

    status = pdf_utils.get_libreoffice_status()

    assert status.available is False
    assert status.error == (
        'LibreOffice was not found. Add "libreoffice" to packages.txt and reboot the Streamlit app.'
    )
