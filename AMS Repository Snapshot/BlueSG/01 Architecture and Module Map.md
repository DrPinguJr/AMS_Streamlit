---
title: BlueSG architecture and module map
tags: [bluesg, architecture, dependencies]
---

# BlueSG architecture and module map

Back to [[00 BlueSG Index]].

Atomic graph: [[Route Optimiser Web/02 Runtime Dependency Spine]] · [[Route Optimiser Web/03 Data Lineage]] · [[Route Optimiser Web/04 Complexity Hotspots]]

## Current execution architecture

```text
Streamlit optimizer page
├─ job_import_staging → committed_jobs
├─ v2_daily_roster_source → optimiser_workflow_state → committed_riders
├─ OperationContext
├─ optimiser_config = v2
│  └─ vehicle_route_optimiser_v2
│     ├─ shared V1 TravelCost / get_*_travel_cost / format_*_output
│     └─ shared zone adjacency normalization
├─ integrity + canonical run result + JSON artifact
├─ Excel export (V1 compatibility backend)
└─ session payload → Route Planner
   └─ manual_route_assignment_editing_and_recalculation
      └─ V1 rebuild/travel/export helpers
```

## Layer boundaries

### Entrypoints and routing

- Root `app.py`: full AMS workspace; both BlueSG pages are in the Flexar group.
- `streamlit_app.py`: dedicated Cloud path bootstrap.
- `cloud_streamlit_router.py`: authenticated/preflighted `/optimise` and `/review` navigation.

### UI/orchestration

- `create_optimised_vehicle_routes_page.py`: import, roster dialog, operation/advanced settings, optimization progress, result review, batch reassignment, dispatch view, export.
- `review_map_and_manually_adjust_route_assignments_page.py`: workbook/session load, focus map, drag/drop lane board, locking, pool reshuffle, undo/redo/reset, preview, apply, result/export.

These pages contain substantial orchestration and session-state logic; domain tests often assert their source layout in addition to testing pure helper modules.

### Workflow/domain state

- `job_import_staging.py`: converts external formats into canonical job rows.
- `optimiser_workflow_state.py`: separates drafts from committed inputs and hashes committed inputs to detect stale results.
- `v2_daily_roster_source.py`: daily roster source selection/persistence.
- `route_operation_time_window_settings.py`: immutable temporal/travel-mode context.

### Solver paths

- V2 active: `vehicle_route_optimiser_v2.py`.
- V1 rollback/compatibility: `build_optimised_vehicle_routes.py`.
- V1 optional improvement: `improve_routes_after_initial_optimisation.py`.
- V1 geographic policy: `regional_capacity_and_cross_region_assignment_rules.py`.
- V1 candidate validation: `validate_route_assignment_hard_constraints.py`.

The optimizer page explicitly runs local improvement only when `OPTIMISER_VERSION != "v2"`.

### Planner

- `manual_route_assignment_editing_and_recalculation.py`: pure assignment/state/recalculation helpers.
- custom HTML component: lane/card drag/drop UI.
- planner page: visualization and user interaction.

### Output boundaries

- `route_optimisation_result_models.py`: canonical dataclasses.
- `route_optimisation_metrics_and_run_summary.py`: one shared run summary and JSON artifact.
- `convert_results_to_output_safe_values.py`: removes NaN/infinity and converts dataclasses/dates/paths recursively.
- `build_optimised_vehicle_routes.export_routes_to_excel`: operational workbook.

### Provider/cache boundary

OneMap authentication, geocoding, routing, disk caches, fallbacks, route paths, and `TravelCost` remain in the compatibility backend. `travel_cache_keys_and_route_confidence.py` owns context-aware key/confidence helpers.

## Active V2 / compatibility coupling

V2 imports these compatibility APIs:

- `ROUTE_COLUMNS`, `SUMMARY_COLUMNS`;
- `TravelCost`;
- empty-travel public-transport adjustment;
- text cleaning and zone inference;
- `get_empty_travel_cost`, `get_travel_cost`;
- route and summary output formatting.

Consequences:

1. V2 search logic can evolve independently from V1 scoring.
2. V2 output remains consumable by current UI, metrics, workbook, and planner.
3. Removing or changing V1 column names/provider signatures can break V2 without touching V2 search code.
4. A future clean split should first extract shared provider/schema/export modules, then retire the V1 solver portion.

## Data ownership

| Data | Owner/source | Lifecycle |
|---|---|---|
| job draft | import staging/UI | replaceable until validation/commit |
| committed jobs | workflow state | optimizer input; change makes result stale |
| rider draft | roster dialog | cancel/save transaction |
| committed riders | workflow state | optimizer input; change makes result stale |
| optimizer result | workflow state/session | tied to a committed-input signature |
| planner confirmed assignment/routes | planner state | last safe exportable plan |
| planner draft assignment | planner state | mutable; dirty draft blocks export |
| OneMap caches | provider backend/disk | shared rebuildable performance data |
| run result/artifact | metrics module | sanitized audit evidence |
| downloaded workbook | export backend/user | durable operational handoff |
