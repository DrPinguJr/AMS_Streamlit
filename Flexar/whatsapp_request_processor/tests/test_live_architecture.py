from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from Flexar.whatsapp_request_processor.config import Settings
from Flexar.whatsapp_request_processor.database import Database
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def _settings(db_path: Path) -> Settings:
    return Settings(
        database_path=db_path,
        min_required_images=4,
        container_inactive_seconds=60,
        container_expiry_seconds=1800,
        require_operator_approval=False,
        automation_mode=True,
        auto_dispatch_complete_requests=True,
        auto_dispatch_in_simulation=True,
        simulation_mode=True,
    )


def _unique_payload(name: str, suffix: str, **overrides: Any) -> dict[str, Any]:
    payload = get_payload(name, message_id=f"{suffix}-{name.lower()}-message", **overrides)
    payload["payload_batch_id"] = f"{suffix}-{name.lower()}-batch"
    payload["correlation_id"] = overrides.get("correlation_id") or f"{suffix}-{name.lower()}-correlation"
    for index, media in enumerate(payload.get("media", []), start=1):
        media["external_media_id"] = f"{suffix}-{name.lower()}-media-{index:03d}"
    return payload


def _api_client(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> tuple[TestClient, Any]:
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setenv("SIMULATION_MODE", "true")
    monkeypatch.setenv("AUTOMATION_MODE", "true")
    monkeypatch.setenv("AUTO_DISPATCH_COMPLETE_REQUESTS", "true")
    monkeypatch.setenv("AUTO_DISPATCH_IN_SIMULATION", "true")
    monkeypatch.setenv("WAAPI_WEBHOOK_SECRET", "")
    api = importlib.import_module("Flexar.whatsapp_request_processor.api")
    api = importlib.reload(api)
    return TestClient(api.app), api


def _page_text(at: Any) -> str:
    values: list[str] = []
    for collection_name in ["title", "header", "subheader", "markdown", "caption", "write", "success", "info", "warning"]:
        collection = getattr(at, collection_name, [])
        values.extend(str(item.value) for item in collection)
    return "\n".join(values)


def test_fastapi_processes_payload_without_streamlit_session(tmp_path, monkeypatch) -> None:
    client, api = _api_client(monkeypatch, tmp_path / "api_no_streamlit.db")

    response = client.post("/webhooks/waapi", json=_unique_payload("A", "no-streamlit"))

    assert response.status_code == 200
    snapshot = api.db.get_dashboard_snapshot()
    assert snapshot["metrics"]["events"] == 1
    assert snapshot["metrics"]["active_requests"] == 1
    assert snapshot["active_requests"][0]["state"] == "READY_WAITING_QUIET"


def test_streamlit_reads_already_processed_state_from_sqlite(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "streamlit_reads.db"
    client, _ = _api_client(monkeypatch, db_path)
    assert client.post("/webhooks/waapi", json=_unique_payload("A", "streamlit-read")).status_code == 200

    st.cache_resource.clear()
    at = AppTest.from_file("Flexar/whatsapp_request_processor/app.py", default_timeout=15)
    at.run()

    assert not at.exception
    assert "SMP3890P" in _page_text(at)
    assert "Active Requests" in _page_text(at)


def test_repeated_fragment_reruns_do_not_duplicate_events_or_outbound_actions(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "reruns.db"
    client, api = _api_client(monkeypatch, db_path)
    assert client.post("/webhooks/waapi", json=_unique_payload("A", "rerun")).status_code == 200
    before = api.db.get_dashboard_snapshot()["metrics"]

    st.cache_resource.clear()
    at = AppTest.from_file("Flexar/whatsapp_request_processor/app.py", default_timeout=15)
    at.run()
    at.run()

    assert not at.exception
    after = api.db.get_dashboard_snapshot()["metrics"]
    assert after["events"] == before["events"]
    assert after["outbound_actions"] == before["outbound_actions"]


def test_database_write_during_dashboard_read_does_not_crash(tmp_path) -> None:
    settings = _settings(tmp_path / "concurrent_read_write.db")
    db = Database(settings)
    reader_errors: list[BaseException] = []

    def read_snapshots() -> None:
        try:
            for _ in range(40):
                db.get_dashboard_snapshot()
        except BaseException as exc:
            reader_errors.append(exc)

    def write_payload() -> None:
        RequestEngine(db=Database(settings), settings=settings).process_webhook_payload(_unique_payload("A", "during-read"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        read_future = executor.submit(read_snapshots)
        write_future = executor.submit(write_payload)
        read_future.result()
        write_future.result()

    assert reader_errors == []
    assert db.get_dashboard_snapshot()["metrics"]["events"] == 1


def test_two_simultaneous_senders_are_processed_independently(tmp_path) -> None:
    settings = _settings(tmp_path / "simultaneous_senders.db")

    payloads = [
        _unique_payload("A", "sender-one", sender_id="6591111111", chat_id="6591111111@c.us", licence_plate="SMP3890P"),
        _unique_payload("A", "sender-two", sender_id="6592222222", chat_id="6592222222@c.us", licence_plate="SNY9109P"),
    ]

    def process(payload: dict[str, Any]) -> None:
        RequestEngine(db=Database(settings), settings=settings).process_webhook_payload(payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(process, payloads))

    snapshot = Database(settings).get_dashboard_snapshot()
    assert snapshot["metrics"]["events"] == 2
    assert snapshot["metrics"]["active_requests"] == 2


def test_dashboard_snapshot_revision_reflects_database_changes_on_next_refresh(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "next_refresh.db"
    client, api = _api_client(monkeypatch, db_path)
    db = api.db
    before = db.get_dashboard_snapshot()

    st.cache_resource.clear()
    at = AppTest.from_file("Flexar/whatsapp_request_processor/app.py", default_timeout=15)
    at.run()
    assert not at.exception

    assert client.post("/webhooks/waapi", json=_unique_payload("C", "next-refresh")).status_code == 200
    after = db.get_dashboard_snapshot()
    at.run()

    assert after["revision"] > before["revision"]
    assert "SMP3890P" in _page_text(at)


def test_pausing_visual_refresh_does_not_pause_backend_processing(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    db_path = tmp_path / "paused_refresh.db"
    client, api = _api_client(monkeypatch, db_path)
    st.cache_resource.clear()
    at = AppTest.from_file("Flexar/whatsapp_request_processor/app.py", default_timeout=15)
    at.run()
    at.checkbox[0].check().run()

    before = api.db.get_dashboard_snapshot()
    response = client.post("/webhooks/waapi", json=_unique_payload("A", "paused-refresh"))
    after = api.db.get_dashboard_snapshot()

    assert response.status_code == 200
    assert after["latest_event_id"] > before["latest_event_id"]
    assert after["metrics"]["active_requests"] == 1
    assert "Live visual refresh is paused" in _page_text(at)
