<p align="center"><img src="assets/lodestar.png" width="112" alt="Lodestar"></p>

# Lodestar

**The star you steer by.** Lodestar is your personal job-search workbot. CLI: `lodestar` (`jobbot` still works as an alias). Tailors resumes and cover letters per job, scores your fit like an ATS, monitors
your inbox for interview / rejection / offer mail and updates a tracker automatically, watches career pages and job
boards, captures postings from your browser, keeps API keys and site passwords in the OS keyring, preps you for
interviews, mirrors everything into Obsidian, and can pool several AI providers together on any task.

## Install (the app)

Double-click **`install.bat`**. It creates `.venv`, installs Lodestar with the desktop extras, creates your data files
in `~/.lodestar`, copies `.env.example` to `.env`, and puts two shortcuts on the Desktop and Start Menu: **Lodestar**
(a native desktop window with the monitor loop running inside it) and **Lodestar monitor** (loop only). The window is
Edge WebView2 via pywebview; if it cannot open, the same UI opens in your browser. Options (`install.ps1`): `-Schedule [-Every 30]` registers a background task that
keeps monitoring even when the app is closed; `-NoShortcuts` skips the shortcuts; `-Exe` builds a standalone
`dist\lodestar.exe`. `uninstall.ps1 [-Purge]` reverses it.

macOS / Linux: `./install.sh [--schedule] [--every 30]` (desktop launcher on Linux, cron line with `--schedule`).
Quick run without installing shortcuts: `start.bat` (or `./start.sh`). Developer install: `pip install -e .`.

Docs: [docs/FEATURES.md](docs/FEATURES.md) (full inventory) · [docs/SETUP.md](docs/SETUP.md) · [docs/AUTOMATION.md](docs/AUTOMATION.md) (tool switches + approvals inbox) · [docs/COMMANDS.md](docs/COMMANDS.md) · [docs/CAPTURE.md](docs/CAPTURE.md) · [docs/RUNDOWN.md](docs/RUNDOWN.md)

Everything lives in `~/.lodestar/` (override with `LODESTAR_HOME`).

## Setup (5 minutes)

1. **Master resume.** Edit `~/.lodestar/profile.md`. Put *everything* in it; lodestar trims per job and never invents facts.
   Faster: `lodestar profile import resume.docx` or `lodestar profile linkedin export.zip`.
2. **At least one AI key** (stored in Windows Credential Manager / Keychain, never on disk):
   ```powershell
   lodestar vault set ANTHROPIC_API_KEY      # prompts, hidden input
   lodestar vault set OPENAI_API_KEY         # optional: more providers = better council
   lodestar vault set GEMINI_API_KEY
   lodestar providers --test
   ```
   Supported: anthropic, openai, gemini, groq, openrouter, mistral, ollama (set `OLLAMA_MODEL`).
   Override models with `<PROVIDER>_MODEL`, pick a default with `LODESTAR_PROVIDER`.
3. **Connect your email** (optional; Gmail, Yahoo, iCloud, Fastmail, Zoho, AOL or a custom server, with an app
   password): Setup > Connect email in the app, or
   ```powershell
   lodestar email connect --user you@example.com    # prompts for the app password, hidden; then tests the login
   lodestar email test-send                         # a test email to yourself
   ```
   Outlook / Microsoft 365 is not supported (Microsoft allows only OAuth sign-in). See docs/COMMANDS.md.
4. **Check the install:** `lodestar doctor` (add `--live` for one real call per provider).

## Daily use

```powershell
# find jobs (free APIs, no keys) and rank them against your profile
lodestar jobs search "python backend" --keywords remote --rank
lodestar jobs search "data engineer" --save 0 3          # add results 0 and 3 to the tracker

# track an application, capture the posting
lodestar jobs add "Acme" "Backend Engineer" --jd https://acme.com/careers/123
lodestar jobs list
lodestar jobs status 1 applied
lodestar jobs show 1

# documents for job #1
lodestar resume gap 1                 # ATS match score, missing keywords, verdict
lodestar resume tailor 1 --docx       # tailored resume -> ~/.lodestar/applications/1-acme-.../resume.md + .docx
lodestar resume cover 1               # cover letter
lodestar resume tailor 1 --council    # ask EVERY configured provider, synthesize the best version
lodestar resume review                # brutal critique of your master resume

# interviews
lodestar interview prep 1             # questions, STAR answers, gaps, questions to ask, pitch
lodestar interview mock 1             # live mock interview with scored debrief

# email
lodestar email check --days 7 --dry   # see what it would classify, change nothing
lodestar email check                  # classify + update tracker + log alerts
lodestar email reply 1 --intent "accept interview, propose Tue/Wed afternoons"

# website + job board monitoring
lodestar watch add https://acme.com/careers --keywords "engineer,python"
lodestar watch search-add "site reliability" --keywords remote
lodestar watch run

# the workbot: loop + UI in one process (what the shortcut runs)
lodestar app
lodestar run --every 30            # loop only
lodestar schedule install          # background task, survives app close
lodestar digest --send             # weekly summary by email
lodestar alerts

# stats and nudges
lodestar jobs stats                   # response rate, interview rate
lodestar variants                     # which resume variant gets interviews
lodestar export obsidian              # tracker -> <vault>/jobs/
lodestar outreach 1 --person "Jane Doe, Eng Manager"
lodestar ics 1 --when "2026-11-12 14:00"
lodestar jobs followups --days 7

# automation with approvals (every automatic AI action waits in the inbox unless its tool is set to auto)
lodestar tools list                   # enable / disable / auto / manual per tool, set availability etc.
lodestar inbox -v                     # replies, status moves, new jobs, answers waiting for you
lodestar approve 12                   # execute (email items can be edited first)
lodestar answers ask 1 "Why do you want to work here?"
lodestar jobs checklist 1 ; lodestar followup 1 ; lodestar thanks 1 --interviewer "Jane" ; lodestar offer 1 --salary 150k

# operations
lodestar usage ; lodestar backup ; lodestar export json ; lodestar providers models

# ideas: brainstorm across every provider, rank, refine, track
lodestar ideas craft strategy          # or resume / gap --role "SRE" / outreach --job 3 / stories / pivot / questions / tools
lodestar ideas refine 4 "cheaper, two weeks max" ; lodestar ideas status 4 doing
lodestar research 3                    # company research pack before an interview

# advice
lodestar chat                         # coach with your profile + tracker loaded
lodestar council "Should I take a contract role while searching?" --all
lodestar ask "Rewrite this bullet: ..." -p groq
```

## Credential vault

```powershell
lodestar vault set linkedin.com --user you@mail.com   # site login
lodestar vault get linkedin.com --show
lodestar vault list
lodestar vault rm linkedin.com
```

Secrets go to the OS keyring; only names and usernames are indexed in `~/.lodestar/vault_index.json`.
Env vars and a `.env` file override the vault for any setting.

## How the pieces fit

Module map (28 modules, what each does): [docs/RUNDOWN.md, section 1](docs/RUNDOWN.md#1-what-it-is-made-of).

Tests (offline): `python -m unittest discover -s tests -v`

## Run it on a schedule (Windows)

```powershell
schtasks /Create /SC MINUTE /MO 30 /TN lodestar /TR "lodestar run --once" /F
```

## Limits worth knowing

- Email classification only sees mail that passes a keyword prefilter or comes from a tracked company, so cost stays low.
- Job APIs are the free, keyless ones. LinkedIn / Indeed have no public API; use the Capture bookmarklet from the Setup tab
  ([docs/CAPTURE.md](docs/CAPTURE.md)) on the posting you have open.
- Nothing auto-submits applications. That is deliberate: most sites ban it and it tanks response rates.

## Web UI

```powershell
lodestar ui            # http://127.0.0.1:8765 (localhost only); --port N, --no-open
```

Today list and board by status (drag and drop, filters, table view), job detail with tracker fields, JD coverage and
one-click gap / tailor / cover / prep, free-API search with filters and AI ranking (six free sources: Remotive,
Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, The Muse) plus watched Greenhouse / Lever / Ashby company boards,
watches and email checks, approvals inbox with unmatched mail (link, track, dismiss), mail filed per job (threaded
replies, trusted / unverified), AI draft options with one recommended and rewrite chips (drawer, Inbox, Answers,
Offers) and suggested emails on Today, contacts with warm paths, interview rounds and a question bank, insights with
weekly goals, offer comparison and an activity log, idea crafting, answer bank and STAR stories, profile editor and
bank, coach chat with a scored mock interview (dictation), tool switches, Connect email (provider presets, login test,
test send), provider and vault setup. Full walkthrough and roadmap: [docs/RUNDOWN.md](docs/RUNDOWN.md).
