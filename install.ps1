# Lodestar installer (Windows). Double-click install.bat, or:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Schedule] [-Every 30] [-NoShortcuts] [-Exe]
#
# Turns this folder into your personal workbot:
#   1. .venv with lodestar and its dependencies
#   2. ~/.lodestar/ data files (profile.md master resume, tracker db, applications/) via `lodestar init`
#   3. .env from .env.example if you do not have one
#   4. Desktop + Start Menu shortcuts: "lodestar" (app: monitor loop + web UI) and "lodestar monitor" (loop only)
#   5. optional -Schedule: a Windows scheduled task running `lodestar run --once` every N minutes, even when the app is closed
#   6. optional -Exe: a standalone dist\lodestar.exe via PyInstaller (no Python needed on the target machine)
param([switch]$Schedule, [int]$Every = 30, [switch]$NoShortcuts, [switch]$Exe)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = $PSScriptRoot

Write-Host "== lodestar installer ==" -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.11+ is required: https://www.python.org/downloads/" }

# 1. environment
if (-not (Test-Path .venv)) { Write-Host "[1/6] creating .venv"; python -m venv .venv } else { Write-Host "[1/6] .venv exists" }
$py = Join-Path $root ".venv\Scripts\python.exe"
$jb = Join-Path $root ".venv\Scripts\lodestar.exe"
foreach ($launcher in @("jobbot.exe", "lodestar.exe")) {  # not $exe: that name is the -Exe switch parameter
  $path = Join-Path $root ".venv\Scripts\$launcher"
  if (Test-Path $path) { try { [IO.File]::Open($path, "Open", "ReadWrite", "None").Close() } catch { throw "$launcher is running (a Lodestar/jobbot window or monitor loop is open). Close it and run the installer again." } }
}
& $py -m pip install --quiet --disable-pip-version-check --upgrade pip
& $py -m pip install --quiet --disable-pip-version-check -e ".[all]"

# 2. data files
Write-Host "[2/6] initializing ~/.lodestar"
& $jb init | Out-Null
$home_ = [Environment]::GetFolderPath("UserProfile")
$dataDir = if ($env:LODESTAR_HOME) { $env:LODESTAR_HOME } else { Join-Path $home_ ".lodestar" }
foreach ($d in @("applications", "snapshots")) { New-Item -ItemType Directory -Force (Join-Path $dataDir $d) | Out-Null }

# 3. .env
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "[3/6] created .env from .env.example (keys can also go in the vault)" } else { Write-Host "[3/6] .env exists" }

# 4. shortcuts
if (-not $NoShortcuts) {
  Write-Host "[4/6] creating shortcuts"
  $ws = New-Object -ComObject WScript.Shell
  $icon = Join-Path $root "assets\lodestar.ico"
  $targets = @(
    @{ Name = "Lodestar";         Args = "desktop";            Desc = "Lodestar: job-search workbot (desktop window + monitor loop)" },
    @{ Name = "Lodestar monitor"; Args = "run --every $Every"; Desc = "Lodestar monitor loop only" }
  )
  foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) "Lodestar"))) {
    New-Item -ItemType Directory -Force $dir | Out-Null
    foreach ($old in @("lodestar.lnk", "lodestar monitor.lnk")) { Remove-Item -Force (Join-Path $dir $old) -ErrorAction SilentlyContinue }
    foreach ($t in $targets) {
      $lnk = $ws.CreateShortcut((Join-Path $dir ($t.Name + ".lnk")))
      $lnk.TargetPath = $jb; $lnk.Arguments = $t.Args; $lnk.WorkingDirectory = $root; $lnk.Description = $t.Desc
      $lnk.IconLocation = if (Test-Path $icon) { "$icon,0" } else { "$env:SystemRoot\System32\shell32.dll,165" }
      $lnk.Save()
    }
  }
  Remove-Item -Recurse -Force (Join-Path ([Environment]::GetFolderPath("Programs")) "lodestar") -ErrorAction SilentlyContinue
} else { Write-Host "[4/6] shortcuts skipped" }

# 5. scheduled task
if ($Schedule) {
  Write-Host "[5/6] registering scheduled task 'lodestar' (every $Every min)"
  schtasks /Create /SC MINUTE /MO $Every /TN lodestar /TR "`"$jb`" run --once" /F | Out-Null
} else { Write-Host "[5/6] scheduled task skipped (re-run with -Schedule, or: lodestar schedule install)" }

# 6. optional standalone exe
if ($Exe) {
  Write-Host "[6/6] building dist\lodestar.exe with PyInstaller (a few minutes)"
  & $py -m pip install --quiet --disable-pip-version-check pyinstaller
  & $py -m PyInstaller --noconfirm --onefile --name lodestar --add-data "lodestar/static;lodestar/static" --add-data "assets;assets" --collect-all keyring --collect-all docx --collect-all webview --icon (Join-Path $root "assets\lodestar.ico") (Join-Path $root "lodestar\__main__.py") | Out-Null
  Write-Host "   dist\lodestar.exe ready (run: dist\lodestar.exe desktop)"
} else { Write-Host "[6/6] standalone exe skipped (re-run with -Exe)" }

Write-Host ""
Write-Host "Installed." -ForegroundColor Green
Write-Host "Next:  1) edit your master resume:  $dataDir\profile.md"
Write-Host "       2) add an AI key:            $jb vault set ANTHROPIC_API_KEY   (or in the app's Setup tab)"
Write-Host "       3) launch the 'Lodestar' shortcut, or:  $jb desktop"
Write-Host "Uninstall: powershell -ExecutionPolicy Bypass -File uninstall.ps1 [-Purge]"
