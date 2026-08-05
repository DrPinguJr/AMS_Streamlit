---
title: Planner input reconstruction
tags: [bluesg, route-optimiser, planner, import]
---

# Planner input reconstruction

Parent: [[70 Route Planner Bridge]]. Inputs: latest session result from [[20 Workflow State Machine]] or workbook from [[64 Excel Workbook Contract]].

Workbook load prefers `Optimised Routes` and can fall back to compatible route sheets. It reconstructs:

- route rows and sequence;
- stable Job IDs from [[13 Stable Job Identity]];
- jobs DataFrame;
- rider names/starts/capacity hints;
- summary;
- assignment lanes.

## Source signature

Workbook/file bytes and route content generate signatures so a new source resets stale [[74 Draft History]] and preview state.

## Risk

If export schema changes without this importer, the optimizer succeeds but the planner becomes unusable. Connect changes through [[91 Change Impact Routes]].

