"""Extract explicit location and parking details from rider text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class LocationInfo:
    location_reference: str | None = None
    address_text: str | None = None
    pickup_dropoff_context: str | None = None
    deck: str | None = None
    level: str | None = None
    basement_level: str | None = None
    lot: str | None = None
    lot_range: str | None = None
    bay: str | None = None
    zone: str | None = None
    parking_type: str | None = None
    raw_location_text: str | None = None

    @property
    def has_location(self) -> bool:
        return bool(self.location_reference or self.raw_location_text)

    @property
    def has_parking_position(self) -> bool:
        return bool(
            self.lot
            or self.lot_range
            or self.bay
            or self.zone
            or self.deck
            or self.level
            or self.basement_level
            or self.parking_type in {"WHITE_LOTS", "SURFACE", "LOADING_BAY", "STATION"}
        )

    @property
    def is_mscp(self) -> bool:
        haystack = " ".join(
            part
            for part in [self.raw_location_text, self.location_reference, self.parking_type]
            if part
        ).lower()
        return bool(re.search(r"\b(mscp|multi[- ]?storey|multi[- ]?story)\b", haystack))

    @property
    def display_location(self) -> str:
        parts = [
            self.location_reference,
            self.deck,
            self.level,
            self.basement_level,
            self.lot,
            self.lot_range,
            self.bay,
            self.zone,
            "White Lots" if self.parking_type == "WHITE_LOTS" else None,
            "Loading Bay" if self.parking_type == "LOADING_BAY" else None,
            "Surface Parking" if self.parking_type == "SURFACE" else None,
        ]
        return ", ".join(part for part in parts if part)


DECK_RE = re.compile(r"\bdeck\s+([A-Z]?\d+[A-Z]?|\d+[A-Z]?)\b", re.IGNORECASE)
LEVEL_RE = re.compile(r"\b(?:level|lvl)\s+([A-Z]?\d+[A-Z]?|\d+[A-Z]?)\b", re.IGNORECASE)
BASEMENT_RE = re.compile(r"\b(?:basement\s*)?B\s*([0-9]+[A-Z]?)\b", re.IGNORECASE)
LOT_RE = re.compile(r"\b(?:lot|lots)\s*#?\s*([A-Z]?\d+[A-Z]?)\b", re.IGNORECASE)
LOT_RANGE_RE = re.compile(r"\b(?:lot|lots)\s*#?\s*([A-Z]?\d+[A-Z]?)\s*(?:-|to)\s*([A-Z]?\d+[A-Z]?)\b", re.IGNORECASE)
BAY_RE = re.compile(r"\b(?:bay|loading bay)\s+([A-Z0-9-]+)\b", re.IGNORECASE)
ZONE_RE = re.compile(r"\bzone\s+([A-Z0-9-]+)\b", re.IGNORECASE)
STATION_RE = re.compile(r"\bstation\s+([A-Z0-9-]+)\b", re.IGNORECASE)


def _first(pattern: re.Pattern[str], text: str, label: str | None = None) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).upper()
    return f"{label} {value}" if label else value


def extract_location_info(text: str) -> LocationInfo:
    """Extract only explicit location information from a text bubble."""

    if not text:
        return LocationInfo()
    info = LocationInfo(raw_location_text=None)
    lower = text.lower()
    relevant = bool(
        re.search(
            r"\b(deck|level|lvl|basement|lot|bay|zone|station|parking|parked|pickup|drop[- ]?off|mscp|multi[- ]?storey|white lots|surface|loading bay|charger)\b",
            text,
            re.IGNORECASE,
        )
    )
    if not relevant:
        return info

    info.raw_location_text = text.strip()
    if re.search(r"\bpickup\b", lower):
        info.pickup_dropoff_context = "Pickup"
    elif re.search(r"\bdrop[- ]?off\b", lower):
        info.pickup_dropoff_context = "Drop-off"

    if re.search(r"\bmscp|multi[- ]?storey|multi[- ]?story\b", lower):
        info.parking_type = "MSCP"
        info.location_reference = "MSCP"
    elif re.search(r"\bwhite lots?\b", lower):
        info.parking_type = "WHITE_LOTS"
        info.location_reference = "White Lots"
    elif re.search(r"\bsurface\b", lower):
        info.parking_type = "SURFACE"
        info.location_reference = "Surface Parking"
    elif re.search(r"\bloading bay\b", lower):
        info.parking_type = "LOADING_BAY"
        info.location_reference = "Loading Bay"

    station = _first(STATION_RE, text, "Station")
    if station:
        info.parking_type = "STATION"
        info.location_reference = station

    info.deck = _first(DECK_RE, text, "Deck")
    info.level = _first(LEVEL_RE, text, "Level")
    basement = _first(BASEMENT_RE, text)
    if basement:
        info.basement_level = f"B{basement}"
        info.level = info.level or f"Level B{basement}"
    range_match = LOT_RANGE_RE.search(text)
    if range_match:
        info.lot_range = f"Lot {range_match.group(1).upper()}-{range_match.group(2).upper()}"
    info.lot = _first(LOT_RE, text, "Lot")
    info.bay = _first(BAY_RE, text, "Bay")
    info.zone = _first(ZONE_RE, text, "Zone")

    if not info.location_reference:
        if info.deck or info.level or info.basement_level:
            info.location_reference = info.pickup_dropoff_context or "Parking location"
        elif info.lot or info.bay or info.zone:
            info.location_reference = "Parking position"

    return info


def merge_location_info(existing: LocationInfo, incoming: LocationInfo) -> LocationInfo:
    """Merge location details without inventing missing values."""

    return LocationInfo(
        location_reference=existing.location_reference or incoming.location_reference,
        address_text=existing.address_text or incoming.address_text,
        pickup_dropoff_context=existing.pickup_dropoff_context or incoming.pickup_dropoff_context,
        deck=existing.deck or incoming.deck,
        level=existing.level or incoming.level,
        basement_level=existing.basement_level or incoming.basement_level,
        lot=existing.lot or incoming.lot,
        lot_range=existing.lot_range or incoming.lot_range,
        bay=existing.bay or incoming.bay,
        zone=existing.zone or incoming.zone,
        parking_type=existing.parking_type or incoming.parking_type,
        raw_location_text=existing.raw_location_text or incoming.raw_location_text,
    )

