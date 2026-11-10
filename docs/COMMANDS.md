# Command reference

Global option: `-p/--provider NAME` picks the AI provider for one command (anthropic, openai, gemini, groq, openrouter, mistral, ollama).

## App and automation

| Command | What it does |
|---|---|
| `lodestar app [--every 30] [--days 2] [--followup N] [--no-email] [--port 8765] [--no-loop] [--no-open]` | The workbot: monitor loop in the background + web UI. What the "lodestar" shortcut runs. |
| `lodestar ui [--port] [--no-open]` | Web UI only. |
| `lodestar run [--every 30] [--days 2] [--followup N] [--no-email] [--once]` | Monitor loop: email check, watches, follow-up nudges (N defaults to pref `followup_days`). `--once` for schedulers. |
| `lodestar schedule install [--every 30]` / `remove` | Windows scheduled task that runs `run --once`; prints the cron line elsewhere. |
| `lodestar digest [--days 7] [--send]` | Weekly summary with a coach's 5-action plan; `--send` emails it to `LODESTAR_NOTIFY_EMAIL`, else to your connected mailbox address, and says where it went (says so when neither is set). |
| `lodestar alerts` | Tail of `alerts.log`. |
| `lodestar init` | Create data dir, profile template, database; print next steps. |

## Tracker

| Command | What it does |
|---|---|
| `lodestar jobs add "Company" "Title" [--jd url\|file\|text] [--url] [--notes]` | Track a job; `--jd` URL is fetched and stored as text. |
| `lodestar jobs list [--status S] [--sort match\|salary\|excitement\|deadline\|updated] [--remote onsite\|hybrid\|remote] [--min-salary N] [--tag T]` | Board as a table, with pay, match, excitement, workplace, deadline and tags on each line. `--min-salary` compares the top of the stated range; jobs with no pay on file are kept and marked `pay unknown`. |
| `lodestar jobs set ID key=value ...` | Tracker fields: `location`, `remote` (onsite/hybrid/remote), `salary_min`, `salary_max` (`120k` works), `currency` (3 letters), `source`, `posted_at`, `deadline`, `next_action_at` (YYYY-MM-DD), `excitement` (1-5), `tags` (comma list), `match_score` (0-100), `next_action`. An empty value clears; a bad value changes nothing. |
| `lodestar today` | Today's agenda: next actions due or overdue, deadlines within 3 days, interviews within 48 h, follow-ups due, contacts whose next touch has come, suggested emails, Inbox size. The Board shows the same as a Today panel. |
| `lodestar jobs show ID` | Fields + full event timeline. |
| `lodestar jobs status ID saved\|applied\|screening\|interview\|offer\|accepted\|rejected\|withdrawn [--note]` | Move it. `applied` stamps `applied_at`. `accepted` proposes withdrawing your other open applications (Inbox). |
| `lodestar jobs note ID "text"` / `jobs jd ID source` / `jobs rm ID` | Notes, replace description, delete. |
| `lodestar jobs stats` | Counts, response rate, interview rate. |
| `lodestar variants` | Outcomes per tailored-resume variant: which resume gets interviews. |
| `lodestar jobs followups [--days N]` | Applications quiet for N+ days (default: pref `followup_days`). |
| `lodestar jobs search "query" [--keywords a,b] [--rank] [--limit 25] [--save 0 3] [--auto] [--location L\|remote] [--min-salary N] [--posted-within DAYS] [--seniority LEVEL]` | Free job APIs; `--rank` scores fit 0-100 against your profile (no provider: results shown unranked with the reason); `--save` tracks results by index; `--auto` proposes strong fits (tool `auto_track`); filters: see Sourcing below. Results already on your Board say `tracked as #N`. |
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
| `lodestar interview prep ID [--council]` | Prep pack: questions with model answers, STAR stories, gaps, questions to ask, pitch, negotiation. Starts from the questions you logged for this company or similar titles and builds behavioural answers from your own stories. |
| `lodestar interview mock ID` | Live mock interview, one question at a time, scored debrief on `done`; the transcript and debrief are saved to `mock_interview.md` (also from Coach > Mock interview, which can speak the questions aloud). Each answer gets a score card (below). |
| `lodestar interview log ID [--round N] [--kind phone\|technical\|onsite\|panel\|final\|other] [--at "YYYY-MM-DD HH:MM"] [--interviewers] [--notes] [--outcome pending\|passed\|rejected\|unknown] [--questions-file F]` | Log an interview round; the questions file holds one question you were asked per line. Again with `--round N` updates that round. |
| `lodestar interview rounds ID` | A job's rounds with kind, time, outcome, interviewers and the questions asked. |
| `lodestar questions [ID]` | Your question bank: questions logged at this job's company first, then for similar titles, then about 30 bundled behavioural questions. Without an ID: every question you logged. |
| `lodestar stories list\|show ID\|rm ID` | STAR story bank. |
| `lodestar stories add --title T [--situation] [--task] [--action] [--result] [--metrics] [--tags conflict,ownership]` / `stories add --from-idea ID` | Save a story (title plus at least one STAR part; tags from leadership, conflict, failure, ambiguity, influence, ownership, customer, data-driven, teamwork, deadline). `--from-idea` turns an idea of the ideas `stories` topic into an incomplete story to finish. |
| `lodestar ics ID --when "YYYY-MM-DD HH:MM" [--minutes 60]` | Calendar file for the interview plus a prep reminder 2 days before; also records the round. Email check creates this automatically when an interview mail carries a date and time. |

## AI keys

Step by step for every provider and mailbox: [CONNECT.md](CONNECT.md).

| Command | What it does |
|---|---|
| `lodestar keys` / `lodestar keys list` | Each provider: linked (vault / env / no), last check (Verified, Failed, Couldn't reach, Not checked), when, the model in use; where to get a key when none is linked. |
| `lodestar keys link NAME` | `NAME`: anthropic, openai, gemini, groq, openrouter, mistral, ollama (or the variable name, e.g. `ANTHROPIC_API_KEY`). Asks for the key without showing it, stores it in the keyring and verifies it at once with a call that spends no tokens (the provider's model list; OpenRouter's key info). Never prints the key. |
| `lodestar keys check [NAME]` | Re-verify one key, or every linked key and the mailbox. |
| `lodestar keys rm NAME` | Remove the key from the keyring (a key in `.env` or the environment stays: remove it there). |

Every app start (`lodestar ui`, `app`, `desktop`) re-checks the linked keys and the mailbox once in the background;
offline is "couldn't reach", never "invalid"; a quota or rate limit (HTTP 429) shows as Failed (quota) and keeps AI
features on. `LODESTAR_NO_STARTUP_CHECK=1` turns that off.

## Connect your email

Lodestar reads hiring replies over IMAP and sends only mail you approve over SMTP, as your own address. Two ways in:
**Sign in with Google or Microsoft** (your usual 2-step check runs on their page; Lodestar keeps only a refresh token)
or an **app password** (never your normal password). Either one is stored in the OS keyring only and no command, API
route, log, export or backup returns it. In the app: Setup > **Connect email**. Full guide: [CONNECT.md](CONNECT.md).

| Provider | IMAP | SMTP | App password |
|---|---|---|---|
| Gmail | imap.gmail.com:993 | smtp.gmail.com:465 ssl | Sign in with Google (your own client, CONNECT.md), or an app password: needs 2-Step Verification; https://myaccount.google.com/apppasswords |
| Yahoo | imap.mail.yahoo.com:993 | smtp.mail.yahoo.com:465 ssl | Account Security > Generate app password |
| iCloud | imap.mail.me.com:993 | smtp.mail.me.com:587 starttls | Apple Account > Sign-In and Security > App-Specific Passwords |
| Fastmail | imap.fastmail.com:993 | smtp.fastmail.com:465 ssl | Settings > Privacy & Security > App passwords |
| Zoho | imap.zoho.com:993 | smtp.zoho.com:465 ssl | turn on IMAP access; Accounts > Security > App Passwords (org/EU accounts: Custom) |
| AOL | imap.aol.com:993 | smtp.aol.com:465 ssl | Account Security > Generate app password |
| Outlook.com, Hotmail, Live | outlook.office365.com:993 | smtp-mail.outlook.com:587 starttls | Sign in with Microsoft only (no app passwords); turn on IMAP in Outlook.com |
| Microsoft 365 (work or school) | outlook.office365.com:993 | smtp.office365.com:587 starttls | Sign in with Microsoft (`--work`); sending needs SMTP AUTH allowed by your organization |
| Proton Mail (via Bridge) | 127.0.0.1:1143 starttls | 127.0.0.1:1025 starttls | the Bridge password; `--cafile` with Bridge's exported certificate (not yet tested with a real Bridge) |
| Custom | your host:port | your host:port, ssl (465) or starttls (587) | whatever your provider issues |

| Command | What it does |
|---|---|
| `lodestar email connect [--preset P] [--user U] [--imap-host] [--imap-port] [--imap-mode ssl\|starttls] [--smtp-host] [--smtp-port] [--smtp-mode ssl\|starttls] [--smtp-user] [--cafile PATH]` | Store the connection, prompt for the app password (hidden; Enter keeps the stored one, but only when the address and servers are unchanged: a new address, IMAP/SMTP host or SMTP login drops it, so one account's password never goes to another server), then test. The preset is guessed from the address when omitted. |
| `lodestar email test` | Log in to IMAP (INBOX read-only, counts the last 7 days) and SMTP (sends nothing); a failure comes with a plain hint (app password / 2-Step Verification, wrong host, timeout, TLS port or mode, IMAP turned off). |
| `lodestar email test-send` | Send a short test email to your own connected address (never anyone else). |
| `lodestar email status` | Connected address, preset and servers (never the password); lists env vars that override the stored values, with a warning when an `IMAP_HOST` / `SMTP_HOST` in `.env` or the environment points somewhere other than the provider you chose (`email test` puts that first in its hint). |
| `lodestar email client google\|microsoft` | Store your own OAuth client (CONNECT.md sections 4, 5): Google asks for the client ID and secret (hidden), Microsoft for the Application (client) ID only. Kept across Disconnect. |
| `lodestar email signin google\|microsoft [--work] [--hint ADDRESS] [--no-browser]` | Sign in on the provider's page in your browser (every 2-step method works there), then test IMAP and SMTP. `--work`: Microsoft 365. `--no-browser` prints the page to open. Waits up to 5 minutes. |
| `lodestar email disconnect` | Remove the stored app password, or sign out (Google: the sign-in is revoked; Microsoft: says where to remove the app). Servers and your client stay. |
| `--imap-mode ssl\|starttls` (on `email connect`) | IMAP over implicit TLS (993, the default) or STARTTLS (143; Proton Mail Bridge's default on 1143, which the Proton preset uses). Never falls back to plain text. |
| `--cafile PATH` (on `email connect`) | Trust only this certificate file for IMAP and SMTP (Proton Mail Bridge's exported certificate); the host-name match is skipped only for a loopback IP. |

Settings: `EMAIL_PRESET`, `IMAP_USER`, `IMAP_HOST`, `IMAP_PORT`, `IMAP_MODE` (`ssl` or `starttls`), `SMTP_HOST`, `SMTP_PORT`, `SMTP_MODE`, `SMTP_USER`
(defaults to `IMAP_USER`), `MAIL_CAFILE`, `EMAIL_AUTH` (`password` or `oauth`) and the secrets `IMAP_PASS` or
`OAUTH_REFRESH` (+ `OAUTH_PROVIDER`, `OAUTH_ACCOUNT`, `OAUTH_REFRESH_EXPIRES`, `OAUTH_NEEDS_SIGNIN`; your client in
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MS_CLIENT_ID`), all in the keyring vault. Access tokens are never stored. A value in the environment or `.env`
wins. Every outgoing message carries a `Message-ID` and `Date`. `lodestar doctor` shows the servers; `--live` also logs
in once to each.

## Monitoring

| Command | What it does |
|---|---|
| `lodestar email check [--days 3] [--dry]` | IMAP scan, AI classification, tracker updates, alerts. `--dry` changes nothing. |
| `lodestar mail list [--job ID \| --unmatched]` | Mail Lodestar recorded, newest first: every relevant scanned message and everything it sent. `--job` shows one job's mail both ways; `--unmatched` the incoming mail no job claims. Each line says trusted / unverified and how it was linked (auto, thread, user). |
| `lodestar mail link MAIL_ID JOB_ID` | File a message under a job. Your link never sets the job's contact and never makes the sender trusted (nor does a reply you send to it). A pending "track this company" Inbox item raised by the same mail is closed. |
| `lodestar mail unlink MAIL_ID` | Undo a link you made (automatic and thread links stay). |
| `lodestar mail dismiss MAIL_ID` | Drop an unmatched message from the list (a scan never brings it back). |
| `lodestar watch add URL [--keywords a,b]` | Alert when matching lines appear on a page (skipped, with one alert, when the site's robots.txt disallows it). |
| `lodestar watch search-add "query" [--keywords] [--location] [--min-salary] [--posted-within] [--seniority]` | Alert on new listings for a query, with saved search filters. |
| `lodestar watch list` / `watch rm ID` / `watch run` | Manage and run watches. `list` shows `last run failed: ...` under a watch whose last run failed, and `note: partial: ...` when only some job boards were unreachable (the run still counted). Re-adding a watch keeps its id and baseline; the Search tab's Save as watch with blank keywords and filters keeps the saved ones and says it updated the existing search. |
| `lodestar companies add URL\|vendor:slug [--name] [--keywords]` / `companies list` / `companies rm ID` | Follow a company's public Greenhouse, Lever or Ashby board (see "Sourcing" below). |

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
| `lodestar vault set NAME [value] [--user U]` | Store in the OS keyring (prompts if no value). Surrounding spaces and newlines are trimmed; an empty or blank value is refused with one line. |
| `lodestar vault get NAME [--show]` / `vault rm NAME` / `vault list` | Read, delete, list names. |

## Web API (for the page and the bookmarklets)

All on `http://127.0.0.1:<port>`, JSON in and out. Every route needs the per-launch `X-Lodestar-Token` header that the
page embeds. Outside scripts can only call `/api/capture` and `/api/autofill`, with `?t=<~/.lodestar/capture.token>`.

| Route | Purpose |
|---|---|
| `GET /api/state` | jobs, stats, variants, watches, alerts, providers, vault names |
| `GET /api/jobs/ID` | job, events, generated documents, linked people (`people`) and the contacts you know at the company (`warm`), interview `rounds`, the logged-question `bank` and `stress` (competencies the posting stresses, those with no story) |
| `POST /api/jobs/ID/rounds` `{round?, kind, at, interviewers, notes, questions_asked, outcome}` | log a round (validated; an existing `round` number updates it) |
| `POST /api/rounds/ID/edit\|delete` | edit a round (`""` clears) / delete it |
| `POST /api/stories` `{id?, title, situation, task, action, result, metrics, competencies}` / `{from_idea}` | save or update a STAR story (unknown keys refused); remove one with `POST /api/answers/ID` |
| `GET /api/contacts` / `GET /api/contacts/ID` | every contact with its linked jobs / one contact, its jobs and the timeline entries naming its email |
| `POST /api/contacts` `{name, email?, phone?, linkedin_url?, company?, position?, how_met?, notes?, last_touch?, next_touch?}` | add a contact (whitelisted, validated; email and LinkedIn URL are unique) |
| `POST /api/contacts/ID/edit\|delete\|link\|unlink` | edit fields (`""` clears) / remove / `{job_id, role}` link to a job (recruiter, hiring_manager, referrer, interviewer, other) / `{job_id}` unlink |
| `POST /api/jobs` `{company,title,jd,url,notes,location?,posted_at?}` | add; source, workplace and pay are read from the notes and JD |
| `POST /api/capture` `{title,url,desc}` | add from a browser page title (bookmarklet) |
| `POST /api/jobs/ID/status|note|jd|contact|delete` | update (`contact` takes `{email, name}` and also files the person under Contacts, linked as recruiter) |
| `POST /api/jobs/ID/fields` `{deadline: "2026-12-01", tags: "a,b", ...}` | set tracker fields (same whitelist and validation as `jobs set`; `""` clears) |
| `POST /api/jobs/ID/skip` `{term}` | JD coverage: mark a keyword "not mine" for this job, or unmark it; returns `{coverage}` |
| `POST /api/watches` `{url,keywords,search,location?,min_salary?,posted_within?,seniority?}` / `POST /api/watches/ID` | add / remove (filters apply to a saved search; re-adding one without any filter key keeps its saved filters; a page watch needs an http(s) URL) |
| `POST /api/companies` `{source,name?,keywords?}` / `POST /api/companies/ID` | watch a company's Greenhouse / Lever / Ashby board / stop |
| `GET|POST /api/profile` | read / save the master resume |
| `POST /api/vault` `{name,value,user}` / `{name,delete:true}` | store / remove a secret |
| `GET /api/email/status` | `{status, presets}`: connected?, preset, address, servers, env overrides (never the password) |
| `POST /api/email/connect` `{preset, user, password?, imap_host?, imap_port?, imap_mode?, smtp_host?, smtp_port?, smtp_mode?, smtp_user?, cafile?}` | store the connection (the password only when given; changing the address, a host or the SMTP login without one removes the stored password); returns the status (`configured: false` until a password is entered) |
| `POST /api/email/test` | IMAP and SMTP login check: `{imap: {ok, detail, kind?}, smtp: {ok, detail, kind?}, hint, reachable}` (`kind`: auth, net or other). Every test (this route, the sign-in task, Re-check all, the startup check) stores its result, which Getting started and `doctor` show |
| `POST /api/email/test_send` | a test email to your own address; any other `to` is refused |
| `POST /api/email/disconnect` | remove the stored app password, or sign out (`note` says where to remove a Microsoft app) |
| `POST /api/email/client` `{provider, client_id, client_secret?}` | store your own OAuth client; returns `{clients: {google: {set}, microsoft: {set}}}`, never the values |
| `POST /api/email/signin` `{provider, account?: personal\|work, login_hint?}` | starts the sign-in as a background task (`{task}`; poll `GET /api/tasks/ID`: `{status, test}`) |
| `GET /api/email/signin` / `POST /api/email/signin_cancel` | the waiting sign-in's page link (`{pending, url, provider}`) / stop it |
| `GET /api/keys` / `POST /api/keys/link\|check\|remove` `{name, key?}` | linked AI keys and their last check (never a key) / link and verify, re-check (`{}`: all, as a task), remove |
| `GET /api/jobs/ID/files` | what a mail for this job may attach: `{files: [{name, size, mtime, type, blocked?}]}` (names and sizes only; no route serves a file's bytes). `blocked`: why sending it would be refused (it names your salary floor); the Inbox greys it out |
| `GET /api/codes` / `POST /api/codes/check` / `POST /api/codes/ID/dismiss` | emailed sign-in codes from the last 15 minutes (memory only) / look in the mailbox now (inline, read-only, nothing marked read) / drop one. `GET /api/state` carries only `codes_count` |
| `GET /api/mail?job=ID` / `?unmatched=1` | recorded mail: one job's, both ways, or incoming mail no job claims (`GET /api/state` carries `mail_unmatched`, `GET /api/jobs/ID` carries `mail`) |
| `POST /api/mail/ID/link\|unlink\|dismiss\|track` | `{job_id}` file under a job (never sets the contact or trust) / undo your own link / drop unmatched mail / `{company?, title?}` add a job from it, without a contact (closes the Inbox's "track" proposal raised by the same mail; `link` does too) |
| `POST /api/comp` `{op: set\|delete, title, city, low, high}` | edit your market-rate table |
| `POST /api/open_folder` `{which: data\|exports\|backups\|applications\|log}` / `{which: job, id, sub: attach\|mail\|""}` | reveal a folder in the file manager (a job's folder, its `attach/` or its saved `mail/`; never a file) |
| `GET /api/analytics` | Insights: per-week series, response rate by source and by match band, funnel, variants, weekly goals |
| `GET /api/offers` | live offers side by side (totals, best per row, market range, gap to your private salary floor) |
| `POST /api/offers/ID` `{base, bonus_pct, sign_on, equity_value_estimate, vest_years, cliff_months, retirement_match_pct, remote, start_date, deadline, notes}` | record or edit a structured offer (whitelisted, validated; `""` clears; the job moves to `offer`; all fields empty records nothing, and clearing every field removes the offer) |
| `GET /api/update/status` / `GET /api/update/log?limit=50` | Setup > Updates, no network: install kind, version, `update_mode` / `update_every_hours` / `update_channel`, last check and update, `available` (the last check found one and no update since), `failed` (the last update failed or was refused), `restart_needed`, `restart` (the desktop app can relaunch), the last 20 log rows (`GET /api/state` carries the same as `update`) / the update log, newest first |
| `POST /api/update/check` / `POST /api/update/apply` `{target}` | background tasks (`{task}`; poll `GET /api/tasks/ID`): the check (`{available, current, target, behind, commits, changelog, blocked, result}`) / the update to exactly the `target` that check showed (a moved origin is refused: check again): backup, fast-forward, tests and doctor, rollback; `{ok, result, backup}` |
| `POST /api/update/restart` | desktop app only: relaunch `lodestar desktop` with the same arguments and close this window; refused while an update (any process), a mail scan, an Inbox send or a background action runs (`GET /api/update/status` `updating` is true while an update runs) |
| `POST /api/run/ACTION` then `GET /api/tasks/ID` | background actions: tailor, cover, gap, prep, review, reply, outreach, ics, email_check, watch_run, search, chat, council, digest, obsidian, providers_test, providers_local, models, export (`{fmt: json or csv}`), auto_track, mock (`{messages, id, session?, seconds?}`; an answer returns a score `card`), packet, doctor (`{live}`), backup, match (`{id}`), lint (`{text}`), audit (`{id}`, or `{}` for the newest saved resume file), referral (`{id, contact_id}`), contacts_import (`{name, data: base64}`), counter (`{id, cite: ["JOB:field"], ask?, template?}`; always waits in the Inbox), activity (`{from, to, fmt?: csv\|html}`) |

## Automation and approvals (see AUTOMATION.md)

| Command | What it does |
|---|---|
| `lodestar tools list` | every automated tool with its enabled / auto switches, plus preferences |
| `lodestar tools enable\|disable\|auto\|manual NAME` | flip a switch |
| `lodestar tools set KEY VALUE` | preferences: name, availability, auto_track_min_score, followup_days, reply_to_confirmations, weekly_target (applications/week, used by idea crafting), provider, council_providers, council_judge, signature, desktop_notifications (true/false), resume_style (classic, modern, compact), excluded_companies, excluded_title_words, weekly_goals (`goal=number`), activity_weekly_min, update_mode (off / notify / auto), update_every_hours, update_channel (commits / releases), update_origin, update_manifest_url, models (`provider=model`; also written by self-healing model selection). Whole numbers are range-checked: followup_days 1-90, auto_track_min_score 0-100, weekly_target 0-200, activity_weekly_min 0-100, update_every_hours 1-720 |
| `lodestar inbox [--all] [-v]` | actions waiting for approval (`-v` shows the drafted email / payload) |
| `lodestar approve ID... [--subject] [--body FILE] [--to]` | execute, optionally editing the email first |
| `lodestar reject ID... [--reason]` | discard |
| `lodestar answers list\|add Q A [--tags t1,t2] [--private]\|rm ID\|ask ID "question"` | answer bank for application-form questions; `ask` drafts from profile + bank and proposes saving. `--private` (UI: the private checkbox / make private) keeps an answer for you only: drafted answers, letters and form autofill never see it. An answer that names your salary floor must be private |
| `lodestar jobs contact ID EMAIL [--name]` | recruiter / hiring-manager address used for replies and follow-ups |
| `lodestar jobs checklist ID` | done / next for every stage of this application |
| `lodestar followup ID [--template]` | follow-up email draft; sent through the inbox when a contact is known. One at a time: while one waits in the Inbox you get that one back, and sending one closes any other waiting for the job |
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
| `lodestar backup [--out DIR] [--keep 7]` | zip of profile, tracker, settings, answers, ideas, documents (never `.env` or keyring secrets); keeps the newest N (at least 1); the `backup` tool does this nightly |
| `lodestar export json / csv [--out DIR]` | dump jobs, events, answers, ideas, pending, contacts, job_contacts, interviews, mock_sessions, offers, touches, mail (CSV: one file per table, formula-safe cells) |
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
The monitor loop reminds you of interviews within 48 hours (from interview rounds with a time; pass 15). The autofill bookmarklet
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
| `lodestar doctor [--live]` | PASS / WARN / FAIL lines for Python version, required and optional modules, WebView2 runtime, keyring backend, data folder, master profile, configured providers (with the model each will use), mail settings, updates (install kind, update preferences, last check and last update from the update log, restart needed), leftover legacy folder; `--live` makes one real call per provider. Exit code 1 when something is broken. |

Setup also has a Diagnostics panel (same checks as `lodestar doctor`, with an optional live AI call) and an
"Open log" button next to the data folders.

## Updates (pass 16.4)

| Command | What it does |
|---|---|
| `lodestar update check` | fetch the origin (pref `update_origin`, else the install's `origin` remote; https:// or a local folder only) and print the commits and the CHANGELOG sections an update would bring, and why it cannot be applied now if something blocks it |
| `lodestar update apply [--yes]` | the same, then (after you answer y, or with `--yes`) back up the data folder, fast-forward the install, reinstall only when `pyproject.toml` changed, run the unit suite (on a throwaway data folder) and `lodestar doctor` on the new code, and on any failure reset to the exact previous commit. Refused while the install has uncommitted changes or commits the origin does not, while a mail scan, an Inbox send, a background action or another update runs, or while another Lodestar process (app, desktop window, loop) is running. A failed test run names the failing tests |
| `lodestar update status` | install kind (git, standalone build, other), version, `update_mode` / `update_every_hours` / `update_channel`, last check and last update, restart needed |
| `lodestar update log [--limit 20]` | every check and update, newest first: time, from, to, result (`~/.lodestar/update-log.jsonl`, last 500) |

The monitor loop (`run`, `app`, `desktop`; `--no-update` skips it) checks every `update_every_hours` (default 24).
`update_mode`: `off`; `notify` (default) raises one alert per new version; `auto` applies it when nothing blocks it
and alerts the result. `update_channel`: `commits` follows the origin branch, `releases` its newest `v*` tag. A check
that cannot reach the origin is logged as "could not check" and the loop goes on. The standalone build (`-Exe`) reads
the https JSON at `update_manifest_url` (`{version, url, notes}`) and only tells you where to download; it never
replaces itself. After an update, restart Lodestar to run the new code. The developer's own checkout is an install
too: with unpushed commits or local changes it is never updated.

Safety net: an update in progress is recorded in `~/.lodestar/update-state.json`; if Lodestar dies before the outcome
(closed, killed, power loss), the next start of `run`, `app`, `ui` or `desktop` (or the next update) resets the install
to the previous commit and logs "the update was interrupted". A fast-forward that fails half-way is put back exactly
(new files it left are removed). A rollback that itself fails is retried, then logged as `ROLLBACK FAILED` with the
`git reset --hard` command to run (a doctor FAIL line), and retried at the next start. The test gate runs with a time
limit and kills the whole process tree when it is exceeded. In auto mode a version that failed its tests is not tried
again automatically (one alert; `lodestar update apply` retries it). The `releases` channel forgets tags the origin
deleted. Each running app, desktop window and loop registers in `~/.lodestar/procs/`; an update waits while another
one is running. A running server serves the screens it started with (read once at start) until it restarts.

Setup > Updates does the same in the app: the mode (off / notify / auto) and the interval, Check now (the commit
range, each commit and the changelog the update adds, or why it cannot be applied now), Update now (asks first, shows
progress, then the result and the backup path; a failure says what failed and that the old version is back), a Restart
button in the desktop app (`lodestar app` / `ui`: close and start it again; hidden while an update is running) and
the update log. A refused Update now (the origin moved, another update running) says why and clears the old plan. A top-bar badge shows
"Update available" or "Restart to finish the update"; a failed or refused update is noted under Getting started and
in Diagnostics until a later update succeeds.

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

## Sourcing: company boards, search filters, sponsors, stale signals (pass 15)

**Companies** (`lodestar companies add|list|rm`, Monitor > Companies, `POST /api/companies`): follow a company's own
public job board. Give its careers or posting link (`boards.greenhouse.io/<slug>`, `job-boards.greenhouse.io/<slug>`,
`jobs.lever.co/<slug>`, `jobs.ashbyhq.com/<slug>`) or `greenhouse:<slug>` / `lever:<slug>` / `ashby:<slug>`; `--name`
sets the display name (default from the slug), `--keywords a,b` keeps only matching postings. Each monitor cycle reads
the board's documented public JSON once (Greenhouse board API, Lever postings API, Ashby posting API). The first good
read is a baseline: the roles already open are recorded with one summary alert ("WATCHING Acme: N open role(s)"), not
alerted or judged one by one. After that, new postings are treated like saved-search hits: one alert each, AI judgement
through `auto_track`, marked seen only once judged.
**Workday, Taleo and iCIMS have no public feed**: Lodestar says so when given one of their links; add the careers page
as a page watch instead. Only Greenhouse, Lever and Ashby are supported.

**Page watches and robots.txt**: before fetching a watched page, Lodestar reads the site's robots.txt (once per host per
cycle). When it disallows the page, the watch is skipped with a single alert and resumes if the rules change.

**Search filters** (`jobs search` and `watch search-add` flags, the Search tab's filter row, saved with "Save as
watch"): `--location TEXT` (a substring of the listing location) or `--location remote`, `--min-salary N` (top of the
stated range, `120k` works, currency not converted), `--posted-within DAYS`, `--seniority
intern|junior|mid|senior|staff|lead|manager` (read off the title; no marker counts as mid; "Product Manager" stays
mid). A listing that does not state its salary, location or date is **kept** and marked `salary unknown` /
`location unknown` / `date unknown`. Private dealbreakers, preferences `excluded_companies` and `excluded_title_words`
(comma lists, Tools > Preferences), drop listings before anything else; they never leave your machine. The same posting
on several boards (same company without Inc/LLC/GmbH..., same title, same location) is shown once with the richest
description and every link. Each result shows JD coverage against your profile as an employer sees it (no salary floor,
no Preferences) with the top matched and missing terms; skipped while the profile is still the template. AI ranking
stays optional.

**H-1B sponsor hint** (optional): download the export from the USCIS H-1B Employer Data Hub yourself, then
`lodestar sponsors import FILE` (CSV or the hub's tab-separated UTF-16 file; columns Employer or Employer (Petitioner)
Name, Fiscal Year, and every "... Approval" column: New Employment / Continuation / Change with Same Employer / New
Concurrent / Change of Employer / Amended in the current export, Initial / Continuing in older ones; denials are
ignored). Approvals are summed per employer and fiscal year; importing a
year again replaces it. Search results and board cards then show "possible H-1B sponsor (N approvals)" on a loose name
match: a hint, not a promise. `sponsors lookup NAME`, `sponsors clear`. Nothing is downloaded automatically.

**Possibly stale**: search results and saved (not yet applied) board cards get a "possibly stale" chip with reasons
when the signals add up to 30 or more: posted over 30 days ago (30), the same company + title + location first seen
over 21 days ago under another link (30), a very short description or one naming no concrete skill, tool or
qualification (20), and for a job from a Greenhouse / Lever / Ashby board, its posting gone from the live feed (60).
`auto_track` leaves listings at 60 or more alone. Weekly, the monitor loop re-checks saved jobs that came from (or link
to) one of those boards, one request per board; when a posting has disappeared it records it on the timeline and
proposes moving the job to `withdrawn` with the note "posting removed". A saved link that names no posting (a
board root) is never counted as removed; `/apply` and `/application` links and Greenhouse embed links (`token=`) are read
as the posting they point to. That always waits in the Inbox (tool
`posting_check`, switchable under Tools); Lodestar never changes the status itself.

## Contacts and warm paths (pass 15)

| Command | What it does |
|---|---|
| `lodestar contacts add "Name" [--email] [--phone] [--linkedin URL] [--company] [--position] [--how-met] [--notes] [--next-touch YYYY-MM-DD]` | Add a person by hand. Email and LinkedIn URL are unique. |
| `lodestar contacts list [TEXT] [--due]` | Name A-Z with company, position, last / next touch and linked jobs; `TEXT` filters name, company, position, email. |
| `lodestar contacts show ID` | Fields, linked jobs with roles, recent timeline entries mentioning their email. |
| `lodestar contacts edit ID key=value ...` | `name`, `email`, `phone`, `linkedin_url`, `company`, `position`, `how_met`, `notes`, `last_touch`, `next_touch`. Empty clears; a bad value changes nothing. |
| `lodestar contacts rm ID` | Remove a contact (linked jobs stay). |
| `lodestar contacts import FILE` | Your LinkedIn "Download your data" `.zip` or the `Connections.csv` inside it (the "Notes:" preamble is skipped). De-duplicated by LinkedIn URL, then email, then name + company; a known contact only gains fields it lacks. No follow-up dates are set. |
| `lodestar contacts due` | Contacts whose next touch has come and who have not been in touch since. Also on the Today list; nothing is drafted for them. |
| `lodestar contacts link ID JOB [--role recruiter\|hiring_manager\|referrer\|interviewer\|other] [--remove]` | Link a contact to a job with a role (again to change it), or unlink. |

**Contacts tab**: a sortable, filterable table (name, company, position, last touch, next touch, linked jobs; the sort
is remembered), an Add form and an "Import LinkedIn connections" control. Clicking a name opens the contact drawer:
edit fields and notes, set the next touch, "Touched today", link to a job with a role, unlink, and the recent timeline
entries that mention their email.

**Warm paths**: a contact whose company matches a job's (same name without Inc / LLC / GmbH..., or every distinctive
word of the shorter name inside the longer, so "Amazon" matches "Amazon Web Services") shows as "you know N people
here" on board cards, search results (`jobs search` prints "you know N here: ...") and in the job drawer's People
section. A loose match: a hint, not a guarantee. From the drawer you can link them with a role or **Ask for referral**:
an outreach draft through `extras.outreach`, addressed to the contact. With their email it goes to the Inbox and always
waits for your review (tool `email_reply`, even on auto); without one you get a LinkedIn note to send yourself. The
contact is linked as referrer unless they already have a role on the job.

**Touches**: mail from a contact's exact address (any message the inbox scan reads) sets their last touch to the mail's
date, and sending an approved email to their address sets it to today. Last touch only moves forward.

**Job contact field**: the drawer's Admin > set contact and `lodestar jobs contact ID email --name` still set the job's
own contact (the address replies and follow-ups go to) and now also file that person under Contacts, linked as
recruiter. One-time on upgrade: every job's stored contact became a contact the same way.

**Mail trust is unchanged**: the email monitor trusts only a job's own stored contact address and company domain. A
contact, imported or typed, linked to a job or not, never makes mail trusted and never becomes a job's contact by
itself.

## Interview rounds, question bank, stories and mock scoring (pass 15)

**Rounds**: each job keeps its interview rounds (number, kind, time, interviewers, notes, the questions you were asked,
outcome) in the drawer's Interview rounds section or with `interview log` / `interview rounds`. Writing an .ics, an
accepted interview slot and an interview email with a stated time from a trusted sender (DKIM-aligned, tied to the
job by address or company domain) also record the round, and with the calendar tool on write the .ics as before. A
mail with only a date (often a reply-by date) or from an unverified sender records no round, only an `interview_date`
timeline note, so it never shows up as an interview in the activity log or Insights. Upcoming interviews, Today, reminders and clash checks read the rounds; calendar events from before
rounds existed are imported once.

**Question bank**: the questions you logged become a personal bank (`lodestar questions [ID]`, and a list in the
drawer): this company first, then similar titles (every word of the shorter core title inside the longer), then a
small bundled set of about 30 behavioural questions (`lodestar/data/questions.json`). Prep packs and mock interviews
use the logged ones first, before inventing new questions.

**Stories**: Answers > Stories is a guided form (situation, task, action, result, metrics, competency tags). Stories
live in the answer bank (question `Story: <title>`, the STAR fields as JSON), so form answers can reuse them; they are
listed apart from form answers. An idea of the ideas `stories` topic has **Save as story**. The job drawer reads the
posting through a small keyword table and says which competencies it stresses and which have no story yet, as a
prompt. Prep and mock interviews put your matching stories in front of the AI so coaching uses your real material.

**Mock score card**: after each answer, one AI call scores situation, task, action and result (0-2 each), relevance and
specificity (0-2), whether a number backs the result, one fix and a rewrite that only reorders your own facts.
Computed offline, with or without a provider: word count, estimated speaking time (about 140 words a minute) against a
60-120 second target, the most repeated words and the posting keywords you used; words per minute only when you
dictated the answer (browser speech recognition; the whole listening time counts). No filler-word counts. Answers
are saved per session (`mock_sessions` table) with averages; the Coach tab shows each card, a session summary and an
inline STAR-average trend across sessions; `interview mock` prints the card. Without a provider the mock still runs:
the questions come from the question bank in order (this company's logged questions first, then the bundled set),
the rubric is skipped and the offline half of the card still shows; there is no debrief.

## Insights, weekly goals, offers and the activity log (pass 15)

```powershell
lodestar insights [--weeks 12] [--json]          # weekly series, response rates, funnel, variants, goals
lodestar tools set weekly_goals contacts=5       # also tailored_applications, mock_sessions, applications; 0 clears
lodestar offers                                  # = offers compare: live offers side by side
lodestar offers set 7 base=150k bonus_pct=10 sign_on=20000 equity_value_estimate=200k vest_years=4 cliff_months=12
lodestar offers counter 7 --cite 9:base 9:sign_on [--ask "a base of 170,000"] [--template]   # a cited figure may equal your floor; the ask may not
lodestar activity [--week 2026-11-04 | --from 2026-10-01 --to 2026-10-31] [--csv | --html]
lodestar tools set activity_weekly_min 3         # the weekly count your claim asks for (default: none)
```

**Insights** (tab and `insights`): per ISO week, the applications you made (jobs entering `applied`: moved by you, or
by the employer's confirmation mail; an auto-tracked save never counts), interview rounds held, offers, people you
contacted (mail sent from the Inbox plus touches you record: a last-touch date or "Touched today") and mock sessions.
Response and interview rate by source and by match-score band (<40, 40-59, 60-79, 80+, unscored) over applications
that left `saved`; a group under 5 shows "not enough data yet". Conversion and median days come from the existing
funnel, resume variants from the existing variant data. Small inline SVG bar charts, each bar with a `<title>`, and a
table of the same numbers. No cover-letter or outreach A/B.

**Weekly goals** (pref `weekly_goals`): none by default and no default application count. The Insights tab offers
contacts and tailored applications first, then mock sessions and applications. Progress counts this week (Monday to
today) from the same events; the Friday digest lists the goals you set.

**Offers**: structured fields per job (`offers` table): base, target bonus %, sign-on, your estimate of the equity
grant's value, vesting years, cliff months, retirement match %, workplace, start date, deadline, notes. `comp.total`
gives year-1 cash and total, 4-year cash and total, equity per year (even monthly vesting after the cliff) and the
match, and names every estimate behind them. The compare table marks the best value per row and shows your recorded
market range (`comp`) and the gap to your private salary floor; the floor row is shown only in Lodestar's own views.
Offer evaluation (`offer`, the drawer's Evaluate offer) now reads the structured rows. **Counter-offer**: tick the
competing figures to cite (another live offer's base, bonus %, sign-on, equity estimate or year-1 total); the draft
(AI, or a plain template) says "another offer" without the company name, uses only `candidate_text(private=False)`,
never your floor, Preferences or offer notes, and always waits in the Inbox for review.

**Activity log** (Insights tab and `activity`): what you did, by week, as date / activity (applied, contacted,
followed up, interviewed) / employer / position / method / contact / result, counted only from your own actions: jobs
moved to applied, mail actually sent from the Inbox (pending, rejected or failed items do not count, nor withdrawals),
interview rounds up to today and touches you recorded. Each week shows its count against `activity_weekly_min` when
set. Export as CSV (cells a spreadsheet would run as formulas are prefixed with `'`) or Markdown plus a printable HTML
page in `~/.lodestar/exports`. It is a helper report: check your state's requirements; it makes no claim of compliance.

## Draft options, rewrites and suggested emails (pass 16)

| Command | What it does |
|---|---|
| `lodestar followup ID --options` | Up to 3 numbered drafts from one AI call, one marked RECOMMENDED with a one-line reason. Nothing is proposed yet; the options are kept in `~/.lodestar/draft_options.json`. Without an AI provider: the plain template as the one option. |
| `lodestar followup ID --pick N` | Use option N of the options just printed (no second AI call): proposed in the Inbox and always waiting for your review, even when the tool is on auto. `--options --pick N` does both at once. |
| `lodestar thanks ID [--interviewer] [--notes] --options` / `--pick N` | Same for a thank-you note. |
| `lodestar withdraw ID --options` / `--pick N` | Same for a withdrawal email (sending it moves the job to `withdrawn`). |
| `lodestar outreach ID [--person "Name, title"] --options` / `--pick N` | Same for an outreach email to the job's contact. |
| `lodestar offers counter ID [--cite JOB:FIELD ...] [--ask ...] --options` / `--pick N` | Same for a counter-offer (only the figures you cite and your ask; never your floor). |
| `lodestar draft options KIND [JOB] [--mail ID] [--pending ID] [--contact ID] [--interviewer] [--notes] [--person] [--cite ...] [--ask] [--question] [--pick N]` | Options for any kind: `reply` (`--mail`: a mail filed under a job), `followup`, `thanks`, `withdraw`, `checkin` (before an offer deadline), `outreach`, `referral` (`--contact`), `counter`, `cover` (the pick is written to `cover_letter.md`), `answer` (`--question`; the pick is proposed for the answer bank), `pending` (`--pending`: alternatives for an Inbox email; the pick replaces only its subject and body). |
| `lodestar draft rewrite --pending ID --how shorter\|warmer\|formal\|direct\|"your words"` | Rewrite an Inbox email in place: subject and body only; recipient, In-Reply-To and job stay, and it stays pending. `--file FILE` prints a rewritten text file instead. Needs an AI provider. |
| `lodestar suggest [--dismiss JOB KIND]` | Suggested emails for today, from the tracker alone (no AI call): thank-you within 24 h after an interview round, follow-up when an application is quiet for `followup_days` (the cadence the loop uses), reply to an unanswered recruiter / interview / offer / assessment mail filed under the job, check-in before an offer deadline (next 3 days), referral ask when you know someone at a saved / applied job's company. Never for rejected or withdrawn jobs or a job with an email already waiting in the Inbox. `--dismiss` hides one for 3 days. |

Every option and rewrite is screened by the salary-floor guard: one that names your floor (or carries your
Preferences) is dropped before you see it, and a pick or edit that names it is refused. Prompts carry your profile
without Preferences only; mail you received goes in fenced as untrusted data.

In the app: the job drawer's Communicate group has **Options** (follow-up, thank-you, withdrawal, outreach, offer
check-in), Documents has **Cover options**, each person under People has **options** for a referral ask, and each mail
under Mail has **Reply with options**. Answers has **Options** (Use this fills the Answer bank form) and Insights >
Offers has **Options** beside the counter-offer. Each opens up to 3 cards (label, tone, recommended badge and why,
subject, body) with **Use this** and rewrite chips (shorter, warmer, more formal, more direct, custom). Every pending
email in the Inbox has **Options** and the same chips; they change its subject and body in place and it stays
pending. Today lists **Suggested emails** (reason, due chip) with **Draft options** and **Dismiss for now** (3 days).

Web API: `POST /api/run/draft_options {kind, id?, mail_id?, pending_id?, contact_id?, interviewer?, notes?, person?,
cite?, ask?, question?, tone?, words?, n?}` -> `{options}`; `POST /api/run/draft_rewrite {kind, subject?, body, how}`
-> `{subject?, body}`; `POST /api/run/draft_use {kind, ...the same context, subject, body}` -> `{draft, proposal}`
(the recipient comes from the job, the mail being answered or the contact, never from the request);
`POST /api/approvals/ID/edit {subject?, body?}` (pending emails only; it stays pending);
`POST /api/suggest/dismiss {job_id, kind}`. `GET /api/state` carries `today.emails`. All behind the page token.
