# AISearchBot

<!-- knowledge-stack -->
## Knowledge stack (auto-seeded once per project; edit freely)
- **Code graph**: `graphify-out/graph.json` + `graphify-out/GRAPH_REPORT.md`, refreshed automatically each session.
  Start codebase questions with `graphify query "<q>"`, `graphify explain "<node>"`, `graphify path "A" "B"` before grepping.
- **Obsidian mirror**: `C:\Users\jorak\Documents\Obsidian Vault\graphs\AISearchBot` (one note per node + `graph.canvas`). Capture decisions and notes there with `ecc:knowledge-ops`.
- **ECC workflow**: `/ecc:plan` -> `/ecc:tdd-guide` -> `/ecc:code-review`; `ecc:codebase-onboarding` reads GRAPH_REPORT.md first.

## Project notes

- **Product**: Lodestar. Package `lodestar/`; `jobbot` is a legacy script alias in `pyproject.toml`.
- **Tests**: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` (561 tests). pytest is not installed in the venv. Tests share one temp `LODESTAR_HOME` and module state: a test that monkeypatches a module attribute must restore it in `finally`.
- **Test matrix** (`docs/TESTS.md`): one row per feature with its unit/integration and E2E tests by exact name
  (`module.Class.test_name`). Every new feature adds a TESTS.md row + a unit test + an E2E test when it has UI;
  `tests/test_feature_matrix.py` fails on a row with no test, an unknown name, a browser test in the unit column, a
  test named in no row, a dropped row or Planned ID (pinned in the guard), or a stale test count above (update it when you add tests). Coverage (informative): see TESTS.md > Coverage.
- **Browser tests**: `.venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"` (139 tests; needs `pip install -e .[e2e]`; skips without Playwright or a browser). `tests/e2e/harness.py` `E2ETestCase`: per class a temp `LODESTAR_HOME` (module-level paths rebound), fictional seed via the app's write paths (`cls.ids`), fakes for AI (`ai_text`/`ai_json`), IMAP/SMTP, OAuth/urlopen, `util.fetch` (`FETCH`), keyring, toasts, `webbrowser`; real server on a free port; per test a fresh page with a console-error guard. Installed Edge by default; `LODESTAR_E2E_BROWSER=chromium` (CI), `LODESTAR_E2E_HEADED=1` to watch. Failures leave a screenshot + HTML in `tests/e2e/_artifacts/`. Never run `playwright install` locally. Wait with `idle()` (fetch-hook count), never sleeps or `networkidle` alone; drag with `Board.drag` (HTML5 events on the exact elements; a mouse drag picks up the wrong card when `<main>` scrolls). `FakeMail.FAIL` makes logins raise (refused/dropped mailbox).
- **Profile**: prompts read `resume.candidate_text(limit)` (master + profile-bank facts, fitted by section), never `profile_text()[:N]`. Free-form helpers (coach, ideas, mock) pass `strict=False`. Anything an employer reads (resume, letters, mail, form answers) passes `private=False` so the salary floor stays out; drafts pass `drafts.screen` (a counter-offer's cited figures go in `cited=`, the only exemption), employer-facing answer reads use `employer=True` (private answers never leave). Writes to profile.md go through `profile.write_master()` (snapshot + atomic).
- **Mail trust** (`email_monitor._match` / `_thread`): trusted = aligned DKIM/DMARC + a *strong* tie + agreement with the stored contact. Strong = stored contact, a thread our mail vouches for (it answered trusted mail or went to the stored contact; job not rejected/withdrawn), or the registrable domain of the job's posting URL on the company site. A domain that only *names* the company (`names_company`, any suffix) is weak: filed, never trusted. Mail about an untracked company is never trusted. Manual links (`link_mail`, Track as new job) and replies to them never make a sender trusted. Never loosen this.
- **Drafts**: AI draft options/rewrites go through `drafts.py` (`options`, `rewrite`, `use`): one AI call, `screen()` (salary-floor guard) on every text, untrusted mail fenced, mail kinds proposed with review (`apply.mail_proposal(review=True)`), recipient from the server. A send_email proposal answering unverified mail is flagged `unverified` and loses `new_status` (`approvals.propose`).
- **Inbox refusals**: anything that must stop an Inbox item (floor guard on edits, a clashing interview slot) goes in `approvals._precheck`, which runs before the claim, so the item stays pending. Tests share one home: `.ics` rounds from other tests can hold a slot.
- **Pipeline** (`pipeline.py`): a new automated step = a `pipeline.register` stage under a `settings.TOOLS` tool. Stage functions read earlier outputs through `ctx.out`/`ctx.file`, ask through `ctx.ask` (never guess), never send/submit/change status (`approvals.propose` does), and pipeline bookkeeping never goes to `events` (the follow-up clock). Handoffs go inside the shared function (`apply.answer`/`followup`/`thanks` read the context themselves). Eligibility/EEO labels are never AI-drafted (`pipeline.never_ai`). `pipeline.AUTO` is set only by the cli ui/app/desktop commands, never by `web.start_server`.
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
