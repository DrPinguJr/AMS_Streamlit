from __future__ import annotations

import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from Contracts.generators import cfs_generator


class ProgressRecorder:
    def __init__(self) -> None:
        self.updates: list[tuple[float, str]] = []

    def progress(self, value: float, text: str) -> None:
        self.updates.append((value, text))


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (datetime.date(2026, 7, 30), datetime.date(2026, 7, 31)),
        (datetime.date(2026, 7, 31), datetime.date(2026, 7, 31)),
        (datetime.date(2026, 4, 1), datetime.date(2026, 4, 30)),
        (datetime.date(2028, 2, 10), datetime.date(2028, 2, 29)),
    ],
)
def test_end_of_month(selected: datetime.date, expected: datetime.date) -> None:
    assert cfs_generator.end_of_month(selected) == expected


def test_contract_context_preserves_a_manually_selected_end_date() -> None:
    context = cfs_generator.build_contract_context(
        agreement_date=datetime.date(2026, 7, 30),
        contractor_name="Example Person",
        nric="S1234567A",
        residential_address="1 Example Street",
        start_date=datetime.date(2026, 7, 30),
        end_date=datetime.date(2026, 7, 30),
        service_start_time=datetime.time(14, 0),
        service_end_time=datetime.time(17, 0),
        service_fee=20,
    )

    assert context["end_date"] == "30 July 2026"


def test_bulk_generation_keeps_successes_after_a_row_failure_and_cleans_temp_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contractors = pd.DataFrame(
        [
            {"Full Name": "Same Name", "NRIC": "S0000001A", "Residential Address": "Address 1"},
            {"Full Name": "Failed Person", "NRIC": "S0000002B", "Residential Address": "Address 2"},
            {"Full Name": "Same Name", "NRIC": "S0000003C", "Residential Address": "Address 3"},
        ]
    )
    row_directories: list[Path] = []

    monkeypatch.setattr(
        cfs_generator,
        "generate_cfs_docx",
        lambda context: BytesIO(b"rendered docx"),
    )
    monkeypatch.setattr(cfs_generator, "ensure_no_unresolved_placeholders", lambda content: None)

    def fake_convert(docx_path: Path, output_directory: Path) -> Path:
        docx_path = Path(docx_path)
        output_directory = Path(output_directory)
        assert docx_path.is_file()
        assert docx_path.parent == output_directory
        row_directories.append(output_directory)
        if docx_path.stem == "contract_2":
            raise RuntimeError("simulated conversion failure")
        pdf_path = output_directory / f"{docx_path.stem}.pdf"
        pdf_path.write_bytes(f"%PDF-{docx_path.stem}".encode())
        return pdf_path

    monkeypatch.setattr(cfs_generator, "convert_docx_to_pdf", fake_convert)
    progress = ProgressRecorder()

    result = cfs_generator.build_bulk_contract_batch(
        contractors=contractors,
        agreement_date=datetime.date(2026, 7, 30),
        start_date=datetime.date(2026, 7, 30),
        end_date=datetime.date(2026, 7, 30),
        service_start_time=datetime.time(14, 0),
        service_end_time=datetime.time(17, 0),
        service_fee=20,
        progress=progress,
    )

    assert result.successful_count == 2
    assert len(result.failures) == 1
    assert result.failures[0].row_number == 2
    assert result.failures[0].identifier == "Failed Person"
    assert result.failures[0].exception_type == "RuntimeError"
    assert result.failures[0].message == "simulated conversion failure"
    assert result.zip_bytes is not None

    with ZipFile(BytesIO(result.zip_bytes)) as archive:
        assert archive.namelist() == [
            "AMS - CFS - REB - Same Name.pdf",
            "AMS - CFS - REB - Same Name (2).pdf",
        ]
        assert archive.read(archive.namelist()[0]).startswith(b"%PDF")
        assert archive.read(archive.namelist()[1]).startswith(b"%PDF")

    assert progress.updates[-1][0] == 1
    assert len(row_directories) == 3
    assert all(not directory.exists() for directory in row_directories)
