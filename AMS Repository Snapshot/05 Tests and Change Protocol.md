---
title: Tests and large-change protocol
tags: [ams, tests, change-management]
---

# Tests and large-change protocol

Back to [[00 Repository Index]].

## Test discovery reality

`pytest.ini` sets:

```ini
[pytest]
norecursedirs = .git .venv artifacts chrome_profiles
testpaths = tests Flexar/BlueSG/tests
```

Therefore `pytest -q` is a strong root/BlueSG check but is not a complete repository check. The WhatsApp processor and HRIQ suites must be named explicitly.

## Recommended baseline commands

```powershell
# Fast/default root + BlueSG contract
.\.venv\Scripts\python.exe -m pytest -q

# Whole known automated set
.\.venv\Scripts\python.exe -m pytest -q `
  tests `
  Flexar\BlueSG\tests `
  Flexar\whatsapp_request_processor\tests `
  Lance\HRIQ_Report_Tool\tests
```

Snapshot results are in [[01 Snapshot Baseline]].

## Before a large change

1. Record commit, branch, `git status --short`, Python version, and installed dependency versions.
2. Save representative input files outside the repo or in approved sanitized fixtures.
3. Run the default and expanded suites.
4. Export one known-good BlueSG workbook and retain its input hash, run summary, and algorithm metadata.
5. Record OneMap/cache mode so cached and live-network results are not compared as if identical.
6. Make the V1/V2 selection explicit; do not infer it from UI labels.
7. Decide which contracts may change: input aliases, roster schema, hard constraints, objective priority, route/export columns, planner compatibility, deployment pins.

## During the change

- Keep parsing, optimization, manual planning, export, and UI changes separable.
- Preserve stable job identity across every transformation.
- Treat coverage and hard feasibility as higher priority than score/duration improvements.
- Never write tokens, passwords, rider data, or route payloads into tests or logs.
- Add focused tests at the nearest boundary and one end-to-end workflow test.
- For BlueSG, use [[BlueSG/10 Change Impact Playbook]].

## After the change

1. Run the default suite, expanded suite, and targeted changed-area suites.
2. Confirm no generated/sensitive files are staged with `git status --short` and `git diff --cached --name-only`.
3. Run BlueSG Cloud preflight imports.
4. Exercise both BlueSG pages with one small sanitized workbook.
5. Verify workbook sheet names/columns and planner re-import.
6. Verify dirty drafts still block export and failed recalculation remains atomic.
7. Compare before/after run summaries on coverage, violations, duty, empty travel, fallback legs, and algorithm identity.
8. Update this vault or create a dated successor snapshot; do not silently overwrite historical baseline claims.

## Known baseline debt

- Expanded suite has one stale repository-folder-name assertion in WhatsApp runtime support.
- BlueSG planner emits a pandas FutureWarning for empty/all-NA concatenation.
- Starlette TestClient/httpx compatibility is deprecated in the installed WhatsApp test stack.
- Some legacy Streamlit code uses deprecated `use_container_width`; that is not part of this documentation-only change.

