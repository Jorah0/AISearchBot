@echo off
rem lodestar one-click starter: creates .venv, installs, starts the monitor loop and opens the web UI.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
