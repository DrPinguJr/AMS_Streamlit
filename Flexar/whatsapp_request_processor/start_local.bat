@echo off
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\Activate.ps1" (
  echo Missing repository virtual environment at .venv.
  echo Create it with: python -m venv .venv
  exit /b 1
)
start "Flexar FastAPI" powershell -NoExit -ExecutionPolicy Bypass -Command ".\.venv\Scripts\Activate.ps1; uvicorn Flexar.whatsapp_request_processor.api:app --host 127.0.0.1 --port 8000 --reload"
start "AMS Streamlit" powershell -NoExit -ExecutionPolicy Bypass -Command ".\.venv\Scripts\Activate.ps1; streamlit run app.py"
