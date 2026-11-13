"""Pass 21, builder 1: the fit score (fit.py). One deterministic 0-100 score per job or listing from five measured
parts plus modifiers, shrunk toward 50 by what could not be measured; weights in data/fit.json with a validated pref
override; never a salary floor figure, never employer text, never an AI prompt; rank() blends in at most the AI weight;
rules-only auto_track with a daily cap; the pipeline's Fit check reads the stored fit; Insights bands by fit.
No network: ai.* and rank() are faked; every patched attribute is put back."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, approvals, ats, cli, contacts, db, drafts, extras, fit, loop, pipeline, profile  # noqa: E402
from lodestar import resume, settings, web, web_monitor  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

PROF = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com\n## Summary\nData engineer.\n## Skills\nPython, SQL, Airflow, Spark\n"
        "## Experience\n### Senior Data Engineer - Globex (2019-01 - Present)\n- Built pipelines in Python and SQL\n"
        "### Data Engineer - Initech (2016-03 - 2019-06)\n- ETL in Spark\n\n"
        "## Preferences\nTarget roles: Data Engineer | Locations / remote: Remote, Austin | Salary floor: $123,456 | "
        "Deal-breakers: gambling | Industries to avoid: tobacco\n")
FILLER = " We value ownership, clear writing and steady delivery across a friendly distributed team." * 3
JD = ("We are hiring a Senior Data Engineer to build pipelines." + FILLER + "\nRequirements:\n- 5+ years of experience in "
      "data work\n- Python, SQL, Kubernetes, Terraform\n- Spark and Airflow\nNice to have:\n- Kafka\n- dbt\n")


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def L(title="Senior Data Engineer", company="Acme", location="Remote", desc=JD, salary="", url=None, source="hn"):
    return web_monitor._listing(title, company, url or f"https://jobs.example.com/{abs(hash((title, company, desc))) % 10**8}",
                                location, salary, "", desc, source)


def run_cli(*argv) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(argv))
    return out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(PROF, encoding="utf-8")
        self.patches = contextlib.ExitStack()
        self.patches.enter_context(patched(ai, available=lambda: [], ask_json=self._no_ai, ask=self._no_ai))
        self.patches.enter_context(patched(web_monitor, notify=lambda m: None))

    @staticmethod
    def _no_ai(*a, **k):
        raise AssertionError("no AI call expected")

    def tearDown(self):
        self.patches.close()
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def job(self, jd=JD, title="Senior Data Engineer", company="Acme", **fields):
        return db.add_job(company, title, None, jd, "via test", **fields)


class Weights(Base):
    def test_weights_from_fit_json_and_the_validated_override(self):
        self.assertEqual(fit.weights(), {"skills": 35, "role": 20, "experience": 15, "location": 15, "pay": 15, "ai": 25})
        settings.set_pref("fit_weights", "skills=40")
        settings.set_pref("fit_weights", "pay=0")
        self.assertEqual((fit.weights()["skills"], fit.weights()["pay"]), (40, 0))
        for bad in ("foo=1", "skills=101", "skills=x", "skills"):
            with self.assertRaises(SystemExit):
                settings.set_pref("fit_weights", bad)
        f = fit.score(L())
        self.assertEqual(f["parts"]["pay"]["w"], 0)  # a switched-off part is not measured and not missed
        self.assertEqual(f["known"], 1.0)
        settings.set_pref("fit_weights", "skills=")
        self.assertEqual(settings.pref("fit_weights"), {"pay": 0})
        settings.set_pref("fit_weights", "reset")
        self.assertEqual(settings.pref("fit_weights"), {})
        self.assertEqual(settings.CHOICES["target_seniority"][1:], web_monitor.SENIORITY)  # copied, not imported
        with self.assertRaises(SystemExit):
            settings.set_pref("years_experience", 61)


class Parts(Base):
    def test_split_nice_by_colon_markdown_bold_and_inline(self):
        h = fit.config()["nice_headings"]
        req, nice = ats.split_nice("Must:\n- Python\nNice to have:\n- Kafka\nAbout us:\n- Go", h)
        self.assertEqual((req.split(), nice.split()), (["-", "Python", "-", "Go"], ["-", "Kafka"]))
        self.assertIn("dbt", ats.split_nice("## Preferred\n- dbt\n## Role\n- SQL", h)[1])
        self.assertIn("Rust", ats.split_nice("**Bonus points**\n- Rust", h)[1])
        req, nice = ats.split_nice("Nice to have: Kafka, Spark\nPython required", h)
        self.assertEqual((nice.strip(), req.strip()), ("Kafka, Spark", "Python required"))

    def test_split_nice_reads_html_headings_after_strip_html(self):  # regression: <h3>Nice to have</h3> was 'required'
        from lodestar.util import strip_html

        h = fit.config()["nice_headings"]
        for head in ("<h3>Nice to have</h3>", "<h3>Preferred qualifications</h3>", "<p><b>Bonus</b></p>"):
            text = strip_html(f"<h3>Requirements</h3><ul><li>Python</li><li>SQL</li></ul>{head}<ul><li>Kubernetes</li>"
                              "<li>Terraform</li></ul><h3>Benefits</h3><p>Snowflake credits</p>")
            req, nice = ats.split_nice(text, h)
            self.assertIn("Kubernetes", nice, head); self.assertNotIn("Kubernetes", req, head)
            self.assertIn("Python", req); self.assertIn("Snowflake", req)  # the next bare section heading ends it
        req, nice = ats.split_nice("Requirements\nKafka is a plus\nPython", h)  # a skill line is never a heading
        self.assertEqual(nice, "")

    def test_skills_required_nice_and_missing(self):
        s = fit.score(L())["parts"]["skills"]
        self.assertEqual(s["required"][1] - s["required"][0], len(s["missing"]))
        self.assertIn("kubernetes", s["missing"]); self.assertIn("terraform", s["missing"])
        self.assertEqual(s["nice"], [0, 2])  # kafka, dbt: only under 'Nice to have'
        self.assertIn("python", s["matched"])
        chips = [c["text"] for c in fit.score(L())["chips"]]
        self.assertTrue(any(t.startswith("missing ") for t in chips))
        self.assertIn("0 of 2 nice-to-haves", chips)

    def test_template_profile_leaves_skills_unknown(self):
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")
        f = fit.score(L())
        self.assertIsNone(f["parts"]["skills"]["s"])
        self.assertIn("template", next(c["text"] for c in f["chips"] if c["part"] == "skills"))

    def test_required_years_patterns(self):
        self.assertEqual(fit.required_years("5+ years of experience with data"), 5)
        self.assertEqual(fit.required_years("3-5 years’ experience in analytics"), 3)
        self.assertEqual(fit.required_years("at least 7 years of Python experience"), 7)
        self.assertIsNone(fit.required_years("our 25 years of experience serving clients"))  # the company, not the role
        self.assertEqual(fit.required_years("2 years of experience; our 25 years of experience"), 2)

    def test_years_from_intervals_and_the_pref(self):
        from datetime import date
        exp = [{"start": "2016-01", "end": "2018-12"}, {"start": "2018-01", "end": "2019-12"},  # overlap counted once
               {"start": "Jan 2021", "end": "Present"}]
        self.assertEqual(fit.years_from(exp, date(2022, 12, 15)), 6.0)
        self.assertIsNone(fit.years_from([{"start": "", "end": ""}]))
        f = fit.score(L(desc=JD.replace("5+ years", "12+ years")))
        self.assertEqual(f["parts"]["experience"]["req"], 12)
        self.assertLess(f["parts"]["experience"]["s"], 100)
        settings.set_pref("years_experience", 14)
        self.assertEqual(fit.score(L(desc=JD.replace("5+ years", "12+ years")))["parts"]["experience"]["s"], 100)

    def test_role_target_rung_and_manager(self):
        settings.set_pref("target_seniority", "senior")
        r = fit.score(L(title="Senior Data Engineer"))["parts"]["role"]
        self.assertEqual((r["title"], r["level"], r["s"]), (100, 100, 100))
        self.assertEqual(fit.score(L(title="Staff Data Engineer"))["parts"]["role"]["level"], 70)
        self.assertEqual(fit.score(L(title="Data Engineering Manager"))["parts"]["role"]["level"], 40)
        settings.set_pref("target_seniority", "")
        self.assertEqual(fit.context()["level"], "staff")  # 2016-03 to now from the profile: 9+ years

    def test_location(self):
        self.assertEqual(fit.score(L(location="Remote (US)"))["parts"]["location"]["s"], 100)
        self.assertEqual(fit.score(L(location="Austin, TX", desc=JD.replace("Remote", "")))["parts"]["location"]["s"], 100)
        self.assertEqual(fit.score(L(location="Boston, MA", desc=JD + " This role is onsite."))["parts"]["location"]["s"], 15)
        self.assertEqual(fit.score(L(location="Boston, MA", desc=JD + " Hybrid, 3 days in office."))["parts"]["location"]["s"], 30)
        PROFILE.write_text(PROF.replace("Locations / remote: Remote, Austin", "Locations / remote:"), encoding="utf-8")
        self.assertIsNone(fit.score(L())["parts"]["location"]["s"])

    def test_pay_against_the_floor(self):
        pay = lambda sal: fit.score(L(salary=sal))["parts"]["pay"]["s"]  # noqa: E731
        self.assertEqual((pay("$90,000 - $110,000"), pay("$110,000 - $140,000"), pay("$130,000 - $160,000")), (0, 70, 100))
        self.assertIsNone(pay("€130,000 - €160,000"))  # another currency: not compared
        self.assertIsNone(pay(""))
        PROFILE.write_text(PROF.replace("Salary floor: $123,456 | ", ""), encoding="utf-8")
        self.assertIsNone(pay("$130,000 - $160,000"))
        jid = self.job(salary_min="100k", salary_max="110k")  # a job's own pay columns win
        self.assertIsNone(fit.for_job(db.get_job(jid))["parts"]["pay"]["s"])


class Modifiers(Base):
    def test_sponsorship_exclusions_dealbreaker_ghost_warm_watched(self):
        no = L(desc=JD + " We cannot sponsor visas for this role.")
        self.assertFalse(fit.score(no)["blocked"])  # authorised (or unset): not judged
        settings.set_pref("work_authorization", "needs_sponsorship")
        f = fit.score(no)
        # pass 24: a failed hard requirement is a gate (blocked), never a cut in the score (blueprint 7.2)
        self.assertTrue(f["blocked"]); self.assertEqual(f["score"], fit.score(L(desc=JD + " We cannot sponsor visas for this role."))["score"])
        self.assertEqual(f["chips"][0]["text"], "says no visa sponsorship")  # blocks first
        yes = fit.score(L(desc=JD + " Visa sponsorship is available."))  # pass 31: a gate met, never points
        self.assertIn("offers sponsorship", [g["evidence"] for g in yes["gates"]])
        settings.set_pref("work_authorization", "authorized")
        base = fit.score(L())["score"]
        settings.set_pref("excluded_companies", "Acme")
        self.assertTrue(fit.score(L())["blocked"]); self.assertEqual(fit.score(L())["score"], base)
        settings.set_pref("excluded_companies", "")
        gamble = fit.score(L(desc=JD + " We build gambling products."))
        self.assertTrue(gamble["blocked"]); self.assertEqual(gamble["score"], base)
        old = L() | {"date": "2020-01-01"}
        self.assertLess(fit.score(old)["score"], base)
        self.assertIn("possibly stale", " ".join(c["text"] for c in fit.score(old)["chips"]))
        contacts.add(name="Sam Lee", company="Acme")
        self.assertEqual(fit.score(L())["score"], min(100, base + 4))
        db.add_company("greenhouse", "acme", "Acme")
        self.assertEqual(fit.score(L())["score"], min(100, base + 9))
        self.assertIn("a company you watch", [c["text"] for c in fit.score(L())["chips"]])

    def test_title_only_listing_is_partial_and_shrunk(self):
        f = fit.score(L(desc="", location="Austin, TX"))
        self.assertTrue(f["partial"]); self.assertLess(f["known"], 0.6); self.assertLessEqual(f["score"], 70)
        self.assertIn("measured", f["note"])
        self.assertNotIn("measured", " ".join(c["text"] for c in fit.top(f)))  # info lines stay off the card

    def test_deterministic_and_never_calls_ai(self):
        a, b = fit.score(L()), fit.score(L())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))


class Privacy(Base):
    FORMS = ("123456", "123,456", "123k", "123.456")

    def test_floor_figure_never_in_fit_state_or_cli(self):
        jid = self.job(salary_min="130k", salary_max="160k")
        f = fit.for_job(db.get_job(jid))
        self.assertEqual(f["parts"]["pay"]["s"], 100)
        st = json.dumps(web.state(), default=str)
        out = run_cli("fit", str(jid))
        for form in self.FORMS:
            self.assertNotIn(form, json.dumps(f)); self.assertNotIn(form, st); self.assertNotIn(form, out)
        self.assertIn("range clears your floor", out)

    def test_rank_prompt_withholds_the_floor_and_fences_listings(self):
        prompts = []
        with patched(ai, available=lambda: ["anthropic"], ask_json=lambda p, **k: prompts.append(p) or [{"i": 0, "score": "85"}]):
            out = web_monitor.rank([L()])
        self.assertEqual(out[0]["score"], 85)
        for form in self.FORMS:
            self.assertNotIn(form, prompts[0])
        self.assertIn("Salary floor: (withheld)", prompts[0])
        self.assertIn("untrusted text copied from job sites", prompts[0])
        self.assertIn("gambling", prompts[0])  # deal-breakers are the fit: they stay

    def test_employer_text_never_carries_fit_data(self):
        jid = self.job()
        db.update_job(jid, contact_email="sam@acme.example", contact_name="Sam")
        db.con().execute("UPDATE jobs SET fit=?, fit_score=55 WHERE id=?", (json.dumps(
            {"score": 55, "chips": [{"sign": "-", "text": "missing zz-skill", "part": "skills"}]}), jid))
        db.con().commit()
        prompts = []

        def grab(p, *a, **k):
            prompts.append(p)
            return {"options": [{"label": "a", "tone": "b", "subject": "s", "body": "Hello.", "recommended": True, "why": "x"}],
                    "answer": "I like data.", "subject": "Hi", "body": "Thanks."}
        with patched(ai, available=lambda: ["anthropic"], ask_json=grab, ask=lambda p, *a, **k: prompts.append(p) or "Dear team."):
            job = db.get_job(jid)
            for call in (lambda: resume.cover_letter(job), lambda: apply.answer(job, "Why us?", propose=False),
                         lambda: apply.followup(job), lambda: drafts.options("followup", {"job": jid})):
                try:
                    call()
                except SystemExit:
                    pass
        self.assertGreaterEqual(len(prompts), 4)
        for p in prompts:
            self.assertNotIn("zz-skill", p); self.assertNotIn('"chips"', p)


class Stale(Base):
    def test_rev_moves_with_profile_weights_and_dealbreakers(self):
        r0 = fit.rev()
        settings.set_pref("fit_weights", "skills=50")
        r1 = fit.rev()
        settings.set_pref("excluded_companies", "Initrode")
        r2 = fit.rev()
        PROFILE.write_text(PROF.replace("Data engineer.", "Data engineer who ships."), encoding="utf-8")
        r3 = fit.rev()
        self.assertEqual(len({r0, r1, r2, r3}), 4)
        self.assertEqual(fit.rev(), r3)

    def test_refresh_scores_stale_items_only_and_the_board_dims_them(self):
        a, b = self.job(), self.job(title="Data Analyst")
        self.assertEqual(fit.stale_count(), 2)
        self.assertEqual(fit.refresh()["jobs"], 2)
        self.assertEqual(fit.refresh()["jobs"], 0)  # nothing stale: nothing re-scored
        PROFILE.write_text(PROF.replace("Data engineer.", "Data engineer, analytics."), encoding="utf-8")  # every job stale
        st = web.state()
        self.assertEqual(st["fit_stale"], 2)
        view = next(j for j in st["jobs"] if j["id"] == a)
        self.assertTrue(view["fit_stale"]); self.assertNotIn("fit", view); self.assertNotIn("ai_fit", view)
        self.assertLessEqual(len(view["fit_chips"]), 3)
        self.assertEqual(fit.refresh(limit=1) | {}, {"jobs": 1, "listings": 0, "left": 1})
        self.assertEqual(fit.refresh()["jobs"], 1)
        self.assertNotEqual(db.get_job(b)["fit_rev"], None)

    def test_for_job_respects_not_mine_and_jd_saves_rescore(self):
        jid = self.job()
        before = fit.for_job(db.get_job(jid))["parts"]["skills"]
        db.toggle_ats_skip(jid, "kubernetes")
        after = fit.for_job(db.get_job(jid))["parts"]["skills"]
        self.assertNotIn("kubernetes", after["missing"]); self.assertGreater(after["s"], before["s"])
        resume.set_jd(jid, "Data Analyst. Excel.")  # a JD save re-scores (never blocks the save)
        self.assertIsNone(fit.stored(db.get_job(jid))["parts"]["skills"]["s"])


class Outcomes(Base):
    def test_fit_applied_once_and_insights_bands_by_fit(self):
        jid = self.job()
        fit.for_job(db.get_job(jid))
        score = db.get_job(jid)["fit_score"]
        db.set_status(jid, "applied")
        self.assertEqual(db.get_job(jid)["fit_applied"], score)
        db.con().execute("UPDATE jobs SET fit_score=5 WHERE id=?", (jid,)); db.con().commit()
        db.set_status(jid, "screening")
        self.assertEqual(db.get_job(jid)["fit_applied"], score)  # kept from when it left 'saved'
        band = next(g for g in extras.analytics()["by_band"] if g["n"])
        self.assertEqual(band["group"], extras._band(score))
        self.assertIn("Response rate by fit score", run_cli("insights"))
        self.assertEqual([j["id"] for j in db.list_jobs(sort="fit")][:1], [jid])


class AutoTrack(Base):
    def setUp(self):
        super().setUp()
        settings.set_pref("auto_track_min_score", 60)
        self.ranked = []

    def fake_rank(self, score):
        def rank(listings, provider=None):
            self.ranked.append([j["title"] for j in listings])
            for j in listings:
                j["score"], j["why"] = score, "ai says so"
            return listings
        return rank

    def test_rules_only_without_ai(self):
        strong, thin = L(), L(title="Data Engineer", desc="")
        out = apply.auto_track([strong, thin])
        self.assertEqual([o["url"] for o in out], [strong["url"]])
        p = out[0]["proposal"]
        self.assertEqual(p["status"], "pending")
        row = db.list_pending("pending")[0]
        self.assertIn("(rules)", row["summary"])
        self.assertEqual(json.loads(row["payload"])["posting_key"], web_monitor.posting_key(strong))
        self.assertTrue(thin["fit"]["partial"]); self.assertIn("score", thin)  # judged, never proposed on guesswork

    def test_rules_only_proposals_wait_even_with_the_tool_on_auto(self):  # regression: they were approved at once
        old = settings.load()["tools"]["auto_track"]
        settings.set_tool("auto_track", enabled=True, auto=True)
        try:
            with patched(ai, available=lambda: []):
                out = apply.auto_track([L(company="Autoco")])
            self.assertEqual(out[0]["proposal"]["status"], "pending")
            self.assertNotIn("Autoco", [j["company"] for j in db.list_jobs()])
            with patched(ai, available=lambda: ["anthropic"]), patched(web_monitor, rank=self.fake_rank(100)):
                out = apply.auto_track([L(company="Aico")])
            self.assertNotEqual(out[0]["proposal"]["status"], "pending")  # an AI-judged one still follows the auto flag
        finally:
            settings.set_tool("auto_track", enabled=old["enabled"], auto=old["auto"])

    def test_ai_only_on_strong_described_listings_and_blended(self):
        weak = L(title="Barista", company="Beanery", desc="Make coffee. " * 30, location="Boston, MA")
        short = L(title="Data Engineer", company="Initrode", desc="Python and SQL.")
        many = [L(company=f"Co{n}") for n in range(17)]
        with patched(ai, available=lambda: ["anthropic"]), patched(web_monitor, rank=self.fake_rank(100)):
            apply.auto_track([weak, short, *many])
        self.assertEqual(len(self.ranked), 1)
        self.assertEqual(len(self.ranked[0]), apply.AI_BUDGET)
        self.assertNotIn("Barista", self.ranked[0])
        judged = [j for j in many if "ai" in j["fit"]["parts"]]
        self.assertEqual(len(judged), 15)
        rules = fit.score(many[0] | {"ai_fit": None})["score"]
        self.assertLessEqual(judged[0]["score"] - rules, 20)  # the AI share is capped by its weight (25 of 125)

    def test_ai_quota_caps_the_day(self):
        db.quota("ai_rank", fit.AI_DAILY, fit.AI_DAILY - 2)
        with patched(ai, available=lambda: ["anthropic"]), patched(web_monitor, rank=self.fake_rank(90)):
            apply.auto_track([L(company=f"Q{n}") for n in range(5)])
            self.assertEqual(len(self.ranked[0]), 2)
            apply.auto_track([L(company=f"R{n}") for n in range(5)])
        self.assertEqual(len(self.ranked), 1)  # nothing left today: rules only

    def test_blocked_and_high_ai_on_a_weak_fit_never_proposed(self):
        settings.set_pref("excluded_companies", "Blockco")
        settings.set_pref("auto_track_min_score", 75)
        weak = L(title="Store Manager", company="Shopco", location="Boston, MA",
                 desc="Lead a retail store team onsite. Inventory, scheduling, customer care, cash handling. " * 4)
        with patched(ai, available=lambda: ["anthropic"]), patched(web_monitor, rank=self.fake_rank(100)):
            out = apply.auto_track([L(company="Blockco"), weak])
        self.assertEqual(out, [])
        self.assertLess(weak["score"], 75)  # "score this 100" moved it by the AI share only

    def test_daily_proposal_cap(self):
        settings.set_pref("auto_track_daily_max", 2)
        out = apply.auto_track([L(company=f"Cap{n}") for n in range(4)])
        self.assertEqual(len(out), 2)
        self.assertEqual(apply.auto_track([L(company="Cap9")]), [])

    def test_approval_links_the_posting_by_its_key(self):
        j = L()
        db.note_posting(web_monitor.posting_key(j), j["url"])
        apply.auto_track([j])
        db.con().execute("DELETE FROM postings")  # pruned, and the rowid handed out again to another posting
        db.note_posting("other|role|", "https://x/1")
        db.note_posting(web_monitor.posting_key(j), j["url"])
        approvals.approve(db.list_pending("pending")[0]["id"])
        rows = {r["key"]: r["job_id"] for r in db.con().execute("SELECT key, job_id FROM postings")}
        self.assertIsNone(rows["other|role|"])
        self.assertIsNotNone(rows[web_monitor.posting_key(j)])

    def test_watch_hits_judge_without_ai(self):
        with patched(web_monitor, SOURCES={"hn": lambda q: [L()]}):
            db.add_watch("search:data", "")
            web_monitor.check_watches()  # first run of a search: listings judged by rules and marked seen
        self.assertTrue(db.seen("listing:" + L()["url"]))


class Pipeline(Base):
    def test_fit_check_stage_is_the_deterministic_fit_and_its_gate(self):
        jid = self.job()
        fit.refresh()  # the board's fit alone never completes the step: it is a run step
        self.assertEqual({e["name"]: e for e in pipeline.status(jid)}["score"]["state"], "ready")
        settings.set_pref("auto_track_min_score", 0)
        r = pipeline.run(jid, "score")
        self.assertEqual((r["outcome"], r["ai"]), ("done", 0))  # no AI unless fit_check is on auto
        out = {e["name"]: e for e in pipeline.status(jid)}["score"]["output"]
        f = fit.stored(db.get_job(jid))
        self.assertEqual((out["score"], out["verdict"], out["chips"]), (f["score"], "go", [f"{c['sign']} {c['text']}" for c in fit.top(f)]))
        self.assertFalse(pipeline.fit_skip(pipeline.status(jid)))
        settings.set_pref("auto_track_min_score", 100)  # under the threshold: the fit gate says skip
        pipeline.run(jid, "score", rerun=True)
        self.assertTrue(pipeline.fit_skip(pipeline.status(jid)))
        settings.set_tool("fit_check", enabled=True, auto=True)  # on auto: one AI judgement joins the fit
        with patched(ai, available=lambda: ["anthropic"]), \
                patched(web_monitor, rank=lambda ls, provider=None: [j.update(score=95, why="ok") or j for j in ls]):
            self.assertEqual(pipeline.run(jid, "score", rerun=True)["ai"], 1)
        self.assertEqual(fit.stored(db.get_job(jid))["parts"]["ai"]["s"], 95)


class Surfaces(Base):
    def test_routes_cli_today_and_tracking_a_top_fit(self):
        jid = self.job()
        self.assertEqual(web._act("fit_refresh", {})["jobs"], 1)
        out = run_cli("fit", str(jid))
        self.assertIn("skills", out); self.assertIn("weight 35", out)
        self.assertIn("re-scored 0 job(s)", run_cli("fit", "refresh"))
        self.assertIn("fit ", run_cli("jobs", "list"))
        db.note_posting("acme|senior data engineer|remote", "https://jobs.example.com/top")
        db.con().execute("UPDATE postings SET title='Senior Data Engineer', company='Acme', location='Remote', jd=?, "
                         "sources='[\"hn\"]'", (JD,))
        db.con().commit()
        fit.refresh()
        tops = loop.agenda()["top_fits"]
        self.assertEqual([t["title"] for t in tops], ["Senior Data Engineer"])
        new = web.track_posting(tops[0]["id"])
        self.assertEqual(db.get_job(new)["url"], "https://jobs.example.com/top")
        self.assertEqual(loop.agenda()["top_fits"], [])  # tracked: no longer a new fit
        with patched(web_monitor, rank=lambda listings, provider=None: [j.update(score=88, why="x") or j for j in listings]), \
                patched(ai, available=lambda: ["anthropic"]):
            f = web._act("job_ai", {"id": jid})["fit"]
        self.assertEqual(f["parts"]["ai"]["s"], 88)
        self.assertEqual(json.loads(db.get_job(jid)["ai_fit"])["score"], 88)


if __name__ == "__main__":
    unittest.main()
