"""Build and manage simulated outbound rider and OPS-group actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from .config import Settings, get_settings
from .database import Database, from_db_time, to_db_time
from .models import ContainerState, OutboundActionType, OutboundStatus


class OutboundService:
    """Creates approval-gated outbound requests and actions."""

    def __init__(self, db: Database, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def build_rider_reply(self, container: dict[str, Any]) -> str:
        action = str(container.get("detected_action") or "UNKNOWN").lower()
        prefix = "Simulation: " if self.settings.simulation_mode else ""
        return f"{prefix}Vehicle {container['detected_licence_plate']} was registered as {action}."

    def build_ops_message(self, container: dict[str, Any], media: list[dict[str, Any]]) -> str:
        from datetime import datetime

        location_parts = [
            container.get("detected_location"),
            container.get("detected_deck"),
            container.get("detected_level"),
            container.get("detected_lot"),
            container.get("detected_lot_range"),
            container.get("detected_bay"),
            container.get("detected_zone"),
            "White Lots" if container.get("detected_parking_type") == "WHITE_LOTS" else None,
        ]
        lines = [
            "FLEXAR OPS UPDATE",
            "",
            f"Vehicle: {container['detected_licence_plate']}",
            f"Action: {container.get('detected_action') or 'UNKNOWN'}",
            f"Rider: {container.get('sender_id') or '-'}",
        ]
        location = ", ".join(part for part in location_parts if part)
        if location:
            lines.extend(["", "Location:", location])
        lines.extend(["", "Images:", f"{len(media)} received"])
        remarks = (container.get("useful_text") or "").strip()
        if remarks:
            lines.extend(["", "Remarks:", remarks])
        lines.extend(
            [
                "",
                "Request:",
                container.get("request_reference") or container["container_uuid"][:8],
                "",
                "Processed:",
                datetime.now().strftime("%d %B %Y, %I:%M %p"),
            ]
        )
        if self.settings.simulation_mode:
            lines.extend(["", "Mode: simulation only"])
        return "\n".join(lines)

    def approve_and_queue(self, container_uuid: str, actor: str = "operator") -> dict[str, Any]:
        """Create one outbound request and one action for each required destination."""

        container = self.db.fetch_one("SELECT * FROM request_containers WHERE container_uuid = ?", (container_uuid,))
        if not container:
            raise ValueError("Unknown container")
        if not container.get("detected_licence_plate") or not container.get("detected_action"):
            raise ValueError("Approval requires a licence plate and a lock/unlock action")

        media = self.db.fetch_all(
            """
            SELECT external_media_id, media_type, filename, local_path, media_sequence
            FROM request_media
            WHERE container_uuid = ? AND included_in_outbound = 1 AND COALESCE(supplemental, 0) = 0
            ORDER BY id
            """,
            (container_uuid,),
        )
        approved_count = len(media)
        payload = {
            "container_uuid": container_uuid,
            "request_reference": container.get("request_reference"),
            "licence_plate": container["detected_licence_plate"],
            "action": container["detected_action"],
            "cleaned_message": container.get("useful_text") or "",
            "approved_image_count": approved_count,
            "media": media,
            "simulation": self.settings.simulation_mode,
        }

        existing = self.db.fetch_one("SELECT * FROM outbound_requests WHERE container_uuid = ?", (container_uuid,))
        if existing:
            outbound_request_id = int(existing["id"])
        else:
            self.db.execute(
                """
                INSERT INTO outbound_requests (
                    container_uuid, request_reference, licence_plate, action, cleaned_message,
                    approved_image_count, payload_json, overall_status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    container_uuid,
                    container.get("request_reference"),
                    container["detected_licence_plate"],
                    container["detected_action"],
                    container.get("useful_text") or "",
                    approved_count,
                    json.dumps(payload, sort_keys=True),
                    OutboundStatus.PENDING.value,
                    to_db_time(),
                ),
            )
            existing = self.db.fetch_one("SELECT * FROM outbound_requests WHERE container_uuid = ?", (container_uuid,))
            outbound_request_id = int(existing["id"])

        rider_text = self.build_rider_reply(container)
        ops_text = self.build_ops_message(container, media)
        actions = [
            (OutboundActionType.RIDER_REPLY.value, container["chat_id"], rider_text, []),
            (
                OutboundActionType.OPS_GROUP_UPDATE.value,
                self.settings.ops_group_chat_id or "SIMULATED_OPS_GROUP",
                ops_text,
                media,
            ),
        ]
        created = 0
        for action_type, destination_id, message_text, media_payload in actions:
            before = self.db.fetch_one(
                "SELECT id FROM outbound_actions WHERE container_uuid = ? AND action_type = ?",
                (container_uuid, action_type),
            )
            self.db.execute(
                """
                INSERT OR IGNORE INTO outbound_actions (
                    outbound_request_id, container_uuid, action_type, destination_id,
                    message_text, media_payload_json, status, created_at, queued_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outbound_request_id,
                    container_uuid,
                    action_type,
                    destination_id,
                    message_text,
                    json.dumps(media_payload, sort_keys=True),
                    OutboundStatus.PENDING.value,
                    to_db_time(),
                    to_db_time(),
                ),
            )
            after = self.db.fetch_one(
                "SELECT id FROM outbound_actions WHERE container_uuid = ? AND action_type = ?",
                (container_uuid, action_type),
            )
            if after and not before:
                created += 1

        self.db.execute(
            """
            UPDATE request_containers
            SET previous_state = state,
                state = ?,
                operator_approved_at = COALESCE(operator_approved_at, ?),
                approved_image_count = ?,
                updated_at = ?
            WHERE container_uuid = ?
            """,
            (ContainerState.DISPATCHING.value, to_db_time(), approved_count, to_db_time(), container_uuid),
        )
        self.db.execute(
            """
            INSERT INTO manual_audit_log (actor, action, container_uuid, after_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor, "APPROVE_AND_QUEUE", container_uuid, json.dumps(payload, sort_keys=True), to_db_time()),
        )
        return {"outbound_request_id": outbound_request_id, "actions_created": created, "payload": payload}

    def create_supplemental_ops_action(self, container_uuid: str, media: list[dict[str, Any]], batch_id: str) -> dict[str, Any]:
        container = self.db.fetch_one("SELECT * FROM request_containers WHERE container_uuid = ?", (container_uuid,))
        if not container:
            raise ValueError("Unknown container")
        existing_request = self.db.fetch_one("SELECT * FROM outbound_requests WHERE container_uuid = ?", (container_uuid,))
        if not existing_request:
            raise ValueError("Supplemental media requires an existing outbound request")
        message = "\n".join(
            [
                "FLEXAR OPS SUPPLEMENTAL MEDIA",
                "",
                f"Vehicle: {container.get('detected_licence_plate') or '-'}",
                f"Request: {container.get('request_reference') or container_uuid[:8]}",
                f"Additional images: {len(media)}",
                "",
                "Mode: simulation only" if self.settings.simulation_mode else "Mode: live WAAPI",
            ]
        )
        self.db.execute(
            """
            INSERT OR IGNORE INTO outbound_actions (
                outbound_request_id, container_uuid, action_type, destination_id,
                message_text, media_payload_json, status, created_at, queued_at, supplemental_batch_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(existing_request["id"]),
                container_uuid,
                OutboundActionType.OPS_GROUP_SUPPLEMENTAL_MEDIA.value,
                self.settings.ops_group_chat_id or "SIMULATED_OPS_GROUP",
                message,
                json.dumps(media, sort_keys=True),
                OutboundStatus.PENDING.value,
                to_db_time(),
                to_db_time(),
                batch_id,
            ),
        )
        action = self.db.fetch_one(
            "SELECT * FROM outbound_actions WHERE container_uuid = ? AND action_type = ? AND supplemental_batch_id = ?",
            (container_uuid, OutboundActionType.OPS_GROUP_SUPPLEMENTAL_MEDIA.value, batch_id),
        )
        if action and self.settings.simulation_mode and self.settings.auto_dispatch_in_simulation:
            self.simulate_action(int(action["id"]))
        self.db.execute(
            """
            UPDATE request_containers
            SET supplemental_media_count = supplemental_media_count + ?,
                latest_revision = latest_revision + 1,
                updated_at = ?
            WHERE container_uuid = ?
            """,
            (len(media), to_db_time(), container_uuid),
        )
        return {"ok": True, "action_id": int(action["id"]) if action else None, "media_count": len(media)}

    def list_outbound_requests(self) -> list[dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM outbound_requests ORDER BY id DESC")

    def list_outbound_actions(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.db.fetch_all("SELECT * FROM outbound_actions WHERE status = ? ORDER BY id DESC", (status,))
        return self.db.fetch_all("SELECT * FROM outbound_actions ORDER BY id DESC")

    def simulate_action(self, action_id: int) -> dict[str, Any]:
        action = self.db.fetch_one("SELECT * FROM outbound_actions WHERE id = ?", (action_id,))
        if not action:
            raise ValueError("Unknown outbound action")
        self.db.execute(
            """
            UPDATE outbound_actions
            SET status = ?, attempt_count = attempt_count + 1, sent_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (OutboundStatus.SIMULATED_SENT.value, to_db_time(), action_id),
        )
        self._refresh_request_status(action["container_uuid"])
        return {"ok": True, "simulated": True, "action_id": action_id}

    def simulate_request(self, container_uuid: str) -> int:
        actions = self.db.fetch_all(
            "SELECT id FROM outbound_actions WHERE container_uuid = ? AND status = ?",
            (container_uuid, OutboundStatus.PENDING.value),
        )
        for action in actions:
            self.simulate_action(int(action["id"]))
        return len(actions)

    def _refresh_request_status(self, container_uuid: str) -> None:
        actions = self.db.fetch_all("SELECT status FROM outbound_actions WHERE container_uuid = ?", (container_uuid,))
        if not actions:
            return
        statuses = {row["status"] for row in actions}
        if statuses <= {OutboundStatus.SIMULATED_SENT.value, OutboundStatus.SENT.value}:
            self.db.execute(
                "UPDATE outbound_requests SET overall_status = ?, completed_at = ? WHERE container_uuid = ?",
                (OutboundStatus.SIMULATED_SENT.value, to_db_time(), container_uuid),
            )
            completed_at = to_db_time()
            grace_until = to_db_time((from_db_time(completed_at) or datetime.now(timezone.utc)) + timedelta(seconds=int(self.settings.late_media_grace_seconds)))
            self.db.execute(
                """
                UPDATE request_containers
                SET previous_state = state,
                    state = ?,
                    completed_at = COALESCE(completed_at, ?),
                    late_media_grace_until = COALESCE(late_media_grace_until, ?),
                    completion_reason = ?,
                    updated_at = ?,
                    latest_revision = latest_revision + 1
                WHERE container_uuid = ?
                """,
                (
                    ContainerState.COMPLETED.value,
                    completed_at,
                    grace_until,
                    "simulated outbound actions sent",
                    to_db_time(),
                    container_uuid,
                ),
            )
