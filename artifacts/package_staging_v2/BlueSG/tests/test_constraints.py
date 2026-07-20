from Flexar.BlueSG.constraints import Constraint, validate_candidate_routes
from Flexar.BlueSG.vehicle_route_optimizer import RiderState, optimise_vehicle_routes


def test_max_jobs_is_soft_by_default(regression_jobs, overnight_context) -> None:
    rider = RiderState("R", "Tampines", "East", max_jobs=1)
    route_df, _, _ = optimise_vehicle_routes(
        regression_jobs.iloc[:2], [rider], use_onemap=False, operation_context=overnight_context
    )
    assert len(route_df) == 2


def test_hard_max_jobs_is_enforced_when_enabled(regression_jobs, overnight_context) -> None:
    rider = RiderState("R", "Tampines", "East", max_jobs=1)
    route_df, _, _ = optimise_vehicle_routes(
        regression_jobs.iloc[:2],
        [rider],
        use_onemap=False,
        operation_context=overnight_context,
        constraints=[Constraint("hard_max_jobs", {"rider_caps": {"R": 1}})],
    )
    assert len(route_df) == 1


def test_central_validator_rejects_duplicates_and_invalid_addresses(overnight_context) -> None:
    job = {"Uploaded Row": 2, "Pickup Address": "", "Drop-off Address": "Bedok"}
    result = validate_candidate_routes({"R": [job, dict(job)]}, overnight_context, [])
    assert not result.is_valid
    assert {item["kind"] for item in result.violations} >= {"duplicate_job_assignment", "invalid_address"}

