---
title: Planner incremental recalculation
tags: [bluesg, route-optimiser, planner, recalculation]
---

# Incremental recalculation

Parent: [[70 Route Planner Bridge]]. Inputs: [[72 Assignment Board Identity]], [[73 Locks and Reshuffle Pool]], and [[75 Map and Preview Geometry]].

## Apply pipeline

1. normalize/validate assignment;
2. enforce locked baselines;
3. detect affected riders/changed legs;
4. derive sequences;
5. reuse confirmed loaded legs and matching previews/cache;
6. recalculate affected rider routes only;
7. merge untouched confirmed routes;
8. run [[57 Route Reconstruction and Integrity]];
9. atomically commit or return failure.

## Provider edge

Changed uncached connectors use [[50 V1 Compatibility Surface]] and [[53 Travel Route Cache Identity]]. Exact previews can avoid new OneMap calls.

## Failure rule

Confirmed routes remain untouched and draft remains correctable. Final transaction is [[77 Confirmed Draft Export Guard]].

