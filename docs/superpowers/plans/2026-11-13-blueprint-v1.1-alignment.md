# Blueprint v1.1 Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Lodestar in line with the *AI Career Agent Product & Development Blueprint v1.1*. Its defining v1.1 capability is industry-agnostic career discovery: a resume used as evidence, never as a boundary. Close the remaining gaps (eligibility gates kept apart from fit, a central policy service, source coverage, the application lifecycle, fact states, calendar availability, skill-gap planning) without rewriting what already works.

**Architecture:** Lodestar stays a local, single-user Python app (stdlib HTTP server + SQLite + static UI + OS keyring). The blueprint's behavioural rules are adopted in full. Its recommended cloud stack is not (see *Decisions*). New capability arrives as focused modules: `occupations.py`, `careers.py`, `policy.py`, `gaps.py`. They plug into the existing choke points: `db.set_status`, `approvals.propose`, `web_monitor.search`, `fit.score` and `profile.write_master`.

**Tech Stack:** Python 3.11+ stdlib (`gzip`, `json`, `zipfile`, `csv`, `sqlite3`, `html.parser`), the existing `lodestar` package, O*NET 31.0 Database (CC BY 4.0) bundled as data, `unittest`, and Playwright with installed Edge for E2E.

**Spec:** *AI_Career_Agent_Product_and_Development_Blueprint.pdf* (v1.1, 2026-11-13), supplied by the user in the session that produced this plan. Executors need it alongside this file. Section numbers below (§4.3 etc.) refer to it.

---

## Part A: Where Lodestar stands against the spec

The legend is **Have**, **Partial** or **Missing**, with the pass that closes each gap. Lodestar already implements most of R1 and R3–R7 in a local-first form. The spec's core v1.1 promise (§4, §5, §18.2, §19.1) is the part that is missing.

| Spec | Requirement | Lodestar today | Status | Pass |
|---|---|---|---|---|
| §3.2 | Resume-led discovery | none (only `ideas pivot`, unstructured AI text) | Missing | 23 |
| §3.2 | Desired-field search | `jobs search` takes any query, but there is no persisted track and gaps go unlabelled | Partial | 23 |
| §3.2 | Combined / pivot planning | — | Missing | 23 |
| §3.2 | Open exploration (tier 6) | `ideas pivot` | Partial | 24 |
| §3.2 | Employer-led search | `companies` (Greenhouse/Lever/Ashby feeds), `watch` | Have | — |
| §4.2–4.3 | Discovery pipeline, expansion tiers 0–6 | — | Missing | 23 (0–5), 24 (6) |
| §4.4 | Six readiness classifications | — (`readiness.py` is *interview* readiness, an unrelated concept) | Missing | 23 occupations, 24 jobs |
| §4.5 | Regulated / safety-sensitive flags | clearance + sponsorship regexes in `data/fit.json` | Partial | 23 flag, 24 gate, 25 review |
| §4.6 | Breadth controls | `excluded_companies`, `excluded_title_words`, Deal-breakers | Partial | 23 |
| §5 | Versioned occupation ontology | `data/oews.json` (SOC subset for pay only) | Partial | 23 (O*NET 31.0) |
| §5.4 | why / what does not transfer / what is missing / how to close | — | Missing | 23 |
| §6.1 | Adapter interface | `web_monitor.SOURCES` functions + `EVERY`/`GLOBAL`/`KEYED`/`ATTRIBUTION` | Have (by convention) | — |
| §6.2 | USAJOBS, Greenhouse, Lever, company pages | all present | Have | — |
| §6.3 | Source capability registry | — | Missing | 26 |
| §6.4 | Freshness + dedupe | posting keys, `ats_id`, `posting_check` removed/reopened | Partial (no `last_verified_at`, no re-verify before apply) | 26 |
| §6.5 | Coverage reporting | `search(errors=, ran=)` collected but never shown as coverage | Partial | 23 tracks, 26 Jobs tab |
| §7.2 | Hard gates separate from fit | `fit.json` modifiers blend clearance −20 / dealbreaker −25 / `blocked_cap` into the score | Partial (conflicts with spec) | 24 |
| §7.3 | Score + separate confidence, readiness, mandatory/preferred gaps | score, chips, `unknown`, `nice_headings` | Partial | 24 |
| §7.4 | Reproducible, user-weighted, never a probability | `fit_weights` pref, deterministic breakdown | Have | — |
| §8.1 | DOCX/PDF/TXT/MD/HTML/RTF/ODT, scan detection | .docx/.pdf/.md/.txt; `resume audit` flags scans | Partial | 27 |
| §8.2 | CareerFact states extracted / user_confirmed / disputed / generated_wording | bank + import review + `profile.verify` flags | Partial | 27 |
| §8.3–8.4 | Variants, evaluation | studio versions, lint, audit, `check_rewrite`, `employer_safe` | Have | — |
| §8.5 | Claim diff | — | Missing | 27 |
| §8.6 | Never overwrite a submitted document; hashes | per-job docs never rewritten; no submitted snapshot | Partial | 26 |
| §9.1–9.3 | Workflow, answer bank, submission modes | pipeline, answers, `never_ai`, apply agent | Have | — |
| §9.4 | Mandatory approval gates in one place | scattered: `approvals._precheck`, `full_ai_check`, `mailfiles`, `apply_agent.forbidden` | Partial | 25 |
| §9.5 | Receipts, idempotency | `apply_runs`, `record_submission`, an `unknown` run is never retried | Have | — |
| §10.1 | Gmail API, read-only scope | IMAP + XOAUTH2 (needs Google's full-mail scope) | Divergent | 31 (optional) |
| §10.2–10.6 | Rules, classification, association, drafts, follow-ups | `email_monitor`, `drafts`, follow-up cadence | Have (holiday handling unverified) | 28 check |
| §11.1 | Job vs Application separated | `postings` (Job) vs `jobs` (Application) via `postings.job_id` | Have, undocumented | 26 doc |
| §11.2 | Full lifecycle | 8 board statuses | Partial | 26 |
| §11.3 | Transition evidence (actor, evidence, from/to) | `events(kind, detail)` text | Partial | 26 |
| §11.4–11.5 | Detail page, recruiter CRM | drawer, `contacts` | Have | — |
| §12.1–12.2 | FreeBusy availability, buffers | `availability` pref, `.ics`, conflict guard | Partial | 28 |
| §12.3 | Profession-aware prep | prep pack; `extras.py:510,527` default to "engineering culture" / "stack" | Partial (software bias) | 28 |
| §13.1–13.2 | Analytics with sample thresholds | insights, funnel, variants, `extras.MIN_N` | Have | 29 adds by-track |
| §13.3 | Skill-gap planner across jobs | per-job `resume.gap`, `boosters.across` | Partial | 29 |
| §13.4 | Offer analysis | `offers compare/counter`, `offer` | Have | — |
| §14 | Narrow agents, typed contracts, deterministic final authority | `settings.TOOLS` + pipeline stages + `approvals` executors | Have in shape | 25 formalises |
| §16.3 | Event UUID/schema/actor/correlation | — | Partial | 25 audit, 26 stage events |
| §17 | Security controls | keyring vault, host check, token, SSRF guard, fences | Have | — |
| §17.2 | `authorize() -> ALLOW / REQUIRE_APPROVAL / BLOCK / HANDOFF` with a recorded decision | — | Missing | 25 |
| §18.2 | Career Discovery workspace | — | Missing | 23 |
| §18.3 | Job card: readiness label, why surfaced, direct/adjacent/bridge | fit chips | Partial | 24 |
| §18.4 | Approval center | Inbox | Have | — |
| §20.2–20.3 | v1.1 + MVP acceptance | 928 unit / 227 E2E tests, none on discovery | Partial | 30 |
| §21 | Backups, retries, cost tracking, budgets | backup/restore, updater, doctor, `usage.jsonl`, autopilot budgets | Have | — |

## Part B: Decisions (what the plan deliberately does not do)

- **No stack migration.** Next.js, FastAPI, PostgreSQL, pgvector, Redis, Celery, S3, OpenTelemetry and tenant row-level security are recommended in §15, but §1 says "designed for one user initially". Lodestar is a working local desktop app with 1,155 tests. A rewrite would trade the spec's actual rules for its suggested tooling. The rules (gates, policy, provenance, coverage, append-only events) are adopted in full on the current stack.
- **No `JobSourceAdapter` Protocol class.** `web_monitor.SOURCES` + `EVERY` + `GLOBAL` + `KEYED` + `ATTRIBUTION` already form the adapter contract, and tests guard it. Pass 26 adds the missing `CAPABILITIES` registry in the same style.
- **No new Job/Application tables.** `postings` is the Job entity and `jobs` is the Application. Pass 26 documents this and adds append-only stage events, which is the part §11 actually needs.
- **No embeddings or vector search.** At single-user scale, matching through the O*NET title index and task/tech overlap is deterministic and explainable (§7.4). Add vector search when a measured recall problem appears.
- **No OCR dependency.** Scanned files are detected and the user is asked to paste text. §8.1 marks OCR as optional.
- **Name clash.** The spec's "readiness classification" is called **career class** in code (`careers.CLASSES`) because `readiness.py` is interview readiness. The UI uses the spec's labels verbatim.
- **Spec doc set (§22 dev process).** No PRODUCT_REQUIREMENTS.md, SYSTEM_ARCHITECTURE.md and so on. Part A of this plan is the traceability map, `docs/CHANGELOG.md` is progress.md, and `docs/TESTS.md` is the test plan.
- **Gmail API (§10.1).** The spec wants a read-only Gmail scope. IMAP needs Google's full-mail scope. This is the one real divergence; pass 31 (optional) adds a `gmail.readonly` API reader beside IMAP. Until then, Lodestar's own code never writes to the mailbox, which `email_monitor` already guarantees.

## Global Constraints

Every task's requirements include these.

- Spec, verbatim: "A match score is not a hiring probability or an employer ATS score."
- Spec, verbatim: "unknown must not be interpreted as met."
- Spec, verbatim: "The system must never broaden the search silently just to increase the number of results."
- Spec, verbatim: "never imply that it searched the entire internet or all employers when coverage was partial."
- Spec, verbatim: "Do not hard-code software, engineering, or a fixed list of professions as the universe of eligible work."
- Tier labels, verbatim (§4.3): 0 `Requested target`, 1 `Equivalent roles`, 2 `Closely related`, 3 `Transferable fit`, 4 `Bridge opportunity`, 5 `Longer-term pathway`, 6 `Explore further`.
- Class labels, verbatim (§4.4): `Qualified now`, `Competitive with framing`, `Bridge required`, `Longer-term development`, `Currently ineligible`, `Insufficient evidence`.
- O*NET credit, shown wherever its data is shown: `Source: O*NET 31.0 Database by the U.S. Department of Labor, Employment and Training Administration. Used under the CC BY 4.0 license.`
- Career suggestions and career classes are candidate-only: never in employer-facing text or prompts, and they never read the salary floor.
- Tests: `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` (unit) and `.venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"` (E2E, from PowerShell, never the Bash sandbox). pytest is not installed.
- A new test module sets `os.environ["LODESTAR_HOME"]` (temp) and `os.environ["LODESTAR_VAULT_SERVICE"] = ""` before importing `lodestar` (copy the header of `tests/test_pass22_find_search.py`). Every monkeypatched module attribute is restored in `finally`. Pin `web_monitor.SOURCES` in any test that searches.
- Every new test is named in a `docs/TESTS.md` row **in the same commit**, and the test counts in `CLAUDE.md` + `docs/TESTS.md` are bumped, or `tests/test_feature_matrix.py` fails. Copy the row format of the pass-22 rows.
- DB changes are additive only (`CREATE TABLE IF NOT EXISTS`, `*_MIGRATIONS` dicts). The user runs the app against their real `~/.lodestar` while passes are built.
- Paths that write tracks, settings or watches call `config.full_ai_check(...)` first. Background paths catch `(Exception, SystemExit)`.
- After editing `lodestar/static/*`, restart the server (`web.ASSETS` is read once).
- Commit locally after each task. Never push.

## Review Focus

These are the inputs most likely to break discovery for a real user that no feature test would otherwise exercise. Each one has its test in the owning task.

1. **Template or empty profile** (fresh install, nothing imported): suggestions are an empty list plus an "Insufficient evidence" note, never an exception, and a desired-field track still searches. *Task 2 `test_empty_profile_is_insufficient_evidence`, Task 4 `test_desired_field_searches_with_no_profile`.*
2. **Past titles O*NET does not know** ("Ninja Rockstar", internal titles): no guessed occupations; the note says insufficient evidence. *Task 2 `test_unmatched_title_is_insufficient_evidence`.*
3. **No board answers** (offline, all failing, keyed boards without keys): coverage says nothing was checked and lists the failures and missing keys, so "no jobs" is never claimed. *Task 4 `test_search_with_no_board_ready_says_nothing_checked`.*
4. **Messy track titles** (duplicates in different case, commas, more than the cap): stored once, case-insensitively, capped at 6, never silently expanded. *Task 3 `test_titles_are_deduped_and_capped`.*
5. **Occupation data missing or corrupt** (a packaged install without `data/onet.json.gz`): CLI and API answer with a clear message, never a 500. *Task 1 `test_missing_data_is_a_clear_error`, Task 6 `test_careers_route_survives_missing_data`.*

---

## Part C: Phase 1 (Pass 23), the career discovery foundation, in full

This is the spec's "Recommended first vertical slice" (§19.1): an uploaded resume (the existing import + review flow) is mapped to a versioned occupation taxonomy, produces direct-fit and transferable career tracks, and one chosen track searches the existing approved boards with visible coverage.

**Files**

| File | Responsibility |
|---|---|
| `scripts/build_onet.py` (new) | O*NET 31.0 text zip → `lodestar/data/onet.json.gz` (reproducible taxonomy updates) |
| `lodestar/data/onet.json.gz` (new, generated) | bundled ontology, about 1,016 occupations |
| `lodestar/data/regulated.json` (new) | SOC prefix → licensing note (data, extendable) |
| `lodestar/occupations.py` (new) | load the ontology, title index, `match_title`, `related`, `meta` |
| `lodestar/careers.py` (new) | evidence, tiers, classes, `suggest`, tracks CRUD, `search_track`, coverage |
| `lodestar/db.py` (modify) | `career_tracks` table in `SCHEMA`; `"track_id": "INTEGER"` in `POSTING_MIGRATIONS` |
| `lodestar/cli.py` (modify) | `lodestar careers ...` |
| `lodestar/web.py` (modify) | `/api/careers*` routes |
| `lodestar/static/index.html`, `app.js`, `app.css` (modify) | Careers tab |
| `pyproject.toml` (modify) | package-data `data/*` already matches `.gz`; verify only |
| `tests/careers_fixture.py` (new) | tiny O*NET-shaped ontology + bank, shared by the unit and E2E tests |
| `tests/test_pass23_careers.py` (new) | unit tests |
| `tests/e2e/e2e_careers.py` (new) | browser tests |

### Task 1: Occupation ontology (O*NET 31.0)

**Files:**
- Create: `scripts/build_onet.py`, `lodestar/occupations.py`, `lodestar/data/onet.json.gz`, `tests/careers_fixture.py`, `tests/test_pass23_careers.py`
- Modify: `docs/TESTS.md`, `CLAUDE.md` (test count)

**Interfaces:**
- Produces:
  - `scripts/build_onet.build(zip_path: Path, out: Path, version: str) -> dict` returns meta.
  - `occupations.DATA: Path` = `Path(__file__).parent / "data" / "onet.json.gz"`.
  - `occupations.load() -> dict` returns `{"meta": {...}, "occ": {code: Occ}}`, cached per `(DATA, mtime)`, so a test that patches `DATA` gets fresh data.
  - `occupations.meta() -> dict` with keys `version, source, url, license, credit, built`.
  - `occupations.get(code: str) -> dict | None`.
  - `occupations.match_title(title: str, n: int = 5) -> list[tuple[str, float]]`.
  - `occupations.related(code: str) -> list[str]`.
  - `occupations.ZONE_PREP: dict[int, str]`.
  - Occ dict: `{code, title, desc, zone: int | None, titles: list[str], related: list[str], tasks: list[str], tech: list[str]}`.
  - `tests/careers_fixture.write_fixture(path: Path) -> Path` and `tests/careers_fixture.BANK: dict`.

- [ ] **Step 1: Write the fixture.** `tests/careers_fixture.py` holds `OCC` with exactly these codes. Keys are code, title, zone, titles, related (in this order), tasks and tech, and the zones and relations shown are what the Task 2 tests assume. `write_fixture` gzips `{"meta": {"version": "test", "source": "O*NET test fixture", "url": "https://www.onetcenter.org/database.html", "license": "CC BY 4.0", "credit": "test", "built": "2026-11-13"}, "occ": {...}}`, adding `code` and `desc: ""` to each entry.

```text
41-1011.00 First-Line Supervisors of Retail Sales Workers  zone 3  titles [Store Manager, Assistant Store Manager, Retail Store Manager]
           related [41-2031.00, 11-2022.00, 11-9051.00, 13-1081.00, 43-4051.00, 11-1011.00]
           tasks [Direct and supervise employees engaged in sales, inventory-taking, reconciling cash receipts.,
                  Prepare work schedules and assign employees to specific duties.,
                  Formulate pricing policies for merchandise.]
           tech [Microsoft Excel, Inventory management software, Point of sale POS software]
41-2031.00 Retail Salespersons            zone 2  titles [Sales Associate, Retail Sales Associate]  related [41-1011.00]  tech [Point of sale POS software]
43-4051.00 Customer Service Representatives zone 2 titles [Customer Service Representative]       related [41-2031.00]  tech [Customer relationship management CRM software]
11-2022.00 Sales Managers                 zone 4  titles [Sales Manager]                           related [41-1011.00]  tech [Salesforce software, Microsoft Excel]
11-9051.00 Food Service Managers          zone 3  titles [Restaurant Manager]                      related [41-1011.00, 11-9081.00] tech [Microsoft Excel]
13-1081.00 Logisticians                   zone 4  titles [Logistics Analyst]                       related [41-1011.00]  tech [SAP software]
11-1011.00 Chief Executives               zone 5  titles [Chief Executive Officer]                 related []            tech []
11-9081.00 Lodging Managers               zone 4  titles [Hotel Manager, Hospitality Manager]      related [43-4081.00, 11-9051.00] tech [Property management system software]
43-4081.00 Hotel, Motel, and Resort Desk Clerks zone 2 titles [Front Desk Agent]                   related [11-9081.00]  tech []
29-1141.00 Registered Nurses              zone 3  titles [Registered Nurse, Staff Nurse]           related []            tech [Electronic health record EHR software]
```

Each occupation not listed with tasks gets one plausible task string. `BANK` is a `profile.empty()`-shaped dict with experience `[{"title": "Store Manager", "company": "Acme Retail", "start": "2019-01", "end": "2025-06", "bullets": ["Prepared weekly schedules for 14 employees", "Reconciled cash receipts and cut inventory shrink"]}]`, skills `[{"name": "Microsoft Excel"}, {"name": "Inventory management"}]` and education `[{"school": "Bay College", "degree": "Associate of Arts"}]`.

- [ ] **Step 2: Write the failing tests** in `tests/test_pass23_careers.py`, class `Ontology`. The module header follows Global Constraints. `setUp` writes the fixture to a temp dir and patches `occupations.DATA`; `tearDown` restores it.

```python
def test_build_script_reads_onet_text_zip(self):
    # zip with tab-separated members: "Occupation Data.txt", "Job Zones.txt", "Job Titles.txt",
    # "Related Occupations.txt", "Task Statements.txt", "Technology Skills.txt"; two occupations
    meta = build_onet.build(zip_path, out, version="31.0")
    data = json.loads(gzip.decompress(out.read_bytes()))
    o = data["occ"]["41-1011.00"]
    self.assertEqual(o["zone"], 3)
    self.assertIn("Store Manager", o["titles"])
    self.assertEqual(o["related"], ["41-2031.00", "11-2022.00"])     # by Related Index ascending
    self.assertEqual(o["tasks"], ["Direct and supervise employees ..."])  # Core only, Supplemental dropped
    self.assertEqual(o["tech"][0], "Microsoft Excel")                   # Hot Technology = Y first
    self.assertEqual((meta["version"], meta["license"]), ("31.0", "CC BY 4.0"))

def test_match_title_exact_and_fuzzy(self):
    self.assertEqual(occupations.match_title("store manager")[0], ("41-1011.00", 1.0))
    code, score = occupations.match_title("Sr. Store Manager")[0]
    self.assertEqual(code, "41-1011.00"); self.assertGreaterEqual(score, 0.5)
    self.assertEqual(occupations.match_title("Ninja Rockstar"), [])

def test_missing_data_is_a_clear_error(self):
    occupations.DATA = Path(self.tmp) / "nope.json.gz"
    with self.assertRaises(SystemExit) as cm:
        occupations.load()
    self.assertIn("occupation data", str(cm.exception))

def test_bundled_data_loads(self):  # the real file, not the fixture
    occupations.DATA = REAL_DATA
    self.assertGreaterEqual(len(occupations.load()["occ"]), 1000)
    self.assertEqual(occupations.meta()["version"], "31.0")
    self.assertTrue(occupations.get("41-1011.00")["title"].startswith("First-Line Supervisors"))
```

- [ ] **Step 3: Run them and confirm they fail.** Run `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pass23_careers.py" -v`. Expected: an ImportError for `occupations` or `build_onet`.

- [ ] **Step 4: Implement `scripts/build_onet.py`.**
  - CLI: `build_onet.py ZIP [--out lodestar/data/onet.json.gz] [--version 31.0]`.
  - Find members by basename, case-insensitively, anywhere in the zip. For titles, accept `Job Titles.txt`, else `Alternate Titles.txt`.
  - Parse each member with `csv.DictReader(delimiter="\t")`. Before parsing, check that the needed columns exist (`O*NET-SOC Code`, `Title`, `Description`, `Job Zone`, `Related O*NET-SOC Code`, `Related Index`, `Task`, `Task Type`, `Example`, `Hot Technology`). For titles, use the first header matching `(?i)alternate title|job title|reported job title`. If anything is missing, exit with the file name and the headers found.
  - Truncate `desc` to 300 characters. Keep up to 5 Core tasks, up to 25 tech examples (Hot = Y first, then file order), and all titles de-duplicated case-insensitively.
  - Write the output through `gzip` with `json.dumps(..., separators=(",", ":"))`. `meta.credit` is the credit line from Global Constraints.
  - Verify the column names against the 31.0 data dictionary (https://www.onetcenter.org/dictionary/31.0/text/) before running.

- [ ] **Step 5: Implement `lodestar/occupations.py`.**
  - `load` reads `DATA` with `gzip` + `json`, cached by `functools.lru_cache` on `(str(DATA), mtime)`. A missing or corrupt file raises `SystemExit("occupation data missing or unreadable: <path>; reinstall Lodestar or run scripts/build_onet.py")`.
  - The title index is built once per load: `web_monitor.norm_title(t) -> set(codes)` over each occupation's `title` and `titles`.
  - `match_title`: an exact normalised hit scores 1.0. Otherwise score with Jaccard similarity over words of three or more letters, keep only scores of at least 0.5, take the best score per code, sort descending and return the top `n`.
  - `ZONE_PREP = {1: "little or no preparation", 2: "some preparation: usually a high school diploma", 3: "medium preparation: vocational training, on-the-job experience or an associate's degree", 4: "considerable preparation: usually a bachelor's degree and several years of experience", 5: "extensive preparation: usually a graduate degree and extensive experience"}`.

- [ ] **Step 6: Build the real data file.**
  - Download `db_31_0_text.zip` (link on https://www.onetcenter.org/database.html) into the scratchpad.
  - Run `.venv\Scripts\python.exe -I scripts\build_onet.py <zip> --version 31.0`.
  - Expected: `lodestar/data/onet.json.gz` exists, under 3 MB, with `occ` ≥ 1,000.

- [ ] **Step 7: Run the tests and confirm they pass.** Same command as Step 3. Expected: 4 OK.

- [ ] **Step 8: Add a `docs/TESTS.md` row** "Occupation ontology (O*NET 31.0)" naming the four tests, then bump the counts.
- Run `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_feature_matrix.py"`. Expected: OK.

- [ ] **Step 9: Commit.** `git add scripts/build_onet.py lodestar/occupations.py lodestar/data/onet.json.gz tests/careers_fixture.py tests/test_pass23_careers.py docs/TESTS.md CLAUDE.md` then `git commit -m "Pass 23.1: bundled O*NET 31.0 occupation ontology + title index"`.

### Task 2: Career evidence, tiers, classes and suggestions

**Files:**
- Create: `lodestar/careers.py`, `lodestar/data/regulated.json`
- Modify: `tests/test_pass23_careers.py`, `docs/TESTS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1 `occupations.*`; `profile.load()`; `settings.pref("excluded_title_words")`; `profile.pref_field("Deal-breakers")`.
- Produces:
  - `careers.TIERS: dict[int, str]` holds the verbatim tier labels.
  - `careers.CLASSES: dict[str, str]` maps keys to the verbatim labels: `qualified_now`, `competitive_with_framing`, `bridge_required`, `longer_term`, `ineligible`, `insufficient_evidence`.
  - `careers.evidence(bank: dict | None = None) -> dict` returns `{titles, skills, certs, degrees, text, direct: [(code, score)], zone}`.
  - `careers.candidate_zone(direct: list[str], degrees: list[str]) -> int | None`.
  - `careers.classify(tier: int, zone: int | None, cand_zone: int | None, excluded: bool = False, regulated_unmet: bool = False) -> str`.
  - `careers.regulated(code: str) -> str | None`.
  - `careers.suggest(tiers=(1, 2, 3, 4, 5), limit=12, per_group=2, bank=None, targets=None, show_excluded=False) -> dict` returns `{suggestions: [Suggestion], zone, meta, note}`.
  - A Suggestion is `{code, title, tier, tier_label, cls, cls_label, zone, overlap, why, missing, not_transfer, close_gap, regulated, source}`. `source` is `"O*NET " + meta.version`, or `meta.source` when that does not start with "O*NET".

- [ ] **Step 1: Write the failing tests** in class `Discovery`. Setup is as in `Ontology`, plus `bank = careers_fixture.BANK`.

```python
def test_resume_led_tiers_and_classes(self):
    got = {s["code"]: (s["tier"], s["cls"]) for s in careers.suggest(bank=BANK)["suggestions"]}
    self.assertEqual(got, {
        "41-1011.00": (1, "qualified_now"),            # the user's own title
        "41-2031.00": (2, "qualified_now"),            # same major group, lower zone
        "11-9051.00": (3, "competitive_with_framing"),
        "43-4051.00": (3, "competitive_with_framing"),
        "11-2022.00": (3, "bridge_required"),          # zone 4 = candidate zone 3 + 1
        "13-1081.00": (3, "bridge_required"),
        "11-1011.00": (5, "longer_term"),              # zone 5 >= 3 + 2
    })

def test_every_suggestion_names_its_source_and_four_explanations(self):
    for s in careers.suggest(bank=BANK)["suggestions"]:
        self.assertEqual(s["source"], "O*NET test fixture")
        for k in ("why", "missing", "not_transfer", "close_gap"):
            self.assertIsInstance(s[k], list)
        self.assertTrue(s["why"])
    logi = next(s for s in careers.suggest(bank=BANK)["suggestions"] if s["code"] == "13-1081.00")
    self.assertIn("SAP software", logi["missing"])
    self.assertTrue(logi["close_gap"])                 # zone 4 > 3: ZONE_PREP[4] named

def test_tiers_are_never_broadened(self):
    got = careers.suggest(bank=BANK, tiers=(1,))["suggestions"]
    self.assertEqual([s["code"] for s in got], ["41-1011.00"])

def test_exclusions_drop_or_show_as_ineligible(self):
    old = settings.pref("excluded_title_words")
    try:
        settings.set_pref("excluded_title_words", "sales")
        codes = {s["code"] for s in careers.suggest(bank=BANK)["suggestions"]}
        self.assertFalse({"41-2031.00", "11-2022.00"} & codes)
        shown = {s["code"]: s["cls"] for s in careers.suggest(bank=BANK, show_excluded=True)["suggestions"]}
        self.assertEqual(shown["11-2022.00"], "ineligible")
    finally:
        settings.set_pref("excluded_title_words", old or "")

def test_unmatched_title_is_insufficient_evidence(self):
    bank = {**BANK, "experience": [{"title": "Ninja Rockstar", "company": "X"}], "education": []}
    out = careers.suggest(bank=bank)
    self.assertEqual(out["suggestions"], [])
    self.assertIn("Insufficient evidence", out["note"])

def test_empty_profile_is_insufficient_evidence(self):
    out = careers.suggest(bank=profile.empty())
    self.assertEqual((out["suggestions"], out["zone"]), ([], None))
    self.assertIn("Insufficient evidence", out["note"])

def test_desired_field_target_and_its_bridges(self):
    got = {s["code"]: s for s in careers.suggest(bank=BANK, targets=["11-9081.00"], tiers=(0, 1, 2, 3, 4, 5))["suggestions"]}
    self.assertEqual((got["11-9081.00"]["tier"], got["11-9081.00"]["cls"]), (0, "bridge_required"))
    self.assertEqual((got["43-4081.00"]["tier"], got["43-4081.00"]["cls"]), (4, "bridge_required"))
    self.assertEqual(got["11-9051.00"]["tier"], 3)      # lowest tier wins ...
    self.assertTrue(any("Lodging Managers" in w for w in got["11-9051.00"]["why"]))  # ... and names the route

def test_regulated_target_is_flagged_and_never_qualified(self):
    s = next(s for s in careers.suggest(bank=BANK, targets=["29-1141.00"], tiers=(0,))["suggestions"])
    self.assertIn("license", s["regulated"].lower())
    self.assertEqual(s["cls"], "bridge_required")       # no RN credential in evidence

def test_classify_table(self):
    C = careers.classify
    self.assertEqual(C(1, 3, 3), "qualified_now")
    self.assertEqual(C(2, 2, 3), "qualified_now")
    self.assertEqual(C(3, 3, 3), "competitive_with_framing")
    self.assertEqual(C(0, 3, 3), "competitive_with_framing")
    self.assertEqual(C(3, 4, 3), "bridge_required")
    self.assertEqual(C(4, 2, 3), "bridge_required")
    self.assertEqual(C(3, 5, 3), "longer_term")
    self.assertEqual(C(1, 3, None), "insufficient_evidence")
    self.assertEqual(C(1, 3, 3, excluded=True), "ineligible")
    self.assertEqual(C(1, 3, 3, regulated_unmet=True), "bridge_required")
```

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: an ImportError for `careers`.

- [ ] **Step 3: Write `lodestar/data/regulated.json`.** It is `{"_about": "SOC code prefixes whose work usually needs a license, registration or clearance; longest prefix wins. A hint, never an eligibility decision.", "29-1": "Licensed health practitioner: a state license or registration is usually required", "29-2": "Health technician: certification or a state license is often required", "23-1011": "Lawyer: bar admission is required", "53-3032": "Heavy truck driver: a commercial driver's license (CDL) is required", "47-2111": "Electrician: a state or local license is usually required", "47-2152": "Plumber: a state or local license is usually required", "33-": "Protective service: background checks and often certification are required", "25-2": "K-12 teacher: a state teaching certificate is usually required", "39-5012": "Cosmetologist: a state license is required", "41-9022": "Real estate agent: a state license is required", "13-2011": "Accountant: CPA licensure is required for some roles", "53-2011": "Pilot: an FAA certificate is required"}`. Add a `ponytail:` comment in `careers.regulated` that this is a seed list, extended as data.

- [ ] **Step 4: Implement `lodestar/careers.py`** (constants, `evidence`, `candidate_zone`, `classify`, `regulated`, `suggest`). The rules the signatures do not fix:

```text
evidence(bank): titles = experience[].title + volunteering[].role; skills = skills[].name + experience/projects technologies;
  certs = certifications[].name; degrees = education[].degree; text = all bullets joined;
  direct = codes with match_title(t, 1) score >= 0.8 for each title (max score per code).
candidate_zone(direct, degrees) = max zone of direct codes; else from degrees: doctoral/master/bachelor -> 4,
  associate -> 3, high school/GED -> 2; else None.
classify(tier, zone, cz, excluded, regulated_unmet):
  excluded -> ineligible; cz is None or zone is None -> insufficient_evidence; tier == 4 -> bridge_required;
  zone >= cz + 2 -> longer_term; zone == cz + 1 -> bridge_required;
  regulated_unmet -> bridge_required; tier <= 2 and tier != 0 -> qualified_now; else competitive_with_framing.
suggest: tiers come from direct (1), related(direct) with zone >= cz+2 (5) / same code[:2] as a direct code (2) / else (3),
  targets (0), related(target) with zone <= cz when zone(target) > cz (4). A code keeps its lowest tier; every route
  adds its own `why` line ("Your title 'Store Manager' is an O*NET title for ...", "Related to <title> in O*NET",
  "Also a route into <target title>", "Uses skills you list: ..."). Keep only tiers in `tiers`.
  overlap = |evidence skills found (casefold substring either way) in tech| / max(1, min(len(tech), 10)).
  missing = tech not in evidence, first 5; not_transfer = tasks sharing no word of 5+ letters with evidence text, first 3;
  close_gap = [ZONE_PREP[zone]] when zone > cz, plus the regulated note when set.
  regulated_unmet = regulated(code) and no evidence cert shares a word of 3+ letters with the occupation title.
  excluded = any excluded word (excluded_title_words + Deal-breakers) in title or titles (casefold).
  Drop excluded unless show_excluded. Sort by (tier, -overlap, code); at most per_group per code[:4] (tiers 0-1 exempt); cut to limit.
  No suggestions, or cz is None, sets note = "Insufficient evidence: no past title matched an O*NET occupation and no
  degree is on file. Add your roles in Profile, or add a career track for the field you want."
```

- [ ] **Step 5: Run the tests and confirm they pass.** Expected: all `Discovery` + `Ontology` OK.
- [ ] **Step 6: Add a TESTS.md row** "Career discovery: tiers, classes, explanations", bump the counts and run `test_feature_matrix`. Expected: OK.
- [ ] **Step 7: Commit.** `git commit -m "Pass 23.2: career discovery - expansion tiers, readiness classes, transfer explanations"`

### Task 3: Career tracks

**Files:**
- Modify: `lodestar/db.py`, `lodestar/careers.py`, `tests/test_pass23_careers.py`, `docs/TESTS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1 `match_title`, `get`; Task 2 `TIERS`.
- Produces:
  - `careers.INTENTS = ("resume_led", "desired_field", "combined", "exploration", "pivot")`.
  - `careers.TRAINING = ("none", "short_course", "certification", "apprenticeship", "degree", "open")`.
  - `careers.PRIORITY = ("high", "medium", "exploratory")`.
  - `careers.add_track(label: str, intent: str, titles=(), codes=(), tiers=None, exclusions=(), location="", training="none", priority="medium") -> int`.
  - `careers.tracks(enabled_only: bool = False) -> list[dict]`, with list fields decoded.
  - `careers.get_track(track_id: int) -> dict`, which raises `SystemExit("no career track #N")`.
  - `careers.update_track(track_id: int, **fields) -> dict`.
  - `careers.remove_track(track_id: int) -> None`.
  - `careers.search_titles(track: dict) -> list[str]`.
  - `careers.TITLE_CAP = 6`.

- [ ] **Step 1: Write the failing tests** in class `Tracks`. Fixture data as before. `tearDown` deletes `career_tracks` rows.

```python
def test_desired_field_unrelated_to_resume_is_accepted(self):
    tid = careers.add_track("Hospitality", "desired_field", titles=["Hotel manager"])
    t = careers.get_track(tid)
    self.assertEqual((t["tiers"], t["codes"]), ([0], ["11-9081.00"]))   # codes resolved, not used at tier 0

def test_validation(self):
    for kw in ({"intent": "nope", "titles": ["x"]}, {"intent": "pivot"}, {"intent": "pivot", "titles": ["x"], "tiers": [7]},
               {"intent": "pivot", "titles": ["x"], "training": "phd"}):
        with self.assertRaises(SystemExit):
            careers.add_track("T", **kw)

def test_search_titles_respects_tiers(self):
    t = careers.get_track(careers.add_track("H", "desired_field", titles=["Hotel manager"]))
    self.assertEqual(careers.search_titles(t), ["Hotel manager"])
    t = careers.update_track(t["id"], tiers=[0, 1])
    self.assertEqual(careers.search_titles(t), ["Hotel manager", "Lodging Managers", "Hospitality Manager"])

def test_titles_are_deduped_and_capped(self):
    t = careers.get_track(careers.add_track("M", "desired_field",
                          titles=["Chef", "chef ", "Cook", "Baker", "Barista", "Server", "Host", "Busser"]))
    self.assertEqual(careers.search_titles(t), ["Chef", "Cook", "Baker", "Barista", "Server", "Host"])

def test_remove_track_clears_posting_tags(self):
    tid = careers.add_track("H", "desired_field", titles=["Hotel manager"])
    db.con().execute("INSERT INTO postings(key, url, track_id) VALUES ('k1', 'https://x.test/1', ?)", (tid,)); db.con().commit()
    careers.remove_track(tid)
    self.assertIsNone(db.con().execute("SELECT track_id FROM postings WHERE key='k1'").fetchone()[0])
```

- [ ] **Step 2: Run the tests and confirm they fail.** Expected: an AttributeError for `add_track`.
- [ ] **Step 3: Add the table and column in `lodestar/db.py`.** Add the table to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS career_tracks(id INTEGER PRIMARY KEY, label TEXT NOT NULL, intent TEXT NOT NULL,
  titles TEXT NOT NULL DEFAULT '[]', codes TEXT NOT NULL DEFAULT '[]', tiers TEXT NOT NULL DEFAULT '[0]',
  exclusions TEXT NOT NULL DEFAULT '[]', location TEXT DEFAULT '', training TEXT DEFAULT 'none',
  priority TEXT DEFAULT 'medium', enabled INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
```

Add `"track_id": "INTEGER"` to `POSTING_MIGRATIONS`.
- [ ] **Step 4: Implement the track functions in `careers.py`.**
  - Every writer calls `config.full_ai_check("changes a career track")` first.
  - Default tiers by intent: `desired_field` → `[0]`, `resume_led` → `[1]`, others → `[0, 1]`.
  - Titles are stripped and de-duplicated case-insensitively, keeping the first spelling. Codes are resolved from titles at score ≥ 0.8 when none are given.
  - Validation messages: `intent must be one of ...`; `a track needs a title or an occupation`; `tiers are 0-6`; `training must be one of ...`; `priority must be one of ...`.
  - `search_titles`: titles (always, tier 0). If 1 is in tiers, add each code's `title` + `titles[:2]`. De-duplicate case-insensitively and cap at `TITLE_CAP`.
  - `remove_track` NULLs `postings.track_id` in the same transaction.
- [ ] **Step 5: Run the tests and confirm they pass.** Expected: all OK.
- [ ] **Step 6: Add a TESTS.md row** "Career tracks (CareerTrackConfig)", bump the counts and run `test_feature_matrix`. Expected: OK.
- [ ] **Step 7: Commit.** `git commit -m "Pass 23.3: career tracks - user-controlled intent, tiers, exclusions"`

### Task 4: Search a track, tag postings, report coverage

**Files:**
- Modify: `lodestar/careers.py`, `tests/test_pass23_careers.py`, `docs/TESTS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `web_monitor.search(query, errors=list, ran=list, location=...)`, `web_monitor.SOURCES`, `web_monitor.sources_ready()`, `listings.store`; Task 3 `get_track`, `search_titles`.
- Produces:
  - `careers.COVERAGE_NOTE = "Partial coverage: only the boards listed were searched. Lodestar never searches every job board or employer."`
  - `careers.coverage(ran: list[str], errors: list[str]) -> dict` returns `{asked, failed, not_ready, total, checked: bool, note}`.
  - `careers.search_track(track_id: int, location: str | None = None) -> dict` returns `{track, titles, results, coverage}`.

- [ ] **Step 1: Write the failing tests** in class `TrackSearch`. Pin `web_monitor.SOURCES` to `{"remotive": ..., "adzuna": ...}` and patch `web_monitor.search` + `web_monitor.sources_ready`, restoring all three in `finally`.

```python
def test_search_track_chunks_queries_tags_postings_and_reports_coverage(self):
    seen = []
    def fake(query, errors=None, ran=None, **f):
        seen.append(query); ran.append("remotive"); errors.append("adzuna: HTTP 500")
        listings.store([{"title": "Hotel Manager", "company": "Inn Co", "url": "https://inn.test/1", "location": "", "description": ""}],
                       source="remotive")
        return [{"title": "Hotel Manager", "company": "Inn Co", "url": "https://inn.test/1"}]
    tid = careers.add_track("H", "desired_field", titles=["Hotel manager"], tiers=[0, 1])
    out = careers.search_track(tid)
    self.assertEqual(seen, ["Hotel manager, Lodging Managers, Hospitality Manager"])
    self.assertEqual(out["coverage"]["asked"], ["remotive"]); self.assertEqual(out["coverage"]["failed"], ["adzuna: HTTP 500"])
    self.assertTrue(out["coverage"]["checked"]); self.assertIn("never searches every job board", out["coverage"]["note"])
    self.assertEqual(db.con().execute("SELECT track_id FROM postings WHERE url='https://inn.test/1'").fetchone()[0], tid)

def test_search_with_no_board_ready_says_nothing_checked(self):
    # fake search returns [] and appends nothing to ran; sources_ready() -> []
    out = careers.search_track(careers.add_track("H", "desired_field", titles=["Hotel manager"]))
    self.assertEqual((out["results"], out["coverage"]["asked"], out["coverage"]["checked"]), ([], [], False))
    self.assertIn("adzuna", out["coverage"]["not_ready"])

def test_desired_field_searches_with_no_profile(self):
    # profile.BANK pointed at an empty temp file: the track still searches its own words
    ...
    self.assertEqual(seen, ["Hotel manager"])
```

- [ ] **Step 2: Run the tests and confirm they fail.**
- [ ] **Step 3: Implement `search_track` and `coverage`.**
  - Chunk `search_titles(track)` into groups of 3, because `web_monitor.alternatives` caps at 3. For each chunk call `web_monitor.search(", ".join(chunk), errors=errs, ran=ran, location=location or track["location"] or None)`, passing `location` only when set.
  - Merge results by `url`.
  - Tag with `UPDATE postings SET track_id=? WHERE url=?` for each result, plus a `ponytail:` note that tagging uses the first link (`url`), which `listings.store` keeps.
  - `not_ready = [s for s in SOURCES if s not in sources_ready()]`.
- [ ] **Step 4: Run the tests and confirm they pass.**
- [ ] **Step 5: Add a TESTS.md row** "Track search + coverage (§6.5)", bump the counts and run `test_feature_matrix`.
- [ ] **Step 6: Commit.** `git commit -m "Pass 23.4: search a career track with visible source coverage"`

### Task 5: CLI `lodestar careers`

**Files:**
- Modify: `lodestar/cli.py`, `tests/test_pass23_careers.py`, `docs/TESTS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces these subcommands. Write their help text in the style of the existing `jobs` parsers.
  - `careers suggest [--tiers 1,2,3,4,5] [--limit 12] [--show-excluded]`
  - `careers occupation CODE`
  - `careers tracks`
  - `careers track-add LABEL --intent I [--titles "a, b"] [--codes C,C] [--tiers 0,1] [--exclude "w, w"] [--location L] [--training T] [--priority P]`
  - `careers track-set ID key=value ...`
  - `careers track-rm ID`
  - `careers search ID [--location L]`

- [ ] **Step 1: Write the failing test** in class `Cli`. Capture output with `contextlib.redirect_stdout`.

```python
def test_careers_cli_round_trip(self):
    out = run(["careers", "track-add", "Hospitality", "--intent", "desired_field", "--titles", "Hotel manager"])
    self.assertIn("track #", out)
    self.assertIn("Requested target", run(["careers", "tracks"]))
    with patched_profile(BANK):
        s = run(["careers", "suggest"])
    for label in ("Qualified now", "Bridge required", "Longer-term development", "O*NET test fixture"):
        self.assertIn(label, s)
    self.assertIn("Lodging Managers", run(["careers", "occupation", "11-9081.00"]))
```

- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Implement the subcommands.**
  - `suggest` prints suggestions grouped by class label in `CLASSES` order. Each line is code, title, tier label and source, with indented why / missing / does not transfer / to close the gap / regulated lines.
  - The note prints when it is set.
  - The O*NET credit line comes last.
  - `search` prints the results and then the coverage lines.
- [ ] **Step 4: Run it and confirm it passes.** Then regenerate the inventory with `.venv\Scripts\python.exe -m lodestar features --markdown` (write it to `docs/FEATURES.md` the way that file says it was generated).
- [ ] **Step 5: Add a TESTS.md row** and bump the counts.
- [ ] **Step 6: Commit.** `git commit -m "Pass 23.5: lodestar careers CLI"`

### Task 6: Careers tab (Career Discovery workspace, §18.2) + API

**Files:**
- Modify: `lodestar/web.py`, `lodestar/static/index.html`, `lodestar/static/app.js`, `lodestar/static/app.css`, `docs/TESTS.md`, `docs/CHANGELOG.md`, `docs/SETUP.md`, `CLAUDE.md`
- Create: `tests/e2e/e2e_careers.py`
- Test: `tests/test_pass23_careers.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces these routes:
  - `GET /api/careers` returns `{suggestions, zone, note, tracks, meta, classes, tiers}`, or `{error, tracks, classes, tiers}` with HTTP 200 when the data is missing.
  - `POST /api/careers/tracks` (body = `add_track` kwargs) returns `{id}`.
  - `POST /api/careers/tracks/<id>/delete`.
  - `POST /api/careers/tracks/<id>/search` with `{location?}` returns the `search_track` result.
  - Existing listing routes keep `POST /api/listings/<id>/track` for "Track".

- [ ] **Step 1: Write the failing unit test** for the route's degrade path in class `Routes`. Follow the existing route-harness tests: grep `tests/` for the helper that calls `web.Handler` (for example the one used by `test_pass21_sources`).

```python
def test_careers_route_survives_missing_data(self):
    occupations.DATA = Path(self.tmp) / "nope.json.gz"
    status, body = get("/api/careers")
    self.assertEqual(status, 200)
    self.assertIn("occupation data", body["error"])
```

- [ ] **Step 2: Write the failing E2E tests** in `tests/e2e/e2e_careers.py`, class `Careers(E2ETestCase)`.
  - `setUpClass` patches `occupations.DATA` to the fixture (restore it in `tearDownClass`) and seeds `careers_fixture.BANK` through `profile.save`.
  - Fake the board through the harness `FETCH` the same way `e2e_search.py` does.
  - Wait with `idle()` only.

```python
def test_bands_show_classes_explanations_and_credit(self):
    self.page.click("[data-tab=careers]"); self.idle()
    for band in ("Qualified now", "Competitive with framing", "Bridge required", "Longer-term development"):
        self.assertTrue(self.page.locator(f"#careers h3:has-text('{band}')").count())
    card = self.page.locator("#careers .career-card", has_text="Logisticians")
    for part in ("Why it fits", "What is missing", "What does not transfer", "To close the gap", "O*NET test fixture"):
        self.assertIn(part, card.inner_text())
    self.assertIn("CC BY 4.0", self.page.locator("#careers .credit").inner_text())

def test_desired_field_track_searches_with_coverage(self):
    self.page.click("[data-tab=careers]"); self.idle()
    self.page.fill("#trackLabel", "Hospitality"); self.page.fill("#trackTitles", "Hotel manager")
    self.page.select_option("#trackIntent", "desired_field"); self.page.click("#trackAdd"); self.idle()
    self.page.locator(".track-row", has_text="Hospitality").get_by_role("button", name="Search live openings").click(); self.idle()
    self.assertIn("never searches every job board", self.page.locator("#careers .coverage").inner_text())
    self.assertTrue(self.page.locator("#careers .career-results li").count())
```

- [ ] **Step 3: Run both and confirm they fail.**
  - `.venv\Scripts\python.exe -m unittest discover -s tests -p "test_pass23_careers.py" -v`
  - From PowerShell: `.venv\Scripts\python.exe -m unittest discover -s tests/e2e -p "e2e_careers.py" -v`
- [ ] **Step 4: Implement the routes** in `web.py`, beside the `/api/listings` GET/POST branches. `SystemExit` from `occupations` becomes `{"error": str(e), ...}` with 200.
- [ ] **Step 5: Implement the tab.**
  - Add `<button data-tab="careers">` (icon `✧`, label "Careers") after Jobs in `index.html`, and a `<section id="careers">` holding:
    - a track form (`#trackLabel`, `#trackIntent` with the 5 intents, `#trackTitles`, tier checkboxes 0–5 labelled with `TIERS`, `#trackAdd`),
    - a track list (`.track-row`, each with "Search live openings" and "Remove"),
    - suggestion bands as `<h3>` per class label, each card `.career-card` with title, tier label, source and the four labelled lists, plus a "Search live openings" button that creates a `resume_led` track for that code,
    - results `.career-results` with "Track" buttons, `.coverage`, and `.credit`.
  - Status is text, not colour only (§18.5).
  - The tab appears in the Ctrl+K palette on its own. It needs no `data-adv-slot`, since `test_pass19_toolbar` only requires toolbars for advisor scopes.
  - Restart the server after editing.
- [ ] **Step 6: Run the tests and confirm they pass.** Run the unit test, the E2E module, then the full unit suite and the full E2E suite. Expected: all OK. The counts are 928 + 23 new unit tests and 227 + 2 new E2E tests (use the counts actually printed).
- [ ] **Step 7: Update the docs.**
  - `docs/TESTS.md` rows (Careers tab, route degrade) and the counts.
  - `docs/CHANGELOG.md` gets a "Pass 23: career discovery foundation" entry: what shipped, O*NET 31.0 credit, what is deliberately deferred to pass 24.
  - `docs/SETUP.md` gets a "Career discovery" section: tiers, classes, tracks, coverage, credit.
  - `CLAUDE.md` gets a **Career discovery** project note: `occupations.py` / `careers.py`; tiers never broadened silently; classes are candidate-only; the O*NET credit; `scripts/build_onet.py` for taxonomy updates; tests patch `occupations.DATA`.
- [ ] **Step 8: Commit.** `git commit -m "Pass 23.6: Careers tab - discovery bands, tracks, live search with coverage"`

**Phase 1 exit criteria (spec R2 + §19.1):** one resume yields suggestions across ≥ 2 SOC major groups with evidence and limits shown; a desired field unrelated to the resume is accepted and searched; every suggestion names O*NET 31.0; coverage is visible; full unit + E2E suites are green.

---

## Part D: Phases 2–8 (outline: expand each into its own plan with superpowers:writing-plans before executing)

Each pass ends with green suites, TESTS.md rows and a CHANGELOG entry, like Pass 23. Interfaces named here are binding for the later plans.

### Pass 24: Eligibility gates, job-level readiness, open exploration (§4.4–4.6, §7.2–7.3, §18.3, §3.2 tier 6)
- `fit.gates(x, ctx) -> list[{requirement, state: "met" | "not_met" | "unknown", evidence}]` covers sponsorship/work authorization (existing `no_sponsor` regexes + `work_authorization` pref), clearance, required licenses/certifications (JD "required"/"must hold" phrases vs bank certifications; `skills.json` certifications list), and user exclusions (dealbreakers, excluded companies/title words).
- Remove `clearance`, `dealbreaker` and `blocked_cap` from the score in `data/fit.json`, bump `version` (so `fit.rev()` restales every score) and move them to gates. Add `confidence` = weight share of known parts, shown apart from the score.
- `careers.job_class(job) -> str` uses Pass 23 `classify`. A not_met gate gives `ineligible`; an unknown gate on a regulated occupation gives `insufficient_evidence`. It is shown on board cards, the drawer and All jobs, with "why surfaced" = the track label + tier label from `postings.track_id`.
- `auto_track` skips not_met gates, and an unknown gate forces `force_pending` (unknown is never met). The pipeline's fit gate reads `gates`.
- Tier 6: `careers.explore(interests: str, provider=None) -> list[Suggestion]`. It makes one AI call fenced with `extras._fence` and sends `candidate_text(private=False)`. Each AI role is matched with `occupations.match_title`; an unmatched role is kept with `source = "AI-suggested unmapped role: review"` (§20.2).
- Tests: gate states including unknown, fit numbers re-pinned, auto_track respecting gates, an E2E job card label.

### Pass 25: Central policy service + audit (§2.2 "Auditable automation", §9.4, §14.2, §17.2)
- `lodestar/policy.py` exposes `authorize(action: str, ctx: dict) -> Decision`, where `Decision = {result: "ALLOW" | "REQUIRE_APPROVAL" | "BLOCK" | "HANDOFF", reasons: list[str], policy_version: str}`.
- Rules, in order:
  1. Full AI → BLOCK.
  2. Tool disabled → BLOCK.
  3. §9.4 mandatory gates (legal/EEO/authorization/sponsorship/salary/start date/relocation/offer/withdraw/accept/negotiation, unverified mail) → REQUIRE_APPROVAL.
  4. CAPTCHA or an unknown apply capability → HANDOFF.
  5. A regulated or safety-sensitive role on submit → REQUIRE_APPROVAL.
  6. Tool auto → ALLOW.
- `approvals.propose`, `approvals.approve` and the apply agent's submit call it. Existing guards stay as defence in depth.
- An `audit` table (append-only: id, at, action, target, result, reasons, policy_version, approval_id, outcome) feeds `lodestar audit` and a Setup "Audit log" panel.
- Tests: one per rule, plus "no executor runs without a decision row".

### Pass 26: Sources, freshness, lifecycle, submitted documents (§6.3–6.5, §8.6, §11.1–11.3)
- `web_monitor.CAPABILITIES[name] = {search, pagination, full_description, apply: "handoff" | "unsupported", auth, terms_reviewed, regions}`. A guard test makes every `SOURCES` key have an entry, like `ATTRIBUTION`. Setup shows a Sources table.
- The Jobs tab shows `careers.coverage(...)` under every search.
- `postings.last_verified_at` is set by `posting_check`. The pipeline's apply step re-verifies a posting unverified for more than 3 days.
- `jobs.stage` holds the fine-grained §11.2 stage, mapped onto the 8 board statuses (mapping table in that plan). `db.set_status(job_id, status, detail="", stage=None, actor="user", evidence=None, approval_id=None)` also appends to `stage_events(job_id, from_stage, to_stage, actor_type, actor_id, evidence, approval_id, at, schema_version)` (A.4). Mail-driven moves pass the message id as evidence.
- On `applied`, snapshot the documents and answers to `applications/<id>/submitted/` with a `manifest.json` of sha256 hashes. Saves never touch `submitted/`.
- `docs/AUTOMATION.md` documents postings = Job and jobs = Application.

### Pass 27: Fact states, ingestion, claim diff (§8.1, §8.2, §8.5)
- Bank entries gain `state ∈ {extracted, user_confirmed, disputed}`. An applied import gives `extracted`; the Profile tab has Confirm / Dispute. The studio refuses disputed facts, and `careers.evidence` skips them. `generated_wording` stays the studio's per-version marker.
- Import gains `.html/.htm` (`html.parser`), `.odt` (`zipfile` content.xml) and `.rtf` (control-word stripper; `ponytail:` ceiling = no embedded tables). A scanned PDF is refused with "looks scanned; paste the text".
- `studio.claim_diff(version_id) -> list[{fact_id, before, after, change: added | removed | reordered | rewritten}]` is shown in the viewer side by side; new numbers are highlighted (`check_rewrite` already refuses uncited ones).

### Pass 28: Calendar availability, profession-aware prep (§10.6, §12)
- `calendar_busy.py` provides `busy(start, end) -> list[(start, end)]`, using Google Calendar FreeBusy through the existing `oauth.py` client (scope `calendar.freebusy`, opt-in pref `calendar_freebusy`, off by default). Interview slot proposals subtract busy blocks + a `interview_buffer_min` pref from `availability`. Tests fake HTTP; note that no real account has been verified (CLAUDE.md gotcha).
- `extras.py:510,527` replace "engineering culture" / "stack" with occupation-aware wording from `careers` (SOC 15- keeps stack). `data/questions.json` gains competency sets keyed by SOC major group (sales discovery/objections, healthcare privacy/workflow, trades safety). Verify that follow-ups skip weekends; add a `holidays` pref if they do not.

### Pass 29: Skill-gap planner, analytics by track (§13.1, §13.3)
- `gaps.py` provides `plan(job_ids=None, track_id=None) -> list[{requirement, count, mandatory, legal, actions: [project | course | certification | apprenticeship | degree | supervised_experience | none]}]` over missing JD terms (`ats`), Pass 24 gates and track occupations' `missing`. Legal requirements (regulated) are kept apart from employer preferences. It appears in an Insights panel and `lodestar gaps`.
- Insights by track, tier and class use `extras.MIN_N` thresholds.

### Pass 30: Industry-agnostic audit + acceptance journey (§2.2, §20.2, §20.3)
- `test_pass30_agnostic`: prompt builders contain no software-only defaults unless they are conditioned on SOC 15-, and searching needs no software term.
- E2E `e2e_acceptance.py` uses a non-tech resume fixture: import → review → suggestions across ≥ 2 major groups → unrelated desired-field track → fake board → track listing → gates + class → studio build + claim diff → packet → Inbox approval (policy row) → fake recruiter mail linked → interview slot proposed against faked FreeBusy.

### Pass 31 (optional): Gmail API read-only reader (§10.1)
- `gmail_api.py` with the `gmail.readonly` scope, `history.list` sync and the same `email_monitor._scan` path. IMAP stays for Microsoft and app passwords. Build only if the user wants least-privilege Google access.

---

## Self-review

- **Spec coverage:** every §3–§21 row in Part A has a pass or an explicit decision. §22 is this plan; §23 references are cited in Tasks 1 and 28.
- **Types:** `Suggestion`, `TIERS`, `CLASSES`, `classify`, `search_titles`, `coverage` and `search_track` match across Tasks 2–6 and Passes 24/26/29.
- **Review Focus:** all five lines have named tests in Tasks 1–4 and 6.
- **Proportion:** Phase 1 is specified to test level. Phases 2–8 are binding interface outlines, expanded one plan per pass before execution, as the spec itself requires (§22: "Do not ask one prompt to implement every release at once").
