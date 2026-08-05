---
title: Excel workbook contract
tags: [bluesg, route-optimiser, excel, output]
---

# Excel workbook contract

Inputs: [[62 Compatible Route Schema]], [[63 Canonical Metrics and Run Artifact]], and [[57 Route Reconstruction and Integrity]]. Planner round-trip: [[71 Planner Input Reconstruction]].

## Current sheets

How To Read This; Flexar Assignment List; Optimised Routes; Map Loader; Unassigned Jobs; Summary; Rider Instructions; Manual Review; Regional Capacity; Regional Assignment Audit; Local Search Audit; Run Metadata; Before After.

## Roles

- Optimised Routes: technical/round-trip source;
- Flexar Assignment List and Rider Instructions: operational handoff;
- Map Loader: compact mapping fields;
- Manual Review: visible low-confidence travel from [[54 Fallback and Confidence]];
- audit/metadata: algorithm and policy trace.

## Safety

- integrity validated before writing;
- route paths retained but hidden in technical sheet;
- Excel cell values sanitized/length-limited;
- planner exports only confirmed state through [[77 Confirmed Draft Export Guard]].

## Durability

Downloaded workbook is the durable Cloud output; local server files are not. See [[80 BlueSG Cloud Entry]].

