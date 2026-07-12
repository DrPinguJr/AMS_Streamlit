"""Safe SQLite schema migrations for the WhatsApp request processor."""

from __future__ import annotations

import sqlite3


SCHEMA_VERSION = 4


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, column_sql: str) -> None:
    column_name = column_sql.split()[0]
    if column_name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")


def run_migrations(conn: sqlite3.Connection) -> None:
    """Create and evolve the local schema without destroying existing rows."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS incoming_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_message_id TEXT NOT NULL UNIQUE,
            payload_batch_id TEXT,
            correlation_id TEXT,
            quoted_message_id TEXT,
            reply_message_id TEXT,
            sender_id TEXT NOT NULL,
            sender_display_name TEXT,
            chat_id TEXT NOT NULL,
            chat_display_name TEXT,
            event_type TEXT NOT NULL,
            text_content TEXT,
            received_at TEXT NOT NULL,
            raw_payload_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'SIMULATOR',
            classification TEXT NOT NULL DEFAULT 'UNSUPPORTED',
            processing_status TEXT NOT NULL,
            duplicate_of_event_id INTEGER,
            assigned_container_uuid TEXT,
            match_reason TEXT,
            detected_licence_plate TEXT,
            included_in_outbound INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS request_containers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL UNIQUE,
            friendly_number INTEGER,
            request_reference TEXT,
            sender_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            detected_licence_plate TEXT,
            detected_action TEXT,
            action_explanation TEXT,
            useful_text TEXT,
            state TEXT NOT NULL,
            previous_state TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_activity_at TEXT,
            inactive_at TEXT,
            expires_at TEXT NOT NULL,
            image_count INTEGER NOT NULL DEFAULT 0,
            approved_image_count INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT,
            completion_reason TEXT,
            manual_review_reason TEXT,
            operator_approved_at TEXT,
            cancelled_at TEXT,
            detected_location TEXT,
            detected_address TEXT,
            detected_deck TEXT,
            detected_level TEXT,
            detected_lot TEXT,
            detected_lot_range TEXT,
            detected_bay TEXT,
            detected_zone TEXT,
            detected_parking_type TEXT,
            validation_status TEXT,
            validation_summary TEXT,
            missing_fields_json TEXT,
            warnings_json TEXT,
            blockers_json TEXT,
            auto_dispatch_eligible INTEGER NOT NULL DEFAULT 0,
            auto_dispatched_at TEXT,
            last_validation_at TEXT,
            ready_at TEXT,
            dispatch_after TEXT,
            dispatch_claimed_at TEXT,
            last_useful_activity_at TEXT,
            paused_at TEXT,
            late_media_grace_until TEXT,
            supplemental_media_count INTEGER NOT NULL DEFAULT 0,
            latest_revision INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS request_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL,
            incoming_event_id INTEGER,
            external_message_id TEXT NOT NULL,
            external_media_id TEXT,
            media_type TEXT NOT NULL,
            filename TEXT NOT NULL,
            local_path TEXT,
            media_sequence INTEGER NOT NULL,
            included_in_outbound INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(container_uuid, external_message_id, media_sequence),
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid),
            FOREIGN KEY(incoming_event_id) REFERENCES incoming_events(id)
        );

        CREATE TABLE IF NOT EXISTS request_event_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            external_message_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(container_uuid, event_id),
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid),
            FOREIGN KEY(event_id) REFERENCES incoming_events(id)
        );

        CREATE TABLE IF NOT EXISTS outbound_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL UNIQUE,
            request_reference TEXT,
            licence_plate TEXT NOT NULL,
            action TEXT NOT NULL,
            cleaned_message TEXT,
            approved_image_count INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid)
        );

        CREATE TABLE IF NOT EXISTS outbound_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            outbound_request_id INTEGER NOT NULL,
            container_uuid TEXT NOT NULL,
            action_type TEXT NOT NULL,
            destination_id TEXT,
            message_text TEXT NOT NULL,
            media_payload_json TEXT,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            queued_at TEXT,
            sent_at TEXT,
            error_message TEXT,
            supplemental_batch_id TEXT,
            UNIQUE(container_uuid, action_type),
            FOREIGN KEY(outbound_request_id) REFERENCES outbound_requests(id),
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid)
        );

        CREATE TABLE IF NOT EXISTS manual_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT,
            action TEXT NOT NULL,
            container_uuid TEXT,
            event_id INTEGER,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS container_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            friendly_message TEXT NOT NULL,
            technical_details_json TEXT,
            incoming_event_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid),
            FOREIGN KEY(incoming_event_id) REFERENCES incoming_events(id)
        );

        CREATE TABLE IF NOT EXISTS outbound_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_uuid TEXT NOT NULL UNIQUE,
            licence_plate TEXT NOT NULL,
            cleaned_message TEXT,
            image_count INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            error_message TEXT,
            FOREIGN KEY(container_uuid) REFERENCES request_containers(container_uuid)
        );
        """
    )

    for column in [
        "payload_batch_id TEXT",
        "correlation_id TEXT",
        "quoted_message_id TEXT",
        "reply_message_id TEXT",
        "sender_display_name TEXT",
        "chat_display_name TEXT",
        "source TEXT NOT NULL DEFAULT 'SIMULATOR'",
        "classification TEXT NOT NULL DEFAULT 'UNSUPPORTED'",
        "duplicate_of_event_id INTEGER",
        "assigned_container_uuid TEXT",
        "match_reason TEXT",
        "included_in_outbound INTEGER NOT NULL DEFAULT 1",
        "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    ]:
        _add_column(conn, "incoming_events", column)

    if "assigned_container_uuid" in _columns(conn, "incoming_events") and "container_uuid" in _columns(conn, "incoming_events"):
        conn.execute(
            """
            UPDATE incoming_events
            SET assigned_container_uuid = COALESCE(assigned_container_uuid, container_uuid)
            WHERE assigned_container_uuid IS NULL
            """
        )

    for column in [
        "friendly_number INTEGER",
        "request_reference TEXT",
        "detected_action TEXT",
        "action_explanation TEXT",
        "previous_state TEXT",
        "approved_image_count INTEGER NOT NULL DEFAULT 0",
        "last_activity_at TEXT",
        "inactive_at TEXT",
        "completed_at TEXT",
        "manual_review_reason TEXT",
        "operator_approved_at TEXT",
        "cancelled_at TEXT",
        "detected_location TEXT",
        "detected_address TEXT",
        "detected_deck TEXT",
        "detected_level TEXT",
        "detected_lot TEXT",
        "detected_lot_range TEXT",
        "detected_bay TEXT",
        "detected_zone TEXT",
        "detected_parking_type TEXT",
        "validation_status TEXT",
        "validation_summary TEXT",
        "missing_fields_json TEXT",
        "warnings_json TEXT",
        "blockers_json TEXT",
        "auto_dispatch_eligible INTEGER NOT NULL DEFAULT 0",
        "auto_dispatched_at TEXT",
        "last_validation_at TEXT",
        "ready_at TEXT",
        "dispatch_after TEXT",
        "dispatch_claimed_at TEXT",
        "last_useful_activity_at TEXT",
        "paused_at TEXT",
        "late_media_grace_until TEXT",
        "supplemental_media_count INTEGER NOT NULL DEFAULT 0",
        "latest_revision INTEGER NOT NULL DEFAULT 0",
    ]:
        _add_column(conn, "request_containers", column)

    for column in [
        "incoming_event_id INTEGER",
        "external_media_id TEXT",
        "included_in_outbound INTEGER NOT NULL DEFAULT 1",
        "supplemental INTEGER NOT NULL DEFAULT 0",
    ]:
        _add_column(conn, "request_media", column)

    for column in [
        "supplemental_batch_id TEXT",
    ]:
        _add_column(conn, "outbound_actions", column)

    conn.executescript(
        """
        UPDATE request_containers
        SET last_activity_at = COALESCE(last_activity_at, updated_at),
            last_useful_activity_at = COALESCE(last_useful_activity_at, last_activity_at, updated_at),
            approved_image_count = CASE
                WHEN approved_image_count IS NULL OR approved_image_count = 0 THEN image_count
                ELSE approved_image_count
            END,
            latest_revision = COALESCE(latest_revision, 0);

        UPDATE request_containers
        SET friendly_number = id
        WHERE friendly_number IS NULL;

        UPDATE request_containers
        SET request_reference = 'REQ-' || printf('%04d', friendly_number)
        WHERE request_reference IS NULL;

        CREATE INDEX IF NOT EXISTS idx_incoming_sender_chat ON incoming_events(sender_id, chat_id);
        CREATE INDEX IF NOT EXISTS idx_incoming_batch ON incoming_events(payload_batch_id);
        CREATE INDEX IF NOT EXISTS idx_incoming_correlation ON incoming_events(correlation_id);
        CREATE INDEX IF NOT EXISTS idx_containers_state ON request_containers(state);
        CREATE INDEX IF NOT EXISTS idx_containers_dispatch_due ON request_containers(state, dispatch_after);
        CREATE INDEX IF NOT EXISTS idx_containers_completed ON request_containers(completed_at);
        CREATE INDEX IF NOT EXISTS idx_containers_lp ON request_containers(detected_licence_plate);
        CREATE INDEX IF NOT EXISTS idx_containers_sender_chat ON request_containers(sender_id, chat_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_request_media_external_media_id
            ON request_media(external_media_id)
            WHERE external_media_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_outbound_actions_status ON outbound_actions(status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_supplemental_batch
            ON outbound_actions(container_uuid, action_type, supplemental_batch_id)
            WHERE supplemental_batch_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_activity_container ON container_activity_log(container_uuid, created_at);
        """
    )
    conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)", (SCHEMA_VERSION,))
