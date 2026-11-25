# 0009: A deny list kept by hand misses routes; sweep the code for the effect instead
Status: proposed
Date: 2026-11-18
Area: phone.py (DENY / DENY_RUN), web.py

Observed failure: the phone listener let a paired phone POST `/api/prefs` (set `update_origin` + `update_mode`, so the
updater would fetch and run another repository's code), `/api/tools`, `/api/master/open`, `/api/view/open`,
`/api/studio/<id>/open`, the apply agent's start / login / forget and several run actions that act on this PC. A first
fix by hand still missed `/api/studio/<id>/open` and `activity`; a second reviewer found them.
Root cause: DENY was a list of routes someone remembered to add; nothing tied it to what a route does.
Evidence: two independent review passes (pass 56 review), `tests/test_phone.py` failing on `/api/studio/1/open`.
Correction: the routes added to DENY / DENY_RUN; `test_every_route_that_acts_on_this_pc_is_refused` sweeps web.py for
every route whose branch opens a file, a browser or a process and asserts the phone refuses it.
Lesson: guard a security boundary with a test that derives its cases from the code (the effect), not with a list a
person keeps; a new route then fails the test until it is classified.
Promoted to: test (`test_phone.Pairing.test_every_route_that_acts_on_this_pc_is_refused`).
