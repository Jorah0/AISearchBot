"""Pass 16 audit, fixer B (behaviour, UX, robustness): follow-ups with a booked round, contacts counted once, match
score after a JD or resume change, offline profile import, search / watch / rank failures that reach the UI, the closed
drawer, unknown ids, funnel and applied counts, unmarked research, narrow windows, CLI file errors, blank answers,
local times, non-editable documents, provider tests and loops that survive SystemExit, test hygiene and the CI lint.
No network: job boards, fetches and AI are faked; every patched attribute is put back."""
import contextlib
import http.client
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, cli, contacts, db, extras, ideas, profile, resume, settings, util, web, web_monitor  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "lodestar" / "static"
REAL = "# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"


@contextlib.contextmanager
def patched(obj, **attrs):
    """Set attributes for the block; the originals always come back."""
    old = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class Base(unittest.TestCase):
    """In-memory database; settings and profile put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")

    def tearDown(self):
        c = getattr(db._local, "con", None)
        if c is not None:
            c.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def age(self, jid: int, days: int) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        db.con().execute("UPDATE events SET ts=? WHERE job_id=?", (old, jid))
        db.con().commit()


# ----------------------------------------------------------------------------- tracker logic
class Tracker(Base):
    def test_a_booked_round_stops_the_follow_up_nudges(self):  # integration-followup-ignores-rounds
        booked, quiet = db.add_job("Initrode Booked", "Eng"), db.add_job("Initrode Quiet", "Eng")
        for jid in (booked, quiet):
            db.set_status(jid, "interview")
            self.age(jid, 20)
        later = (datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d %H:%M")
        db.con().execute("INSERT INTO interviews(job_id, round, kind, at) VALUES(?,?,?,?)", (booked, 1, "onsite", later))
        db.con().commit()
        self.assertEqual([j["id"] for j in db.needs_followup(7)], [quiet])

    def test_unknown_ids_report_not_found(self):  # live-orphan-status-nonexistent-job
        for call, msg in ((lambda: db.set_status(99, "applied"), "no job #99"), (lambda: db.delete_job(98), "no job #98"),
                          (lambda: db.remove_company(97), "no watched company #97"), (lambda: db.remove_watch(96), "no watch #96")):
            with self.assertRaises(SystemExit) as e:
                call()
            self.assertIn(msg, str(e.exception))
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)  # no orphan timeline event
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
            cli.main(["jobs", "status", "99", "applied"])
        self.assertIn("no job #99", str(e.exception))
        self.assertNotIn("->", out.getvalue())

    def test_a_later_stage_counts_as_passing_the_skipped_ones(self):  # live-funnel-skipped-stage-zero
        a, b, c = db.add_job("Acme", "Eng"), db.add_job("Globex", "Eng"), db.add_job("Hooli", "Eng")
        for jid, path in ((a, ["applied", "interview", "offer"]), (b, ["applied", "offer"]), (c, ["applied"])):
            for st in path:
                db.set_status(jid, st)
        f = db.funnel()["stages"]
        self.assertEqual((f["applied"]["reached"], f["applied"]["advanced"], f["applied"]["conversion"]), (3, 2, 0.67))
        self.assertEqual((f["screening"]["reached"], f["screening"]["advanced"]), (2, 2))  # passed on the way, unlogged
        self.assertEqual((f["interview"]["reached"], f["interview"]["advanced"]), (2, 2))
        self.assertEqual(f["offer"]["reached"], 2)
        self.assertIsNotNone(f["applied"]["median_days_to_next"])  # from applied to the first later stage

    def test_withdrawing_a_saved_job_is_not_an_application(self):  # live-stats-withdrawn-saved-counts-as-applied
        jobs = [db.add_job(f"Co{i}", "Eng") for i in range(5)]
        for jid, path in zip(jobs, (["applied", "interview"], ["applied", "rejected"], ["applied"], ["applied", "withdrawn"])):
            for st in path:
                db.set_status(jid, st)
        before = db.stats()
        db.set_status(jobs[4], "withdrawn")  # saved, never applied: posting gone
        after = db.stats()
        self.assertEqual((before["applied_total"], after["applied_total"]), (4, 4))
        self.assertEqual((after["response_rate"], after["interview_rate"]), (before["response_rate"], before["interview_rate"]))
        self.assertEqual((after["response_rate"], after["interview_rate"]), (0.5, 0.25))
        self.assertEqual(sum(g["n"] for g in extras.analytics(2)["by_source"]), 4)  # Insights groups count the same way

    def test_one_person_touched_and_mailed_counts_once(self):  # integration-contacts-double-count
        cid = contacts.add(name="Jane Doe", email="jane@acme.example", company="Acme")
        db.con().execute("INSERT INTO touches(contact_id, day) VALUES(?,?)", (cid, date.today().isoformat()))
        jid = db.add_job("Acme", "Eng")
        pid = db.add_pending("followup", "send_email", jid, "mail", json.dumps({"to": "Jane@Acme.example", "subject": "s",
                                                                                "body": "b", "purpose": "followup"}))
        db.con().execute("UPDATE pending SET status='done', decided_at=? WHERE id=?", (db._now(), pid))
        db.con().commit()
        settings.set_pref("weekly_goals", {"contacts": 5})
        self.assertEqual([g["done"] for g in extras.goal_progress() if g["goal"] == "contacts"], [1])
        self.assertEqual(extras.analytics(1)["weeks"][-1]["contacts"], 1)
        self.assertEqual(extras._who("Pat Lee"), "pat lee")  # no address: the name is the identity

    def test_blank_answer_is_refused(self):  # live-blank-answer-saved
        for q, a in (("", ""), ("Why us?", "  "), ("  ", "Because.")):
            with self.assertRaises(SystemExit):
                db.save_answer(q, a)
        self.assertEqual(db.list_answers(), [])
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("async function saveAnswer(btn)", js)
        self.assertIn("onclick=\"saveAnswer(this)\"", (STATIC / "index.html").read_text(encoding="utf-8"))

    def test_applied_at_is_the_local_day(self):  # live-utc-times-shown-as-local (storage side)
        class Evening(datetime):  # 23:30 local on the 7th is already the 8th in UTC (local = UTC-5)
            @classmethod
            def now(cls, tz=None):
                local = datetime(2026, 11, 7, 23, 30)
                return local if tz is None else (local + timedelta(hours=5)).replace(tzinfo=tz)

        jid = db.add_job("Acme", "Eng")
        with patched(db, datetime=Evening):
            db.set_status(jid, "applied")
        self.assertEqual(db.get_job(jid)["applied_at"], "2026-11-07")


# ----------------------------------------------------------------------------- match score
class MatchScore(Base):
    def test_a_new_jd_rescoring_and_a_cleared_one_dropping_the_score(self):  # integration-stale-match-score
        jid = db.add_job("Vandelay Rescore", "Data Engineer", jd="Python and SQL for data pipelines")
        first = resume.coverage(db.get_job(jid))["score"]
        resume.set_jd(jid, "Rust, Haskell, Erlang, Elixir, OCaml and Kubernetes operators")
        self.assertLess(db.get_job(jid)["match_score"], first)
        stored = json.loads((resume.app_dir(db.get_job(jid)) / "coverage.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["score"], db.get_job(jid)["match_score"])
        resume.set_jd(jid, "")  # no JD: no score rather than the old JD's one
        self.assertIsNone(db.get_job(jid)["match_score"])
        self.assertFalse((resume.app_dir(db.get_job(jid)) / "coverage.json").is_file())
        never = db.add_job("Vandelay Unscored", "Eng", jd="Python")
        resume.set_jd(never, "Python and SQL")
        self.assertIsNone(db.get_job(never)["match_score"])  # nothing stored before: nothing is made by a JD edit


class WebPaths(unittest.TestCase):
    """Through the real HTTP routes (file database in the temp home, as the server threads use)."""

    def setUp(self):
        from lodestar import desktop

        self._con = getattr(db._local, "con", None)
        db._local.con = None  # this thread uses the same on-disk database as the server threads
        self.snap = PROFILE.read_bytes() if PROFILE.is_file() else None
        PROFILE.write_text(REAL, encoding="utf-8")
        self.port = desktop.free_port(8870)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        db.release()
        db._local.con = self._con
        PROFILE.write_bytes(self.snap) if self.snap is not None else PROFILE.unlink(missing_ok=True)

    def call(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN,
                                                     "Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def test_jd_and_resume_saves_rescore_coverage(self):  # integration-stale-match-score
        jid = db.add_job("Kramerica Web", "Data Engineer", jd="Python and SQL for data pipelines")
        first = resume.coverage(db.get_job(jid))["score"]
        st, r = self.call(f"/api/jobs/{jid}/jd", {"source": "Rust, Haskell, Erlang, Elixir and OCaml services"})
        self.assertEqual(st, 200, r)
        low = db.get_job(jid)["match_score"]
        self.assertLess(low, first)
        st, r = self.call(f"/api/docs/{jid}", {"name": "resume.md", "text": "# Jane\nRust Haskell Erlang Elixir OCaml services"})
        self.assertEqual(st, 200, r)
        self.assertGreater(db.get_job(jid)["match_score"], low)
        st, r = self.call("/api/answers", {"question": "", "answer": ""})  # live-blank-answer-saved, at the route
        self.assertEqual(st, 400)
        self.assertIn("question and an answer", r["error"])
        db.delete_job(jid)


# ----------------------------------------------------------------------------- profile import
class ProfileImport(Base):
    def test_a_repeated_name_line_is_not_the_location(self):  # live-profile-import-location-is-name
        text = "# Dana Fictional\n\nDana Fictional | Austin, TX | dana@example.com | +1 555 010 0199\n## Skills\nPython\n"
        c = profile.extract_heuristic(text)["contact"]
        self.assertEqual((c["name"], c["location"]), ("Dana Fictional", "Austin, TX"))
        c = profile.extract_heuristic("# Dana Fictional\nAustin, TX | dana@example.com\n")["contact"]
        self.assertEqual(c["location"], "Austin, TX")  # the city-first layout still works

    def test_project_bullets_stay_bullets(self):  # live-project-heading-mangled
        text = ("# Dana Fictional\n## Projects\n### pgsnap - CLI to snapshot PostgreSQL schemas, github.com/danafictional/pgsnap\n"
                "- Python CLI with 300 GitHub stars; diff two schema snapshots\n- Packaged on PyPI\n")
        p = profile.extract_heuristic(text)["projects"][0]
        self.assertEqual(p["description"], "CLI to snapshot PostgreSQL schemas, github.com/danafictional/pgsnap")
        self.assertEqual(p["bullets"], ["Python CLI with 300 GitHub stars; diff two schema snapshots", "Packaged on PyPI"])
        bank = profile.empty()
        profile.merge(bank, {"projects": [p, {"name": "lodestar", "description": "job search", "url": "github.com/x/lodestar"}]}, "t")
        md = profile.render_markdown(bank, "")
        self.assertIn("### pgsnap - CLI to snapshot PostgreSQL schemas, github.com/danafictional/pgsnap\n"
                      "- Python CLI with 300 GitHub stars; diff two schema snapshots\n- Packaged on PyPI", md)
        self.assertIn("### lodestar - job search, github.com/x/lodestar", md)
        self.assertEqual(profile.extract_heuristic(md)["projects"][0]["bullets"], p["bullets"])  # round trip


# ----------------------------------------------------------------------------- search, watches, AI rank
class SearchFailures(Base):
    def boom(self, q):
        raise OSError("board unreachable")

    def test_unreachable_boards_reach_the_ui_and_the_watch(self):  # live-search-failures-silent
        ok = lambda q: [web_monitor._listing("Dev", "Co", "https://jobs.example.com/1", desc="Python")]  # noqa: E731

        def no_fetch(url, *a, **k):
            raise OSError("offline")

        # no provider: the new listing is not sent to a real AI for judging (auto_track)
        with patched(web_monitor, SOURCES={"a": self.boom, "b": self.boom}, fetch=no_fetch, notify=lambda m: None),                 patched(ai, available=lambda: []):
            r = web._act("search", {"query": "dev"})
            self.assertEqual((r["results"], len(r["errors"]), r["boards"]), ([], 2, 2))
            self.assertIn("board unreachable", r["errors"][0])
            with self.assertRaises(SystemExit) as e:
                web._act("auto_track", {"query": "dev"})
            self.assertIn("no job board could be reached", str(e.exception))
            db.add_watch("search:dev", "")
            db.add_watch("https://careers.example.com/jobs", "")
            web_monitor.check_watches()
            w = {x["url"]: x for x in db.watches()}
            self.assertIsNone(w["search:dev"]["last_seen"])  # no successful run time on a failed run
            self.assertIn("no job board could be reached", w["search:dev"]["last_error"])
            self.assertIsNone(w["https://careers.example.com/jobs"]["last_seen"])
            self.assertIn("fetch failed: offline", w["https://careers.example.com/jobs"]["last_error"])
            web_monitor.SOURCES = {"a": self.boom, "b": ok}
            web_monitor.check_watches()
            s = {x["url"]: x for x in db.watches()}["search:dev"]
            self.assertIsNotNone(s["last_seen"])  # one board answered: a run, with what failed noted
            self.assertIn("unreachable a:", s["last_error"])
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("No job board could be reached, so nothing was checked", js)
        self.assertIn("last run failed", js)

    def test_rank_without_a_provider_says_so(self):  # live-ai-rank-silent-noop
        listing = web_monitor._listing("Senior Python Engineer", "Co", "https://jobs.example.com/2", desc="Python, remote")
        with patched(ai, available=lambda: []), patched(web_monitor, SOURCES={"b": lambda q: [dict(listing)]}):
            with self.assertRaises(SystemExit) as e:
                web_monitor.rank([dict(listing)])
            self.assertIn("needs an AI provider", str(e.exception))
            r = web._act("search", {"query": "python", "rank": True})  # results still shown, unranked, with why
            self.assertEqual(len(r["results"]), 1)
            self.assertTrue(any("needs an AI provider" in x for x in r["errors"]))
            with self.assertRaises(SystemExit) as e:
                web._act("auto_track", {"query": "python"})  # never '0 strong fits' as if judged
            self.assertIn("needs an AI provider", str(e.exception))

        def rejected(*a, **k):
            raise SystemExit("model 'gpt-x' was rejected")

        with patched(ai, ask_json=rejected):
            with self.assertRaises(SystemExit) as e:
                web_monitor.rank([dict(listing)])
            self.assertIn("AI ranking failed", str(e.exception))


# ----------------------------------------------------------------------------- research
class Research(Base):
    def test_nothing_fetched_is_marked_and_sources_are_listed(self):  # live-research-nothing-fetched-unmarked
        def no_fetch(url, *a, **k):
            raise OSError("offline")

        jid = db.add_job("Globex Research", "Eng", url="https://globex.example.com/jobs/1")
        with patched(util, fetch=no_fetch), patched(ai, ask=lambda *a, **k: "Globex was named most innovative."):
            text = extras.research(db.get_job(jid)).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("> **No public source could be fetched**"), text[:200])
        self.assertIn("## Sources read\n- none", text)
        with patched(util, fetch=lambda url, *a, **k: '{"extract": "Globex makes widgets."}' if "wikipedia" in url else "<p>page</p>"), \
                patched(ai, ask=lambda *a, **k: "Pack."):
            text = extras.research(db.get_job(jid)).read_text(encoding="utf-8")
        self.assertNotIn("No public source", text)
        self.assertIn("- https://globex.example.com/jobs/1", text)


# ----------------------------------------------------------------------------- providers and SystemExit
class Providers(Base):
    def test_no_provider_gives_a_clear_message(self):  # live-test-providers-blank
        with patched(ai, available=lambda: []):
            for action in ("providers_test", "models"):
                with self.assertRaises(SystemExit) as e:
                    web._act(action, {})
                self.assertIn("no AI provider configured", str(e.exception))

    def test_one_rejected_model_does_not_stop_the_others(self):  # packaging-providers-test-systemexit
        def ask(prompt, system=None, provider=None, **k):
            if provider == "openai":
                raise SystemExit("OpenAI rejected model 'gpt-nope'")
            return "OK"

        def models(n):
            if n == "openai":
                raise SystemExit("OpenAI rejected the key")
            return ["claude-x"]

        with patched(ai, available=lambda: ["anthropic", "openai"], ask=ask, list_models=models):
            r = web._act("providers_test", {})
            self.assertEqual(r["anthropic"], "OK")
            self.assertIn("FAIL", r["openai"])
            m = web._act("models", {})
            self.assertEqual((m["anthropic"], m["openai"][:4]), (["claude-x"], "FAIL"))

    def test_council_digest_and_ideas_survive_a_rejected_model(self):  # packaging-provider-loops-systemexit
        def ask(prompt, system=None, provider=None, **k):
            if provider == "openai":
                raise SystemExit("OpenAI rejected model 'gpt-nope'")
            return "merged answer"

        with patched(ai, ask=ask):
            r = ai.council("q", providers=["anthropic", "openai"])
            self.assertEqual(r["synthesis"], "merged answer")
            self.assertIn("error", r["answers"]["openai"])

        def ask_all_fail(*a, **k):
            raise SystemExit("model rejected")

        with patched(ai, ask=ask_all_fail, available=lambda: ["anthropic"]):
            self.assertIn("coach unavailable: model rejected", extras.digest(7))

        idea = [{"title": "Ship a portfolio project", "idea": "x", "effort": 2, "impact": 4, "fit": 80}]

        def ask_json(prompt, provider=None, **k):
            if provider == "openai":
                raise SystemExit("OpenAI rejected model 'gpt-nope'")
            return idea

        with patched(ai, ask_json=ask_json, council_providers=lambda: ["openai", "anthropic"]), \
                contextlib.redirect_stdout(io.StringIO()):
            out = ideas.craft("strategy", use_council=True)
        self.assertEqual([i["title"] for i in out], ["Ship a portfolio project"])


# ----------------------------------------------------------------------------- CLI
class Cli(Base):
    def test_a_missing_file_is_one_clear_line(self):  # live-cli-missing-file-traceback
        for argv in (["resume", "lint", "no-such-file.md"], ["contacts", "import", "no-such-file.csv"],
                     ["profile", "import", "no-such-file.md", "--no-ai"]):
            with self.assertRaises(SystemExit) as e:
                cli.main(argv)
            self.assertRegex(str(e.exception.code), r"^cannot open no-such-file\.\w+: ", argv)


# ----------------------------------------------------------------------------- UI (markup, CSS, JS)
class Ui(unittest.TestCase):
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    def test_a_closed_drawer_is_inert_and_focus_returns(self):  # live-drawer-hidden-focus
        self.assertIn('<div id="drawer" role="dialog" aria-label="Details" inert></div>', self.html)  # no static aria-modal
        close = self.js[self.js.index("function closeDrawer()"):self.js.index("async function openJob")]
        self.assertIn("d.inert = true", close)
        self.assertIn("removeAttribute('aria-modal')", close)
        self.assertIn("back?.focus()", close)
        self.assertRegex(self.css, r"#drawer \{[^}]*visibility: hidden")
        self.assertRegex(self.css, r"#drawer\.open \{[^}]*visibility: visible")
        self.assertEqual(self.js.count("openDrawer('"), 2)  # job and contact drawers both go through it

    def test_narrow_windows_keep_the_top_bar_actions(self):  # live-narrow-window-loses-actions
        narrow = self.css[self.css.index("@media (max-width: 900px)"):]
        narrow = narrow[:narrow.index("\n}\n")]
        self.assertNotRegex(narrow, r"\.top \{[^}]*display: none")
        self.assertIn('"brand" "top" "nav" "main"', narrow)
        self.assertRegex(narrow, r"\.today \.b \{[^}]*white-space: normal")
        self.assertIn("Run watches", self.html)

    def test_only_editable_documents_offer_edit(self):  # live-edit-noneditable-doc
        self.assertEqual(web.state()["doc_names"], sorted(web.DOC_NAMES))
        edit = self.js[self.js.index("function editDoc()"):self.js.index("async function saveDoc()")]
        self.assertIn("if (!editable(n))", edit)
        adjust = self.js[self.js.index("function adjustDoc(btn)"):self.js.index("function reviewDoc(btn)")]
        self.assertIn("if (!editable(n))", adjust)

    def test_stored_utc_times_render_in_local_time(self):  # live-utc-times-shown-as-local
        for raw in ("${e.ts}", "updated_at.slice(0, 10)", "r.ts.slice(0, 16)", "esc(e.ts)"):
            self.assertNotIn(raw, self.js)
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        fn = re.search(r"function localTs\(s, n = 19\) \{.*?\n\}", self.js, re.S).group(0)
        script = fn + ";console.log(JSON.stringify([localTs('2026-11-07 19:32:27'), localTs('2026-11-08 01:00:00', 10), " \
                      "localTs('2026-11-07', 10), localTs(null, 10)]))"
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30,
                             env={**os.environ, "TZ": "America/New_York"})
        self.assertEqual(json.loads(out.stdout), ["2026-11-07 14:32:27", "2026-11-07", "2026-11-07", ""], out.stderr)


# ----------------------------------------------------------------------------- test hygiene and CI
class Hygiene(unittest.TestCase):
    def test_the_scheduler_test_puts_platform_back(self):  # packaging-test-platform-leak
        import test_lodestar

        real = platform.system
        r = unittest.TestResult()
        test_lodestar.Hardening("test_scheduler_uses_this_interpreter").run(r)
        try:
            self.assertTrue(r.wasSuccessful(), r.errors + r.failures)
            self.assertIs(platform.system, real)
        finally:
            platform.system = real

    def test_ci_lint_step_passes(self):  # packaging-ci-pyflakes-red: the exact command .github/workflows/ci.yml runs
        self.assertIn("python -m pyflakes lodestar tests", (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
        py = next((p for p in (sys.executable, shutil.which("python"), shutil.which("python3")) if p and subprocess.run(
            [p, "-c", "import pyflakes"], capture_output=True).returncode == 0), None)
        if not py:
            self.skipTest("pyflakes is not installed (CI installs it)")
        r = subprocess.run([py, "-m", "pyflakes", "lodestar", "tests"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
