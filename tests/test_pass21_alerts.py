"""Pass 21, builder 3: job-alert email ingestion. Hand-made fictional alert mails (tests/fixtures/alerts/*.eml:
LinkedIn, a reskinned LinkedIn, Indeed HTML and plain text, Glassdoor, ZipRecruiter behind opaque click trackers) are
parsed into All jobs; recognition needs an authenticated sender domain AND a known alert sender address (InMail and
'application submitted' mail from the same domains still reach the classifier); one notify per mail, never a link or
a sign-in token; judging runs after the IMAP logout; alert links are never fetched, alert mail is never classified
and never stored in the mail table. No network: imaplib, util.fetch and the AI are faked, and everything patched is
put back."""
import contextlib
import email
import imaplib
import io
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, alerts, cli, db, email_monitor as em, settings, util, web_monitor as wm  # noqa: E402
from lodestar.config import ALERTS  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "alerts"
SECRETS = ("OTPSECRET42", "MIDSECRET42", "SIGSECRET42", "ZIPSECRET77")
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


def fixture(name: str) -> bytes:
    return (FIX / f"{name}.eml").read_bytes()


def msg(name: str, **headers) -> bytes:
    """A fixture with some headers replaced (a fresh Message-ID unless one is given)."""
    m = email.message_from_bytes(fixture(name))
    headers.setdefault("Message_ID", f"<{uuid.uuid4().hex}@fixture>")
    for k, v in headers.items():
        del m[k.replace("_", "-")]
        if v is not None:
            m[k.replace("_", "-")] = v
    return m.as_bytes()


def plain(frm: str, subject: str, body: str, dom: str) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "pat.rivera@example.com", subject
    m["Message-ID"] = f"<{uuid.uuid4().hex}@{dom}>"
    m["Date"] = email.utils.format_datetime(datetime.now(timezone.utc))
    m["Authentication-Results"] = PASS.format(d=dom)
    m.set_content(body)
    return m.as_bytes()


class Box:
    """A fake IMAP mailbox: every call is logged, so the order of logout and judging can be checked."""

    def __init__(self, msgs, log):
        self.msgs, self.log = msgs, log

    def login(self, *a):
        pass

    def select(self, *a, **k):
        pass

    def logout(self):
        self.log.append("logout")

    def uid(self, op, *a):
        if op == "search":
            return "OK", [b" ".join(str(u).encode() for u in self.msgs)]
        return "OK", [(a[0], self.msgs[int(a[0])])]


def no_fetch(*a, **k):
    raise AssertionError(f"alert links are never fetched: {a[:1]}")


def no_ai(*a, **k):
    raise AssertionError("an alert mail is never sent to the AI")


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = settings.PATH.read_bytes() if settings.PATH.is_file() else None
        settings.PATH.unlink(missing_ok=True)
        for t in ("email_reply", "interview_scheduling", "calendar", "auto_track"):
            settings.set_tool(t, enabled=False)
        self.notes, self.log, self.uid, self.classified = [], [], 0, []
        self.real = (alerts.notify, em.notify, wm.notify, wm.fetch, wm.fetch_json, util.fetch, ai.ask_json)
        alerts.notify = em.notify = wm.notify = self.notes.append
        wm.fetch = wm.fetch_json = util.fetch = no_fetch
        ai.ask_json = no_ai

    def tearDown(self):
        alerts.notify, em.notify, wm.notify, wm.fetch, wm.fetch_json, util.fetch, ai.ask_json = self.real
        db._local.con.close()
        db._local.con = self._con
        settings.PATH.write_bytes(self.snap) if self.snap is not None else settings.PATH.unlink(missing_ok=True)

    def scan(self, raws, category="other", company="", title=""):
        def classify(subject, sender, body, provider=None):
            self.classified.append(sender)
            return {"category": category, "company": company, "title": title, "summary": "s", "action": "none",
                    "deadline": None}

        box = Box({self.uid + i + 1: r for i, r in enumerate(raws)}, self.log)  # new UIDs: a seen one is skipped
        self.uid += len(raws)
        with patched(imaplib, IMAP4_SSL=lambda host, **kw: box), patched(em, classify=classify), \
                contextlib.redirect_stdout(io.StringIO()):
            return em._scan("imap.example.com", "me@example.com", "p", 3, 50, False, None)

    def postings(self):
        return db.con().execute("SELECT * FROM postings WHERE title IS NOT NULL ORDER BY rowid").fetchall()


class Parse(Base):
    def rows(self, name):
        r = alerts.parse_file(fixture(name))
        self.assertTrue(r["authenticated"])
        return r["site"], r["rows"]

    def test_each_site_reads_title_company_place_pay_and_a_canonical_url(self):
        site, rows = self.rows("linkedin")
        self.assertEqual(site, "linkedin")
        self.assertEqual([(r["title"], r["company"], r["location"], r["salary"]) for r in rows],
                         [("Data Engineer", "Quillfeather Labs", "Austin, TX (Hybrid)", "$120,000 - $140,000"),
                          ("Senior Analytics Engineer", "Bramblecrest", "Remote (United States)", ""),
                          ("Platform Engineer", "Marrowgate", "Berlin, Germany", "")])
        self.assertEqual(rows[0]["url"], "https://www.linkedin.com/jobs/view/4012345678/")  # tokens and trackers gone
        self.assertEqual(rows[0]["date"], "2026-11-07")  # '3 days ago' from the mail's own date
        self.assertEqual(rows[0]["source"], "linkedin_alert")
        site, rows = self.rows("indeed")  # Indeed's click redirector unwrapped offline (url=)
        self.assertEqual([(r["title"], r["company"], r["location"], r["url"]) for r in rows],
                         [("Analytics Engineer", "Bramblecrest", "Denver, CO", "https://www.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b"),
                          ("Data Engineer II", "Fernwood Analytics", "Remote", "https://www.indeed.com/viewjob?jk=1b2c3d4e5f6a7b8c")])
        self.assertEqual(rows[0]["salary"], "$95,000 - $110,000")
        site, rows = self.rows("glassdoor")
        self.assertEqual([(r["title"], r["company"], r["location"], r["salary"]) for r in rows],
                         [("Senior Data Engineer", "Larchmont Data", "Chicago, IL", "$130K - $160K"),
                          ("Data Analyst", "Thistledown Co", "Remote", "")])
        self.assertIn("jobListingId=1009876543", rows[0]["url"])
        self.assertNotIn("utm_source", rows[0]["url"])
        self.assertTrue(all(r["url"].startswith("https://") for r in rows))

    def test_reskinned_linkedin_reads_the_same_rows(self):
        keep = ("title", "company", "location", "salary", "url", "date")
        a = [{k: r[k] for k in keep} for r in self.rows("linkedin")[1]]
        b = [{k: r[k] for k in keep} for r in self.rows("linkedin_reskinned")[1]]
        self.assertEqual(len(a), 3)
        self.assertEqual(a, b)

    def test_plain_text_alert_and_opaque_trackers_fall_back(self):
        site, rows = self.rows("indeed_plain")
        self.assertEqual([(r["title"], r["company"], r["location"], r["url"]) for r in rows],
                         [("Data Engineer", "Fernwood Analytics", "Remote", "https://www.indeed.com/viewjob?jk=1a2b3c4d5e6f7a8b"),
                          ("Senior Data Engineer", "Larchmont Data", "Chicago, IL", "https://www.indeed.com/viewjob?jk=9f8e7d6c5b4a3f2e")])
        site, rows = self.rows("ziprecruiter")  # no job-id link at all: grouped by anchor text, links minus tokens
        self.assertEqual([(r["title"], r["company"], r["location"]) for r in rows],
                         [("Data Platform Engineer", "Ostrava Systems", "Lisbon, Portugal"),
                          ("Site Reliability Engineer", "Thistledown Co", "Remote")])
        self.assertEqual(rows[0]["url"], "https://click.zipmail.example/ls/click?upn=AbC123opaque")  # sign-in token gone
        self.assertEqual(alerts.parse("linkedin", "<a href='http://www.linkedin.com/jobs/view/1/'>Data Engineer</a>"
                                      "<div>Acme</div>", "")[0]["url"], "https://www.linkedin.com/jobs/view/1/")
        self.assertEqual(alerts.parse("ziprecruiter", "<a href='http://t.example/c?x=1'>Data Engineer</a><div>Acme</div>")[0]["url"],
                         "")  # only https links are kept
        many = "".join(f"<a href='https://www.linkedin.com/jobs/view/{i}/'>Engineer {i}</a><div>Acme</div>" for i in range(80))
        self.assertEqual(len(alerts.parse("linkedin", many)), alerts.MAX_ROWS)

    def test_recognition_needs_an_alert_sender_on_the_real_domain(self):
        for addr, want in (("jobalerts-noreply@linkedin.com", "linkedin"), ("JobAlerts-NoReply+x@LinkedIn.com", "linkedin"),
                           ("jobs-listings@e.linkedin.com", "linkedin"), ("alert@indeed.com", "indeed"),
                           ("alert@indeedemail.com", "indeed"), ("noreply@glassdoor.co.uk", "glassdoor"),
                           ("alerts@ziprecruiter.com", "ziprecruiter"),
                           ("inmail-hit-reply@linkedin.com", None), ("indeedapply@indeed.com", None),
                           ("jobalerts-noreply@linkedin-jobs.com", None), ("jobalerts-noreply@linkedin.com.evil.net", None),
                           ("alert@notindeed.com", None), ("", None)):
            self.assertEqual(alerts.site_of(addr), want, addr)
        failed = msg("linkedin", Authentication_Results="mx.example.net; dkim=fail header.d=linkedin.com; dmarc=fail")
        r = alerts.parse_file(failed)
        self.assertEqual((r["site"], r["authenticated"], r["rows"]), ("linkedin", False, []))
        self.assertEqual(len(alerts.parse_file(failed, trust=True)["rows"]), 3)  # --trust: a saved file's headers
        look = msg("linkedin", From="LinkedIn <jobalerts-noreply@linkedin-jobs.com>",
                   Authentication_Results=PASS.format(d="linkedin-jobs.com"))
        self.assertEqual((alerts.parse_file(look)["site"], alerts.parse_file(look)["rows"]), (None, []))


class Scan(Base):
    def test_alerts_go_to_all_jobs_with_no_ai_no_fetch_and_no_mail_row(self):
        found = self.scan([msg("linkedin"), msg("indeed")])
        self.assertEqual((list(found), found.alerts), ([], 5))  # Check email names the 5 new alert listings
        rows = self.postings()
        self.assertEqual(len(rows), 5)
        self.assertEqual({r["sources"] for r in rows}, {'["linkedin_alert"]', '["indeed_alert"]'})
        self.assertEqual(self.classified, [])  # never classified (ai.ask_json raises; classify is not even asked)
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM mail").fetchone()[0], 0)  # nothing in Unmatched mail
        self.assertTrue(db.seen("email:me@example.com:1") and db.seen("email:me@example.com:2"))
        self.assertEqual(db.meta_get("alerts:linkedin:n"), 3)
        self.assertGreater(db.meta_get("alerts:linkedin:last"), 0)
        # the same posting in another alert merges into the same row (Bramblecrest at another place stays its own)
        self.scan([msg("linkedin_reskinned")])
        self.assertEqual(len(self.postings()), 5)
        self.assertEqual(db.con().execute("SELECT seen_count FROM postings WHERE company='Quillfeather Labs'").fetchone()[0], 2)

    def test_one_notify_per_mail_and_never_a_link_or_token(self):
        sent = []
        os.environ["LODESTAR_NOTIFY_EMAIL"] = "pat.rivera@example.com"
        try:
            with patched(alerts, notify=util.notify), patched(util, send_email=lambda *a, **k: sent.append(a)), \
                    contextlib.redirect_stdout(io.StringIO()):
                before = ALERTS.read_text(encoding="utf-8") if ALERTS.is_file() else ""
                self.scan([msg("linkedin"), msg("ziprecruiter")])
                logged = (ALERTS.read_text(encoding="utf-8") if ALERTS.is_file() else "")[len(before):]
        finally:
            os.environ.pop("LODESTAR_NOTIFY_EMAIL", None)
        self.assertEqual(len(sent), 2)  # one self-mail per alert mail, not one per listing
        self.assertIn("LinkedIn alert: 3 jobs (3 new)", logged)
        self.assertIn("ZipRecruiter alert: 2 jobs (2 new)", logged)
        for s in SECRETS + ("http",):
            self.assertNotIn(s, logged)
            self.assertNotIn(s, repr(sent))
        stored = db.con().execute("SELECT url FROM postings WHERE company='Ostrava Systems'").fetchone()[0]
        self.assertEqual(stored, "https://click.zipmail.example/ls/click?upn=AbC123opaque")  # the sign-in token is never stored
        self.assertTrue(wm.no_fetch(stored))  # and the tracker's host is never opened

    def test_judging_runs_after_the_mailbox_is_closed(self):
        judged = []
        with patched(wm, _hits=lambda label, rows, quiet=False: (self.log.append("judge"), judged.append((label, quiet, len(rows))))):
            self.scan([msg("glassdoor")])
        self.assertEqual(self.log, ["logout", "judge"])
        self.assertEqual(judged, [("job alerts", True, 2)])
        self.scan([msg("glassdoor")])  # nothing new: nothing to judge
        self.assertEqual(self.log, ["logout", "judge", "logout"])

    def test_a_tracked_job_seen_again_gets_one_event_per_message(self):
        jid = db.add_job("Quillfeather Labs", "Data Engineer", "https://www.linkedin.com/jobs/view/4012345678/")
        mail = msg("linkedin", Message_ID="<same-alert@linkedin.com>")
        self.scan([mail])
        self.scan([mail])  # the same Message-ID again (another UID): no second event
        ev = [e for e in db.events(jid) if e["kind"] == "listing_seen"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["detail"], "in LinkedIn alert 2026-11-10: Data Engineer")
        self.assertEqual(db.con().execute("SELECT job_id FROM postings WHERE company='Quillfeather Labs'").fetchone()[0], jid)
        self.scan([msg("linkedin")])
        self.assertEqual(len([e for e in db.events(jid) if e["kind"] == "listing_seen"]), 2)

    def test_inmail_and_application_submitted_still_reach_the_classifier(self):  # regression guard
        jid = db.add_job("Fernwood Analytics", "Data Engineer II", "https://www.indeed.com/viewjob?jk=1b2c3d4e5f6a7b8c")
        inmail = plain("Sam Okafor via LinkedIn <inmail-hit-reply@linkedin.com>", "New opportunity: Data Engineer",
                       "Hi Pat, I am recruiting for a data engineer role at Quillfeather Labs.", "linkedin.com")
        self.scan([inmail], category="recruiter_outreach", company="Quillfeather Labs", title="Data Engineer")
        applied = plain("Indeed Apply <indeedapply@indeed.com>", "Application submitted: Data Engineer II",
                        "Your application to Fernwood Analytics was submitted. Thank you for applying.", "indeed.com")
        self.scan([applied], category="application_received", company="Fernwood Analytics", title="Data Engineer II")
        self.assertEqual(self.classified, ["Sam Okafor via LinkedIn <inmail-hit-reply@linkedin.com>",
                                           "Indeed Apply <indeedapply@indeed.com>"])
        self.assertEqual(self.postings(), [])  # neither one was read as an alert
        cats = [r["category"] for r in db.con().execute("SELECT category FROM mail ORDER BY id")]
        self.assertEqual(cats, ["recruiter_outreach", "application_received"])
        kinds = {(p["kind"], p["job_id"]) for p in db.list_pending("pending")}
        self.assertIn(("add_job", None), kinds)  # the recruiter's role waits in the Inbox, as before
        self.assertIn(("set_status", jid), kinds)  # 'application received' still proposes Applied

    def test_linkedin_application_sent_mail_reaches_the_classifier(self):  # regression: jobs-noreply is not an alert
        self.assertIsNone(alerts.site_of("jobs-noreply@linkedin.com"))
        jid = db.add_job("Fernwood Analytics", "Data Engineer", "https://www.linkedin.com/jobs/view/4099999999/")
        sent = plain("LinkedIn <jobs-noreply@linkedin.com>", "Pat, your application was sent to Fernwood Analytics",
                     "Your application was sent to Fernwood Analytics.\nData Engineer\n"
                     "https://www.linkedin.com/comm/jobs/view/4099999999/", "linkedin.com")
        self.scan([sent], category="application_received", company="Fernwood Analytics", title="Data Engineer")
        self.assertEqual(self.classified, ["LinkedIn <jobs-noreply@linkedin.com>"])
        self.assertEqual(self.postings(), [])  # not a listing in All jobs
        self.assertIn(("set_status", jid), {(p["kind"], p["job_id"]) for p in db.list_pending("pending")})

    def test_tool_switches(self):
        settings.set_tool("job_alerts", enabled=False)  # off: an alert mail is ordinary mail again (as before pass 21)
        self.scan([msg("linkedin")])
        self.scan([msg("linkedin", Subject="Data Engineer role at Quillfeather Labs")])  # 'role': a hiring hint
        self.assertEqual((len(self.classified), self.postings()), (1, []))
        settings.set_tool("job_alerts", enabled=True)
        settings.set_tool("email_classify", enabled=False)  # alerts only: other mail stays unseen, never classified
        n = self.uid
        self.scan([msg("indeed"), plain("Jane <jane@acme.example>", "Interview", "Interview next week?", "acme.example")])
        self.assertEqual(len(self.classified), 1)
        self.assertEqual(len(self.postings()), 2)
        self.assertTrue(db.seen(f"email:me@example.com:{n + 1}"))
        self.assertFalse(db.seen(f"email:me@example.com:{n + 2}"))
        settings.set_tool("job_alerts", enabled=False)
        with self.assertRaises(SystemExit):
            em.check()
        settings.set_tool("email_classify", enabled=True)
        settings.set_tool("job_alerts", enabled=True)

    def test_an_unreadable_alert_notifies_once_a_day_and_is_marked_seen(self):
        empty = plain("LinkedIn <jobalerts-noreply@linkedin.com>", "Your job alert", "Nothing we can read here.", "linkedin.com")
        self.scan([empty])
        self.scan([plain("LinkedIn <jobalerts-noreply@linkedin.com>", "Your job alert", "Still nothing.", "linkedin.com")])
        fails = [n for n in self.notes if "could not be read" in n]
        self.assertEqual(len(fails), 1)
        self.assertIn("lodestar email parse-alert", fails[0])
        self.assertTrue(db.seen("email:me@example.com:1"))
        self.assertEqual(self.classified, [])

    def test_parse_alert_cli_prints_rows_and_changes_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["email", "parse-alert", str(FIX / "linkedin.eml")])
        text = out.getvalue()
        self.assertIn("local part 'jobalerts-noreply'", text)
        self.assertIn("Data Engineer @ Quillfeather Labs | Austin, TX (Hybrid) | $120,000 - $140,000", text)
        self.assertIn("3 job(s) read", text)
        self.assertEqual(self.postings(), [])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["email", "parse-alert", str(FIX / "indeed.eml")])
        self.assertIn("https://www.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b", out.getvalue())


if __name__ == "__main__":
    unittest.main()
