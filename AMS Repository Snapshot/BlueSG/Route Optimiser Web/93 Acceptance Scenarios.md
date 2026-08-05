---
title: Route Optimiser acceptance scenarios
tags: [bluesg, route-optimiser, acceptance]
---

# Acceptance scenarios

Behavior map: [[90 Behaviour Contract Map]]. Change paths: [[91 Change Impact Routes]].

## Minimum scenario set

1. Small complete local plan with verified/cache travel.
2. 30 jobs with enough Maximum capacity and deterministic repeat.
3. Capacity shortfall returning INFEASIBLE before [[41 Travel Matrix Construction]].
4. Area Lead home cluster plus flexible adjacent support.
5. Required-end rider who can and cannot return by deadline.
6. Cross-midnight [[30 Operation Context]].
7. Fallback-only travel with visible [[54 Fallback and Confidence]] warnings.
8. Cache cold then warm with identical context and no policy drift.
9. Duplicate plate with distinct [[13 Stable Job Identity]].
10. Export→planner upload→move/reorder→apply→export round-trip.
11. Locked-rider and dirty-draft rejection through [[73 Locks and Reshuffle Pool]] and [[77 Confirmed Draft Export Guard]].
12. Failed incremental route lookup leaving confirmed plan unchanged.

## Compare

- coverage and hard violations first;
- status and algorithm version;
- extreme/cross-zone/Area Lead exceptions;
- maximum burden and spread;
- empty, loaded, total duty, fallback legs;
- route chain and sheet/column compatibility;
- provider calls/cache hit rate/runtime;
- operator explanation and workbook usability.

## Promotion rule

Automated tests, controlled live OneMap run, and dispatch-user review must agree before removing the V1 rollback path.

