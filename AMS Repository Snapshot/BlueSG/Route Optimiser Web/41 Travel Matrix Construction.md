---
title: V2 travel matrix construction
tags: [bluesg, route-optimiser, v2, travel]
---

# Travel matrix construction

Upstream: [[40 V2 Capacity Gate]], [[30 Operation Context]], and provider nodes [[51 OneMap Credential and Token Flow]] through [[54 Fallback and Confidence]].

## Pair sets

- empty origins: every rider start plus every job drop-off;
- empty destinations: every pickup plus required-end location;
- loaded pairs: each pickup→drop-off.

Calls run concurrently with a bounded worker pool. Empty costs receive configured public-transport adjustment; loaded costs use driving.

## Metrics

Cache hits/misses, live OneMap requests, fallback routes, failed routes, and matrix runtime feed [[61 Progress and Diagnostics]].

## Search boundary

The complete matrix is built before [[45 Beam Search Expansion]]. Search performs no provider I/O.

## Complexity

Empty pairs scale with `(rider starts + job drop-offs) × (job pickups + end locations)`. See [[04 Complexity Hotspots]].

