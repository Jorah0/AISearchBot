"""Pass 15, group D: public ATS board feeds for watched companies, robots.txt for page watches, search filters with
unknown-pass marking, cross-source de-dup, JD coverage on results, H-1B sponsor hints, stale / repost signals and the
weekly posting check. No network: every HTTP call is faked and every patched attribute is put back."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta, timezone

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, db, profile, settings, web_monitor as wm  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

GH = {"jobs": [{"id": 11, "title": "Data Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/11",
                "location": {"name": "Berlin"}, "first_published": "2026-10-30T10:00:00-04:00",
                "content": "&lt;p&gt;Build pipelines in &lt;b&gt;Python&lt;/b&gt;.&lt;/p&gt;&lt;p&gt;Pay: $120,000 - $150,000&lt;/p&gt;"}]}
LEVER_TS = int(datetime(2026, 10, 28, tzinfo=timezone.utc).timestamp() * 1000)
LEVER = [{"id": "abc", "text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/acme/abc", "categories": {"location": "NYC"},
          "workplaceType": "remote", "createdAt": LEVER_TS, "descriptionPlain": "Go services.",
          "lists": [{"text": "Requirements", "content": "<li>Go and Postgres</li>"}],
          "salaryRange": {"min": 130000, "max": 160000, "currency": "USD", "interval": "per-year-salary"}}]
ASHBY = {"jobs": [{"id": "u1", "title": "Designer", "jobUrl": "https://jobs.ashbyhq.com/acme/u1", "location": "Lisbon",
                   "workplaceType": "Hybrid", "publishedAt": "2026-11-01T00:00:00Z", "descriptionPlain": "Figma all day.",
                   "compensation": {"scrapeableCompensationSalarySummary": "$100K - $120K"}},
                  {"id": "u2", "isListed": False, "title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/acme/u2"}]}
LONG = ("You will design and run data pipelines in Python and SQL on AWS, own the warehouse in Snowflake, write dbt models, "
        "review code, mentor two engineers and work with analysts on metrics. ") * 4
REAL_PROFILE = "# Jane Doe\njane@example.com\n## Skills\nPython, SQL, AWS, Docker\n## Experience\n- Built data pipelines in Python and SQL on AWS\n"


def L(title, company, url, location="", salary="", days_ago=None, desc=LONG, source="a"):
    d = (date.today() - timedelta(days=days_ago)).isoformat() if days_ago is not None else ""
    return wm._listing(title, company, url, location, salary, d, desc, source)


class Base(unittest.TestCase):
    """In-memory database; settings, profile, bank and every patched module attribute put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        self.real = (wm.fetch, wm.fetch_json, wm.notify, wm.SOURCES, wm.rank, apply.auto_track, ai.available)
        self.alerts, self.calls = [], []
        wm.notify = self.alerts.append

    def tearDown(self):
        wm.fetch, wm.fetch_json, wm.notify, wm.SOURCES, wm.rank, apply.auto_track, ai.available = self.real
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def fake_feeds(self, lever=None):
        def fake(url, **k):
            self.calls.append(url)
            if "greenhouse" in url:
                return json.loads(json.dumps(GH))
            if "lever" in url:
                return json.loads(json.dumps(LEVER if lever is None else lever))
            if "ashby" in url:
                return json.loads(json.dumps(ASHBY))
            raise AssertionError(f"unexpected fetch {url}")
        wm.fetch_json = fake


class Feeds(Base):
    def test_detect_ats_and_add_company(self):
        self.assertEqual(wm.detect_ats("https://boards.greenhouse.io/acme/jobs/123"), ("greenhouse", "acme"))
        self.assertEqual(wm.detect_ats("job-boards.greenhouse.io/acme"), ("greenhouse", "acme"))
        self.assertEqual(wm.detect_ats("https://jobs.lever.co/acme/abc-123"), ("lever", "acme"))
        self.assertEqual(wm.detect_ats("https://jobs.ashbyhq.com/acme"), ("ashby", "acme"))
        self.assertEqual(wm.detect_ats("ashby:acme"), ("ashby", "acme"))
        for bad in ("https://evil.com/boards.greenhouse.io/x", "javascript:alert(1)", "lever:../x", "https://jobs.lever.co/"):
            self.assertIsNone(wm.detect_ats(bad), bad)
        with self.assertRaises(SystemExit) as e:
            wm.add_company("https://acme.wd5.myworkdayjobs.com/en-US/careers")
        self.assertIn("Workday", str(e.exception)); self.assertIn("no public job feed", str(e.exception))
        c = wm.add_company("https://boards.greenhouse.io/acme-corp", keywords="python")
        self.assertEqual((c["vendor"], c["slug"], c["name"]), ("greenhouse", "acme-corp", "Acme Corp"))
        self.assertEqual(wm.add_company("greenhouse:acme-corp", name="ACME")["id"], c["id"])  # again: renamed, not doubled
        self.assertEqual([(r["name"], r["keywords"]) for r in db.companies()], [("ACME", "python")])  # re-add without keywords keeps them
        with self.assertRaises(SystemExit):
            wm.add_company("lever:acme", name="x" * 81)
        a = build().parse_args(["companies", "add", "lever:acme", "--keywords", "go"])
        self.assertEqual((a.cmd, a.op, a.source, a.keywords), ("companies", "add", "lever:acme", "go"))

    def test_each_vendor_normalises_to_a_listing(self):
        from lodestar.resume import parse_salary

        self.fake_feeds()
        gh, = wm.feed("greenhouse", "acme", "Acme")
        self.assertEqual((gh["title"], gh["company"], gh["location"], gh["date"], gh["source"], gh["ats_feed"], gh["ats_id"]),
                         ("Data Engineer", "Acme", "Berlin", "2026-10-30", "greenhouse", "greenhouse:acme", "11"))
        self.assertIn("Build pipelines in Python.", gh["desc"]); self.assertNotIn("<", gh["desc"])
        self.assertEqual(gh["salary"], "$120,000 - $150,000")
        lv, = wm.feed("lever", "acme", "Acme")
        self.assertEqual((lv["location"], lv["date"], lv["url"], lv["salary"]), ("NYC (remote)", "2026-10-28", "https://jobs.lever.co/acme/abc", "USD 130000-160000"))
        self.assertIn("Go and Postgres", lv["desc"])
        self.assertEqual(parse_salary(wm.jd_with_salary(lv)), {"salary_min": 130000, "salary_max": 160000, "currency": "USD"})
        ab = wm.feed("ashby", "acme", "Acme")
        self.assertEqual([(j["title"], j["location"], j["salary"]) for j in ab], [("Designer", "Lisbon (hybrid)", "$100K - $120K")])
        self.assertEqual(wm.listing_fields(lv), {"location": "NYC (remote)", "posted_at": "2026-10-28", "ats_feed": "lever:acme"})
        self.assertNotIn("ats_feed", wm.listing_fields({"ats_feed": "workday:x"}))  # lenient: a bad value is dropped
        jid = db.add_job("Acme", "Backend", lv["url"], "x", ats_feed="lever:acme")
        self.assertEqual(db.get_job(jid)["ats_feed"], "lever:acme")
        with self.assertRaises(SystemExit):
            db.add_job("Acme", "Backend", "https://x/2", ats_feed="lever:acme;drop")

    def test_company_postings_alert_once_and_are_seen_only_after_judgement(self):
        self.fake_feeds()
        wm.add_company("lever:acme")
        ai.available = lambda: ["anthropic"]
        judged = []

        def judge(listings, provider=None):
            judged.extend(listings)
            for j in listings:
                j["score"] = 10
            return []
        apply.auto_track = judge
        wm.check_watches()                                                     # first poll: the open roles are a baseline
        self.assertEqual(len(self.calls), 1)                                   # one request per company per cycle
        self.assertEqual([a for a in self.alerts if "Acme" in a], ["WATCHING Acme: 1 open role(s) now; new postings alert from the next cycle"])
        self.assertEqual(judged, [])
        self.assertTrue(db.seen("listing:https://jobs.lever.co/acme/abc"))
        new = dict(LEVER[0], id="def", text="Data Engineer", hostedUrl="https://jobs.lever.co/acme/def")
        self.fake_feeds(lever=LEVER + [new])
        wm.check_watches()
        self.assertEqual(sum("NEW LISTING [Acme]" in a for a in self.alerts), 1)
        self.assertEqual([j["url"] for j in judged], ["https://jobs.lever.co/acme/def"])
        self.assertIn("ghost", judged[0])                                       # annotated before judgement
        self.assertTrue(db.seen("listing:https://jobs.lever.co/acme/def"))
        wm.check_watches()
        self.assertEqual((len(self.calls), len(judged)), (3, 1))                # polled again, nothing new
        wm.fetch_json = lambda url, **k: (_ for _ in ()).throw(OSError("board down"))
        wm.check_watches()
        self.assertEqual(db.companies()[0]["last_error"], "board down")

    def test_robots_txt_is_checked_once_per_host_and_disallow_skips(self):
        db.add_watch("https://ex.com/careers", "")
        db.add_watch("https://ex.com/jobs", "")
        fetched = []

        def fake(url, **k):
            fetched.append(url)
            return "User-agent: *\nDisallow: /careers\n" if url.endswith("/robots.txt") else "<p>Open roles</p>"
        wm.fetch = fake
        wm.check_watches()
        self.assertEqual(fetched, ["https://ex.com/robots.txt", "https://ex.com/jobs"])
        self.assertEqual(sum("robots.txt" in a for a in self.alerts), 1)
        wm.check_watches()
        self.assertEqual(sum("robots.txt" in a for a in self.alerts), 1)        # alerted once, skipped every cycle
        for code, allowed in ((404, True), (403, False)):
            def http_err(url, code=code, **k):
                raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
            wm.fetch = http_err
            self.assertEqual(wm._robots_ok("https://other.com/careers", {}), allowed, code)


class Search(Base):
    def setUp(self):
        super().setUp()
        wm.SOURCES = {"a": lambda q: [
            L("Senior Python Engineer", "Acme, Inc.", "https://a/1", "Remote (US)", "$150,000 - $180,000", 3),
            L("Python Developer", "Globex", "https://a/3"),                                  # salary, location, date unknown
            L("Junior Python Dev", "Initech", "https://a/4", "Berlin", "€50k", 60),
            L("Python Engineer", "Umbrella Corp", "https://a/5", "Remote"),
            L("Python Recruiter", "Hooli", "https://a/6", "Remote")],
            "b": lambda q: [L("Sr Python Engineer", "ACME", "https://b/1", "Remote - US", "", 3, desc="short", source="b")]}
        settings.set_pref("excluded_companies", "umbrella")
        settings.set_pref("excluded_title_words", "recruiter")

    def urls(self, **f):
        return [j["url"] for j in wm.search("python", **f)]

    def test_dealbreakers_and_cross_source_dedup(self):
        got = wm.search("python")
        self.assertEqual([j["url"] for j in got], ["https://a/1", "https://a/3", "https://a/4"])
        acme = got[0]
        self.assertEqual((acme["urls"], acme["sources"], acme["desc"]), (["https://a/1", "https://b/1"], ["a", "b"], LONG.strip()))
        self.assertEqual([j["seniority"] for j in got], ["senior", "mid", "junior"])

    def test_dedup_never_merges_two_openings_from_one_source(self):
        a1, a2 = L("Software Engineer", "Bigco", "https://a/x1", "Seattle, WA"), L("Software Engineer", "BigCo Inc", "https://a/x2", "Seattle WA")
        b1 = L("Software Engineer", "Bigco", "https://b/x1", "Seattle, WA", source="b")
        got = wm.dedupe([a1, a2, b1])
        self.assertEqual([j["urls"] for j in got], [["https://a/x1", "https://b/x1"], ["https://a/x2"]])
        g1, g2 = (L("Eng", "Acme", f"https://g/{i}", source=s) | {"ats_id": i} for i, s in (("1", "g"), ("2", "h")))
        self.assertEqual(len(wm.dedupe([g1, g2])), 2)                           # both carry an ats_id and they differ

    def test_monthly_pay_is_not_read_as_annual(self):
        monthly = dict(LEVER[0], salaryRange={"min": 5000, "max": 7000, "currency": "EUR", "interval": "per-month-salary"})
        self.fake_feeds(lever=[monthly])
        lv, = wm.feed("lever", "acme", "Acme")
        ash = L("Designer", "Acme", "https://c/1", salary="€5K – €7K per month")
        got = wm.refine([lv, ash], min_salary=60000)
        self.assertEqual(len(got), 2)                                           # kept as unknown, not dropped as 7000
        self.assertTrue(all(j["salary_unknown"] for j in got))

    def test_filters_keep_unknowns_and_mark_them(self):
        self.assertEqual(self.urls(location="remote"), ["https://a/1", "https://a/3"])
        self.assertTrue(wm.search("python", location="remote")[1]["location_unknown"])
        self.assertEqual(self.urls(location="berlin"), ["https://a/3", "https://a/4"])
        self.assertEqual(self.urls(min_salary="120k"), ["https://a/1", "https://a/3"])
        self.assertTrue(wm.search("python", min_salary=120000)[1]["salary_unknown"])
        self.assertEqual(self.urls(posted_within=30), ["https://a/1", "https://a/3"])
        self.assertTrue(wm.search("python", posted_within=30)[1]["date_unknown"])
        self.assertEqual(self.urls(seniority="senior"), ["https://a/1"])
        self.assertNotIn("salary_unknown", wm.search("python")[1])  # marked only when that filter is on
        for bad in ({"seniority": "wizard"}, {"min_salary": "-5"}, {"posted_within": "soon"}, {"location": "x" * 81}):
            with self.assertRaises(SystemExit, msg=bad):
                wm.clean_filters(**bad)

    def test_saved_search_uses_its_filters(self):
        settings.set_tool("auto_track", enabled=False)
        db.add_watch("search:python", "", wm.clean_filters(seniority="junior"))
        wm.check_watches()
        self.assertEqual([a for a in self.alerts if "NEW LISTING" in a], [a for a in self.alerts if "Initech" in a])
        self.assertEqual(sum("NEW LISTING" in a for a in self.alerts), 1)

    def test_fit_on_results_and_skills_unknown_for_a_template_profile(self):  # pass 21: the fit replaced JD coverage
        from lodestar.resume import PROFILE_TEMPLATE

        PROFILE.write_text(REAL_PROFILE, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        sk = wm.search("python")[0]["fit"]["parts"]["skills"]
        self.assertIsInstance(sk["s"], int)
        self.assertIn("python", sk["matched"]); self.assertIn("snowflake", sk["missing"])
        PROFILE.write_text(PROFILE_TEMPLATE, encoding="utf-8")
        self.assertIsNone(wm.search("python")[0]["fit"]["parts"]["skills"]["s"])


class Signals(Base):
    def test_ghost_signals(self):
        old_short = L("Dev", "Acme", "https://a/1", days_ago=45, desc="Join us. Great team.")
        g = wm.ghost_signals(old_short)
        self.assertEqual(g["score"], 50); self.assertEqual(len(g["reasons"]), 2)
        self.assertIn("posted 45 days ago", g["reasons"][0])
        vague = L("Dev", "Acme", "https://a/1", desc="We are a passionate team that loves what we do and values people. " * 10)
        self.assertIn("no concrete skill", wm.ghost_signals(vague)["reasons"][0])
        self.assertEqual(wm.ghost_signals(L("Dev", "Acme", "https://a/1"))["score"], 0)
        first = L("Data Engineer", "Acme Inc", "https://jobs.example.com/old/1", "Berlin")
        db.note_posting(wm.posting_key(first), first["url"])
        db._local.con.execute("UPDATE postings SET first_seen=datetime('now','-30 days')")
        again = L("Data Engineer", "ACME", "https://jobs.example.com/new/2", "Berlin")  # a new link on the same site
        self.assertIn("reposted", wm.ghost_signals(again)["reasons"][0])
        self.assertEqual(wm.ghost_signals(first)["score"], 0)                 # same link: not a repost
        jid = db.add_job("Initech", "Dev")                                    # a job with no JD is not suspicious
        self.assertEqual(wm.ghost_signals(db.get_job(jid))["score"], 0)
        self.assertFalse(any("salary" in r.lower() for r in g["reasons"]))

    def test_auto_track_skips_stale_listings(self):
        passed = []
        wm.rank = lambda listings, provider=None: passed.extend(listings) or listings
        stale = L("Dev", "Acme", "https://a/1", days_ago=45) | {"ghost": {"score": 60, "reasons": ["posted 45 days ago", "x"]}}
        fresh = L("Dev", "Globex", "https://a/2")
        self.assertEqual(apply.auto_track([stale, fresh]), [])
        self.assertNotIn(stale, passed)  # never scored further, never sent to the AI
        self.assertIn("fit", fresh); self.assertIn("score", fresh)  # pass 21: the fresh one is judged (rules, no key here)
        self.assertEqual(stale["score"], 0); self.assertTrue(stale["why"].startswith("skipped: possibly stale"))

    def test_sponsor_import_tolerates_both_export_formats(self):
        # the current hub export: six approval kinds, each with its denial column
        new = ("Line by line,Fiscal Year,Employer (Petitioner) Name,Tax ID,Industry (NAICS) Code,Petitioner City,Petitioner State,"
               "Petitioner Zip Code,New Employment Approval,New Employment Denial,Continuation Approval,Continuation Denial,"
               "Change with Same Employer Approval,Change with Same Employer Denial,New Concurrent Approval,New Concurrent Denial,"
               "Change of Employer Approval,Change of Employer Denial,Amended Approval,Amended Denial\n"
               '1,2024,ACME INC,1,54,Austin,TX,78701,"1,100",5,200,2,100,0,50,0,40,0,10,1\n'
               "2,2024,Acme Inc.,2,54,Austin,TX,78701,10,0,0,0,0,0,0,0,0,0,0,0\n"
               "3,2023,ACME INC,1,54,Austin,TX,78701,7,0,3,0,0,0,0,0,0,0,0,0\n").encode()
        r = wm.import_sponsors(new)
        self.assertEqual((r["employers"], r["approvals"]), (1, 1520))
        wm.import_sponsors(new)                                                 # a year imported again replaces it
        self.assertEqual(wm.sponsor_hint("Acme")["approvals"], 1520)
        old = "Fiscal Year\tEmployer\tInitial Approvals\tInitial Denials\tContinuing Approvals\tContinuing Denials\n2019\tGLOBEX CORP\t4\t0\t6\t0\n"
        wm.import_sponsors(old.encode("utf-16"))
        self.assertEqual(wm.sponsor_hint("Globex LLC")["approvals"], 10)
        self.assertIsNone(wm.sponsor_hint("Initech"))
        self.assertEqual(wm.annotate([L("Dev", "acme", "https://a/1")])[0]["sponsor"]["approvals"], 1520)
        with self.assertRaises(SystemExit):
            wm.import_sponsors(b"name,city\nAcme,Austin\n")
        self.assertEqual(db.clear_sponsors(), 3)

    def test_weekly_posting_check_proposes_withdrawal_and_never_moves_status(self):  # daily since pass 21
        self.fake_feeds()
        pages = []
        wm.fetch = lambda url, **k: pages.append(url) or ""                     # robots.txt and the page: blank, open
        settings.set_tool("posting_check", auto=True)                          # still waits: the loop only proposes
        live = db.add_job("Acme", "Backend", "https://jobs.lever.co/acme/abc", LONG)
        gone = db.add_job("Acme", "Frontend", "https://jobs.lever.co/acme/gone", LONG, ats_feed="lever:acme")
        applied = db.add_job("Acme", "Ops", "https://jobs.lever.co/acme/gone2", LONG)
        db.set_status(applied, "applied")
        db.add_job("Acme", "Data", "https://acme.com/careers?gh_jid=9", LONG)    # not a feed job: a page check instead
        db.add_job("Acme", "Backend apply", "https://jobs.lever.co/acme/abc/apply", LONG)  # the live posting's apply link
        db.add_job("Acme", "Board", "https://jobs.lever.co/acme", LONG)          # names no posting: cannot be proven gone
        self.assertEqual([wm._posting_id(u) for u in ("https://boards.greenhouse.io/embed/job_app?for=acme&token=123",
                          "https://jobs.ashbyhq.com/acme/u1/application", "https://boards.greenhouse.io/acme/jobs/11",
                          "https://jobs.lever.co/acme/")], ["123", "u1", "11", ""])
        now = datetime(2026, 11, 6)
        self.assertEqual(wm.check_listings(now), [gone])                         # the applied one: event only, no proposal
        p = db.list_pending("pending")[0]
        self.assertEqual((p["kind"], p["job_id"], json.loads(p["payload"])["status"], json.loads(p["payload"])["note"]),
                         ("set_status", gone, "withdrawn", "posting removed"))
        self.assertEqual(db.get_job(gone)["status"], "saved")
        self.assertEqual(db.get_job(applied)["status"], "applied")
        self.assertTrue(wm.removed_event(applied))
        g = wm.ghost_signals(db.get_job(gone))
        self.assertGreaterEqual(g["score"], wm.GHOST_SKIP); self.assertIn("posting removed", g["reasons"][-1])
        self.assertEqual(wm.ghost_signals(db.get_job(live))["score"], 0)
        self.assertEqual(len(self.calls), 1)                                    # one request for the lever:acme feed
        self.assertEqual(pages, ["https://acme.com/robots.txt", "https://acme.com/careers?gh_jid=9"])
        self.assertEqual(wm.check_listings(now), [])                            # same day: nothing fetched
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(wm.check_listings(now + timedelta(days=1)), [])       # next day: checked, not proposed twice
        self.assertEqual((len(self.calls), len(db.list_pending("pending"))), (2, 1))
        self.assertEqual(len(pages), 2)                                         # a page is read at most weekly
        self.fake_feeds(lever=[])                                               # an empty board proposes nothing
        self.assertEqual(wm.check_listings(now + timedelta(days=2)), [])


class Routes(unittest.TestCase):
    def test_company_watch_and_job_routes(self):
        import http.client
        from lodestar import desktop, web

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        port = desktop.free_port(8910); srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        jid = None
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            def call(path, body, headers=h):
                c.request("POST", path, json.dumps(body), headers); r = c.getresponse(); return r.status, json.loads(r.read())
            st, r = call("/api/companies", {"source": "https://jobs.lever.co/zzco/123", "keywords": "go"})
            self.assertEqual((st, r["vendor"], r["slug"]), (200, "lever", "zzco"))
            st, r = call("/api/companies", {"source": "https://zz.taleo.net/careersection/2/jobsearch.ftl"})
            self.assertEqual(st, 400); self.assertIn("Taleo", r["error"])
            self.assertEqual(call("/api/companies", {"source": "lever:zz2"}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            self.assertEqual(call("/api/watches", {"url": "zz python", "search": True, "seniority": "senior", "min_salary": "150k"})[0], 200)
            self.assertEqual(call("/api/watches", {"url": "zz python", "search": True, "seniority": "boss"})[0], 400)
            self.assertEqual(call("/api/watches", {"url": "zz python", "search": True, "keywords": "x"})[0], 200)  # Monitor form: filters kept
            self.assertEqual(call("/api/watches", {"url": "javascript:alert(1)"})[0], 400)
            st, r = call("/api/jobs", {"company": "ZZCo", "title": "Go Dev", "url": "https://jobs.lever.co/zzco/123", "jd": "Go", "ats_feed": "lever:zzco"})
            jid = r["id"]
            self.assertEqual(db.get_job(jid)["ats_feed"], "lever:zzco")
            c.request("GET", "/api/state", headers=h); s = json.loads(c.getresponse().read())
            self.assertIn(("lever", "zzco"), [(x["vendor"], x["slug"]) for x in s["companies"]])
            w = next(x for x in s["watches"] if x["url"] == "search:zz python")
            self.assertEqual(w["filters"], {"min_salary": 150000, "seniority": "senior"})
            job = next(x for x in s["jobs"] if x["id"] == jid)
            self.assertIn("ghost", job); self.assertIn("sponsor", job)
            c.close()
        finally:
            srv.shutdown()
            if jid:
                db.delete_job(jid)
            for co in db.companies():
                if co["slug"].startswith("zz"):
                    db.remove_company(co["id"])
            for x in db.watches():
                if x["url"] == "search:zz python":
                    db.remove_watch(x["id"])
            db._local.con.close()
            db._local.con = saved


if __name__ == "__main__":
    unittest.main()
