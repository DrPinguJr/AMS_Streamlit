@echo off
setlocal
title Stop AMS WhatsApp Operations System
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Flexar\whatsapp_request_processor\scripts\stop_ams_whatsapp.ps1"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%
