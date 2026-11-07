"""Pass 16 audit, fixer A (security and data integrity): lookalike mail domains, private Preferences under any heading,
idea markup, research/scheduling prompts, .ics escaping, zip and fetch caps, DNS rebinding, database locks after a
failed write, stale status proposals, job id reuse, closed jobs' interviews, the .ics import race, failed sends kept
for a retry, mail socket timeouts. No network: mail, AI and DNS are faked; every patched attribute is put back."""
import http.server
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, approvals, contacts, db, email_monitor as em, extras, ideas, interview, profile, settings, util  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

REAL = "# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"
APP_JS = Path(__file__).resolve().parent.parent / "lodestar" / "static" / "app.js"


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


class FileDb(Base):
    """An on-disk database, so a second connection can see the first one's locks."""

    def setUp(self):
        super().setUp()
        db._local.con.close()
        self.path = str(Path(tempfile.mkdtemp(prefix="lodestar-p16-")) / "t.db")
        db._local.con = db.connect(self.path)

    def other(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=0.3)


# ----------------------------------------------------------------------------- security
class MailDomains(Base):
    def test_lookalike_domains_never_tie_mail_to_a_company(self):  # security-mail-lookalike-domain-trusted
        jid = db.add_job("Globex Corporation", "Engineer", "https://careers.globex.com/jobs/1")
        db.set_status(jid, "applied")
        for addr in ("r@globex.attacker.net", "r@globex-hiring.com", "r@mail.globex.evil.co.uk", "r@notglobex.com"):
            job, strong = em._match({"sender_email": addr, "company": "Globex"})
            self.assertFalse(strong, addr)
        for addr in ("r@globex.com", "r@careers.globex.com", "r@mail.globex.com"):  # the posting URL's own domain
            job, strong = em._match({"sender_email": addr, "company": ""})
            self.assertEqual((job and job["id"], strong), (jid, True), addr)
        for addr in ("r@globex.co.uk", "r@GLOBEX.com.au", "r@globex.xyz"):  # names Globex, other suffix: filed, weakly
            job, strong = em._match({"sender_email": addr, "company": ""})
            self.assertEqual((job and job["id"], strong), (jid, False), addr)
        self.assertTrue(em.names_company("acme-robotics.com", "Acme Robotics"))
        self.assertFalse(em.names_company("acme.com", "Acme Robotics"))
        self.assertEqual((em.org_label("a.b.globex.co.uk"), em.registrable("a.b.globex.co.uk")), ("globex", "globex.co.uk"))

    def test_a_new_job_from_a_lookalike_domain_is_not_trusted(self):
        sent = []
        real = (approvals.propose, em.notify)
        approvals.propose = lambda *a, **k: sent.append(k.get("force_pending")) or {"status": "pending"}
        em.notify = lambda *a: None
        try:
            for addr, want in (("r@globex-hiring.com", True), ("r@globex.com", True)):  # an untracked company: never trusted
                em._apply({"category": "recruiter_outreach", "company": "Globex", "title": "Eng", "sender_email": addr,
                           "from": addr, "subject": "s", "summary": "", "dkim_pass": True}, dry=False)
                self.assertEqual(sent[-1], want, addr)  # force_pending: the lookalike waits for review
        finally:
            approvals.propose, em.notify = real


class PrivatePrefs(Base):
    def test_any_preferences_heading_stays_private(self):  # security-prefs-heading-variants-leak-floor
        for head in ("## Job Preferences", "### my preferences", "**Preferences**", "**Job preferences:**", "Preferences:",
                     "My job preferences:"):
            PROFILE.write_text(REAL + f"\n{head}\nSalary floor: $187,000 | Visa: needs H-1B transfer\n\n## Education\nBSc\n",
                               encoding="utf-8")
            text = profile.candidate_text(private=False)
            self.assertNotIn("187", text, head)
            self.assertNotIn("H-1B", text, head)
            self.assertIn("BSc", text, head)                                   # the section ends at the next heading
            self.assertEqual(profile.salary_floor(), 187000, head)             # and is still read as Preferences

    def test_floor_outside_preferences_is_refused_for_employers(self):
        PROFILE.write_text(REAL + "\n## Summary\nSalary floor: $187,000\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as e:
            profile.candidate_text(private=False)
        self.assertIn("Preferences", str(e.exception))
        self.assertIn("187", profile.candidate_text())                         # private prompts still read it
        PROFILE.write_text(REAL + "\n## Summary\nExpected salary around 187k\n\n## Preferences\nSalary floor: 187,000\n",
                           encoding="utf-8")
        with self.assertRaises(SystemExit):
            profile.candidate_text(private=False)                              # the figure on a line about pay
        PROFILE.write_text(REAL + "\n- Scaled to 187,000 users\n\n## Preferences\nSalary floor: 187,000\n", encoding="utf-8")
        self.assertIn("187,000 users", profile.candidate_text(private=False))  # a number that is not pay passes


class IdeaMarkup(Base):
    def test_body_never_overrides_the_row_and_numbers_are_numbers(self):  # security-ideas-xss-body-overrides-row
        body = {"id": "1);alert(1);(1", "topic": "<img src=x onerror=alert(1)>", "score": "<b>", "title": "T",
                "impact": "<svg onload=x>", "effort": 2, "fit": "90", "plan": "not a list", "status": "done"}
        iid = db.add_idea("strategy", "T", json.dumps(body), 4.5)
        row = ideas.rows()[0]
        self.assertEqual((row["id"], row["topic"], row["score"], row["status"]), (iid, "strategy", 4.5, "new"))
        self.assertEqual((row["impact"], row["effort"], row["fit"], row["plan"]), (3, 2, 90, []))
        real = ai.ask_json
        ai.ask_json = lambda *a, **k: body
        try:
            out = ideas.refine(iid, "more")
        finally:
            ai.ask_json = real
        self.assertEqual((out["id"], out["topic"]), (iid, "strategy"))
        self.assertEqual(ideas.rows()[0]["id"], iid)

    def test_app_js_escapes_idea_fields(self):
        src = APP_JS.read_text(encoding="utf-8")
        block = src[src.index("function renderIdeas"):src.index("No ideas yet")]
        for raw in ("${i.topic}", "${i.score}", "${i.id}", "${i.impact ?? '?'}"):
            self.assertNotIn(raw, block)
        self.assertIn("const id = Number(i.id)", block)


class EmployerPrompts(Base):
    def test_research_pack_prompt_has_no_floor(self):  # security-research-pack-floor-into-cover-letter
        PROFILE.write_text(REAL + "\n## Preferences\nSalary floor: $187,000 | needs H-1B transfer\n", encoding="utf-8")
        prompts, real = [], (ai.ask, util.fetch)
        ai.ask = lambda p, *a, **k: prompts.append(p) or "pack"
        util.fetch = lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
        try:
            extras.research(db.get_job(db.add_job("Initech", "Eng")))
        finally:
            ai.ask, util.fetch = real
        self.assertIn("Python", prompts[0])
        self.assertNotIn("187", prompts[0])
        self.assertNotIn("H-1B", prompts[0])

    def test_scheduling_reply_names_no_other_company(self):  # security-scheduling-reply-names-other-interviews
        other = db.add_job("Globex", "Eng")
        when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=3)
        interview.booked(other, f"{when:%Y-%m-%d %H:%M}")
        jid = db.add_job("Initech", "Eng")
        prompts, real = [], (ai.ask_json, approvals.propose, em.notify)
        ai.ask_json = lambda p, *a, **k: prompts.append(p) or {"subject": "Re", "body": "b", "chosen_time": None}
        approvals.propose = lambda *a, **k: {"status": "pending", "id": 1}
        em.notify = lambda *a: None
        try:
            em._maybe_reply({"category": "interview", "from": "r@initech.com", "subject": "Interview", "body": "when?",
                             "sender_email": "r@initech.com", "trusted": True}, db.get_job(jid))
        finally:
            ai.ask_json, approvals.propose, em.notify = real
        self.assertIn(f"{when:%Y-%m-%d %H:%M}", prompts[0])
        self.assertNotIn("Globex", prompts[0])
        self.assertIn("Never mention other interviews", prompts[0])


class IcsEscaping(Base):
    def test_company_newlines_cannot_add_events(self):  # security-ics-line-injection
        jid = db.add_job("Acme\r\nEND:VEVENT\nBEGIN:VEVENT\nURL:https://evil.example/confirm", "Eng; lead, data")
        out = extras.ics(db.get_job(jid), datetime(2031, 3, 4, 10, 0))
        try:
            text = out.read_text(encoding="utf-8")
        finally:
            import shutil
            shutil.rmtree(out.parent, ignore_errors=True)
        self.assertEqual(sum(ln == "BEGIN:VEVENT" for ln in text.splitlines()), 2)  # the text stays inside SUMMARY
        self.assertFalse(any(ln.startswith("URL:") for ln in text.splitlines()))
        self.assertIn("Eng\\; lead\\, data", text)
        self.assertEqual(extras.ics_text("a\\b\nc"), "a\\\\b\\nc")


class LinkedInZip(Base):
    def test_an_oversized_member_is_refused_before_reading(self):  # security-linkedin-zip-inflation
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Skills.csv", "Name\n" + "Python\n" * 50)
        real = profile.LI_MAX_BYTES
        profile.LI_MAX_BYTES = 100
        try:
            with self.assertRaises(SystemExit) as e:
                profile.linkedin_facts(buf.getvalue())
        finally:
            profile.LI_MAX_BYTES = real
        self.assertIn("larger than", str(e.exception))
        self.assertIn("Python", [s["name"] for s in profile.linkedin_facts(buf.getvalue())["skills"]])


# ----------------------------------------------------------------------------- network
class _Server:
    """A loopback HTTP server; handler(self) writes the response."""

    def __init__(self, handler):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                handler(self)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _ok(h, body=b"secret intranet page"):
    h.send_response(200)
    h.send_header("Content-Type", "text/plain")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.pop("LODESTAR_ALLOW_PRIVATE_URLS", None)

    def tearDown(self):
        os.environ.pop("LODESTAR_ALLOW_PRIVATE_URLS", None)
        if self.env is not None:
            os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = self.env

    def test_dns_rebinding_never_reaches_a_private_address(self):  # security-ssrf-dns-rebinding-toctou
        srv = _Server(_ok)
        real = (socket.getaddrinfo, urllib.request.getproxies)
        calls = []

        def fake(host, port, *a, **k):
            if host != "rebind.example":
                return real[0](host, port, *a, **k)
            calls.append(1)
            ip = "8.8.8.8" if len(calls) == 1 else "127.0.0.1"  # public for the check, loopback for the connect
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, srv.port))]
        socket.getaddrinfo, urllib.request.getproxies = fake, lambda: {}
        try:
            with self.assertRaises(ValueError) as e:
                util.fetch(f"http://rebind.example:{srv.port}/", timeout=3)
        finally:
            socket.getaddrinfo, urllib.request.getproxies = real
            srv.close()
        self.assertIn("non-public", str(e.exception))

    def test_size_cap_and_overall_deadline(self):  # packaging-fetch-unbounded
        def drip(h):
            h.send_response(200)
            h.send_header("Content-Length", "12")
            h.end_headers()
            for _ in range(12):
                h.wfile.write(b"x")
                h.wfile.flush()
                time.sleep(0.25)
        big, slow = _Server(lambda h: _ok(h, b"y" * 5000)), _Server(drip)
        os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = "1"
        real = util.FETCH_MAX_BYTES
        try:
            self.assertEqual(len(util.fetch(f"http://127.0.0.1:{big.port}/")), 5000)
            util.FETCH_MAX_BYTES = 1000
            with self.assertRaises(ValueError) as e:
                util.fetch(f"http://127.0.0.1:{big.port}/")
            self.assertIn("larger than", str(e.exception))
            util.FETCH_MAX_BYTES = real
            t = time.monotonic()
            with self.assertRaises(ValueError) as e:  # each read is quick, the whole response is not
                util.fetch(f"http://127.0.0.1:{slow.port}/", timeout=0.4)
            self.assertIn("took longer", str(e.exception))
            self.assertLess(time.monotonic() - t, 2.8)
        finally:
            util.FETCH_MAX_BYTES = real
            big.close()
            slow.close()

    def test_mail_sockets_have_timeouts(self):  # packaging-mail-no-timeout
        seen = {}

        class Stop(Exception):
            pass

        def rec(name):
            def f(*a, **k):
                seen[name] = k.get("timeout")
                raise Stop()
            return f
        real = (em.imaplib.IMAP4_SSL, util.smtplib.SMTP_SSL, util.setting)
        em.imaplib.IMAP4_SSL, util.smtplib.SMTP_SSL = rec("imap"), rec("smtp")
        util.setting = lambda k, d=None: {"IMAP_USER": "me@example.com", "IMAP_PASS": "p"}.get(k, d)
        try:
            with self.assertRaises(Stop):
                em._scan("imap.example.com", "me@example.com", "p", 1, 10, True, None)
            with self.assertRaises(Stop):
                util.send_email("you@example.com", "s", "b")
        finally:
            em.imaplib.IMAP4_SSL, util.smtplib.SMTP_SSL, util.setting = real
        self.assertEqual(seen, {"imap": util.MAIL_TIMEOUT, "smtp": util.MAIL_TIMEOUT})


# ----------------------------------------------------------------------------- data integrity
class Locks(FileDb):
    def test_duplicate_contact_or_story_never_leaves_the_database_locked(self):  # live-db-lock-after-duplicate
        contacts.add(name="Sam", email="sam@example.com")
        interview.save_story("Billing migration", situation="s")
        other = self.other()
        try:
            for fail in (lambda: contacts.add(name="Dup Sam", email="sam@example.com"),
                         lambda: interview.save_story("Billing migration", situation="again")):
                with self.assertRaises(SystemExit) as e:
                    fail()
                self.assertIn("already", str(e.exception))
                other.execute("INSERT INTO seen(key) VALUES(?)", (f"probe-{time.monotonic()}",))  # locked before the fix
                other.commit()
        finally:
            other.close()

    def test_release_rolls_back_and_closes(self):
        db.con().execute("INSERT INTO seen(key) VALUES('half-done')")  # a write that then failed, never committed
        c = db.con()
        db.release()
        self.assertIsNone(getattr(db._local, "con", None))
        with self.assertRaises(sqlite3.ProgrammingError):
            c.execute("SELECT 1")
        other = self.other()
        try:
            other.execute("INSERT INTO seen(key) VALUES('next')")
            other.commit()
            self.assertIsNone(other.execute("SELECT 1 FROM seen WHERE key='half-done'").fetchone())
        finally:
            other.close()
        db._local.con = db.connect(self.path)


class StaleStatus(Base):
    def test_a_proposal_never_moves_a_job_that_moved_since(self):  # integration-stale-status-proposal
        jid = db.add_job("Globex", "Eng")
        db.set_status(jid, "screening")
        r = approvals.propose("email_classify", "set_status", {"job_id": jid, "status": "interview"}, "move", jid,
                              force_pending=True)
        self.assertEqual(json.loads(db.get_pending(r["id"])["payload"])["from_status"], "screening")
        db.set_offer(jid, base=150000)                                         # your own move: the job is at offer
        self.assertEqual(db.get_pending(r["id"])["status"], "rejected")         # the waiting proposal is closed
        self.assertEqual(approvals.approve(r["id"])["status"], "rejected")
        self.assertEqual(db.get_job(jid)["status"], "offer")
        r2 = approvals.propose("followup", "set_status", {"job_id": jid, "status": "withdrawn"}, "close", jid)
        db.update_job(jid, status="accepted")                                   # moved without set_status
        out = approvals.approve(r2["id"])
        self.assertEqual(out["status"], "rejected")
        self.assertIn("stale", out["result"])
        self.assertEqual(db.get_job(jid)["status"], "accepted")


class JobIds(Base):
    def test_ids_are_never_reused(self):  # integration-rowid-reuse
        a = db.add_job("Initech", "Eng")
        db.add_pending("followup", "send_email", a, "sent", json.dumps({"to": "pm@initech.example"}))
        db.con().execute("UPDATE pending SET status='done' WHERE job_id=?", (a,))
        db.delete_job(a)
        b = db.add_job("Hooli", "Eng")
        self.assertGreater(b, a)
        rows = [r for r in extras.activity_log(date.today() - timedelta(days=3), date.today()) if r["employer"] == "Hooli"]
        self.assertEqual(rows, [])                                             # Initech's mail stays Initech's
        db.con().execute("INSERT INTO ideas(topic, title, body, job_id) VALUES('x', 'y', '{}', 40)")  # pre-upgrade leftover
        self.assertEqual(db.add_job("Next", "Eng"), 41)


class ClosedJobs(Base):
    def test_withdrawn_jobs_rounds_leave_today_and_clash_checks(self):  # integration-closed-job-interviews
        jid = db.add_job("Umbrella", "Eng")
        db.set_status(jid, "interview")
        when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
        interview.booked(jid, f"{when:%Y-%m-%d %H:%M}")
        self.assertEqual(len(extras.conflicts(when + timedelta(minutes=30))), 1)
        db.set_status(jid, "withdrawn")
        self.assertEqual(extras.upcoming_interviews(2), [])
        self.assertEqual(extras.conflicts(when + timedelta(minutes=30)), [])

    def test_activity_log_keeps_rounds_before_the_close_only(self):
        y = date.today() - timedelta(days=1)
        kept, gone = db.add_job("Before", "Eng"), db.add_job("After", "Eng")
        interview.booked(kept, f"{y:%Y-%m-%d} 10:00")
        interview.booked(gone, f"{y:%Y-%m-%d} 10:00")
        db.set_status(kept, "rejected")                                         # closed after the round
        db.set_status(gone, "withdrawn")
        db.con().execute("UPDATE events SET ts='2020-01-01 00:00:00' WHERE job_id=? AND kind='status'", (gone,))
        names = [r["employer"] for r in extras.activity_log(y, date.today()) if r["activity"] == "interviewed"]
        self.assertEqual(names, ["Before"])


class IcsRace(FileDb):
    def test_concurrent_imports_store_one_round(self):  # integration-sync-ics-race
        for trial in range(4):
            jid = db.add_job(f"Race{trial}", "Eng")
            db.add_event(jid, "calendar", f"C:/x/{jid}-race/interview-2031{trial + 1:02d}05-1000.ics")
            gate, errors = threading.Barrier(5), []

            def run():
                db._local.con = db.connect(self.path)
                try:
                    gate.wait()
                    interview.sync_ics()
                except BaseException as e:  # noqa: BLE001 - reported below
                    errors.append(e)
                finally:
                    db.release()
            threads = [threading.Thread(target=run) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            self.assertEqual(errors, [])
            n = db.con().execute("SELECT COUNT(*) FROM interviews WHERE job_id=?", (jid,)).fetchone()[0]
            self.assertEqual(n, 1, f"trial {trial}")


class FailedSend(Base):
    def test_a_failed_send_keeps_the_edited_draft_for_a_retry(self):  # live-send-error-drops-draft
        jid = db.add_job("Initech", "Eng")
        r = approvals.propose("followup", "send_email", {"to": "pm@initech.example", "subject": "Orig", "body": "b",
                                                         "job_id": jid}, "follow-up", jid)
        real = approvals.send_email

        def boom(*a, **k):
            raise RuntimeError("sending needs IMAP_USER + IMAP_PASS")
        approvals.send_email = boom
        try:
            out = approvals.approve(r["id"], {"subject": "Edited subject", "body": "my words"})
        finally:
            approvals.send_email = real
        row = db.get_pending(r["id"])
        self.assertEqual((out["status"], row["status"]), ("pending", "pending"))
        self.assertNotIn("error: error", out["result"])
        self.assertIn("sending needs", row["result"])
        p = json.loads(row["payload"])
        self.assertEqual((p["subject"], p["body"]), ("Edited subject", "my words"))
        sent = []
        approvals.send_email = lambda *a, **k: sent.append(a)
        try:
            self.assertEqual(approvals.approve(r["id"])["status"], "done")
        finally:
            approvals.send_email = real
        self.assertEqual(sent[0][1], "Edited subject")
        src = APP_JS.read_text(encoding="utf-8")
        self.assertIn("Retry send", src)


if __name__ == "__main__":
    unittest.main()
