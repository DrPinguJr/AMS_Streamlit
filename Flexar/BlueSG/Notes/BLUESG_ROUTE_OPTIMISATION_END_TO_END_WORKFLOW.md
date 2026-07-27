# BlueSG End-to-End Process

## Overview

The system converts a vehicle-relocation job workbook and a weekday rider roster into a validated route plan. Each job is atomic:

```text
rider's current location
→ travel without the car to the pickup
→ collect and drive the car to the drop-off
→ use that drop-off as the next starting location
```

The optimizer creates the initial plan. The separate Route Planner can then make controlled manual changes and recalculate only the affected riders.

## 1. Start the application

Run the workspace Streamlit entry point:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

`app.py` registers:

- `Flexar/BlueSG/pages/create_optimised_vehicle_routes_page.py`;
- `Flexar/BlueSG/pages/review_map_and_manually_adjust_route_assignments_page.py`.

## 2. Upload and parse the job workbook

The optimizer accepts an Excel workbook and calls `load_and_validate_jobs`.

The parser:

1. scans the first rows to locate a recognizable header row;
2. maps supported header aliases to canonical job columns;
3. keeps the original workbook row and upload order;
4. normalizes dates, including supplier day/month formats;
5. requires Car Plate, Pickup Address, Pickup Lot, and Drop-off Address;
6. removes rows with unusable pickup or drop-off addresses;
7. warns about duplicate vehicle plates;
8. infers broad pickup and drop-off zones when needed.

If the workbook contains dates, the page lets the dispatcher select the operation date and only sends matching rows to the optimizer.

## 3. Confirm the rider roster

The live roster is `data/weekday_rider_availability_and_capacity_roster.xlsx`, with one sheet for every weekday.

The page:

1. loads the selected weekday;
2. normalizes the required columns;
3. allows rows to be added, removed, or edited;
4. removes exact duplicate rider rows before optimization;
5. converts valid rows into `RiderState` objects.

Each rider has:

- Rider Name;
- Start Location;
- Start Zone;
- Max Jobs;
- Rider Load.

`Max Jobs` is normally a soft preference. It becomes a hard limit only when the hard-cap constraint is enabled.

Rider Load affects assignment behavior:

- `Low`: strongly avoids long empty travel and area changes;
- `Medium`: balanced default; pasted `Normal` is normalized to `Medium`;
- `High`: prefers more work and clustering;
- `Very High`: applies a stronger work/cluster preference;
- `Priority`: owns matching-area work and shares it evenly with other Priority riders for the same area.

The common pasted spelling `Piority` is normalized to `Priority`, case-insensitively.

Selecting **Save Roster** persists the edited columns back to the weekday workbook.

## 4. Configure the run

The dispatcher chooses:

- operation date, start time, and end time;
- duration or distance optimization;
- OneMap usage;
- empty-travel mode;
- pickup, drop-off, unlock, and waiting allowances;
- operational duration buffer;
- fallback-quality penalty;
- workload and route-scoring weights;
- hard Max Jobs and maximum-duty constraints;
- regional-overflow policy;
- optional local improvement;
- optional deterministic route variant.

`OperationContext.for_window` creates full Singapore datetimes. If the end time is earlier than the start time, the end is placed on the following day.

## 5. Resolve OneMap credentials

The page can use:

1. a token entered in the current session;
2. Streamlit secrets in deployment;
3. environment variables or the workspace `.env`;
4. configured OneMap credentials to request and refresh a token.

Tokens and credentials are never written into the run summary.

If OneMap is disabled or unavailable, the optimizer can continue with explicit low-confidence fallback estimates.

## 6. Prepare geocodes and travel data

Before assignment, unique rider starts, pickups, and drop-offs are geocoded in parallel.

Lookup order is:

1. in-memory result;
2. compatible disk cache;
3. OneMap request;
4. fallback zone estimate when verified travel is unavailable.

The cache layout is:

```text
data/cache/
├── seed/verified_onemap_address_coordinates_seed.csv
└── runtime/
    ├── onemap_address_coordinates_runtime_cache.csv
    └── onemap_travel_routes_runtime_cache.csv
```

Travel-cache keys include the normalized origin and destination, travel mode, day type, hour bucket, and provider version. This prevents a drive result, daytime result, or old provider result from being reused in the wrong context.

Loaded legs use driving travel. Empty legs use the selected empty-travel mode, such as public transport, walking, recovery vehicle, or mixed/manual.

Public-transport adjustment changes the operational empty-leg duration using the configured multiplier and wait buffer. The fallback-quality penalty changes candidate ranking only; it does not falsify the duration shown to the dispatcher.

## 7. Build regional capacity context

`build_regional_overflow_context` classifies jobs and rider coverage before assignment.

The regional policy:

- recognizes operational subregions rather than relying only on broad zones;
- marks candidates as primary, approved support, or exceptional;
- allows directional support where it is operationally reasonable;
- protects scarce riders for high-specificity work;
- recalculates protection as riders move around the island;
- adds penalties and audit details without bypassing hard constraints.

An exceptional assignment remains possible when it is required for job coverage, but it is clearly marked for review.

## 8. Run the production solver

`optimise_vehicle_routes` starts with all selected jobs unassigned and every rider at their configured start.

For each assignment round:

1. every remaining job is considered for every rider;
2. the job is inserted into a complete prospective rider sequence;
3. the sequence is evaluated from the rider's start through every pickup and drop-off;
4. hard constraints reject invalid candidates;
5. candidate scores combine empty travel, loaded travel, duty, workload, Max Jobs, route zones, clusters, load level, regional policy, and fallback confidence;
6. Priority ownership and balance are evaluated explicitly;
7. deterministic upload-order and rider-name tie-breakers prevent random results;
8. the best feasible candidate is accepted;
9. that job's drop-off becomes the rider's next current location.

During final confirmation, the progress terminal shows both the overall batch
position and the driver's own route position. It also identifies whether the
driver starts that order from their roster starting location or from the
previous order's drop-off, together with the exact `Start From` address.

Jobs are never split. A pickup-to-drop-off vehicle movement remains one indivisible assignment.

## 9. Rescue and rebalance

If the ordinary append phase cannot place every job:

1. the rescue phase tests each remaining job at every feasible insertion position;
2. the same regional and hard-constraint rules still apply;
3. when complete assignment is requested, the soft duration cap can be relaxed but hard constraints cannot;
4. a minimum-workload rebalance can transfer suitable non-protected work to an under-target rider without losing job coverage.

The completed sequence map is then rebuilt through the same route evaluator so all rows and totals use consistent calculations.

## 10. Optional local improvement

When enabled, local improvement starts only after the complete baseline exists.

It tries bounded:

- reinsertion;
- adjacent swaps;
- inter-rider moves;
- one-for-one rider swaps.

Each candidate is copied, reevaluated, constrained, and audited. The lexicographic objective prioritizes:

1. fewer unassigned jobs;
2. fewer hard violations;
3. lower maximum duty;
4. lower duty spread and variance;
5. lower empty travel;
6. fewer fallback legs;
7. lower adjusted duty;
8. lower Max Jobs overage;
9. fewer zone jumps.

A move that harms coverage or hard feasibility is not accepted.

## 11. Validate and finalize

Before presenting the plan, the backend checks:

- every selected job is accounted for;
- no job appears twice;
- source and routed job rows do not overlap incorrectly;
- every rider's next start matches the previous drop-off;
- all enabled hard constraints pass;
- unassigned jobs retain their best available reason;
- route warnings and low-confidence legs remain visible.

`create_run_result` then produces the shared metric source used by Streamlit, Excel, JSON, and benchmarks. `save_run_artifact` writes a sanitized summary under:

```text
runs/YYYY-MM-DD/HHMMSS_<algorithm>_run_summary.json
```

## 12. Review the result

The optimizer page displays:

- assigned and unassigned totals;
- duty and travel metrics;
- rider summaries;
- fallback and manual-review warnings;
- regional capacity and assignment audit;
- map routes and stops;
- a route table;
- selective reshuffle controls.

The selective reshuffle editor proposes bounded changes for chosen jobs. Accepted proposals are rebuilt and validated before replacing the current result.

## 13. Export the workbook

`export_routes_to_excel` writes the operational workbook with these sheets:

1. `How To Read This`;
2. `Optimised Routes`;
3. `Map Loader`;
4. `Unassigned Jobs`;
5. `Summary`;
6. `Rider Instructions`;
7. `Manual Review`;
8. `Regional Capacity`;
9. `Regional Assignment Audit`;
10. `Local Search Audit`;
11. `Run Metadata`;
12. `Before After`.

The Rider Instructions sheet includes concise dispatch/WhatsApp text. Low-confidence travel is repeated in Manual Review instead of being hidden.

## 14. Open the Route Planner

The Route Planner can load:

- the workbook downloaded from the optimizer; or
- the latest optimizer result held in the current Streamlit session.

Workbook loading prefers the `Optimised Routes` table and can fall back to compatible route sheets. It reconstructs stable job IDs, rider starts, assignments, and summary data.

## 15. Edit a route safely

The planner begins with rider lanes locked.

A dispatcher can:

- unlock selected riders;
- reorder jobs within a rider;
- drag jobs between unlocked riders;
- place jobs in the reshuffle pool;
- run a bounded reshuffle across unlocked riders;
- highlight routes;
- undo, redo, or reset draft changes;
- refresh exact connector previews.

The draft is separate from the last confirmed plan. Export stays disabled while unapplied changes exist.

## 16. Apply planner changes

When **Apply & Recalculate** is selected:

1. the assignment board is normalized and validated;
2. locked-rider changes are rejected;
3. affected riders and changed route legs are detected;
4. unchanged confirmed loaded legs and compatible cache entries are reused;
5. only affected rider sequences are rebuilt;
6. untouched rider routes are combined with recalculated routes;
7. job-set, duplicate, hard-constraint, and chaining checks run;
8. success atomically replaces the confirmed plan;
9. failure leaves both the previous confirmed result and the draft available for correction.

The confirmed planner result can then be exported through the same workbook writer.

## Operational checklist

Before dispatch:

- confirm the correct workbook date;
- check every rider's start location and zone;
- verify Priority riders and Max Jobs settings;
- review OneMap/fallback warnings;
- review unassigned jobs and exceptional regional assignments;
- check maximum rider duty and route-chain status;
- apply all planner drafts before export;
- manually verify every low-confidence route shown in Manual Review.
