"""Reusable simulated WhatsApp-style payloads for local testing."""

from __future__ import annotations

import random
import inspect
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_SENDER_ID = "6591234567"
DEFAULT_CHAT_ID = "6598765432@c.us"
DEFAULT_SENDER_NAME = "Rider A"
DEFAULT_CHAT_NAME = "Rider A Chat"
SENDER_DEFAULT = DEFAULT_SENDER_ID
CHAT_DEFAULT = DEFAULT_CHAT_ID


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_placeholder_images(count: int = 12) -> list[dict[str, str]]:
    """Create tiny local placeholder image files and return metadata."""

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    images: list[dict[str, str]] = []
    # A tiny valid GIF byte stream, saved with .gif filenames to avoid dependencies.
    gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    for index in range(1, count + 1):
        path = DATA_DIR / f"placeholder_{index:02d}.gif"
        if not path.exists():
            path.write_bytes(gif_bytes)
        images.append(
            {
                "media_type": "image",
                "filename": path.name,
                "local_path": str(path),
            }
        )
    return images


def _payload(
    suffix: str,
    *,
    text: str = "",
    image_count: int = 0,
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    sender_display_name: str = DEFAULT_SENDER_NAME,
    chat_display_name: str = DEFAULT_CHAT_NAME,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    payload_batch_id: str | None = None,
    message_id: str | None = None,
    source: str = "SIMULATOR",
    **_: object,
) -> dict[str, Any]:
    images = ensure_placeholder_images(max(12, image_count))[:image_count]
    external_id = message_id or f"sim-{suffix.lower()}-001"
    lp = licence_plate or "SMP3890P"
    text = text.replace("{lp}", lp)
    return {
        "external_message_id": external_id,
        "payload_batch_id": payload_batch_id or f"batch-{suffix.lower()}-001",
        "correlation_id": correlation_id,
        "sender_id": sender_id,
        "sender_display_name": sender_display_name,
        "chat_id": chat_id,
        "chat_display_name": chat_display_name,
        "event_type": "mixed" if text and image_count else "image" if image_count else "message",
        "text": text,
        "source": source,
        "received_at": _timestamp(),
        "media": [
            {
                **item,
                "sequence": index,
                "external_media_id": f"sim-{suffix.lower()}-media-{index:03d}",
            }
            for index, item in enumerate(images, start=1)
        ],
    }


def payload_a(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    payload = _payload(
        "A",
        text="{lp}\nPickup complete at Deck 3 Lot 42. Vehicle secured and locked after photo set.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )
    return payload


def payload_b(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "B",
        text="Vehicle locked at Deck 2 Lot 18, parked near charger.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_c(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "C",
        text="{lp} drop-off at B2 Lot 19. Lock completed, charger connected.",
        image_count=0,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_d(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload("D", text="", image_count=7, sender_id=sender_id, chat_id=chat_id, licence_plate=licence_plate, correlation_id=correlation_id, **kwargs)


def payload_e(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload("E", text="hello ok thanks bro", image_count=0, sender_id=sender_id, chat_id=chat_id, licence_plate=licence_plate, correlation_id=correlation_id, **kwargs)


def payload_f_duplicate(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return payload_a(sender_id=sender_id, chat_id=chat_id, licence_plate=licence_plate, correlation_id=correlation_id, **kwargs)


def payload_g(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "G",
        text="{lp} and SNY9109P correction for same request, MSCP Deck 5 Lot 51. Vehicle locked.",
        image_count=0,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id or "sim-c-001",
        **kwargs,
    )


def payload_h(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload("H", text="", image_count=3, sender_id=sender_id, chat_id=chat_id, licence_plate=licence_plate, correlation_id=correlation_id, **kwargs)


def payload_i(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload("I", text="", image_count=4, sender_id=sender_id, chat_id=chat_id, licence_plate=licence_plate, correlation_id=correlation_id, **kwargs)


def payload_j(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "J",
        text="{lp} pickup at Station 12 Zone C. Please unlock for collection.",
        image_count=0,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate or "SNY9109P",
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_k(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "K",
        text="{lp} vehicle locked at MSCP Lot 42.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_l(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "L",
        text="{lp} vehicle locked at Surface Lot 75.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_m(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "M",
        text="{lp} vehicle locked at MSCP Deck 5A White Lots.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


def payload_n(
    sender_id: str = DEFAULT_SENDER_ID,
    chat_id: str = DEFAULT_CHAT_ID,
    licence_plate: str | None = None,
    correlation_id: str | None = None,
    **kwargs: object,
) -> dict[str, Any]:
    return _payload(
        "N",
        text="{lp} at Deck 3 Lot 42.",
        image_count=7,
        sender_id=sender_id,
        chat_id=chat_id,
        licence_plate=licence_plate,
        correlation_id=correlation_id,
        **kwargs,
    )


PAYLOAD_BUILDERS = {
    "A": payload_a,
    "B": payload_b,
    "C": payload_c,
    "D": payload_d,
    "E": payload_e,
    "F": payload_f_duplicate,
    "G": payload_g,
    "H": payload_h,
    "I": payload_i,
    "J": payload_j,
    "K": payload_k,
    "L": payload_l,
    "M": payload_m,
    "N": payload_n,
}


def _call_builder(builder: Callable[..., dict[str, Any]], overrides: dict[str, Any]) -> dict[str, Any]:
    signature = inspect.signature(builder)
    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    if accepts_kwargs:
        return builder(**overrides)
    supported = {key: value for key, value in overrides.items() if key in signature.parameters}
    return builder(**supported)


def get_payload(name: str, **overrides: Any) -> dict[str, Any]:
    """Return a deep copy of a named payload using a defensive builder call."""

    key = name.upper()
    if key not in PAYLOAD_BUILDERS:
        raise ValueError(f"Unknown simulated payload '{name}'. Choose one of {', '.join(PAYLOAD_BUILDERS)}.")
    builder = PAYLOAD_BUILDERS[key]
    payload = _call_builder(builder, overrides)
    return deepcopy(payload)


def random_payload(seed: int | None = None, unique: bool = True, **overrides: Any) -> dict[str, Any]:
    """Return a random simulated payload."""

    rng = random.Random(seed)
    name = rng.choice(list(PAYLOAD_BUILDERS.keys()))
    payload = get_payload(name, **overrides)
    if unique:
        unique_suffix = rng.randrange(1_000_000)
        payload["external_message_id"] = f"{payload['external_message_id']}-{unique_suffix}"
        payload["payload_batch_id"] = f"{payload.get('payload_batch_id', 'batch')}-{unique_suffix}"
        for media in payload.get("media", []):
            media["external_media_id"] = f"{media.get('external_media_id', 'media')}-{unique_suffix}"
    return payload


def random_payload_sequence(count: int, seed: int | None = None, **overrides: Any) -> list[dict[str, Any]]:
    """Return a deterministic random payload sequence."""

    rng = random.Random(seed)
    return [random_payload(seed=rng.randrange(10_000_000), unique=True, **overrides) for _ in range(count)]
