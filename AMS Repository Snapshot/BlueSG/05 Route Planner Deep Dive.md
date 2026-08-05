---
title: BlueSG Route Planner deep dive
tags: [bluesg, planner, manual-editing, state]
---

# BlueSG Route Planner deep dive

Back to [[00 BlueSG Index]].

Atomic planner web: [[Route Optimiser Web/70 Route Planner Bridge]] → [[Route Optimiser Web/72 Assignment Board Identity]] → [[Route Optimiser Web/75 Map and Preview Geometry]] → [[Route Optimiser Web/76 Incremental Recalculation]] → [[Route Optimiser Web/77 Confirmed Draft Export Guard]].

## Input paths

The planner loads either:

- the latest optimizer result from the current Streamlit session; or
- an exported workbook upload.

Workbook import prefers `Optimised Routes`, reconstructs stable Job IDs, jobs, riders, starts, summary, and assignment order, and accepts compatibility route sheets where supported.

## Confirmed versus draft model

The most important safety boundary is:

- **confirmed assignment/routes**: last successfully calculated, validated, exportable plan;
- **draft assignment**: current drag/drop/reorder/pool edits;
- **dirty state**: draft differs from confirmed; export is blocked;
- **original assignment**: reset target for the loaded workbook/session.

A failed apply never mutates confirmed routes. The draft remains available for correction.

## Assignment board

The custom component displays rider lanes plus special lanes:

- `__UNASSIGNED__`;
- `__RESHUFFLE_POOL__`.

The Python boundary maps exact lane/card identifiers back to riders/jobs. It does not parse business labels to infer identity. Normalization rejects duplicates and malformed lanes.

Assignment validation requires:

- every known job appears exactly once;
- no unknown job appears;
- only known riders/special lanes are used;
- sequences are complete and deterministic.

## Locking and pool behavior

- Riders begin locked.
- Locked rider sequences are immutable, backed by captured baselines.
- Stale rider IDs are removed when lock state is normalized.
- Pool-selected jobs are frozen until the user runs the pool reshuffle action or moves them back.
- Reshuffle operates only within permitted/unlocked scope and must preserve assignment integrity.
- Manual move history preserves each job’s first origin for audit/penalty behavior.

## History

Draft changes use separate undo and redo stacks with a default limit of 15. New changes clear redo. Reset returns to the original assignment. A new workbook/session payload clears stale history and preview state.

## Map semantics

Planner visualization distinguishes:

- white rider start markers;
- green loaded car movements for the draft job order;
- purple draft connectors for changed between-job/start-to-pickup legs;
- red rider-access/reposition paths where shown.

Focus mode supports rider visibility/highlighting, route glow, start arrows, and animated direction arrows. Visibility controls must not mutate the draft.

Green geometry can reuse confirmed loaded routes because a job’s pickup-to-drop-off movement is atomic. Connector geometry changes when order/rider/start changes.

## Preview invalidation and reuse

The planner builds signatures for route legs and draft assignments. A change marks only affected riders/stale preview rows. It reuses, in order:

1. identical confirmed connector;
2. matching previously previewed connector;
3. compatible route cache;
4. a new lookup/fallback.

Unchanged loaded legs and connectors should not trigger OneMap. Missing coordinates or route lookup failure returns a safe error without mutating assignment.

## Apply and recalculate

`incremental_recalculate` follows this transaction:

1. normalize and validate the assignment;
2. enforce locked-rider baselines;
3. detect affected riders and changed legs;
4. derive rider sequences;
5. reuse confirmed loaded legs and compatible previews/cache;
6. recalculate affected rider routes only;
7. combine them with untouched confirmed routes;
8. run job-set, duplicate, hard-constraint, and route-chain checks;
9. atomically commit on success;
10. retain confirmed and draft states separately on failure.

## Important session-state families

- source/load: `bluesg_map_viewer_file_signature`, selected rider/sequence;
- core: `route_planner_confirmed_assignment`, `route_planner_confirmed_routes`, `route_planner_draft_assignment`, `route_planner_original_assignment`, `route_planner_is_dirty`;
- safety: locked IDs/baselines, affected riders, manual move history;
- history: undo/redo stacks, board revision;
- preview: connectors, preview routes/signature/stale riders/stats/error, access cache;
- focus/UI: focus mode, highlighted/visible riders, map focus, notices;
- pool: reshuffle pool job IDs/request/notice.

## Change traps

- Exporting draft rows before successful apply.
- Recalculating every rider on any edit, causing unnecessary network calls and latency.
- Identifying jobs by plate/label rather than stable ID.
- Allowing a locked rider’s order to change indirectly through a pool/reshuffle.
- Mutating confirmed state before validation finishes.
- Reusing a connector with a mismatched origin/destination or time/mode context.
- Changing component IDs without updating exact Python mappings and layout tests.
