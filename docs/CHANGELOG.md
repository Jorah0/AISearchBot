# Changelog (development passes, newest first)

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

