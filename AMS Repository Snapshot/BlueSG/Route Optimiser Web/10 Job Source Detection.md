---
title: Job source detection
tags: [bluesg, route-optimiser, input]
---

# Job source detection

Gateway from [[00 Route Optimiser Mega Web]] and [[01 Operator Journey]].

`job_import_staging.parse_job_source` chooses among Excel, CSV, HTML, and pasted delimited text. Excel and CSV accept bytes, file-like objects, strings, or paths; pasted text can be tab/comma/other detected delimiters.

## Edges

- sends raw columns to [[11 Header and Alias Mapping]];
- sends rows to [[12 Job Normalisation]];
- reports source metadata in [[61 Progress and Diagnostics]];
- invalid replacement must not overwrite [[14 Job Validation and Atomic Commit]].

## Invariant

Source detection chooses a parser; it must not invent business meaning or discard unknown source fields prematurely.

## Source anchors

- `job_import_staging.py`: `parse_excel_jobs`, `parse_csv_jobs`, `parse_html_job_list`, `parse_delimited_text`, `parse_job_source`
- optimizer page: `cached_parse_job_upload`, `cached_parse_pasted_jobs`, `render_job_importer`

