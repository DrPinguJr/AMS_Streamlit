---
title: BlueSG outputs, metrics, and artifacts
tags: [bluesg, output, excel, metrics, artifacts]
---

# BlueSG outputs, metrics, and artifacts

Back to [[00 BlueSG Index]].

Atomic output web: [[Route Optimiser Web/62 Compatible Route Schema]] → [[Route Optimiser Web/63 Canonical Metrics and Run Artifact]] → [[Route Optimiser Web/64 Excel Workbook Contract]].

## Compatibility route schema

The base route table preserves these field groups:

- identity/order: Rider, Sequence, Uploaded Row;
- chain: Start From, empty-leg description/instructions/path;
- job: Car Plate, pickup address/lot, drop-off address, loaded movement/instructions/path;
- travel: empty/loaded/total distances and durations;
- V1 scoring: assignment score, zone adjustment, same-zone flags, route priority, weights and penalties;
- time/duty: projected duration, first positioning, ETAs, in-window duration, handling, route/duty/adjusted duty;
- quality: feasibility, unassigned reason, cost source, empty/loaded confidence, warning, validation status;
- geography/audit: home/current/pickup zones, rank/status/exception, job region/subregion/confidence, tier and regional penalties/reason.

V2 appends V2-specific columns such as V2 Job ID, Assignment Severity, Work Style, Preferred/Maximum Jobs, Area Lead Match, end-progress/arrival, and cache status while preserving compatibility columns.

Route paths are hidden in the Excel route sheet but retained for downstream map use.

## Summary schema

```text
Rider
Total Jobs
Total Empty Distance KM
Total Empty Duration Min
Total Loaded Distance KM
Total Loaded Duration Min
Total Route Distance KM
Total Route Duration Min
Adjusted Route Duration Min
First Positioning Min
Pickup Handling Min
Drop-off Handling Min
Total Duty Time Min
Adjusted Duty Time Min
Fallback Leg Count
Max Jobs Target
Max Jobs Overage
Hard Violation Count
Total Route Duration Hours
Within 3 Hours
Final Location
Empty Travel %
Loaded Travel %
Workload Comment
```

## Canonical run result

`OptimisationRunResult` records:

- run ID/time and explicit algorithm name/version;
- input filename and SHA-256;
- selected job date and settings;
- assigned/unassigned rows;
- per-rider `RiderRouteMetrics`;
- warnings, move audit, hard validation;
- shared summary.

`build_run_summary` is the canonical source for jobs/riders, travel/duty distribution, fallback/hard/max-job/zone metrics, regional support/exception counts, runtime, local-search moves, manual-review count, settings, and objective.

The canonical run objective used for V1/baseline comparison is distinct from the internal V2 plan objective. Both put coverage and hard violations first; do not compare tuple positions without labeling which objective produced them.

## JSON artifacts

`save_run_artifact` writes:

```text
runs/YYYY-MM-DD/HHMMSS_<algorithm_name>_run_summary.json
```

Serialization recursively sanitizes dataclasses, dict/list/tuple/set, dates, paths, pandas-like scalars, NaN, and infinity. JSON writes with `allow_nan=False`.

Observed snapshot: 14 run JSON files. Their operational contents were not copied into this vault.

## Excel workbook sheets

Current writer creates 13 sheets:

1. `How To Read This`;
2. `Flexar Assignment List`;
3. `Optimised Routes`;
4. `Map Loader`;
5. `Unassigned Jobs`;
6. `Summary`;
7. `Rider Instructions`;
8. `Manual Review`;
9. `Regional Capacity`;
10. `Regional Assignment Audit`;
11. `Local Search Audit`;
12. `Run Metadata`;
13. `Before After`.

The existing older workflow note lists 12 sheets and omits `Flexar Assignment List`; this snapshot reflects the current code.

## Workbook contracts

- `Optimised Routes` is the primary technical/round-trip route table.
- `Flexar Assignment List` is a user-facing assignment representation kept for workflow compatibility.
- `Map Loader` contains Rider, Sequence, Uploaded Row, Start From, Car Plate, Pickup Address/Lot, Drop-off Address.
- `Unassigned Jobs` must account for selected source jobs absent from routes.
- `Summary` contains overall metrics plus rider workload rows.
- `Rider Instructions` contains concise dispatch/WhatsApp-ready text.
- `Manual Review` repeats low-confidence/problem legs rather than hiding them.
- audit/metadata/before-after sheets may be empty/placeholder when their feature is not active, but sheet stability supports downstream readers.

## Planner/export safety

- Integrity is validated against source jobs before writing when `jobs_df` is provided.
- Planner export uses confirmed routes only.
- Dirty/unapplied drafts disable export.
- Workbook re-import must reconstruct stable identities and route chain.

## Change traps

- Removing/renaming a compatibility column or sheet without updating planner/tests/downstream operations.
- Mixing V2 internal objective with canonical run objective.
- Serializing DataFrame attrs/dataclasses without sanitization.
- Writing secrets/tokens into `settings` or session payloads that flow into artifacts.
- Treating Cloud-local artifacts as durable.
