---
title: Route Optimiser known technical debt
tags: [bluesg, route-optimiser, technical-debt]
---

# Known technical debt

Context: [[04 Complexity Hotspots]]. Change routing: [[91 Change Impact Routes]].

## Coupling debt

- active V2 imports provider/schema/formatting from [[50 V1 Compatibility Surface]];
- optimizer and planner Streamlit pages are very large orchestration files;
- route schema is shared implicitly by UI, Excel, metrics, and planner.

## Runtime debt

- planner preview concatenation emits pandas FutureWarnings;
- route-board registration uses legacy `streamlit.components.v1`;
- local/Cloud mutable filesystem is not a durable multi-user data store — [[96 Local Dispatch Ledger]] is explicitly same-day/best-effort for this reason, not a fix;
- shared in-process/session/disk boundaries require care under concurrent sessions;
- [[95 Standby Driver Advisor]]'s `GEMINI_MODEL_NAME` is a single hardcoded model id with no fallback if Google retires it — cheap to fix, easy to forget.
- [[94 Hourly Rolling Dispatch]]'s `guarantee_minimum_coverage=True` default is an intentional, operator-confirmed override of hard feasibility (shift-end buffer, Max Jobs) — not a bug, but worth re-confirming with the operator if it ever needs to change, since the override is easy to miss in a status string unless the UI's forced-assignment callout is actually read.

## Resolved

- ~~`residual_riders`/`archive_completed_prefix` read route rows via scattered string literals~~ - centralised in `RouteSchemaAdapter`; see [[94 Hourly Rolling Dispatch]].
- ~~`residual_riders`'s `max(dispatch_at, *a, *b)` crashed for a rider with no shift window and no completion history~~ - fixed; see [[94 Hourly Rolling Dispatch]] "Fixed production bugs".
- ~~`run_hourly_dispatch` trusted any `isinstance(x, pd.DataFrame)` as correctly shaped, including a columnless session-state default~~ - fixed; same section.

## Documentation/acceptance debt

- source notes are mostly V1-centered;
- V2 code says V1 remains for rollback until live acceptance;
- automated tests are strong but do not prove real roster/workbook/provider usability.

## Refactor order

Extract [[53 Travel Route Cache Identity]], [[62 Compatible Route Schema]], [[57 Route Reconstruction and Integrity]], and [[64 Excel Workbook Contract]] before retiring V1 solver internals.

