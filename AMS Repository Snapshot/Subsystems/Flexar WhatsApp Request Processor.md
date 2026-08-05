---
title: Flexar WhatsApp request processor
tags: [ams, flexar, whatsapp, fastapi, sqlite, simulation]
---

# Flexar WhatsApp request processor

Back to [[../00 Repository Index]].

## Safety statement

This subsystem is a simulation-only WhatsApp-style request assembly service. WAAPI registration, credentials, webhooks, and live sends are deliberately disabled. The supervisor forces `SIMULATION_MODE=true` and all WAAPI/outbound gates false in its child environment without editing `.env`.

## Runtime architecture

```text
simulator / future webhook payload
        ↓
FastAPI api.py
        ↓
payload_parser + location_parser
        ↓
request_engine + request_policy + validation_engine
        ↓
SQLite Database
        ↓
DueRequestWorker → OutboundService → simulated WAAPIClient actions
        ↑
Streamlit app reads snapshots and renders UI components
```

The root START launcher delegates to PowerShell and `scripts/ams_supervisor.py`, which starts:

1. FastAPI at `127.0.0.1:8000`;
2. its lifespan-owned due-request worker;
3. optional ngrok for port 8000;
4. Streamlit at `127.0.0.1:8501`;
5. the dashboard route `/whatsapp-request-processor`.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `api.py` | FastAPI lifespan, health, simulated payload, container/outbound endpoints. |
| `app.py` | Single-page Streamlit simulator and live database dashboard. |
| `config.py` | Typed environment-derived settings and safe defaults. |
| `database.py` | SQLite persistence, WAL/busy-timeout behavior, snapshots, atomic claims. |
| `migrations.py` | Additive/safe schema migration. |
| `models.py` | enums/dataclasses for container, events, payloads, outbound actions, status. |
| `payload_parser.py` | batch splitting, action detection, licence-plate extraction, dedupe-friendly media parsing. |
| `location_parser.py` | location, parking, deck/lot extraction and merging. |
| `request_engine.py` | deterministic request/container assembly and matching. |
| `request_policy.py` | action-specific validation rules. |
| `validation_engine.py` | checklist/status generation. |
| `outbound_service.py` | rider/OPS simulated action construction and lifecycle. |
| `waapi_client.py` | future adapter with simulation/master gates. |
| `worker.py` | background dispatch of due requests. |
| `simulator_service.py` / `test_payloads.py` | guided/stress payload generation. |
| `runtime_support.py` | repository/Python discovery, safe status reads, redaction, process matching. |
| `scripts/ams_supervisor.py` | safe process orchestration, port ownership checks, logs, cleanup. |
| `ui_components.py` | reusable status, event, container, and outbound cards. |

## Request semantics

- Events are deduplicated by message/media identity.
- Matching prefers explicit licence plate/quote context and prevents completed containers from being reopened.
- Ambiguous/conflicting matches go to manual review.
- A complete request produces one request and controlled rider/OPS actions.
- Quiet-time dispatch resets after useful activity.
- Late media may become an OPS supplemental update without a duplicate rider response.
- Atomic database claims let background dispatch run independently of Streamlit reruns.

## Persistent/local data

- SQLite database: not deleted by normal startup/shutdown.
- `logs/YYYY-MM-DD_HH-mm-ss/`: supervisor, FastAPI, Streamlit, ngrok, errors.
- `runtime/ams_processes.json` and `runtime/system_status.json`: process IDs and safe operational URLs.
- The reset BAT requires typing `RESET` before clearing simulator data.

## Tests and known baseline issue

The suite covers API health, engine matching, ordering, inactivity, quiet timers, atomic dispatch, outbound idempotency, UI reruns, concurrent reads/writes, supervisor safety, validation, and WAAPI gates. It is excluded from default `pytest.ini` discovery.

At the snapshot, one test fails because it asserts `root.name == "Lance"`; this checkout is named `AMS_Streamlit`. See [[../01 Snapshot Baseline]].

