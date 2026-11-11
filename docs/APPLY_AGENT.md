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
  Such a job needs the employer's own application link (Application link / `jobs set ID apply_url=...`).
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

A visible CAPTCHA, a sign-in page or a code request stops the agent and brings the window to the front: do it there,
then press Continue (`lodestar apply-agent continue RUN`). It never types into a password field, never reads codes from
your mail and never touches a CAPTCHA. Nothing hides that the window is automated, so some sites may ask for an emailed
code or file the application as spam.

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
before running the agent (one browser per profile). `lodestar apply-agent forget` deletes it. On Windows the cookies are
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
