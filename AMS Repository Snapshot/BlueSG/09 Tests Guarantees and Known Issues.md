---
title: BlueSG tests, guarantees, and known issues
tags: [bluesg, tests, guarantees, debt]
---

# BlueSG tests, guarantees, and known issues

Back to [[00 BlueSG Index]].

Atomic contract web: [[Route Optimiser Web/90 Behaviour Contract Map]] · [[Route Optimiser Web/92 Known Technical Debt]] · [[Route Optimiser Web/93 Acceptance Scenarios]]

## Snapshot result

The default root+BlueSG suite passed `191/191` tests. No BlueSG test failed in the expanded 303-test run. See [[../01 Snapshot Baseline]] for commands and warnings.

## BlueSG package test contracts

| Test file | Protected behavior |
|---|---|
| `test_job_workbook_to_optimised_route_export_workflow.py` | parse→optimize→validate→export, 30-job coverage, route chaining, deterministic tie break |
| `test_output_safe_value_conversion.py` | nested NaN/infinity becomes finite JSON-safe output |
| `test_post_optimisation_route_improvement_safety.py` | accepted moves preserve count/uniqueness/atomicity; no-op returns baseline |
| `test_regional_capacity_and_cross_region_assignment_rules.py` | scarcity, directional support, East affinity, exceptional fallback, clustering, rescue/improvement safety, 30-job regional fixture |
| `test_route_assignment_hard_constraint_validation.py` | V1 Max Jobs soft by default, hard when enabled, duplicates/address rejection |
| `test_route_operation_windows_and_duty_time.py` | overnight rollover, 14:00–17:00 default, duty includes positioning/handling |
| `test_route_optimisation_objective_priority_order.py` | canonical objective puts coverage then hard feasibility first |
| `test_travel_cache_keys_and_route_confidence.py` | fallback penalty does not falsify duration; mode/time cache separation |
| `test_vehicle_route_optimiser_v2_core.py` | strict roster, hard maximum, completion, severity/Area Lead/burden/end-return logic, matrix/cache/progress/serialization |
| `test_vehicle_route_optimiser_v2_workflow.py` | multi-format import, atomic commit/drafts, stale result, assignment validation/recalculation, export compatibility |
| `test_zone_adjacency_route_assignments.py` | seven-zone policy, adjacent time limits, local preference, exceptional-only cross-zone behavior |

## Workspace-level BlueSG contracts

| Test file | Protected behavior |
|---|---|
| `test_bluesg_streamlit_cloud_deployment.py` | existing pages, dedicated/full entrypoints, preflight/reload/sanitization, exact pins, safe secret example, gitignore, token-widget secrecy, login policy |
| `test_priority_and_geocode_cache.py` | V1 Priority ownership/balance, load aliases, parallel deduplicated geocoding, silent worker context, North-West support |
| `test_route_optimiser_terminal.py` | progress history and human-readable rider/order/start-location events |
| `test_route_planner.py` | exact assignment identity, locks, history, pool, map/preview reuse, incremental apply, atomic failure, export guard |
| `test_route_planner_layout.py` | Streamlit/pydeck compatibility, focus sizing, rider panel/pool controls, route colors/arrows, focus controller, dirty export guard |
| `test_selective_reshuffle.py` | bounded reshuffle behavior and safety |

## V2 guarantees most important for a rewrite

- Maximum Jobs is a hard cap; Preferred Jobs is soft.
- A success status means all jobs are assigned.
- Capacity 31 can cover a deterministic 30-job fixture.
- A route with zero-minute empty travel is valid, not missing.
- Area Lead capacity is reserved for home demand and may be overridden only by configured advantage logic.
- A return/end requirement must be reachable by its deadline.
- Travel matrix caching is context-aware and reusable across provider runs.
- Result DataFrame attributes are JSON-serializable.
- Progress is throttled and reaches completion.

## Planner guarantees most important for a rewrite

- Stable IDs, not card labels/plates, define identity.
- Exactly-once job coverage is required in drafts.
- Locked sequences cannot change.
- Failed recalculation leaves confirmed state untouched.
- Dirty drafts are not exportable.
- Only affected rider legs should cause recalculation/network lookup.
- Identical confirmed/preview/cache connectors are reused safely.
- New workbook loads clear stale history.

## Known issues/debt at snapshot

1. Planner red-preview concatenation emits three pandas FutureWarnings at line 1127; future pandas behavior may change inferred dtypes for empty/all-NA frames.
2. The custom route-board registration uses legacy `streamlit.components.v1`, although current Streamlit guidance favors newer component APIs. A migration would require UI/layout/interaction regression testing.
3. The V2 selection docstring states V1 remains for rollback until live acceptance scenarios are exercised. Automated coverage is strong but does not replace real roster/workbook acceptance.
4. The changelog says a historical V1 local-search benchmark was not promoted because empty travel increased despite full coverage/hard feasibility.
5. Existing source notes are primarily V1-centered and do not fully describe the active V2 path; this vault corrects that snapshot gap.

## Test execution trap

`pytest -q` does not discover WhatsApp/HRIQ tests, but it does cover root and BlueSG. Do not alter `pytest.ini` casually during a BlueSG rewrite; CI/runtime assumptions may rely on its speed and scope. Add a separate whole-repository command/job if broader gating is desired.
