---
title: V2 beam pruning and timeout
tags: [bluesg, route-optimiser, v2, performance]
---

# V2 beam pruning and timeout

Upstream: [[45 Beam Search Expansion]]. Ranking: [[47 Lexicographic Objective]].

Candidate plans are sorted by objective and deduplicated by the complete tuple of rider routes.

## Width

- requested/default page width: 120;
- when jobs > 20, effective width is capped at 60;
- otherwise requested width applies.

## Timeout semantics

The default search deadline is 45 seconds. After the deadline, the beam narrows to its best retained plan, but deterministic placement continues. Timeout does not authorize partial coverage.

## Implications

- width/time changes can change results;
- job ordering from [[42 V2 Job Ordering]] matters more with narrower beams;
- matrix time is separate from the search deadline;
- status still follows [[49 V2 Status and Explanations]].

## Change test

Benchmark quality, determinism, runtime, and full coverage together using [[93 Acceptance Scenarios]].

