# Setup

## 0. One-click (Windows)

Double-click `start.bat` (quick run) or `install.bat` (shortcuts too). Both create `.venv`, install Lodestar with the
desktop extras, initialize `~/.lodestar`, and open the desktop window with the monitor loop inside it.
`start.ps1 -Browser` gives the old behaviour (minimized loop + browser tab). Flags via PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1 -NoLoop        # UI only
powershell -ExecutionPolicy Bypass -File start.ps1 -Every 15      # loop every 15 min
powershell -ExecutionPolicy Bypass -File start.ps1 -Browser -NoUI # loop only (-NoUI needs -Browser)
powershell -ExecutionPolicy Bypass -File start.ps1 -Port 8800     # fixed port instead of the first free one
```

macOS / Linux: `./start.sh` (flags `--no-loop`, `--no-ui`, `--every 15`, `--port 8765`) for a quick run, or
`./install.sh [--schedule] [--every 30]` to install: a desktop launcher on Linux (an alias hint on macOS) and, with
`--schedule`, a cron line that runs `lodestar run --once`.

## 1. Master resume

`lodestar init` creates `~/.lodestar/profile.md`. Fill it with everything: every job, every bullet, numbers, projects,
education, certifications, and the Preferences line (target roles, locations, salary floor, deal-breakers).
The Preferences section is private: it feeds ranking, gap, offer review and coaching, but never a resume, letter,
email or form answer.
lodestar never invents facts, so anything not in this file cannot appear in a tailored resume.
You can also edit it in the UI (Profile tab) and get an AI review there.

Faster start: import what you already have. Each import keeps the original file and pools its facts (contact,
skills, spoken languages, roles, education, certifications, projects) in the **profile bank**, tagged with where
they came from. While profile.md is still the template it is written from the bank automatically.

```bash
lodestar profile import ~/Documents/resume.docx      # or .pdf / .md / .txt  (--no-ai: offline parse only)
lodestar profile link https://www.linkedin.com/in/your-name
lodestar profile linkedin ~/Downloads/Basic_LinkedInDataExport.zip   # or the profile's "Save to PDF"
lodestar profile show                                 # what the bank holds
lodestar profile add skills "Terraform" --detail Tools
lodestar profile rebuild                              # regenerate profile.md from the bank (old copy kept)
```

LinkedIn: its API does not give third-party apps your positions or skills, and scraping profiles breaks its terms, so
Lodestar uses what LinkedIn hands you. Request **Settings → Data privacy → Get a copy of your data**
(<https://www.linkedin.com/mypreferences/d/download-my-data>); the basic archive arrives in minutes. Only profile facts
are read from it (Profile, Positions, Skills, Languages, Education, Certifications, Projects, email, phone); the
archive itself, with messages and connections, is never stored.

Prompts read the master profile plus any bank facts it does not mention yet, fitted to each prompt's budget by whole
sections (contact, summary, skills, languages and preferences first). Every save of profile.md keeps the previous
version in `profile-history/`.

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

Create an **app password** with your provider (Gmail: turn on 2-Step Verification, then
https://myaccount.google.com/apppasswords), then use Setup > **Connect email** in the app, or:

```powershell
lodestar email connect --user you@example.com    # preset guessed from the address; app password prompted, hidden
lodestar email test-send                         # a test email to yourself
lodestar email check --days 7 --dry
```

Presets: Gmail, Yahoo, iCloud (SMTP starttls on 587), Fastmail, Zoho, AOL, or Custom with your own hosts and ports.
Outlook, Hotmail and Microsoft 365 are not supported: Microsoft accepts only OAuth sign-in for IMAP and SMTP. The
provider table is in [COMMANDS.md](COMMANDS.md#connect-your-email). To be emailed about alerts and digests, set
`LODESTAR_NOTIFY_EMAIL` (sent from the connected mailbox).

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
~/.lodestar/profile.json          profile bank: pooled facts with their sources
~/.lodestar/resumes/              every imported resume (original + extracted text; LinkedIn zips as parsed facts only)
~/.lodestar/profile-history/      profile.md before each overwrite (last 30)
~/.lodestar/lodestar.db             tracker
~/.lodestar/applications/<id>-…/  resume.md/.docx, cover_letter.md, gap.json, interview_prep.md, interview-*.ics
                                  history/ keeps a regenerated document's previous version
~/.lodestar/capture.token         bookmarklet token (delete to revoke; bookmarklets then need re-dragging)
~/.lodestar/alerts.log            monitor output
~/.lodestar/settings.json         tool switches and preferences
~/.lodestar/comp.json             your market-rate table
~/.lodestar/usage.jsonl           tokens per AI call
~/.lodestar/lodestar.log          rotating log (2 MB x 3)
~/.lodestar/backups/              nightly zips (last 7)
~/.lodestar/exports/              JSON / CSV dumps, job packets
~/.lodestar/snapshots/            last page text per watch (for diffs)
~/.lodestar/vault_index.json      secret names and usernames only; secrets live in the OS keyring
~/.lodestar/template.docx         optional: styles for .docx export
~/.lodestar/.env                  optional: setting overrides
<vault>/jobs/                   Obsidian mirror of the tracker
```

Override the data dir with `LODESTAR_HOME`. The repo's `.gitignore` already excludes all of these names.
