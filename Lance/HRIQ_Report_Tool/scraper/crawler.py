from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from time import sleep
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By

from Lance.HRIQ_Report_Tool.scraper import selectors
from Lance.HRIQ_Report_Tool.scraper.auth import browser_session, requests_session_from_browser, windows_session
from Lance.HRIQ_Report_Tool.scraper.downloader import remote_path_to_local
from Lance.HRIQ_Report_Tool.scraper.models import CatalogItem
from Lance.HRIQ_Report_Tool.scraper.ssrs_client import SSRSClient, SSRSClientError, normalize_portal_base_url
from Lance.HRIQ_Report_Tool.services.crawl_state import CrawlStateStore


LOGGER = logging.getLogger(__name__)


def _normalized_url(base: str, href: str) -> str:
    joined = urljoin(base, href)
    parts = urlsplit(joined)
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), unquote(parts.path), "", ""))


def extract_ssrs_links(html: str, page_url: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Extract only verified SSRS folder/report tile links."""
    soup = BeautifulSoup(html, "html.parser")
    base_tag = soup.select_one("base[href]")
    base = urljoin(page_url, base_tag.get("href")) if base_tag else page_url
    portal = normalize_portal_base_url(base)
    portal_host = urlsplit(portal).netloc.casefold()
    folders: list[str] = []
    reports: list[tuple[str, str]] = []
    for anchor in soup.select("folder-tile a.tile[href]"):
        href = str(anchor.get("href", ""))
        if not (href.startswith("browse/") or "/browse/" in href):
            continue
        url = _normalized_url(base, href)
        if urlsplit(url).netloc.casefold() == portal_host and "/browse/" in urlsplit(url).path.casefold():
            folders.append(url)
    for anchor in soup.select("report-tile a.tile[href]"):
        href = str(anchor.get("href", ""))
        if not (href.startswith("report/") or "/report/" in href):
            continue
        url = _normalized_url(base, href)
        if urlsplit(url).netloc.casefold() != portal_host or "/report/" not in urlsplit(url).path.casefold():
            continue
        name_node = anchor.select_one(selectors.TILE_NAME)
        name = name_node.get_text(" ", strip=True) if name_node else unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        reports.append((url, name))
    return list(dict.fromkeys(folders)), list(dict.fromkeys(reports))


def discover_dom_catalog(driver, portal_url: str, stop_event: Event, update) -> tuple[set[str], set[str], set[str]]:
    queue = deque([normalize_portal_base_url(portal_url)])
    visited_folder_urls: set[str] = set()
    discovered_report_urls: set[str] = set()
    failed_folder_urls: set[str] = set()
    while queue and not stop_event.is_set():
        folder_url = queue.popleft()
        if folder_url in visited_folder_urls:
            continue
        visited_folder_urls.add(folder_url)
        try:
            driver.get(folder_url)
            sleep(0.4)
            folder_links, report_links = extract_ssrs_links(driver.page_source, folder_url)
            update(current_folder=urlsplit(folder_url).path, files_found=len(discovered_report_urls) + len(report_links))
            for child in folder_links:
                if child not in visited_folder_urls:
                    queue.append(child)
            discovered_report_urls.update(url for url, _name in report_links)
        except Exception:
            LOGGER.exception("SSRS folder traversal failed")
            failed_folder_urls.add(folder_url)
    return visited_folder_urls, discovered_report_urls, failed_folder_urls


def capture_sanitized_api_patterns(driver) -> list[str]:
    patterns: set[str] = set()
    try:
        for record in driver.get_log("performance"):
            message = json.loads(record["message"])["message"]
            if message.get("method") != "Network.requestWillBeSent":
                continue
            url = message.get("params", {}).get("request", {}).get("url", "")
            path = urlsplit(url).path
            if "/api/v2.0/" in path.casefold():
                sanitized = path
                sanitized = sanitized.replace(urlsplit(url).path.split("Reports(", 1)[-1].split(")", 1)[0], "{report-id}") if "Reports(" in path else sanitized
                patterns.add(sanitized)
    except Exception:
        LOGGER.info("Browser performance log capture is unavailable")
    return sorted(patterns)


def try_context_menu_download(driver) -> bool:
    """Last-resort, non-destructive SSRS download action for development verification."""
    menus = driver.find_elements(By.CSS_SELECTOR, selectors.CONTEXT_MENU)
    if not menus:
        return False
    menus[0].click()
    sleep(0.25)
    downloads = driver.find_elements(By.CSS_SELECTOR, selectors.DOWNLOAD_MENU_ITEMS)
    if not downloads:
        return False
    downloads[0].click()
    return True


def _targets(items: list[CatalogItem], raw_root: Path, root_segment: str) -> list[tuple[CatalogItem, Path]]:
    result: list[tuple[CatalogItem, Path]] = []
    used: dict[str, str] = {}
    for item in sorted(items, key=lambda value: value.path.casefold()):
        target = remote_path_to_local(raw_root, item.path, root_segment)
        key = str(target).casefold()
        if key in used and used[key] != item.path:
            suffix = hashlib.sha256(item.path.encode("utf-8")).hexdigest()[:8]
            target = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
        used[str(target).casefold()] = item.path
        result.append((item, target))
    return result


def crawl_portal(
    portal_url, username, password, raw_root, stop_event: Event, update,
    download_workers: int = 3, *, auth_mode: str = "automatic", headless: bool = True,
    development_mode: bool = False, root_segment: str = "GOLDBELL",
    state_path: Path | None = None, retry_limit: int = 3,
) -> None:
    raw_root = Path(raw_root)
    store = CrawlStateStore(state_path or raw_root.parent / "ssrs_state.db")
    run_id = store.begin_run(auth_mode)
    driver = None
    counters = {"found": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    rest_message = "Not tested"
    run_status = "Completed"
    try:
        if auth_mode == "current windows session":
            session = windows_session()
            update(log="Using the current Windows identity.")
        else:
            driver = browser_session(
                portal_url, raw_root, auth_mode, username, password, stop_event, update,
                headless=headless, development_mode=development_mode,
            )
            session = requests_session_from_browser(driver)
        store.set_value("portal_detected", "true")
        store.set_value("authentication_mode", auth_mode)
        client = SSRSClient(portal_url, session)
        status = client.test_api()
        rest_message = status.message
        store.set_value("rest_status", status.message)
        store.set_value("rest_base_url", status.rest_base_url)
        update(log=f"REST API: {status.message}")
        if not status.available:
            if driver is None:
                raise RuntimeError(f"REST API unavailable: {status.message} Use Interactive browser session for DOM discovery.")
            visited, reports, failed = discover_dom_catalog(driver, portal_url, stop_event, update)
            if development_mode and reports:
                driver.get(next(iter(reports)))
                sleep(1)
                patterns = capture_sanitized_api_patterns(driver)
                LOGGER.info("Sanitised SSRS API patterns: %s", patterns)
            counters["found"] = len(reports)
            if reports:
                update(log="REST is unavailable. SSRS report tiles were discovered, but a verified content endpoint is required before download.")
            if failed:
                update(errors=len(failed), log=f"Folder discovery failures: {len(failed)}")
            return

        catalog = client.enumerate_catalog()
        store.set_value("catalog_access", "true")
        store.upsert_catalog(catalog)
        prefix = f"/{root_segment.casefold()}/" if root_segment else "/"
        reports = [
            item for item in catalog
            if item.item_id and item.is_report and not item.hidden
            and (not root_segment or item.path.casefold().startswith(prefix))
        ]
        targets = _targets(reports, raw_root, root_segment)
        counters["found"] = len(targets)
        update(files_found=len(targets), log=f"Catalog reports found: {len(targets)}")
        store.prepare_downloads(
            [(item, target.relative_to(raw_root.resolve()).as_posix()) for item, target in targets],
            retry_limit,
        )
        item_map = {item.item_id: (item, target) for item, target in targets}
        pending = [row for row in store.pending() if row["item_id"] in item_map]
        if not pending:
            update(log="All catalog reports are unchanged.")
            return

        # Verify the content endpoint with exactly one report before starting workers.
        verification_index = next(
            (i for i, row in enumerate(pending) if item_map[row["item_id"]][0].name.casefold() == "preclaimform"), 0
        )
        verification = pending.pop(verification_index)

        def download_row(row: dict):
            item, target = item_map[row["item_id"]]
            store.mark_downloading(item.item_id)
            worker = client.clone()
            result = worker.download_report(item, target)
            store.mark_success(item.item_id, result.status, result.sha256)
            return item, result

        try:
            item, result = download_row(verification)
            store.set_value("report_content_access", "true")
            counters[result.status] += 1
            update(**{result.status: 1}, current_folder=str(Path(item.path).parent), log=f"Verified report content: {item.name}")
        except SSRSClientError as exc:
            store.mark_failed(verification["item_id"], str(exc), permanent=exc.permanent, retry_limit=retry_limit)
            counters["failed"] += 1
            update(errors=1, log=f"One-report verification failed: {exc}")
            raise RuntimeError("One-report REST verification failed; mass download was not started") from exc

        workers = max(1, min(download_workers, 8))
        transient_errors = 0
        while pending and not stop_event.is_set():
            batch, pending = pending[: workers * 2], pending[workers * 2 :]
            batch_transient = 0
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hriq-ssrs") as executor:
                futures = {executor.submit(download_row, row): row for row in batch}
                for future in as_completed(futures):
                    row = futures[future]
                    try:
                        item, result = future.result()
                        counters[result.status] += 1
                        update(**{result.status: 1}, current_folder=str(Path(item.path).parent), log=f"{result.status.title()}: {item.name}")
                    except SSRSClientError as exc:
                        transient_errors += int(not exc.permanent)
                        batch_transient += int(not exc.permanent)
                        store.mark_failed(row["item_id"], str(exc), permanent=exc.permanent, retry_limit=retry_limit)
                        counters["failed"] += 1
                        update(errors=1, log=f"Report failed: {exc}")
                    except Exception as exc:
                        batch_transient += 1
                        store.mark_failed(row["item_id"], str(exc), retry_limit=retry_limit)
                        counters["failed"] += 1
                        update(errors=1, log=f"Report failed: {exc}")
            if batch_transient >= workers and workers > 1:
                workers = max(1, workers // 2)
                update(log=f"Transient errors detected; concurrency reduced to {workers} worker(s).")
        if stop_event.is_set():
            store.mark_cancelled()
            update(log="Download stopped. Resume will continue unfinished reports.")
        else:
            update(log="Download complete.")
    except Exception:
        run_status = "Cancelled" if stop_event.is_set() else "Failed"
        raise
    finally:
        if driver is not None:
            driver.quit()
        store.finish_run(
            run_id, "Cancelled" if stop_event.is_set() else run_status,
            **counters, rest_status=rest_message,
        )
