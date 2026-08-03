# Lance Streamlit Apps

This repository runs several Streamlit tools from one grouped app.

## Run The App On Windows

### First-time setup (when `.venv` does not exist)

Install Python first if this command does not print a version:

```powershell
python --version
```

Open PowerShell in the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The first installation can take several minutes. The `.venv` folder is local to
your computer and is intentionally not committed to Git.

### Start it again later

From the project folder, run:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

This uses the virtual environment directly, so activating it is not required.
Streamlit normally opens a browser automatically. If it does not, open:

```text
http://localhost:8501
```

To stop the app, return to PowerShell and press `Ctrl+C`.

### Optional: activate the virtual environment

If you prefer shorter commands:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

If PowerShell blocks `Activate.ps1`, either use the non-activation command above
or allow scripts for only the current PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Rebuild the environment

If `.venv` is missing or broken, delete that folder and repeat the first-time
setup commands. Your source code and app data are outside `.venv`.

## App Groups

### Home

The home page links to the main workspace sections.

### Lance Tools

Lance-owned tools live under `Lance/`, including:

- TenderBoard
- Sesami
- Recruitment Tracker
- Converter
- WhatsApp Monitor

### Flexar Tools

Flexar-specific tools live under `Flexar/`.

- BlueSG Vehicle Route Optimiser: `Flexar/BlueSG/pages/create_optimised_vehicle_routes_page.py`

BlueSG OneMap credentials are read from Streamlit secrets in deployment and from the local `.env` file in development. Runtime cache files are written under `Flexar/BlueSG/data/cache/runtime/`.

### Contracts Tools

Contract generators live under `Contracts/`.

- CFS Contract Generator: existing working generator.
- Letter of Appointment template path: `Contracts/templates/LOA/gbh_loa_template.docx`
- Permanent Placement Service Agreement template path: `Contracts/templates/Service_Agreement/permanent_placement_service_agreement_template.docx`

## Streamlit Community Cloud Deployment

Streamlit Community Cloud installs Python packages from `requirements.txt`.

Contract PDF generation uses an invisible Microsoft Word instance on Windows. DOCX generation remains available on systems without Microsoft Word.

## Useful Commands

Run with hot reload:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.runOnSave true
```

Run the Tender scraper directly:

```powershell
.\.venv\Scripts\python.exe Lance\Tender\Tender.py
```

Re-process an existing Tender CSV:

```powershell
.\.venv\Scripts\python.exe Lance\Tender\TenderProcess.py "Lance\Tender\Excel Sheets\151514_TenderBoard.csv"
```
