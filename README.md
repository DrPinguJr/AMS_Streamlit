# Lance Streamlit Apps

This repository runs several Streamlit tools from one grouped app.

## Start The App On Windows

From the project root:

```powershell
cd "C:\Users\HRteam\Desktop\Lance"
.\.venv\Scripts\streamlit.exe run app.py
```

Open the app at:

```text
http://127.0.0.1:8501
```

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

- BlueSG Vehicle Route Optimiser: `Flexar/BlueSG/Vehicle_Route_Optimiser.py`

BlueSG OneMap credentials are read from Streamlit secrets in deployment and from the local `.env` file in development. Runtime cache files are written under `Flexar/BlueSG/cache/runtime/`.

### Contracts Tools

Contract generators live under `Contracts/`.

- CFS Contract Generator: existing working generator.
- Letter of Appointment template path: `Contracts/templates/LOA/gbh_loa_template.docx`
- Permanent Placement Service Agreement template path: `Contracts/templates/Service_Agreement/permanent_placement_service_agreement_template.docx`

## Streamlit Community Cloud Deployment

Streamlit Community Cloud installs Python packages from `requirements.txt` and Linux system packages from `packages.txt`. Reboot the Streamlit app after adding or changing `packages.txt` so the system packages are installed.

Contract PDF generation uses headless LibreOffice rather than Microsoft Word. The Liberation and DejaVu font packages provide Linux-compatible fallbacks for fonts referenced by the existing DOCX templates; the source templates are left unchanged.

## Useful Commands

Run with hot reload:

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.runOnSave true
```

Run the Tender scraper directly:

```powershell
.\.venv\Scripts\python.exe Lance\Tender\Tender.py
```

Re-process an existing Tender CSV:

```powershell
.\.venv\Scripts\python.exe Lance\Tender\TenderProcess.py "Lance\Tender\Excel Sheets\151514_TenderBoard.csv"
```
