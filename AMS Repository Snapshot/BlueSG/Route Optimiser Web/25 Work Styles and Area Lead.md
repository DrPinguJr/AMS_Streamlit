---
title: Rider work styles and Area Lead
tags: [bluesg, route-optimiser, policy]
---

# Work styles and Area Lead

Upstream: [[24 V2 Rider Validation]]. Policy consumers: [[43 Assignment Severity]], [[42 V2 Job Ordering]], and [[47 Lexicographic Objective]].

## Styles

- Local: strongly prefers current/home-zone work.
- Flexible: accepts a wider adjacent-zone envelope.
- Area Lead: owns home-zone demand and protects capacity for it.

Each rider derives preferred areas from home and acceptable areas from [[55 Seven Zone Adjacency]].

## Area Lead mechanisms

- lead-zone jobs sort early in [[42 V2 Job Ordering]];
- `_preserve_area_lead_capacity` blocks non-home use when remaining home demand needs the slots;
- plan metrics count Area Lead ownership violations and fragmented lead clusters;
- a 12-minute advantage threshold controls tested override behavior.

## Compatibility mapping

Local/Flexible/Area Lead map to legacy Low/Medium/Priority. `Piority` also migrates to Area Lead through [[50 V1 Compatibility Surface]].

