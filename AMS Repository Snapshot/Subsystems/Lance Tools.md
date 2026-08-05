---
title: Lance tools subsystem
tags: [ams, lance, selenium, recruitment, converter]
---

# Lance tools subsystem

Back to [[../00 Repository Index]]. HRIQ is documented separately in [[HR and HRIQ]].

## TenderBoard

- `Tender.py`: Streamlit page/direct entry that streams scraper logs and displays processed results.
- `TenderScrape.py`: loads local environment, creates Selenium driver, logs in, navigates keyword search, paginates, and extracts raw tender records.
- `TenderProcess.py`: normalizes raw/line-based results, parses dates/reference/company/industry/briefing data, deduplicates by stable identity, saves Excel, and supports reprocessing an existing CSV.

Primary risks: fragile remote selectors, credentials in `.env`, Chrome/driver compatibility, duplicated tenders, and output folders excluded from Git.

## Sesami

- `Sesami.py`: Streamlit/direct page and cached data presentation.
- `SesamiScrape.py`: Selenium login/navigation, modal handling, scroll-to-load, raw row extraction.
- `SesamiProcess.py`: typed normalization, stable identity, Excel persistence, and latest-result loading.

Primary risks mirror Tender: portal markup changes, authentication, driver lifecycle, and scraped data privacy.

## Recruitment Tracker

`Recruitment_Tracker.py` is a large all-in-one Streamlit workflow. It owns:

- folder/workbook setup;
- role and candidate sheets;
- ID generation and activity log;
- resume/JD upload and safe filenames;
- PDF/DOCX preview/extraction;
- filtering, editing, status/result coloring, and persistence;
- exports and local file opening.

Candidate and staff data are sensitive. Workbooks, resumes, JDs, and exports must remain ignored and access-controlled.

## PDF to Word Converter

`Converter/Converter.py` supports uploaded PDFs or a selected local PDF folder, creates unique safe paths, converts with `pdf2docx`, renders per-file results, and packages outputs into ZIP files.

Key boundaries: uploaded file size/content, safe names, temporary/output cleanup, conversion fidelity, and avoiding accidental overwrite.

## WhatsApp Monitor

- `WhatsApp.py`: Streamlit status and recent-message view.
- `whatsapp_driver.py`: Chrome driver, WhatsApp Web opening, login/QR detection.
- `whatsapp_monitor.py`: chat selection, contenteditable interaction, message extraction, timestamps, optional image capture, monitor lifecycle.
- `whatsapp_storage.py`: safe local message/image storage and recent-message retrieval.

This is distinct from the simulation-only [[Flexar WhatsApp Request Processor]]. It automates WhatsApp Web and therefore has a different operational/privacy risk profile.

## Shared operating assumptions

- These tools are predominantly Windows/desktop oriented.
- Selenium/browser sessions and local files are not expected to work unchanged on Community Cloud.
- Root navigation imports page scripts under one Streamlit process, so page-level `set_page_config` calls defensively catch the already-configured exception where needed.

