@echo off
rem Проверка зависимостей локального режима (без Docker), PowerShell 5.1.
rem   check-deps.cmd              - полная проверка (оба движка)
rem   check-deps.cmd -Engine gitsync   - только движок gitsync
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-deps.ps1" %*
exit /b %ERRORLEVEL%
