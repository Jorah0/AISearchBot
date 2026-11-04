# Lodestar: full rundown

lodestar is a local, AI-assisted job-search operations tool. One Python package, one CLI, one local web UI,
one SQLite file. Nothing leaves your machine except the API calls you configure (AI providers, IMAP, job APIs).

## 1. What it is made of

| Layer | Module | Responsibility | Depends on |
|---|---|---|---|
| Config | `lodestar/config.py` | `~/.lodestar/` paths, `.env` loading, setting lookup (env > vault > default) | stdlib |
| Secrets | `lodestar/vault.py` | OS keyring store for API keys, mail creds, site logins; name index only on disk | `keyring` |
| AI | `lodestar/ai.py` | `chat()`, `ask()`, `ask_json()` over Anthropic + every OpenAI-compatible API; `council()` pools providers and synthesizes | urllib |
| Data | `lodestar/db.py` | jobs, events, watches, seen-keys; status pipeline; stats; follow-up query; thread-local connections | sqlite3 |
| Documents | `lodestar/resume.py` | master profile, per-job tailoring, cover letter, ATS gap JSON, review, Markdown to .docx | `python-docx` |
| Inbox | `lodestar/email_monitor.py` | IMAP scan, keyword prefilter, AI classification, status upgrade rules, auto-created jobs, reply drafts | imaplib |
| Web | `lodestar/web_monitor.py` | career-page diffs with keyword filter; Remotive / Arbeitnow / RemoteOK search; AI fit ranking | urllib |
| Interview | `lodestar/interview.py` | prep pack (questions, STAR answers, pitch, negotiation); mock-interview REPL | ai |
| CLI | `lodestar/cli.py` | argparse front end, `run` scheduler loop, `chat` coach, `ui` launcher | all |
| UI | `lodestar/web.py` + `lodestar/static/index.html` | localhost dashboard; long actions run as background tasks and are polled | http.server |

Data layout on disk:

```
~/.lodestar/
  profile.md                 master resume (you edit; everything else derives from it)
  lodestar.db                  tracker
  applications/<id>-<company>-<title>/   resume.md, resume.docx, cover_letter.md, gap.json, interview_prep.md
  snapshots/<watch-id>.txt   last page text per watch (for diffs)
  alerts.log                 everything the monitors flagged
  vault_index.json           names + usernames only; secrets live in the OS keyring
```

## 2. The workflow it supports

1. **Find**: `jobs search` hits three free job APIs, dedupes, filters by must-have keywords, optionally AI-ranks
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

`lodestar ui` serves a dashboard on `http://127.0.0.1:8765` (localhost only, no auth, so do not expose it).

- **Board**: kanban by status, orange edge on anything quiet 7+ days, add a job from a URL or pasted text.
  Click a card: timeline, job description, generated documents as tabs, status dropdown, notes, and one-click
  gap / tailor / cover / prep / draft-reply with a council toggle.
- **Search**: free-API search with keyword filter and AI ranking, "track" button saves a listing with its description.
- **Monitor**: watches (URL or saved search), run watches, check email, email dry-run, live alert log.
- **Profile**: edit the master resume in place, AI review button.
- **Coach**: chat with profile and tracker context, council mode.
- **Setup**: provider readiness, provider test, keyring vault entry form.

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

## 6. Verified state (2026-11-04, seventh pass: coverage and analytics)

- Three more keyless job sources (Hacker News Who is hiring via Algolia, Jobicy, The Muse), URL de-duplication on
  add/capture, a conversion funnel with median days per stage and outcomes by source (`jobs funnel`, Board header),
  interview reminders 48 hours ahead from the calendar files, application packet zips, pay figures extracted from
  postings into the gap check, per-ATS autofill selectors. 34 tests.

## 6a. Verified state (2026-11-04, sixth pass: hardening)

- 26 offline tests pass. Fixed: cross-origin access to the local API (per-launch token, CORS only on the two
  bookmarklet routes), lost mail on classification failure, substring company matches, scheduler command that
  depended on `VIRTUAL_ENV`, deprecated UTC calls. Added: rotating log file, task-table pruning, stale Obsidian notes
  removed, chunked ranking, council allowlist and default-provider preference, token usage accounting, model
  discovery with a clear wrong-model error, ATS-aware autofill matching, backup and export commands with a nightly
  backup tool, accessibility attributes and focus handling, mock interview and dictation in the UI, local-only
  preset, version 0.2.0, CI workflow, unix installer.
- Verified live: 403 without token, 200 with token, CSRF-style approve blocked, bookmarklet routes still work
  cross-origin, no CORS headers on private routes.

## 6a. Verified state (2026-11-03, fifth pass: Lodestar rename + UI overhaul)

- Full rename: package and CLI `lodestar` (`jobbot` kept as an alias), data in `~/.lodestar` (an existing `~/.jobbot`
  is copied over on first run), `LODESTAR_*` env vars (`JOBBOT_HOME` still honoured), keyring service `lodestar`
  (old secrets are read and copied transparently), scheduled task and shortcuts renamed, docs and tests rewritten.
- UI overhaul: sidebar navigation with inbox badge, top bar with stats and quick actions, status-coloured board,
  right-hand job drawer with grouped actions (Documents / Communicate / Schedule and decide / Admin), inline offer
  form, loading states on every AI button, empty states, toasts with severity, Esc to close, responsive under 900px.
  Markup, styles and script split into `index.html`, `app.css`, `app.js`; one `/static/<file>` route with a
  traversal guard. Verified: JS syntax, all routes, 18 tests.
- Still not exercised with real credentials: live AI calls and SMTP sending.

## 6a. Verified state (2026-11-03, fourth pass: idea crafting + lifecycle gaps)

- 18 offline tests pass. New: idea-crafting engine (`ideas.py`: diverge across providers or one provider plus a
  critic pass, converge, score impact x fit / effort, refine with history, status tracking) with ten preset topics;
  company research pack; autofill-not-submit bookmarklet (`/api/autofill`); docx template hook; `lodestar features`
  self-generating inventory (`docs/FEATURES.md`); Ideas tab in the UI.
- Verified live: autofill data route, ideas status and delete endpoints, craft error path without a provider.

## 6a. Verified state (2026-11-03, third pass: automation with approvals)

- 16 offline tests pass. New in this pass: per-tool switches (`settings.py`), the approvals inbox with the only
  executors that send mail / move status / add jobs (`approvals.py`), reply drafting for confirmations, assessments,
  interview invites (slot acceptance from your availability, .ics on send) and offers (never accepts or names a number),
  recruiter contact capture, follow-up and thank-you drafts, answer bank + form-question answering, per-job checklist,
  offer evaluation, AI triage of new listings, Inbox / Tools / Answers tabs in the UI, `docs/AUTOMATION.md`.
- Verified live through the UI: tool toggles, preferences, answer bank, checklist task, propose -> inbox -> approve.
- Verified offline with a faked model: an interview email from a human sender captures the contact, leaves the status
  untouched while `email_classify` is manual, and queues one `set_status` and one `send_email` proposal carrying the
  chosen slot and In-Reply-To; a no-reply sender gets neither contact nor reply.
- Still not exercised with real credentials: live AI calls and SMTP sending.

## 6b. Verified state (2026-11-03, second pass)

- 12 offline tests pass. Added since the first pass: browser capture endpoint with CORS and title splitting,
  resume-variant hashing + `lodestar variants`, interview `.ics` files (auto-created from interview mail with a date),
  outreach drafts, weekly digest, Obsidian mirror of the tracker (`lodestar export obsidian`), scheduled-task installer,
  `lodestar app` (loop + UI in one process), one-click `start.bat` / `start.sh`, and `install.bat` / `uninstall.ps1`.
- Installer verified on this machine: `.venv` created, `.env` created, Desktop + Start Menu shortcuts written,
  `lodestar.exe app` launches. The scheduled task and standalone exe are opt-in flags and were not exercised.
- Earlier verified state:

- 9 offline tests pass (`python -m unittest discover -s tests`).
- Live checks passed: job search against the three APIs, page watch baseline and no-change cycle, every UI endpoint
  (add, status, note, detail, background search task, clean no-key error, watches, delete).
- Not yet exercised with real credentials: AI calls (no provider key stored yet) and IMAP (no mail creds stored yet).
  Both paths are covered by request-shape tests with a faked HTTP layer.

## 7. Further tools worth adding (ranked by payoff for interviews)

Done in the second pass: 1 (capture), 3 (outreach), 4 (calendar), 6 (variant tracking), 10 (digest), 12 (Obsidian mirror).
Done in the third pass: approvals + tool switches, auto-replies, scheduling, follow-ups, thank-you, answer bank, checklist, offer evaluation, listing triage.
Done in the fourth pass: idea crafting, company research pack, autofill bookmarklet, docx template, feature inventory. Remaining: compensation data, voice mock interview, local-only preset.

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
