# 0008: A patch script that may run twice must check before it inserts
Status: proposed
Date: 2026-11-18
Area: docs/TESTS.md, scratch patch scripts

Observed failure: re-running a script that appended a sentence after an anchor ("baseline comparison)") inserted the
sentence a second time, because the anchor was still present after the first run.
Root cause: `str.replace(anchor, anchor + addition)` is not idempotent; nothing checked whether the addition was there.
Evidence: `grep -c "user-level Stop hook" docs/TESTS.md` returned 2 after the second run.
Correction: the duplicate removed; the row checked by grep.
Lesson: a scripted insert asserts the addition is absent first (`assert addition not in text`), or replaces whole known
content instead of appending after an anchor.
Promoted to: rule (engineering-loop skill, tooling notes).
