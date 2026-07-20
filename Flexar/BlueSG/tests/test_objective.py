from datetime import datetime

from Flexar.BlueSG.models import OptimisationRunResult, RiderRouteMetrics
from Flexar.BlueSG.run_metrics import objective_tuple


def _result(*, unassigned=0, violations=0, duty=60.0):
    metric = RiderRouteMetrics("R", 1, 5, 5, 40, 3, 3, 51, duty, duty * 1.2, 11.1, 0, None, 0, violations, "B")
    return OptimisationRunResult(
        "run", datetime.now(), "a", "2", "f", "h", "2026-07-17", {}, [{}], [{}] * unassigned,
        [metric], [], [], {"hard_violation_count": violations}, {},
    )


def test_objective_prioritises_coverage_over_duration() -> None:
    full_but_long = _result(unassigned=0, duty=200)
    short_but_missing = _result(unassigned=1, duty=10)
    assert objective_tuple(full_but_long) < objective_tuple(short_but_missing)


def test_objective_prioritises_zero_hard_violations() -> None:
    feasible = _result(violations=0, duty=200)
    infeasible = _result(violations=1, duty=10)
    assert objective_tuple(feasible) < objective_tuple(infeasible)

