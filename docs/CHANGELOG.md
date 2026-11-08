# Changelog (development passes, newest first)

## Pass 16.1 (2026-11-07): full feature overview fixes

Every feature was checked end to end (code read, then driven in the app against faked job boards, AI, IMAP and SMTP).
What was broken or half-done and now works, by area:

**Tracker and sourcing**
- Adding a job whose posting cannot be fetched still adds it (with its link; fetch the description later); a mistyped
  file path is refused instead of being stored as the description.
- Withdrawing, being rejected or accepting closes the follow-up and thank-you emails still waiting in the Inbox.
- Follow-ups: one at a time per job (asking again gives you the waiting one, sending one closes any duplicate), and
  "ghosted" counts only follow-ups that were actually sent.
- Saved searches reuse a board's recent answer instead of asking it again every cycle; a bad `--save` index says so.
- Save as watch on the Search tab no longer wipes a saved search's keywords and filters when its fields are blank; the
  toast says it updated the existing search.
- One unreachable job board no longer marks a whole saved search as "last run failed": the run counts, and the watch
  shows "some boards unreachable".
- Ranking keeps your salary floor out of the prompt, survives odd scores, and an unranked search still prints.
  LinkedIn titles in the current "(3) Role | Company | LinkedIn" form, autofill contact lines in any order, and
  posting checks that never mark an unknown link as withdrawn.

**Profile, resume and AI**
- The salary floor stays out of cover letters, offline drafts and every email or answer an employer reads, at one
  choke point. A counter-offer may now cite a competing offer that happens to equal your floor (the figure you ticked
  is sent by your choice); the ask is still checked.
- Rebuilding the master profile from the bank keeps everything you typed by hand: roles, summary, and education and
  certification lines without a keyword (only a LinkedIn PDF's sidebar is filtered).
- Provider names are checked when you set them (no crash at the next AI call), the allowlist ignores case
  (`Anthropic` = `anthropic`), and the default provider respects it. The local preset changes nothing when Ollama does
  not answer; a council keeps its synthesis when the judge fails.
- Answers can be marked private and never reach an employer prompt or form; an edited answer that names the floor
  stays in the Inbox instead of failing.
- Saving an adjusted resume or a document from the editor keeps the old version in history.

**Mail, people and interviews**
- Short replies from a job's contact or in a thread Lodestar started are scanned; without an AI provider the scan
  files that mail and carries on instead of stopping.
- An interview reply whose chosen slot clashes with another interview is refused before it is sent (it waits in the
  Inbox); accepting the invite's own slot is no clash. A new time moves the pending round instead of adding one.
- Inbox bookkeeping no longer restarts the follow-up clock; referral asks skip the job's own recruiter; mock
  interviews run from the question bank without a provider.
- Connect email warns when an `IMAP_HOST` / `SMTP_HOST` line in `.env` overrides the provider you chose (a Yahoo
  connection logging in to Gmail), and the login hint names that line first.

**Outcomes and platform**
- Email digest goes to `LODESTAR_NOTIFY_EMAIL`, else your connected mailbox, and says where it went; alert emails get
  a one-line subject and a failed send is reported.
- The monitor loop survives every error, skips the mailbox step quietly when none is connected, and shows only current
  problems. Preferences are range-checked; backups keep at least one and never overwrite in the same minute; the
  scheduled task works from the exe build and reads the install folder's `.env`; the installers keep the Start Menu
  folder and check for Python 3.11+.
- The vault trims a pasted key and refuses a blank one (a blank key made a provider look configured);
  `lodestar vault set` with nothing typed prints one line, not a traceback.

**UI**
- Add job refuses an empty card and fills company and title from a link; Esc asks before discarding typed text and Tab
  stays in the drawer; blank notes and an empty profile are refused, and unsaved edits warn before you leave.
- Preferences have labels and help; the master profile editor, Coach and Answers selects have accessible names; the
  narrow layout keeps the nav on one row; one no-key message points to Setup.

Tests: 386 in total (98 new: `tests/test_overview_*.py`, including `test_overview_review.py` for the review findings).

## Pass 16 (2026-11-07): audit fixes, email connection, mail linking, AI options

- Connect email (Setup > Connect email, `lodestar email connect|test|test-send|status|disconnect`): pick Gmail,
  Yahoo, iCloud, Fastmail, Zoho, AOL or a custom server, paste an app password, and Lodestar logs in to IMAP and SMTP
  to check both (it sends nothing) and explains a failure in plain steps (app password and 2-Step Verification, IMAP
  turned off, wrong host, timeout, port or mode). "Send me a test email" only ever writes to your own address.
  Outlook / Hotmail is refused with the reason (Microsoft allows only OAuth sign-in). The password stays in the OS
  keyring and is never returned. Sent mail now carries `Date` and `Message-ID`; doctor shows the mail servers and
  `--live` logs in once each. `.env.example` no longer sets `IMAP_HOST` (it silently overrode a connected provider)
  and backups leave `.env` out.
- Mail linked to jobs: every relevant scanned message and everything Lodestar sends is kept per job (deduped by
  Message-ID) and shown in the job drawer's Mail section, both ways, trusted or unverified. Replies in a thread Lodestar
  started are filed under the right job. Mail no job claims is listed under Inbox > Unmatched mail: Link to job, Track
  as new job, or Dismiss (`lodestar mail list|link|unlink|dismiss`). Deleting a job deletes its mail; exports include
  it.
- AI draft options: Options buttons in the drawer (follow-up, thank-you, withdrawal, offer check-in, outreach,
  referral, counter-offer, cover letter, reply to a mail), on each Inbox email, in Answers and Offers give up to 3
  drafts from one AI call, one recommended with a reason, plus rewrite chips (shorter, warmer, formal, direct, your
  own words). Picking one never sends anything: it waits in the Inbox for review, to the recipient Lodestar already
  knows. Every draft passes the salary-floor guard. Today lists suggested emails (thank-you after a round, follow-up,
  unanswered recruiter mail, offer check-in, referral ask) without an AI call; Dismiss for now hides one for 3 days.
  CLI: `--options` / `--pick N` on followup, thanks, withdraw, outreach and `offers counter`; `lodestar draft options`,
  `draft rewrite`, `suggest`.
- Audit fixes (security): lookalike sender domains (globex-hiring.com, globex.attacker.net) no longer tie mail to a
  company; any heading spelling of Preferences stays private, and employer-facing text that still names the salary
  floor is refused; idea cards can no longer inject markup; the research pack and scheduling replies no longer leak
  the floor or name your other interviews; calendar files escape company names; oversized LinkedIn zips are refused
  before reading; page fetches pin the checked address (no DNS-rebinding to a private address), cap size and total
  time; mail sockets time out.
- Audit fixes (data and tracker): a duplicate contact or story no longer leaves the database locked; a status proposal
  never moves a job that moved since (it closes as stale), and changing a status by hand closes waiting ones; job ids
  are never reused; withdrawn jobs leave Today, clash checks and the activity log; concurrent calendar imports store one
  round; a failed send keeps your edited draft for a retry; a booked round stops follow-up nudges; one person touched
  and mailed counts once; a new or cleared JD rescores the match; unknown ids say "no job #N"; the funnel counts a
  skipped stage as passed; withdrawing a saved job is not an application; blank answers are refused; applied dates use
  your local day.
- Audit fixes (sources and UI): search says which boards could not be reached instead of "nothing found", and
  watches show "last run failed"; AI ranking without a provider says so; a research pack built from no source says it
  is unverified recall and lists what it read; provider tests and council keep going past one rejected model; a missing
  CLI file is one clear line; profile import keeps the name out of location and project bullets as bullets; the closed
  drawer is inert and focus returns; narrow windows keep the top-bar actions; only editable documents offer Edit;
  stored UTC times show in local time.
- Review fixes (mail trust): a domain that only names the company under another suffix (globex.xyz, stripe.xyz) is
  now a weak tie: the mail is filed under the job, but it never becomes the contact, never books a round, and its status
  moves and replies wait for you. A strong tie needs something Lodestar already holds: the stored contact, our own
  thread, or the company site of the job's posting URL (`careers.globex.com` vouches for `globex.com`). Behaviour
  change: recruiter outreach about a company you do not track yet always waits in the Inbox (it no longer creates the
  job on its own) and its sender is not made the contact; mail from the company's domain moves a job unreviewed only
  when the job has a contact or a posting URL on that domain.
- Review fixes (threads): a reply in our thread is trusted only when our mail went to someone already trusted (it
  answered trusted mail, or went to the job's stored contact). Replying to a mail you linked by hand no longer makes
  its sender trusted one message later. A threaded reply on a rejected or withdrawn job is filed but never trusted: no
  round, no calendar file, no reply accepting a slot.
- Review fixes (Inbox and Setup): a reply to unverified mail shows "unverified sender" on its Inbox card, and
  approving it sends the mail only (an offer reply no longer moves the job). The "track this company" proposal and the
  same message under Unmatched mail are tied together: tracking or linking the mail closes the proposal, and approving
  the proposal files the mail, so you never get two copies of a job. Changing the mail address or servers without
  typing a password removes the stored one, so one provider's app password is never sent to another server. A test
  whose sign-in failed reads "Saved, but sign-in failed" instead of "Connected as". Picking Outlook no longer locks the
  address field. The Answers answer box is multi-line, so "Use this" keeps paragraph breaks.
- Tests: 288 in total (103 new this pass) (`tests/test_pass16_audit_a.py`, `test_pass16_audit_b.py`, `test_pass16_email.py`,
  `test_pass16_mail.py`, `test_pass16_drafts.py`, `test_pass16_review.py`); mail servers, keyring and AI are faked, so
  no real IMAP, SMTP or AI call has been made yet. Older trust tests now give the job a posting URL or contact (the new
  rule) and expect untracked-company outreach to wait.

## Pass 15 (2026-11-06): best-in-class gaps

- Review fixes (batch 2): an interview mail with only a date (often a reply-by date) or from an unverified sender no
  longer creates an interview round, so it cannot add a fake "interviewed" line to the activity log or Insights.
  `sponsors import` reads the current USCIS hub export (New Employment / Continuation / Change of Employer / ...
  Approval columns; every "... Approval" column is summed, denials ignored). The weekly posting check reads Greenhouse
  embed links (`token=`) and `/apply` / `/application` links as their posting and never flags a link that names no
  posting. A newly watched company's open roles are a baseline (one summary alert) instead of one alert and AI
  judgement each. The one-time contacts migration runs under `BEGIN IMMEDIATE`, so parallel first connections cannot
  duplicate contacts or fail. Reminder and toast keys include the round's time (a rescheduled round reminds again).
  Cross-source de-dup no longer folds two openings from the same source (or with different ATS ids) into one. Pay
  stated per month / week / day / hour is no longer read as annual (`parse_salary` skips it; min-salary marks it
  unknown). Every CSV export defuses formula cells (`extras.csv_cell`). Saving a blank offer records nothing and
  clearing every field removes the offer. Re-adding a saved search without filter fields keeps its saved filters.
  Behaviour change: the first poll of a watched company no longer alerts each open role (test updated). 3 new
  regression tests and 6 extended; 185 in total.

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
- Company boards: `lodestar companies add|list|rm`, a Companies panel under Monitor and `POST /api/companies`.
  `web_monitor.detect_ats` maps Greenhouse (`boards.` / `job-boards.greenhouse.io`), Lever and Ashby links or
  `vendor:slug` to their documented public JSON feeds; postings become ordinary listings (`source` greenhouse / lever /
  ashby, HTML stripped, pay and posting date kept). The monitor loop reads each board once per cycle; new postings go
  through the saved-search path (one alert, `auto_track` judgement, seen only once judged). Workday, Taleo and iCIMS
  links get a clear "no public feed, use a page watch" message. New table `companies`; jobs gain `ats_feed`.
- Page watches read robots.txt first (once per host per cycle, `urllib.robotparser`); a disallowed page is skipped with
  one alert. Page watches added from the UI must be http(s) URLs.
- Search filters for `jobs search`, saved searches (`watch search-add`, stored in the new `watches.filters` column), the
  Search tab ("Save as watch") and auto-track: location substring or remote, minimum pay (parsed with the existing
  salary parser), posted within N days, seniority from the title. Unknown salary / location / date pass and are
  marked, never dropped. Private dealbreakers (prefs `excluded_companies`, `excluded_title_words`) apply first.
  Cross-source de-dup on normalised company + title + location keeps the richest description and every link. Results
  carry JD coverage against `candidate_text(private=False)` with the top 3 matched / missing terms (skipped for a
  template profile).
- H-1B sponsor hint: `lodestar sponsors import FILE` loads the user-downloaded USCIS H-1B Employer Data Hub export
  (CSV or UTF-16 tab file, old and new column names) into a `sponsors` table per employer and fiscal year; results and
  board cards show "possible H-1B sponsor (N approvals)". `sponsors lookup`, `sponsors clear`. No automatic download.
- Stale / repost signals: `web_monitor.ghost_signals` scores posting age over 30 days, a repost (same company, title
  and location first seen over 21 days ago under another link, new `postings` table), a very short or skill-free
  description, and for board jobs a posting gone from the live feed. "Possibly stale" chip with reasons on results and
  saved board cards; `auto_track` skips listings at 60+. New tool `posting_check`: weekly, saved board jobs are
  re-checked and a vanished posting is proposed for `withdrawn` ("posting removed"), always through the Inbox.
- 13 new tests (`tests/test_pass15_sourcing.py`), 150 in total; all HTTP faked.
- Contacts CRM: new tables `contacts` (name, email, phone, LinkedIn URL, company, position, how met, source, last /
  next touch, notes; email and LinkedIn URL unique) and `job_contacts` (role recruiter / hiring_manager / referrer /
  interviewer / other). One-time migration: each job's stored contact became a contact linked as recruiter; the job
  columns stay and alone drive mail trust. `lodestar contacts add|list|show|edit|rm|import|due|link`, a Contacts tab
  (sortable, filterable table; contact drawer with fields, notes, next touch, linked jobs, recent activity) and
  `GET|POST /api/contacts...`. Setting a job's contact also files the person under Contacts.
- LinkedIn connections import (opt-in, `profile.linkedin_connections`): the export zip or `Connections.csv`, preamble
  skipped; de-dup by LinkedIn URL, then email, then name + company; known contacts only gain blank fields; no next
  touch is set. The profile's LinkedIn import still ignores connections.
- Warm paths: "you know N people here" on board cards, search results (`jobs search` too) and the job drawer, from a
  normalised-company match. The drawer's People section links a contact with a role or drafts **Ask for referral**
  through `extras.outreach` to the contact's own address (Inbox, always reviewed; no address: a LinkedIn note).
  `extras.outreach` and `apply.mail_proposal` take an explicit recipient.
- Touches: any scanned mail from a contact's exact address sets its last touch (mail date); sending an approved email
  to it sets today. Contacts whose next touch has come appear on Today, in `lodestar today`, the daily desktop agenda
  and `contacts due`; nothing is drafted for them. Exports include both new tables.
- A contact never makes mail trusted or becomes a job's contact (tested). `jobs contact` now validates the address.
- Behaviour changes: `state.today` gains `contacts`; JSON / CSV exports gain `contacts` and `job_contacts` (two
  existing tests updated for that).
- 11 new tests (`tests/test_pass15_contacts.py`), 161 in total; mail, AI and HTTP faked.
- Interview rounds: new table `interviews` (job, round, kind phone / technical / onsite / panel / final / other, time,
  interviewers, notes, questions asked one per line, outcome pending / passed / rejected / unknown). `extras.ics`, an
  accepted slot and interview mail with a stated time from a trusted sender record rounds (re-scans add nothing); a
  date-only or unverified mail records only an `interview_date` note. `upcoming_interviews` (Today, reminders, desktop toasts, clash checks) reads the rounds; old calendar
  events are imported once. Drawer section to add / edit / delete rounds; `lodestar interview log|rounds`,
  `POST /api/jobs/ID/rounds`, `POST /api/rounds/ID/edit|delete`.
- Question bank: `lodestar questions [ID]` lists questions logged at the company, then for similar titles, then a
  bundled set of 30 behavioural questions (`lodestar/data/questions.json`). Prep and mock interviews use logged
  questions first.
- STAR stories in the answer bank (new `answers.star` column; `Story: <title>`, tags `story,<competencies>`), ten fixed
  competency tags, a guided form under Answers > Stories, **Save as story** on ideas of the `stories` topic (no second
  drafter), `lodestar stories list|show|add|rm` (`--from-idea`), `POST /api/stories`. The drawer prompts with the
  competencies a posting stresses that no story covers (small keyword table). Prep and mock inject matching stories.
- Mock scoring: per answer one `ai.ask_json` rubric (STAR parts, relevance, specificity 0-2, metrics used, one fix,
  rewrite) plus offline metrics (words, ~140 wpm time vs 60-120 s, repeated words, JD keywords, wpm only from a
  dictation duration; no filler counts). Sessions saved in new table `mock_sessions` with averages; Coach tab cards,
  session summary and an inline SVG trend; `interview mock` prints the card. `mock_interview.md` is still written.
- Behaviour changes: JSON / CSV exports gain `interviews` and `mock_sessions` (export test updated); deleting a job also
  deletes its rounds and mock sessions; the answer bank in the UI no longer lists stories (they have their own view).
- An unauthenticated POST now has its body read before the 403, so Windows no longer resets the connection (a flaky
  failure seen once in the sourcing route test).
- 9 new tests (`tests/test_pass15_interviews.py`), 170 in total; AI faked.
- Insights: `extras.analytics` / `GET /api/analytics` / `lodestar insights`: per-ISO-week applications (jobs entering
  `applied`; auto-tracked saves never), interview rounds, offers, people contacted and mock sessions; response and
  interview rate by source and by match-score band (<40, 40-59, 60-79, 80+); groups under 5 say "not enough data
  yet". Reuses `db.funnel()` and `db.variant_stats()`. New Insights tab with inline SVG bar charts (`<title>` per bar,
  table fallback). No cover-letter or outreach A/B.
- Weekly goals: pref `weekly_goals` (contacts, tailored_applications, mock_sessions, applications), all unset by
  default, validated; progress from this week's events on Insights and in the Friday digest when set.
- Offers: new table `offers` (validated `db.set_offer`; recording one moves the job to `offer`), pure `comp.total`
  (year-1 / 4-year cash and total, equity by year with cliff, match, labelled estimates), `comp.compare` with best per
  row, market range and the gap to the private salary floor (`profile.salary_floor`, shown only in Lodestar's views).
  `apply.offer` reads the structured rows (accepted offers count as live too). Counter-offer `apply.counter`: cites
  the competing figures you tick, AI or offline template, `candidate_text(private=False)`, proposed with
  `review=True`; a test proves the floor never reaches the draft. `lodestar offers [compare|set|counter]`,
  `GET /api/offers`, `POST /api/offers/ID`, run action `counter`.
- Activity log: `extras.activity_log(start, end)` (applied, contacted, followed up, interviewed; only your own
  actions: sent Inbox mail, rounds up to today, touches you record), weekly counts against pref
  `activity_weekly_min`, CSV (formula cells neutralised) and Markdown + printable HTML through `resume.export_html`.
  `lodestar activity`, run action `activity`, a date-range panel on Insights. Labelled a helper report, not a
  compliance claim.
- New table `touches`: the contact touches you record (a last-touch date or "Touched today"), so weekly counts have a
  history; mail touches are not stored there (the sent mail itself is counted).
- Behaviour changes: JSON / CSV exports gain `offers` and `touches` (export test updated); deleting a job deletes its
  offer; a non-numeric value for a whole-number preference is now a clear error instead of a traceback.
- 12 new tests (`tests/test_pass15_insights.py`), 182 in total; AI and HTTP faked.

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

