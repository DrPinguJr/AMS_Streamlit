from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from Contracts.shared import pdf_utils


class FakePythonCom:
    def __init__(self) -> None:
        self.initialized = 0
        self.uninitialized = 0

    def CoInitialize(self) -> None:
        self.initialized += 1

    def CoUninitialize(self) -> None:
        self.uninitialized += 1


class FakeDocument:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.export_arguments: tuple[str, int] | None = None
        self.closed = False

    def ExportAsFixedFormat(self, output_path: str, export_format: int) -> None:
        self.export_arguments = (output_path, export_format)
        if self.fail:
            raise RuntimeError("simulated Word export failure")
        Path(output_path).write_bytes(b"%PDF-1.7\ntest")

    def Close(self, save_changes: bool) -> None:
        assert save_changes is False
        self.closed = True


class FakeDocuments:
    def __init__(self, document: FakeDocument) -> None:
        self.document = document
        self.open_arguments: tuple[str, bool, bool, bool] | None = None

    def Open(
        self,
        source: str,
        *,
        ReadOnly: bool,
        AddToRecentFiles: bool,
        Visible: bool,
    ) -> FakeDocument:
        self.open_arguments = (source, ReadOnly, AddToRecentFiles, Visible)
        return self.document


class FakeWord:
    def __init__(self, document: FakeDocument) -> None:
        self.Documents = FakeDocuments(document)
        self.Visible: bool | None = None
        self.DisplayAlerts: int | None = None
        self.quit_called = False

    def Quit(self, save_changes: bool) -> None:
        assert save_changes is False
        self.quit_called = True


def _available_status() -> pdf_utils.PdfConverterStatus:
    return pdf_utils.PdfConverterStatus(
        available=True,
        converter="Microsoft Word",
        executable=r"C:\Program Files\Microsoft Office\WINWORD.EXE",
    )


def test_convert_docx_to_pdf_uses_invisible_word_and_closes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Sample Contract.docx"
    source.write_bytes(b"test docx")
    output_dir = tmp_path / "pdfs"
    pythoncom = FakePythonCom()
    document = FakeDocument()
    word = FakeWord(document)
    client = SimpleNamespace(DispatchEx=lambda name: word)

    monkeypatch.setattr(pdf_utils, "get_pdf_converter_status", _available_status)
    monkeypatch.setattr(pdf_utils, "_load_word_automation", lambda: (pythoncom, client))

    result = pdf_utils.convert_docx_to_pdf(source, output_dir)

    assert result == output_dir.resolve() / "Sample Contract.pdf"
    assert result.read_bytes().startswith(b"%PDF")
    assert word.Visible is False
    assert word.DisplayAlerts == 0
    assert word.Documents.open_arguments == (
        str(source.resolve()),
        True,
        False,
        False,
    )
    assert document.export_arguments == (str(result), 17)
    assert document.closed is True
    assert word.quit_called is True
    assert pythoncom.initialized == 1
    assert pythoncom.uninitialized == 1


def test_convert_docx_to_pdf_closes_word_after_export_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "contract.docx"
    source.write_bytes(b"test docx")
    pythoncom = FakePythonCom()
    document = FakeDocument(fail=True)
    word = FakeWord(document)
    client = SimpleNamespace(DispatchEx=lambda name: word)

    monkeypatch.setattr(pdf_utils, "get_pdf_converter_status", _available_status)
    monkeypatch.setattr(pdf_utils, "_load_word_automation", lambda: (pythoncom, client))

    with pytest.raises(pdf_utils.DocxToPdfConversionError) as exc_info:
        pdf_utils.convert_docx_to_pdf(source)

    assert "simulated Word export failure" in str(exc_info.value)
    assert document.closed is True
    assert word.quit_called is True
    assert pythoncom.uninitialized == 1


def test_convert_docx_to_pdf_reports_unavailable_converter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "contract.docx"
    source.write_bytes(b"test docx")
    unavailable = pdf_utils.PdfConverterStatus(
        available=False,
        converter="Microsoft Word",
        executable=None,
        error="Word is unavailable",
    )
    monkeypatch.setattr(pdf_utils, "get_pdf_converter_status", lambda: unavailable)

    with pytest.raises(pdf_utils.PdfConverterUnavailableError, match="Word is unavailable"):
        pdf_utils.convert_docx_to_pdf(source)


def test_convert_docx_to_pdf_uses_libreoffice_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Sample Contract.docx"
    source.write_bytes(b"test docx")
    output_dir = tmp_path / "pdfs"
    status = pdf_utils.PdfConverterStatus(
        available=True,
        converter=pdf_utils.LIBREOFFICE_CONVERTER_NAME,
        executable="/usr/bin/soffice",
    )
    monkeypatch.setattr(pdf_utils, "get_pdf_converter_status", lambda: status)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append((command, kwargs))
        outdir = Path(command[command.index("--outdir") + 1])
        source_path = Path(command[-1])
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / f"{source_path.stem}.pdf").write_bytes(b"%PDF-1.7\nlibreoffice")
        return SimpleNamespace(returncode=0, stdout="converted", stderr="")

    monkeypatch.setattr(pdf_utils.subprocess, "run", fake_run)

    result = pdf_utils.convert_docx_to_pdf(source, output_dir)

    assert result == output_dir.resolve() / "Sample Contract.pdf"
    assert result.read_bytes().startswith(b"%PDF")
    assert calls
    command, kwargs = calls[0]
    assert command == [
        "/usr/bin/soffice",
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir.resolve()),
        str(source.resolve()),
    ]
    assert kwargs["check"] is False
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 120


def test_convert_docx_to_pdf_reports_libreoffice_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "contract.docx"
    source.write_bytes(b"test docx")
    status = pdf_utils.PdfConverterStatus(
        available=True,
        converter=pdf_utils.LIBREOFFICE_CONVERTER_NAME,
        executable="/usr/bin/soffice",
    )
    monkeypatch.setattr(pdf_utils, "get_pdf_converter_status", lambda: status)
    monkeypatch.setattr(
        pdf_utils.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="simulated LibreOffice failure",
        ),
    )

    with pytest.raises(pdf_utils.DocxToPdfConversionError) as exc_info:
        pdf_utils.convert_docx_to_pdf(source)

    assert "simulated LibreOffice failure" in str(exc_info.value)


def test_convert_docx_to_pdf_validates_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="DOCX file was not found"):
        pdf_utils.convert_docx_to_pdf(tmp_path / "missing.docx")

    wrong_extension = tmp_path / "contract.txt"
    wrong_extension.write_text("not a docx", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Expected a \.docx file"):
        pdf_utils.convert_docx_to_pdf(wrong_extension)


def test_find_microsoft_word_prefers_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "WINWORD.EXE"
    configured.write_bytes(b"word")
    monkeypatch.setenv("MICROSOFT_WORD_PATH", str(configured))
    monkeypatch.setattr(pdf_utils.shutil, "which", lambda command: None)

    assert pdf_utils.find_microsoft_word() == str(configured.resolve())


def test_find_microsoft_word_checks_registered_then_standard_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard = tmp_path / "Microsoft Office" / "WINWORD.EXE"
    standard.parent.mkdir()
    standard.write_bytes(b"word")
    monkeypatch.delenv("MICROSOFT_WORD_PATH", raising=False)
    monkeypatch.setattr(pdf_utils.shutil, "which", lambda command: None)
    monkeypatch.setattr(
        pdf_utils,
        "_registered_microsoft_word_paths",
        lambda: (tmp_path / "missing.exe",),
    )
    monkeypatch.setattr(pdf_utils, "_standard_microsoft_word_paths", lambda: (standard,))

    assert pdf_utils.find_microsoft_word() == str(standard.resolve())


def test_find_libreoffice_prefers_configured_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "soffice"
    configured.write_bytes(b"libreoffice")
    monkeypatch.setenv("LIBREOFFICE_PATH", str(configured))
    monkeypatch.setattr(pdf_utils.shutil, "which", lambda command: None)

    assert pdf_utils.find_libreoffice() == str(configured.resolve())


def test_find_libreoffice_checks_path_then_standard_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standard = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    standard.parent.mkdir(parents=True)
    standard.write_bytes(b"libreoffice")
    monkeypatch.delenv("LIBREOFFICE_PATH", raising=False)
    monkeypatch.setattr(pdf_utils.shutil, "which", lambda command: None)
    monkeypatch.setattr(pdf_utils, "_standard_libreoffice_paths", lambda: (standard,))

    assert pdf_utils.find_libreoffice() == str(standard.resolve())


@pytest.mark.skipif(os.name != "nt", reason="Microsoft Word automation is Windows-only")
def test_pdf_converter_status_reports_word_without_starting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    word_path = r"C:\Program Files\Microsoft Office\WINWORD.EXE"
    monkeypatch.setattr(pdf_utils, "_load_word_automation", lambda: (object(), object()))
    monkeypatch.setattr(pdf_utils, "find_microsoft_word", lambda: word_path)

    status = pdf_utils.get_pdf_converter_status()

    assert status.available is True
    assert status.converter == "Microsoft Word"
    assert status.executable == word_path
    assert status.error is None


def test_pdf_converter_status_reports_libreoffice_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    libreoffice_path = "/usr/bin/soffice"
    monkeypatch.setattr(pdf_utils.os, "name", "posix")
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: libreoffice_path)

    status = pdf_utils.get_pdf_converter_status()

    assert status.available is True
    assert status.converter == pdf_utils.LIBREOFFICE_CONVERTER_NAME
    assert status.executable == libreoffice_path
    assert status.error is None


def test_pdf_converter_status_reports_unavailable_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf_utils.os, "name", "posix")
    monkeypatch.setattr(pdf_utils, "find_libreoffice", lambda: None)

    status = pdf_utils.get_pdf_converter_status()

    assert status.available is False
    assert status.converter == pdf_utils.PDF_CONVERTER_NAME
    assert status.executable is None
    assert "LibreOffice" in (status.error or "")
