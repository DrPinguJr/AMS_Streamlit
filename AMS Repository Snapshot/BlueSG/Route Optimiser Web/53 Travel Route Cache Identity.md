---
title: Travel route cache identity
tags: [bluesg, route-optimiser, cache]
---

# Travel route cache identity

Inputs: [[30 Operation Context]] and provider calls from [[50 V1 Compatibility Surface]]. Consumers: [[41 Travel Matrix Construction]] and [[76 Incremental Recalculation]].

Key tuple:

```text
normalized origin, normalized destination, mode,
service day, time bucket, provider version
```

Public transport uses weekday/weekend plus a 15-minute operation-start bucket. Other modes currently use all-days/timeless. Provider version is `onemap-v1`.

## Disk files

- runtime route CSV;
- runtime geocode CSV from [[52 Geocode Resolution]];
- tracked verified geocode seed.

## Invariant

Never reuse public transport across incompatible time/day/mode. Bump provider version or migrate/clear cache when response semantics change.

## Planner edge

Exact origin/destination/context matching determines safe connector reuse in [[75 Map and Preview Geometry]].

