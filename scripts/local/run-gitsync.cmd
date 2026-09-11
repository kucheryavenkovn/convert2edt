@echo off
rem Локальная выгрузка хранилища через gitsync (без Docker), PowerShell 5.1.
rem Примеры:
rem   run-gitsync.cmd                          - fixtures\crs\cf -^> output\local-gitsync
rem   run-gitsync.cmd -PrepareOnly             - только подготовить инструменты
rem   run-gitsync.cmd -Limit 2 -VerboseLog     - пробный прогон на 2 версиях
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-gitsync.ps1" %*
exit /b %ERRORLEVEL%
