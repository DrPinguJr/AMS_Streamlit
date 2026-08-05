---
title: Job normalisation
tags: [bluesg, route-optimiser, canonical-data]
---

# Job normalisation

Upstream: [[11 Header and Alias Mapping]]. Downstream: [[13 Stable Job Identity]] and [[14 Job Validation and Atomic Commit]].

Canonical staged columns are Job ID, Car Plate, Pickup/Drop-off Address and Lot, Created At, Deadline, Status, Source, and `_original_order`.

Normalisation:

- cleans whitespace/null-like cells;
- resolves aliases into one canonical column;
- preserves original order;
- retains source metadata needed for review;
- creates consistent DataFrames across upload types.

V2 later converts rows into `V2Job` with uploaded row, original order, normalized pickup/drop-off zones, and raw fields. See [[42 V2 Job Ordering]].

## Invariant

Normalisation may standardize representation but must not merge distinct jobs solely because their plate/address matches.

## Connections

[[03 Data Lineage]] · [[62 Compatible Route Schema]] · [[90 Behaviour Contract Map]]

