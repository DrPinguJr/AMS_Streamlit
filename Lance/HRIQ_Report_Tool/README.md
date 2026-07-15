# HRIQ Report Tool

Compact Windows Streamlit workspace for downloading, indexing, inspecting, archiving, and safely querying HRIQ SSRS reports.

## Setup and start

From `C:\Users\HRteam\Desktop\Lance`:

```powershell
Set-Location 'C:\Users\HRteam\Desktop\Lance'
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\requirements.txt
python -m streamlit run .\Lance\HRIQ_Report_Tool\app.py
```

Copy the HRIQ keys from `Lance\HRIQ_Report_Tool\.env.example` into the repository `.env`. The application starts without portal or database settings. `requests-negotiate-sspi` provides Windows Negotiate/SSPI authentication on Windows; interactive Chrome remains the safe fallback when the company authentication flow cannot be represented by an HTTP session.

## Data flow

```text
HR/RDL                         primary mutable RDL source of truth
    -> incremental parser (content SHA-256)
HR/RDL_Parsed                  lightweight schema JSON and exact dataset SQL
    -> SQLite metadata index
Lance/HRIQ_Report_Tool/state   report index and persistent SSRS download state

HR/RDL_Archives                verified portable ZIP snapshots
    -> optional direct read-only parsing (never extracted)
```

Normal RDL folders remain primary because individual downloads, resume, and partial retry are safer there. ZIP archives are portable snapshots or optional read-only import sources; changing one member generally requires rebuilding the ZIP. A directory copy always remains the active indexed source when the same logical path also exists in a ZIP.

## Download behavior

The downloader establishes an authenticated SSRS session, tests `/Reports/api/v2.0/CatalogItems?$top=1`, enumerates catalog items through REST, and verifies one report through `/Reports/api/v2.0/Reports({Id})/Content/$value` before starting the bounded worker pool. It never follows generic same-domain links. If REST is unavailable, its DOM fallback traverses only semantic `folder-tile` and `report-tile` links and does not guess an RDL download URL.

Authentication modes are:

- **Automatic:** detects an existing SSRS browser session and opens visible Chrome if authentication is required.
- **Current Windows session:** uses Windows Negotiate/SSPI for REST requests.
- **Interactive browser session:** opens visible Chrome and waits for the user to complete company authentication without capturing a password.
- **Form login:** submits credentials only if an actual username/password form is detected.

Catalog metadata, attempts, hashes, statuses, errors, and timestamps are stored in `state/ssrs_state.db`. Stale `Downloading` rows are requeued after interruption, changed reports are downloaded again, and unchanged reports are skipped. Downloads are validated as RDL and atomically replaced; HTML login/error pages never overwrite a valid report.

## ZIP archives and direct parsing

**Create ZIP** writes a temporary ZIP64 archive, includes only validated `.rdl` files with their hierarchy, adds `manifest.json`, reopens and tests the archive, and only then moves it into `HR/RDL_Archives`. The final archive SHA-256 is stored beside it as `<archive>.zip.sha256` because a ZIP cannot truthfully contain its own final hash.

The Reports page can inspect or parse an existing/uploaded ZIP directly through `zipfile`; it does not extract members. It rejects traversal, absolute/drive/UNC paths, duplicates, encrypted members, excessive sizes/counts, and suspicious compression ratios. Configure limits with:

```dotenv
ZIP_MAX_ENTRIES=20000
ZIP_MAX_RDL_SIZE_MB=100
ZIP_MAX_TOTAL_UNCOMPRESSED_MB=5000
ZIP_MAX_COMPRESSION_RATIO=200
```

## SQL workbench

The existing SQL section still permits one `SELECT` or `WITH ... SELECT` statement, binds detected `@Parameters`, limits returned rows, and exports results to CSV. Install Microsoft ODBC Driver 18 for SQL Server. Username/password are optional when trusted Windows database authentication is used.

## Development verification (one report first)

Set these values only for a controlled development run:

```dotenv
HRIQ_DEVELOPMENT_MODE=true
HRIQ_BROWSER_HEADLESS=false
HRIQ_AUTH_MODE=interactive browser session
HRIQ_SSRS_ROOT_FOLDER=GOLDBELL
```

Then:

1. Start Streamlit and select **Interactive browser session**.
2. Click **Start**, authenticate in visible Chrome, and confirm the SSRS portal markers are detected.
3. In Diagnostics, confirm the REST base is `/Reports/api/v2.0/` and catalog access succeeds.
4. Confirm the crawler locates one catalog report (preferring `PreClaimForm` only when present), downloads its content endpoint, validates it as RDL, maps it under `HR/RDL`, and reports `Report-content access: true`.
5. Do not proceed with a mass download unless this one-report gate succeeds.
6. Open Reports, run **Parse Changes**, and confirm the report appears in the index.
7. Return to Download, click **Create ZIP**, and confirm `Ready` plus a `.sha256` sidecar in `HR/RDL_Archives`.
8. In Reports select **ZIP Archive**, choose the ZIP, click **Inspect**, then **Parse**.
9. Confirm the same report parses from the ZIP and no extracted RDL folder is created.

Development failures may save a screenshot and a sanitised form/selector shape under `HR/HRIQ_Dev`. Cookies, tokens, authorization headers, passwords, and full report pages are never saved.

## Tests

From the repository root:

```powershell
python -m pytest .\Lance\HRIQ_Report_Tool\tests -q
```

All REST tests use mocks and do not contact the company portal.
