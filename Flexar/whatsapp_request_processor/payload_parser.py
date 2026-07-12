"""Parse simulated and future WAAPI-style payloads."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import ActionDetection, ActionIntent, EventClassification, MediaItem, ParsedPayload, PayloadSource, utc_now


LP_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{1,3})[\s-]*(\d{1,4})[\s-]*([A-Z])(?!(?:[A-Z0-9]))",
    re.IGNORECASE,
)

FILLER_WORDS = {
    "hello",
    "hi",
    "ok",
    "okay",
    "thanks",
    "thank",
    "you",
    "bro",
    "can",
    "please",
    "pls",
    "sent",
    "image",
    "images",
    "photo",
    "photos",
}

USEFUL_HINTS = {
    "pickup",
    "pick",
    "drop",
    "dropoff",
    "drop-off",
    "lot",
    "deck",
    "basement",
    "b1",
    "b2",
    "b3",
    "level",
    "parking",
    "parked",
    "lock",
    "unlock",
    "complete",
    "completed",
    "done",
    "fault",
    "damage",
    "remarks",
    "remark",
    "left",
    "right",
    "front",
    "rear",
    "charging",
    "charger",
    "bay",
}


def normalize_licence_plate(value: str) -> str:
    """Normalize a licence plate by removing spaces and hyphens."""

    return re.sub(r"[\s-]+", "", value).upper()


def is_valid_licence_plate(value: str) -> bool:
    """Return True when the value looks like a Singapore-style plate."""

    normalized = normalize_licence_plate(value)
    match = re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]", normalized)
    if not match:
        return False
    letters = re.match(r"[A-Z]+", normalized)
    prefix = letters.group(0) if letters else ""
    digits = re.search(r"\d+", normalized)
    digit_text = digits.group(0) if digits else ""
    return prefix.startswith("S") and 1 <= len(digit_text) <= 4


def extract_licence_plates(text: str) -> list[str]:
    """Extract normalized licence plates from text in encounter order."""

    found: list[str] = []
    for match in LP_PATTERN.finditer(text or ""):
        candidate = normalize_licence_plate("".join(match.groups()))
        if is_valid_licence_plate(candidate) and candidate not in found:
            found.append(candidate)
    return found


def extract_primary_licence_plate(text: str) -> str | None:
    """Return one valid licence plate, or None when absent or conflicting."""

    plates = extract_licence_plates(text)
    return plates[0] if len(plates) == 1 else None


LOCK_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\block(?:ed|ing)?\b",
        r"\bsecure vehicle\b",
        r"\bsecured vehicle\b",
        r"\bcar secured\b",
        r"\bvehicle secured\b",
    ]
]

UNLOCK_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bunlock(?:ed|ing)?\b",
        r"\bopen vehicle\b",
        r"\bopen car\b",
        r"\bvehicle opened\b",
        r"\bready for collection\b",
    ]
]

NEGATED_LOCK_PATTERN = re.compile(
    r"\b(?:not|no|never|havent|haven't|hasnt|hasn't|isnt|isn't|not yet)\s+(?:\w+\s+){0,2}lock(?:ed|ing)?\b",
    re.IGNORECASE,
)


def _is_negated_lock(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 28) : min(len(text), end + 8)]
    return bool(NEGATED_LOCK_PATTERN.search(window))


def detect_action_intent(text: str) -> ActionDetection:
    """Detect LOCKED/UNLOCKED/UNKNOWN/CONFLICTING with phrase-aware rules."""

    if not text:
        return ActionDetection()

    lock_phrases: list[str] = []
    unlock_phrases: list[str] = []

    for pattern in LOCK_PATTERNS:
        for match in pattern.finditer(text):
            if pattern.pattern.startswith(r"\block") and _is_negated_lock(text, match.start(), match.end()):
                continue
            phrase = match.group(0).strip()
            if phrase.lower() not in {item.lower() for item in lock_phrases}:
                lock_phrases.append(phrase)

    for pattern in UNLOCK_PATTERNS:
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            if phrase.lower() not in {item.lower() for item in unlock_phrases}:
                unlock_phrases.append(phrase)

    if lock_phrases and unlock_phrases:
        phrases = unlock_phrases + lock_phrases
        return ActionDetection(
            action=ActionIntent.CONFLICTING,
            confidence=1.0,
            explanation=f"Needs review because both lock and unlock instructions were found: {', '.join(phrases)}.",
            matched_phrases=phrases,
        )
    if unlock_phrases:
        return ActionDetection(
            action=ActionIntent.UNLOCKED,
            confidence=0.95,
            explanation=f"Detected UNLOCKED because the message contains '{unlock_phrases[0]}'.",
            matched_phrases=unlock_phrases,
        )
    if lock_phrases:
        return ActionDetection(
            action=ActionIntent.LOCKED,
            confidence=0.95,
            explanation=f"Detected LOCKED because the message contains '{lock_phrases[0]}'.",
            matched_phrases=lock_phrases,
        )
    return ActionDetection()


def clean_useful_text(text: str) -> str:
    """Keep operationally useful lines and discard obvious filler."""

    if not text:
        return ""
    useful_lines: list[str] = []
    for raw_line in re.split(r"[\r\n]+", text):
        line = raw_line.strip()
        if not line:
            continue
        words = re.findall(r"[A-Za-z0-9-]+", line.lower())
        if not words:
            continue
        has_plate = bool(extract_licence_plates(line))
        only_filler = all(word in FILLER_WORDS for word in words)
        has_hint = any(word in USEFUL_HINTS for word in words)
        has_location_code = bool(re.search(r"\b(?:lot|deck|lvl|level|b\d|bay)\s*[-#]?\s*\w+", line, re.IGNORECASE))
        if has_plate or has_hint or has_location_code or not only_filler:
            if not only_filler:
                useful_lines.append(line)
            elif has_plate or has_hint:
                useful_lines.append(line)
    return "\n".join(useful_lines)


def split_payload_batch(raw_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one or more message-like payloads from a webhook body."""

    if "messages" in raw_payload and isinstance(raw_payload["messages"], list):
        base = {key: value for key, value in raw_payload.items() if key != "messages"}
        return [{**base, **message} for message in raw_payload["messages"] if isinstance(message, dict)]
    if "events" in raw_payload and isinstance(raw_payload["events"], list):
        base = {key: value for key, value in raw_payload.items() if key != "events"}
        return [{**base, **event} for event in raw_payload["events"] if isinstance(event, dict)]
    return [raw_payload]


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return utc_now()
    return utc_now()


def _coalesce(*values: Any, default: str = "") -> str:
    for value in values:
        if value is not None and value != "":
            return str(value)
    return default


def _extract_media(raw_payload: dict[str, Any]) -> list[MediaItem]:
    media_values = raw_payload.get("media") or raw_payload.get("images") or raw_payload.get("attachments") or []
    if isinstance(media_values, dict):
        media_values = [media_values]
    media: list[MediaItem] = []
    for index, item in enumerate(media_values, start=1):
        if isinstance(item, str):
            media.append(MediaItem(filename=item, local_path=item, sequence=index))
            continue
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("media_type") or item.get("type") or "image")
        filename = str(item.get("filename") or item.get("file_name") or f"image_{index}.jpg")
        local_path = item.get("local_path") or item.get("path") or item.get("url")
        external_media_id = item.get("external_media_id") or item.get("media_id") or item.get("id")
        media.append(
            MediaItem(
                media_type=media_type,
                filename=filename,
                local_path=local_path,
                sequence=int(item.get("sequence") or index),
                external_media_id=str(external_media_id) if external_media_id else None,
                included_in_outbound=bool(item.get("included_in_outbound", True)),
            )
        )
    return media


def classify_payload(text: str, media: list[MediaItem], plates: list[str], action: ActionDetection) -> EventClassification:
    """Classify one normalized event for display and matching."""

    useful_text = clean_useful_text(text)
    if len(plates) > 1 or action.action == ActionIntent.CONFLICTING:
        return EventClassification.CONFLICT
    if media and not text:
        return EventClassification.IMAGE
    if useful_text:
        return EventClassification.USEFUL_TEXT
    if text:
        return EventClassification.FILLER_TEXT
    return EventClassification.UNSUPPORTED


def parse_payload(raw_payload: dict[str, Any]) -> ParsedPayload:
    """Parse a message payload into normalized fields used by the engine."""

    if not isinstance(raw_payload, dict):
        raise ValueError("Payload must be a JSON object")

    message = raw_payload.get("message") if isinstance(raw_payload.get("message"), dict) else {}
    text_content = _coalesce(
        raw_payload.get("text"),
        raw_payload.get("body"),
        raw_payload.get("caption"),
        message.get("text"),
        message.get("body"),
        default="",
    )
    media = _extract_media(raw_payload)
    event_type = _coalesce(raw_payload.get("event_type"), raw_payload.get("type"), default="message")
    if media and not text_content:
        event_type = "image"
    elif media and text_content:
        event_type = "mixed"

    external_message_id = _coalesce(
        raw_payload.get("external_message_id"),
        raw_payload.get("message_id"),
        raw_payload.get("id"),
        message.get("id"),
    )
    if not external_message_id:
        raise ValueError("Payload is missing external_message_id")

    for index, item in enumerate(media, start=1):
        if not item.external_media_id:
            item.external_media_id = f"{external_message_id}:media:{index}"

    sender_id = _coalesce(raw_payload.get("sender_id"), raw_payload.get("from"), message.get("from"))
    chat_id = _coalesce(raw_payload.get("chat_id"), raw_payload.get("chatId"), raw_payload.get("to"), message.get("chat_id"))
    if not sender_id or not chat_id:
        raise ValueError("Payload is missing sender_id or chat_id")

    plates = extract_licence_plates(text_content)
    action_detection = detect_action_intent(text_content)
    useful_text = clean_useful_text(text_content)
    classification = classify_payload(text_content, media, plates, action_detection)
    source_value = str(raw_payload.get("source") or "SIMULATOR").upper()
    try:
        source = PayloadSource(source_value)
    except ValueError:
        source = PayloadSource.SIMULATOR

    return ParsedPayload(
        external_message_id=external_message_id,
        payload_batch_id=raw_payload.get("payload_batch_id"),
        correlation_id=raw_payload.get("correlation_id"),
        quoted_message_id=raw_payload.get("quoted_message_id"),
        reply_message_id=raw_payload.get("reply_message_id"),
        sender_id=sender_id,
        sender_display_name=str(raw_payload.get("sender_display_name") or raw_payload.get("push_name") or sender_id),
        chat_id=chat_id,
        chat_display_name=str(raw_payload.get("chat_display_name") or chat_id),
        event_type=event_type,
        text_content=text_content,
        useful_text=useful_text,
        licence_plate=plates[0] if len(plates) == 1 else None,
        licence_plates=plates,
        action_detection=action_detection,
        classification=classification,
        source=source,
        received_at=_parse_timestamp(raw_payload.get("received_at") or raw_payload.get("timestamp")),
        media=media,
        raw_payload=raw_payload,
    )
