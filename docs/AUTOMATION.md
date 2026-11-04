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

## The inbox

```powershell
lodestar inbox                 # what is waiting
lodestar inbox -v              # with the drafted email / payload
lodestar approve 12            # execute as drafted
lodestar approve 12 --subject "Re: Interview" --body edited.txt
lodestar reject 12 --reason "already replied"
```

In the UI the Inbox tab shows each item with the email fields editable before **Approve & send**.

Executors are the only code that sends mail, changes status, or adds jobs on lodestar's initiative, and they all live in
`lodestar/approvals.py`, so the rule cannot be bypassed by a new feature by accident.

## What a full automatic cycle does (`lodestar run` / `lodestar app`)

1. Email check: classify new mail, propose or apply status changes, capture the sender as the job's contact, write
   .ics for dated interviews, draft replies for confirmations / assessments / interviews / offers.
2. Watches: diff career pages; new listings from saved searches are AI-judged and strong fits proposed.
3. Follow-ups: nudge about quiet applications; draft a follow-up when a contact is known.
4. Optional Obsidian sync and Friday digest.
5. Print how many actions are waiting in the inbox.

Sending mail needs `IMAP_USER` / `IMAP_PASS` (SMTP uses the same login). Without them, approvals of email items fail
with a clear error and the draft stays visible so you can copy it.

## Contact capture

Replies and follow-ups need a human address. lodestar records the sender of the first human (non no-reply) email about
a job as its contact. Set one yourself with `lodestar jobs contact ID email --name "Jane Doe"`.

## Security model of the local UI

- The page embeds a per-launch token; every `/api/*` request must carry it (`X-Lodestar-Token` header). A web page
  you visit cannot call your inbox, tools, or vault routes: it gets 403.
- Only `/api/capture` and `/api/autofill` accept cross-origin calls, and only with `?t=<token>`, which the
  bookmarklets receive when you drag them from the Setup tab. Re-drag them after restarting the app.
- Mail that failed classification (provider outage) is left unread for the next run instead of being skipped.
- Company matching uses whole-word tokens of the classifier's company or the sender's domain, never substrings of
  the free-text From line.
- `council_providers` limits which providers ever receive your profile. `backup` keeps the last 7 nightly zips.
