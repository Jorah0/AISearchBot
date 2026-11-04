# Lodestar runtime starter (Windows).
# Double-click start.bat, or:  powershell -ExecutionPolicy Bypass -File start.ps1 [-NoLoop] [-NoUI] [-Every 30] [-Port 8765]
# Creates .venv, installs lodestar into it, initializes ~/.lodestar, starts the monitor loop minimized, opens the web UI.
# Default: opens the desktop window (monitor loop inside). -Browser: minimized loop + web UI in the browser instead.
param([switch]$NoLoop, [switch]$NoUI, [switch]$Browser, [int]$Every = 30, [int]$Port = 0)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) { Write-Host "creating .venv ..."; python -m venv .venv }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$jb = Join-Path $PSScriptRoot ".venv\Scripts\lodestar.exe"
& $py -m pip install --quiet --disable-pip-version-check -e ".[all]"
& $jb init
& $jb providers
if (-not $Browser) {
  $args_ = @("desktop", "--every", "$Every"); if ($NoLoop) { $args_ += "--no-loop" }; if ($Port -gt 0) { $args_ += @("--port", "$Port") }
  & $jb @args_
  exit
}
if (-not $NoLoop) {
  Start-Process -FilePath $jb -ArgumentList "run --every $Every" -WindowStyle Minimized
  Write-Host "monitor loop started: every $Every min (minimized window). Permanent: lodestar schedule install"
}
if ($NoUI) { Write-Host "UI skipped. Run: .venv\Scripts\lodestar.exe ui" } else { if ($Port -gt 0) { & $jb ui --port $Port } else { & $jb ui } }
