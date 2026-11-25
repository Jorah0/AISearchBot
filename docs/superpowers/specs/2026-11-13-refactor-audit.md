# Lodestar refactor audit against blueprint v1.1 (2026-11-13, branch blueprint-v1.1 @ 8d2798f)

Read-only audit; every item was grep- or run-checked. Input to the refactor plan.

## Boundary map
Career Profile: profile, studio, lint | Occupation Intelligence: occupations, careers, gaps, paydata, comp |
Discovery: web_monitor, listings, alerts, apply_find | Matching: fit, ats, boosters | Documents: resume, render,
viewer, lint, drafts, mailfiles | Application Workflow: pipeline, apply, apply_agent, apply_ats, accounts, extension |
Email: email_monitor, mailconn, oauth, codes, contacts | Interview/Calendar: interview, readiness, calendar_busy |
Analytics: intel + extras analytics | Policy: policy, approvals, settings, config.full_ai_check | AI: ai, advisor,
ideas, connections | Platform: web, cli, desktop, loop, updater, doctor, vault, util, log, inventory, db.
Mixed: extras.py (8+ boundaries: outreach :24, calendar :50-98 / conflicts / upcoming_interviews, digest / obsidian /
activity / analytics :1266-1409, schedule :184, backup/restore :709-1004, export_data :1010, _fence / clean_label
:207-223, company_pages / research :335-476, ext autofill :556-609, import_document + readers :1109-1232, packet,
resume_hash); apply.py (answers, follow-up / thanks / withdraw, offer / counter, auto_track, slots); pipeline.py
(engine + answer-bank policy classify..suggestions :213-298); web_monitor.py (adapters + ranking + normalisers);
resume.py (docs + pay parsing + candidate_text shim :155); db.py (persistence + funnel / variants / derive_fields).
16 import cycles (GRAPH_REPORT.md:258-273). Largest functions: cli.build 584 lines, web.do_POST 563, web._do 371.

## Dead code
apply_agent.py:32 DONE; pipeline.py:34 GLOBAL; advisor.py:33 FORBIDDEN (docstring-only). Test-only: db.note_posting
(e2e seeds use it), interview.mock_turn. UI-orphaned: /api/apply/* routes (no page controls for the apply agent).

## Duplication (single home)
_now (db:401, connections:66, intel:51, listings:22 -> db._now); sha1[:12] _h (fit:53, pipeline:88 -> util);
JSON column _load (interview:775, pipeline:148 -> db); ISO day parsing (intel:200, web_monitor:624, listings:38,
extras:1246, db:293); UTC->local (extras:1250, readiness:30, calendar_busy:18 -> util); atomic JSON write (settings:236
with retry, extension:157, connections:89, vault:43, profile:128, comp:15 not atomic -> util with retry); whole-word
match (careers:127, profile:2042, fit inline -> util); _has_all re-inlined at web_monitor:665/689/713/736;
registrable domain extras:277 vs email_monitor:49/61 DISAGREE (jobs.ibm.ca -> 'jobs' vs 'ibm'); host-or-subdomain
x9; company-name normalisation db:606 vs web_monitor:1051; resume.candidate_text shim -> profile.

## Test hazards
Unit tests patch module attributes (web_monitor.SOURCES/fetch/fetch_json/notify/sources_ready, occupations.DATA,
resume.candidate_text x4, extras.PAGE_PAUSE, approvals.send_email, ai.ask/ask_json): a moved function escapes
patches on its old module. E2E harness rebinds paths and functions across all modules. Source-reading tests:
test_pass30_agnostic (allow-list careers/extras/db), test_matrix_gaps:208 ('"/TN", "lodestar"' in extras.py),
test_overview_profile_resume_ai:270 ('save_doc(job, name,' in web.py), test_xml_safety:35 (parse_xml in intel /
web_monitor), apply engine / accounts static scans.

## Blueprint contradictions still in code
1. web_monitor.py:720 MUSE_CATEGORIES: 'engineer*' -> Software Engineering, 'security' -> IT; _muse asks only that
   category: civil engineer sees software listings only (silent narrowing).
2. app.js:1375 JS-set placeholder 'data engineer, analytics engineer' (agnostic test only reads placeholder="...").
3. extras.py:526 research asks for "what you reliably know" (unverified) and research.md feeds employer-facing
   prompts (apply.py:39-40 form answers, resume.py:572 cover letter).
4. fit.py:400-404 sponsorship +5 / H-1B hint +3 still move the score; fit.py:3 docstring still lists dealbreakers /
   clearance as modifiers.
5. Status moves outside approvals default actor="user" (apply.py:316, db.py:1224-1225).
6. Source keyword filters match substrings (web_monitor.py:639/665/689/713/736: 'intern' ~ 'internal').
7. Apply agent has no UI controls (UI phase).
