---
title: Route Optimiser Mega Web
tags: [bluesg, route-optimiser, graph-hub]
---

# Route Optimiser Mega Web

This is the atomic, graph-first bridge for the BlueSG Route Optimiser. Return to [[../00 BlueSG Index]].

At creation this subgraph contains 59 connected notes and 381 internal note-to-note edges. Every node has at least five connections, so the local graph forms a dependency mesh rather than isolated leaves.

## Enter the web

- Operator-facing flow → [[01 Operator Journey]]
- Runtime dependencies → [[02 Runtime Dependency Spine]]
- Data transformations → [[03 Data Lineage]]
- Main complexity centers → [[04 Complexity Hotspots]]
- Graph display setup → [[05 Graph View Setup]]
- Job ingestion cluster → [[10 Job Source Detection]]
- State and roster cluster → [[20 Workflow State Machine]]
- Time and duty cluster → [[30 Operation Context]]
- Active V2 solver cluster → [[40 V2 Capacity Gate]]
- Shared V1/provider cluster → [[50 V1 Compatibility Surface]]
- Streamlit/output cluster → [[60 Optimiser Page Orchestrator]]
- Manual planning cluster → [[70 Route Planner Bridge]]
- Cloud cluster → [[80 BlueSG Cloud Entry]]
- Behavioral guarantees → [[90 Behaviour Contract Map]]
- Change navigation → [[91 Change Impact Routes]]

## The spine

```text
job source → canonical jobs → committed inputs → operation context
→ travel matrix → hard-feasible beam search → compatible route rows
→ canonical metrics/artifact → Excel/session → Route Planner
```

Follow the corresponding nodes:

[[10 Job Source Detection]] → [[12 Job Normalisation]] → [[14 Job Validation and Atomic Commit]] → [[20 Workflow State Machine]] → [[30 Operation Context]] → [[41 Travel Matrix Construction]] → [[45 Beam Search Expansion]] → [[49 V2 Status and Explanations]] → [[62 Compatible Route Schema]] → [[63 Canonical Metrics and Run Artifact]] → [[64 Excel Workbook Contract]] → [[70 Route Planner Bridge]]

## Reading rule

Every atomic node contains:

- what it owns;
- its upstream and downstream edges;
- source anchors;
- invariants or change risks.

Graph View should show this note as the bridge from BlueSG, then several connected clusters rather than one undifferentiated star.
