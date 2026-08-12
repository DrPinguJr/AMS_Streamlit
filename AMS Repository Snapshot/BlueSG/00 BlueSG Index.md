---
title: BlueSG knowledge base
snapshot_date: 2026-08-05
active_optimizer: v2
tags: [ams, bluesg, index]
---

# BlueSG knowledge base

Back to [[../00 Repository Index]].

## Route Optimiser mega web

Enter [[Route Optimiser Web/00 Route Optimiser Mega Web]] for the heavily split, node-based Route Optimiser map. Its 59 connected notes branch into atomic input, state, roster, time, V2 solver, V1 compatibility, OneMap/cache, output, planner, Cloud, test, and change-impact nodes with dense lateral dependency links.

## Critical snapshot statement

The live developer switch is `OPTIMISER_VERSION = "v2"`. The V2 solver is active, but it deliberately depends on the V1-era backend for travel acquisition/cache, compatible route/summary formatting, run metrics, Excel export, and much of planner recalculation. “Replace V1” is therefore not a single-file operation.

## Deep-dive notes

- [[01 Architecture and Module Map]] — execution/data boundaries and every module’s role.
- [[02 Optimiser V2 Deep Dive]] — roster model, matrix, hard feasibility, beam search, objective, and statuses.
- [[03 V1 Compatibility Backend]] — what the 6,300-line backend still owns and why it cannot simply be removed.
- [[04 Data Input State and Schemas]] — import formats, staged/committed state, rider schema, operation context.
- [[05 Route Planner Deep Dive]] — draft/confirmed state, locks, map colors, incremental recalculation, export guard.
- [[06 Travel OneMap Cache and Confidence]] — credential precedence, geocoding/routing, cache keys, fallback semantics.
- [[07 Outputs Metrics and Artifacts]] — route/summary schemas, canonical results, JSON and workbook outputs.
- [[08 Deployment Security Operations]] — Cloud entrypoint, access gate, preflight, temporary storage.
- [[09 Tests Guarantees and Known Issues]] — behavioral contracts and current warnings/debt.
- [[10 Change Impact Playbook]] — safe paths for the next large change.
- [[11 Glossary and Defaults]] — terms, thresholds, modes, constants, and active defaults.
- [[Route Optimiser Web/00 Route Optimiser Mega Web]] — detailed dependency graph for reference and major changes.

## Source file quick map

| File | Current responsibility |
|---|---|
| `optimiser_config.py` | developer-only V1/V2 switch; currently V2 |
| `vehicle_route_optimiser_v2.py` | independent severity/area-lead beam-search solver |
| `build_optimised_vehicle_routes.py` | V1 solver plus shared parser, roster, OneMap/cache, rebuild, export compatibility API |
| `job_import_staging.py` | multi-format V2-era job import and validation |
| `optimiser_workflow_state.py` | staged/committed inputs, rider drafts, stale-result signatures, assignment validation |
| `v2_daily_roster_source.py` | Google-Sheet-first daily roster with local workbook fallback |
| `route_operation_time_window_settings.py` | Singapore timezone, cross-midnight windows, handling/buffer/mode context |
| `regional_capacity_and_cross_region_assignment_rules.py` | V1 regional policy and shared seven-zone adjacency normalization |
| `validate_route_assignment_hard_constraints.py` | central V1/local-improvement constraint validator |
| `improve_routes_after_initial_optimisation.py` | bounded V1 post-optimization moves and audit |
| `manual_route_assignment_editing_and_recalculation.py` | UI-independent planner state, preview, locks, reshuffle, incremental apply |
| `travel_cache_keys_and_route_confidence.py` | contextual cache identity and confidence/warning classification |
| `route_optimisation_result_models.py` | canonical run/leg/rider dataclasses |
| `route_optimisation_metrics_and_run_summary.py` | metrics, objective, sanitized JSON artifact persistence |
| `convert_results_to_output_safe_values.py` | finite and JSON-safe boundary conversion |
| `pages/create_optimised_vehicle_routes_page.py` | 3,284-line operational optimizer UI/orchestrator |
| `pages/review_map_and_manually_adjust_route_assignments_page.py` | 2,219-line detailed planner UI/orchestrator |
| `pages/hourly_route_optimiser_page.py` | rolling hourly dispatch UI: append releases, live shift timeline, commit completions, re-solve remainder, standby-driver review |
| `hourly_route_dispatch.py` | pure engine behind the hourly page: append/dedupe, archive contiguous completions, residual-rider shrink, incremental re-solve, standby-options orchestration |
| `gemini_standby_advisor.py` | pure Gemini (`google-genai`) call for the standby-driver activation recommendation; never raises |
| `hourly_dispatch_ledger.py` | local Excel same-day resume ledger for the hourly page; not durable across a Cloud redeploy |
| `onemap_token_session.py` | shared per-session OneMap token override + dialog; used by the hourly page, duplicated (not shared) in the main optimiser page |
| `gemini_key_session.py` | shared per-session Gemini API key override + dialog, mirroring `onemap_token_session.py` |
| `components/.../index.html` | drag/drop lane board UI |
| `components/register_...py` | component registration; currently legacy `streamlit.components.v1` |
| `cloud_access_control.py` | shared password gate |
| `cloud_deployment_preflight.py` | dependency/module/export smoke checks with safe UI errors |
| `cloud_streamlit_router.py` | BlueSG-only navigation |
| `streamlit_app.py` | Community Cloud entrypoint and path bootstrap |
| `tools/compare_route_optimisation_algorithms.py` | V1 baseline/local-improvement benchmark CLI |
| `requirements.txt` | exact Cloud pins |
| `Notes/*.md` | earlier V1-centered design/operational notes |
| `tests/*.py` | BlueSG unit/integration contracts |

## Core invariant

Each relocation job is atomic:

```text
rider current location
→ empty travel to pickup
→ pickup handling/unlock
→ loaded car movement to drop-off
→ drop-off becomes the next current location
```

Stable job identity, exactly-once coverage, route chaining, and hard feasibility must survive optimization, manual edits, recalculation, export, and re-import.
