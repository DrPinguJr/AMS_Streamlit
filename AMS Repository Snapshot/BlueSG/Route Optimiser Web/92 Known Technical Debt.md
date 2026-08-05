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
- local/Cloud mutable filesystem is not a durable multi-user data store;
- shared in-process/session/disk boundaries require care under concurrent sessions.

## Documentation/acceptance debt

- source notes are mostly V1-centered;
- V2 code says V1 remains for rollback until live acceptance;
- automated tests are strong but do not prove real roster/workbook/provider usability.

## Refactor order

Extract [[53 Travel Route Cache Identity]], [[62 Compatible Route Schema]], [[57 Route Reconstruction and Integrity]], and [[64 Excel Workbook Contract]] before retiring V1 solver internals.

