---
title: Canonical metrics and run artifact
tags: [bluesg, route-optimiser, metrics, audit]
---

# Canonical metrics and run artifact

Inputs: [[62 Compatible Route Schema]], [[30 Operation Context]], integrity from [[57 Route Reconstruction and Integrity]], and V2 identity from [[49 V2 Status and Explanations]].

`OptimisationRunResult` stores run/time, algorithm name/version, input name/hash/date, settings, assigned/unassigned rows, rider metrics, warnings, move audit, validation, and summary.

## Metrics

Coverage, riders used, first positioning, empty/loaded/route/duty/adjusted time, duty spread/variance, fallback legs, hard violations, overage, zone jumps, regional exceptions, wall time, local-search moves, manual-review count.

## Artifact

Saved as `runs/YYYY-MM-DD/HHMMSS_<algorithm>_run_summary.json` with recursive sanitization and `allow_nan=False`.

## Objective distinction

Canonical before/after objective is not [[47 Lexicographic Objective]]. Both prioritize coverage/violations, but remaining fields differ.

## Security

Never include tokens, credentials, or raw secret configuration from [[51 OneMap Credential and Token Flow]].

