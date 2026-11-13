# Apply agent

Lodestar can fill a job's application form for you in its own browser window and, depending on the mode, stop before
Submit, wait for your approval in the Inbox, or submit on its own within strict gates. This page covers the engine
(pass 22). Code: `lodestar/apply_agent.py` (policy, plan, runs), `lodestar/apply_ats.py` (the browser, the guard, the
one write path).

## Install

`pip install -e .[apply]` (the `all` extra includes it). It drives your installed Edge or Chrome; no
`playwright install`. It needs the source install (it reuses `extension/matcher.js` and `extension/content.js`).
`lodestar apply-agent status` says what is missing.

## Modes

| Mode | What happens at the last page |
|---|---|
| stop (default) | The form is filled; you check the window and press Submit yourself. Lodestar watches for the confirmation page and records it (run `by_user`); it changes no job status: Mark applied is yours |
| review | Screenshots and every field go to the Inbox (`submit_application`). After you approve, the agent re-reads the form (a change you made in the window is proposed again), ticks the consent boxes your approval covered, clicks Submit once, and on the confirmation page the job moves to applied with the evidence |
| auto | Off by default. Needs the `apply_agent` tool on auto, the ATS on your list (`apply_agent_auto_ats`, empty by default), fit >= `apply_agent_min_fit`, under `apply_agent_daily_cap` today, and 2 applications you approved that went through on that ATS. Any flag, consent box, AI-written value, host you added or form error at the last page sends it to review |

A link that is not on a known application system (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, iCIMS,
Taleo) runs in stop mode only. Bulk and the pipeline's Apply step use your default mode.

## Where it may go

- **Never**: LinkedIn, Indeed, Glassdoor, ZipRecruiter, SimplyHired (their terms forbid bots), in any page, popup or
  while you drive a handoff. Three layers: the request route aborts them, the agent's browser cannot resolve their
  names (Playwright's route does not see a server redirect's next hop), and a post-navigation check ends the run.
  Such a job needs the employer's own application link (Application link / `jobs set ID apply_url=...`). When it has
  none, queueing it looks for the posting first (Finding the posting, below).
- A run loads only its exact hosts: the application link's host (plus the other Greenhouse board host). When a page
  wants another host the run asks you: **Continue here** allows that exact host for this run; Stop ends it.
- Service workers are blocked in the agent's browser (a route never sees what a worker intercepts).

## What it types

Your contact details, work history and education (as the extension would), saved answers whose question matches
exactly, and answers you give to its questions (Inbox > Questions; "this job only" or reusable). Eligibility, legal and
EEO questions come only from answers you wrote; EEO only when included (a required EEO field with nothing included gets
the form's decline option, flagged). Desired salary only from its saved row; the salary floor never. Identity numbers,
dates of birth, bank details and passwords are never filled. The resume is uploaded as a copy named
`First_Last_Resume.pdf`. Page text is untrusted: every safety rule reads the label in Lodestar, not what the page says.

## Handoffs

A visible CAPTCHA or a code request stops the agent and brings the window to the front: do it there, then press
Continue (`lodestar apply-agent continue RUN`). A sign-in page goes to your site account (below), else to you. The form
filler never types into a password field and never touches a CAPTCHA. Nothing hides that the window is automated, so
some sites may ask for an emailed code or file the application as spam.

## Site accounts

Many application systems (Workday tenants, iCIMS and Taleo portals) want an account before the form. Setup > **Site
accounts** keeps one per site (the exact host, so every Workday tenant is its own site): the sign-in link, the username,
when it was created and last signed in, its status (active, needs verification, locked, sign-in failed, or sign-up filled
while you have not pressed Create yet) and the jobs it was used for. The password lives only in the OS keyring (never in
the database, a listing, a backup, an export or a log) and shows only when you press **Reveal**. Never for LinkedIn,
Indeed, Glassdoor, ZipRecruiter or SimplyHired.

- **When an application asks you to sign in**, the agent signs in with the saved account (username and password, typed
  only on that site and the password only into its password field, then the one Sign in button). With no saved account it
  opens the site's Create Account page and fills the sign-up form with your profile's email and a new strong, unique
  password (saved first), and **stops**: you tick the terms or consent box if you agree and press Create yourself. Already
  have an account there? Press **I have an account** and sign in yourself (Save login keeps it for next time). A site that
  says your email is already registered gets the same: the unused password is deleted and sign-in is yours.
- **Verification and 2-step codes**: the code or link the site emails you is picked up from your connected inbox (only
  from senders that pass DKIM/DMARC, memory only, 15 minutes). The agent uses it when you click **Fill code** or **Open
  link** under Site accounts, or by itself only on a site where you ticked "use my inbox's codes and links here without a
  click". A verification link opens only on the account's own site. An authenticator-app code you type in the window.
- **A failed or locked sign-in** is recorded with the site's message and its password-reset link and is never tried again
  by itself (no lockouts): **Reset password on the site** opens it in the plain sign-in window; store the new password
  with **Change password** (or **Generate a new one** to type into the site's form), and the account is tried again.
- **Re-login** signs in again in the agent's window (one click); **Open site** opens the sign-in page in the plain
  sign-in window. **Create an account there** (Save a login, or create an account) runs the sign-up for a link you paste.
  The account window, the agent's worker and the sign-in window share the agent's browser profile, so one waits for the
  other. A CAPTCHA on any of these pages is always yours.
- **General login** (Site accounts > General login for new accounts): one password, and a username if your sites want
  one other than your profile email, kept only in the OS keyring. New accounts use it instead of a generated password,
  and a site that says your email is already registered gets one sign-in try with it (a wrong one is recorded and never
  tried again). One password on many sites means a leak on one opens the others: a generated one per site is safer.
- **Finish sign-ups for me** (pref `accounts_auto_create`, off by default, asks first): the agent ticks only the sign-up's
  terms / privacy box (never a newsletter, marketing or partner box), presses Create, and uses that site's emailed code or
  link by itself. You agree to each site's terms when it does. A CAPTCHA stays yours.
- CLI: `lodestar accounts list | add URL USERNAME | password ID [--generate] | remove ID`.

## Finding the posting

A job tracked from a board (LinkedIn, Indeed, Remotive, ...) has no link the agent may open. Queueing it first looks for
the same posting on the employer's own application system (`apply_find.py`), stopping at the first single match:

1. a link in the job's own text (JD, notes) on a known application system;
2. the company's public board: one you follow (Monitor > Companies), else the company's name as its Greenhouse, Lever
   or Ashby board name;
3. the company website (Intel > company website, or the posting's host when it is the company's): the homepage and its
   careers page (robots.txt first), and the boards they link. When no link is named like a careers page, the AI picks one
   from that page's own links (by number; it cannot make up an address).

A match has the same title; among several, the same city; still several is no match. At most 12 requests; never a
forbidden board. The found link is saved as the job's Application link, the run says where it came from ("check it is
this job"), and it never submits by itself (auto becomes review). Nothing found: the refusal lists where it looked.

## Never twice

The agent refuses a job that is not saved, one with a confirmed or `unknown` run, one with a confirmation email (from
any sender) or a page that says you already applied. A run that clicked Submit and then lost track (Lodestar closed,
no confirmation page) is `unknown`: check your mail or the employer's portal; Lodestar will not submit it again.

## Evidence

`applications/<job>/apply/run-<id>/`: `page-NN.png` per page, `confirmation.png` and `.txt`, `plan.json` (every field,
its source and flags), `summary.md`, `files/` (the uploaded copies).

## The browser profile

`browser-profile/` in your data folder holds the agent's site sign-ins (cookies). It is never backed up or exported.
`lodestar apply-agent login [URL]` opens a plain (not automated) window on it so you can sign in once, by hand; close it
before running the agent (one browser per profile). `lodestar apply-agent forget` deletes it (your site accounts and their passwords stay: Re-login signs in again). On Windows the cookies are
encrypted by the OS for your account; on macOS / Linux they are protected only by the folder's permissions.

## Verified on this machine (2026-11-11, local fictional pages only)

| Check | Result |
|---|---|
| V1 Playwright 1.65 on Python 3.14, Edge via `channel="msedge"`, headful and headless | works; `navigator.webdriver` is true (not hidden) |
| V2 the scan on a strict-CSP page | works (evaluation is not subject to the page's CSP) |
| V3 a cookie set in the plain sign-in window, read by the agent's Edge on the same profile | present after the window closed normally; lost if the window is killed |
| V4 Google sign-in in the automated window | not tried (no real sites); the plain window carries no automation flags |
| V5 route guard with SPA steps (pushState) | works; `service_workers="block"`: `register()` resolves but no worker runs or controls the page; a server redirect's next hop bypasses the route (hence the DNS block) |
| V7 processes after the sign-in window closes / after the agent closes | none left on the profile; a second instance on a profile in use fails with "Opening in existing browser session" (reported as "close the sign-in window first") |
| V6 adapter selectors on live forms | not run: no real job sites are opened by builders |

## Commands and routes

See COMMANDS.md > Apply agent.
