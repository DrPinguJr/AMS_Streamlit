from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from Flexar.BlueSG.gemini_standby_advisor import (
    build_standby_context,
    recommend_standby_activation,
)

ZONE = ZoneInfo("Asia/Singapore")

_JOB = {"Job ID": "J999", "Pickup Address": "Woodlands Ave 2", "Drop-off Address": "Marsiling"}
_RIDER = {"name": "Kin Soon", "home_zone": "North", "shift_window": "13:00-16:00", "idle_minutes": 120}


def _context(**overrides) -> dict:
    base = {"leftover_jobs": [_JOB], "standby_riders": [_RIDER], "travel_times_to_pickup_minutes": {}}
    base.update(overrides)
    return base


def test_build_standby_context_shapes_the_payload() -> None:
    context = build_standby_context(
        dispatch_at=datetime(2026, 8, 11, 14, tzinfo=ZONE),
        leftover_jobs=[_JOB],
        standby_riders=[_RIDER],
        travel_minutes={"Kin Soon": {"J999": 12.5}},
    )
    assert context["current_time"] == "14:00"
    assert context["leftover_jobs"] == [
        {
            "job_id": "J999",
            "pickup_zone": "Woodlands Ave 2",
            "pickup_address": "Woodlands Ave 2",
            "dropoff_zone": "Marsiling",
        }
    ]
    assert context["standby_riders"] == [_RIDER]
    assert context["travel_times_to_pickup_minutes"] == {"Kin Soon": {"J999": 12.5}}


def test_no_leftover_jobs_skips_the_model_entirely() -> None:
    result = recommend_standby_activation(_context(leftover_jobs=[]), api_key="fake-key")
    assert result.activate_driver is False
    assert "No leftover jobs" in result.business_reasoning


def test_no_standby_riders_skips_the_model_entirely() -> None:
    result = recommend_standby_activation(_context(standby_riders=[]), api_key="fake-key")
    assert result.activate_driver is False
    assert "No standby riders" in result.business_reasoning


def test_missing_api_key_degrades_without_raising() -> None:
    result = recommend_standby_activation(_context(), api_key=None)
    assert result.activate_driver is False
    assert "not configured" in result.business_reasoning


def test_missing_dependency_degrades_without_raising(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "google", None)
    monkeypatch.setitem(sys.modules, "google.genai", None)
    result = recommend_standby_activation(_context(), api_key="fake-key")
    assert result.activate_driver is False
    assert "google-genai" in result.business_reasoning


def test_successful_response_is_parsed_into_the_result(monkeypatch) -> None:
    import sys
    import types as pytypes

    payload = {
        "activate_driver": True,
        "recommended_driver_name": "Kin Soon",
        "recommended_job_id": "J999",
        "business_reasoning": "Closest idle standby rider with buffer to spare.",
    }

    class _FakeResponse:
        text = json.dumps(payload)

    class _FakeModels:
        def generate_content(self, *, model, contents, config):  # noqa: ANN001
            assert model
            assert "J999" in contents
            assert config.response_mime_type == "application/json"
            return _FakeResponse()

    class _FakeClient:
        def __init__(self, *, api_key):  # noqa: ANN001
            assert api_key == "fake-key"
            self.models = _FakeModels()

    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.Client = _FakeClient

    fake_types = pytypes.ModuleType("google.genai.types")

    class _FakeConfig:
        def __init__(self, *, system_instruction, response_mime_type):  # noqa: ANN001
            self.system_instruction = system_instruction
            self.response_mime_type = response_mime_type

    fake_types.GenerateContentConfig = _FakeConfig

    fake_google = pytypes.ModuleType("google")
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    result = recommend_standby_activation(_context(), api_key="fake-key")

    assert result.activate_driver is True
    assert result.recommended_driver_name == "Kin Soon"
    assert result.recommended_job_id == "J999"
    assert "Closest idle" in result.business_reasoning


def test_provider_failure_degrades_without_raising(monkeypatch) -> None:
    import sys
    import types as pytypes

    class _FakeModels:
        def generate_content(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("network unreachable")

    class _FakeClient:
        def __init__(self, *, api_key):  # noqa: ANN001
            self.models = _FakeModels()

    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.Client = _FakeClient
    fake_types = pytypes.ModuleType("google.genai.types")
    fake_types.GenerateContentConfig = lambda **kwargs: None
    fake_google = pytypes.ModuleType("google")
    fake_google.genai = fake_genai

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    result = recommend_standby_activation(_context(), api_key="fake-key")

    assert result.activate_driver is False
    assert "Gemini request failed" in result.business_reasoning
