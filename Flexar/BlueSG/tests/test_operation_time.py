from datetime import date, time

import pytest

from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.run_metrics import build_rider_metrics
from Flexar.BlueSG.vehicle_route_optimizer import RiderState, optimise_vehicle_routes


def test_overnight_window_crosses_midnight() -> None:
    context = OperationContext.for_window(date(2026, 7, 17), time(23), time(3))
    assert context.operation_end.date() == date(2026, 7, 18)
    assert context.window_duration_min == 240
    assert context.at_minutes(180).isoformat().startswith("2026-07-18T02:00")


def test_default_window_is_two_pm_to_five_pm() -> None:
    context = OperationContext()
    assert context.operation_start.hour == 14
    assert context.operation_end.hour == 17
    assert context.window_duration_min == 180


def test_total_duty_includes_positioning_and_handling(regression_jobs, overnight_context) -> None:
    rider = RiderState("R", "Woodlands", "North")
    route_df, _, _ = optimise_vehicle_routes(
        regression_jobs.iloc[:1], [rider], use_onemap=False, operation_context=overnight_context
    )
    metrics = build_rider_metrics(route_df, [rider], overnight_context)[0]
    assert metrics.total_duty_time_min == pytest.approx(
        metrics.first_positioning_min
        + metrics.empty_travel_min
        + metrics.loaded_travel_min
        + metrics.pickup_handling_min
        + metrics.dropoff_handling_min
    )
    assert metrics.total_duty_time_min > metrics.route_time_min
