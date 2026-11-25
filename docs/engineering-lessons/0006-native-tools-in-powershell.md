# 0006: Native SDK tools under PowerShell and cmd
Status: proposed
Date: 2026-11-18
Area: tooling (Android SDK install)

Observed failure: the Android license step stopped (`$ErrorActionPreference = 'Stop'` turned the SDK manager's normal
stderr into a terminating error); `cmd /c sdkmanager platforms;android-35` installed nothing (cmd splits on `;`);
piped "y" answers were never read.
Root cause: shell quoting and error rules, not the SDK.
Evidence: the empty `sdk` folder after each attempt; the SDK log.
Correction: Start-Process with -RedirectStandardInput from an answers file and quoted package names.
Lesson: run interactive native tools with Start-Process (or a .bat) and a redirected input file; quote arguments that
contain `;`; check the result on disk, not the exit code.
Promoted to: skill (engineering-loop, tooling notes).
