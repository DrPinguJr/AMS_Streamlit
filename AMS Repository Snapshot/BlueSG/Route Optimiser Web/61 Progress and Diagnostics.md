---
title: Optimiser progress and diagnostics
tags: [bluesg, route-optimiser, observability]
---

# Progress and diagnostics

UI owner: [[60 Optimiser Page Orchestrator]]. Producers: [[41 Travel Matrix Construction]], [[45 Beam Search Expansion]], and [[49 V2 Status and Explanations]].

Progress events carry phase, status text, completion fraction, assigned/remaining jobs, comparison counts, matrix counts, cache metrics, retained plans, and current job/location details.

## Visible phases

- capacity check;
- travel matrix;
- complete-plan search;
- finished/infeasible.

The terminal/history explains the batch position, rider route position, roster start versus previous drop-off, and exact `Start From` address.

## Diagnostics payload

Session result records checks, estimates, elapsed time, V2 runtime, capacity, cache metrics, objective, explanations, warnings, and integrity.

## Safety

Diagnostic values are sanitized/Arrow-safe. Secrets from [[51 OneMap Credential and Token Flow]] must never enter events.

## Test edge

Progress detail, throttling, completion, and human-readable start chaining are protected by [[90 Behaviour Contract Map]].

