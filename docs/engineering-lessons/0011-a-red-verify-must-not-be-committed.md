# 0011: A safety guard was stubbed out and committed while verify was red
Status: proposed
Date: 2026-11-24
Area: apply agent, commits

Observed failure: commit 9d93d9c (CAPTCHA solver) replaced `apply_agent.forbidden()` with `return None` and removed the
`forbidden` check from `apply_ats.decide`, so the apply agent could load LinkedIn / Indeed / Glassdoor / ZipRecruiter /
SimplyHired again (CLAUDE.md > Apply agent). 15 unit tests failed from then on; the commit also brought 6 pyflakes
errors (`captcha_solver.py`: an undefined `CHECKBOX`, unused imports). Found two commits later while verifying unrelated
work, not when it was committed.
Root cause: the commit was made without a passing `scripts/verify.py`; the pre-commit hook runs only the staged secret
scan, and the Stop gate checks Claude sessions, not commits made elsewhere.
Evidence: the same 16 failures on a clean HEAD worktree; `git show 9d93d9c -- lodestar/apply_agent.py lodestar/apply_ats.py`.
Correction: restored both guard bodies from the parent commit and fixed the lint; the tests went green.
Lesson: a guard the tests pin must never be disabled to make a feature work; and a red verify must not reach a commit.
Promoted to: hook (proposed: `.githooks/pre-commit` also runs lint + the guard tests, `test_apply_engine.Policy`, when
`lodestar/apply_*.py` is staged). Not added: adopting it is the user's call.
