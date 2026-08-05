---
title: Daily rider roster sources
tags: [bluesg, route-optimiser, roster]
---

# Daily roster sources

Gateway from [[00 Route Optimiser Mega Web]]. Downstream: [[23 Rider Draft Transaction]] and [[24 V2 Rider Validation]].

`load_daily_v2_roster` uses:

1. Google Sheets published CSV from `BLUESG_ROSTER_GOOGLE_SHEET_CSV_URL`;
2. local weekday workbook fallback at `data/weekday_rider_availability_and_capacity_roster.xlsx`.

The URL may contain `{day}` or the CSV may include a Day column. Preferred/Maximum are preserved as numeric cells for strict validation.

## Persistence

`save_local_v2_roster` writes only the local seven-sheet workbook. It never writes back to Google Sheets. Cloud-local edits are temporary; see [[80 BlueSG Cloud Entry]].

## Compatibility

Legacy weekday names and roster columns come from [[50 V1 Compatibility Surface]].

## Risk

The live roster contains operational/person data. Do not copy its rows into notes, tests, Git, or [[63 Canonical Metrics and Run Artifact]].

