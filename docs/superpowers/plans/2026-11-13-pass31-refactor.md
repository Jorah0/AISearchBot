# Pass 31: Refactor and Cleanup to the Blueprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove what still contradicts the blueprint, delete dead code, give each duplicated helper one home, and
split extras.py (8+ boundaries) along the blueprint's service boundaries, with no behaviour change except the
listed contradiction fixes.

**Architecture:** Behaviour fixes first (each TDD), then mechanical moves with `from .new import name` re-exports in
the old module so every caller and every test patch keeps working; a moved function that tests patch on its old
module is not moved (see hazards). Pass 30 docs/TESTS.md conventions apply.

**Spec:** blueprint v1.1; audit `docs/superpowers/specs/2026-11-13-refactor-audit.md`.

## Global Constraints
- Master plan constraints apply (tests, TESTS.md rows + counts, additive DB, never push).
- A move never changes a public name; the old module re-exports it. Never move a name tests patch on its module
  (web_monitor.SOURCES/fetch/fetch_json/notify/sources_ready, resume.candidate_text, extras.PAGE_PAUSE,
  approvals.send_email, occupations.DATA).
- Source-reading tests stay true: '"/TN", "lodestar"' in extras.py; 'save_doc(job, name,' in web.py; parse_xml in
  intel.py / web_monitor.py; the pass-30 allow-list (careers.py, extras.py, db.py).
- Full unit suite after every task; full E2E (PowerShell) after Tasks 4 and 6.

## Review Focus
1. A civil-engineer or security-officer search must still ask The Muse (all categories), not only software / IT.
2. 'intern' must not match 'internal' in board keyword filters; a phrase filter ('customer service') still works.
3. Research text marked (unverified) must never reach a cover letter or form-answer prompt.
4. Moved helpers keep identical behaviour on Windows (atomic write retry) and on naive vs aware datetimes.

### Task 1: Blueprint contradictions (behaviour, TDD) - tests/test_pass31_refactor.py
- [ ] Muse: `_muse` stops narrowing by MUSE_CATEGORIES (no category filter; keyword filter does the matching);
  test: a 'civil engineer' query requests no `category=Software` / `IT`.
- [ ] Keyword filters whole-word: `web_monitor._has_all` uses whole-word / phrase matching and the four re-inlined
  copies call it; test: 'intern' rejects 'Internal Auditor', accepts 'Marketing Intern'.
- [ ] Unverified research out of employer prompts: `extras.research_for_prompts(job) -> str` drops lines containing
  '(unverified)'; apply.py form answers and resume.py cover letter read it; test with a research.md holding one
  verified and one unverified line.
- [ ] Sponsorship signals out of the score: drop `sponsor_yes` / `sponsor_hint` modifiers (they stay chips: the gate
  already carries 'offers sponsorship'); fit.json version 3; fit.py docstring updated; test: score equal with and
  without "Visa sponsorship is available"; existing pass-21 test re-pinned under a ruling.
- [ ] app.js JS-set search placeholder: industry examples; extend test_pass30_agnostic to scan `placeholder =` and
  `.placeholder` assignments in app.js.

### Task 2: Dead code
- [ ] Delete apply_agent.DONE, pipeline.GLOBAL, advisor.FORBIDDEN (grep proves no reader). Keep note_posting /
  mock_turn (test + e2e seeds use them) under a ruling.

### Task 3: One home per helper (util / db), copies become aliases
- [ ] `util.now_utc()`-style: `db._now` is the home; connections / intel / listings `_now = db._now` (pipeline keeps
  microseconds). `util.short_hash(s, n=12)` for fit._h / pipeline._h. `db.load_json(v, default)` for interview._load /
  pipeline._load. `util.word_in(word, text)` for careers._word_in / profile._mentioned / fit inline. `util.to_local`
  for extras / readiness / calendar_busy. `util.write_json_atomic(path, data)` with settings' Windows retry, used by
  settings, extension, connections, vault, profile, comp (comp becomes atomic).
- [ ] Tests: one unit test per new util helper (edge cases: aware vs naive, retry on PermissionError, word in
  punctuation, phrase).

### Task 4: Split extras.py along boundaries (re-exported from extras)
- [ ] `backup.py`: in_backup, backup, restore_*, export_data. `analytics.py`: digest, activity / analytics /
  goal_progress, MIN_N, export_obsidian. `ingest.py`: import_document, pdf_text, _html_text, _odt_text, _rtf_text.
  `calendar_busy.py` gains parse_when, ics_text, ics, conflicts, upcoming_interviews. `ai_safety` stays in extras?
  No: `_fence` / `clean_label` move to `ai.py`. research / company_pages / schedule stay in extras (patch +
  static-test hazards).
- [ ] extras imports each moved name back (`from .backup import ...  # noqa: F401`); CLAUDE.md lines naming
  `extras.*` updated to the new homes.
- [ ] Prove: full unit + full E2E.

### Task 5: Answer bank out of pipeline.py
- [ ] `answers.py`: classify .. suggestions, never_ai, yours, for_prompts, CANON_KEYS; re-exported from pipeline.

### Task 6: One registrable-domain rule
- [ ] `util.registrable(host) -> str` and `util.org_label(host)` from email_monitor's TWO_PART_SUFFIXES rule;
  email_monitor and extras call it (fail-closed); tests: jobs.ibm.ca -> ibm, careers.sap.de -> sap, hr.bt.uk -> bt
  for both company-page vetting and mail; full unit + E2E.

### Task 7: Retire the resume.candidate_text shim
- [ ] Callers use profile.candidate_text; the 4 test patches move to profile.candidate_text; delete the shim.
