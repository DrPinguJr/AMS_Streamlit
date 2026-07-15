from pathlib import Path

from Lance.HRIQ_Report_Tool.scraper.crawler import extract_ssrs_links
from Lance.HRIQ_Report_Tool.scraper.downloader import remote_path_to_local
from Lance.HRIQ_Report_Tool.scraper.ssrs_client import normalize_portal_base_url


FIXTURES = Path(__file__).parent / "fixtures"


def test_portal_normalisation_and_virtual_directory() -> None:
    assert normalize_portal_base_url("https://server/Reports/") == "https://server/Reports/"
    assert normalize_portal_base_url("https://server/Reports/browse/GOLDBELL") == "https://server/Reports/"
    assert normalize_portal_base_url("https://server") == "https://server/Reports/"


def test_ssrs_tile_extraction_rejects_unrelated_links() -> None:
    html = (FIXTURES / "ssrs_folder_page.html").read_text(encoding="utf-8")
    folders, reports = extract_ssrs_links(html, "https://server/Reports/")
    assert folders == [
        "https://server/Reports/browse/GOLDBELL/CLAIMS",
        "https://server/Reports/browse/GOLDBELL/ReportBuilder_Reports",
    ]
    assert reports == [("https://server/Reports/report/GOLDBELL/PreClaimForm", "PreClaimForm")]
    assert all("microsoft.com" not in value for value in folders + [item[0] for item in reports])


def test_nested_links_are_decoded_and_deduplicated() -> None:
    html = (FIXTURES / "ssrs_nested_folder_page.html").read_text(encoding="utf-8")
    folders, reports = extract_ssrs_links(html + html, "https://server/Reports/")
    assert folders == ["https://server/Reports/browse/GOLDBELL/ReportBuilder_Reports/LEAVE"]
    assert reports[0][0].endswith("/Monthly%20Leave") or reports[0][0].endswith("/Monthly Leave")


def test_remote_path_mapping_preserves_hierarchy_and_windows_safety(tmp_path: Path) -> None:
    target = remote_path_to_local(
        tmp_path, "/GOLDBELL/ReportBuilder_Reports/LEAVE/Monthly%20Leave", "GOLDBELL",
    )
    assert target == tmp_path / "ReportBuilder_Reports" / "LEAVE" / "Monthly Leave.rdl"
    reserved = remote_path_to_local(tmp_path, "/GOLDBELL/CON/AUX", "GOLDBELL")
    assert reserved.relative_to(tmp_path).parts == ("_CON", "_AUX.rdl")
    long_target = remote_path_to_local(
        tmp_path, "/GOLDBELL/" + "/".join(["Very Long Folder Name " * 8] * 5) + "/Report", "GOLDBELL",
    )
    assert len(str(long_target)) <= 245
