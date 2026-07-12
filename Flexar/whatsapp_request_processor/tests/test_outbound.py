from __future__ import annotations

from Flexar.whatsapp_request_processor.models import ContainerState, OutboundStatus
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def test_complete_request_auto_creates_one_request_and_two_actions(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("A"))
    assert result.container_state == ContainerState.COMPLETED
    assert len(engine.list_outbound()) == 1
    assert len(engine.list_outbound_actions()) == 2
    engine.process_payload(get_payload("F"))
    assert len(engine.list_outbound()) == 1
    assert len(engine.list_outbound_actions()) == 2


def test_simulated_send_happens_automatically(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("A"))
    container = engine.get_container(result.container_uuid)
    assert container["state"] == ContainerState.COMPLETED
    assert {row["status"] for row in engine.list_outbound_actions()} == {OutboundStatus.SIMULATED_SENT.value}
