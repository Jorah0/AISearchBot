# Developing Lodestar

How Lodestar is put together, the rules every change keeps, and how to add a board, a pipeline stage, an AI helper or
an extension feature. CLAUDE.md holds the full rule set per area; this guide is the map and the workflow.

## Architecture in one screen

| Layer | Where | What it does |
|---|---|---|
| Server | `lodestar/web.py` | stdlib HTTP server: `/api/state`, the page actions (`_do`), the extension routes (`/api/ext/*`, signed) |
| Page | `lodestar/static/index.html`, `app.js`, `app.css` | vanilla JS; read once at import (`web.ASSETS`): restart after editing |
| Data | `lodestar/db.py` (SQLite), `~/.lodestar/` | jobs, mail, listings, approvals (`pending`), `audit` and `stage_events` (append-only) |
| Loop | `lodestar/loop.py` | the monitor cycle: mail, watches, fit, the job model, the pipeline (Autopilot), backups |
| Discovery | `web_monitor.py`, `listings.py`, `alerts.py` | boards (`SOURCES`), saved searches, All jobs, the place / seniority / remote filters |
| Judging | `fit.py`, `careers.py`, `boosters.py` | the deterministic fit score, career classes, chance boosters |
| Pipeline | `pipeline.py`, `approvals.py`, `policy.py` | each application step as a stage; anything that sends or submits is a proposal |
| Writing | `resume.py`, `studio.py`, `drafts.py`, `apply.py` | resumes, letters, form answers, mail; every employer text through the floor guard |
| Applying | `apply_agent.py`, `apply_ats.py`, `accounts.py`, `extension/` | the apply agent on company sites, site accounts, the browser extension |
| AI | `ai.py`, `jobmodel.py` | providers, the light model, `using()`, the cross-check, the local job model in Ollama |

## Rules no change may break

- **The salary floor never leaves.** Employer-facing text uses `candidate_text(private=False)` and passes the floor
  guard (`drafts.screen` / `employer_safe`); AI prompts never carry the floor.
- **Mail trust is never loosened** (`email_monitor._match`): trusted needs aligned DKIM/DMARC and a strong tie.
- **Never automate the big five.** LinkedIn, Indeed, Glassdoor, ZipRecruiter and SimplyHired are never fetched or
  driven (`apply_agent.forbidden`, `util.NEVER_FETCH`); no stealth, no CAPTCHA solving. The extension acts only on your
  click.
- **Nothing sends, submits or moves on its own** without a proposal (`approvals.propose`) that `policy.authorize` allows.
- **Append-only tables stay append-only** (`audit`, `stage_events`); migrations are additive.
- **Keys live in the keyring** through `vault.py`; tests never touch the real one (`LODESTAR_VAULT_SERVICE=""`).

## The workflow: test first

1. `lodestar dev new board|stage|helper NAME` writes a failing test in this codebase's patterns and prints the code to
   add, where it goes, and that kind's checklist.
2. Run the test and watch it fail: `.venv\Scripts\python.exe -m unittest tests.test_board_NAME`.
3. Add the code where the kit said; run the test until it passes.
4. Add a `docs/TESTS.md` row naming the test(s) (and an E2E test when the feature has UI), and update the test count in
   CLAUDE.md.
5. `lodestar dev check` runs the fast guards (feature matrix, lint, keyring isolation, no console windows).
6. Run the full suites: unit (`-m unittest discover -s tests -p "test_*.py"`) and browser (`-s tests/e2e -p "e2e_*.py"`,
   from PowerShell: the Bash sandbox cannot start Edge).

## Adding a board

`lodestar dev new board NAME`. A board is a function `q -> [listing]` registered in `SOURCES`, `EVERY` (its published
rate limit), `ATTRIBUTION` (its credit link) and `CAPABILITIES`. Keyed boards also go in `KEYED` and the connections
`REGISTRY`; per-user-limited ones in `GLOBAL` (one `_cached` fetch per window); boards that search near a place in
`LOCAL` (they read `_RUN.where` and `_RUN.radius`). Listings reach All jobs by themselves.

## Adding a pipeline stage

`lodestar dev new stage NAME`. A `Stage` in `pipeline.REGISTRY` under a `settings.TOOLS` tool: it reads earlier output
through `ctx.out` / `ctx.file`, asks through `ctx.ask`, never sends or changes status, and writes no `events`.

## Adding an AI helper

`lodestar dev new helper NAME`. A `HELPERS` entry in `advisor.py`: a label, the menu it lives in, the task, and a
`context(target)` whose blocks are fenced as data. A new menu needs its `data-ai-menu` slot and `AIM_NAME` entry.

## Extension features

The client is `extension/` (MV3, load unpacked). `content.js` and `matcher.js` run only on a click and never touch the
network or `chrome.storage` (`test_extension_client`); the popup fetches only `/api/ext/*`, signed with the paired
secret. Matcher tests: `node --test "extension/test/*.test.mjs"`; after a scan change, re-run `e2e_extension` with
`LODESTAR_E2E_UPDATE=1`.

## The local job model

`jobmodel.py` builds `lodestar-jobs` in Ollama from a general base model (`jobmodel_base`, else the best general model
installed), carrying your employer-safe profile, your preferences without the floor, and your decisions (pursued:
applied and beyond; passed on: rejected auto-track proposals, withdrawn jobs) as its message history. Every fourth
decision is held out so `lodestar jobmodel eval` (Setup > Local job model > Evaluate) can compare it with its base on
decisions it never saw. Change what it learns in `decisions()` / `messages()`; a change in either rebuilds it on the
next daily loop step. `ai.using(model)` pins one model for a call (evaluation, experiments).

## Tests that share state

Unit tests share one temp `LODESTAR_HOME` and module state: a test that patches a module attribute puts it back
(`patched(...)`); an earlier module may leave `web_monitor.SOURCES` patched, so a board test pins it. Two jobs with the
same company and title are one role to the apply agent's duplicate check: give each test job its own company or link.
