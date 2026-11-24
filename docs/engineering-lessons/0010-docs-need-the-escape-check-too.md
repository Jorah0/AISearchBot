# 0010: The heredoc escape rule (0001) misses documentation
Status: proposed
Date: 2026-11-23
Area: tooling (agent edits), docs

Observed failure: a Python doc-patch script run through a bash heredoc wrote `android` + U+0008 + `uild.ps1` where the
text said `android\build.ps1`, in docs/SETUP.md, docs/TESTS.md (the android-update row) and android/README.md. An older
`cache\boards` in docs/SETUP.md had the same defect. Found by the fresh-context reviewer (`grep -P '\x08'`), not by
verify: Markdown is never compiled, so 0001's `py_compile` / `node --check` step never sees it.
Root cause: the same as 0001 (the Python string literal turned `\b` into a backspace); the rule's check covers code only.
Evidence: `grep -cP '[\x00-\x08\x0b\x0c\x0e-\x1f]' docs/*.md android/README.md CLAUDE.md` was non-zero before the fix.
Correction: rewrote the four lines from a script file in the scratchpad (backspace back to a backslash + b).
Lesson: the 0001 rule applies to docs too, and a rule is not enough: a test should reject C0 control characters (other
than tab, LF, CR) in tracked text files (`*.md`, `*.py`, `*.js`, `*.html`, `*.css`, `*.java`, `*.ps1`).
Promote to: test (proposed: one unit test in tests/test_pass16_audit_b.Hygiene that walks `git ls-files` for those
suffixes and fails naming file:line). Not added: adopting it is the user's call.
