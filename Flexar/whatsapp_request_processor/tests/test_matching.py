from __future__ import annotations

from Flexar.whatsapp_request_processor.models import ContainerState
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def test_different_lp_creates_new_container(engine: RequestEngine) -> None:
    first = engine.process_payload(get_payload("C", licence_plate="SMP3890P"))
    second = engine.process_payload(get_payload("J", licence_plate="SNY9109P", message_id="second-lp"))
    assert first.container_uuid != second.container_uuid
    assert len(engine.list_containers(include_completed=True)) == 2


def test_completed_container_is_not_reopened(engine: RequestEngine) -> None:
    first = engine.process_payload(get_payload("A"))
    engine.complete_manually(first.container_uuid)
    second = engine.process_payload(get_payload("C", message_id="new-after-completed"))
    assert second.container_uuid != first.container_uuid


def test_quoted_message_match(engine: RequestEngine) -> None:
    first = engine.process_payload(get_payload("C"))
    image_payload = get_payload("D", message_id="reply-images")
    image_payload["quoted_message_id"] = "sim-c-001"
    result = engine.process_payload(image_payload)
    assert result.container_uuid == first.container_uuid
    assert result.container_state == ContainerState.COMPLETED
