---
title: BlueSG data input, state, and schemas
tags: [bluesg, input, schema, session-state]
---

# BlueSG data input, state, and schemas

Back to [[00 BlueSG Index]].

Atomic input/state web: [[Route Optimiser Web/10 Job Source Detection]] → [[Route Optimiser Web/13 Stable Job Identity]] → [[Route Optimiser Web/14 Job Validation and Atomic Commit]] → [[Route Optimiser Web/20 Workflow State Machine]].

## Job input formats

`job_import_staging.py` accepts:

- Excel workbooks, scanning past title rows to find the header;
- CSV uploads;
- HTML job lists;
- pasted delimited text, including tab-separated rows;
- source auto-detection through `parse_job_source`.

It normalizes aliases, preserves source/order metadata, and reports validation errors/warnings without replacing valid committed jobs when a new import is invalid.

Canonical staged job columns:

```text
Job ID
Car Plate
Pickup Address
Pickup Lot
Drop-off Address
Drop-off Lot
Created At
Deadline
Status
Source
_original_order
```

Required route fields are Car Plate, Pickup Address, and Drop-off Address. Compatibility parsing additionally recognizes historical supplier/workbook headers and tracks uploaded rows. Duplicate plates with distinct Job IDs are retained and flagged; they are not silently collapsed.

## Stable identity

Stable Job ID is the cross-system key. If no explicit ID exists, staging builds a deterministic fallback from row content/order. Route rows also carry uploaded row/order data for compatibility.

Identity must remain stable across:

```text
import → validation → commit → V2Job → route row → assignment board
→ recalculation → Excel export → planner workbook re-import
```

Car plate alone is not a safe unique key.

## Draft and commit transaction

Core workflow state:

| Key | Meaning |
|---|---|
| `imported_source_data` | raw/import metadata for the selected source |
| `job_draft` | latest normalized/validated candidate jobs |
| `committed_jobs` | optimizer-authorized job snapshot |
| `rider_draft` | temporary roster editor transaction |
| `committed_riders` | optimizer-authorized roster snapshot |
| `optimiser_result` | latest committed result payload |
| `optimiser_result_signature` | SHA-256 of canonical committed jobs+riders |
| `result_is_stale` | committed inputs differ from the result signature |

Invalid job imports leave prior committed jobs intact. Cancelling a rider draft discards edits. Saving changed rider/job inputs marks an existing result stale. Committing a new result binds it to the current input signature.

## Rider roster schema

The V2 draft schema is:

```text
Rider Name
Start Location
Start Zone
Preferred
Maximum
Work Style
End Requirement
Active
Maximum Jobs     # compatibility alias
Rider Load       # compatibility alias
```

V2 fields:

- Preferred: soft target, whole number ≥ 0.
- Maximum: hard cap, whole number ≥ 1.
- Work Style: Local, Flexible, Area Lead.
- End Requirement: optional location and required time.
- Active: only active rows become solver riders.

Legacy migration:

- `Maximum Jobs` or `Max Jobs` populates Maximum;
- absent Preferred defaults to Maximum;
- Low/Local → Local;
- Priority/Piority/Area Lead → Area Lead;
- other load levels → Flexible;
- compatibility output maps Local/Flexible/Area Lead to Low/Medium/Priority.

## Daily roster source

`v2_daily_roster_source.py` validates weekday names and loads in this order:

1. configured Google Sheets CSV URL from `BLUESG_ROSTER_GOOGLE_SHEET_CSV_URL` or explicit argument;
2. local `data/weekday_rider_availability_and_capacity_roster.xlsx`, one sheet per weekday.

The Google URL may contain `{day}`. A `Day` column can filter a shared export. Numeric Preferred/Maximum cells are preserved as numbers so strict V2 validation does not mistake them for free-form text.

Saving edits writes only the local fallback workbook. It never writes back to Google Sheets.

## Operation context

`OperationContext` is immutable and owns:

- timezone `Asia/Singapore`;
- operation start/end datetimes;
- cross-midnight rollover when end ≤ start;
- empty travel mode;
- pickup/drop-off handling minutes;
- unlock wait;
- default operational buffer percentage.

Default window is 14:00–17:00, handling is 3+3 minutes, unlock is 0, and operational buffer is 20%. Negative handling/wait/buffer is rejected.

Supported empty travel modes:

- public transport;
- recovery vehicle;
- private hire/taxi;
- walking;
- mixed/manual.

## UI workflow

The optimizer page is organized as:

1. Upload jobs.
2. Configure today’s riders in a dialog, then run optimizer.
3. Review results, explanations/audits/maps, optionally edit assignments, and download.

Large UI state includes import notices/errors, roster source/warnings, route editor history, map rider selection, V2 assignment undo, latest optimization payload, and result-specific diagnostics. When changing keys, search both pages and tests; some planner handoff keys intentionally span pages.
