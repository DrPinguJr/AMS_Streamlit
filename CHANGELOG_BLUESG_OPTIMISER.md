# BlueSG Vehicle Route Optimiser Changelog

## Unreleased

- Made clustered cross-region trips human-first: when at least three jobs form a cluster, the optimiser applies zero first-positioning and unsupported-region scoring penalty, while retaining the real travel time for duty and feasibility checks.
- Changed the default operating-window preset to 14:00-17:00. Cross-midnight windows remain supported when selected.
- Added capacity-aware regional overflow without replacing the state-aware greedy/insertion solver.
- Added directional North-to-North-West, Central-to-South-West, and East-to-boundary support rules.
- Added dynamic East affinity, per-round regional specificity, and scarce West rider protection.
- Applied regional policy to greedy assignment, rescue, rebalance, and bounded local-improvement safeguards.
- Added per-job regional audit fields, Streamlit diagnostics, and `Regional Capacity` and `Regional Assignment Audit` Excel sheets.
- Added a deterministic 30-job / 15-West regression fixture and regional overflow tests.

## 2.0.0 — 2026-07-20

### Added

- Canonical `OptimisationRunResult`, `RiderRouteMetrics`, and `TravelLegResult` models.
- One `build_run_summary` metric source for UI, Excel, JSON, and benchmark output.
- Timezone-aware operation windows that correctly cross midnight.
- Explicit empty-travel modes and time/mode/provider-aware travel cache keys.
- Verified/cached/fallback/manual travel confidence and standard manual-review warnings.
- First-positioning, handling, route-time, total-duty, and adjusted-duty metrics.
- Central hard-constraint validation with soft `Max Jobs` preserved by default.
- Bounded local improvement using reinsertion, adjacent swap, inter-rider relocation, and one-for-one swap.
- Full evaluated/accepted move audit and strict coverage/hard-feasibility acceptance.
- Finite nested output sanitisation.
- Machine-readable run artifacts, benchmark CLI, benchmark reports, corrected workbook, and automated tests.
- Excel sheets for manual review, local-search audit, run metadata, and baseline/final comparison.
- Optional post-dispatch outcome fields in the canonical summary schema.

### Changed

- Production remains state-aware, job-by-job greedy/insertion with rescue and rebalance.
- Rider state and route chaining continue from each prior drop-off.
- Fallback estimates now receive a configurable quality penalty without altering reported duration.
- Public-transport routing uses the configured operation datetime instead of a fixed daytime request.
- Excel and Streamlit KPIs use canonical result metrics when available.
- `Max Jobs` is explicitly soft unless the hard-cap constraint is enabled.

### Fixed

- Removed fixed 14:00–17:00 assumptions from new production runs.
- Included first positioning and handling in rider duty burden.
- Prevented daytime/mode-incompatible travel-cache reuse.
- Prevented NaN/infinity failures at Streamlit, JSON, and Excel boundaries.
- Made unresolved fallback use visible to dispatchers and riders.

### Compatibility

- Existing `optimise_vehicle_routes` callers and DataFrame return contract remain supported.
- Existing essential workbook sheets and operational columns remain; new columns/sheets are additive.
- Existing map, route planner, roster, date filter, WhatsApp output, rescue insertion, and integrity validation remain available.
- Local improvement and experimental cluster-first flags default to off; the baseline remains production default.

### Promotion status

- Not promoted: the 17 July local-search benchmark preserved 30/30 coverage and zero hard violations but increased empty travel from 621.0 to 666.0 minutes.
