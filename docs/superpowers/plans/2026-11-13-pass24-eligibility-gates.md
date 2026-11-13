# Pass 24: Eligibility Gates and Job Career Class Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Hard requirements (work authorization / sponsorship, clearance, required licenses, your exclusions) become eligibility gates with states met / not_met / unknown, kept out of the fit score (blueprint 7.2), and every job and listing gets a career class (blueprint 4.4, 7.3, 18.3).

**Architecture:** `fit.gates(x, ctx)` beside `fit._mods`. `fit.score` stops blending clearance, deal-breaker and exclusion effects into the number (`blocked_cap` goes), and stores `gates` + `confidence`. `blocked` keeps its meaning for every consumer: a gate is not_met. `fit.job_class(fit)` maps gates + score to `careers.CLASSES`. The fit config version bumps, so every stored fit is stale and the loop refreshes it.

**Spec:** blueprint v1.1 §4.4, §4.5, §7.2, §7.3, §18.3; master plan Part D, Pass 24.

## Global Constraints
- Master plan Global Constraints apply.
- Verbatim: "A hard gate can be 'not met,' 'met,' or 'unknown'; unknown must not be interpreted as met."
- Gates never hold a salary-floor figure (fit is private, but evidence strings must still be floor-free).
- `fit.json` "version" bumps from 1 to 2 (fit.rev() changes -> stale -> refreshed).

## Review Focus
1. A posting silent on sponsorship for a user who needs it: gate unknown, never met; auto_track never auto-adds it (force_pending).
2. A user who never set work_authorization, posting says "no sponsorship": unknown (their status is not known), not not_met.
3. A license phrase inside "nice to have": preferred, not a gate (test in Task 1).
4. Excluded company: score still computed (not capped at 10), blocked true, class ineligible.

### Task 1: fit.gates + score without blended gates
**Files:** modify `lodestar/fit.py`, `lodestar/data/fit.json`; test `tests/test_pass24_gates.py`.
**Produces:** `fit.gates(x, ctx) -> list[{"requirement": str, "state": "met"|"not_met"|"unknown", "evidence": str}]`; `score()` adds `gates`, `confidence` (= known), `gates_unknown: bool`; `blocked` = any not_met.
- [ ] Tests: sponsorship (needs + "no sponsorship" -> not_met; needs + silent -> unknown; authorized + "no sponsorship" -> met; unset + "no sponsorship" -> unknown); clearance required + resume mentions clearance -> met, else unknown; "must hold a valid CDL" -> gate "CDL ..." unknown without a matching certification, met with one; the same phrase only under "Preferred" -> no gate; excluded company / title word / deal-breaker -> not_met with blocked True and the score equal to the same job's score without the exclusion.
- [ ] Implement, bump fit.json version, drop the `clearance`, `dealbreaker` modifiers and `blocked_cap`.
- [ ] Update pinned fit tests in older modules only where they asserted the blended numbers (rule each in the ledger).

### Task 2: job career class + consumers
**Files:** modify `lodestar/fit.py`, `lodestar/apply.py` (auto_track), `lodestar/pipeline.py` (fit gate), `lodestar/static/app.js` (card + drawer); tests in `tests/test_pass24_gates.py`, `tests/e2e/e2e_fit.py`.
**Produces:** `fit.job_class(fit: dict) -> str` with `careers.CLASSES` keys: any not_met -> ineligible; any unknown gate or partial -> insufficient_evidence; score >= 75 -> qualified_now; >= 55 -> competitive_with_framing; >= 35 -> bridge_required; else longer_term. `fit.light()` adds `fit_class`, `fit_class_label`.
- [ ] Tests: the table above; auto_track proposes a job with an unknown gate only with force_pending; the pipeline fit gate treats not_met as blocked and unknown as needing you.
- [ ] UI: the class label as a text chip on board cards and All jobs, a Gates list (requirement, state, evidence) in the drawer's Fit group, "confidence N%" beside the score; E2E in e2e_fit.
