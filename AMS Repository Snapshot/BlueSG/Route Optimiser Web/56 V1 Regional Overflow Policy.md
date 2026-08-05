---
title: V1 regional overflow policy
tags: [bluesg, route-optimiser, v1, regional-policy]
---

# V1 regional overflow policy

Parent: [[50 V1 Compatibility Surface]]. Geography: [[55 Seven Zone Adjacency]].

The regional module owns subregion demand/capacity, primary/support/exceptional tiers, directional support, East affinity, scarce-rider protection, and per-job audit fields.

## V1 integration points

- greedy assignment;
- rescue insertion;
- minimum-workload rebalance;
- [[58 Optional Local Improvement]].

## Important distinction

Active V2 does not use the complete regional-penalty engine. It reuses zone normalization/adjacency and implements its own [[25 Work Styles and Area Lead]] plus [[43 Assignment Severity]].

## Output

Regional Capacity and Regional Assignment Audit sheets live in [[64 Excel Workbook Contract]].

## Test edge

Scarcity, North→North-West, Central→South-West, East boundary, cluster, rescue, and 30-job regression behavior are in [[90 Behaviour Contract Map]].

