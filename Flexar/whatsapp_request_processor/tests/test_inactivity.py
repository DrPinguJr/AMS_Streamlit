from __future__ import annotations

from datetime import timedelta

from Flexar.whatsapp_request_processor.database import to_db_time
from Flexar.whatsapp_request_processor.models import ContainerState
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def test_inactive_then_reactivated(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("C"))
    old = to_db_time(__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(seconds=90))
    engine.db.execute("UPDATE request_containers SET last_useful_activity_at = ?, last_activity_at = ? WHERE container_uuid = ?", (old, old, result.container_uuid))
    engine.update_time_states()
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.PAUSED
    second = engine.process_payload(get_payload("D"))
    assert second.container_uuid == result.container_uuid
    assert second.container_state == ContainerState.COMPLETED


def test_completed_container_not_sender_fallback_merged(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("A"))
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.COMPLETED
    second = engine.process_payload(get_payload("C", message_id="new-lp-after-complete", licence_plate="SNY9109P"))
    assert second.container_uuid != result.container_uuid
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.COMPLETED
