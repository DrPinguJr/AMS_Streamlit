---
title: Route reconstruction and integrity
tags: [bluesg, route-optimiser, integrity]
---

# Route reconstruction and integrity

Identity input: [[13 Stable Job Identity]]. Route input: [[62 Compatible Route Schema]]. Shared owner: [[50 V1 Compatibility Surface]].

## Checks

- every selected job accounted for;
- no duplicate/unknown job;
- assigned/unassigned sets do not overlap;
- sequences rebuild deterministically;
- first start matches roster start;
- each later start matches prior drop-off;
- enabled hard constraints pass.

## Uses

- post-V2 validation before [[63 Canonical Metrics and Run Artifact]];
- sequence reconstruction for manual changes;
- workbook round-trip in [[71 Planner Input Reconstruction]];
- final apply in [[76 Incremental Recalculation]];
- pre-export guard in [[64 Excel Workbook Contract]].

## Invariant

Pretty maps/metrics never override an invalid integrity report.

