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
| `digest` | email the weekly digest on Fridays | off |
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
4. Optional Obsidian sync and Friday digest (with your weekly goals' progress when you set any).
5. Print how many actions are waiting in the inbox.

Sending mail needs `IMAP_USER` / `IMAP_PASS` (SMTP uses the same login). Without them, approvals of email items fail
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
- A message is matched to a job by the stored contact address, then the sender's company domain
  (`careers.acme.com` -> Acme), then the company name the classifier read. Only contact or domain matches act without
  review. Free-mail senders (gmail.com, outlook.com, ...) count only when they are the exact stored contact.
- `council_providers` limits which providers ever receive your profile. `backup` keeps the last 7 nightly zips.

### After the ECC and security reviews (2026-11-04)

- Two tokens: the page token (header only) drives the full API; the bookmarklets carry a separate capture token that
  works only on `/api/capture` and `/api/autofill`. A job board that reads the bookmarklet URL learns nothing useful.
- The server refuses any request whose `Host` header is not this loopback address (DNS-rebinding defence) and any
  POST that is not `application/json`.
- Actions triggered by inbound mail (status moves, replies) run automatically only when the message carries
  `Authentication-Results: dkim=pass` aligned with the sender **and** is tied to the job by contact address or company
  domain (see above); otherwise they wait in the inbox even if the tool is set to auto. Free-mail or unauthenticated
  recruiter outreach waits in the inbox instead of creating a job.
- Approving an item claims it atomically: a double-click or a CLI/UI race cannot send twice. Rejecting a decided item
  is a no-op, so the record of a sent mail is never overwritten.
- `council_providers` is a hard boundary: synthesis and the default provider come from the list, and a list that
  matches no configured provider stops with an error instead of widening to everyone.
- Page fetches (watches, job descriptions, research) refuse loopback, link-local and private addresses and re-check
  every redirect; `LODESTAR_ALLOW_PRIVATE_URLS=1` opts an intranet careers page back in.

### Cadence, conflicts, judge (pass 8)

- `followup`: nudge at every `followup_days`; after three nudges the loop proposes `withdrawn` ("ghosted") instead of
  nudging forever. A proposal, so it waits in the inbox unless the tool is auto.
- Interview replies see your booked interviews (interview rounds with a time) and are told never to accept or propose a time
  within 90 minutes of one; approving a reply that still clashes sends the mail but skips the calendar file and says so.
- `council_judge`: when on and two or more providers are allowed, the second provider audits the synthesis.
