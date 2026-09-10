@echo off
rem Синхронизация всех хранилищ/обработок в монорепо (локально, без Docker).
rem Конфиг: scripts\local\sync.local.toml
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0run-local.ps1' -CommandArgs @(%*)"
exit /b %ERRORLEVEL%
