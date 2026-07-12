@echo off
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\Activate.ps1" (
  echo Missing repository virtual environment at .venv.
  echo Create it with: python -m venv .venv
  exit /b 1
)
powershell -ExecutionPolicy Bypass -Command ".\.venv\Scripts\Activate.ps1; python -m pytest Flexar\whatsapp_request_processor\tests -v"
