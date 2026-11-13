# AISearchBot

<!-- knowledge-stack -->
## Knowledge stack (auto-seeded once per project; edit freely)
- **Code graph**: `graphify-out/graph.json` + `graphify-out/GRAPH_REPORT.md`, refreshed automatically each session.
  Start codebase questions with `graphify query "<q>"`, `graphify explain "<node>"`, `graphify path "A" "B"` before grepping.
- **Obsidian mirror**: `C:\Users\jorak\Documents\Obsidian Vault\graphs\AISearchBot` (one note per node + `graph.canvas`). Capture decisions and notes there with `ecc:knowledge-ops`.
- **ECC workflow**: `/ecc:plan` -> `/ecc:tdd-guide` -> `/ecc:code-review`; `ecc:codebase-onboarding` reads GRAPH_REPORT.md first.

## Project notes

- **Product**: Lodestar. Package `lodestar/`; `jobbot` is a legacy script alias in `pyproject.toml`.
- **Tests**: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` (982 tests). pytest is not installed in the venv. Tests share one temp `LODESTAR_HOME` and module state: a test that monkeypatches a module attribute must restore it in `finally`.
- **Test matrix** (`docs/TESTS.md`): one row per feature with its unit/integration and E2E tests by exact name
  (`module.Class.test_name`). Every new feature adds a TESTS.md row + a unit test + an E2E test when it has UI;
  `tests/test_feature_matrix.py` fails on a row with no test, an unknown name, a browser test in the unit column, a
  test named in no row, a dropped row or Planned ID (pinned in the guard), or a stale test count above (update it when you add tests). Coverage (informative): see TESTS.md > Coverage.
- **Browser tests**: `.venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"` (235 tests; needs `pip install -e .[e2e]`; skips without Playwright or a browser). `tests/e2e/harness.py` `E2ETestCase`: per class a temp `LODESTAR_HOME` (module-level paths rebound), fictional seed via the app's write paths (`cls.ids`), fakes for AI (`ai_text`/`ai_json`), IMAP/SMTP, OAuth/urlopen, `util.fetch` (`FETCH`), keyring, toasts, `webbrowser`; real server on a free port; per test a fresh page with a console-error guard. Installed Edge by default; `LODESTAR_E2E_BROWSER=chromium` (CI), `LODESTAR_E2E_HEADED=1` to watch. Failures leave a screenshot + HTML in `tests/e2e/_artifacts/`. Never run `playwright install` locally. Wait with `idle()` (fetch-hook count), never sleeps or `networkidle` alone; drag with `Board.drag` (HTML5 events on the exact elements; a mouse drag picks up the wrong card when `<main>` scrolls). `FakeMail.FAIL` makes logins raise (refused/dropped mailbox).
- **Profile**: prompts read `resume.candidate_text(limit)` (master + profile-bank facts, fitted by section), never `profile_text()[:N]`. Free-form helpers (coach, ideas, mock) pass `strict=False`. Anything an employer reads (resume, letters, mail, form answers) passes `private=False` so the salary floor stays out; drafts pass `drafts.screen` (a counter-offer's cited figures go in `cited=`, the only exemption), employer-facing answer reads use `employer=True` (private answers never leave). Writes to profile.md go through `profile.write_master()` (snapshot + atomic).
- **Mail trust** (`email_monitor._match` / `_thread`): trusted = aligned DKIM/DMARC + a *strong* tie + agreement with the stored contact. Strong = stored contact, a thread our mail vouches for (it answered trusted mail or went to the stored contact; job not rejected/withdrawn), or the registrable domain of the job's posting URL on the company site. A domain that only *names* the company (`names_company`, any suffix) is weak: filed, never trusted. Mail about an untracked company is never trusted. Manual links (`link_mail`, Track as new job) and replies to them never make a sender trusted. Never loosen this.
- **Drafts**: AI draft options/rewrites go through `drafts.py` (`options`, `rewrite`, `use`): one AI call, `screen()` (salary-floor guard) on every text, untrusted mail fenced, mail kinds proposed with review (`apply.mail_proposal(review=True)`), recipient from the server. A send_email proposal answering unverified mail is flagged `unverified` and loses `new_status` (`approvals.propose`).
- **Inbox refusals**: anything that must stop an Inbox item (floor guard on edits, a clashing interview slot) goes in `approvals._precheck`, which runs before the claim, so the item stays pending. Tests share one home: `.ics` rounds from other tests can hold a slot.
- **Pipeline** (`pipeline.py`): a new automated step = a `pipeline.register` stage under a `settings.TOOLS` tool. Stage functions read earlier outputs through `ctx.out`/`ctx.file`, ask through `ctx.ask` (never guess), never send/submit/change status (`approvals.propose` does), and pipeline bookkeeping never goes to `events` (the follow-up clock). Handoffs go inside the shared function (`apply.answer`/`followup`/`thanks` read the context themselves). Eligibility/EEO labels are never AI-drafted (`pipeline.never_ai`). `pipeline.AUTO` is set only by the cli ui/app/desktop commands, never by `web.start_server`. Root fingerprints hash content, never row ids or read times (`interview.qset_fp`); a stage that itself moves a root it reads records the new value in `ctx.read_now`, or it reads stale right after its own run.
- **Company pages** (`extras.company_pages`, pass 18): fetches use `util.fetch(follow=False)` and vet every redirect hop themselves (company's own site via `_names_company` = registrable label, not substring; not `_listing_host`; the target's robots.txt), each hop counted in the 12-request cap, the page stored under its final URL; origins via `util.origin` (default port dropped). The prep pack's source tags are checked against `question_set` (`interview._check_tags`); stored AI questions are served only while their source still holds the quote (`_still_sourced`).
- **Profile import** (`profile.stage_import` / `apply_import`): every import is a review (profile-imports/<id>.json);
  nothing reaches the bank or profile.md until applied, in one `write_master` (one snapshot). Personal data
  (`profile.redact_personal`: DOB, ID numbers, pay, References, Preferences...) is removed before any parser or AI sees
  the text and again in `saved_text()`. AI facts are trusted only when `profile.verify` finds them in the file (flagged
  rows start unchecked). `extract_heuristic` and `render_markdown` are symmetric for the master format (round-trip test).
  POST /api/profile with a `base` hash answers 409 when profile.md changed since the editor loaded it. An item profile.md
  already shows (`diff` -> `in_master`: profile.md parsed like an import; contact values compared normalised) is never
  inserted again, and a Re-read of profile.md only fills the bank (never written back).
- **Master resume** (`studio.py`): resumes/master.* rebuilt offline from the saved profile (no AI); `profile.profile_rev`
  / `section_revs` fingerprint it (drop_preferences, never employer_safe: it runs in every state()). `studio.AUTO` (the
  debounce timer and the loop step) is set by the cli run/ui/app/desktop commands, never by `web.start_server`; CLI
  commands that change the profile call `studio.sync_master()` once. Per-job resumes are never rewritten: jobs.profile_rev
  holds the sections resume.md used (`profile.used_revs`; a studio version passes the `section_revs` it was built from,
  kept in plan.json), and the drawer badge names the ones that changed. The .pdf / .docx beside a per-job .md follow it:
  `save_doc` / `_save_resume` remove the old PDF first (a locked one stops the save before anything changed) and print it
  again after (no engine: it stays removed); `use_for_job` moves the old files aside before resume.md is written.
- **Resume studio** (`studio.build` / `resolve`, `render.py`): structural facts (employers, titles, dates, schools,
  degrees, certifications, contact, links) are ref-only: the plan cites catalogue ids (`profile.structured`) and
  resolve copies them. The AI writes only headline, summary, bullet text and skill-group labels, each through
  `resume.check_rewrite` (the one guard; `tailor_bullets` uses it too): a bullet is checked against its own entry
  (scope), the summary per sentence, numbers only from the cited facts (plus the computed 'N years', allowed only as
  'N years' / 'N+ years', never the same figure elsewhere). `build(max_ai=)` caps its AI calls (the pipeline passes the
  run's budget left: no tighten call without a second one). Every output
  passes `employer_safe`; a refused build leaves no version. Renderers read one block list (`render.blocks`); the
  style goes through `render.clean_style` (AI values dropped with a note, user values strict). The pipeline's Tailor
  step is the studio; it is stale via `Stage.stale` (`_profile_stale`: the drawer badge's sections), not the profile root.
- **Document viewer** (`viewer.py`, `/api/view*`): every generated document goes markdown (or a studio version's
  stored `doc`) -> `render.md_blocks` / `letter_blocks` / `blocks` -> `page_html` (preview + PDF) / `page_docx` /
  `page_txt`; never a second renderer. Refs are `{type: master|studio|job|text}`; job documents only by name from
  `viewer.JOB_DOCS`. Look = pref `resume_look` -> the document's own (a studio version's style) -> its overrides in
  viewer.json. Exports re-run the floor guard (`drafts.leaks` on page text + raw text; employer kinds only) and, for
  edited resume lines, `check_rewrite` on every distinct changed line (409 until confirm; over `CHECK_MAX` the rest needs
  confirm too). A job document's Save runs the same guards (`save_text(confirm=)`): saved text is what exports, mail
  and the packet read. The preview frame is `sandbox="allow-same-origin
  allow-modals"` (no scripts; app.js paginates it into sheets): Edge logs "Blocked script execution in about:srcdoc"
  on pointer input over it, so E2E tests that click in it allow that message. The E2E fetch hook counts json, blob and
  text reads.
- **Gotcha, PDF**: headless Edge / Chrome first (`resume.pdf_from_html`, through `updater._proc`), with a throwaway
  `--user-data-dir` removed with retries; print into the temp folder, then replace the target (Edge exits 0 when it
  cannot write a locked target, so the exit code is never trusted); no CSS floats, ligatures off. Tests stub
  `resume._browser` where they pin Word / LibreOffice / the print page. The Bash tool sandbox cannot run Edge: run
  Edge-touching tests from PowerShell.
- **Keyring isolation** (`vault.namespace`): the keyring service is `lodestar` (legacy `jobbot` fallback) only when the data folder is the default `~/.lodestar` (or `~/.jobbot`), resolved, case-insensitive on Windows; any other `LODESTAR_HOME` uses `lodestar:<12 hex of sha256(resolved path)>` with no fallback, so a temp home (tests, agents, doc writers) never reads or writes the real keys or mail password. `LODESTAR_VAULT_SERVICE` fixes the service (a deliberate portable install); never set it for tests or sandbox runs (the update gate, the E2E harness and every unit test module blank it: a new test module that sets `LODESTAR_HOME` must also set `os.environ["LODESTAR_VAULT_SERVICE"] = ""` before importing lodestar, guarded by `test_pass17_isolation.Suite`; a test that fakes keyring calls fakes `get_password` too, never only `delete_password`). All keyring access goes through `vault.py`; never call `keyring` elsewhere. Repo `.env` values still load into any home (plain config the user wrote). Agents: a temp `LODESTAR_HOME` now isolates the keyring; still add `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` for manual runs.
- **Interview readiness / sourced questions** (`readiness.py`, `interview.question_set`): readiness is candidate-only:
  never in employer text or prompts, a pipeline stage output, or an AI prompt (except "Explain my readiness": the five
  parts, no fit data); the chance is a band, always "not a probability", never a percentage. Question `source` tags are
  code-set after quote checks (`_clean_qset`); the AI cannot assign `logged`/`general`; "reported" is off unless the
  `reported_questions` pref is on. Company material goes into prompts inside `extras._fence` nonce fences as untrusted
  data; labels are cleaned when stored (`extras.clean_label`). Never fetch `util.NEVER_FETCH` hosts (checked in
  `_check_url`, so every redirect hop) or pasted URLs; company pages only via `extras.company_pages` (robots.txt, 12
  requests, 30-day cache, never board / ATS hosts). Tests set `extras.PAGE_PAUSE = 0` and put it back.
- **AI advisor** (`advisor.py`, pass 19): Recommend / Apply suggestions / Full AI / Undo for the user's own content.
  A new scope = a `SCOPES` entry: `gather(target)` -> `{field: (label, value)}` and `write(target, field, value, restore)`
  through the app's existing write path (write_master, set_fields, viewer.save_text, approvals.edit ...); `restore=True`
  must put a gathered value back exactly (undo compares the gathered value with the logged one). Never gather what a
  model may not see (eligibility / EEO / private answers, Preferences, the contact line, readiness). `employer=True`
  turns on the floor + no-invented-facts guards. Full AI writes with `config.FULL_AI` set: every path that sends,
  submits, moves or adds a job, proposes or approves, or writes settings, the vault or watches calls
  `config.full_ai_check` first; a new such path must too.
  A scope Full AI may write whose prompt carries third-party text (job, contacts) needs a `check`: `_k_own` refuses a
  new link / email / phone and notes that lose a line. Form answers: `_answer_bad` (no heading, no `_source:` note) and
  `_w_docs` refuses any change to the question list (apply and restore alike); the pipeline's `_source: ...; check this`
  note is never gathered and `_with_notes` puts it back on every write. UI: `advRefresh` never re-renders over typed,
  unsaved input (`drawerDirty()`, `PROFILE_LOADED`); it says what happened instead.
  UI: `aiBar(scope, target)` in app.js (tab headers via `data-adv-slot` in index.html, cards inline); a new scope needs
  its toolbar and its `ADV_NAME` entry, and `ADV_NOAUTO` / `ADV_ADVICE` mirror SCOPES (test_pass19_toolbar checks).
  AI help menus: a `HELPERS` entry (label, menu `where`, `ask`, `context(target)` fenced; `scope=` makes it appliable:
  a Recommend with `ask` as focus, so only Apply suggestions writes); the page groups `S.ai_helpers` by `where` into
  `aiMenu(where, target)` (a new `where` needs a `data-ai-menu` slot or an `aiMenu(` call and an `AIM_NAME` entry).
  Text a user may send gets `employer=True` (floor guard). Explain this setting's `SETTINGS` name docs/SETUP.md headings:
  renaming one fails test_pass19_helpers.
- **Browser extension** (`extension.py`, `web.Handler._ext_post`, `extras.ext_autofill`): its secret authorizes `/api/ext/*`
  only (closed table before `_authed`; never the page token, never CORS on ext routes); pairing needs a
  `chrome-extension://` Origin + the one-time code; `extension.json` never goes in backups. Signatures cover
  `ts
METHOD
PORT
path
` + body and the ping proof `pong
ts
PORT`, PORT = the server's own
  `server_address[1]` (never Host) and the port popup.js dialled: change the server, popup.js and test_extension's
  `sign()` together, or a relay on another scanned port works again. Autofill answers come from
  `pipeline.known(employer=True)` / `suggestions` and pass the floor guard unchanged or are withheld; EEO and desired
  salary only when ticked; no LinkedIn (refused server-side). content.js never clicks, submits or ticks.
  The client (`extension/`, MV3, load unpacked): content.js and matcher.js run only on a click and never touch the
  network or chrome.storage (test_extension_client guards it); radios stay "needs you"; the popup fetches only
  `/api/ext/*`. Matcher tests: `node --test "extension/test/*.test.mjs"`. After a scan change, re-run `e2e_extension`
  with `LODESTAR_E2E_UPDATE=1` (rewrites the fixtures' descriptors). The E2E blocks 8765-8774, so no test pings a real
  Lodestar.
- **Market pay** (`paydata.py`, pass 20): only `paydata.fetch` calls BLS (series IDs only; `BLS_API_KEY` in the POST
  body, never echoed; the daily budget is one atomic upsert on meta `bls:YYYYMMDD`, refunded when BLS was never
  reached). Everything else (board chip, drawer, offers, counter-offer, prompts) reads the cache through
  `for_job(job, idx)` with `index()` read once per board. Pref `market_pay` is off by default: off = no network
  anywhere. A counter-offer cites `market_median` / `market_p75` only for the countered job (`paydata.phrase`; its
  phrases start with `paydata.HEAD`, which `apply._split` keeps apart from competing offers); the floor is never read.
  A changed area or SOC code in `data/oews.json` needs a live check recorded in its `verified`. Tests fake `util.fetch`.
- **Restore** (`extras.restore`, pass 20): `extras.in_backup` is the one scope rule for what a backup carries and a
  restore replaces or removes (never .env, extension.json, capture.token, update-state.json, procs/, backups/, logs);
  change both together through it. It compares case-folded (on Windows `Extension.json` IS extension.json) and
  `restore_check` refuses 8.3 short names (`EXTENS~1.JSO`) and `lodestar.db` in another spelling: keep both. Order: `restore_busy` (updater.busy + `_others`) and `loop.HOLD` (held by each loop
  cycle) -> `restore_check` (no writes) -> stage + `_check_stage` -> before-restore safety zip -> swap (rollback on
  failure; the DB via SQLite's backup API). The page names a backup only by bare name (`backup_file`). Restore tests run
  in their own home (module paths rebound): never restore over the shared test home.
- **Command palette** (app.js `pal*`, Ctrl+K): a capture-phase keydown listener, so it runs before the drawer's and
  viewer's keys and stops them while open; actions reuse the real buttons (`#topEmail`, `#topWatches`, the tab's own
  Recommend). A new tab, Setup card (`#setup .panel > h3`) or preference appears in it by itself.
- **Fit score** (`fit.py`, pass 21): deterministic (no AI inside; the AI part is a stored `ai_fit` from `rank()`, at most
  its weight's share), private (never a floor figure in fit data, never in employer text or prompts; `rank()` sends
  `candidate_text(private=False)` + `profile.redact_floor(preferences_text())`). Stored per job / postings row with
  `fit_rev`; stale when it differs from `fit.rev()` (refreshed by the loop's `fit` step and the page). The board gets
  `fit.light()` only; `GET /api/jobs/<id>` the full breakdown. `jobs.match_score` is JD coverage ("Coverage").
  auto_track: rules-only without a key, AI on the best few under `quota:ai_rank`, at most `auto_track_daily_max`.
  The pipeline's Fit check is a run step over the same fit (its verdict is the fit gate). A rules-only `auto_track` proposal (no AI
  judgement) is always `force_pending`, whatever the tool's auto flag.
- **Sources / All jobs** (`web_monitor.SOURCES`, `listings.py`, pass 21): a new board goes in `SOURCES`, `EVERY` (its
  throttle; per-user limits go in `GLOBAL`: one unfiltered `_cached` fetch per window, filtered locally) and
  `ATTRIBUTION` (its credit link); a keyed one also in `KEYED` + the connections `REGISTRY` (kind `jobs`: key + `id`,
  verified by one small search, never on the AI card) and runs only when `sources_ready()`. Error text passes
  `_redact`. Every listing a search, watch, feed or capture sees is stored by `annotate` -> `listings.store` (merged by
  posting key or same company+title at the same place, never across two different `ats_id`s: a second opening gets
  key `<key>#<ats_id>` and is never a repost; `url` stays the first link). A GLOBAL board's answer is also saved under
  `cache/boards/<name>.json`: inside its window a manual search in another process reads it, else skips the board,
  and a scheduled run skips it. Anything stored about a posting
  (approval payloads) uses its text `key`, never the rowid. Tests: an earlier module may leave `web_monitor.SOURCES`
  patched (pin it), and the E2E harness clears `_CACHE` / `_ANSWERS` / meta `src:*` per test.
- **Job alerts / listing monitor** (`alerts.py`, `web_monitor.check_listings`, pass 21): an alert mail is one whose
  From is in `alerts.SITES` (domain AND `alert_from` local part) and passes `mail_authenticated`; anything else from
  those domains (InMail, `indeedapply@`, LinkedIn's `jobs-noreply@` application confirmations) stays ordinary mail.
  `web_monitor.no_fetch` is the one guard: every `alerts.SITES` domain, plus any host an ingested alert linked to (seen
  key `alerthost:<host>`, so a click tracker is never opened). Alert links are stored through `alerts.canonical` (token
  and tracking parameters stripped, the opaque-tracker fallback too); still never print or notify one. Alert mail never reaches the AI or the mail table. ATS mail (`email_monitor.ATS_MAIL`, `_ats_match`) is
  filed with `mail.link_reason` and is never a strong tie. Posting pages: two misses in a row before `posting_removed`;
  `posting_reopened` clears it (`web_monitor.removed_event` reads the newer of the two). Tests: job ids restart per
  in-memory database, so clear `SNAPSHOTS/job-*.json` around listing-check tests.
- **Job intelligence / chance boosters** (`intel.py`, `boosters.py`, pass 21): every intel item is `{kind, text,
  source, url, date}`; the web part (company site + the feed it links on its own host, robots.txt first via
  `util.robots_ok`; Wikipedia REST) runs only on a click and is cached in the `intel` table (`co:<company>` 7 days,
  `ai:<job>` summary, `boost:<job>` AI boosters; `delete_job` drops the job keys). Never fetch a job board / ATS /
  `NEVER_FETCH` host (`extras._listing_host`), never a third-party news aggregator. AI summaries keep only lines citing
  a valid `[S#]`. Boosters: rules first (`for_job`, `across`), effect high/medium/low, never a number or probability
  (`boosters.NUMERIC` drops AI items stating one, multipliers included; an AI item needs a `basis` that
  `boosters._grounded` finds: an existing S#, or JD / profile words those texts contain); your own response record only as counts
  once a group has `extras.MIN_N`. Buttons only open a feature (`boostAct`); nothing a booster does sends or spends AI.
  Prompts here use `candidate_text(private=False)`: no floor, no fit score. Booster button labels avoid the names E2E
  tests match by substring (no "Check", "Refresh", "Save website", "New story").
- **Apply agent** (`apply_agent.py`, `apply_ats.py`, pass 22; docs/APPLY_AGENT.md): Playwright only in the `apply` extra,
  imported inside `apply_ats.open_browser`. Never load linkedin / indeed / glassdoor / ziprecruiter / simplyhired
  (`apply_agent.forbidden`: route abort, `apply_ats.BLOCK_RULES` DNS block, post-navigation check; Playwright's route never
  sees a server redirect's next hop). A run loads only its exact `hosts` (widened only by your Continue here). Page
  text is untrusted: safety rules run in `build_plan` on the label, writes only through `Tab.write` (planned items,
  allowed hosts, never a password field), clicks only `Tab.button` by text. Missing values are pipeline questions
  (`pipeline.ask(stage='apply')`), never guesses. Submissions: `approvals.propose('apply_agent', 'submit_application')`;
  `approvals.record_submission` is the only status change; a run that clicked Submit and lost track is `unknown`, never
  retried. No stealth, no CAPTCHA solving (`test_apply_engine.Surfaces`). Tests drive `_loop(new_driver)` with a fake
  browser; E2E (`e2e_apply_agent`) uses a temp profile, fixtures in tests/fixtures/apply and `MAP * 127.0.0.1`, never
  `HOME/browser-profile`; the worker's idle hook is the only thread that may touch the page.
- **Site accounts** (`accounts.py`, pass 22 addendum A; docs/APPLY_AGENT.md > Site accounts): one account per exact host
  (`site_accounts` row: link, username, status, dates, jobs); the password only in the keyring (`vault` name `site:<host>`,
  filtered out of the Setup vault list), back only from Reveal, `_secret` or `_general_pw` (static test: three
  `vault.get` calls). The general login (`accounts.GENERAL` = `site:*`, keyring only) is new accounts' password and gets
  one sign-in try on an "already registered" site. Only
  `accounts.Page.type` types a password, only into a password field on the account's own host; `apply_agent.py` /
  `apply_ats.py` still never do (their static test). A run's `login` blocker goes to `accounts.handle` (saved account signs
  in; else Create Account + the sign-up form filled, then you tick terms and press Create; the agent clicks Create or
  a checkbox only with pref `accounts_auto_create`, through `accounts._finish`: consent boxes only, never marketing), else
  the usual handoff with its hint. A failed / locked account is never retried by itself. CAPTCHAs stay
  yours. Codes and verification links (`codes.links`, memory only, masked like codes) are used on your click
  (`accounts.act`, worker-thread `_serve`) or automatically only with the account's `auto_verify`; a link opens only on the
  account's host. The account window (`accounts.start`: Re-login / Create) and the agent's worker and the sign-in window
  exclude each other on the profile. Tests: `test_apply_accounts` (FakePage), `e2e_accounts` (fixtures account.html/.js).
- **Finding the posting** (`apply_find.py`, pass 22 addendum B): `enqueue` calls `apply_find.find` only when
  `resolve_url` refuses (so `resolve_url` itself never touches the network); a found link is saved as `apply_url` and its
  run is never `auto`. A match is an exact normalised title (then city), never a guess; the AI answers an index into the
  page's own links (fenced), never a URL; at most `MAX_REQUESTS`; tests fake `web_monitor.feed`, `util.fetch`,
  `util.robots_ok`, `extras._site_for`.
- **Search input** (`web_monitor.alternatives` / `_loc_alts` / `place_ok` / `defaults`): a query's commas and 'or' are
  separate searches; a location's alternatives split on ';', '|' and a lowercase ' or ' only ('Portland, OR' is a place);
  only `LOCAL` boards get the place (`_RUN.where`, in the cache key). The Jobs tab fills the location filter only from
  Preferences (a resume-only city is a placeholder), so no hidden filter; `profile.set_pref_fields` writes Preferences.
- **Career discovery** (`occupations.py`, `careers.py`, pass 23; plan docs/superpowers/plans/2026-11-13-blueprint-v1.1-alignment.md):
  the bundled O*NET 31.0 ontology (`data/onet.json.gz`, CC BY 4.0: show `occupations.meta()['credit']` wherever its
  data shows) is rebuilt only by `scripts/build_onet.py` from the O*NET text zip. Suggestions are deterministic (no AI):
  tiers 0-5 (`careers.TIERS`, the blueprint's labels verbatim), classes (`careers.CLASSES`; code says career class,
  because `readiness.py` is interview readiness), never broadened beyond the tiers asked for, every one naming its
  source and version. A title O*NET files under several occupations counts at the lowest Job Zone (never the most
  flattering reading); a licensed occupation (`data/regulated.json`) is never Qualified without a matching credential.
  Candidate-only: never in employer text or prompts, never the salary floor. Track search reports coverage
  (`careers.coverage`: asked / failed / not ready / checked) and never claims every board. Tests patch
  `occupations.DATA` to `tests/careers_fixture.py` and put it back. Tier 6 (`careers.explore`, pass 24) is the only AI
  path: `candidate_text(private=False)` minus Preferences, titles through `extras.clean_label`, an unmapped role is
  labelled `careers.UNMAPPED`.
- **Eligibility gates** (`fit.gates`, pass 24): hard requirements are met / not_met / unknown, never a score cut
  (no `blocked_cap`, no clearance / deal-breaker modifiers); `blocked` = a gate not met; unknown is never met:
  auto_track proposals with `gates_unknown` are `force_pending`, the pipeline fit gate says skip. `fit.job_class`
  maps a fit to `careers.CLASSES`. A new hard requirement is a gate, not a modifier.
- **Policy + audit** (`policy.py`, pass 25): `approvals.propose` asks `policy.authorize(tool, kind, payload, job_id,
  force_pending)` (ALLOW / REQUIRE_APPROVAL / BLOCK + reason codes in `policy.REASONS`) and only ALLOW runs at once.
  Mandatory waits: withdrawal/acceptance `new_status`, `chosen_time`, unverified replies, attachments, jobs at
  offer/accepted. Every decision, your approvals and every executor run append to `audit` (triggers refuse UPDATE /
  DELETE: never write a migration or cleanup that touches it). A new always-review rule is a reason code here; the
  older guards stay (defence in depth). Apply-agent auto: licensed occupations (`apply_agent._licensed`) go to review.
- **Lifecycle** (pass 26): `db.set_status` / `db.set_stage` append to `stage_events` (actor user | agent | integration |
  system, evidence JSON, approval_id; triggers refuse UPDATE and DELETE while the job exists: `delete_job` removes its
  rows after the job). Executors get `_pid` / `_tool` in their payload copy for the record. `db.STAGES` maps a stage
  to its board column (on_hold: none). Applied snapshots `resume.SUBMITTED` into `submitted/` once (manifest). A new
  board needs a `web_monitor.CAPABILITIES` entry (guard test). Jobs searches return `careers.coverage`.
- **Gotcha, SystemExit**: `ai.*` and `profile_text()` report user-facing problems (no key, model rejected, template profile) as `SystemExit`, which `except Exception` does not catch. Background paths catch `(Exception, SystemExit)`.
- **Run**: `lodestar doctor` (add `--live` for one real AI call per provider), `lodestar desktop` (WebView2 window; falls back to the browser).
- **Answer bank sources**: every `db.save_answer` from a path where you typed the answer passes `source` (Answers tab "typed under Answers", CLI, `pipeline.answer`); an AI `save_answer` proposal carries `source: "AI draft for job #N"`. Eligibility / EEO answers (`pipeline.never_ai`, which also knows the CANON legal keys) are reused only when `pipeline.yours(source)`, and AI prompts read bank rows only via `db.employer_answers()` (`pipeline.for_prompts`: never such a row, tagged or not). A new event kind a document builder writes goes in `db.BOOKKEEPING` (the follow-up clock).
- **Gotcha, settings.json**: on Windows `os.replace` fails while another thread has the file open for reading (every `settings.pref` call does); `settings.save` retries the rename briefly. Write other shared files the same way.
- **Gotcha, icon**: write `.ico` frames as classic BMP. Pillow's PNG-compressed frames render in Explorer but garble in .NET `System.Drawing.Icon` (used by pywebview).
- **Gotcha, installer**: changes to `install.ps1` only apply after it is re-run (regenerates the launcher and desktop shortcut).
- **Updater** (`updater.py`): the loop runs `updater.tick` only when the args carry `update=True` (the run/app/desktop parsers; test `A` classes do not), so no test fetches this checkout's origin. Updater tests build throwaway repos (bare origin + clone); `apply` is the only `git reset --hard` and runs only on a tree it saw clean. Callers pass `updater.ROOT` explicitly (`check(updater.ROOT)`): the `repo=ROOT` defaults bind at import, so a test that patches `updater.ROOT` reaches only explicit callers. `apply` journals to `HOME/update-state.json` and every rollback goes through `_restore` (retries; removes files the target added); `recover()` rolls back an interrupted update. Long-running entry points (`run`, `app`, `ui`, `desktop`) call `updater.startup()` (recover + register in `HOME/procs`); a Restart checks `busy(include_update=True)`. Subprocesses with a timeout go through `updater._proc` (temp files, tree kill), never `subprocess.run(capture_output=True, timeout=...)`, which a grandchild can hang.
- **Gotcha, static files**: `web.ASSETS` reads `lodestar/static/` once at import (an update must not change the front end under a running server). After editing `index.html` / `app.js` / `app.css`, restart the server.
- **Gotcha, real calls**: no real AI, SMTP or OAuth sign-in has been verified yet; the tests use a faked HTTP layer.
- **OAuth mail** (`oauth.py`): OAuth tokens live only in the keyring vault: the refresh token is stored (chunked when
  long: the head names its pieces and a hash, so never a mixed or half token), access tokens stay in memory, nothing
  in files, logs, exports or API answers. IMAP/SMTP log in through `util.imap_login` / `smtp_login` (XOAUTH2); every
  IMAP connection opens through `util.imap_open` (IMAP_MODE ssl or starttls, never plain). Never weaken the sign-in
  listener's state, Host or loopback checks, and the sign-in page always opens in the system browser.
- **Mail check results**: `mailconn.test()` records its own result (`connections.mail_result`), so every path that
  tests (Connect & test, the sign-in task, Re-check all, startup) updates Getting started and doctor.
- **Attachments** (`mailfiles.py`): outgoing files only from the job's folder, through `mailfiles.resolve` (resume /
  cover letter + the job's `attach/`; never private docs: .md/.json/.ics, `mail/`, `history/`), checked at
  `approvals.propose` (review required), `_precheck` and `_send`; `attachable()` flags what the floor guard refuses.
  Received files are saved only for job-filed mail and never opened or served.
- **Codes** (`codes.py`): emailed sign-in codes are memory only: never written, logged, notified, put in `/api/state`
  (only `codes_count`) or sent to an AI; `email_monitor._scan` runs `codes.mask` on subject and body before relevance,
  classification and recording. Tests reset `codes._CODES`.
- **Startup checks** (`connections.start_checks`): one daemon thread, catches `(Exception, SystemExit)`, never blocks
  or stops startup; `LODESTAR_NO_STARTUP_CHECK=1` turns it off. Tests that touch mail settings pop them from
  `os.environ` (the repo `.env` is loaded into the test process).
