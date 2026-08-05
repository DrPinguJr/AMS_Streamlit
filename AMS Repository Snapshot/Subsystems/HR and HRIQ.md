---
title: HR RDL and HRIQ subsystem
tags: [ams, hr, hriq, rdl, ssrs, sql]
---

# HR RDL and HRIQ subsystem

Back to [[../00 Repository Index]].

Two related tools operate on SSRS RDL reports.

## RDL Management Studio (`HR/RDL`)

- `app.py`: upload one/many `.rdl` files, parse/store them, display a report dashboard, inspect textboxes/datasets/parameters/JSON, and edit textbox values.
- `rdl_parser.py`: namespace-independent XML traversal, parse to dictionaries, and construct an edited RDL.
- `rdl_editor.py`: applies textbox updates while preserving the original/version model.
- `rdl_storage.py`: creates directories, sanitizes names, stores uploaded RDL/JSON/edited copies, lists reports, and versions originals.

The editor never overwrites the only original: it creates a version copy and an edited output.

## HRIQ Report Tool (`Lance/HRIQ_Report_Tool`)

The Streamlit app has Download, Reports, and SQL sections.

### Download pipeline

```text
auth.py / browser.py
  → SSRSClient REST catalog and content checks
  → crawler.py controlled REST or semantic-DOM traversal
  → downloader.py validated atomic RDL writes
  → CrawlStateStore + DownloadJobManager
```

- Authentication supports current Windows SSPI, an interactive visible browser, detected form login, and automatic selection.
- REST is preferred; DOM fallback follows only semantic folder/report tiles.
- HTML/login/error responses cannot replace a valid RDL.
- Interrupted `Downloading` rows are resumable; hashes skip unchanged reports.

### Parsing and library

- Directory and ZIP sources share an `RdlSource` abstraction.
- `batch_parser.py` parses new/changed content by SHA-256.
- `rdl_parser.py` extracts lightweight metadata and exact dataset SQL while redacting connection strings.
- `ReportLibrary` maintains searchable indexed metadata.
- Directory source wins if the same logical path exists in a ZIP.

### Archive safety

`archive_service.py` builds verified ZIP64 snapshots containing valid RDLs and a manifest. The final archive hash lives in an external `.sha256` sidecar. Direct ZIP parsing does not extract members and rejects traversal, absolute/drive/UNC paths, duplicates, encryption, size/count abuse, and suspicious compression ratios.

### SQL safety

- Accepts one `SELECT` or `WITH … SELECT` statement only.
- Masks literals/comments before safety classification.
- Detects `@Parameters`, binds values, limits rows, and exports CSV.
- Uses SQLAlchemy/ODBC; trusted Windows authentication is supported.

## Data flow

```text
HR/RDL (primary mutable source)
  → incremental parsing
HR/RDL_Parsed (schema JSON + dataset SQL)
  → SQLite report index / download state
HR/RDL_Archives (verified portable snapshots, optional read-only source)
```

## Tests

HRIQ tests cover archive/ZIP safety, incremental indexing, namespace-independent parsing, resume state, read-only SQL, REST client validation, atomic replacement, and SSRS path/link normalization. These tests are excluded from default `pytest.ini` discovery and must be invoked explicitly.

## Change risks

- Capturing credentials/cookies/full report pages in logs or diagnostics.
- Allowing crawler scope to broaden beyond catalog semantics.
- Extracting untrusted ZIPs to disk.
- Weakening SQL from a single read-only statement.
- Treating ZIP snapshots as the primary mutable source.
- Editing an RDL without versioning its original.

