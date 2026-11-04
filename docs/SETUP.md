# Setup

## 0. One-click (Windows)

Double-click `start.bat` in the project folder. It creates `.venv`, installs lodestar, initializes `~/.lodestar`,
starts the monitor loop minimized, and opens the web UI. Flags via PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1 -NoLoop        # UI only
powershell -ExecutionPolicy Bypass -File start.ps1 -Every 15      # loop every 15 min
```

macOS / Linux: `./start.sh` (flags `--no-loop`, `--no-ui`, `--every 15`, `--port 8765`).

## 1. Master resume

`lodestar init` creates `~/.lodestar/profile.md`. Fill it with everything: every job, every bullet, numbers, projects,
education, certifications, and the Preferences line (target roles, locations, salary floor, deal-breakers).
lodestar never invents facts, so anything not in this file cannot appear in a tailored resume.
You can also edit it in the UI (Profile tab) and get an AI review there.

## 2. AI providers

Store at least one key in the OS keyring (never on disk):

```powershell
lodestar vault set ANTHROPIC_API_KEY
lodestar vault set OPENAI_API_KEY      # optional; more providers make `council` better
lodestar vault set GEMINI_API_KEY
lodestar providers --test
```

| Provider | Key | Notes |
|---|---|---|
| anthropic | ANTHROPIC_API_KEY | default model `claude-sonnet-5-5` |
| openai | OPENAI_API_KEY | |
| gemini | GEMINI_API_KEY | OpenAI-compatible endpoint |
| groq | GROQ_API_KEY | fast, cheap |
| openrouter | OPENROUTER_API_KEY | any model behind one key |
| mistral | MISTRAL_API_KEY | |
| ollama | set `OLLAMA_MODEL=llama3.1` | local, free, private |

`LODESTAR_PROVIDER=groq` picks the default; `<PROVIDER>_MODEL` overrides a model. Either goes in `.env` or the vault.

## 3. Email monitoring (optional)

Gmail: Google Account, Security, 2-Step Verification, App passwords, create one named "lodestar".

```powershell
lodestar vault set IMAP_USER     # your address
lodestar vault set IMAP_PASS     # the app password
lodestar email check --days 7 --dry
```

Other providers: set `IMAP_HOST` in `.env`. To be emailed about alerts and digests, set `LODESTAR_NOTIFY_EMAIL`
(uses the same account over SMTP; `SMTP_HOST` defaults to smtp.gmail.com).

## 4. Automation

Foreground loop: `lodestar run --every 30`. Background forever: `lodestar schedule install --every 30` creates a Windows
scheduled task that runs `lodestar run --once`; `lodestar schedule remove` deletes it. On macOS/Linux the command prints
the cron line to add. `lodestar digest --send` once a week gives you the summary by email.

What the loop is allowed to do on its own is controlled per tool: see [AUTOMATION.md](AUTOMATION.md). By default only
mail classification and calendar files run automatically; replies, follow-ups, new jobs and saved answers wait in the inbox.

## 5. Browser capture (LinkedIn, Indeed, anything)

See [CAPTURE.md](CAPTURE.md): a bookmarklet that sends the page you are looking at straight into the tracker.

## 6. Obsidian

`lodestar export obsidian` writes one note per application plus an index table into `<vault>/jobs/` (vault from
`OBSIDIAN_VAULT`, default `~/Documents/Obsidian Vault`). Re-run any time; notes are regenerated.

## 7. Privacy switches

`lodestar tools set council_providers anthropic` restricts which providers receive your profile during council and
idea crafting; `lodestar providers local` makes everything Ollama-only. `lodestar usage` shows what was sent where.

## 8. Where things live

```
~/.lodestar/profile.md            master resume
~/.lodestar/lodestar.db             tracker
~/.lodestar/applications/<id>-…/  resume.md/.docx, cover_letter.md, gap.json, interview_prep.md, interview-*.ics
~/.lodestar/alerts.log            monitor output
<vault>/jobs/                   Obsidian mirror of the tracker
```

Override the data dir with `LODESTAR_HOME`. The repo's `.gitignore` already excludes all of these names.
