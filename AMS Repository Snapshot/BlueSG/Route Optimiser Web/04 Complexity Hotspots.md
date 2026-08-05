---
title: Route Optimiser complexity hotspots
tags: [bluesg, route-optimiser, complexity]
---

# Complexity hotspots

Bridge: [[00 Route Optimiser Mega Web]].

## Highest-density files

| File | Approximate size | Why it is complex |
|---|---:|---|
| `build_optimised_vehicle_routes.py` | 6,300 lines | [[50 V1 Compatibility Surface]], provider/cache, V1 solver, reconstruction, export |
| optimizer Streamlit page | 3,284 lines | [[60 Optimiser Page Orchestrator]], state, dialogs, progress, maps, result actions |
| planner Streamlit page | 2,219 lines | [[70 Route Planner Bridge]], map/focus UI, component/state orchestration |
| `vehicle_route_optimiser_v2.py` | 1,465 lines | matrix, feasibility, severity, beam search, explanations |
| planner helper | 1,378 lines | identity, locks/history, geometry, cache reuse, incremental apply |

## Algorithmic hotspots

- candidate pair volume in [[41 Travel Matrix Construction]];
- route reevaluation inside [[45 Beam Search Expansion]];
- global policy ordering in [[47 Lexicographic Objective]];
- route-leg reuse/invalidation in [[75 Map and Preview Geometry]] and [[76 Incremental Recalculation]].

## Coupling hotspots

- V2 ↔ V1 shared surface: [[02 Runtime Dependency Spine]];
- route schema ↔ workbook ↔ planner: [[62 Compatible Route Schema]], [[64 Excel Workbook Contract]], [[71 Planner Input Reconstruction]];
- session state ↔ two Streamlit pages: [[20 Workflow State Machine]], [[70 Route Planner Bridge]].

## Change guidance

Use [[91 Change Impact Routes]] before editing a hotspot and [[93 Acceptance Scenarios]] before promotion.

