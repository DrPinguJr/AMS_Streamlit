from Flexar.whatsapp_request_processor.payload_parser import (
    clean_useful_text,
    detect_action_intent,
    extract_licence_plates,
    extract_primary_licence_plate,
    is_valid_licence_plate,
    normalize_licence_plate,
    parse_payload,
)
from Flexar.whatsapp_request_processor.models import ActionIntent, EventClassification


def test_licence_plate_extraction_and_normalisation() -> None:
    assert extract_primary_licence_plate("Need pickup for SMP 3890 P") == "SMP3890P"
    assert extract_primary_licence_plate("SMP-3890-P photos sent") == "SMP3890P"
    assert extract_licence_plates("SNY9109P and SLU 9479 R") == ["SNY9109P", "SLU9479R"]
    assert extract_primary_licence_plate("SNY9109P and SLU 9479 R") is None
    assert extract_licence_plates("smp3890p then SMP 3890 P") == ["SMP3890P"]
    assert normalize_licence_plate("sls-4281-l") == "SLS4281L"


def test_invalid_lp_rejection() -> None:
    assert not is_valid_licence_plate("HELLO123")
    assert not is_valid_licence_plate("ABC1234D")
    assert extract_primary_licence_plate("ordinary number 123456 and hello") is None


def test_useful_text_filtering() -> None:
    assert clean_useful_text("hello\nok thanks bro") == ""
    cleaned = clean_useful_text("please\nSMP3890P\nDeck 3 lot 42\nsent images")
    assert "SMP3890P" in cleaned
    assert "Deck 3 lot 42" in cleaned
    assert "please" not in cleaned


def test_action_intent_detection() -> None:
    assert detect_action_intent("please unlock SMP3890P").action == ActionIntent.UNLOCKED
    assert detect_action_intent("vehicle unlocked").action == ActionIntent.UNLOCKED
    assert detect_action_intent("done locking SMP3890P").action == ActionIntent.LOCKED
    assert detect_action_intent("vehicle locked").action == ActionIntent.LOCKED
    assert detect_action_intent("not locked yet").action == ActionIntent.UNKNOWN
    assert detect_action_intent("unlock first, then lock later").action == ActionIntent.CONFLICTING


def test_conflicting_plates_classification() -> None:
    payload = {
        "external_message_id": "conflict-1",
        "sender_id": "6591234567",
        "chat_id": "6591234567@c.us",
        "text": "SMP3890P and SNY9109P both mentioned",
    }
    parsed = parse_payload(payload)
    assert parsed.classification == EventClassification.CONFLICT
    assert parsed.licence_plate is None

