# Competitive parity plan: Simplify, Teal, Huntr, Jobscan

**Goal:** match what the best-known job-search tools do well, keep what Lodestar does that they don't, and skip
what goes against Lodestar's rules (mass auto-apply, automating the big five boards, claiming to "pass the ATS").

**Sources** (checked 2026-11-18): simplify.jobs/copilot; tealhq.com and its pricing page via fastapply.co (2026-10-30);
huntr.co and its Chrome Web Store listing (updated 2026-04-27); jobscan.co/resume-scanner and fastapply.co's Jobscan
pricing (2026-10-30). The prices below are theirs; check them again before quoting them.

## 1. Who does what

| Capability | Simplify | Teal | Huntr | Jobscan | Lodestar today |
|---|---|---|---|---|---|
| Price | Free core; Simplify+ paid | Free; Teal+ $13/wk, $29/mo, $79/qtr | Free; ~$40/mo AI | 5 scans/mo free; $49.95/mo | Free; your own AI keys or local Ollama |
| Save jobs from any site | Extension | Extension (best in class) | Extension "Job Clipper" | Extension | Extension + bookmarklet + **in-app browser (pass 52)** |
| Kanban tracker | Yes | Yes (strongest) | Yes, plus a map view and per-job tasks | Basic | Yes: Board, Table view, lifecycle record, funnel |
| Autofill ATS forms | 100+ portals (Workday, Greenhouse, iCIMS, Taleo, Lever...) | No | One-click, "top ATS" | No | Extension Fill + apply agent (Greenhouse, Lever, Ashby...), with review |
| Auto-submit | Paid Autopilot, weekly allowance | No | No | Auto-apply add-on | Apply agent: per-site daily caps, duplicate check, approval before Submit |
| Match score vs posting | Missing keywords on LinkedIn / Indeed | Top 5 keywords free | Match score | **Match Rate + 30 checks + ATS detected** | Coverage (`ats.py`), Fit score (`fit.py`), lint / audit (`lint.py`): **three separate places** |
| Tailored resume | AI, per role | AI bullets (credits) | AI, per job | Builder | Studio: guarded rewrites, no invented facts, versions |
| Cover letters | Yes | Credits | Yes | Yes | Yes, salary floor screened |
| Interview practice | No | AI practice | Interview tracker | Practice | Mock interview, sourced question sets, readiness |
| Contacts / outreach | Basic | CRM-like | Contact tracker | No | Contacts, warm paths, drafted outreach |
| Mail | No | Email templates | No | No | **Inbox monitoring, classified mail, drafted replies, follow-up clock** |
| Unemployment activity log | No | No | Yes | No | Yes (`lodestar activity`, `activity_weekly_min`) |
| Mobile | App | Web | Web | Web | Desktop / local only (deliberate) |
| Privacy | Cloud account | Cloud | Cloud | Cloud | **Local data, keyring secrets, salary floor never leaves** |

**Lodestar already leads on:** privacy, mail handling, multi-AI council and cross-check, guarded tailoring, pay
data, careers, eligibility gates, the duplicate check, and per-site pacing.

**Where it trails:** the result is not shown in one place. Jobscan's single "Match Report" with a number, a gap
list and a rescan button is clearer than Lodestar's Coverage, Fit and lint, which are spread across the drawer, the
studio and the CLI. Huntr and Teal feel simpler because they have ~5 core views; Lodestar has 17 tabs.

## 2. Gaps, ranked by value to you ÷ effort

| # | Gap | Copied from | Effort | Why it matters |
|---|---|---|---|---|
| G1 | **One Match Report per job**: a score, hard / soft skills, title, education, the detected ATS with its tips, format checks, a rescan as you edit | Jobscan | M | The clearest "what to fix before I apply" view; every piece already exists |
| G2 | **Simpler navigation**: 5 primary views (Today, Jobs, Board, Documents, Prepare), the rest under More | Teal, Huntr | M | Speed of daily use; the user asked for a cleaner UI |
| G3 | **Missing keywords highlighted on the posting page**, on your click (extension + in-app browser) | Huntr, Simplify | S | Tailor while reading the posting |
| G4 | **"I applied" in one click** after an extension Fill or an in-app browser visit, so the Board updates without a trip to the drawer | Simplify, Huntr | S | Keeps the tracker honest for applications you submit yourself |
| G5 | **Per-job checklist** (tasks with due dates, shown on the card and on Today) | Huntr | S | The pipeline covers automated steps, not your own to-dos |
| G6 | **Resume template gallery** with live thumbnails (`render.clean_style` presets) | Teal | S | Choosing a look is currently a settings form |
| G7 | **Map / commute view** of saved jobs | Huntr | M | Needs geocoding: offline US place table first, never a paid API |

## 3. Tasks

Each task: TDD, a `docs/TESTS.md` row, a unit test, and an E2E test when it has UI (CLAUDE.md rules).

### Task 1: Match Report (G1)
- `lodestar/match.py`: `report(job, resume_text=None) -> {score, parts: {hard, soft, title, education, other}, missing,
  ats: {name, tips}, format: [...], note}`. It only combines `ats.coverage`, `lint.lint` / `audit`, and
  `apply_ats.ats_of(host(apply_url or url))`. No AI, no new scoring.
- `data/ats_tips.json`: a short, sourced tip list per ATS (Workday, Greenhouse, Lever, iCIMS, Taleo, Ashby).
- The score is the existing Coverage, labelled "keyword match, not the employer's ATS score" (Jobscan says the same
  about its own Match Rate).
- `GET /api/jobs/<id>/match`; drawer section "Match report" replaces the separate Coverage chip; the studio and the
  viewer rescan on save.
- Tests: `test_match.py` (parts add up, the ATS is detected from apply_url, no floor figure, no AI call);
  `e2e_match.py` (open a job, see the report, edit resume.md, rescan, the score moves).

### Task 2: Navigation (G2)
- Five primary nav items. The other twelve go under a "More" group, collapsed but remembered (`localStorage`, in
  try/catch). Tab ids and `go(tab)` stay unchanged so the palette, E2E tests and deep links keep working.
- Every tab stays reachable through Ctrl+K. Nothing is removed.
- Tests: `e2e_nav.py` (each tab reachable; More remembers its state; at phone width the nav is one row).

### Task 3: Keyword highlight (G3)
- Extension popup button "Show missing keywords": the job's missing hard skills come from `/api/ext/*` (signed like
  the others) and content.js marks them on the page only. No network from content.js and no storage, as before.
- In-app browser: the same reader, through a bar button.
- Tests: `test_extension_client` guard unchanged; matcher test for highlighting; `e2e_extension` case.

### Task 4: "I applied" (G4)
- Popup and browser bar: "Mark applied" records `db.set_status(..., actor='user', evidence={source: 'extension'})`.
  Your click is the evidence: never inferred from a page.
- Tests: unit (status + stage_events row); E2E (bar button moves the card).

### Task 5: Per-job checklist (G5)
- New table `tasks(job_id, text, due, done_at)`, added by an additive migration; drawer list; due tasks on Today.
  Task edits are bookkeeping, so they never touch the follow-up clock.
- Tests: unit (CRUD, delete_job removes them); E2E (add, tick, shows on Today).

### Task 6: Template gallery (G6)
- Studio "Look" opens a grid of the existing style presets rendered by `viewer.page_html` (one renderer). Clicking a
  thumbnail sets pref `resume_look`.
- Tests: unit (each preset passes `clean_style`); E2E (pick one, the preview changes).

### Task 7: Map view (G7, last)
- Offline US place table (Census gazetteer, public domain) maps city/ZIP to lat/lon. Board "Map" view uses inline SVG;
  no tile server, no external calls. Remote jobs are listed beside it.
- Tests: unit (lookup, unknown place); E2E (map shows the seeded cities).

## Status (2026-11-18, pass 53)
- Built: Task 1 (Match report, with a 75% target and the AI keyword fix), Task 3 (keyword marks), Task 4 (I applied),
  Task 5 (to-dos, AI suggestions), Task 6 (look gallery, AI pick), Task 7 (map), plus phone access (moved out of "Not
  doing" at the user's request) and the UI trim (long help folded, AI rows merged).
- Skipped: Task 2 (five primary views). The sidebar is grouped, now stays put while a tab scrolls, and every tab is in
  Ctrl+K; hiding tabs behind "More" would cost a click without removing anything.

## 4. Not doing, on purpose
- **Mass auto-apply** (JobCopilot's 50 a day, Simplify Autopilot): you chose limited, per-site capped applying.
- **Automating LinkedIn / Indeed / Glassdoor / ZipRecruiter / SimplyHired**: their terms. You browse them yourself in
  the in-app browser; Lodestar saves and fills only on your click.
- **"Beat the ATS" claims**: the match rate (target 75%) is shown, labelled a tailoring guide, not the employer's verdict.
- **Cloud accounts and sharing**: local-first is the point. Phone access covers the phone over home Wi-Fi.

## 5. Order
Task 1 → 2 → 4 → 3 → 5 → 6 → 7. Tasks 1, 2 and 4 bring the biggest everyday gain; 7 can be dropped without loss.
