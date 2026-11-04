# Command reference

Global option: `-p/--provider NAME` picks the AI provider for one command (anthropic, openai, gemini, groq, openrouter, mistral, ollama).

## App and automation

| Command | What it does |
|---|---|
| `lodestar app [--every 30] [--port 8765] [--no-loop] [--no-open]` | The workbot: monitor loop in the background + web UI. What the "lodestar" shortcut runs. |
| `lodestar ui [--port] [--no-open]` | Web UI only. |
| `lodestar run [--every 30] [--days 2] [--followup 7] [--no-email] [--once]` | Monitor loop: email check, watches, follow-up nudges. `--once` for schedulers. |
| `lodestar schedule install [--every 30]` / `remove` | Windows scheduled task that runs `run --once`; prints the cron line elsewhere. |
| `lodestar digest [--days 7] [--send]` | Weekly summary with a coach's 5-action plan; `--send` emails it. |
| `lodestar alerts` | Tail of `alerts.log`. |
| `lodestar init` | Create data dir, profile template, database; print next steps. |

## Tracker

| Command | What it does |
|---|---|
| `lodestar jobs add "Company" "Title" [--jd url\|file\|text] [--url] [--notes]` | Track a job; `--jd` URL is fetched and stored as text. |
| `lodestar jobs list [--status S]` | Board as a table. |
| `lodestar jobs show ID` | Fields + full event timeline. |
| `lodestar jobs status ID saved\|applied\|screening\|interview\|offer\|rejected\|withdrawn [--note]` | Move it. `applied` stamps `applied_at`. |
| `lodestar jobs note ID "text"` / `jobs jd ID source` / `jobs rm ID` | Notes, replace description, delete. |
| `lodestar jobs stats` | Counts, response rate, interview rate. |
| `lodestar variants` | Outcomes per tailored-resume variant: which resume gets interviews. |
| `lodestar jobs followups [--days 7]` | Applications quiet for N+ days. |
| `lodestar jobs search "query" [--keywords a,b] [--rank] [--limit 25] [--save 0 3]` | Free job APIs; `--rank` scores fit 0-100 against your profile; `--save` tracks results by index. |
| `lodestar export obsidian [--folder jobs]` | One note per application + index table in your vault. |

## Documents

| Command | What it does |
|---|---|
| `lodestar resume gap ID` | ATS + hiring-manager comparison: score, missing keywords, verdict. Writes `gap.json`. |
| `lodestar resume tailor ID [--council] [--docx]` | Tailored `resume.md` (+ `.docx`); records the variant hash. |
| `lodestar resume cover ID [--council] [--tone "..."]` | Cover letter. |
| `lodestar resume review [file]` | Brutal critique of your master profile or any file. |
| `lodestar resume export file.md` | Markdown to .docx. |
| `lodestar resume profile` | Print the master profile path. |
| `lodestar outreach ID [--person "Name, title"] [--channel linkedin\|email]` | Short note asking for a conversation or referral. |
| `lodestar email reply ID --intent "..."` | Reply draft to the company. |

## Interviews

| Command | What it does |
|---|---|
| `lodestar interview prep ID [--council]` | Prep pack: questions with model answers, STAR stories, gaps, questions to ask, pitch, negotiation. |
| `lodestar interview mock ID` | Live mock interview, one question at a time, scored debrief on `done`. |
| `lodestar ics ID --when "YYYY-MM-DD HH:MM" [--minutes 60]` | Calendar file for the interview plus a prep reminder 2 days before. Email check creates this automatically when an interview mail carries a date. |

## Monitoring

| Command | What it does |
|---|---|
| `lodestar email check [--days 3] [--dry]` | IMAP scan, AI classification, tracker updates, alerts. `--dry` changes nothing. |
| `lodestar watch add URL [--keywords a,b]` | Alert when matching lines appear on a page. |
| `lodestar watch search-add "query" [--keywords]` | Alert on new listings for a query. |
| `lodestar watch list` / `watch rm ID` / `watch run` | Manage and run watches. |

## AI

| Command | What it does |
|---|---|
| `lodestar providers [--test]` | Which providers have keys; `--test` round-trips each. |
| `lodestar ask "prompt" [-p groq]` | One-off question. |
| `lodestar council "prompt" [--all]` | Every provider answers, then one synthesizes the best. |
| `lodestar chat` | Coach with your profile and tracker loaded. |

## Secrets

| Command | What it does |
|---|---|
| `lodestar vault set NAME [value] [--user U]` | Store in the OS keyring (prompts if no value). |
| `lodestar vault get NAME [--show]` / `vault rm NAME` / `vault list` | Read, delete, list names. |

## Web API (for the bookmarklet and your own scripts)

All on `http://127.0.0.1:8765`, JSON in and out, localhost only.

| Route | Purpose |
|---|---|
| `GET /api/state` | jobs, stats, variants, watches, alerts, providers, vault names |
| `GET /api/jobs/ID` | job, events, generated documents |
| `POST /api/jobs` `{company,title,jd,url,notes}` | add |
| `POST /api/capture` `{title,url,desc}` | add from a browser page title (bookmarklet) |
| `POST /api/jobs/ID/status|note|jd|delete` | update |
| `POST /api/watches` `{url,keywords,search}` / `POST /api/watches/ID` | add / remove |
| `GET|POST /api/profile` | read / save the master resume |
| `POST /api/vault` `{name,value,user}` | store a secret |
| `POST /api/run/ACTION` then `GET /api/tasks/ID` | background actions: tailor, cover, gap, prep, review, reply, outreach, ics, email_check, watch_run, search, chat, council, digest, obsidian, providers_test |

## Automation and approvals (see AUTOMATION.md)

| Command | What it does |
|---|---|
| `lodestar tools list` | every automated tool with its enabled / auto switches, plus preferences |
| `lodestar tools enable\|disable\|auto\|manual NAME` | flip a switch |
| `lodestar tools set KEY VALUE` | preferences: name, availability, auto_track_min_score, followup_days, reply_to_confirmations, signature |
| `lodestar inbox [--all] [-v]` | actions waiting for approval (`-v` shows the drafted email / payload) |
| `lodestar approve ID... [--subject] [--body FILE] [--to]` | execute, optionally editing the email first |
| `lodestar reject ID... [--reason]` | discard |
| `lodestar answers list\|add\|rm\|ask ID "question"` | answer bank for application-form questions; `ask` drafts from profile + bank and proposes saving |
| `lodestar jobs contact ID EMAIL [--name]` | recruiter / hiring-manager address used for replies and follow-ups |
| `lodestar jobs checklist ID` | done / next for every stage of this application |
| `lodestar followup ID` | follow-up email draft; sent through the inbox when a contact is known |
| `lodestar thanks ID [--interviewer] [--notes]` | post-interview thank-you note |
| `lodestar offer ID [--salary --bonus --equity --benefits --deadline --notes]` | offer evaluation vs your preferences + negotiation plan (`offer.md`) |
| `lodestar jobs search "q" --auto` | AI-judge results; propose tracking fits at or above `auto_track_min_score` |

Web API additions: `POST /api/approvals/ID/approve {edits}` / `reject`, `POST /api/tools {tool, enabled, auto}`,
`POST /api/prefs {key, value}`, `POST /api/answers {question, answer}` / `POST /api/answers/ID` (delete); actions
`answer`, `checklist`, `followup`, `thanks`, `offer`, `auto_track`. `GET /api/state` now includes `pending`, `decided`,
`tools`, `prefs`, `answers`.

## Idea crafting, research, inventory

| Command | What it does |
|---|---|
| `lodestar ideas topics` | preset topics: strategy, resume, gap, outreach, stories, pivot, questions, negotiation, tools, custom |
| `lodestar ideas craft TOPIC [--job ID] [--role R] [--extra text] [--n 8] [--single]` | diverge across providers (or one + critic), merge, score impact x fit / effort, save |
| `lodestar ideas list [--topic] [--status]` / `show ID` / `rm ID` | browse saved ideas |
| `lodestar ideas refine ID "feedback"` | rewrite one idea with your feedback (history kept) |
| `lodestar ideas status ID new/planned/doing/done/dropped` | turn ideas into a plan |
| `lodestar research ID` | interview research pack from the job page, company site and a web search (`research.md`) |
| `lodestar features [--markdown]` | self-generated inventory of every command, tool, preference, topic (docs/FEATURES.md) |

Web: Ideas tab (craft, status, refine), `GET /api/autofill` (data for the autofill bookmarklet, never submits),
`POST /api/ideas/ID/status` / `delete`; actions `craft`, `refine`, `research`. Drop a styled `template.docx` next to
`profile.md` and `resume export` uses its styles.

## Operations: usage, backup, export, models

| Command | What it does |
|---|---|
| `lodestar usage [--days 30]` | token counts per provider/model from `~/.lodestar/usage.jsonl` (every call is recorded) |
| `lodestar backup [--out DIR] [--keep 7]` | zip of profile, tracker, settings, answers, ideas, documents; the `backup` tool does this nightly |
| `lodestar export json / csv [--out DIR]` | dump jobs, events, answers, ideas, pending |
| `lodestar providers models [NAME...]` | model ids each provider advertises; set `<PROVIDER>_MODEL` from the list |
| `lodestar providers local` | local-only preset: default provider and council restricted to Ollama |
| `lodestar tools set provider NAME` / `council_providers a,b` | default provider and which providers the council / idea crafting may send data to |

Log file: `~/.lodestar/lodestar.log` (rotating, 2 MB x 3) records every command, UI request, alert, and task failure.

## Pipeline analytics and packets (pass 7)

| Command | What it does |
|---|---|
| `lodestar jobs funnel` | stage conversion (applied -> screening -> interview -> offer), median days per stage, where rejections happen, outcomes by source |
| `lodestar jobs packet ID` | one zip with every document, the posting, notes and timeline for an application (`~/.lodestar/exports/`) |

Search now covers six free sources: Remotive, Arbeitnow, RemoteOK, Hacker News "Who is hiring?" (current month),
Jobicy, The Muse. Adding a job with a URL that is already tracked returns the existing card instead of a duplicate.
The gap check records pay figures stated in the posting (`salary_in_posting`) and weighs them against your floor.
The monitor loop reminds you of interviews within 48 hours (from the .ics files it wrote). The autofill bookmarklet
tries Greenhouse, Lever, Workday, Ashby and SmartRecruiters field selectors before falling back to label matching.

## Desktop window

| Command | What it does |
|---|---|
| `lodestar desktop [--port N] [--no-loop] [--every 30] [--no-email]` | native window (Edge WebView2 via pywebview) with the server and monitor loop in the same process; the Desktop shortcut runs this. Falls back to the browser if the window cannot open. |

Install the window dependency with `pip install -e ".[desktop]"` (the installer does this); `.[pdf]` adds PDF resume import.

## Resume import, adjustment, and cover letters (pass 8)

| Command | What it does |
|---|---|
| `lodestar resume import FILE [--merge] [--save]` | bring in an existing .docx / .pdf / .md / .txt resume; `--merge` folds it into the master profile structure with AI; `--save` writes the profile |
| `lodestar resume adjust "instruction" [--job ID] [--doc resume.md\|cover_letter.md] [--save]` | AI-revise the master profile (default) or a job document, keeping every fact; prints unless `--save` |
| `lodestar resume cover ID [--tone ...] [--words 300] [--docx]` | a complete letter: contact block, date, addressee (the job's contact or Hiring Manager), greeting, 3-4 paragraphs built from the tailored resume, gap check and research pack, sign-off; `--docx` exports |

UI: the Profile tab imports a file (preview, then "Merge into my profile" or "Replace"), and has an Adjust box; every
per-job document tab has "Edit document" and an Adjust box; nothing is saved until you click Save.
Web API: `POST /api/upload {name, data(base64)}` -> `{text}`; `POST /api/docs/ID {name, text}` saves one of
resume.md, cover_letter.md, interview_prep.md, research.md, offer.md; actions `adjust`, `merge_profile`.

## Market rates and cadence (pass 8)

| Command | What it does |
|---|---|
| `lodestar comp set "software engineer" austin 130000 170000` | record a market range (city optional; `*` = anywhere); gap checks and offer evaluations quote it |
| `lodestar comp list` / `comp lookup "title" [city]` | inspect the table |

Follow-up cadence: a quiet application is nudged (and drafted, if a contact is known) every `followup_days`; after the
third nudge the loop proposes closing it as ghosted (tool `followup`). Accepted interview slots are checked against
booked interviews; a clash is reported and no calendar file is written. `council_judge` (preference) makes a second
provider audit the council's synthesis.

## Onboarding and health (pass 9)

The Board shows a "Getting started" banner until the master resume is filled in and an AI key is stored (and, optionally,
the inbox is connected); on a fresh install the window opens on Setup once. The top bar reports the monitor loop running
inside the desktop process (interval, last cycle, cycle count) or says when no loop is running. `GET /api/state` now
carries `version`, `setup` {profile_ready, provider_ready, email_ready} and `loop` {running, every, last_cycle, cycles}.

## Self-healing models and the Data panel (pass 10)

If a provider rejects the configured model id, Lodestar fetches the provider's model list, picks the best match from a
preference order (for example `claude-sonnet-5*`, `gpt-5*`, `gemini-2.5-flash*`), saves it under the `models`
preference, and retries once. `lodestar providers --test` prints the model each provider ends up using. An explicit
`<PROVIDER>_MODEL` env setting is never overridden.

Setup now has a Data panel: Backup now, Export JSON, and buttons that open the data, documents and backups folders.
