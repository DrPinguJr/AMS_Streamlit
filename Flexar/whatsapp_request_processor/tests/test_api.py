from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from Flexar.whatsapp_request_processor.test_payloads import get_payload


def test_api_health_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    api = importlib.import_module("Flexar.whatsapp_request_processor.api")
    api = importlib.reload(api)
    client = TestClient(api.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
