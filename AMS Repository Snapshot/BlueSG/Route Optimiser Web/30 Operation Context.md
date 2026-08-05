---
title: Operation context
tags: [bluesg, route-optimiser, time]
---

# Operation context

Gateway from [[00 Route Optimiser Mega Web]]. Created by [[60 Optimiser Page Orchestrator]].

`OperationContext` is the immutable temporal/travel-mode contract shared by provider, V1, V2, metrics, and planner recalculation.

## Fields

- Asia/Singapore timezone;
- operation start/end;
- empty travel mode;
- pickup/drop-off handling;
- unlock wait;
- operational buffer percentage.

Default window is 14:00–17:00. End ≤ start rolls into the next day. Negative handling/wait/buffer is rejected.

## Edges

- cache context → [[53 Travel Route Cache Identity]];
- elapsed duty → [[31 Duty Time Composition]];
- availability/end checks → [[26 End Requirements and Availability]];
- solver feasibility → [[44 Hard Feasibility]];
- run metadata → [[63 Canonical Metrics and Run Artifact]].

