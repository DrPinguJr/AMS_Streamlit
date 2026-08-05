---
title: Runtime data, security, and operations
tags: [ams, operations, security, data]
---

# Runtime data, security, and operations

Back to [[00 Repository Index]].

## Data classes

| Class | Examples | Rule |
|---|---|---|
| Source code/config examples | `.py`, `.bat`, `.ps1`, `requirements.txt`, `.env.example`, `secrets.toml.example` | Commit and review normally. Examples must contain placeholders only. |
| Stable source assets | contract DOCX templates, safe OneMap seed CSV, verified RDL archive | Commit only after privacy/licensing review; record hashes when changing. |
| Sensitive inputs | `.env`, real `secrets.toml`, rider roster, uploaded RDLs, resumes/JDs | Never copy values into Git, this vault, run artifacts, or screenshots. |
| Generated outputs | route workbooks, parsed JSON, CSV/XLSX scraper results, converted documents | Keep local unless an explicit controlled publication path exists. |
| Rebuildable caches | OneMap runtime CSVs, Streamlit cache, parsed indexes | Safe to rebuild; do not treat as source of truth. |
| Operational state | SQLite databases, WhatsApp process state, HRIQ crawl state, run summaries | Back up only through approved, access-controlled channels. |
| Disposable tooling | `.venv`, `__pycache__`, `.pytest_cache`, Chrome profiles | Recreate; do not document file-by-file. |

## Secret locations

- Root `.env`: local credentials/configuration for several tools.
- `.streamlit/secrets.toml`: real local Streamlit secrets.
- Any nested `.env` or `.env.*`: ignored except `.env.example`.
- Streamlit Community Cloud Secrets editor: hosted `APP_PASSWORD` and OneMap credentials.

Only variable names/placeholders may be documented. Values must be rotated if exposed in a terminal transcript, screenshot, chat, commit, or run artifact.

## BlueSG mutable paths

- `Flexar/BlueSG/data/weekday_rider_availability_and_capacity_roster.xlsx`: weekday operational roster; sensitive and not durable on Community Cloud.
- `Flexar/BlueSG/data/cache/seed/verified_onemap_address_coordinates_seed.csv`: safe, read-only seed cache.
- `Flexar/BlueSG/data/cache/runtime/`: mutable geocode and travel route caches.
- `runs/YYYY-MM-DD/*.json`: machine-readable optimization run summaries.
- downloaded route workbooks: durable operational output; users must download them from Cloud.

See [[BlueSG/04 Data Input State and Schemas]], [[BlueSG/06 Travel OneMap Cache and Confidence]], and [[BlueSG/08 Deployment Security Operations]].

## Other mutable paths

- WhatsApp processor: database, logs, runtime process JSON, placeholder/simulated media.
- HRIQ: `HR/RDL`, parsed JSON/index/state, download logs, development diagnostics, archives.
- Recruitment: workbook, resumes, JDs, and exports.
- Tender/Sesami: scraped CSV/XLSX output folders.
- Converter/Contracts: uploaded/converted/generated documents and temporary directories.
- WhatsApp Monitor: message SQLite and extracted images.

## Operational launch patterns

- Full workspace: `.\.venv\Scripts\python.exe -m streamlit run app.py`.
- BlueSG Cloud/local isolation: `python -m streamlit run Flexar/BlueSG/streamlit_app.py`.
- WhatsApp simulation stack: root `START AMS WHATSAPP SYSTEM.bat`; stop with root `STOP AMS WHATSAPP SYSTEM.bat`.
- Tender direct scraper: `python Lance/Tender/Tender.py`.
- Tests: see [[05 Tests and Change Protocol]].

## Known security posture

- The full workspace and BlueSG Cloud entrypoint share `require_cloud_access`.
- On Linux/Cloud the login gate is secure-by-default; Windows stays convenient unless `APP_PASSWORD` or `BLUESG_REQUIRE_LOGIN` enables it.
- `hmac.compare_digest` verifies the shared app password.
- BlueSG preflight errors are sanitized for the UI; complete tracebacks go to Cloud logs.
- The WhatsApp processor is simulation-only by design. The supervisor forces every WAAPI/live-send gate off in child processes.
- HRIQ SQL accepts only one read-only `SELECT` or `WITH … SELECT`, binds parameters, and limits rows.
- Contract PDF conversion starts an invisible Word instance and guarantees cleanup on success/failure.

## Immediate review item

A real local Streamlit secrets file was present during the snapshot. Its values are not recorded here. Confirm that it remains ignored, restrict its filesystem access, and rotate any credential that may have been exposed outside the trusted machine.

