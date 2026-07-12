from __future__ import annotations

import pytest

from Flexar.whatsapp_request_processor.test_payloads import PAYLOAD_BUILDERS, get_payload


def test_all_builders_accept_common_overrides() -> None:
    for name in PAYLOAD_BUILDERS:
        payload = get_payload(name, sender_id="6599999999", chat_id="test@c.us", licence_plate="SLU9479R")
        assert payload["sender_id"] == "6599999999"
        assert payload["chat_id"] == "test@c.us"


def test_payload_f_no_type_error_and_preserves_duplicate_ids() -> None:
    original = get_payload("A", sender_id="6599999999", chat_id="test@c.us", licence_plate="SMP3890P")
    duplicate = get_payload("F", sender_id="6599999999", chat_id="test@c.us", licence_plate="SMP3890P")
    assert duplicate["external_message_id"] == original["external_message_id"]
    assert [m["external_media_id"] for m in duplicate["media"]] == [m["external_media_id"] for m in original["media"]]


def test_unknown_payload_name_raises_value_error() -> None:
    with pytest.raises(ValueError):
        get_payload("Z")

