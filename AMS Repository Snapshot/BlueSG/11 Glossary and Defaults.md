---
title: BlueSG glossary and defaults
tags: [bluesg, glossary, defaults, constants]
---

# BlueSG glossary and defaults

Back to [[00 BlueSG Index]]. Values are code defaults at the snapshot; UI/session settings can override exposed values.

Graph entry: [[Route Optimiser Web/00 Route Optimiser Mega Web]]. Policy defaults connect to [[Route Optimiser Web/30 Operation Context]], [[Route Optimiser Web/43 Assignment Severity]], [[Route Optimiser Web/46 Beam Pruning and Timeout]], and [[Route Optimiser Web/55 Seven Zone Adjacency]].

## Active selection and timing

| Setting | Default/current |
|---|---|
| Optimizer switch | `v2` |
| Timezone | `Asia/Singapore` |
| Operation window | 14:00–17:00 |
| Cross-midnight | end moves to next day when end ≤ start |
| Pickup handling | 3 min/job |
| Drop-off handling | 3 min/job |
| Unlock wait | 0 min/job |
| Operational buffer | 20% |
| Empty mode | public transport |
| Empty duration multiplier | 1.5 |
| Empty wait buffer | 6 min |

## V2 search/policy defaults

| Constant | Value |
|---|---:|
| requested beam width | 120 |
| beam cap for >20 jobs | 60 |
| search time limit | 45 s |
| Area Lead override advantage | 12 min |
| end-requirement buffer | 10 min |
| long repositioning | 35 min |
| long-distance cross-zone | 45 min |
| operationally extreme | 75 min |

V2 objective order: unassigned, hard violations, extreme, cross-zone, Area Lead violations, fragmented clusters, maximum burden, burden spread, disliked, preferred overage, empty minutes, total duration.

## V1 compatibility/scoring defaults

| Constant | Value |
|---|---:|
| empty weight | 4.5 |
| loaded weight | 0.8 |
| soft workload | 115 min |
| workload penalty | 2.0/min |
| soft adjusted duration | 165 min |
| duration penalty | 2.0/min |
| Max Jobs overage penalty | 60 |
| duration buffer multiplier | 1.2 |
| max adjusted duration | 180 min |
| cluster pressure bonus/job | 30 |
| fallback quality penalty | 100 |
| minimum jobs/rider target | 2 |
| selective changed-rider penalty | 20 |
| selective moved-job penalty | 10 |
| selective sequence-change penalty | 5 |
| selective candidate cap | 50,000 |
| selective beam width | 100 |

V1 Max Jobs remains soft unless a hard-cap constraint is enabled.

## Regional defaults

- Adjacent pickup permitted up to 25 minutes.
- “Side by side” threshold is 15 minutes.
- Regional overflow enabled.
- Support tolerance: 15 minutes and 1.25 ratio.
- Protected-job advantage: 15 minutes.
- Approved support penalty: 5.
- Unsupported penalty: 180.
- Clustered-trip penalty: 0 when at least 3 jobs.
- Scarce-driver escape penalties: 40 small / 180 large.
- Estimated job duration for capacity: 45 minutes.

Seven normalized zones and adjacency:

| Zone | Allowed adjacency set |
|---|---|
| West | West, South-West, North-West |
| North-West | North-West, West, North |
| North | North, North-West, North-East |
| North-East | North-East, North, East, Central |
| East | East, North-East, Central |
| Central | Central, East, North-East, South-West |
| South-West | South-West, West, Central |

## Planner defaults

| Setting | Value |
|---|---:|
| undo/redo history limit | 15 |
| unassigned lane ID | `__UNASSIGNED__` |
| reshuffle pool lane ID | `__RESHUFFLE_POOL__` |

## Cache/confidence defaults

- Provider version: `onemap-v1`.
- Public transport key: weekday/weekend + 15-minute operation-start bucket.
- Other modes: all-days + timeless.
- Confidence values: verified, cached_verified, fallback, manual.

## Cloud defaults

| Setting | Value |
|---|---|
| documented Python | 3.12 |
| deployment guard | `2026.08.03.1` |
| login on Linux | required by default |
| login on Windows | optional unless configured |
| storage | temporary/shared instance filesystem |

## Glossary

**Area Lead** — V2 rider work style with primary ownership of home-zone demand and protected capacity.

**Assignment severity** — V2 ordered soft-quality category from Preferred to Operationally Extreme.

**Confirmed plan** — last successfully recalculated/validated planner result; only exportable plan.

**Draft plan** — current manual edits that may not yet have exact travel recalculation or validation.

**Empty leg** — rider travel without the relocation vehicle, from current/start/drop-off location to pickup.

**Loaded leg** — atomic driving movement from job pickup to its drop-off.

**Fallback** — low-confidence estimated route used when verified routing is unavailable.

**Hard constraint** — rule that makes a candidate infeasible; cannot be offset by score.

**Preferred Jobs** — V2 soft workload target.

**Maximum Jobs** — V2 hard rider job cap.

**Priority/Piority** — V1 load level/legacy spelling; migrates to V2 Area Lead.

**Route chain** — rider start, then each job’s drop-off becoming the next empty-leg origin.

**Stable Job ID** — identity key preserved independent of car plate, row display, rider, or sequence.

**Support/exceptional assignment** — V1 regional policy tiers for non-primary rider coverage.
