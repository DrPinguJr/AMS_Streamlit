# BlueSG Vehicle Route Optimiser Architecture

## Runtime entrypoints

- The main Streamlit page is `Flexar/BlueSG/Vehicle_Route_Optimiser.py`. It is registered by `app.py` and linked from `Home.py`.
- The separate interactive planner/map page is `Flexar/BlueSG/Route_Map_Viewer.py`.
- The production optimisation engine entrypoint is `optimise_vehicle_routes` in `Flexar/BlueSG/vehicle_route_optimizer.py`.
- `optimise_routes` and `build_excel_download` in the same module are compatibility wrappers around the engine and Excel exporter.

## Input parsing and date filtering

- `load_jobs_from_excel` locates and normalises the workbook header row.
- `validate_jobs` validates pickup/drop-off fields, preserves the source row as `_uploaded_row`, preserves upload order as `_original_order`, and derives pickup/drop-off zones.
- `load_and_validate_jobs` composes those two operations.
- `Flexar/BlueSG/Vehicle_Route_Optimiser.py` performs the user-selected date filtering after parsing and before calling the optimiser.

## Rider parsing and configuration

- `ensure_rider_roster_workbook`, `load_rider_roster`, `save_rider_roster`, and `read_rider_roster_file` manage the weekday roster workbook.
- `validate_riders` converts the edited table to `RiderState` objects.
- `dedupe_rider_roster` removes repeated rider rows before optimisation.
- `RiderState` carries each rider's start/current location, zone, assigned count, duration, soft `Max Jobs`, and load level.
- The Streamlit rider editor in `Vehicle_Route_Optimiser.py` is the user-facing configuration surface.

## Production assignment flow

`optimise_vehicle_routes` implements the production state-aware flow:

1. Stable `_original_order` sorting creates the unassigned job list.
2. `evaluate_rider_sequence` evaluates a rider's complete prospective sequence from their configured start.
3. The greedy loop compares every remaining fixed pickup-to-drop-off job with every rider and ranks feasible candidates using explicit tuple tie-breakers.
4. On assignment, the rider sequence and `RiderState.current_location`/`current_zone` are updated to the selected job's drop-off.
5. The rescue pass attempts insertion of leftovers at every rider/position and can relax the duration cap when complete assignment is requested.
6. The minimum-job rebalance attempts to give under-target riders work without losing jobs.
7. Final routes are rebuilt from accepted rider sequences.
8. `optimisation_integrity_report`, `validate_optimisation_integrity`, and `validate_route_chain` check missing, duplicate, overlap, and chaining errors.

`find_best_selective_reshuffle` provides the existing bounded, opt-in route-editor reshuffle. `rebuild_outputs_from_sequences` and `evaluate_explicit_rider_sequence` recalculate manually edited sequences using the production evaluator.

## Cluster behaviour

- `infer_zone` supplies broad geographic labels.
- `calculate_route_zone_priority`, `calculate_zone_adjustment`, cluster counts in `evaluate_rider_sequence`, and the cluster pressure term in `optimise_vehicle_routes` are score hints.
- Jobs remain atomic and are not pre-packaged into hard cluster assignments.
- `route_variant_index` provides deterministic alternate score perturbations; it does not change the assignment unit.

## Capacity-aware regional overflow

- `Flexar/BlueSG/regional_overflow.py` owns operational subregion classification, the directional support graph, East rider affinity, regional capacity summaries, per-round specificity/protected-job sets, three-tier candidate assessment, and audit fields.
- `optimise_vehicle_routes` builds the regional context before assignment and supplies it with route-aware empty-travel costs from every feasible rider/job comparison.
- The protected-job set is recalculated each greedy and rescue round after rider current locations change. Regional penalties are added to the existing candidate score; they do not bypass hard constraints or make exceptional coverage assignments impossible.
- Rescue insertion uses the same candidate tiers. Minimum-rider rebalance prices unsupported transfers and strongly prices movement of high-specificity work away from its primary rider.
- `rebuild_outputs_from_sequences` reapplies tier/audit classification for manual refresh and local-search candidates. `improve_assigned_routes` rejects a move that increases unsupported exceptions or West Core primary misassignments.
- Streamlit reads `route_df.attrs["regional_capacity"]`; Excel writers create `Regional Capacity` and `Regional Assignment Audit` sheets from the same route result.

## Travel cost provider and caches

- `get_cached_geocode` and `geocode_address_onemap` provide geocoding.
- `get_onemap_route_cost` calls/parses OneMap routing.
- `get_fallback_cost` returns zone estimates.
- `get_travel_cost` selects verified/cached/fallback costs for loaded driving legs.
- `get_empty_travel_cost` selects public-transport or walking access costs, and `adjust_empty_travel_for_public_transport` applies the operational multiplier/wait buffer.
- `TravelCost` is the current travel-result value object.
- In-memory caches are `GEOCODE_MEMORY_CACHE` and `ROUTE_MEMORY_CACHE`. Seed caches live in `Flexar/BlueSG/cache`; mutable runtime caches live in `Flexar/BlueSG/cache/runtime` (or `BLUESG_RUNTIME_CACHE_DIR`).
- `_load_geocode_disk_cache_once`, `_load_route_disk_cache_once`, `_append_csv_cache_row`, and `_write_csv_cache` implement disk-cache access.

## Route evaluation and validation

- `calculate_assignment_score` combines travel, workload, duration, zone, and soft maximum-job preferences.
- `evaluate_explicit_rider_sequence` is the reusable evaluator for a known sequence.
- `optimisation_integrity_report` is the non-raising coverage/duplicate report.
- `validate_optimisation_integrity` raises on invalid coverage/duplicate state.
- `validate_route_chain` and `format_route_output` attach row-level chain status.
- `route_planner.validate_assignment_board`, `route_planner.validate_locked_rider_change`, and `route_planner._validate_route_chaining` protect manual planner changes.

## Output builders

- `format_route_output` and `format_summary_output` provide the legacy route/summary data-frame contract.
- `_overall_summary` and `_data_quality_rows` build workbook-facing metrics and diagnostics.
- `build_unassigned_jobs_df` preserves selected jobs not present in routes.
- `_build_whatsapp_message` and `_build_route_table_text` create concise rider instructions.
- `_write_rider_instructions_sheet`, `_write_manager_dispatch_summary_sheet`, `_write_unassigned_jobs_sheet`, `_write_rejected_candidate_audit_sheet`, and `_write_map_loader_sheet` build operational sheets.
- `export_routes_to_excel` is the Excel output entrypoint and preserves `How To Read This`, `Optimised Routes`, `Map Loader`, `Unassigned Jobs`, `Summary`, and `Rider Instructions` (plus conditional audit/dispatch sheets).
- `show_route_map` and `build_route_map_data` in `Vehicle_Route_Optimiser.py` render the embedded result map.
- `Route_Map_Viewer.py` and pure helpers in `route_planner.py` provide the detailed assignment board, route recalculation, route locking, undo/redo, selective reshuffle, and map preview.

## Baseline capture

- Pre-change backup: `artifacts/pre_implementation_backup/Flexar_BlueSG`.
- Baseline artifacts are stored under `artifacts/baseline`.
- Source workbook: `Antares x Flexar - RB Jobs (5) 1.xlsx`, filtered to 17 July 2026.
- Git commit at audit: `704ac6a6cc214fe43302806daa7f7948a7af7512`.
- The two optimiser source files contained pre-existing uncommitted progress-terminal changes; these were treated as user-owned and preserved.
