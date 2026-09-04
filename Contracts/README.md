# Contract Generator — End-to-End Guide

This document explains how the `Contracts` module works today, so it can be lifted
out of `AMS_Streamlit` and rebuilt somewhere else in a more dynamic (data-driven)
form.

## 1. What this module does

It is a set of Streamlit pages that fill Word (`.docx`) templates with form data
and optionally convert the result to PDF. There are three independent
generators sharing the same pattern:

| Generator | Page | Template | Notes |
|---|---|---|---|
| CFS (Contract for Service) | [pages/CFS_Generator.py](pages/CFS_Generator.py) | [templates/CFS/AMS - CFS - REB - Template.docx](templates/CFS/AMS%20-%20CFS%20-%20REB%20-%20Template.docx) | Only one with a **bulk/batch** mode and custom pagination logic |
| LOA (Letter of Appointment) | [pages/LOA_Generator.py](pages/LOA_Generator.py) | [templates/LOA/gbh_loa_template.docx](templates/LOA/gbh_loa_template.docx) | Manual entry only; batch tab is a stub |
| Service Agreement | [pages/Service_Agreement_Generator.py](pages/Service_Agreement_Generator.py) | [templates/Service_Agreement/permanent_placement_service_agreement_template.docx](templates/Service_Agreement/permanent_placement_service_agreement_template.docx) | Manual entry only; batch tab is a stub |

All three follow the same pipeline:

```
Streamlit form inputs
        │
        ▼
build_*_context()  ──  turns raw form values into template-ready strings
        │
        ▼
DocxTemplate(template_path).render(context)   (docxtpl, Jinja2-style {{ field }} tags)
        │
        ▼
(optional) python-docx post-processing (CFS only: pagination rules)
        │
        ▼
in-memory .docx bytes  ──►  (optional) convert_docx_to_pdf()  ──►  .pdf bytes
        │
        ▼
st.download_button()
```

## 2. Folder layout

```
Contracts/
├── __init__.py
├── generators/                    # pure logic: no Streamlit imports here
│   ├── cfs_generator.py
│   ├── loa_generator.py
│   └── service_agreement_generator.py
├── pages/                         # Streamlit UI only — forms + buttons
│   ├── CFS_Generator.py
│   ├── LOA_Generator.py
│   └── Service_Agreement_Generator.py
├── shared/                        # cross-cutting helpers used by all generators
│   ├── batch_utils.py             # DataFrame cleanup for pasted/bulk input
│   ├── file_utils.py               # filename sanitizing + zip creation
│   └── pdf_utils.py                # DOCX → PDF conversion (Word or LibreOffice)
└── templates/                     # the actual .docx files with {{ placeholders }}
    ├── CFS/
    ├── LOA/
    └── Service_Agreement/
```

This is a clean separation already: **pages** (UI) → **generators** (business
logic: build context + render template) → **templates** (the .docx files) →
**shared** (utilities every generator reuses). That separation is exactly what
makes it portable to a different app.

## 3. The rendering engine: `docxtpl`

Every template `.docx` is a normal Word document with Jinja2-style tags typed
directly into the text, e.g. `{{ contractor_name }}`, `{{ start_date }}`. There
is no code-side layout — Word/the template fully controls formatting, fonts,
letterhead, etc.

At render time:

```python
from docxtpl import DocxTemplate

template = DocxTemplate(str(template_path))
template.render(context)          # context = {"contractor_name": "JOHN TAN", ...}
template.save(output_buffer)      # in-memory BytesIO, never touches disk
```

`context` is just a `dict[str, str]` — every value must already be a
formatted string (dates, currency, times are all pre-formatted in Python
before being handed to the template; see §4).

Each generator also exposes `get_template_placeholders()` which opens the
`.docx` as a zip, reads `word/document.xml` (+ headers/footers), and regexes
out every `{{ ... }}` tag it finds. This is how the UI can show "Template
fields" and how `validate_*_context()` can detect:
- **missing required fields** (context key present in `REQUIRED_*_FIELDS` but blank)
- **unknown fields** (a `{{ tag }}` exists in the .docx that the Python code
  doesn't know how to fill — usually means someone edited the template and
  added a new placeholder without updating the generator)

This placeholder-discovery mechanism is the main lever for making the system
"more dynamic" — see §7.

## 4. Context building (the business-logic layer)

Each `generators/*_generator.py` file has a `build_*_context(data) -> dict`
function. This is where all formatting rules live:

- **Dates** → `"30 June 2026"` style, no leading zero on the day
  (`format_contract_date`, duplicated per-page as a local helper today).
- **Times** → `"2:00 p.m."` style (`format_contract_time`, CFS only).
- **Money** → `"1,234.00"` plus a spelled-out words version
  (`"One Thousand Two Hundred And Thirty-Four"`) via a small
  `number_to_words()`/`money_to_words()` implementation duplicated in both
  `loa_generator.py` and `service_agreement_generator.py`.
- **Names/NRIC** → upper-cased and stripped (CFS only).
- **Numeric terms → words** — Service Agreement additionally emits a
  `_words` twin for every numeric term (e.g. `payment_terms_days` = `"14"`
  and `payment_terms_days_words` = `"fourteen"`), so the template can say
  "within 14 (fourteen) days".

After building the context, each generator calls its own
`validate_*_context()` before rendering, and `ensure_no_unresolved_placeholders()`
after rendering (opens the produced .docx and fails loudly if any `{{`, `{%`,
or `{#` markup survived — i.e. the render silently skipped a field).

## 5. Generator-specific behavior

### CFS — [generators/cfs_generator.py](generators/cfs_generator.py)
- `build_contract_context(...)` — takes 9 explicit keyword args (not a dict)
  and maps 1:1 to the 9 placeholders in the CFS template.
- `generate_cfs_docx()` renders, then re-opens the result with `python-docx`
  and applies `_apply_cfs_pagination()` — a set of hard-coded rules keyed off
  literal section-heading text (`CFS_MAIN_SECTION_HEADINGS`,
  `CFS_ANNEX_SECTION_HEADINGS`) so that sections don't get split awkwardly
  across pages, and a page break is forced before "Entire Agreement" and
  before "Annex A – Scope of Services". **This is template-content-coupled**:
  if headings in the .docx are reworded, this code silently stops finding
  them.
- `generate_blank_cfs_docx()` renders the same template with
  `BLANK_CFS_CONTEXT` (underscores instead of real values) to produce a
  printable paper form.
- `generate_cfs_pdf()` renders to docx bytes → writes to a temp file →
  `convert_docx_to_pdf()` → reads PDF bytes back.
- **Bulk mode** (`build_bulk_contract_batch`): takes a `pandas.DataFrame` of
  contractors + one set of shared terms (dates/times/fee), loops rows,
  generates a PDF per row independently (one row failing doesn't stop the
  others — failures are collected as `BulkContractFailure` and shown in the
  UI), then zips every successful PDF in-memory (`create_zip_from_bytes`).
  Filenames are de-duplicated via `_unique_archive_filename` (`"Name (2).pdf"`).

### LOA — [generators/loa_generator.py](generators/loa_generator.py)
- `LOA_FIELDS` (full list of template placeholders) and
  `REQUIRED_LOA_FIELDS` (subset that must be non-blank) are both hard-coded
  lists that must be kept in sync with the .docx template by hand.
  - Note: `job_duty_2`–`job_duty_7` are deliberately **not required** —
    the form has a fixed 7-row job-duties editor but only duty #1 is
    mandatory.
- `generate_loa_docx()` → `generate_loa_pdf()` (PDF just wraps the DOCX
  path + `convert_docx_to_pdf`).
- No bulk/batch generation implemented — the page has a "Batch / Paste" tab
  that just shows an info message.

### Service Agreement — [generators/service_agreement_generator.py](generators/service_agreement_generator.py)
- `SERVICE_AGREEMENT_FIELDS` is one hard-coded list (no separate "required"
  subset — everything in it is required).
- 4 fixed "fee bands" (salary range / fee / guarantee) are flattened into
  `fee_band_1_*` .. `fee_band_4_*` keys — i.e. the number of bands is
  hard-coded into both the Python field list and the .docx template.
- Same DOCX → PDF wrapping pattern as LOA. No bulk mode.

## 6. Shared utilities

- [shared/file_utils.py](shared/file_utils.py)
  - `sanitize_filename()` — general-purpose, keeps spaces (used by LOA,
    Service Agreement, CFS bulk).
  - `sanitize_filename_for_legacy_docx()` — CFS individual mode only, strips
    everything but alnum/`_`/`-` and turns spaces into underscores (kept for
    backward-compatible filenames).
  - `create_zip_from_bytes()` / `create_zip_from_paths()` — in-memory zip
    building for the CFS bulk download.
- [shared/batch_utils.py](shared/batch_utils.py)
  - `normalize_dataframe()` — coerces a pasted/edited table to the expected
    columns, fills NaN with `""`, strips whitespace, drops fully-blank rows.
    Used by CFS's `st.data_editor` bulk table.
- [shared/pdf_utils.py](shared/pdf_utils.py)
  - `get_pdf_converter_status()` — detects, in order: Microsoft Word (Windows
    only, via `pywin32`/COM automation) → LibreOffice (`soffice`/`libreoffice`
    binary on PATH or standard install paths, cross-platform, headless
    `--convert-to pdf`). Returns availability + which converter + any error,
    **without launching anything**, so the UI can show a warning before the
    user tries to generate a PDF.
  - `convert_docx_to_pdf(docx_path, output_dir)` — does the actual
    conversion via whichever converter is available, validates the output is
    a real, non-empty PDF (checks the `%PDF` magic bytes).
  - This is the only part of the pipeline that is **not pure Python** — it
    shells out to LibreOffice or drives Word over COM, so it needs one of
    those installed on the host machine running the Streamlit app.

## 7. How the pages wire in generators (Streamlit-specific)

Each `pages/*.py` file is a plain Streamlit script (registered as an
`st.Page` in the root [app.py](../app.py) under the "Contracts" section, and
linked from [Home.py](../Home.py)). Pattern:

1. Render `st.text_input`/`st.date_input`/etc. widgets, each with a stable
   `key=` and `on_change=clear_generated_outputs` (so any edit invalidates
   the previously generated file cached in `st.session_state`).
2. On "Generate DOCX"/"Generate PDF" button press: read
   `st.session_state[...]` values into a `dict`, call the generator's
   `build_*_context()` + `generate_*_docx()`/`generate_*_pdf()`, and stash the
   resulting bytes + filename back into `st.session_state`.
3. If bytes exist in session state, show a `st.download_button()`.

CFS additionally has an "Individual Contract" vs "Paste Multiple Contractors"
radio toggle (`render_individual_contract_generator()` vs
`render_bulk_contract_generator()`), the latter using `st.data_editor` +
`normalize_dataframe()`/row-level validation before enabling the bulk-generate
button.

## 8. Dependencies

From [requirements.txt](../requirements.txt):
- `streamlit` — UI framework (pages, forms, session state).
- `pandas` — bulk contractor table handling (CFS only).
- `python-docx` — post-render document manipulation (CFS pagination only).
- `docxtpl` — Jinja2-in-docx templating engine (all three generators).
- `pywin32` (Windows only) — Word COM automation for PDF conversion.
- LibreOffice (`soffice`) is an **external binary**, not a pip package —
  must be installed separately on non-Windows hosts for PDF export to work.

## 9. What makes this "static" today (things to change for more dynamism)

If the goal is to move this somewhere else and make it more dynamic, these
are the concrete hard-coded points to target:

1. **One Python module per document type.** Adding a new contract type today
   means writing a new `generators/*.py` + `pages/*.py` pair, each
   duplicating the same render/validate/PDF-export boilerplate (and, for
   LOA/Service Agreement, duplicated `number_to_words()` implementations).
   A dynamic version would have **one generic engine** driven by a small
   config/manifest per document type (template path, required fields,
   field types/formatters, output filename pattern), instead of one file per
   type.
2. **Field lists are hand-maintained, not derived.** `LOA_FIELDS`,
   `REQUIRED_LOA_FIELDS`, `SERVICE_AGREEMENT_FIELDS` are manually kept in
   sync with the `.docx` placeholders; `get_template_placeholders()` already
   proves the placeholders *can* be discovered automatically from the
   template. A dynamic engine could generate the form itself (labels, input
   types, defaults) from template placeholders + a lightweight metadata file,
   instead of hard-coded Streamlit widgets per field.
3. **CFS pagination logic is coupled to literal heading text** in
   `CFS_MAIN_SECTION_HEADINGS`/`CFS_ANNEX_SECTION_HEADINGS` — any edit to the
   template's wording silently breaks pagination with no error.
4. **No bulk/batch mode for LOA or Service Agreement** (stub tabs only) —
   only CFS has it, and CFS's bulk implementation
   (`build_bulk_contract_batch`) is itself CFS-specific rather than a shared
   "render N rows against any template" utility.
5. **Fee bands are fixed at 4** in Service Agreement (`fee_band_1_*` ..
   `fee_band_4_*`) — not data-driven, so changing band count means editing
   both the template and the Python field list.
6. **PDF conversion requires local desktop software** (Word or LibreOffice)
   on the machine running Streamlit — there's no headless/cloud conversion
   path, which matters if this moves to a server without either installed.
7. **Templates live inside the app's own repo tree** — moving the module
   elsewhere means either moving `templates/` with it or making the template
   location configurable (e.g. env var / uploaded template) rather than the
   current `PROJECT_ROOT`-relative hard-coded `Path` constants at the top of
   each generator file.

## 10. Tests

Existing coverage lives in [tests/](../tests/):
- `test_cfs_generator.py` — context building, docx rendering, pagination.
- `test_cfs_bulk_pdf.py` — bulk batch behavior, partial failures, zip output.
- `test_cfs_page_dates.py` — default date behavior in the Streamlit page.
- `test_pdf_utils.py` — converter detection/selection logic.

There is no equivalent test file yet for LOA or Service Agreement generators.
