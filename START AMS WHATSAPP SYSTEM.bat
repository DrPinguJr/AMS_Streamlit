@echo off
setlocal
title AMS WhatsApp Operations System
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Flexar\whatsapp_request_processor\scripts\start_ams_whatsapp.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] The AMS WhatsApp Operations System did not start completely.
  echo Review the message above or contact the system administrator.
  pause
)
exit /b %EXIT_CODE%
