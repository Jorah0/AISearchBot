"""Pass 21, builder 2: all-sites sourcing. The new boards (Adzuna and USAJOBS behind their keys, Himalayas, We Work
Remotely) and feeds (SmartRecruiters, Recruitee, Personio) on hand-made fictional fixtures; the per-board throttle and
quotas; key redaction; the All jobs store (listings.py: merged copies, every link, reposts, query, track, dismiss,
prune); the Adzuna / USAJOBS keys in the connections registry; the routes and the CLI. No network: util.fetch,
fetch_json and urlopen are faked, and every patched attribute is put back."""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import date, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, connections, db, listings, settings, vault, web, web_monitor as wm  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

LONG = ("You will design and run data pipelines in Python and SQL on AWS, own the warehouse in Snowflake, write dbt models, "
        "review code and mentor two engineers. ") * 3
KEYS = {"ADZUNA_APP_ID": "adzid0123456", "ADZUNA_APP_KEY": "adzkeyZZ9988776655", "USAJOBS_API_KEY": "usakeyQQ11223344",
        "USAJOBS_EMAIL": "pat.rivera@example.com"}
ADZUNA = {"results": [
    {"title": "Data Engineer", "company": {"display_name": "Quillfeather Labs"}, "redirect_url": "https://www.adzuna.com/land/ad/101",
     "location": {"display_name": "Austin, Texas"}, "salary_min": 120000, "salary_max": 140000, "salary_is_predicted": "0",
     "created": "2026-11-05T10:00:00Z", "description": "Python and SQL pipelines."},
    {"title": "Analytics Engineer", "company": {"display_name": "Bramblecrest"}, "redirect_url": "https://www.adzuna.com/land/ad/102",
     "location": {"display_name": "Denver"}, "salary_min": 90000, "salary_max": 95000, "salary_is_predicted": "1",
     "created": "2026-11-04T10:00:00Z", "description": "dbt models."}]}
USAJOBS = {"SearchResult": {"SearchResultItems": [
    {"MatchedObjectDescriptor": {"PositionTitle": "IT Specialist (Data)", "OrganizationName": "Bureau of Fictional Records",
                                 "PositionURI": "https://www.usajobs.gov/job/700001", "PositionLocationDisplay": "Washington, DC",
                                 "PositionRemuneration": [{"MinimumRange": "99000", "MaximumRange": "128000", "RateIntervalCode": "PA"}],
                                 "PublicationStartDate": "2026-11-02", "ApplicationCloseDate": "2026-12-01T23:59:59",
                                 "UserArea": {"Details": {"JobSummary": "Manage data systems."}}}},
    {"MatchedObjectDescriptor": {"PositionTitle": "Seasonal Data Clerk", "OrganizationName": "Bureau of Fictional Records",
                                 "PositionURI": "https://www.usajobs.gov/job/700002", "PositionLocationDisplay": "Ogden, UT",
                                 "PositionRemuneration": [{"MinimumRange": "21", "MaximumRange": "25", "RateIntervalCode": "PH"}],
                                 "PublicationStartDate": "2026-11-03", "UserArea": {"Details": {"JobSummary": "Hourly."}}}}]}}
HIMALAYAS = {"jobs": [{"title": "Senior Data Engineer", "companyName": "Larchmont Data", "applicationLink": "https://himalayas.app/companies/larchmont/jobs/sde",
                       "locationRestrictions": ["United States", "Canada"], "minSalary": 150000, "maxSalary": 180000, "currency": "USD",
                       "pubDate": 1793000000, "expiryDate": 1795600000, "description": "<p>Python, Spark.</p>"}]}
WWR = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>WWR</title>"
       "<item><title>Fernwood Analytics: Data Engineer</title><region>Anywhere in the World</region>"
       "<link>https://weworkremotely.com/remote-jobs/fernwood-analytics-data-engineer</link>"
       "<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate><description><![CDATA[<p>Python &amp; <b>SQL</b> pipelines.</p>]]></description></item>"
       "<item><title>Fernwood Analytics: Office Manager</title><region>USA Only</region>"
       "<link>https://weworkremotely.com/remote-jobs/fernwood-analytics-office-manager</link>"
       "<pubDate>Mon, 09 Nov 2026 10:00:00 +0000</pubDate><description>Run the office.</description></item></channel></rss>")
SR_LIST = {"content": [{"id": "743999100200300", "name": "Data Engineer", "releasedDate": "2026-11-01T10:00:00.000Z",
                        "location": {"city": "Lisbon", "country": "pt", "remote": True}, "company": {"name": "Ostrava Systems"}}]}
SR_ONE = {"jobAd": {"sections": {"jobDescription": {"title": "Job", "text": "<p>Build Python pipelines.</p>"},
                                 "qualifications": {"title": "You", "text": "<ul><li>SQL</li></ul>"}}}}
RECRUITEE = {"offers": [{"id": 9001, "slug": "data-engineer", "title": "Data Engineer", "company_name": "Pemberton Works",
                         "careers_url": "https://pemberton.recruitee.com/o/data-engineer", "location": "Utrecht", "remote": False,
                         "description": "<p>Python.</p>", "requirements": "<p>SQL.</p>",
                         "salary": {"min": 60000, "max": 70000, "currency": "EUR", "period": "year"},
                         "published_at": "2026-11-03 09:00:00 UTC"}]}
PERSONIO = ("<?xml version='1.0' encoding='UTF-8'?><workzag-jobs><position><id>2201</id><subcompany>Kestrelhaus GmbH</subcompany>"
            "<office>Berlin</office><name>Data Engineer</name><createdAt>2026-11-02T10:00:00+00:00</createdAt>"
            "<jobDescriptions><jobDescription><name>Your tasks</name><value><![CDATA[<p>Python pipelines</p>]]></value>"
            "</jobDescription></jobDescriptions></position></workzag-jobs>")


# the real boards: an earlier test module may leave web_monitor.SOURCES set to its fakes
BOARDS = {n: getattr(wm, f) for n, f in (("remotive", "_remotive"), ("arbeitnow", "_arbeitnow"), ("remoteok", "_remoteok"),
                                         ("hn", "_hn"), ("jobicy", "_jobicy"), ("himalayas", "_himalayas"),
                                         ("wwr", "_wwr"), ("adzuna", "_adzuna"), ("usajobs", "_usajobs"))}


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


@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    os.environ.update({k: v for k, v in kw.items() if v is not None})
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def L(title="Data Engineer", company="Acme", url="https://jobs.example.com/1", location="Remote", desc=LONG, source="a",
      salary="", days_ago=None):
    d = (date.today() - timedelta(days=days_ago)).isoformat() if days_ago is not None else ""
    return wm._listing(title, company, url, location, salary, d, desc, source)


def run_cli(*argv) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(argv))
    return out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        wm._CACHE.clear(); wm._ANSWERS.clear()
        self.calls = []
        self.real = (wm.fetch, wm.fetch_json, wm.notify, wm.SOURCES)
        wm.notify, wm.SOURCES = (lambda m: None), dict(BOARDS)
        self._env = env(**{k: None for k in KEYS})
        self._env.__enter__()

    def tearDown(self):
        self._env.__exit__(None, None, None)
        wm.fetch, wm.fetch_json, wm.notify, wm.SOURCES = self.real
        wm._CACHE.clear(); wm._ANSWERS.clear()
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def fake(self, pages: dict):
        """fetch / fetch_json answer by URL substring; every URL asked is recorded with its headers."""
        def text(url, headers=None, **k):
            self.calls.append((url, headers or {}))
            hit = next((v for key, v in pages.items() if key in url), None)
            if isinstance(hit, BaseException):
                raise hit
            if hit is None:
                raise AssertionError(f"unexpected fetch {url}")
            return hit if isinstance(hit, str) else json.dumps(hit)
        wm.fetch = text
        wm.fetch_json = lambda url, **k: json.loads(text(url, **k))


class Sources(Base):
    def test_adzuna_needs_its_keys_drops_predicted_pay_and_credits_adzuna(self):
        self.fake({"api.adzuna.com": ADZUNA})
        self.assertNotIn("adzuna", wm.sources_ready())  # no keys: not run, and not an error
        errs = []
        with patched(wm, SOURCES={"adzuna": wm._adzuna}):
            self.assertEqual(wm.search("data", errors=errs), [])
        self.assertEqual((self.calls, errs), ([], []))
        with env(**KEYS):
            self.assertIn("adzuna", wm.sources_ready()); self.assertIn("usajobs", wm.sources_ready())
            settings.set_pref("adzuna_country", "GB")
            got = wm._adzuna("data engineer")
        url = self.calls[-1][0]
        self.assertTrue(url.startswith("https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id=adzid0123456&app_key="), url)
        self.assertEqual([(j["company"], j["salary"], j["source"]) for j in got],
                         [("Quillfeather Labs", "120000-140000", "adzuna"), ("Bramblecrest", "", "adzuna")])  # predicted: dropped
        with self.assertRaises(SystemExit):
            settings.set_pref("adzuna_country", "usa")
        self.assertEqual(wm.ATTRIBUTION["adzuna"][0], "Adzuna")
        css = (Path(web.__file__).parent / "static" / "app.css").read_text(encoding="utf-8")
        self.assertIn("min-width: 116px; min-height: 23px", css)  # Adzuna's attribution size

    def test_usajobs_sends_its_documented_headers_and_keeps_annual_pay_only(self):
        self.fake({"data.usajobs.gov": USAJOBS})
        with env(**KEYS):
            got = wm._usajobs("data")
        url, headers = self.calls[-1]
        self.assertEqual(url, "https://data.usajobs.gov/api/search?Keyword=data&ResultsPerPage=100")
        self.assertEqual((headers["Host"], headers["User-Agent"], headers["Authorization-Key"]),
                         ("data.usajobs.gov", "pat.rivera@example.com", "usakeyQQ11223344"))
        self.assertEqual([(j["title"], j["salary"], j["closes_at"]) for j in got],
                         [("IT Specialist (Data)", "USD 99000-128000", "2026-12-01"), ("Seasonal Data Clerk", "", "")])

    def test_himalayas_expiry_and_we_work_remotely_rss(self):
        self.fake({"himalayas.app": HIMALAYAS, "weworkremotely.com": WWR})
        h, = wm._himalayas("data")
        self.assertEqual((h["company"], h["url"], h["location"], h["salary"], h["date"]),
                         ("Larchmont Data", HIMALAYAS["jobs"][0]["applicationLink"], "United States, Canada", "USD 150000-180000",
                          "2026-10-26"))
        self.assertEqual(h["closes_at"], "2026-11-25")
        self.assertNotIn("<", h["desc"])
        w = wm._wwr("data engineer")
        self.assertEqual([(j["company"], j["title"], j["location"], j["date"]) for j in w],
                         [("Fernwood Analytics", "Data Engineer", "Anywhere in the World", "2026-11-09")])
        self.assertIn("Python & SQL", w[0]["desc"])
        self.assertIn("himalayas", db.REMOTE_BOARDS); self.assertIn("wwr", db.REMOTE_BOARDS)

    def test_new_feeds_parse_and_their_posting_ids_match_the_feed(self):
        self.fake({"api.smartrecruiters.com/v1/companies/ostrava/postings/743999100200300": SR_ONE,
                   "api.smartrecruiters.com/v1/companies/ostrava/postings": SR_LIST,
                   "pemberton.recruitee.com/api/offers": RECRUITEE, "kestrelhaus.jobs.personio.de/xml": PERSONIO})
        sr, = wm.feed("smartrecruiters", "ostrava", "Ostrava")
        self.assertEqual((sr["company"], sr["location"], sr["ats_feed"], sr["ats_id"]),
                         ("Ostrava Systems", "Lisbon, pt (remote)", "smartrecruiters:ostrava", "743999100200300"))
        self.assertIn("Build Python pipelines.", sr["desc"]); self.assertIn("SQL", sr["desc"])
        rc, = wm.feed("recruitee", "pemberton", "Pemberton")
        self.assertEqual((rc["url"], rc["ats_id"], rc["salary"]), ("https://pemberton.recruitee.com/o/data-engineer", "data-engineer",
                                                                    "EUR 60000-70000"))
        pe, = wm.feed("personio", "kestrelhaus", "Kestrelhaus")
        self.assertEqual((pe["company"], pe["url"], pe["location"]), ("Kestrelhaus GmbH", "https://kestrelhaus.jobs.personio.de/job/2201", "Berlin"))
        self.assertTrue(any("language=en" in u for u, _ in self.calls))
        for j in (sr, rc, pe):  # the posting check looks a job up by the id its URL carries: never a false 'removed'
            self.assertEqual(wm._posting_id(j["url"]), j["ats_id"], j["url"])
            self.assertTrue(db.ATS_FEED_RE.fullmatch(j["ats_feed"]))
            self.assertEqual(wm.detect_ats(j["url"])[0], j["source"])
        self.assertEqual(wm.detect_ats("https://jobs.smartrecruiters.com/OstravaSystems/743999100200300-data-engineer"),
                         ("smartrecruiters", "OstravaSystems"))
        self.assertEqual(wm.detect_ats("https://pemberton.recruitee.com/"), ("recruitee", "pemberton"))
        self.assertEqual(wm.detect_ats("personio:kestrelhaus"), ("personio", "kestrelhaus"))
        self.assertIsNone(wm.detect_ats("recruitee:a.b"))  # a slug that goes into a host name is one label
        self.assertIsNone(wm.detect_ats("https://evil.example/pemberton.recruitee.com"))
        self.assertEqual(wm.add_company("https://pemberton.recruitee.com/o/data-engineer")["vendor"], "recruitee")
        jid = db.add_job("Pemberton", "Data Engineer", rc["url"], "x", ats_feed="recruitee:pemberton")
        self.assertEqual(db.get_job(jid)["ats_feed"], "recruitee:pemberton")
        detail = lambda: len([u for u, _ in self.calls if "/postings/743999100200300" in u])  # noqa: E731
        n = detail()
        db.mark_seen("listing:" + sr["url"])
        wm.feed("smartrecruiters", "ostrava", "Ostrava")
        self.assertEqual(detail(), n)  # a posting seen before is not described again (one call each, new ones only)

    def test_a_feed_the_employer_did_not_make_public_says_so(self):
        def http(code):
            return urllib.error.HTTPError("https://x", code, "no", {}, io.BytesIO(b""))
        self.fake({"api.smartrecruiters.com": http(401), "nofeed.jobs.personio.de": http(404)})
        for vendor, slug in (("smartrecruiters", "secretco"), ("personio", "nofeed")):
            with self.assertRaises(ValueError) as e:
                wm.feed(vendor, slug, "X")
            self.assertIn("feed is not public", str(e.exception)); self.assertIn("page watch", str(e.exception))
        cid = db.add_company("smartrecruiters", "secretco", "Secretco")
        wm.check_watches()
        co = next(c for c in db.companies() if c["id"] == cid)
        self.assertIn("SmartRecruiters feed is not public (HTTP 401)", co["last_error"])

    def test_errors_never_show_a_keyed_sources_secret(self):
        def leak(url, **k):
            raise ValueError(f"response from {url} took too long (key adzkeyZZ9988776655, id adzid0123456)")
        out = io.StringIO()
        with env(**KEYS), patched(wm, fetch_json=leak), contextlib.redirect_stdout(out):
            errs = []
            wm.search("data", sources=["adzuna"], errors=errs)
            db.add_watch("search:data", "")
            with patched(wm, SOURCES={"adzuna": wm._adzuna}):
                wm.check_watches()
        w = db.watches()[0]
        for text in (errs[0], out.getvalue(), w["last_error"]):
            self.assertNotIn("adzkeyZZ9988776655", text); self.assertNotIn("adzid0123456", text)
            self.assertIn("***", text)


class Throttle(Base):
    def setUp(self):
        super().setUp()
        settings.set_tool("auto_track", enabled=False)  # judging is not what this tests
        self.fake({"remotive.com": {"jobs": [{"title": "Data Engineer", "company_name": "Acme", "url": "https://r/1",
                                              "description": "python data"}]},
                   "hn.algolia.com": {"hits": []}})

    def remotive_calls(self):
        return len([u for u, _ in self.calls if "remotive.com" in u])

    def test_global_boards_are_asked_once_per_window_for_every_saved_search(self):
        with patched(wm, SOURCES={"remotive": wm._remotive, "hn": wm._hn}):
            for q in ("data engineer", "python", "analytics"):
                db.add_watch(f"search:{q}", "")
            seen_before = db.con().execute("SELECT COUNT(*) n FROM seen").fetchone()["n"]
            wm.check_watches()
            wm.check_watches()
            self.assertEqual(self.remotive_calls(), 1)  # one unfiltered fetch for all three queries, all day
            self.assertIn("https://remotive.com/api/remote-jobs?limit=100", [u for u, _ in self.calls])
            keys = {r["key"] for r in db.con().execute("SELECT key FROM meta WHERE key LIKE 'src:%'")}
            self.assertEqual(keys, {"src:remotive", "src:hn:data engineer", "src:hn:python", "src:hn:analytics"})
            wm.search("data")  # a manual search reuses the fresh copy: rapid clicks never trip the per-minute block
            self.assertEqual(self.remotive_calls(), 1)
            seen = [r["key"] for r in db.con().execute("SELECT key FROM seen")]
            self.assertFalse([k for k in seen if k.startswith("src")])  # the throttle writes meta timestamps only
            self.assertLessEqual(len(seen) - seen_before, 10)
            wm._CACHE.clear(); wm._ANSWERS.clear()  # a restart inside the window: scheduled runs skip the board
            before = {w["id"]: (w["last_seen"], w["last_error"]) for w in db.watches()}
            wm.check_watches()
            self.assertEqual(self.remotive_calls(), 1)
            self.assertEqual({w["id"]: (w["last_seen"], w["last_error"]) for w in db.watches()}, before)  # nothing ran
            wm.search("data")  # regression: a manual search in a new process (a CLI run) reads the saved copy
            self.assertEqual(self.remotive_calls(), 1)
            wm._CACHE.clear()
            wm._board_file("remotive").unlink()
            errs = []
            wm.search("data", errors=errs)  # no saved copy inside the window: skipped, never asked again
            self.assertEqual((self.remotive_calls(), errs), (1, []))
            db.con().execute("UPDATE meta SET value=value-7*3600 WHERE key LIKE 'src:%'")
            wm.check_watches()
            self.assertEqual(self.remotive_calls(), 2)  # the window passed

    def test_adzuna_daily_quota_and_a_connection_error_refunds(self):
        with env(**KEYS), patched(wm, ADZUNA_DAILY=2):
            self.fake({"api.adzuna.com": urllib.error.URLError("offline")})
            for _ in range(3):
                with self.assertRaises(urllib.error.URLError):
                    wm._adzuna("data")
            self.fake({"api.adzuna.com": ADZUNA})
            wm._adzuna("data"); wm._adzuna("data")  # never reached before: the calls were refunded
            with self.assertRaises(wm.Throttled):
                wm._adzuna("data")
            errs = []
            wm.search("data", sources=["adzuna"], errors=errs)
            self.assertEqual(errs, [])  # over the quota: skipped, not an error


class Store(Base):
    def row(self, **where):
        k, v = next(iter(where.items()))
        return dict(db.con().execute(f"SELECT rowid AS id, * FROM postings WHERE {k}=?", (v,)).fetchone())

    def test_merge_keeps_the_first_url_and_every_link_and_source(self):
        a = L(url="https://jobs.example.com/a/1", source="remotive", desc="short")
        b = L(company="ACME Inc.", url="https://boards.greenhouse.io/acme/jobs/9", source="greenhouse") | {"ats_id": "9",
                                                                                                         "ats_feed": "greenhouse:acme"}
        r1, = listings.store([a])
        r2, = listings.store([b])
        self.assertEqual((r1["id"], r1["new"], r2["new"]), (r2["id"], True, False))
        row = self.row(key=r1["key"])
        self.assertEqual(row["url"], "https://jobs.example.com/a/1")
        self.assertEqual(json.loads(row["urls"]), ["https://jobs.example.com/a/1", "https://boards.greenhouse.io/acme/jobs/9"])
        self.assertEqual(json.loads(row["sources"]), ["remotive", "greenhouse"])
        self.assertEqual((row["jd"], row["ats_feed"], row["seen_count"]), (LONG.strip(), "greenhouse:acme", 2))
        self.assertIsNotNone(row["fit_score"]); self.assertIsNotNone(row["last_seen"])
        self.assertIsNone(row["reposted_at"])  # another site, the same posting: syndication, not a repost

    def test_fuzzy_place_merges_and_distinct_titles_stay_apart(self):
        listings.store([L(location="Austin, TX", url="https://x.example/1")])
        listings.store([L(location="Austin, Texas, United States", url="https://y.example/2")])
        listings.store([L(title="Data Engineer, Payments", location="Austin, TX", url="https://z.example/3")])
        listings.store([L(company="Brightwater", location="", url="https://b.example/1")])
        listings.store([L(company="Brightwater", location="Remote", url="https://b.example/2")])
        rows = db.con().execute("SELECT title, company, urls FROM postings ORDER BY first_seen, rowid").fetchall()
        self.assertEqual([(r["title"], r["company"], len(json.loads(r["urls"]))) for r in rows],
                         [("Data Engineer", "Acme", 2), ("Data Engineer, Payments", "Acme", 1), ("Data Engineer", "Brightwater", 2)])

    def test_repost_on_the_same_site_after_21_days_marks_the_tracked_job(self):
        first = L(url="https://boards.greenhouse.io/acme/jobs/1")
        listings.store([first])
        jid = db.add_job("Acme", "Data Engineer", first["url"], LONG)  # add_job links the row by its URL
        self.assertEqual(self.row(url=first["url"])["job_id"], jid)
        db.con().execute("UPDATE postings SET first_seen=datetime('now','-30 days')"); db.con().commit()
        listings.store([L(url="https://jobs.linkedin.com/view/77")])  # another site: syndication
        self.assertIsNone(self.row(url=first["url"])["reposted_at"])
        again = L(url="https://boards.greenhouse.io/acme/jobs/2")
        self.assertIn("reposted", wm.ghost_signals(again)["reasons"][0])
        self.assertEqual(wm.ghost_signals(L(url="https://jobs.linkedin.com/view/78"))["score"], 0)
        listings.store([again])
        row = self.row(url=first["url"])
        self.assertEqual(row["reposted_at"], date.today().isoformat())
        self.assertEqual([e["kind"] for e in db.events(jid)].count("posting_reposted"), 1)
        listings.store([again])
        self.assertEqual([e["kind"] for e in db.events(jid)].count("posting_reposted"), 1)  # once per new link
        db.delete_job(jid)
        self.assertIsNone(self.row(url=first["url"])["job_id"])  # deleting the job untracks the listing

    def test_two_openings_with_other_ats_ids_stay_apart_and_are_no_repost(self):  # regression: they were merged
        def gh(i):
            return L(title="Software Engineer", url=f"https://boards.greenhouse.io/acme/jobs/{i}", source="greenhouse") | {
                "ats_id": str(i), "ats_feed": "greenhouse:acme"}

        r111, = listings.store([gh(111)])
        jid = db.add_job("Acme", "Software Engineer", gh(111)["url"], LONG)
        db.con().execute("UPDATE postings SET first_seen=datetime('now','-30 days')"); db.con().commit()
        self.assertEqual(len(wm.dedupe([gh(111), gh(222)])), 2)
        r111b, r222 = listings.store([gh(111), gh(222)])
        self.assertEqual((r111b["id"], r222["new"]), (r111["id"], True))
        self.assertNotEqual(r222["id"], r111["id"])
        self.assertIsNone(self.row(url=gh(111)["url"])["reposted_at"])
        self.assertNotIn("posting_reposted", [e["kind"] for e in db.events(jid)])
        self.assertEqual(wm.ghost_signals(gh(222))["score"], 0)  # not 'reposted: first seen 30 days ago'
        r222b, = listings.store([gh(222)])  # seen again: the same second row
        self.assertEqual((r222b["id"], r222b["new"]), (r222["id"], False))
        self.assertEqual(listings.query(show="all")["total"], 2)

    def test_query_filters_new_since_visit_sources_and_fit(self):
        listings.store([L(company="Acme", url="https://a.example/1", source="remotive", salary="$150,000 - $170,000")])
        listings.store([L(company="Bolt", url="https://b.example/1", source="hn", location="Berlin (hybrid)")])
        listings.store([L(company="Cobalt", url="https://c.example/1", source="adzuna")])
        q = listings.query()
        self.assertEqual((q["total"], q["sources"]), (3, {"remotive": 1, "hn": 1, "adzuna": 1}))
        self.assertTrue(all(r["new"] for r in q["rows"]))
        self.assertNotIn("jd", q["rows"][0]); self.assertNotIn("desc", q["rows"][0]); self.assertNotIn("fit", q["rows"][0])
        self.assertEqual([r["company"] for r in listings.query(sources=["hn", "adzuna"], sort="company")["rows"]], ["Bolt", "Cobalt"])
        self.assertEqual(listings.query(sources=["hn"])["sources"], q["sources"])  # chips keep their counts
        self.assertEqual([r["company"] for r in listings.query(remote="hybrid")["rows"]], ["Bolt"])
        self.assertEqual([r["company"] for r in listings.query(min_salary="160k")["rows"]], ["Acme"])
        self.assertEqual([r["company"] for r in listings.query(q="cob")["rows"]], ["Cobalt"])
        self.assertEqual(listings.query(min_fit=101)["total"], 0)
        with self.assertRaises(SystemExit):
            listings.query(days="soon")
        listings.visit()
        self.assertEqual(listings.query(new=True)["total"], 0)
        db.con().execute("UPDATE postings SET first_seen=datetime('now', '-1 hour')")
        db.con().execute("UPDATE meta SET value=value-100 WHERE key='alljobs_visit'"); db.con().commit()
        listings.store([L(company="Dune", url="https://d.example/1")])
        self.assertEqual([r["company"] for r in listings.query(new=True)["rows"]], ["Dune"])

    def test_track_dismiss_and_prune(self):
        rows = listings.store([L(company=c, url=f"https://{c}.example/1") for c in ("acme", "bolt", "cobalt", "dune")])
        pid = rows[0]["id"]
        jid = listings.track(pid)
        job = db.get_job(jid)
        self.assertEqual((job["company"], job["url"], job["status"]), ("acme", "https://acme.example/1", "saved"))
        self.assertIn("found via a", job["notes"])
        self.assertEqual([r["job_id"] for r in listings.query(show="tracked")["rows"]], [jid])
        self.assertEqual(listings.query()["total"], 3)
        listings.dismiss(rows[1]["id"])
        self.assertEqual(listings.query()["total"], 2)
        self.assertEqual([r["company"] for r in listings.query(show="dismissed")["rows"]], ["bolt"])
        listings.dismiss(rows[1]["id"], on=False)
        with self.assertRaises(SystemExit):
            listings.dismiss(999999)
        db.con().execute("UPDATE postings SET last_seen=datetime('now','-50 days')")
        # local date, as prune compares: the UTC date is already tomorrow in a US evening
        db.con().execute("UPDATE postings SET closed_at=date('now','localtime','-1 day'), last_seen=datetime('now') "
                         "WHERE company='dune'")
        db.con().commit()
        self.assertEqual(listings.prune(), 3)  # unseen 45 days, or past its closing date; never the tracked one
        self.assertEqual([r["company"] for r in db.con().execute("SELECT company FROM postings")], ["acme"])
        g = listings.get(pid)
        self.assertEqual((g["job_id"], g["desc"][:20]), (jid, LONG[:20]))
        self.assertIn("parts", g["fit"])

    def test_search_results_are_stored_with_their_row_id(self):
        with patched(wm, SOURCES={"a": lambda q: [L(url="https://s.example/1"), L(company="Zed", url="https://s.example/2")]}):
            got = wm.search("data")
        self.assertTrue(all(j["id"] and j["key"] and j["fit"]["score"] is not None for j in got))
        self.assertEqual(listings.query()["total"], 2)


class Keys(Base):
    def setUp(self):
        super().setUp()
        self.store = {}
        self.kreal = (vault.get, vault.set, vault.delete, connections.urlopen, connections.PATH)
        vault.get = lambda n: self.store.get(n)
        vault.set = lambda n, v: self.store.__setitem__(n, v)
        vault.delete = lambda n: self.store.pop(n, None)
        connections.PATH = connections.PATH.with_name("connections-test-sources.json")
        connections.PATH.unlink(missing_ok=True)
        self.asked = []

    def tearDown(self):
        connections.PATH.unlink(missing_ok=True)
        vault.get, vault.set, vault.delete, connections.urlopen, connections.PATH = self.kreal
        super().tearDown()

    def answer(self, code=200):
        def urlopen(req, timeout=None):
            self.asked.append((req.full_url, dict(req.header_items())))
            if code != 200:
                raise urllib.error.HTTPError(req.full_url, code, "no", {}, io.BytesIO(b"{}"))
            return contextlib.closing(io.BytesIO(b'{"results": []}'))
        connections.urlopen = urlopen

    def test_adzuna_and_usajobs_keys_link_verify_and_stay_off_the_ai_card(self):
        self.answer()
        with self.assertRaises(SystemExit):
            connections.link("adzuna", "adzkeyZZ9988776655")  # the Application ID is needed too
        r = connections.link("adzuna", "adzkeyZZ9988776655", "adzid0123456")
        self.assertEqual((r["status"], self.store["ADZUNA_APP_ID"], self.store["ADZUNA_APP_KEY"]),
                         ("verified", "adzid0123456", "adzkeyZZ9988776655"))
        self.assertIn("api.adzuna.com/v1/api/jobs/us/search/1?app_id=adzid0123456", self.asked[-1][0])
        with self.assertRaises(SystemExit):
            connections.link("usajobs", "usakeyQQ11223344", "not-an-email")
        r = connections.link("USAJOBS_API_KEY", "usakeyQQ11223344", "pat.rivera@example.com")
        self.assertEqual(r["status"], "verified")
        self.assertEqual((self.asked[-1][1].get("Authorization-key"), self.asked[-1][1].get("User-agent")),
                         ("usakeyQQ11223344", "pat.rivera@example.com"))
        st = connections.status()["keys"]
        self.assertEqual((st["adzuna"]["kind"], st["adzuna"]["linked"], st["adzuna"]["model"]), ("jobs", True, ""))
        self.assertNotIn("adzuna", __import__("lodestar.ai", fromlist=["available"]).available())
        self.assertIn("adzuna", wm.sources_ready())
        self.assertNotIn("adzkeyZZ9988776655", json.dumps(st) + connections.PATH.read_text(encoding="utf-8"))
        self.answer(401)
        self.assertEqual(connections.check("adzuna")["status"], "failed")
        connections.unlink("adzuna")
        self.assertNotIn("ADZUNA_APP_ID", self.store); self.assertNotIn("ADZUNA_APP_KEY", self.store)
        self.assertNotIn("adzuna", wm.sources_ready())
        js = (__import__("pathlib").Path(web.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("c.keys[n].kind !== 'jobs'", js)  # the AI card lists AI providers only


class Routes(unittest.TestCase):
    def test_routes_need_the_token_return_raw_json_and_never_a_floor_figure(self):
        import http.client
        from lodestar import desktop

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        snap = PROFILE.read_bytes() if PROFILE.is_file() else None
        PROFILE.write_text("# Pat Rivera\npat@example.com\n## Skills\nPython, SQL\n## Preferences\nSalary floor: $123,456\n",
                           encoding="utf-8")
        xss = "<img src=x onerror=alert(1)>"
        rows = listings.store([L(title=f"Data Engineer {xss}", company="Zzroutes", url="https://zz.example/1",
                                 salary="$100,000 - $130,000")])
        pid = rows[0]["id"]
        real_sources, wm.SOURCES = wm.SOURCES, dict(BOARDS)
        port = desktop.free_port(8930); srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        jid = None
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            def call(method, path, body=None, headers=h):
                c.request(method, path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse(); raw = r.read().decode()
                return r.status, raw
            for m, path, body in (("GET", "/api/listings", None), ("GET", f"/api/listings/{pid}", None),
                                  ("POST", f"/api/listings/{pid}/dismiss", {}), ("POST", "/api/listings/visit", {}),
                                  ("POST", f"/api/listings/{pid}/track", {})):
                self.assertEqual(call(m, path, body, {**h, "X-Lodestar-Token": "no"})[0], 403, path)
            st, raw = call("GET", "/api/listings?q=zzroutes&sort=new")
            r = json.loads(raw)
            self.assertEqual((st, r["rows"][0]["title"]), (200, f"Data Engineer {xss}"))  # raw in JSON; the page escapes it
            self.assertIn("remotive", r["boards"]); self.assertFalse(r["boards"]["adzuna"]["ready"])
            for figure in ("123456", "123,456", "123k"):
                self.assertNotIn(figure, raw)
                self.assertNotIn(figure, call("GET", f"/api/listings/{pid}")[1])
            self.assertEqual(call("GET", "/api/listings?days=soon")[0], 400)
            self.assertEqual(call("GET", "/api/listings/999999")[0], 404)
            self.assertEqual(call("POST", f"/api/listings/{pid}/dismiss", {"on": True})[0], 200)
            self.assertEqual(json.loads(call("GET", "/api/listings?q=zzroutes&show=dismissed")[1])["total"], 1)
            self.assertGreater(json.loads(call("POST", "/api/listings/visit", {})[1])["visit"], time.time() - 60)
            st, raw = call("POST", f"/api/listings/{pid}/track", {})
            jid = json.loads(raw)["id"]
            self.assertEqual(db.get_job(jid)["company"], "Zzroutes")
            s = json.loads(call("GET", "/api/state")[1])
            self.assertEqual(s["sources"]["adzuna"]["keys"], [{"name": "ADZUNA_APP_ID", "set": False},
                                                             {"name": "ADZUNA_APP_KEY", "set": False}])
            c.close()
        finally:
            srv.shutdown()
            wm.SOURCES = real_sources
            if jid:
                db.delete_job(jid)
            db.con().execute("DELETE FROM postings WHERE company='Zzroutes'"); db.con().commit()
            PROFILE.write_bytes(snap) if snap is not None else PROFILE.unlink(missing_ok=True)
            db._local.con.close()
            db._local.con = saved


class Cli(Base):
    def test_jobs_all_and_track_listing(self):
        rows = listings.store([L(company="Quillfeather", url="https://q.example/1", source="himalayas")])
        out = run_cli("jobs", "all", "--source", "himalayas")
        self.assertIn(f"L{rows[0]['id']}", out); self.assertIn("Quillfeather", out); self.assertIn("[new]", out)
        self.assertIn("1 listing(s)", out)
        self.assertIn("tracked as #", run_cli("jobs", "track-listing", str(rows[0]["id"])))
        self.assertIn("0 listing(s)", run_cli("jobs", "all"))
        self.assertIn("[tracked #", run_cli("jobs", "all", "--show", "tracked"))


if __name__ == "__main__":
    unittest.main()
