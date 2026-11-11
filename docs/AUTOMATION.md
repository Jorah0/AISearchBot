# Automation, approvals, and tool switches

lodestar can act on your behalf: reply to recruiters, accept interview slots, move applications forward, add jobs it
finds, save answers it writes. Every one of those actions is a named **tool** with two switches, and every tool
that is not explicitly set to auto must get your approval first.

## The rule

| enabled | auto | behaviour |
|---|---|---|
| off | any | the tool never runs |
| on | off | the tool **proposes** an action into the Inbox and waits for you |
| on | on | the tool **executes immediately** and logs an event on the job |

Commands you type yourself (`lodestar resume tailor 3`, `lodestar outreach 3`) are confirmed by typing them; the inbox
is only for things lodestar decided to do on its own during `lodestar run`, `lodestar app`, or an email check.

Change switches in the UI (Tools tab) or:

```powershell
lodestar tools list
lodestar tools disable auto_track            # never judge listings
lodestar tools auto email_classify           # status changes from mail happen without asking (default)
lodestar tools manual calendar               # ask before writing .ics files
lodestar tools set availability "Tue-Thu 13:00-17:00 ET"
lodestar tools set auto_track_min_score 80
lodestar tools set reply_to_confirmations true
lodestar tools set signature "Sean"
```

## The tools

| Tool | What it proposes / does | Default |
|---|---|---|
| `email_classify` | classify inbox mail; move the matching job to screening / interview / offer / rejected; create a job from recruiter outreach | on, auto |
| `email_reply` | draft a reply to an application confirmation (only if `reply_to_confirmations`), an assessment invite, an offer, or recruiter outreach. Offer replies thank, ask for the written offer and a timeline, and never accept, decline, or name a number | on, manual |
| `interview_scheduling` | for interview invites: accept the first proposed slot inside your `availability` (an .ics is written on send) or propose three slots | on, manual |
| `followup` | draft a follow-up for applications quiet for `followup_days` when a contact email is known | on, manual |
| `auto_track` | score new listings from watches, searches and job-alert mail (the fit score; the AI judges the best few when a key is linked) and propose tracking those at or above `auto_track_min_score`, at most `auto_track_daily_max` a day. Without an AI key it proposes on the rules fit only when 60% of the fit could be measured, and those proposals always wait in the inbox, even on auto | on, manual |
| `answers` | save the answers it drafts for application-form questions into the answer bank | on, manual |
| `calendar` | write .ics files for interview dates found in mail | on, auto |
| `obsidian_sync` | mirror the tracker into your vault after each monitor cycle | off |
| `digest` | email the weekly digest to `LODESTAR_NOTIFY_EMAIL` on the first cycle from Friday on (a missed Friday catches up on the next cycle); without that address a one-line alert says it is ready | off |
| `posting_check` | daily listing check (`web_monitor.check_listings`) of every open tracked job: feed jobs (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Personio) compared with their last copy (changes as a `posting_changed` event and a diff in the job folder's `posting_changes.md`; the JD is never rewritten), other posting pages at most weekly where robots.txt allows (gone only after two misses in a row; LinkedIn, Indeed, Glassdoor and ZipRecruiter are never fetched, nor is any link that came from job-alert mail). A saved job whose posting is gone gets a `withdrawn` proposal that always waits in the inbox, even on auto; an applied one gets the event and a Today item | on, manual |
| `job_alerts` | read job-alert emails (LinkedIn, Indeed, Glassdoor, ZipRecruiter) from your own inbox into All jobs: only mail from the site's known alert address that passed DKIM/DMARC; never sent to the AI, never stored as mail, its links never opened; one notice per alert mail. New rows are judged by `auto_track` after the mailbox is closed | on, auto |

## The inbox

```powershell
lodestar inbox                 # what is waiting
lodestar inbox -v              # with the drafted email / payload
lodestar approve 12            # execute as drafted
lodestar approve 12 --subject "Re: Interview" --body edited.txt
lodestar reject 12 --reason "already replied"
```

In the UI the Inbox tab shows each item with the email fields editable before **Approve & send**. An edit that would
be refused (an email or a saved answer that names your salary floor, a slot that clashes with another interview) is
refused before the item is claimed, so it stays in the Inbox with the reason and nothing is sent or saved. Only one
follow-up per job waits at a time: asking again returns the waiting one, and sending one closes any other.

Attachments: an email card for a job shows its attachments as chips you can remove, plus "Add from this job's files"
(the job's `resume.pdf` / `.docx`, `cover_letter.pdf` / `.docx`, and pdf, docx, png or jpg files in its `attach/`
folder; nothing else, so interview prep, offer notes, research, gap checks, calendar files and received mail can never
reach an employer). The list is checked when the item is proposed, again before the claim (a bad edit keeps the item
pending) and again just before sending (a file that changed or vanished keeps it pending with the error). An attached
resume or cover letter that names your salary floor is refused. `approvals.propose` refuses attachments unless the
item waits for review, so a tool on auto can never mail a file. Drafts you ask for (outreach, referral asks, replies to
verified mail) pre-tick your tailored resume; replies to unverified mail and every automatic draft carry none.

A counter-offer (`lodestar offers counter`, Insights > Offers) is always proposed with review, even when
`email_reply` is on auto, and never contains your salary floor, Preferences or offer notes. A competing figure you
cite is sent by your choice, so it may equal your floor (the exact cited phrase is exempt from the floor check, in the
draft, the Inbox and your edits); the ask and everything else in the email are still checked.

Insights, weekly goals and the activity log count only what you did: an approved and sent item counts, a
pending, rejected or failed one does not, and nothing the loop adds on its own (an auto-tracked save) is an
application.

Executors are the only code that sends mail, changes status, or adds jobs on lodestar's initiative, and they all live in
`lodestar/approvals.py`, so the rule cannot be bypassed by a new feature by accident.

## What a full automatic cycle does (`lodestar run` / `lodestar app`)

1. Email check: classify new mail, propose or apply status changes, capture the sender as the job's contact, write
   .ics for interviews with a stated time from a trusted sender (each also recorded as an interview round; a date
   without a time, often a reply-by date, or an unverified sender records only a timeline note), draft replies for
   confirmations / assessments / interviews / offers. A calendar invite (.ics) attached to the mail supplies the time
   when the text states none; the same trust rule decides whether it becomes a round. Attachments of mail filed under
   a job are saved under `applications/<job>/mail/` (kept types only, size capped, marked as downloaded from the
   internet, never opened); mail no job claims lists their names only. Sign-in codes in authenticated mail from the
   last 15 minutes go to the Inbox's Codes panel, in memory only (never saved, notified or sent to an AI): every
   code-shaped token in a mail is replaced by `******` before the mail is classified or recorded.
2. Watches: diff career pages (only where robots.txt allows; a disallowed page is skipped with one alert); new
   listings from saved searches (with their saved filters) and from watched companies' Greenhouse / Lever / Ashby
   boards (one request per company; a newly watched board's open roles are a baseline with one summary alert) are
   alerted once, AI-judged, and strong fits proposed. Listings that look stale
   are not proposed. Weekly, saved jobs from those boards are re-checked and a removed posting is proposed for
   `withdrawn` (tool `posting_check`, always via the inbox).
   Market pay (pref `market_pay`, off by default): the next missing public BLS figure for live jobs, at most one
   BLS query a cycle, cache first, never an AI call (`paydata.fill`).
3. Follow-ups: nudge about quiet applications; draft a follow-up when a contact is known (a plain template when no
   AI provider is configured, still proposed through the inbox).
   Desktop notifications, if you turned them on (pref `desktop_notifications`): the day's agenda once, an interview
   within 2 hours, a deadline tomorrow; each fires once (recorded in the `seen` table).
   Contacts whose next touch has come are listed on Today and in the daily agenda; the loop never drafts anything for
   them. Mail from a contact's exact address, and approved mail sent to it, update that contact's last touch.
   Suggested emails (thank-you after a round, follow-up, unanswered recruiter mail, offer check-in, referral ask) are
   computed from the tracker with no AI call, listed on Today and counted in the daily agenda; nothing is drafted until
   you click Draft options.
4. Pipeline: every live job's steps are refreshed (work done by hand is adopted, the board summary written, questions
   no step needs any more are dropped). With Autopilot on, steps whose tool is on auto run within the AI budgets and
   the rest are proposed once per job in the Inbox (see "The pipeline and Autopilot" below). A budget that runs out
   shows on the loop line as "pipeline: per-cycle AI budget reached" or "pipeline: daily AI budget reached".
5. Optional Obsidian sync and Friday digest (with your weekly goals' progress when you set any).
6. Update check, every `update_every_hours` (pref `update_mode`: off / notify / auto; see COMMANDS.md >
   Updates). Auto applies only a fast-forward that passes the tests, and never while mail or a send is in flight.
   Setup > Updates sets the mode and the interval, checks and updates on demand and shows the update log; a
   failed update shows under Getting started, and the desktop app offers Restart after a successful one (never
   while an update is still running). An update cut off mid-way is rolled back at the next start; in auto mode a
   version that failed its tests is not retried automatically, and no update is applied while another Lodestar
   process (app, desktop window, loop) is running.
7. Print how many actions are waiting in the inbox.

The master resume (`resumes/master.*`, pass 17) is rebuilt offline, without AI, when profile.md or the profile bank
changed: about 20 seconds after the last save while the app runs, and in each cycle of `lodestar run` / `app` /
`desktop` for edits made outside the app. It only reads saved files and only writes `resumes/master*`, so it never
touches text you are editing, and it never rewrites a resume already tailored for a job (the drawer shows "Profile
changed since this resume was made" instead, only when a section that resume used changed; a studio version is
compared with the profile it was built from, not the profile on the day you used it). The Profile tab's card follows
the rebuild by itself.

Sending mail needs a connected mailbox (Setup > Connect email: Sign in with Google / Microsoft or an app password; or
`lodestar email signin google|microsoft` / `lodestar email connect`; see CONNECT.md). Without one, approvals of email
items fail with a clear error and the draft stays visible so you can copy it. A signed-in mailbox whose sign-in expired
stops the email check with "Sign-in expired: sign in again"; the rest of the cycle still runs.

Every app start (`lodestar ui`, `app`, `desktop`) re-checks the linked AI keys and the mailbox once, in a background
thread that never blocks or stops the start (`LODESTAR_NO_STARTUP_CHECK=1` turns it off). Offline reads as "couldn't
reach" and never marks a working key or mailbox as broken.

## The pipeline and Autopilot

Each tracked job moves through 13 steps (`pipeline.py`), shown in the job drawer's Pipeline group and by
`lodestar pipeline status JOB`:

| Step | What it does | Tool (Autopilot) | Runs unattended |
|---|---|---|---|
| Fit check | the deterministic fit score (fit.py; one AI judgement as its AI part only when fit_check is on auto); skip under auto_track_min_score (asks for the JD when there is none) | fit_check | yes |
| Research | company research pack from public pages | research | yes |
| Tailor resume | the resume studio builds the job's resume from your facts (pref `resume_request`, your look, one page; every AI rewrite checked) and uses it; within the run's AI budget (one call left: no AI shortening call, the plan is trimmed) | tailor | yes |
| Cover letter | from the tailored resume, research and fit check | cover_letter | yes |
| Form answers | the job's form questions: closed-form ones from your answers, open-ended ones drafted | form_answers | yes (never eligibility or EEO) |
| Apply | you send it and click Mark applied | none | no |
| Confirmation | the application-received mail (confirmation number) | email step | observed |
| Follow-up | the loop's follow-up cadence | followup | loop step |
| Schedule | interview rounds (mail and the Rounds group) | email step | observed |
| Interview prep | builds the job's sourced practice set (the company's own pages on their 30-day cache, one AI call within the run's budget), then the prep pack once an interview is booked | interview_prep | yes |
| Thank-you | drafted after a round; always waits in the Inbox | thank_you | yes (draft only) |
| Offer | offer evaluation | none | no |
| Close | accepted, rejected or withdrawn | none | no |

**States**: done, ready, waiting on you (a question, an Inbox item, an approval) or on the employer (a reply, a
confirmation), stale, blocked (no AI provider), error (with Retry), running, todo (an earlier step first), later (a
later status), skipped (by you, or n/a). A step reads earlier steps' results (the letter reads the tailored resume and
the research pack; form answers read both; prep reads the next round). When something a done step was built from
changes (the JD, your profile, the resume, the research, your stories, a new round) the step reads **stale** (Tailor
resume: only when a profile section that resume used changed, the drawer's 'profile changed' badge): it is
never redone on its own, only by Re-run (or Run to with "include stale steps"). Work done by hand is adopted as done.

**Questions**: a step that lacks a fact asks once (Inbox > Questions for you, the drawer, `lodestar pipeline
questions`) instead of guessing. One answer serves every job and step that asks the same question (common screening
questions share one canonical key), or only this job. Eligibility, work-authorization and EEO questions are never
AI-drafted (however the form words them: "legally eligible to work in", "18 years or older" count too). They are
filled in only from answers you wrote (under Answers, in the CLI, or by answering the question), never from an
approved AI draft or an answer saved before pass 16.5 (asked once more), and never shown to an AI prompt, tagged or
not. Questions that only look alike keep their own key (pending charges vs a conviction, sex vs gender, the start date
of your current role vs your earliest start date). Private answers never reach employer text, and a salary answer
equal to your floor is refused. A fact you give for one job only is used when that job's answer is redrafted. Re-run
of Form answers looks every saved answer up again (a changed or newly private one is honoured). "I'll fill it in
myself" lets the step go on without it.

**Autopilot** (Setup > Autopilot, `lodestar pipeline autopilot on|off`) is off by default. On, each monitor cycle
advances at most `autopilot_jobs_per_cycle` jobs (default 3) within `autopilot_ai_per_cycle` (6) and
`autopilot_ai_per_day` (30, a rolling 24 hours, approved runs included) AI calls. A step whose tool is **auto** runs; a
step that is enabled but not auto is covered by **one** Inbox approval per job for its next batch of steps (`run_to`):
its card estimates the AI calls (one per open-ended form question the batch drafts, at most 8) and lists the saved
answers it fills in on the form. An approved batch spends from the daily budget; once that is used up the rest waits
(Setup > Autopilot says so). A disabled step is left for you. Jobs whose fit check says skip are left alone. A failed auto step is retried once on a
later cycle; a step you answered a question for continues on the next cycle. Never unattended: applying, offers,
closing, sends, status changes and job adds (those still go only through the Inbox), re-running a stale step, and
answering eligibility or EEO questions. Pipeline bookkeeping goes to its own run log (Setup > Autopilot > Show the
run log, `lodestar pipeline log`), never to the job timeline, so the follow-up clock is untouched; building a
document (fit check, research, tailored resume, cover letter, interview prep) does not move it either, by a click or
a step. The Confirmation step counts only trusted confirmation mail, and only its reference is quoted in a follow-up.
The Follow-up step says no follow-up is needed while an interview is booked.

**Interview prep and the practice set.** The prep step first builds the job's practice set: the questions you logged
for the company, the ones in your pasted notes, questions derived from the company's own public hiring and values
pages, the job description's and the general bank. The pages come from the company's website: the job URL's host when
it is registered under the company's name (never a job board, ATS or ATS customer subdomain), or the one you typed. Without one, the step asks "What is
<company>'s website?" (a non-blocking question, shared by every job at that company; the step runs without the pages
meanwhile). Pages are read with robots.txt respected, at most 12 requests per company (robots.txt and every redirect count; a
redirect is followed only on the company's own site after its robots.txt), and reused for 30 days: under
Autopilot a prep run never forces a re-read (only Refresh in the drawer or `lodestar interview questions ID --refresh`
does). LinkedIn, Indeed, Glassdoor, ZipRecruiter, Blind and SimplyHired are never fetched, on any path or redirect,
and a link you paste with your notes is stored as a citation, never opened. One AI call turns the material into
questions; the code checks each quote against its source and sets the tag (the AI cannot claim a question is one you
logged), and questions the AI says a company is "reported" to ask are off unless you turn on the `reported_questions`
preference. A new paste, a newly logged question or a page refresh that changed the pages' text makes the prep step read
stale (re-reading unchanged pages does not, and neither does the step's own first read); it is never redone on its own. Readiness (the drawer's 0-100 preparation score and its chance band) is computed live for you: it is never
put into a step's output, an employer-facing draft, or an AI prompt (except "Explain my readiness", which sends the
five preparation parts and never your fit score).

## Contact capture

Replies and follow-ups need a human address. lodestar records the sender of the first human (non no-reply) email about
a job as its contact. Set one yourself in the job drawer (Admin > set contact) or with
`lodestar jobs contact ID email --name "Jane Doe"`. With a contact, Draft reply and email outreach are proposed for
sending through the Inbox like follow-ups; the checklist counts a follow-up or thank-you as done only once it is sent.
Setting a job's contact also files the person under Contacts (linked as recruiter). The reverse never happens: a
contact (LinkedIn import or typed in, linked to the job or not) is never made a job's contact and plays no part in
deciding whether mail is trusted. Ask for referral (job drawer > People) proposes an email to the contact's own
address, always reviewed in the Inbox.

## Security model of the local UI

- The page embeds a per-launch token; every `/api/*` request must carry it (`X-Lodestar-Token` header). A web page
  you visit cannot call your inbox, tools, or vault routes: it gets 403.
- Only `/api/capture` and `/api/autofill` accept cross-origin calls, and only with `?t=<token>`, which the
  bookmarklets receive when you drag them from the Setup tab. The capture token persists across restarts; delete
  `~/.lodestar/capture.token` to revoke it and re-drag.
- Mail that failed classification (provider outage) is left unread for the next run instead of being skipped.
  A reply in a thread Lodestar started, or mail from a live job's stored contact address, is scanned even without a
  hiring keyword ("Sounds good, talk Tuesday."). With no AI provider such tied mail is still filed under its job as
  `unclassified` (no status move, round or reply); other mail waits unread until a provider works.
- A message is matched to a job by something Lodestar already holds for it: the stored contact address (or its
  corporate domain), our own thread (below), or the full registrable domain of the job's posting URL when that URL is
  on the company's own site (`careers.acme.com/jobs/1` vouches for `acme.com` and its subdomains). Those are strong
  ties, and only they act without review. A domain that merely names the company (`acme.xyz`, `acme.co.uk` for a job
  whose site is `acme.com`), a thread reply from someone else, or the company name the classifier read is a weak tie:
  the mail is filed under the job, but it never becomes the contact, never books an interview round, and its status
  moves and replies wait in the Inbox. Job-board URLs (greenhouse.io, linkedin.com) and ATS feed slugs vouch for no
  domain. Free-mail senders (gmail.com, outlook.com, ...) count only when they are the exact stored contact.
- Mail is linked to jobs. Every relevant scanned message (anything not classified `other`) and every message Lodestar
  sends is kept in the `mail` table, deduplicated by Message-ID, and shown in the job drawer's Mail group (both
  directions, trusted / unverified). A reply whose `In-Reply-To` or `References` names a Message-ID Lodestar sent is
  filed under that job (`thread`). The thread counts as a strong tie only when the sender is the address Lodestar
  sent to, or shares its corporate (non-free-mail) domain, **and** the mail Lodestar sent went to someone already
  trusted (it answered trusted mail, or it went to the job's stored contact), **and** the job is not rejected or
  withdrawn. A reply you approved to an unverified sender (a mail you linked by hand or tracked as a new job) vouches
  for nobody, so that sender's answer stays unverified. A threaded reply on a closed job is filed, never trusted: no
  round, no reply drafted. Trust still needs aligned DKIM/DMARC and agreement with the stored contact. Anyone can copy
  a Message-ID, so a reply from another domain is filed under the job but stays unverified and never acts unreviewed.
- A reply Lodestar drafts to unverified mail is marked "unverified sender" on its Inbox card, and approving it sends
  the mail only: it never moves the job (an offer reply's status-on-send is dropped).
- Relevant mail no job claims is listed under Inbox > Unmatched mail (`lodestar mail list --unmatched`). Link to job
  files it (it never sets the contact or makes the sender trusted); Track as new job adds the job at once, since it is
  your click, without a contact (mail about a company you do not track yet is never trusted); Dismiss drops it. The
  "track this company" proposal the same mail raised in the Inbox is tied to it by Message-ID: tracking or linking the
  mail closes the proposal, and approving the proposal files the mail under the new job, so you never get two jobs.
  Deleting a job deletes its mail records too. Exports include the mail table (CSV formula cells neutralised).
- `council_providers` limits which providers receive your profile: the council, idea crafting and the default provider
  (a `provider` pref or `LODESTAR_PROVIDER` outside the list stops with an error; names compare without case, so
  `Anthropic` = `anthropic`). Only an explicit `-p NAME` on one
  command overrides it. `backup` keeps the last 7 nightly zips.

### After the ECC and security reviews (2026-11-04)

- Three credentials: the page token (header only) drives the full API; the bookmarklets carry a separate capture token
  that works only on `/api/capture` and `/api/autofill` (and only while the `bookmarklets` pref allows it: auto turns it
  off once a browser extension is paired); a paired browser extension signs each `/api/ext/*` request with its own
  secret (HMAC, 120 s, pinned `chrome-extension://` Origin, bound to the port the popup dialled, so a program on
  another port cannot relay it), which works on no other route and gets no CORS headers.
- The server refuses any request whose `Host` header is not this loopback address (DNS-rebinding defence) and any
  POST that is not `application/json`.
- Actions triggered by inbound mail (status moves, replies) run automatically only when the message carries
  `Authentication-Results: dkim=pass` aligned with the sender **and** is strongly tied to the job (contact, thread or
  the company site Lodestar holds; see above); otherwise they wait in the inbox even if the tool is set to auto.
  Recruiter outreach about a company you do not track yet always waits in the inbox instead of creating a job
  (pass 16 review: `acme.xyz` can claim to be Acme as easily as `acme.com`), and its sender is never the contact.
- Approving an item claims it atomically: a double-click or a CLI/UI race cannot send twice. Rejecting a decided item
  is a no-op, so the record of a sent mail is never overwritten.
- `council_providers` is a hard boundary: synthesis and the default provider come from the list, and a list that
  matches no configured provider stops with an error instead of widening to everyone.
- Page fetches (watches, job descriptions, research) refuse loopback, link-local and private addresses and re-check
  every redirect; `LODESTAR_ALLOW_PRIVATE_URLS=1` opts an intranet careers page back in.

### Cadence, conflicts, judge (pass 8)

- `followup`: nudge at every `followup_days`; after three nudges the loop proposes `withdrawn` ("ghosted") instead of
  nudging forever. A proposal, so it waits in the inbox unless the tool is auto. "Quiet" counts real activity only:
  Inbox proposals, rejections, failed sends, unsent drafts and unverified mail do not restart the clock
  (`db.BOOKKEEPING`).
- Interview replies see your booked interviews (interview rounds with a time) and are told never to accept or propose a time
  within 90 minutes of one; approving a reply whose chosen slot still clashes is refused before anything is sent (the
  item stays in the Inbox: pick another slot or clear it), and on auto it waits in the Inbox instead.
  The same job's own rounds are not a clash (the slot its invite booked can be accepted). A new time for a job whose
  only upcoming round is still pending moves that round ("rescheduled from ..." in its notes) instead of adding one.
- `council_judge`: when on and two or more providers are allowed, the second provider audits the synthesis.

### Draft options and suggested emails (pass 16)

- One AI call per set of options (up to 3), whatever the kind; suggestions cost none. Usage is recorded in
  `usage.jsonl` like every other call.
- Exactly one option is recommended, with a one-line reason tied to the situation. Without a provider, follow-up,
  thank-you, withdrawal, offer check-in, referral ask and counter-offer options are the offline template; other kinds say they need
  a provider, and so do rewrites.
- Picking an option never sends anything: mail is proposed through `approvals.propose` with review (it waits in the
  Inbox even when the tool is on auto), to the recipient Lodestar already knows (the job's contact, the sender of the
  mail being answered, the contact you ask for a referral). The page cannot choose the recipient.
- On a pending Inbox email, Options and rewrite chips replace only the subject and body; recipient, In-Reply-To, job,
  chosen time and status-on-send stay as proposed, and the item stays pending (`POST /api/approvals/ID/edit`, or
  `lodestar draft rewrite --pending ID`). A decided item cannot be edited.
- Prompts carry `candidate_text(private=False)` (no Preferences, no salary floor); a reply's original mail (sender,
  subject, text) and a pending draft go in fenced as untrusted data. Every option, rewrite, pick and pending edit passes
  the salary-floor guard (`profile.employer_safe`): a draft naming the floor is dropped or refused, never proposed.
  So does an email you edit in its Inbox card and approve; there only the recipient, subject, body and chosen time
  can change (job, status-on-send and the unverified flag stay as proposed).
- Mail trust is unchanged: replying to a mail does not make its sender trusted or the job's contact.
- "Dismiss for now" snoozes a suggestion for 3 days through the `seen` table (`suggest:JOB:KIND`).

### AI recommendations, Full AI and Undo (pass 19)

- Every tab and card that holds your own content (profile.md sections, the profile bank, a job's details and
  documents, the answer bank, STAR stories, contacts, saved searches, Today, Insights, Inbox drafts) has an AI
  toolbar: **Recommend** (one AI call; nothing changes), **Apply suggestions** (writes only the cards you ticked),
  **Full AI** (Recommend, then writes every suggestion that passes the guards) and **Undo AI changes**. Same from the
  terminal: `lodestar advise SCOPE [TARGET]` with `--apply`, `--auto`, `--undo`, `--history`.
- Full AI is not a tool switch and never acts on its own: it runs only when you click it (the first time it asks you
  to confirm). While it writes, every path that sends mail, submits, changes a job's status, adds a job, proposes or
  approves an Inbox item, adds a watch or a watched company, or writes settings, the vault or automation refuses
  (`config.full_ai_check`). Today, Insights and new saved searches / companies are advice only; adding one stays your
  click. An Inbox draft it improves stays pending until you approve it.
- Guards on both Apply suggestions and Full AI: a field you changed since the suggestion is skipped (stale); text an
  employer reads gets no invented fact (skill, number, title, degree, term, link) and never your salary floor or
  Preferences; eligibility / EEO and private answers are never sent to a model or changed; a form answer may not add a
  question heading, and the pipeline's "check this" note under an answer always stays (an answer marked that way gets
  no credit for its own claims); a job's or contact's fields may not gain a link, email address or phone number the
  field did not hold (a posting is third-party text: an instruction hidden in it cannot plant its own contact route in
  your to-dos), and notes keep every line you wrote. Postings, mail and company pages go into prompts fenced as data.
- Every write is logged as one batch (Setup > Data > AI changes, `lodestar advise --history`). Undo puts a batch back
  exactly, newest first; a field you changed since keeps your version. profile.md changes go through the usual
  snapshot, so profile-history/ has every version too.
- Text you typed and have not saved is never thrown away by an AI change: the job drawer is not re-rendered over it
  (a message says the change is saved), and on Profile the editor keeps your text; Save is refused until the editor
  matches the file again (copy your text out and reload, or click Undo AI changes and Save works).
- The AI help menus ("AI help" on Board, a job drawer, Contacts, each story, Insights, Search, Monitor, Setup and
  Tools) answer one question each with one AI call and change nothing; Fill STAR from my notes puts its suggestions in
  the story's toolbar, so only Apply suggestions writes them. Without an AI provider every AI control says it needs
  one (a local Ollama model counts). Usage is recorded in `usage.jsonl` like every other call.
