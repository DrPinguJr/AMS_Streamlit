from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from Lance.HRIQ_Report_Tool.scraper.models import CatalogItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS ssrs_catalog_items (
    item_id TEXT PRIMARY KEY, name TEXT NOT NULL, remote_path TEXT NOT NULL,
    item_type TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0,
    modified_at TEXT, parent_id TEXT, is_linked INTEGER, etag TEXT,
    response_shape_json TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ssrs_download_state (
    item_id TEXT PRIMARY KEY, remote_path TEXT NOT NULL, local_relative_path TEXT NOT NULL,
    modified_at TEXT, etag TEXT, last_successful_hash TEXT,
    status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT, last_attempted_at TEXT, last_completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ssrs_download_status ON ssrs_download_state(status);
CREATE TABLE IF NOT EXISTS ssrs_crawl_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
    completed_at TEXT, status TEXT NOT NULL, found INTEGER NOT NULL DEFAULT 0,
    downloaded INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0, auth_mode TEXT, rest_status TEXT
);
CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CrawlStateStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def begin_run(self, auth_mode: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO ssrs_crawl_runs(started_at,status,auth_mode) VALUES(?, 'Running', ?)",
                (_now(), auth_mode),
            )
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, *, found=0, downloaded=0, skipped=0, failed=0, rest_status="") -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE ssrs_crawl_runs SET completed_at=?, status=?, found=?, downloaded=?,
                   skipped=?, failed=?, rest_status=? WHERE run_id=?""",
                (_now(), status, found, downloaded, skipped, failed, rest_status, run_id),
            )

    def upsert_catalog(self, items: Iterable[CatalogItem]) -> None:
        now = _now()
        with self._connect() as connection:
            connection.executemany(
                """INSERT INTO ssrs_catalog_items(
                       item_id,name,remote_path,item_type,hidden,modified_at,parent_id,is_linked,
                       etag,response_shape_json,last_seen_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(item_id) DO UPDATE SET name=excluded.name,
                       remote_path=excluded.remote_path,item_type=excluded.item_type,
                       hidden=excluded.hidden,modified_at=excluded.modified_at,
                       parent_id=excluded.parent_id,is_linked=excluded.is_linked,
                       etag=excluded.etag,response_shape_json=excluded.response_shape_json,
                       last_seen_at=excluded.last_seen_at""",
                [
                    (
                        item.item_id, item.name, item.path, item.item_type, int(item.hidden),
                        item.modified_at, item.parent_id,
                        None if item.is_linked is None else int(item.is_linked), item.etag,
                        json.dumps(item.raw_shape), now,
                    ) for item in items if item.item_id
                ],
            )

    def prepare_downloads(self, rows: Iterable[tuple[CatalogItem, str]], retry_limit: int = 3) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE ssrs_download_state SET status='Pending', last_error='Interrupted before completion' WHERE status='Downloading'"
            )
            for item, relative in rows:
                existing = connection.execute(
                    "SELECT * FROM ssrs_download_state WHERE item_id=?", (item.item_id,)
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """INSERT INTO ssrs_download_state(
                           item_id,remote_path,local_relative_path,modified_at,etag,status
                           ) VALUES(?,?,?,?,?,'Pending')""",
                        (item.item_id, item.path, relative, item.modified_at, item.etag),
                    )
                    continue
                changed = (
                    str(existing["remote_path"]) != item.path
                    or (item.modified_at is not None and existing["modified_at"] != item.modified_at)
                    or (item.etag is not None and existing["etag"] != item.etag)
                )
                status = str(existing["status"])
                attempts = int(existing["attempt_count"])
                if changed or status in {"Pending", "Cancelled"} or (status == "Failed" and attempts < retry_limit):
                    status = "Pending"
                connection.execute(
                    """UPDATE ssrs_download_state SET remote_path=?,local_relative_path=?,
                       modified_at=?,etag=?,status=?,last_error=CASE WHEN ? THEN NULL ELSE last_error END,
                       attempt_count=CASE WHEN ? THEN 0 ELSE attempt_count END
                       WHERE item_id=?""",
                    (item.path, relative, item.modified_at, item.etag, status, int(changed), int(changed), item.item_id),
                )

    def pending(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ssrs_download_state WHERE status='Pending' ORDER BY remote_path COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_downloading(self, item_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE ssrs_download_state SET status='Downloading',attempt_count=attempt_count+1,
                   last_attempted_at=?,last_error=NULL WHERE item_id=?""",
                (_now(), item_id),
            )

    def mark_success(self, item_id: str, status: str, digest: str) -> None:
        stored_status = "Skipped" if status.casefold() == "skipped" else "Downloaded"
        with self._connect() as connection:
            connection.execute(
                """UPDATE ssrs_download_state SET status=?,last_successful_hash=?,
                   last_completed_at=?,last_error=NULL WHERE item_id=?""",
                (stored_status, digest, _now(), item_id),
            )

    def mark_failed(self, item_id: str, error: str, *, permanent: bool = False, retry_limit: int = 3) -> None:
        safe_error = error[:1000]
        with self._connect() as connection:
            if permanent:
                connection.execute(
                    "UPDATE ssrs_download_state SET status='Failed',attempt_count=?,last_error=? WHERE item_id=?",
                    (retry_limit, safe_error, item_id),
                )
            else:
                connection.execute(
                    "UPDATE ssrs_download_state SET status='Failed',last_error=? WHERE item_id=?",
                    (safe_error, item_id),
                )

    def mark_cancelled(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE ssrs_download_state SET status='Cancelled',last_error='Cancelled by user' WHERE status='Downloading'"
            )

    def set_value(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_value(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
        return default if row is None else str(row["value"])
