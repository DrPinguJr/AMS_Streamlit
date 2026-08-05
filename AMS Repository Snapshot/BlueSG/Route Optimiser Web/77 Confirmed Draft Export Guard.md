---
title: Confirmed versus draft export guard
tags: [bluesg, route-optimiser, planner, transaction]
---

# Confirmed versus draft export guard

Parent: [[70 Route Planner Bridge]]. Apply source: [[76 Incremental Recalculation]]. Export destination: [[64 Excel Workbook Contract]].

## States

- confirmed assignment/routes: last successful safe plan;
- draft assignment: current edits;
- dirty: draft differs from confirmed;
- original: reset target.

## Rules

- dirty draft disables export;
- successful apply atomically replaces confirmed data and clears dirty state;
- failed apply changes neither confirmed routes nor export payload;
- draft remains available after failure;
- export uses confirmed routes only.

## Why this node matters

It prevents visually plausible but unrecalculated/unvalidated manual changes from becoming dispatch instructions.

## Test edge

Dirty guard, failed atomicity, applied workbook content, and focus state transitions are protected by [[90 Behaviour Contract Map]].

