# Command reference

Global option: `-p/--provider NAME` picks the AI provider for one command (anthropic, openai, gemini, groq, openrouter, mistral, ollama).

## App and automation

| Command | What it does |
|---|---|
| `lodestar app [--every 30] [--days 2] [--followup N] [--no-email] [--port 8765] [--no-loop] [--no-open]` | The workbot: monitor loop in the background + web UI. What the "lodestar" shortcut runs. |
| `lodestar ui [--port] [--no-open]` | Web UI only. |
| `lodestar run [--every 30] [--days 2] [--followup N] [--no-email] [--once]` | Monitor loop: email check, watches, follow-up nudges (N defaults to pref `followup_days`). `--once` for schedulers. |
| `lodestar schedule install [--every 30]` / `remove` | Windows scheduled task that runs `run --once`; prints the cron line elsewhere. |
| `lodestar digest [--days 7] [--send]` | Weekly summary with a coach's 5-action plan; `--send` emails it. |
| `lodestar alerts` | Tail of `alerts.log`. |
| `lodestar init` | Create data dir, profile template, database; print next steps. |

## Tracker

| Command | What it does |
|---|---|
| `lodestar jobs add "Company" "Title" [--jd url\|file\|text] [--url] [--notes]` | Track a job; `--jd` URL is fetched and stored as text. |
| `lodestar jobs list [--status S] [--sort match\|salary\|excitement\|deadline\|updated] [--remote onsite\|hybrid\|remote] [--min-salary N] [--tag T]` | Board as a table, with pay, match, excitement, workplace, deadline and tags on each line. `--min-salary` compares the top of the stated range. |
| `lodestar jobs set ID key=value ...` | Tracker fields: `location`, `remote` (onsite/hybrid/remote), `salary_min`, `salary_max` (`120k` works), `currency` (3 letters), `source`, `posted_at`, `deadline`, `next_action_at` (YYYY-MM-DD), `excitement` (1-5), `tags` (comma list), `match_score` (0-100), `next_action`. An empty value clears; a bad value changes nothing. |
| `lodestar today` | Today's agenda: next actions due or overdue, deadlines within 3 days, interviews within 48 h, follow-ups due, Inbox size. The Board shows the same as a Today panel. |
| `lodestar jobs show ID` | Fields + full event timeline. |
| `lodestar jobs status ID saved\|applied\|screening\|interview\|offer\|accepted\|rejected\|withdrawn [--note]` | Move it. `applied` stamps `applied_at`. `accepted` proposes withdrawing your other open applications (Inbox). |
| `lodestar jobs note ID "text"` / `jobs jd ID source` / `jobs rm ID` | Notes, replace description, delete. |
| `lodestar jobs stats` | Counts, response rate, interview rate. |
| `lodestar variants` | Outcomes per tailored-resume variant: which resume gets interviews. |
| `lodestar jobs followups [--days N]` | Applications quiet for N+ days (default: pref `followup_days`). |
| `lodestar jobs search "query" [--keywords a,b] [--rank] [--limit 25] [--save 0 3]` | Free job APIs; `--rank` scores fit 0-100 against your profile; `--save` tracks results by index. |
| `lodestar export obsidian [--folder jobs]` | One note per application + index table in your vault. |

## Documents

| Command | What it does |
|---|---|
| `lodestar resume gap ID` | JD coverage (deterministic, works without AI) plus the AI's verdict, weak areas and suggestions, which see the missing-keyword table. Writes `gap.json` and the job's match score. |
| `lodestar match ID [--file resume.md\|.docx\|.pdf] [--skip TERM]` | JD coverage: which of the posting's keywords your resume mentions, by category, with missing and matched terms. No AI; a tailoring guide, not an ATS verdict. `--skip` marks a keyword "not mine" for this job (again to undo). `--file` scores another file without saving. |
| `lodestar resume tailor ID [--council] [--docx] [--base RID]` | Tailored `resume.md` (+ `.docx`); records the variant hash. `--base` starts from a saved resume in the profile bank (ids: `lodestar profile show`) instead of the master. |
| `lodestar resume tailor ID --bullets [--base RID]` | Per-bullet proposals (one AI call) with no-invention flags, printed numbered and saved to `bullets.json`; `resume.md` is untouched. |
| `lodestar resume tailor ID --accept all\|unflagged\|1,3,5 [--docx]` | Build `resume.md` from `bullets.json`: accepted rows take the proposed text, the rest keep the original. Re-scores coverage and logs the change. |
| `lodestar resume cover ID [--council] [--tone "..."] [--words 300] [--docx]` | A complete letter: contact block, date, addressee (the job's contact or Hiring Manager), greeting, 3-4 paragraphs built from the tailored resume, gap check and research pack, sign-off; `--docx` exports. |
| `lodestar resume review [file]` | Brutal critique of your master profile or any file; the AI is given the lint results. |
| `lodestar resume lint [file] [--job ID]` | Offline line checks: weak openers, bullets without a number, pronouns, passive hint, repeated verbs, long/short bullets, cliches, missing email/phone/sections, employment gaps (info). Default: the master profile. |
| `lodestar resume audit file.docx\|.pdf` | File checks a parser trips on (contact in header/footer, tables, text boxes, images, columns, fonts under 10 pt, non-standard headings, scanned PDFs, size, file name) and the plain text a parser sees. |
| `lodestar resume export ID\|file.md [--pdf] [--style classic\|modern\|compact]` | Markdown (a job id means its `resume.md`) to .docx in the chosen style; `--pdf` converts with Microsoft Word, else LibreOffice, else opens an HTML print page in your browser, and says which it used. |
| `lodestar resume profile` | Print the master profile path. |
| `lodestar outreach ID [--person "Name, title"] [--channel linkedin\|email]` | Short note asking for a conversation or referral. |
| `lodestar email reply ID --intent "..."` | Reply draft to the company. |

## Interviews

| Command | What it does |
|---|---|
| `lodestar interview prep ID [--council]` | Prep pack: questions with model answers, STAR stories, gaps, questions to ask, pitch, negotiation. |
| `lodestar interview mock ID` | Live mock interview, one question at a time, scored debrief on `done`; the transcript and debrief are saved to `mock_interview.md` (also from Coach > Mock interview, which can speak the questions aloud). |
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

## Web API (for the page and the bookmarklets)

All on `http://127.0.0.1:<port>`, JSON in and out. Every route needs the per-launch `X-Lodestar-Token` header that the
page embeds. Outside scripts can only call `/api/capture` and `/api/autofill`, with `?t=<~/.lodestar/capture.token>`.

| Route | Purpose |
|---|---|
| `GET /api/state` | jobs, stats, variants, watches, alerts, providers, vault names |
| `GET /api/jobs/ID` | job, events, generated documents |
| `POST /api/jobs` `{company,title,jd,url,notes,location?,posted_at?}` | add; source, workplace and pay are read from the notes and JD |
| `POST /api/capture` `{title,url,desc}` | add from a browser page title (bookmarklet) |
| `POST /api/jobs/ID/status|note|jd|contact|delete` | update (`contact` takes `{email, name}`) |
| `POST /api/jobs/ID/fields` `{deadline: "2026-12-01", tags: "a,b", ...}` | set tracker fields (same whitelist and validation as `jobs set`; `""` clears) |
| `POST /api/jobs/ID/skip` `{term}` | JD coverage: mark a keyword "not mine" for this job, or unmark it; returns `{coverage}` |
| `POST /api/watches` `{url,keywords,search}` / `POST /api/watches/ID` | add / remove |
| `GET|POST /api/profile` | read / save the master resume |
| `POST /api/vault` `{name,value,user}` / `{name,delete:true}` | store / remove a secret |
| `POST /api/comp` `{op: set\|delete, title, city, low, high}` | edit your market-rate table |
| `POST /api/open_folder` `{which: data\|exports\|backups\|applications\|log}` | reveal a folder in the file manager |
| `POST /api/run/ACTION` then `GET /api/tasks/ID` | background actions: tailor, cover, gap, prep, review, reply, outreach, ics, email_check, watch_run, search, chat, council, digest, obsidian, providers_test, providers_local, models, export (`{fmt: json or csv}`), auto_track, mock (`{messages, id}`), packet, doctor (`{live}`), backup, match (`{id}`), lint (`{text}`), audit (`{id}`, or `{}` for the newest saved resume file) |

## Automation and approvals (see AUTOMATION.md)

| Command | What it does |
|---|---|
| `lodestar tools list` | every automated tool with its enabled / auto switches, plus preferences |
| `lodestar tools enable\|disable\|auto\|manual NAME` | flip a switch |
| `lodestar tools set KEY VALUE` | preferences: name, availability, auto_track_min_score, followup_days, reply_to_confirmations, weekly_target (applications/week, used by idea crafting), provider, council_providers, council_judge, signature, desktop_notifications, models (`provider=model`; also written by self-healing model selection) |
| `lodestar inbox [--all] [-v]` | actions waiting for approval (`-v` shows the drafted email / payload) |
| `lodestar approve ID... [--subject] [--body FILE] [--to]` | execute, optionally editing the email first |
| `lodestar reject ID... [--reason]` | discard |
| `lodestar answers list\|add Q A [--tags t1,t2]\|rm ID\|ask ID "question"` | answer bank for application-form questions; `ask` drafts from profile + bank and proposes saving |
| `lodestar jobs contact ID EMAIL [--name]` | recruiter / hiring-manager address used for replies and follow-ups |
| `lodestar jobs checklist ID` | done / next for every stage of this application |
| `lodestar followup ID [--template]` | follow-up email draft; sent through the inbox when a contact is known |
| `lodestar thanks ID [--interviewer] [--notes] [--template]` | post-interview thank-you note |
| `lodestar withdraw ID [--template]` | withdrawal email; always waits in the inbox, and sending it moves the job to `withdrawn` |
| `lodestar offer ID [--salary --bonus --equity --benefits --deadline --notes]` | offer evaluation vs your preferences + negotiation plan (`offer.md`) |
| `lodestar jobs search "q" --auto` | AI-judge results; propose tracking fits at or above `auto_track_min_score` |

Web API additions: `POST /api/approvals/ID/approve {edits}` / `reject`, `POST /api/tools {tool, enabled, auto}`,
`POST /api/prefs {key, value}`, `POST /api/answers {question, answer, tags}` / `POST /api/answers/ID` (delete); actions
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
| `lodestar providers local` | local-only preset: default provider and council restricted to Ollama, and a model Ollama serves is pinned (UI: Setup > Local only) |
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
| `lodestar desktop [--port N] [--no-loop] [--every 30] [--days 2] [--followup N] [--no-email]` | native window (Edge WebView2 via pywebview) with the server and monitor loop in the same process; the Desktop shortcut runs this. Falls back to the browser if the window cannot open. |

Install the window dependency with `pip install -e ".[desktop]"` (the installer does this); `.[pdf]` adds PDF resume import.

## Resume import, adjustment, and cover letters (pass 8)

| Command | What it does |
|---|---|
| `lodestar resume import FILE [--merge] [--save]` | bring in an existing .docx / .pdf / .md / .txt resume; `--merge` folds it into the master profile structure with AI; `--save` writes the profile |
| `lodestar resume adjust "instruction" [--job ID] [--doc resume.md\|cover_letter.md] [--save]` | AI-revise the master profile (default) or a job document, keeping every fact; prints unless `--save` |

UI: the Profile tab imports a file (preview, then "Merge into my profile" or "Replace"), and has an Adjust box; every
per-job document tab has "Edit document" and an Adjust box; nothing is saved until you click Save.
Web API: `POST /api/upload {name, data(base64)}` -> `{text}`; `POST /api/docs/ID {name, text}` saves one of
resume.md, cover_letter.md, interview_prep.md, research.md, offer.md, mock_interview.md; actions `adjust`, `merge_profile`.

## Market rates and cadence (pass 8)

| Command | What it does |
|---|---|
| `lodestar comp set "software engineer" austin 130000 170000` | record a market range (city optional; `*` = anywhere); gap checks, offer evaluations and interview prep quote it. Also in the UI: Setup > Market rates |
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

Setup now has a Data panel: Backup now, Export JSON, Export CSV, and buttons that open the data, exports, documents
and backups folders.

## Diagnostics (pass 11)

| Command | What it does |
|---|---|
| `lodestar doctor [--live]` | PASS / WARN / FAIL lines for Python version, required and optional modules, WebView2 runtime, keyring backend, data folder, master profile, configured providers (with the model each will use), mail settings, leftover legacy folder; `--live` makes one real call per provider. Exit code 1 when something is broken. |

Setup also has a Diagnostics panel (same checks as `lodestar doctor`, with an optional live AI call) and an
"Open log" button next to the data folders.

## Profile bank and LinkedIn (pass 12)

| Command | What it does |
|---|---|
| `lodestar profile show` | Contact, skills, spoken languages, role/education/certification/project counts, saved resumes |
| `lodestar profile import <file> [--no-ai]` | Keep the original (.docx/.pdf/.md/.txt) in `resumes/`, extract its facts into the bank; fills profile.md if it is still the template |
| `lodestar profile linkedin <export.zip or profile.pdf>` | LinkedIn "Download your data" archive or "Save to PDF"; only profile facts are kept |
| `lodestar profile link <url>` | Store your LinkedIn profile URL (rendered resumes, autofill) |
| `lodestar profile add skills\|languages\|certifications <name> [--detail X]` | Add by hand (category / proficiency / issuer) |
| `lodestar profile remove skills\|languages\|certifications <name>` | Remove from the bank |
| `lodestar profile rebuild` | Regenerate profile.md from the bank; the old file goes to `profile-history/` |

The Profile tab has the same as a "Profile bank" panel: LinkedIn link and import, skill and language chips, saved
resumes, rebuild. Web API: `GET /api/profile/bank`, `POST /api/profile/bank {op: add|remove|contact, ...}`,
`POST /api/run/profile_import {name, data: base64, linkedin?, ai?}`, `POST /api/run/profile_rebuild`.

## Tracker board, Today and notifications (pass 15)

Jobs carry structured fields: location, workplace (onsite / hybrid / remote), pay range and currency, source, posted
and deadline dates, excitement (1-5 stars), tags, a match score (0-100) and a next action with a due date. Adding a
job fills what the listing already carries: pay from a salary line or figure in the JD, workplace from the location
and JD (remote-only job boards count as remote), source from how it was added, location and posting date from a
saved search result. Existing jobs were backfilled once from their notes and JD (only empty fields are written).

Board: drag a card to another column to change its status (moving it back asks first; `accepted` still proposes
withdrawing your other applications, after a confirm). Without a mouse, focus a card and press Enter, then pick a
status in the drawer's select and press "move" (arrowing through the select changes nothing on its own). A filter bar narrows by text, status, workplace, minimum pay, tag and "has deadline", and sorts by last
activity, stalest first, match, salary, excitement or deadline. "Table view" shows a sortable table with checkboxes
for bulk status, add tag and delete. View, sort and filters are remembered by the browser. Cards show stars, pay,
match, location and a deadline chip that turns red three days out. The drawer's Details form edits every field.
The Today panel on top lists overdue and due next actions, deadlines within 3 days, interviews within 48 hours,
follow-ups due and the Inbox count.

Offline drafts: without an AI provider, follow-up, thank-you and withdrawal emails use a plain template filled from
the job and your name (pref `signature` or `name`, else the profile bank), proposed through the Inbox like AI drafts.
Choose it with a key present via `--template` or the "plain template, no AI" box in the drawer. Templates never
include your private preferences.

Desktop notifications (pref `desktop_notifications`, off by default; Setup > Desktop notifications or Tools >
Preferences): while the monitor loop runs, one agenda per day, an interview within 2 hours and a deadline tomorrow,
each shown once. Windows uses a toast (under PowerShell's app identity), macOS `osascript`, Linux `notify-send`;
a system that refuses is silently skipped. Actions: `POST /api/run/withdraw {id, template?}`,
`POST /api/run/notify_test`; `followup` and `thanks` accept `template`. `GET /api/state` includes `today`.

## JD coverage, resume check and file audit (pass 15)

JD coverage (`lodestar match ID`, the drawer's Match section) compares the posting with your current resume (the job's
tailored `resume.md`, else your profile without Preferences) using a lexicon of about 1,500 terms in
`lodestar/data/skills.json`: hard skills across software, data, cloud, security, design, product, marketing, sales,
finance, healthcare, education, operations, HR, legal, trades and customer service, plus certifications, soft skills,
degrees and aliases (`k8s` = Kubernetes, `ms excel` = Excel, `rn` = registered nurse). Categories and weights: hard
skills 45%, job title 15%, education 10% (only when the posting names a degree; a higher degree covers a lower one),
soft skills 10%, other 20% (phrases the posting repeats that the lexicon does not know). An empty category hands its
weight to the rest. Keywords repeated far more often than the posting uses them are flagged as possible stuffing.
Mark a keyword "not mine" to leave it out of the score for that job. The score is saved as the job's match score
and in `coverage.json`; when a gap check has run, its `gap.json` keyword lists follow too (the AI verdict stays as
judged). Tailoring re-scores and logs `coverage 54 -> 78` on the timeline. Computing coverage, "not mine", tags and
other Details fields do not count as the job's last activity. It is a guide for tailoring, not a pass/fail ATS verdict.

Check (`lodestar resume lint`, the Check buttons on Profile and in the drawer) lists line-numbered issues by severity
with a fix hint; the 0-100 score is secondary. Audit (`lodestar resume audit`, "Audit resume.docx" in the drawer,
"Audit latest saved resume file" in the profile bank) inspects the file itself and shows the text a parser would
read. A PDF audit needs the optional `pypdf` for its text checks; without it the size, name and image checks still run.

## Bullet tailoring, resume styles and PDF (pass 15)

"Tailor by bullet" in the drawer (`lodestar resume tailor ID --bullets`) reads the experience and project bullets of
your master profile (or a saved resume chosen under "tailor from" / `--base`; Preferences never included), works out
which of the posting's keywords are missing, and asks the AI once for rewrites that carry them only where the facts
allow, plus a relevance order per role. Two checks then run without AI:

- **unsupported**: a keyword the rewrite adds (a posting keyword, or any hard skill, certification or degree the
  original bullet did not name, declared by the AI or not) that appears nowhere in your profile, the bank's facts or
  the source resume;
- **new number**: a number, percentage or amount the original bullet does not have.

Flagged rows start unchecked. The table shows original | proposed (added keywords highlighted, flags in amber) |
accept; "Accept all unflagged" resets the checks and "Build resume" writes `resume.md` (the previous one moves to
`history/`), regenerates `resume.docx`, re-scores coverage and logs `coverage X -> Y`. Within each role the bullets
follow the suggested order; an accepted "drop" removes the bullet. A role is a `###` heading, a heading deeper than
its section (`# Experience` then `## Engineer - Acme`), or any plain line between bullets (`**Analyst**, Beta`), so a
bullet never moves to another employer. Bullets are lines starting with `-`, `*` or `•`-style marks; a saved `.docx`
keeps its headings and list bullets when imported (one imported before pass 15: import it again), and a PDF's text
works when it keeps its bullet marks. Any Preferences heading (any level, any case) is left out, and a build that
would still contain "Salary floor" stops with a message. The whole-document "Tailor resume" is unchanged.

Styles (preference `resume_style`, the drawer's "style" select or Tools > Preferences): `classic` (the previous look,
Calibri 10.5), `modern` (Arial, navy headings, 0.8" margins), `compact` (Calibri 10, tight spacing, 0.6" margins). All
are single column with no tables, text boxes, headers or footers, and pass the file audit. A `template.docx` beside
`profile.md` still overrides them. "Export PDF" (`lodestar resume export ID --pdf`) uses Microsoft Word over COM
(Windows, 2-minute timeout), else LibreOffice (`soffice --headless`), else writes `resume.html` with print CSS and opens
it in the system browser (also from the desktop window) to print to PDF. `POST /api/run/bullets {id, base?}`,
`/api/run/bullets_apply {id, accept: [ids]}` and `/api/run/export_pdf {id}`; `GET /api/state` includes `bases` (saved
resumes) and `pref_choices`.
