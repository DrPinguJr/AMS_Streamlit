---
title: Planner assignment board identity
tags: [bluesg, route-optimiser, planner, identity]
---

# Assignment board identity

Upstream: [[71 Planner Input Reconstruction]] and [[13 Stable Job Identity]]. Consumers: [[73 Locks and Reshuffle Pool]], [[74 Draft History]], and [[76 Incremental Recalculation]].

The HTML component displays lanes/cards, but Python maps exact lane IDs and card IDs. Business labels are never parsed to infer identity.

## Validation

- every known Job ID exactly once;
- no unknown/duplicate/missing job;
- valid rider or special lane;
- numeric deterministic sequences.

Special lanes:

- `__UNASSIGNED__`;
- `__RESHUFFLE_POOL__`.

## Boundary

Card title can show plate/location for humans; Job ID remains the data key.

## Test edge

Exact mapping and malformed-board behavior are in [[90 Behaviour Contract Map]].

