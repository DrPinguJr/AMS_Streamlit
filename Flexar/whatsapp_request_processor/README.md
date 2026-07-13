# AMS WhatsApp Request Processor

This package is the simulation-only WhatsApp request assembly service used by the AMS Streamlit workspace. It combines rider-style text and images into operational vehicle requests, validates them, waits for a quiet period, and records simulated rider and OPS actions.

WAAPI is intentionally disabled. Starting this local system does not register a webhook, test a WAAPI credential, call WAAPI, or send a WhatsApp message.

## Daily Use

1. Double-click `START AMS WHATSAPP SYSTEM.bat` in the repository root.
2. Wait until the terminal shows `SYSTEM READY`.
3. Use the Streamlit dashboard that opens in the browser.
4. Leave the terminal open while the system is in use.
5. Double-click `STOP AMS WHATSAPP SYSTEM.bat` when finished.

The console must remain open because it supervises FastAPI, the request worker, ngrok, and Streamlit. Starting the system a second time will not create duplicate services.

## What Starts

The launcher starts services in this order:

1. FastAPI on `http://127.0.0.1:8000`.
2. The existing request worker through FastAPI's lifespan startup.
3. ngrok connected to FastAPI port `8000`, when ngrok is installed and authenticated.
4. Streamlit on `http://127.0.0.1:8501`.
5. The browser at `http://127.0.0.1:8501/whatsapp-request-processor`.

All child output is captured in the one visible supervisor console and in a timestamped log directory. The launcher does not use Uvicorn reload mode.

If ngrok is unavailable, FastAPI and Streamlit can still operate locally. The console and dashboard show the tunnel as offline and never claim the complete system is online.

## Administrator Setup

### Python environment

Create the repository virtual environment once from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The launcher searches for Python in this order:

1. The active project virtual environment.
2. `.venv\Scripts\python.exe`.
3. `venv\Scripts\python.exe`.
4. `AMS_PYTHON`, when explicitly configured.
5. System Python as a final fallback.

It validates required imports but never installs packages automatically.

### ngrok installation

Install ngrok once using the organization's approved installation method. The launcher searches:

- `AMS_NGROK_PATH` or `NGROK_PATH`;
- the system `PATH`;
- `tools\ngrok.exe` in this repository;
- common per-user Windows installation locations.

Authenticate ngrok once under the same Windows account that will run the AMS system. Use ngrok's normal configuration command or approved configuration deployment. Never place the authentication token in the START file or repository.

The supervisor runs the equivalent of:

```powershell
ngrok http http://127.0.0.1:8000
```

It reads the public HTTPS tunnel from ngrok's local API at `http://127.0.0.1:4040/api/tunnels`. It displays the future webhook URL but does not submit it anywhere.

### Required local ports

| Port | Service |
|---|---|
| `8000` | FastAPI |
| `8501` | Streamlit |
| `4040` | ngrok local inspection API |

If another program owns a required port, the launcher reports its PID and stops safely. It does not kill unrelated processes. An already-running AMS service is reused only when its health response and Windows command line both match the expected service. Existing FastAPI is never reused unless it reports simulation mode enabled and WAAPI disabled.

### Safety configuration

The supervisor overrides these values only in its child-process environment:

```dotenv
SIMULATION_MODE=true
WAAPI_ENABLED=false
WAAPI_OUTBOUND_ENABLED=false
WAAPI_RIDER_REPLY_ENABLED=false
WAAPI_OPS_UPDATE_ENABLED=false
```

It does not edit `.env`. The outbound client also requires the master outbound gate and the relevant destination-specific gate before a future network call could be allowed.

Confirm safe status in either place:

- The console summary must show `Simulation Mode: ENABLED`, `WAAPI: DISABLED`, and `Live Sending: DISABLED`.
- `http://127.0.0.1:8000/health` must show `simulation_mode: true`, WAAPI `status: disabled`, and `outbound_enabled: false`.

### Logs and runtime files

Each session writes to:

```text
Flexar\whatsapp_request_processor\logs\YYYY-MM-DD_HH-mm-ss\
```

Files include:

- `supervisor.log`
- `fastapi.log`
- `streamlit.log`
- `ngrok.log`
- `errors.log`

Safe runtime state is stored atomically in:

```text
Flexar\whatsapp_request_processor\runtime\ams_processes.json
Flexar\whatsapp_request_processor\runtime\system_status.json
```

These files contain process IDs and operational URLs, not credentials. Logs and runtime files are excluded from Git. The SQLite database is not deleted during startup or shutdown.

### Shutdown behavior

The STOP launcher requests shutdown from the active supervisor. The supervisor verifies each recorded PID's command line, then stops Streamlit, ngrok, and FastAPI in that order. Stopping FastAPI triggers its lifespan shutdown and stops the request worker. A recorded child is force-stopped only if it does not exit after the graceful attempt. Unrelated Python, PowerShell, Streamlit, or ngrok processes are never globally terminated.

## Troubleshooting

### ngrok was not found

FastAPI and Streamlit remain available locally. Install ngrok once, authenticate it under the daily user's Windows account, and start the system again.

### FastAPI could not start

Check the displayed `fastapi.log` path. Confirm the virtual environment contains the project requirements and port `8000` is free.

### Streamlit could not start

Check `streamlit.log`. The supervisor cleans up services that it started so a failed dashboard does not leave an unintended partial session.

### A port is already in use

Close the named application if appropriate or contact the administrator. The launcher deliberately does not terminate unidentified processes.

### START says the system is already running

Use the existing browser dashboard and console. If the old console is unavailable, double-click STOP, wait for the offline summary, then START again. Stale process files are ignored when their PIDs or command lines no longer match.

### Database locked

Close duplicate development sessions and retry. The normal launcher prevents duplicate managed services and SQLite uses WAL plus a busy timeout.

## Future WAAPI Preparation

Do not activate WAAPI as part of local daily setup. Future integration work should separately verify real webhook payloads, HMAC validation, event filtering, media downloads, chat IDs, outbound delivery, retries, and idempotency. Only after that work is reviewed should an administrator deliberately configure live credentials and change all required safety gates.

The current future webhook shape is:

```text
https://YOUR-STABLE-PUBLIC-DOMAIN/webhooks/waapi
```

Displaying that URL does not register it and does not connect WAAPI.

## Tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest Flexar\whatsapp_request_processor\tests -v
```

Tests use temporary SQLite databases and mocked process/network behavior where appropriate. They do not require a WAAPI account and must not make a WAAPI network request.
