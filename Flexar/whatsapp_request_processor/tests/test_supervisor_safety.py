from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


SUPERVISOR_PATH = Path("Flexar/whatsapp_request_processor/scripts/ams_supervisor.py")


@pytest.fixture()
def supervisor_module():
    spec = importlib.util.spec_from_file_location("ams_supervisor_test", SUPERVISOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_safe_environment_forces_simulation_and_disables_all_waapi(supervisor_module, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WAAPI_ENABLED", "true")
    monkeypatch.setenv("SIMULATION_MODE", "false")
    instance = object.__new__(supervisor_module.Supervisor)
    env = instance.safe_environment()
    assert env["SIMULATION_MODE"] == "true"
    assert env["WAAPI_ENABLED"] == "false"
    assert env["WAAPI_OUTBOUND_ENABLED"] == "false"
    assert env["WAAPI_RIDER_REPLY_ENABLED"] == "false"
    assert env["WAAPI_OPS_UPDATE_ENABLED"] == "false"


def test_pid_liveness_probe_does_not_disrupt_current_process(supervisor_module) -> None:
    assert supervisor_module.pid_alive(os.getpid()) is True
    assert supervisor_module.pid_alive(0) is False


def test_missing_ngrok_returns_none_without_installing(supervisor_module, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AMS_NGROK_PATH", raising=False)
    monkeypatch.delenv("NGROK_PATH", raising=False)
    monkeypatch.setattr(supervisor_module.shutil, "which", lambda _: None)
    monkeypatch.setattr(supervisor_module, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    assert supervisor_module.find_ngrok() is None


def test_stale_supervisor_is_not_reused(supervisor_module, monkeypatch) -> None:
    monkeypatch.setattr(supervisor_module, "load_json_file", lambda _: {"supervisor": {"pid": 999, "markers": ["ams_supervisor.py"]}})
    monkeypatch.setattr(supervisor_module, "pid_alive", lambda _: False)
    assert supervisor_module.existing_supervisor() is None


def test_duplicate_supervisor_is_detected_only_with_expected_command(supervisor_module, monkeypatch) -> None:
    runtime = {"supervisor": {"pid": 123, "markers": ["ams_supervisor.py"]}}
    monkeypatch.setattr(supervisor_module, "load_json_file", lambda _: runtime)
    monkeypatch.setattr(supervisor_module, "pid_alive", lambda _: True)
    monkeypatch.setattr(supervisor_module, "process_command_line", lambda _: "python scripts/ams_supervisor.py")
    assert supervisor_module.existing_supervisor() == runtime
    monkeypatch.setattr(supervisor_module, "process_command_line", lambda _: "unrelated.exe")
    assert supervisor_module.existing_supervisor() is None


def test_unrelated_recorded_pid_is_never_stopped(supervisor_module, monkeypatch) -> None:
    monkeypatch.setattr(supervisor_module, "pid_alive", lambda _: True)
    monkeypatch.setattr(supervisor_module, "process_command_line", lambda _: "unrelated.exe")
    called = []
    monkeypatch.setattr(supervisor_module.os, "kill", lambda *args: called.append(args))
    message = supervisor_module.terminate_recorded_process({"pid": 55, "markers": ["uvicorn", "api:app"]}, "FastAPI")
    assert "was not stopped" in message
    assert called == []


def test_port_conflict_is_not_treated_as_ams_api(supervisor_module, monkeypatch) -> None:
    instance = object.__new__(supervisor_module.Supervisor)
    instance.log = type("Log", (), {"write": lambda self, *args, **kwargs: None})()
    monkeypatch.setattr(supervisor_module, "port_owner_pid", lambda _: 77)
    monkeypatch.setattr(supervisor_module, "process_command_line", lambda _: "unrelated-server.exe")
    monkeypatch.setattr(supervisor_module, "http_json", lambda _: {"status": "ok"})
    assert instance.start_api({}) is False


def test_existing_unsafe_ams_api_is_not_reused(supervisor_module, monkeypatch) -> None:
    instance = object.__new__(supervisor_module.Supervisor)
    instance.log = type("Log", (), {"write": lambda self, *args, **kwargs: None})()
    monkeypatch.setattr(supervisor_module, "port_owner_pid", lambda _: 88)
    monkeypatch.setattr(supervisor_module, "process_command_line", lambda _: "python -m uvicorn Flexar.whatsapp_request_processor.api:app")
    monkeypatch.setattr(
        supervisor_module,
        "http_json",
        lambda _: {
            "service": "ams-whatsapp-request-processor",
            "status": "ok",
            "simulation_mode": False,
            "waapi": {"status": "configured", "outbound_enabled": True},
        },
    )
    assert instance.start_api({}) is False
