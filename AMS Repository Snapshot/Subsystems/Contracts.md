---
title: Contracts subsystem
tags: [ams, contracts, docx, pdf]
---

# Contracts subsystem

Back to [[../00 Repository Index]].

## Purpose and routes

Three Streamlit pages generate employment/business documents from tracked DOCX templates:

| Page | Generator | Template |
|---|---|---|
| `pages/CFS_Generator.py` | `generators/cfs_generator.py` | `templates/CFS/AMS - CFS - REB - Template.docx` |
| `pages/LOA_Generator.py` | `generators/loa_generator.py` | `templates/LOA/gbh_loa_template.docx` |
| `pages/Service_Agreement_Generator.py` | `generators/service_agreement_generator.py` | `templates/Service_Agreement/permanent_placement_service_agreement_template.docx` |

## CFS

- Supports individual and bulk contract generation.
- Builds date/time/context values, removes template/manual pagination artifacts, applies stable pagination controls, and checks for unresolved placeholders.
- Bulk generation keeps successful rows if another row fails, returns structured successes/failures, assigns unique archive names, and produces ZIP output.
- Can generate a blank writing-line form in addition to populated contracts.

## LOA and service agreement

- Build template context from form data.
- Convert numbers/money to words where required.
- Discover and validate template placeholders before generation.
- Generate DOCX and optionally PDF.

## Shared utilities

- `batch_utils.py`: Excel/tab-paste ingestion, normalization, blank-row removal, required-column checks.
- `file_utils.py`: safe legacy-compatible filenames and ZIP creation from paths/bytes.
- `pdf_utils.py`: Word discovery, COM automation, availability reporting, invisible conversion, input validation, and guaranteed Word shutdown.

## Platform boundary

DOCX generation is portable. PDF conversion depends on Microsoft Word/COM and is therefore Windows-only in normal operation. Streamlit Community Cloud may serve DOCX generation but cannot provide the Word automation path.

## Tests that protect it

- CFS default/end-date behavior and manual date preservation.
- Blank form markers/writing lines and pagination grouping.
- Bulk partial-success cleanup.
- Word discovery order, invisible conversion, error cleanup, input validation, and non-Windows unavailability reporting.

## Change risks

- Renaming a template placeholder without updating its context builder.
- Template pagination edits invalidating layout tests or unresolved-placeholder checks.
- Starting Word visibly or leaking a Word process after an exception.
- Using unsafe filenames in ZIPs or legacy Word paths.
- Assuming PDF support in Linux/Cloud.

