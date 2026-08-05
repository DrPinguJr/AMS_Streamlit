---
title: V2 lexicographic objective
tags: [bluesg, route-optimiser, v2, objective]
---

# V2 lexicographic objective

Consumes [[43 Assignment Severity]], [[48 Rider Burden and Fairness]], and Area Lead metrics from [[25 Work Styles and Area Lead]]. Used by [[46 Beam Pruning and Timeout]].

Earlier items dominate all later items:

1. unassigned jobs;
2. hard violations;
3. extreme assignments;
4. cross-zone assignments;
5. Area Lead violations;
6. fragmented lead clusters;
7. maximum rider burden;
8. burden spread;
9. disliked assignments;
10. preferred overage;
11. empty minutes;
12. total duration.

## Meaning

One fewer extreme assignment is preferred even if it costs more empty minutes. Coverage and feasibility are absolute priorities.

## Distinction

This internal V2 tuple is not the canonical before/after objective in [[63 Canonical Metrics and Run Artifact]]. Label both explicitly in analysis.

## Change risk

Reordering tuple fields is a business-policy change requiring [[90 Behaviour Contract Map]] and [[93 Acceptance Scenarios]].

