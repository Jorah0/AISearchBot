# 0004: Tests that change shared state must put it back
Status: proposed
Date: 2026-11-18
Area: tests

Observed failure: a new advisor browser test applied a profile change and left it; the next test's suggestion was then
flagged and its Apply did nothing ("Tick at least one suggestion first"). Earlier, a class-level `ai_json` fake was
restored to the already-mutated value.
Root cause: the browser tests share one home per class; class attributes are shared by every test in the class.
Evidence: tests/e2e/e2e_advisor.py test order; the panel snapshot in tests/e2e/_artifacts.
Correction: the test presses Undo AI changes at the end; cleanups capture the original value before mutating.
Lesson: capture the original before changing shared state and restore it in a cleanup (addCleanup), never by re-reading
the attribute you just changed.
Promoted to: rule (CLAUDE.md already: "a test that monkeypatches a module attribute must restore it").
