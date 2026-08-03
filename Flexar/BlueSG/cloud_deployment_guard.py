"""Deployment guards for the BlueSG Streamlit application."""

from __future__ import annotations

import os
from collections.abc import Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FORCE_CLOUD_ENVIRONMENT_VARIABLE = "BLUESG_FORCE_CLOUD_ENTRYPOINT"


def should_use_bluesg_cloud_entrypoint(
    *,
    platform_name: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the safe BlueSG-only router must be used.

    The repository's root app contains Windows-only tools and must never be
    exposed by a Linux deployment. The environment override exists only to
    exercise the Cloud route on Windows during automated checks; it cannot
    disable the guard on Linux.
    """

    resolved_platform = os.name if platform_name is None else platform_name
    if resolved_platform != "nt":
        return True

    resolved_environment = os.environ if environment is None else environment
    forced = resolved_environment.get(_FORCE_CLOUD_ENVIRONMENT_VARIABLE, "")
    return forced.strip().casefold() in _TRUE_VALUES
