---
title: Local dispatch ledger
tags: [bluesg, route-optimiser, hourly, persistence]
---

# Local dispatch ledger

Gateway from [[94 Hourly Rolling Dispatch]]. Owns `hourly_dispatch_ledger.py` (no Streamlit import, unit-testable with a temp path).

## What it does

A local Excel workbook (`Flexar/BlueSG/data/hourly_dispatch_ledger.xlsx`, git-ignored) with sheets `Committed_Jobs`, `Committed_Riders`, `Open_Routes`, `Archived_Routes`, `Meta`. On page load the hourly page calls `load_hourly_ledger(today)`; if the ledger's `Meta.Last_Accessed_Date` matches today it resumes session state from the saved sheets, otherwise it starts with an empty canvas. Every state-changing action on the page (append jobs, save roster, archive completions, run dispatch) calls `save_hourly_ledger` afterward, overwriting the previous snapshot.

## Why "same-day, best-effort" and not durable storage

Streamlit Community Cloud's filesystem is wiped on redeploy and on a full container restart, not just a rerun - the Cloud entrypoint already carries this warning ("Cloud storage is temporary...", see [[80 BlueSG Cloud Entry]]). This ledger survives reruns and brief in-container restarts within one calendar day; it does not survive a redeploy. It exists in this form because it was explicitly specified as a local-Excel design. A Google-Sheet-backed ledger, mirroring [[22 Daily Roster Sources]]'s Sheet-first/local-fallback pattern, would be the path to real cross-restart durability if that becomes necessary.

## Failure handling

`load_hourly_ledger` returns `None` - not an exception - for a missing file, an unreadable/corrupt file, or a ledger left over from a previous day; all three cases collapse to "start fresh," which is the same outcome the operator would expect from any of them. `save_hourly_ledger` failures are caught by the page and shown as a dismissible warning rather than blocking the dispatch flow - a save failure should never stop an operator mid-shift.

## Change risk

Route/job/roster frames are written with the same "already Excel-safe" assumption `export_routes_to_excel` relies on (see [[64 Excel Workbook Contract]]) - tz-aware `Timestamp` columns are not writable by `openpyxl`. `dispatch_at` is therefore stored as an ISO string in the `Meta` sheet, not as a real datetime column. If a new tz-aware column is ever added to `ROUTE_COLUMNS`/`RIDER_COLUMNS`, it needs the same string treatment before it reaches this module.
