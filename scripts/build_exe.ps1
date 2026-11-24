# Builds the standalone dist\lodestar.exe. install.ps1 -Exe and the git hooks (.githooks/post-commit, post-merge) share
# this one PyInstaller line. Without -Force it builds only when an exe is already there (someone opted in with -Exe) and
# the last commit touching what the exe bundles differs from the one it was built from (dist\lodestar.exe.rev).
# PyInstaller reads the working tree: an exe built with uncommitted edits there is stamped "<rev>-dirty" (rebuilt by the
# next commit), and one whose commit moved during the build (a checkout, the updater's merge and rollback) is thrown
# away. The new exe is built aside and then moved in: while the old one is running the move fails, the old exe stays and
# the stamp is not written, so the next commit tries again. One build at a time (build\exe.lock); a second one waits.
param([string]$Dist, [switch]$DryRun, [switch]$Force)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if (-not $Dist) { $Dist = Join-Path $root "dist" }
$exe = Join-Path $Dist "lodestar.exe"
$stamp = "$exe.rev"
$py = Join-Path $root ".venv\Scripts\python.exe"
$bundled = @("lodestar", "assets", "pyproject.toml")

function Get-BundleRev {
  $r = git -C $root log -1 --format=%H -- lodestar assets pyproject.toml
  if (-not $r) { throw "git log found no commit for the bundled paths (is git on PATH?)" }
  return $r
}
function Test-Due {
  if ($Force) { return "build (forced)" }
  if (-not (Test-Path $exe)) { return "skip: no exe at $exe (opt in with install.ps1 -Exe)" }
  $rev = Get-BundleRev
  if ((Test-Path $stamp) -and "$(Get-Content $stamp -Raw)".Trim() -eq $rev) { return "up to date: $rev" }
  return "build: $rev"
}

$due = Test-Due
if ($DryRun -or -not $due.StartsWith("build")) { $due; exit 0 }

Push-Location $root  # --add-data paths and the spec are relative to the repo
$lock = $null
try {
  New-Item -ItemType Directory -Force (Join-Path $root "build") | Out-Null
  while (-not $lock) {  # ponytail: waits without a limit; a hung PyInstaller holds it until that process is killed
    try { $lock = [IO.File]::Open((Join-Path $root "build\exe.lock"), "OpenOrCreate", "ReadWrite", "None") }
    catch { Start-Sleep -Seconds 5 }
  }
  $due = Test-Due  # the build we waited for may already cover this commit
  if (-not $due.StartsWith("build")) { $due; exit 0 }
  $rev = Get-BundleRev
  "$(Get-Date -Format s) building $rev"
  & $py -m pip install --quiet --disable-pip-version-check pyinstaller
  if ($LASTEXITCODE -ne 0) { throw "pip could not install PyInstaller (exit $LASTEXITCODE)" }
  $tmp = Join-Path $root "build\exe-new"
  & $py -m PyInstaller --noconfirm --onefile --distpath $tmp --name lodestar --add-data "lodestar/static;lodestar/static" --add-data "lodestar/data;lodestar/data" --add-data "assets;assets" --collect-all keyring --collect-all docx --collect-all webview --icon (Join-Path $root "assets\lodestar.ico") (Join-Path $root "lodestar\__main__.py") | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
  if ((Get-BundleRev) -ne $rev) { throw "the checkout moved during the build; the new exe was discarded (the next commit rebuilds)" }
  if (git -C $root status --porcelain -- $bundled) { $rev = "$rev-dirty" }  # built with uncommitted edits
  New-Item -ItemType Directory -Force $Dist | Out-Null
  try { Move-Item -Force (Join-Path $tmp "lodestar.exe") $exe }
  catch { throw "could not replace $exe (is Lodestar running?): $($_.Exception.Message). The old exe stays; the next commit rebuilds it" }
  Set-Content -Encoding ascii $stamp $rev
  "$(Get-Date -Format s) built $exe from $rev"
} finally {
  if ($lock) { $lock.Close() }
  Pop-Location
}
