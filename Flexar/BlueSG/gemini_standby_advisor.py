"""Gemini-backed decision support for activating a standby half-day rider.

Kept deliberately thin and pure: this module never touches Streamlit or
``st.secrets`` directly, so it can be unit tested without a live API key or a
Streamlit session. The calling page is responsible for reading the API key
out of ``st.secrets``/environment (the same pattern already used for the
OneMap token and the roster Google-Sheet URL) and passing it in here.

Every failure mode - missing key, missing dependency, malformed response,
network error - degrades to a "do not activate" recommendation with the
reason explained in `business_reasoning`, rather than raising. A flaky or
unavailable model must never block the operator's dispatch flow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from Flexar.BlueSG.build_optimised_vehicle_routes import clean_text

# Update this if the pinned google-generativeai release retires the model.
GEMINI_MODEL_NAME = "gemini-2.5-flash"

_SYSTEM_INSTRUCTION = (
    "You are an expert Singapore logistics dispatcher. Decide whether to activate a "
    "standby half-day driver to cover one of the leftover relocation jobs. Only "
    "recommend activation when the chosen rider's shift window leaves at least a "
    "10-minute buffer before their shift end after the job's estimated travel and "
    "handling time. Among riders who qualify, prefer whoever has been idle longest "
    "(fairness). Respond ONLY with JSON matching this shape: "
    '{"activate_driver": bool, "recommended_driver_name": string|null, '
    '"recommended_job_id": string|null, "business_reasoning": string}.'
)


@dataclass(frozen=True)
class StandbyAdvisorResult:
    activate_driver: bool
    recommended_driver_name: str | None
    recommended_job_id: str | None
    business_reasoning: str


def build_standby_context(
    *,
    dispatch_at: datetime,
    leftover_jobs: list[dict[str, Any]],
    standby_riders: list[dict[str, Any]],
    travel_minutes: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Assemble the JSON-serialisable payload the model reasons over.

    `standby_riders` entries are plain dicts (name/home_zone/shift_window/
    idle_minutes) rather than `Rider` objects, so this stays independent of
    the solver's dataclasses and easy to hand-build in a test.
    """

    return {
        "current_time": dispatch_at.strftime("%H:%M"),
        "leftover_jobs": [
            {
                "job_id": clean_text(job.get("Job ID")),
                "pickup_zone": clean_text(job.get("Pickup Zone") or job.get("Pickup Address")),
                "pickup_address": clean_text(job.get("Pickup Address")),
                "dropoff_zone": clean_text(job.get("Drop-off Zone") or job.get("Drop-off Address")),
            }
            for job in leftover_jobs
        ],
        "standby_riders": standby_riders,
        "travel_times_to_pickup_minutes": travel_minutes,
    }


def recommend_standby_activation(
    context: dict[str, Any],
    *,
    api_key: str | None,
    model_name: str = GEMINI_MODEL_NAME,
) -> StandbyAdvisorResult:
    """Ask Gemini whether to activate a standby driver for the leftover jobs."""

    if not context.get("leftover_jobs"):
        return StandbyAdvisorResult(False, None, None, "No leftover jobs to cover.")
    if not context.get("standby_riders"):
        return StandbyAdvisorResult(False, None, None, "No standby riders are available.")
    if not api_key:
        return StandbyAdvisorResult(False, None, None, "Gemini API key is not configured.")
    try:
        # `google-generativeai` (the package older examples use) is fully
        # end-of-life as of this writing - Google's SDK docs point everyone
        # to `google-genai` instead, so that is what this module targets.
        from google import genai
        from google.genai import types
    except ImportError:
        return StandbyAdvisorResult(
            False, None, None, "google-genai is not installed in this environment."
        )
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=f"Analyze this payload and respond with JSON only: {json.dumps(context)}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
            ),
        )
        payload = json.loads(response.text)
    except Exception as exc:  # noqa: BLE001 - any provider/network failure degrades gracefully
        return StandbyAdvisorResult(False, None, None, f"Gemini request failed: {exc}")
    return StandbyAdvisorResult(
        activate_driver=bool(payload.get("activate_driver", False)),
        recommended_driver_name=clean_text(payload.get("recommended_driver_name")) or None,
        recommended_job_id=clean_text(payload.get("recommended_job_id")) or None,
        business_reasoning=clean_text(payload.get("business_reasoning")) or "No reasoning provided.",
    )
