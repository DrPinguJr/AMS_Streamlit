---
title: V2 result status and explanations
tags: [bluesg, route-optimiser, v2, explainability]
---

# V2 result status and explanations

Upstream: [[40 V2 Capacity Gate]], [[45 Beam Search Expansion]], and [[47 Lexicographic Objective]]. Downstream: [[62 Compatible Route Schema]], [[61 Progress and Diagnostics]], and [[63 Canonical Metrics and Run Artifact]].

## Status

- COMPLETE: all jobs assigned without tracked soft exceptions.
- COMPLETE_WITH_EXCEPTIONS: complete/hard-feasible with severity, overage, Area Lead, or similar soft exceptions.
- INFEASIBLE: capacity shortfall or no complete hard-feasible plan. Default behaviour for every caller.
- PARTIAL: only reachable when a caller opts in with `allow_partial_assignment=True` (currently only [[94 Hourly Rolling Dispatch]]'s standby review). A job that cannot be hard-feasibly placed is skipped instead of aborting the search; `route_df` covers everything that *could* be placed, and the skipped jobs come back on `unassigned_jobs`/`infeasible_reasons`. See [[95 Standby Driver Advisor]].
- COMPLETE_WITH_FORCED_COVERAGE: only reachable with `guarantee_minimum_coverage=True` (the default for [[94 Hourly Rolling Dispatch]]'s mandatory solve, off everywhere else). Set when the post-search top-up forced a job onto a rider outside their own hard-feasibility limits (past shift-end buffer, over Max Jobs) to get every rider off zero jobs. Every override lists on `result.forced_assignments` (rider, job, donor, feasible, reasons) and marks `hard_constraint_validation.is_valid=False` in `route_df.attrs`. A rider stays uncovered only when no other rider had a spare job to redistribute.

## Per-job explanation

Records rider/job, severity, empty/loaded minutes, projected count, Preferred/Maximum, Area Lead match, end progress/arrival, selected reasons, up to three alternatives, soft exceptions, travel source, and cache status.

## Limit

Alternative rejection text summarizes that the final complete-plan objective was worse; it is not a full replay of every discarded beam branch.

## Output safety

Capacity, objective, explanations, cache metrics, algorithm identity, validation, and context are sanitized before attaching to DataFrame attributes. See [[63 Canonical Metrics and Run Artifact]].

