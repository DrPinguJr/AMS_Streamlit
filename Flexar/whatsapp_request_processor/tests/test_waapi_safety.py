from __future__ import annotations

from Flexar.whatsapp_request_processor.config import Settings
from Flexar.whatsapp_request_processor.waapi_client import WAAPIClient


def test_master_outbound_gate_prevents_network_even_when_waapi_enabled(monkeypatch) -> None:
    settings = Settings(
        waapi_enabled=True,
        waapi_outbound_enabled=False,
        simulation_mode=False,
        waapi_instance_id="instance",
        waapi_token="secret",
        waapi_base_url="https://waapi.invalid",
    )
    monkeypatch.setattr("httpx.Client", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network attempted")))
    result = WAAPIClient(settings).send_text_message("chat", "message")
    assert result["simulated"] is True
    assert result["status"] == "SIMULATED_SENT"


def test_rider_and_ops_gates_are_disabled_by_default() -> None:
    settings = Settings(waapi_enabled=True, waapi_outbound_enabled=True, simulation_mode=False)
    client = WAAPIClient(settings)
    assert "disabled" in client.send_rider_reply("chat", "message")["message"].lower()
    assert "disabled" in client.send_ops_group_update("group", "message")["message"].lower()
