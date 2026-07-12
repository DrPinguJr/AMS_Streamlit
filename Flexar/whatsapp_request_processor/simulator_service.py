"""Simulator queue and guided scenario helpers."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from .request_engine import ProcessMetrics, RequestEngine
from .test_payloads import get_payload, random_payload_sequence


GUIDED_SCENARIOS = {
    "Scenario A - Slow Rider A, Fast Rider B": ["H", "A", "C", "I"],
    "Scenario B - Fifteen Events in One Request": ["E", "C", "E", "H", "E", "I"],
    "Scenario C - Quiet Timer Reset": ["A", "D"],
    "Scenario D - Paused and Resumed": ["C", "D"],
    "Scenario E - Late Image": ["A", "D"],
    "Scenario F - New Request After Completion": ["A", "J"],
}


@dataclass
class SimulatorJob:
    payloads: list[dict[str, Any]] = field(default_factory=list)
    queued_at: float = field(default_factory=time.perf_counter)
    processed: int = 0
    cancelled: bool = False

    @property
    def remaining(self) -> int:
        return max(0, len(self.payloads) - self.processed)


def build_payload(name: str, **overrides: Any) -> dict[str, Any]:
    return get_payload(name, **overrides)


def build_guided_scenario(name: str, **overrides: Any) -> list[dict[str, Any]]:
    sequence = GUIDED_SCENARIOS[name]
    payloads: list[dict[str, Any]] = []
    for index, payload_name in enumerate(sequence):
        item_overrides = dict(overrides)
        if name == "Scenario A - Slow Rider A, Fast Rider B" and payload_name == "A":
            item_overrides["sender_id"] = "6592222222"
            item_overrides["chat_id"] = "6592222222@c.us"
            item_overrides["sender_display_name"] = "Rider B"
            item_overrides["licence_plate"] = "SNY9109P"
            item_overrides["message_id"] = f"scenario-a-fast-rider-{payload_name.lower()}-{index}"
        else:
            item_overrides["message_id"] = f"scenario-{name.lower().replace(' ', '-')}-{payload_name.lower()}-{index}"
        payload = get_payload(payload_name, **item_overrides)
        if name == "Scenario A - Slow Rider A, Fast Rider B" and payload_name in {"H", "I"}:
            payload["sender_id"] = overrides.get("sender_id", payload["sender_id"])
            payload["chat_id"] = overrides.get("chat_id", payload["chat_id"])
            payload["sender_display_name"] = overrides.get("sender_display_name", payload["sender_display_name"])
        if name == "Scenario B - Fifteen Events in One Request":
            payload["external_message_id"] = f"{payload['external_message_id']}-{index}"
            for media_index, media in enumerate(payload.get("media", []), start=1):
                media["external_media_id"] = f"scenario-b-media-{index}-{media_index}"
        if name == "Scenario F - New Request After Completion" and payload_name == "J":
            payload["licence_plate"] = "SNY9109P"
        payloads.append(payload)
    return payloads


def build_stress_payloads(
    count: int,
    seed: int,
    sender_count: int,
    chat_count: int,
    duplicate_probability: float,
    **overrides: Any,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    payloads = random_payload_sequence(count, seed=seed, **overrides)
    seen: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads):
        sender_index = rng.randrange(max(1, sender_count))
        chat_index = rng.randrange(max(1, chat_count))
        payload["sender_id"] = f"65912{sender_index:04d}"
        payload["chat_id"] = f"65912{chat_index:04d}@c.us"
        if seen and rng.random() < duplicate_probability:
            payloads[index] = seen[-1].copy()
        else:
            seen.append(payload)
    return payloads


def process_payloads(engine: RequestEngine, payloads: list[dict[str, Any]]) -> ProcessMetrics:
    metrics = ProcessMetrics()
    for payload in payloads:
        before = len(engine.list_containers(include_completed=True))
        results = engine.process_webhook_payload(payload)
        after = len(engine.list_containers(include_completed=True))
        metrics.events_processed += len(results)
        metrics.containers_created += max(0, after - before)
        for result in results:
            if result.duplicate:
                metrics.duplicates_ignored += 1
            if result.message == "merged":
                metrics.containers_merged += 1
            if result.container_state == "READY_FOR_APPROVAL":
                metrics.containers_ready += 1
            if result.container_state == "MANUAL_REVIEW":
                metrics.manual_review_count += 1
            if result.match_reason == "FILLER_IGNORED":
                metrics.filler_ignored += 1
            if result.status == "error":
                metrics.errors += 1
    time_counts = engine.update_time_states()
    metrics.inactive_count += time_counts["inactive"]
    metrics.expired_count += time_counts["expired"]
    return metrics
