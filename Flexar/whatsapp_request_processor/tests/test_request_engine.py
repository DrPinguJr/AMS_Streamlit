from __future__ import annotations

from datetime import timedelta

from Flexar.whatsapp_request_processor.database import to_db_time
from Flexar.whatsapp_request_processor.models import ContainerState
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def process(engine: RequestEngine, name: str, **overrides):
    return engine.process_payload(get_payload(name, **overrides))


def test_new_container_creation(engine: RequestEngine) -> None:
    result = process(engine, "C")
    assert result.container_state == ContainerState.COLLECTING
    assert len(engine.list_containers(include_completed=True)) == 1


def test_exact_lp_matching(engine: RequestEngine) -> None:
    first = process(engine, "C")
    image_payload = get_payload("H", sender_id="6590000000", chat_id="other@c.us")
    image_payload["text"] = "SMP3890P additional photos"
    image_payload["external_message_id"] = "lp-match-images"
    result = engine.process_payload(image_payload)
    assert result.container_uuid == first.container_uuid


def test_sender_chat_fallback_matching(engine: RequestEngine) -> None:
    first = process(engine, "D")
    second = process(engine, "C")
    assert second.container_uuid == first.container_uuid
    assert second.container_state == ContainerState.COMPLETED


def test_ambiguous_matching_creates_manual_review_container(engine: RequestEngine) -> None:
    process(engine, "C")
    process(engine, "J")
    result = process(engine, "D", message_id="ambiguous-images")
    assert result.container_state == ContainerState.NEEDS_REVIEW
    assert not result.completed


def test_c_then_d_completes(engine: RequestEngine) -> None:
    result_c = process(engine, "C")
    result_d = process(engine, "D")
    assert result_d.container_uuid == result_c.container_uuid
    assert result_d.container_state == ContainerState.COMPLETED
    assert len(engine.list_outbound()) == 1


def test_d_then_c_completes(engine: RequestEngine) -> None:
    result_d = process(engine, "D")
    result_c = process(engine, "C")
    assert result_c.container_uuid == result_d.container_uuid
    assert result_c.container_state == ContainerState.COMPLETED
    assert engine.get_container(result_c.container_uuid)["image_count"] == 7


def test_h_plus_i_plus_c_completes(engine: RequestEngine) -> None:
    h = process(engine, "H")
    i = process(engine, "I")
    c = process(engine, "C")
    assert i.container_uuid == h.container_uuid
    assert c.container_uuid == h.container_uuid
    assert c.container_state == ContainerState.COMPLETED


def test_duplicate_message_rejection(engine: RequestEngine) -> None:
    first = process(engine, "A")
    duplicate = process(engine, "F")
    assert first.container_state == ContainerState.COMPLETED
    assert duplicate.duplicate
    assert engine.get_container(first.container_uuid)["image_count"] == 7
    assert len(engine.list_outbound()) == 1


def test_duplicate_media_rejection(engine: RequestEngine) -> None:
    first = process(engine, "H")
    duplicate = process(engine, "H")
    assert duplicate.duplicate
    assert engine.get_container(first.container_uuid)["image_count"] == 3


def test_conflicting_lp_behaviour(engine: RequestEngine) -> None:
    process(engine, "C")
    result = process(engine, "G")
    assert result.container_state == ContainerState.NEEDS_REVIEW
    containers = engine.list_containers(include_completed=True)
    assert any(row["state"] == ContainerState.NEEDS_REVIEW for row in containers)


def test_completion_at_exactly_7_images(engine: RequestEngine) -> None:
    result = process(engine, "A")
    assert result.container_state == ContainerState.COMPLETED
    assert engine.get_container(result.container_uuid)["image_count"] == 7


def test_no_completion_below_7_images(engine: RequestEngine) -> None:
    result = process(engine, "H")
    assert not result.completed
    assert result.container_state == ContainerState.COLLECTING
    assert len(engine.list_outbound()) == 0


def test_one_outbound_row_only(engine: RequestEngine) -> None:
    process(engine, "C")
    first = process(engine, "D")
    duplicate = process(engine, "D")
    assert duplicate.duplicate
    assert len(engine.list_outbound()) == 1
    assert len(engine.list_outbound_actions()) == 2


def test_container_expiry(engine: RequestEngine) -> None:
    result = process(engine, "H")
    old = to_db_time(__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(seconds=90))
    engine.db.execute("UPDATE request_containers SET last_useful_activity_at = ? WHERE container_uuid = ?", (old, result.container_uuid))
    assert engine.update_time_states()["inactive"] == 1
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.PAUSED


def test_manual_correction(engine: RequestEngine) -> None:
    result = process(engine, "D")
    corrected = engine.correct_licence_plate(result.container_uuid, "SMP 3890 P")
    assert corrected["state"] == ContainerState.COLLECTING
    corrected = engine.correct_action(result.container_uuid, "LOCKED")
    assert corrected["state"] == ContainerState.COLLECTING
    assert "MISSING_LOCATION_REFERENCE" in corrected["missing_fields_json"]


def test_manual_merge(engine: RequestEngine) -> None:
    images = process(engine, "D")
    text = process(engine, "C", sender_id="6590000000", chat_id="other@c.us")
    merged = engine.merge_containers(images.container_uuid, text.container_uuid)
    assert merged["state"] == ContainerState.COMPLETED
    assert len(engine.list_outbound()) == 1


def test_manual_completion(engine: RequestEngine) -> None:
    result = process(engine, "A")
    engine.complete_manually(result.container_uuid)
    container = engine.get_container(result.container_uuid)
    assert container["state"] == ContainerState.COMPLETED
    assert len(engine.list_outbound()) == 1
    assert len(engine.list_outbound_actions()) == 2


def test_ordering_scenarios(engine: RequestEngine) -> None:
    for name in ["A", "B", "C", "D"]:
        process(engine, name, message_id=f"random-{name}")
    outbound = engine.list_outbound()
    assert len(outbound) >= 1
    assert len(engine.list_containers(include_completed=True)) >= 1
