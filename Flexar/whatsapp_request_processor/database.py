"""SQLite persistence helpers for the prototype."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from .config import Settings, get_settings
from .migrations import SCHEMA_VERSION, run_migrations


LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


def to_db_time(value: datetime | str | None = None) -> str:
    """Convert timestamps to an ISO string stored in SQLite."""

    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def from_db_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Database:
    """One-connection-per-operation SQLite helper."""

    def __init__(self, settings: Settings | None = None, database_path: str | Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = Path(database_path) if database_path else self.settings.database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def execute_with_retry(self, operation: Callable[[sqlite3.Connection], T], attempts: int = 5) -> T:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(attempts):
            try:
                with self.connect() as conn:
                    return operation(conn)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError("Database operation failed")

    def init_db(self) -> None:
        """Create and migrate all tables needed by the prototype."""

        def op(conn: sqlite3.Connection) -> None:
            run_migrations(conn)

        self.execute_with_retry(op)

    def insert_event(
        self,
        *,
        external_message_id: str,
        payload_batch_id: str | None = None,
        correlation_id: str | None = None,
        quoted_message_id: str | None = None,
        reply_message_id: str | None = None,
        sender_id: str,
        sender_display_name: str = "",
        chat_id: str,
        chat_display_name: str = "",
        event_type: str,
        text_content: str,
        received_at: datetime,
        raw_payload: dict[str, Any],
        processing_status: str,
        source: str = "SIMULATOR",
        classification: str = "UNSUPPORTED",
        detected_licence_plate: str | None = None,
        assigned_container_uuid: str | None = None,
        match_reason: str | None = None,
        included_in_outbound: bool = True,
    ) -> tuple[int | None, bool]:
        """Insert an incoming event, returning (event_id, duplicate)."""

        def op(conn: sqlite3.Connection) -> tuple[int | None, bool]:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO incoming_events (
                        external_message_id, payload_batch_id, correlation_id, quoted_message_id,
                        reply_message_id, sender_id, sender_display_name, chat_id, chat_display_name,
                        event_type, text_content, received_at, raw_payload_json, source,
                        classification, processing_status, detected_licence_plate,
                        assigned_container_uuid, match_reason, included_in_outbound, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        external_message_id,
                        payload_batch_id,
                        correlation_id,
                        quoted_message_id,
                        reply_message_id,
                        sender_id,
                        sender_display_name,
                        chat_id,
                        chat_display_name,
                        event_type,
                        text_content,
                        to_db_time(received_at),
                        json.dumps(raw_payload, sort_keys=True),
                        source,
                        classification,
                        processing_status,
                        detected_licence_plate,
                        assigned_container_uuid,
                        match_reason,
                        1 if included_in_outbound else 0,
                        to_db_time(),
                    ),
                )
                return int(cur.lastrowid), False
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id FROM incoming_events WHERE external_message_id = ?",
                    (external_message_id,),
                ).fetchone()
                return (int(row["id"]) if row else None), True

        return self.execute_with_retry(op)

    def update_event_status(
        self,
        event_id: int,
        status: str,
        container_uuid: str | None = None,
        match_reason: str | None = None,
        classification: str | None = None,
        included_in_outbound: bool | None = None,
    ) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                UPDATE incoming_events
                SET processing_status = ?,
                    assigned_container_uuid = COALESCE(?, assigned_container_uuid),
                    match_reason = COALESCE(?, match_reason),
                    classification = COALESCE(?, classification),
                    included_in_outbound = COALESCE(?, included_in_outbound)
                WHERE id = ?
                """,
                (
                    status,
                    container_uuid,
                    match_reason,
                    classification,
                    None if included_in_outbound is None else 1 if included_in_outbound else 0,
                    event_id,
                ),
            )

        self.execute_with_retry(op)

    def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        def op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

        return self.execute_with_retry(op)

    def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        def op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

        return self.execute_with_retry(op)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute(sql, params)

        self.execute_with_retry(op)

    def execute_count(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        def op(conn: sqlite3.Connection) -> int:
            cur = conn.execute(sql, params)
            return int(cur.rowcount)

        return self.execute_with_retry(op)

    def get_dashboard_snapshot(self) -> dict[str, Any]:
        """Return a consistent read-only dashboard snapshot in one short transaction."""

        def _loads(value: str | None, default: Any) -> Any:
            if not value:
                return default
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default

        def _validation_report(row: dict[str, Any]) -> dict[str, Any]:
            missing = _loads(row.get("missing_fields_json"), [])
            warnings = _loads(row.get("warnings_json"), [])
            blockers = _loads(row.get("blockers_json"), [])
            labels = {
                "MISSING_SENDER": ("Rider identified", "Waiting for a rider identifier.", "Request identity"),
                "MISSING_CHAT": ("Chat identified", "Waiting for a chat identifier.", "Request identity"),
                "MISSING_LICENCE_PLATE": ("Licence plate detected", "Waiting for the rider to send the vehicle plate.", "Request identity"),
                "MISSING_IMAGES": ("Seven required images received", "More unique images are required.", "Evidence received"),
                "MISSING_ACTION": ("Lock/unlock action detected", "Waiting for a clear LOCKED or UNLOCKED instruction.", "Operational information"),
                "MISSING_LOCATION_REFERENCE": ("Location detected", "No address, station, deck, lot, bay or zone was detected.", "Operational information"),
                "MISSING_PARKING_POSITION": ("Parking position detected", "Waiting for a lot, bay, deck, level, zone, white-lot or station reference.", "Operational information"),
                "MISSING_MSCP_DECK": ("Deck or level for MSCP", "Deck or level missing for this MSCP.", "Operational information"),
                "NO_LOT_NUMBER": ("Lot number", "Optional - no numbered lot supplied.", "Operational information"),
                "MULTIPLE_LICENCE_PLATES": ("One licence plate only", row.get("manual_review_reason") or "Licence plate conflict.", "Automation safety"),
                "CONFLICTING_ACTION": ("One action only", row.get("manual_review_reason") or "Action conflict.", "Automation safety"),
                "AMBIGUOUS_CONTAINER_MATCH": ("Request matched safely", row.get("manual_review_reason") or "Ambiguous match.", "Automation safety"),
                "EXPIRED_CONTAINER": ("Container is active", "Expired or cancelled containers cannot auto-dispatch.", "Automation safety"),
                "ALREADY_DISPATCHED": ("Not already dispatched", "Outbound actions already exist for this request.", "Automation safety"),
            }
            passed_values = {
                "MISSING_SENDER": row.get("sender_id"),
                "MISSING_CHAT": row.get("chat_id"),
                "MISSING_LICENCE_PLATE": row.get("detected_licence_plate"),
                "MISSING_IMAGES": f"{row.get('image_count') or 0} / {self.settings.min_required_images} unique images",
                "MISSING_ACTION": row.get("detected_action"),
                "MISSING_LOCATION_REFERENCE": row.get("detected_location"),
                "MISSING_PARKING_POSITION": ", ".join(
                    part
                    for part in [
                        row.get("detected_deck"),
                        row.get("detected_level"),
                        row.get("detected_lot"),
                        row.get("detected_lot_range"),
                        row.get("detected_bay"),
                        row.get("detected_zone"),
                        row.get("detected_parking_type"),
                    ]
                    if part
                ),
            }
            all_codes = [
                "MISSING_SENDER",
                "MISSING_CHAT",
                "MISSING_LICENCE_PLATE",
                "MISSING_IMAGES",
                "MISSING_ACTION",
                "MISSING_LOCATION_REFERENCE",
                "MISSING_PARKING_POSITION",
                "MISSING_MSCP_DECK",
                "NO_LOT_NUMBER",
                "MULTIPLE_LICENCE_PLATES",
                "CONFLICTING_ACTION",
                "AMBIGUOUS_CONTAINER_MATCH",
                "EXPIRED_CONTAINER",
                "ALREADY_DISPATCHED",
            ]
            items = []
            for code in all_codes:
                label, explanation, section = labels[code]
                status = "PASSED"
                required = code != "NO_LOT_NUMBER"
                if code in missing:
                    status = "MISSING"
                elif code in blockers:
                    status = "BLOCKED"
                elif code in warnings:
                    status = "WARNING"
                    required = False
                elif code == "NO_LOT_NUMBER" and not row.get("detected_lot") and not row.get("detected_lot_range"):
                    status = "OPTIONAL"
                    required = False
                elif code == "MISSING_MSCP_DECK" and code not in missing:
                    status = "NOT_APPLICABLE" if not row.get("detected_parking_type") == "MSCP" else "PASSED"
                    required = row.get("detected_parking_type") == "MSCP"
                items.append(
                    {
                        "key": code,
                        "label": label,
                        "status": status,
                        "value": passed_values.get(code),
                        "explanation": explanation if status in {"MISSING", "BLOCKED", "WARNING", "OPTIONAL"} else "Check passed.",
                        "required": required,
                        "source_event_ids": [],
                        "section": section,
                    }
                )
            return {
                "container_uuid": row["container_uuid"],
                "items": items,
                "missing_required_fields": missing,
                "blockers": blockers,
                "warnings": warnings,
                "is_technically_complete": row.get("validation_status") == "PASSED",
                "auto_dispatch_eligible": bool(row.get("auto_dispatch_eligible")),
                "next_required_input": "; ".join(missing) if missing else "All required information received",
                "next_action": row.get("validation_summary") or "",
                "summary": row.get("validation_summary") or "",
                "story_steps": [],
            }

        def _waiting_for(row: dict[str, Any]) -> str:
            state = row.get("state")
            missing = _loads(row.get("missing_fields_json"), [])
            if state == "READY_WAITING_QUIET":
                dispatch_after = from_db_time(row.get("dispatch_after"))
                if dispatch_after:
                    remaining = max(0, int((dispatch_after - datetime.now(timezone.utc)).total_seconds()))
                    return "Nothing - sending now" if remaining == 0 else f"Messages to finish - sending in {remaining} seconds"
                return "Messages to finish"
            if state in {"NEEDS_REVIEW", "MANUAL_REVIEW"}:
                return f"Manual review: {row.get('manual_review_reason') or 'operator decision required'}"
            labels = {
                "MISSING_LICENCE_PLATE": "Licence plate",
                "MISSING_ACTION": "Lock/unlock instruction",
                "MISSING_LOCATION_REFERENCE": "Parking location",
                "MISSING_PARKING_POSITION": "Parking position",
                "MISSING_MSCP_DECK": "Deck or level",
            }
            parts: list[str] = []
            image_count = int(row.get("image_count") or 0)
            missing_images = max(0, int(self.settings.min_required_images) - image_count)
            for code in missing:
                if code == "MISSING_IMAGES":
                    if missing_images == 1:
                        parts.append("1 more image")
                    elif missing_images > 1:
                        parts.append(f"{missing_images} more images")
                elif code in labels:
                    parts.append(labels[code])
            if not parts:
                return "Messages to finish" if state == "DISPATCHING" else "Nothing"
            if len(parts) == 1:
                return parts[0]
            return ", ".join(parts[:-1]) + " and " + parts[-1]

        def _quiet_seconds(row: dict[str, Any]) -> int | None:
            dispatch_after = from_db_time(row.get("dispatch_after"))
            if not dispatch_after:
                return None
            return max(0, int((dispatch_after - datetime.now(timezone.utc)).total_seconds()))

        def op(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN")
            try:
                recent_events = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT * FROM incoming_events
                        ORDER BY id DESC
                        LIMIT 12
                        """
                    ).fetchall()
                ]
                containers = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT c.*,
                               GROUP_CONCAT(l.external_message_id, ', ') AS matched_event_ids,
                               COALESCE((SELECT MAX(a.id) FROM container_activity_log a WHERE a.container_uuid = c.container_uuid), 0) AS latest_activity_id
                        FROM request_containers c
                        LEFT JOIN request_event_links l ON l.container_uuid = c.container_uuid
                        WHERE c.deleted_at IS NULL
                          AND c.state NOT IN ('COMPLETED', 'CANCELLED')
                        GROUP BY c.id
                        ORDER BY
                          CASE c.state
                            WHEN 'MANUAL_REVIEW' THEN 1
                            WHEN 'WAITING_FOR_LP' THEN 2
                            WHEN 'WAITING_FOR_IMAGES' THEN 3
                            WHEN 'WAITING_FOR_ACTION' THEN 4
                            WHEN 'RECEIVING' THEN 5
                            WHEN 'INACTIVE' THEN 6
                            WHEN 'EXPIRED' THEN 7
                            ELSE 8
                          END,
                          c.updated_at DESC
                        """
                    ).fetchall()
                ]
                completed = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT c.*,
                               COALESCE((SELECT MAX(a.id) FROM container_activity_log a WHERE a.container_uuid = c.container_uuid), 0) AS latest_activity_id
                        FROM request_containers c
                        WHERE deleted_at IS NULL AND state = 'COMPLETED'
                        ORDER BY completed_at DESC, updated_at DESC
                        LIMIT 10
                        """
                    ).fetchall()
                ]
                outbound_actions = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT * FROM outbound_actions
                        ORDER BY id DESC
                        LIMIT 20
                        """
                    ).fetchall()
                ]
                outbound_by_container: dict[str, dict[str, str]] = {}
                for action in outbound_actions:
                    statuses = outbound_by_container.setdefault(action["container_uuid"], {})
                    statuses[action["action_type"]] = action["status"]
                activity_rows = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT * FROM container_activity_log
                        ORDER BY id DESC
                        LIMIT 100
                        """
                    ).fetchall()
                ]
                activity_by_container: dict[str, list[dict[str, Any]]] = {}
                for activity in reversed(activity_rows):
                    activity_by_container.setdefault(activity["container_uuid"], []).append(activity)

                for row in containers + completed:
                    report = _validation_report(row)
                    story = [
                        f"{str(activity['created_at'])[11:19]} - {activity['friendly_message']}"
                        for activity in activity_by_container.get(row["container_uuid"], [])
                    ]
                    report["story_steps"] = story
                    row["validation_report"] = report
                    row["display_state"] = row["state"].replace("_", " ").title()
                    row["friendly_status"] = {
                        "COLLECTING": "Collecting rider messages",
                        "READY_WAITING_QUIET": "Complete - waiting for messages to finish",
                        "DISPATCHING": "Sending rider and OPS updates",
                        "COMPLETED": "Completed",
                        "PAUSED": "Paused - waiting for the rider to continue",
                        "NEEDS_REVIEW": "Needs review",
                        "FAILED": "Send failed",
                        "CANCELLED": "Cancelled",
                    }.get(row["state"], row["display_state"])
                    row["what_next"] = report["next_action"]
                    row["waiting_for"] = _waiting_for(row)
                    row["quiet_seconds_remaining"] = _quiet_seconds(row)
                    statuses = outbound_by_container.get(row["container_uuid"], {})
                    row["rider_reply_status"] = statuses.get("RIDER_REPLY", "")
                    row["ops_update_status"] = statuses.get("OPS_GROUP_UPDATE", "")
                    row["supplemental_status"] = statuses.get("OPS_GROUP_SUPPLEMENTAL_MEDIA", "")

                active_states = {
                    "COLLECTING",
                    "READY_WAITING_QUIET",
                    "DISPATCHING",
                    "RECEIVING",
                    "WAITING_FOR_LP",
                    "WAITING_FOR_IMAGES",
                    "WAITING_FOR_ACTION",
                    "READY_TO_SEND",
                    "READY_FOR_APPROVAL",
                }
                review_states = {"NEEDS_REVIEW", "MANUAL_REVIEW", "FAILED"}
                paused_states = {"PAUSED", "INACTIVE"}
                active_requests = [row for row in containers if row["state"] in active_states]
                review_requests = [row for row in containers if row["state"] in review_states]
                paused_requests = [row for row in containers if row["state"] in paused_states]
                state_order = {"DISPATCHING": 0, "READY_WAITING_QUIET": 1, "COLLECTING": 2}
                active_requests.sort(
                    key=lambda row: (
                        state_order.get(row["state"], 3),
                        -(from_db_time(row.get("last_useful_activity_at") or row.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp(),
                    )
                )

                metrics_row = conn.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM incoming_events) AS events,
                      (SELECT COUNT(*) FROM request_containers WHERE deleted_at IS NULL AND state IN ('COLLECTING', 'READY_WAITING_QUIET', 'DISPATCHING', 'RECEIVING', 'WAITING_FOR_LP', 'WAITING_FOR_IMAGES', 'WAITING_FOR_ACTION')) AS active_requests,
                      (SELECT COUNT(*) FROM request_containers WHERE deleted_at IS NULL AND state NOT IN ('COMPLETED', 'CANCELLED')) AS live_containers,
                      (SELECT COUNT(*) FROM request_containers WHERE deleted_at IS NULL AND state IN ('NEEDS_REVIEW', 'MANUAL_REVIEW', 'FAILED')) AS manual_review,
                      (SELECT COUNT(*) FROM request_containers WHERE deleted_at IS NULL AND state IN ('PAUSED', 'INACTIVE')) AS inactive,
                      (SELECT COUNT(*) FROM request_containers WHERE deleted_at IS NULL AND state = 'COMPLETED') AS completed,
                      (SELECT COUNT(*) FROM outbound_actions) AS outbound_actions
                    """
                ).fetchone()
                revision_row = conn.execute(
                    """
                    SELECT
                      COALESCE((SELECT MAX(id) FROM container_activity_log), 0) AS activity_id,
                      COALESCE((SELECT MAX(id) FROM incoming_events), 0) AS event_id,
                      COALESCE((SELECT MAX(id) FROM request_containers), 0) AS container_id,
                      COALESCE((SELECT MAX(id) FROM outbound_actions), 0) AS outbound_action_id,
                      COALESCE((SELECT SUM(latest_revision) FROM request_containers), 0) AS request_revision
                    """
                ).fetchone()
                conn.execute("COMMIT")
                revision = max(
                    int(revision_row["activity_id"]),
                    int(revision_row["event_id"]),
                    int(revision_row["outbound_action_id"]),
                    int(revision_row["request_revision"]),
                )
                return {
                    "revision": revision,
                    "latest_activity_id": revision,
                    "latest_event_id": int(revision_row["event_id"]),
                    "latest_container_id": int(revision_row["container_id"]),
                    "latest_outbound_action_id": int(revision_row["outbound_action_id"]),
                    "recent_events": recent_events,
                    "recent_activity": activity_rows[:10],
                    "containers": containers,
                    "active_requests": active_requests,
                    "needs_review_requests": review_requests,
                    "paused_requests": paused_requests,
                    "outbound_actions": outbound_actions,
                    "recent_completed_requests": completed,
                    "completed_today": completed,
                    "metrics": dict(metrics_row),
                    "read_at": to_db_time(),
                }
            except Exception:
                conn.execute("ROLLBACK")
                raise

        return self.execute_with_retry(op)

    def reset_all(self) -> None:
        """Delete all prototype data while preserving schema."""

        def op(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM outbound_actions")
                conn.execute("DELETE FROM outbound_requests")
                conn.execute("DELETE FROM outbound_queue")
                conn.execute("DELETE FROM manual_audit_log")
                conn.execute("DELETE FROM container_activity_log")
                conn.execute("DELETE FROM request_event_links")
                conn.execute("DELETE FROM request_media")
                conn.execute("DELETE FROM incoming_events")
                conn.execute("DELETE FROM request_containers")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        self.execute_with_retry(op)

    def health(self) -> dict[str, Any]:
        try:
            with self.connect() as conn:
                conn.execute("SELECT 1").fetchone()
                row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
            return {"ok": True, "path": str(self.path), "schema_version": row["version"] or SCHEMA_VERSION}
        except sqlite3.Error as exc:
            LOGGER.exception("SQLite health check failed")
            return {"ok": False, "path": str(self.path), "error": str(exc)}
