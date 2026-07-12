"""Typed domain models used by the request processor."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def new_container_uuid() -> str:
    """Return a short stable container identifier."""

    return uuid4().hex


class ContainerState(StrEnum):
    COLLECTING = "COLLECTING"
    READY_WAITING_QUIET = "READY_WAITING_QUIET"
    DISPATCHING = "DISPATCHING"
    PAUSED = "PAUSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    RECEIVING = "RECEIVING"
    WAITING_FOR_LP = "WAITING_FOR_LP"
    WAITING_FOR_IMAGES = "WAITING_FOR_IMAGES"
    WAITING_FOR_ACTION = "WAITING_FOR_ACTION"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    READY_TO_SEND = "READY_TO_SEND"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INACTIVE = "INACTIVE"
    EXPIRED = "EXPIRED"


DISPLAY_STATE_LABELS = {
    ContainerState.COLLECTING: "Collecting rider messages",
    ContainerState.READY_WAITING_QUIET: "Complete - waiting for messages to finish",
    ContainerState.DISPATCHING: "Sending rider and OPS updates",
    ContainerState.PAUSED: "Paused - waiting for the rider to continue",
    ContainerState.NEEDS_REVIEW: "Needs review",
    ContainerState.FAILED: "Send failed",
    ContainerState.CANCELLED: "Cancelled",
    ContainerState.COMPLETED: "Completed",
    ContainerState.RECEIVING: "Receiving rider messages",
    ContainerState.WAITING_FOR_LP: "Waiting for licence plate",
    ContainerState.WAITING_FOR_IMAGES: "Waiting for more images",
    ContainerState.WAITING_FOR_ACTION: "Waiting for lock/unlock instruction",
    ContainerState.READY_FOR_APPROVAL: "Ready for operator approval",
    ContainerState.READY_TO_SEND: "Approved and ready to send",
    ContainerState.MANUAL_REVIEW: "Needs manual review",
    ContainerState.INACTIVE: "Inactive - waiting for rider to continue",
    ContainerState.EXPIRED: "Expired - manual restoration required",
    ContainerState.CANCELLED: "Cancelled",
}


class ActionIntent(StrEnum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class EventClassification(StrEnum):
    USEFUL_TEXT = "USEFUL_TEXT"
    FILLER_TEXT = "FILLER_TEXT"
    IMAGE = "IMAGE"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class MatchReason(StrEnum):
    MATCHED_BY_CORRELATION = "MATCHED_BY_CORRELATION"
    MATCHED_BY_REPLY = "MATCHED_BY_REPLY"
    MATCHED_BY_BATCH = "MATCHED_BY_BATCH"
    MATCHED_BY_EXACT_LP = "MATCHED_BY_EXACT_LP"
    MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER = "MATCHED_BY_SINGLE_COMPATIBLE_SENDER_CONTAINER"
    NEW_CONTAINER = "NEW_CONTAINER"
    AMBIGUOUS = "AMBIGUOUS"
    DUPLICATE = "DUPLICATE"
    FILLER_IGNORED = "FILLER_IGNORED"
    ERROR = "ERROR"


class PayloadSource(StrEnum):
    SIMULATOR = "SIMULATOR"
    WAAPI = "WAAPI"
    MANUAL = "MANUAL"


class OutboundStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SIMULATED_SENT = "SIMULATED_SENT"
    SENT = "SENT"
    FAILED = "FAILED"


class OutboundActionType(StrEnum):
    RIDER_REPLY = "RIDER_REPLY"
    OPS_GROUP_UPDATE = "OPS_GROUP_UPDATE"
    OPS_GROUP_SUPPLEMENTAL_MEDIA = "OPS_GROUP_SUPPLEMENTAL_MEDIA"


class ProcessingStatus(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    IGNORED = "IGNORED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ERROR = "ERROR"


class MediaItem(BaseModel):
    media_type: str = "image"
    filename: str
    local_path: str | None = None
    sequence: int = 1
    external_media_id: str | None = None
    included_in_outbound: bool = True


class ActionDetection(BaseModel):
    action: ActionIntent = ActionIntent.UNKNOWN
    confidence: float = 0.0
    explanation: str = "No lock or unlock instruction detected."
    matched_phrases: list[str] = Field(default_factory=list)


class ParsedPayload(BaseModel):
    external_message_id: str
    payload_batch_id: str | None = None
    correlation_id: str | None = None
    quoted_message_id: str | None = None
    reply_message_id: str | None = None
    sender_id: str
    sender_display_name: str = ""
    chat_id: str
    chat_display_name: str = ""
    event_type: str = "message"
    text_content: str = ""
    useful_text: str = ""
    licence_plate: str | None = None
    licence_plates: list[str] = Field(default_factory=list)
    action_detection: ActionDetection = Field(default_factory=ActionDetection)
    classification: EventClassification = EventClassification.UNSUPPORTED
    source: PayloadSource = PayloadSource.SIMULATOR
    received_at: datetime = Field(default_factory=utc_now)
    media: list[MediaItem] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class ProcessResult(BaseModel):
    status: str
    event_id: int | None = None
    event_ids: list[int] = Field(default_factory=list)
    external_message_id: str | None = None
    container_uuid: str | None = None
    container_state: str | None = None
    display_state: str | None = None
    duplicate: bool = False
    created_container: bool = False
    completed: bool = False
    outbound_actions_created: int = 0
    match_reason: str | None = None
    classification: str | None = None
    explanation: str = ""
    message: str = ""


def display_state(state: str | ContainerState | None) -> str:
    """Return a beginner-friendly state label."""

    if state is None:
        return ""
    try:
        enum_state = ContainerState(state)
    except ValueError:
        return str(state)
    return DISPLAY_STATE_LABELS[enum_state]


class BatchProcessResult(BaseModel):
    results: list[ProcessResult]

    @property
    def completed_count(self) -> int:
        return sum(1 for result in self.results if result.completed)
