---
title: Hourly rolling dispatch
tags: [bluesg, route-optimiser, hourly, streamlit]
---

# Hourly rolling dispatch

Gateway from [[00 Route Optimiser Mega Web]]. Sibling UI to [[60 Optimiser Page Orchestrator]]; owns `pages/hourly_route_optimiser_page.py` and the pure engine `hourly_route_dispatch.py` (no Streamlit import — unit-testable directly).

## Page shape (post-redesign)

The page is a header + two primary actions + a two-column body, not a stack of forms:

- Header: title + three `@st.dialog` buttons — Today's riders (two tabs, see below), OneMap key ([[51 OneMap Credential and Token Flow]] session override, shared via `onemap_token_session.py`), Gemini key (session override for [[95 Standby Driver Advisor]], via `gemini_key_session.py`).
- Primary actions: Upload (dialog: file only, no paste-text path) and Optimise (runs `run_hourly_dispatch`, settings tucked in an `st.popover`).
- Left column: a plain-text run log (`st.code`, last 16 lines) plus the latest dispatch output, map, and a "Mark jobs complete" expander.
- Right column: one card per full-day driver (current location + remaining stop chain, from `driver_route_snapshot`), then the Backup pool cards ([[95 Standby Driver Advisor]]'s standby pool) with a "Check standby options" button that opens that review as a dialog.

**"Today's riders" tabs *are* the Active flag.** Full day drivers tab = `Active=True` rows; Half day / Ad hoc pool tab = `Active=False` rows. The dialog hides the Active checkbox entirely and reconstructs it on save from which tab a row was edited in (`full_day_edit.assign(Active=True)` + `pool_edit.assign(Active=False)`). This was a deliberate operator-facing simplification — see [[20 Workflow State Machine]] for the underlying `committed_riders` shape it still writes to.

## Why it exists

The main optimiser page solves once against a full job/rider set. This page solves repeatedly across a shift: jobs arrive in hourly Flexar releases, riders start/stop mid-shift, and jobs already completed must be locked so they are never re-planned or re-costed on the next run.

## The rolling loop

```text
append_hourly_jobs (new release, dedupe by Job ID)
→ live_shift_timeline (Active / Pending shift start / Shift ending / Shift ended per rider)
→ operator ticks completed jobs → archive_completed_prefix (contiguous prefix only)
→ run_hourly_dispatch:
    active_riders_for_dispatch (shift-window filter)
    → residual_riders (shrink capacity, advance start location/time by completions)
    → run_optimiser_v2 over open jobs only
    → incremental_recalculate (reuse unchanged legs against confirmed_open_routes)
    → combine_dispatch_routes (archive + open, resequenced per rider)
```

## Key invariants

- **Append-only job identity**: `append_hourly_jobs` refuses a Job ID that already exists with a different Car Plate/Pickup/Drop-off (raises `ValueError`); a byte-identical duplicate release is silently ignored, not re-appended. See [[13 Stable Job Identity]].
- **Contiguous completion only**: `archive_completed_prefix` requires a rider's completed jobs to be ticked in strict route order — completing job 3 before 1/2 raises `ValueError`. Archived rows are immutable and never re-enter planning.
- **Residual rider state**: `residual_riders` reduces `preferred_jobs`/`maximum_jobs` by jobs already archived for that rider, and advances `start_location`/`available_from` to the last archived drop-off/completion time, so the solver plans only the remainder of the shift from where the rider actually is.
- **No active rider ⇒ hard stop**: if jobs are still open but no rider is inside an available shift window, `run_hourly_dispatch` raises rather than silently dropping jobs.

## State reuse

Reuses [[20 Workflow State Machine]] session keys (`committed_jobs`, `committed_riders`) and [[10 Job Source Detection]] / [[14 Job Validation and Atomic Commit]] to stage each hourly release. Adds its own keys: `hourly_dispatch_at`, `hourly_open_routes` (last solved, still-editable plan), `hourly_archived_routes` (immutable completed ledger), `hourly_dispatch_result`.

## Downstream

- solve path shares [[40 V2 Capacity Gate]] → [[45 Beam Search Expansion]] → [[49 V2 Status and Explanations]];
- reuses [[76 Incremental Recalculation]] so confirmed legs are not recosted on every hourly rerun;
- route/summary shape stays [[62 Compatible Route Schema]] compatible, so the map and export paths need no special-casing;
- shortfall handling and standby-driver decision support → [[95 Standby Driver Advisor]];
- same-day resume across reruns/restarts → [[96 Local Dispatch Ledger]].

## Schema access

Route-row field access (`Rider`, `Sequence`, `Drop-off Address`, `Final Completion ETA`) is centralised in a `RouteSchemaAdapter` class inside `hourly_route_dispatch.py`, used by `residual_riders` and `archive_completed_prefix`. A `ROUTE_COLUMNS` rename is now a one-place edit instead of a scattered hunt — this was previously the top-flagged change risk here.

`open_jobs_for_dispatch` (committed jobs minus archived) and `operation_context_for_riders` (operation window from the latest rider shift end) are shared helpers factored out of `run_hourly_dispatch`, reused by [[95 Standby Driver Advisor]]'s review flow so it never duplicates that filtering logic.

## Change risk

The rolling lock-and-archive path (`run_hourly_dispatch`) stays strictly all-or-nothing by design — coverage is mandatory there, unlike the opt-in partial mode in [[95 Standby Driver Advisor]]. Do not let `allow_partial_assignment` leak into `run_hourly_dispatch`'s own solve call; that would silently let committed jobs go unassigned during the mandatory rolling loop. See [[92 Known Technical Debt]].
