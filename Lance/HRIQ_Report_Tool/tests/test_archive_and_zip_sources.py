import json
import zipfile
from pathlib import Path

import pytest

from Lance.HRIQ_Report_Tool.parser.batch_parser import parse_new_or_changed, parse_zip_new_or_changed
from Lance.HRIQ_Report_Tool.parser.rdl_parser import parse_rdl_content
from Lance.HRIQ_Report_Tool.parser.sources import ZipLimits, ZipRdlSource
from Lance.HRIQ_Report_Tool.services.archive_service import create_rdl_archive, verify_rdl_archive
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary


def _zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)


def test_archive_preserves_nested_rdl_only_and_hash(tmp_path: Path, sample_rdl: str) -> None:
    raw = tmp_path / "raw"
    archives = tmp_path / "archives"
    report = raw / "CLAIMS" / "PreClaimForm.rdl"
    report.parent.mkdir(parents=True)
    report.write_text(sample_rdl, encoding="utf-8")
    (raw / "ignored.sql").write_text("SELECT 1", encoding="utf-8")
    (raw / "old.zip").write_bytes(b"not a zip")
    result = create_rdl_archive(raw, archives)
    count, manifest = verify_rdl_archive(result.archive_path)
    with zipfile.ZipFile(result.archive_path) as archive:
        assert set(archive.namelist()) == {"CLAIMS/PreClaimForm.rdl", "manifest.json"}
    assert count == result.report_count == 1
    assert manifest["archive_sha256"] is None
    assert result.sidecar_path.exists() and result.sha256 in result.sidecar_path.read_text()


def test_empty_archive_source_rejected_and_temp_cleaned(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    archives = tmp_path / "archives"
    with pytest.raises(ValueError):
        create_rdl_archive(raw, archives)
    assert not list(archives.glob("*.tmp")) if archives.exists() else True


@pytest.mark.parametrize("name", ["../escape.rdl", "/absolute.rdl", "C:/drive.rdl", "//server/share.rdl"])
def test_zip_rejects_unsafe_members(tmp_path: Path, sample_rdl: str, name: str) -> None:
    path = tmp_path / "unsafe.zip"
    _zip(path, [(name, sample_rdl.encode())])
    with pytest.raises(ValueError):
        list(ZipRdlSource(path).iter_rdl_entries())


def test_zip_rejects_duplicates_oversize_and_ratio(tmp_path: Path, sample_rdl: str) -> None:
    duplicate = tmp_path / "duplicate.zip"
    _zip(duplicate, [("A.rdl", sample_rdl.encode()), ("a.rdl", sample_rdl.encode())])
    with pytest.raises(ValueError, match="Duplicate"):
        list(ZipRdlSource(duplicate).iter_rdl_entries())
    normal = tmp_path / "normal.zip"
    _zip(normal, [("A.rdl", sample_rdl.encode())])
    with pytest.raises(ValueError, match="size limit"):
        list(ZipRdlSource(normal, ZipLimits(max_rdl_size_bytes=10)).iter_rdl_entries())
    with pytest.raises(ValueError, match="compression ratio"):
        list(ZipRdlSource(normal, ZipLimits(max_compression_ratio=1)).iter_rdl_entries())


def test_direct_zip_parse_no_extraction_hierarchy_incremental_and_dedup(tmp_path: Path, sample_rdl: str) -> None:
    archive = tmp_path / "reports.zip"
    _zip(archive, [("CLAIMS/PreClaimForm.rdl", sample_rdl.encode()), ("manifest.json", b"{}")])
    source = ZipRdlSource(archive)
    entry = next(iter(source.iter_rdl_entries()))
    with source.open_entry(entry) as stream:
        parsed = parse_rdl_content(stream.read(), entry.logical_path, source_type="zip", source_archive=str(archive))
    assert parsed["source_member"] == "CLAIMS/PreClaimForm.rdl"
    assert not (tmp_path / "CLAIMS").exists()

    library = ReportLibrary(tmp_path / "state" / "reports.db")
    parsed_root = tmp_path / "parsed"
    first = parse_zip_new_or_changed(archive, parsed_root, library)
    second = parse_zip_new_or_changed(archive, parsed_root, library)
    assert (first.parsed, second.skipped) == (1, 1)
    assert (parsed_root / "CLAIMS" / "PreClaimForm_schema.json").exists()

    raw = tmp_path / "raw"
    directory_report = raw / "CLAIMS" / "PreClaimForm.rdl"
    directory_report.parent.mkdir(parents=True)
    directory_report.write_text(sample_rdl, encoding="utf-8")
    directory = parse_new_or_changed(raw, parsed_root, library)
    zip_again = parse_zip_new_or_changed(archive, parsed_root, library)
    assert directory.parsed == 1
    assert zip_again.skipped == 1
    assert library.get_report("CLAIMS/PreClaimForm.rdl")["source_type"] == "directory"
