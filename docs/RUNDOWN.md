# Lodestar: full rundown

lodestar is a local, AI-assisted job-search operations tool. One Python package, one CLI, one local web UI,
one SQLite file. Nothing leaves your machine except the API calls you configure (AI providers, IMAP, job APIs).

## 1. What it is made of

| Layer | Module | Responsibility | Depends on |
|---|---|---|---|
| Config | `lodestar/config.py` | `~/.lodestar/` paths, `.env` loading, setting lookup (env > vault > default) | stdlib |
| Secrets | `lodestar/vault.py` | OS keyring store for API keys, mail creds, site logins; name index only on disk | `keyring` |
| AI | `lodestar/ai.py` | `chat()`, `ask()`, `ask_json()` over Anthropic + every OpenAI-compatible API; `council()` pools providers and synthesizes | urllib |
| Data | `lodestar/db.py` | jobs (with validated tracker fields), events, watches, companies, contacts, interview rounds, offers, mail (deduped by Message-ID), seen-keys; status pipeline; stats; funnel; thread-local connections | sqlite3 |
| Documents | `lodestar/resume.py` | master profile, per-job tailoring (bullet by bullet), cover letter, gap JSON, review, salary parsing, Markdown to .docx / PDF | `python-docx` |
| Resume studio | `lodestar/studio.py` | the profile-synced master resume (offline, debounced), and AI-planned resume versions that cite profile facts by id (every AI rewrite through `resume.check_rewrite`), page limit, versions, Use for this job | ai, render |
| Rendering | `lodestar/render.py` | one block list per document -> the HTML page (preview, headless-Edge PDF), python-docx, master-format markdown, ATS text; the style spec | `python-docx` |
| Viewer | `lodestar/viewer.py` | every generated document as pages with a formatting panel, compare, exports; floor and fact guards on export and Save | render |
| JD coverage | `lodestar/ats.py` | deterministic keyword coverage of a posting against your resume (`match`), over `data/skills.json`; no AI | stdlib |
| Resume lint | `lodestar/lint.py` | offline resume checks and the saved-file audit (`resume lint`, `resume audit`) | stdlib |
| Inbox | `lodestar/email_monitor.py` | IMAP scan, keyword prefilter, AI classification, sender trust (DKIM + a strong job tie: contact, vouched thread, or the company site held for the job), status upgrade rules, interview rounds from trusted timed invites, contact touches, reply drafts, mail recording and thread linking, Track as new job | imaplib |
| Mail connection | `lodestar/mailconn.py` | provider presets (Gmail, Yahoo, iCloud, Fastmail, Zoho, AOL, Outlook.com and Microsoft 365 by sign-in only, Proton via Bridge with STARTTLS, custom), stored connection, IMAP + SMTP login test with plain hints (every test is recorded for Getting started and doctor), test send to yourself | imaplib, smtplib |
| Sign-in | `lodestar/oauth.py` | Google / Microsoft sign-in with your own client: authorization code + PKCE through a one-shot loopback listener, refresh token in the keyring only, XOAUTH2 for IMAP and SMTP, revoke | urllib, http.server |
| Connections | `lodestar/connections.py` | AI key registry, no-token key checks, stored check results (fingerprints, never keys), the non-blocking startup check | urllib |
| Codes | `lodestar/codes.py` | emailed sign-in codes from DKIM-passing mail, 15 minutes, memory only; masks codes before any AI call | imaplib |
| Attachments | `lodestar/mailfiles.py` | outgoing files only from the job folder's employer-safe set (salary-floor guard, size caps, no links); incoming files saved under the job, never opened | email |
| Drafts | `lodestar/drafts.py` | AI draft options (one call, one recommended), rewrites, picking an option (always proposed for review), suggested emails from the tracker (no AI) | ai, approvals |
| Web | `lodestar/web_monitor.py` | career-page diffs (robots.txt respected); six free job sources (Remotive, Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, The Muse); Greenhouse / Lever / Ashby company boards; search filters, cross-source de-dup, stale signals, H-1B sponsor hints, weekly posting check; AI fit ranking | urllib |
| Interview | `lodestar/interview.py` | interview rounds, question bank (`data/questions.json`), STAR stories, prep pack, mock interview with per-answer scoring | ai |
| Contacts | `lodestar/contacts.py` | contacts CRM: people, job links with a role, LinkedIn connections import, warm paths, touches, referral asks | db |
| Profile bank | `lodestar/profile.py` | saved resumes, every resume section (schema v2), import reviews (new / changed / conflict / duplicate, verified against the file, personal data dropped), LinkedIn import, the structured catalogue, `candidate_text()` for prompts | ai |
| Apply | `lodestar/apply.py` | answer bank drafts, checklist, follow-up, thank-you, offer review, auto-track | ai, approvals |
| Pipeline | `lodestar/pipeline.py` | per-job steps (fit check to close-out) that read earlier outputs, ask once for missing facts, go stale when an input changes, Autopilot with a daily AI budget | ai, approvals |
| Updater | `lodestar/updater.py` | update check / apply with backup, tests and rollback; subprocesses with a timeout | git |
| Approvals | `lodestar/approvals.py` | the Inbox: propose, execute, reject; the only code that acts on Lodestar's initiative | db, settings |
| Settings | `lodestar/settings.py` | tool switches (enabled / auto) and preferences in `settings.json` | stdlib |
| Ideas | `lodestar/ideas.py` | idea crafting: diverge across providers, critique, rank, refine | ai |
| Extras | `lodestar/extras.py` | outreach, .ics, digest, Obsidian export, backup, export (CSV formula-safe), research, packet, autofill data, insights, weekly goals and activity log | ai, db |
| Loop | `lodestar/loop.py` | the monitor cycle behind `run`, `app` and `desktop` (email, watches, company boards, posting check, follow-ups, reminders, backups) and the Today agenda | all |
| Desktop | `lodestar/desktop.py` | native window (Edge WebView2 via pywebview), browser fallback | pywebview |
| Doctor | `lodestar/doctor.py` | install diagnostics (`lodestar doctor`, Setup > Diagnostics) | stdlib |
| Comp | `lodestar/comp.py` | your market-rate table, quoted by gap, offer and prep; offer totals (vesting, cliff) and side-by-side compare | stdlib |
| Inventory | `lodestar/inventory.py` | `lodestar features`: the generated FEATURES.md | argparse |
| Support | `lodestar/log.py`, `lodestar/util.py` | rotating log file; safe URL fetches, source reading, alerts, SMTP sending | stdlib |
| CLI | `lodestar/cli.py` | argparse front end, `chat` coach, `ui` launcher | all |
| UI | `lodestar/web.py` + `lodestar/static/index.html`, `app.js`, `app.css` | localhost dashboard; long actions run as background tasks and are polled | http.server |

Data layout: see [SETUP.md, Where things live](SETUP.md#8-where-things-live).

## 2. The workflow it supports

1. **Find**: `jobs search` hits six free job sources, dedupes, filters by must-have keywords, optionally AI-ranks
   against your profile (0-100 with a one-line reason). `watch search-add` turns a query into a standing alert.
2. **Qualify**: `resume gap` scores the posting like an ATS and a hiring manager: match score, missing keywords,
   weak areas, red flags, verdict apply / stretch / skip. Cheap, so run it before spending effort.
3. **Produce**: `resume tailor` rewrites the master resume for the posting without inventing anything (hard rule in
   the system prompt), `resume cover` writes the letter, `--docx` exports an upload-ready file. `--council` runs the
   same prompt through every configured provider and merges the strongest parts.
4. **Apply and track**: `jobs status N applied`. Everything is an event, so the timeline per job is complete.
5. **Monitor**: `email check` classifies replies (interview, rejection, offer, assessment, recruiter outreach) and
   moves the job forward automatically; it never moves a job backward. `watch run` diffs career pages. `run --every 30`
   loops all of it and nudges you about applications that have gone quiet.
6. **Prepare**: `interview prep` builds a pack from the actual posting and your actual history; `interview mock`
   runs a live interview with a scored debrief.
7. **Decide**: `jobs stats` gives response and interview rates so you can see whether the resume or the targeting
   is the problem. `chat` is a coach with the profile and tracker loaded.

## 3. The UI

`lodestar ui` (or the desktop window) serves the dashboard on 127.0.0.1 (port 8765, or the first free port for
`desktop`). Every API call carries a per-launch token and the Host header must be loopback; see
[AUTOMATION.md, Security model](AUTOMATION.md#security-model-of-the-local-ui).

- **Board**: Today panel (due follow-ups, next actions, interviews, contacts to touch), kanban by status with drag
  and drop, filter bar, sort and a Board / Table toggle, orange edge on anything quiet for `followup_days` (default
  7), upcoming interviews, add a job from a URL or pasted text. Click a card: details form (tracker fields),
  timeline, job description, JD coverage, people and warm paths, interview rounds, generated documents as tabs, status
  dropdown, notes, and one-click gap / tailor / cover / prep / draft-reply with a council toggle.
- **Inbox**: approve, edit or reject the actions Lodestar queued on its own.
- **Search**: free-API search with filters (location / remote, minimum pay, posted within, seniority), keyword
  filter, JD coverage, stale and sponsor chips, optional AI ranking; "track" saves a listing with its description;
  "Save as watch" keeps the filters.
- **Monitor**: watches (URL or saved search), watched companies (Greenhouse / Lever / Ashby boards), run watches,
  check email, email dry-run, live alert log.
- **Contacts**: sortable, filterable table of people with a contact drawer (fields, notes, next touch, linked jobs).
- **Insights**: weekly series and rates, weekly goals, offers side by side with a counter-offer draft, activity log
  export (CSV / printable HTML).
- **Ideas**: craft, refine and track ideas across providers.
- **Answers**: application-form answer bank and STAR stories; draft an answer for a job.
- **Coach**: chat with profile and tracker context, council mode; mock interview for a tracked job, with dictation
  and a score card per answer.
- **Profile**: edit the master resume in place, AI review, import, Adjust, profile bank, LinkedIn import.
- **Tools**: per-tool enabled / auto switches and preferences.
- **Setup**: provider readiness and test, model list, local-only preset, keyring vault, market rates, bookmarklets,
  Diagnostics (doctor), Data panel (backup, export, folders).

All AI and network actions run as background tasks (`/api/run/<action>` returns a task id, the page polls
`/api/tasks/<id>`), so the UI stays responsive and a failed provider shows a readable error instead of a hang.

## 4. Multi-AI design

One function, two wire formats. `anthropic` uses the Messages API; everything else (OpenAI, Gemini's OpenAI-compatible
endpoint, Groq, OpenRouter, Mistral, local Ollama) uses chat-completions. Keys resolve from env, then the keyring.
`<PROVIDER>_MODEL` overrides a model, `LODESTAR_PROVIDER` picks the default, otherwise the first configured provider wins.

`council()` is the "pool ideas" primitive: every configured provider answers independently, then the default provider
merges them with instructions to keep the strongest elements and drop contradictions. It is exposed everywhere a
document is produced (`--council`) and as a standalone `council "<question>"` command.

## 5. Safety and privacy choices

- Secrets never touch disk in plain text (OS keyring). `.env` is supported for convenience and git-ignored.
- The resume prompts forbid inventing employers, dates, metrics, or skills. Rephrasing and reordering only.
- Email classification runs only on mail that passes a keyword prefilter or comes from a tracked company, which keeps
  both cost and exposure low. `--dry` shows what would happen without touching the tracker.
- Nothing auto-submits applications. Most job sites forbid it and it measurably lowers response rates.
- The UI binds to 127.0.0.1 only.
- `.gitignore` excludes every personal artifact (profile, database, applications, alerts, snapshots, vault index,
  `.env`) and every development artifact (graph outputs, caches, build dirs), so the repo can be shared safely.

## 6. Current state (2026-11-10, pass 17.1: credential isolation and fixes, after pass 17: resume import, master resume, resume studio, document viewer)

657 offline tests pass (`python -m unittest discover -s tests -p "test_*.py"`), and 157 browser tests pass in Edge
and Chromium (`python -m unittest discover -s tests/e2e -p "e2e_*.py"`); [TESTS.md](TESTS.md) maps every feature to its tests. Live-verified: installer (Desktop shortcuts; the Start Menu folder fix after the overview is checked statically only), desktop window (Edge
WebView2), every UI route with token and Host checks, six free job sources, page watches, Obsidian export. Not yet
exercised with real credentials: AI calls and key checks, Google / Microsoft sign-in, IMAP login and SMTP sending, Proton
Mail Bridge (all tested against faked servers and a fake OAuth server on 127.0.0.1 only). Pass-by-pass history is in [CHANGELOG.md](CHANGELOG.md).

## 7. Roadmap (shipped)

All twelve items below have shipped: 1 capture bookmarklet, 2 autofill bookmarklet, 3 `outreach`, 4 `.ics`, 5 `comp`
market-rate table, 6 `variants`, 7 `template.docx`, 8 `research`, 9 mock interview with dictation (and spoken
questions) in the Coach tab, 10 `digest`, 11 `providers local`, 12 `export obsidian`. Also shipped along the way:
approvals and tool switches, auto-replies, scheduling, follow-ups, thank-you notes, answer bank, checklist, offer
evaluation, listing triage, idea crafting, feature inventory, profile bank. Still open: item 5 fills its table by hand
(`comp set` or Setup > Market rates); nothing pulls ranges from levels.fyi or Glassdoor automatically.

The original proposals, kept for the reasoning:

1. **LinkedIn / Indeed capture via the browser you already use.** Neither has a public API. A tiny bookmarklet or a
   Claude-in-Chrome routine that posts the current page's title, company, and description to `POST /api/jobs` on the
   local UI would close the biggest gap: most real postings live there. Zero scraping risk because it is your own tab.
2. **Application autofill, not auto-submit.** A browser-side form filler fed from `profile.md` (name, links, work
   history, EEO answers) that stops before the submit button. Saves the most minutes per application of anything here.
3. **Recruiter and referral outreach drafts.** `outreach draft --company X --role Y --person "Name, title"` producing a
   short LinkedIn note or email from the tailored resume. Referrals convert several times better than cold applies.
4. **Calendar hooks.** When `email check` classifies an interview with a date, create a calendar event and a prep
   reminder two days before. The Google Calendar connector or an `.ics` file both work; `.ics` needs no auth.
5. **Compensation data.** Pull levels.fyi / Glassdoor-style ranges by title and city into `gap.json` so the verdict
   also reflects pay, and feed the negotiation section of interview prep with real numbers.
6. **Resume A/B tracking.** Hash the tailored resume per application and join it to outcomes in `stats`, so after
   20 applications you know which resume variant actually gets responses.
7. **ATS-safe docx template.** The current exporter is structurally clean but plain. A single `template.docx` with
   named styles (python-docx supports it) gives a better-looking file with no risk to parsing.
8. **Company research pack.** For each interview-stage job: recent news, product, funding, engineering blog, Glassdoor
   themes, pulled by `read_source` and summarized. Pairs with the "questions to ask" section of prep.
9. **Voice mock interview.** Browser speech-to-text in the Coach tab feeding `interview mock`; the hard part of
   interviews is speaking, not typing.
10. **Weekly digest.** A `run` option that emails a Monday summary: new matches, pending follow-ups, interview rate
    trend, and what to do this week. Cheap, keeps momentum.
11. **Local-only mode.** Ollama is already supported; a `lodestar providers --local` preset (model picks + the
    council restricted to local models) gives a zero-cost, zero-data-sharing path for people who want it.
12. **Obsidian mirror of the tracker.** One note per application in the vault with status, timeline, and links to
    the generated documents, so the job hunt sits next to the rest of your knowledge base and is searchable there.

Items 1, 2, and 4 are the ones that most directly raise interview counts; 6 is the one that tells you whether the
rest is working.
