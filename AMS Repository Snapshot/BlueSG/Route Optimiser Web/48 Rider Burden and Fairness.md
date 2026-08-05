---
title: V2 rider burden and fairness
tags: [bluesg, route-optimiser, v2, fairness]
---

# Rider burden and fairness

Inputs: assignment categories from [[43 Assignment Severity]] and workload targets from [[24 V2 Rider Validation]]. Consumer: [[47 Lexicographic Objective]].

Per-rider burden score includes:

- disliked assignments;
- Preferred overage;
- long repositioning ×3;
- long-distance cross-zone ×10;
- operationally extreme ×25.

Empty travel minutes are tracked separately.

## Plan fairness

The objective minimizes maximum rider burden before burden spread, then total disliked/overage and travel. This protects one rider from becoming a repeated sacrifice.

## Distinctions

- Preferred overage is allowed.
- Maximum overage is hard infeasible through [[44 Hard Feasibility]].
- duty-time fairness in canonical reports is calculated separately by [[63 Canonical Metrics and Run Artifact]].

## Test edge

Repeated-sacrifice and preferred-overage scenarios are in [[90 Behaviour Contract Map]].

