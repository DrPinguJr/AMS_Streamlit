# BlueSG Optimiser Improvement Report

## Outcome

The state-aware, job-by-job greedy/insertion optimiser remains the production default. It still updates each rider's state to the prior job drop-off, preserves one route row per source job, treats `Max Jobs` as soft unless an explicit hard-cap constraint is enabled, retains rescue insertion/rebalance, and preserves the existing map, planner, WhatsApp instructions, date filtering, rider roster, and Excel workflow.

Bounded local improvement is implemented but remains opt-in. The 17 July benchmark did not satisfy promotion requirements because its accepted variance-improving move increased empty travel. No cluster-first solver was promoted.

Phase 2A is now implemented around that retained solver. Regional capacity is assessed before solving, approved overflow is directional and route-aware, scarce West capacity is reserved for high-specificity West Core work, and protection is recalculated from each rider's changing current location on every greedy/rescue round. Unsupported assignments remain possible for coverage but are explicitly marked as exceptions.

## Files added

- `models.py`: canonical travel, rider-metric, and run-result dataclasses.
- `operation_context.py`: timezone-aware, cross-midnight operating windows and empty-travel modes.
- `travel_costs.py`: contextual cache keys, source confidence, and standard low-confidence warnings.
- `constraints.py`: central hard-constraint validator.
- `run_metrics.py`: canonical summary builder, objective tuple, finite JSON artifact writer, and input hashing.
- `output_sanitizer.py`: recursive NaN/infinity and non-JSON type sanitisation.
- `local_improvement.py`: bounded reinsertion, adjacent swap, inter-rider relocation, and one-for-one swap with full audit.
- `regional_overflow.py`: operational subregions, directional support graph, dynamic East affinity, regional capacity diagnostics, specificity/protection, and three-tier candidate policy.
- `benchmark_optimizer.py` and workspace `benchmark_optimizer.py`: production-path benchmark CLI.
- `tests/`: deterministic unit and integration coverage.
- `docs/bluesg_optimizer_architecture.md`: audited architecture map.
- `benchmark_results.csv`, `benchmark_results.json`, and `benchmark_summary.md`: reproducible benchmark deliverables.
- `corrected_example_output.xlsx`: corrected example export using the retained baseline.

## Files modified

- `vehicle_route_optimizer.py`: operation context, duty calculations, confidence-aware travel costs, fallback penalty/recheck, central hard validation, deterministic local-improvement adapter, canonical-compatible Excel output, manual-review output, and finite sanitisation.
- `Vehicle_Route_Optimiser.py`: overnight settings, explicit travel mode, handling/buffer controls, hard-cap controls, opt-in local search, canonical KPI display, baseline/final comparison, and automatic run artifact persistence.
- `CHANGELOG_BLUESG_OPTIMISER.md`: release notes and migration guidance.

The pre-existing live progress-terminal edits in both optimiser files and `tests/test_route_optimiser_terminal.py` were preserved.

## Functions and contracts added or materially changed

- `OperationContext.for_window` creates full datetimes and rolls an end time over midnight.
- `build_travel_cache_key` includes normalised endpoints, mode, day type, hour bucket, and provider version.
- `TravelCost.to_leg_result` bridges legacy callers to `TravelLegResult`; every produced cost now carries confidence and leg context.
- `validate_candidate_routes` is the central hard-constraint gate.
- `build_rider_metrics`, `create_run_result`, and `build_run_summary` define the single metric source for UI, Excel, JSON, and benchmarks.
- `objective_tuple` implements the required lexicographic order.
- `improve_assigned_routes` implements four bounded move classes without in-place candidate mutation.
- `improve_route_dataframe` evaluates local-search candidates with the same production parser, route evaluator, travel provider/cache, constraints, validation, and summary definitions.
- `verify_fallback_travel_legs` retries low-confidence legs and leaves standard manual-review warnings when unresolved.
- `export_routes_to_excel` accepts a canonical run result and adds `Manual Review`, `Local Search Audit`, `Run Metadata`, and `Before After` while preserving existing operational sheets.

## Bugs fixed

- Replaced fixed `14:00`/`17:00` operational behaviour with configurable, timezone-aware datetimes.
- Correctly handles a window such as 23:00 on one day to 03:00 on the next.
- Separates first positioning, subsequent empty travel, loaded travel, handling, route time, total duty time, and buffered duty time.
- Includes first positioning and handling in rider workload/duty metrics.
- Makes fallback confidence explicit and penalises fallback only in the quality score, never by altering reported travel minutes.
- Prevents time/mode-incompatible cache reuse.
- Makes unresolved fallback legs visible in route rows, rider instructions, manual-review Excel output, JSON warnings, and UI warnings.
- Sanitises nested NaN and infinity values before Streamlit/JSON/Excel boundaries.
- Removes independently calculated UI/Excel metrics when a canonical run result is available.
- Uses stable sorting and explicit candidate tuple tie-breakers; tests verify repeatability.

## New configuration

- Operation date, duty start, duty end, and timezone.
- Empty-travel mode: public transport, recovery vehicle, private hire/taxi, walking, or mixed/manual.
- Pickup handling, drop-off handling, unlock wait, and operational buffer.
- Fallback quality penalty.
- Explicit hard `Max Jobs` switch and maximum total duty time.
- Local-search enable switch, time limit, and iteration limit.
- Experimental cluster-first flag, defaulting to false and retaining the safe job-by-job solver.
- Capacity-aware regional overflow switch and configurable support tolerance, specificity threshold, support penalty, unsupported-region penalty, and scarce-driver escape penalties.

All effective settings and hard constraints are stored in the run artifact. Tokens and credentials are not stored.

## New metrics

- Total/maximum/median/minimum rider duty and duty spread/variance.
- First-positioning, subsequent empty, loaded, handling, route, total duty, and adjusted duty minutes.
- Empty-travel percentage, fallback leg count, hard violations, soft `Max Jobs` overage, zone jumps, wall time, accepted local moves, and manual-review warnings.
- Optional post-dispatch feedback fields, including whether the plan was dispatched without edits.
- Approved-support assignment count and exceptional unsupported regional assignment count.

## Tests

The BlueSG tests cover overnight rollover, duty composition, soft and hard job caps, confidence penalties without duration falsification, contextual cache keys, nested non-finite sanitisation, coverage/feasibility objective priority, local-search invariants, deterministic tie-breaking, route chaining, 30-job coverage, full workbook parsing/export, required sheets, and fallback warnings in rider instructions. Phase 2A adds a deterministic 30-job fixture with 15 West-related jobs and verifies scarce West protection, North-West and South-West overflow, East boundaries, rescue/local-search safeguards, coverage, and serialisable diagnostics.

Current V2 test result: **109 passed** across the configured repository suites (`python -m pytest -q`).

## Baseline and benchmark results

Baseline capture used the real source `Antares x Flexar - RB Jobs (5) 1.xlsx`, selected 30 jobs for 17 July 2026, and recorded SHA-256 `a83a92bef07b192401ed314c2fcde682ead5db9359cf9f09c9c5870f2c5e9285` plus Git commit `704ac6a6cc214fe43302806daa7f7948a7af7512`.

The pre-change live/cached OneMap reproduction exceeded 600 seconds before its first assignment. A reproducible fallback-only baseline was therefore recorded, and the supplied historical output was retained separately rather than misrepresented as raw input.

The final benchmark used the historical 14-rider dispatch roster, 23:00–03:00, explicit public-transport mode, frozen fallback estimates, and the same production evaluator for every algorithm:

| Algorithm | Assigned | Max duty | Empty travel | Fallback legs | Hard violations | Accepted moves |
|---|---:|---:|---:|---:|---:|---:|
| Baseline greedy/insertion | 30 | 224.0 min | 621.0 min | 60 | 0 | 0 |
| Baseline + local search | 30 | 224.0 min | 666.0 min | 60 | 0 | 1 |
| Cluster-hint greedy | 30 | 224.0 min | 619.5 min | 60 | 0 | 0 |

The local move slightly reduced duty variance but increased empty travel by 45 minutes. It therefore failed the promotion rule. The stable baseline remains default and the feature stays opt-in.

### Phase 2A regional fixture

The deterministic 14:00-17:00 fixture contains 30 jobs, 15 West-related jobs, one West rider, and multiple North, Central, East, and North-East riders. It uses a frozen verified fake travel matrix so it is fast and reproducible.

| Policy | Assigned | Hard violations | Maximum duty | Empty travel | Unsupported exceptions |
|---|---:|---:|---:|---:|---:|
| Regional policy disabled | 30 | 0 | 178.0 min | 234.0 min | 9 |
| Capacity-aware regional overflow | 30 | 0 | 86.5 min | 220.5 min | 1 |

Artifacts are in `Flexar/BlueSG/artifacts/regional_overflow_30_job/`. This synthetic result verifies the intended overflow behaviour but does not replace real-date tuning.

An additional current-roster check found only 8 Friday riders and fit 23/30 jobs inside the configured four-hour hard window. This is reported as a staffing/window feasibility result, not hidden as an algorithm failure.

## Known limitations

- OneMap public-transport availability and time sensitivity remain provider-dependent. Compatibility is now explicit, but successful verification still depends on provider response and credentials.
- All benchmark travel legs were fallback estimates because the controlled benchmark intentionally avoided live provider calls. Dispatch must verify the resulting 30 manual-review routes.
- Only one representative real date with a reconstructable 14-rider roster was available. Ten-date promotion evidence is not available, so no candidate is promoted.
- The generic constraint validator supports the requested constraint types, but the current UI exposes only hard rider job caps and maximum duty. Advanced fixed-job, together/separate, availability, final-location, and deadline constraints currently require programmatic configuration.
- Post-dispatch feedback fields are stored in the canonical schema but no external dispatch-outcome data source is connected.

## Recommended next steps

1. Restore/refresh a time-compatible verified OneMap cache and rerun the same benchmark with `--use-onemap`.
2. Collect at least ten real dates and actual rider rosters, including the required edge cases, before considering promotion.
3. Feed dispatcher corrections into the optional operational-feedback fields and track the percentage dispatched without edits.
4. Add UI editors for advanced per-job constraints once operations supplies the authoritative constraint source format.
5. Investigate a local-search acceptance refinement that rejects variance-only gains when empty travel materially worsens; keep lexicographic coverage and hard-feasibility priority unchanged.
