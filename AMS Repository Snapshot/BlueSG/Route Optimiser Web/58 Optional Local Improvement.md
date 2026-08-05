---
title: Optional V1 local improvement
tags: [bluesg, route-optimiser, v1, local-search]
---

# Optional V1 local improvement

Parent: [[50 V1 Compatibility Surface]]. Validation: [[57 Route Reconstruction and Integrity]] and V1 hard-constraint validator.

Candidate moves:

- reinsertion;
- adjacent swap;
- inter-rider relocation;
- one-for-one rider swap.

Every candidate is copied, reevaluated, constrained, and audited. Coverage and hard feasibility dominate duty/travel/quality.

## Active-selection rule

[[60 Optimiser Page Orchestrator]] runs this only when optimizer version is not V2. It remains for V1 rollback/benchmark.

## Promotion history

The changelog records a non-promoted benchmark: coverage and zero hard violations held, but empty travel worsened. This illustrates why [[47 Lexicographic Objective]] and acceptance metrics must be explicit.

## Outputs

Move audit feeds [[63 Canonical Metrics and Run Artifact]] and Local Search Audit in [[64 Excel Workbook Contract]].

