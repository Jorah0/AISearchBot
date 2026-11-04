# Lodestar uninstaller:  powershell -ExecutionPolicy Bypass -File uninstall.ps1 [-Purge]
# Removes shortcuts, the scheduled task, and .venv. Your data in ~/.lodestar (resume, tracker, documents) is KEPT
# unless you pass -Purge. Secrets in the OS keyring are never touched (remove with: lodestar vault rm NAME).
param([switch]$Purge)
Set-Location $PSScriptRoot
foreach ($t in @("lodestar", "jobbot")) { schtasks /Delete /TN $t /F 2>$null | Out-Null }
$programs = [Environment]::GetFolderPath("Programs")
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $programs "Lodestar"), (Join-Path $programs "lodestar"))) {
  foreach ($n in @("Lodestar.lnk", "Lodestar monitor.lnk", "lodestar.lnk", "lodestar monitor.lnk")) { Remove-Item -Force (Join-Path $dir $n) -ErrorAction SilentlyContinue }
}
foreach ($d in @("Lodestar", "lodestar")) { Remove-Item -Recurse -Force (Join-Path $programs $d) -ErrorAction SilentlyContinue }
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
foreach ($d in @("build", "dist", "lodestar.spec")) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
if ($Purge) {
  $dataDir = if ($env:LODESTAR_HOME) { $env:LODESTAR_HOME } else { Join-Path ([Environment]::GetFolderPath("UserProfile")) ".lodestar" }
  if (Test-Path $dataDir) { Remove-Item -Recurse -Force $dataDir; Write-Host "purged $dataDir" }
}
Write-Host "lodestar uninstalled." -ForegroundColor Green
