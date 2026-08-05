---
title: Optimiser workflow state machine
tags: [bluesg, route-optimiser, streamlit-state]
---

# Workflow state machine

Gateway from [[00 Route Optimiser Mega Web]]. UI owner: [[60 Optimiser Page Orchestrator]].

Core `st.session_state` lifecycle:

```text
job/rider drafts → validated committed inputs → optimiser result
                               ↘ input signature → stale flag
```

Core keys include imported source data, job draft, committed jobs, rider draft, committed riders, optimizer result, result signature, and stale flag.

## Edges

- job transaction: [[14 Job Validation and Atomic Commit]];
- rider transaction: [[23 Rider Draft Transaction]];
- result fingerprint: [[21 Result Staleness Signature]];
- operation/run: [[60 Optimiser Page Orchestrator]];
- cross-page handoff: [[70 Route Planner Bridge]].

## Streamlit boundary

State is per user/tab and temporary. It is appropriate for UI transactions, not durable storage. Durable operational output is [[64 Excel Workbook Contract]]. Cloud loss behavior is in [[80 BlueSG Cloud Entry]].

## Change risk

Renaming keys without migrating both pages can create stale history, mismatched results, or silent loss after rerun.

