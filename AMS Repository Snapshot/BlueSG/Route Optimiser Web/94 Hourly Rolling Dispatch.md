---
title: Hourly rolling dispatch
tags: [bluesg, route-optimiser, hourly, streamlit]
---

# Hourly rolling dispatch

Gateway from [[00 Route Optimiser Mega Web]]. Sibling UI to [[60 Optimiser Page Orchestrator]]; owns `pages/hourly_route_optimiser_page.py` and the pure engine `hourly_route_dispatch.py` (no Streamlit import — unit-testable directly).

## Page shape (post-redesign)

The page is a header + two primary actions + a two-column body, not a stack of forms:

- Header: title + four `@st.dialog` buttons — Today's riders (two tabs, see below), OneMap key ([[51 OneMap Credential and Token Flow]] session override, shared via `onemap_token_session.py`), Gemini key (session override for [[95 Standby Driver Advisor]], via `gemini_key_session.py`), and Daily exports (lists every finished-day workbook from `hourly_daily_export.py`, most recent first, each with its own download button).
- Primary actions: Upload (dialog: file only, no paste-text path), Optimise (opens the **Review & confirm dispatch** popup - see below - instead of solving inline), and Reset (a confirm-gated `st.popover` that clears jobs/routes and the local ledger for a clean test run - `reset_hourly_jobs`, leaves the roster alone).

## Optimise opens a frozen review popup, not an inline draft

Clicking Optimise no longer solves inline. `open_review_popup` snapshots a fresh popup session (`hourly_popup_session_id` incremented, used to key the popup's widgets so a new Optimise click never inherits stale widget state from the last one) and opens `review_and_dispatch_dialog`, an `@st.dialog` that stays open across its own internal reruns until the operator explicitly Saves or Cancels - the rest of the page is inert while it's open, which is what makes the drag-and-drop board below safe to edit freely: nothing is written to `hourly_open_routes` until Save.

The popup has two phases, tracked by `hourly_popup_phase`:

- **"confirm"** - every job currently open on a driver's route is shown pre-checked as finished (`render_confirm_phase`; the operator unchecks a driver's most recent job(s) if they genuinely haven't finished - unchecking anything that isn't a trailing run raises the same `archive_completed_prefix` "route order" `ValueError` as before). Clicking **Confirm & solve** (`confirm_completions_and_solve`) archives exactly the checked set, then calls `run_hourly_dispatch` exactly as before and seeds a drag-and-drop board from its result. This is the "assume the previous batch is finished unless told otherwise" default the operator asked for - it replaces what used to be an opt-in, all-unchecked "Mark jobs complete" step for this specific append-then-optimise flow (that expander still exists lower on the page, unchanged, default-unchecked, for marking things complete outside of an Optimise run).
- **"board"** (`render_board_phase`) - a per-driver "current status" strip (from `driver_route_snapshot`, using each residual rider's actual start location - their last archived drop-off, or roster start if they haven't moved yet), the same `render_solver_callouts` warnings as before, then the drag-and-drop board itself: `render_route_assignment_board` from the newly extracted `route_assignment_board_rendering.py` (see [[72 Assignment Board Identity]]), seeded via `assignment_from_routes(solver_result.route_df, open_jobs, rider_names)`. Only this hour's newly-solved jobs ever enter the board - jobs archived in the "confirm" phase never appear as cards, so there is nothing to lock and no locked-rider machinery is used here (unlike the full Route Planner). **Save** (`save_popup_board`) validates the edited board and calls the new `apply_manual_dispatch_edits` (in `hourly_route_dispatch.py`) - which treats every residual rider as starting from an empty `confirmed_assignment` (nothing was committed for these jobs yet) so `incremental_recalculate` rebuilds every rider the operator touched, reusing legs from the solver's own `route_df` wherever the edit left that leg unchanged. **Re-solve** re-runs the solve from the already-confirmed completions (the old "Discard & re-optimise" behaviour, now scoped to the board phase). **Cancel** at either phase discards the popup's transient state (`close_review_popup`) without touching the committed plan.

`render_solver_callouts` (unassigned jobs / forced-coverage warnings) is shared between the popup's board phase and the accepted-plan banner below so both read identically.
- A result banner sits above the two-column body, outside both columns: a toast on Save (✅ via `hourly_run_toast`, the same pending-message-then-rerun pattern as `hourly_notice`), then a persistent 3-tile readout (Status / Riders routed / Stops planned) of the currently accepted plan, or an explicit "no solve yet" caption.
- Left column: a plain-text run log (`st.code`, last 16 lines) plus the latest dispatch output (table/reasons/map) and a "Mark jobs complete" expander (independent of the popup - still opt-in, default-unchecked).
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

Reuses [[20 Workflow State Machine]] session keys (`committed_jobs`, `committed_riders`) and [[10 Job Source Detection]] / [[14 Job Validation and Atomic Commit]] to stage each hourly release. Adds its own keys: `hourly_dispatch_at`, `hourly_open_routes` (last solved, still-editable plan), `hourly_archived_routes` (immutable completed ledger), `hourly_dispatch_result` (the currently accepted plan), `hourly_business_day` (see below), plus the popup's own transient `hourly_popup_*` keys (`phase`, `session_id`, `residual`, `open_jobs`, `solver_result`, `draft_assignment`, `error`) which only exist while the review popup is open and are fully cleared by `close_review_popup`.

## Business-day rollover and per-day export

The operating "day" boundary is 11am, not midnight (`business_day_for` in `hourly_route_dispatch.py` - before 11am local time still belongs to the previous business day). Once per browser session (`hourly_rollover_checked` guard, checked right after the ledger resume block), the page compares the current business day against the one the ledger last saved; if they differ, it exports the previous business day's combined archived+open routes to a dated workbook via `export_daily_dispatch_excel` (new `hourly_daily_export.py`, writes `Flexar/BlueSG/data/daily_exports/dispatch_YYYY-MM-DD.xlsx`, reusing `export_routes_to_excel` - see [[64 Excel Workbook Contract]]) and then resets jobs/routes for the new day via the existing `reset_hourly_jobs` (roster untouched). The Daily exports header dialog lists every such file (`list_daily_exports`) with its own download button, so a finished day can be handed to a manager.

This interacts with [[96 Local Dispatch Ledger]]'s same-day resume gate: a session spanning past midnight without yet crossing 11am is still the *same* business day even though the calendar date changed, so the normal same-calendar-day gate would otherwise reject the file and let the immediately-following `persist_hourly_ledger` call silently overwrite real data with an empty day before the rollover ever got to export it. See that note for `load_hourly_ledger_ignoring_staleness`, the fallback this page's rollover check uses to recover the real previous-day data when that happens.

## Downstream

- solve path shares [[40 V2 Capacity Gate]] → [[45 Beam Search Expansion]] → [[49 V2 Status and Explanations]];
- reuses [[76 Incremental Recalculation]] so confirmed legs are not recosted on every hourly rerun or every popup board edit;
- the popup's drag-and-drop board reuses the full Route Planner's component and encode/decode logic, now factored out into `route_assignment_board_rendering.py` so neither page defines it twice - see [[72 Assignment Board Identity]];
- route/summary shape stays [[62 Compatible Route Schema]] compatible, so the map and export paths need no special-casing;
- shortfall handling and standby-driver decision support → [[95 Standby Driver Advisor]];
- same-day resume across reruns/restarts, plus business-day rollover → [[96 Local Dispatch Ledger]].

## Schema access

Route-row field access (`Rider`, `Sequence`, `Drop-off Address`, `Final Completion ETA`) is centralised in a `RouteSchemaAdapter` class inside `hourly_route_dispatch.py`, used by `residual_riders` and `archive_completed_prefix`. A `ROUTE_COLUMNS` rename is now a one-place edit instead of a scattered hunt — this was previously the top-flagged change risk here.

`open_jobs_for_dispatch` (committed jobs minus archived) and `operation_context_for_riders` (operation window from the latest rider shift end) are shared helpers factored out of `run_hourly_dispatch`, reused by [[95 Standby Driver Advisor]]'s review flow so it never duplicates that filtering logic.

## Change risk

The rolling lock-and-archive path (`run_hourly_dispatch`) stays strictly all-or-nothing by design — coverage is mandatory there, unlike the opt-in partial mode in [[95 Standby Driver Advisor]]. Do not let `allow_partial_assignment` leak into `run_hourly_dispatch`'s own solve call; that would silently let committed jobs go unassigned during the mandatory rolling loop. See [[92 Known Technical Debt]].

## Every full-day driver gets a job, deliberately overriding safety limits if needed

`run_hourly_dispatch(..., guarantee_minimum_coverage=True)` is the default (not opt-in) for this page's mandatory solve — a standing operator decision, confirmed explicitly after being warned it can override a rider's shift-end buffer or Max Jobs cap. Implementation is a post-search top-up (`_force_minimum_coverage` in `vehicle_route_optimiser_v2.py`): any rider left with zero jobs after the normal hard-feasible search gets one job reassigned from a rider who has more than one, preferring a fully feasible reassignment if the search happened to miss one, and only forcing an infeasible pairing when no feasible option exists. A rider stays at zero only when no other rider has a spare job — this does not invent work when jobs < riders. See [[49 V2 Status and Explanations]] for the resulting status and [[45 Beam Search Expansion]] for where this sits relative to the search itself. The UI surfaces every override by name/reason in the result banner and run log — see "Latest result" in the page shape above.

**Redistributing capacity is not the same as having enough of it.** The first version of this feature only bypassed the *search's* per-job placement abort, not the earlier pre-search gate that reports INFEASIBLE outright when total jobs exceed every rider's combined Max Jobs - so 7 jobs against 6 riders' worth of capacity still hit INFEASIBLE even with the guarantee on, since the gate never got a chance to see it. Fixed by making `guarantee_minimum_coverage` also tolerate a real capacity shortfall the same way `allow_partial_assignment` does (shared `tolerate_unplaceable_jobs` flag at both gates): every rider still gets spread one job each up to what capacity allows, and the genuine surplus job(s) land on `unassigned_jobs` (status `PARTIAL`) rather than failing the whole hour. `assignment_from_routes` already tolerated jobs absent from `route_df` via its `UNASSIGNED_LANE` bucket - built originally for the manual planner - so no change was needed in `incremental_recalculate`'s side of the pipeline. The page shows unassigned jobs from a `PARTIAL` result the same way it shows forced overrides: a warning plus the specific job list, right in the result banner.

## Fixed production bugs (both were "any DataFrame/positional-arg shape is trusted" traps)

- **`max()` arity trap** in `residual_riders`: `max(dispatch_at, *maybe_a, *maybe_b)` degenerates to `max(dispatch_at)` — a single non-iterable argument — whenever a rider has both no Shift Start/End *and* no archived completion yet (a full-day rider's very first hour). `max()` with one argument tries to iterate it rather than treat it as the answer, raising `'datetime.datetime' object is not iterable`. Fixed by building an explicit candidate list and calling `max()` on that.
- **Columnless-DataFrame trap** in `run_hourly_dispatch`: `confirmed_open_routes.copy(deep=True) if isinstance(confirmed_open_routes, pd.DataFrame) else pd.DataFrame(columns=ROUTE_COLUMNS)` trusted *any* DataFrame instance, including the bare `pd.DataFrame()` Streamlit's session state starts with before the first solve of a session — zero columns, not the `ROUTE_COLUMNS` shape. `incremental_recalculate` then crashed on `confirmed_routes["Rider"]`. This hit on literally the first Optimise click of a fresh session. Fixed by also requiring `not confirmed_open_routes.empty`.

Both were caught by reproducing the exact reported error against the real function, not by code reading — see the regression tests `test_residual_riders_handles_no_shift_window_and_no_history`, `test_hourly_dispatch_succeeds_for_a_rider_with_no_shift_window`, and `test_hourly_dispatch_accepts_the_raw_session_state_default_frames` in `test_hourly_route_dispatch.py`. The pattern to watch for elsewhere in this module: an `isinstance(x, pd.DataFrame)` check alone is not a shape check — a real DataFrame can still be empty or columnless.
