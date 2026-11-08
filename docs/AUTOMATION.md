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
| `auto_track` | AI-score new listings from watches/searches against your profile; propose tracking those at or above `auto_track_min_score` | on, manual |
| `answers` | save the answers it drafts for application-form questions into the answer bank | on, manual |
| `calendar` | write .ics files for interview dates found in mail | on, auto |
| `obsidian_sync` | mirror the tracker into your vault after each monitor cycle | off |
| `digest` | email the weekly digest to `LODESTAR_NOTIFY_EMAIL` on the first cycle from Friday on (a missed Friday catches up on the next cycle); without that address a one-line alert says it is ready | off |
| `posting_check` | weekly: re-check saved jobs from Greenhouse / Lever / Ashby boards; propose `withdrawn` ("posting removed") for ones whose posting vanished. Always waits in the inbox, even on auto | on, manual |

## The inbox

```powershell
lodestar inbox                 # what is waiting
lodestar inbox -v              # with the drafted email / payload
lodestar approve 12            # execute as drafted
lodestar approve 12 --subject "Re: Interview" --body edited.txt
lodestar reject 12 --reason "already replied"
```

In the UI the Inbox tab shows each item with the email fields editable before **Approve & send**.

A counter-offer (`lodestar offers counter`, Insights > Offers) is always proposed with review, even when
`email_reply` is on auto, and never contains your salary floor, Preferences or offer notes.

Insights, weekly goals and the activity log count only what you did: an approved and sent item counts, a
pending, rejected or failed one does not, and nothing the loop adds on its own (an auto-tracked save) is an
application.

Executors are the only code that sends mail, changes status, or adds jobs on lodestar's initiative, and they all live in
`lodestar/approvals.py`, so the rule cannot be bypassed by a new feature by accident.

## What a full automatic cycle does (`lodestar run` / `lodestar app`)

1. Email check: classify new mail, propose or apply status changes, capture the sender as the job's contact, write
   .ics for interviews with a stated time from a trusted sender (each also recorded as an interview round; a date
   without a time, often a reply-by date, or an unverified sender records only a timeline note), draft replies for
   confirmations / assessments / interviews / offers.
2. Watches: diff career pages (only where robots.txt allows; a disallowed page is skipped with one alert); new
   listings from saved searches (with their saved filters) and from watched companies' Greenhouse / Lever / Ashby
   boards (one request per company; a newly watched board's open roles are a baseline with one summary alert) are
   alerted once, AI-judged, and strong fits proposed. Listings that look stale
   are not proposed. Weekly, saved jobs from those boards are re-checked and a removed posting is proposed for
   `withdrawn` (tool `posting_check`, always via the inbox).
3. Follow-ups: nudge about quiet applications; draft a follow-up when a contact is known (a plain template when no
   AI provider is configured, still proposed through the inbox).
   Desktop notifications, if you turned them on (pref `desktop_notifications`): the day's agenda once, an interview
   within 2 hours, a deadline tomorrow; each fires once (recorded in the `seen` table).
   Contacts whose next touch has come are listed on Today and in the daily agenda; the loop never drafts anything for
   them. Mail from a contact's exact address, and approved mail sent to it, update that contact's last touch.
   Suggested emails (thank-you after a round, follow-up, unanswered recruiter mail, offer check-in, referral ask) are
   computed from the tracker with no AI call, listed on Today and counted in the daily agenda; nothing is drafted until
   you click Draft options.
4. Optional Obsidian sync and Friday digest (with your weekly goals' progress when you set any).
5. Print how many actions are waiting in the inbox.

Sending mail needs a connected mailbox (Setup > Connect email, or `lodestar email connect`). Without one, approvals of email items fail
with a clear error and the draft stays visible so you can copy it.

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
  (a `provider` pref or `LODESTAR_PROVIDER` outside the list stops with an error). Only an explicit `-p NAME` on one
  command overrides it. `backup` keeps the last 7 nightly zips.

### After the ECC and security reviews (2026-11-04)

- Two tokens: the page token (header only) drives the full API; the bookmarklets carry a separate capture token that
  works only on `/api/capture` and `/api/autofill`. A job board that reads the bookmarklet URL learns nothing useful.
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
  within 90 minutes of one; approving a reply that still clashes sends the mail but skips the calendar file and says so.
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
