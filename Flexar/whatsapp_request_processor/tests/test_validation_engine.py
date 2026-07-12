from __future__ import annotations

from Flexar.whatsapp_request_processor.models import ContainerState, OutboundStatus
from Flexar.whatsapp_request_processor.request_engine import RequestEngine
from Flexar.whatsapp_request_processor.test_payloads import get_payload
from Flexar.whatsapp_request_processor.validation_engine import ValidationEngine, ValidationStatus


def report_for(engine: RequestEngine, container_uuid: str):
    return ValidationEngine(engine.db, engine.settings).validate_container(container_uuid)


def test_report_identifies_lp_missing(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("B"))
    report = report_for(engine, result.container_uuid)
    assert "MISSING_LICENCE_PLATE" in report.missing_required_fields
    assert "vehicle plate" in report.next_required_input.lower()


def test_report_identifies_exact_missing_images(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("C"))
    report = report_for(engine, result.container_uuid)
    image_item = next(item for item in report.items if item.key == "MISSING_IMAGES")
    assert image_item.status == ValidationStatus.MISSING
    assert "7 more" in image_item.explanation


def test_report_identifies_action_missing(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("N"))
    report = report_for(engine, result.container_uuid)
    assert "MISSING_ACTION" in report.missing_required_fields
    assert len(engine.list_outbound_actions()) == 0


def test_report_identifies_location_missing(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("D"))
    engine.correct_licence_plate(result.container_uuid, "SMP3890P")
    engine.correct_action(result.container_uuid, "LOCKED")
    report = report_for(engine, result.container_uuid)
    assert "MISSING_LOCATION_REFERENCE" in report.missing_required_fields


def test_mscp_requires_deck(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("K"))
    report = report_for(engine, result.container_uuid)
    assert "MISSING_MSCP_DECK" in report.missing_required_fields
    assert len(engine.list_outbound_actions()) == 0


def test_surface_parking_deck_not_applicable(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("L"))
    report = report_for(engine, result.container_uuid)
    deck_item = next(item for item in report.items if item.key == "MISSING_MSCP_DECK")
    assert deck_item.status == ValidationStatus.NOT_APPLICABLE
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.COMPLETED


def test_white_lots_satisfy_position_and_lot_optional(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("M"))
    report = report_for(engine, result.container_uuid)
    lot_item = next(item for item in report.items if item.key == "NO_LOT_NUMBER")
    position_item = next(item for item in report.items if item.key == "MISSING_PARKING_POSITION")
    assert lot_item.status == ValidationStatus.OPTIONAL
    assert position_item.status == ValidationStatus.PASSED
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.COMPLETED


def test_complete_request_auto_dispatches_and_simulates(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("A"))
    container = engine.get_container(result.container_uuid)
    assert container["state"] == ContainerState.COMPLETED
    assert container["auto_dispatched_at"]
    assert len(engine.list_outbound()) == 1
    assert len(engine.list_outbound_actions()) == 2
    assert {row["status"] for row in engine.list_outbound_actions()} == {OutboundStatus.SIMULATED_SENT.value}


def test_conflict_blocks_outbound(engine: RequestEngine) -> None:
    result = engine.process_payload(get_payload("G"))
    report = report_for(engine, result.container_uuid)
    assert report.blockers
    assert engine.get_container(result.container_uuid)["state"] == ContainerState.NEEDS_REVIEW
    assert len(engine.list_outbound_actions()) == 0
