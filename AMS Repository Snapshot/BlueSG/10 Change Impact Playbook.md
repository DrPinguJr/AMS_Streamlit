---
title: BlueSG large-change impact playbook
tags: [bluesg, migration, change-management]
---

# BlueSG large-change impact playbook

Back to [[00 BlueSG Index]]. This is the primary guide for the planned large change.

Navigate the atomic dependency paths in [[Route Optimiser Web/91 Change Impact Routes]] and validate them through [[Route Optimiser Web/93 Acceptance Scenarios]].

## Non-negotiable invariants

1. Every selected job is represented exactly once as assigned or explicitly unassigned/infeasible.
2. Pickup→drop-off is atomic; no solver/planner operation splits it.
3. A rider route starts at the roster start and chains each prior drop-off to the next pickup.
4. Hard constraints and Maximum Jobs are never traded for a lower score in V2.
5. Stable Job ID survives import, solve, edit, export, and re-import.
6. Low-confidence/fallback travel stays visible.
7. Failed manual recalculation does not mutate the last confirmed plan.
8. Dirty drafts cannot be exported.
9. Secrets and live rider/job data never enter source, logs, artifacts, tests, or this vault.
10. Algorithm name/version and input hash identify every retained run.

## Impact matrix

| Change | Primary files | Required neighboring checks |
|---|---|---|
| Job format/header/schema | `job_import_staging.py`, compatibility parser | workflow state, page importer, stable IDs, V2Job, workbook export/re-import, workflow tests |
| Rider roster/work styles | `optimiser_workflow_state.py`, `vehicle_route_optimiser_v2.py`, `v2_daily_roster_source.py` | legacy aliases, local workbook/Google CSV, planner rider reconstruction, V2 core/workflow tests |
| Hard constraints/feasibility | V2 route evaluation or central V1 validator | operation context, planner apply, integrity, objective, infeasible UI, export metadata |
| V2 objective/search | `vehicle_route_optimiser_v2.py` | job ordering, beam width/time semantics, explanations, deterministic fixtures, status/metrics |
| V1 scoring/regional behavior | compatibility backend, regional module | rescue/rebalance/improvement, benchmark, audits, V1/root tests |
| OneMap/provider/cache | compatibility backend, cache helper | V2 matrix, planner previews/apply, provider version, fallback warnings, Cloud secrets |
| Operation time/mode | operation context, optimizer page | cache keys, end requirements, duty metrics, tests, artifact settings |
| Route/summary columns | compatibility backend | V2 compatible output, UI tables/maps, planner load/apply, Excel sheets, tests |
| Planner behavior/component | planner helper/page/HTML component | exact IDs, locks, history, colors, preview signatures, network reuse, export guard |
| Workbook sheets | export backend | planner import, downstream Flexar use, tests, source docs |
| Cloud import/dependency | requirements/preflight/router | exact-pin test, Python 3.12 smoke check, safe error display |
| Authentication/storage | access control/router | Linux/Windows policy, session isolation, privacy review, durable external store |

## Recommended branch sequence for a rewrite

### Phase 0 — capture

- Freeze this commit and keep a known input workbook/roster outside source control.
- Save one V2 result workbook, JSON summary, cache mode, and screen captures without personal data.
- Run default and expanded tests; record the known non-BlueSG folder-name failure separately.

### Phase 1 — characterize contracts

- Add golden tests for the exact intended input aliases, rider rules, route columns, workbook sheets, and planner round-trip.
- Add small deterministic objective fixtures for every proposed policy change.
- Decide whether old V1 behavior is rollback-only or must remain user-selectable.

### Phase 2 — extract shared infrastructure if architecture is changing

- Move provider/cache, schemas, export, and integrity into dedicated modules behind stable adapters.
- Keep both V1 and V2 tests passing after each extraction.
- Avoid mixing extraction with objective changes; otherwise regressions are hard to attribute.

### Phase 3 — implement policy/solver change

- Keep travel matrix/provider I/O outside search.
- Preserve deterministic ordering/tie breaks.
- Emit explicit algorithm version and explanations.
- Return `INFEASIBLE`, never a misleading partial success, when the new hard model cannot cover all jobs.

### Phase 4 — planner/output migration

- Adapt compatible route rows before touching planner internals where possible.
- Verify upload→solve→export→planner upload→edit→apply→export.
- Test dirty/failed states, not only the happy path.

### Phase 5 — operational acceptance

- Run sanitized small, 30-job regression, capacity-shortfall, fallback-only, and cross-midnight cases.
- Run a controlled live OneMap/cache-warm/cache-cold comparison.
- Have dispatch users verify explanations, rider instructions, manual-review warnings, map paths, and workbook usability.

## Acceptance scorecard

| Category | Pass condition |
|---|---|
| Coverage | all feasible selected jobs assigned exactly once |
| Hard feasibility | zero violations in success states |
| Determinism | same inputs/context/cache produce same assignment/order |
| Chain | every Start From matches roster start or prior drop-off |
| Capacity | hard Maximum never exceeded; shortfall explained |
| Quality | objective movement explained; no hidden regression in empty/duty/fallback/extreme metrics |
| Planner | locks/history/preview/apply/export transactions remain safe |
| Output | 13 sheets and required columns remain or migrate with an approved compatibility plan |
| Security | no secrets/PII in Git, UI errors, logs, artifacts, fixtures |
| Cloud | exact dependency/preflight/login/storage smoke checks pass |

## Rollback preparation

- Retain `optimiser_config.py` switch until live acceptance is complete.
- Keep the previous algorithm code/imports deployable and tested.
- A rollback must also restore compatible roster semantics, algorithm metadata, and cache/schema assumptions—not just flip a UI label.
- Never roll back using stale generated workbooks as source code.
