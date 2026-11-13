"""Pass 21, builder 3: one listing monitored both ways. The daily listing check (web_monitor.check_listings: feed jobs
compared with their last copy, removals, reopenings; posting pages read only where robots.txt allows, never LinkedIn /
Indeed / Glassdoor / ZipRecruiter, gone only after two misses in a row), ATS mail tied to its job by a posting link,
a Workday tenant or company + title (link_reason; never trusted), the drawer's Listing activity and the routes. No
network: fetch, fetch_json and imaplib are faked, and everything patched is put back."""
import contextlib
import email
import imaplib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import db, email_monitor as em, listings, loop, pipeline, settings, web, web_monitor as wm  # noqa: E402
from lodestar.config import SNAPSHOTS  # noqa: E402
from lodestar.resume import app_dir  # noqa: E402

DESC = ("You will build data pipelines in Python and SQL, own the warehouse and review code.\n"
        "We work in small teams and ship weekly.\nYou mentor two engineers.\n")
NOW = datetime(2026, 11, 9, 9, 0)  # a Monday
PASS = "mx.example.net; dkim=pass header.d={d}; dmarc=pass header.from={d}"


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


def gh(*jobs):
    return {"jobs": [{"id": i, "title": t, "absolute_url": f"https://boards.greenhouse.io/zephyrine/jobs/{i}",
                      "location": {"name": loc}, "content": c} for i, t, loc, c in jobs]}


def ld_page(valid="2026-12-31", desc="<p>Build pipelines.</p><p>Own the warehouse.</p>", salary=(130000, 160000)):
    post = {"@type": "JobPosting", "title": "Data Engineer", "hiringOrganization": {"@type": "Organization", "name": "Larchmont Data"},
            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Chicago", "addressRegion": "IL"}},
            "baseSalary": {"currency": "USD", "value": {"minValue": salary[0], "maxValue": salary[1], "unitText": "YEAR"}},
            "description": desc, "validThrough": valid}
    return ('<html><head><script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Larchmont"}, post]}) + "</script></head><body>Apply now</body></html>")


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = settings.PATH.read_bytes() if settings.PATH.is_file() else None
        settings.PATH.unlink(missing_ok=True)
        for t in ("email_reply", "interview_scheduling", "calendar", "auto_track"):
            settings.set_tool(t, enabled=False)
        for p in SNAPSHOTS.glob("job-*.json"):  # job ids restart in each in-memory database
            p.unlink()
        self.tag = uuid.uuid4().hex[:6]  # job folders are named after the company: one per test
        self.notes, self.fetched, self.pages, self.feed = [], [], {}, gh()
        self.real = (wm.fetch, wm.fetch_json, wm.notify, em.notify)
        wm.notify = em.notify = self.notes.append
        wm.fetch, wm.fetch_json = self.fake_fetch, lambda url, **k: json.loads(json.dumps(self.feed))

    def tearDown(self):
        wm.fetch, wm.fetch_json, wm.notify, em.notify = self.real
        for p in SNAPSHOTS.glob("job-*.json"):
            p.unlink()
        db._local.con.close()
        db._local.con = self._con
        settings.PATH.write_bytes(self.snap) if self.snap is not None else settings.PATH.unlink(missing_ok=True)

    def fake_fetch(self, url, **k):
        self.fetched.append(url)
        v = self.pages.get(url, "" if url.endswith("/robots.txt") else None)
        if v is None:
            raise AssertionError(f"unexpected fetch {url}")
        if isinstance(v, int):
            raise urllib.error.HTTPError(url, v, "gone", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        return v

    def check(self, days=0):
        with contextlib.redirect_stdout(io.StringIO()):
            return wm.check_listings(NOW + timedelta(days=days))

    def kinds(self, jid):
        return [e["kind"] for e in db.events(jid) if e["kind"].startswith("posting_")]


class Feeds(Base):
    def test_description_and_salary_changes_are_diffed_and_the_jd_kept(self):
        self.feed = gh((101, "Data Engineer", "Austin, TX", DESC + "Salary: $120,000 - $140,000"))
        jid = db.add_job(f"Zephyrine {self.tag}", "Data Engineer", "https://boards.greenhouse.io/zephyrine/jobs/101", "my tailored JD")
        self.assertEqual(self.check(), [])
        self.assertTrue((SNAPSHOTS / f"job-{jid}.json").is_file())  # the first sighting only takes a copy
        self.assertEqual(self.kinds(jid), [])
        self.feed = gh((101, "Data Engineer", "Austin, TX", DESC.replace("weekly", "daily") + "You own the dbt models.\n"
                        "Salary: $130,000 - $150,000"))
        self.check(1)
        ev = [e for e in db.events(jid) if e["kind"] == "posting_changed"]
        self.assertEqual(len(ev), 1)
        self.assertIn("salary '$120,000 - $140,000' -> '$130,000 - $150,000'", ev[0]["detail"])
        self.assertRegex(ev[0]["detail"], r"description \+\d+/-\d+ lines")
        diff = (app_dir(db.get_job(jid)) / "posting_changes.md").read_text(encoding="utf-8")
        self.assertIn("## 2026-11-10 posting changed", diff)
        self.assertIn("+We work in small teams and ship daily.", diff)
        self.assertIn("-We work in small teams and ship weekly.", diff)
        self.assertEqual(db.get_job(jid)["jd"], "my tailored JD")  # never rewritten by the monitor
        self.assertIn("posting_changes.md", web._docs(db.get_job(jid)))  # the drawer lists it
        self.check(1)  # same day: nothing fetched again
        self.check(2)  # no change: no new event
        self.assertEqual(self.kinds(jid), ["posting_changed"])
        changed = web.use_live_jd(jid)  # 'Use live description': the user's click
        self.assertTrue(changed)
        self.assertIn("You own the dbt models.", db.get_job(jid)["jd"])
        self.assertFalse(web.use_live_jd(jid))

    def test_removal_proposes_for_saved_only_records_applied_and_today_lists_it(self):
        self.feed = gh((201, "Keeper", "Remote", DESC))
        saved = db.add_job(f"Zephyrine {self.tag}", "Gone saved", "https://boards.greenhouse.io/zephyrine/jobs/202", DESC)
        applied = db.add_job(f"Zephyrine {self.tag}", "Gone applied", "https://boards.greenhouse.io/zephyrine/jobs/203", DESC)
        db.set_status(applied, "applied")
        keeper = db.add_job(f"Zephyrine {self.tag}", "Keeper", "https://boards.greenhouse.io/zephyrine/jobs/201", DESC)
        self.assertEqual(self.check(), [saved])
        p = db.list_pending("pending")
        self.assertEqual([(x["job_id"], json.loads(x["payload"])["status"]) for x in p], [(saved, "withdrawn")])
        self.assertEqual((self.kinds(saved), self.kinds(applied), self.kinds(keeper)), (["posting_removed"], ["posting_removed"], []))
        self.assertEqual(db.get_job(applied)["status"], "applied")
        closed = loop.agenda()["closed"]
        self.assertEqual([c["id"] for c in closed], [applied])  # the saved one is in the Inbox instead
        db.con().execute("UPDATE events SET ts=datetime('now', '-30 days') WHERE job_id=? AND kind != 'posting_removed'", (applied,))
        db.add_event(applied, "listing_seen", "in LinkedIn alert: Gone applied")
        db.con().commit()
        self.assertIn(applied, [j["id"] for j in db.needs_followup(7)])  # watching the posting is not hearing back
        self.assertEqual(self.check(1), [])  # not proposed or recorded twice
        self.assertEqual(self.kinds(saved), ["posting_removed"])

    def test_a_reopened_posting_clears_the_removal(self):
        self.feed = gh((301, "Other", "Remote", DESC))
        jid = db.add_job(f"Zephyrine {self.tag}", "Data Engineer", "https://boards.greenhouse.io/zephyrine/jobs/302", DESC * 4)
        db.set_status(jid, "applied")
        self.check()
        removed = wm.ghost_signals(db.get_job(jid))
        self.assertIn("posting removed", " ".join(removed["reasons"]))
        fit_gone = db.get_job(jid)["fit_score"]
        self.feed = gh((301, "Other", "Remote", DESC), (302, "Data Engineer", "Remote", DESC * 4))
        self.assertIsNone(db.get_job(jid)["posting_checked_at"])  # pass 26: never seen live yet
        self.check(1)
        self.assertEqual(self.kinds(jid), ["posting_removed", "posting_reopened"])
        self.assertTrue(db.get_job(jid)["posting_checked_at"])  # the day its posting last answered
        back = wm.ghost_signals(db.get_job(jid))
        self.assertNotIn("posting removed", " ".join(back["reasons"]))
        self.assertLess(back["score"], removed["score"])
        if fit_gone is not None:  # a real profile on this home: the fit recovers with the ghost penalty gone
            self.assertGreaterEqual(db.get_job(jid)["fit_score"], fit_gone)
        self.assertIsNone(wm.removed_event(jid))
        self.assertEqual(loop.agenda()["closed"], [])
        self.feed = gh((301, "Other", "Remote", DESC))
        self.check(2)  # a second removal after reopening is recorded again
        self.assertEqual(self.kinds(jid), ["posting_removed", "posting_reopened", "posting_removed"])


class Pages(Base):
    URL = "https://careers.larchmont.example/jobs/data-engineer"

    def job(self, url=None, status="applied"):
        jid = db.add_job(f"Larchmont {self.tag}", "Data Engineer", url or self.URL, DESC)
        db.set_status(jid, status) if status != "saved" else None
        return jid

    def test_robots_disallow_skips_with_one_notify(self):
        jid = self.job()
        self.pages["https://careers.larchmont.example/robots.txt"] = "User-agent: *\nDisallow: /jobs/\n"
        self.check()
        self.check(1)
        self.assertNotIn(self.URL, self.fetched)
        self.assertEqual(len([n for n in self.notes if "robots.txt" in n]), 1)
        self.assertEqual(self.kinds(jid), [])

    def test_two_404s_in_a_row_make_it_gone_and_one_flaky_404_does_not(self):
        jid = self.job(status="saved")
        self.pages[self.URL] = 404
        self.assertEqual(self.check(), [])  # one miss: nothing recorded
        self.assertEqual(self.kinds(jid), [])
        self.assertEqual(self.check(1), [jid])  # the next day: gone, and a saved job's withdrawal is proposed
        self.assertEqual(self.kinds(jid), ["posting_removed"])
        self.assertEqual(self.fetched.count(self.URL), 2)
        other = self.job(url="https://careers.larchmont.example/jobs/analyst")
        self.pages["https://careers.larchmont.example/jobs/analyst"] = 410
        self.check(2)
        self.pages["https://careers.larchmont.example/jobs/analyst"] = "<html>We are hiring an analyst.</html>"
        self.check(3)
        self.assertEqual(self.kinds(other), [])  # a 410 then a 200: nothing recorded
        self.assertEqual(db.meta_get(f"pagemiss:{other}"), 0)

    def test_json_ld_closing_date_description_diff_and_weekly_cadence(self):
        jid = self.job()
        self.pages[self.URL] = ld_page()
        self.check()
        snap = json.loads((SNAPSHOTS / f"job-{jid}.json").read_text(encoding="utf-8"))
        self.assertEqual((snap["title"], snap["location"], snap["salary"]), ("Data Engineer", "Chicago, IL", "USD 130000-160000 YEAR"))
        self.pages[self.URL] = ld_page(desc="<p>Build pipelines.</p><p>Own the lakehouse.</p>", salary=(135000, 165000))
        self.check(1)
        self.assertEqual(self.fetched.count(self.URL), 1)  # a page is read at most weekly
        self.check(7)
        self.assertEqual(self.fetched.count(self.URL), 2)
        ev = [e["detail"] for e in db.events(jid) if e["kind"] == "posting_changed"]
        self.assertEqual(len(ev), 1)
        self.assertIn("salary 'USD 130000-160000 YEAR' -> 'USD 135000-165000 YEAR'", ev[0])
        self.pages[self.URL] = ld_page(valid="2026-11-01")  # closing date passed: a miss, then gone the day after
        self.check(14)
        self.assertNotIn("posting_removed", self.kinds(jid))
        self.check(15)
        self.assertEqual(self.kinds(jid)[-1], "posting_removed")
        closed = self.job(url="https://careers.larchmont.example/jobs/closed")
        self.pages["https://careers.larchmont.example/jobs/closed"] = "<p>This position has been filled.</p>"
        self.check(16)
        self.check(17)
        self.assertEqual(self.kinds(closed), ["posting_removed"])

    def test_linkedin_indeed_glassdoor_and_ziprecruiter_are_never_fetched(self):
        ids = [self.job(url=u) for u in ("https://www.linkedin.com/jobs/view/4012345678/", "https://www.indeed.com/viewjob?jk=0a1b2c3d4e5f",
                                         "https://www.glassdoor.co.uk/job-listing/x?jl=1", "https://www.ziprecruiter.com/c/Acme/Job/x")]
        self.check()
        self.assertEqual(self.fetched, [])
        self.assertTrue(all(wm.no_fetch(db.get_job(j)["url"]) for j in ids))
        self.assertFalse(wm.no_fetch(self.URL))
        p = listings.posting_of(db.get_job(ids[0]))
        self.assertTrue(p["no_fetch"])
        self.assertIsNone(p["seen_alert"])

    def test_a_tracked_alert_link_is_never_opened(self):  # regression: a click tracker carried a sign-in token
        from pathlib import Path

        from lodestar import alerts

        raw = (Path(__file__).resolve().parent / "fixtures" / "alerts" / "ziprecruiter.eml").read_bytes()
        m = email.message_from_bytes(raw)
        with patched(alerts, notify=self.notes.append), contextlib.redirect_stdout(io.StringIO()):
            alerts.ingest("ziprecruiter", em._html(m), em._text(m), f"<{self.tag}@zip>", m["Date"])
        r = db.con().execute("SELECT rowid AS id, url FROM postings WHERE company='Ostrava Systems'").fetchone()
        self.assertEqual(r["url"], "https://click.zipmail.example/ls/click?upn=AbC123opaque")  # no otpToken stored
        with contextlib.redirect_stdout(io.StringIO()):
            jid = listings.track(r["id"])
        db.set_status(jid, "applied")
        indeed_mail = self.job(url="https://www.indeedemail.com/r/abc?jk=0a1b2c3d4e5f")  # an Indeed domain too
        self.check()
        self.assertEqual(self.fetched, [])
        self.assertTrue(wm.no_fetch(db.get_job(jid)["url"]) and wm.no_fetch(db.get_job(indeed_mail)["url"]))
        self.assertFalse(wm.no_fetch(self.URL))


def ats_mail(frm, subject, body, html="", dom=None, auth=True):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "pat.rivera@example.com", subject
    m["Message-ID"] = f"<{uuid.uuid4().hex}@ats.example>"
    m["Date"] = email.utils.format_datetime(datetime.now(timezone.utc))
    if auth:
        m["Authentication-Results"] = PASS.format(d=dom or frm.split("@")[1].rstrip(">"))
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


class Box:
    def __init__(self, msgs):
        self.msgs = msgs

    def login(self, *a):
        pass

    def select(self, *a, **k):
        pass

    def logout(self):
        pass

    def uid(self, op, *a):
        if op == "search":
            return "OK", [b" ".join(str(u).encode() for u in self.msgs)]
        return "OK", [(a[0], self.msgs[int(a[0])])]


class AtsMail(Base):
    def scan(self, raw, company, title, category="application_received"):
        def classify(subject, sender, body, provider=None):
            return {"category": category, "company": company, "title": title, "summary": "s", "action": "none", "deadline": None}

        self.uid = getattr(self, "uid", 0) + 1
        with patched(imaplib, IMAP4_SSL=lambda host, **kw: Box({self.uid: raw})), patched(em, classify=classify), \
                contextlib.redirect_stdout(io.StringIO()):
            em._scan("imap.example.com", "me@example.com", "p", 3, 50, False, None)
        return db.con().execute("SELECT * FROM mail ORDER BY id DESC LIMIT 1").fetchone()

    def test_greenhouse_link_files_it_under_the_right_job_never_trusted(self):
        co = f"Acme Widgets {self.tag}"
        a = db.add_job(co, "Data Engineer", "https://boards.greenhouse.io/acmewidgets/jobs/4012345")
        b = db.add_job(co, "Data Engineer, Platform", "https://boards.greenhouse.io/acmewidgets/jobs/4012399")
        settings.set_tool("email_classify", enabled=True, auto=True)  # auto: still waits, the tie is never strong
        raw = ats_mail("Acme Widgets <no-reply@us.greenhouse-mail.io>", "Thank you for applying to Acme Widgets",
                       "We received your application for Data Engineer, Platform.",
                       html='<p>Track it: <a href="https://boards.greenhouse.io/acmewidgets/jobs/4012399?gh_src=mail">'
                            "Data Engineer, Platform</a></p>")
        m = self.scan(raw, co, "Data Engineer")  # the classifier's title fits the other job: the link wins
        self.assertEqual((m["job_id"], m["link_reason"], m["trusted"], m["linked_by"]), (b, "ATS posting link 4012399", 0, "auto"))
        p = [x for x in db.list_pending("pending") if x["kind"] == "set_status"]
        self.assertEqual([(x["job_id"], json.loads(x["payload"])["status"]) for x in p], [(b, "applied")])
        self.assertEqual(db.get_job(b)["status"], "saved")
        self.assertEqual(db.get_job(a)["contact_email"], None)
        self.assertEqual(pipeline._confirm_observe(db.get_job(b), None)["via"], "listing")  # an authenticated ATS confirmation
        forged = ats_mail("Acme Widgets <no-reply@us.greenhouse-mail.io>", "Thank you for applying",
                          "Received: https://boards.greenhouse.io/acmewidgets/jobs/4012345", auth=False)
        m = self.scan(forged, co, "Data Engineer")
        self.assertEqual((m["job_id"], m["link_reason"]), (a, "ATS posting link 4012345 (sender not verified)"))
        self.assertIsNone(pipeline._confirm_observe(db.get_job(a), None))  # unverified: no confirmation fact

    def test_workday_tenant_and_title_overlap_ties(self):
        co = f"Bramblecrest {self.tag}"
        wd = db.add_job(co, "Analyst", "https://bramblecrest.wd5.myworkdayjobs.com/en-US/External/job/Remote/Analyst_R12345")
        db.add_job(co, "Office Manager", "https://bramblecrest.example/jobs/om")
        m = self.scan(ats_mail("Bramblecrest <bramblecrest@myworkday.com>", "Application received", "Thanks for applying."),
                      co, "Something else entirely")
        self.assertEqual((m["job_id"], m["link_reason"], m["trusted"]), (wd, "Workday tenant bramblecrest", 0))
        de = db.add_job(co, "Senior Data Engineer", "")
        m = self.scan(ats_mail("Bramblecrest <no-reply@hire.lever.co>", "Your application", "Thanks for applying."),
                      co, "Data Engineer (Senior)")
        self.assertEqual((m["job_id"], m["link_reason"]), (de, "company + title"))
        info = {"sender_email": "jane@bramblecrest.example", "company": co, "title": "Senior Data Engineer"}
        self.assertIsNone(em._ats_match(info, db.list_jobs()))  # not an ATS sender: the old rules decide


class Activity(Base):
    def test_activity_merges_events_and_mail_newest_first(self):
        jid = db.add_job(f"Larchmont {self.tag}", "Data Engineer", "https://careers.larchmont.example/jobs/1")
        for kind, detail, ts in (("posting_changed", "salary 'a' -> 'b'", "2026-11-03 10:00:00"),
                                 ("listing_seen", "in LinkedIn alert 2026-11-04: Data Engineer", "2026-11-04 10:00:00"),
                                 ("email", "application_received: Thanks", "2026-11-05 10:00:00"),
                                 ("note", "my own note", "2026-11-06 10:00:00")):
            db.con().execute("INSERT INTO events(job_id, kind, detail, ts) VALUES(?,?,?,?)", (jid, kind, detail, ts))
        db.con().execute("UPDATE events SET ts='2026-11-01 10:00:00' WHERE job_id=? AND kind='created'", (jid,))
        db.con().commit()
        db.add_mail(message_id="<a1@x>", job_id=jid, direction="in", from_addr="no-reply@greenhouse-mail.io",
                    subject="Thanks for applying", sent_at="2026-11-05 10:00:00", category="application_received",
                    trusted=False, linked_by="auto", link_reason="ATS posting link 1")
        db.add_mail(message_id="<a2@x>", job_id=jid, direction="out", to_addr="jane@larchmont.example",
                    subject="Following up", sent_at="2026-11-07 10:00:00", trusted=True, linked_by="auto")
        act = listings.activity(jid)
        self.assertEqual([(a["src"], a["kind"]) for a in act[:4]],
                         [("mail", ""), ("mail", "application_received"), ("alert", "listing_seen"), ("web", "posting_changed")])
        self.assertEqual((act[1]["dir"], act[1]["trusted"], act[1]["reason"]), ("in", False, "ATS posting link 1"))
        self.assertEqual(act[0]["dir"], "out")
        self.assertNotIn("email", [a["kind"] for a in act])  # the mail rows already cover it
        self.assertNotIn("note", [a["kind"] for a in act])
        self.assertEqual(act[-1]["kind"], "created")
        self.assertEqual(listings.posting_of(db.get_job(jid))["seen_alert"], "2026-11-04 10:00:00")

    def test_delete_job_clears_the_snapshot_and_the_posting_link(self):
        jid = db.add_job(f"Larchmont {self.tag}", "Data Engineer", "https://careers.larchmont.example/jobs/2")
        listings.store([{"title": "Data Engineer", "company": f"Larchmont {self.tag}", "url": "https://careers.larchmont.example/jobs/2"}],
                       source="capture", job_id=jid)
        SNAPSHOTS.mkdir(exist_ok=True)
        (SNAPSHOTS / f"job-{jid}.json").write_text("{}", encoding="utf-8")
        db.meta_set(f"pagemiss:{jid}", 1)
        db.delete_job(jid)
        self.assertFalse((SNAPSHOTS / f"job-{jid}.json").exists())
        self.assertEqual(db.meta_get(f"pagemiss:{jid}"), 0)
        self.assertIsNone(db.con().execute("SELECT job_id FROM postings WHERE company=?", (f"Larchmont {self.tag}",)).fetchone()[0])

    def test_job_route_carries_activity_and_posting_and_live_jd_needs_the_token(self):
        import http.client

        from lodestar import desktop

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database
        jid = db.add_job(f"Larchmont {self.tag}", "Data Engineer <b>x</b>", "https://www.linkedin.com/jobs/view/77/")
        db.add_event(jid, "listing_seen", "in LinkedIn alert 2026-11-04: <img src=x onerror=alert(1)>")
        port = desktop.free_port(8960)
        srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", f"/api/jobs/{jid}", None, h)
            r = c.getresponse(); d = json.loads(r.read().decode())
            self.assertEqual(r.status, 200, d)
            self.assertEqual(d["activity"][0]["text"], "in LinkedIn alert 2026-11-04: <img src=x onerror=alert(1)>")  # raw JSON
            self.assertTrue(d["posting"]["no_fetch"])
            c.request("POST", f"/api/jobs/{jid}/live_jd", "{}", {**h, "X-Lodestar-Token": "no"})
            r = c.getresponse(); r.read()
            self.assertEqual(r.status, 403)
            c.request("POST", f"/api/jobs/{jid}/live_jd", "{}", h)
            r = c.getresponse(); body = json.loads(r.read().decode())
            self.assertIn("no live description", body.get("error", ""))  # nothing read yet
            s = json.loads((c.request("GET", "/api/state", None, h), c.getresponse().read().decode())[1])
            self.assertEqual(set(s["alert_sites"]), {"linkedin", "indeed", "glassdoor", "ziprecruiter"})
            c.close()
        finally:
            srv.shutdown(); srv.server_close()
            db.delete_job(jid)
            db._local.con.close()
            db._local.con = saved


if __name__ == "__main__":
    unittest.main()
