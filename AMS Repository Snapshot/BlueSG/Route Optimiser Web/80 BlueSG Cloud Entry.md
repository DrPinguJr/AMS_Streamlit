---
title: BlueSG Cloud entry and routing
tags: [bluesg, route-optimiser, cloud, deployment]
---

# BlueSG Cloud entry

Gateway from [[00 Route Optimiser Mega Web]]. Security: [[81 Access Gate]]. Startup validation: [[82 Deployment Preflight]].

`Flexar/BlueSG/streamlit_app.py` adds repository root to `sys.path` and calls the shared router.

The router:

1. sets wide page configuration;
2. enforces access;
3. runs preflight;
4. warns that storage is temporary;
5. exposes `/optimise` and `/review` via `st.navigation`.

## Page edges

- `/optimise` → [[60 Optimiser Page Orchestrator]];
- `/review` → [[70 Route Planner Bridge]].

## Storage consequence

Cloud roster/cache/run files can disappear and may be shared across sessions. Download [[64 Excel Workbook Contract]] for durable output.

## Dependency contract

Python 3.12 is documented; exact pins are Streamlit 1.57.0, pandas 3.0.3, openpyxl 3.1.5, and pydeck 0.9.2.

