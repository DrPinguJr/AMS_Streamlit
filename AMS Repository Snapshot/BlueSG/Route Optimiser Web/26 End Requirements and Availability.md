---
title: Rider end requirements and availability
tags: [bluesg, route-optimiser, time-constraints]
---

# End requirements and availability

Upstream: [[24 V2 Rider Validation]] and [[30 Operation Context]]. Consumers: [[41 Travel Matrix Construction]], [[43 Assignment Severity]], and [[44 Hard Feasibility]].

An end requirement contains location text and a required-by datetime. V2 also supports optional available-from and available-until on the rider model.

## Search behavior

- the matrix precomputes routes from starts/drop-offs to required-end locations;
- severity worsens when a job moves away from the end destination near deadline;
- moving materially toward the end can soften a disliked assignment;
- final evaluation adds return travel plus a 10-minute buffer;
- missing return route or late arrival is hard infeasible.

## Distinction

Direction/progress is soft during construction; the final ability to reach the required destination by deadline is hard.

## Tests

Protected by required-end parsing, return-before-four, zero-minute route, and end-direction scenarios in [[90 Behaviour Contract Map]].

