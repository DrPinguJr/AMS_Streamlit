---
title: Route Optimiser behaviour contract map
tags: [bluesg, route-optimiser, tests, graph-gateway]
---

# Behaviour contract map

Gateway from [[00 Route Optimiser Mega Web]]. Acceptance layer: [[93 Acceptance Scenarios]].

## Input/state contracts

[[10 Job Source Detection]] · [[11 Header and Alias Mapping]] · [[13 Stable Job Identity]] · [[14 Job Validation and Atomic Commit]] · [[23 Rider Draft Transaction]] · [[21 Result Staleness Signature]]

## V2 contracts

[[24 V2 Rider Validation]] · [[40 V2 Capacity Gate]] · [[41 Travel Matrix Construction]] · [[43 Assignment Severity]] · [[44 Hard Feasibility]] · [[45 Beam Search Expansion]] · [[47 Lexicographic Objective]] · [[48 Rider Burden and Fairness]]

## Provider/geographic contracts

[[52 Geocode Resolution]] · [[53 Travel Route Cache Identity]] · [[54 Fallback and Confidence]] · [[55 Seven Zone Adjacency]] · [[56 V1 Regional Overflow Policy]]

## Output/planner contracts

[[57 Route Reconstruction and Integrity]] · [[62 Compatible Route Schema]] · [[64 Excel Workbook Contract]] · [[72 Assignment Board Identity]] · [[73 Locks and Reshuffle Pool]] · [[74 Draft History]] · [[75 Map and Preview Geometry]] · [[76 Incremental Recalculation]] · [[77 Confirmed Draft Export Guard]]

## Deployment contracts

[[80 BlueSG Cloud Entry]] · [[81 Access Gate]] · [[82 Deployment Preflight]]

## Snapshot

Default root+BlueSG suite: 191 passed. Important tests cover 30-job completion, deterministic chaining, hard Maximum, Area Lead ownership, end deadlines, cache-context separation, fallback visibility, planner atomicity, and workbook round-trip.

