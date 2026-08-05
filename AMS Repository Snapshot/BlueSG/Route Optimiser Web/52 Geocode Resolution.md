---
title: Address geocode resolution
tags: [bluesg, route-optimiser, geocode]
---

# Geocode resolution

Credentials: [[51 OneMap Credential and Token Flow]]. Cache/provider parent: [[50 V1 Compatibility Surface]].

Unique rider starts, pickups, and drop-offs are cleaned, deduplicated, and geocoded concurrently.

## Lookup layers

1. in-memory result;
2. tracked verified seed CSV;
3. mutable runtime CSV;
4. live OneMap search;
5. unavailable/fallback zone behavior.

`GeocodeResult` records address, coordinates, source, and warning/error. Worker threads avoid unsafe Streamlit context access.

## Consumers

- route requests in [[41 Travel Matrix Construction]];
- map rendering in [[60 Optimiser Page Orchestrator]];
- planner geometry in [[75 Map and Preview Geometry]].

## Risk

Address cache rows may contain live operational locations. Do not duplicate them into the knowledge graph.

