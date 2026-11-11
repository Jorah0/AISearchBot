# Lodestar setup and operations guide

Lodestar is a personal job-search assistant that runs on your own computer. It tracks the jobs you are going for,
builds resumes, cover letters and form answers from your own facts, reads hiring mail in your mailbox and files it under
the right job, watches job boards and career pages, prepares you for interviews, and puts anything it wants to do on
its own (send a reply, move a job, add a job) in an **Inbox** for your approval. It is a Python program with a local web
interface on `127.0.0.1`, shown in its own desktop window or in your browser. This guide covers installing it,
connecting an AI provider and your mailbox, every component of the app and how to run each one from the app and from
the `lodestar` command, where your data lives, backups and updates, troubleshooting, and working on the code.

Date: 2026-11-10. Written for Windows 10/11 (commands are PowerShell); macOS and Linux notes are given where the code
supports them.

## Contents

- [Quick start (15 minutes)](#quick-start-15-minutes)
- [Before you start: how to read this guide](#before-you-start-how-to-read-this-guide)
  - [Commands](#commands)
  - [The app at a glance](#the-app-at-a-glance)
  - [The safety rules](#the-safety-rules)
  - [Reference documents](#reference-documents)
- [Install and run Lodestar](#install-and-run-lodestar)
  - [What you need](#what-you-need)
  - [Get the code](#get-the-code)
  - [Windows: install.bat and install.ps1](#windows-installbat-and-installps1)
  - [The scheduled task](#the-scheduled-task)
  - [The standalone exe](#the-standalone-exe)
  - [macOS and Linux: install.sh](#macos-and-linux-installsh)
  - [Quick start without installing shortcuts: start.bat, start.ps1, start.sh](#quick-start-without-installing-shortcuts-startbat-startps1-startsh)
  - [Manual install with pip](#manual-install-with-pip)
  - [Running `lodestar` commands](#running-lodestar-commands)
  - [Uninstall: uninstall.ps1](#uninstall-uninstallps1)
  - [First run](#first-run)
  - [Ways to run Lodestar](#ways-to-run-lodestar)
  - [The monitor loop: what each cycle does](#the-monitor-loop-what-each-cycle-does)
  - [Where your data lives](#where-your-data-lives)
  - [Settings and secrets: .env and the keyring vault](#settings-and-secrets-env-and-the-keyring-vault)
  - [lodestar doctor](#lodestar-doctor)
  - [Backups, export and restore](#backups-export-and-restore)
  - [Obsidian export](#obsidian-export)
  - [Auto-update](#auto-update)
  - [Moving to a new PC](#moving-to-a-new-pc)
- [Connections: AI keys, local models, secrets and email](#connections-ai-keys-local-models-secrets-and-email)
  - [Where secrets and connection data live](#where-secrets-and-connection-data-live)
  - [AI keys](#ai-keys)
  - [Local models (Ollama)](#local-models-ollama)
  - [Choose models, the default provider and council providers](#choose-models-the-default-provider-and-council-providers)
  - [Other secrets (the vault)](#other-secrets-the-vault)
  - [Market pay (BLS)](#market-pay-bls)
  - [Email: pick a way to connect](#email-pick-a-way-to-connect)
  - [Email with an app password](#email-with-an-app-password)
  - [Email with Sign in with Google (Gmail)](#email-with-sign-in-with-google-gmail)
  - [Email with Sign in with Microsoft (Outlook.com, Hotmail, Live, Microsoft 365)](#email-with-sign-in-with-microsoft-outlookcom-hotmail-live-microsoft-365)
  - [Test, re-sign-in and disconnect](#test-re-sign-in-and-disconnect)
  - [Emailed sign-in codes](#emailed-sign-in-codes)
  - [Attachments](#attachments)
  - [Notification email address](#notification-email-address)
  - [Email commands](#email-commands)
- [Profile and documents](#profile-and-documents)
  - [Quick start: from nothing to a finished resume](#quick-start-from-nothing-to-a-finished-resume)
  - [The master profile (profile.md)](#the-master-profile-profilemd)
  - [The profile bank](#the-profile-bank)
  - [Importing resumes and LinkedIn exports (with review)](#importing-resumes-and-linkedin-exports-with-review)
  - [The master resume](#the-master-resume)
  - [PDF engines](#pdf-engines)
  - [The resume studio](#the-resume-studio)
  - [The document viewer and formatting panel](#the-document-viewer-and-formatting-panel)
  - [Tailoring a resume for a job](#tailoring-a-resume-for-a-job)
  - [JD coverage and the gap check](#jd-coverage-and-the-gap-check)
  - [Resume check (lint) and file audit](#resume-check-lint-and-file-audit)
  - [Cover letters](#cover-letters)
  - [Form answers and the answer bank](#form-answers-and-the-answer-bank)
  - [Company research packs](#company-research-packs)
  - [AI suggestions on every tab (Recommend, Apply suggestions, Full AI, Undo)](#ai-suggestions-on-every-tab-recommend-apply-suggestions-full-ai-undo)
  - [Settings in this area](#settings-in-this-area)
  - [Safety rules in this area, in short](#safety-rules-in-this-area-in-short)
- [Finding and tracking jobs](#finding-and-tracking-jobs)
  - [Job search (Search tab, `lodestar jobs search`)](#job-search-search-tab-lodestar-jobs-search)
  - [The fit score](#the-fit-score)
  - [All jobs and job sources](#all-jobs-and-job-sources)
  - [Job-alert emails (LinkedIn, Indeed, Glassdoor, ZipRecruiter)](#job-alert-emails-linkedin-indeed-glassdoor-ziprecruiter)
  - [The listing monitor and Listing activity](#the-listing-monitor-and-listing-activity)
  - [Job intelligence](#job-intelligence)
  - [Chance boosters](#chance-boosters)
  - [Saved searches (watches on a query)](#saved-searches-watches-on-a-query)
  - [Page watches (career pages) and robots.txt](#page-watches-career-pages-and-robotstxt)
  - [Company boards (Greenhouse, Lever, Ashby)](#company-boards-greenhouse-lever-ashby)
  - [Stale signals and the weekly posting check](#stale-signals-and-the-weekly-posting-check)
  - [H-1B sponsor hints (optional)](#h-1b-sponsor-hints-optional)
  - [Browser extension](#browser-extension)
  - [Capture and Autofill bookmarklets](#capture-and-autofill-bookmarklets)
  - [Adding jobs by hand](#adding-jobs-by-hand)
  - [Statuses](#statuses)
  - [The Board](#the-board)
  - [The job drawer](#the-job-drawer)
  - [Today and the agenda](#today-and-the-agenda)
  - [Follow-up cadence](#follow-up-cadence)
  - [The step-by-step pipeline](#the-step-by-step-pipeline)
  - [The Inbox and approvals](#the-inbox-and-approvals)
- [Mail, people, interviews and outcomes](#mail-people-interviews-and-outcomes)
  - [The email monitor (Check email)](#the-email-monitor-check-email)
  - [How Lodestar decides whether mail is trusted](#how-lodestar-decides-whether-mail-is-trusted)
  - [Mail linked to jobs, and Unmatched mail](#mail-linked-to-jobs-and-unmatched-mail)
  - [Replies and drafts, with AI options and rewrites](#replies-and-drafts-with-ai-options-and-rewrites)
  - [Suggested emails](#suggested-emails)
  - [Contacts (people, LinkedIn import, warm paths, touches)](#contacts-people-linkedin-import-warm-paths-touches)
  - [Interview rounds, calendar files and reminders](#interview-rounds-calendar-files-and-reminders)
  - [Question bank](#question-bank)
  - [STAR stories](#star-stories)
  - [Interview prep and mock interviews](#interview-prep-and-mock-interviews)
  - [Offers, the comp table and counter-offers](#offers-the-comp-table-and-counter-offers)
  - [Insights and weekly goals](#insights-and-weekly-goals)
  - [Activity log export](#activity-log-export)
  - [The weekly digest](#the-weekly-digest)
  - [Desktop notifications](#desktop-notifications)
- [For developers and maintenance](#for-developers-and-maintenance)
  - [Developer setup](#developer-setup)
  - [Repo layout](#repo-layout)
  - [Running the unit suite](#running-the-unit-suite)
  - [Running the browser (E2E) suite](#running-the-browser-e2e-suite)
  - [The test matrix (docs/TESTS.md) and its guard](#the-test-matrix-docstestsmd-and-its-guard)
  - [Coverage](#coverage)
  - [CI](#ci)
  - [Knowledge graph and the Obsidian mirror](#knowledge-graph-and-the-obsidian-mirror)
  - [Project conventions (CLAUDE.md, summarised)](#project-conventions-claudemd-summarised)
  - [Adding a feature safely](#adding-a-feature-safely)
  - [Logs: where to look](#logs-where-to-look)
- [Troubleshooting](#troubleshooting)
- [Coming later](#coming-later)

## Quick start (15 minutes)

The shortest path from nothing to a working app with an AI key, your mailbox connected and your resume imported. Each
step links to its full section. You need a Windows PC, an internet connection, an account with an AI provider (Gemini
and Groq have free tiers; [Local models (Ollama)](#local-models-ollama) need no account) and an email account.

1. **Check Python.** In a new PowerShell window run `python --version`. You should see `Python 3.11` or newer. If not,
   install Python from https://www.python.org/downloads/ and open a new window. See [What you need](#what-you-need).
2. **Get the code** into a permanent folder (not Downloads):

   ```powershell
   git clone https://github.com/Jorah0/AISearchBot.git
   cd AISearchBot
   ```

   See [Get the code](#get-the-code).
3. **Install.** Double-click `install.bat`, or run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

   You should see the steps `[1/6]` to `[6/6]`, a green `Installed.` line, and two new shortcuts, **Lodestar** and
   **Lodestar monitor**. On macOS or Linux run `./install.sh`. See [Windows: install.bat and install.ps1](#windows-installbat-and-installps1) and
   [macOS and Linux: install.sh](#macos-and-linux-installsh).
4. **Open Lodestar** with the **Lodestar** shortcut. On a fresh install the window opens on the **Setup** tab. See
   [First run](#first-run).
5. **Link an AI key.** Setup > **Link an AI key**: pick the provider, paste the key, click **Link**. You should see a
   green **Verified** pill. Or, in PowerShell in the install folder:

   ```powershell
   .venv\Scripts\Activate.ps1
   lodestar keys link anthropic
   ```

   No paid key? Install Ollama and click **Local only (Ollama)**. See [AI keys](#ai-keys).
6. **Connect your mailbox.** Setup > **Connect email**. The quickest way is an app password (Gmail, Yahoo, iCloud,
   Fastmail, Zoho, AOL): create one on your provider's page, paste it, click **Connect & test**, then **Send me a test
   email**. In the terminal:

   ```powershell
   lodestar email connect --user you@gmail.com
   lodestar email test-send
   ```

   Outlook.com, Hotmail, Live and Microsoft 365 need **Sign in with Microsoft**, which takes a one-time client setup
   of about 10 minutes (Sign in with Google likewise). See [Email: pick a way to connect](#email-pick-a-way-to-connect).
7. **Import your resume.** Profile tab > **Import an existing resume** > **Import**, then **Accept all new** in the
   review. In the terminal (use the id the import prints):

   ```powershell
   lodestar profile import "$HOME\Documents\resume.docx"
   lodestar profile review <id> --accept new
   ```

   Then open your master profile on the Profile tab and fill in the Preferences line (target roles, locations, salary
   floor, deal-breakers); it stays private. See [Importing resumes and LinkedIn exports (with review)](#importing-resumes-and-linkedin-exports-with-review) and
   [The master profile (profile.md)](#the-master-profile-profilemd).
8. **Check the install.** Run `lodestar doctor`. It should end with `all good` or `usable; see WARN lines`. See
   [lodestar doctor](#lodestar-doctor).
9. **Start using it.** Track a job (Board > **Add job**, or
   `lodestar jobs add "Acme" "Backend Engineer" --jd https://acme.com/jobs/123`) and run its steps from the job drawer.
   To keep checking mail while the window is closed, add the background task: `lodestar schedule install --every 30`.
   See [Adding jobs by hand](#adding-jobs-by-hand), [The step-by-step pipeline](#the-step-by-step-pipeline) and [The scheduled task](#the-scheduled-task).

## Before you start: how to read this guide

### Commands

- Commands are written as `lodestar ...`. The installer does not put `lodestar` on your PATH: in PowerShell, from the
  install folder, run `.venv\Scripts\lodestar.exe ...`, or run `.venv\Scripts\Activate.ps1` once per window and then
  type `lodestar ...`. Details in [Running `lodestar` commands](#running-lodestar-commands). On macOS and Linux: `.venv/bin/lodestar ...`, or
  `source .venv/bin/activate` first.
- Every command group has help: `lodestar -h`, `lodestar jobs --help`, `lodestar pipeline run --help`.
- `~/.lodestar` means your data folder: `%USERPROFILE%\.lodestar` on Windows, unless `LODESTAR_HOME` points elsewhere
  ([Where your data lives](#where-your-data-lives)).
- `JOB` or `ID` is a job number from `lodestar jobs list`, or the `#N` on a Board card.
- `-p PROVIDER` before the command name picks the AI provider for one command (`lodestar -p groq pipeline run 1`).
- To try something without touching your real data, set `$env:LODESTAR_HOME` to an empty folder in that PowerShell
  window first. That folder also gets its own keyring namespace, so it cannot see or change the keys and mail login of
  your real install ([Settings and secrets](#settings-and-secrets-env-and-the-keyring-vault)). Values in a `.env` file
  still apply to it.

### The app at a glance

- **Left sidebar** (the tabs): **Board** (your tracked jobs, Today, Getting started), **Inbox** (approvals, questions,
  sign-in codes, unmatched mail), **Contacts**, **Search**, **Monitor** (watches, company boards, alerts, digest),
  **Ideas** (idea crafting across providers, `lodestar ideas`), **Answers** (answer bank, form answers, STAR stories),
  **Coach** (career-coach chat, `lodestar chat`, and mock interviews), **Insights**, **Profile**, **Studio**, and at
  the bottom **Tools** (tool switches and preferences) and **Setup** (keys, email, data, updates, diagnostics).
- **Top bar**: **Check email**, **Run watches**, the monitor-loop status line, the **Autopilot** pill, and badges such
  as **Update available** or **Codes** when they apply.
- **Job drawer**: the panel that opens when you click a card on the Board ([The job drawer](#the-job-drawer)). Esc closes it.
- **Command palette**: Ctrl+K (Cmd+K on a Mac) anywhere. Type a few letters of a tab, job, contact, document or
  setting, or an action (Add job, Check email, Run watches, Recommend on this tab, Open Today); arrows move, Enter
  runs, Esc closes and gives focus back. The letters only need to appear in order.

### The safety rules

These hold everywhere in Lodestar. Each component below repeats the part that applies to it.

1. **Approvals.** Anything Lodestar decides to do on its own (send mail, change a job's status, add a job, save an
   answer, run a batch of pipeline steps) waits in the **Inbox** unless you set that tool to auto. Some things always
   wait, even on auto ([The Inbox and approvals](#the-inbox-and-approvals)). Commands you type and buttons you click are your own decision and
   run at once.
2. **Salary floor privacy.** The Preferences section of your master profile (salary floor, deal-breakers, target roles)
   guides ranking and advice only. It never goes into anything an employer reads (resumes, letters, mail, form
   answers); a document, draft or attachment that names your floor is refused.
3. **Mail trust.** Mail can act without your review only when it is authenticated (aligned DKIM/DMARC) and strongly
   tied to a job you track. Everything else is filed for you to look at ([How Lodestar decides whether mail is trusted](#how-lodestar-decides-whether-mail-is-trusted)).
4. **You apply yourself.** Nothing submits an application; Autofill fills empty contact fields and stops.
5. **Local only.** The UI listens on `127.0.0.1`, so other computers cannot open it. Secrets live in the OS keyring,
   never in the data folder, logs, exports or backups.

### Reference documents

This guide explains how to set up and run each part. The full references are:

| Document | Holds |
|---|---|
| [CONNECT.md](CONNECT.md) | Linking AI keys and email, provider by provider, and the sign-in error table |
| [COMMANDS.md](COMMANDS.md) | Every command with its options |
| [AUTOMATION.md](AUTOMATION.md) | Tool switches, the Inbox, the automatic cycle, the pipeline and the security model of the local UI |
| [TESTS.md](TESTS.md) | The test matrix: every feature and the tests that cover it, plus what is planned |
| [FEATURES.md](FEATURES.md) | The generated inventory of every command, tool and preference |
| [CAPTURE.md](CAPTURE.md) | The bookmarklet code |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each version |

## Install and run Lodestar

This section takes you from an empty PC to a running Lodestar: what you need, every installer and its switches, a
manual install, the first run, the different ways to run it, where your data lives, how secrets are stored, health
checks, backups, updates and moving to a new computer.

Lodestar runs entirely on your own computer. The app is a small web server bound to `127.0.0.1` (your machine only),
shown either in its own desktop window or in your browser. Your data lives in one folder in your user profile, and
secrets (AI keys, mail passwords and sign-ins, site logins) live in the operating system's keyring, never in that
folder.

### What you need

| Need | Details |
|---|---|
| Python | 3.11 or newer (`requires-python = ">=3.11"` in `pyproject.toml`). The test suite runs on 3.11, 3.12, 3.13 and 3.14 on Windows and Ubuntu. |
| Operating system | Windows 10/11 is the main target (installer, shortcuts, scheduled task, desktop window). Linux and macOS have their own installer (`install.sh`); macOS is not part of the automated test runs. |
| Desktop window (Windows) | The Microsoft Edge WebView2 runtime. Without it the same UI opens in your browser instead. `lodestar doctor` tells you whether it was found. |
| PDF export | Nothing extra on Windows 11: Lodestar prints PDFs with Microsoft Edge in the background. On macOS and Linux it uses Chrome, Edge or Chromium, else Microsoft Word or LibreOffice, else it opens a print page in your browser. `LODESTAR_BROWSER` can point at any Chromium-based browser. |
| git | Only for automatic updates of a git install (`lodestar update`). Not needed to run Lodestar. |
| Internet during install | `pip` downloads the dependencies (`keyring`, `python-docx`, and with the extras `pywebview`, `pypdf`). |

Check your Python in a new PowerShell window:

```powershell
python --version
```

You should see `Python 3.11.x` or newer. If the command is not found, or the version is older, install Python 3.11+
from https://www.python.org/downloads/ and open a new PowerShell window. On macOS and Linux the installers use
`python3`.

### Get the code

The folder you install from becomes the install: the virtual environment (`.venv`), the shortcuts, the scheduled task
and the updater all point at it. Put it somewhere permanent before installing (for example your user folder), not in
Downloads or a temp folder.

```powershell
git clone https://github.com/Jorah0/AISearchBot.git
cd AISearchBot
```

That is the project's origin repository. A copy made with `git clone` can update itself later (see "Auto-update"). A
copy without the `.git` folder (a plain zip download or a copied folder) runs the same, but Setup > Updates and
`lodestar update check` then say "not a git install: reinstall with install.ps1 / install.sh to get updates".

If you move the folder after installing, run the installer again from the new place: the shortcuts and the scheduled
task still point at the old path until you do.

### Windows: install.bat and install.ps1

`install.bat` is a double-click wrapper around `install.ps1` (it runs PowerShell with `-ExecutionPolicy Bypass`, passes
your switches through, and pauses at the end so you can read the output).

**Steps**

1. Close Lodestar if it is running (the window, the "Lodestar monitor" window, any `lodestar` command). The installer
   refuses to run while `.venv\Scripts\lodestar.exe` or `jobbot.exe` is in use.
2. Double-click `install.bat` in the install folder. Or, for switches, open PowerShell in the install folder and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   powershell -ExecutionPolicy Bypass -File install.ps1 -Schedule -Every 30
   powershell -ExecutionPolicy Bypass -File install.ps1 -NoShortcuts
   powershell -ExecutionPolicy Bypass -File install.ps1 -Exe
   ```

   (`install.bat -Schedule` works too: the switches are passed on.)
3. Wait for the six numbered steps (`[1/6]` to `[6/6]`) and the green `Installed.` line.
4. Follow the three "Next" lines it prints: edit your master resume, add an AI key, launch the Lodestar shortcut.

**Switches**

| Switch | Default | What it does |
|---|---|---|
| `-Schedule` | off | Registers a Windows scheduled task named `lodestar` that runs `lodestar run --once` every `-Every` minutes, so monitoring continues while the app is closed. |
| `-Every N` | 30 | Minutes between monitor cycles: used by the scheduled task and by the "Lodestar monitor" shortcut (`run --every N`). |
| `-NoShortcuts` | off | Skips the Desktop and Start Menu shortcuts. |
| `-Exe` | off | Also builds a standalone `dist\lodestar.exe` with PyInstaller (see "The standalone exe"). |

**What it does and creates**

| Step | Result |
|---|---|
| Python check | Stops with "Python 3.11+ is required" if `python` is missing or older than 3.11. |
| `[1/6]` environment | Creates `.venv` in the install folder (kept if it exists), upgrades pip, installs Lodestar in editable mode with the `all` extras (`pip install -e ".[all]"`: the desktop window, PDF import and the apply agent's Playwright; `.[apply]` alone adds only the agent). |
| `[2/6]` data files | Runs `lodestar init` (data folder, `profile.md` template, tracker database) and makes sure `applications\` and `snapshots\` exist. The data folder is `%USERPROFILE%\.lodestar`, or `LODESTAR_HOME` if set in that PowerShell session. |
| `[3/6]` .env | Copies `.env.example` to `.env` in the install folder if you do not have one. |
| `[4/6]` shortcuts | On the Desktop and in the Start Menu folder `Lodestar`: **Lodestar** (runs `lodestar desktop`: the window with the monitor loop inside) and **Lodestar monitor** (runs `lodestar run --every N`: the loop only, in a console window). Both use `assets\lodestar.ico` and start in the install folder. Old lower-case shortcuts from earlier versions are removed. |
| `[5/6]` scheduled task | Only with `-Schedule`: task `lodestar` runs `"<install folder>\.venv\Scripts\lodestar.exe" run --once` every N minutes. Otherwise it prints how to add it later. |
| `[6/6]` standalone exe | Only with `-Exe`: installs PyInstaller into `.venv` and builds `dist\lodestar.exe`. |

The "launcher" the shortcuts call is `.venv\Scripts\lodestar.exe` (pip creates it, plus `jobbot.exe`, the legacy name
for the same command).

**When it worked** you see `Installed.` in green, two new shortcuts named Lodestar and Lodestar monitor, and
`lodestar doctor` (below) prints PASS for Python, the modules and the data folder.

**Re-running the installer** is safe and is how you repair or refresh an install: it keeps `.venv`, `.env` and your
data, reinstalls the package and its dependencies, and rewrites the shortcuts. Changes to `install.ps1` itself (a new
shortcut, a new launcher) only reach your PC when you re-run it.

**When it does not work**

| Message | What to do |
|---|---|
| `Python 3.11+ is required: https://www.python.org/downloads/` | Install Python 3.11+ and open a new PowerShell window so `python` is found, then run the installer again. |
| `Python 3.11+ is required (found Python 3.x.y)` | An older Python comes first on your PATH. Install 3.11+ and make sure `python --version` shows it. |
| `lodestar.exe is running (a Lodestar/jobbot window or monitor loop is open). Close it and run the installer again.` | Close the Lodestar window, the Lodestar monitor window and any console running a `lodestar` command. A scheduled task run that is in progress also counts: wait a minute and retry. |
| pip errors during `[1/6]` | Usually no internet or a proxy. Fix the connection and run the installer again; it picks up where it stopped. |
| Shortcut opens and closes at once | Run `.venv\Scripts\lodestar.exe desktop` in PowerShell from the install folder to read the error, then `.venv\Scripts\lodestar.exe doctor`. |

### The scheduled task

The scheduled task keeps Lodestar checking mail and watches while the app is closed. Each run does one monitor cycle
(`lodestar run --once`) and exits. There are two ways to create it; both make a task named `lodestar` and replace an
existing one of that name.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -Schedule -Every 30   # runs .venv\Scripts\lodestar.exe run --once
.venv\Scripts\lodestar.exe schedule install --every 30                      # runs <python> -m lodestar run --once
.venv\Scripts\lodestar.exe schedule remove                                  # deletes the task
```

`lodestar schedule install` prints the `schtasks` result followed by `(task 'lodestar' runs ... every 30 min)`. You
can also see the task in Windows Task Scheduler under the name `lodestar`.

On macOS and Linux, `lodestar schedule install` does not change anything: it prints the crontab line to add with
`crontab -e` (output goes to `cron.log` in the data folder). `install.sh --schedule` adds that line for you.

Things to know:

- The task uses the data folder the program finds when it starts: `%USERPROFILE%\.lodestar`, or `LODESTAR_HOME` only
  if that is set as a permanent user environment variable (a value set in one PowerShell window does not reach the
  task).
- The task reads settings from the install folder's `.env` even though Windows starts it in another folder.
- Running the task and the app at the same time is safe: two mail scans never overlap (the second one stops with a
  message instead of handling the same message twice).
- The automatic actions the loop may take on its own are set per tool (Tools tab, `lodestar tools list`; see [The Inbox and approvals](#the-inbox-and-approvals)). By default
  only mail classification, interview calendar files and the nightly backup run on their own; replies, follow-ups,
  new jobs and saved answers wait in the Inbox for your approval.

### The standalone exe

`install.ps1 -Exe` builds `dist\lodestar.exe`: one file with Python, Lodestar, the UI, the icon and the keyring, Word
and desktop-window libraries inside. It runs on a Windows PC without Python.

1. Build it (takes a few minutes):

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1 -Exe
   ```

   The installer prints `dist\lodestar.exe ready (run: dist\lodestar.exe desktop)`.
2. Copy `dist\lodestar.exe` wherever you want it, and start it with a command, for example:

   ```powershell
   .\dist\lodestar.exe desktop
   .\dist\lodestar.exe doctor
   ```

Things to know:

- The exe takes the same commands as `lodestar`. Started with no command (a plain double-click) it only prints
  `lodestar: error: the following arguments are required: cmd`. Make a shortcut whose target ends in ` desktop`.
- It uses the same data folder as a Python install (`%USERPROFILE%\.lodestar` or `LODESTAR_HOME`), so both can share
  your data, but not at the same time.
- It reads a `.env` from the folder you start it in or from the data folder (`%USERPROFILE%\.lodestar\.env`), not
  from inside the exe. Secrets belong in the keyring vault either way.
- `lodestar schedule install` run from the exe schedules the exe itself (`"<exe>" run --once`).
- It never updates itself. It is a snapshot of the code at build time: rebuild with `-Exe` after updating the git
  install, or set `update_manifest_url` so it tells you when a newer version is published (see "Auto-update").
- `uninstall.ps1` deletes `dist\` (and `build\`, `lodestar.spec`). Copy the exe elsewhere first if you want to keep it.

### macOS and Linux: install.sh

```sh
./install.sh                         # install
./install.sh --schedule --every 30   # install and add a cron line
```

What it does:

1. Stops with "Python 3.11+ is required" if `python3` is missing or older than 3.11.
2. `[1/5] venv`: creates `.venv` and installs Lodestar in editable mode with the `pdf` extra (`-e ".[pdf]"`). The
   desktop-window extra is not installed here; add it yourself with `.venv/bin/python -m pip install -e ".[desktop]"`
   if you want the native window (otherwise `lodestar desktop` opens the browser).
3. `[2/5] data files`: `lodestar init`.
4. `[3/5] .env`: copies `.env.example` to `.env` if missing.
5. `[4/5]`: on Linux (when `~/.local/share/applications` exists) writes `lodestar.desktop`, a launcher named Lodestar
   that runs `lodestar app` in a terminal with the Lodestar icon. Otherwise (macOS, or Linux without that folder) it
   prints an alias line to add to your shell profile: `alias lodestar='<install folder>/.venv/bin/lodestar'`.
6. `[5/5]`: with `--schedule`, adds `*/N * * * * <install folder>/.venv/bin/lodestar run --once` to your crontab
   (output appended to `cron.log` in the data folder), replacing an earlier Lodestar line. Without it: "background
   task skipped".

It ends with `Installed. Next: edit ~/.lodestar/profile.md, then: ... vault set ANTHROPIC_API_KEY ; ... app`.
`lodestar keys link anthropic` (see "First run") does the same as that `vault set` and also checks the key.

There is no `uninstall.sh`: to remove Lodestar on macOS or Linux, delete the crontab line, the `lodestar.desktop`
file and the install folder; your data stays in `~/.lodestar` until you delete it.

### Quick start without installing shortcuts: start.bat, start.ps1, start.sh

For a trial run, or to start Lodestar from the install folder without shortcuts:

```powershell
start.bat                                                        # double-click: same as start.ps1 with no switches
powershell -ExecutionPolicy Bypass -File start.ps1               # desktop window with the monitor loop inside
powershell -ExecutionPolicy Bypass -File start.ps1 -NoLoop       # window only, no monitor loop
powershell -ExecutionPolicy Bypass -File start.ps1 -Every 15     # loop every 15 minutes
powershell -ExecutionPolicy Bypass -File start.ps1 -Port 8800    # fixed port instead of the first free one
powershell -ExecutionPolicy Bypass -File start.ps1 -Browser      # loop in a minimized window + UI in the browser
powershell -ExecutionPolicy Bypass -File start.ps1 -Browser -NoUI  # loop only (-NoUI needs -Browser)
```

Each start creates `.venv` if needed, runs `pip install -e ".[all]"`, `lodestar init` and `lodestar providers` (the
list of AI providers and whether each is ready), then starts Lodestar.

macOS / Linux:

```sh
./start.sh                  # loop in the background + web UI on port 8765
./start.sh --no-loop        # UI only
./start.sh --no-ui          # loop only
./start.sh --every 15 --port 8800
```

`start.sh` installs without extras, runs the loop with `nohup` and writes its output to `~/.lodestar/run.log`.

### Manual install with pip

For developers, or if you prefer to do each step yourself. From the install folder:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[all]"
.venv\Scripts\lodestar.exe init
.venv\Scripts\lodestar.exe doctor
```

macOS / Linux: `python3 -m venv .venv`, then `.venv/bin/python -m pip install -e ".[all]"` and `.venv/bin/lodestar init`.

Optional extras (from `pyproject.toml`):

| Extra | Installs | Needed for |
|---|---|---|
| (none) | `keyring`, `python-docx` | Everything in the CLI and the browser UI, Word export. |
| `desktop` | `pywebview` | The native desktop window (`lodestar desktop`). Without it the UI opens in the browser. |
| `pdf` | `pypdf` | Importing PDF resumes and the text checks of a PDF audit. |
| `all` | `pywebview`, `pypdf` | Both of the above (what `install.ps1` and `start.ps1` install). |
| `e2e` | `playwright`, `coverage` | Only for running the browser test suite. |

```powershell
.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.venv\Scripts\python.exe -m pip install -e ".[pdf]"
.venv\Scripts\python.exe -m pip install -e ".[e2e]"
```

`-e` (editable) matters: the updater fast-forwards this folder and the installed command follows it. A manual install
creates no shortcuts and no scheduled task; use `lodestar schedule install` for the task.

To check a development install, run the offline unit tests (pytest is not used):

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

### Running `lodestar` commands

The installers do not put `lodestar` on your PATH. In PowerShell, from the install folder, either call it by path:

```powershell
.venv\Scripts\lodestar.exe doctor
```

or activate the environment once per PowerShell window and then type `lodestar`:

```powershell
.venv\Scripts\Activate.ps1
lodestar doctor
```

If PowerShell refuses to run `Activate.ps1` (script execution disabled on your PC), use the full path instead.
`python -m lodestar <command>` with the venv's Python works too (`.venv\Scripts\python.exe -m lodestar doctor`).
On macOS / Linux: `.venv/bin/lodestar <command>`, or `source .venv/bin/activate`. `jobbot` is an old name for the
same command and still works.

### Uninstall: uninstall.ps1

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1          # remove the program, keep your data
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -Purge   # also delete the data folder
```

It removes the scheduled tasks `lodestar` and `jobbot`, the Desktop and Start Menu shortcuts (current and old names)
and the Start Menu folder, `.venv`, and the build output (`build\`, `dist\`, `lodestar.spec`). It prints
`lodestar uninstalled.` in green.

- Your data folder (`%USERPROFILE%\.lodestar`, or `LODESTAR_HOME`) is kept unless you pass `-Purge`. With `-Purge`
  it is deleted completely, backups included: make a copy of `backups\` first if you might want it.
- Secrets in the OS keyring are never touched. Remove them yourself before uninstalling if you want them gone:
  `lodestar keys rm anthropic`, `lodestar email disconnect`, `lodestar vault rm NAME` (`lodestar vault list` shows the
  names). For a data folder set with `LODESTAR_HOME`, run them with that same `LODESTAR_HOME`: each data folder has
  its own keyring namespace.
- The install folder itself, its `.env` and the source code stay; delete the folder afterwards if you want.

### First run

1. Start Lodestar: the **Lodestar** shortcut, or `lodestar desktop`. On a fresh install with no AI key and no jobs
   the window opens on the **Setup** tab once.
2. Or create the data files from the terminal first. `lodestar init` is safe to run again (it never overwrites
   `profile.md`) and prints the next steps:

   ```text
   Lodestar (lodestar) home: C:\Users\you\.lodestar

   1. Edit your master resume:   C:\Users\you\.lodestar\profile.md
   2. Link an AI key:            lodestar keys link anthropic   (or openai, gemini, groq, openrouter, mistral; checked at once)
   3. Optional email:            lodestar email connect   (app password: Gmail, Yahoo, iCloud, Fastmail, Zoho, AOL, Proton, custom)
                                 or lodestar email signin google|microsoft   (any 2-step method; docs/CONNECT.md)
   4. Track a job:               lodestar jobs add "Acme" "Backend Engineer" --jd https://acme.com/jobs/123
   5. Tailor + check fit:        lodestar resume tailor 1 ; lodestar resume gap 1 ; lodestar resume cover 1
   6. Automate:                  lodestar run --every 30
   ```

3. Work through the **Getting started** list at the top of the Board. It shows only what is still missing, and
   disappears when everything is done:
   - **1. Fill in your master resume** (button: Profile), or import one there. From the terminal:

     ```powershell
     lodestar profile import C:\path\to\resume.docx --accept new   # .docx, .pdf, .md or .txt; --no-ai: offline only
     ```

     The `Preferences` part of your profile (target roles, locations, salary floor, deal-breakers) is private: it
     guides ranking and advice but never appears in anything an employer reads (resumes, letters, mail, form
     answers).
   - **2. Link an AI key** (button: Setup). The key is checked at once without spending tokens and kept in the OS
     keyring. From the terminal (the key is asked for and not shown):

     ```powershell
     lodestar keys link anthropic
     lodestar keys
     ```

   - **3. Optional: Connect email**, so replies are classified and drafted. Setup > Connect email, or
     `lodestar email connect --user you@example.com` (app password), or `lodestar email client google` then
     `lodestar email signin google`. The full guide is [Email: pick a way to connect](#email-pick-a-way-to-connect) and [CONNECT.md](CONNECT.md).
   - A red or orange line here means something that worked has stopped: a key that failed its check, an email check
     that failed, an expired email sign-in, or the last update failed or was refused. Each line has a button to the
     place that fixes it.
4. Run `lodestar doctor` (below). When it ends with `all good` or `usable; see WARN lines`, you are set.

### Ways to run Lodestar

| How | Command | What runs | Stop it |
|---|---|---|---|
| Desktop app (recommended) | `lodestar desktop` (the **Lodestar** shortcut) | The UI in its own window (Edge WebView2), the server and the monitor loop in one process. Port: the first free one from 8765. | Close the window. |
| App in the browser | `lodestar app` | The monitor loop in the background and the UI in your browser, on port 8765. | Ctrl+C in its console. |
| UI only | `lodestar ui` | The UI on http://127.0.0.1:8765, no monitor loop. | Ctrl+C. |
| Loop only | `lodestar run` (the **Lodestar monitor** shortcut) | The monitor loop in a console, every 30 minutes by default. No UI. | Ctrl+C or close the console. |
| One cycle | `lodestar run --once` | One monitor cycle, then exit. For schedulers. | Ends by itself. |
| In the background | the scheduled task (Windows) or cron line (macOS/Linux) | `run --once` every N minutes, app open or not. | `lodestar schedule remove`, or delete the cron line. |

Options (all from `--help`):

```text
lodestar desktop [--every 30] [--days 2] [--followup N] [--no-email] [--no-update] [--port N] [--no-loop]
lodestar app     [--every 30] [--days 2] [--followup N] [--no-email] [--no-update] [--port 8765] [--no-open] [--no-loop]
lodestar ui      [--port 8765] [--no-open]
lodestar run     [--every 30] [--days 2] [--followup N] [--no-email] [--no-update] [--once]
```

| Option | Meaning |
|---|---|
| `--every N` | Minutes between monitor cycles (default 30). |
| `--days N` | How many days back each mail check looks (default 2). |
| `--followup N` | Nudge a quiet application after N days (default: the `followup_days` preference, 7). |
| `--no-email` | Skip the mail check in each cycle. |
| `--no-update` | Skip the update check in each cycle. |
| `--port N` | Port for the UI. `desktop` picks the first free port from 8765 when you leave it out; `app` and `ui` use 8765. |
| `--no-open` | `app` / `ui`: do not open a browser tab. |
| `--no-loop` | `desktop`: window only. `app`: UI only. |

What you should see:

- `lodestar desktop` prints `Lodestar desktop on http://127.0.0.1:8765  (close the window to stop)` and opens the
  window. The top bar shows `monitor loop: every 30 min · last cycle HH:MM · N runs`.
- `lodestar app` prints `monitor loop running every 30 min` and `Lodestar ui at http://127.0.0.1:8765  (Ctrl-C to stop)`.
- `lodestar run` prints `--- lodestar cycle HH:MM ---` each cycle, followed by each step's result (for example
  `email: skipped (no mailbox connected: Setup > Connect email)` or `backup: <path>`), and
  ``N action(s) waiting in `lodestar inbox` `` when something needs your approval.

Each cycle checks mail (when connected), runs your watches and company boards, re-checks saved postings weekly,
nudges quiet applications, reminds you of interviews, refreshes pipeline steps (and runs them only when Autopilot is
on), and does notifications, the digest, the nightly backup and the update check when they are due; the full list is in
[The monitor loop: what each cycle does](#the-monitor-loop-what-each-cycle-does). If the window shows `monitor loop: not running in this process`, you
started the UI without the loop (`ui`, or `--no-loop`): monitoring then only happens through the scheduled task or a
separate `lodestar run`.

If the desktop window cannot open (no `pywebview`, no WebView2 runtime, a remote session), Lodestar prints
`desktop window failed (...); opening the browser instead` (or `desktop window needs pywebview ...`), opens the UI in
your browser and waits: `Lodestar is running in your browser. Press Enter here to stop it.`

### The monitor loop: what each cycle does

The monitor loop is the background worker behind everything that happens without a click. It runs inside
`lodestar desktop` and `lodestar app`, in `lodestar run`, and as the scheduled task's `lodestar run --once` (see
[Ways to run Lodestar](#ways-to-run-lodestar) for the commands and options, and [The scheduled task](#the-scheduled-task)). It does not run while Lodestar is
closed or the PC sleeps, unless the scheduled task is installed.

**One cycle, in order** (from `lodestar/loop.py`). Each step is isolated: a failure costs only that step, is printed
as `<step> skipped: <reason>` and shown in the top bar, and the next cycle runs normally.

1. **Email check** ([The email monitor (Check email)](#the-email-monitor-check-email)), with a 2-day lookback (`--days`). Without a connected
   mailbox it prints `email: skipped (no mailbox connected: Setup > Connect email)`.
2. **Watches**: career pages and saved searches, plus watched Greenhouse, Lever and Ashby boards
   ([Saved searches (watches on a query)](#saved-searches-watches-on-a-query), [Company boards (Greenhouse, Lever, Ashby)](#company-boards-greenhouse-lever-ashby)). Strong fits are proposed
   through `auto_track`.
3. **Market pay** (only with the `market_pay` preference on; off by default): the next missing public BLS figure
   for your live jobs, at most one BLS query a cycle and never an AI call ([Market pay (BLS)](#market-pay-bls)).
4. **Posting check** (weekly): saved jobs from those boards whose posting vanished are proposed for `withdrawn`;
   always via the Inbox ([Stale signals and the weekly posting check](#stale-signals-and-the-weekly-posting-check)).
5. **Follow-ups**: every application quiet for `followup_days` gets a `FOLLOW UP:` alert; with a contact address and
   the `followup` tool on, a follow-up draft goes to the Inbox (a plain template without AI). After three follow-ups
   the loop proposes closing the job as ghosted instead of nudging forever ([Follow-up cadence](#follow-up-cadence)).
6. **Interview reminders**: one alert per interview within 48 hours.
7. **Pipeline**: refreshes every live job's step states; with Autopilot on, runs steps within the AI budgets
   ([The step-by-step pipeline](#the-step-by-step-pipeline)).
8. **Desktop notifications**, if you turned them on ([Desktop notifications](#desktop-notifications)).
9. **Obsidian sync**, only if the `obsidian_sync` tool is on ([Obsidian export](#obsidian-export)).
10. **Digest**, weekly, if the `digest` tool is on ([The weekly digest](#the-weekly-digest)).
11. **Backup**: one zip a night into `~/.lodestar/backups` (keeps 7).
12. **Master resume**: rebuilt offline if your profile changed outside the app ([The master resume](#the-master-resume)).
13. **Update check**, every `update_every_hours` (skipped with `--no-update`; [Auto-update](#auto-update)).
14. Prints how many actions wait in the Inbox (``N action(s) waiting in `lodestar inbox` ``).

When a cycle works you see a header like `--- lodestar cycle 18:43 ---` followed by the lines of the steps that had
something to do. The app's top bar shows `monitor loop: every N min · last cycle HH:MM · N runs` and the last problem,
if any.

What each step may do without asking is set per tool; the defaults and the switches are in
[The Inbox and approvals](#the-inbox-and-approvals).

### Where your data lives

Everything Lodestar knows about you is in one folder:

- Windows: `%USERPROFILE%\.lodestar` (for example `C:\Users\you\.lodestar`)
- macOS / Linux: `~/.lodestar`

Setup > Data has buttons that open it: Open data folder, Open documents, Open exports, Open backups, Open log.

| Path (inside the data folder) | What it holds |
|---|---|
| `profile.md` | Your master profile, including the private Preferences section. |
| `profile.json` | The profile bank: facts pooled from your imports, with their sources. |
| `profile-history/` | `profile.md` before each change Lodestar made (last 30). |
| `profile-imports/` | Imports waiting for your review (removed when applied or discarded; dropped after 30 days). |
| `resumes/` | Every imported resume (original plus extracted text) and the master resume: `master.pdf` (or `master.html` without a PDF engine), `.docx`, `.md`, `.txt` and `master.json`. |
| `studio/<version>/` | One folder per build in the Studio tab: the resume files and `plan.json` (request, choices, every guard event). |
| `lodestar.db` | The tracker database: jobs and their timelines (`events`), the Inbox (`pending`), watches, companies, pipeline steps, questions and run log, the answer bank, contacts (`contacts`, `job_contacts`, `touches`), interview rounds (`interviews`), `mock_sessions`, `offers`, mail records (`mail`), sponsor data, and `seen` (once-only reminders, snoozes, scanned messages). |
| `applications/<id>-<company>-<title>/` | Each job's documents: `resume.md` / `.docx` / `.pdf`, `bullets.json`, `coverage.json`, `gap.json`, `cover_letter.md` / `.docx`, `form_answers.md`, `research.md`, `interview_prep.md`, `mock_interview.md`, `offer.md`, `interview-*.ics`. `history/` keeps the previous versions of a regenerated document, `attach/` holds files you add for outgoing mail, `mail/` holds saved attachments of received mail. |
| `settings.json` | Tool switches and preferences (Tools tab, `lodestar tools`). |
| `connections.json` | The result of the last check of each AI key and the mailbox (never a key). |
| `vault_index.json` | Names and usernames of vault entries only; the secrets are in the OS keyring. |
| `comp.json` | Your market-rate table. |
| `draft_options.json` | The last set of draft options, for `--pick`. |
| `capture.token` | The bookmarklet token (delete it to revoke; drag the bookmarklets again afterwards). |
| `extension.json` | Paired browser extensions and their signing secrets (owner-only; never in backups; Setup > Browser extension > Revoke). |
| `viewer.json`, `cache/` | Document viewer formatting per document, and rendered PDFs it can reuse (`cache/view/`). |
| `alerts.log` | Monitor alerts (Monitor tab > Alerts, `lodestar alerts`). |
| `lodestar.log` | Rotating log (2 MB x 3) of commands, UI requests, alerts and failures. |
| `usage.jsonl` | Tokens per AI call (`lodestar usage`). |
| `backups/` | Backup zips (nightly, plus any you make; last 7 kept). |
| `exports/` | JSON / CSV dumps, activity logs, job packets, files opened from the viewer. |
| `snapshots/` | Last page text per watch, for change detection. |
| `update-log.jsonl` | Every update check and update (last 500). |
| `update-state.json` | Present only while an update runs; used to roll back an interrupted update. |
| `procs/` | One file per running app, desktop window or loop, so updates wait for them. |
| `.env` | Optional setting overrides (you create it). |
| `template.docx` | Optional: your Word styles for `.docx` export. |
| `cron.log`, `run.log` | Output of the cron line (`install.sh --schedule`) and of `start.sh`'s background loop. |

**A different data folder: `LODESTAR_HOME`.** Set it to any folder and Lodestar uses that instead. For one PowerShell
window:

```powershell
$env:LODESTAR_HOME = "D:\LodestarData"
.venv\Scripts\lodestar.exe init
```

A variable set like this only lasts for that window and only affects commands started from it. For the shortcuts and
the scheduled task to use the same folder, add `LODESTAR_HOME` as a permanent user environment variable in Windows
(Settings > System > About > Advanced system settings > Environment Variables), then run the installer again.
`LODESTAR_HOME` must be an environment variable: a `LODESTAR_HOME=` line in a `.env` file is read too late to move the
data folder. A data folder other than `~/.lodestar` keeps its secrets in its own keyring namespace (see the next
section), so link your keys and mailbox again there, or set `LODESTAR_VAULT_SERVICE=lodestar` to keep using the ones
you already linked. `JOBBOT_HOME` is still accepted as the old name. A data folder from before the rename (`~/.jobbot`) is copied to
`~/.lodestar` automatically the first time Lodestar starts; `lodestar doctor` then says when the old folder is safe
to delete.

### Settings and secrets: .env and the keyring vault

Lodestar reads a setting (an API key, `LODESTAR_PROVIDER`, `OLLAMA_MODEL`, `LODESTAR_NOTIFY_EMAIL`, `OBSIDIAN_VAULT`,
a model override such as `ANTHROPIC_MODEL`, ...) from the first place that has it:

1. An environment variable.
2. `.env` in the folder you started Lodestar from.
3. `.env` in the install folder (the one the installer created from `.env.example`).
4. `.env` in the data folder.
5. The keyring vault.
6. The built-in default.

**Use the vault for secrets.** `lodestar keys link`, Setup > Link an AI key, Setup > Connect email and
`lodestar vault set` store secrets in the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service on
Linux). They are never written to disk in plain text, never shown again after you paste them, and never put in logs,
exports or backups. Only names and usernames are listed in `vault_index.json`.

How to store and remove secrets: AI keys in [AI keys](#ai-keys), your mailbox in [Email: pick a way to connect](#email-pick-a-way-to-connect), and
anything else (with the `lodestar vault` commands) in [Other secrets (the vault)](#other-secrets-the-vault).

**Use `.env` only for convenience settings.** It is a plain text file: anything in it is readable by anyone with
access to your files, and it is left out of backups for that reason. A value in `.env` or the environment wins over
the vault, so an old `ANTHROPIC_API_KEY=` or `IMAP_HOST=` line there can hide what you set in the app (Setup says so,
and `lodestar email status` warns about mail overrides). Empty lines like `ANTHROPIC_API_KEY=` in the copied
`.env.example` do nothing.

Secrets are tied to the computer and the Windows user: they do not travel with the data folder (see "Moving to a new
PC").

**Each data folder has its own keyring namespace.** Only the default data folder (`~/.lodestar`, or `~/.jobbot` while
an old folder could not be moved) uses the keyring service `lodestar` (and still picks up secrets saved under the old
name `jobbot`, copying each one over the first time it is read). A data folder set with `LODESTAR_HOME` anywhere else
uses `lodestar:` plus 12 hex characters derived from that folder's full path, with no fallback, so a test copy or a
sandbox can never read or change your real keys and mail password: link them again there. Because the name comes from
the path, moving or renaming such a folder also moves it to a new, empty namespace (link again, or use
`LODESTAR_VAULT_SERVICE`). `lodestar doctor` and Setup > Run diagnostics show the active one on the `vault namespace`
line. To give a portable install one fixed name on purpose, set `LODESTAR_VAULT_SERVICE`, as an environment variable
or in a `.env` file (for example `LODESTAR_VAULT_SERVICE=lodestar` to use the default folder's secrets). Never set it
for a test or sandbox run: that would point the sandbox back at real secrets (the unit tests, the E2E suite and the
update check blank it for their own runs, so a line in the repo `.env` does not reach them). If you used your own
`LODESTAR_HOME` before this change, your keys and mailbox were saved under `lodestar`: `vault namespace` shows a WARN
naming the secrets this folder's index lists but its namespace does not hold. Link them again, or set
`LODESTAR_VAULT_SERVICE=lodestar` in the environment. `.env` files still load for every data
folder: a key written in `.env` is plain config and applies wherever that file is read (the `.env` in the install
folder is read by every data folder you use from that install).

### lodestar doctor

`lodestar doctor` checks the install and prints one PASS / WARN / FAIL line per item, with the fix next to each
problem. Setup > Diagnostics runs the same checks (**Run diagnostics**, or **Diagnostics + live AI call**).

```powershell
lodestar doctor          # no network
lodestar doctor --live   # also checks every linked key and the mailbox, and makes one real AI call per provider
```

On a fresh install with no key yet it looks like this:

```text
[PASS] Python             3.14.5 (3.11+ required)
[PASS] module keyring     installed
[PASS] module docx        installed
[PASS] module webview     installed
[PASS] module pypdf       installed
[PASS] keyring backend    ...
[PASS] vault namespace    lodestar (the default data folder)
[PASS] WebView2 runtime   found
[PASS] PDF engine         edge (C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe)
[PASS] data folder        C:\Users\you\.lodestar (writable)
[WARN] master profile     C:\Users\you\.lodestar\profile.md still the template: fill it in or import a resume
[WARN] profile bank       empty: lodestar profile import <resume> or lodestar profile linkedin <export.zip>
[FAIL] AI providers       none configured: lodestar keys link anthropic (or another provider)
[WARN] email              not connected (optional): Setup > Connect email, or lodestar email connect
[PASS] updates            git install, 0.2.0; mode notify, every 24 h, channel commits
something is broken; see FAIL lines
```

It also reports, when they apply: the stored result of each key check (`key anthropic`), the mail connection and
sign-in, your OAuth client, the last update check and update, `restart` after an update, and a leftover `~/.jobbot`
folder. The last line is `all good`, `usable; see WARN lines` or `something is broken; see FAIL lines`; the exit
code is 1 only in the last case.

| Line | Fix |
|---|---|
| `module webview missing (pip install -e .[desktop])` | `.venv\Scripts\python.exe -m pip install -e ".[desktop]"`, or re-run `install.ps1`. Until then the UI opens in the browser. |
| `module pypdf missing (pip install -e .[pdf])` | Same with `.[pdf]`; needed only to import PDF resumes. |
| `keyring backend` WARN (`fail.Keyring` or `null.Keyring`) | With `PYTHON_KEYRING_BACKEND` set to the null backend, that is your choice for a scratch run. Otherwise: no usable OS keyring (common on a headless Linux without a Secret Service). Keys cannot be stored in the vault; install and unlock a keyring, or put settings in `.env`. |
| `[WARN] vault namespace ...; N stored secret(s) not found here (...)` | This data folder's name index lists secrets its keyring namespace does not hold: usually an own `LODESTAR_HOME` install from before Pass 17.1, whose secrets are under `lodestar`. Link them again, or set `LODESTAR_VAULT_SERVICE=lodestar` in the environment. |
| `vault namespace lodestar:... (this data folder only ...)` | Not a fault: `LODESTAR_HOME` points at a data folder other than `~/.lodestar`, so it has its own keyring namespace and does not see the default folder's keys. Link them there, or set `LODESTAR_VAULT_SERVICE=lodestar` on purpose. |
| `WebView2 runtime not found` | Install the Microsoft Edge WebView2 runtime, or use the browser. |
| `PDF engine none ...` | Install Edge, Chrome or Chromium (or Word / LibreOffice), or set `LODESTAR_BROWSER`. |
| `data folder ... not writable` | Check the folder's permissions, or point `LODESTAR_HOME` elsewhere. |
| `AI providers none configured` | `lodestar keys link anthropic` (or another provider). |
| `key NAME` FAIL | The detail says why (wrong key, no credit, quota). Fix it at the provider, then `lodestar keys check NAME`. |
| `last update` FAIL with `ROLLBACK FAILED` | Run the `git reset --hard` command the line prints, from the install folder; see "Auto-update". |

`--live` costs a few tokens (one short call per configured provider); without it doctor never goes on the network.

### Backups, export and restore

**Backups.** A backup is a zip of your data folder: profile, profile bank, tracker database (copied consistently even
while the loop writes to it), settings, answers, ideas, generated documents and imported resumes.

- Nightly: the `backup` tool (on and automatic by default) makes one backup a day during a monitor cycle, so it needs
  the app, the loop or the scheduled task to run that day.
- Before every update: the updater makes one first and refuses to update if it fails.
- Any time: Setup > Data > **Backup now**, or:

  ```powershell
  lodestar backup                       # -> <data folder>\backups\lodestar-backup-YYYYMMDD-HHMMSS.zip
  lodestar backup --out D:\Backups      # somewhere else, e.g. another drive
  lodestar backup --keep 14             # keep the newest 14 in that folder (at least 1)
  ```

  It prints `wrote <path of the zip>`. Only the newest 7 (or `--keep N`) zips in that folder are kept.

Not in a backup: `.env` files and keyring secrets (by design), saved mail attachments (`applications\*\mail\`; they
are still in your mailbox), `snapshots\`, `cache\`, the log and older backups. Backups do contain your profile with
its private Preferences (salary floor included) and your mail records, so keep the zips somewhere only you can read.

**Export.** A readable dump of your data, for a spreadsheet or another tool. Setup > Data > **Export JSON** /
**Export CSV**, or:

```powershell
lodestar export json                  # one JSON file with every table
lodestar export csv                   # one CSV per table (cells that look like formulas are made safe)
lodestar export json --out D:\Exports
lodestar jobs packet 3                # one zip with every document, the posting, notes and timeline of job 3
```

Files go to `exports\` in the data folder unless you pass `--out`. An export is for reading; Lodestar cannot import
it back. Use a backup to restore.

**Restore.** Setup > Data > **Restore from backup**: pick a zip from the list (the zips in the backups folder; put one
from elsewhere there with **Open backups**, then **Refresh**), click **Restore** and confirm. Or:

```powershell
lodestar restore "$HOME\.lodestar\backups\lodestar-backup-20261101-021500.zip"         # shows what it holds, asks
lodestar restore D:\Backups\lodestar-backup-20261101-021500.zip --yes                   # no question
```

What happens, in order:

1. Refused while anything could write the old data meanwhile: the monitor loop in the middle of a cycle, an Inbox
   send, a mail scan, a background action, an update, or another Lodestar process (close the other window, or restore
   from it).
2. The zip is checked before anything is written: only files a backup holds (programs and scripts are refused), no
   absolute, drive or `..` paths, backslashes, links, reserved or short (8.3, like `EXTENS~1.JSO`) names, at most 2 GB
   on disk and 4 GB unpacked, and a `lodestar.db` at its top level. Files a backup never carries (`.env`,
   `extension.json`, `backups\`, logs) are skipped in any spelling (`Extension.json`, `.ENV`), since Windows treats
   those as the same files.
3. It is unpacked into a staging folder; its database must open, pass SQLite's integrity check and take this
   version's migrations; `settings.json` must be valid.
4. A safety backup of your data as it is now goes to `backups\before-restore-YYYYMMDD-HHMMSS.zip` (the newest 7 are
   kept, apart from the nightly ones).
5. The swap: your current files move aside, the backup's move in, files made since the backup are removed, and the
   database is copied in in one step. If any of it fails, your files are put back.

The result says how many files came back, the jobs, contacts and answers in the restored tracker, and where the
safety backup is. Not in backups, so never touched by a restore: AI keys, the mail sign-in and other secrets in the OS
keyring, paired browsers (the extension pairs again from Setup) and `.env`. Restart Lodestar afterwards so every part
reads the restored data.

**Restore by hand** (only when Lodestar itself will not start, so neither Setup nor `lodestar restore` can run): a
backup zip holds the data folder's files at their relative paths, so you can unzip it into a fresh data folder.

1. Close everything Lodestar: the window, the monitor console, any `lodestar` command. If you use the scheduled task,
   remove it for the moment (`lodestar schedule remove`) so it does not start during the restore.
2. Rename the current data folder (for example `.lodestar` to `.lodestar-old`) so nothing is lost if you picked the
   wrong zip. Take the zip you want from `.lodestar-old\backups\` (or wherever you keep it).
3. Unzip it into a new, empty data folder:

   ```powershell
   Expand-Archive -Path "$env:USERPROFILE\.lodestar-old\backups\lodestar-backup-20261110-184007.zip" -DestinationPath "$env:USERPROFILE\.lodestar"
   ```

4. Run `lodestar doctor`. You should see `data folder ... (writable)`, and `master profile` should no longer say
   "still the template". Check `lodestar jobs list`.
5. Start Lodestar, and put the scheduled task back (`lodestar schedule install`) if you removed it. When everything is
   there, delete `.lodestar-old` (copy its `backups\` first if you want the older zips).

Your keys and mail connection are not affected by a restore on the same PC: they live in the keyring.

### Obsidian export

`lodestar export obsidian` writes one note per tracked job (properties and wikilinks) plus an index table into the
`jobs` folder of your Obsidian vault, and prints `wrote <folder>`. Re-run it any time: notes it wrote before are
updated.

1. Choose the vault: Lodestar uses the `OBSIDIAN_VAULT` setting, else `Documents\Obsidian Vault` in your user folder.
   Store another folder in Setup > Other secrets (name `OBSIDIAN_VAULT`), or:

   ```powershell
   lodestar vault set OBSIDIAN_VAULT "D:\Notes\My Vault"
   ```

2. Export: Monitor > **Export tracker to Obsidian**, or:

   ```powershell
   lodestar export obsidian
   lodestar export obsidian --folder lodestar-jobs   # another folder inside the vault
   ```

3. Optional: to refresh it after every monitor cycle, turn on the `obsidian_sync` tool (off by default):
   `lodestar tools enable obsidian_sync`.

The notes contain your tracker data (companies, statuses, notes), so keep the vault private if it syncs anywhere.

### Auto-update

A git install can update itself from its origin repository, carefully: it shows you what changes first, takes a
backup, runs the tests on the new code and rolls back by itself if anything fails.

**Which installs can update**

| Install kind (shown in Setup > Updates and `lodestar update status`) | Updates |
|---|---|
| `git install` (a `git clone` installed with install.ps1 / install.sh / pip `-e`) | Check, Update now, automatic updates. Needs `git` on PATH. |
| `standalone build (notify only)` (`dist\lodestar.exe`) | Can only tell you a new version exists and link the download, from `update_manifest_url`. Never replaces itself. |
| `not a git install` (no `.git` folder) | None: reinstall from a `git clone` to get updates. |

**Settings** (Setup > Updates, or Tools > Preferences, or `lodestar tools set NAME VALUE`)

| Preference | Values | Default | Meaning |
|---|---|---|---|
| `update_mode` | `off`, `notify`, `auto` | `notify` | off: never check. notify: one alert per new version (and the top-bar badge). auto: apply it when nothing blocks it, then alert the result. |
| `update_every_hours` | 1-720 | 24 | How often the monitor loop checks. |
| `update_channel` | `commits`, `releases` | `commits` | commits: every change on the origin branch. releases: only the newest `v*` tag. |
| `update_origin` | an `https://` git URL or a local folder | empty | Where to update from; empty means the checkout's own `origin` remote. SSH and other URLs are refused. |
| `update_manifest_url` | an `https://` URL | empty | Standalone exe only: a JSON file `{version, url, notes}` it checks. |

```powershell
lodestar tools set update_mode auto
lodestar tools set update_every_hours 12
lodestar tools set update_channel releases
```

The check runs inside the monitor loop (`desktop`, `app`, `run`, and the scheduled task's `run --once`) every
`update_every_hours`; `--no-update` skips it. A check that cannot reach the origin is logged as `could not check` and
the loop carries on.

**In the app: Setup > Updates**

1. The **Updates** box (off / tell me (notify) / install automatically) and **check every N hours** set the mode
   and interval.
2. **Check now** shows either "up to date", or `Update available: N commits` with the commit range, each commit, and
   "What's new (changelog)" from docs/CHANGELOG.md. If something blocks the update right now it says
   `Not now: <reason>` and **Update now** is disabled.
3. **Update now** asks for confirmation, then shows progress (backup, fast-forward, then the tests and doctor on the
   new code). It takes a minute or two. You then see either "Updated" with the backup path, or what failed and that
   the old version is back.
4. **Restart** appears in the desktop app after a successful update and relaunches it on the new code. In
   `lodestar app` / `ui` (browser) it says to close Lodestar and start it again instead.
5. **Update log** (fold-out) lists every check and update with time, commit range and result.

A top-bar badge shows **Update available** or **Restart to finish the update**. A failed or refused update is noted
under Getting started and in Diagnostics until a later update succeeds.

**From the terminal**

```powershell
lodestar update check           # fetch the origin; show the commits and changelog, and anything that blocks it
lodestar update apply           # the same, then asks "Apply this update? [y/N]"
lodestar update apply --yes     # without asking
lodestar update status          # install kind, version, mode, interval, channel, last check and update
lodestar update log             # every check and update, newest first
lodestar update log --limit 50
```

`update apply` prints `backing up, updating and running the tests (a minute or two)...`, then
`updated <old> -> <new>; restart Lodestar to use it` and the backup path, or the failure (exit code 1).

**What an update does, in order**

1. Refuses (and says why) if the install folder has uncommitted changes, has commits the origin does not have, is
   not on a branch, or if a mail scan, an Inbox send, a background action, another update or another Lodestar process
   (app, desktop window, loop) is running. Update from the window that is open, or close the others first.
2. Backs up the data folder.
3. Fast-forwards the install folder to exactly the version the check showed (if the origin moved since, it asks you
   to check again).
4. Reinstalls the package only when `pyproject.toml` changed.
5. Runs the offline unit tests on a throwaway data folder (never yours) and `lodestar doctor` on the new code.
6. If any step fails, resets the install to the exact previous commit and names the failing tests. In `auto` mode a
   version that failed is not tried again automatically; `lodestar update apply` retries it.

The running app keeps using the code it started with until you restart it.

**Rollback and recovery**

- Automatic: any failure during the update puts the previous version back.
- Interrupted update (Lodestar closed, killed or the PC lost power mid-update): the next start of `run`, `app`, `ui`
  or `desktop` puts the previous version back and logs "the update was interrupted".
- If a rollback itself fails, it is retried; the log and `lodestar doctor` then show a FAIL line with
  `ROLLBACK FAILED` and the exact command to run, of the form `git -C "<install folder>" reset --hard <commit>`.
  Close Lodestar, run that command, then `lodestar doctor`.
- Your data: updates only add to the data format, and the backup taken before the update is in `backups\` (its path
  is shown in the result). To go back to it, see "Restore".

**Common update messages**

| Message | Meaning / fix |
|---|---|
| `not a git install: reinstall with install.ps1 / install.sh to get updates` | The install has no `.git` folder. Install from a `git clone`. |
| `could not check: git is not installed or not on PATH` | Install git, or leave updates on `off`. |
| `could not check: updates come only from an https:// origin or a local folder, not ...` | Your origin is an SSH URL. Set `update_origin` to the https URL. |
| `could not check: ...` (network) | Offline, or the origin needs a login (private repositories are not prompted for): it tries again next interval. |
| `the install folder has uncommitted changes` | You edited files in the install folder. Commit, stash or undo them. |
| `this install has N commit(s) the origin does not (fast-forward only)` | Local commits: Lodestar never updates over your own work. |
| `another Lodestar process is running (pid N: ...)` | Close the other window or loop, or update from it. |
| `the install moved since the check; check again` | Press Check now again. |

### Moving to a new PC

Your data moves as a folder; your secrets do not (they are in the old PC's keyring and stay there).

On the old PC:

1. Note what you have linked: `lodestar keys`, `lodestar email status` and `lodestar vault list` (names only; you
   will enter the secrets again).
2. Close Lodestar and make a backup: `lodestar backup --out <USB drive or cloud folder>`. Or, with Lodestar closed,
   copy the whole data folder: that also brings saved mail attachments and watch snapshots, which a backup leaves out.
3. If you keep settings in a `.env` file (install folder or data folder), copy it separately and carefully: backups
   leave it out because it may hold secrets.

On the new PC:

1. Install Python 3.11+, get the code (`git clone`) and run `install.bat` (with `-Schedule` if you want the task).
2. Make sure Lodestar is closed, then put your data in place: unzip the backup into `%USERPROFILE%\.lodestar` (see
   "Restore"), or copy the old folder over the new one.
3. Link your secrets again:

   ```powershell
   lodestar keys link anthropic
   lodestar email connect --user you@example.com       # app password
   lodestar email client google                        # or sign-in: set up your client again,
   lodestar email signin google                        # then sign in (microsoft: same two commands)
   lodestar vault set linkedin.com --user you@mail.com # each site login you had
   ```

4. Run `lodestar doctor` and start Lodestar. If the Capture or Autofill bookmarklets stop working, drag them to your
   bookmarks bar again from Setup > Browser bookmarklets.
5. On the old PC, remove the scheduled task (`lodestar schedule remove`) or uninstall, so two computers do not both
   scan the same mailbox; and remove its secrets if you are giving the PC away (`lodestar keys rm NAME`,
   `lodestar email disconnect`, `lodestar vault rm NAME`).

## Connections: AI keys, local models, secrets and email

Lodestar needs at least one AI provider for drafting, tailoring and classifying mail. Connecting your mailbox is
optional: with it, Lodestar reads hiring replies over IMAP and sends the mail you approve over SMTP, from your own
address. Everything here is done once, in **Setup** in the app or with the `lodestar` command.

### Where secrets and connection data live

| What | Where it is kept |
|---|---|
| AI keys, the app password, the Google / Microsoft refresh token, your OAuth client ID and secret, anything you store under Other secrets | the OS keyring: Windows Credential Manager, macOS Keychain, Secret Service on Linux (service name `lodestar` for the default data folder; see the namespace note in [Settings and secrets: .env and the keyring vault](#settings-and-secrets-env-and-the-keyring-vault)) |
| Names of stored secrets (never the values) | `~/.lodestar/vault_index.json` |
| Result of the last key and mailbox checks (status, time, model; never a key) | `~/.lodestar/connections.json` |
| Default provider, council providers, pinned models | `~/.lodestar/settings.json` |
| Tokens used per AI call | `~/.lodestar/usage.jsonl` |
| Files received with job mail | `~/.lodestar/applications/<job>/mail/<date>-<id>/` |

Rules that hold everywhere:

- A secret is never shown again after you paste it, never written to disk in plain text, and never put in logs,
  exports or backups. Google / Microsoft access tokens live in memory only (about an hour); only the refresh token is
  stored.
- A value in the environment or in a `.env` file wins over the keyring (the full order is in
  [Settings and secrets: .env and the keyring vault](#settings-and-secrets-env-and-the-keyring-vault)). Setup and `lodestar email status` tell you when an
  environment value overrides what you stored.
- Uninstalling never touches the keyring. Remove a secret yourself with `lodestar vault rm NAME` (or the matching
  Remove / Disconnect button).
- On Linux the keyring needs a running Secret Service (for example GNOME Keyring or KWallet). `lodestar doctor` shows a
  WARN on "keyring backend" when there is no usable keyring.

### AI keys

What it is for: every AI feature (tailored resumes, cover letters, gap checks, interview prep, mail classification,
drafts) calls one of these providers with your key. You need one; more providers make `council` and idea crafting
better.

| Provider (name to type) | Get a key | The key looks like | Variable | Default model |
|---|---|---|---|---|
| Anthropic (Claude) (`anthropic`) | https://console.anthropic.com/settings/keys | starts with `sk-ant-` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| OpenAI (`openai`) | https://platform.openai.com/api-keys | starts with `sk-` | `OPENAI_API_KEY` | `gpt-5` |
| Google Gemini (`gemini`) | https://aistudio.google.com/apikey | starts with `AIza`; has a free tier | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| Groq (`groq`) | https://console.groq.com/keys | starts with `gsk_`; has a free tier | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| OpenRouter (`openrouter`) | https://openrouter.ai/settings/keys | starts with `sk-or-` | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4.5` |
| Mistral (`mistral`) | https://console.mistral.ai/api-keys | | `MISTRAL_API_KEY` | `mistral-large-latest` |
| Ollama (local, no key) (`ollama`) | https://ollama.com/download | no key; runs on this computer | `OLLAMA_MODEL` | `llama3.1` |

The paid providers are pay as you go: add billing or credit on the provider's site, or a new key reads Failed.

#### Link a key in the app

1. Open **Setup** and find the **Link an AI key** card. On a fresh install the window opens on Setup once by itself,
   and the Board's **Getting started** banner has a button that takes you there.
2. Pick the provider in the list. Under it you see "Get a key:" with the provider's page and what the key looks like.
3. Create a key on the provider's page, copy all of it, paste it into **paste the key** and click **Link**.
4. You should see a message like `Anthropic (Claude): Verified - 52 models; using claude-sonnet-5-5`, and the provider
   appears in the list with a green **Verified** pill, the time of the check and `model <id>`.

The box is cleared as soon as you click Link; the key never comes back to the page.

#### Link a key from the terminal

```powershell
lodestar keys link anthropic     # or openai, gemini, groq, openrouter, mistral, ollama, or ANTHROPIC_API_KEY
lodestar keys                    # every provider: linked (vault / env / no), last check, time, model
```

`keys link` prints "Get a key: <page>", then asks `Anthropic (Claude) key (not shown):`. Paste the key and press
Enter (nothing appears while you paste; that is normal). It then prints one line, for example
`Anthropic (Claude): verified - 52 models; using claude-sonnet-5-5`.

#### How a key is checked

- At link: one call that lists the provider's models (OpenRouter: its key-info endpoint). It **spends no tokens**.
- At every start of the app (`lodestar ui`, `lodestar app`, `lodestar desktop`): every linked key and the mailbox are
  checked again once, in the background, a couple of seconds after the window opens. Set
  `LODESTAR_NO_STARTUP_CHECK=1` to skip this (for people who start the app many times a day).
- If the model Lodestar would use is not in the provider's list, linking switches to the best one the provider offers
  and says `switched to <model>`. A model you pinned with `<PROVIDER>_MODEL` is never changed; the detail then says it
  is not offered.
- A key that fails is still stored, so you can fix your billing and click Re-check without pasting it again.
- A key that does not start the way the table says is linked anyway, with the note "this does not look like an ... key".

| Pill in the app | Word in `lodestar keys` | Meaning | What to do |
|---|---|---|---|
| Verified | `verified` | the provider accepted the key; the model in use is shown | nothing |
| Failed | `failed` | the provider rejected the key, or the account has no credit | copy the whole key again (or create a new one), or add billing / credit |
| Failed, with "quota or rate limit reached" | `failed` | the key was accepted, but the account hit its quota or rate limit (HTTP 429) | wait, or check your plan; AI features stay on |
| Couldn't reach, will retry | `unreachable` | no answer: offline, an outage, a provider error | nothing: AI features stay on and the next start checks again; or click Re-check |
| Not checked | `unchecked` | linked but not checked yet, or the key changed | Re-check |

#### Re-check and Remove

- **Re-check** (next to each key) checks that one key now. **Re-check all** checks every linked key and the mailbox.
- **Remove** deletes the key from the keyring after you confirm. It is greyed out when the key comes from `.env` or the
  environment: remove that line there instead. For Ollama (no key) **Remove** unlinks it: it clears the model its
  link saved, so Lodestar stops using Ollama (unless `OLLAMA_MODEL` is set or Ollama is the default provider; the
  message then says which).
- Terminal:

```powershell
lodestar keys check            # every linked key and the mailbox, then the table
lodestar keys check openai     # one key
lodestar keys rm openai        # remove it from the keyring
lodestar keys rm ollama        # unlink Ollama (clears its saved model)
```

### Local models (Ollama)

What it is for: run the AI on your own computer, free and private. Nothing about you leaves the machine. Lodestar talks
to Ollama at `http://localhost:11434` (fixed address).

1. Install Ollama from https://ollama.com/download and start it.
2. Download a model, for example:

   ```powershell
   ollama pull llama3.1
   ```

3. In Setup > **Link an AI key**, click **Local only (Ollama)**. Terminal:

   ```powershell
   lodestar providers local
   ```

   When it works you see `local-only preset: provider=ollama, council_providers=ollama, model llama3.1 (saved in
   prefs.models)` (or the model Ollama actually serves). This makes Ollama the default provider, restricts the council
   and idea crafting to Ollama, and pins a model Ollama serves.

   If Ollama is not running or serves no model you see `local-only preset NOT applied (nothing changed): Ollama is not
   reachable at localhost:11434 or serves no model.` Start Ollama, pull a model, and run it again.

Other ways to turn Ollama on: store the model name (`lodestar vault set OLLAMA_MODEL llama3.1`, or an
`OLLAMA_MODEL=llama3.1` line in `.env`), or pick `ollama` as the default provider. Picking **Ollama (local, no key)**
in the Link list and clicking Link checks that Ollama answers and pins its model (`llama3.1`, or one Ollama serves),
so the card shows Ollama linked. If Ollama is not running, Link shows **Couldn't reach** and saves nothing: the card
stays "not linked" and the offline templates keep working. Start Ollama and click Link again. Linking does not make
Ollama the default provider; **Local only (Ollama)** does. **Remove** on the Ollama row (or `lodestar keys rm ollama`)
unlinks it.

To leave local-only mode: Tools > Preferences, set **Default AI provider** back to "(automatic)" and empty **Council
providers**. In the terminal (`--%` makes Windows PowerShell pass the empty value):

```powershell
lodestar --% tools set provider ""
lodestar --% tools set council_providers ""
```

### Choose models, the default provider and council providers

Which model a provider uses, in this order: a `<PROVIDER>_MODEL` setting (environment, `.env` or the keyring), then a
model pinned in the **models** preference, then the default in the table above.

```powershell
lodestar providers                       # each provider, the model it will use, ready or missing
lodestar providers models                # the model ids each configured provider offers
lodestar providers models openai groq    # only these
lodestar tools set models openai=gpt-5   # pin a model (openai= with nothing after it goes back to the default)
lodestar vault set ANTHROPIC_MODEL claude-sonnet-5-5   # or pin with a setting, which nothing overrides
```

In the app: Setup > **List models** shows the ids; pin one under Tools > Preferences > **Pinned models**
(`provider=model`).

Self-healing: if a provider rejects the configured model, Lodestar fetches its model list, picks the best match, saves
it under the models preference, says `switched to model '<id>'`, and retries once. It never overrides an explicit
`<PROVIDER>_MODEL`.

Default provider: the first configured one, unless you choose. Set it with Tools > Preferences > **Default AI
provider**, `lodestar tools set provider groq`, or `LODESTAR_PROVIDER=groq` in `.env`. For one command only, put `-p`
before the command name:

```powershell
lodestar -p groq ask "Summarize this posting in three lines"
```

(`lodestar ask "..." -p groq`, with `-p` after the command, is refused.)

Council: `lodestar council "prompt"` asks every allowed provider, then one of them combines the best parts (`--all`
also prints each answer). Commands with `--council` (for example `lodestar resume tailor ID --council`,
`lodestar interview prep ID --council`) do the same. Two preferences control it:

| Preference (Tools > Preferences) | Terminal | Effect |
|---|---|---|
| Council providers (`council_providers`) | `lodestar tools set council_providers anthropic,openai` | the only providers the council and idea crafting may send your data to; empty = every configured one. It is a hard limit: a default provider outside the list is refused, and a list that matches no configured provider stops with an error instead of using everyone |
| Council judge (`council_judge`) | `lodestar tools set council_judge true` | a second provider checks and improves the combined answer |

Testing that calls work:

| Button / command | Spends tokens? | What it does |
|---|---|---|
| Re-check, Re-check all, `lodestar keys check`, `lodestar doctor` | no | checks keys with the model list |
| **Test providers**, `lodestar providers --test` | yes, a tiny amount | asks each provider to reply "OK" |
| `lodestar doctor --live` | yes, a tiny amount | key checks, one IMAP and SMTP login, and one real call per provider |
| `lodestar usage` (`--days 30`) | no | tokens per provider and model, from `usage.jsonl`; the Link an AI key card shows the same |

**AI helpers (Setup and Tools):** **✦ AI help** > **Explain this setting** at the top of both tabs: pick a Setup card (email, Autopilot, keys, Ollama, models, secrets, market rates, browser extension, bookmarklets, notifications, diagnostics, data, updates, tool switches) or a preference, and the AI explains it from this guide (`lodestar ai-help explain_setting autopilot`).

### Other secrets (the vault)

What it is for: any other setting you would rather keep in the keyring than in `.env`. Setup > **Other secrets (OS
keyring)**: type a name, an optional username, the secret, and click **Store**. Stored names show below with an `×` to
remove them. AI keys and email settings are not listed here: they have their own cards.

Useful names (all read by Lodestar from the environment, `.env` or the vault, in that order):

| Name | What it does |
|---|---|
| `LODESTAR_NOTIFY_EMAIL` | where alerts and the emailed digest go (see "Notification email address") |
| `OLLAMA_MODEL` | turns on Ollama with this model |
| `<PROVIDER>_MODEL`, for example `OPENAI_MODEL` | pins a model for that provider |
| `LODESTAR_PROVIDER` | default provider |
| `OBSIDIAN_VAULT` | folder for the Obsidian export |
| `BLS_API_KEY` | optional, free from data.bls.gov/registrationEngine: raises market pay lookups from 25 to 500 BLS queries a day; BLS expires it yearly, so renew it (see [Market pay (BLS)](#market-pay-bls)) |

```powershell
lodestar vault set LODESTAR_NOTIFY_EMAIL you@example.com
lodestar vault set SOME_NAME               # asks for the value without showing it
lodestar vault list                        # names and usernames only
lodestar vault get SOME_NAME               # shows ******** ; add --show to print the value
lodestar vault rm SOME_NAME
```

An empty or blank value is refused with one line. Spaces and line breaks around a value are trimmed.

### Market pay (BLS)

What it is for: public U.S. wage percentiles (10th, 25th, median, 75th, 90th and the mean) for each tracked job's
occupation in its area, from the Bureau of Labor Statistics' Occupational Employment and Wage Statistics (OEWS). They
show as a chip on the board card ("market median $150k (BLS May 2025, Portland)"), as the drawer's **Market pay (BLS)**
group (a percentile strip with the posting's own pay drawn over it), as a row in Insights > Offers, as figures you can
cite in a counter-offer, and in the private prompts of interview prep, the gap check and offer evaluation.

It is **off by default**: until you turn it on, Lodestar never contacts api.bls.gov. Turn it on with **Turn on market
pay** in any job's drawer, in Tools > Preferences (`market_pay`), or with `lodestar tools set market_pay on`. Then the
drawer fetches the job you open (one try per job per page load; **Fetch BLS figures** tries again), and the monitor loop
fills in the other live jobs, at most one BLS query a cycle.

How a job is matched (always shown next to the figure, because a wrong occupation means a wrong number):

- **Occupation**: your pick in the drawer (or `lodestar comp market ID --soc 15-1252`) wins; else a title keyword from
  the bundled crosswalk (`lodestar/data/oews.json`, 50 occupations; SRE, DevOps, platform and cloud titles map to
  "Computer Occupations, All Other", labelled "closest BLS group"; product manager has no BLS occupation and is left to
  you); else the AI's pick from that fixed list, only when you click **Match occupation (AI)**. `none` hides market
  pay for the job.
- **Area**: the metro the location names (39 metros), else its U.S. state, else national. When BLS publishes no metro
  figure for the occupation, the state is used, then national. Remote jobs use your home area (the location in your
  profile's contact line), else national. A location outside the U.S., or a U.S. city without its state, gets no
  figure: add the state ("Boise, ID").

What leaves your computer: only BLS series IDs (an occupation code plus an area code, for example
`OEUM004266000000015125213`) to api.bls.gov, plus your `BLS_API_KEY` when you stored one. Never your profile, the job's
text, your salary floor or Preferences. From your IP address the IDs still reveal which occupations and metros you look
at, and for remote jobs **your home metro or state**; a key, registered with your email, ties those queries to you.
**Match occupation (AI)** sends the job title and the first 1,500 characters of the posting to your AI provider.

Limits: without a key BLS allows 25 queries a day (Lodestar uses at most 20; one query covers 4 jobs); a free
`BLS_API_KEY` (Setup > Other secrets) raises that to 500 (Lodestar uses 400; 8 jobs a query). BLS keys expire once a
year: renew yours at data.bls.gov/registrationEngine. When the day's limit is reached, the cached figures stay and
Lodestar waits until tomorrow; a query that never reached BLS (offline) does not count. A figure is cached in the
`paydata` table until the next annual release (May Y figures stay until June 1 of Y+2); "not published" is asked again
after 30 days. `lodestar doctor` shows the state, the key and today's query count.

Honesty: the figure is what employers of every kind and size paid that occupation in that area, pooled from surveys
over three years (it lags the market), base wages including commissions but not overtime, non-production bonuses,
benefits or equity. It is not the company's pay band; big-tech pay often sits at or above the 75th-90th percentile.
Source: U.S. Bureau of Labor Statistics; BLS.gov cannot vouch for the data or analyses derived from these data after
the data have been retrieved from BLS.gov. Search results and the `min_salary` filter never use BLS figures.

### Email: pick a way to connect

Lodestar reads hiring replies over IMAP and sends only the mail you approve over SMTP, as your own address. It never
sees your normal password or your 2-step codes. One way to sign in is active at a time; switching removes the other.

| | Sign in with Google / Microsoft | App password |
|---|---|---|
| Works for | Gmail and Google Workspace; Outlook.com / Hotmail / Live; Microsoft 365 | Gmail, Yahoo, AOL, iCloud, Fastmail, Zoho, Proton Mail (via Bridge), any other IMAP/SMTP server |
| Setup | your own sign-in client, once (about 10 minutes) | about a minute |
| 2-step verification | every method runs on the provider's page | checked once, when you create the app password |
| Not possible with | an organization that blocks the app | Microsoft (no app passwords for IMAP/SMTP); Google accounts with security-key-only 2-step, Advanced Protection, most work accounts |

The presets Lodestar knows (Setup's list, or `--preset` in the terminal):

| Preset | Label | IMAP | SMTP | How you sign in |
|---|---|---|---|---|
| `gmail` | Gmail | imap.gmail.com:993 ssl | smtp.gmail.com:465 ssl | Sign in with Google, or an app password |
| `yahoo` | Yahoo Mail | imap.mail.yahoo.com:993 | smtp.mail.yahoo.com:465 ssl | app password |
| `icloud` | iCloud Mail | imap.mail.me.com:993 | smtp.mail.me.com:587 starttls | app password |
| `fastmail` | Fastmail | imap.fastmail.com:993 | smtp.fastmail.com:465 ssl | app password |
| `zoho` | Zoho Mail | imap.zoho.com:993 | smtp.zoho.com:465 ssl | app password |
| `aol` | AOL Mail | imap.aol.com:993 | smtp.aol.com:465 ssl | app password |
| `outlook` | Outlook.com / Hotmail / Live | outlook.office365.com:993 | smtp-mail.outlook.com:587 starttls | Sign in with Microsoft only |
| `m365` | Microsoft 365 (work or school) | outlook.office365.com:993 | smtp.office365.com:587 starttls | Sign in with Microsoft only |
| `proton` | Proton Mail (via Bridge) | 127.0.0.1:1143 starttls | 127.0.0.1:1025 starttls | the Bridge password |
| `custom` | Other (custom server) | your server (993 ssl by default) | your server (465 ssl, or 587 starttls) | whatever your provider issues |

Typing your address picks the preset from its domain (gmail.com, outlook.com, icloud.com and so on). A Google
Workspace or other own-domain address is not recognised: pick the preset yourself.

Connections are always encrypted and the server certificate is always checked. STARTTLS never falls back to plain
text.

What Lodestar may do with your mail on its own is limited by the approval, salary-floor and trust rules: see
[The safety rules](#the-safety-rules) and [How Lodestar decides whether mail is trusted](#how-lodestar-decides-whether-mail-is-trusted).

### Email with an app password

1. Turn on 2-step verification for the account, then create an app password on the provider's page:

   | Provider | Where to create it |
   |---|---|
   | Gmail | https://myaccount.google.com/apppasswords (paste the 16 letters; the spaces Google shows are removed for you) |
   | Yahoo Mail | https://login.yahoo.com/account/security > Generate app password |
   | AOL Mail | https://login.aol.com/account/security > Generate app password |
   | iCloud Mail | https://account.apple.com > Sign-In and Security > App-Specific Passwords (needs two-factor authentication) |
   | Fastmail | Settings > Privacy & Security > Manage app passwords > New app password (IMAP and SMTP); help: https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords |
   | Zoho Mail | turn on IMAP access in Zoho Mail settings first, then https://accounts.zoho.com/home#security/app_password. Organisation or EU accounts use other servers (imappro.zoho.com, imap.zoho.eu): pick Other (custom server) |
   | Other (custom server) | your provider's help; use an app password if it offers one |

2. In the app: Setup > **Connect email**. Pick the provider, type your address, paste the app password in **App
   password** (for Gmail, open "Or use an app password"), and click **Connect & test**.
3. You should see `Connected as you@example.com (Yahoo Mail) · IMAP imap.mail.yahoo.com:993 · SMTP
   smtp.mail.yahoo.com:465 ssl` and two lines: `IMAP ok logged in; N message(s) in INBOX from the last 7 days` and
   `SMTP ok logged in as you@example.com (nothing sent)`.
4. Click **Send me a test email**. It goes only to your own connected address; check that inbox.

Terminal:

```powershell
lodestar email connect --user you@yahoo.com     # preset guessed from the address; add --preset yahoo to choose
lodestar email test-send
```

`email connect` prints the provider's steps and link, then asks `app password (not shown; Enter keeps the stored one):`,
stores everything and runs the test. The output ends with `IMAP  ok   ...` and `SMTP  ok   ...` lines, or `FAIL` and a
`hint:` line saying what to do.

Pressing Enter keeps the stored app password only while the address, servers and SMTP login stay the same: a new
address or server drops it, so one account's password never goes to another server.

Other servers: open **Advanced: servers and ports** (or use the flags) to set IMAP host / port / security, SMTP host /
port / security, an SMTP login that differs from your address, and a CA certificate file:

```powershell
lodestar email connect --preset custom --user you@example.org --imap-host imap.example.org --imap-port 993 --smtp-host smtp.example.org --smtp-port 587 --smtp-mode starttls
```

`--imap-mode` is `ssl` (port 993, the default) or `starttls` (port 143); `--smtp-mode` is `ssl` (465) or `starttls`
(587). Choosing the other mode without a port uses that mode's usual port.

#### Proton Mail (via Bridge)

Not yet tested with a real Bridge.

1. Install Proton Mail Bridge (https://proton.me/mail/bridge, paid Proton plans) and sign in there. Your 2-step check
   happens in Bridge.
2. In Bridge: Settings > Advanced > Export TLS certificates. Note where the file is saved.
3. Setup > Connect email > **Proton Mail (via Bridge)**. Under **Advanced: servers and ports**, put the certificate
   file's path in **CA certificate file**. Paste the password Bridge shows (not your Proton password) and click
   **Connect & test**. Terminal:

   ```powershell
   lodestar email connect --preset proton --user you@proton.me --cafile "C:\path\to\cert.pem"
   ```

Lodestar then trusts only that certificate for IMAP and SMTP. The preset uses Bridge's defaults (IMAP 127.0.0.1:1143
and SMTP 127.0.0.1:1025, both starttls). If you switched Bridge to SSL, choose ssl for both (`--imap-mode ssl
--smtp-mode ssl`).

### Email with Sign in with Google (Gmail)

Why you create your own sign-in client: the only Google permission that allows IMAP and SMTP
(`https://mail.google.com/`) is a "restricted" scope. A shared app would need Google's verification and a yearly
security assessment; a personal app that only you use does not. You create it once (Google Cloud console):

1. Go to https://console.cloud.google.com/ and create a project named "Lodestar".
2. APIs & Services > Library: enable **Gmail API** (this makes the scope appear; Lodestar itself uses IMAP and SMTP).
3. Google Auth Platform > **Branding**: app name "Lodestar (personal)", your address as support and developer contact.
   **Audience**: External. **Data access**: add the scope `https://mail.google.com/` (plus `openid`, `email`).
4. **Clients** > Create client > Application type **Desktop app** > Create. Copy the **Client ID** and **Client
   secret** at once: Google shows the full secret only at creation. Lost it? Add a new secret to the client (or create
   a new client) and use that.
5. **Audience** > Test users: add your own address.
6. **Audience** > **Publish app** ("In production"). Google shows the app as unverified: that is fine for your own use.
   If you skip this, the sign-in stops working after 7 days.
7. In Lodestar: Setup > Connect email > **Gmail** > open **Set up your Google client (one time)** (the same steps are
   listed there with links), paste the Client ID (ends in `.apps.googleusercontent.com`) and the Client secret (starts
   with `GOCSPX-`), and click **Save client**. Terminal:

   ```powershell
   lodestar email client google
   ```

   It asks for the client ID, then the secret without showing it, and prints `google client stored in the keyring;
   next: lodestar email signin google`.
8. Click **Sign in with Google**. Your normal browser opens Google's page (never inside the Lodestar window). On "Google
   hasn't verified this app" click Advanced > Go to Lodestar (unsafe): it is your own app. Do your usual 2-step check,
   then Allow. Terminal:

   ```powershell
   lodestar email signin google
   lodestar email signin google --hint you@gmail.com   # preselect the account
   lodestar email signin google --no-browser           # print the page to open yourself
   ```

You should see "Signed in. You can close this tab and go back to Lodestar." in the browser, and in Setup
`Signed in with Google as you@gmail.com (Gmail, OAuth)` with IMAP and SMTP ok. The terminal prints `signed in as ...`
and the two test lines. Lodestar waits up to 5 minutes; **Cancel** (or Ctrl-C) stops it. If no browser opened, use the
**Open the sign-in page** link that appears while it waits.

If your app is still in Testing, Setup warns "Your Google app is in Testing: this sign-in stops on <date>": publish it
(step 6) and sign in again.

### Email with Sign in with Microsoft (Outlook.com, Hotmail, Live, Microsoft 365)

Microsoft accepts only this sign-in for IMAP and SMTP; there are no app passwords. Choosing Outlook or Microsoft 365
hides the app-password box, and `lodestar email connect` for such an address tells you to sign in instead. One-time
setup in the Microsoft Entra admin center:

1. You need a Microsoft Entra tenant to register an app
   (https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-create-new-tenant). Work or school: ask IT, or
   use your organization's tenant if you may register apps. Personal: create a free tenant (Microsoft may ask you to
   sign up for a free Azure account, which can ask for a card to prove who you are; an app registration costs nothing).
   Not for you? Forward your Outlook mail to a Gmail address and connect that instead.
2. https://entra.microsoft.com > Applications > App registrations > **New registration**: name "Lodestar", Supported
   account types **Any Entra ID Tenant + Personal Microsoft accounts**, Redirect URI platform **Public client/native
   (mobile & desktop)** with `http://localhost`. Register.
3. **Authentication** > Advanced settings > **Allow public client flows**: Yes. Save.
4. **API permissions** > Add a permission > APIs my organization uses > "Office 365 Exchange Online" > Delegated >
   `IMAP.AccessAsUser.All` and `SMTP.Send` (plus Microsoft Graph `offline_access`, `openid`, `email`, `profile`). Work
   accounts: an admin may need to grant consent.
5. Copy the **Application (client) ID** (a GUID). In Lodestar: Setup > Connect email > pick **Outlook.com / Hotmail /
   Live** or **Microsoft 365 (work or school)** > **Set up your Microsoft client (one time)**, paste it, **Save
   client**. There is no secret. Terminal: `lodestar email client microsoft`.
6. Outlook.com only: turn on IMAP (Outlook.com > Settings > Mail > Forwarding and IMAP;
   https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com).
7. Choose **Personal (Outlook.com, Hotmail, Live)** or **Work or school (Microsoft 365)**, click **Sign in with
   Microsoft**, and finish your usual 2-step check on Microsoft's page. Terminal:

   ```powershell
   lodestar email signin microsoft          # personal
   lodestar email signin microsoft --work   # Microsoft 365
   ```

The account you sign in with decides the final setting: a personal account gets the Outlook.com servers, a work
account the Microsoft 365 ones.

Microsoft 365 sending: if your organization turned SMTP AUTH off, Lodestar can read but not send. The test says so and
tells you to ask your admin to allow SMTP AUTH for your mailbox.

### Test, re-sign-in and disconnect

| Action | In the app | Terminal |
|---|---|---|
| Test the login (reads INBOX read-only, sends nothing) | **Connect & test** (app password), automatic after a sign-in; **Re-check all** on the key card also re-tests the mailbox | `lodestar email test` |
| Send yourself a test email | **Send me a test email** | `lodestar email test-send` |
| See the connection (never the password) | the status line under the buttons | `lodestar email status` |
| Sign in again | **Sign in again** (in Setup and in Getting started) | `lodestar email signin google` or `microsoft` |
| Disconnect | **Disconnect** (asks first) | `lodestar email disconnect` |

What Disconnect does: with an app password, it removes the stored password. With a sign-in, it forgets the sign-in;
for Google it also revokes it at Google; for Microsoft it tells you where to remove the app yourself
(https://account.live.com/consent/Manage for personal accounts, https://myapps.microsoft.com for work accounts). The
server settings and your sign-in client stay, so connecting again is quick. You can also revoke Google access at
https://myaccount.google.com/connections.

What the mailbox status means (Setup's status line, Getting started, `lodestar keys`, `lodestar doctor`):

| Status | Meaning | What to do |
|---|---|---|
| Connected / Signed in, IMAP ok, SMTP ok (`verified`) | both logins work | nothing |
| "Saved, but sign-in failed" / "Email check failed: ..." (`failed`) | the server refused the login, or a setting is wrong | follow the "What to do" line, fix, test again |
| couldn't reach the mail server; will retry (`unreachable`) | offline or the server did not answer | nothing: a network problem never disconnects a working mailbox |
| "Sign-in expired" with **Sign in again** | the Google / Microsoft sign-in stopped working | sign in again |
| Not connected | no app password and no sign-in stored | connect |

Any passing test (Connect & test, a new sign-in, Re-check all, the start-up check) replaces an old failure at once.

Why a sign-in expires: you revoked Lodestar's access or changed your Google password; it was unused for 6 months
(Google) or 90 days (Microsoft); your Google app is still in Testing (7 days); more than 100 sign-ins for the same Google
client; or your organization's policy changed. `lodestar doctor` then shows a FAIL on "email sign-in".

Sign-in security: the page that receives the browser's answer listens on this computer only (127.0.0.1 on a random
port, plus ::1 for Microsoft), answers only the sign-in it started, and closes within 5 minutes. A firewall prompt for
it can be declined; nothing leaves the computer.

### Emailed sign-in codes

What it is for: job and application sites often email a one-time code when you sign in. With a mailbox connected, the
**Inbox** has an **Emailed sign-in codes** panel and a **Codes (N)** button appears at the top when one arrives. Each
code shows in large type with the sender's domain, **Copy** and **Dismiss**. **Check for a code now** looks in the
mailbox right away (read-only; nothing is marked read).

- Only codes from the last 15 minutes, only from senders whose mail passes DKIM/DMARC. Always check the domain, and
  enter the code only on the site you are signing in to right now.
- Codes are kept in memory for 15 minutes: never saved, logged, sent to an AI or typed anywhere for you. Before a mail
  goes to the AI or into the mail list, every code in it is replaced by `******`.
- Lodestar never stores an authenticator (TOTP) secret: next to your other sign-ins it would turn two factors into one.
  Your phone, passkey or security key stays the second factor.

There is no terminal command for codes; the regular mail check (`lodestar email check`, the monitor loop) also picks
them up while the app runs.

### Attachments

Outgoing (an Inbox email for a job can carry):

- that job's `resume.pdf`, `resume.docx`, `cover_letter.pdf`, `cover_letter.docx`;
- pdf, docx, png or jpg files you put in the job's `attach/` folder. **Show attach folder** on the email card opens it
  in Explorer; then pick the file from **Add from this job's files…**.

Limits: 10 MB per file, 10 MB per mail in total, 10 files. Never attachable: notes, interview prep, offer notes,
research, gap checks, calendar files, received mail, old versions, links (shortcuts, symlinks), and any document that
names your salary floor (it shows greyed out in the list with the reason). Drafts you ask for (outreach, referral asks,
replies to verified mail) pre-tick your tailored resume; you can remove it with `×`. The files are checked again just
before sending; if one changed or vanished, nothing is sent.

Incoming: attachments of mail filed under a tracked job are saved under
`~/.lodestar/applications/<job>/mail/<date>-<id>/` (pdf, docx, odt, txt, png, jpg, gif, ics, csv, xlsx; 10 MB each,
25 MB and 10 files per message). On Windows they are marked as downloaded from the internet. The job's Mail section
lists them with **Show in folder**. Programs, scripts, web pages and macro documents are never kept, forwarded messages
are skipped, and Lodestar never opens a received file. Mail no job claims keeps its files in your mailbox. A calendar
invite (.ics) fills in the interview time when the mail text gives none; the trust rules decide whether it becomes an
interview round. Backups leave the saved mail files out (they are still in your mailbox).

### Notification email address

`LODESTAR_NOTIFY_EMAIL` is where Lodestar emails you. It is sent from your connected mailbox, so connect email first.

- Every alert (new matching jobs, watch hits, monitor messages) is also emailed there.
- The weekly digest the monitor loop prepares is emailed there; without it you get a one-line alert that the digest is
  ready.
- `lodestar digest --send` and Monitor > **Email digest** send to it, or to your connected address when it is not set.

Set it in Setup > Other secrets (name `LODESTAR_NOTIFY_EMAIL`), or:

```powershell
lodestar vault set LODESTAR_NOTIFY_EMAIL you@example.com
lodestar digest --send     # try it: prints where it went
```

If sending fails, the alert still lands in `~/.lodestar/alerts.log` and the terminal shows `(email notify failed: ...)`.
Pop-up notifications on this computer are a separate switch (Setup > Desktop notifications).

### Email commands

| Command | What it does |
|---|---|
| `lodestar email connect [--preset P] [--user U] [--imap-host H] [--imap-port N] [--imap-mode ssl\|starttls] [--smtp-host H] [--smtp-port N] [--smtp-mode ssl\|starttls] [--smtp-user U] [--cafile PATH]` | store address, servers and app password (asked for, not shown), then test |
| `lodestar email client google\|microsoft` | store your own sign-in client (Google: ID and secret; Microsoft: Application ID) |
| `lodestar email signin google\|microsoft [--work] [--hint ADDRESS] [--no-browser]` | sign in on the provider's page, then test |
| `lodestar email test` | IMAP and SMTP login check; sends nothing |
| `lodestar email test-send` | a test email to your own address |
| `lodestar email status` | address, preset, servers, overriding environment values, sign-in warnings |
| `lodestar email disconnect` | remove the app password, or sign out |
| `lodestar email check [--days N] [--dry]` | scan the mailbox for hiring mail: classify, file under jobs, propose replies; `--dry` changes nothing |
| `lodestar doctor` / `lodestar doctor --live` | the email line, sign-in state and last check / plus one real IMAP and SMTP login |

Settings behind Connect email (kept in the keyring; an environment or `.env` value wins): `EMAIL_PRESET`, `IMAP_USER`,
`IMAP_HOST`, `IMAP_PORT`, `IMAP_MODE`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_MODE`, `SMTP_USER`, `MAIL_CAFILE`, `EMAIL_AUTH`,
and the secrets `IMAP_PASS` or `OAUTH_REFRESH`; your client in `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`MS_CLIENT_ID`. Prefer Setup or `lodestar email connect` over writing these by hand.

## Profile and documents

Everything Lodestar writes for an employer (resumes, cover letters, form answers) is built from one place: your
**master profile**. This part of the guide covers how to fill it, how to import what you already have, and every
document Lodestar makes from it.

How the pieces connect:

- **profile.md** (the master profile) is the text you own and edit. Its Preferences section is private.
- **profile.json** (the profile bank) pools facts from every resume and LinkedIn export you import, each with its
  source.
- The **master resume** (`resumes/master.*`) is profile.md printed as a clean resume, rebuilt for you whenever the
  profile changes.
- The **resume studio** makes a new resume version from a request in your own words plus formatting choices.
- **Per-job documents** (tailored resume, cover letter, form answers, research pack) live in the job's folder under
  `applications/`.
- The **document viewer** shows any of these as real pages, lets you change the formatting, and downloads PDF, DOCX,
  TXT, MD or HTML.

In the app, everything here is on the **Profile**, **Studio** and **Answers** tabs and in a job's drawer (click a card
on the Board). All files named here are in your data folder; the full list is in [Where your data lives](#where-your-data-lives).

### Quick start: from nothing to a finished resume

1. Import the resume you already have (skip to step 3 if you prefer to type it):

   ```powershell
   lodestar profile import "$HOME\Documents\resume.docx" --no-ai
   ```

   You should see a numbered list of facts, each marked `new`, and the line
   `nothing saved to the bank yet: lodestar profile review <id> --accept new`.
2. Accept the new facts (use the id the import printed):

   ```powershell
   lodestar profile review 02c13f4a --accept new
   ```

   You should see `applied 02c13f4a: added ...; profile.md updated` and a `master resume:` line naming `master.pdf`
   (`master.html` without a PDF engine) with `(first build)` or what changed.
3. Open profile.md (Profile tab, or the path `lodestar resume profile` prints) and fill in what is missing, including
   the Preferences line.
4. Check it offline:

   ```powershell
   lodestar resume lint
   ```

   `no issues found` means the offline checks pass; otherwise each issue has a line number and a fix hint.
5. Look at your master resume: Profile tab > Master resume > **View / format**, or `lodestar resume master`.
6. For a specific job, track it, then use the drawer's **Build in Studio** or **Tailor resume (+docx)**, and
   **Cover letter (+docx)** (these need an AI key: [AI keys](#ai-keys)).

### The master profile (profile.md)

**What it is for.** The single source of truth about you. Lodestar trims and rewords it per job but never adds facts
that are not in it (or in your profile bank). Put everything in it: every job, every bullet, numbers, projects,
education, certifications.

**How to create it.** `lodestar init` (and the installer) creates a starter template with these sections: Contact,
Summary, Skills, Experience, Projects, Education, Certifications, Preferences. While it still holds only the
template text, Lodestar treats your profile as empty.

**Format that reads best.** Keep `##` section headings (Experience, Education, Skills and so on; `## Work History`
also counts as Experience) and one `###` line per role, then `-` bullets:

```markdown
## Contact
Jane Example | Austin, TX | jane@example.com | +1 555 010 2000 | linkedin.com/in/jane-example

## Experience
### Senior Software Engineer | Acme Corp | Austin, TX | Jan 2021 - Present
- Cut API latency 40% by redesigning the caching layer

## Preferences (used for job search ranking)
Target roles: | Locations / remote: | Salary floor: 150000 | Deal-breakers: | Industries to avoid:
```

A section Lodestar does not model (for example "Security clearance") is kept under its own heading.

**The Preferences section is private.** Target roles, locations, salary floor and deal-breakers feed job ranking,
gap checks, offer review and coaching. They never go into a resume, letter, email or form answer. If your salary floor
appears anywhere outside Preferences in something an employer would read, Lodestar refuses to build or export it.

**Edit it in the app.** Profile tab: the editor, then **Save**. Next to it:

- **Check**: instant offline checks (see "Resume check and file audit" below); line numbers match the editor.
- **AI review**: a critique of the text in the editor (needs an AI key; the critique is given the Check results).
- **Adjust** (the box above the editor, for example "tighten to one page"): the AI rewrites the editor text, keeping
  every fact. Nothing is saved until you click **Save**.

**Edit it from the terminal.** `lodestar resume profile` prints the file's path; open it in any text editor.

```powershell
lodestar resume review                                    # AI critique of the master profile (or: lodestar resume review file.md)
lodestar resume adjust "rewrite the summary for data roles"         # prints the result only
lodestar resume adjust "rewrite the summary for data roles" --save  # writes it (old version kept)
```

`resume adjust` also works on a job document: `--job ID --doc resume.md` (or `cover_letter.md`).

**Safety.** Every write Lodestar makes to profile.md first copies the old file to `profile-history\`. If an import
or an AI change (Apply suggestions, Full AI) changed profile.md after you opened the editor, **Save** is refused with
"profile.md changed since you opened it (an import or an AI change wrote it): copy your text, reload, then redo your
edit", so nothing written meanwhile is erased. After an AI change, Undo AI changes also makes Save work again.

### The profile bank

**What it is for.** A pool of facts from every resume and LinkedIn export you import: contact, summary, skills,
spoken languages, experience (with location and technologies), education (with honors), certifications (issuer,
dates, credential id, link), projects, awards, publications, volunteering, patents, speaking, links, interests and any
other section. Each fact keeps its source and the line it was read from.

**How prompts use it.** AI prompts read your master profile plus any bank facts the profile does not mention yet
(shown to the AI as "On file"). Facts that are only in the bank do not appear on your master resume: add them to
profile.md, or run **Rebuild master profile from bank**.

**In the app.** Profile tab > Profile bank: skill, language and certification chips with **Add**, the LinkedIn link,
**Saved resumes**, **Rebuild master profile from bank**, **Re-read my master profile** and **Audit latest saved resume
file**.

**From the terminal:**

```powershell
lodestar profile show                                     # contact, skills, languages, counts, saved resumes (with ids)
lodestar profile add skills "Terraform" --detail Tools    # --detail: category (skills), proficiency (languages), issuer (certifications)
lodestar profile remove skills "Terraform"
lodestar profile link https://www.linkedin.com/in/your-name
lodestar profile rebuild                                  # regenerate profile.md from the bank; the old file goes to profile-history\
lodestar profile reread                                   # read profile.md itself into a review
```

`profile rebuild` keeps your Preferences section. `profile reread` is useful after you type new roles into profile.md
by hand, or to fix education entries saved on one line by older versions; it creates a review like an import does.

**AI helpers (Profile):** **AI review**, **Adjust**, **Merge into my profile (AI)** and the Profile and Profile bank toolbars. No extra AI help menu.

### Importing resumes and LinkedIn exports (with review)

**What it is for.** Bringing in what you already have instead of typing it. Nothing reaches the bank or profile.md
until you accept it in a review.

**Supported files.**

| File | Notes |
|---|---|
| `.docx` | Headings and list bullets are kept. |
| `.pdf` | Needs the `pypdf` module. `install.bat`, `start.bat` and `install.sh` install it; after `start.sh` or a plain `pip install -e .`, run `pip install -e ".[pdf]"`. A scanned PDF has no text: "no text found ... (a scanned PDF needs OCR first)". |
| `.md`, `.txt` | Read as plain text. |
| LinkedIn `.zip` | The "Download your data" archive. Only profile facts are read (Profile, Positions, Skills, Languages, Education, Certifications, Projects, email, phone); the archive itself, with messages and connections, is never stored. |
| LinkedIn profile PDF | The profile's "Save to PDF" file. |

Uploads in the app are limited to 15 MB.

**Import in the app.**

1. Profile tab > **Import an existing resume**: choose the file, click **Import**. For LinkedIn, use the Profile bank's
   file picker and **Import LinkedIn** (the **Request my LinkedIn data** link opens LinkedIn's download page,
   https://www.linkedin.com/mypreferences/d/download-my-data; on LinkedIn it is Settings > Data privacy > Get a copy
   of your data, and the basic archive arrives by email).
2. To keep the file away from any AI provider, tick **offline only** first (the box is in the Profile bank panel and
   covers both the LinkedIn import and Import an existing resume). Offline reading is verbatim.
3. A **Review import** panel appears. Each row has a status, the kind of fact, the fact, and the line it came from.
4. Click **Accept all new**, or tick rows and click **Apply selected**. For conflicts choose **keep mine**, **use
   incoming** or (when it looks like a separate role) **add separately**. Untick **also add to my master profile
   (profile.md)** to keep the facts in the bank only. **Discard** drops the review.
5. A message like "applied: 6 skills, 2 experience; 0 updated; profile.md updated" confirms it. The master resume
   rebuilds shortly after.

**Import from the terminal.**

```powershell
lodestar profile import "$HOME\Documents\resume.docx"            # uses AI when a key is linked
lodestar profile import "$HOME\Documents\resume.pdf" --no-ai     # offline only
lodestar profile linkedin "$HOME\Downloads\Basic_LinkedInDataExport.zip"
lodestar profile review                                          # imports waiting, with their ids
lodestar profile review b0ec8f25                                 # show one
lodestar profile review b0ec8f25 --accept new                    # new and changed rows that are not flagged
lodestar profile review b0ec8f25 --accept i13,i17 --take i13=incoming
lodestar profile review b0ec8f25 --discard
```

`--accept` takes `new`, `all`, `none` (applies nothing and closes the review) or item ids. `--take` sets conflict
choices: `i4=incoming` or `i7=both` (the default is mine). `--no-master` keeps accepted facts in the bank only. The
same `--accept` / `--take` / `--no-master` flags work directly on `profile import` and `profile linkedin` to apply in
one step.

What a review looks like (a second resume where one title and the email differ):

```text
import b0ec8f25: sample_resume2.md (offline extraction)
      i1   duplicate contact        name: Jane Example
  [ ] i2   conflict  contact        email: jane.e@example.com
  [ ] i13  conflict  experience     Staff Engineer | Acme Corp | Austin, TX | Jan 2021 - Present
                                    title: yours 'Senior Software Engineer | Acme Corp ...' | incoming 'Staff Engineer | Acme Corp ...'
  [x] i17  new       awards         Hackathon winner, Acme Corp, 2022
nothing saved to the bank yet: lodestar profile review b0ec8f25 --accept new  (or all, none, i1,i3)
```

**Statuses.**

| Status | Meaning |
|---|---|
| new | Not in your bank yet. Ticked unless flagged. |
| changed | Fills empty fields or adds bullets to an entry you have. Ticked unless flagged. |
| conflict | A field differs, or the same company with another title and overlapping dates. Yours is kept unless you choose otherwise. |
| duplicate | Already in the bank; only the source is recorded. |

**Checks on what was read.** When AI reads the file, every company, title, school, degree, contact value, link,
date, bullet and quote it returns must be found in the file; anything else is flagged ("not in file", "bullet 2
reworded" with the original line offered) and starts unticked. Offline, a guessed title/company split or a lost end
date is flagged too. Lines the offline reader could not place are listed under "line(s) were not read into the
profile".

**Personal details are not stored.** Date of birth, age, gender, marital status, children, nationality, religion,
ethnicity, ID / passport / social security numbers, health, height and weight, photos, political affiliation, pay
lines, a References section and any Preferences span are removed before any parser or AI provider sees the text. The
review names what was dropped by label and line number, never the value, for example `not stored: date of birth (line
8), nationality (line 9)`. Note: the original file you imported is kept as you gave it in `resumes\` (for a .docx or
.pdf, the extracted `.txt` beside it is the cleaned text). Delete it there if you do not want the original on disk.

**After "use incoming".** The role's header is replaced; bullets from both versions are kept. Read the role in
profile.md afterwards and delete the bullet you no longer want.

**Older one-step import.** `lodestar resume import FILE [--merge] [--save]` still exists: it prints the file's text,
`--merge` folds it into the profile structure with AI, and only `--save` writes profile.md. The review flow above is
the recommended way.

### The master resume

**What it is for.** A ready-to-send resume that always matches your profile: `resumes\master.pdf`, `.docx`, `.md` and
`.txt` (an `.html` print page instead of the PDF when no PDF engine works). Preferences and bank-only ("On file")
facts are left out. It is drawn in your saved look (pref `resume_look`), else the `resume_style` preset.

**How it stays current.** It is rebuilt offline, with no AI:

- about 20 seconds after profile.md or the bank changes while the app, desktop window or monitor loop runs;
- at the end of any CLI command that changes the profile (you see a `master resume: ...` line with what changed).

Resumes already tailored for a job are never rewritten. Their drawer shows "Profile changed since this resume was made
(Experience)" only when a section that resume used changed.

**In the app.** Profile tab > **Master resume** card: status (built when, engine, pages; "profile changed: updates
shortly" while a rebuild is due), what changed, warnings, **Open PDF** (**Open print page** when no PDF engine
worked), **Open DOCX**, **View / format**, **Show folder**, **Update now**.

**From the terminal:**

```powershell
lodestar resume master             # files, engine, build time, what changed, warnings
lodestar resume master --rebuild   # rebuild now
```

`master.json` keeps the engine used, page count, what changed ("skills +Terraform"), the last 20 builds, warnings
(a section that looks private, a personal-data line) and the last error.

**Common problems.**

- "fill in your profile first (Profile tab, or import a resume)": profile.md is still the template and the bank is
  empty.
- "close master.pdf (open in another program), then Update now": a PDF viewer holds the file. Close it; the old files
  stay until the next build.
- A salary floor outside Preferences stops the build and nothing is printed; the error says so. Move the figure into
  Preferences.

### PDF engines

Lodestar prints PDFs from the same HTML page you see in the preview. It tries, in order:

1. A headless Chromium browser with a throwaway profile: Microsoft Edge, then Chrome, then Chromium (Windows: the
   Program Files folders and your per-user install; macOS: `/Applications`; Linux and others: `msedge`,
   `microsoft-edge`, `google-chrome`, `chrome`, `chromium` or `chromium-browser` on PATH). Every Windows 11 PC has
   Edge. Set `LODESTAR_BROWSER` (in `.env` or as an environment variable) to the full path of another Chromium-based
   browser to use it instead.
2. Microsoft Word through COM (Windows only, 2-minute limit), on the .docx.
3. LibreOffice (`soffice --headless`), on the .docx.
4. Nothing worked: an HTML page with print styles is written (and, for `resume export --pdf`, opened in your browser).
   Print it and choose "Save as PDF".

The browser gets 60 seconds per PDF. Steps 2 and 3 apply to `resume export --pdf`, the master resume and studio
builds. The document viewer's PDF tab and PDF download use step 1 only.

`lodestar doctor` shows which engine was found, for example `[PASS] PDF engine  edge (C:\Program Files
(x86)\Microsoft\Edge\Application\msedge.exe)`.

If a build says `PDF engine: edge: no PDF written (exit 0)`, the browser was found but did not write the file. Try
again with Edge closed, check that security software is not blocking `msedge.exe --headless`, or point
`LODESTAR_BROWSER` at Chrome. Without a PDF the studio cannot count pages ("page count unknown ... the page limit was
not checked").

### The resume studio

**What it is for.** Making a resume version from a request in plain words ("one page, lead with leadership, modern with
a navy accent, drop the 2015 job"), optionally aimed at a job, with full control of the formatting. You get PDF, DOCX,
plain text and markdown, a preview, the page count, JD coverage and the ATS checks.

**How it keeps to your facts.** One AI call plans the resume by citing fact ids from your profile (see them with
`lodestar resume catalogue`). Employers, titles, dates, schools, degrees, certifications, contact details and links
are copied from your profile by id; the AI never writes them. The AI writes only the headline, summary, bullet
wording and skill-group labels, and each of those is checked: a rewrite that adds a number (including years and
dates), a skill or tool its own role never mentions, a seniority word, a degree, a name, a link, email or phone, or
personal data or pay goes back to your own words. You see each such correction in the result. The one computed number
allowed is "N years" from your earliest role. The job description and your request are treated as data, and contact
values never reach the AI.

**Page limit.** When the result is over the limit, the AI gets one "only remove or shorten" pass; then the last
bullet of the longest role (oldest first) and then optional sections are cut until it fits (at most 8 renders).
Still over is reported as a warning.

**In the app (Studio tab).**

1. Type your request in **Request**.
2. Optional: pick a tracked job under **target**, or paste a job description.
3. Optional: open **Requirements and formatting** to set the look, the sections and their order, **leave out
   entries**, **include facts from my other resumes**, and the formats. Left blank, the request, your saved look and
   then the template decide.
4. Click **Build** (needs an AI key) or **Build without AI** (your profile as written, with your sections, bullets per
   role, leave-out and page settings).
5. The result shows pages, engine, coverage, the AI's notes, every guard event and warning, and a preview. Buttons:
   **Open PDF** / **Open DOCX** / **Open TXT** / **Open MD** / **Open page**, **View / format**, **Make this my
   default look**, **Use for this job** (replaces that job's resume.md / .docx / .pdf; the old ones go to
   `history\`) and **Refine** (a follow-up such as "shorter").
6. **Versions** lists every build with **Open** and **Delete**; **Show folder** opens `studio\`.

From a job's drawer, **Build in Studio** opens the tab aimed at that job.

**From the terminal:**

```powershell
lodestar resume catalogue                                        # your facts with their ids (e1 = a role, e1.b2 = its 2nd bullet)
lodestar resume build --request "one page, lead with leadership" --job 1
lodestar resume build --no-ai --job 1 --pages 1 --style modern --accent navy
lodestar resume build --from 20261110-184244-example-co-backend-engineer --request "shorter summary"
lodestar resume build --no-ai --drop e3,p2 --since 2015 --format pdf,docx,txt
lodestar resume build --job 1 --use-for-job                      # also make it job 1's resume
lodestar resume versions                                         # newest first
lodestar resume open 20261110-184244-example-co-backend-engineer --format docx
```

A build prints the version id (AI or offline, the page count and the PDF engine), each file, the JD coverage and
any warnings. This example is an offline build on a PC where no PDF could be printed, so the page count is `?`:

```text
version 20261110-184244-example-co-backend-engineer (offline; ? page(s); no PDF engine)
  ...\studio\20261110-184244-example-co-backend-engineer\Jane-Example-Resume.docx
  ...\studio\20261110-184244-example-co-backend-engineer\Jane-Example-Resume.md
  ...\studio\20261110-184244-example-co-backend-engineer\Jane-Example-Resume.txt
  ...\studio\20261110-184244-example-co-backend-engineer\Jane-Example-Resume.html
  JD coverage 73%; missing: communication, terraform
  - page count unknown (no PDF engine: Edge, Chrome, Word or LibreOffice): the page limit was not checked; ...
```

With a working PDF engine you also get the `.pdf`, the real page count and the engine's name.

**Build options** (`lodestar resume build`; the same choices are in the app):

| Option | Values |
|---|---|
| `--request TEXT` | What you want, in words. Needs an AI provider. |
| `--job ID` / `--jd FILE\|URL\|TEXT` | Aim at a tracked job, or at a job description. |
| `--from VID` | Refine that version with `--request`. If your profile changed since, it is built fresh from the earlier requests plus yours. |
| `--pages 0\|1\|2` | Page limit (0: none). |
| `--style classic\|modern\|compact` | Template. |
| `--font F` | Calibri, Arial, Helvetica, Verdana, Tahoma, Georgia, Cambria, Garamond, Times New Roman, Book Antiqua. |
| `--size PT` | Body size, 9.5 to 12. |
| `--accent C` | `#rrggbb` or navy, blue, teal, green, burgundy, gray, black. |
| `--margins IN` | 0.4 to 1.25 inches. |
| `--spacing X` | Line spacing 1.0 to 1.5. |
| `--paper letter\|a4` | Page size. |
| `--date-format F` | `Mar 2021`, `March 2021`, `03/2021`, `2021-03` or `2021`. |
| `--contact one_line\|two_lines\|centered` | Contact line layout. |
| `--density compact\|normal\|airy` | Spacing overall. |
| `--sections a,b` | Sections in order, for example `summary,experience,skills,education`. |
| `--bullets N` | Bullets per role (0: all). |
| `--drop e3,p2` | Fact ids to leave out (from `resume catalogue`). |
| `--since YEAR` | Leave out entries that ended before this year. |
| `--on-file` | Also use facts from your other resumes. |
| `--format pdf,docx,md,txt,html` | Files to write (default `pdf,docx`; the markdown and the HTML page are always kept). |
| `--no-ai` | Offline: your profile as written. Cannot be combined with `--request`. |
| `--use-for-job` | Make it the job's resume.md / .docx / .pdf. |

A value you type that is not allowed is refused (for example a font outside the list); a value the AI picks that is
not allowed is dropped with a note. Every format is single column with no tables, text boxes or header contact, so it
passes the file audit.

**Your default look.** **Make this my default look** saves the version's look as the preference `resume_look`, where
later builds, the master resume and the viewer start. From the terminal, set it one key at a time:

```powershell
lodestar tools set resume_look font=Georgia
lodestar tools set resume_look accent=navy
```

**Used by the pipeline.** The pipeline's Tailor resume step builds the job's resume in the studio with your look (one
page unless the look says otherwise) and uses it for the job. What it asks for is the preference `resume_request`
(empty: a strong resume for the job): `lodestar tools set resume_request "one page, lead with impact"`. The step reads
stale when a profile section that resume used changes.

**Common problems.**

- "add an AI provider to describe changes in words (Setup > Link an AI key), or clear the request and use Build
  without AI": you typed a request but no AI key is linked.
- "fill in your profile first (Profile tab, or import a resume)": nothing to build from yet.
- A build stopped because a salary floor appears outside Preferences: nothing was written. Move the figure into
  Preferences.

**AI helpers (Studio):** **Build** is the AI request itself; no extra menu.

### The document viewer and formatting panel

**What it is for.** One place to see any generated document as real pages, adjust how it looks, edit it, compare
versions and download it in any format.

**Where to open it.**

- Profile tab > Master resume > **View / format**.
- Studio tab > a version > **View / format**.
- A job's drawer: pick a document tab (resume.md, cover_letter.md, form_answers.md and so on) and click **View /
  format**; **View** next to **Interview prep** and **Company research**; Admin > **View documents** for the whole
  packet (switch documents with the select at the top).
- Insights > offers: **View offer notes**, and **View / format the draft** for an unsaved counter-offer.

**What you see.**

- **Preview**: Letter or A4 sheets with your margins and page breaks, "Page 1 of 2" under each, zoom (fit width,
  100%, fit page), the page count, and a marker on every page past the limit. Click a heading to jump to that
  section's editor.
- **PDF**: the file headless Edge (or Chrome / Chromium) prints from the same page, with its page count. The viewer
  uses only a browser engine (not Word or LibreOffice): without one, the PDF tab and download say so; download the
  DOCX or the HTML page and print that. **DOCX**: the same pages, labelled as a Word
  layout preview (Word may differ slightly). **TXT** and **MD**: the exact text of those downloads (TXT is what an
  ATS text box gets).
- **Print**, **Open in new window** (written to `exports\` and opened), **Download** PDF / DOCX / TXT / MD / HTML,
  and **compare with** another version side by side (the master, studio versions, a job document's earlier versions
  from `history\`), with what changed in words.

**Format panel** (changes show live): template, font, base size, heading size, accent (a named colour or any colour),
margins, line spacing, paragraph spacing, page size, page limit, density, date format, bullet style (disc, circle,
square, dash, none), contact line, heading case (upper or title), and **Sections** (drag or use the arrows to
reorder; untick to hide). Picking another template resets this document's other look choices to that template's.
Letters also get the date line, the recipient block and the signature. Changes are kept for that document in
`viewer.json`. **Save as my default look** writes `resume_look`; **Reset to template** drops this document's look. A
studio version opens in its own look.

**Edit text panel.** One editor per section. Edits change the preview and the downloads. For a job's documents,
**Save document** keeps them (the old version goes to `history\`); elsewhere (the master resume, studio versions,
drafts) edits apply only to what you preview and export, and there is no Save button. **Discard edits** throws them
away. Switching documents with unsaved edits, or closing the viewer with unsaved edits to a job's document, asks
first.

**Safety.** Every export and every **Save document** re-runs the salary-floor guard: a resume, cover letter, form
answers or counter-offer draft that names your floor or private Preferences is refused ("this document names your
salary floor ...: edit it out before it is exported or sent"), and nothing is saved. Your private notes (prep,
research, offer notes) are not checked. For resumes, each line you changed is checked against your profile: a new
number, tool, title or link shows "not in your profile" above the preview. A download (or Open in new window) then
asks **Export anyway?**, and **Save document** asks **Save anyway?** ("Mail and the application packet will use this
text"), because the saved text is what later exports, mail and the packet read. Cancel keeps the document as it was.
Lines that state personal data are flagged too.

### Tailoring a resume for a job

There are three ways; all start from your master profile (or a saved resume) and leave Preferences out.

**1. The studio** (recommended): see above. Drawer > **Build in Studio**, or `lodestar resume build --job ID`.

**2. Whole-document tailoring.** One AI call rewrites the resume for the posting, told to use only your facts.

- App: drawer > Documents > **Tailor resume (+docx)**. Tick **council (all providers)** to pool every configured
  provider. **tailor from** picks a saved resume instead of the master profile.
- Terminal:

  ```powershell
  lodestar resume tailor 1 --docx
  lodestar resume tailor 1 --base cded1577 --docx    # start from a saved resume (ids: lodestar profile show)
  lodestar resume tailor 1 --council                 # every configured provider, then a synthesis
  ```

The result is the job's `resume.md` (and `resume.docx`); the previous one moves to `history\`. JD coverage is
re-scored and the timeline logs `coverage 54 -> 78`. This mode has no line-by-line fact check; read the result, or use
the studio or bullet tailoring, which check every rewrite.

**3. Bullet-by-bullet tailoring.** One AI call proposes a rewrite per experience and project bullet, adding the
posting's missing keywords only where your facts allow, plus an order per role. Two offline checks then flag rows:
**unsupported** (a keyword, skill, certification or degree that appears nowhere in your profile, bank or the source
resume) and **new number** (a number the original bullet does not have). Flagged rows start unticked.

- App: drawer > **Tailor by bullet**. The table shows original, proposed (added keywords highlighted, flags in amber)
  and accept. **Accept all unflagged** resets the ticks; **Build resume** writes `resume.md`, regenerates
  `resume.docx` and re-scores coverage.
- Terminal:

  ```powershell
  lodestar resume tailor 1 --bullets            # numbered proposals, saved to bullets.json; resume.md untouched
  lodestar resume tailor 1 --accept unflagged   # or: all, or numbers like 1,3,5
  lodestar resume tailor 1 --accept 1,3,5 --docx
  ```

Bullets never move to another employer, and a build that would still contain "Salary floor" stops.

**Styles and PDF export.** The drawer's **style** select (pref `resume_style`: `classic`, `modern`, `compact`) sets
the .docx and PDF look when no studio look is saved; a `template.docx` next to profile.md overrides it. **Export PDF**
(or the terminal) prints the job's resume with the engines listed under "PDF engines":

```powershell
lodestar resume export 1 --pdf                       # job 1's resume.md -> resume.docx + resume.pdf
lodestar resume export "$HOME\Documents\resume.md" --style compact   # any markdown file -> .docx beside it
```

**Profile changed since.** A tailored resume is never rewritten on its own. When a section it used changes, the
drawer says "Profile changed since this resume was made (...). It was not rewritten: it may already have been sent."
Tailor again if you want the new facts in it.

### JD coverage and the gap check

**JD coverage** (no AI) shows which of the posting's keywords your current resume mentions: the job's tailored
resume.md, else your profile without Preferences. It uses a lexicon of about 1,500 terms with aliases (`k8s` =
Kubernetes). Weights: hard skills 45%, job title 15%, education 10% (only when the posting names a degree), soft
skills 10%, other repeated phrases 20%. It is a guide for tailoring, not a pass/fail ATS verdict.

- App: drawer > Match > **Compute JD coverage** (or **Recompute**). Mark a keyword **not mine** to leave it out of the
  score for that job.
- Terminal:

  ```powershell
  lodestar match 1
  lodestar match 1 --skip terraform                  # mark 'not mine' (again to undo)
  lodestar match 1 --file "$HOME\Documents\other.docx"   # score another file without saving
  ```

What you should see:

```text
#1 Example Co - Backend Engineer
JD coverage 73/100
  hard        75%  3/4
  ...
missing (most mentioned first): communication (1x), terraform (1x)
matched: aws, kubernetes, python
```

The job needs a job description (drawer > Admin > **set JD**, or `lodestar jobs add ... --jd`). Only add a keyword
you can back up.

**Gap check** = coverage first (saved even without AI), then the AI's verdict, weak areas and suggestions. Drawer >
**Gap check (coverage + AI verdict)**, or `lodestar resume gap 1`. Without a key you get the coverage with the note
"no AI provider configured: keyword coverage only". The gap check sees your Preferences (it weighs pay against your
floor) and is private to you; only the parts that name no floor feed a cover letter.

### Resume check (lint) and file audit

**Check** (no AI): line-numbered issues by severity with a fix hint: weak openers, bullets without a number,
pronouns, passive voice, repeated verbs, long or short bullets, cliches, missing email, phone or section headings,
employment gaps (info). The 0-100 score is secondary.

- App: Profile tab > **Check**; drawer > **Check resume**.
- Terminal: `lodestar resume lint` (master profile), `lodestar resume lint file.docx`, `lodestar resume lint --job 1`.

**Audit** inspects a .docx or .pdf file for things parsers trip on: contact details in the header or footer,
tables, text boxes, images, columns, fonts under 10 pt, non-standard headings, scanned PDFs, size and file name, and
shows the plain text a parser sees.

- App: drawer > **Audit resume.docx**; Profile bank > **Audit latest saved resume file**.
- Terminal: `lodestar resume audit "$HOME\Documents\resume.docx"`. A PDF's text checks need `pypdf`.

### Cover letters

**What you get.** A complete letter: your contact block, date, addressee (the job's contact or Hiring Manager),
greeting, 3-4 paragraphs and sign-off. It reads the tailored resume, the gap check and the research pack when they
exist, so run those first for a better letter.

- App: drawer > **Cover letter (+docx)**, with **tone** and **words** boxes. **Cover options** asks for up to 3 letters
  in one AI call with one recommended; using one writes it to `cover_letter.md`.
- Terminal:

  ```powershell
  lodestar resume cover 1 --docx
  lodestar resume cover 1 --tone "warm, direct" --words 250 --council
  lodestar draft options cover 1 --options       # up to 3 numbered options
  lodestar draft options cover 1 --pick 2        # use option 2
  ```

The result is `cover_letter.md` (and `.docx`) in the job's folder. Edit it in the drawer (**Edit document**, then
**Save document**), adjust it with AI (the **Adjust** box, or `lodestar resume adjust "shorter" --job 1 --doc
cover_letter.md --save`), and format it in the viewer (date line, recipient block, signature). A letter that names your
salary floor is refused.

### Form answers and the answer bank

**The answer bank** keeps your answers to application-form questions so drafts can reuse them.

- App: **Answers** tab > Answer bank: question, answer, tags, the **private** box, **Save**. Each saved answer has
  **make private** / **allow for employers**.
- Terminal:

  ```powershell
  lodestar answers add "Notice period?" "Two weeks" --tags logistics
  lodestar answers add "Are you legally authorized to work in the US?" "Yes"
  lodestar answers add "Minimum salary you would accept?" "..." --private
  lodestar answers list
  lodestar answers rm 2
  ```

**Private answers** (`--private`, or the private box) are for you only: never used in an AI prompt for an employer, a
drafted answer, a letter or a form. `answers list` marks them `[private]`.

**Drafting an answer for a job.**

- App: Answers tab > pick the job, type the question, **Draft** (or **Options** for up to 3).
- Terminal: `lodestar answers ask 1 "Why do you want to work here?"`.

The draft uses the job's tailored resume (else your profile without Preferences), the research pack and your
employer-safe saved answers, and prints which saved answers it reused. Saving the new answer to the bank is proposed in
the Inbox (tool `answers`) unless you set that tool to auto.

**Questions only you answer.** Lodestar never drafts eligibility, work-authorization or EEO questions, however the form
words them: `answers ask` replies "Lodestar never drafts eligibility or EEO answers: write your own under Answers".
Write these yourself in the answer bank. One you wrote and did not mark private is filled in on forms; it is never
shown to an AI. An import review that drops a line such as nationality reminds you to put work authorization here.

**Form answers for a job** (`form_answers.md`) are produced by the pipeline's Form answers step: add the form's
questions in the drawer (**Add form questions**), run the step, and it drafts what it can and asks you the rest in
Inbox > Questions for you. Each answer is marked with its source and "check this" flags (a new number or an
unsupported skill). An answer that would name your salary floor is withheld. Open it in the viewer like any other
document. See [The step-by-step pipeline](#the-step-by-step-pipeline) for running steps.

**AI helpers (Answers):** **Draft** and **Options** for a form question; the answer bank's toolbar (Recommend is the improve button). Stories: see [STAR stories](#star-stories).

### Company research packs

**What it is for.** A short brief before an interview (and an input to cover letters and form answers): what the
company does, products and news, team and stack signals, the challenges this role solves, talking points, five
questions to ask, and things to verify.

**How it works.** It fetches the job's page, the company site and its `/about` page, a Wikipedia summary and a web
search page, respecting each site's robots.txt (skipped pages are named). Anything the sources do not support is marked
"(unverified)"; if nothing could be fetched, the pack says so at the top. The list of sources read is at the end. It
needs an AI key and network access. Your salary floor and private preferences are not in its prompt.

- App: drawer > **Company research**, then **View**.
- Terminal: `lodestar research 1` prints the path of `research.md`.

### AI suggestions on every tab (Recommend, Apply suggestions, Full AI, Undo)

**What it is for.** A second pair of eyes on your own content: profile.md sections, the profile bank, a job's details
and documents (resume, cover letter, form answers), the answer bank, STAR stories, contacts, saved searches, Inbox
drafts, plus a plan for today and advice on your Insights numbers. It never touches the app's settings or code.

**How it works.** Each of those places has the same AI toolbar: on the tab (Profile, Profile bank, Answers, Stories,
Contacts, Search and Monitor, Insights, Inbox, the Board's Today row) and on each card (a job drawer's Details and
Documents, a contact's drawer, each story, each Inbox email).

- **Recommend**: one AI call. Suggestions appear as cards: a checkbox, what is there now and what is proposed (removed
  lines in red, added lines in green), why, and the impact and risk. Nothing changes yet. A suggestion that adds a fact
  your profile does not state (a skill, number, title, employer, date or link) or names your salary floor is flagged,
  marked high risk and left unticked.
- **Apply suggestions**: writes the ticked cards. A card whose text you changed since the suggestion turns **stale**
  and is skipped; a flagged one is refused even if you tick it. The import review's **Apply selected** button is a
  different button and keeps its meaning.
- **Full AI**: Recommend, then everything that passes those checks is written for you. The first time, it asks you to
  confirm. It never sends mail, submits anything, changes a job's status, adds jobs, or touches settings, automation or
  the vault; Inbox drafts it improves still wait for your approval. Search, Today and Insights have no Full AI (Today
  and Insights are advice only; a new saved search or watched company stays your click).
- **Undo AI changes**: puts the last AI change made from this toolbar back exactly. A field you edited since keeps your
  version. Setup > Data > **AI changes** lists every batch, with what each field was before, and an **Undo this
  batch** button.

Without an AI provider every one of these buttons says it needs one (a linked key, or **Local only (Ollama)** in
Setup: local models count). Eligibility and EEO answers, private answers, your Preferences and the contact line are
never sent to the AI or changed by it.

- Terminal: `lodestar advise SCOPE [TARGET]`, then `--apply IDS`, `--auto`, `--undo BATCH`, `--history`.

#### AI help menus (the assist-button inventory)

Next to the toolbar, most places have a folded **✦ AI help** menu with a few more helpers. Each one is **one AI
call**, sends its material to the AI as data (a posting, a contact's notes and mail are never followed as
instructions; your salary floor and Preferences never go in), and shows its answer as a card you read: **nothing is
changed**. The one helper that proposes edits, **Fill STAR from my notes**, puts suggestion cards in that story's AI
toolbar, and only **Apply suggestions** writes them (Undo puts them back). Without an AI provider every helper says
it needs one and calls nothing. Terminal: `lodestar ai-help` lists them, `lodestar ai-help NAME [TARGET]` runs one.

| Tab / box | AI that was already there | AI help menu (new) |
|---|---|---|
| Board, Today row | toolbar (Recommend: a priority plan, advice only), **Draft options** on suggested emails, **Run next step** / **Run to** | **What to do next**, **Plan my day** |
| Job drawer | toolbars on Details and Documents, pipeline steps, readiness explain, question set, gap check, tailor (whole / by bullet), cover letter and options, interview prep, company research, drafts and options, referral asks, offer evaluation, document Adjust and Review | **Summarise the posting**, **Red flags**, **Questions to ask them**, **Likely interview topics**, **Map my stories to this job** |
| Inbox, each email | toolbars, **Options**, **Shorter / Warmer / More formal / More direct / custom…** rewrites | (none: the rewrites cover it) |
| Contacts tab | toolbar | **Who to ask for a referral** |
| A contact's drawer | toolbar | **Draft an intro** (refused when it would name your salary floor) |
| Search | toolbar, **AI rank vs my profile**, **Auto-track strong fits** | **Suggest search terms** |
| Monitor | toolbar, **Weekly digest**, email dry-run | **Companies like my targets** (adding one to watch stays your click) |
| Ideas | **Craft**, **Refine** (the whole tab is AI) | (none) |
| Answers: the form and the answer bank | **Draft**, **Options**, the answer bank toolbar (Recommend = improve your answers) | (none: Recommend is the improve button) |
| Answers: each story | toolbar | **Fill STAR from my notes** (suggestions for Apply suggestions) |
| Coach | coach chat (council), mock interview with scored answers | (none: the tab is a conversation with the AI) |
| Insights | toolbar (advice only), counter-offer **Draft** / **Options** | **Explain my numbers** |
| Profile, Profile bank | toolbars, **AI review**, **Adjust**, **Merge into my profile (AI)**, AI import | (none) |
| Studio | **Build** (the request is the AI instruction) | (none) |
| Tools, Setup | **Test providers**, **List models**, **Diagnostics + live AI call** | **Explain this setting** (pick a Setup card or a preference; it explains it from this guide) |

### Settings in this area

| Setting | Where | What it does |
|---|---|---|
| `resume_style` | drawer **style**, Tools > Preferences, `lodestar tools set resume_style modern` | `classic`, `modern` or `compact`: the .docx / PDF look when no studio look is saved. |
| `resume_look` | Studio **Make this my default look**, viewer **Save as my default look**, `lodestar tools set resume_look key=value` | Your default look; every document starts from it. |
| `resume_request` | Tools > Preferences, `lodestar tools set resume_request "..."` | What the pipeline's Tailor step asks the studio for. |
| `name`, `signature` | Tools > Preferences | How drafts sign off (else the name from your profile). |
| Tool `answers` | `lodestar tools list` / Tools tab | Save newly drafted answers to the bank (manual: via the Inbox). |
| Tools `research`, `tailor`, `cover_letter`, `form_answers` | `lodestar tools list` / Tools tab | The matching pipeline steps. |
| `LODESTAR_BROWSER` | `.env` or environment | Path to the Chromium-based browser used to print PDFs. |
| `LODESTAR_HOME` | environment | Where all of the files above live. |

### Safety rules in this area, in short

- **Never invented.** Studio and bullet rewrites are checked line by line against your facts and revert or flag
  anything new; AI-read imports are checked against the file; the viewer asks before exporting resume lines your
  profile does not support.
- **Salary floor stays private.** Preferences never reach a resume, letter, form answer or research prompt. A floor
  that leaks into an employer-facing document stops the build or export.
- **You approve.** Imports wait for your review; saving AI-drafted answers waits in the Inbox; tailored resumes are
  never rewritten behind your back; every overwrite keeps the old version (`profile-history\`, `history\`).
- **Personal details** (date of birth, ID numbers, photos, pay and the like) are dropped from imports before any AI
  sees them and flagged if they appear on a resume.

## Finding and tracking jobs

This part covers everything between "I want a job" and "I applied and I am waiting": finding listings, keeping
standing searches, following companies' job boards, getting postings in from your browser, the Board where every job
you track lives, the Today agenda, follow-ups, the step-by-step pipeline that prepares each application, and the Inbox
where anything Lodestar wants to do on its own waits for your approval.

**Before you start.** Two things make this area work much better:

1. Fill in your master profile (`~/.lodestar/profile.md`, or the Profile tab; see [The master profile (profile.md)](#the-master-profile-profilemd)). Several features are skipped or stop
   while it is still the template: the fit score cannot measure skills (it shows "partial"), and the pipeline's Fit check
   stops with "your master profile is still the template".
2. Link at least one AI key (Setup > Link an AI key, or `lodestar keys link anthropic`). Searching, tracking, the
   Board, watches, company boards, H-1B hints and the Inbox all work without AI. AI ranking, auto-tracking, the fit
   verdict and the document steps of the pipeline need a provider.

### Job search (Search tab, `lodestar jobs search`)

**What it is for.** (Since pass 21 the tab is called **Jobs**, it also searches Himalayas, We Work Remotely and, with
your keys, Adzuna and USAJOBS, and every result is kept in All jobs: see [All jobs and job sources](#all-jobs-and-job-sources).)
One search across the free job sources that need no account or key: Remotive, Arbeitnow,
RemoteOK, HN Who is hiring, Jobicy and The Muse. Results are de-duplicated (the same company without Inc / LLC /
GmbH..., same title and same location is shown once, with the richest description and every link), filtered, and
optionally ranked against your profile by AI. LinkedIn and Indeed have no public API: use the Capture bookmarklet
(below) for those.

**In the app:**

1. Open the **Search** tab.
2. Type a query (for example `python backend`) and, optionally, must-have keywords (comma list; each must appear in
   the title or description).
3. Optional filters on the second row: **location, or remote**, **min salary**, **posted within (days)** and a
   seniority list (**any seniority**, intern, junior, mid, senior, staff, lead, manager).
4. Tick **AI rank vs my profile** if you want each result scored 0-100 with a one-line reason (needs an AI key).
5. Click **Search free job APIs**.

What you should see: a list of listings, each with title, company, location, salary when stated and the source in
angle brackets, an **open** link to the posting (plus a link per extra board it was found on), a **track** button and
chips:

| Chip | Meaning |
|---|---|
| `tracked as #N` | already on your Board |
| `JD coverage N%` | share of the posting's keywords your profile mentions (no AI; hover for matched and missing terms) |
| `possibly stale` | stale or ghost-posting signals add up (see "Stale signals" below); reasons listed under the listing |
| `possible H-1B sponsor (N approvals)` | only after you import USCIS data (see "H-1B sponsor hints") |
| `you know N people here` (or `1 person`) | a contact of yours works at this company (Contacts tab); a loose name match |
| `salary unknown` / `location unknown` / `date unknown` | the listing does not say; it is kept, not dropped |
| a seniority word | read off the title |

Click **track** to add a listing to the Board (Saved column) with its description, location, posting date and
source. **Auto-track strong fits** AI-judges the current results and proposes the strong ones (see "Auto-track"
below). **Save as watch** turns the query and filters into a standing alert (see "Saved searches").

**From the terminal:**

```powershell
lodestar jobs search "python backend" --keywords remote --rank
lodestar jobs search "data engineer" --location remote --min-salary 120k --posted-within 14 --seniority senior
lodestar jobs search "data engineer" --save 0 3      # track results 0 and 3 (indexes from the list)
lodestar jobs search "site reliability" --auto       # AI-judge and propose strong fits (tool auto_track)
```

Flags (from `lodestar jobs search --help`):

| Flag | Effect |
|---|---|
| `--keywords a,b` | comma list; each must appear in the title or description |
| `--rank` | AI fit score 0-100 against your profile; without a provider the results are shown unranked with the reason |
| `--limit N` | how many results (default 25) |
| `--save I J ...` | add those result indexes to the tracker |
| `--auto` | AI-judge the results and propose tracking strong fits (tool `auto_track`) |
| `--location TEXT` | a substring of the listing location, or `remote` |
| `--min-salary N` | the top of the stated range must be at least this (`120000` or `120k`; currency is not converted) |
| `--posted-within DAYS` | only listings posted in the last N days |
| `--seniority LEVEL` | intern, junior, mid, senior, staff, lead or manager, read off the title (no marker counts as mid; "Product Manager" stays mid) |

A listing that does not state its salary, location or date is kept and marked unknown, so a filter never silently
hides a good job.

**Private dealbreakers.** Two preferences drop listings before anything else, in searches, saved searches and
auto-tracking: `excluded_companies` and `excluded_title_words` (comma lists). Set them in the **Tools** tab under
**Preferences**, or:

```powershell
lodestar tools set excluded_companies "Initech, Globex"
lodestar tools set excluded_title_words "unpaid, commission"
```

They stay on your machine and are never sent anywhere.

**Auto-track.** The `auto_track` tool AI-scores listings against your profile and proposes tracking those at or above
`auto_track_min_score` (default 75; `lodestar tools set auto_track_min_score 80`, range 0-100). It runs on new
listings from saved searches and company boards in every monitor cycle, and on demand with **Auto-track strong fits**
or `--auto`. By default (enabled, not auto) each strong fit becomes an Inbox item you approve; set the tool to auto to
have them added straight to the Board. Listings with a stale score of 60 or more are left alone, and a listing already
on your Board is never proposed again. Auto-tracked jobs never count as applications in Insights.

**Where the data lives.** Search results are not stored; tracked jobs go into `~/.lodestar/lodestar.db`.

**AI helpers (Search):** **AI rank vs my profile**, **Auto-track strong fits**, the toolbar (saved-search keywords) and **✦ AI help** > **Suggest search terms** (queries and filters from your profile; you type the one you want).

### The fit score

**What it is for.** One number from 0 to 100 per job and per listing that says how well the posting matches you, with
the reasons as chips. It is worked out by rules from your profile and Preferences, so it is the same every time, costs
nothing, and works without an AI key. It is private: it never goes to an employer and never into an AI prompt.

**How it is worked out.** Five parts, each 0-100, weighted (defaults in `lodestar/data/fit.json`):

| Part | Weight | What it compares |
|---|---|---|
| Skills | 35 | the skills the posting requires (and, at half weight, its nice-to-haves) against your profile |
| Role | 20 | the title and level against your target roles and `target_seniority` (manager is its own track) |
| Experience | 15 | the years the posting asks for against your years (from your experience dates, or `years_experience`) |
| Location | 15 | the posting's place and workplace against your Preferences locations / remote |
| Pay | 15 | the posting's range against your private salary floor (below it is a penalty, not a block) |

Then modifiers: an excluded company or title word, or "no sponsorship" when you need it, blocks the job (fit 10 at
most); a deal-breaker word costs 25; clearance required costs 20; sponsorship offered, a watched company and people you
know add a little; a stale-looking posting loses up to 15. A part that cannot be measured (no description, no pay
stated) pulls the score toward 50, and under 60% measured the badge says **partial**.

**In the app.** The Board's card badge (`fit 74`, colour by band, the top reasons in its tooltip; dimmed while it is
being re-scored), the table's **Fit** column (and **Coverage**, the JD-coverage share, beside it), the **Best fit**
sort, and the drawer's **Fit** group: every part with its weight and chips, the modifiers, **Why not higher?** (the
points each part costs) and **AI fit** (one AI call that judges the posting against your profile without the floor; its
score joins as one more part, weight 25 at most). Today lists **Top new fits** (untracked listings of the last 3 days
at 70+), with Track.

**Settings** (Tools > Preferences): `fit_weights` (e.g. `skills=40`; `0` turns a part off; `reset` restores the
defaults), `work_authorization`, `target_seniority`, `years_experience`, `auto_track_min_score` (the threshold
auto-tracking compares the fit with) and `auto_track_daily_max` (proposals a day, default 10). Any change re-scores
every job and listing in the background.

```powershell
lodestar fit 12            # one job's breakdown: parts, weights, chips
lodestar fit refresh       # re-score everything that is out of date (no AI)
lodestar jobs list --sort fit
```

### All jobs and job sources

**What it is for.** Every listing any source found, in one list on the **Jobs** tab (the Search tab's new name):
searches, saved searches, company boards, captures and job-alert emails, merged across sources (the same company and
title at the same place is one row with every link and source), each with its fit.

**The sources.** Keyless: Remotive, Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, The Muse, Himalayas (expired
listings are removed) and We Work Remotely (RSS). With your own free keys: **Adzuna** and **USAJOBS**. Company feeds:
Greenhouse, Lever, Ashby, and SmartRecruiters, Recruitee and Personio where the employer made the feed public (when it
is not, Lodestar says so; add the careers page as a page watch instead). LinkedIn, Indeed, Glassdoor and ZipRecruiter
are never searched or fetched: their terms forbid it. Their jobs come in through job-alert emails (next section) and
the browser extension. Each source's name is shown as a link back to it, as Adzuna, Himalayas and We Work Remotely ask.

**Getting the Adzuna and USAJOBS keys.**

1. Adzuna: sign up at developer.adzuna.com, create an application, and copy its **Application ID** and **Application
   key**. Set the country with the `adzuna_country` preference (two letters, default `us`). Lodestar uses at most 100
   calls a day.
2. USAJOBS: request an API key at developer.usajobs.gov (it is mailed to you); Lodestar sends the email address you
   registered with as its User-Agent, as USAJOBS requires.
3. Setup > **Job sources** > the source's row: paste the values and click Link. Lodestar checks them with one small
   search and stores them in your OS keyring (vault names `ADZUNA_APP_ID` + `ADZUNA_APP_KEY`, `USAJOBS_API_KEY` +
   `USAJOBS_EMAIL`). From a terminal: `lodestar keys link adzuna` / `lodestar keys link usajobs`.

**Throttles.** Saved searches ask each board at most once per window (Remotive every 6 hours, Jobicy and most others
hourly). Remotive, Jobicy, RemoteOK and We Work Remotely limit calls per user, not per query, so Lodestar fetches them
once per window for all your searches together and filters locally. A manual search reuses that fresh copy, also
after a restart or from a separate `lodestar jobs search` run (the copy is saved under `cacheoards` in your data
folder); with no saved copy inside the window the board is skipped until the window passes. Setup >
Job sources shows each board's window and when it was last asked.

**In the app (Jobs tab > All jobs).** Filters (text, source chips with counts, minimum fit, workplace, minimum pay,
posted within, not tracked / tracked / dismissed / all, sort), **New since last visit** and **Mark all seen**; per
row **Track** (adds it to the Board), **Dismiss** / Undismiss and **AI fit**; click a row for its fit breakdown and
description. Untracked listings not seen again for 45 days drop off; tracked ones never do.

```powershell
lodestar jobs all --new --min-fit 60
lodestar jobs track-listing L42
```

### Job-alert emails (LinkedIn, Indeed, Glassdoor, ZipRecruiter)

**What it is for.** Those sites forbid automated reading, but they will email you new jobs. Lodestar reads those alert
emails from **your own inbox** and puts their jobs in All jobs, merged with every other source.

**Set it up.**

1. Connect your email (Setup > Connect email; see [Email: pick a way to connect](#email-pick-a-way-to-connect)).
2. On each site, run a job search and turn on its email alert, delivered to that same address (LinkedIn: Jobs > search >
   **Set alert**; Indeed, Glassdoor and ZipRecruiter: the email-alert option on a search results page; the labels change
   now and then).
3. Setup > **Job alerts**: the "Read job-alert emails" box (tool `job_alerts`) is on by default once email works. The
   panel shows, per site, when Lodestar last read an alert and how many jobs it held.

**What Lodestar does and never does.** An email counts as an alert only when it comes from the site's known alert
address **and** passed DKIM/DMARC; anything else from those sites (InMail, "application submitted") is ordinary mail.
Alerts are never classified by AI, never stored in the mail table, and their links are **never opened** (a link can
carry a sign-in token; notices never show one). A job you already track that shows up again gets one "seen in an
alert" line on its Listing activity. Strong new fits can be proposed by `auto_track` (they wait in the Inbox).

**When an alert is not read.** Lodestar sends one notice a day per site. Save the email as a `.eml` file (your mail
program: Save as / Download message) and run:

```powershell
lodestar email parse-alert alert.eml            # what it finds; changes nothing
lodestar email parse-alert alert.eml --trust    # skip the DKIM/DMARC check for a saved file
```

Lodestar's parser was built from hand-made samples; if a real alert reads wrongly, keep that `.eml` for a fix.

### The listing monitor and Listing activity

**What it is for.** Watching each job you track until it closes, both on the web and in your mail, in one timeline.

**Daily listing check (tool `posting_check`, on by default).** Once a day Lodestar looks at the posting of every open
tracked job:

- Jobs from a company feed (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Personio) are looked up in the live
  feed, one request per feed. A changed title, place, pay or description is recorded (the description diff goes to
  `posting_changes.md` in the job's folder; your job description is not replaced). A posting that disappeared is
  recorded as removed: for a **saved** job a move to `withdrawn` is proposed and always waits for you; for an applied
  one it is listed on Today as "posting closed". A posting that comes back clears it.
- Other posting pages at most weekly, at most 20 a run, only where robots.txt allows, and never LinkedIn, Indeed,
  Glassdoor or ZipRecruiter. A page counts as gone only after two misses in a row (a deploy's 404 does not).

**Mail from applicant-tracking systems** (Greenhouse, Workday, Lever, iCIMS ...: confirmations, status updates) is filed
under its job by the posting link, the Workday tenant, the iCIMS id or company + title, with the reason shown. It is
never treated as trusted, so a status change it suggests always waits in the Inbox.

**In the drawer: Listing activity.** One timeline, newest first: posting checks, alert sightings, the job's own events
and its mail both ways, plus a line saying whether the posting is open, removed or last seen in an alert. **Use live
description** replaces the job's description with the posting's current one (your click; tailored documents are not
touched); **View changes** opens the diff. `lodestar jobs show ID` prints the same timeline.

### Job intelligence

**What it is for.** What is publicly known about the company and the role, in one place, each fact with **where it
came from and its date**, before you tailor, reach out or interview.

**What it shows (drawer > Job intelligence):**

| Group | From | Network |
|---|---|---|
| Company | the company's own homepage (how it describes itself) and its Wikipedia summary | on your click |
| Recent news | the news feed (RSS / Atom) the company links from its own homepage, newest 5 | on your click |
| Hiring signals | your listing store: roles seen at the company and since when, how many are still listed, new in the last 30 days, which roles, how long listings stay up, how many were reposted | none |
| The role | the job description: level, years asked for, how many required and nice-to-have skills, what it stresses, workplace, closing date | none |
| Pay context | the posting's own range, the BLS figure for the occupation and area (from the market-pay cache), pay in similar postings you have stored | none |

Each item is numbered (S1, S2 ...) and names its source (linked when it has a link) and date.

**Gather public facts.** The web part runs only when you click **Gather public facts** (then **Gather again**). Lodestar
reads the company's website (the one you set with **Set company site**, or the job's link when it is on the company's
own domain), checks its robots.txt first, follows a news-feed link only to the company's own site, and reads the
Wikipedia summary through Wikipedia's API. It never reads a job board, an ATS page or LinkedIn / Indeed / Glassdoor /
ZipRecruiter, and it uses no third-party news aggregator (their terms do not allow automated reading). Results are
cached for a week per company, shared by all its jobs. **Not read** lists what was skipped and why (robots.txt, no
site on file, no article). Check the Wikipedia item names the right company: the panel says so.

**AI summary** (needs an AI key). One AI call over the items in the panel only, asked to cite them; any line that cites
no source is dropped, so every line you see ends with its `[S#]`. Nothing private goes into that call: no salary
floor, no Preferences, no fit score. The panel says when the sources changed since the summary.

```powershell
lodestar intel 12              # the items with sources and dates (no network)
lodestar intel 12 --gather     # read the company site, its feed and Wikipedia (cached a week)
lodestar intel 12 --summary    # plus the cited AI summary
```

### Chance boosters

**What it is for.** The specific things most likely to help a job's chances right now, ranked, each with **why** and a
button into the feature that does it. Lodestar never shows a probability: each booster has an expected effect of
high, medium or low.

**The rules (no AI):**

| Booster | When |
|---|---|
| Apply while the posting is fresh | a saved job whose posting is up to 7 days old (high) or 21 (medium), not removed |
| Ask a contact for a referral | you know someone at the company (Contacts) not yet linked to this job |
| Send the recruiter / hiring manager a note | a contact is on the job; otherwise "find one" |
| Tailor your resume to this posting | a saved job with a description and no tailored resume |
| Name X, Y in your tailored resume | your profile has skills the posting requires that the tailored resume does not mention |
| Close a named gap | required skills not in your profile: a short course or certification you can finish and list honestly (across your search: a gap 2+ open jobs share) |
| Follow up | the application is due a follow-up (`followup_days`) |
| Prepare a STAR story for X | the posting stresses a competency none of your stories is tagged with |
| Fix resume check issues | the tailored resume has high or medium lint issues |
| Read up on the company | a screening or interview with no Job intelligence gathered yet |
| Aim more of your search at ... | titles or workplaces where your own response record beats your overall one, once each group has 5 applications (shown as counts, "4 of your 6 applications there got a response, against 5 of 20 overall": your record, not a prediction) |

Closed jobs and jobs your deal-breakers block get none.

**Where they show.** The drawer's **Chance boosters** group (the job's boosters, plus **More from AI**); Today's top 3
across your search; Insights > **Chance boosters across your search**. Each button only opens the feature (the
pipeline, People with Ask for referral, Communicate, Documents, the Match group, stories, search, Job intelligence,
Contacts, your profile); nothing is sent or spent until you act there.

**More from AI** (needs an AI key and the job's description). One AI call adds up to 3 boosters specific to this job,
each with the posting line, intelligence item or profile fact it rests on ("basis"). An item without a basis, or one
that states a percentage, odds or probability, is dropped. The call gets the posting, the intelligence items and your
profile without the salary floor.

```powershell
lodestar boosters          # the best across your search
lodestar boosters 12       # one job
lodestar boosters 12 --ai  # plus up to 3 AI additions with their basis
lodestar today             # Today, top 3 boosters included
```

### Saved searches (watches on a query)

**What it is for.** A search you want repeated. Each monitor cycle runs it with its saved filters across the six
sources and alerts once per new listing; new listings are then AI-judged by `auto_track` and strong fits proposed.

**Turn it on:**

- Search tab: set the query and filters, then **Save as watch**. You should see "saved: new listings for "..." will
  alert (Monitor > Watches)".
- Monitor tab > **Watches**: type the query, tick **is a search**, add keywords if you like, click **Add**.
- Terminal:

```powershell
lodestar watch search-add "python backend" --keywords remote --location remote --min-salary 120k --posted-within 14 --seniority senior
```

You should see: `will alert on new listings for 'python backend' (location=remote, min_salary=120000, posted_within=14, seniority=senior)`.

Re-adding the same query keeps its id and baseline. Saving it again with blank keywords and filters keeps the saved
ones (the app says it "updated the existing saved search"). To change filters, save again with the new values.

**Manage:**

```powershell
lodestar watch list          # every watch with keywords, filters, last good run and last error
lodestar watch rm 1          # remove watch #1
lodestar watch run           # run every watch and watched company once now
```

In the app, the Watches list shows each one with `kw=`, its filters and `last` run, a **remove** button, and a chip
when something went wrong: **last run failed** (no source answered) or **some boards unreachable** (only some failed;
the run still counted). The top bar's **Run watches** button runs them all now.

### Page watches (career pages) and robots.txt

**What it is for.** Any careers page that is not on a supported job board (Workday, Taleo, iCIMS, a company's own
site). Lodestar keeps the page's text and alerts when matching lines appear.

**Turn it on:**

- Monitor > **Watches**: paste the URL (http or https), optional keywords, leave **is a search** unticked, **Add**.
- Terminal:

```powershell
lodestar watch add https://example.com/careers --keywords "engineer,python"
```

You should see `watch added; first run takes a baseline snapshot`. The first run only records the page; later runs
alert on new lines that contain your keywords (or any new lines without keywords).

**robots.txt.** Before fetching a watched page, Lodestar reads that site's robots.txt (once per site per cycle). If
the site disallows automated fetching of the page, the watch is skipped with a single alert ("SKIPPED watch #N ...:
the site's robots.txt does not allow automated fetching of this page"). The watch stays and resumes if the site
changes its rules.

**Safety.** Page fetches refuse loopback, link-local and private network addresses and re-check every redirect. To
watch an intranet careers page on purpose, set `LODESTAR_ALLOW_PRIVATE_URLS=1` (in `.env` or as an environment
variable).

**Where the data lives.** `~/.lodestar/snapshots/` (last page text per watch), alerts in `~/.lodestar/alerts.log`
(also on the Monitor tab under **Alerts**, and `lodestar alerts`).

### Company boards (Greenhouse, Lever, Ashby)

**What it is for.** Following a company's own public job board. Lodestar reads the board's documented public JSON
feed (Greenhouse board API, Lever postings API, Ashby posting API), one request per company per cycle.

**Turn it on:**

- Monitor > **Companies**: paste the careers or posting link, or type `greenhouse:slug`, `lever:slug` or
  `ashby:slug`; optionally a display name and keywords (comma; only matching postings alert); **Add**. You should see
  a toast like "watching Acme (greenhouse:acme)".
- Terminal:

```powershell
lodestar companies add https://boards.greenhouse.io/acme
lodestar companies add greenhouse:acme --keywords "engineer,python"
lodestar companies add lever:acme --name "Acme Corp"
lodestar companies list
lodestar companies rm 1
```

Accepted links: `boards.greenhouse.io/<slug>`, `job-boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`,
`jobs.ashbyhq.com/<slug>`. You should see:
`watching #1 Acme (greenhouse:acme); the next monitor cycle records what is open, later postings alert`.

**How it behaves.** The first good read is a baseline: the roles already open are recorded with one summary alert
("WATCHING Acme: N open role(s)"), not alerted one by one. After that, each new posting alerts once and goes through
the same `auto_track` judgement as saved-search hits. Re-adding a company keeps its name and keywords unless you give
new ones; to clear keywords, remove it and add it again.

**Workday, Taleo and iCIMS have no public feed.** Giving one of their links is refused with "Workday detected.
Workday, Taleo and iCIMS have no public job feed: add the careers page as a page watch instead ...". Use a page watch
for those.

**AI helpers (Monitor):** the toolbar and **✦ AI help** > **Companies like my targets** (suggestions only: you add a company yourself).

### Stale signals and the weekly posting check

**What it is for.** Spotting reposted, vague or vanished postings so you do not waste an application.

**Possibly stale.** Search results and saved (not yet applied) Board cards get a **possibly stale** chip, with
reasons, when these signals add up to 30 or more:

| Signal | Points |
|---|---|
| posted over 30 days ago | 30 |
| the same company + title + location first seen over 21 days ago under another link (a repost) | 30 |
| a very short description (under 80 words) or one that names no concrete skill, tool or qualification | 20 |
| for a job from a Greenhouse / Lever / Ashby board: its posting is gone from the live feed | 60 |

At 60 or more, `auto_track` leaves the listing alone.

**Posting check (tool `posting_check`, on by default).** Since pass 21 this runs **daily** over every open tracked job,
feeds and posting pages: see [The listing monitor and Listing activity](#the-listing-monitor-and-listing-activity). What
follows is the original weekly feed check it grew from. Once a week, on the first monitor cycle of the week,
Lodestar re-checks your **saved** (not yet applied) jobs that came from, or link to, a Greenhouse, Lever or Ashby
board, one request per board. When a posting has disappeared it records "posting removed" on the job's timeline and
proposes moving the job to `withdrawn` in the Inbox. That proposal **always waits for you**, even if the tool is set
to auto; Lodestar never changes the status itself. A saved link that names no posting (a board root) is never counted
as removed; `/apply` and `/application` links and Greenhouse embed links are read as the posting they point to. An
unreachable or empty board is skipped until next week rather than guessed.

Switch it off in the **Tools** tab (posting_check, enabled) or:

```powershell
lodestar tools disable posting_check
```

### H-1B sponsor hints (optional)

**What it is for.** A hint, on search results and Board cards, that an employer has had H-1B approvals. Nothing is
downloaded automatically: you download the data yourself.

1. Download the export from the USCIS H-1B Employer Data Hub (CSV, or the hub's tab-separated UTF-16 file).
2. Import it:

```powershell
lodestar sponsors import C:\Users\you\Downloads\h1b_datahubexport.csv
lodestar sponsors lookup "Acme"
lodestar sponsors clear          # remove all imported sponsor data
```

You should see a line like `loaded 5 approvals for 1 employers (1 employer-years). Search results and board cards now
show 'possible H-1B sponsor' as a hint (loose name match, not a promise).` and, for the lookup,
`possible H-1B sponsor: ACME INC (5 approvals)`.

Columns read: the employer (`Employer` or `Employer (Petitioner) Name`), `Fiscal Year`, and every "... Approval"
column; denials are ignored. Approvals are summed per employer and fiscal year; importing a year again replaces that
year. The match is loose and past approvals say nothing about a given role. The data is stored in the tracker
database.

### Browser extension

**What it is for.** The Lodestar browser extension (Edge or Chrome) replaces the bookmarklets. **Capture this posting**
sends the posting on your tab to the Board, reading the page's structured job data when it has some (real company,
location, posting date and pay instead of a title split). **Fill this form** fills the **empty** fields of an
application form: contact details and links, current company and title, work history and education, and answers from
your answer bank for the questions the page shows. It never clicks, submits, presses Next, ticks a checkbox or
uploads a file: radio buttons, dropdown widgets, file uploads and date pickers are listed as "needs you" with your
stored answer.

**Not on LinkedIn.** LinkedIn's User Agreement bans browser plugins and add-ons that scrape or copy its site, so the
extension does nothing there (the server refuses LinkedIn pages too). Open the job on the company's own careers page.

**Install (load unpacked, no store):**

1. Open `edge://extensions` (or `chrome://extensions`) and turn on **Developer mode**.
2. **Load unpacked** > pick the `extension` folder of your Lodestar install (the repo folder; a moved `-Exe` build
   needs that folder copied along).
3. Pin the Lodestar icon to the toolbar.

**Pair it:** in Lodestar open **Setup** > **Browser extension** > **Pair a browser**. A pairing string such as
`8765-K7QX-M2PD` appears with a 5-minute countdown. Click the extension's icon, type the string, press **Pair**. The
string carries the port, so the code only ever goes to this Lodestar. Each code works once and dies after 5 wrong
tries; press Pair a browser again for a new one. Once the browser pairs, Setup clears the code and shows
"paired: Edge" (or Chrome) and the browser in the list.

**Use it.** Open a posting or an application form, click the Lodestar icon:

- The popup first finds Lodestar (the paired port, then 8765-8774) and shows "Lodestar 0.2.0 connected (port N)". The
  buttons stay disabled until that check proves the answer came from your Lodestar.
- **Capture this posting**: "Tracked #12: Company - Title", or "Already on your Board (#12)" for a URL you track.
  Select the posting text first if the page is busy; a selection over 200 characters is sent instead of the page.
- **Fill this form**: fills the empty fields, outlines them (blue from your profile, amber from your answers) and opens
  a small panel at the bottom right of the page listing every field it filled, each with **Undo**, plus **Undo all**
  and **Close** (Close keeps the values). Undo never touches a field you changed since. The popup lists what **needs
  you**: radio buttons and dropdown widgets with your stored answer, the resume upload (the job's tailored resume when
  the page's URL is a job you track), dates, and "I currently work here". Run Fill again on each step of a multi-step
  form (Workday): it never presses Next, Add or Submit.
- **include EEO answers** and **include desired salary** start unticked on every open and apply to that click only.
- A form embedded from Greenhouse, Ashby or another ATS on a company's own site sits in a frame the extension cannot
  reach; the popup offers **Open the form in its own tab**, where Fill works.

**When it does not work:**

| The popup says | Do this |
|---|---|
| Lodestar is not running | Start Lodestar. If it runs on a port above 8774, press Pair a browser and pair again (the string carries the port). |
| Lodestar on port N does not know this browser | The browser was revoked in Setup, or another program answers on that port. Pair again, or press **Unpair**. The popup never forgets its pairing on its own. |
| pairing code wrong or expired | Codes last 5 minutes, work once and die after 5 wrong tries. Press Pair a browser for a new one. |
| Lodestar cannot run on this page | Browser pages (`edge://`, `chrome://`), the extension stores, the PDF viewer and `file://` pages are off limits to every extension. |
| No form fields here that Lodestar can fill | The form is in a cross-origin frame (use Open the form in its own tab) or not on screen yet. |
| your profile is still the starter template | Fill in your profile (Profile tab) first; the starter's placeholders are never typed into a form. |

After the repo folder moves, Edge or Chrome shows the extension as missing: Load unpacked again from the new folder,
pair again, and revoke the old entry in Setup.

**What it sends.** Contact fields, work history and education from your profile (never the `## Preferences` section),
and answer-bank answers matched by the same question keys the pipeline uses (for example every wording of "willing to
relocate"). Anything marked private, interview stories, and text that names your salary floor never leave; an answer
the floor guard would change is withheld, not trimmed. EEO answers (save them under `EEO: gender`, `EEO: race`,
`EEO: hispanic or latino`, `EEO: veteran status`, `EEO: disability status`, typed by you and not private) go only
when you tick **include EEO answers** on that click; a desired salary (an answer to `Desired salary`, never your
floor) only when you tick **include desired salary**. Filling a form on a site you do not trust discloses what
matches, as if you had typed it.

**Security.** Pairing gives that browser its own secret, stored only in the extension's local storage and in
`~/.lodestar/extension.json` (owner-only, never in backups). Every request is signed with it and must come from the
extension's own origin, so a web page can neither call these routes nor read the secret, and the secret never works
for the rest of the app. Each signature and the server's answer to the popup's ping name the port, so another program
listening on one of the ports the popup tries cannot pass the popup's requests on to Lodestar and read the answers. The list under Pair a browser shows each paired browser with its last use; **Revoke** ends
it. If the extension's folder moves, its id changes: pair again and revoke the old entry.

**Bookmarklets** stay on until a browser is paired, then turn off (their token sits in a URL the page they run on can
read). **Setup** > **Browser extension** > **Bookmarklets** (also `lodestar tools set bookmarklets on`) sets auto, on or
off.

### Capture and Autofill bookmarklets

**What they are for.** **Capture** sends the job posting you are looking at (LinkedIn, Indeed, any careers page) to
the Board. **Autofill** types your contact details into empty fields of an application form. Neither scrapes or
automates the site: Capture copies what is on your screen, Autofill fills empty fields and stops.

**Set up:**

1. Start Lodestar (desktop window or `lodestar app` / `lodestar ui`). The bookmarklets only work while it runs.
2. Open **Setup** > **Browser bookmarklets**.
3. Drag **+ Lodestar capture** and **+ Lodestar autofill** to your browser's bookmarks bar. They already carry this
   server's address and your capture token.

**Use Capture:** open a posting, click the bookmark. You should see an alert like `Lodestar tracked #2: Globex -
Data Engineer`, and the card appears in the Saved column. Lodestar splits the page title into role and company
(LinkedIn and Indeed title shapes are recognised; "Remote" / "Hybrid" is never taken as the company) and stores the
page text as the job description. If the split guessed wrong, fix company or title on the card's Details.

**Use Autofill:** on an application form, click the bookmark. It fetches your name, email, phone, LinkedIn, GitHub,
website and location from your profile (falling back to the profile bank), fills **empty** fields (Greenhouse, Lever,
Workday, Ashby and SmartRecruiters field selectors first, then label matching) and stops with
`Lodestar filled N field(s). Review everything, then submit yourself.` It fills only those contact fields and links,
never clicks Submit, and never touches fields that already have a value.

**Security.** The bookmarklets carry a separate capture token (`~/.lodestar/capture.token`) that works only for
capture and autofill, not for the rest of the app. Without it the server answers "missing or wrong token; reload the
Lodestar page". To revoke it, delete `capture.token`, restart Lodestar and drag the bookmarklets again.

### Adding jobs by hand

**In the app:** on the **Board** tab, the top row has **Company**, **Title** and **Job description: URL or pasted
text**; click **Add job**. The drawer for the new job opens.

**Terminal:**

```powershell
lodestar jobs add "Acme" "Backend Engineer" --jd https://acme.com/careers/123
lodestar jobs add "Acme" "Backend Engineer" --jd C:\Users\you\Desktop\acme-jd.txt --notes "referred by Sam"
lodestar jobs add "Acme" "Backend Engineer" --jd "We need a Python backend engineer. Remote (US)..." --url https://acme.com/careers/123
```

`--jd` takes a URL (fetched and stored as text), a file, or the text itself. You should see
`added job #1 (JD captured)`. Lodestar fills what it can from the listing (workplace, pay when the description states
it in a form it recognises, source); check the Details form or `lodestar jobs show 1` and correct anything it missed.

Other ways a job gets onto the Board: **track** on a search result, the Capture bookmarklet, an approved `auto_track`
proposal, **Track as new job** on unmatched mail in the Inbox, or an approved "track this company" proposal raised by
recruiter mail.

### Statuses

Every job has exactly one status. The Board has one column per status, in this order:

| Status | Meaning |
|---|---|
| `saved` | tracked, not applied yet (where the pipeline prepares the application) |
| `applied` | you applied; setting it stamps the applied date |
| `screening` | first contact, recruiter screen |
| `interview` | interviews booked or under way |
| `offer` | you have an offer |
| `accepted` | you accepted; Lodestar proposes withdrawing your other open applications (Inbox) |
| `rejected` | closed by the employer |
| `withdrawn` | closed by you (or a posting removed / ghosted close-out you approved) |

Change it from the Board (drag), the drawer (status list + **move**), the table's bulk bar, or:

```powershell
lodestar jobs status 1 applied --note "applied on the company site"
```

You should see `#1 -> applied`. Mail classification (tool `email_classify`) moves jobs forward only (to screening,
interview, offer or rejected) and never backward; a move triggered by unverified mail waits in the Inbox.

### The Board

**What it is for.** All your tracked jobs, by status, with everything you need to decide what to do next.

**Columns and cards.** One column per status with a count. Each card shows company, title, excitement stars, pay,
match %, location / workplace, a deadline chip (red three days out), the pipeline chip (next step, `? N` questions
waiting, stale, error), possibly stale, possible H-1B sponsor and warm-path chips, the job number and last activity.
A card with an orange edge has been quiet for `followup_days` (default 7).

**Drag and drop.** Drag a card to another column to change its status. Moving a card backward asks first; dropping
on `accepted` asks first and then proposes withdrawing your other open applications in the Inbox. Without a mouse:
focus a card and press Enter (or Space) to open its drawer, pick the status in the drawer's list and press **move**
(arrowing through the list changes nothing on its own). Esc closes the drawer.

**Filters and sort.** The filter row narrows by text (**search company, title, location, tags**), status, workplace
(remote / hybrid / onsite), **min salary**, **tag** and **has deadline**, and sorts by last activity, stalest first,
match, salary, excitement or deadline. The browser remembers your view, sort and filters; if they hide every job you
see "No jobs match these filters." with **Clear filters**.

**Table view.** **Table view** switches to a sortable table (click a column header; again to flip) with columns #,
Company, Title, Status, Next step, Salary, Match, Excitement, Deadline, Location, Last activity, and a checkbox per row.
**Board view** switches back.

**Bulk actions.** Tick rows in the table and a bar appears: **Set status** (asks to confirm), **Add tag**,
**Run next step** and **Run to** a step for up to 25 jobs (the confirm names the AI calls; jobs with nothing ready
are counted as such, not as errors), and **Delete selected** (asks; cannot be undone).

Above the columns: the **Today** panel, upcoming interviews, resume-variant and funnel lines.

**Terminal equivalents:**

```powershell
lodestar jobs list
lodestar jobs list --status saved --sort deadline
lodestar jobs list --remote remote --min-salary 120000 --tag python
lodestar jobs set 1 excitement=4 deadline=2026-11-20 tags=python,remote next_action="ask Sam" next_action_at=2026-11-11
lodestar jobs show 1            # every field plus the timeline
lodestar jobs note 1 "Recruiter said the team is hiring two"
lodestar jobs jd 1 https://acme.com/careers/123     # replace the description
lodestar jobs rm 1              # delete the job and its timeline
```

`jobs list` sorts by `match`, `salary`, `excitement`, `deadline` or `updated` (default, most recent first).
`--min-salary` compares the top of the stated range; jobs with no pay on file are kept and marked `pay unknown`.
`jobs set` fields: `location`, `remote` (onsite / hybrid / remote), `salary_min`, `salary_max` (`120k` works),
`currency` (3 letters), `source`, `posted_at`, `deadline`, `next_action_at` (YYYY-MM-DD), `excitement` (1-5), `tags`
(comma list), `match_score` (0-100), `next_action`. An empty value clears a field; a bad value changes nothing. You
should see the fields echoed back, for example
`#1 excitement=4, deadline=2026-11-20, tags=python,remote, next_action=ask Sam, next_action_at=2026-11-11`.

**AI helpers (Board):** the Today row's AI toolbar (Recommend: a priority plan) and its **✦ AI help** menu: **What to do next**, **Plan my day**. See [AI help menus](#ai-help-menus-the-assist-button-inventory).

### The job drawer

Click a card (or a company name in the table) to open the drawer. From top to bottom:

- **Header**: company, title, job number, a **posting** link, the status list with **move**, and close. Under it, the
  job's contact (replies and follow-ups need one).
- **Pipeline**: the step strip, **Run next step**, **Run to**, questions for this job, Form questions and the run log
  (see "The step-by-step pipeline").
- **Details**: location, workplace, salary min / max, currency, excitement, match %, deadline, posted, source, tags,
  next action and its due date; **Save details**. An empty field clears it.
- **People**: contacts you know at this company (warm paths), linking them to the job with a role, and asking for a
  referral (the email always waits in the Inbox).
- **Interview readiness** (screening, interview, offer): the 0-100 preparation score, the chance estimate band (not a probability), the parts with their reasons, Raise it, Question sources and Questions (above, Interview prep and mock interviews).
- **Interview rounds**: rounds with time, interviewers, notes and questions asked.
- **Match**: **Compute JD coverage** (no AI), **Check resume**, **Audit resume.docx**.
- **Documents**: **Gap check (coverage + AI verdict)**, **Tailor resume (+docx)**, **Tailor by bullet**, **Build in
  Studio**, **Cover letter (+docx)**, **Cover options**, **Interview prep**, **Company research**, **Checklist**, a
  council toggle, **Export PDF**.
- **Communicate**: **Draft reply**, **Draft outreach**, **Follow-up email**, **Thank-you note**, **Withdrawal email**,
  a "plain template, no AI" box, and **Options** for up to 3 drafts. Every email you draft here is proposed through
  the Inbox for sending.
- **Mail**: mail filed under this job, both directions, each marked **trusted** or **unverified**, with **Reply with
  options** and **Unlink** for links you made.
- **Schedule and decide**: **Calendar .ics** for an interview time, **Evaluate offer**.
- **Admin**: add a note, **set contact** (name and email; also files the person under Contacts as recruiter),
  **set JD**, **export packet (zip)**, **View documents**, **delete job**.
- **Tabs**: timeline, description and each generated document, with **View / format**, **Edit document**, **Adjust**
  and **Review**.

The checklist is also a command: `lodestar jobs checklist 1` prints each stage as `[x]` done, `[ ]` with the next
command to run, or `[-]` not relevant yet.

**AI helpers (job drawer):** the **✦ AI help** menu under the contact line: **Summarise the posting**, **Red flags**, **Questions to ask them**, **Likely interview topics**, **Map my stories to this job** (one AI call each; nothing changes), plus the Details and Documents toolbars.

### Today and the agenda

**What it is for.** What needs you today, in one place.

**In the app:** the **Today** panel on top of the Board lists overdue and due next actions, deadlines within 3 days,
interviews within 48 hours, follow-ups due, contacts whose next touch has come ("get in touch"), the Inbox count and
the number of questions for you. Each entry opens its job or contact. Below it, **Suggested emails** lists mail worth
sending today, each with **Draft options** and **Dismiss for now** ([Suggested emails](#suggested-emails)).

**Terminal:**

```powershell
lodestar today
lodestar suggest
lodestar suggest --dismiss 1 followup     # hide one suggestion for 3 days
```

`lodestar today` prints the same agenda as headed lines (Next actions due, Deadlines within 3 days, Interviews within
48 h, Follow-ups due, Contacts to get in touch with, Suggested emails, Inbox: N waiting).

**Desktop notifications** (off by default) can show this agenda once a day and remind you of an interview within 2
hours: see [Desktop notifications](#desktop-notifications).

### Follow-up cadence

**What it is for.** Not letting an application go quiet without a nudge, and not nudging forever.

**How it works** (tool `followup`, enabled, not auto, by default):

1. An application with no real activity for `followup_days` (default 7) is "quiet". Its card gets the orange edge and
   it shows under Follow-ups due on Today.
2. Each monitor cycle nudges about it. If the job has a contact email, a follow-up email is drafted (by AI, or a plain
   template without a provider) and proposed in the Inbox. Only one follow-up per job waits at a time; sending one
   closes any other.
3. After three follow-ups, Lodestar stops nudging and proposes closing the job as `withdrawn` ("no response after
   three follow-ups (ghosted)"). That is a proposal: it waits in the Inbox unless the tool is on auto.

Only real activity restarts the clock. Inbox proposals, rejections, failed sends, unsent drafts and unverified mail
do not. While an interview is booked, the pipeline's Follow-up step says no follow-up is needed.

**Settings and commands:**

```powershell
lodestar tools set followup_days 10       # 1-90
lodestar jobs followups                   # applications quiet for followup_days or more
lodestar jobs followups --days 14
lodestar followup 1                       # draft one now (waits in the Inbox when a contact is known)
lodestar followup 1 --template            # plain template, no AI
lodestar followup 1 --options             # up to 3 options from one AI call
lodestar followup 1 --pick 2              # use option 2; proposed for review in the Inbox
lodestar jobs contact 1 jane@acme.com --name "Jane Doe"   # the address follow-ups go to
```

### The step-by-step pipeline

**What it is for.** Each tracked job moves through 13 steps, from fit check to close. Lodestar shows each step's state
in words, runs the next one when you ask (or, with Autopilot, in the background within budgets), feeds each step the
earlier steps' results, and asks you once for facts it cannot know.

**The steps.** The app shows the label; commands use the name.

| Name (CLI) | Label (app) | What it does | Tool | Relevant at |
|---|---|---|---|---|
| `score` | Fit check | the deterministic fit score (fit.py) with its chips; verdict skip under auto_track_min_score or when blocked; one AI judgement only when `fit_check` is on auto; asks for the JD when there is none | `fit_check` | saved |
| `research` | Research | company research pack from public pages | `research` | saved, interview |
| `tailor` | Tailor resume | the resume studio builds this job's resume from your facts and uses it | `tailor` | saved |
| `letter` | Cover letter | from the tailored resume, research and fit check | `cover_letter` | saved |
| `answers` | Form answers | the job's form questions: closed ones from your answers, open-ended ones drafted | `form_answers` | saved |
| `apply` | Apply | you apply on the site and click **Mark applied** | none | saved |
| `confirm` | Confirmation | the application-received mail (trusted mail only) | observed | applied, screening |
| `followup` | Follow-up | the follow-up cadence above | observed | applied, screening, interview |
| `schedule` | Schedule | interview rounds from mail and the Interview rounds group | observed | screening, interview |
| `prep` | Interview prep | prep pack once an interview is booked | `interview_prep` | interview |
| `thanks` | Thank-you | drafted after a round; the email always waits in the Inbox | `thank_you` | interview |
| `offer` | Offer | offer evaluation | none | offer |
| `close` | Close | accepted, rejected or withdrawn | none | any live status |

**States.** done, ready, waiting on you (a question, an Inbox item, an approval) or waiting on the employer (a reply,
a confirmation), stale, blocked (no AI provider), error (with Retry), running, todo (an earlier step first), later (a
later status), skipped (by you, or not applicable). Work you did by hand (a drawer Tailor, an edited cover_letter.md,
a sent thank-you) is adopted as done.

**Stale.** When something a done step was built from changes (the JD, your profile, the tailored resume, the research
pack, your stories, a new round) the step reads **stale**. Tailor resume reads stale only when a profile section that
resume used changed. A stale step is never redone on its own: you re-run it.

**In the app (job drawer > Pipeline):**

1. The strip shows every step with an icon and its state in words ("N of M steps done" in the heading).
2. **Run next step (Fit check)** runs the next ready step. When nothing is ready the reason is shown beside it
   ("waiting on you: ...", "waiting on the employer: ..." or "nothing is ready to run").
3. **Run to** [a step] + **Go** runs the ready steps in order up to that step and stops at anything waiting, blocked,
   failed or manual (Apply, Offer, Close) and at a stale step, unless you tick **include stale steps (re-run them)**.
4. Click a step for its line: why, revision, who ran it, what it was built from, its document, and **Run**,
   **Re-run**, **Retry**, **Skip** or **Unskip**. On Apply: **Open posting**, **Show folder**, **form_answers.md** and
   **Mark applied**.
5. **Form questions (N)**: paste the application form's questions, one per line, and click **Add form questions**;
   then run Form answers.
6. **Run log (N)**: every run for this job, with who ran it, outcome and AI calls.
7. When the fit check says skip, a **fit: skip** pill appears with **Continue anyway** (your click is the override;
   Autopilot still leaves the job alone).

Board cards and the table's Next step column show the same chip; the bulk bar runs next step / run to for up to 25
jobs.

**Terminal:**

```powershell
lodestar pipeline status                # one line per live job: next step, questions, stale and failed steps
lodestar pipeline status 1              # the step table for job #1
lodestar pipeline run 1                 # run the next ready step
lodestar pipeline run 1 --to letter     # ready steps up to Cover letter
lodestar pipeline run 1 --to letter --rerun     # also re-run stale steps on the way
lodestar pipeline run 1 --stage research --rerun   # one step again (the old document moves to history/)
lodestar pipeline skip 1 letter         # no cover letter for this job
lodestar pipeline skip 1 letter --undo
lodestar pipeline add-questions 1 questions.txt     # one question per line; or - to read from the pipe
Get-Content questions.txt | lodestar pipeline add-questions 1 -
lodestar pipeline log                   # newest first; add a job id or --limit N
lodestar -p groq pipeline run 1         # pick the AI provider for this run
```

`lodestar pipeline status 1` prints one row per step, for example:

```
score     ready               rev 0  -                            ready to run
research  todo                rev 0  -                            after fit check
...
confirm   later               rev 0  -                            relevant again at applied
```

A wrong step name lists the valid ones: `unknown step 'x'. Steps: score, research, tailor, letter, answers, apply,
confirm, followup, schedule, prep, thanks, offer, close`. Your own runs need no tool switch and no Autopilot.

**Questions for you.** A step that lacks a fact asks once instead of guessing. Questions show at the top of the Inbox
(**Questions for you (N)**), in the drawer, and with `lodestar pipeline questions`. Each card has an answer field,
**Use this: ...** buttons for near matches from your answer bank, a choice of **every job** or **only this job**, a
**private (this job only, never in the answer bank)** box, **Save answer** and **I'll fill it in myself** (the step
goes on without it). One answer serves every job and step that asks the same question.

```powershell
lodestar pipeline questions             # waiting ones (--all: answered and dismissed too; --job 1 for one job)
lodestar pipeline answer 3 "6"          # saved to the answer bank for every job
lodestar pipeline answer 1 "Yes" --job-only
lodestar pipeline answer 4 "..." --private      # this job only, never saved to the bank
lodestar pipeline dismiss 2             # I'll fill it in myself
```

You should see, for example, `Q1    [open/eligibility] Are you legally authorized to work in the US?` in the list and
`saved to the answer bank #1; resumed: ...` after answering.

**Rules you can rely on:** eligibility, work-authorization and EEO questions are never drafted by AI (however the form
words them) and are filled only from answers you wrote yourself; they never reach an AI prompt. Private answers never
go into employer text, and a salary answer equal to your floor is refused.

**Autopilot (off by default).** With Autopilot on, each monitor cycle moves jobs along their pipelines:

- A step whose tool is **auto** runs on its own.
- A step whose tool is enabled but not auto is covered by **one** Inbox approval per job for its next batch of steps
  (kind `run_to`). The card estimates the AI calls and lists the saved answers it will fill in on the form.
- A disabled step is left for you. Jobs whose fit check says skip are left alone. A failed step is retried once on a
  later cycle.
- Never unattended: applying, offers, closing, sends, status changes and job adds (those go only through the Inbox),
  re-running a stale step, and answering eligibility or EEO questions.

Budgets (Setup > **Autopilot**, or preferences):

| Preference | Default | Range | Meaning |
|---|---|---|---|
| `autopilot` | false | true / false | the switch |
| `autopilot_jobs_per_cycle` | 3 | 0-50 | jobs advanced per cycle |
| `autopilot_ai_per_cycle` | 6 | 0-500 | AI calls per cycle |
| `autopilot_ai_per_day` | 30 | 0-500 | AI calls in a rolling 24 hours (approved batches count too) |

Turn it on:

1. Setup > **Autopilot**: tick **Autopilot on**; adjust **AI calls per cycle**, **per day** and **jobs per cycle**.
   The panel also lists each step's enabled / auto switch and has **Show the run log**.
2. Or the top bar's **Autopilot: off** pill, which opens the same panel.
3. Or the terminal:

```powershell
lodestar pipeline autopilot on
lodestar pipeline autopilot status
lodestar tools set autopilot_ai_per_day 20
lodestar tools auto fit_check            # let the fit check run without asking
```

`lodestar pipeline autopilot status` prints the switch, budgets, AI calls in the last 24 hours and each step's mode,
for example `Autopilot: off; budgets 6 AI calls per cycle, 30 per day, 3 jobs per cycle; 0 AI calls in the last 24 h`
followed by lines like `score     tool fit_check       asks in the Inbox`. Autopilot only runs inside the monitor
loop (desktop window, `lodestar app`, `lodestar run` or the scheduled task). A budget that runs out shows on the loop
line as "pipeline: per-cycle AI budget reached" or "pipeline: daily AI budget reached".

Pipeline bookkeeping goes to its own run log, never to the job timeline, so it does not restart the follow-up clock.

**Where the data lives.** Step state, questions and the run log in `~/.lodestar/lodestar.db`; documents in
`~/.lodestar/applications/<id>-.../` (for example `form_answers.md`; a re-run moves the old one to `history/`).

### The Inbox and approvals

**What it is for.** The one place where Lodestar's own initiatives wait for you. Nothing is sent, moved or added until
you approve it, unless you set that tool to auto (and some things wait even then).

**The rule:**

| enabled | auto | behaviour |
|---|---|---|
| off | any | the tool never runs |
| on | off | the tool proposes an action into the Inbox and waits |
| on | on | the tool acts at once and logs an event on the job |

Commands you type and buttons you click are confirmed by doing them; the Inbox is only for what Lodestar decided on
its own (monitor loop, email check, Autopilot, auto-track).

**What waits for you, and the tools behind it** (defaults as installed; `lodestar tools list` shows yours):

| Tool | What it does | enabled | auto |
|---|---|---|---|
| `email_classify` | classify inbox mail and move matching jobs forward | on | on |
| `email_reply` | draft replies to confirmations, assessments, interview invites and offers | on | off |
| `interview_scheduling` | accept a proposed interview slot or propose times from your availability | on | off |
| `followup` | draft follow-ups for quiet applications | on | off |
| `auto_track` | judge new listings from watches and searches; add strong fits | on | off |
| `answers` | save newly generated form answers to the answer bank | on | off |
| `calendar` | write .ics files for interviews found in mail | on | on |
| `obsidian_sync` | mirror the tracker into Obsidian after each cycle | off | on |
| `digest` | email the weekly digest | off | on |
| `backup` | nightly zip of your data folder (keeps 7) | on | on |
| `posting_check` | weekly re-check of saved board jobs; proposes withdrawing removed postings (always waits) | on | off |
| `fit_check` | pipeline: Fit check | on | off |
| `research` | pipeline: Research | on | off |
| `tailor` | pipeline: Tailor resume | on | off |
| `cover_letter` | pipeline: Cover letter | on | off |
| `form_answers` | pipeline: Form answers (never eligibility or EEO) | on | off |
| `interview_prep` | pipeline: Interview prep | on | off |
| `thank_you` | pipeline: Thank-you draft (the email always waits in the Inbox) | on | on |

For the pipeline tools, enabled means Autopilot may use that step and auto means it runs without asking.

**Always waits, even on auto:** removed-posting withdrawals (`posting_check`), any email with attachments, every email
you ask for from the drawer (replies, outreach, withdrawals, referral asks, counter-offers) or pick from options,
thank-you emails drafted by the pipeline, and anything triggered by mail that is not both authenticated and strongly
tied to the job. A reply to unverified mail is marked **unverified sender** and, when sent, never moves the job.

**Switches.** In the app: the **Tools** tab (in the left sidebar, beside Setup) has a table with an **enabled** and an
**auto** checkbox per tool, and **Preferences** below it. Terminal:

```powershell
lodestar tools list
lodestar tools disable auto_track        # never judge listings
lodestar tools enable auto_track
lodestar tools auto auto_track           # add strong fits without asking
lodestar tools manual calendar           # ask before writing .ics files
lodestar tools set auto_track_min_score 80
```

Preferences relevant here: `auto_track_min_score` (0-100), `followup_days` (1-90), `availability` (used when
proposing interview times), `excluded_companies`, `excluded_title_words`, `desktop_notifications`, and the four
`autopilot*` settings. Out-of-range numbers are refused with a message such as
`auto_track_min_score must be between 0 and 100`.

**Working the Inbox (app).** The **Inbox** tab (its badge counts approvals and questions) shows, top to bottom:
**Emailed sign-in codes**, **Questions for you**, the pending items, **Unmatched mail** and **Recently decided**.
Each pending item shows its number, tool, kind and summary:

- An email (`send_email`): editable To, subject and body, attachments (only the job's resume, cover letter and files
  in its `attach/` folder; **Show attach folder**), an interview-slot field when the reply accepts a time,
  **Options** and rewrite chips (shorter, warmer, more formal, more direct, custom) when an AI key is linked, then
  **Approve and send** (or **Retry send** after a failure) and **Reject**.
- Anything else (status change, new job, saved answer, note, pipeline batch): the payload as editable JSON,
  **Approve** and **Reject**. A pipeline batch (`run_to`) also lists **Saved answers this fills in on the form**.

An edit that would be refused (an email or answer that names your salary floor, a slot that clashes with another
interview) is refused before the item is claimed: it stays in the Inbox with the reason and nothing is sent. Approving
is atomic, so a double click cannot send twice. Sending mail needs a connected mailbox (see [Email: pick a way to connect](#email-pick-a-way-to-connect));
without one, the approval fails with a clear error and the draft stays so you can copy it.

**Terminal:**

```powershell
lodestar inbox                  # what is waiting ("inbox empty" when nothing is)
lodestar inbox -v               # with the drafted email or payload
lodestar inbox --all            # include decided items
lodestar approve 12             # execute as drafted
lodestar approve 12 --subject "Re: Interview" --body edited.txt --to jane@acme.com
lodestar reject 12 --reason "already replied"
lodestar approve 12 13 14       # several at once
```

**Where the data lives.** Inbox items, their results and the event they leave on each job are in
`~/.lodestar/lodestar.db`; tool switches and preferences in `~/.lodestar/settings.json`.

**AI helpers (Inbox):** the toolbar on the tab and on each email, and each email's **Options** and rewrite buttons. No extra AI help menu: the rewrites cover it.

## Mail, people, interviews and outcomes

This part covers everything that happens after you start talking to employers: reading your mailbox, filing mail
under jobs, drafting replies, keeping track of people, interview rounds, practice, offers, your weekly numbers, and the
weekly digest. Most of it needs an AI provider; where a feature works without one, it says what you get instead.
What runs in the background is in [The monitor loop: what each cycle does](#the-monitor-loop-what-each-cycle-does).

### The email monitor (Check email)

**What it is for.** Lodestar reads your mailbox for hiring mail (interview invites, rejections, offers, recruiter
outreach, application confirmations, assessments), sorts each message with AI, files it under the matching job,
updates the tracker and drafts replies for you to approve.

**How to turn it on.**

1. Connect a mailbox: Setup > **Connect email** in the app, or `lodestar email connect` / `lodestar email signin
   google|microsoft` in the terminal. The full walkthrough for every provider is in [CONNECT.md](CONNECT.md) and in
   [Email: pick a way to connect](#email-pick-a-way-to-connect).
2. Link at least one AI key (classification needs one; see "Without an AI provider" below).
3. The tool `email_classify` is on and on auto by default. Check with:

   ```powershell
   lodestar tools list
   ```

   You should see `email_classify   True   True`. If it says `False` in the enabled column, run
   `lodestar tools enable email_classify`.

**Run it from the app.**

- The **Check email** button in the top bar scans the last 3 days. A message at the bottom says how many relevant
  emails it found.
- Monitor > **Email dry-run (7 days)** shows what it would classify over 7 days and changes nothing.
- The monitor loop (inside the desktop window, `lodestar app` or `lodestar run`) checks mail on every cycle with a
  2-day lookback.

**Run it from the terminal.**

```powershell
lodestar email check --days 7 --dry   # report only: what it would classify; changes nothing
lodestar email check                  # the last 3 days (default): classify, file, update, propose replies
lodestar alerts                       # the lines it wrote to alerts.log
```

When it works, each relevant message prints a line such as
`EMAIL INTERVIEW: Acme - phone screen invite | ACTION: reply with times`. The same lines go to `alerts.log` and the
Monitor tab's Alerts panel.

**What one scan does, step by step.**

1. Opens INBOX **read-only** and looks at up to the newest 100 messages in the lookback window. Nothing is marked
   read, moved or deleted in your mailbox. Each message is handled once; a message that failed (provider outage, odd
   format) is retried on the next scan.
2. Masks sign-in codes. Any code-shaped token is replaced by `******` before the message is classified, filed or
   shown anywhere (see "Emailed sign-in codes" below).
3. Picks the relevant mail. A message is classified only when it contains a hiring word (interview, application,
   offer, recruiter, assessment, "next steps", "unfortunately" and similar), comes from a company you track, answers
   mail Lodestar sent, or comes from a live job's stored contact address. Everything else is skipped, which keeps AI
   cost low.
4. Classifies it as one of: `interview`, `rejection`, `offer`, `recruiter_outreach`, `application_received`,
   `assessment` or `other`. The message text goes to the AI fenced as untrusted data, so text inside a mail cannot
   change the instructions. `other` (newsletters, job-board digests, marketing) is dropped.
5. Matches it to a job and decides whether it is trusted (next section).
6. Acts on it:
   - **Status.** interview moves the job to `interview`, rejection to `rejected`, offer to `offer`, assessment to
     `screening`, application received to `applied`. A job only moves forward, never back. With trusted mail and
     `email_classify` on auto this happens at once; otherwise it waits in the Inbox.
   - **Contact.** The sender of the first trusted, human (not no-reply) mail about a job becomes that job's contact,
     if it has none yet.
   - **Interview time.** An interview mail with a stated date **and time** from a trusted sender records an interview
     round and, with the `calendar` tool on (default), writes an `.ics` calendar file. A date without a time (often a
     reply-by date) or an unverified sender only adds a note to the job's timeline. A calendar invite attached to the
     mail supplies the time when the text gives none; the same trust rule applies.
   - **New company.** Recruiter outreach, an interview or an offer from a company you do not track yet becomes an
     Inbox proposal to track it. It is never added on its own.
   - **Reply draft.** For confirmations (only if you set `reply_to_confirmations`), assessments, interview invites,
     offers and recruiter outreach, a reply is drafted and proposed (see "Replies Lodestar drafts on its own" below).
   - **Attachments.** Files on mail filed under a job are saved to `applications\<job>\mail\` (kept types only: pdf,
     docx, odt, txt, png, jpg, gif, ics, csv, xlsx; size-capped; marked as downloaded from the internet; never
     opened). Mail no job claims lists the file names only.
   - **Record.** The message is stored in the mail table and shown in the job drawer's **Mail** group.

**Without an AI provider.** Mail tied to a job by your thread or its contact address is still filed under that job as
`unclassified` (no status move, no round, no reply). Other mail waits, unread by Lodestar, until a provider works.

**Where its data lives.** `~/.lodestar/lodestar.db` (tables `mail`, `events`, `pending`, `seen`),
`~/.lodestar/alerts.log`, and `~/.lodestar/applications/<id>-<company>-<title>/mail/` for saved attachments.

**Emailed sign-in codes.** The scan also picks up the one-time codes job sites email you; they show in Inbox >
**Emailed sign-in codes**, in memory only. See [Emailed sign-in codes](#emailed-sign-in-codes).

### How Lodestar decides whether mail is trusted

Anyone can write "Acme Recruiting" in a From line, and anyone can register `acme-careers.xyz`. So Lodestar only lets
mail act on its own when **all three** of these hold:

1. **Authenticated.** Your mail provider's own `Authentication-Results` header shows a passing DKIM or DMARC result
   for the sender's domain.
2. **Strongly tied to the job.** The sender matches something Lodestar already holds for that job:
   - the job's stored contact address (or, for a company address, the same domain);
   - a reply in a thread Lodestar started, from the address it wrote to (or the same company domain), where Lodestar's
     own mail was itself to a trusted person, and the job is not rejected or withdrawn;
   - the registrable domain of the job's posting URL when that URL is on the company's own site
     (`careers.acme.com/jobs/1` vouches for `acme.com`). Job boards (greenhouse.io, linkedin.com) vouch for nobody.
3. **Consistent with the stored contact.** If the job already has a contact, the sender is that contact (free-mail
   addresses such as gmail.com must match exactly) or shares its company domain.

Everything else is a **weak tie** or no tie: a domain that merely spells the company name (`acme.xyz`), a thread
reply from someone else, or a company name the AI read in the text. Such mail is filed under the job and shown as
**unverified**. It never becomes the job's contact, never records an interview round, and any status move or reply it
causes waits in the Inbox, even when the tool is on auto. Mail about a company you do not track is never trusted.

Your own clicks never create trust: linking a mail to a job by hand, Track as new job, or a reply you send to such
mail does not make that sender trusted, not even a thread later. A contact in your Contacts list never makes mail
trusted either.

### Mail linked to jobs, and Unmatched mail

**What it is for.** Every relevant scanned message and every message Lodestar sends is kept, de-duplicated by
Message-ID, so each job shows its conversation in both directions.

**In the app.**

- Job drawer > **Mail**: the job's mail, newest first, each marked trusted or unverified and how it was linked
  (auto, thread, user). Incoming mail has **Reply with options**. Mail you linked by hand has **Unlink**.
- Inbox > **Unmatched mail**: relevant mail no tracked job claims. Each row has:
  - a job picker and **Link to job**: files it under that job. It never sets the job's contact and never makes the
    sender trusted.
  - **Track as new job**: adds a job from it at once (your click), without a contact. The sender becomes the contact
    only when the mail was trusted and its domain names the company you entered.
  - **Dismiss**: removes it from the list; later scans do not bring it back.

  If the same mail also raised a "track this company" proposal in the Inbox, linking or tracking the mail closes that
  proposal, and approving the proposal files the mail under the new job, so you never get two jobs.

**In the terminal.**

```powershell
lodestar mail list                 # everything recorded, newest first
lodestar mail list --job 3         # one job's mail, both directions
lodestar mail list --unmatched     # incoming mail no job claims
lodestar mail link 12 3            # file mail #12 under job #3
lodestar mail unlink 12            # undo a link you made (automatic and thread links stay)
lodestar mail dismiss 12           # drop it from the unmatched list
```

Track as new job is in the app only. With nothing recorded yet you see
`no mail recorded yet (lodestar email check records relevant mail)`.

**Where it lives.** The `mail` table in `lodestar.db`. Deleting a job deletes its mail records. `lodestar export
json` / `csv` include the mail table.

### Replies and drafts, with AI options and rewrites

There are three ways an email gets drafted. All of them end in the Inbox; none sends anything by itself.

**1. Replies Lodestar drafts on its own (during a scan).**

| Mail category | Tool | What the draft does |
|---|---|---|
| application received | `email_reply` | thanks them briefly; only when `reply_to_confirmations` is true (off by default) |
| assessment | `email_reply` | confirms you will do it, asks for the deadline if missing |
| offer | `email_reply` | thanks them, asks for the written offer and a timeline; never accepts, declines, negotiates or names a number |
| recruiter outreach | `email_reply` | shows interest, asks for details, pay range and process |
| interview | `interview_scheduling` | accepts the first proposed slot inside your `availability`, or proposes three slots |

Both tools are on and manual by default, so drafts wait in the Inbox. Interview replies never accept or propose a
time within 90 minutes of another booked interview, and never mention other employers. Approving an interview reply
that accepts a slot writes the `.ics`; a slot that clashes with another interview is refused and the item stays in
the Inbox. No reply is drafted for a rejected or withdrawn job.

Set your availability and signature once:

```powershell
lodestar tools set availability "Tue-Thu 13:00-17:00 ET"
lodestar tools set signature "Sean"
lodestar tools set reply_to_confirmations true    # optional
```

**2. Drafts you ask for.**

| Draft | App (job drawer) | Terminal |
|---|---|---|
| Reply with your own intent | Communicate > type the intent > **Draft reply** | `lodestar email reply 3 --intent "accept interview, propose Tue/Wed afternoons"` |
| Outreach note or email | Communicate > **Draft outreach** (LinkedIn note or Email) | `lodestar outreach 3 --person "Jane Doe, Eng Manager" --channel email` |
| Follow-up | Communicate > **Follow-up email** | `lodestar followup 3` |
| Thank-you | Communicate > **Thank-you note** (interviewer, something specific) | `lodestar thanks 3 --interviewer "Jane" --notes "the caching discussion"` |
| Withdrawal | Communicate > **Withdrawal email** | `lodestar withdraw 3` (sending it moves the job to `withdrawn`) |
| Offer evaluation (not an email) | Schedule and decide > **Evaluate offer** | `lodestar offer 3 --salary 150k --deadline 2026-12-01` (writes `offer.md`) |

An email goes to the job's contact. Set it in the drawer's Admin > **set contact**, or:

```powershell
lodestar jobs contact 3 jane@acme.com --name "Jane Doe"
```

Without a contact address you get the text to copy (`draft_only`) instead of an Inbox item. Without an AI provider,
follow-up, thank-you and withdrawal use a plain template (tick **plain template, no AI** in the drawer, or add
`--template`). Only one follow-up per job waits at a time.

**3. AI options and rewrites.** Instead of one draft, ask for up to three from one AI call, with exactly one marked
recommended and a one-line reason.

In the app:

- Job drawer > Communicate > **options for** (follow-up, thank-you, withdrawal, outreach email, offer check-in) >
  **Options**.
- Job drawer > Documents > **Cover options**; People > **options** (referral ask); Mail > **Reply with options**.
- Answers > **Options** (form answers); Insights > Offers > **Options** (counter-offer).
- Each card has **Use this** and rewrite chips (shorter, warmer, more formal, more direct, custom). **Use this**
  proposes the email to the Inbox, always for review, even when the tool is on auto.
- On any pending email in the Inbox, **Options** and the same chips replace only the subject and body. The
  recipient, the job and the reply-to stay as proposed and the item stays pending.

In the terminal:

```powershell
lodestar followup 3 --options              # up to 3 numbered drafts; nothing is proposed yet
lodestar followup 3 --pick 2               # propose option 2 (no second AI call) for review in the Inbox
lodestar draft options thanks 3 --interviewer "Jane"            # options for any kind
lodestar draft options thanks 3 --interviewer "Jane" --pick 1   # repeat the same arguments with --pick
lodestar draft options reply --mail 12     # reply to mail #12 (ids: lodestar mail list)
lodestar draft options pending --pending 7 # alternatives for Inbox item #7
lodestar draft rewrite --pending 7 --how shorter   # or warmer, formal, direct, or "your own words"
```

Kinds for `draft options`: `reply`, `followup`, `thanks`, `withdraw`, `checkin`, `outreach`, `referral`
(`--contact ID`), `counter`, `cover` (the pick is written to `cover_letter.md`), `answer` (`--question`), `pending`.
`--pick N` only works with the same arguments as the `--options` run (the options are kept in
`~/.lodestar/draft_options.json`); otherwise you see `no kept options for this draft: run the same command with
--options first`. Without an AI provider, follow-up, thank-you, withdrawal, offer check-in, referral and counter-offer
give the plain template as the single option; other kinds and every rewrite say they need a provider
(`rewriting needs an AI provider: ...`).

**Approving, editing, rejecting.**

```powershell
lodestar inbox -v                                   # what waits, with the drafted email
lodestar approve 7                                  # send as drafted
lodestar approve 7 --subject "Re: Interview" --body edited.txt   # edit first (body from a file)
lodestar reject 7 --reason "already replied"
```

In the app, Inbox cards have editable To, Subject and Body fields, **Approve and send** and **Reject**. Sending needs a
connected mailbox; without one, the approval fails with a clear error and the draft stays so you can copy it.

**Safety.** Prompts carry your profile without Preferences; mail you received goes in as fenced, untrusted data. Every
option, rewrite, pick and edit passes the salary-floor guard. A reply to unverified mail is marked **unverified
sender** on its card, and approving it sends the mail only: it never moves the job. Replying to a mail never makes its
sender trusted.

### Suggested emails

**What it is for.** A short list of mail worth sending today, worked out from the tracker alone, with no AI call:

- a thank-you within 24 hours after an interview round;
- a follow-up when an application has been quiet for `followup_days` (default 7);
- a reply to unanswered recruiter, interview, offer or assessment mail filed under a job (last 14 days);
- a check-in when an offer deadline is within 3 days;
- a referral ask when you know someone at the company of a saved or applied job.

Nothing is suggested for rejected or withdrawn jobs, or for a job that already has an email waiting in the Inbox.

**In the app.** The **Today** panel at the top of the Board lists them under **Suggested emails**, each with a due
chip, **Draft options** (opens the options described above) and **Dismiss for now** (hidden for 3 days).

**In the terminal.**

```powershell
lodestar suggest                       # numbered list, each with the command to draft it
lodestar suggest --dismiss 3 thanks    # hide one for 3 days (kinds: thanks, reply, checkin, followup, referral)
lodestar today                         # the whole agenda, suggestions included
```

### Contacts (people, LinkedIn import, warm paths, touches)

**What it is for.** A small address book of the people in your search: recruiters, hiring managers, referrers,
interviewers and your LinkedIn connections, linked to jobs with a role.

**Add people.**

- App: Contacts tab > name, email, company, position > **Add contact**.
- Terminal:

  ```powershell
  lodestar contacts add "Sam Lee" --email sam@initech.com --company Initech --position "Eng Manager" --next-touch 2026-12-01
  ```

  Email and LinkedIn URL must be unique. Setting a job's contact (`lodestar jobs contact` or the drawer's **set
  contact**) also files that person under Contacts, linked as recruiter.

**Import your LinkedIn connections.**

1. On LinkedIn, request your data: Settings > Data privacy > Get a copy of your data. The basic archive arrives by
   email.
2. In the app: Contacts > choose the `.zip` (or the `Connections.csv` inside it) > **Import LinkedIn connections**.
   In the terminal:

   ```powershell
   lodestar contacts import "$HOME\Downloads\Basic_LinkedInDataExport.zip"
   ```

3. You should see a line like
   `2 row(s): 2 added, 0 updated (blank fields filled), 0 unchanged or skipped. No follow-up dates were set: ...`.
   Importing again is safe: duplicates are matched by LinkedIn URL, then email, then name + company, and a known
   contact only gains fields it lacks, so your edits stay. "Connected on" becomes the how-met note.

**Work with them.**

```powershell
lodestar contacts list                 # A-Z with company, position, last / next touch, linked jobs
lodestar contacts list acme --due      # filter text; --due: only those whose next touch has come
lodestar contacts show 1               # fields, linked jobs, timeline entries mentioning their email
lodestar contacts edit 1 next_touch=2026-12-01 notes="met at PyCon"   # empty value clears a field
lodestar contacts link 1 3 --role referrer   # roles: recruiter, hiring_manager, referrer, interviewer, other
lodestar contacts link 1 3 --remove    # unlink
lodestar contacts due                  # whose next touch has come
lodestar contacts rm 1                 # linked jobs stay
```

In the app, click a name to open the contact drawer: edit fields and notes, set the next touch, **Touched today**,
link to a job with a role, unlink, delete.

**Warm paths.** When a contact's company matches a job's company (legal suffixes such as Inc or LLC ignored; "Amazon"
also matches "Amazon Web Services"), the board card, search results and the job drawer's **People** group show "you
know N people here". It is a loose match: a hint, not a guarantee. From People you can **link** them with a role or
**Ask for referral**: with their email, a referral email goes to the Inbox and always waits for your review; without
one you get a LinkedIn note to send yourself. The contact is linked as referrer unless they already have a role.

**Touches.** Last touch moves forward on its own when mail from their exact address is scanned, or when you send them
an approved email. **Touched today** (or `contacts edit ID last_touch=YYYY-MM-DD`) records one by hand; those count
toward Insights, weekly goals and the activity log. A next touch puts them on the Today list (and in `lodestar today`)
once the date comes, until you are in touch again. Nothing is ever drafted or sent for a due contact.

**Safety.** A contact never becomes a job's contact by itself and never makes mail trusted. Only the job's own contact
field counts for trust.

**Where it lives.** Tables `contacts`, `job_contacts` and `touches` in `lodestar.db`. The LinkedIn archive itself is
not stored.

**AI helpers (Contacts):** the tab's **✦ AI help** > **Who to ask for a referral**; a contact's drawer > **Draft an intro** (a message to paste yourself; refused when it would name your salary floor). Both read only; asking for the referral stays the job drawer's **Ask for referral**.

### Interview rounds, calendar files and reminders

**What it is for.** Each job keeps its rounds: number, kind (phone, technical, onsite, panel, final, other), time,
interviewers, the questions you were asked, notes and outcome (pending, passed, rejected, unknown). Today, reminders,
clash checks, suggested thank-yous and Insights all read the rounds.

**How rounds get recorded.**

- Automatically: a trusted interview mail with a stated time (above), an interview reply you approve that accepts a
  slot, and every `.ics` you create.
- By hand, app: job drawer > **Interview rounds** > **Log a round**, then **Save round**; **edit** and **delete** on
  each round.
- By hand, terminal:

  ```powershell
  lodestar interview log 3 --kind phone --at "2026-11-20 14:00" --interviewers "Jane Doe" --questions-file asked.txt
  lodestar interview log 3 --round 1 --outcome passed    # update round 1
  lodestar interview rounds 3
  ```

  `asked.txt` holds one question per line. Without `--round` the next number is used. `--at` also takes a date only.

**Calendar files.**

```powershell
lodestar ics 3 --when "2026-11-20 14:00" --minutes 45
```

It prints the path of `applications\<job>\interview-YYYYMMDD-HHMM.ics`. Double-click it to add it to Outlook, Google
Calendar or Apple Calendar. The file holds the interview (with a 30-minute alarm) and a 30-minute prep reminder at
09:00 two days before. It also records the round. In the app: job drawer > Schedule and decide > enter the time >
**Calendar .ics**. A new time for a job whose only upcoming round is still pending moves that round instead of adding
one.

**Reminders.** While the monitor loop runs, each interview within the next 48 hours produces one alert line
(`INTERVIEW Wed 2026-11-11 14:00: #1 Acme - ...`), shown once. Interviews within 48 hours are also on the Today list.
Desktop notifications add a toast 2 hours before (below).

**Where it lives.** The `interviews` table in `lodestar.db` and the `.ics` files in the job's folder.

### Question bank

**What it is for.** The questions you were actually asked become a personal bank that prep packs and mock interviews
use first.

```powershell
lodestar questions 3     # this company's logged questions, then similar titles, then ~30 bundled behavioural ones
lodestar questions       # every question you logged
```

In the app, the job drawer's Interview rounds group has a **Question bank** list for that job. To add questions, log
them with a round (above). The bundled set lives in `lodestar/data/questions.json`.

### STAR stories

**What it is for.** Your real stories (Situation, Task, Action, Result, plus metrics), tagged by competency. Prep and
mock interviews put your matching stories in front of the AI so it coaches with your material instead of inventing
examples.

**In the app.** Answers > **Stories (STAR)**: fill title, Situation, Task, Action, Result, metrics, tick
competencies, **Save story** (**New story** clears the form). An idea from the Ideas tab's `stories` topic has
**Save as story**. The job drawer says which competencies a posting stresses and offers **Add a story** for one you
have no story for yet.

**In the terminal.**

```powershell
lodestar stories add --title "Rescued the billing migration" --situation "..." --task "..." --action "..." --result "..." --metrics "shipped 2 weeks early" --tags ownership,deadline
lodestar stories add --from-idea 4     # turn an ideas 'stories' idea into a story to finish
lodestar stories list                  # shows "(missing: task)" for incomplete ones
lodestar stories show 1
lodestar stories rm 1
```

A story needs a title and at least one STAR part. Tags: leadership, conflict, failure, ambiguity, influence,
ownership, customer, data-driven, teamwork, deadline. Stories are stored in the answer bank (question
`Story: <title>`) but listed separately from form answers.

**AI helpers (stories):** each story's toolbar, and its **✦ AI help** > **Fill STAR from my notes**: the AI moves what you wrote into the right STAR parts (empty parts included) without adding facts; the suggestions appear in the story's toolbar and only **Apply suggestions** writes them. **Map my stories to this job** is in the job drawer.

### Interview prep and mock interviews

**Prep pack** (needs an AI provider and a filled-in profile): likely questions with model answers, STAR answers from
your stories, the toughest questions given your gaps, questions to ask, a 60-second pitch and pay notes. It starts
from the questions logged for this company.

```powershell
lodestar interview prep 3              # writes applications\<job>\interview_prep.md
lodestar interview prep 3 --council    # every configured provider, then a synthesis
```

App: job drawer > **Interview prep** (and **View** to open it in the document viewer). If your profile is still the
template you get `your master profile is still the template: fill in ...profile.md or import a resume`.

**Mock interview.** One question at a time; type `done` to finish.

- App: Coach tab > choose **Mock interview for…** and the job, and optionally a **focus** (one competency, e.g.
  conflict). The microphone button (**Dictate**) uses your browser's speech recognition; **speak replies** reads
  questions aloud.
- Terminal: `lodestar interview mock 3` (`--focus conflict`).

Lodestar picks every question from the job's sourced practice set (below), and the AI interviewer asks it word for
word. Under each question a chip says where it came from: `logged · round 2`, `pasted · Glassdoor reviews (you)`,
`Acme page` with a link to the page, `job description`, `reported, unverified` or `general`; hover it for the full
source and quote. Your logged and pasted questions and the company's own pages come first whenever any are left.

After each answer you get a score card. With an AI provider: situation, task, action and result (0-2 each),
relevance and specificity (0-2), whether a number backs the result, one fix and a rewrite that only reorders your own
facts, plus a scored debrief at `done`. Always, even offline: word count, estimated speaking time (about 140 words a
minute against a 60-120 second target), the most repeated words and the posting keywords you used; words per minute
only when you dictated. Without a provider the questions come from your question bank in order and there is no
rubric or debrief. The transcript is saved to `applications\<job>\mock_interview.md`; sessions and cards go to the
`mock_sessions` table, and the Coach tab shows a **Mock interview trend** across sessions.

**Practice questions and their sources.** Each job has a practice set, best-founded first: questions **you logged**
in a round at this company > questions in **notes you pasted** > questions derived from **the company's own public
pages** (how we hire, values, culture) > the **job description** > **reported, unverified** (what the AI says the
company is known to ask; off unless you run `lodestar tools set reported_questions true`) > the **general** bank.
The drawer's **Interview readiness > Question sources** panel (shared by every job at the company) shows the counts,
the **Company website** (taken from the job URL when its host names the company, or typed by you; job boards and ATS
hosts are refused), the pages read (with "skipped: robots.txt disallows" where the site says no), your pastes with
**Delete**, and **Paste what you read**: where it is from, an optional link (stored as a citation, never opened)
and the text. Lodestar never opens Glassdoor, Blind, LinkedIn or Indeed pages; paste what you read there yourself.
**Refresh** re-reads the company's pages (robots.txt respected, at most 12 requests) and makes one AI call that turns
your notes, the pages and the JD into questions; the code checks every quote against its source, and the questions it
drops are listed with why. **Questions (N)** lists the set by competency, with how often the company's material
mentions each one (counts, never percentages).

```powershell
lodestar interview questions 3 --refresh          # the set with sources (--offline: never the AI)
lodestar interview paste 3 --label "Glassdoor reviews, read 2026-11-05" --file notes.txt
lodestar interview site 3 https://www.acme.com    # the company website
lodestar interview sources 3                      # website, pages, pastes
```

**Readiness.** Drawer > **Interview readiness** (shown once a job is at screening, interview or offer, or has a round
or a mock) scores your **preparation** for that job from 0 to 100: mock answer quality (30 points), the competencies
the company's material stresses that you have practised (20), STAR stories for the four most mentioned ones (15), the
company's own questions practised (15) and the prep pack and research (10). Each part has a bar with its number and
the reasons; **Raise it** lists the three actions that would add the most points with a button each (Practise opens
the mock on that competency). Next to the score sits a **chance estimate band** (low, fair, good, strong), always "from
your preparation; not a probability": Lodestar does not know how the company decides or who else applied, so it never
shows a percentage. Once 8 of your rounds have a recorded result, your own record (rounds passed per band, as plain
counts) is shown beside it and in **Insights > Readiness vs results**; it never moves the band. **Explain my
readiness** asks the AI for advice on the breakdown (never your fit score); **What should I practise next?** shows the
top raise-it row without AI. Today shows the readiness of an interview in the next 48 hours, and under 60 its top tip.
After each mock answer the Coach shows the new readiness. Readiness never goes into anything an employer reads or a
pipeline step's output. Terminal: `lodestar interview readiness 3`, `lodestar interview calibration`.

**AI helpers (Coach):** the coach chat and the mock interview are the AI; no extra menu. **Likely interview topics** and **Questions to ask them** are in the job drawer's AI help.

### Offers, the comp table and counter-offers

**Record an offer.** Fields: base, bonus % (target), sign-on, your estimate of the equity grant's value, vesting
years, cliff months, retirement match %, workplace (`remote`), start date, deadline, notes. `150k` works for amounts;
an empty value clears a field. Recording an offer moves the job to `offer`.

```powershell
lodestar offers set 7 base=150k bonus_pct=10 sign_on=20000 equity_value_estimate=200k vest_years=4 cliff_months=12 deadline=2026-12-01
lodestar offers                        # the same as: lodestar offers compare
```

App: Insights > Offers > **Record or edit an offer** > pick the job > **Save offer**.

**Compare.** The table shows each live offer (status offer or accepted) side by side: base, target bonus, sign-on,
match, equity per year, year-1 cash, year-1 total, 4-year total, your market range, workplace, start date and deadline,
with `*` on the best value per row. It lists every estimate behind the totals (bonus at target, equity at your own
value with no growth, monthly vesting after the cliff). When your profile's Preferences name a salary floor, a
private row shows the gap to it; that row appears only in Lodestar's own views, never in anything sent.

**Market-rate table (comp).** Your own ranges per title and city, quoted by gap checks, offer evaluation and prep:

```powershell
lodestar comp set "backend engineer" austin 130000 170000    # city optional; * = anywhere
lodestar comp list
lodestar comp lookup "backend engineer" austin
```

Also in the app under Setup > Market rates. Stored in `~/.lodestar/comp.json`.

**Offer evaluation.** `lodestar offer 7 ...` or the drawer's **Evaluate offer** compares the offer with your
preferences and writes a negotiation plan to `offer.md` (needs an AI provider). Insights > **View offer notes** opens
it.

**Counter-offer.**

1. App: Insights > Offers > **Draft a counter-offer** > pick the offer to counter > tick the competing figures to cite
   > optionally type your ask > **Draft counter-offer** (or **Options** for up to three). Tick **plain template, no
   AI** for the offline template. **View / format the draft** opens it in the document viewer.
2. Terminal:

   ```powershell
   lodestar offers counter 7 --cite 9:base 9:sign_on --ask "a base of 170,000"
   lodestar offers counter 7 --cite 9:sign_on --template     # no AI
   lodestar offers counter 7 --cite 9:base --options         # then --pick N
   ```

   Citable fields: `base`, `bonus_pct`, `sign_on`, `equity_value_estimate`, `year1_total` of another offer
   (`JOB:FIELD`).
3. The draft says "another offer" without naming the company, uses only the figures you ticked and your ask, and
   always waits in the Inbox for review, even with `email_reply` on auto. Without a contact on the job you get the text
   only (`'status': 'draft_only', 'reason': 'no contact email on this job'`).

**Safety.** A counter never contains your salary floor, Preferences or offer notes. A competing figure you cite is
sent by your choice, so it may equal your floor; your ask and everything else in the email are still checked.

**Where it lives.** The `offers` table in `lodestar.db`, `comp.json`, and `offer.md` in the job folder.

### Insights and weekly goals

**What it is for.** What you did each week and what is working. Only your own actions count: jobs entering `applied`
(moved by you, or by the employer's confirmation mail), interview rounds held, offers, people you contacted (mail
sent from the Inbox plus touches you record) and mock sessions. An auto-tracked save and Inbox items you did not send
never count.

**In the app.** The Insights tab: **Weekly goals**, **Each week** (last 4, 12 or 26 weeks, with "as a table"),
**Response rate by source**, **Does tailoring pay off? Response rate by match score**, **Funnel and resume variants**,
**Offers** and **Activity log**. A group with fewer than 5 applications shows "not enough data yet".

**In the terminal.**

```powershell
lodestar insights                      # last 12 weeks
lodestar insights --weeks 4 --json
```

**Weekly goals.** None are set by default. Goals: `contacts`, `tailored_applications`, `mock_sessions`,
`applications`. Set one at a time; `0` removes it:

```powershell
lodestar tools set weekly_goals contacts=5
lodestar tools set weekly_goals tailored_applications=3
```

Progress counts Monday to today (`Weekly goals: contacts 0/5  applications 1/3` at the end of `lodestar insights`)
and is listed in the weekly digest. In the app, set them on the Insights tab's Weekly goals panel.

**AI helpers (Insights):** the toolbar (Recommend: advice only) and **✦ AI help** > **Explain my numbers**.

### Activity log export

**What it is for.** A week-by-week record of your job-search activity (applied, contacted, followed up,
interviewed), for example for an unemployment claim. Columns: date, activity, employer, position, method, contact,
result. It is a helper report built from what Lodestar recorded: check your state's requirements; it makes no claim
of compliance.

Counted: jobs moved to applied, mail actually sent from the Inbox (not pending, rejected or failed items, and not
withdrawals), interview rounds up to today and contact touches you recorded.

**In the app.** Insights > **Activity log**: pick from and to dates, optionally a **weekly minimum**, then **Show**,
**Export CSV** or **Printable page** (print it to PDF from the browser).

**In the terminal.**

```powershell
lodestar activity                                   # this week
lodestar activity --week 2026-11-04                 # the Monday-Sunday week containing that date
lodestar activity --from 2026-10-01 --to 2026-10-31 --csv
lodestar activity --from 2026-10-01 --to 2026-10-31 --html   # Markdown + printable HTML
lodestar tools set activity_weekly_min 3            # each week then shows met / not met
```

Files go to `~/.lodestar/exports/activity-<from>-to-<to>.csv` (or `.md` and `.html`). CSV cells a spreadsheet would
run as formulas are prefixed with `'`. A range can be at most three years.

### The weekly digest

**What it is for.** A one-page summary: pipeline counts and rates, jobs that moved in the last 7 days, applications
needing a follow-up, your weekly goals, the week's alerts and, with an AI provider, a coach's five actions for next
week.

**Run it by hand.**

- App: Monitor > **Weekly digest** (shows it) or **Email digest** (also emails it).
- Terminal:

  ```powershell
  lodestar digest                 # print it
  lodestar digest --days 14       # a longer window
  lodestar digest --send          # also email it
  ```

  `--send` goes to `LODESTAR_NOTIFY_EMAIL` if set, else to your connected mailbox's own address, through your
  connected mailbox. With neither you see `emailing the digest needs your own address: connect your mailbox ...`.

**Get it automatically.** The `digest` tool is off by default. Turn it on:

```powershell
lodestar tools enable digest
lodestar vault set LODESTAR_NOTIFY_EMAIL     # prompts for the address; or put it in .env
```

The loop then handles it once a week, on the first cycle from Friday on (a Friday when the app was closed catches up
on the next cycle). The automatic digest is emailed only when `LODESTAR_NOTIFY_EMAIL` is set; without it a one-line
alert says `DIGEST ready: Monitor > Weekly digest (or lodestar digest)`. One try a week: a failed send is reported
once.

Note that `LODESTAR_NOTIFY_EMAIL` also emails you every alert line the loop writes (new mail, follow-up nudges,
interview reminders), not only the digest.

### Desktop notifications

**What it is for.** Operating-system notifications while the monitor loop runs: one agenda a day (next actions,
deadlines, follow-ups, interviews, contacts due, suggested emails, Inbox size), an interview within 2 hours, and a
deadline tomorrow. Each fires once.

**Turn it on.** Off by default.

- App: Setup > **Desktop notifications** > tick **notify me on this computer**; **Send a test** checks your system
  (you should see "test notification sent"; "this computer did not accept the notification" means the OS refused).
  Also under Tools > Preferences.
- Terminal: `lodestar tools set desktop_notifications true`

Windows shows a toast under PowerShell's identity (check Windows Settings > System > Notifications if nothing
appears), macOS uses `osascript`, Linux uses `notify-send` (install your distribution's notify-send package if it is missing). A system that
refuses is skipped silently. Notifications only fire while a loop runs (the desktop window, `lodestar app` or
`lodestar run`).

## For developers and maintenance

This part is for whoever changes Lodestar's code, runs its tests, or keeps an install healthy. If you only use the app,
the parts you need most are [Logs: where to look](#logs-where-to-look) here and [Troubleshooting](#troubleshooting) at the end of this guide.

Paths below are relative to the repo folder (for example `C:\Users\you\AISearchBot`). Windows commands are PowerShell;
on macOS and Linux replace `.venv\Scripts\python.exe` with `.venv/bin/python`.

### Developer setup

Lodestar needs Python 3.11 or newer (`requires-python = ">=3.11"` in `pyproject.toml`). CI runs 3.11 to 3.14.

1. Create the virtual environment in the repo folder (skip if `start.bat`, `start.ps1` or `install.ps1` already made
   `.venv`):

   ```powershell
   python -m venv .venv
   ```

2. Install Lodestar in editable mode with the extras you need:

   ```powershell
   .venv\Scripts\python.exe -m pip install -e ".[all,e2e]"
   ```

   The extras are explained in [Manual install with pip](#manual-install-with-pip); `e2e` adds `playwright` and `coverage` for the browser
   suite and coverage reports.

3. Optional, to match CI exactly: the linter CI uses is not in any extra.

   ```powershell
   .venv\Scripts\python.exe -m pip install pyflakes
   ```

4. Check the install. Point `LODESTAR_HOME` at a scratch folder first so you do not touch your real data:

   ```powershell
   $env:LODESTAR_HOME = "$env:TEMP\lodestar-dev"
   .venv\Scripts\python.exe -m lodestar doctor
   ```

   You should see `[PASS]` lines for Python, the modules, the keyring backend and the data folder. On a fresh scratch
   folder, `master profile` and `profile bank` are WARN and `AI providers` may be FAIL; that is expected.

   A scratch `LODESTAR_HOME` also gets its own keyring namespace: `vault namespace` reads `lodestar:<12 hex> (this
   data folder only ...)`, and the AI keys and mail login you linked for real are not visible there. Do not set
   `LODESTAR_VAULT_SERVICE` for scratch runs. For manual experiments you can also add
   `$env:PYTHON_KEYRING_BACKEND = "keyring.backends.null.Keyring"`, so nothing at all is read from or written to the OS
   keyring (doctor then shows `keyring backend` as WARN `null.Keyring`). The repo's `.env` still loads: keep secrets out
   of it.

`python -m lodestar` and the `lodestar` / `jobbot` scripts (`.venv\Scripts\lodestar.exe`) run the same CLI
(`lodestar.cli:main`); `jobbot` is a legacy alias.

### Repo layout

Top level:

| Path | What it is |
|---|---|
| `lodestar/` | the Python package (all code, the web page, data files) |
| `lodestar/static/` | the web UI: `index.html`, `app.js`, `app.css`, `logo.svg` (served by `web.py`, no build step) |
| `lodestar/data/` | `skills.json` (the JD coverage lexicon), `questions.json` (the interview question bank) |
| `tests/` | the offline unit and integration suite (`test_*.py`) |
| `tests/e2e/` | the browser suite (`e2e_*.py`) and its `harness.py`; failures leave files in `tests/e2e/_artifacts/` |
| `docs/` | user and developer docs: SETUP, CONNECT, COMMANDS, AUTOMATION, FEATURES (generated), RUNDOWN, TESTS, CHANGELOG, CAPTURE |
| `.github/workflows/ci.yml` | CI (see "CI") |
| `pyproject.toml` | package metadata, dependencies, extras, the `lodestar` and `jobbot` scripts, coverage settings |
| `install.ps1`, `install.bat`, `install.sh`, `uninstall.ps1` | installers and uninstaller (Desktop shortcut, launcher, optional schedule, optional `-Exe` build) |
| `start.ps1`, `start.bat`, `start.sh` | quick-run starters (create `.venv`, install, `init`, open the app) |
| `lodestar.spec`, `build/`, `dist/` | PyInstaller spec and its output (`dist\lodestar.exe`, made by `install.ps1 -Exe`); git-ignored |
| `assets/` | app icons (`lodestar.ico`, `.png`, `.svg`) |
| `.env.example` | every setting you can put in `.env`, commented |
| `CLAUDE.md` | project conventions for AI-assisted work (summarised below) |
| `graphify-out/` | the code knowledge graph (git-ignored; see "Knowledge graph") |

The package, module by module (from `docs/RUNDOWN.md` section 1 and each module's own docstring):

| Module | What it does |
|---|---|
| `__init__.py`, `__main__.py` | version; the `python -m lodestar` entry (also what the PyInstaller build runs) |
| `cli.py` | the argparse front end: every `lodestar` command, the `chat` coach, the `ui` launcher |
| `config.py` | data-folder paths (`LODESTAR_HOME`), `.env` loading, `setting()` lookup: env var, then `.env` files, then the keyring vault, then the default |
| `vault.py` | OS-keyring store for API keys, mail credentials and site logins; only a name index (`vault_index.json`) is on disk |
| `settings.py` | tool switches (enabled / auto) and preferences in `settings.json` |
| `log.py` | the one rotating log file, `lodestar.log` |
| `util.py` | safe URL fetches (SSRF guard, robots.txt), HTML to text, JSON extraction, alerts (`notify`), SMTP sending, run locks |
| `db.py` | the SQLite tracker: jobs, events, watches, companies, contacts, interview rounds, offers, mail, the Inbox, stats |
| `ai.py` | `chat()`, `ask()`, `ask_json()` over Anthropic and every OpenAI-compatible API; `council()`; token accounting in `usage.jsonl` |
| `connections.py` | AI key registry, no-token key checks, stored check results (`connections.json`, fingerprints only), the background startup check |
| `profile.py` | the profile bank (`profile.json`), resume and LinkedIn import with review, `candidate_text()` for prompts, `write_master()` |
| `resume.py` | master profile reading, tailoring, cover letters, gap check, review, Markdown to DOCX / PDF |
| `studio.py` | the master resume kept in step with your profile, and the resume studio's versions |
| `render.py` | the deterministic renderers: one document + one style to HTML, DOCX, profile Markdown and ATS plain text |
| `viewer.py` | the document viewer: every generated document through one renderer path, per-document formatting (`viewer.json`), PDF cache |
| `ats.py` | JD coverage: which posting keywords your resume mentions (offline, no AI) |
| `lint.py` | offline resume checks (`resume lint`) and the saved-file audit (`resume audit`) |
| `email_monitor.py` | IMAP scan, keyword prefilter, AI classification, sender trust, status moves, interview rounds, reply drafts, mail recording |
| `mailconn.py` | mail provider presets, the stored connection, IMAP and SMTP login tests, test send |
| `oauth.py` | Google / Microsoft sign-in (your own client, PKCE, loopback), refresh token in the keyring, XOAUTH2 |
| `codes.py` | emailed sign-in codes from DKIM-passing mail, memory only, 15 minutes |
| `mailfiles.py` | attachments: outgoing only from the job folder's employer-safe set; incoming saved, never opened |
| `drafts.py` | AI draft options, rewrites, `use()` (always through the Inbox), suggested emails, the salary-floor `screen()` |
| `approvals.py` | the Inbox: `propose`, `approve`, `reject`; the only code that sends mail, moves a job or adds a job on Lodestar's own initiative |
| `apply.py` | answer bank, checklist, follow-up, thank-you, offer review, listing judgement for auto-track |
| `pipeline.py` | step-by-step automation per job (fit check through close), Run next step, questions for you, Autopilot |
| `interview.py` | interview rounds, question bank, STAR stories, prep pack, mock interview with scoring |
| `contacts.py` | contacts CRM, LinkedIn connections import, warm paths, touches |
| `web_monitor.py` | career-page diffs, six free job sources, Greenhouse / Lever / Ashby boards, filters, de-dup, stale and sponsor signals |
| `comp.py` | your market-rate table (`comp.json`), offer totals and compare |
| `ideas.py` | idea crafting across providers |
| `extras.py` | outreach, `.ics`, digest, Obsidian export, backup, export, research, packet, insights, activity log, schedule installer |
| `loop.py` | the monitor cycle behind `run`, `app` and `desktop`, and the Today agenda |
| `updater.py` | self-update: check, apply (backup, fast-forward, tests, rollback), status, log |
| `doctor.py` | `lodestar doctor` and Setup > Diagnostics |
| `inventory.py` | `lodestar features`, the generator of `docs/FEATURES.md` |
| `desktop.py` | the native window (Edge WebView2 via pywebview) with the browser fallback |
| `web.py` | the local web server on 127.0.0.1: per-launch token, Host check, background tasks polled by the page |

To find your way around quickly, `graphify god-nodes` lists the most connected parts of the code (for example
`con()` and `get_job()` in `db.py`); see "Knowledge graph" below.

### Running the unit suite

The unit and integration suite is offline: every AI provider, mail server, OAuth server and job site is faked. Each
test module sets its own temporary `LODESTAR_HOME`, so `~/.lodestar` is not used. pytest is not installed; the suite
uses the standard library's `unittest`.

1. From the repo folder, run:

   ```powershell
   .venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
   ```

   CI runs the same thing with warnings about unclosed resources hidden and one line per test:

   ```powershell
   .venv\Scripts\python.exe -W ignore::ResourceWarning -m unittest discover -s tests -v
   ```

2. What you should see: dots, some `[date] ...` alert lines that tests print on purpose (they come from fake mail and
   watches), and at the end `Ran N tests in ...` (644 at the time of writing; `CLAUDE.md` holds the current count) followed by `OK` (two tests skip when their condition is not met).
   It takes about four minutes.

3. To run one module, one class or one test, run from inside `tests` (the modules import each other by bare name):

   ```powershell
   cd tests
   ..\.venv\Scripts\python.exe -m unittest test_pass17_viewer
   ..\.venv\Scripts\python.exe -m unittest test_pass17_viewer.RealEdge
   ..\.venv\Scripts\python.exe -m unittest test_lodestar.Cli.test_parser
   ```

If it fails: read the `FAIL:` / `ERROR:` block at the end. Two failures that are about the docs, not the code:
`update the test count in CLAUDE.md` and the matrix guard (see "The test matrix"). One test,
`test_pass17_viewer.RealEdge`, prints a real PDF with your installed Edge; it skips when no Edge, Chrome or Chromium is
found, and it can fail with `no PDF written (exit 0)` when the suite runs inside a restricted or sandboxed shell. The
same test passed when run from a normal PowerShell window.

### Running the browser (E2E) suite

The browser suite drives the real web UI with Playwright. For each test class, `tests/e2e/harness.py` makes a fresh
temporary `LODESTAR_HOME`, seeds fictional data (a sample profile for "Pat Rivera" and a set of jobs) through the app's
own write paths, fakes every outside service (AI, IMAP and SMTP, OAuth, job-site fetches, the keyring, desktop toasts,
the default browser), starts the real server on a free 127.0.0.1 port, and opens one browser. It never touches
`~/.lodestar` and makes no network calls. It also blanks any key found in the repo's `.env` for the test process.

1. Install the extra (once):

   ```powershell
   .venv\Scripts\python.exe -m pip install -e ".[e2e]"
   ```

2. Run the whole suite (uses your installed Microsoft Edge by default):

   ```powershell
   .venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"
   ```

   What you should see: `Ran 155 tests` (at the time of writing) and `OK`, after about seven minutes. One module alone, for a quick check:

   ```powershell
   .venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_smoke.py"
   ```

   The smoke module (15 tests, one per tab plus the page token check) takes about 20 seconds.

3. Environment variables (read by `harness.py`):

   | Variable | Default | Effect |
   |---|---|---|
   | `LODESTAR_E2E_BROWSER` | `msedge` | `chromium` uses Playwright's own Chromium (what CI uses); any other value is passed as the Playwright channel |
   | `LODESTAR_E2E_HEADED` | off | `1` shows the browser window so you can watch |
   | `LODESTAR_E2E_SLOWMO` | `250` when headed, else `0` | milliseconds of pause between browser steps |

4. To watch it run:

   ```powershell
   $env:LODESTAR_E2E_HEADED = "1"
   $env:LODESTAR_E2E_SLOWMO = "500"
   .venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_board.py"
   Remove-Item Env:LODESTAR_E2E_HEADED, Env:LODESTAR_E2E_SLOWMO
   ```

5. To use Chromium instead of Edge (for example on Linux):

   ```powershell
   .venv\Scripts\python.exe -m playwright install chromium
   $env:LODESTAR_E2E_BROWSER = "chromium"
   .venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"
   ```

Rules the suite enforces, and what to do when it fails:

- Any console error or uncaught page error fails the test, on every screen.
- A failing test leaves a screenshot and the page HTML in `tests/e2e/_artifacts/` (git-ignored). Open them first.
- Without Playwright installed, the suite skips with `playwright is not installed ...; pip install -e .[e2e]`.
- Without the chosen browser it skips with `no msedge browser for Playwright ...`; set `LODESTAR_E2E_BROWSER=chromium`
  and install Chromium as in step 5. When the `CI` environment variable is set, a missing browser is a failure instead
  of a skip.

### The test matrix (docs/TESTS.md) and its guard

`docs/TESTS.md` has one row per feature with an ID, a description, the unit/integration tests and the E2E tests that
cover it, each named exactly as `module.Class.test_name`. Features that are planned but not built are listed under
"Planned" with no tests.

`tests/test_feature_matrix.py` (part of the unit suite) guards it. It fails when:

- a row lists no test, names a test that does not exist, puts a browser test in the unit column, or repeats an ID;
- a test exists that no row names;
- a row ID or a Planned ID disappears (all IDs are pinned in the guard's `NUMBERED`, `NAMED` and `PLANNED` sets);
- `CLAUDE.md`'s stated unit-test count (the `(644 tests)` after the unit command) differs from the real count.

It reads the test files with `ast` instead of importing them, so it runs without Playwright.

The convention: every new feature adds a row to `docs/TESTS.md`, a unit test, and an E2E test when it has UI. When a
Planned feature gets built, move its ID out of "Planned" into a row, and update the guard's pinned sets (raise the
number for a numbered area, or add the name to `NAMED`).

### Coverage

Coverage is informative only; there is no minimum. `pyproject.toml` limits it to `lodestar/`. To measure both suites
together (needs the `e2e` extra for `coverage`):

```powershell
.venv\Scripts\python.exe -m coverage erase
.venv\Scripts\python.exe -m coverage run -p -m unittest discover -s tests -p "test_*.py"
.venv\Scripts\python.exe -m coverage run -p -m unittest discover -s tests/e2e -p "e2e_*.py"
.venv\Scripts\python.exe -m coverage combine
.venv\Scripts\python.exe -m coverage report --sort=cover
```

The last measured table, and why the least covered modules are low, is in `docs/TESTS.md` > Coverage.

### CI

`.github/workflows/ci.yml` runs on every push and pull request. Two jobs:

| Job | Runs on | Steps |
|---|---|---|
| `test` | ubuntu-latest and windows-latest, Python 3.11, 3.12, 3.13 and 3.14 | `pip install -e . pyflakes`; `python -m pyflakes lodestar tests`; `python -W ignore::ResourceWarning -m unittest discover -s tests -v`; `node --check lodestar/static/app.js` |
| `e2e` | ubuntu-latest, Python 3.12 | `pip install -e .[e2e]`; `python -m playwright install --with-deps chromium`; the E2E suite with `LODESTAR_E2E_BROWSER=chromium`; on failure, uploads `tests/e2e/_artifacts` as the `e2e-artifacts` artifact |

To run the same checks locally before you push:

```powershell
.venv\Scripts\python.exe -m pyflakes lodestar tests
.venv\Scripts\python.exe -W ignore::ResourceWarning -m unittest discover -s tests -v
node --check lodestar/static/app.js
```

`node --check` needs Node.js; it only checks that `app.js` parses. pyflakes reports unused imports, undefined names and
similar; fix every line it prints, because CI fails on any.

### Knowledge graph and the Obsidian mirror

The repo has a code knowledge graph made by the `graphify` tool. It is a development aid only: Lodestar itself never
reads it, and `graphify-out/` is git-ignored.

- `graphify-out/graph.json`: the graph (functions, classes, files, doc sections and the links between them).
- `graphify-out/GRAPH_REPORT.md`: a readable summary: size, the commit it was built from ("Graph Freshness"), and the
  main hubs.
- `graphify-out/graph.html`: an interactive view you can open in a browser.
- `graphify-out/autobuild.log`: when automatic rebuilds started and finished.

On this machine a Claude Code session hook (`~/.claude/hooks/knowledge-stack.py`, outside the repo) refreshes the graph
in the background when a session starts or stops (it runs `graphify update <repo>`) and mirrors it as Obsidian notes
into `<vault>\graphs\AISearchBot\` (one note per node plus `graph.canvas`, by `graphify export obsidian`). The vault is
`$env:OBSIDIAN_VAULT` if set, else `~\Documents\Obsidian Vault`. Do not hand-edit the generated notes there; they are
regenerated. Add your own notes beside them.

Useful commands (run from the repo folder):

```powershell
graphify query "how does approvals propose screen the salary floor"   # walk the graph from the matching nodes
graphify query "mail trust" --budget 4000                             # a bigger answer (default budget 2000 tokens)
graphify explain "lodestar/approvals.py::propose()"                   # one node and its neighbours
graphify path "lodestar/approvals.py::propose()" "lodestar/drafts.py::screen()"   # shortest link between two nodes
graphify god-nodes --top 10                                           # the most connected nodes
graphify update .                                                     # rebuild after code changes (no API cost)
```

`query`, `path` and `explain` exit 0 with an answer, 3 when a name is ambiguous (the candidates are listed: retry with
`path::symbol`, for example `lodestar/approvals.py::propose()`), and 4 when no node matches. If `GRAPH_REPORT.md`'s
"Built from commit" differs from `git rev-parse HEAD`, the graph is stale: run `graphify update .`. When the graph
and the code disagree, the code is right.

### Project conventions (CLAUDE.md, summarised)

`CLAUDE.md` holds the rules every change must keep. In plain words:

- **Tests**: the unit command and its count (kept in step by the matrix guard). All tests share one temp
  `LODESTAR_HOME` and module state, so a test that replaces a module attribute must put it back in a `finally`.
- **Profile text in prompts**: prompts read `resume.candidate_text(limit)` (master profile plus profile-bank facts,
  fitted by section), never `profile_text()[:N]`. Free-form helpers (coach, ideas, mock interview) pass
  `strict=False`.
- **Salary floor privacy**: anything an employer reads (resume, letters, mail, form answers) passes `private=False`, so
  the Preferences section (salary floor, deal-breakers) stays out. Drafts pass `drafts.screen`; the only exemption is a
  counter-offer's cited figures, passed in `cited=`. Reads of the answer bank for employers use `employer=True`
  (private answers never leave).
- **Writing profile.md**: always through `profile.write_master()` (it snapshots the old file and writes atomically).
- **Keyring isolation** (`vault.namespace`): the keyring service is `lodestar` (legacy `jobbot` fallback) only for
  the default data folder; any other `LODESTAR_HOME` uses `lodestar:<12 hex of its path>` with no fallback, so tests,
  agents and sandboxes never touch the real keys. All keyring access goes through `vault.py`. Never set
  `LODESTAR_VAULT_SERVICE` for a test or sandbox run (the update gate and the E2E harness blank it); manual runs also
  set `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`.
- **Mail trust** (`email_monitor._match` / `_thread`): mail is trusted only with aligned DKIM/DMARC, a strong tie to
  the job and agreement with the stored contact. Strong ties are the stored contact, a thread Lodestar's own mail
  vouches for, or the registrable domain of the job's posting URL on the company's own site. A domain that only names
  the company is weak: the mail is filed, never trusted. Mail about an untracked company is never trusted. Manual links
  never make a sender trusted. Never loosen this.
- **Drafts**: AI draft options and rewrites go through `drafts.py` (`options`, `rewrite`, `use`): one AI call, `screen()`
  on every text, untrusted mail fenced as data, mail proposals reviewed, recipient chosen by the server. A reply to
  unverified mail is flagged `unverified` and loses its status change.
- **Refusals for Inbox items** (the floor guard on edits, a clashing interview slot) go in `approvals._precheck`, which
  runs before the item is claimed, so a refused item stays pending.
- **SystemExit is the user-facing error**: `ai.*` and `profile_text()` report "no key", "model rejected" and "profile
  still the template" as `SystemExit`, which `except Exception` does not catch. Background code catches
  `(Exception, SystemExit)`.
- **Icons**: write `.ico` frames as classic BMP (PNG-compressed frames garble in pywebview's icon loader).
- **Installer**: changes to `install.ps1` apply only after it is re-run.
- **Real calls**: no real AI or SMTP call has been verified yet; the tests use a faked HTTP layer.

### Adding a feature safely

Follow these steps for any new feature. They keep the approvals, privacy and trust rules intact.

1. **Put the logic in the module that owns it** (see the module table). Reuse what exists: `db.py` for storage,
   `ai.ask` / `ai.ask_json` for AI calls, `util.fetch` for web pages (it applies the SSRF guard and robots.txt), and
   `util.notify` for alerts.
2. **Anything Lodestar does on its own goes through the Inbox.** Call `approvals.propose(tool, kind, payload, summary,
   job_id)`; never send mail, change a job's status or add a job directly. If it is a new automatic flow, add a tool to
   `settings.TOOLS` as `name: (description, enabled_default, auto_default)`; with `enabled` on and `auto` off it waits
   for you. New executors go in `approvals.EXECUTORS`, and new refusals in `approvals._precheck`. Commands a person
   types are confirmed by typing them and do not need the Inbox.
3. **Keep the salary floor private.** Employer-facing text reads the profile with `candidate_text(..., private=False)`
   and is checked with `drafts.screen()`. `propose()` already screens every `send_email` and `save_answer`.
4. **Treat incoming mail and web pages as data.** Fence untrusted text in prompts the way `drafts.py` does, and never
   widen mail trust.
5. **Report user problems as `SystemExit("one plain sentence with the fix")`.** In background threads, catch
   `(Exception, SystemExit)` and log with `log.get("<area>")`.
6. **Expose it.** A CLI command in `cli.build()` (with `help=`, so it shows in `lodestar -h` and in the generated
   inventory); a UI action in `web.py` (`_do(action, p)` runs it as a background task the page polls); the button in
   `lodestar/static/`.
7. **Test it.** A unit test (restore anything you monkeypatch in `finally`), an E2E test in `tests/e2e/` if it has UI,
   a row in `docs/TESTS.md`, and the new unit-test count in `CLAUDE.md`. Run both suites, pyflakes and
   `node --check`.
8. **Document it.** The command in `docs/COMMANDS.md`, behaviour in the relevant doc, an entry in `docs/CHANGELOG.md`.
   Regenerate the inventory from a scratch data folder, so your own preferences are not written into the repo:

   ```powershell
   $env:LODESTAR_HOME = "$env:TEMP\lodestar-features"
   $env:PYTHONUTF8 = "1"
   cmd /c ".venv\Scripts\python.exe -m lodestar features --markdown > docs\FEATURES.md"
   ```

   Going through `cmd /c` keeps the file plain UTF-8; Windows PowerShell's own `>` would write UTF-16. Check the result
   with `git diff docs/FEATURES.md`: only your new lines and the date should change.

### Logs: where to look

All of these are in the data folder (`~/.lodestar`, or `LODESTAR_HOME`). In the app: Setup > Data > **Open log** opens
`lodestar.log`, and **Open data folder** opens the folder.

| File | What is in it | How to read it |
|---|---|---|
| `lodestar.log` | everything: each CLI command line (a secret given to `vault set` is masked), user-facing errors, unhandled errors with tracebacks, failed background tasks (`tasks`), monitor-loop failures (`loop`), pipeline steps, studio rebuilds, alerts | open it in any editor; rotates at 2 MB, keeping 3 old files (`lodestar.log.1` ...) |
| `alerts.log` | one line per alert: `[YYYY-MM-DD HH:MM] message` (new mail classified, watch changes, follow-ups, update notices) | `lodestar alerts` prints the last part; the Monitor tab shows it live. With `LODESTAR_NOTIFY_EMAIL` set, each alert is also emailed to you |
| `usage.jsonl` | one JSON line per AI call: time, provider, model, input and output tokens (counts only) | `lodestar usage` (last 30 days), `lodestar usage --days 7` |
| `update-log.jsonl` | every update check and update: time, from, to, result (last 500) | `lodestar update log`, Setup > Updates |
| `connections.json` | the result of the last check of each AI key and the mailbox (status, time, detail; a key fingerprint, never the key) | Setup, `lodestar keys`, `lodestar doctor` |

## Troubleshooting

Where to look first:

1. Run `lodestar doctor` (or Setup > Diagnostics > **Run diagnostics**). Each line is PASS, WARN or FAIL with the fix
   beside it; the exit code is 1 when something is FAIL. The fixes for each doctor line are in [lodestar doctor](#lodestar-doctor).
   `lodestar doctor --live` (or **Diagnostics + live AI call**) also makes one real call per configured provider and
   one IMAP and SMTP login, so use it only when you want that.
2. Open `lodestar.log` (Setup > Data > **Open log**) and search for `ERROR` or `WARNING` near the time of the problem
   ([Logs: where to look](#logs-where-to-look)).
3. Run `lodestar alerts` for what the monitor loop reported.
4. Installer messages are in [Windows: install.bat and install.ps1](#windows-installbat-and-installps1), update messages in [Auto-update](#auto-update), and the
   sign-in errors in full in [CONNECT.md section 12](CONNECT.md#12-troubleshooting).

| Area | Symptom or message | Fix |
|---|---|---|
| Install and run | `lodestar` is not recognized | Run `.venv\Scripts\lodestar.exe ...` or `.venv\Scripts\python.exe -m lodestar ...`, or activate the venv first ([Running `lodestar` commands](#running-lodestar-commands)). |
| Install and run | PowerShell refuses to run `start.ps1`, `install.ps1` or `Activate.ps1` | Script execution policy: use `powershell -ExecutionPolicy Bypass -File start.ps1`; instead of activating, call `.venv\Scripts\lodestar.exe` by path. |
| Install and run | Double-clicking `dist\lodestar.exe` only flashes a console | Start it with a command: `.\dist\lodestar.exe desktop`. |
| Install and run | The window does not open and the UI opens in the browser (`desktop window failed ...` or `desktop window needs pywebview`) | `pywebview` or the WebView2 runtime is missing (see `lodestar doctor`): `.venv\Scripts\python.exe -m pip install -e ".[desktop]"`, or install WebView2. The browser UI works the same. |
| Install and run | `lodestar app` or `lodestar ui` fails because port 8765 is in use (for example `PermissionError: [WinError 10013]`) | Another Lodestar or another program holds it. Close it, or pass `--port 8800`. `lodestar desktop` picks a free port by itself. |
| Install and run | `no free port between 8765 and 8815` | Close other Lodestar windows, or `lodestar desktop --port N`. |
| Install and run | The page shows `missing or wrong token; reload the Lodestar page` | The server restarted, so the per-launch token changed: reload the page. |
| Install and run | The page or an API call answers `bad host` (HTTP 421) | The UI was opened by LAN address or another host name: open `http://127.0.0.1:<port>` or `http://localhost:<port>`. |
| Install and run | The top bar says `monitor loop: not running in this process`, or nothing happens on its own | You started `lodestar ui` or used `--no-loop`. Use the Lodestar shortcut, `lodestar desktop`, `lodestar app`, `lodestar run`, or the scheduled task. |
| Install and run | Nothing new happens while the app is closed or the PC sleeps | The loop only runs while Lodestar runs: install the scheduled task (`install.ps1 -Schedule` or `lodestar schedule install`). |
| Install and run | `<step> skipped: ...` every cycle | Read the reason; `lodestar doctor` checks keys, mail and the data folder. |
| Install and run | Data seems missing | Check which folder is in use: `lodestar doctor` prints it on the `data folder` line. A `LODESTAR_HOME` set in one window changes it for that window only. |
| Install and run | A key or setting you set in Setup is ignored | A value in an environment variable or `.env` wins. Remove that line and restart; `lodestar keys` shows where each key comes from. |
| Install and run | No nightly backups | The backup runs during a monitor cycle; with the app closed and no scheduled task, none runs. Check the `backup` tool is enabled in `lodestar tools list`. |
| Install and run | `lodestar update apply` is refused | Uncommitted changes or local commits in the install, a mail scan, Inbox send, background action or another update running, or another Lodestar process open. Commit or stash, close other windows, then `lodestar update check`; `lodestar update status` and `lodestar update log` say why. |
| Install and run | `git is not installed or not on PATH` / `this install has no origin remote; set update_origin` | Install git, or set `update_origin` (Tools > Preferences). |
| Install and run | doctor shows `ROLLBACK FAILED` for updates | Close Lodestar and run the `git reset --hard` command it prints, from the install folder; it is also retried at the next start. |
| Install and run | doctor: `legacy folder ~/.jobbot still exists` | Data from before the rename; delete it once `~/.lodestar` has your data. |
| Install and run | Profile bank suddenly empty, `profile.json.corrupt-<date>` in the data folder | `profile.json` could not be read and was moved aside: restore from `backups/` ([Backups, export and restore](#backups-export-and-restore)) or re-import. |
| Install and run | `cannot open <file>: ...` | A file argument points to a missing file: check the path. |
| AI keys | Getting started says "No AI provider configured", doctor shows `[FAIL] AI providers none configured`, or an AI action says `No AI provider configured: ...` | Link a key (Setup > **Link an AI key**, `lodestar keys link anthropic`) or click **Local only (Ollama)**. |
| AI keys | Failed right after linking | The key was cut short when copying, or the account has no credit: copy the whole key again, or add billing. |
| AI keys | `ANTHROPIC_API_KEY in .env or the environment overrides this key` | An old line in `.env` wins over what you linked: delete the line, restart Lodestar. |
| AI keys | `unknown key 'foo'. One of: anthropic, openai, gemini, groq, openrouter, mistral, ollama` | A typo in the provider name. |
| AI keys | `unknown AI provider '...'` | A typo in `-p`, `LODESTAR_PROVIDER` or the `provider` preference: use one of anthropic, openai, gemini, groq, openrouter, mistral, ollama. |
| AI keys | `<provider>: missing <KEY>` | The key is not in the environment, `.env` or the vault: `lodestar keys link <provider>`. |
| AI keys | `<provider>: the model '...' was rejected` | Run `lodestar providers models NAME` and pin one ([Choose models, the default provider and council providers](#choose-models-the-default-provider-and-council-providers)); Lodestar also tries to switch once on its own. |
| AI keys | `provider X is not in council_providers=...` | The default provider is outside your `council_providers` list: add it with `lodestar tools set council_providers ...`, or change the default provider. |
| AI keys | The Getting started banner says "<provider> key failed: ..." | Open Setup, read the detail next to the pill, fix it at the provider, click **Re-check**. |
| AI keys | `local-only preset NOT applied (nothing changed): Ollama is not reachable at localhost:11434 or serves no model.` | Start Ollama, `ollama pull llama3.1`, run `lodestar providers local` again. |
| AI keys | With `LODESTAR_HOME` set, your keys and mailbox show as not linked | Expected: a data folder other than `~/.lodestar` has its own keyring namespace (`lodestar doctor`, `vault namespace` line). Link them again there, or set `LODESTAR_VAULT_SERVICE=lodestar` on purpose to share the default folder's secrets. |
| AI keys | A scratch `LODESTAR_HOME` still shows your keys or mailbox | A `.env` file (current folder, install folder or that data folder) or an environment variable supplies them, or `LODESTAR_VAULT_SERVICE` is set. Remove it for scratch runs. |
| Email | `Set up your Google client first` (or Microsoft) | No sign-in client stored: do the one-time client setup ([Email with Sign in with Google (Gmail)](#email-with-sign-in-with-google-gmail)). |
| Email | `redirect_uri_mismatch` | The Google client is not a Desktop app: create a Desktop app client (Google step 4). |
| Email | `access_denied`, "Access blocked: app has not completed the Google verification process" | Not a test user, or you cancelled: add yourself as a test user or publish the app (Google steps 5, 6). |
| Email | `invalid_client` | Client ID or secret pasted wrong: paste them again. |
| Email | `client_secret is missing` | Google wants the secret too: set up the client again, with the secret. |
| Email | `org_internal`, `admin_policy_enforced` | Your Google Workspace admin blocks the app: ask them, or use an app password if allowed. |
| Email | `AADSTS50011` | Redirect URI missing: add `http://localhost` under Authentication > Mobile and desktop applications. |
| Email | `AADSTS700016`, `unauthorized_client` | Wrong application ID, or the app does not allow this account type: set Supported account types to "Any Entra ID Tenant + Personal Microsoft accounts". |
| Email | `AADSTS65001`, `consent_required` | An admin must approve the app: ask your admin, or use another account. |
| Email | `AADSTS7000218` | Public client flows are off: Authentication > Advanced settings > Allow public client flows: Yes. |
| Email | `Google did not return a refresh token` | An old grant is still in place: remove Lodestar at https://myaccount.google.com/connections, sign in again. |
| Email | `Sign-in timed out after 5 minutes` | The browser step was not finished: click Sign in again. |
| Email | The browser did not open for a sign-in | Use **Open the sign-in page**, or `--no-browser` and open the printed page. |
| Email | Signed in with the wrong account | Disconnect, Sign in again, pick the account. |
| Email | `Sign-in expired: sign in again` | Run `lodestar email signin google` (or `microsoft`) again. The rest of the monitor cycle still runs. |
| Email | Outlook: "User is authenticated but not connected" | IMAP is off in Outlook.com: turn it on (Microsoft step 6), test again. |
| Email | Microsoft 365: 5.7.139, SMTP AUTH disabled | Your organization turned SMTP AUTH off: ask your admin to allow it for your mailbox, or send from another account. |
| Email | "Sign-in was refused. Use an app password, not your normal password." | Normal password used, or a typo: create an app password and paste it again. `lodestar email test` prints a `hint:` line with the cause. |
| Email | "Could not find the server" / "did not answer within 60 s" / "The secure connection failed" | Wrong host, port or security mode, or offline: IMAP 993 with ssl (Proton Bridge: 1143 with starttls); SMTP 465 with ssl or 587 with starttls. |
| Email | "certificate does not match that host name" | The host is typed differently from your provider's list: use the exact host. |
| Email | "IMAP access is turned off for this account" | Turn IMAP on in your mail settings. |
| Email | `IMAP_HOST=... in .env or the environment overrides the ... server` | An old line in `.env`: delete it, restart Lodestar, test again. |
| Email | Getting started still shows an old email problem after a fix | An older check result: any passing test replaces it at once. |
| Email | `email is not connected: Setup > Connect email, or lodestar email connect` | Connect a mailbox first. |
| Email | `tool email_classify is off (lodestar tools enable email_classify)` | Run that command. |
| Email | `not classified '...': ... (will retry)` | No AI provider is working: link a key; the message is picked up on the next scan. |
| Email | `classify failed for '...' (will retry)` | The provider was unreachable: nothing to do, it retries. |
| Email | An expected mail was not picked up | It may not contain a hiring word and not come from a tracked company. Add the job (or set its contact with `lodestar jobs contact`) and scan again with a wider `--days`. |
| Email | `another email run is in progress; skipped` | Two mail scans overlapped: nothing to do, the next cycle runs. |
| Email | Mail is filed under a job but marked unverified and does nothing | By design: a weak tie or failed DKIM/DMARC. Review it; to make a sender trusted, store them as the job's contact. |
| Email | A file cannot be attached | Not in the allowed set, too large, a link, or it names your salary floor: put a pdf/docx/png/jpg in the job's `attach/` folder; edit the floor out. |
| Email | `a mail with attachments always waits in the Inbox for your review` | By design: files leave only after you have seen the mail. Approve it in the Inbox. |
| Email | Approving an email fails | Connect a mailbox (Setup > Connect email); the draft stays in the Inbox so you can copy it. |
| Email | An edited email stays pending: it names your salary floor, or `... clashes with ...` | Remove the figure, or pick another interview slot, and approve again. |
| Email | `emailing the digest needs your own address: connect your mailbox ...` | Connect a mailbox, or set `LODESTAR_NOTIFY_EMAIL`. |
| Profile and documents | `No AI provider configured: Setup > Link an AI key ...` on a document action | Tailoring, cover letters, AI review, adjust, answer drafts, research and Studio requests need a key. Offline: **Build without AI**, `--no-ai` imports, `match`, `resume lint`, `resume audit`. |
| Profile and documents | "PDF import needs pypdf" | `.venv\Scripts\python.exe -m pip install -e ".[pdf]"` in the install folder. |
| Profile and documents | "no text found in ... (a scanned PDF needs OCR first)" | The PDF is an image: import the .docx instead, or run OCR first. |
| Profile and documents | "unsupported resume format" | Use .docx, .pdf, .md or .txt (or a LinkedIn .zip). |
| Profile and documents | "fill in your profile first (Profile tab, or import a resume)", `Created ...profile.md. Fill in your full history there, then rerun.`, or a step's "your master profile is still the template" | Fill in `profile.md` or `lodestar profile import <resume>`; then Retry the step. |
| Profile and documents | The editor's Save is refused: "profile.md changed since you opened it ..." | An import or an AI change wrote profile.md: copy your text, reload the Profile tab and redo your edit (after an AI change, Undo AI changes also lets Save through). |
| Profile and documents | A fact you added to the bank is missing from the master resume | Bank-only facts are used by prompts but not printed: add it to profile.md or click **Rebuild master profile from bank**. |
| Profile and documents | "close master.pdf (open in another program), then Update now" / `<file>.pdf is open in another program` | A PDF or Word window holds the file: close it and try again. |
| Profile and documents | No PDF, only an .html file; `no PDF engine (Edge, Chrome or Chromium) ...`; `edge: no PDF written (exit 0)` | See [PDF engines](#pdf-engines); `lodestar doctor` names the engine it found. Try with Edge closed, or point `LODESTAR_BROWSER` at Chrome. |
| Profile and documents | A build, export or draft is refused because it names your salary floor | Move the figure into Preferences, or remove it in the viewer's **Edit text** panel, and try again. |
| Profile and documents | "add an AI provider to describe changes in words ..." in the Studio | Link a key, or clear the request and use **Build without AI**. |
| Profile and documents | `job #N has no job description` | `lodestar jobs jd N <url or file>`, or drawer > Admin > **set JD**. |
| Profile and documents | JD coverage looks low | Check the job has the full description, and mark keywords you do not have as **not mine** rather than adding them. |
| Search and pipeline | "could not read ..." in a yellow box, or "No job board could be reached ..." | One (or every) free source did not answer: check your connection; the others still count. |
| Search and pipeline | "could not rank: ..." (Search tab) or `not ranked: ...` (`jobs search --rank`) | No working AI provider, or it failed; results are shown unranked. |
| Search and pipeline | No JD coverage chips on search results | Your profile is still the template. |
| Search and pipeline | A saved search shows **last run failed**; a company shows **last read failed** | No source (or the board) answered; it retries next cycle. For a company, check the slug in the board's URL. |
| Search and pipeline | A page watch logs `SKIPPED ... robots.txt does not allow automated fetching` | The site forbids fetching that page: use the Capture bookmarklet there. |
| Search and pipeline | `Lodestar does not fetch pages from <site>` | LinkedIn, Indeed, Glassdoor and ZipRecruiter are never fetched: use the Capture bookmarklet or paste the description. |
| Search and pipeline | `refusing to fetch a non-public address for <host>` | The private-address guard: to watch an intranet careers page on purpose, set `LODESTAR_ALLOW_PRIVATE_URLS=1`. |
| Search and pipeline | `companies add` says "Workday detected" (or Taleo / iCIMS) | Those have no public feed: `lodestar watch add URL` (a page watch). |
| Search and pipeline | Capture says "Lodestar UI not running? ..." | Start Lodestar. If it now runs on another port, drag the bookmarklets again from Setup > Browser bookmarklets. |
| Search and pipeline | Capture or Autofill says "missing or wrong token" | Drag the bookmarklets again from Setup > Browser bookmarklets. Hand-built bookmarklets: [CAPTURE.md](CAPTURE.md). |
| Search and pipeline | Pipeline steps show **blocked** | No AI provider: link a key in Setup. |
| Search and pipeline | **Run next step** is greyed out | Read the reason beside it: usually a question waits (Inbox > Questions for you) or the employer has not replied. |
| Search and pipeline | A step reads **stale** | Something it used changed: Re-run it, or Run to with "include stale steps". |
| Search and pipeline | Autopilot is on but does nothing | Check the budgets in Setup > Autopilot and the loop line for "budget reached"; jobs whose fit check said skip are left alone. |
| Search and pipeline | `auto_track_min_score must be between 0 and 100` (or another range) | The value is outside the allowed range: use one inside it. |
| Mail and people | Follow-up drafts never appear | The job needs a contact address (`lodestar jobs contact`), and only one follow-up per job waits at a time. |
| Mail and people | `no kept options for this draft: run the same command with --options first` | `--pick` needs the same arguments as the earlier `--options` run. |
| Mail and people | `rewriting needs an AI provider: ...` | Link a key; plain templates exist for follow-up, thank-you, withdrawal, check-in, referral and counter-offer. |
| Mail and people | A LinkedIn connections import adds nothing | Choose the zip or `Connections.csv`, not `Profile.csv`. Missing emails are normal. |
| Mail and people | Desktop notifications do not appear ("this computer did not accept the notification") | Windows: Settings > System > Notifications. Linux: install your distribution's notify-send package. |
| Developers | Unit test fails: `update the test count in CLAUDE.md` | Set the number in `CLAUDE.md` to the new count. |
| Developers | `test_feature_matrix` fails | A test is not named in `docs/TESTS.md`, a named test does not exist, or a row or Planned ID was removed ([The test matrix (docs/TESTS.md) and its guard](#the-test-matrix-docstestsmd-and-its-guard)). |
| Developers | `test_pass17_viewer.RealEdge` fails with `no PDF written (exit 0)` | Seen when the suite runs inside a restricted or sandboxed shell; run it from a normal PowerShell window. |
| Developers | A test passes alone but fails in the full run | A monkeypatched module attribute was not restored: restore it in a `finally` block. |
| Developers | E2E suite skips: `playwright is not installed` | `.venv\Scripts\python.exe -m pip install -e ".[e2e]"`. |
| Developers | E2E suite skips: `no msedge browser for Playwright` | `$env:LODESTAR_E2E_BROWSER = "chromium"` plus `.venv\Scripts\python.exe -m playwright install chromium`. |
| Developers | An E2E test fails on a console error | Open the screenshot and HTML in `tests/e2e/_artifacts/`, then rerun headed. |
| Developers | CI fails at pyflakes | Run `.venv\Scripts\python.exe -m pyflakes lodestar tests` locally and fix each line. |
| Developers | `graphify query` exits with code 3 or 4 | The name is ambiguous (3) or matches nothing (4): use `path::symbol` from the listed candidates, or other words. |
| Developers | `GRAPH_REPORT.md` is built from an older commit | The graph is stale: `graphify update .`. |

## Coming later

These are planned but not built yet. They are not in the app today and nothing in this guide depends on them
([TESTS.md](TESTS.md) lists them under Planned):

- An AI apply agent that works with your job-site accounts. Until then you always apply yourself.
