---
title: Optimiser Streamlit page orchestrator
tags: [bluesg, route-optimiser, streamlit, ui]
---

# Optimiser page orchestrator

Gateway from [[00 Route Optimiser Mega Web]] and user path [[01 Operator Journey]].

The 3,284-line page coordinates UI and calls domain modules. It owns import widgets, rider dialog, operation/advanced settings, progress, maps, result review, assignment edits, dispatch view, and download.

## Major edges

- source cache/import → [[10 Job Source Detection]];
- session transactions → [[20 Workflow State Machine]];
- operation settings → [[30 Operation Context]];
- active branch → [[40 V2 Capacity Gate]] or V1 through [[50 V1 Compatibility Surface]];
- progress → [[61 Progress and Diagnostics]];
- result formatting → [[62 Compatible Route Schema]];
- artifact/export → [[63 Canonical Metrics and Run Artifact]], [[64 Excel Workbook Contract]];
- latest-result handoff → [[70 Route Planner Bridge]].

## Rerun reality

The script reruns top-to-bottom on interaction. Expensive work is guarded by run buttons/forms and cached parsing/geocodes. Per-user transaction state belongs in `st.session_state`; see [[20 Workflow State Machine]].

## Risk

The page is a coupling hotspot. Move business logic into testable modules before adding another major UI workflow. See [[04 Complexity Hotspots]].

