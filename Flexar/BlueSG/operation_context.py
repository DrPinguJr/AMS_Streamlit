"""Timezone-aware operating-window configuration for overnight relocation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


EMPTY_TRAVEL_MODES = {
    "Public transport": "public_transport",
    "Recovery vehicle": "recovery_vehicle",
    "Private hire/taxi": "private_hire_taxi",
    "Walking": "walking",
    "Mixed/manual": "mixed_manual",
}


@dataclass(frozen=True)
class OperationContext:
    timezone: str = "Asia/Singapore"
    operation_start: datetime | None = None
    operation_end: datetime | None = None
    empty_travel_mode: str = "public_transport"
    pickup_handling_min: float = 3.0
    dropoff_handling_min: float = 3.0
    unlock_wait_min: float = 0.0
    default_operational_buffer_pct: float = 0.20

    def __post_init__(self) -> None:
        zone = ZoneInfo(self.timezone)
        start = self.operation_start
        end = self.operation_end
        if start is None:
            today = datetime.now(zone).date()
            start = datetime.combine(today, time(14, 0), tzinfo=zone)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=zone)
        else:
            start = start.astimezone(zone)
        if end is None:
            end = datetime.combine(start.date(), time(17, 0), tzinfo=zone)
        elif end.tzinfo is None:
            end = end.replace(tzinfo=zone)
        else:
            end = end.astimezone(zone)
        if end <= start:
            end += timedelta(days=1)
        if self.pickup_handling_min < 0 or self.dropoff_handling_min < 0 or self.unlock_wait_min < 0:
            raise ValueError("Handling and wait times cannot be negative.")
        if self.default_operational_buffer_pct < 0:
            raise ValueError("Operational buffer cannot be negative.")
        object.__setattr__(self, "operation_start", start)
        object.__setattr__(self, "operation_end", end)
        object.__setattr__(self, "empty_travel_mode", normalise_empty_travel_mode(self.empty_travel_mode))

    @classmethod
    def for_window(
        cls,
        operation_date: date,
        start_time: time,
        end_time: time,
        **kwargs: object,
    ) -> "OperationContext":
        """Build a full-datetime window, automatically rolling the end over midnight."""

        timezone_name = str(kwargs.get("timezone", "Asia/Singapore"))
        zone = ZoneInfo(timezone_name)
        start = datetime.combine(operation_date, start_time, tzinfo=zone)
        end_date = operation_date if end_time > start_time else operation_date + timedelta(days=1)
        end = datetime.combine(end_date, end_time, tzinfo=zone)
        return cls(operation_start=start, operation_end=end, **kwargs)

    @property
    def window_duration_min(self) -> float:
        return (self.operation_end - self.operation_start).total_seconds() / 60.0

    @property
    def operation_day_type(self) -> str:
        return "weekend" if self.operation_start.weekday() >= 5 else "weekday"

    @property
    def operation_hour_bucket(self) -> str:
        hour = self.operation_start.hour
        return f"{hour // 3 * 3:02d}-{(hour // 3 * 3 + 3) % 24:02d}"

    def at_minutes(self, minutes: float) -> datetime:
        return self.operation_start + timedelta(minutes=float(minutes))

    def to_settings(self) -> dict[str, object]:
        return {
            "timezone": self.timezone,
            "operation_start": self.operation_start.isoformat(),
            "operation_end": self.operation_end.isoformat(),
            "empty_travel_mode": self.empty_travel_mode,
            "pickup_handling_min": self.pickup_handling_min,
            "dropoff_handling_min": self.dropoff_handling_min,
            "unlock_wait_min": self.unlock_wait_min,
            "default_operational_buffer_pct": self.default_operational_buffer_pct,
        }


def normalise_empty_travel_mode(value: str) -> str:
    text = str(value or "public_transport").strip()
    if text in EMPTY_TRAVEL_MODES:
        return EMPTY_TRAVEL_MODES[text]
    folded = text.casefold().replace("/", "_").replace(" ", "_").replace("-", "_")
    aliases = {
        "pt": "public_transport",
        "transit": "public_transport",
        "taxi": "private_hire_taxi",
        "private_hire": "private_hire_taxi",
        "mixed": "mixed_manual",
        "manual": "mixed_manual",
    }
    return aliases.get(folded, folded)
