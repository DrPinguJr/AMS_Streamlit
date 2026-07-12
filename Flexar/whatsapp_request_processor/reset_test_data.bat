@echo off
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
  echo Missing repository virtual environment at .venv.
  exit /b 1
)
set /p CONFIRM=Type RESET to clear simulator data in the configured local database: 
if /I not "%CONFIRM%"=="RESET" (
  echo Reset cancelled.
  exit /b 0
)
".venv\Scripts\python.exe" -c "from Flexar.whatsapp_request_processor.config import get_settings; from Flexar.whatsapp_request_processor.database import Database; s=get_settings(); db=Database(s); db.reset_all(); print('Simulator data reset at', s.database_path)"
