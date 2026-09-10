@echo off
rem Универсальный запуск локального конвертера (без Docker), PowerShell 5.1.
rem Примеры:
rem   run-local.cmd                                    - sync-all по scripts\local\sync.local.toml
rem   run-local.cmd 'info'                             - версии инструментов
rem   run-local.cmd 'selfcheck'
rem   run-local.cmd 'storage-info','D:\crs\cf'         - аргументы в одинарных кавычках, через запятую
rem   run-local.cmd -DownloadOnly
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0run-local.ps1' -CommandArgs @(%*)"
exit /b %ERRORLEVEL%
