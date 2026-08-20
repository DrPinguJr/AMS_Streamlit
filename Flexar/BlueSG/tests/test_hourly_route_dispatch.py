from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from Flexar.BlueSG.build_optimised_vehicle_routes import (
    TravelCost,
    stable_job_id_from_job,
    stable_job_id_from_route_row,
)
from Flexar.BlueSG.hourly_route_dispatch import (
    active_riders_for_dispatch,
    append_hourly_jobs,
    apply_manual_dispatch_edits,
    archive_completed_prefix,
    business_day_for,
    live_shift_timeline,
    open_jobs_for_dispatch,
    operation_context_for_riders,
    residual_riders,
    run_hourly_dispatch,
    solve_with_standby_options,
    standby_riders_for_dispatch,
)
from Flexar.BlueSG.job_import_staging import commit_staged_jobs
from Flexar.BlueSG.route_operation_time_window_settings import OperationContext
from Flexar.BlueSG.vehicle_route_optimiser_v2 import (
    Rider,
    TravelMatrix,
    WorkStyle,
    jobs_from_dataframe,
    run_optimiser_v2,
    validate_v2_roster,
)


DAY = date(2026, 8, 5)
ZONE = ZoneInfo("Asia/Singapore")
CONTEXT = OperationContext.for_window(DAY, time(14), time(16))


def _job(job_id: str = "J1", order: int = 0) -> dict[str, object]:
    return {
        "Job ID": job_id,
        "Car Plate": f"SPE{1001 + order}A",
        "Pickup Address": f"Tampines {order}",
        "Pickup Lot": "A1",
        "Drop-off Address": f"Bedok {order}",
        "Drop-off Lot": "B1",
        "_original_order": order,
        "Uploaded Row": order + 2,
    }


def _matrix(jobs: pd.DataFrame, riders: list[Rider], empty_min: float = 5) -> TravelMatrix:
    parsed = jobs_from_dataframe(jobs)
    origins = {rider.start_location for rider in riders} | {
        job.dropoff_address for job in parsed
    }
    empty = {
        TravelMatrix._key(origin, job.pickup_address): TravelCost(
            1, empty_min, "test cache"
        )
        for origin in origins
        for job in parsed
    }
    loaded = {
        TravelMatrix._key(job.pickup_address, job.dropoff_address): TravelCost(
            1, 5, "test cache"
        )
        for job in parsed
    }
    return TravelMatrix(empty, loaded)


def _roster(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "Rider Name": "Rider A",
        "Start Location": "Tampines",
        "Start Zone": "East",
        "Preferred": 2,
        "Maximum": 3,
        "Work Style": "Flexible",
        "End Requirement": "",
        "Active": True,
        "Shift Start": "1:00 PM",
        "Shift End": "4:00 PM",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_shift_window_populates_rider_availability() -> None:
    result = validate_v2_roster(_roster(), DAY)
    assert result.is_valid
    assert result.riders[0].available_from == datetime(2026, 8, 5, 13, tzinfo=ZONE)
    assert result.riders[0].available_until == datetime(2026, 8, 5, 16, tzinfo=ZONE)


def test_active_status_alias_controls_roster_activation() -> None:
    source = _roster().drop(columns="Active")
    source["Active Status"] = "Inactive"
    result = validate_v2_roster(source, DAY)
    assert not result.is_valid
    assert result.errors == ["At least one rider must be active."]


def test_shift_end_buffer_rejects_job_finishing_inside_last_ten_minutes() -> None:
    jobs = pd.DataFrame([_job()])
    rider = Rider(
        "Rider A",
        "Tampines",
        "East",
        1,
        1,
        WorkStyle.FLEXIBLE,
        available_until=datetime(2026, 8, 5, 15, tzinfo=ZONE),
    )
    result = run_optimiser_v2(
        jobs,
        [rider],
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, [rider], empty_min=40),
    )
    assert result.status == "INFEASIBLE"
    assert any("shift-end buffer" in reason for reason in result.infeasible_reasons)


def test_wait_objective_assigns_next_job_to_longest_idle_rider() -> None:
    jobs = pd.DataFrame([_job()])
    riders = [
        Rider(
            "Long idle",
            "East A",
            "East",
            1,
            1,
            WorkStyle.FLEXIBLE,
            last_completion_at=CONTEXT.operation_start - timedelta(minutes=60),
        ),
        Rider(
            "Short idle",
            "East B",
            "East",
            1,
            1,
            WorkStyle.FLEXIBLE,
            last_completion_at=CONTEXT.operation_start - timedelta(minutes=5),
        ),
    ]
    result = run_optimiser_v2(
        jobs,
        riders,
        operation_context=CONTEXT,
        travel_matrix=_matrix(jobs, riders),
        beam_width=20,
    )
    assert result.route_df.iloc[0]["Rider"] == "Long idle"
    assert len(result.objective) == 13


def test_commit_and_append_preserves_existing_stable_identity() -> None:
    existing = commit_staged_jobs(pd.DataFrame([_job("J1", 0)]))
    existing["Uploaded Row"] = existing["_original_order"] + 2
    before = stable_job_id_from_job(existing.iloc[0].to_dict())
    released = pd.DataFrame([_job("J2", 0)])
    result = append_hourly_jobs(
        existing,
        released,
        released_at=datetime(2026, 8, 5, 15, tzinfo=ZONE),
    )
    assert result.appended_job_ids == ("J2",)
    assert stable_job_id_from_job(result.dataframe.iloc[0].to_dict()) == before
    assert result.dataframe["Uploaded Row"].tolist() == [2, 3]


def test_completed_archive_only_accepts_a_route_prefix() -> None:
    routes = pd.DataFrame(
        [
            {**_job("J1", 0), "Rider": "A", "Sequence": 1},
            {**_job("J2", 1), "Rider": "A", "Sequence": 2},
        ]
    )
    second_id = stable_job_id_from_route_row(routes.iloc[1])
    with pytest.raises(ValueError, match="route order"):
        archive_completed_prefix(routes, pd.DataFrame(), {second_id})


def test_live_timeline_distinguishes_pending_and_active_shifts() -> None:
    roster = pd.concat(
        [
            _roster(**{"Rider Name": "Early"}),
            _roster(
                **{
                    "Rider Name": "Late",
                    "Shift Start": "4:00 PM",
                    "Shift End": "6:00 PM",
                }
            ),
        ],
        ignore_index=True,
    )
    timeline = live_shift_timeline(
        roster, datetime(2026, 8, 5, 15, tzinfo=ZONE)
    ).set_index("Rider")
    assert timeline.loc["Early", "Status"] == "Active"
    assert timeline.loc["Late", "Status"] == "Pending shift start"


def test_hourly_run_uses_incremental_recalculation_for_open_routes() -> None:
    jobs = pd.DataFrame([_job()])
    result = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=_roster(**{"Shift End": "6:00 PM"}),
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )
    assert result.solver_result.status == "COMPLETE"
    assert result.recalculation.affected_riders == ["Rider A"]
    assert result.route_df[["Rider", "Car Plate"]].to_dict("records") == [
        {"Rider": "Rider A", "Car Plate": "SPE1001A"}
    ]


def test_residual_riders_handles_no_shift_window_and_no_history() -> None:
    # Regression: a full-day rider with blank Shift Start/End and no archived
    # completions yet (the first solve of the day) used to crash inside
    # `max(dispatch_at, *[], *[])`, which degenerates to `max(dispatch_at)` -
    # a single non-iterable positional argument.
    rider = Rider("Rider A", "Tampines", "East", 1, 2, WorkStyle.FLEXIBLE)
    dispatch_at = datetime(2026, 8, 5, 14, tzinfo=ZONE)

    residual = residual_riders([rider], pd.DataFrame(), dispatch_at)

    assert len(residual) == 1
    assert residual[0].available_from == dispatch_at


def test_hourly_dispatch_succeeds_for_a_rider_with_no_shift_window() -> None:
    jobs = pd.DataFrame([_job()])
    roster = _roster(**{"Shift Start": "", "Shift End": ""})

    result = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=roster,
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )

    assert result.solver_result.status == "COMPLETE"


def test_hourly_dispatch_accepts_the_raw_session_state_default_frames() -> None:
    # Regression: `st.session_state.setdefault("hourly_open_routes", pd.DataFrame())`
    # is a bare, columnless DataFrame - still `isinstance(..., pd.DataFrame)`,
    # so it used to be trusted as-is instead of falling back to the
    # ROUTE_COLUMNS-shaped empty frame, crashing inside
    # `incremental_recalculate` on `confirmed_routes["Rider"]` the first time
    # anyone clicked Optimise in a fresh session.
    jobs = pd.DataFrame([_job()])

    result = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=_roster(**{"Shift End": "6:00 PM"}),
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        confirmed_open_routes=pd.DataFrame(),
        archived_routes=pd.DataFrame(),
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )

    assert result.solver_result.status == "COMPLETE"


def test_guarantee_minimum_coverage_spreads_jobs_when_capacity_is_short() -> None:
    # Regression: the mandatory hourly solve's guarantee_minimum_coverage
    # default used to still hit the pre-search capacity gate (which only
    # checked allow_partial_assignment) and abort with INFEASIBLE the moment
    # jobs outnumbered total rider capacity - exactly the "6 drivers, 7
    # jobs" case this feature exists for. Every rider should get one job and
    # the surplus job should come back unassigned, not an outright failure.
    jobs = pd.DataFrame([_job(f"J{i + 1}", i) for i in range(7)])
    roster = pd.concat(
        [_roster(**{"Rider Name": f"Rider {i}", "Preferred": 1, "Maximum": 1}) for i in range(6)],
        ignore_index=True,
    )

    result = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=roster,
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        confirmed_open_routes=pd.DataFrame(),
        archived_routes=pd.DataFrame(),
        use_onemap=False,
        beam_width=20,
        time_limit_seconds=10,
    )

    assert result.solver_result.status == "PARTIAL"
    assert result.route_df["Rider"].nunique() == 6
    assert len(result.route_df) == 6
    assert len(result.solver_result.unassigned_jobs) == 1


def test_standby_riders_excludes_active_and_requires_a_shift_window() -> None:
    roster = pd.concat(
        [
            _roster(**{"Rider Name": "Active One"}),
            _roster(**{"Rider Name": "Standby With Window", "Active": False}),
            _roster(
                **{
                    "Rider Name": "Standby No Window",
                    "Active": False,
                    "Shift Start": "",
                    "Shift End": "",
                }
            ),
        ],
        ignore_index=True,
    )
    standby = standby_riders_for_dispatch(roster, datetime(2026, 8, 5, 14, tzinfo=ZONE))
    assert [rider.name for rider in standby] == ["Standby With Window"]


def test_open_jobs_for_dispatch_excludes_archived_jobs() -> None:
    committed = commit_staged_jobs(pd.DataFrame([_job("J1", 0), _job("J2", 1)]))
    archived = pd.DataFrame([{**_job("J1", 0), "Rider": "A", "Sequence": 1}])
    open_jobs = open_jobs_for_dispatch(committed, archived)
    assert open_jobs["Job ID"].tolist() == ["J2"]


def test_operation_context_for_riders_falls_back_to_three_hours() -> None:
    dispatch_at = datetime(2026, 8, 5, 14, tzinfo=ZONE)
    context = operation_context_for_riders([], dispatch_at)
    assert context.operation_end == dispatch_at + timedelta(hours=3)


def test_solve_with_standby_options_has_no_recommendation_without_standby_riders() -> None:
    jobs = pd.DataFrame([_job("J1", 0), _job("J2", 1)])
    active = [Rider("Rider A", "Tampines 0", "East", 1, 1, WorkStyle.FLEXIBLE)]
    options = solve_with_standby_options(
        open_jobs=jobs,
        active_riders=active,
        standby_riders=[],
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        operation_context=CONTEXT,
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )
    assert options.partial_result.status == "PARTIAL"
    assert len(options.unassigned_jobs) == 1
    assert options.standby_recommendation is None


def test_solve_with_standby_options_asks_the_advisor_when_leftovers_exist() -> None:
    jobs = pd.DataFrame([_job("J1", 0), _job("J2", 1)])
    active = [Rider("Rider A", "Tampines 0", "East", 1, 1, WorkStyle.FLEXIBLE)]
    standby = [
        Rider(
            "Standby B",
            "Bedok 1",
            "East",
            1,
            1,
            WorkStyle.FLEXIBLE,
            available_from=datetime(2026, 8, 5, 13, tzinfo=ZONE),
            available_until=datetime(2026, 8, 5, 16, tzinfo=ZONE),
        )
    ]
    options = solve_with_standby_options(
        open_jobs=jobs,
        active_riders=active,
        standby_riders=standby,
        dispatch_at=datetime(2026, 8, 5, 14, tzinfo=ZONE),
        operation_context=CONTEXT,
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
        gemini_api_key=None,
    )
    assert len(options.unassigned_jobs) == 1
    assert options.standby_recommendation is not None
    assert options.standby_recommendation.activate_driver is False
    assert "not configured" in options.standby_recommendation.business_reasoning


def test_business_day_for_rolls_over_at_eleven_am() -> None:
    assert business_day_for(datetime(2026, 8, 19, 10, 59)) == date(2026, 8, 18)
    assert business_day_for(datetime(2026, 8, 19, 11, 0)) == date(2026, 8, 19)
    assert business_day_for(datetime(2026, 8, 19, 23, 59)) == date(2026, 8, 19)
    assert business_day_for(datetime(2026, 8, 19, 0, 0)) == date(2026, 8, 18)


def test_apply_manual_dispatch_edits_moves_a_job_to_a_different_rider() -> None:
    jobs = pd.DataFrame([_job()])
    dispatch_at = datetime(2026, 8, 5, 14, tzinfo=ZONE)
    roster = pd.concat(
        [
            _roster(**{"Rider Name": "Rider A", "Shift End": "6:00 PM"}),
            _roster(**{"Rider Name": "Rider B", "Shift End": "6:00 PM"}),
        ],
        ignore_index=True,
    )

    solved = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=roster,
        dispatch_at=dispatch_at,
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )
    job_id = stable_job_id_from_route_row(solved.route_df.iloc[0])
    residual = residual_riders(
        active_riders_for_dispatch(roster, dispatch_at), pd.DataFrame(), dispatch_at
    )
    open_jobs = open_jobs_for_dispatch(jobs, pd.DataFrame())

    # Whichever rider the solver picked, the operator drags the job onto
    # Rider B in the review popup before saving.
    edited = apply_manual_dispatch_edits(
        draft_assignment={"Rider A": [], "Rider B": [job_id]},
        residual=residual,
        open_jobs=open_jobs,
        archived_routes=pd.DataFrame(),
        operation_context=CONTEXT,
        solver_result=solved.solver_result,
        use_onemap=False,
        matching_preview_routes=solved.route_df,
    )

    assert edited.route_df["Rider"].tolist() == ["Rider B"]
    assert edited.solver_result is solved.solver_result


def test_apply_manual_dispatch_edits_rejects_a_duplicated_job_on_the_board() -> None:
    jobs = pd.DataFrame([_job()])
    dispatch_at = datetime(2026, 8, 5, 14, tzinfo=ZONE)
    roster = _roster(**{"Shift End": "6:00 PM"})

    solved = run_hourly_dispatch(
        committed_jobs=jobs,
        roster_df=roster,
        dispatch_at=dispatch_at,
        use_onemap=False,
        beam_width=10,
        time_limit_seconds=5,
    )
    job_id = stable_job_id_from_route_row(solved.route_df.iloc[0])
    residual = residual_riders(
        active_riders_for_dispatch(roster, dispatch_at), pd.DataFrame(), dispatch_at
    )
    open_jobs = open_jobs_for_dispatch(jobs, pd.DataFrame())

    with pytest.raises(ValueError):
        apply_manual_dispatch_edits(
            draft_assignment={"Rider A": [job_id, job_id]},
            residual=residual,
            open_jobs=open_jobs,
            archived_routes=pd.DataFrame(),
            operation_context=CONTEXT,
            solver_result=solved.solver_result,
            use_onemap=False,
        )
