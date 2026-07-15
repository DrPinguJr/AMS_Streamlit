from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread

from Lance.HRIQ_Report_Tool.services.crawl_state import CrawlStateStore


@dataclass
class JobState:
    running: bool = False
    current_folder: str = ""
    files_found: int = 0
    downloaded: int = 0
    skipped: int = 0
    errors: int = 0
    latest_archive: str = ""
    logs: list[str] = field(default_factory=list)


class DownloadJobManager:
    def __init__(self, state_path: Path):
        self._store = CrawlStateStore(state_path)
        self._state = JobState(latest_archive=self._store.get_value("latest_archive"))
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(
        self, portal_url, username, password, raw_root, download_workers=3, *,
        auth_mode="automatic", headless=True, development_mode=False,
        root_segment="GOLDBELL", state_path=None, create_zip_after=False,
        archive_dir: Path | None = None,
    ) -> bool:
        with self._lock:
            if self._state.running:
                return False
            latest = self._state.latest_archive
            self._state = JobState(running=True, latest_archive=latest, logs=["Starting SSRS download..."])
            self._stop_event.clear()
        from Lance.HRIQ_Report_Tool.scraper.crawler import crawl_portal

        def run():
            completed = False
            try:
                crawl_portal(
                    portal_url, username, password, raw_root, self._stop_event,
                    self.update, download_workers, auth_mode=auth_mode, headless=headless,
                    development_mode=development_mode, root_segment=root_segment,
                    state_path=state_path,
                )
                completed = not self._stop_event.is_set() and self.snapshot()["errors"] == 0
                if completed and create_zip_after and archive_dir is not None:
                    from Lance.HRIQ_Report_Tool.services.archive_service import create_rdl_archive
                    result = create_rdl_archive(Path(raw_root), archive_dir)
                    metadata = json.dumps(asdict(result), default=str)
                    self._store.set_value("latest_archive", str(result.archive_path))
                    self._store.set_value("latest_archive_result", metadata)
                    with self._lock:
                        self._state.latest_archive = str(result.archive_path)
                    self.update(log=f"ZIP ready: {result.archive_path.name}")
            except Exception as exc:
                self.update(errors=1, log=f"Download stopped with an error: {exc}")
            finally:
                with self._lock:
                    self._state.running = False

        self._thread = Thread(target=run, name="hriq-downloader", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self.update(log="Stop requested...")

    def update(self, *, current_folder=None, files_found=None, downloaded=0, skipped=0,
               errors=0, log=None) -> None:
        with self._lock:
            if current_folder is not None:
                self._state.current_folder = current_folder
            if files_found is not None:
                self._state.files_found = files_found
            self._state.downloaded += downloaded
            self._state.skipped += skipped
            self._state.errors += errors
            if log:
                self._state.logs = (self._state.logs + [log])[-200:]

    def snapshot(self) -> dict:
        with self._lock:
            return asdict(self._state)

    def set_latest_archive(self, path: Path) -> None:
        with self._lock:
            self._state.latest_archive = str(path)
