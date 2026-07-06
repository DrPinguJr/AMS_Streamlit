# AMS Streamlit Apps

This project runs several Streamlit tools from one main app, including the BlueSG Vehicle Route Optimiser.

## Start The App On Windows

Open PowerShell and go to the project root folder:

```powershell
cd "C:\Users\popla\OneDrive\Desktop\AMS_Streamlit"
```

Then run Streamlit:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

Open the app in your browser:

```text
http://127.0.0.1:8501
```

## If You Are Already Inside BlueSG

If your terminal looks like this:

```text
C:\Users\popla\OneDrive\Desktop\AMS_Streamlit\BlueSG>
```

go back one folder first:

```powershell
cd ..
.\.venv\Scripts\streamlit.exe run app.py
```

The `.venv` folder and `app.py` file are in `AMS_Streamlit`, not inside `AMS_Streamlit\BlueSG`.

## First-Time Setup Or Repair

Run these from the project root:

```powershell
cd "C:\Users\popla\OneDrive\Desktop\AMS_Streamlit"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then start the app:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

## If Streamlit Still Cannot Start

Use Python to run Streamlit directly:

```powershell
cd "C:\Users\popla\OneDrive\Desktop\AMS_Streamlit"
.\.venv\Scripts\python.exe -m streamlit run app.py
```

If that says Streamlit is missing, reinstall the requirements:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## BlueSG Vehicle Route Optimiser

Start the main app, then choose the BlueSG page from the Streamlit sidebar.

The job upload supports the normal route optimiser format and the Antares/Flexar RB Jobs format. If the uploaded Excel file contains multiple dates, choose the date from the **Job date** dropdown before optimising.

### Streamlit Community Cloud Deployment

This app is intended for BlueSG vehicle rostering and route optimisation.

Use these Streamlit Community Cloud settings:

```text
Repository: DrPinguJr/AMS_Streamlit
Branch: main
Main file path: BlueSG/Vehicle_Route_Optimiser.py
```

Add these Streamlit secrets before enabling OneMap routing:

```toml
ONEMAP_EMAIL = "your-email"
ONEMAP_PASSWORD = "your-password"
```

The tracked files in `BlueSG/cache/` are used as seed cache data. New runtime cache entries are written to `BlueSG/cache/runtime/`, which is ignored by Git and may be temporary on Streamlit Community Cloud.

## Useful Commands

Run with hot reload:

```powershell
.\.venv\Scripts\streamlit.exe run app.py --server.runOnSave true
```

Run the Tender scraper directly:

```powershell
.\.venv\Scripts\python.exe Tender\Tender.py
```

Re-process an existing Tender CSV:

```powershell
.\.venv\Scripts\python.exe Tender\TenderProcess.py "Tender\Excel Sheets\151514_TenderBoard.csv"
```

## Credentials

BlueSG OneMap credentials are read from Streamlit secrets in deployment and from the local `.env` file in development.
