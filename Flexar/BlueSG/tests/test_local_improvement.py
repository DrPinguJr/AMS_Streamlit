from Flexar.BlueSG.local_improvement import improve_assigned_routes
from Flexar.BlueSG.vehicle_route_optimizer import RiderState


def _evaluator(candidate):
    ids = [job["Uploaded Row"] for jobs in candidate.values() for job in jobs]
    order_penalty = 0 if candidate["A"][0]["Uploaded Row"] == 2 else 10
    return {
        "objective_tuple": (0, 0, order_penalty, 0, 0, 0, 0, order_penalty, 0, 0),
        "jobs_assigned": len(ids),
        "unassigned_job_count": 0,
        "hard_constraint_violation_count": 0,
        "fallback_leg_count": 0,
        "validation": {"is_valid": True, "hard_violation_count": 0},
    }


def test_accepted_move_preserves_count_uniqueness_and_atomic_jobs(overnight_context) -> None:
    sequences = {"A": [{"Uploaded Row": 3, "Pickup Address": "C", "Drop-off Address": "D"}, {"Uploaded Row": 2, "Pickup Address": "A", "Drop-off Address": "B"}]}
    improved, audit = improve_assigned_routes(
        sequences, [RiderState("A", "A")], overnight_context, {"_candidate_evaluator": _evaluator}, [],
        time_limit_seconds=2, max_iterations=5,
    )
    ids = [job["Uploaded Row"] for job in improved["A"]]
    assert ids == [2, 3]
    assert sorted(ids) == [2, 3]
    assert any(move["accepted"] for move in audit)
    assert all("Pickup Address" in job and "Drop-off Address" in job for job in improved["A"])


def test_no_improvement_returns_baseline_unchanged(overnight_context) -> None:
    sequences = {"A": [{"Uploaded Row": 2, "Pickup Address": "A", "Drop-off Address": "B"}]}
    improved, audit = improve_assigned_routes(
        sequences, [RiderState("A", "A")], overnight_context, {"_candidate_evaluator": _evaluator}, [],
        time_limit_seconds=1, max_iterations=2,
    )
    assert improved == sequences
    assert not any(move["accepted"] for move in audit)

