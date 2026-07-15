from pathlib import Path

from Lance.HRIQ_Report_Tool.scraper.models import CatalogItem
from Lance.HRIQ_Report_Tool.services.crawl_state import CrawlStateStore


def _item(modified="2026-01-01"):
    return CatalogItem("id-1", "Report", "/ROOT/Report", "Report", modified_at=modified)


def test_interrupted_failed_changed_and_completed_resume(tmp_path: Path) -> None:
    store = CrawlStateStore(tmp_path / "state.db")
    store.prepare_downloads([(_item(), "Report.rdl")])
    store.mark_downloading("id-1")
    store.prepare_downloads([(_item(), "Report.rdl")])
    assert store.pending()[0]["status"] == "Pending"

    store.mark_downloading("id-1")
    store.mark_success("id-1", "downloaded", "abc")
    store.prepare_downloads([(_item(), "Report.rdl")])
    assert store.pending() == []

    store.prepare_downloads([(_item("2026-02-01"), "Report.rdl")])
    assert len(store.pending()) == 1
    store.mark_downloading("id-1")
    store.mark_failed("id-1", "transient")
    store.prepare_downloads([(_item("2026-02-01"), "Report.rdl")], retry_limit=3)
    assert len(store.pending()) == 1


def test_permanent_failure_does_not_retry(tmp_path: Path) -> None:
    store = CrawlStateStore(tmp_path / "state.db")
    store.prepare_downloads([(_item(), "Report.rdl")])
    store.mark_downloading("id-1")
    store.mark_failed("id-1", "forbidden", permanent=True, retry_limit=3)
    store.prepare_downloads([(_item(), "Report.rdl")], retry_limit=3)
    assert store.pending() == []
