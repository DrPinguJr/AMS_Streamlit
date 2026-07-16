from __future__ import annotations

from io import BytesIO
import json

import pandas as pd
import pytest

from Flexar.BlueSG import vehicle_route_optimizer as optimizer
from Flexar.BlueSG.route_planner import (
    UNASSIGNED_LANE,
    RESHUFFLE_POOL_LANE,
    assignment_from_routes,
    build_planner_session_state,
    build_draft_connector_lines,
    build_rider_access_paths,
    build_rider_start_markers,
    build_focus_map_data,
    build_compact_rider_summary,
    build_route_leg_signatures,
    clone_assignment,
    derive_sequences_from_assignment,
    detect_affected_riders,
    detect_changed_route_legs,
    incremental_recalculate,
    enter_focus_mode_state,
    exit_focus_mode_state,
    focus_apply_failure_state,
    focus_apply_success_state,
    draft_assignment_signature,
    invalidate_red_preview,
    matching_red_preview_routes,
    normalise_rider_locks,
    normalise_assignment_board,
    refresh_red_connector_preview,
    record_manual_job_moves,
    reconcile_reshuffle_pool_board,
    renderable_red_preview_routes,
    redo_draft,
    reset_draft,
    reshuffle_unlocked_assignments,
    undo_draft,
    update_draft_history,
    validate_assignment_board,
    validate_locked_rider_change,
)
from Flexar.BlueSG.vehicle_route_optimizer import (
    GeocodeResult,
    RiderState,
    SUMMARY_COLUMNS,
    TravelCost,
    build_jobs_by_stable_id,
    export_routes_to_excel,
    format_summary_output,
    rebuild_outputs_from_sequences,
    stable_job_id_from_job,
)


@pytest.fixture()
def planner_data():
    jobs = [
        {"Uploaded Row": 2, "_original_order": 0, "Car Plate": "SPE1001A", "Pickup Address": "Tampines", "Pickup Lot": "A1", "Drop-off Address": "Bedok", "Pickup Zone": "East", "Drop-off Zone": "East"},
        {"Uploaded Row": 3, "_original_order": 1, "Car Plate": "SPE1002B", "Pickup Address": "Simei", "Pickup Lot": "B2", "Drop-off Address": "Pasir Ris", "Pickup Zone": "East", "Drop-off Zone": "East"},
        {"Uploaded Row": 4, "_original_order": 2, "Car Plate": "SPE1003C", "Pickup Address": "Yishun", "Pickup Lot": "C3", "Drop-off Address": "Woodlands", "Pickup Zone": "North", "Drop-off Zone": "North"},
    ]
    jobs_df = pd.DataFrame(jobs)
    ids = {job["Car Plate"]: stable_job_id_from_job(job) for job in jobs}
    rider_df = pd.DataFrame(
        [
            {"Rider Name": "Lester", "Start Location": "Tampines", "Start Zone": "East", "Max Jobs": 5, "Rider Load": "Medium"},
            {"Rider Name": "Syed", "Start Location": "Yishun", "Start Zone": "North", "Max Jobs": 5, "Rider Load": "Medium"},
        ]
    )
    riders = [RiderState("Lester", "Tampines", "East", max_jobs=5), RiderState("Syed", "Yishun", "North", max_jobs=5)]
    assignment = {"Lester": [ids["SPE1001A"], ids["SPE1002B"]], "Syed": [ids["SPE1003C"]], UNASSIGNED_LANE: []}
    routes, _, _ = rebuild_outputs_from_sequences(
        {"Lester": assignment["Lester"], "Syed": assignment["Syed"]},
        riders,
        build_jobs_by_stable_id(jobs_df),
        jobs_df=jobs_df,
        use_onemap=False,
    )
    return jobs_df, rider_df, ids, assignment, routes


def summary_builder(route_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for rider, routes in route_df.groupby("Rider", sort=False):
        total = float(pd.to_numeric(routes["Total Duration Min"], errors="coerce").fillna(0).sum())
        rows.append({"Rider": rider, "Total Jobs": len(routes), "Total Route Duration Min": total, "Adjusted Route Duration Min": total * 1.2, "Within 3 Hours": "OK", "Final Location": routes.iloc[-1]["Drop-off Address"]})
    frame = pd.DataFrame(rows)
    for column in SUMMARY_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0 if "Distance" in column or "Duration" in column else ""
    return format_summary_output(frame[SUMMARY_COLUMNS], route_df)


def test_reorder_within_one_rider_affects_only_that_rider(planner_data) -> None:
    _, _, _, original, _ = planner_data
    draft = {**original, "Lester": list(reversed(original["Lester"]))}
    assert detect_affected_riders(original, draft) == ["Lester"]
    assert derive_sequences_from_assignment(draft, ["Lester", "Syed"])["Lester"] == draft["Lester"]


def test_move_between_riders_affects_both_only(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    assert detect_affected_riders(original, draft) == ["Lester", "Syed"]


def test_move_into_and_out_of_unassigned(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    unassigned = {"Lester": [ids["SPE1001A"]], "Syed": original["Syed"], UNASSIGNED_LANE: [ids["SPE1002B"]]}
    assert validate_assignment_board(unassigned, ids.values(), ["Lester", "Syed"]).is_valid
    restored = {"Lester": original["Lester"], "Syed": original["Syed"], UNASSIGNED_LANE: []}
    assert validate_assignment_board(restored, ids.values(), ["Lester", "Syed"]).is_valid


@pytest.mark.parametrize(
    ("mutator", "field"),
    [
        (lambda board, job: {**board, "Syed": [*board["Syed"], job]}, "duplicate_job_ids"),
        (lambda board, job: {**board, "Lester": board["Lester"][1:]}, "missing_job_ids"),
        (lambda board, job: {**board, "Lester": [*board["Lester"], "unknown-job"]}, "unknown_job_ids"),
    ],
)
def test_assignment_validation_rejects_duplicate_missing_and_unknown(planner_data, mutator, field) -> None:
    _, _, ids, original, _ = planner_data
    validation = validate_assignment_board(mutator(original, ids["SPE1001A"]), ids.values(), ["Lester", "Syed"])
    assert not validation.is_valid
    assert getattr(validation, field)


def test_normalise_board_uses_exact_mappings_not_business_label_parsing() -> None:
    raw = [{"header": "Lester · lane-x", "items": ["SPE1001A · opaque-a"]}, {"header": "Unassigned · lane-y", "items": []}]
    result = normalise_assignment_board(raw, {"Lester · lane-x": "Lester", "Unassigned · lane-y": UNASSIGNED_LANE}, {"SPE1001A · opaque-a": "job-stable-1"}, ["Lester", UNASSIGNED_LANE])
    assert result == {"Lester": ["job-stable-1"], UNASSIGNED_LANE: []}


def test_normalise_board_rejects_duplicate_empty_lane() -> None:
    raw = [
        {"header": "Unassigned A", "items": []},
        {"header": "Unassigned B", "items": []},
    ]
    with pytest.raises(ValueError, match="more than once"):
        normalise_assignment_board(
            raw,
            {"Unassigned A": UNASSIGNED_LANE, "Unassigned B": UNASSIGNED_LANE},
            {},
            [UNASSIGNED_LANE],
        )


def test_undo_redo_and_reset_transitions(planner_data) -> None:
    _, _, _, original, _ = planner_data
    proposed = {**original, "Lester": list(reversed(original["Lester"]))}
    current, undo, redo, changed = update_draft_history(original, proposed, [], [])
    assert changed and redo == []
    current, undo, redo, changed = undo_draft(current, undo, redo)
    assert changed and current == original
    current, undo, redo, changed = redo_draft(current, undo, redo)
    assert changed and current == proposed
    current, undo, redo, changed = reset_draft(original, current)
    assert changed and current == original and redo == []


def test_locked_rider_sequence_is_strictly_immutable(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    proposed = {
        "Lester": [ids["SPE1001A"]],
        "Syed": [ids["SPE1003C"], ids["SPE1002B"]],
        UNASSIGNED_LANE: [],
    }
    validation = validate_locked_rider_change(original, proposed, ["Lester"])
    assert not validation.is_valid
    assert "Lester" in validation.errors[0]
    assert validate_locked_rider_change(original, proposed, ["Syed"]).is_valid is False


def test_lock_state_removes_stale_riders_and_captures_baseline(planner_data) -> None:
    _, _, _, original, _ = planner_data
    locked, baselines = normalise_rider_locks(
        ["Missing", "Lester"], ["Lester", "Syed"], original, {"Missing": ["old"]}
    )
    assert locked == ["Lester"]
    assert baselines == {"Lester": original["Lester"]}


def test_manual_move_history_preserves_first_origin(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    moved = {
        "Lester": [ids["SPE1001A"]],
        "Syed": [ids["SPE1003C"], ids["SPE1002B"]],
        UNASSIGNED_LANE: [],
    }
    history = record_manual_job_moves(original, moved)
    returned = record_manual_job_moves(moved, original, history)
    assert returned[ids["SPE1002B"]]["origin_rider_id"] == "Lester"
    assert returned[ids["SPE1002B"]]["last_to_rider_id"] == "Lester"


def test_purple_draft_connector_appears_immediately_for_changed_legs(planner_data) -> None:
    jobs_df, rider_df, ids, original, _ = planner_data
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    coordinates = {
        "Tampines": [103.94, 1.35], "Bedok": [103.93, 1.32], "Simei": [103.95, 1.34],
        "Pasir Ris": [103.95, 1.37], "Yishun": [103.84, 1.43], "Woodlands": [103.79, 1.44],
    }
    unchanged = build_draft_connector_lines(
        original, original, jobs_df, starts, coordinate_lookup=coordinates.get
    )
    assert unchanged.route_df.empty
    draft = {
        "Lester": [ids["SPE1001A"]],
        "Syed": [ids["SPE1003C"], ids["SPE1002B"]],
        UNASSIGNED_LANE: [],
    }
    changed = build_draft_connector_lines(
        original, draft, jobs_df, starts, coordinate_lookup=coordinates.get
    )
    assert not changed.route_df.empty
    assert set(changed.route_df["geometry_source"]) == {"draft_straight_line"}
    assert changed.route_df.iloc[0]["color"] == [168, 85, 247, 235]


def test_purple_connectors_cover_middle_insert_and_removed_gap(planner_data) -> None:
    jobs_df, rider_df, ids, _, _ = planner_data
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    coordinates = {
        "Tampines": [103.94, 1.35], "Bedok": [103.93, 1.32], "Simei": [103.95, 1.34],
        "Pasir Ris": [103.95, 1.37], "Yishun": [103.84, 1.43], "Woodlands": [103.79, 1.44],
    }
    a, b, c = ids["SPE1001A"], ids["SPE1002B"], ids["SPE1003C"]
    before_insert = {"Lester": [a, c], "Syed": [b], UNASSIGNED_LANE: []}
    after_insert = {"Lester": [a, b, c], "Syed": [], UNASSIGNED_LANE: []}
    inserted = build_draft_connector_lines(
        before_insert, after_insert, jobs_df, starts, coordinate_lookup=coordinates.get
    )
    assert {(row["Rider"], row["Job ID"]) for _, row in inserted.route_df.iterrows()} >= {
        ("Lester", b), ("Lester", c)
    }
    removed = build_draft_connector_lines(
        after_insert, before_insert, jobs_df, starts, coordinate_lookup=coordinates.get
    )
    closed_gap = removed.route_df[(removed.route_df["Rider"] == "Lester") & (removed.route_df["Job ID"] == c)]
    assert len(closed_gap) == 1
    assert closed_gap.iloc[0]["path"] == [coordinates["Bedok"], coordinates["Yishun"]]


def test_reshuffle_pool_freezes_selected_jobs_until_action(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    selected = ids["SPE1002B"]
    board = {
        RESHUFFLE_POOL_LANE: [selected],
        "Lester": [ids["SPE1001A"]],
        "Syed": list(original["Syed"]),
        UNASSIGNED_LANE: [],
    }
    proposed, pool = reconcile_reshuffle_pool_board(original, board)
    assert pool == [selected]
    assert proposed == original


def test_rider_start_markers_are_bright_white() -> None:
    markers = build_rider_start_markers(
        ["Rider A", "Rider B"],
        {"Rider A": "Home A", "Rider B": "Missing"},
        coordinate_lookup={"Home A": [103.8, 1.3]}.get,
    )
    assert markers[["Rider", "lon", "lat"]].to_dict("records") == [
        {"Rider": "Rider A", "lon": 103.8, "lat": 1.3}
    ]
    assert markers.iloc[0]["fill_color"] == [255, 255, 255, 255]


def test_red_rider_access_uses_confirmed_public_transport_then_cache(planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    first = routes[routes["Car Plate"] == "SPE1001A"].index[0]
    routes.loc[first, "Start From"] = "Tampines"
    routes.loc[first, "Empty Route Path"] = json.dumps([[103.94, 1.35], [103.941, 1.351]])
    coordinates = {"Tampines": [103.94, 1.35], "Yishun": [103.84, 1.43], "SPE": [0, 0]}
    for address in jobs_df["Pickup Address"]:
        coordinates.setdefault(address, [103.9 + len(coordinates) / 1000, 1.3])
    result = build_rider_access_paths(
        original, ["Lester"], routes, pd.DataFrame(), jobs_df, starts, {}, coordinate_lookup=coordinates.get
    )
    assert result.route_df.iloc[0]["geometry_source"] == "cached_public_transport"
    assert result.route_df.iloc[0]["color"] == [239, 68, 68, 235]
    cached = build_rider_access_paths(
        original, ["Lester"], pd.DataFrame(), pd.DataFrame(), jobs_df, starts, result.cache,
        coordinate_lookup=coordinates.get,
    )
    assert cached.route_df.iloc[0]["geometry_source"] == "cached_public_transport"


def test_red_rider_access_falls_back_without_network_and_changes_with_first_job(planner_data) -> None:
    jobs_df, rider_df, ids, original, _ = planner_data
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    coordinates = {address: [103.8 + index / 100, 1.3 + index / 100] for index, address in enumerate(
        ["Tampines", "Yishun", *jobs_df["Pickup Address"].tolist()]
    )}
    initial = build_rider_access_paths(
        original, ["Lester"], pd.DataFrame(), pd.DataFrame(), jobs_df, starts, {},
        coordinate_lookup=coordinates.get,
    )
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    changed = build_rider_access_paths(
        reordered, ["Lester"], pd.DataFrame(), pd.DataFrame(), jobs_df, starts, initial.cache,
        coordinate_lookup=coordinates.get,
    )
    assert initial.route_df.iloc[0]["geometry_source"] == "fallback_straight_line"
    assert changed.route_df.iloc[0]["Job ID"] == ids["SPE1002B"]
    assert changed.route_df.iloc[0]["path"] != initial.route_df.iloc[0]["path"]


def test_missing_access_coordinates_fail_safely_without_mutating_assignment(planner_data) -> None:
    jobs_df, rider_df, _, original, _ = planner_data
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    before = clone_assignment(original)
    result = build_rider_access_paths(
        original, ["Lester", "Syed"], pd.DataFrame(), pd.DataFrame(), jobs_df, starts, {},
        coordinate_lookup=lambda _address: None,
    )
    assert result.route_df.empty
    assert len(result.warnings) == 2
    assert original == before


def test_reshuffle_wrapper_preserves_locks_and_assignment_integrity(planner_data) -> None:
    jobs_df, rider_df, ids, original, _ = planner_data
    rider_df = pd.concat([
        rider_df,
        pd.DataFrame([{"Rider Name": "Alex", "Start Location": "Bedok", "Start Zone": "East", "Max Jobs": 5, "Rider Load": "Medium"}]),
    ], ignore_index=True)
    draft = {**original, "Alex": []}

    def fake_search(sequences, *args, **kwargs):
        assert kwargs["locked_riders"] == {"Lester"}
        assert kwargs["reshuffle_job_ids"] == {ids["SPE1003C"]}
        assert kwargs["origin_rider_by_job"][ids["SPE1003C"]] == "Syed"
        proposed = {rider: list(jobs) for rider, jobs in sequences.items()}
        proposed["Syed"] = []
        proposed["Alex"] = [ids["SPE1003C"]]
        return {"success": True, "proposed_sequences": proposed, "candidate_count": 4, "plan_score": 10}

    result = reshuffle_unlocked_assignments(
        draft,
        ["Lester"],
        {ids["SPE1003C"]: {"origin_rider_id": "Syed"}},
        rider_df,
        jobs_df,
        eligible_job_ids=[ids["SPE1003C"]],
        search_fn=fake_search,
    )
    assert result.changed
    assert result.assignment["Lester"] == draft["Lester"]
    assert sorted(job for jobs in result.assignment.values() for job in jobs) == sorted(
        job for jobs in draft.values() for job in jobs
    )
    current, undo, redo, changed = update_draft_history(draft, result.assignment, [], [])
    assert changed
    current, undo, redo, _ = undo_draft(current, undo, redo)
    assert current == draft
    current, undo, redo, _ = redo_draft(current, undo, redo)
    assert current == result.assignment


def test_origin_return_penalty_is_soft_but_material_and_origin_remains_feasible() -> None:
    summary = pd.DataFrame([{"Adjusted Route Duration Min": 100.0}])
    original = {"A": ["job"], "B": []}
    origin = optimizer._selective_plan_result(
        original, original, pd.DataFrame(), summary, 100.0, {"job"}, 1,
        changed_rider_penalty=0, moved_job_penalty=0, sequence_change_penalty=0,
        origin_rider_by_job={"job": "A"}, origin_return_penalty=20,
    )
    away = optimizer._selective_plan_result(
        original, {"A": [], "B": ["job"]}, pd.DataFrame(), summary, 100.0, {"job"}, 2,
        changed_rider_penalty=0, moved_job_penalty=0, sequence_change_penalty=0,
        origin_rider_by_job={"job": "A"}, origin_return_penalty=20,
    )
    assert origin["success"] and origin["origin_return_count"] == 1
    assert origin["plan_score"] == away["plan_score"] + 20


def test_route_leg_signatures_only_change_necessary_connector(planner_data) -> None:
    jobs_df, rider_df, ids, original, _ = planner_data
    jobs = build_jobs_by_stable_id(jobs_df)
    starts = dict(zip(rider_df["Rider Name"], rider_df["Start Location"]))
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    changes = detect_changed_route_legs(build_route_leg_signatures(original, jobs, starts), build_route_leg_signatures(draft, jobs, starts))
    assert f"loaded::{ids['SPE1002B']}" in changes["unchanged"]
    assert any(key.startswith("empty::") and ids["SPE1002B"] in key for key in changes["changed"])


def test_precomputed_loaded_and_empty_legs_avoid_lookup(monkeypatch, planner_data) -> None:
    jobs_df, _, ids, _, routes = planner_data
    job = build_jobs_by_stable_id(jobs_df)[ids["SPE1001A"]]
    row = routes[routes["Car Plate"] == "SPE1001A"].iloc[0]
    loaded = TravelCost(row["Loaded Distance KM"], row["Loaded Duration Min"], "reused")
    empty = TravelCost(row["Empty Distance KM"], row["Empty Duration Min"], "reused")
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: pytest.fail("empty lookup called"))
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("loaded lookup called"))
    stats = {}
    result = optimizer.evaluate_explicit_rider_sequence(
        RiderState("Lester", "Tampines", "East"), [job], use_onemap=True,
        precomputed_loaded_costs={ids["SPE1001A"]: loaded},
        precomputed_empty_costs={("Lester", ids["SPE1001A"]): empty}, route_lookup_stats=stats,
    )
    assert result["rows"] and stats == {"reused_empty": 1, "reused_loaded": 1}


def test_changed_uncached_connector_calls_lookup_but_loaded_is_reused(monkeypatch, planner_data) -> None:
    jobs_df, _, ids, _, routes = planner_data
    job = build_jobs_by_stable_id(jobs_df)[ids["SPE1001A"]]
    row = routes[routes["Car Plate"] == "SPE1001A"].iloc[0]
    calls = []
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: calls.append("empty") or TravelCost(1, 5, "OneMap"))
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("loaded lookup called"))
    stats = {}
    optimizer.evaluate_explicit_rider_sequence(
        RiderState("Lester", "Different Start", "East"), [job], use_onemap=True,
        precomputed_loaded_costs={ids["SPE1001A"]: TravelCost(row["Loaded Distance KM"], row["Loaded Duration Min"], "reused")},
        route_lookup_stats=stats,
    )
    assert calls == ["empty"] and stats["onemap_requests"] == 1 and stats["reused_loaded"] == 1


def test_existing_route_cache_avoids_second_onemap_call(monkeypatch, tmp_path) -> None:
    start = GeocodeResult("A", 1.300001, 103.800001, "test")
    end = GeocodeResult("B", 1.310001, 103.810001, "test")
    key = "1.300001,103.800001|1.310001,103.810001"
    optimizer.ROUTE_MEMORY_CACHE.pop(key, None)
    monkeypatch.setattr(optimizer, "ROUTE_DISK_CACHE_LOADED", True)
    monkeypatch.setattr(optimizer, "ROUTE_CACHE_FILE", tmp_path / "routes.csv")
    calls = []
    monkeypatch.setattr(optimizer, "_fetch_json", lambda *a, **k: calls.append(1) or {"route_summary": {"total_distance": 1000, "total_time": 600}})
    first = optimizer.get_onemap_route_cost(start, end)
    second = optimizer.get_onemap_route_cost(start, end)
    assert first.duration_min == 10 and second.duration_min == 10
    assert calls == [1] and "cache" in second.source.lower()
    optimizer.ROUTE_MEMORY_CACHE.pop(key, None)


def test_incremental_recalculation_and_export_use_applied_assignment(planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    result = incremental_recalculate(
        confirmed_routes=routes, confirmed_assignment=original, draft_assignment=draft,
        rider_df=rider_df, jobs_df=jobs_df, settings={"use_onemap": False}, summary_builder=summary_builder,
    )
    assert result.affected_riders == ["Lester", "Syed"]
    syed = result.route_df[result.route_df["Rider"] == "Syed"].sort_values("Sequence")
    assert syed["Car Plate"].tolist() == ["SPE1003C", "SPE1002B"]
    assert syed["Sequence"].tolist() == [1, 2]
    exported = export_routes_to_excel(result.route_df, result.summary_df, jobs_df=jobs_df)
    exported_routes = pd.read_excel(BytesIO(exported), sheet_name="Optimised Routes", header=4)
    assert exported_routes.loc[exported_routes["Car Plate"] == "SPE1002B", "Rider"].iloc[0] == "Syed"


def test_failed_recalculation_does_not_mutate_confirmed_routes(planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    before = routes.copy(deep=True)
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    def failing_rebuild(*args, **kwargs):
        raise TimeoutError("OneMap timeout")
    with pytest.raises(TimeoutError):
        incremental_recalculate(
            confirmed_routes=routes, confirmed_assignment=original, draft_assignment=draft,
            rider_df=rider_df, jobs_df=jobs_df, settings={"use_onemap": True}, summary_builder=summary_builder, rebuild=failing_rebuild,
        )
    pd.testing.assert_frame_equal(routes, before)


def test_new_workbook_session_payload_clears_stale_history(planner_data) -> None:
    jobs_df, _, _, _, routes = planner_data
    payload = build_planner_session_state(routes, jobs_df, ["Lester", "Syed"], "new-workbook")
    assert payload["route_planner_workbook_id"] == "new-workbook"
    assert payload["route_planner_undo_stack"] == []
    assert payload["route_planner_redo_stack"] == []
    assert payload["route_planner_is_dirty"] is False
    assert payload["route_planner_locked_rider_ids"] == ["Lester", "Syed"]
    assert payload["route_planner_locked_rider_baselines"] == {
        "Lester": payload["route_planner_draft_assignment"]["Lester"],
        "Syed": payload["route_planner_draft_assignment"]["Syed"],
    }
    assert payload["route_planner_manual_move_history"] == {}
    assert payload["route_planner_rider_access_cache"] == {}
    assert payload["route_planner_reshuffle_pool_job_ids"] == []
    assert payload["route_planner_highlighted_rider_ids"] == []


def test_unapplied_draft_is_distinct_from_confirmed_for_export_guard(planner_data) -> None:
    _, _, ids, confirmed, routes = planner_data
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    assert draft != confirmed
    assert routes.loc[routes["Car Plate"] == "SPE1002B", "Rider"].iloc[0] == "Lester"


def routes_with_cached_geometry(routes: pd.DataFrame) -> pd.DataFrame:
    enriched = routes.copy()
    for offset, index in enumerate(enriched.index):
        lon = 103.80 + (offset * 0.01)
        lat = 1.30 + (offset * 0.01)
        enriched.at[index, "Loaded Route Path"] = json.dumps([[lon, lat], [lon + 0.004, lat + 0.004]])
        enriched.at[index, "Empty Route Path"] = json.dumps([[lon - 0.003, lat - 0.003], [lon, lat]])
    return enriched


def test_entering_focus_mode_preserves_confirmed_and_makes_no_route_call(monkeypatch, planner_data) -> None:
    jobs_df, _, _, _, routes = planner_data
    payload = build_planner_session_state(routes, jobs_df, ["Lester", "Syed"], "book")
    before = payload["route_planner_confirmed_routes"].copy(deep=True)
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("routing called"))
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: pytest.fail("routing called"))
    updates = enter_focus_mode_state(payload, ["Lester", "Syed"])
    assert updates == {"route_planner_focus_mode": True, "route_planner_visible_riders": ["Lester", "Syed"]}
    pd.testing.assert_frame_equal(payload["route_planner_confirmed_routes"], before)


def test_green_route_follows_job_move_and_reorder(planner_data) -> None:
    jobs_df, _, ids, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    moved = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    moved_map = build_focus_map_data(moved, ["Lester", "Syed"], routes, jobs_df)
    moved_row = moved_map.route_df[moved_map.route_df["Job ID"] == ids["SPE1002B"]].iloc[0]
    assert moved_row["Rider"] == "Syed" and moved_row["Sequence"] == 2
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    reordered_map = build_focus_map_data(reordered, ["Lester", "Syed"], routes, jobs_df)
    reordered_row = reordered_map.route_df[reordered_map.route_df["Job ID"] == ids["SPE1002B"]].iloc[0]
    assert reordered_row["Rider"] == "Lester" and reordered_row["Sequence"] == 1
    assert moved_row["path"] == reordered_row["path"]


def test_focus_map_is_green_only_and_visibility_does_not_change_draft(planner_data) -> None:
    jobs_df, _, _, assignment, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    before = {lane: list(job_ids) for lane, job_ids in assignment.items()}
    visible = build_focus_map_data(assignment, ["Lester"], routes, jobs_df)
    assert set(visible.route_df["Rider"]) == {"Lester"}
    assert set(visible.route_df["leg_type"]) == {"loaded"}
    assert "Syed" not in set(visible.marker_df["Rider"])
    assert assignment == before


def test_drag_undo_redo_refresh_green_map_without_onemap(monkeypatch, planner_data) -> None:
    jobs_df, _, _, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    proposed = {**original, "Lester": list(reversed(original["Lester"]))}
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("routing called"))
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: pytest.fail("routing called"))
    current, undo, redo, _ = update_draft_history(original, proposed, [], [])
    assert build_focus_map_data(current, ["Lester"], routes, jobs_df).route_df.sort_values("Sequence")["Car Plate"].tolist() == ["SPE1002B", "SPE1001A"]
    current, undo, redo, _ = undo_draft(current, undo, redo)
    assert build_focus_map_data(current, ["Lester"], routes, jobs_df).route_df.sort_values("Sequence")["Car Plate"].tolist() == ["SPE1001A", "SPE1002B"]
    current, undo, redo, _ = redo_draft(current, undo, redo)
    assert build_focus_map_data(current, ["Lester"], routes, jobs_df).route_df.sort_values("Sequence")["Car Plate"].tolist() == ["SPE1002B", "SPE1001A"]


def test_apply_reuses_green_and_unchanged_red_but_recalculates_changed_red(monkeypatch, planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    draft = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    calls: list[str] = []
    monkeypatch.setattr(
        optimizer,
        "get_empty_travel_cost",
        lambda *a, **k: calls.append("red") or TravelCost(1, 5, "OneMap", route_path=[[103.9, 1.3], [103.91, 1.31]]),
    )
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("valid green rerouted"))
    result = incremental_recalculate(
        confirmed_routes=routes, confirmed_assignment=original, draft_assignment=draft,
        rider_df=rider_df, jobs_df=jobs_df, settings={"use_onemap": True}, summary_builder=summary_builder,
    )
    assert calls == ["red"]
    assert result.stats["reused_loaded"] == 3
    assert result.stats["reused_connectors"] == 2
    changed = result.route_df[result.route_df["Car Plate"] == "SPE1002B"].iloc[0]
    assert json.loads(changed["Empty Route Path"])
    assert json.loads(changed["Loaded Route Path"])


def test_apply_recalculates_only_missing_green_route(monkeypatch, planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    routes.loc[routes["Car Plate"] == "SPE1002B", "Loaded Route Path"] = "[]"
    draft = {**original, "Lester": list(reversed(original["Lester"]))}
    green_calls: list[str] = []
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: TravelCost(1, 5, "OneMap", route_path=[[103.8, 1.3], [103.81, 1.31]]))
    monkeypatch.setattr(
        optimizer,
        "get_travel_cost",
        lambda *a, **k: green_calls.append("green") or TravelCost(2, 7, "OneMap", route_path=[[103.82, 1.32], [103.83, 1.33]]),
    )
    result = incremental_recalculate(
        confirmed_routes=routes, confirmed_assignment=original, draft_assignment=draft,
        rider_df=rider_df, jobs_df=jobs_df, settings={"use_onemap": True}, summary_builder=summary_builder,
    )
    assert green_calls == ["green"]
    assert result.stats["reused_loaded"] == 1


def test_focus_success_failure_and_exit_state_are_atomic(planner_data) -> None:
    jobs_df, _, _, assignment, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    payload = build_planner_session_state(routes, jobs_df, ["Lester", "Syed"], "book")
    payload["route_planner_focus_mode"] = True
    payload["route_planner_is_dirty"] = True
    result = type("Result", (), {
        "route_df": routes,
        "summary_df": summary_builder(routes),
        "warnings": [],
        "affected_riders": ["Lester"],
        "stats": {"reused_legs": 4, "reused_loaded": 2, "reused_connectors": 2, "cache_hits": 0, "onemap_requests": 0},
    })()
    success = focus_apply_success_state(assignment, result)
    assert success["route_planner_focus_mode"] is False
    assert success["route_planner_is_dirty"] is False
    assert success["route_planner_manual_move_history"] == {}
    assert success["route_planner_draft_connectors"].empty
    assert success["route_planner_reshuffle_pool_job_ids"] == []
    assert success["route_planner_highlighted_rider_ids"] == []
    failed = focus_apply_failure_state(payload)
    assert failed["route_planner_focus_mode"] is True
    assert failed["route_planner_draft_assignment"] == payload["route_planner_draft_assignment"]
    pd.testing.assert_frame_equal(failed["route_planner_confirmed_routes"], routes)
    assert exit_focus_mode_state(payload) == {"route_planner_focus_mode": False}
    assert payload["route_planner_is_dirty"] is True


def test_preview_signature_changes_after_reorder(planner_data) -> None:
    _, _, _, original, _ = planner_data
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    assert draft_assignment_signature(original) != draft_assignment_signature(reordered)
    assert draft_assignment_signature(original) == draft_assignment_signature({key: list(value) for key, value in reversed(list(original.items()))})


def test_drag_invalidates_only_affected_preview_riders(planner_data) -> None:
    _, _, ids, original, _ = planner_data
    moved = {"Lester": [ids["SPE1001A"]], "Syed": [ids["SPE1003C"], ids["SPE1002B"]], UNASSIGNED_LANE: []}
    assert invalidate_red_preview(original, moved) == ("Lester", "Syed")
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    assert invalidate_red_preview(original, reordered) == ("Lester",)


def test_red_preview_refreshes_only_stale_and_preserves_unaffected(planner_data) -> None:
    jobs_df, rider_df, ids, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    existing = pd.DataFrame([
        {"Rider": "Syed", "Sequence": 1, "Job ID": ids["SPE1003C"], "Start Label": "Yishun", "End Label": "Yishun", "Distance KM": 1, "Duration Min": 4, "Route Path": json.dumps([[103.8, 1.3], [103.81, 1.31]]), "Source": "existing preview"}
    ])
    calls: list[tuple[str, str]] = []
    result = refresh_red_connector_preview(
        confirmed_routes=routes,
        confirmed_assignment=original,
        draft_assignment={**original, "Lester": list(reversed(original["Lester"]))},
        existing_preview_routes=existing,
        stale_riders=["Lester"],
        rider_df=rider_df,
        jobs_df=jobs_df,
        use_onemap=True,
        token=None,
        connector_lookup=lambda start, end, *a, **k: calls.append((start, end)) or TravelCost(1, 5, "OneMap cache", route_path=[[103.9, 1.3], [103.91, 1.31]]),
    )
    assert set(result.route_df["Rider"]) == {"Lester", "Syed"}
    assert result.route_df[result.route_df["Rider"] == "Syed"].iloc[0]["Source"] == "existing preview"
    assert len(calls) == 2
    assert result.stats["refreshed_riders"] == 1


def test_red_preview_reuses_identical_confirmed_connector_first(planner_data) -> None:
    jobs_df, rider_df, _, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    result = refresh_red_connector_preview(
        confirmed_routes=routes,
        confirmed_assignment=original,
        draft_assignment=original,
        existing_preview_routes=None,
        stale_riders=["Lester"],
        rider_df=rider_df,
        jobs_df=jobs_df,
        use_onemap=True,
        token=None,
        connector_lookup=lambda *a, **k: pytest.fail("identical confirmed connector was looked up"),
    )
    assert result.stats["confirmed_reused"] == 2
    assert set(result.route_df["Source"]) == {"confirmed connector reused"}


def test_red_preview_cache_source_is_counted_without_confirmed_mutation(planner_data) -> None:
    jobs_df, rider_df, _, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    before = routes.copy(deep=True)
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    result = refresh_red_connector_preview(
        confirmed_routes=routes,
        confirmed_assignment=original,
        draft_assignment=reordered,
        existing_preview_routes=None,
        stale_riders=["Lester"],
        rider_df=rider_df,
        jobs_df=jobs_df,
        use_onemap=True,
        token=None,
        connector_lookup=lambda *a, **k: TravelCost(1, 5, "OneMap cache", route_path=[[103.9, 1.3], [103.91, 1.31]]),
    )
    assert result.stats["cache_hits"] == 2 and result.stats["onemap_requests"] == 0
    pd.testing.assert_frame_equal(routes, before)


def test_matching_red_preview_is_reused_during_apply(monkeypatch, planner_data) -> None:
    jobs_df, rider_df, _, original, routes = planner_data
    routes = routes_with_cached_geometry(routes)
    reordered = {**original, "Lester": list(reversed(original["Lester"]))}
    preview = refresh_red_connector_preview(
        confirmed_routes=routes, confirmed_assignment=original, draft_assignment=reordered,
        existing_preview_routes=None, stale_riders=["Lester"], rider_df=rider_df, jobs_df=jobs_df,
        use_onemap=True, token=None,
        connector_lookup=lambda *a, **k: TravelCost(1, 5, "OneMap cache", route_path=[[103.9, 1.3], [103.91, 1.31]]),
    )
    monkeypatch.setattr(optimizer, "get_empty_travel_cost", lambda *a, **k: pytest.fail("matching preview connector rerouted"))
    monkeypatch.setattr(optimizer, "get_travel_cost", lambda *a, **k: pytest.fail("valid green rerouted"))
    result = incremental_recalculate(
        confirmed_routes=routes, confirmed_assignment=original, draft_assignment=reordered,
        rider_df=rider_df, jobs_df=jobs_df, settings={"use_onemap": True}, summary_builder=summary_builder,
        matching_preview_routes=preview.route_df,
    )
    assert result.stats["reused_connectors"] == 2


def test_compact_summary_totals_and_workload_limits(planner_data) -> None:
    _, rider_df, _, _, routes = planner_data
    summary = build_compact_rider_summary(routes, rider_df, duration_limit_min=180)
    assert summary["Job count"].sum() == len(routes)
    assert summary["Total minutes"].sum() == pytest.approx(pd.to_numeric(routes["Total Duration Min"]).sum())
    assert set(summary["Workload"]) <= {"Heavy", "Balanced", "Light"}
    tiny_limits = rider_df.copy()
    tiny_limits["Max Jobs"] = 1
    heavy = build_compact_rider_summary(routes, tiny_limits, duration_limit_min=1)
    assert set(heavy["Workload"]) == {"Heavy"}


def test_compact_summary_does_not_invent_workload_without_limits(planner_data) -> None:
    _, rider_df, _, _, routes = planner_data
    rider_df = rider_df.copy()
    rider_df["Max Jobs"] = None
    summary = build_compact_rider_summary(routes, rider_df, duration_limit_min=None)
    assert set(summary["Workload"]) == {""}
    assert set(summary["Status"]) == {"Limits unavailable"}


def test_stale_preview_is_hidden_but_unaffected_rows_remain(planner_data) -> None:
    _, _, ids, _, _ = planner_data
    preview = pd.DataFrame([
        {"Rider": "Lester", "Job ID": ids["SPE1001A"]},
        {"Rider": "Syed", "Job ID": ids["SPE1003C"]},
    ])
    visible = renderable_red_preview_routes(preview, ["Lester", "Syed"], ["Lester"])
    assert visible["Rider"].tolist() == ["Syed"]


def test_apply_preview_selection_requires_exact_signature_and_no_stale_riders(planner_data) -> None:
    _, _, _, assignment, _ = planner_data
    preview = pd.DataFrame([{"Rider": "Lester"}])
    signature = draft_assignment_signature(assignment)
    assert matching_red_preview_routes(preview, signature, assignment, []) is not None
    assert matching_red_preview_routes(preview, "wrong", assignment, []) is None
    assert matching_red_preview_routes(preview, signature, assignment, ["Lester"]) is None
