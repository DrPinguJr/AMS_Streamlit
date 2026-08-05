---
title: Planner draft history
tags: [bluesg, route-optimiser, planner, state]
---

# Draft history

Parent: [[70 Route Planner Bridge]]. Inputs: changes from [[72 Assignment Board Identity]] and [[73 Locks and Reshuffle Pool]].

State contains current draft, undo stack, redo stack, original assignment, confirmed assignment, and board revision. Default history limit is 15.

## Transitions

- new change: push prior draft to undo, clear redo;
- undo: move current to redo and restore prior;
- redo: inverse transition;
- reset: return to original loaded assignment;
- new workbook/session: clear stale stacks/previews.

## State separation

History changes draft only. Confirmed routes change only through [[76 Incremental Recalculation]] and [[77 Confirmed Draft Export Guard]].

## Map edge

Undo/redo/reset invalidates affected preview signatures in [[75 Map and Preview Geometry]].

