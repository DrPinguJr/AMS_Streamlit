"""Central request validation and checklist generation."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .database import Database, to_db_time
from .location_parser import LocationInfo, extract_location_info
from .models import ActionIntent, ContainerState, OutboundActionType, utc_now
from .request_policy import policy_for_action


class ValidationStatus(StrEnum):
    PASSED = "PASSED"
    MISSING = "MISSING"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    OPTIONAL = "OPTIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ValidationItem(BaseModel):
    key: str
    label: str
    status: ValidationStatus
    value: str | None = None
    explanation: str
    required: bool
    source_event_ids: list[str] = Field(default_factory=list)
    section: str = "Automation safety"


class ValidationReport(BaseModel):
    container_uuid: str
    items: list[ValidationItem]
    missing_required_fields: list[str]
    blockers: list[str]
    warnings: list[str]
    is_technically_complete: bool
    auto_dispatch_eligible: bool
    next_required_input: str
    next_action: str
    summary: str
    story_steps: list[str]


class ValidationEngine:
    """Validate one request container using policy from settings."""

    def __init__(self, db: Database, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def validate_container(self, container_uuid: str) -> ValidationReport:
        container = self.db.fetch_one("SELECT * FROM request_containers WHERE container_uuid = ?", (container_uuid,))
        if not container:
            raise ValueError("Unknown container")

        media = self.db.fetch_all(
            """
            SELECT * FROM request_media
            WHERE container_uuid = ? AND included_in_outbound = 1
              AND COALESCE(supplemental, 0) = 0
              AND lower(media_type) IN ('image', 'photo')
              AND COALESCE(external_media_id, filename, '') != ''
            ORDER BY id
            """,
            (container_uuid,),
        )
        events = self.db.fetch_all(
            """
            SELECT e.* FROM incoming_events e
            JOIN request_event_links l ON l.event_id = e.id
            WHERE l.container_uuid = ?
            ORDER BY e.id
            """,
            (container_uuid,),
        )
        outbound_actions = self.db.fetch_all("SELECT * FROM outbound_actions WHERE container_uuid = ?", (container_uuid,))

        source_ids = [str(event["external_message_id"]) for event in events]
        location = self._location_from_container(container)
        policy = policy_for_action(container.get("detected_action"), self.settings)
        items: list[ValidationItem] = []

        def add(
            key: str,
            label: str,
            status: ValidationStatus,
            value: str | None,
            explanation: str,
            required: bool,
            section: str,
        ) -> None:
            items.append(
                ValidationItem(
                    key=key,
                    label=label,
                    status=status,
                    value=value,
                    explanation=explanation,
                    required=required,
                    source_event_ids=source_ids,
                    section=section,
                )
            )

        add(
            "MISSING_SENDER",
            "Rider identified",
            ValidationStatus.PASSED if container.get("sender_id") else ValidationStatus.MISSING,
            container.get("sender_id"),
            "Rider phone number is known." if container.get("sender_id") else "Waiting for a rider identifier.",
            True,
            "Request identity",
        )
        add(
            "MISSING_CHAT",
            "Chat identified",
            ValidationStatus.PASSED if container.get("chat_id") else ValidationStatus.MISSING,
            container.get("chat_id"),
            "Originating chat is known." if container.get("chat_id") else "Waiting for a chat identifier.",
            True,
            "Request identity",
        )
        lp = container.get("detected_licence_plate")
        add(
            "MISSING_LICENCE_PLATE",
            "Licence plate detected",
            ValidationStatus.PASSED if lp else ValidationStatus.MISSING,
            lp,
            f"Vehicle plate {lp} was resolved." if lp else "Waiting for the rider to send the vehicle plate.",
            True,
            "Request identity",
        )

        image_count = len(media)
        missing_images = max(0, self.settings.min_required_images - image_count)
        add(
            "MISSING_IMAGES",
            f"{self.settings.min_required_images} required images received",
            ValidationStatus.PASSED if missing_images == 0 else ValidationStatus.MISSING,
            f"{image_count} / {self.settings.min_required_images} unique images",
            "Enough unique eligible images were received."
            if missing_images == 0
            else f"{missing_images} more unique image(s) required.",
            True,
            "Evidence received",
        )
        add(
            "ADDITIONAL_IMAGES_PRESENT",
            "Additional images",
            ValidationStatus.WARNING if image_count > self.settings.min_required_images else ValidationStatus.NOT_APPLICABLE,
            str(max(0, image_count - self.settings.min_required_images)) if image_count > self.settings.min_required_images else None,
            f"{self.settings.min_required_images} required images + {image_count - self.settings.min_required_images} additional image(s)."
            if image_count > self.settings.min_required_images
            else "No extra images beyond the required count.",
            False,
            "Evidence received",
        )

        configured_action = self.settings.default_action if self.settings.default_action in {ActionIntent.LOCKED.value, ActionIntent.UNLOCKED.value} else None
        action = container.get("detected_action") or configured_action
        action_ok = action in {ActionIntent.LOCKED.value, ActionIntent.UNLOCKED.value}
        add(
            "MISSING_ACTION",
            "Lock/unlock action detected",
            ValidationStatus.PASSED if action_ok else ValidationStatus.MISSING,
            action,
            f"Action {action} was resolved." if action_ok else "Waiting for a clear LOCKED or UNLOCKED instruction.",
            True,
            "Operational information",
        )
        add(
            "MISSING_LOCATION_REFERENCE",
            "Location detected",
            ValidationStatus.PASSED if location.has_location else ValidationStatus.MISSING,
            location.location_reference or location.raw_location_text,
            "A rider-supplied location reference was detected." if location.has_location else "No address, station, deck, lot, bay or zone was detected.",
            policy.require_location_reference,
            "Operational information",
        )
        add(
            "MISSING_PARKING_POSITION",
            "Parking position detected",
            ValidationStatus.PASSED if location.has_parking_position else ValidationStatus.MISSING,
            location.display_location or None,
            "A sufficiently specific parking position was detected."
            if location.has_parking_position
            else "Waiting for a lot, bay, deck, level, zone, white-lot or station reference.",
            policy.require_parking_position,
            "Operational information",
        )
        deck_required = policy.require_deck_for_mscp and location.is_mscp
        add(
            "MISSING_MSCP_DECK",
            "Deck or level for MSCP",
            ValidationStatus.PASSED
            if deck_required and (location.deck or location.level or location.basement_level)
            else ValidationStatus.MISSING
            if deck_required
            else ValidationStatus.NOT_APPLICABLE,
            location.deck or location.level or location.basement_level,
            "Deck or level was supplied for the MSCP."
            if deck_required and (location.deck or location.level or location.basement_level)
            else "Deck or level missing for this MSCP."
            if deck_required
            else "Deck is not required for this location type.",
            deck_required,
            "Operational information",
        )
        lot_required = policy.require_lot_number
        add(
            "NO_LOT_NUMBER",
            "Lot number",
            ValidationStatus.PASSED
            if location.lot or location.lot_range
            else ValidationStatus.MISSING
            if lot_required
            else ValidationStatus.OPTIONAL,
            location.lot or location.lot_range,
            "A lot number was supplied."
            if location.lot or location.lot_range
            else "Optional - no numbered lot supplied.",
            lot_required,
            "Operational information",
        )

        manual_reason = container.get("manual_review_reason") or ""
        ambiguous = "accept these images" in manual_reason.lower() or "ambiguous" in manual_reason.lower()
        lp_conflict = "licence plate" in manual_reason.lower() or "multiple licence plates" in manual_reason.lower()
        action_conflict = "action" in manual_reason.lower() or "lock" in manual_reason.lower() and "conflict" in manual_reason.lower()
        add(
            "MULTIPLE_LICENCE_PLATES",
            "One licence plate only",
            ValidationStatus.BLOCKED if lp_conflict else ValidationStatus.PASSED,
            manual_reason if lp_conflict else lp,
            manual_reason if lp_conflict else "No unresolved licence-plate conflict.",
            True,
            "Automation safety",
        )
        add(
            "CONFLICTING_ACTION",
            "One action only",
            ValidationStatus.BLOCKED if action_conflict else ValidationStatus.PASSED,
            manual_reason if action_conflict else action,
            manual_reason if action_conflict else "No unresolved action conflict.",
            True,
            "Automation safety",
        )
        add(
            "AMBIGUOUS_CONTAINER_MATCH",
            "Request matched safely",
            ValidationStatus.BLOCKED if ambiguous else ValidationStatus.PASSED,
            manual_reason if ambiguous else None,
            manual_reason if ambiguous else "No unresolved matching ambiguity.",
            True,
            "Automation safety",
        )
        terminal_block = container.get("state") in {ContainerState.EXPIRED.value, ContainerState.CANCELLED.value, ContainerState.FAILED.value}
        add(
            "EXPIRED_CONTAINER",
            "Container is active",
            ValidationStatus.BLOCKED if terminal_block else ValidationStatus.PASSED,
            container.get("state"),
            "Expired, failed or cancelled containers cannot auto-dispatch." if terminal_block else "Container is eligible for validation.",
            True,
            "Automation safety",
        )
        already_dispatched = bool(outbound_actions) or bool(container.get("auto_dispatched_at"))
        add(
            "ALREADY_DISPATCHED",
            "Not already dispatched",
            ValidationStatus.BLOCKED if already_dispatched else ValidationStatus.PASSED,
            str(len(outbound_actions)) if already_dispatched else None,
            "Outbound actions already exist for this request." if already_dispatched else "No outbound actions have been created yet.",
            True,
            "Automation safety",
        )

        missing_required = [
            item.key
            for item in items
            if item.required and item.status == ValidationStatus.MISSING
        ]
        blockers = [
            item.key
            for item in items
            if item.status == ValidationStatus.BLOCKED
        ]
        warnings = [
            item.key
            for item in items
            if item.status == ValidationStatus.WARNING
        ]
        is_complete = not missing_required and not blockers
        auto_eligible = (
            self.settings.automation_mode
            and self.settings.auto_dispatch_complete_requests
            and is_complete
            and not already_dispatched
        )
        next_required_input = self._next_required_input(items)
        next_action = self._next_action(auto_eligible, missing_required, blockers, next_required_input)
        summary = self._summary(is_complete, missing_required, blockers)
        story = self._story(container_uuid, container, items, events)

        report = ValidationReport(
            container_uuid=container_uuid,
            items=items,
            missing_required_fields=missing_required,
            blockers=blockers,
            warnings=warnings,
            is_technically_complete=is_complete,
            auto_dispatch_eligible=auto_eligible,
            next_required_input=next_required_input,
            next_action=next_action,
            summary=summary,
            story_steps=story,
        )
        self.persist_report(report)
        return report

    def _location_from_container(self, container: dict[str, Any]) -> LocationInfo:
        info = LocationInfo(
            location_reference=container.get("detected_location"),
            address_text=container.get("detected_address"),
            deck=container.get("detected_deck"),
            level=container.get("detected_level"),
            lot=container.get("detected_lot"),
            lot_range=container.get("detected_lot_range"),
            bay=container.get("detected_bay"),
            zone=container.get("detected_zone"),
            parking_type=container.get("detected_parking_type"),
            raw_location_text=container.get("useful_text"),
        )
        parsed = extract_location_info(container.get("useful_text") or "")
        return LocationInfo(
            location_reference=info.location_reference or parsed.location_reference,
            address_text=info.address_text or parsed.address_text,
            pickup_dropoff_context=parsed.pickup_dropoff_context,
            deck=info.deck or parsed.deck,
            level=info.level or parsed.level,
            basement_level=parsed.basement_level,
            lot=info.lot or parsed.lot,
            lot_range=info.lot_range or parsed.lot_range,
            bay=info.bay or parsed.bay,
            zone=info.zone or parsed.zone,
            parking_type=info.parking_type or parsed.parking_type,
            raw_location_text=info.raw_location_text or parsed.raw_location_text,
        )

    def _next_required_input(self, items: list[ValidationItem]) -> str:
        missing = [item for item in items if item.required and item.status == ValidationStatus.MISSING]
        if not missing:
            return "All required information received"
        return "; ".join(item.explanation for item in missing)

    def _next_action(self, eligible: bool, missing: list[str], blockers: list[str], next_input: str) -> str:
        if eligible:
            return "All checks passed. The rider reply and OPS-group update will be dispatched automatically."
        if blockers:
            return "Automation stopped. Operator review is required before dispatch."
        if missing:
            return f"The system is waiting for: {next_input}."
        return "Validation completed."

    def _summary(self, complete: bool, missing: list[str], blockers: list[str]) -> str:
        if blockers:
            return "Automation stopped - manual review required."
        if complete:
            return "All hard validation checks passed."
        return f"{len(missing)} required item(s) missing."

    def _story(
        self,
        container_uuid: str,
        container: dict[str, Any],
        items: list[ValidationItem],
        events: list[dict[str, Any]],
    ) -> list[str]:
        activity = self.db.fetch_all(
            """
            SELECT friendly_message, created_at FROM container_activity_log
            WHERE container_uuid = ?
            ORDER BY id
            """,
            (container_uuid,),
        )
        steps = [f"{str(row['created_at'])[11:19]} - {row['friendly_message']}" for row in activity]
        if not steps:
            for event in events:
                if event.get("text_content"):
                    steps.append(f"Rider sent text: {event['text_content']}")
                else:
                    steps.append(f"Rider sent {event.get('event_type', 'payload')}.")
            if container.get("detected_licence_plate"):
                steps.append(f"Licence plate {container['detected_licence_plate']} was detected.")
            if container.get("detected_action"):
                steps.append(f"Action {container['detected_action']} was detected.")
        missing = [item.explanation for item in items if item.required and item.status == ValidationStatus.MISSING]
        blocked = [item.explanation for item in items if item.status == ValidationStatus.BLOCKED]
        if blocked:
            steps.append("Automation stopped instead of guessing.")
        elif missing:
            steps.append("The system is waiting for: " + "; ".join(missing))
        else:
            steps.append("All required checks passed.")
        return steps

    def persist_report(self, report: ValidationReport) -> None:
        self.db.execute(
            """
            UPDATE request_containers
            SET validation_status = ?,
                validation_summary = ?,
                missing_fields_json = ?,
                warnings_json = ?,
                blockers_json = ?,
                auto_dispatch_eligible = ?,
                last_validation_at = ?
            WHERE container_uuid = ?
            """,
            (
                "PASSED" if report.is_technically_complete else "BLOCKED" if report.blockers else "MISSING",
                report.summary,
                json.dumps(report.missing_required_fields),
                json.dumps(report.warnings),
                json.dumps(report.blockers),
                1 if report.auto_dispatch_eligible else 0,
                to_db_time(utc_now()),
                report.container_uuid,
            ),
        )


def validate_container(container_uuid: str, db: Database | None = None, settings: Settings | None = None) -> ValidationReport:
    """Validate one container using a shared report model."""

    settings = settings or get_settings()
    db = db or Database(settings)
    return ValidationEngine(db, settings).validate_container(container_uuid)
