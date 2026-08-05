---
title: Route Optimiser data lineage
tags: [bluesg, route-optimiser, data-lineage]
---

# Data lineage

Bridge: [[00 Route Optimiser Mega Web]].

## Jobs

[[10 Job Source Detection]] → [[11 Header and Alias Mapping]] → [[12 Job Normalisation]] → [[13 Stable Job Identity]] → [[14 Job Validation and Atomic Commit]] → `V2Job` records → [[42 V2 Job Ordering]] → route rows in [[62 Compatible Route Schema]].

## Riders

[[22 Daily Roster Sources]] → [[23 Rider Draft Transaction]] → [[24 V2 Rider Validation]] → work-style behavior in [[25 Work Styles and Area Lead]] plus timing rules in [[26 End Requirements and Availability]].

## Travel

Addresses flow through [[52 Geocode Resolution]] and [[53 Travel Route Cache Identity]] into [[41 Travel Matrix Construction]]. Each selected sequence becomes [[31 Duty Time Composition]] and assignment quality in [[43 Assignment Severity]].

## Result

Best plan → [[49 V2 Status and Explanations]] → [[62 Compatible Route Schema]] → [[63 Canonical Metrics and Run Artifact]] and [[64 Excel Workbook Contract]] → [[71 Planner Input Reconstruction]].

## Identity boundary

Job ID must survive every arrow. Car plate, workbook row, rider, and sequence are attributes, not identity. See [[13 Stable Job Identity]] and [[72 Assignment Board Identity]].

