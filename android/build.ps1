# Builds Lodestar for Android: android\lodestar.apk (a debug-signed APK you can install on your own phone).
# Needs the toolchain under %USERPROFILE%\Android (jdk, sdk, gradle), or JAVA_HOME / ANDROID_HOME / GRADLE set.
# Usage:  powershell -ExecutionPolicy Bypass -File android\build.ps1   (add -Test to also run unit tests and lint)
param([switch]$Test)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$tools = Join-Path $env:USERPROFILE 'Android'
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = Join-Path $tools 'jdk' }
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $tools 'sdk' }
$gradle = if ($env:GRADLE) { $env:GRADLE } else { Join-Path $tools 'gradle\bin\gradle.bat' }
foreach ($p in @("$env:JAVA_HOME\bin\java.exe", "$env:ANDROID_HOME\platforms\android-35\android.jar", $gradle)) {
    if (-not (Test-Path $p)) { throw "missing $p : install the toolchain first (see android\README.md)" }
}
Set-Content -Encoding ascii (Join-Path $here 'local.properties') ("sdk.dir=" + ($env:ANDROID_HOME -replace '\\', '\\'))
# every build is newer than the last (minutes since 2026-01-01 UTC): the phone app updates itself to it from Lodestar
$now = (Get-Date).ToUniversalTime()
$code = [int][math]::Floor(($now - [datetime]'2026-01-01').TotalMinutes)
$name = $now.ToString('yyyy.MM.dd-HHmm')
$tasks = @("-PlodestarCode=$code", "-PlodestarName=$name", 'assembleDebug')
if ($Test) { $tasks += @('testDebugUnitTest', 'lintDebug') }
Push-Location $here
try {
    & $gradle --no-daemon --console=plain @tasks
    if ($LASTEXITCODE -ne 0) { throw "gradle failed ($LASTEXITCODE)" }
} finally { Pop-Location }
$apk = Join-Path $here 'app\build\outputs\apk\debug\app-debug.apk'
Copy-Item $apk (Join-Path $here 'lodestar.apk') -Force
# what Lodestar's phone listener offers (/phone/app.json); written after the APK so it never names a build not there yet
Set-Content -Encoding ascii (Join-Path $here 'lodestar.version.json') ('{"code": ' + $code + ', "name": "' + $name + '"}')
"built: " + (Join-Path $here 'lodestar.apk') + " (" + [math]::Round((Get-Item $apk).Length / 1KB) + " KB, build $code / $name)"
