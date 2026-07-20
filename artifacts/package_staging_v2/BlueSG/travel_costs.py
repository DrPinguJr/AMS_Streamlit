"""Travel-context and confidence helpers used by the existing OneMap provider."""

from __future__ import annotations

import re
from typing import Literal

from Flexar.BlueSG.operation_context import OperationContext, normalise_empty_travel_mode


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
    return (
        normalise_location(origin),
        normalise_location(destination),
        normalise_empty_travel_mode(travel_mode),
        context.operation_day_type,
        context.operation_hour_bucket,
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

