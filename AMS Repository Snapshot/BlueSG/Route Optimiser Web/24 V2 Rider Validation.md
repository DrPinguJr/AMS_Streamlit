---
title: V2 rider validation
tags: [bluesg, route-optimiser, rider-validation]
---

# V2 rider validation

Upstream: [[23 Rider Draft Transaction]]. Downstream: [[40 V2 Capacity Gate]].

Strict validation requires:

- non-empty unique Rider Name;
- Start Location;
- recognized seven-zone Start Zone;
- Preferred as numeric whole number ≥ 0;
- Maximum as numeric whole number ≥ 1;
- Preferred ≤ Maximum;
- Work Style exactly Local, Flexible, or Area Lead;
- valid optional End Requirement;
- at least one Active rider.

Numeric-looking strings are rejected deliberately. Maximum is hard in V2; Preferred is soft.

## Produced model

Valid rows become immutable `Rider` records used by [[25 Work Styles and Area Lead]], [[26 End Requirements and Availability]], [[41 Travel Matrix Construction]], and [[44 Hard Feasibility]].

## Compatibility edge

Legacy loads normalize before strict validation through [[50 V1 Compatibility Surface]].

