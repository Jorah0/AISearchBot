"""Pass 15, group A: tracker fields, backfill, filters/sort, Today agenda, desktop notifications, offline templates."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, db, loop, resume, settings, util, web_monitor  # noqa: E402
from lodestar.cli import build  # noqa: E402


class MemDb(unittest.TestCase):
    """Each test gets its own in-memory database; the shared thread connection is put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con


class Fields(MemDb):
    def test_set_fields_validates_and_clears(self):
        jid = db.add_job("Acme", "Engineer")
        db.set_fields(jid, remote="Hybrid", salary_min="120k", salary_max=150000, currency="usd", deadline="2026-12-01",
                      excitement=4, tags="python, remote ,python", match_score=82, next_action="ask Sam", next_action_at="2026-11-07")
        j = db.get_job(jid)
        self.assertEqual((j["remote"], j["salary_min"], j["salary_max"], j["currency"]), ("hybrid", 120000, 150000, "USD"))
        self.assertEqual((j["tags"], j["excitement"], j["match_score"], j["deadline"]), ("python,remote", 4, 82, "2026-12-01"))
        for bad in ({"remote": "mars"}, {"excitement": 6}, {"match_score": -1}, {"deadline": "12/01/2026"}, {"deadline": "2026-1-5"},
                    {"deadline": "2026-02-30"}, {"currency": "dollars"}, {"salary_min": 200000}, {"nope": 1}, {"location": "x" * 121}):
            with self.assertRaises(SystemExit, msg=bad):
                db.set_fields(jid, **bad)
        self.assertEqual(db.get_job(jid)["remote"], "hybrid")  # a rejected write changed nothing
        db.set_fields(jid, deadline="", tags="")
        self.assertIsNone(db.get_job(jid)["deadline"]); self.assertIsNone(db.get_job(jid)["tags"])
        with self.assertRaises(SystemExit):
            db.set_fields(99999, remote="remote")

    def test_add_job_fills_fields_from_the_listing(self):
        jid = db.add_job("Acme", "Eng", "https://a/1", "Salary (from remoteok): 120000-160000\n\nWork from anywhere.",
                         "found via remoteok", location="Worldwide", posted_at="2026-11-01")
        j = db.get_job(jid)
        self.assertEqual((j["salary_min"], j["salary_max"], j["source"], j["remote"]), (120000, 160000, "search:remoteok", "remote"))
        self.assertEqual((j["location"], j["posted_at"]), ("Worldwide", "2026-11-01"))
        cap = db.get_job(db.add_job("Globex", "Ops", None, "Hybrid role in Berlin. Pay: €70k - €85k", "captured from https://x"))
        self.assertEqual((cap["source"], cap["remote"], cap["salary_min"], cap["salary_max"], cap["currency"]), ("captured", "hybrid", 70000, 85000, "EUR"))
        bare = db.get_job(db.add_job("Initech", "Dev"))
        self.assertEqual((bare["source"], bare["remote"], bare["salary_min"]), ("manual", None, None))
        before = len(db.list_jobs())
        with self.assertRaises(SystemExit):  # validated before the insert: nothing is added
            db.add_job("Bad", "Date", posted_at="yesterday")
        self.assertEqual(len(db.list_jobs()), before)
        self.assertEqual(web_monitor.listing_fields({"location": "  Remote,\n EU ", "date": "2026-13-40"}), {"location": "Remote, EU", "posted_at": ""})

    def test_parse_salary(self):
        self.assertEqual(resume.parse_salary("Pay: $140,000 - $170,000 plus equity"), {"salary_min": 140000, "salary_max": 170000, "currency": "USD"})
        self.assertEqual(resume.parse_salary("CAD $90k-$110k"), {"salary_min": 90000, "salary_max": 110000, "currency": "CAD"})
        self.assertEqual(resume.parse_salary("$50 - $70 an hour"), {})
        self.assertEqual(resume.parse_salary("no pay"), {})

    def test_backfill_only_fills_nulls_and_keeps_updated_at(self):
        c = db._local.con
        c.execute("INSERT INTO jobs(company,title,jd,notes,updated_at) VALUES('Old','Eng','Salary: $100k-$120k, remote','found via remotive','2020-01-01 00:00:00')")
        c.execute("INSERT INTO jobs(company,title,jd,notes,remote) VALUES('Kept','Eng','fully remote','captured from x','onsite')")
        c.execute("DELETE FROM seen WHERE key=?", (db.BACKFILL_KEY,)); c.commit()
        self.assertEqual(db.backfill(c), 2)
        old, kept = (c.execute("SELECT * FROM jobs WHERE company=?", (n,)).fetchone() for n in ("Old", "Kept"))
        self.assertEqual((old["salary_min"], old["salary_max"], old["source"], old["remote"]), (100000, 120000, "search:remotive", "remote"))
        self.assertEqual(old["updated_at"], "2020-01-01 00:00:00")
        self.assertEqual((kept["remote"], kept["source"]), ("onsite", "captured"))  # a value already there is never replaced
        self.assertEqual(db.backfill(c), 0)  # marker: the scan runs once
        c.execute("DELETE FROM seen WHERE key=?", (db.BACKFILL_KEY,)); c.commit()
        db.backfill(c)  # a forced rerun changes nothing
        self.assertEqual(dict(c.execute("SELECT * FROM jobs WHERE company='Old'").fetchone()), dict(old))

    def test_list_jobs_filters_and_sorts(self):
        a, b, c = (db.add_job(n, "Eng") for n in ("A", "B", "C"))
        db.set_fields(a, salary_min=90000, salary_max=100000, match_score=60, excitement=2, remote="remote", tags="Python")
        db.set_fields(b, salary_min=150000, match_score=90, deadline="2026-12-01", remote="onsite")
        db.set_fields(c, excitement=5, deadline="2026-11-20", tags="go,python")
        ids = lambda **kw: [j["id"] for j in db.list_jobs(**kw)]
        self.assertEqual(ids(sort="match")[:2], [b, a])
        self.assertEqual(ids(sort="salary"), [b, a, c])
        self.assertEqual(ids(sort="excitement")[:2], [c, a])
        self.assertEqual(ids(sort="deadline"), [c, b, a])
        self.assertEqual(ids(remote="remote"), [a])
        self.assertEqual(sorted(ids(min_salary=120000)), sorted([b, c]))  # c has no pay: kept (marked), as search does
        self.assertEqual(sorted(ids(tag="python")), sorted([a, c]))

    def test_funnel_reads_the_source_column(self):
        jid = db.add_job("Acme", "Eng", notes="found via remotive")
        db.set_fields(jid, source="referral")
        self.assertIn("referral", db.funnel()["by_source"])


class Today(MemDb):
    def test_agenda(self):
        now = datetime(2026, 11, 6, 9, 0)
        due = db.add_job("Due", "Eng"); late = db.add_job("Late", "Eng"); later = db.add_job("Later", "Eng")
        dl = db.add_job("Deadline", "Eng"); far = db.add_job("Far", "Eng"); closed = db.add_job("Closed", "Eng")
        db.set_fields(due, next_action="call Sam", next_action_at="2026-11-06")
        db.set_fields(late, next_action_at="2026-11-01"); db.set_fields(later, next_action_at="2026-11-09")
        db.set_fields(dl, deadline="2026-11-08"); db.set_fields(far, deadline="2026-11-12")
        db.set_fields(closed, deadline="2026-11-07", next_action_at="2026-11-01"); db.set_status(closed, "rejected")
        db.add_pending("followup", "note", None, "x", "{}")
        ag = loop.agenda(now)
        self.assertEqual([(i["id"], i["overdue"]) for i in ag["actions"]], [(late, True), (due, False)])
        self.assertEqual(ag["actions"][1]["what"], "call Sam")
        self.assertEqual([(i["id"], i["days"]) for i in ag["deadlines"]], [(dl, 2)])
        self.assertEqual((ag["pending"], ag["followups"], ag["interviews"]), (1, [], []))


class Notifications(MemDb):
    def test_desktop_notify_never_raises(self):
        import subprocess
        real = subprocess.run
        subprocess.run = lambda *a, **k: (_ for _ in ()).throw(OSError("no shell"))
        try:
            self.assertFalse(util.desktop_notify("t", "b"))
        finally:
            subprocess.run = real

    def test_loop_toasts_once_and_only_when_opted_in(self):
        from lodestar import extras
        sent, real_notify, real_pref = [], loop.desktop_notify, settings.pref("desktop_notifications")
        loop.desktop_notify = lambda t, b: sent.append((t, b)) or True
        try:
            now = datetime.now()
            jid = db.add_job("Acme", "Eng")
            db.set_fields(jid, deadline=f"{now + timedelta(days=1):%Y-%m-%d}")
            soon = now + timedelta(minutes=50)
            db.add_event(jid, "calendar", f"/x/interview-{soon:%Y%m%d-%H%M}.ics")
            settings.set_pref("desktop_notifications", False)
            loop._desktop(now)
            self.assertEqual(sent, [])  # default off: nothing
            settings.set_pref("desktop_notifications", True)
            loop._desktop(now); loop._desktop(now)
            titles = sorted(t for t, _ in sent)
            self.assertEqual(titles, sorted(["Lodestar: today", f"Interview at {soon:%H:%M}", "Deadline tomorrow"]))
            self.assertTrue(extras.upcoming_interviews(1))
        finally:
            loop.desktop_notify = real_notify
            settings.set_pref("desktop_notifications", real_pref)


class Templates(MemDb):
    def test_offline_drafts_go_through_the_inbox_without_the_floor(self):
        from lodestar import approvals
        real_avail, real_json, real_name = ai.available, ai.ask_json, settings.pref("name")
        real_auto = settings.load()["tools"]["email_reply"]["auto"]
        ai.ask_json = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no AI call expected"))
        try:
            settings.set_pref("name", "Jane Doe")
            settings.set_tool("email_reply", auto=True)  # a requested withdrawal still waits for review
            jid = db.add_job("Acme", "Backend Engineer")
            db.update_job(jid, contact_email="sam@acme.com", contact_name="Sam")
            ai.available = lambda: []
            r = apply.followup(db.get_job(jid))
            self.assertIn("Backend Engineer", r["draft"]["body"]); self.assertIn("Acme", r["draft"]["body"])
            self.assertTrue(r["draft"]["body"].startswith("Hello Sam,")); self.assertTrue(r["draft"]["body"].endswith("Jane Doe"))
            self.assertEqual(r["proposal"]["status"], "pending")
            ai.available = real_avail  # a provider is configured, but the template was asked for
            t = apply.thanks(db.get_job(jid), "Kim", "the data platform", template=True)["draft"]
            self.assertIn("Hello Kim,", t["body"]); self.assertIn("the data platform", t["body"])
            w = apply.withdraw(db.get_job(jid), template=True)
            self.assertEqual(w["proposal"]["status"], "pending")
            payload = json.loads(db.get_pending(w["proposal"]["id"])["payload"])
            self.assertEqual((payload["to"], payload["new_status"]), ("sam@acme.com", "withdrawn"))
            for d in (r["draft"], t, w["draft"]):
                self.assertNotRegex(d["body"], r"\d{2,3},?\d{3}|salary|floor")
            sent = []
            real_send = approvals.send_email
            approvals.send_email = lambda *a, **k: sent.append(a)
            try:
                approvals.approve(w["proposal"]["id"])
            finally:
                approvals.send_email = real_send
            self.assertEqual(db.get_job(jid)["status"], "withdrawn")  # sending the withdrawal closes the job
            db.update_job(jid, contact_email=None)
            self.assertEqual(apply.followup(db.get_job(jid), template=True)["proposal"]["status"], "draft_only")
        finally:
            ai.available, ai.ask_json = real_avail, real_json
            settings.set_pref("name", real_name or "")
            settings.set_tool("email_reply", auto=real_auto)


class Cli(MemDb):
    def test_jobs_set_list_and_today(self):
        import contextlib
        import io
        jid = db.add_job("Acme", "Eng")
        out = io.StringIO()
        def run(*argv):
            a = build().parse_args(list(argv))
            a.f(a)

        with contextlib.redirect_stdout(out):
            run("jobs", "set", str(jid), "deadline=2026-12-01", "tags=a,b", "excitement=3")
            run("jobs", "list", "--sort", "deadline", "--tag", "b", "--min-salary", "0")
            run("today")
        text = out.getvalue()
        self.assertIn("due 2026-12-01", text); self.assertIn("[a,b]", text); self.assertIn("Inbox: 0 waiting", text)
        with self.assertRaises(SystemExit):
            run("jobs", "set", str(jid), "deadline")
        self.assertTrue(build().parse_args(["withdraw", "3", "--template"]).template)
        self.assertTrue(build().parse_args(["followup", "3", "--template"]).template)


class WebFields(unittest.TestCase):
    def test_fields_route_and_state_today(self):
        import http.client
        from lodestar import desktop, web
        old = getattr(db._local, "con", None)
        port = desktop.free_port(8910); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def call(path, body=None, headers=h):
                c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse()
                return r.status, json.loads(r.read())

            st, r = call("/api/jobs", {"company": "Acme", "title": "Eng", "url": "https://acme.example/j/15", "jd": "Remote. $100k-$130k",
                                       "notes": "found via remotive", "location": "EU", "posted_at": "not a date"})
            self.assertEqual(st, 200, r); jid = r["id"]
            self.assertEqual(call(f"/api/jobs/{jid}/fields", {"deadline": "2026-12-01", "excitement": "5"})[0], 200)
            st, r = call(f"/api/jobs/{jid}/fields", {"excitement": "9"}); self.assertEqual(st, 400); self.assertIn("excitement", r["error"])
            st, r = call(f"/api/jobs/{jid}/fields", {"resume_hash": "x"}); self.assertEqual(st, 400)  # not user-settable
            self.assertEqual(call(f"/api/jobs/{jid}/fields", {"deadline": "1"}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            j = call(f"/api/jobs/{jid}")[1]["job"]
            self.assertEqual((j["deadline"], j["excitement"], j["location"], j["posted_at"], j["salary_max"], j["remote"]),
                             ("2026-12-01", 5, "EU", None, 130000, "remote"))
            state = call("/api/state")[1]
            self.assertEqual(set(state["today"]), {"actions", "deadlines", "followups", "interviews", "contacts", "emails", "pending"})
            self.assertIn("desktop_notifications", state["prefs"])
            call(f"/api/jobs/{jid}/delete", {})
        finally:
            srv.shutdown()
            db._local.con = old


if __name__ == "__main__":
    unittest.main()
