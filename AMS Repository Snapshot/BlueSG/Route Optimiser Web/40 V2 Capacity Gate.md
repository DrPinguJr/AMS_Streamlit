---
title: V2 capacity gate
tags: [bluesg, route-optimiser, v2, feasibility]
---

# V2 capacity gate

Gateway from [[00 Route Optimiser Mega Web]]. Inputs: committed jobs from [[14 Job Validation and Atomic Commit]] and riders from [[24 V2 Rider Validation]].

Before any route lookup, V2 computes:

- job count;
- rider count;
- total Preferred capacity;
- total Maximum capacity;
- required average;
- exact shortfall.

If Maximum capacity is below job count, V2 returns `INFEASIBLE` immediately. No [[41 Travel Matrix Construction]] or [[45 Beam Search Expansion]] occurs.

## Policy

Preferred may be exceeded to complete the plan. Maximum may never be exceeded.

## Output edges

Capacity details appear in [[49 V2 Status and Explanations]], [[61 Progress and Diagnostics]], and run attributes consumed by [[63 Canonical Metrics and Run Artifact]].

