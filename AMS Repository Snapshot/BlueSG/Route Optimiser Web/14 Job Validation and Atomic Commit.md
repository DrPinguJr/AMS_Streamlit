---
title: Job validation and atomic commit
tags: [bluesg, route-optimiser, validation, state]
---

# Job validation and atomic commit

Upstream: [[12 Job Normalisation]] and [[13 Stable Job Identity]]. State owner: [[20 Workflow State Machine]].

`validate_staged_jobs` returns a validation object with normalized data, errors, and warnings. `validate_and_commit_job_import` always updates the draft view but replaces committed jobs only when validation succeeds.

## Validity rules

- required route fields are present;
- pickup/drop-off text is usable;
- IDs remain complete;
- duplicate plates are warnings when IDs differ, not automatic deletion.

## Transaction rule

An invalid new upload must never erase a previously valid committed job set. A valid changed commit triggers [[21 Result Staleness Signature]].

## Downstream

Committed jobs feed [[40 V2 Capacity Gate]] and [[03 Data Lineage]]. The original file name/hash later enter [[63 Canonical Metrics and Run Artifact]].

## Test edge

Atomic replacement behavior is protected in [[90 Behaviour Contract Map]].

