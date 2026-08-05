---
title: V1 compatibility surface
tags: [bluesg, route-optimiser, v1, compatibility]
---

# V1 compatibility surface

Gateway from [[00 Route Optimiser Mega Web]] and dependency edge from [[02 Runtime Dependency Spine]].

`build_optimised_vehicle_routes.py` is both the rollback V1 solver and active shared infrastructure.

## Active V2 imports

- `TravelCost` and provider calls → [[51 OneMap Credential and Token Flow]], [[53 Travel Route Cache Identity]];
- zone inference → [[55 Seven Zone Adjacency]];
- route/summary formatting → [[62 Compatible Route Schema]].

## Other retained consumers

- job/roster compatibility → [[11 Header and Alias Mapping]], [[22 Daily Roster Sources]];
- reconstruction/integrity → [[57 Route Reconstruction and Integrity]];
- Excel writer → [[64 Excel Workbook Contract]];
- planner apply → [[76 Incremental Recalculation]].

## Retirement rule

Extract provider, schemas, reconstruction, and export behind stable modules before deleting V1 scoring/rescue/rebalance code. See [[91 Change Impact Routes]].

