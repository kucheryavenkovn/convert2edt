@echo off
rem Сервер хранилища конфигураций 1С (crserver) локально, PowerShell 5.1.
rem   run-crs.cmd                 - storage-crs, порт 1542
rem   run-crs.cmd -Port 1543      - другой порт
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-crs.ps1" %*
exit /b %ERRORLEVEL%
