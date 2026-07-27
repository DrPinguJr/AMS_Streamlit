# BlueSG Route and File Guide

## Purpose

`Flexar/BlueSG` contains two connected Streamlit tools:

1. **Vehicle Route Optimiser** creates a complete rider assignment from an uploaded job workbook.
2. **Route Planner** opens the result, shows it on a map, and lets a dispatcher safely reorder or reassign jobs.

The package is organised by responsibility. The core Python modules remain at the package root because they form the stable `Flexar.BlueSG.*` import API used by the application and tests.

## Application route

```text
app.py / Home.py
├── pages/create_optimised_vehicle_routes_page.py
│   ├── build_optimised_vehicle_routes.py
│   ├── regional_capacity_and_cross_region_assignment_rules.py
│   ├── validate_route_assignment_hard_constraints.py
│   ├── improve_routes_after_initial_optimisation.py
│   └── route_optimisation_metrics_and_run_summary.py
└── pages/review_map_and_manually_adjust_route_assignments_page.py
    ├── manual_route_assignment_editing_and_recalculation.py
    ├── build_optimised_vehicle_routes.py
    └── components/drag_and_drop_route_assignment_board/
```

The optimizer page produces the first route. The planner page consumes that route and applies controlled manual changes using the same validation, travel, and export logic.

## Folder layout

```text
Flexar/BlueSG/
├── Notes/                  Human documentation
├── components/             Custom Streamlit front-end component
├── data/                   Live roster and routing caches
│   └── cache/
│       ├── seed/           Read-only verified geocode seed
│       └── runtime/        Mutable generated cache
├── pages/                  Streamlit user interfaces
├── tests/                  BlueSG unit and integration tests
├── tools/                  Developer-only command-line tools
├── *.py                    Importable optimization and planner modules
└── __init__.py             BlueSG Python package marker
```

## Root integration files

These files are outside `Flexar/BlueSG`, but they route users into it:

| File | Responsibility |
|---|---|
| `app.py` | Registers both BlueSG pages in the main Streamlit navigation. |
| `Home.py` | Shows links to the optimizer and planner. |
| `benchmark_optimizer.py` | Small workspace command that calls `Flexar.BlueSG.tools.compare_route_optimisation_algorithms`. |
| `.env` | Optional local OneMap credentials/token source. Secrets are not stored in run artifacts. |
| `.gitignore` | Excludes the mutable BlueSG runtime cache and generated Python files. |

## Streamlit pages

### `pages/create_optimised_vehicle_routes_page.py`

This is the main operational screen. It:

- uploads and previews a job workbook;
- filters jobs by the selected date;
- loads, edits, deduplicates, and saves the weekday rider roster;
- gathers route, time-window, scoring, capacity, and OneMap settings;
- calls `optimise_vehicle_routes`;
- optionally calls `improve_route_dataframe`;
- shows progress, warnings, metrics, maps, route tables, and a selective reshuffle editor;
- stores the latest result in Streamlit session state;
- writes a JSON run summary through `save_run_artifact`;
- creates the downloadable workbook through `export_routes_to_excel`.

### `pages/review_map_and_manually_adjust_route_assignments_page.py`

This is the separate detailed planning screen. It:

- opens an optimizer workbook or the latest result from the current Streamlit session;
- reconstructs the jobs, riders, summary, and assignment board;
- renders the full-screen map and rider lanes;
- supports locks, drag-and-drop, a reshuffle pool, undo, redo, and reset;
- previews changed rider connectors;
- recalculates only affected riders when a draft is applied;
- validates the result before committing it;
- prevents export while a draft is dirty;
- exports the confirmed plan with the same workbook writer used by the optimizer.

## Core modules

### `build_optimised_vehicle_routes.py`

The production backend and main public API.

Important responsibilities:

- workbook parsing: `load_jobs_from_excel`, `validate_jobs`, and `load_and_validate_jobs`;
- roster storage: `ensure_rider_roster_workbook`, `load_rider_roster`, `save_rider_roster`, and `validate_riders`;
- rider/load normalization, including `Normal` to `Medium` and `Piority` to `Priority`;
- OneMap authentication, geocoding, routing, cache access, and fallback estimates;
- route evaluation and assignment scoring;
- stable job identifiers and route-sequence reconstruction;
- production assignment through `optimise_vehicle_routes`;
- rescue insertion and minimum-workload rebalance;
- integrity and route-chain validation;
- selective reshuffle and optional local-improvement adapters;
- route, summary, rider-instruction, map-loader, audit, and Excel output.

Its main value objects are:

- `RiderState`: a rider's start, current state, capacity preference, and accumulated route totals;
- `GeocodeResult`: a location lookup and its source/error;
- `TravelCost`: distance, duration, route geometry/instructions, source, and confidence.

### `route_operation_time_window_settings.py`

Defines `OperationContext`, including:

- Singapore timezone-aware operation dates;
- start and end datetimes;
- automatic next-day rollover for an overnight window;
- empty-travel mode;
- pickup, drop-off, unlock, and operational buffer settings.

### `regional_capacity_and_cross_region_assignment_rules.py`

Owns geographic capacity policy:

- operational subregion classification;
- primary, approved-support, and exceptional assignment tiers;
- regional rider capacity summaries;
- East boundary affinity;
- directional overflow rules;
- scarce-driver protection;
- regional penalties and audit fields.

### `validate_route_assignment_hard_constraints.py`

Defines the central hard-constraint model and `validate_candidate_routes`. Hard constraints are checked before a candidate route can be accepted. Soft preferences such as ordinary `Max Jobs` scoring stay in the optimizer.

### `improve_routes_after_initial_optimisation.py`

Implements bounded post-processing moves:

- reinsertion;
- adjacent swap;
- inter-rider relocation;
- one-for-one inter-rider swap.

Every candidate is reevaluated and audited. This feature remains optional.

### `manual_route_assignment_editing_and_recalculation.py`

Contains UI-independent planner logic:

- assignment-board normalization and validation;
- locked-rider protection;
- draft history and undo/redo;
- changed-rider and changed-leg detection;
- reshuffle-pool handling;
- map preview geometry;
- exact rider-access previews;
- affected-rider incremental recalculation;
- final job-set and route-chain validation.

Keeping this logic outside the page makes it testable without running Streamlit.

### `route_optimisation_metrics_and_run_summary.py`

Builds the canonical run result and summary metrics used by the UI, workbook, JSON, and benchmark tool. `save_run_artifact` writes summaries under the workspace-level `runs/YYYY-MM-DD/` directory.

### `route_optimisation_result_models.py`

Defines the canonical structured results:

- `TravelLegResult`;
- `RiderRouteMetrics`;
- `OptimisationRunResult`.

### `travel_cache_keys_and_route_confidence.py`

Defines contextual travel-cache keys, source-confidence classification, and standardized fallback warnings. Cache keys include endpoints, mode, day type, hour bucket, and provider version to prevent incompatible reuse.

### `convert_results_to_output_safe_values.py`

Recursively converts pandas, NumPy, datetime, and non-finite values into safe JSON/Excel/Streamlit values.

## Components

| File | Responsibility |
|---|---|
| `components/register_drag_and_drop_route_assignment_board.py` | Registers the custom component with Streamlit. |
| `components/drag_and_drop_route_assignment_board/index.html` | Drag-and-drop rider lanes, locks, highlighting, and reshuffle-pool events. |
| `components/__init__.py` | Marks the component package. |

## Operational data

| Path | Type | Handling |
|---|---|---|
| `data/weekday_rider_availability_and_capacity_roster.xlsx` | Live persistent input | Keep. It contains Monday-Sunday sheets and is edited by the app. |
| `data/cache/seed/verified_onemap_address_coordinates_seed.csv` | Compatible read-only seed | Keep. It avoids repeating known geocodes. |
| `data/cache/runtime/onemap_address_coordinates_runtime_cache.csv` | Generated mutable cache | Keep for speed; it can be rebuilt if deleted. |
| `data/cache/runtime/onemap_travel_routes_runtime_cache.csv` | Generated mutable cache | Keep for speed; current contextual route results are stored here. |

The obsolete legacy route seed was removed because its old coordinate-only keys could not match the current contextual key format.

## Developer tool

### `tools/compare_route_optimisation_algorithms.py`

Runs selected optimizer variants from the command line against a supplied workbook, date, roster, and output directory. It produces result tables, JSON summaries, Excel outputs, and a Markdown comparison. It is not called during normal Streamlit use.

## Test files

| File | Coverage |
|---|---|
| `tests/conftest.py` | Shared job, rider, and operation-window fixtures. |
| `tests/test_route_assignment_hard_constraint_validation.py` | Soft versus hard capacity and central validation. |
| `tests/test_job_workbook_to_optimised_route_export_workflow.py` | Parse, optimize, validate, and Excel-export integration. |
| `tests/test_post_optimisation_route_improvement_safety.py` | Move safety, uniqueness, and no-regression behavior. |
| `tests/test_route_optimisation_objective_priority_order.py` | Lexicographic coverage and feasibility priorities. |
| `tests/test_route_operation_windows_and_duty_time.py` | Overnight rollover and duty composition. |
| `tests/test_output_safe_value_conversion.py` | Nested JSON-safe finite output. |
| `tests/test_regional_capacity_and_cross_region_assignment_rules.py` | Capacity-aware regional policy and scarce-driver protection. |
| `tests/test_travel_cache_keys_and_route_confidence.py` | Contextual cache keys, confidence, and fallback scoring. |

Additional workspace tests under `/tests` cover the planner, page source contracts, progress terminal, selective reshuffle, Priority behavior, and cache behavior.

## Where to make common changes

| Desired change | Primary location |
|---|---|
| Change assignment scoring or solver behavior | `build_optimised_vehicle_routes.py` |
| Change regional ownership or cross-region support | `regional_capacity_and_cross_region_assignment_rules.py` |
| Add a hard rule | `validate_route_assignment_hard_constraints.py` |
| Change operating times or travel mode semantics | `route_operation_time_window_settings.py` |
| Change optimizer controls/layout | `pages/create_optimised_vehicle_routes_page.py` |
| Change planner behavior | `manual_route_assignment_editing_and_recalculation.py` |
| Change planner screen/layout | `pages/review_map_and_manually_adjust_route_assignments_page.py` |
| Change drag-and-drop component behavior | `components/drag_and_drop_route_assignment_board/index.html` |
| Change Excel sheets | `build_optimised_vehicle_routes.py` |
| Change run metrics/schema | `route_optimisation_metrics_and_run_summary.py` and `route_optimisation_result_models.py` |
