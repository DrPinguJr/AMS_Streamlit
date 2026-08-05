---
title: BlueSG V1 compatibility backend
tags: [bluesg, v1, compatibility, legacy]
---

# BlueSG V1 compatibility backend

Back to [[00 BlueSG Index]].

Atomic shared-infrastructure web: [[Route Optimiser Web/50 V1 Compatibility Surface]] · [[Route Optimiser Web/51 OneMap Credential and Token Flow]] · [[Route Optimiser Web/56 V1 Regional Overflow Policy]] · [[Route Optimiser Web/58 Optional Local Improvement]]

`build_optimised_vehicle_routes.py` is about 6,300 lines. It is both the V1 production/rollback solver and the de facto shared backend. V2 is active, but this module remains load-bearing.

## Responsibilities still used across the system

### Input and roster compatibility

- legacy Excel header scanning/aliases and date coercion;
- required job validation;
- stable job identifiers and reconstruction;
- weekday roster workbook creation/read/write;
- legacy rider columns/load aliases, including `Normal → Medium` and `Piority → Priority`;
- conversion to `RiderState`.

The newer job staging and roster workflow sit in separate modules, but rollback, exports, planner, and tests still call compatibility functions.

### Provider and cache

- `.env`, Streamlit secret, environment, token-session handling;
- OneMap token refresh/authentication;
- geocoding and route HTTP requests;
- in-memory and CSV disk caches with locking;
- zone inference and fallback estimates;
- public-transport empty-leg adjustment;
- route geometry and directions;
- `GeocodeResult` and `TravelCost` value objects.

V2 imports `TravelCost`, `get_travel_cost`, `get_empty_travel_cost`, and adjustment/formatting helpers directly.

### V1 solver

`optimise_vehicle_routes` implements the state-aware greedy/insertion path:

- evaluates remaining jobs against rider state;
- scores empty/loaded travel, duty/workload, Max Jobs penalties, load policy, zones/clusters, regional policy, and fallback confidence;
- honors Priority ownership/balance;
- advances current location to each assigned drop-off;
- uses deterministic upload-order/rider tie breaks;
- attempts rescue insertion for unassigned jobs;
- rebalances minimum workload while retaining coverage.

In V1, Max Jobs is soft unless a hard constraint is enabled. This differs from V2, where Maximum is always hard.

### Regional policy

V1 integrates `RegionalOverflowContext` during greedy assignment, rescue, rebalance, and improvement safeguards. It distinguishes primary, supported, and exceptional assignments, protects scarce regional capacity, and writes audit fields.

V2 reuses seven-zone normalization/adjacency but not the complete V1 regional-penalty engine.

### Reconstruction and integrity

- rebuild outputs from explicit rider sequences;
- build jobs by stable ID and sequences from route rows;
- validate exact coverage/duplicates/chaining;
- compute unassigned reasons;
- selective reshuffle and route editor proposals;
- merge unchanged and recalculated routes.

The Route Planner depends heavily on this layer.

### Output and export

- route/summary formatting and fixed compatibility columns;
- map-loader and rider instruction tables;
- warnings/manual review;
- regional/local-search audits;
- `export_routes_to_excel` workbook assembly.

## Optional local improvement

`improve_routes_after_initial_optimisation.py` tries bounded reinsertion, adjacent swap, inter-rider relocation, and one-for-one swap. Each candidate is fully evaluated, constraint-checked, and audited. Coverage and hard feasibility dominate the improvement objective.

The optimizer page disables this path when V2 is selected. It remains relevant for V1 benchmarks/rollback and for understanding historical changelog claims.

## Benchmark path

Root `benchmark_optimizer.py` delegates to `tools/compare_route_optimisation_algorithms.py`, which compares V1 baseline with bounded local improvement, records metrics/artifacts, and can write a corrected workbook. It does not benchmark the active V2 solver as a peer unless extended.

## Safe extraction/retirement sequence

Before deleting the V1 solver, extract and stabilize these shared APIs:

1. canonical route/summary/export schemas;
2. `TravelCost` and provider/cache services;
3. geocode/route fallback and confidence model;
4. roster/job compatibility adapters;
5. route reconstruction/integrity functions;
6. workbook export and re-import contracts;
7. planner incremental-recalculation dependencies.

Only then can V1 scoring/greedy/rescue/rebalance code be retired independently.

## Semantic differences to preserve consciously

| Concern | V1 | V2 |
|---|---|---|
| Primary algorithm | state-aware greedy/insertion + rescue/rebalance | complete-assignment beam search |
| Max Jobs | soft by default; optional hard constraint | Maximum always hard |
| Rider behavior | load levels including Priority | Local/Flexible/Area Lead |
| Regional policy | detailed subregion capacity/penalties | zone adjacency, severity, Area Lead ownership |
| Local improvement | optional post-pass | not run by the page |
| Completion | rescue may relax soft duration, never hard rules | success requires full hard-feasible assignment |
| Shared provider/export | native | imports compatibility APIs |
