---
title: Stable job identity
tags: [bluesg, route-optimiser, identity]
---

# Stable job identity

Upstream: [[12 Job Normalisation]]. Downstream: [[42 V2 Job Ordering]], [[57 Route Reconstruction and Integrity]], and [[72 Assignment Board Identity]].

Job ID is the only safe cross-stage identity. If a source lacks it, staging creates a deterministic fallback from stable row content/order. Compatibility helpers can also reconstruct IDs from route rows.

## Not identity

- Car Plate: duplicate plates may represent distinct jobs.
- Uploaded Row: useful lineage but changes with workbook structure.
- Rider/Sequence: output placement, not source identity.
- Card label: human presentation only.

## Exactly-once chain

```text
canonical Job ID → V2Job.job_id → route V2 Job ID/stable row
→ planner card ID → recalculated route → workbook re-import
```

## Failure signature

Identity loss appears as duplicate, missing, or unknown jobs in [[14 Job Validation and Atomic Commit]], [[57 Route Reconstruction and Integrity]], or [[77 Confirmed Draft Export Guard]].

