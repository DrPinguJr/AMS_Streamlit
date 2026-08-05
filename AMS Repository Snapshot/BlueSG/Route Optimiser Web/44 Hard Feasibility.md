---
title: V2 hard feasibility
tags: [bluesg, route-optimiser, v2, hard-constraints]
---

# V2 hard feasibility

Inputs: [[24 V2 Rider Validation]], [[26 End Requirements and Availability]], [[30 Operation Context]], and [[41 Travel Matrix Construction]]. Called from [[45 Beam Search Expansion]].

A candidate route is rejected for:

- Maximum Jobs exceeded;
- fixed/required rider mismatch;
- explicit rider exclusion;
- missing pickup/drop-off;
- non-finite/missing travel cost;
- completion after operation end;
- completion after rider availability;
- missing required-end route;
- required-end arrival after deadline/buffer.

## Atomic evaluation

Each candidate sequence is rebuilt from rider start through every job. The previous drop-off becomes the next origin; see [[31 Duty Time Composition]].

## Priority rule

Hard feasibility dominates every item in [[47 Lexicographic Objective]]. A lower-travel plan cannot compensate for a violation.

## Integrity edge

Post-search/export/planner coverage is separately checked by [[57 Route Reconstruction and Integrity]].

