from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from Flexar.whatsapp_request_processor.test_payloads import get_payload


def test_api_health_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    api = importlib.import_module("Flexar.whatsapp_request_processor.api")
    api = importlib.reload(api)
    with TestClient(api.app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "ams-whatsapp-request-processor"
        assert body["worker"]["status"] == "online"
        assert body["database"]["ok"] is True
        assert body["application_started_at"]
        assert body["simulation_mode"] is True
        assert body["waapi"]["status"] == "disabled"
        assert body["waapi"]["outbound_enabled"] is False
        assert body["pending_request_count"] == 0
        assert body["failed_action_count"] == 0


def test_api_test_payload_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api_payload.db"))
    api = importlib.import_module("Flexar.whatsapp_request_processor.api")
    api = importlib.reload(api)
    client = TestClient(api.app)
    response = client.post("/test/payload", json=get_payload("C"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed"
    assert body["container_state"] == "COLLECTING"


def test_health_tracks_last_simulator_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api_last_event.db"))
    api = importlib.import_module("Flexar.whatsapp_request_processor.api")
    api = importlib.reload(api)
    with TestClient(api.app) as client:
        assert client.post("/test/payload", json=get_payload("C")).status_code == 200
        health = client.get("/health").json()
    assert health["last_inbound_simulator_event_at"]
