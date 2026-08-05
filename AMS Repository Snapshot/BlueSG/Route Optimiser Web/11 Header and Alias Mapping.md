---
title: Job header and alias mapping
tags: [bluesg, route-optimiser, input-schema]
---

# Header and alias mapping

Upstream: [[10 Job Source Detection]]. Downstream: [[12 Job Normalisation]].

Excel import scans leading rows for a recognizable header rather than assuming row 1. Alias mapping supports historic Flexar/supplier names and duplicate “Lots Number” positions.

## Required meaning

- car plate;
- pickup address;
- pickup lot where available;
- drop-off address;
- optional source/date/deadline/status fields.

The staging path requires car plate, pickup, and drop-off for routing. The compatibility parser retains its older required-header contract, which includes Pickup Lot. See [[50 V1 Compatibility Surface]].

## Risk

Adding an alias in only one parser can make V2 UI imports differ from planner/rollback/benchmark behavior. Route changes through [[91 Change Impact Routes]].

## Test edges

Protected by old Flexar header, extra title row, duplicate lot-header, CSV, HTML, and tab-paste scenarios in [[90 Behaviour Contract Map]].

