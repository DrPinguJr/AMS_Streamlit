---
title: Route Planner bridge
tags: [bluesg, route-optimiser, planner, graph-gateway]
---

# Route Planner bridge

Gateway from [[00 Route Optimiser Mega Web]]. Upstream optimizer outputs: [[62 Compatible Route Schema]] and [[64 Excel Workbook Contract]].

The planner is a second Streamlit page that safely changes assignments without rerunning the complete V2 solver.

## Planner web

- load/reconstruct → [[71 Planner Input Reconstruction]];
- exact jobs/cards → [[72 Assignment Board Identity]];
- permissions/pool → [[73 Locks and Reshuffle Pool]];
- undo/redo/reset → [[74 Draft History]];
- map/connectors → [[75 Map and Preview Geometry]];
- apply changed riders → [[76 Incremental Recalculation]];
- safe commit/export → [[77 Confirmed Draft Export Guard]].

## Shared dependencies

Planner uses provider/cache from [[50 V1 Compatibility Surface]], identity from [[13 Stable Job Identity]], context from [[30 Operation Context]], and integrity from [[57 Route Reconstruction and Integrity]].

## Core transaction

Confirmed routes remain the exportable truth until a draft applies and validates successfully.

