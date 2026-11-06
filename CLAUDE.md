# AISearchBot

<!-- knowledge-stack -->
## Knowledge stack (auto-seeded once per project; edit freely)
- **Code graph**: `graphify-out/graph.json` + `graphify-out/GRAPH_REPORT.md`, refreshed automatically each session.
  Start codebase questions with `graphify query "<q>"`, `graphify explain "<node>"`, `graphify path "A" "B"` before grepping.
- **Obsidian mirror**: `C:\Users\jorak\Documents\Obsidian Vault\graphs\AISearchBot` (one note per node + `graph.canvas`). Capture decisions and notes there with `ecc:knowledge-ops`.
- **ECC workflow**: `/ecc:plan` -> `/ecc:tdd-guide` -> `/ecc:code-review`; `ecc:codebase-onboarding` reads GRAPH_REPORT.md first.

## Project notes

- **Product**: Lodestar. Package `lodestar/`; `jobbot` is a legacy script alias in `pyproject.toml`.
- **Tests**: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` (71 tests). pytest is not installed in the venv. Tests share one temp `LODESTAR_HOME` and module state: a test that monkeypatches a module attribute must restore it in `finally`.
- **Profile**: prompts read `resume.candidate_text(limit)` (master + profile-bank facts, fitted by section), never `profile_text()[:N]`. Free-form helpers (coach, ideas, mock) pass `strict=False`. Writes to profile.md go through `profile.write_master()` (snapshot + atomic).
- **Gotcha, SystemExit**: `ai.*` and `profile_text()` report user-facing problems (no key, model rejected, template profile) as `SystemExit`, which `except Exception` does not catch. Background paths catch `(Exception, SystemExit)`.
- **Run**: `lodestar doctor` (add `--live` for one real AI call per provider), `lodestar desktop` (WebView2 window; falls back to the browser).
- **Gotcha, icon**: write `.ico` frames as classic BMP. Pillow's PNG-compressed frames render in Explorer but garble in .NET `System.Drawing.Icon` (used by pywebview).
- **Gotcha, installer**: changes to `install.ps1` only apply after it is re-run (regenerates the launcher and desktop shortcut).
- **Gotcha, real calls**: no real AI or SMTP call has been verified yet; the tests use a faked HTTP layer.
