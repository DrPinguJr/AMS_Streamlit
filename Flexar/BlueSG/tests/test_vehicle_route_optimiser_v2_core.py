from __future__ import annotations

import json
from datetime import date, time

import pandas as pd

from Flexar.BlueSG.build_optimised_vehicle_routes import TravelCost
from Flexar.BlueSG import build_optimised_vehicle_routes as backend
from Flexar.BlueSG.route_operation_time_window_settings import OperationContext
from Flexar.BlueSG.travel_cache_keys_and_route_confidence import build_travel_cache_key
from Flexar.BlueSG.v2_daily_roster_source import load_daily_v2_roster
from Flexar.BlueSG.vehicle_route_optimiser_v2 import (
    AssignmentExplanation,
    AssignmentSeverity,
    PlanMetrics,
    Rider,
    TravelMatrix,
    WorkStyle,
    build_v2_travel_matrix,
    capacity_summary,
    jobs_from_dataframe,
    parse_end_requirement,
    run_optimiser_v2,
    validate_v2_roster,
)


DAY = date(2026, 7, 31)
CONTEXT = OperationContext.for_window(DAY, time(14), time(17))


def _jobs(count: int, zone: str = "East") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Job ID": f"J{index + 1}",
                "Uploaded Row": index + 2,
                "_original_order": index,
                "Car Plate": f"SLA{index + 1:04d}A",
                "Pickup Address": f"{zone} pickup {index + 1}",
                "Pickup Lot": f"L{index + 1}",
                "Drop-off Address": f"{zone} drop {index + 1}",
                "Pickup Zone": zone,
                "Drop-off Zone": zone,
            }
            for index in range(count)
        ]
    )


def _cost(minutes: float) -> TravelCost:
    return TravelCost(0 if minutes == 0 else 1, minutes, "test cache", confidence="cached_verified")


def _matrix(jobs_df: pd.DataFrame, riders: list[Rider], *, default_empty: float = 5, loaded: float = 5, overrides=None) -> TravelMatrix:
    jobs = jobs_from_dataframe(jobs_df)
    origins = {rider.start_location for rider in riders} | {job.dropoff_address for job in jobs}
    destinations = {job.pickup_address for job in jobs} | {
        rider.end_requirement.location_text
        for rider in riders
        if rider.end_requirement is not None
    }
    overrides = overrides or {}
    empty = {}
    for origin in origins:
        for destination in destinations:
            minutes = overrides.get((origin, destination), 0 if origin == destination else default_empty)
            empty[TravelMatrix._key(origin, destination)] = _cost(minutes)
    loaded_routes = {
        TravelMatrix._key(job.pickup_address, job.dropoff_address): _cost(loaded)
        for job in jobs
    }
    return TravelMatrix(empty, loaded_routes, cache_hits=len(empty) + len(loaded_routes))


def _roster_row(**overrides):
    row = {
        "Rider Name": "Safuwan",
        "Start Location": "Woodlands",
        "Start Zone": "North",
        "Preferred": 1,
        "Maximum": 2,
        "Work Style": "Flexible",
        "End Requirement": "",
        "Active": True,
    }
    row.update(overrides)
    return row


def test_preferred_jobs_cannot_exceed_maximum_jobs() -> None:
    result = validate_v2_roster(pd.DataFrame([_roster_row(Preferred=2, Maximum=1)]), DAY)
    assert not result.is_valid
    assert result.errors == [
        "Safuwan: Preferred Jobs cannot exceed Maximum Jobs. Preferred = 2; Maximum = 1."
    ]


def test_maximum_jobs_entered_as_text_is_rejected() -> None:
    result = validate_v2_roster(pd.DataFrame([_roster_row(Maximum="2")]), DAY)
    assert not result.is_valid
    assert "not text" in result.errors[0]


def test_google_csv_keeps_numeric_cells_valid_when_another_row_contains_text(tmp_path) -> None:
    csv_path = tmp_path / "Friday.csv"
    pd.DataFrame(
        [
            _roster_row(**{"Rider Name": "Valid", "Preferred": 1, "Maximum": 2}),
            _roster_row(**{"Rider Name": "Invalid", "Preferred": 1, "Maximum": "two"}),
        ]
    ).to_csv(csv_path, index=False)
    loaded = load_daily_v2_roster("Friday", google_csv_url=str(csv_path))
    validation = validate_v2_roster(loaded.dataframe, DAY)
    assert loaded.source == "Google Sheets"
    assert not validation.is_valid
    assert validation.errors == [
        "Invalid: Maximum Jobs must be entered as a number, not text."
    ]


def test_required_end_requirement_and_alias_are_parsed() -> None:
    parsed = parse_end_requirement("Return to CCK by 4:30 PM", DAY)
    assert parsed is not None
    assert parsed.location_text == "Choa Chu Kang"
    assert (parsed.required_by.hour, parsed.required_by.minute) == (16, 30)


def test_unclear_end_requirement_is_rejected() -> None:
    result = validate_v2_roster(
        pd.DataFrame([_roster_row(**{"End Requirement": "Back north around evening"})]),
        DAY,
    )
    assert not result.is_valid
    assert "Could not understand End Requirement" in result.errors[0]


def test_capacity_precheck_detects_shortfall() -> None:
    riders = [Rider("A", "Tampines", "East", 1, 1, WorkStyle.LOCAL)]
    summary = capacity_summary(2, riders)
    assert not summary.feasible_by_job_count
    assert summary.shortfall == 1


def test_maximum_jobs_is_a_hard_constraint_and_incomplete_is_not_success() -> None:
    jobs = _jobs(2)
    riders = [Rider("A", "Tampines", "East", 1, 1, WorkStyle.LOCAL)]
    result = run_optimiser_v2(jobs, riders, operation_context=CONTEXT, travel_matrix=_matrix(jobs, riders))
    assert result.status == "INFEASIBLE"
    assert result.route_df.empty


def test_preferred_jobs_can_be_exceeded_for_completion() -> None:
    jobs = _jobs(2)
    riders = [Rider("A", "Tampines", "East", 1, 2, WorkStyle.FLEXIBLE)]
    result = run_optimiser_v2(jobs, riders, operation_context=CONTEXT, travel_matrix=_matrix(jobs, riders), beam_width=20)
    assert result.status == "COMPLETE_WITH_EXCEPTIONS"
    assert len(result.route_df) == 2
    assert int(result.summary_df.iloc[0]["Total Jobs"]) == 2


def test_all_30_jobs_complete_when_capacity_is_31() -> None:
    jobs = _jobs(30)
    riders = [
        *[Rider(f"R{index}", f"East start {index}", "East", 2, 2, WorkStyle.FLEXIBLE) for index in range(12)],
        Rider("Overflow", "East overflow", "East", 5, 7, WorkStyle.FLEXIBLE),
    ]
    assert sum(r.preferred_jobs for r in riders) == 29
    assert sum(r.maximum_jobs for r in riders) == 31
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders, default_empty=1, loaded=1),
        beam_width=12,
        time_limit_seconds=10,
    )
    assert result.status == "COMPLETE_WITH_EXCEPTIONS"
    assert len(result.route_df) == 30
    counts = result.route_df.groupby("Rider").size().to_dict()
    assert all(counts.get(rider.name, 0) <= rider.maximum_jobs for rider in riders)


def test_area_lead_receives_main_local_cluster() -> None:
    jobs = _jobs(5)
    riders = [
        Rider("Lester", "Bedok", "East", 4, 4, WorkStyle.AREA_LEAD),
        Rider("Clifford", "Tampines", "East", 1, 1, WorkStyle.LOCAL),
    ]
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders),
        beam_width=80,
    )
    assert result.route_df.groupby("Rider").size().to_dict() == {"Clifford": 1, "Lester": 4}
    assert result.route_df[result.route_df["Rider"] == "Lester"]["Area Lead Match"].all()


def test_three_disliked_assignments_beat_one_cross_zone() -> None:
    three_disliked = PlanMetrics(0, 0, 0, 0, 0, 0, 3, 0, 3, 0, 30, 90)
    one_cross_zone = PlanMetrics(0, 0, 0, 1, 0, 0, 10, 10, 0, 0, 10, 30)
    assert three_disliked.objective() < one_cross_zone.objective()


def test_preferred_workload_overage_beats_cross_zone() -> None:
    overage = PlanMetrics(0, 0, 0, 0, 0, 0, 1, 1, 0, 1, 20, 60)
    cross = PlanMetrics(0, 0, 0, 1, 0, 0, 10, 10, 0, 0, 10, 50)
    assert overage.objective() < cross.objective()


def test_last_job_before_four_is_invalid_if_return_is_after_four() -> None:
    roster = validate_v2_roster(
        pd.DataFrame([_roster_row(**{"End Requirement": "Woodlands by 4:00 PM"})]),
        DAY,
    )
    assert roster.is_valid
    rider = roster.riders[0]
    jobs = _jobs(1, "North")
    job = jobs_from_dataframe(jobs)[0]
    overrides = {
        (rider.start_location, job.pickup_address): 10,
        (job.dropoff_address, rider.end_requirement.location_text): 30,
        (rider.start_location, rider.end_requirement.location_text): 0,
    }
    matrix = _matrix(jobs, [rider], loaded=70, overrides=overrides)
    result = run_optimiser_v2(jobs, [rider], operation_context=CONTEXT, travel_matrix=matrix)
    assert result.status == "INFEASIBLE"
    assert any("Required destination arrival" in reason for reason in result.infeasible_reasons)


def test_partial_assignment_off_by_default_returns_infeasible() -> None:
    jobs = _jobs(2)
    riders = [Rider("A", "East pickup 1", "East", 1, 1, WorkStyle.FLEXIBLE)]
    matrix = _matrix(jobs, riders)
    result = run_optimiser_v2(jobs, riders, operation_context=CONTEXT, travel_matrix=matrix)
    assert result.status == "INFEASIBLE"
    assert result.route_df.empty
    assert len(result.unassigned_jobs) == 2


def test_allow_partial_assignment_places_what_fits_and_lists_the_rest() -> None:
    jobs = _jobs(2)
    riders = [Rider("A", "East pickup 1", "East", 1, 1, WorkStyle.FLEXIBLE)]
    matrix = _matrix(jobs, riders)
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=matrix,
        allow_partial_assignment=True,
    )
    assert result.status == "PARTIAL"
    assert len(result.route_df) == 1
    assert len(result.unassigned_jobs) == 1
    assert result.unassigned_jobs[0]["Job ID"] == "J2"
    assert result.infeasible_reasons


def test_allow_partial_assignment_still_completes_when_everything_fits() -> None:
    jobs = _jobs(1)
    riders = [Rider("A", "East pickup 1", "East", 1, 1, WorkStyle.FLEXIBLE)]
    matrix = _matrix(jobs, riders)
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=matrix,
        allow_partial_assignment=True,
    )
    assert result.status == "COMPLETE"
    assert not result.unassigned_jobs
    assert len(result.route_df) == 1


def test_zero_minute_empty_route_is_valid() -> None:
    jobs = _jobs(1)
    jobs.loc[0, "Pickup Address"] = "Tampines"
    riders = [Rider("A", "Tampines", "East", 1, 1, WorkStyle.LOCAL)]
    matrix = _matrix(jobs, riders)
    result = run_optimiser_v2(jobs, riders, operation_context=CONTEXT, travel_matrix=matrix)
    assert result.status == "COMPLETE"
    assert result.route_df.iloc[0]["Empty Duration Min"] == 0
    assert result.explanations[0].severity == AssignmentSeverity.PREFERRED


def test_v1_compatibility_cost_does_not_treat_zero_as_missing() -> None:
    zero = TravelCost(0, 0, "exact same location")
    assert zero.optimisation_value("duration") == 0
    assert zero.optimisation_value("distance") == 0


def test_public_transport_cache_uses_fifteen_minute_bucket() -> None:
    at_1401 = OperationContext.for_window(DAY, time(14, 1), time(17))
    at_1414 = OperationContext.for_window(DAY, time(14, 14), time(17))
    at_1415 = OperationContext.for_window(DAY, time(14, 15), time(17))
    first = build_travel_cache_key("A", "B", "public_transport", at_1401)
    same = build_travel_cache_key("A", "B", "public_transport", at_1414)
    next_bucket = build_travel_cache_key("A", "B", "public_transport", at_1415)
    assert first == same
    assert first != next_bucket


def test_local_rider_prefers_local_work_and_flexible_rider_supports_neighbour() -> None:
    jobs = pd.concat([_jobs(1, "East"), _jobs(1, "Central")], ignore_index=True)
    jobs.loc[1, ["Job ID", "Uploaded Row", "_original_order"]] = ["J2", 3, 1]
    riders = [
        Rider("Local", "East start", "East", 1, 1, WorkStyle.LOCAL),
        Rider("Flexible", "East support", "East", 1, 1, WorkStyle.FLEXIBLE),
    ]
    overrides = {
        ("East start", "East pickup 1"): 2,
        ("East start", "Central pickup 1"): 8,
        ("East support", "East pickup 1"): 3,
        ("East support", "Central pickup 1"): 8,
    }
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders, overrides=overrides),
        beam_width=40,
    )
    assignment = result.route_df.set_index("Job ID")["Rider"].to_dict() if "Job ID" in result.route_df else {
        row["V2 Job ID"]: row["Rider"] for _, row in result.route_df.iterrows()
    }
    assert assignment == {"J1": "Local", "J2": "Flexible"}


def test_area_lead_override_requires_twelve_minute_advantage() -> None:
    jobs = _jobs(1, "East")
    riders = [
        Rider("Lead", "Lead start", "East", 1, 1, WorkStyle.AREA_LEAD),
        Rider("Local", "Local start", "East", 1, 1, WorkStyle.LOCAL),
    ]
    job_pickup = jobs.iloc[0]["Pickup Address"]
    below_threshold = _matrix(
        jobs,
        riders,
        overrides={("Lead start", job_pickup): 15, ("Local start", job_pickup): 5},
    )
    first = run_optimiser_v2(
        jobs, riders, operation_context=CONTEXT, travel_matrix=below_threshold, beam_width=20
    )
    assert first.route_df.iloc[0]["Rider"] == "Lead"

    material_advantage = _matrix(
        jobs,
        riders,
        overrides={("Lead start", job_pickup): 20, ("Local start", job_pickup): 5},
    )
    second = run_optimiser_v2(
        jobs, riders, operation_context=CONTEXT, travel_matrix=material_advantage, beam_width=20
    )
    assert second.route_df.iloc[0]["Rider"] == "Local"


def test_area_lead_capacity_is_reserved_for_home_demand() -> None:
    jobs = pd.concat([_jobs(1, "East"), _jobs(1, "West")], ignore_index=True)
    jobs.loc[1, ["Job ID", "Uploaded Row", "_original_order"]] = ["J2", 3, 1]
    riders = [
        Rider("East Lead", "Bedok", "East", 1, 1, WorkStyle.AREA_LEAD),
        Rider("Support", "Jurong", "West", 1, 1, WorkStyle.FLEXIBLE),
    ]
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders),
        beam_width=30,
    )
    assignment = {row["V2 Job ID"]: row["Rider"] for _, row in result.route_df.iterrows()}
    assert assignment == {"J1": "East Lead", "J2": "Support"}


def test_solver_avoids_a_repeated_sacrifice_rider() -> None:
    jobs = _jobs(3, "West")
    riders = [
        Rider(name, f"{name} East", "East", 3, 3, WorkStyle.FLEXIBLE)
        for name in ("A", "B", "C")
    ]
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders, default_empty=30),
        beam_width=80,
    )
    assert sorted(result.route_df.groupby("Rider").size().tolist()) == [1, 1, 1]


def test_preferred_overage_is_used_before_cross_zone_support() -> None:
    jobs = _jobs(2, "East")
    riders = [
        Rider("East Local", "Tampines", "East", 1, 2, WorkStyle.LOCAL),
        Rider("West Support", "Jurong", "West", 1, 1, WorkStyle.FLEXIBLE),
    ]
    overrides = {
        ("Tampines", "East pickup 1"): 5,
        ("Tampines", "East pickup 2"): 5,
        ("East drop 1", "East pickup 2"): 5,
        ("East drop 2", "East pickup 1"): 5,
    }
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders, default_empty=50, overrides=overrides),
        beam_width=50,
    )
    assert result.route_df.groupby("Rider").size().to_dict() == {"East Local": 2}


def test_job_moving_toward_required_end_is_preferred() -> None:
    roster = validate_v2_roster(
        pd.DataFrame([_roster_row(**{"End Requirement": "Woodlands by 4:00 PM"})]), DAY
    )
    end_rider = roster.riders[0]
    support = Rider("Support", "Woodlands", "North", 1, 1, WorkStyle.FLEXIBLE)
    jobs = _jobs(2, "North")
    jobs.loc[0, "Drop-off Address"] = "Toward Woodlands"
    jobs.loc[1, "Drop-off Address"] = "Away from Woodlands"
    job_objects = jobs_from_dataframe(jobs)
    overrides = {
        ("Woodlands", "Woodlands"): 0,
        ("Toward Woodlands", "Woodlands"): 0,
        ("Away from Woodlands", "Woodlands"): 50,
    }
    matrix = _matrix(jobs, [end_rider, support], default_empty=30, loaded=5, overrides=overrides)
    result = run_optimiser_v2(
        jobs,
        [end_rider, support],
        operation_context=CONTEXT,
        travel_matrix=matrix,
        beam_width=60,
    )
    assignment = {row["V2 Job ID"]: row["Rider"] for _, row in result.route_df.iterrows()}
    assert assignment[job_objects[0].job_id] == "Safuwan"
    assert assignment[job_objects[1].job_id] == "Support"


def test_safuwan_can_return_to_woodlands_before_four() -> None:
    roster = validate_v2_roster(
        pd.DataFrame([_roster_row(**{"End Requirement": "Woodlands by 4:00 PM"})]), DAY
    )
    rider = roster.riders[0]
    jobs = _jobs(1, "North")
    job = jobs_from_dataframe(jobs)[0]
    matrix = _matrix(
        jobs,
        [rider],
        loaded=20,
        overrides={(job.dropoff_address, "Woodlands"): 15},
    )
    result = run_optimiser_v2(
        jobs, [rider], operation_context=CONTEXT, travel_matrix=matrix
    )
    assert result.status in {"COMPLETE", "COMPLETE_WITH_EXCEPTIONS"}
    assert result.explanations[0].estimated_end_arrival is not None
    assert result.explanations[0].estimated_end_arrival.hour < 16


def test_unavoidable_opposite_side_demand_is_completed_then_clustered() -> None:
    jobs = _jobs(4, "West")
    riders = [
        Rider("Punggol A", "Punggol A", "North-East", 2, 2, WorkStyle.FLEXIBLE),
        Rider("Punggol B", "Punggol B", "North-East", 2, 2, WorkStyle.FLEXIBLE),
    ]
    overrides = {}
    for drop_index in range(1, 5):
        for pickup_index in range(1, 5):
            overrides[(f"West drop {drop_index}", f"West pickup {pickup_index}")] = 5
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(
            jobs, riders, default_empty=50, loaded=5, overrides=overrides
        ),
        beam_width=80,
    )
    assert result.status == "COMPLETE_WITH_EXCEPTIONS"
    assert len(result.route_df) == 4
    for _, route in result.route_df.groupby("Rider"):
        ordered = route.sort_values("Sequence")
        assert ordered.iloc[0]["Assignment Severity"] == "LONG_DISTANCE_CROSS_ZONE"
        assert ordered.iloc[1]["Assignment Severity"] == "PREFERRED"


def test_second_provider_run_uses_persistent_route_cache(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "route-cache.csv"
    monkeypatch.setattr(backend, "ROUTE_CACHE_FILE", cache_file)
    backend.ROUTE_MEMORY_CACHE.clear()
    monkeypatch.setattr(backend, "ROUTE_DISK_CACHE_LOADED", False)
    calls = {"count": 0}

    def fake_fetch(*args, **kwargs):
        calls["count"] += 1
        return {"route_summary": {"total_distance": 1000, "total_time": 600}}

    monkeypatch.setattr(backend, "_fetch_json", fake_fetch)
    origin = backend.GeocodeResult("Origin", 1.30, 103.80, "test")
    destination = backend.GeocodeResult("Destination", 1.31, 103.81, "test")
    first = backend.get_onemap_route_cost(
        origin, destination, route_type="drive", operation_context=CONTEXT
    )
    backend.ROUTE_MEMORY_CACHE.clear()
    monkeypatch.setattr(backend, "ROUTE_DISK_CACHE_LOADED", False)
    second = backend.get_onemap_route_cost(
        origin, destination, route_type="drive", operation_context=CONTEXT
    )
    assert first.duration_min == second.duration_min == 10
    assert "cache" in second.source.casefold()
    assert calls["count"] == 1


def test_v2_progress_reports_capacity_search_and_completion() -> None:
    jobs = _jobs(2)
    riders = [Rider("A", "Tampines", "East", 2, 2, WorkStyle.FLEXIBLE)]
    events: list[dict[str, object]] = []
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders),
        progress_callback=events.append,
    )
    assert result.status == "COMPLETE"
    assert events[0]["event_type"] == "v2_capacity"
    search_events = [event for event in events if event["event_type"] == "v2_search"]
    assert [event["assigned_jobs"] for event in search_events[-2:]] == [1, 2]
    assert events[-1]["event_type"] == "v2_finished"
    assert events[-1]["assigned_jobs"] == 2


def test_v2_route_dataframe_attributes_are_json_serializable() -> None:
    jobs = _jobs(1)
    riders = [Rider("A", "Tampines", "East", 1, 1, WorkStyle.LOCAL)]
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders),
    )
    json.dumps(result.route_df.attrs)
    assert isinstance(result.route_df.attrs["v2_explanations"][0], dict)
    assert isinstance(result.explanations[0], AssignmentExplanation)


def test_v2_matrix_progress_is_throttled_and_reaches_total() -> None:
    jobs_df = _jobs(2)
    riders = [Rider("A", "Tampines", "East", 2, 2, WorkStyle.FLEXIBLE)]
    events: list[dict[str, object]] = []
    matrix = build_v2_travel_matrix(
        jobs_from_dataframe(jobs_df),
        riders,
        CONTEXT,
        use_onemap=False,
        progress_callback=events.append,
    )
    matrix_events = [event for event in events if event["event_type"] == "v2_matrix"]
    assert matrix_events
    assert matrix_events[-1]["matrix_completed"] == matrix_events[-1]["matrix_total"]
    assert len(matrix_events) <= 52
    assert matrix.empty and matrix.loaded
