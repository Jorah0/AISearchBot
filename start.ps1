# Lodestar runtime starter (Windows).
# Double-click start.bat, or:  powershell -ExecutionPolicy Bypass -File start.ps1 [-NoLoop] [-NoUI] [-Every 30] [-Port 8765]
# Creates .venv, installs lodestar into it, initializes ~/.lodestar, starts the monitor loop minimized, opens the web UI.
param([switch]$NoLoop, [switch]$NoUI, [int]$Every = 30, [int]$Port = 8765)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { Write-Host "creating .venv ..."; python -m venv .venv }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$jb = Join-Path $PSScriptRoot ".venv\Scripts\lodestar.exe"
& $py -m pip install --quiet --disable-pip-version-check -e .
& $jb init
& $jb providers
if (-not $NoLoop) {
  Start-Process -FilePath $jb -ArgumentList "run --every $Every" -WindowStyle Minimized
  Write-Host "monitor loop started: every $Every min (minimized window). Permanent: lodestar schedule install"
}
if ($NoUI) { Write-Host "UI skipped. Run: .venv\Scripts\lodestar.exe ui" } else { & $jb ui --port $Port }
