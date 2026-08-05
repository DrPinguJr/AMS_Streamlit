---
title: Route Optimiser runtime dependency spine
tags: [bluesg, route-optimiser, dependencies]
---

# Runtime dependency spine

Bridge: [[00 Route Optimiser Mega Web]].

## Active path

`optimiser_config.py` selects V2, so [[60 Optimiser Page Orchestrator]] calls [[40 V2 Capacity Gate]] and ultimately `run_optimiser_v2`.

V2 is independent in policy/search but imports infrastructure from [[50 V1 Compatibility Surface]]:

- `TravelCost`;
- [[51 OneMap Credential and Token Flow]];
- [[53 Travel Route Cache Identity]];
- route/summary formatting used by [[62 Compatible Route Schema]].

It also imports adjacency normalization from [[55 Seven Zone Adjacency]].

## Downstream consumers

V2 output flows into:

- [[57 Route Reconstruction and Integrity]];
- [[63 Canonical Metrics and Run Artifact]];
- [[64 Excel Workbook Contract]];
- session handoff to [[70 Route Planner Bridge]].

## Deployment spine

[[80 BlueSG Cloud Entry]] → [[81 Access Gate]] → [[82 Deployment Preflight]] → Streamlit navigation → optimizer page.

## Architectural warning

Changing the 6,300-line compatibility module can break active V2 even when the V1 solver is never selected. See [[91 Change Impact Routes]] and [[92 Known Technical Debt]].

