from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from Flexar.whatsapp_request_processor.config import Settings
from Flexar.whatsapp_request_processor.database import Database, to_db_time
from Flexar.whatsapp_request_processor.models import ContainerState, OutboundActionType
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload


def settings_for(path: Path) -> Settings:
    return Settings(
        database_path=path,
        min_required_images=4,
        request_quiet_seconds=8,
        request_inactive_seconds=60,
        late_media_grace_seconds=120,
        simulation_mode=True,
        automation_mode=True,
        auto_dispatch_complete_requests=True,
        auto_dispatch_in_simulation=True,
    )


def unique_payload(name: str, suffix: str, **overrides: Any) -> dict[str, Any]:
    payload = get_payload(name, message_id=f"{suffix}-{name.lower()}", **overrides)
    payload["payload_batch_id"] = f"{suffix}-{name.lower()}-batch"
    payload["correlation_id"] = overrides.get("correlation_id") or f"{suffix}-{name.lower()}-corr"
    for index, media in enumerate(payload.get("media", []), start=1):
        media["external_media_id"] = f"{suffix}-{name.lower()}-media-{index}"
    return payload


def image_payload(suffix: str, count: int, **overrides: Any) -> dict[str, Any]:
    payload = unique_payload("D", suffix, **overrides)
    payload["media"] = payload["media"][:count]
    payload["event_type"] = "image"
    payload["text"] = ""
    return payload


def force_due(engine: RequestEngine, container_uuid: str) -> None:
    engine.db.execute("UPDATE request_containers SET dispatch_after = ? WHERE container_uuid = ?", ("2000-01-01T00:00:00+00:00", container_uuid))
    engine.process_due_dispatches()


def test_fifteen_events_from_one_rider_create_one_request(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "fifteen.db"))
    for index in range(5):
        engine.process_payload(unique_payload("E", f"filler-{index}"))
    first = engine.process_payload(unique_payload("C", "fifteen-text"))
    for index in range(14):
        engine.process_payload(image_payload(f"fifteen-image-{index}", 1))

    snapshot = engine.db.get_dashboard_snapshot()
    assert len(snapshot["active_requests"]) == 1
    assert snapshot["metrics"]["events"] == 20
    assert snapshot["active_requests"][0]["container_uuid"] == first.container_uuid


def test_four_unique_images_satisfy_minimum_and_duplicate_images_do_not_count(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "four-images.db"))
    result = engine.process_payload(unique_payload("C", "four-text"))
    engine.process_payload(image_payload("four-images", 4))
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.READY_WAITING_QUIET

    duplicate = image_payload("four-images-dup", 4)
    duplicate["media"] = [
        {**media, "external_media_id": f"four-images-d-media-{index}"}
        for index, media in enumerate(duplicate["media"], start=1)
    ]
    engine.process_payload(duplicate)
    assert engine.get_container(result.container_uuid)["image_count"] == 4


def test_quiet_timer_begins_after_completion_and_resets_for_useful_activity(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "quiet-reset.db"))
    result = engine.process_payload(unique_payload("C", "quiet-text"))
    assert engine.get_container(result.container_uuid)["dispatch_after"] is None
    engine.process_payload(image_payload("quiet-images", 4))
    first_dispatch_after = engine.get_container(result.container_uuid)["dispatch_after"]
    assert first_dispatch_after

    engine.process_payload(image_payload("quiet-extra", 1))
    second_dispatch_after = engine.get_container(result.container_uuid)["dispatch_after"]
    assert second_dispatch_after >= first_dispatch_after

    engine.process_payload(unique_payload("E", "quiet-filler"))
    assert engine.get_container(result.container_uuid)["dispatch_after"] == second_dispatch_after


def test_due_dispatch_and_atomic_claim_work_without_streamlit(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "due.db"))
    result = engine.process_payload(unique_payload("A", "due"))
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.READY_WAITING_QUIET
    engine.db.execute("UPDATE request_containers SET dispatch_after = ? WHERE container_uuid = ?", ("2000-01-01T00:00:00+00:00", result.container_uuid))
    assert engine.claim_due_request(result.container_uuid, "2000-01-01T00:00:01+00:00")
    assert not engine.claim_due_request(result.container_uuid, "2000-01-01T00:00:02+00:00")
    engine.outbound.approve_and_queue(result.container_uuid, actor="test")
    engine.outbound.simulate_request(result.container_uuid)
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.COMPLETED


def test_later_created_request_can_complete_first(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "fast-rider.db"))
    rider_a = {"sender_id": "6591111111", "chat_id": "6591111111@c.us", "sender_display_name": "Rider A", "licence_plate": "SMP3890P"}
    rider_b = {"sender_id": "6592222222", "chat_id": "6592222222@c.us", "sender_display_name": "Rider B", "licence_plate": "SNY9109P"}
    a = engine.process_payload(image_payload("slow-a-1", 2, **rider_a))
    b = engine.process_payload(unique_payload("A", "fast-b", **rider_b))
    force_due(engine, b.container_uuid)
    assert engine.get_container(b.container_uuid)["state"] == ContainerState.COMPLETED
    assert engine.get_container(a.container_uuid)["state"] == ContainerState.COLLECTING
    engine.process_payload(unique_payload("C", "slow-a-text", **rider_a))
    engine.process_payload(image_payload("slow-a-2", 2, **rider_a))
    force_due(engine, a.container_uuid)
    assert engine.get_container(a.container_uuid)["state"] == ContainerState.COMPLETED


def test_paused_request_is_excluded_then_reactivated(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "pause.db"))
    result = engine.process_payload(unique_payload("C", "pause-text"))
    old = to_db_time(__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - timedelta(seconds=90))
    engine.db.execute("UPDATE request_containers SET last_useful_activity_at = ? WHERE container_uuid = ?", (old, result.container_uuid))
    engine.update_time_states()
    snapshot = engine.db.get_dashboard_snapshot()
    assert len(snapshot["active_requests"]) == 0
    assert len(snapshot["paused_requests"]) == 1

    resumed = engine.process_payload(image_payload("pause-resume", 4))
    assert resumed.container_uuid == result.container_uuid
    snapshot = engine.db.get_dashboard_snapshot()
    assert len(snapshot["active_requests"]) == 1
    assert len(snapshot["paused_requests"]) == 0


def test_completed_rows_leave_active_and_remain_visible_today(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "completed-today.db"))
    result = engine.process_payload(unique_payload("A", "complete-visible"))
    force_due(engine, result.container_uuid)
    snapshot = engine.db.get_dashboard_snapshot()
    assert len(snapshot["active_requests"]) == 0
    assert snapshot["completed_today"][0]["container_uuid"] == result.container_uuid


def test_late_media_creates_ops_supplemental_without_second_rider_reply(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "late.db"))
    result = engine.process_payload(unique_payload("A", "late-base"))
    force_due(engine, result.container_uuid)
    engine.process_payload(image_payload("late-extra", 2))

    actions = engine.list_outbound_actions()
    rider_replies = [row for row in actions if row["action_type"] == OutboundActionType.RIDER_REPLY.value]
    supplemental = [row for row in actions if row["action_type"] == OutboundActionType.OPS_GROUP_SUPPLEMENTAL_MEDIA.value]
    assert len(rider_replies) == 1
    assert len(supplemental) == 1


def test_ambiguous_late_media_is_not_auto_attached(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "ambiguous-late.db"))
    first = engine.process_payload(unique_payload("A", "late-one", licence_plate="SMP3890P"))
    force_due(engine, first.container_uuid)
    second = engine.process_payload(unique_payload("A", "late-two", licence_plate="SNY9109P"))
    force_due(engine, second.container_uuid)
    late = engine.process_payload(image_payload("late-ambiguous", 1))

    assert late.container_uuid not in {first.container_uuid, second.container_uuid}
    actions = [row for row in engine.list_outbound_actions() if row["action_type"] == OutboundActionType.OPS_GROUP_SUPPLEMENTAL_MEDIA.value]
    assert actions == []


def test_live_snapshot_waiting_for_is_exact(tmp_path) -> None:
    engine = RequestEngine(settings=settings_for(tmp_path / "waiting-for.db"))
    engine.process_payload(image_payload("waiting-images", 3))
    row = engine.db.get_dashboard_snapshot()["active_requests"][0]
    assert "Licence plate" in row["waiting_for"]
    assert "1 more image" in row["waiting_for"]
    assert "Lock/unlock instruction" in row["waiting_for"]
