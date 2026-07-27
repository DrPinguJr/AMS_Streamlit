"""Finite, JSON-safe output sanitisation for UI, Excel, and run artifacts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path
from typing import Any


def finite_or(value: Any, default: float = 0.0) -> Any:
    if isinstance(value, float) and not isfinite(value):
        return default
    return value


def sanitize_for_output(value: Any, *, non_finite_default: float = 0.0) -> Any:
    """Recursively replace NaN/infinity and convert common non-JSON types."""

    if is_dataclass(value):
        return sanitize_for_output(asdict(value), non_finite_default=non_finite_default)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else non_finite_default
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): sanitize_for_output(item, non_finite_default=non_finite_default)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_output(item, non_finite_default=non_finite_default) for item in value]
    try:
        scalar = value.item()
    except (AttributeError, ValueError):
        return str(value)
    return sanitize_for_output(scalar, non_finite_default=non_finite_default)

