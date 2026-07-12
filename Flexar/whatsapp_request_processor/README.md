# Flexar WhatsApp Request Processor

This module is a local simulator for assembling WhatsApp-style rider messages into one operational request.

It is part of the existing AMS Streamlit app under **Flexar -> WhatsApp Request Processor** and keeps the route:

```text
/whatsapp-request-processor
```

No live WAAPI messages are sent in the default configuration.

## What It Does

```text
Rider text/images
  -> payload parser
  -> deterministic request matching
  -> request container
  -> automatic validation
  -> quiet-window wait
  -> backend worker dispatch
  -> simulated rider reply and OPS group update
```

A request is automatically processed only when it has:

- one valid licence plate;
- at least `MIN_REQUIRED_IMAGES` approved images, default `4`;
- one clear action: `LOCKED` or `UNLOCKED`;
- no unresolved matching or licence-plate conflict.

## Simulation Mode

Simulation is enabled by default:

```env
SIMULATION_MODE=true
WAAPI_ENABLED=false
```

In this mode, outbound sends only update SQLite rows. The app does not call WAAPI, ngrok, cloud storage, external AI, OCR, or any paid service.

## Automation Mode

Automation is enabled by default:

```env
AUTOMATION_MODE=true
REQUIRE_OPERATOR_APPROVAL=false
AUTO_DISPATCH_COMPLETE_REQUESTS=true
AUTO_DISPATCH_IN_SIMULATION=true
```

When every hard validation check passes, the request moves to `READY_WAITING_QUIET` for `REQUEST_QUIET_SECONDS`, default `8`. The FastAPI lifespan starts a lightweight due-request worker from `worker.py`; that worker atomically claims due rows, creates exactly two normal outbound actions, simulates both sends in simulation mode, and marks the request completed. Streamlit does not run this worker and does not decide when quiet timers finish.

## Start The System

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn Flexar.whatsapp_request_processor.api:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```powershell
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

The convenience script does the same:

```powershell
Flexar\whatsapp_request_processor\start_local.bat
```

## Payloads A To J

- A: LP, action, useful text, and seven images.
- B: useful location text and seven images, but no LP.
- C: text with LP and lock action, no images.
- D: seven images, no text.
- E: filler text only.
- F: genuine duplicate of A.
- G: conflicting LP data.
- H: three images.
- I: four images.
- J: a second vehicle request with a different LP.
- K: MSCP request without deck, blocked until deck/level arrives.
- L: surface parking with lot number and no deck, valid.
- M: MSCP white-lot parking with deck but no numbered lot, valid because lot is optional.
- N: complete LP/location/images with no lock or unlock action, blocked until action arrives.

## Guided Scenarios

Use the guided scenario selector to play:

- Scenario A - Slow Rider A, Fast Rider B.
- Scenario B - Fifteen Events in One Request.
- Scenario C - Quiet Timer Reset.
- Scenario D - Paused and Resumed.
- Scenario E - Late Image.
- Scenario F - New Request After Completion.

## Understanding Containers

A container is one vehicle request being assembled. It appears only after useful text or image data arrives. Completed containers leave the live lane and move into the collapsed history area.

Common states:

- Collecting rider messages.
- Complete - waiting for messages to finish.
- Sending rider and OPS updates.
- Completed.
- Paused - waiting for the rider to continue.
- Needs review.
- Send failed.

## Inactivity And Expiry

Defaults:

```env
REQUEST_INACTIVE_SECONDS=60
LATE_MEDIA_GRACE_SECONDS=120
```

Paused requests can be reactivated by a compatible payload from the same rider. Late images inside the grace window can create an OPS-only supplemental media action without creating a second rider reply.

## Database Location

The active SQLite database resolves in this order:

1. `DATABASE_PATH` from environment configuration.
2. `%LOCALAPPDATA%\AMS_Streamlit\Flexar\flexar_requests.db`
3. `Flexar/whatsapp_request_processor/data/flexar_requests.db`

The app creates parent directories automatically. Existing DB files are migrated safely and are not deleted automatically.

If you previously used the repo-local database and want to copy it to the new default location, first close Streamlit and FastAPI, then run a one-time copy after checking both paths:

```powershell
$source = "Flexar\whatsapp_request_processor\data\flexar_requests.db"
$target = "$env:LOCALAPPDATA\AMS_Streamlit\Flexar\flexar_requests.db"
New-Item -ItemType Directory -Force (Split-Path $target)
Copy-Item $source $target -WhatIf
```

Remove `-WhatIf` only after the printed source and target look correct.

Database files are excluded from Git:

```text
*.db
*.sqlite
*.sqlite3
*.db-wal
*.db-shm
```

## Tests

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest Flexar\whatsapp_request_processor\tests -v
```

Tests use temporary SQLite databases and do not modify the operator database.

## Future WAAPI Configuration

Copy `.env.example` and fill these only when a real WAAPI account is ready:

```env
WAAPI_ENABLED=false
WAAPI_INSTANCE_ID=
WAAPI_TOKEN=
WAAPI_BASE_URL=
WAAPI_WEBHOOK_SECRET=
OPS_GROUP_CHAT_ID=
```

Future ngrok command:

```powershell
ngrok http 8000
```

Future webhook URL:

```text
https://YOUR-NGROK-DOMAIN/webhooks/waapi
```

Live WAAPI delivery is not production-ready until the actual account, endpoint format, webhook format, media handling, and retry behaviour have been tested.

## Troubleshooting

- FastAPI offline: start `uvicorn Flexar.whatsapp_request_processor.api:app --host 127.0.0.1 --port 8000 --reload`.
- Database locked: close duplicate app sessions, then retry; SQLite uses WAL and busy timeout.
- Duplicate ignored: the same external message ID was already processed.
- No container for filler: standalone text like "okay thanks" is intentionally ignored.
- Virtual environment missing: create it with `python -m venv .venv`.
- Port already in use: run Uvicorn on another port and update `API_BASE_URL` if needed.
