---
title: Planner map and preview geometry
tags: [bluesg, route-optimiser, planner, map]
---

# Map and preview geometry

Parent: [[70 Route Planner Bridge]]. Coordinates: [[52 Geocode Resolution]]. Cache identity: [[53 Travel Route Cache Identity]]. Draft state: [[74 Draft History]].

## Visual layers

- white rider starts;
- green atomic pickup→drop-off movements;
- purple changed draft connectors;
- red rider-access/reposition paths;
- focus glow, start arrows, animated direction arrows.

## Reuse hierarchy

1. identical confirmed connector;
2. exact matching preview;
3. compatible cache;
4. new lookup/fallback.

Loaded movement is reusable because each job is atomic. Connectors depend on rider/order/start and may become stale.

## Signatures

Draft and leg signatures mark only affected riders. Stale previews stay hidden while unaffected rows remain.

## Safety

Missing coordinates/route failure returns an error without mutating draft or confirmed state.

