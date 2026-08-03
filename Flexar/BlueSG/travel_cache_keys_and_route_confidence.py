"""Travel-context and confidence helpers used by the existing OneMap provider."""

from __future__ import annotations

import re
from typing import Literal

from Flexar.BlueSG.route_operation_time_window_settings import OperationContext, normalise_empty_travel_mode


PROVIDER_VERSION = "onemap-v1"
TravelConfidence = Literal["verified", "cached_verified", "fallback", "manual"]


def normalise_location(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def build_travel_cache_key(
    origin: object,
    destination: object,
    travel_mode: str,
    context: OperationContext,
    provider_version: str = PROVIDER_VERSION,
) -> tuple[str, str, str, str, str, str]:
    mode = normalise_empty_travel_mode(travel_mode)
    folded_mode = str(travel_mode or "").casefold()
    is_public_transport = any(
        marker in folded_mode for marker in ("public_transport", "transit", "pt:")
    )
    time_bucket = context.operation_quarter_hour_bucket if is_public_transport else "timeless"
    service_day = context.operation_day_type if is_public_transport else "all-days"
    return (
        normalise_location(origin),
        normalise_location(destination),
        mode,
        service_day,
        time_bucket,
        provider_version,
    )


def confidence_from_source(source: object) -> TravelConfidence:
    text = str(source or "").casefold()
    if "manual" in text:
        return "manual"
    if "fallback" in text or "estimate" in text:
        return "fallback"
    if "cache" in text:
        return "cached_verified"
    return "verified"


def fallback_warning(origin: str, destination: str, duration_min: float, source: str) -> str:
    return (
        f"LOW-CONFIDENCE ROUTE: Verify travel from {origin} to {destination} before dispatch. "
        f"Estimated duration: {duration_min:.1f} min. Source: {source}."
    )
