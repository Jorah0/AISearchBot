# Lodestar UI redesign: audit, competitor patterns, recommendations (2026-11-13)

Source: a read-only research pass over `lodestar/static/{index.html,app.js,app.css}`, `tests/e2e/*` and the leading
tools' public pages. This is the input to the UI plan; the plan decides.

## Current UI and pain points
- 14 flat sidebar tabs (Board, Inbox, Contacts, Jobs=`search`, Careers, Monitor, Ideas, Answers, Coach, Insights,
  Profile, Studio | Tools, Setup); Unicode glyph icons; top bar with stats, loop line, 5 pills.
- Board is home + tracker + add form: the kanban starts below ~8 stacked blocks (Today, onboarding, upcoming, funnel,
  variants, filters, bulk).
- Buried: offers + counter in Insights, run log in Setup > Autopilot, market rates in Setup, digest in Monitor;
  Setup has 17 panels, Preferences live in Tools.
- Job drawer: ~18 groups, ~45 buttons in one scroll, no hierarchy or primary action.
- Inconsistent: inline onclick, 3 filter-bar styles, arbitrary button weights, long `.muted` paragraphs everywhere.
- Jargon: council, JD coverage, auto_track, watches, monitor loop, tool enabled/auto, gap check, variants, funnel,
  bookmarklet, EEO, O*NET, DKIM/DMARC, floor.
- Dark only; inputs `outline:none` (weak focus); weak type hierarchy (h3 13px uppercase dim).

## E2E selector contract (keep stable)
- `harness.go(tab)` clicks `nav button[data-tab="X"]`, waits for `section#X.on` (~91 uses, all 14 tabs); palette
  "Go to <label>" comes from those buttons.
- Drawer: `open_job()` clicks `.card[data-id=N]`, waits `#drawer.open` (68 sites); group ids `#jFit #jBoost #pGroup
  #jPay #jIntel #jPeople #jReady #jMatchG #jDocs #jComm #jActivity`, `#jStatus #docTabs #jOut #jOpts #jQsrc`.
- Board: `.col[data-s]`, `Board.drag`, `#fView`, `#bulk`. Hooks: `data-adv-slot`, `data-ai-menu`, `data-advp`,
  `data-aim`, `data-q`, `data-src`, `data-kind`.
- Classes read: `.card .pill .chip .row .opt .advcard .advmsg .sheet .review .career-card .ajrow .close`.
- Viewer `#viewer #vwFrame #vwTabs #vwClose`; palette `#palette #palQ #palList`.
- 298 `get_by_role` + 133 `has_text` (button names are contract: renaming one breaks tests).
- `overflow()` must stay empty at 420px. 523 distinct `#id` tokens (438 static UI ids).

## Competitor patterns (cited)
- Teal (tealhq.com, /tools/job-tracker): tracker + resume builder share the job; Bookmarked -> Applied ->
  Interviewing -> Offer kanban; excitement, keywords per job, stage email templates, follow-ups, spreadsheet view.
- Huntr (huntr.co/product/job-tracker): kanban; cards with timeline, notes, contacts, docs, to-dos; metrics.
- Simplify (simplify.jobs/copilot): profile once, auto-saved applications, JD resume score.
- Careerflow (careerflow.ai/job-tracker): labels, deadlines, follow-up from the tracker, tailoring from the job.
- Jobscan (jobscan.co): one match rate with a target (75%); Searchability -> Hard -> Soft -> Tips; click a skill to
  see it in the JD; exclude an irrelevant skill.
- LinkedIn My Jobs: Saved / In progress / Applied / Archived in one filter.
- Welcome to the Jungle / Otta: preferences first; triage "Skip, save, apply"; learns from skips.
- Rezi / resume builders: per-section score, assistant per section, live preview.
- Linear (linear.app/now/how-we-redesigned-the-linear-ui): less sidebar noise, aligned icons, LCH themes from base /
  accent / contrast, "G then X" go-to keys, Inbox top-level. Notion: Quick Find shows recents first.

## Recommended IA: 7 sections + Settings (every current tab becomes a sub-tab; section ids kept)
| Section | Sub-tabs | Absorbs |
|---|---|---|
| Today (new home) | - | Today panel, Getting started, upcoming interviews, suggested emails, top fits, boosters, goals |
| Inbox | (inbox) | approvals, questions, mail, codes |
| Pipeline | Board/Table (`board`), People (`contacts`) | funnel, variants, bulk |
| Discover | Search (`search`), Watches & companies (`monitor`), Careers (`careers`) | alerts, digest, All jobs |
| Resume | Profile (`profile`), Studio (`studio`) | bank, import, master |
| Prepare | Answers & stories (`answers`), Coach & mock (`coach`), Ideas (`ideas`) | |
| Progress | Insights (`insights`) | offers, activity log |
| Settings (gear, bottom) | Setup (`setup`), Tools & preferences (`tools`) | |
Implementation: groups render sub-nav `<button data-tab=...>` with the current labels; `go(tab)` opens the parent.

## Today spec
Greeting + one next-best action; Due now; Interviews 48h with readiness; Waiting on you (Inbox, questions);
Suggested emails; New fits to triage (Skip / Track / Open); This week goal bars; Boosters (collapsed). Empty blocks
hide. Keep `#today #onboard #upcoming`.

## Drawer
Sticky header: company, title, `#jStatus`, chips (fit, class, coverage, deadline, next step), one primary action by
stage, posting link, close. Body phase 1: sticky section index (Overview: Details, Fit, Boost, Pipeline | Apply:
Match, Documents | Talk: Communicate, Mail, People | Interview: Readiness, Rounds, Intel, Pay | Log: Activity, Admin)
with ids unchanged. Phase 2 (later): real tabs with a harness `drawer_tab()` helper.

## Onboarding
Skippable 4-step wizard in Today (roles + location -> resume import -> AI key or local only -> email / extension),
progress checklist until done; keep `#onboard`. Empty states: one sentence + one primary button.

## Visual principles
OKLCH tokens for dark + light (`prefers-color-scheme` + `data-theme`), AA status colours; Inter / system UI 13px base,
scale 12/13/14/16/20/24, sentence-case h3 14px/600; 4px spacing grid; one filled primary per panel; inline SVG icons;
one-line hints with a "?" disclosure; 2px `:focus-visible` ring.

## Prioritised changes (impact / effort)
1 Today home (H/L) - 2 two-level nav (H/M) - 3 drawer header + section index (H/L) - 4 help-text diet + plain words
(H/L, renames with their tests) - 5 Settings consolidation (M/M) - 6 onboarding wizard (H/M) - 7 light theme, tokens,
focus ring (M/L) - 8 board filter popover + quick add (M/M) - 9 G-then-X keys, ? cheat sheet, J/K (M/L) -
10 Discover unified results + triage (H/H) - 11 Studio split preview + section score (M/H) - 12 drawer real tabs (M/M).
