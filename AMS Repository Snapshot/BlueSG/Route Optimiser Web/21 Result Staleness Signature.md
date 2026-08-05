---
title: Optimiser result staleness signature
tags: [bluesg, route-optimiser, state-integrity]
---

# Result staleness signature

Parent state: [[20 Workflow State Machine]]. Inputs: [[14 Job Validation and Atomic Commit]] and [[23 Rider Draft Transaction]].

`dataframe_signature` canonicalizes columns, converts values to strings, fills nulls, serializes sorted records, and hashes them. `committed_input_signature` hashes job and normalized-rider signatures together.

## Lifecycle

- result commit stores the current input signature;
- later committed job/rider changes recompute it;
- mismatch sets `result_is_stale`;
- new optimizer result clears staleness.

## Why it matters

A displayed plan must never be mistaken for a plan generated from the currently edited inputs. Staleness is a UI/data-lineage guard before [[64 Excel Workbook Contract]] or [[70 Route Planner Bridge]].

## Limitation

The signature binds jobs and riders, not every algorithm/config/cache/provider change. Algorithm identity/settings are separately recorded by [[63 Canonical Metrics and Run Artifact]].

