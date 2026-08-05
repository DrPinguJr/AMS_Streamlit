---
title: Planner locks and reshuffle pool
tags: [bluesg, route-optimiser, planner, safety]
---

# Locks and reshuffle pool

Identity: [[72 Assignment Board Identity]]. History: [[74 Draft History]]. Apply: [[76 Incremental Recalculation]].

## Locks

- riders begin locked;
- lock normalization captures a baseline sequence;
- locked sequence is strictly immutable;
- stale rider IDs are removed safely.

## Pool

- selected jobs enter `__RESHUFFLE_POOL__`;
- pooled jobs remain frozen until explicit pool action/move-back;
- reshuffle operates only in unlocked/allowed scope;
- assignment integrity must remain exact.

## Audit behavior

Manual move history preserves the first origin for each moved job. Lock violations reject the candidate before recalculation.

## Risk

A reshuffle implementation can indirectly alter a locked rider even if drag/drop UI is disabled. Validate baseline sequences, not just UI controls.

