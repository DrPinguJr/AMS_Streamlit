---
title: Compatible route schema
tags: [bluesg, route-optimiser, schema, compatibility]
---

# Compatible route schema

Producer: [[49 V2 Status and Explanations]] via formatting in [[50 V1 Compatibility Surface]]. Consumers: [[57 Route Reconstruction and Integrity]], [[63 Canonical Metrics and Run Artifact]], [[64 Excel Workbook Contract]], and [[71 Planner Input Reconstruction]].

## Field families

- rider, sequence, uploaded row;
- start/empty connector;
- atomic car plate/pickup/lot/drop-off/loaded movement;
- distances/durations/route paths;
- scoring and timing/duty;
- feasibility, source, confidence, warnings;
- zone/region/audit fields.

V2 appends V2 Job ID, severity, work style, Preferred/Maximum, Area Lead match, end progress/arrival, and cache status.

## Compatibility purpose

V2 can change search internals while keeping maps, metrics, Excel, planner, and downstream Flexar workflows working.

## Risk

Column rename/removal is a multi-consumer migration, not a local refactor. Route through [[91 Change Impact Routes]].

