---
title: Standby driver advisor
tags: [bluesg, route-optimiser, hourly, gemini, llm]
---

# Standby driver advisor

Gateway from [[94 Hourly Rolling Dispatch]]. Owns `solve_with_standby_options` in `hourly_route_dispatch.py` and the pure `gemini_standby_advisor.py` module (no Streamlit, no `st.secrets` — the page reads the API key and passes it in, the same pattern as the OneMap token and roster Sheet URL).

## When it fires

Only reachable from the hourly page's "Standby driver review" button, shown after the mandatory rolling solve (`run_hourly_dispatch`) reports `INFEASIBLE`. It is a separate, operator-triggered "what if" path — the mandatory rolling loop itself stays strictly all-or-nothing (see [[94 Hourly Rolling Dispatch]] change risk).

## The two options

```text
run_optimiser_v2(..., allow_partial_assignment=True)
→ Option A: partial_result.route_df (jobs that fit) + unassigned_jobs (jobs that don't)
→ if unassigned_jobs and standby riders exist:
    build travel-time matrix (leftover jobs × standby riders)
    → build_standby_context (JSON payload)
    → recommend_standby_activation (Gemini, or a graceful "not configured" without one)
→ Option B: StandbyAdvisorResult (activate_driver, recommended_driver_name/job_id, business_reasoning)
```

`allow_partial_assignment` lives on `run_optimiser_v2` itself ([[45 Beam Search Expansion]]): when a job can't be hard-feasibly placed, the search skips it and keeps going instead of aborting, producing status `PARTIAL` (see [[49 V2 Status and Explanations]]). Default is off everywhere else in the codebase — this is the only caller that opts in.

## Standby rider pool

`standby_riders_for_dispatch` reuses the existing roster schema rather than adding a new column: a "standby" candidate is any roster row with `Active` **unticked** but a parsed Shift Start/End. It temporarily flips `Active` to `True` before calling `validate_v2_roster`, since that function only returns `Rider` objects for active rows, then keeps only rows that resolved a `available_from`. A row with no shift window is excluded — a standby candidate needs a declared window for the 10-minute shift-end buffer to mean anything.

## Gemini call contract

`recommend_standby_activation` never raises. Every failure mode - no leftover jobs, no standby riders, no API key, `google-genai` not installed, a malformed response, or a provider/network error - degrades to `activate_driver=False` with the reason in `business_reasoning`, so a flaky or unavailable model can never block the operator's dispatch flow. Targets the current `google-genai` SDK (`google.genai.Client(...).models.generate_content(...)`), **not** `google.generativeai`, which is fully end-of-life.

## UI contract

The review is read-only: it does not mutate `committed_jobs`/`hourly_open_routes` by itself. Acting on Option A means rerunning the solve after resolving the shortfall; acting on Option B means ticking `Active` for the recommended rider in the roster editor and rerunning. See [[20 Workflow State Machine]].

## Change risk

`GEMINI_MODEL_NAME` in `gemini_standby_advisor.py` is a single constant (`"gemini-2.5-flash"` at time of writing) - if Google retires that model, this is a one-line fix, not a code change. See [[92 Known Technical Debt]].
