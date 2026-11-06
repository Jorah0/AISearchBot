# Changelog (development passes, newest first)

## Pass 15 (2026-11-06): best-in-class gaps

- Tracker fields: location, workplace (onsite/hybrid/remote), pay range and currency, source, posted date, deadline,
  excitement (1-5), tags, match score, next action and its due date. Filled on add, capture and search-save from what
  the listing carries; old jobs backfilled once (empty fields only, `updated_at` untouched). Validated, whitelisted
  writes through `db.set_fields`, `lodestar jobs set ID key=value`, `POST /api/jobs/ID/fields` and the drawer's
  Details form. The funnel's "by source" now reads the editable source field.
- Board: drag and drop between columns (moving back asks first; `accepted` keeps proposing withdrawals), focusable
  cards, filter bar (text, status, workplace, minimum pay, tag, has deadline), sort (last activity, stalest, match,
  salary, excitement, deadline), Board/Table toggle with sortable headers and bulk status / tag / delete, all
  remembered in localStorage. Cards show stars, pay, match, location and a red deadline chip at 3 days.
- `jobs list` gains `--sort`, `--remote`, `--min-salary`, `--tag` and shows the new fields.
- Today: `lodestar today` and a Today panel on the Board (next actions due or overdue, deadlines within 3 days,
  interviews within 48 h, follow-ups due, Inbox size).
- Desktop notifications (opt-in, default off): daily agenda, interview within 2 hours, deadline tomorrow, each once.
  Windows toast via PowerShell, macOS osascript, Linux notify-send; never raises. Setup has a toggle and a test.
- Offline drafts: follow-up, thank-you and the new withdrawal email fall back to a plain template when no provider
  is configured, still routed through the Inbox; `--template` / a drawer checkbox picks it with a key present. The
  monitor loop now drafts template follow-ups without a provider. Sending a withdrawal moves the job to `withdrawn`.
- Unknown `POST /api/jobs/ID/<op>` operations now return an error instead of a silent ok.
- 12 new tests (`tests/test_pass15_tracker.py`), 104 in total; browser smoke test of drag, table, bulk tag, filters
  and the Details form on a temp home.
- JD coverage engine (`lodestar/ats.py`, lexicon `lodestar/data/skills.json`, ~1,500 terms across 16 fields plus
  certifications, soft skills, degrees and aliases): deterministic score 0-100 by category (hard .45, title .15,
  education .10 only when a degree is named, soft .10, other .20 from repeated posting phrases), word-boundary matching
  that handles c++, c#, .net and node.js, stuffing flags, and per-job "not mine" keywords (`jobs.ats_skip`,
  `POST /api/jobs/ID/skip`). Presented as JD coverage, not an ATS verdict. `lodestar match ID [--file] [--skip]` and a
  Match section in the drawer (score, category bars, keyword table, title and education lines).
- `resume gap` computes coverage first and saves it even without an AI provider or when the AI call fails; the AI gets
  the missing-keyword table and keeps verdict, weak areas and suggestions. `missing_keywords` / `present_keywords` and
  `match_score` in `gap.json` now come from coverage (the AI no longer supplies its own score). `resume tailor`
  re-scores and logs `coverage X -> Y`. The job's match score follows every coverage run.
- Resume lint (`lodestar/lint.py`, `lodestar resume lint [file] [--job ID]`, Check buttons on Profile and in the drawer):
  weak openers, bullets without numbers, pronouns, passive-voice hint, repeated verbs, long/short bullets, cliches,
  missing email/phone/sections, gaps over 6 months as information only. No age or graduation-year heuristics.
  `resume review` passes the lint results to the AI.
- File audit (`lodestar resume audit FILE`, drawer and profile-bank buttons): contact in header/footer, tables, text
  boxes, images, columns, fonts under 10 pt, non-standard headings, scanned or unreadable PDFs, size over 2 MB, odd file
  names, and the plain text a parser sees. Lodestar's own .docx export comes out clean.
- Packaging: `data/*` in package data and `--add-data "lodestar/data;lodestar/data"` in the PyInstaller line.
- 16 new tests (`tests/test_pass15_coverage.py`), 120 in total.
- Bullet-level tailoring: `resume.tailor_bullets` / `apply_bullets`, `lodestar resume tailor ID --bullets` and
  `--accept all|unflagged|1,3,5`, and a "Tailor by bullet" table in the drawer (original | proposed with added keywords
  highlighted | accept). One AI call; deterministic "unsupported" (added keyword not in profile or bank) and "new
  number" flags; flagged rows start rejected. Proposals in `bullets.json`; building writes `resume.md` through the
  tailoring save path (history kept, `.docx` regenerated), re-scores coverage and logs the delta. Whole-document tailor
  unchanged.
- Tailoring can start from a saved resume in the profile bank (`--base RID`, "tailor from" select); `profile show`
  now prints each saved resume's id.
- Resume styles `classic` (default, the previous look), `modern`, `compact` (preference `resume_style`, validated;
  selects in the drawer and Tools > Preferences); each passes the file audit.
- PDF export (`lodestar resume export ID --pdf`, drawer "Export PDF"): Microsoft Word over COM, else LibreOffice, else
  an HTML print page opened in the system browser; reports which one ran. `resume export` now takes a job id too.
- 8 new tests (`tests/test_pass15_bullets.py`), 128 in total; browser smoke test of the bullet table, Build and Export
  PDF on a temp home.
- Review fixes. Bullet tailoring works from a saved `.docx` (the importer now keeps Title/Heading N as `#` and list
  paragraphs as `-` bullets; re-importing the same file refreshes its text) and from PDF text with `•`-style marks and bare
  section names. Reordering never moves a bullet to another employer: bold or plain role lines between bullets start
  a new group. The "unsupported" flag also covers any hard skill, certification or degree the rewrite adds, not just
  posting keywords. Preferences headings at any level or case are kept out of employer text, and a bullet build that
  still names a salary floor stops. Coverage is saved to `coverage.json` (gap.json is the gap check's: "Fit checked"
  no longer ticks from coverage alone; an existing gap.json's keyword lists are refreshed on re-score). `$120-150k`
  parses as 120,000-150,000. "Hybrid cloud" no longer marks a job hybrid. Tracker field writes, match score and "not
  mine" leave `updated_at` alone. `resume export ID` without a tailored resume prints a message, not a traceback.
  UI: Save details no longer writes back a stale match score after Compute or "not mine"; Search "track" sends the
  listing's location and date; the drawer status select needs "move" (arrow keys fired a change per step) and
  marking a job accepted asks first. 9 new tests (`tests/test_pass15_fixes.py`), 137 in total.

## Pass 14 (2026-11-06): gap audit, CLI features in the UI, docs caught up

- New status `accepted` (after offer): accepting a job proposes withdrawing your other open applications, always
  through the Inbox. Stats, variants and the funnel count it as a positive outcome.
- Mail you send yourself goes through the Inbox too: Draft reply and email outreach are proposed to the job's contact
  like follow-ups, and always wait for review even when `email_reply` is on auto (the Inbox label names the real
  recipient, since an outreach note may be written for someone else). Set the contact in the job drawer. The checklist counts a follow-up or thank-you as done only once
  it is sent, not when drafted.
- Interviews: a mail with only a date (often a reply-by date) no longer writes an .ics at midnight; the date goes on
  the timeline. Interview prep quotes real pay figures (posting, your market range, your private floor) and uses the
  research pack and gap check. Mock interviews save the transcript and debrief to `mock_interview.md`; in the Coach
  tab they can speak the questions aloud.
- Offers: each `offer.md` opens with its terms line, and evaluating one offer now weighs it against the others.
- `followup_days` drives the Board, digest, loop and `jobs followups` (`--followup` / `--days` still override).
- Listing salaries are kept on saved jobs, so the gap check sees them.
- UI: upcoming interviews and an empty-board hint on the Board; cover letter tone, length and .docx; .ics from
  the drawer; editable non-mail Inbox payloads (JSON); "Auto-track strong fits" on Search; Email digest; idea count;
  answer tags; certifications in the profile bank; offline-only imports; review of an open document; Setup gets
  List models, Local only (Ollama), Market rates, a 30-day usage line, vault removal, Export CSV and Open exports.
- `providers local` pins a model Ollama actually serves. `tools set models provider=model` is validated. `vault rm`
  also removes the old `jobbot` copy.
- Docs: CAPTURE.md shows the token-carrying bookmarklet and documents autofill; RUNDOWN lists all modules, all ten
  tabs and the shipped roadmap; COMMANDS documents the API token, every background action, `/api/open_folder`,
  `/api/comp` and all preferences; SETUP lists every data file and installer flag; AUTOMATION describes the pass-13
  mail trust rules; FEATURES.md regenerated (now with `lodestar profile`).
- Found by the review of this pass and fixed: Review in the drawer is limited to resumes (its prompt is
  resume-specific) and an empty text is an error instead of silently reviewing profile.md; `jobs followups` prints
  the real day count; Setup, onboarding and doctor use the same "profile filled in" rule as prompts, so a short real
  profile no longer keeps the Getting started banner up. Browser smoke test of Board, Coach, Setup and the drawer.
  92 tests.

## Pass 13 (2026-11-06): the faults pass 12 left open

- Private preferences: `candidate_text(private=False)` drops the Preferences section (salary floor, deal-breakers)
  from everything an employer reads: tailored resume, cover letter, outreach, follow-up and thank-you mail, email
  replies, form answers. The gap check gets the preferences as a separate private block, so it still weighs the floor
  after a tailored resume exists. Ranking, offer review, interview prep, research, ideas and coach keep them.
- Mail trust: a job is matched to an email by its stored contact address, then by the sender's company domain
  (`careers.acme.com` -> Acme), and only then by the company name the classifier read. Only the first two can act
  without review. Free-mail senders (gmail.com, outlook.com, ...) are trusted only when they are the job's exact stored
  contact; they never become a contact on their own, and outreach from them (or unauthenticated outreach) waits in
  the inbox instead of creating a job.
- Inbox items left `running` by a crash are closed as `error` ("interrupted: check before redoing") after 30 minutes,
  never re-run automatically (the mail may already have gone). The claim time is stored in `decided_at`.
- Schema migration: a column added by another thread or process between the check and the ALTER is ignored.

## Pass 12 (2026-11-05): profile bank, LinkedIn import, design-review fixes

- Profile bank (`lodestar/profile.py`): every imported resume is kept; contact, skills, spoken languages, roles,
  education, certifications and projects are pooled in `profile.json` with their sources. AI extraction with an
  offline parser fallback. LinkedIn: profile URL, "Download your data" zip (profile CSVs only), "Save to PDF".
  `lodestar profile ...`, Profile bank panel, doctor line, autofill falls back to bank contact details.
- Prompts read `candidate_text()`: the master plus bank facts it omits, fitted by whole sections. The old
  `profile_text()[:N]` cut the Preferences section out of ranking and reply prompts. A template master never reaches
  a prompt (the bank stands in, or the feature stops with a clear message).
- Design review (6 dimensions, 42 confirmed findings, about 20 distinct) and fixes: the monitor loop no longer dies
  silently on SystemExit from the AI layer (per-step guards, `last_error` in the top bar, `running` reset); IMAP and
  SMTP verify TLS certificates; a cross-process lock stops duplicate mail scans; unauthenticated senders no longer
  become a job's contact; watch listings are marked seen only after judgement and manual searches mark nothing;
  truncated AI replies raise instead of being saved; a self-healed model is remembered only after it answers;
  settings.json writes are atomic and locked; profile.md writes are snapshotted; regenerated job documents keep the
  previous version; backups snapshot SQLite with the online backup API; the capture token persists across restarts;
  the page cannot be framed; the public autofill route no longer returns the answer bank; search-result XSS fixed;
  inbox draft edits survive the refresh; drafted answers show on the Answers tab; council chat keeps the coach
  context; merge uses the editor text; the .docx is regenerated when an edited document is saved; follow-up cadence
  counts nudges once and proposes the ghosted close-out once; the AI client retries network errors and timeouts.
- Left open here, fixed in pass 13: email-to-job matching by company name only, DKIM trust for free-mail domains,
  private preferences living inside the resume file, inbox items stuck in "running", schema migration race.

## Pass. Verified state (2026-11-04, seventh pass: coverage and analytics)

- Three more keyless job sources (Hacker News Who is hiring via Algolia, Jobicy, The Muse), URL de-duplication on
  add/capture, a conversion funnel with median days per stage and outcomes by source (`jobs funnel`, Board header),
  interview reminders 48 hours ahead from the calendar files, application packet zips, pay figures extracted from
  postings into the gap check, per-ATS autofill selectors. 34 tests.

## Passa. Verified state (2026-11-04, sixth pass: hardening)

- 26 offline tests pass. Fixed: cross-origin access to the local API (per-launch token, CORS only on the two
  bookmarklet routes), lost mail on classification failure, substring company matches, scheduler command that
  depended on `VIRTUAL_ENV`, deprecated UTC calls. Added: rotating log file, task-table pruning, stale Obsidian notes
  removed, chunked ranking, council allowlist and default-provider preference, token usage accounting, model
  discovery with a clear wrong-model error, ATS-aware autofill matching, backup and export commands with a nightly
  backup tool, accessibility attributes and focus handling, mock interview and dictation in the UI, local-only
  preset, version 0.2.0, CI workflow, unix installer.
- Verified live: 403 without token, 200 with token, CSRF-style approve blocked, bookmarklet routes still work
  cross-origin, no CORS headers on private routes.

## Passa. Verified state (2026-11-03, fifth pass: Lodestar rename + UI overhaul)

- Full rename: package and CLI `lodestar` (`jobbot` kept as an alias), data in `~/.lodestar` (an existing `~/.jobbot`
  is copied over on first run), `LODESTAR_*` env vars (`JOBBOT_HOME` still honoured), keyring service `lodestar`
  (old secrets are read and copied transparently), scheduled task and shortcuts renamed, docs and tests rewritten.
- UI overhaul: sidebar navigation with inbox badge, top bar with stats and quick actions, status-coloured board,
  right-hand job drawer with grouped actions (Documents / Communicate / Schedule and decide / Admin), inline offer
  form, loading states on every AI button, empty states, toasts with severity, Esc to close, responsive under 900px.
  Markup, styles and script split into `index.html`, `app.css`, `app.js`; one `/static/<file>` route with a
  traversal guard. Verified: JS syntax, all routes, 18 tests.
- Still not exercised with real credentials: live AI calls and SMTP sending.

## Passa. Verified state (2026-11-03, fourth pass: idea crafting + lifecycle gaps)

- 18 offline tests pass. New: idea-crafting engine (`ideas.py`: diverge across providers or one provider plus a
  critic pass, converge, score impact x fit / effort, refine with history, status tracking) with ten preset topics;
  company research pack; autofill-not-submit bookmarklet (`/api/autofill`); docx template hook; `lodestar features`
  self-generating inventory (`docs/FEATURES.md`); Ideas tab in the UI.
- Verified live: autofill data route, ideas status and delete endpoints, craft error path without a provider.

## Passa. Verified state (2026-11-03, third pass: automation with approvals)

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

## Passb. Verified state (2026-11-03, second pass)

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

