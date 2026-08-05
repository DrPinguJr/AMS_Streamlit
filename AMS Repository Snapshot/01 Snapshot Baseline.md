---
title: Repository snapshot baseline
snapshot_date: 2026-08-05
tags: [ams, baseline, git, tests]
---

# Repository snapshot baseline

Back to [[00 Repository Index]].

## Git identity

| Field | Value |
|---|---|
| Repository root | `C:\Users\popla\OneDrive\Desktop\AMS_Streamlit` |
| Branch | `main` |
| Commit | `8b82a5fc9f08a1b0ac2b5eafd7c243d791fe3e5a` |
| Short commit | `8b82a5f` |
| Commit time | `2026-08-03T17:51:29+08:00` |
| Commit subject | `feat: Update deployment documentation and enhance module import checks for BlueSG application` |
| Source status before notes | clean; only `.obsidian/` untracked |
| Tracked files | 201 |

Tracked-file distribution at the snapshot:

| Area | Count |
|---|---:|
| `Flexar/` | 91 |
| `Lance/` | 64 |
| `Contracts/` | 16 |
| `tests/` | 10 |
| `HR/` | 8 |
| root files | 10 |
| `.streamlit/` | 1 |
| `.vscode/` | 1 |

## Runtime and dependency baseline

- Python environment: repository-local `.venv`.
- Root Streamlit constraint: `streamlit>=1.57,<2`.
- BlueSG Cloud pins: Streamlit `1.57.0`, pandas `3.0.3`, openpyxl `3.1.5`, pydeck `0.9.2`.
- Root dependency set additionally covers Selenium/browser automation, BeautifulSoup, requests, pandas/openpyxl, SQLAlchemy/ODBC, SQL parsing, DOCX/PDF generation, FastAPI, Uvicorn, Pydantic, dotenv, HTTPX, and pytest.
- Root app entrypoint: `app.py`.
- BlueSG-only Cloud entrypoint: `Flexar/BlueSG/streamlit_app.py`.
- Active BlueSG optimizer switch: `OPTIMISER_VERSION = "v2"` in `optimiser_config.py`.

## Test baseline

### Default configured suite

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result on 2026-08-05:

- `191 passed` in `18.27s`.
- Three pandas `FutureWarning`s at `manual_route_assignment_editing_and_recalculation.py:1127`, caused by concatenating empty/all-NA DataFrames for red route previews.
- `pytest.ini` discovers only `tests` and `Flexar/BlueSG/tests`.

### Expanded known suite

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests Flexar\BlueSG\tests Flexar\whatsapp_request_processor\tests Lance\HRIQ_Report_Tool\tests
```

Result:

- `302 passed`, `1 failed`, `14 warnings` in `77.85s`.
- Failure: `Flexar/whatsapp_request_processor/tests/test_runtime_support.py::test_repository_path_resolution`.
- Cause: the test asserts that the repository root folder is named `Lance`; the actual root folder is `AMS_Streamlit`. The helper still resolves the correct repository because the expected WhatsApp `api.py` exists. This is a stale test/environment-name assumption, not a BlueSG failure.
- Other warnings: one Starlette/TestClient deprecation, ten Streamlit/NumPy timedelta deprecations, and the three BlueSG pandas warnings above.

See [[BlueSG/09 Tests Guarantees and Known Issues]] and [[05 Tests and Change Protocol]].

## Mutable local artifacts observed

- `runs/`: 14 JSON run summaries spread across dated folders for 2026-07-31, 2026-08-03, and 2026-08-04.
- BlueSG runtime geocode cache: 3,240 bytes, modified 2026-08-04 13:26 local time.
- BlueSG runtime route cache: 50,149,649 bytes, modified 2026-08-04 13:28 local time.
- BlueSG weekday rider roster workbook: 11,584 bytes, modified 2026-08-04 13:33 local time. It is operational/sensitive and its row values are deliberately not copied here.
- Local `.env` and `.streamlit/secrets.toml` exist. They are sensitive and ignored. No values belong in this vault.

## Binary source assets

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `Contracts/templates/CFS/AMS - CFS - REB - Template.docx` | 109,762 | `013C06423C24B25F47F5C2CA3DB4DD2CE4E64E1DDE932955EAD48A6B1204E9B0` |
| `Contracts/templates/LOA/gbh_loa_template.docx` | 116,285 | `3F0A13BF59D513385FD1AAEF595320F50D07A854398C5CB6223E0943BF1BF678` |
| `Contracts/templates/Service_Agreement/permanent_placement_service_agreement_template.docx` | 104,799 | `2CE168D610E946761959F9A1D050B70AB7E1E6A9ECCCCB35DD2A23EC9193B2D0` |
| `HR/RDL_Archives/HRIQ_RDL_20260714_171111.zip` | 6,838 | `E977AA0524A2202DB17C9F7AB4C17DAA9CCC9E3DD3917D53EE1CF93FF8E1D615` |

The archive has a tracked `.sha256` sidecar. The BlueSG roster hash is intentionally omitted from this general note because it is mutable operational data, not a stable source asset.
