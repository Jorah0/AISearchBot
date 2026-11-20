# 0005: AI verdicts that can hide data need a deterministic veto
Status: proposed
Date: 2026-11-18
Area: novelty.py (new listing or copy?)

Observed failure: in a live check the local Ollama model called a payroll job in Dallas (Req 5120) a "repost" of a
stores job in Austin (Req 4471); auto-track would have skipped a genuinely new job. Claude judged it correctly.
Root cause: a small model's judgement treated as final on a decision that removes something from view.
Evidence: live run of novelty._ask on both providers; tests/test_novelty.py.
Correction: `novelty.veto()`: different requisition numbers or places over 50 miles apart are new whatever the AI says;
a bad answer leaves the listing new and marked unchecked.
Lesson: when an AI verdict hides, merges or skips something, add the cheap evidence checks it may not override, and
default to showing the item when the AI fails.
Promoted to: test (`test_novelty.Novelty.test_evidence_overrides_a_wrong_same_or_repost`).
