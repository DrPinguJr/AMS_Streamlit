---
title: V2 beam search expansion
tags: [bluesg, route-optimiser, v2, beam-search]
---

# V2 beam search expansion

Upstream: [[42 V2 Job Ordering]], [[41 Travel Matrix Construction]], and [[44 Hard Feasibility]]. Downstream: [[46 Beam Pruning and Timeout]].

For each ordered job and retained plan:

1. visit every rider below Maximum;
2. preserve Area Lead home capacity from [[25 Work Styles and Area Lead]];
3. insert at every route position;
4. fully reevaluate that rider sequence;
5. discard hard-infeasible candidates;
6. compute plan metrics and objective.

## State representation

A plan stores immutable rider route tuples, route evaluations, and plan metrics. Only the modified rider route is reevaluated for that candidate, while metrics describe the whole plan.

## Failure behavior

If no candidate can place the current job, V2 returns `INFEASIBLE`; it does not label a partial plan successful. See [[49 V2 Status and Explanations]].

## Complexity edge

Candidate count depends on jobs × retained plans × riders × insertion positions. See [[04 Complexity Hotspots]].

