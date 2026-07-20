from datetime import date, time

from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.travel_costs import build_travel_cache_key
from Flexar.BlueSG.vehicle_route_optimizer import (
    calculate_assignment_score,
    get_fallback_cost,
)


def test_fallback_confidence_and_penalty_do_not_change_duration() -> None:
    fallback = get_fallback_cost("Tampines", "Jurong", "East", "West")
    assert fallback.confidence == "fallback"
    before_duration = fallback.duration_min
    unpenalised = calculate_assignment_score(1, 10, 1, 10, "East", "East", "West", 0, 0, None)
    penalised = calculate_assignment_score(
        1, 10, 1, 10, "East", "East", "West", 0, 0, None,
        fallback_leg_count=1, fallback_penalty=100,
    )
    assert penalised["assignment_score"] == unpenalised["assignment_score"] + 100
    assert fallback.duration_min == before_duration


def test_cache_key_differs_by_mode_and_time_context() -> None:
    day = OperationContext.for_window(date(2026, 7, 17), time(14), time(17))
    night = OperationContext.for_window(date(2026, 7, 17), time(23), time(3))
    day_pt = build_travel_cache_key("A", "B", "public_transport", day)
    night_pt = build_travel_cache_key("A", "B", "public_transport", night)
    night_taxi = build_travel_cache_key("A", "B", "private_hire_taxi", night)
    assert day_pt != night_pt
    assert night_pt != night_taxi

