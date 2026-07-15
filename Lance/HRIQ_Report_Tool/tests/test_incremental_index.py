from pathlib import Path

from Lance.HRIQ_Report_Tool.parser.batch_parser import parse_new_or_changed
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary


def test_incremental_parser_preserves_structure_and_indexes_reports(tmp_path: Path, sample_rdl: str) -> None:
    raw = tmp_path / "raw"
    parsed = tmp_path / "parsed"
    source = raw / "Claims" / "PreClaimForm.rdl"
    source.parent.mkdir(parents=True)
    source.write_text(sample_rdl, encoding="utf-8")
    library = ReportLibrary(tmp_path / "state" / "reports.db")

    first = parse_new_or_changed(raw, parsed, library)
    second = parse_new_or_changed(raw, parsed, library)

    assert (parsed / "Claims" / "PreClaimForm_schema.json").exists()
    sql_path = parsed / "Claims" / "PreClaimForm_Claims.sql"
    assert sql_path.exists()
    assert sql_path.read_text(encoding="utf-8").endswith(
        "SELECT ClaimID, Amount\nFROM dbo.Claims\nWHERE CompCode = @CompCode"
    )
    assert (first.parsed, first.skipped) == (1, 0)
    assert (second.parsed, second.skipped) == (0, 1)
    matches = library.search("claim")
    assert len(matches) == 1
    assert matches[0]["dataset_count"] == 1
    assert matches[0]["field_count"] == 2

    source.write_text(sample_rdl.replace("Sanitized claims", "Updated claims"), encoding="utf-8")
    changed = parse_new_or_changed(raw, parsed, library)
    assert changed.parsed == 1

    source.unlink()
    removed = parse_new_or_changed(raw, parsed, library)
    assert removed.removed == 1
    assert library.search() == []
