# TenderBoard Scraper

## Install

Run from the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `.venv` already exists:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Streamlit

Original command:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

With hot reload:

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.runOnSave true
```

Open:

```text
http://127.0.0.1:8501
```

## Run Scraper Directly

```powershell
.\.venv\Scripts\python.exe Tender\Tender.py
```

## Re-process Existing CSV

Use this when scraping is already done and you only want to clean the CSV again into Excel:

```powershell
.\.venv\Scripts\python.exe Tender\TenderProcess.py "Tender\Excel Sheets\151514_TenderBoard.csv"
```

## Output

Excel files are saved here:

```text
Tender\Excel Sheets
```

File names use this format:

```text
DDHHMM_TenderBoard.xlsx
```

## Credentials

Credentials are read from the local `.env` file.

## File Structure

```text
Tender\Tender.py         Streamlit page
Tender\TenderScrape.py   Selenium scraping and pagination
Tender\TenderProcess.py  Excel/data processing
```
