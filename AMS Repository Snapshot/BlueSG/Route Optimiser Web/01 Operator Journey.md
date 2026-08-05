---
title: Route Optimiser operator journey
tags: [bluesg, route-optimiser, operator-flow]
---

# Operator journey

Bridge: [[00 Route Optimiser Mega Web]].

The operator experiences three visible stages inside [[60 Optimiser Page Orchestrator]]:

1. Upload jobs through [[10 Job Source Detection]].
2. Confirm riders through [[22 Daily Roster Sources]] and [[23 Rider Draft Transaction]].
3. Run, review, explain, adjust, and download through [[49 V2 Status and Explanations]], [[61 Progress and Diagnostics]], and [[64 Excel Workbook Contract]].

The separate planning route begins at [[70 Route Planner Bridge]].

## Hidden work behind one click

The Run button freezes [[14 Job Validation and Atomic Commit]] and validated riders from [[24 V2 Rider Validation]], creates [[30 Operation Context]], passes [[40 V2 Capacity Gate]], builds [[41 Travel Matrix Construction]], and enters [[45 Beam Search Expansion]].

The visible result is not directly the solver object. It passes through [[62 Compatible Route Schema]] and [[63 Canonical Metrics and Run Artifact]].

## Operator safety signals

- stale committed inputs: [[21 Result Staleness Signature]];
- infeasible capacity or routes: [[49 V2 Status and Explanations]];
- low-confidence travel: [[54 Fallback and Confidence]];
- integrity failure: [[57 Route Reconstruction and Integrity]];
- unapplied manual changes: [[77 Confirmed Draft Export Guard]].

## Source anchors

- `pages/create_optimised_vehicle_routes_page.py`
- `pages/review_map_and_manually_adjust_route_assignments_page.py`

