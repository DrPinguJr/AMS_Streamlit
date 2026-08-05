---
title: BlueSG Optimiser V2 deep dive
tags: [bluesg, optimizer, v2, beam-search]
---

# BlueSG Optimiser V2 deep dive

Back to [[00 BlueSG Index]]. Active selection is V2.

Atomic solver web: [[Route Optimiser Web/40 V2 Capacity Gate]] → [[Route Optimiser Web/41 Travel Matrix Construction]] → [[Route Optimiser Web/45 Beam Search Expansion]] → [[Route Optimiser Web/47 Lexicographic Objective]] → [[Route Optimiser Web/49 V2 Status and Explanations]].

## Design goal

V2 is deliberately independent of the V1 scoring tower. It searches for a complete hard-feasible assignment using a precomputed travel matrix, explicit assignment severity, Area Lead ownership, rider burden balancing, and deterministic beam search.

Algorithm metadata:

- name: `severity_area_lead_beam_search`;
- version: `2.0.0-v2`;
- default requested beam width: 120;
- effective beam width is capped at 60 when there are more than 20 jobs;
- default time limit: 45 seconds.

## Rider model

Each `Rider` has:

- name, start location, normalized start zone;
- `preferred_jobs` soft workload target;
- `maximum_jobs` hard cap;
- work style: `Local`, `Flexible`, or `Area Lead`;
- optional required end location/time;
- preferred/acceptable areas derived from home and adjacency;
- optional availability interval.

Compatibility properties map `maximum_jobs` to `max_jobs` and work styles to legacy load levels (`Low`, `Medium`, `Priority`).

Strict validation rejects text values for Preferred/Maximum even if numeric-looking, non-whole/negative values, Preferred greater than Maximum, duplicate names, unknown zones/styles, malformed end requirements, missing name/start, and an empty active roster.

## Capacity precheck

Before route acquisition/search:

- total preferred and maximum slots are summed;
- maximum capacity below job count returns `INFEASIBLE` immediately;
- status explains exact capacity shortfall;
- all jobs remain unassigned in the result.

Preferred capacity may be exceeded; maximum capacity may not.

## Job model and ordering

Each `V2Job` preserves Job ID, uploaded row, original order, car plate, pickup/drop-off addresses/lots, normalized zones, and raw source fields.

Search order is deterministic:

1. jobs in zones with an Area Lead;
2. larger pickup-zone demand clusters;
3. original upload order;
4. stable Job ID.

## Travel matrix

All route I/O happens before search:

- empty origins: every rider start plus every job drop-off;
- empty destinations: every pickup plus every rider required-end location;
- loaded pairs: each job pickup to its drop-off;
- fetches run in a bounded thread pool;
- empty travel uses the configured mode and public-transport adjustment;
- loaded travel uses driving;
- cache hit/miss, OneMap request, fallback, failure, and runtime metrics are counted.

The beam search performs no network/disk provider I/O.

## Route evaluation and hard feasibility

For every proposed rider sequence, V2 rebuilds from the rider start and evaluates each job in order. Hard rejection reasons include:

- sequence exceeds Maximum Jobs;
- fixed/required rider mismatch or explicit rider exclusion;
- missing pickup/drop-off;
- missing/non-finite travel route;
- completion after operation end;
- completion after rider availability;
- inability to route to a required end destination;
- arrival at required end after the deadline plus a 10-minute buffer.

Handling and unlock waits are added to elapsed duty. The next job begins from the previous drop-off.

## Assignment severity

Ordered from best to worst:

0. `PREFERRED`
1. `ACCEPTABLE`
2. `DISLIKED`
3. `LONG_DISTANCE_CROSS_ZONE`
4. `OPERATIONALLY_EXTREME`

Global thresholds:

- long repositioning: 35 minutes;
- long-distance cross-zone: 45 minutes;
- operationally extreme: 75 minutes;
- Area Lead override advantage: 12 minutes;
- end-requirement buffer: 10 minutes.

Work style changes local/adjacent thresholds. Moving away from a required end destination escalates severity as the deadline approaches; moving materially toward it can soften a disliked assignment.

## Beam search

For each ordered job, for every retained plan:

1. consider every rider below Maximum Jobs;
2. preserve Area Lead capacity for remaining home demand;
3. insert the job at every possible sequence position;
4. fully reevaluate that rider route;
5. discard hard-infeasible candidates;
6. compute complete-plan metrics;
7. deduplicate identical route tuples;
8. keep the best beam by lexicographic objective.

If no candidate can place the current job, V2 returns `INFEASIBLE`; it does not publish a partial assignment as success. When the time deadline is reached, the beam is narrowed to its best one plan but deterministic search continues so coverage remains mandatory.

## Lexicographic objective

Earlier items dominate all later items:

1. unassigned jobs;
2. hard violations;
3. operationally extreme assignments;
4. long-distance cross-zone assignments;
5. Area Lead violations;
6. fragmented Area Lead clusters;
7. maximum rider burden;
8. burden spread;
9. disliked assignments;
10. preferred-job overage;
11. empty travel minutes;
12. total duration.

Rider burden weights long repositioning ×3, cross-zone ×10, and extreme ×25, plus disliked and preferred-overage counts. Coverage/hard feasibility cannot be traded for travel savings.

## Result states

- `COMPLETE`: all jobs assigned without tracked soft exceptions.
- `COMPLETE_WITH_EXCEPTIONS`: complete/hard-feasible but includes severity, overage, Area Lead, or related soft exceptions.
- `INFEASIBLE`: capacity shortfall or no complete hard-feasible plan.

V2 attaches capacity, objective, explanations, cache metrics, algorithm identity, hard-validation summary, and operation context to compatible route DataFrame attributes.

## Assignment explanations

For each assigned job, V2 records selected rider/job, severity, travel minutes, projected count vs targets, Area Lead match, end progress/arrival, reasons, up to three alternative riders, soft exceptions, travel source, and cache status.

Alternative explanations are comparative summaries, not a replayable proof of every beam-search branch; their rejection reason is that the final complete-plan lexicographic objective was worse.

## Key modification traps

- Reordering the objective changes policy even if totals look better.
- Lowering beam width or changing job ordering can change deterministic outcomes.
- Treating Preferred as hard contradicts current V2 behavior; treating Maximum as soft is unsafe.
- Network lookup inside search destroys determinism/performance.
- A partial route DataFrame must never be labeled COMPLETE.
- Changing compatibility columns affects planner/export even when the V2 model still passes unit tests.
