@echo off
rem lodestar installer: double-click. Creates .venv, data files, shortcuts. Add -Schedule for a background task, -Exe for a standalone exe.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
