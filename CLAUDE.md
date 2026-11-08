# AISearchBot

<!-- knowledge-stack -->
## Knowledge stack (auto-seeded once per project; edit freely)
- **Code graph**: `graphify-out/graph.json` + `graphify-out/GRAPH_REPORT.md`, refreshed automatically each session.
  Start codebase questions with `graphify query "<q>"`, `graphify explain "<node>"`, `graphify path "A" "B"` before grepping.
- **Obsidian mirror**: `C:\Users\jorak\Documents\Obsidian Vault\graphs\AISearchBot` (one note per node + `graph.canvas`). Capture decisions and notes there with `ecc:knowledge-ops`.
- **ECC workflow**: `/ecc:plan` -> `/ecc:tdd-guide` -> `/ecc:code-review`; `ecc:codebase-onboarding` reads GRAPH_REPORT.md first.

## Project notes

- **Product**: Lodestar. Package `lodestar/`; `jobbot` is a legacy script alias in `pyproject.toml`.
- **Tests**: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` (386 tests). pytest is not installed in the venv. Tests share one temp `LODESTAR_HOME` and module state: a test that monkeypatches a module attribute must restore it in `finally`.
- **Profile**: prompts read `resume.candidate_text(limit)` (master + profile-bank facts, fitted by section), never `profile_text()[:N]`. Free-form helpers (coach, ideas, mock) pass `strict=False`. Anything an employer reads (resume, letters, mail, form answers) passes `private=False` so the salary floor stays out; drafts pass `drafts.screen` (a counter-offer's cited figures go in `cited=`, the only exemption), employer-facing answer reads use `employer=True` (private answers never leave). Writes to profile.md go through `profile.write_master()` (snapshot + atomic).
- **Mail trust** (`email_monitor._match` / `_thread`): trusted = aligned DKIM/DMARC + a *strong* tie + agreement with the stored contact. Strong = stored contact, a thread our mail vouches for (it answered trusted mail or went to the stored contact; job not rejected/withdrawn), or the registrable domain of the job's posting URL on the company site. A domain that only *names* the company (`names_company`, any suffix) is weak: filed, never trusted. Mail about an untracked company is never trusted. Manual links (`link_mail`, Track as new job) and replies to them never make a sender trusted. Never loosen this.
- **Drafts**: AI draft options/rewrites go through `drafts.py` (`options`, `rewrite`, `use`): one AI call, `screen()` (salary-floor guard) on every text, untrusted mail fenced, mail kinds proposed with review (`apply.mail_proposal(review=True)`), recipient from the server. A send_email proposal answering unverified mail is flagged `unverified` and loses `new_status` (`approvals.propose`).
- **Inbox refusals**: anything that must stop an Inbox item (floor guard on edits, a clashing interview slot) goes in `approvals._precheck`, which runs before the claim, so the item stays pending. Tests share one home: `.ics` rounds from other tests can hold a slot.
- **Gotcha, SystemExit**: `ai.*` and `profile_text()` report user-facing problems (no key, model rejected, template profile) as `SystemExit`, which `except Exception` does not catch. Background paths catch `(Exception, SystemExit)`.
- **Run**: `lodestar doctor` (add `--live` for one real AI call per provider), `lodestar desktop` (WebView2 window; falls back to the browser).
- **Gotcha, icon**: write `.ico` frames as classic BMP. Pillow's PNG-compressed frames render in Explorer but garble in .NET `System.Drawing.Icon` (used by pywebview).
- **Gotcha, installer**: changes to `install.ps1` only apply after it is re-run (regenerates the launcher and desktop shortcut).
- **Gotcha, real calls**: no real AI or SMTP call has been verified yet; the tests use a faked HTTP layer.
