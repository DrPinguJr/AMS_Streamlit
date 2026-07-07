from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "whatsapp_messages.sqlite"
IMAGE_ROOT = DATA_DIR / "whatsapp_images"


def sanitize_filename(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    cleaned = cleaned.strip("._")
    return cleaned[:120] or "unknown"


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id TEXT PRIMARY KEY,
                chat_name TEXT NOT NULL,
                sender TEXT,
                direction TEXT,
                timestamp TEXT,
                text TEXT,
                has_image INTEGER NOT NULL DEFAULT 0,
                image_path TEXT,
                raw_metadata TEXT,
                captured_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def make_record_id(record: dict[str, Any]) -> str:
    stable_value = "|".join(
        [
            str(record.get("chat_name") or ""),
            str(record.get("sender") or ""),
            str(record.get("direction") or ""),
            str(record.get("timestamp") or ""),
            str(record.get("text") or ""),
            json.dumps(record.get("raw_metadata") or {}, sort_keys=True, default=str),
        ]
    )
    return hashlib.sha256(stable_value.encode("utf-8")).hexdigest()


def save_message_record(record: dict[str, Any]) -> bool:
    ensure_storage()
    prepared = dict(record)
    prepared.setdefault("id", make_record_id(prepared))
    prepared.setdefault("captured_at", datetime.now().isoformat(timespec="seconds"))
    raw_metadata = prepared.get("raw_metadata")
    if not isinstance(raw_metadata, str):
        raw_metadata = json.dumps(raw_metadata or {}, ensure_ascii=True, default=str)

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO whatsapp_messages (
                id, chat_name, sender, direction, timestamp, text, has_image,
                image_path, raw_metadata, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prepared["id"],
                prepared.get("chat_name") or "",
                prepared.get("sender") or "",
                prepared.get("direction") or "",
                prepared.get("timestamp") or "",
                prepared.get("text") or "",
                1 if prepared.get("has_image") else 0,
                prepared.get("image_path") or "",
                raw_metadata,
                prepared["captured_at"],
            ),
        )
        conn.commit()
        return cursor.rowcount > 0


def save_image_from_base64(base64_data: str, metadata: dict[str, Any]) -> Path:
    ensure_storage()
    if "," in base64_data[:80]:
        base64_data = base64_data.split(",", 1)[1]

    image_bytes = base64.b64decode(base64_data)
    digest = hashlib.sha256(image_bytes).hexdigest()[:16]
    chat_name = sanitize_filename(str(metadata.get("chat_name") or "chat"))
    sender = sanitize_filename(str(metadata.get("sender") or "sender"))
    timestamp = sanitize_filename(str(metadata.get("timestamp") or datetime.now().isoformat(timespec="seconds")))

    folder = IMAGE_ROOT / chat_name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{chat_name}_{sender}_{timestamp}_{digest}.png"
    path.write_bytes(image_bytes)
    return path


def load_recent_messages(limit: int = 100, chat_name: str | None = None) -> list[dict[str, Any]]:
    ensure_storage()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if chat_name:
            rows = conn.execute(
                """
                SELECT * FROM whatsapp_messages
                WHERE chat_name = ?
                ORDER BY captured_at DESC
                LIMIT ?
                """,
                (chat_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM whatsapp_messages
                ORDER BY captured_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]
