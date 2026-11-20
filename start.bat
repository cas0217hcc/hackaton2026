@echo off
rem Start the Azure to Leaseweb Migration Assistant on Windows (runs start.ps1 without changing your execution policy).
rem Options are passed on, for example:  start.bat -Port 9000 -Reload
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %ERRORLEVEL%
