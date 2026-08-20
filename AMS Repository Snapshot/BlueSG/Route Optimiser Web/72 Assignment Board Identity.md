---
title: Planner assignment board identity
tags: [bluesg, route-optimiser, planner, identity]
---

# Assignment board identity

Upstream: [[71 Planner Input Reconstruction]] and [[13 Stable Job Identity]]. Consumers: [[73 Locks and Reshuffle Pool]], [[74 Draft History]], [[76 Incremental Recalculation]], and [[94 Hourly Rolling Dispatch]]'s review popup.

The rendering side (`build_sortable_board`, `render_route_assignment_board`, plus their `assignment_signature`/`short_location`/`lane_duration` helpers) lives in its own module, `route_assignment_board_rendering.py`, so both the full Route Planner page and the hourly page's popup can render the same component against this same identity model without duplicating the label-encoding logic. The hourly popup renders it with no locked riders and no reshuffle pool - it only ever seeds the board from that hour's newly-solved jobs, so there is nothing to lock.

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

