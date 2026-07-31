@echo off
REM Double-click target for setting Railway deployment secrets.
REM Bypasses execution policy for this one script only; nothing is installed
REM and nothing is deployed.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0set-railway-secrets.ps1" %*
echo.
pause
