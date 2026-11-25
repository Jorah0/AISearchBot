# Engineering lessons

Reviewed lessons from real mistakes in this repository: the "verified learning" layer of the engineering loop. A lesson
is here only when the failure was reproduced, fixed, and protected by a test, a hook or a rule. One-off details stay in
the commit or issue; nothing here comes from a guess.

## The rule: evidence before permanence

1. **Capture** what failed and how it was detected (test name, command output).
2. **Find the root cause**, not the first guess.
3. **Fix the code and add the regression test first.** Never change instructions to make up for a software defect.
4. **Ask if it generalises.** A lesson must be accurate, reusable, non-sensitive and not in conflict with another rule.
5. **Promote it to the narrowest layer that enforces it**: test or CI gate > hook / permission > CLAUDE.md or
   `.claude/rules/` > skill > agent definition > this file alone.
6. **Review**: a lesson is `proposed` until a person accepts it (status `adopted`). An AI may draft one; it never
   adopts one.
7. **Prune**: when the code changes so a lesson no longer holds, mark it `retired` (keep the file: the history matters).

Never put keys, passwords, cookies, personal data or real mail in a lesson.

## Template

Copy to `NNNN-short-title.md`:

```markdown
# NNNN: <short title>
Status: proposed | adopted | retired
Date: YYYY-MM-DD
Area: <module / workflow>

Observed failure: what happened and how it was detected.
Root cause: the verified cause.
Evidence: reproduction, test names, command output.
Correction: the code fix and the regression test.
Lesson: the smallest accurate general rule.
Promoted to: test | hook | rule | skill | agent | ADR | none (and where)
Approved by: <name, when adopted>
```

## Index

| # | Lesson | Promoted to | Status |
|---|---|---|---|
| [0001](0001-shell-heredocs-mangle-escapes.md) | Shell heredocs rewrite `\n` / `\b` inside code: write files with an editor tool or a script file | rule (CLAUDE.md) | proposed |
| [0002](0002-css-selectors-must-be-scoped.md) | A bare element selector (`nav { ... }`) restyles every match, drawers included | test (`e2e_selfcheck`, browser suite) | proposed |
| [0003](0003-labels-collide-with-role-locators.md) | An accessible label that contains another control's name breaks role/name lookups | rule (`lodestar-reviewer`) | proposed |
| [0004](0004-tests-must-restore-shared-state.md) | A test that changes the shared profile or a class-level fake must put it back | rule (CLAUDE.md) + tests | proposed |
| [0005](0005-ai-verdicts-need-a-deterministic-veto.md) | A small model's judgement that can hide data needs evidence the AI cannot override | test (`test_novelty`) | proposed |
| [0006](0006-native-tools-in-powershell.md) | PowerShell turns a native tool's stderr into an error and cmd splits `;`: run SDK tools through Start-Process / a .bat | skill (engineering-loop) | proposed |
| [0007](0007-select-every-column-a-view-reads.md) | A view that reads a new column fails when the query lists columns by name | test (`e2e_novelty`) | proposed |
| [0008](0008-patch-scripts-must-be-idempotent.md) | A scripted insert after an anchor runs twice unless it checks the addition is absent | rule (engineering-loop skill) | proposed |
| [0009](0009-deny-lists-need-a-sweep.md) | A hand-kept deny list misses routes: a test sweeps the code for the effect | test (`test_phone`) | proposed |
| [0010](0010-docs-need-the-escape-check-too.md) | The heredoc escape rule (0001) misses documentation: Markdown is never compiled, so check docs for control characters too | test (proposed, `test_pass16_audit_b.Hygiene`) | proposed |
| [0011](0011-a-red-verify-must-not-be-committed.md) | A safety guard was stubbed out and committed while verify was red | hook (proposed, `.githooks/pre-commit`) | proposed |
