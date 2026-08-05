---
title: Route Optimiser change impact routes
tags: [bluesg, route-optimiser, change-management, graph-gateway]
---

# Change impact routes

Gateway from [[00 Route Optimiser Mega Web]]. Risk inventory: [[92 Known Technical Debt]]. Acceptance: [[93 Acceptance Scenarios]].

## Choose the route matching the planned change

- Import/schema: [[10 Job Source Detection]] → [[14 Job Validation and Atomic Commit]] → [[13 Stable Job Identity]] → [[62 Compatible Route Schema]] → [[71 Planner Input Reconstruction]].
- Roster/policy: [[22 Daily Roster Sources]] → [[24 V2 Rider Validation]] → [[25 Work Styles and Area Lead]] → [[43 Assignment Severity]] → [[47 Lexicographic Objective]].
- Timing: [[30 Operation Context]] → [[53 Travel Route Cache Identity]] → [[31 Duty Time Composition]] → [[44 Hard Feasibility]] → [[63 Canonical Metrics and Run Artifact]].
- Solver: [[42 V2 Job Ordering]] → [[45 Beam Search Expansion]] → [[46 Beam Pruning and Timeout]] → [[47 Lexicographic Objective]] → [[49 V2 Status and Explanations]].
- Provider/cache: [[51 OneMap Credential and Token Flow]] → [[52 Geocode Resolution]] → [[53 Travel Route Cache Identity]] → [[41 Travel Matrix Construction]] → [[75 Map and Preview Geometry]].
- Output: [[62 Compatible Route Schema]] → [[63 Canonical Metrics and Run Artifact]] → [[64 Excel Workbook Contract]] → [[71 Planner Input Reconstruction]].
- Planner: [[72 Assignment Board Identity]] → [[73 Locks and Reshuffle Pool]] → [[75 Map and Preview Geometry]] → [[76 Incremental Recalculation]] → [[77 Confirmed Draft Export Guard]].
- Cloud: [[80 BlueSG Cloud Entry]] → [[81 Access Gate]] → [[82 Deployment Preflight]].

Every route ends at [[90 Behaviour Contract Map]] and [[93 Acceptance Scenarios]].

