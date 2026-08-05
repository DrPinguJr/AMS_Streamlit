---
title: V2 job ordering
tags: [bluesg, route-optimiser, v2, determinism]
---

# V2 job ordering

Inputs: [[13 Stable Job Identity]], [[25 Work Styles and Area Lead]], and normalized zones from [[55 Seven Zone Adjacency]]. Downstream: [[45 Beam Search Expansion]].

Jobs sort by:

1. pickup zone has an Area Lead;
2. larger demand cluster first;
3. original upload order;
4. stable Job ID.

## Why ordering matters

Beam search is bounded. Early jobs shape retained plans, so ordering is policy, not presentation. Lead work is protected before flexible spillover consumes capacity.

## Determinism

Original order and Job ID provide stable tie breaks. Changing order can change assignments even when [[47 Lexicographic Objective]] is unchanged.

## Test edge

Deterministic and Area Lead cluster scenarios belong to [[90 Behaviour Contract Map]] and [[93 Acceptance Scenarios]].

