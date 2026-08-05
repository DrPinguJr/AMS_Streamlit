---
title: V2 result status and explanations
tags: [bluesg, route-optimiser, v2, explainability]
---

# V2 result status and explanations

Upstream: [[40 V2 Capacity Gate]], [[45 Beam Search Expansion]], and [[47 Lexicographic Objective]]. Downstream: [[62 Compatible Route Schema]], [[61 Progress and Diagnostics]], and [[63 Canonical Metrics and Run Artifact]].

## Status

- COMPLETE: all jobs assigned without tracked soft exceptions.
- COMPLETE_WITH_EXCEPTIONS: complete/hard-feasible with severity, overage, Area Lead, or similar soft exceptions.
- INFEASIBLE: capacity shortfall or no complete hard-feasible plan.

## Per-job explanation

Records rider/job, severity, empty/loaded minutes, projected count, Preferred/Maximum, Area Lead match, end progress/arrival, selected reasons, up to three alternatives, soft exceptions, travel source, and cache status.

## Limit

Alternative rejection text summarizes that the final complete-plan objective was worse; it is not a full replay of every discarded beam branch.

## Output safety

Capacity, objective, explanations, cache metrics, algorithm identity, validation, and context are sanitized before attaching to DataFrame attributes. See [[63 Canonical Metrics and Run Artifact]].

