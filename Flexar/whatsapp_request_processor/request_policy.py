"""Request validation policy helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .models import ActionIntent


@dataclass(frozen=True)
class RequestPolicy:
    """Hard and soft requirements for a request profile."""

    require_location_reference: bool
    require_parking_position: bool
    require_deck_for_mscp: bool
    require_lot_number: bool


def policy_for_action(action: str | None, settings: Settings) -> RequestPolicy:
    """Return the active policy for LOCKED or UNLOCKED requests."""

    if action == ActionIntent.UNLOCKED.value:
        return RequestPolicy(
            require_location_reference=settings.require_location_reference,
            require_parking_position=False,
            require_deck_for_mscp=False,
            require_lot_number=False,
        )
    return RequestPolicy(
        require_location_reference=settings.require_location_reference,
        require_parking_position=settings.require_parking_position,
        require_deck_for_mscp=settings.require_deck_for_mscp,
        require_lot_number=settings.require_lot_number,
    )

