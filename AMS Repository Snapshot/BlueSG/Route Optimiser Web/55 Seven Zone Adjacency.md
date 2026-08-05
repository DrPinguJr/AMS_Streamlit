---
title: Seven-zone adjacency policy
tags: [bluesg, route-optimiser, geography]
---

# Seven-zone adjacency policy

Shared by V2 and [[56 V1 Regional Overflow Policy]]. Inputs address/zone text; consumers include [[25 Work Styles and Area Lead]] and [[43 Assignment Severity]].

Normalized zones: West, North-West, North, North-East, East, Central, South-West.

Adjacency graph:

- West ↔ South-West, North-West;
- North-West ↔ West, North;
- North ↔ North-West, North-East;
- North-East ↔ North, East, Central;
- East ↔ North-East, Central;
- Central ↔ East, North-East, South-West;
- South-West ↔ West, Central.

Same-zone/adjacent assessment also uses 15-minute side-by-side and 25-minute permitted-adjacent thresholds in V1 policy.

## Risk

Zone normalization changes affect job ordering, severity, Area Lead ownership, regional audits, and test fixtures simultaneously. Use [[91 Change Impact Routes]].

