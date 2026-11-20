# 0001: Shell heredocs rewrite escapes inside code
Status: proposed
Date: 2026-11-18
Area: tooling (agent edits)

Observed failure: Python patch scripts passed through a bash heredoc wrote real newlines where the code said `\n`, and
backspace characters where it said `\b`. Detected by SyntaxError / unterminated string literal (lodestar/apply.py
task_ideas, web.py look_pick, tests/e2e/e2e_advisor.py) and a regex that silently stopped matching.
Root cause: the shell and the Python string literal both process escapes; one layer too many.
Evidence: `py_compile` failures; `node --check` on app.js; grep showing literal line breaks inside strings.
Correction: rewrote the lines with the editor tool; later patches written as script files (scratchpad) and run.
Lesson: never pass code containing backslash escapes through a heredoc or an inline `-c`; write the file with an editor
tool or a script file, then run `py_compile` / `node --check` on what changed.
Promoted to: rule (CLAUDE.md > Project contract).
