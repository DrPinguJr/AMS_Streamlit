"""Deterministic request assembly engine."""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .config import Settings, get_settings
from .database import Database, from_db_time, to_db_time
from .models import (
    ActionIntent,
    ActionDetection,
    ContainerState,
    EventClassification,
    MatchReason,
    ParsedPayload,
    ProcessResult,
    display_state,
    new_container_uuid,
    utc_now,
)
from .outbound_service import OutboundService
from .location_parser import extract_location_info
from .payload_parser import extract_primary_licence_plate, is_valid_licence_plate, normalize_licence_plate, parse_payload, split_payload_batch
from .validation_engine import ValidationEngine


LOGGER = logging.getLogger(__name__)

MATCHABLE_STATES = {
    ContainerState.COLLECTING.value,
    ContainerState.READY_WAITING_QUIET.value,
    ContainerState.PAUSED.value,
    ContainerState.RECEIVING.value,
    ContainerState.WAITING_FOR_LP.value,
    ContainerState.WAITING_FOR_IMAGES.value,
    ContainerState.WAITING_FOR_ACTION.value,
    ContainerState.INACTIVE.value,
}

REVIEW_STATES = {ContainerState.NEEDS_REVIEW.value, ContainerState.MANUAL_REVIEW.value}
TERMINAL_STATES = {
    ContainerState.COMPLETED.value,
    ContainerState.CANCELLED.value,
    ContainerState.EXPIRED.value,
    ContainerState.FAILED.value,
}


@dataclass
class ProcessMetrics:
    events_processed: int = 0
    containers_created: int = 0
    containers_merged: int = 0
    containers_ready: int = 0
    containers_completed: int = 0
    duplicates_ignored: int = 0
    filler_ignored: int = 0
    manual_review_count: int = 0
    inactive_count: int = 0
    expired_count: int = 0
    errors: int = 0


class RequestEngine:
    """Framework-independent engine used by Streamlit and FastAPI."""

    def __init__(self, db: Database | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings)
        self.outbound = OutboundService(self.db, self.settings)
        self.validator = ValidationEngine(self.db, self.settings)

    def process_webhook_payload(self, raw_payload: dict[str, Any]) -> list[ProcessResult]:
        """Process a single payload body that may contain a message batch."""

        results: list[ProcessResult] = []
        for message_payload in split_payload_batch(raw_payload):
            results.append(self.process_payload(message_payload))
        return results

    def process_payload(self, raw_payload: dict[str, Any]) -> ProcessResult:
        """Process one parsed message-like payload."""

        self.update_time_states()
        try:
            parsed = parse_payload(raw_payload)
        except ValueError as exc:
            return ProcessResult(status="error", match_reason=MatchReason.ERROR.value, explanation=str(exc), message=str(exc))
        parsed = self._apply_configured_default_action(parsed)

        event_id, duplicate = self.db.insert_event(
            external_message_id=parsed.external_message_id,
            payload_batch_id=parsed.payload_batch_id,
            correlation_id=parsed.correlation_id,
            quoted_message_id=parsed.quoted_message_id,
            reply_message_id=parsed.reply_message_id,
            sender_id=parsed.sender_id,
            sender_display_name=parsed.sender_display_name,
            chat_id=parsed.chat_id,
            chat_display_name=parsed.chat_display_name,
            event_type=parsed.event_type,
            text_content=parsed.text_content,
            received_at=parsed.received_at,
            raw_payload=parsed.raw_payload,
            processing_status="RECEIVED",
            source=parsed.source.value,
            classification=parsed.classification.value,
            detected_licence_plate=parsed.licence_plate,
        )
        if duplicate:
            return ProcessResult(
                status="duplicate ignored",
                event_id=event_id,
                event_ids=[event_id] if event_id else [],
                external_message_id=parsed.external_message_id,
                duplicate=True,
                match_reason=MatchReason.DUPLICATE.value,
                classification=EventClassification.DUPLICATE.value,
                explanation="Duplicate ignored - this message was already processed.",
                message="duplicate ignored",
            )

        late_result = self._try_attach_late_media(parsed, event_id or 0)
        if late_result:
            return late_result

        if parsed.classification == EventClassification.FILLER_TEXT:
            self.db.update_event_status(
                event_id or 0,
                "IGNORED",
                match_reason=MatchReason.FILLER_IGNORED.value,
                classification=EventClassification.FILLER_TEXT.value,
                included_in_outbound=False,
            )
            return ProcessResult(
                status="ignored",
                event_id=event_id,
                event_ids=[event_id] if event_id else [],
                external_message_id=parsed.external_message_id,
                match_reason=MatchReason.FILLER_IGNORED.value,
                classification=EventClassification.FILLER_TEXT.value,
                explanation="Filler ignored - it did not create or change a request.",
                message="filler ignored",
            )

        container, created, match_reason, manual_reason = self._find_or_create_container(parsed, event_id or 0)
        if manual_reason:
            self.mark_manual_review(container["container_uuid"], manual_reason)
            container = self.get_container(container["container_uuid"]) or container

        if parsed.classification == EventClassification.CONFLICT or manual_reason:
            if not manual_reason:
                self.mark_manual_review(container["container_uuid"], self._conflict_reason(parsed))
                container = self.get_container(container["container_uuid"]) or container
            self._link_event(container["container_uuid"], event_id or 0)
        else:
            container = self._merge_payload_into_container(container["container_uuid"], parsed, event_id or 0)

        self.db.update_event_status(
            event_id or 0,
            "MANUAL_REVIEW" if container["state"] in REVIEW_STATES else "PROCESSED",
            container_uuid=container["container_uuid"],
            match_reason=match_reason.value,
            classification=parsed.classification.value,
            included_in_outbound=parsed.classification != EventClassification.FILLER_TEXT,
        )

        container = self._refresh_container_state(container["container_uuid"])
        if container["state"] == ContainerState.READY_WAITING_QUIET.value and int(self.settings.request_quiet_seconds) <= 0:
            self.process_due_dispatches(limit=1)
            container = self.get_container(container["container_uuid"]) or container
        state = container["state"]
        ready = state in {
            ContainerState.READY_WAITING_QUIET.value,
            ContainerState.DISPATCHING.value,
            ContainerState.COMPLETED.value,
        }
        return ProcessResult(
            status="processed",
            event_id=event_id,
            event_ids=[event_id] if event_id else [],
            external_message_id=parsed.external_message_id,
            container_uuid=container["container_uuid"],
            container_state=state,
            display_state=display_state(state),
            duplicate=False,
            created_container=created,
            completed=ready,
            outbound_actions_created=int(container.get("_outbound_actions_created") or 0),
            match_reason=match_reason.value,
            classification=parsed.classification.value,
            explanation=self._explain_result(created, match_reason, state, parsed),
            message="created" if created else "merged",
        )

    def _conflict_reason(self, parsed: ParsedPayload) -> str:
        if len(parsed.licence_plates) > 1:
            return f"Multiple licence plates found: {', '.join(parsed.licence_plates)}"
        if parsed.action_detection.action == ActionIntent.CONFLICTING:
            return parsed.action_detection.explanation
        return "Conflicting payload needs operator review"

    def _apply_configured_default_action(self, parsed: ParsedPayload) -> ParsedPayload:
        configured = self.settings.default_action
        if parsed.action_detection.action != ActionIntent.UNKNOWN or configured not in {ActionIntent.LOCKED.value, ActionIntent.UNLOCKED.value}:
            return parsed
        return parsed.model_copy(
            update={
                "action_detection": ActionDetection(
                    action=ActionIntent(configured),
                    confidence=1.0,
                    explanation=f"Configured workflow default action {configured} applied.",
                    matched_phrases=["DEFAULT_ACTION"],
                )
            }
        )

    def _try_attach_late_media(self, parsed: ParsedPayload, event_id: int) -> ProcessResult | None:
        if not parsed.media or parsed.useful_text or parsed.licence_plate:
            return None
        now = utc_now()
        newer_open = self.db.fetch_one(
            """
            SELECT container_uuid FROM request_containers
            WHERE sender_id = ?
              AND deleted_at IS NULL
              AND state NOT IN (?, ?, ?, ?)
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (
                parsed.sender_id,
                ContainerState.COMPLETED.value,
                ContainerState.CANCELLED.value,
                ContainerState.EXPIRED.value,
                ContainerState.FAILED.value,
            ),
        )
        if newer_open:
            return None
        candidates = self.db.fetch_all(
            """
            SELECT * FROM request_containers
            WHERE sender_id = ?
              AND state = ?
              AND late_media_grace_until >= ?
              AND deleted_at IS NULL
            ORDER BY completed_at DESC
            """,
            (parsed.sender_id, ContainerState.COMPLETED.value, to_db_time(now)),
        )
        if len(candidates) != 1:
            return None
        container = candidates[0]
        media_payload: list[dict[str, Any]] = []
        for media in parsed.media:
            self.db.execute(
                """
                INSERT OR IGNORE INTO request_media (
                    container_uuid, incoming_event_id, external_message_id, external_media_id,
                    media_type, filename, local_path, media_sequence, included_in_outbound, supplemental, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    container["container_uuid"],
                    event_id,
                    parsed.external_message_id,
                    media.external_media_id,
                    media.media_type,
                    media.filename,
                    media.local_path,
                    media.sequence,
                    1,
                    1,
                    to_db_time(now),
                ),
            )
            row = self.db.fetch_one(
                "SELECT * FROM request_media WHERE container_uuid = ? AND external_media_id = ?",
                (container["container_uuid"], media.external_media_id),
            )
            if row:
                media_payload.append(
                    {
                        "external_media_id": row.get("external_media_id"),
                        "media_type": row.get("media_type"),
                        "filename": row.get("filename"),
                        "local_path": row.get("local_path"),
                        "media_sequence": row.get("media_sequence"),
                    }
                )
        self._link_event(container["container_uuid"], event_id)
        self.db.update_event_status(
            event_id,
            "PROCESSED",
            container_uuid=container["container_uuid"],
            match_reason=MatchReason.MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER.value,
            classification=parsed.classification.value,
            included_in_outbound=True,
        )
        if media_payload:
            self.outbound.create_supplemental_ops_action(container["container_uuid"], media_payload, parsed.external_message_id)
            self._log_activity(
                container["container_uuid"],
                "SUPPLEMENTAL_MEDIA_ADDED",
                f"{len(media_payload)} late image(s) sent to OPS.",
                event_id,
                {"message": parsed.external_message_id},
            )
        return ProcessResult(
            status="processed",
            event_id=event_id,
            event_ids=[event_id],
            external_message_id=parsed.external_message_id,
            container_uuid=container["container_uuid"],
            container_state=ContainerState.COMPLETED.value,
            display_state=display_state(ContainerState.COMPLETED.value),
            duplicate=False,
            created_container=False,
            completed=True,
            outbound_actions_created=1 if media_payload else 0,
            match_reason=MatchReason.MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER.value,
            classification=parsed.classification.value,
            explanation="Late image attached as supplemental OPS media.",
            message="supplemental media",
        )

    def _explain_result(self, created: bool, reason: MatchReason, state: str, parsed: ParsedPayload) -> str:
        if reason == MatchReason.MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER:
            match_text = "It matched the only incomplete request from this rider and chat."
        elif reason == MatchReason.MATCHED_BY_EXACT_LP:
            match_text = f"It matched an existing request for {parsed.licence_plate}."
        elif reason in {MatchReason.MATCHED_BY_CORRELATION, MatchReason.MATCHED_BY_REPLY, MatchReason.MATCHED_BY_BATCH}:
            match_text = "It matched by an explicit relationship ID."
        elif reason == MatchReason.AMBIGUOUS:
            match_text = "It needs review because more than one request could accept this payload."
        elif created:
            match_text = "A new request container was created."
        else:
            match_text = "The request container was updated."
        return f"{match_text} Current status: {display_state(state)}."

    def _candidate_containers(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in MATCHABLE_STATES)
        return self.db.fetch_all(
            f"""
            SELECT * FROM request_containers
            WHERE state IN ({placeholders})
              AND deleted_at IS NULL
            ORDER BY
              CASE state
                WHEN 'READY_WAITING_QUIET' THEN 1
                WHEN 'COLLECTING' THEN 2
                WHEN 'PAUSED' THEN 3
                ELSE 4
              END,
              updated_at DESC
            """,
            tuple(MATCHABLE_STATES),
        )

    def _compatible(self, container: dict[str, Any], parsed: ParsedPayload) -> bool:
        current_lp = container.get("detected_licence_plate")
        if current_lp and parsed.licence_plate and current_lp != parsed.licence_plate:
            return False
        current_action = container.get("detected_action")
        parsed_action = parsed.action_detection.action
        if current_action and parsed_action not in {ActionIntent.UNKNOWN, ActionIntent.CONFLICTING} and current_action != parsed_action.value:
            return False
        return True

    def _supplies_missing(self, container: dict[str, Any], parsed: ParsedPayload) -> bool:
        if not container.get("detected_licence_plate") and parsed.licence_plate:
            return True
        if int(container.get("image_count") or 0) < self.settings.min_required_images and parsed.media:
            return True
        if not container.get("detected_action") and parsed.action_detection.action in {ActionIntent.LOCKED, ActionIntent.UNLOCKED}:
            return True
        return bool(parsed.useful_text and not container.get("useful_text"))

    def _find_or_create_container(self, parsed: ParsedPayload, event_id: int) -> tuple[dict[str, Any], bool, MatchReason, str | None]:
        explicit, explicit_reason = self._find_by_explicit_relationship(parsed)
        if explicit:
            if not self._compatible(explicit, parsed):
                return explicit, False, explicit_reason, "Explicitly related payload conflicts with the existing request"
            return explicit, False, explicit_reason, None

        active = self._candidate_containers()
        if parsed.licence_plate:
            exact = [
                container
                for container in active
                if container.get("detected_licence_plate") == parsed.licence_plate and self._compatible(container, parsed)
            ]
            if len(exact) == 1:
                return exact[0], False, MatchReason.MATCHED_BY_EXACT_LP, None
            if len(exact) > 1:
                container = self._create_container(parsed, event_id, state=ContainerState.NEEDS_REVIEW, reason="Multiple active containers share this licence plate")
                return container, True, MatchReason.AMBIGUOUS, "Multiple active containers share this licence plate"

        same_sender = [
            container
            for container in active
            if container["sender_id"] == parsed.sender_id
            and container["chat_id"] == parsed.chat_id
            and self._compatible(container, parsed)
        ]
        if len(same_sender) == 1:
            return same_sender[0], False, MatchReason.MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER, None
        if len(same_sender) > 1:
            container = self._create_container(
                parsed,
                event_id,
                state=ContainerState.NEEDS_REVIEW,
                reason="Two existing requests from this sender could accept these images.",
            )
            return container, True, MatchReason.AMBIGUOUS, "Two existing requests from this sender could accept these images."

        return self._create_container(parsed, event_id), True, MatchReason.NEW_CONTAINER, None

    def _find_by_explicit_relationship(self, parsed: ParsedPayload) -> tuple[dict[str, Any] | None, MatchReason]:
        if parsed.payload_batch_id:
            row = self.db.fetch_one(
                """
                SELECT c.* FROM request_containers c
                JOIN incoming_events e ON e.assigned_container_uuid = c.container_uuid
                WHERE e.payload_batch_id = ?
                  AND c.state NOT IN (?, ?, ?, ?)
                  AND c.deleted_at IS NULL
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (
                    parsed.payload_batch_id,
                    ContainerState.COMPLETED.value,
                    ContainerState.EXPIRED.value,
                    ContainerState.CANCELLED.value,
                    ContainerState.FAILED.value,
                ),
            )
            if row:
                return row, MatchReason.MATCHED_BY_BATCH

        if parsed.correlation_id:
            row = self.db.fetch_one(
                """
                SELECT c.* FROM request_containers c
                JOIN incoming_events e ON e.assigned_container_uuid = c.container_uuid
                WHERE e.correlation_id = ?
                  AND c.state NOT IN (?, ?, ?, ?)
                  AND c.deleted_at IS NULL
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                (
                    parsed.correlation_id,
                    ContainerState.COMPLETED.value,
                    ContainerState.EXPIRED.value,
                    ContainerState.CANCELLED.value,
                    ContainerState.FAILED.value,
                ),
            )
            if row:
                return row, MatchReason.MATCHED_BY_CORRELATION

        ids = [value for value in [parsed.quoted_message_id, parsed.reply_message_id] if value]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            row = self.db.fetch_one(
                f"""
                SELECT c.* FROM request_containers c
                JOIN request_event_links l ON l.container_uuid = c.container_uuid
                WHERE l.external_message_id IN ({placeholders})
                  AND c.state NOT IN (?, ?, ?, ?)
                  AND c.deleted_at IS NULL
                ORDER BY c.updated_at DESC
                LIMIT 1
                """,
                tuple(ids + [ContainerState.COMPLETED.value, ContainerState.EXPIRED.value, ContainerState.CANCELLED.value, ContainerState.FAILED.value]),
            )
            if row:
                return row, MatchReason.MATCHED_BY_REPLY
        return None, MatchReason.NEW_CONTAINER

    def _create_container(
        self,
        parsed: ParsedPayload,
        event_id: int,
        state: ContainerState | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        expires_at = now + timedelta(seconds=self.settings.container_expiry_seconds)
        uuid = new_container_uuid()
        action = parsed.action_detection.action
        detected_action = action.value if action in {ActionIntent.LOCKED, ActionIntent.UNLOCKED} else None
        if state is None:
            state = self._derive_state(parsed.licence_plate, len(parsed.media), detected_action, reason)
        useful_at = to_db_time(now) if self._is_useful(parsed) else None
        self.db.execute(
            """
            INSERT INTO request_containers (
                container_uuid, sender_id, chat_id, detected_licence_plate, detected_action,
                action_explanation, useful_text, state, previous_state, created_at, updated_at,
                last_activity_at, expires_at, image_count, approved_image_count, completion_reason,
                manual_review_reason, detected_location, detected_deck, detected_level, detected_lot,
                detected_lot_range, detected_bay, detected_zone, detected_parking_type,
                last_useful_activity_at, latest_revision
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*(
                uuid,
                parsed.sender_id,
                parsed.chat_id,
                parsed.licence_plate,
                detected_action,
                parsed.action_detection.explanation,
                parsed.useful_text,
                state.value,
                None,
                to_db_time(now),
                to_db_time(now),
                to_db_time(now),
                to_db_time(expires_at),
                0,
                0,
                None,
                reason,
            ), *self._location_db_values(parsed.useful_text), useful_at, 1),
        )
        row = self.db.fetch_one("SELECT id FROM request_containers WHERE container_uuid = ?", (uuid,))
        if row:
            friendly_number = int(row["id"])
            self.db.execute(
                "UPDATE request_containers SET friendly_number = ?, request_reference = ? WHERE container_uuid = ?",
                (friendly_number, f"REQ-{friendly_number:04d}", uuid),
            )
        self._link_event(uuid, event_id)
        self._log_activity(uuid, "CONTAINER_CREATED", f"Created {uuid[:8]} for rider {parsed.sender_id}.", event_id, {"match": "new"})
        return self.get_container(uuid) or {"container_uuid": uuid, "state": state.value}

    def _derive_state(self, licence_plate: str | None, image_count: int, action: str | None, manual_reason: str | None = None) -> ContainerState:
        if manual_reason:
            return ContainerState.NEEDS_REVIEW
        return ContainerState.COLLECTING

    def _is_useful(self, parsed: ParsedPayload) -> bool:
        return bool(parsed.useful_text or parsed.media or parsed.licence_plate or parsed.action_detection.action in {ActionIntent.LOCKED, ActionIntent.UNLOCKED})

    def _link_event(self, container_uuid: str, event_id: int) -> None:
        event = self.db.fetch_one("SELECT external_message_id FROM incoming_events WHERE id = ?", (event_id,))
        if not event:
            return
        self.db.execute(
            """
            INSERT OR IGNORE INTO request_event_links (container_uuid, event_id, external_message_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (container_uuid, event_id, event["external_message_id"], to_db_time()),
        )

    def _merge_payload_into_container(self, container_uuid: str, parsed: ParsedPayload, event_id: int) -> dict[str, Any]:
        container = self.get_container(container_uuid)
        if not container:
            raise RuntimeError(f"Missing container {container_uuid}")
        if container["state"] in TERMINAL_STATES:
            return container

        current_lp = container.get("detected_licence_plate")
        if current_lp and parsed.licence_plate and current_lp != parsed.licence_plate:
            self.mark_manual_review(container_uuid, "Different licence plate conflicts with this request")
            return self.get_container(container_uuid) or container

        parsed_action = parsed.action_detection.action
        current_action = container.get("detected_action")
        if current_action and parsed_action in {ActionIntent.LOCKED, ActionIntent.UNLOCKED} and current_action != parsed_action.value:
            self.mark_manual_review(container_uuid, "Different lock/unlock actions conflict with this request")
            return self.get_container(container_uuid) or container
        if parsed_action == ActionIntent.CONFLICTING:
            self.mark_manual_review(container_uuid, parsed.action_detection.explanation)
            return self.get_container(container_uuid) or container

        new_text = self._join_text(container.get("useful_text") or "", parsed.useful_text)
        location_values = self._merged_location_values(container, new_text)
        new_lp = current_lp or parsed.licence_plate
        new_action = current_action or (parsed_action.value if parsed_action in {ActionIntent.LOCKED, ActionIntent.UNLOCKED} else None)
        action_explanation = container.get("action_explanation") or parsed.action_detection.explanation

        for media in parsed.media:
            self.db.execute(
                """
                INSERT OR IGNORE INTO request_media (
                    container_uuid, incoming_event_id, external_message_id, external_media_id,
                    media_type, filename, local_path, media_sequence, included_in_outbound, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    container_uuid,
                    event_id,
                    parsed.external_message_id,
                    media.external_media_id,
                    media.media_type,
                    media.filename,
                    media.local_path,
                    media.sequence,
                    1 if media.included_in_outbound else 0,
                    to_db_time(),
                ),
            )
        self._link_event(container_uuid, event_id)
        image_count = self.count_media(container_uuid)
        state = ContainerState.COLLECTING
        useful_at = to_db_time() if self._is_useful(parsed) else container.get("last_useful_activity_at")
        self.db.execute(
            """
            UPDATE request_containers
            SET detected_licence_plate = ?,
                detected_action = ?,
                action_explanation = ?,
                useful_text = ?,
                detected_location = ?,
                detected_deck = ?,
                detected_level = ?,
                detected_lot = ?,
                detected_lot_range = ?,
                detected_bay = ?,
                detected_zone = ?,
                detected_parking_type = ?,
                previous_state = CASE WHEN state != ? THEN state ELSE previous_state END,
                state = ?,
                image_count = ?,
                approved_image_count = ?,
                updated_at = ?,
                last_activity_at = ?,
                last_useful_activity_at = ?,
                inactive_at = NULL,
                paused_at = NULL,
                ready_at = NULL,
                dispatch_after = NULL,
                dispatch_claimed_at = NULL,
                latest_revision = latest_revision + 1
            WHERE container_uuid = ?
            """,
            (
                new_lp,
                new_action,
                action_explanation,
                new_text,
                *location_values,
                state.value,
                state.value,
                image_count,
                image_count,
                to_db_time(),
                to_db_time(),
                useful_at,
                container_uuid,
            ),
        )
        if parsed.media:
            self._log_activity(container_uuid, "IMAGE_ADDED", f"{len(parsed.media)} image(s) received.", event_id, {"message": parsed.external_message_id})
        if parsed.useful_text:
            self._log_activity(container_uuid, "TEXT_ADDED", f"Rider text added: {parsed.useful_text}", event_id, {"message": parsed.external_message_id})
        if parsed.licence_plate:
            self._log_activity(container_uuid, "LP_DETECTED", f"Licence plate {parsed.licence_plate} was detected.", event_id, {})
        if new_action and not current_action:
            self._log_activity(container_uuid, "ACTION_DETECTED", f"Action {new_action} was detected.", event_id, {})
        loc = extract_location_info(parsed.useful_text)
        if loc.has_location:
            self._log_activity(container_uuid, "LOCATION_DETECTED", f"Location detected: {loc.display_location or loc.raw_location_text}.", event_id, {})
        return self.get_container(container_uuid) or container

    def _join_text(self, existing: str, incoming: str) -> str:
        lines: list[str] = []
        for line in (existing + "\n" + incoming).splitlines():
            line = line.strip()
            if line and line not in lines:
                lines.append(line)
        return "\n".join(lines)

    def _refresh_container_state(self, container_uuid: str) -> dict[str, Any]:
        container = self.get_container(container_uuid)
        if not container:
            raise RuntimeError(f"Missing container {container_uuid}")
        if container["state"] in TERMINAL_STATES or container["state"] == ContainerState.DISPATCHING.value:
            return container
        if container["state"] in REVIEW_STATES:
            self.validator.validate_container(container_uuid)
            return self.get_container(container_uuid) or container
        image_count = self.count_media(container_uuid)
        self.db.execute(
            """
            UPDATE request_containers
            SET image_count = ?,
                approved_image_count = ?,
                updated_at = ?,
                latest_revision = latest_revision + 1
            WHERE container_uuid = ?
            """,
            (image_count, image_count, to_db_time(), container_uuid),
        )
        updated = self.get_container(container_uuid) or container
        report = self.validator.validate_container(container_uuid)
        self._log_activity(
            container_uuid,
            "VALIDATION_UPDATED",
            report.summary,
            None,
            {"missing": report.missing_required_fields, "blockers": report.blockers},
        )
        if report.blockers and any(code != "ALREADY_DISPATCHED" for code in report.blockers):
            self.db.execute(
                """
                UPDATE request_containers
                SET previous_state = state, state = ?, updated_at = ?, latest_revision = latest_revision + 1
                WHERE container_uuid = ?
                """,
                (ContainerState.NEEDS_REVIEW.value, to_db_time(), container_uuid),
            )
            return self.get_container(container_uuid) or updated
        if report.missing_required_fields:
            self.db.execute(
                """
                UPDATE request_containers
                SET previous_state = CASE WHEN state != ? THEN state ELSE previous_state END,
                    state = ?,
                    ready_at = NULL,
                    dispatch_after = NULL,
                    dispatch_claimed_at = NULL,
                    updated_at = ?,
                    latest_revision = latest_revision + 1
                WHERE container_uuid = ?
                """,
                (ContainerState.COLLECTING.value, ContainerState.COLLECTING.value, to_db_time(), container_uuid),
            )
            return self.get_container(container_uuid) or updated
        if report.auto_dispatch_eligible:
            refreshed = self.get_container(container_uuid) or updated
            last_useful = from_db_time(refreshed.get("last_useful_activity_at")) or utc_now()
            dispatch_after = last_useful + timedelta(seconds=int(self.settings.request_quiet_seconds))
            now = utc_now()
            self.db.execute(
                """
                UPDATE request_containers
                SET previous_state = CASE WHEN state != ? THEN state ELSE previous_state END,
                    state = ?,
                    ready_at = COALESCE(ready_at, ?),
                    dispatch_after = ?,
                    dispatch_claimed_at = NULL,
                    updated_at = ?,
                    latest_revision = latest_revision + 1
                WHERE container_uuid = ?
                """,
                (
                    ContainerState.READY_WAITING_QUIET.value,
                    ContainerState.READY_WAITING_QUIET.value,
                    to_db_time(now),
                    to_db_time(dispatch_after),
                    to_db_time(now),
                    container_uuid,
                ),
            )
            self._log_activity(container_uuid, "READY_WAITING_QUIET", "Checklist passed. Waiting for rider messages to finish.", None, {})
            if int(self.settings.request_quiet_seconds) <= 0:
                self.process_due_dispatches(limit=1)
            return self.get_container(container_uuid) or refreshed
        return updated

    def _state_for_missing(self, missing_fields: list[str]) -> ContainerState:
        return ContainerState.COLLECTING

    def _auto_dispatch(self, container_uuid: str) -> int:
        container = self.get_container(container_uuid)
        if not container or container.get("auto_dispatched_at"):
            return 0
        self.db.execute(
            """
            UPDATE request_containers
            SET auto_dispatched_at = COALESCE(auto_dispatched_at, ?),
                previous_state = state,
                state = ?,
                updated_at = ?
            WHERE container_uuid = ? AND auto_dispatched_at IS NULL
            """,
            (to_db_time(), ContainerState.DISPATCHING.value, to_db_time(), container_uuid),
        )
        self._log_activity(container_uuid, "AUTO_DISPATCH_STARTED", "All checks passed. Automatic dispatch started.", None, {})
        result = self.outbound.approve_and_queue(container_uuid, actor="automation")
        self._log_activity(container_uuid, "RIDER_REPLY_CREATED", "Rider reply prepared automatically.", None, {})
        self._log_activity(container_uuid, "OPS_UPDATE_CREATED", "OPS-group update prepared automatically.", None, {})
        if self.settings.simulation_mode and self.settings.auto_dispatch_in_simulation:
            actions = self.list_outbound_actions()
            for action in [row for row in actions if row["container_uuid"] == container_uuid and row["status"] == "PENDING"]:
                self.outbound.simulate_action(int(action["id"]))
                self._log_activity(
                    container_uuid,
                    "RIDER_REPLY_SIMULATED" if action["action_type"] == "RIDER_REPLY" else "OPS_UPDATE_SIMULATED",
                    f"{action['action_type'].replace('_', ' ').title()} simulated successfully.",
                    None,
                    {"action_id": action["id"]},
                )
            self._log_activity(container_uuid, "COMPLETED", "Both simulated messages completed.", None, {})
        return int(result.get("actions_created") or 0)

    def claim_due_request(self, container_uuid: str, now: str | None = None) -> bool:
        now = now or to_db_time()
        changed = self.db.execute_count(
            """
            UPDATE request_containers
            SET previous_state = state,
                state = ?,
                dispatch_claimed_at = ?,
                updated_at = ?,
                latest_revision = latest_revision + 1
            WHERE container_uuid = ?
              AND state = ?
              AND dispatch_after <= ?
              AND deleted_at IS NULL
            """,
            (
                ContainerState.DISPATCHING.value,
                now,
                now,
                container_uuid,
                ContainerState.READY_WAITING_QUIET.value,
                now,
            ),
        )
        return changed == 1

    def process_due_dispatches(self, limit: int = 20) -> int:
        now = to_db_time()
        due = self.db.fetch_all(
            """
            SELECT container_uuid FROM request_containers
            WHERE state = ?
              AND dispatch_after <= ?
              AND deleted_at IS NULL
            ORDER BY dispatch_after ASC
            LIMIT ?
            """,
            (ContainerState.READY_WAITING_QUIET.value, now, int(limit)),
        )
        processed = 0
        for row in due:
            container_uuid = row["container_uuid"]
            if not self.claim_due_request(container_uuid, now):
                continue
            report = self.validator.validate_container(container_uuid)
            if report.missing_required_fields or (report.blockers and any(code != "ALREADY_DISPATCHED" for code in report.blockers)):
                self.db.execute(
                    """
                    UPDATE request_containers
                    SET previous_state = state, state = ?, updated_at = ?, latest_revision = latest_revision + 1
                    WHERE container_uuid = ?
                    """,
                    (ContainerState.NEEDS_REVIEW.value, to_db_time(), container_uuid),
                )
                continue
            self.db.execute(
                """
                UPDATE request_containers
                SET auto_dispatched_at = COALESCE(auto_dispatched_at, ?), updated_at = ?
                WHERE container_uuid = ?
                """,
                (to_db_time(), to_db_time(), container_uuid),
            )
            self._log_activity(container_uuid, "AUTO_DISPATCH_STARTED", "Quiet window ended. Automatic dispatch started.", None, {})
            result = self.outbound.approve_and_queue(container_uuid, actor="automation")
            self._log_activity(container_uuid, "RIDER_REPLY_CREATED", "Rider reply prepared automatically.", None, {})
            self._log_activity(container_uuid, "OPS_UPDATE_CREATED", "OPS-group update prepared automatically.", None, {})
            if self.settings.simulation_mode and self.settings.auto_dispatch_in_simulation:
                actions = self.list_outbound_actions()
                for action in [item for item in actions if item["container_uuid"] == container_uuid and item["status"] == "PENDING"]:
                    self.outbound.simulate_action(int(action["id"]))
                    self._log_activity(
                        container_uuid,
                        "RIDER_REPLY_SIMULATED" if action["action_type"] == "RIDER_REPLY" else "OPS_UPDATE_SIMULATED",
                        f"{action['action_type'].replace('_', ' ').title()} simulated successfully.",
                        None,
                        {"action_id": action["id"]},
                    )
                self._log_activity(container_uuid, "COMPLETED", "Both simulated messages completed.", None, {})
            processed += int(result.get("actions_created") or 0) > 0
        return processed

    def get_container(self, container_uuid: str) -> dict[str, Any] | None:
        return self.db.fetch_one("SELECT * FROM request_containers WHERE container_uuid = ?", (container_uuid,))

    def list_containers(self, include_completed: bool = False) -> list[dict[str, Any]]:
        self.update_time_states()
        where = "deleted_at IS NULL"
        params: list[Any] = []
        if not include_completed:
            where += " AND state NOT IN (?, ?)"
            params.extend([ContainerState.COMPLETED.value, ContainerState.CANCELLED.value])
        rows = self.db.fetch_all(
            f"""
            SELECT c.*,
                   GROUP_CONCAT(l.external_message_id, ', ') AS matched_event_ids
            FROM request_containers c
            LEFT JOIN request_event_links l ON l.container_uuid = c.container_uuid
            WHERE {where}
            GROUP BY c.id
            ORDER BY
              CASE c.state
                WHEN 'READY_FOR_APPROVAL' THEN 1
                WHEN 'READY_TO_SEND' THEN 2
                WHEN 'WAITING_FOR_ACTION' THEN 3
                WHEN 'WAITING_FOR_IMAGES' THEN 4
                WHEN 'WAITING_FOR_LP' THEN 5
                WHEN 'MANUAL_REVIEW' THEN 6
                WHEN 'INACTIVE' THEN 7
                WHEN 'EXPIRED' THEN 8
                ELSE 9
              END,
              c.updated_at DESC
            """,
            tuple(params),
        )
        for row in rows:
            row["display_state"] = display_state(row["state"])
            row["validation_report"] = self.validator.validate_container(row["container_uuid"]).model_dump()
            row["what_next"] = row["validation_report"]["next_action"]
        return [row for row in rows if row.get("useful_text") or row.get("detected_licence_plate") or int(row.get("image_count") or 0) > 0]

    def what_next(self, container: dict[str, Any]) -> str:
        state = container["state"]
        if state == ContainerState.WAITING_FOR_LP.value:
            return "Ask the rider for the vehicle licence plate."
        if state == ContainerState.WAITING_FOR_IMAGES.value:
            missing = max(0, self.settings.min_required_images - int(container.get("image_count") or 0))
            return f"Waiting for {missing} more image(s)."
        if state == ContainerState.WAITING_FOR_ACTION.value:
            return "Ask whether the vehicle is locked or unlocked."
        if state == ContainerState.READY_FOR_APPROVAL.value:
            return "Review the reply and OPS update, then approve both actions."
        if state == ContainerState.READY_TO_SEND.value:
            return "Simulate sending the queued rider reply and OPS update."
        if state == ContainerState.MANUAL_REVIEW.value:
            return container.get("manual_review_reason") or "Operator review is required."
        if state == ContainerState.INACTIVE.value:
            return "The rider paused; a compatible message can reactivate this request."
        if state == ContainerState.EXPIRED.value:
            return "Restore manually before adding new payloads."
        return "No further action required."

    def list_events(self) -> list[dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM incoming_events ORDER BY id DESC")

    def list_outbound(self) -> list[dict[str, Any]]:
        return self.outbound.list_outbound_requests()

    def list_outbound_actions(self, status: str | None = None) -> list[dict[str, Any]]:
        return self.outbound.list_outbound_actions(status)

    def count_media(self, container_uuid: str) -> int:
        row = self.db.fetch_one("SELECT COUNT(*) AS count FROM request_media WHERE container_uuid = ? AND COALESCE(supplemental, 0) = 0", (container_uuid,))
        return int(row["count"]) if row else 0

    def get_container_media(self, container_uuid: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT external_message_id, external_media_id, media_type, filename, local_path, media_sequence, included_in_outbound
            FROM request_media
            WHERE container_uuid = ?
            ORDER BY id
            """,
            (container_uuid,),
        )

    def update_time_states(self) -> dict[str, int]:
        now = utc_now()
        inactive_cutoff = now - timedelta(seconds=self.settings.request_inactive_seconds)
        inactive_rows = self.db.fetch_all(
            """
            SELECT container_uuid FROM request_containers
            WHERE state IN (?, ?, ?, ?)
              AND COALESCE(last_useful_activity_at, last_activity_at, updated_at) <= ?
              AND deleted_at IS NULL
            """,
            (
                ContainerState.COLLECTING.value,
                ContainerState.WAITING_FOR_LP.value,
                ContainerState.WAITING_FOR_IMAGES.value,
                ContainerState.WAITING_FOR_ACTION.value,
                to_db_time(inactive_cutoff),
            ),
        )
        for row in inactive_rows:
            self.db.execute(
                """
                UPDATE request_containers
                SET previous_state = state,
                    state = ?,
                    inactive_at = COALESCE(inactive_at, ?),
                    paused_at = COALESCE(paused_at, ?),
                    updated_at = ?,
                    latest_revision = latest_revision + 1
                WHERE container_uuid = ?
                """,
                (ContainerState.PAUSED.value, to_db_time(now), to_db_time(now), to_db_time(now), row["container_uuid"]),
            )
            self._log_activity(row["container_uuid"], "PAUSED_FOR_INACTIVITY", "Paused - waiting for the rider to continue.", None, {})
        return {"expired": 0, "inactive": len(inactive_rows)}

    def expire_containers(self) -> int:
        return self.update_time_states()["expired"]

    def correct_licence_plate(self, container_uuid: str, licence_plate: str) -> dict[str, Any]:
        normalized = normalize_licence_plate(licence_plate)
        if not is_valid_licence_plate(normalized):
            raise ValueError("Invalid licence plate")
        self.db.execute(
            """
            UPDATE request_containers
            SET detected_licence_plate = ?, updated_at = ?, last_activity_at = ?, inactive_at = NULL
            WHERE container_uuid = ?
            """,
            (normalized, to_db_time(), to_db_time(), container_uuid),
        )
        return self._refresh_container_state(container_uuid)

    def _location_db_values(self, text: str) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
        loc = extract_location_info(text)
        return (
            loc.location_reference,
            loc.deck,
            loc.level or loc.basement_level,
            loc.lot,
            loc.lot_range,
            loc.bay,
            loc.zone,
            loc.parking_type,
        )

    def _merged_location_values(self, container: dict[str, Any], text: str) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None, str | None, str | None]:
        incoming = self._location_db_values(text)
        existing = (
            container.get("detected_location"),
            container.get("detected_deck"),
            container.get("detected_level"),
            container.get("detected_lot"),
            container.get("detected_lot_range"),
            container.get("detected_bay"),
            container.get("detected_zone"),
            container.get("detected_parking_type"),
        )
        return tuple(existing_value or incoming_value for existing_value, incoming_value in zip(existing, incoming))

    def _log_activity(
        self,
        container_uuid: str,
        activity_type: str,
        friendly_message: str,
        event_id: int | None,
        details: dict[str, Any],
    ) -> None:
        # Avoid noisy duplicate validation/activity lines from Streamlit fragment reruns.
        existing = self.db.fetch_one(
            """
            SELECT id FROM container_activity_log
            WHERE container_uuid = ? AND activity_type = ? AND friendly_message = ?
            ORDER BY id DESC LIMIT 1
            """,
            (container_uuid, activity_type, friendly_message),
        )
        if existing and activity_type in {"VALIDATION_UPDATED", "BECAME_INACTIVE"}:
            return
        self.db.execute(
            """
            INSERT INTO container_activity_log (
                container_uuid, activity_type, friendly_message, technical_details_json,
                incoming_event_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (container_uuid, activity_type, friendly_message, json.dumps(details, sort_keys=True), event_id, to_db_time()),
        )

    def correct_action(self, container_uuid: str, action: str) -> dict[str, Any]:
        normalized = action.strip().upper()
        if normalized not in {ActionIntent.LOCKED.value, ActionIntent.UNLOCKED.value}:
            raise ValueError("Action must be LOCKED or UNLOCKED")
        self.db.execute(
            """
            UPDATE request_containers
            SET detected_action = ?, action_explanation = ?, updated_at = ?, last_activity_at = ?, inactive_at = NULL
            WHERE container_uuid = ?
            """,
            (normalized, f"Operator set action to {normalized}.", to_db_time(), to_db_time(), container_uuid),
        )
        return self._refresh_container_state(container_uuid)

    def mark_manual_review(self, container_uuid: str, reason: str = "manual review") -> None:
        self.db.execute(
            """
            UPDATE request_containers
            SET previous_state = state, state = ?, manual_review_reason = ?, updated_at = ?
            WHERE container_uuid = ?
            """,
            (ContainerState.NEEDS_REVIEW.value, reason, to_db_time(), container_uuid),
        )

    def restore_expired(self, container_uuid: str) -> dict[str, Any]:
        container = self.get_container(container_uuid)
        if not container:
            raise ValueError("Unknown container")
        expires_at = utc_now() + timedelta(seconds=self.settings.container_expiry_seconds)
        self.db.execute(
            """
            UPDATE request_containers
            SET state = COALESCE(previous_state, ?), expires_at = ?, inactive_at = NULL, updated_at = ?, last_activity_at = ?
            WHERE container_uuid = ?
            """,
            (ContainerState.WAITING_FOR_LP.value, to_db_time(expires_at), to_db_time(), to_db_time(), container_uuid),
        )
        return self._refresh_container_state(container_uuid)

    def approve_container(self, container_uuid: str, actor: str = "operator") -> dict[str, Any]:
        container = self._refresh_container_state(container_uuid)
        if container["state"] == ContainerState.READY_TO_SEND.value:
            existing = self.db.fetch_one("SELECT id FROM outbound_requests WHERE container_uuid = ?", (container_uuid,))
            return {"outbound_request_id": int(existing["id"]) if existing else None, "actions_created": 0, "payload": {}}
        if container["state"] != ContainerState.READY_FOR_APPROVAL.value:
            raise ValueError(f"Container is not ready for approval: {display_state(container['state'])}")
        return self.outbound.approve_and_queue(container_uuid, actor=actor)

    def complete_manually(self, container_uuid: str) -> None:
        container = self.get_container(container_uuid)
        if not container:
            raise ValueError("Unknown container")
        if container["state"] == ContainerState.READY_WAITING_QUIET.value:
            self.db.execute("UPDATE request_containers SET dispatch_after = ? WHERE container_uuid = ?", ("2000-01-01T00:00:00+00:00", container_uuid))
            self.process_due_dispatches(limit=1)
            return
        if container["state"] == ContainerState.READY_FOR_APPROVAL.value:
            self.approve_container(container_uuid)
        self.outbound.simulate_request(container_uuid)

    def merge_containers(self, target_uuid: str, source_uuid: str) -> dict[str, Any]:
        target = self.get_container(target_uuid)
        source = self.get_container(source_uuid)
        if not target or not source:
            raise ValueError("Unknown container")
        if target_uuid == source_uuid:
            raise ValueError("Choose two different containers")
        target_lp = target.get("detected_licence_plate")
        source_lp = source.get("detected_licence_plate")
        if target_lp and source_lp and target_lp != source_lp:
            self.mark_manual_review(target_uuid, "manual merge conflict")
            self.mark_manual_review(source_uuid, "manual merge conflict")
            raise ValueError("Containers have conflicting licence plates")
        target_action = target.get("detected_action")
        source_action = source.get("detected_action")
        if target_action and source_action and target_action != source_action:
            self.mark_manual_review(target_uuid, "manual merge action conflict")
            self.mark_manual_review(source_uuid, "manual merge action conflict")
            raise ValueError("Containers have conflicting actions")

        merged_lp = target_lp or source_lp
        merged_action = target_action or source_action
        merged_text = self._join_text(target.get("useful_text") or "", source.get("useful_text") or "")
        for link in self.db.fetch_all("SELECT event_id, external_message_id FROM request_event_links WHERE container_uuid = ?", (source_uuid,)):
            self.db.execute(
                "INSERT OR IGNORE INTO request_event_links (container_uuid, event_id, external_message_id, created_at) VALUES (?, ?, ?, ?)",
                (target_uuid, link["event_id"], link["external_message_id"], to_db_time()),
            )
        self.db.execute("DELETE FROM request_event_links WHERE container_uuid = ?", (source_uuid,))
        self.db.execute("UPDATE request_media SET container_uuid = ? WHERE container_uuid = ?", (target_uuid, source_uuid))
        self.db.execute(
            """
            UPDATE request_containers
            SET detected_licence_plate = ?, detected_action = ?, useful_text = ?, image_count = ?,
                approved_image_count = ?, updated_at = ?, last_activity_at = ?
            WHERE container_uuid = ?
            """,
            (merged_lp, merged_action, merged_text, self.count_media(target_uuid), self.count_media(target_uuid), to_db_time(), to_db_time(), target_uuid),
        )
        self.db.execute(
            "UPDATE request_containers SET deleted_at = ?, previous_state = state, state = ?, updated_at = ? WHERE container_uuid = ?",
            (to_db_time(), ContainerState.CANCELLED.value, to_db_time(), source_uuid),
        )
        return self._refresh_container_state(target_uuid)

    def detach_event(self, container_uuid: str, external_message_id: str) -> None:
        self.db.execute("DELETE FROM request_event_links WHERE container_uuid = ? AND external_message_id = ?", (container_uuid, external_message_id))
        self.db.execute("DELETE FROM request_media WHERE container_uuid = ? AND external_message_id = ?", (container_uuid, external_message_id))
        self.db.execute(
            "UPDATE request_containers SET image_count = ?, approved_image_count = ?, updated_at = ? WHERE container_uuid = ?",
            (self.count_media(container_uuid), self.count_media(container_uuid), to_db_time(), container_uuid),
        )
        self._refresh_container_state(container_uuid)

    def set_media_included(self, media_id: int, included: bool) -> None:
        self.db.execute("UPDATE request_media SET included_in_outbound = ? WHERE id = ?", (1 if included else 0, media_id))

    def delete_test_container(self, container_uuid: str) -> None:
        self.db.execute("UPDATE request_containers SET deleted_at = ?, updated_at = ? WHERE container_uuid = ?", (to_db_time(), to_db_time(), container_uuid))

    def simulate_outbound_send(self, outbound_id: int) -> None:
        request = self.db.fetch_one("SELECT container_uuid FROM outbound_requests WHERE id = ?", (outbound_id,))
        if request:
            self.outbound.simulate_request(request["container_uuid"])
            return
        self.outbound.simulate_action(outbound_id)

    def health(self) -> dict[str, Any]:
        db_health = self.db.health()
        actions = self.list_outbound_actions()
        return {
            "ok": db_health["ok"],
            "sqlite": db_health,
            "request_engine": {
                "ok": True,
                "min_required_images": self.settings.min_required_images,
                "approval_required": self.settings.require_operator_approval,
            },
            "outbound_queue": {"actions": len(actions), "pending": sum(1 for row in actions if row["status"] == "PENDING")},
        }

    def apply_text_to_container(self, container_uuid: str, text: str) -> dict[str, Any]:
        plate = extract_primary_licence_plate(text)
        if plate:
            return self.correct_licence_plate(container_uuid, plate)
        raise ValueError("No valid licence plate found in text")
