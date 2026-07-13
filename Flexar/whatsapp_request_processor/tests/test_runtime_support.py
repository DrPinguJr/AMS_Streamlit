from __future__ import annotations

import json
from pathlib import Path

from Flexar.whatsapp_request_processor.runtime_support import (
    atomic_write_json,
    command_matches,
    load_json_file,
    python_candidates,
    redact_sensitive,
    repository_root_from_launcher,
    safe_runtime_status,
    select_https_tunnel,
)


def test_repository_path_resolution() -> None:
    root = repository_root_from_launcher(Path("START AMS WHATSAPP SYSTEM.bat"))
    assert (root / "Flexar" / "whatsapp_request_processor" / "api.py").is_file()
    assert root.name == "Lance"


def test_python_candidate_order(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active"))
    candidates = python_candidates(tmp_path / "repo", str(tmp_path / "custom.exe"))
    assert candidates == [
        tmp_path / "active" / "Scripts" / "python.exe",
        tmp_path / "repo" / ".venv" / "Scripts" / "python.exe",
        tmp_path / "repo" / "venv" / "Scripts" / "python.exe",
        tmp_path / "custom.exe",
    ]


def test_selects_https_tunnel_for_fastapi_only() -> None:
    payload = {
        "tunnels": [
            {"public_url": "http://wrong.example", "config": {"addr": "http://localhost:8000"}},
            {"public_url": "https://streamlit.example", "config": {"addr": "http://localhost:8501"}},
            {"public_url": "https://api.example", "config": {"addr": "http://127.0.0.1:8000"}},
        ]
    }
    assert select_https_tunnel(payload, 8000)["public_url"] == "https://api.example"
    assert select_https_tunnel({"tunnels": []}, 8000) is None


def test_atomic_status_write_and_safe_read(tmp_path) -> None:
    target = tmp_path / "runtime" / "system_status.json"
    payload = safe_runtime_status(session_started_at="now", log_directory="logs")
    atomic_write_json(target, payload)
    assert load_json_file(target) == payload
    assert not list(target.parent.glob("*.tmp"))
    target.write_text("{partial", encoding="utf-8")
    assert load_json_file(target) == {}


def test_runtime_status_has_hard_disabled_waapi() -> None:
    status = safe_runtime_status(session_started_at="now", log_directory="logs")
    assert status["simulation_mode"] is True
    assert status["live_sending"] is False
    assert status["waapi"] == {
        "status": "disabled",
        "outbound_enabled": False,
        "rider_reply_enabled": False,
        "ops_update_enabled": False,
    }
    assert "token" not in json.dumps(status).lower()


def test_secret_and_phone_redaction() -> None:
    value = redact_sensitive("Authorization: Bearer abc123 token=secret-value rider=6591234567")
    assert "abc123" not in value
    assert "secret-value" not in value
    assert "6591234567" not in value
    assert "65****67" in value


def test_command_matching_requires_every_marker() -> None:
    command = "python -m uvicorn Flexar.whatsapp_request_processor.api:app --port 8000"
    assert command_matches(command, ["uvicorn", "Flexar.whatsapp_request_processor.api:app"])
    assert not command_matches(command, ["streamlit", "app.py"])
    assert not command_matches("", ["uvicorn"])
