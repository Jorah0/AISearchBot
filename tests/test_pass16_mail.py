"""Pass 16, builder 2: linking mail to jobs. The mail table (dedupe by Message-ID), outgoing Message-IDs recorded,
replies threaded to the right job, forged threads staying untrusted, manual links never trusting, unmatched mail,
delete_job cleanup, token-protected routes, CSV formula cells and mail-derived text rendered as text.
No network: the sender, the reply drafter and the classifier are faked; every patched attribute is put back."""
import contextlib
import http.client
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import approvals, cli, db, email_monitor as em, extras, settings  # noqa: E402

SEQ = itertools.count(1)
APP_JS = Path(__file__).resolve().parent.parent / "lodestar" / "static" / "app.js"


class MailBase(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.real = (approvals.send_email, em.ai.ask_json, settings.auto("email_classify"))
        approvals.send_email = lambda to, subject, body, in_reply_to=None: (
            self.sent.append((to, subject, in_reply_to)) or f"<out{len(self.sent)}.{id(self)}@example.com>")
        em.ai.ask_json = lambda *a, **k: {"subject": "Re: hi", "body": "thanks", "chosen_time": None}
        settings.set_tool("email_classify", auto=True)

    def tearDown(self):
        approvals.send_email, em.ai.ask_json, auto = self.real
        settings.set_tool("email_classify", auto=auto)

    def send(self, jid, to, subject="Following up"):
        """Mail Lodestar sends for a job through the approvals executor; returns its Message-ID."""
        approvals.EXECUTORS["send_email"]({"to": to, "subject": subject, "body": "Hello", "job_id": jid})
        return db.list_mail(jid)[0]["message_id"]

    @staticmethod
    def info(sender, **kw):
        return {"category": "interview", "company": "", "title": "", "summary": "s", "action": "", "subject": "Re: Following up",
                "from": sender, "sender_email": sender, "sender_name": "Pat", "body": "Can we talk Tuesday?",
                "message_id": f"<in-{next(SEQ)}-{os.getpid()}@example.net>", "dkim_pass": True} | kw

    @staticmethod
    def row(message_id):
        return db.con().execute("SELECT * FROM mail WHERE message_id=?", (message_id,)).fetchone()


class Storage(MailBase):
    def test_dedupe_by_message_id_and_snippet_cap(self):
        db.add_mail(message_id="<dup@example.com>", direction="in", subject="first", snippet="x" * 5000)
        db.add_mail(message_id="<dup@example.com>", direction="in", subject="second")
        rows = db.con().execute("SELECT * FROM mail WHERE message_id='<dup@example.com>'").fetchall()
        self.assertEqual((len(rows), rows[0]["subject"], len(rows[0]["snippet"])), (1, "first", 1500))

    def test_outgoing_message_id_is_recorded_with_the_job(self):
        jid = db.add_job("Vandelay Industries", "Importer")
        mid = self.send(jid, "art@vandelay.example")
        m = db.list_mail(jid)[0]
        self.assertEqual((m["direction"], m["to_addr"], m["job_id"], m["message_id"]), ("out", "art@vandelay.example", jid, mid))
        self.assertTrue(mid.startswith("<out"))

    def test_relevant_scanned_mail_is_recorded_and_dry_runs_record_nothing(self):
        jid = db.add_job("Pendant Publishing", "Editor", "https://pendantpublishing.com/jobs/editor"); db.set_status(jid, "applied")
        i = self.info("j@pendantpublishing.com", subject="Interview")
        em._apply(i | {"message_id": "<dry@example.net>"}, dry=True)
        self.assertIsNone(self.row("<dry@example.net>"))
        em._apply(i, dry=False)
        m = self.row(i["message_id"])
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"], m["direction"]), (jid, "auto", 1, "in"))


class Threads(MailBase):
    def test_a_reply_in_our_thread_links_to_the_right_job_and_counts_as_a_strong_tie(self):
        a = db.add_job("Acme Robotics", "Engineer"); db.set_status(a, "applied")
        b = db.add_job("Acme Rockets", "Engineer"); db.set_status(b, "applied")
        db.update_job(a, contact_email="pat@acmehr.example")  # our mail went to the stored contact: the thread vouches
        mid = self.send(a, "pat@acmehr.example")
        i = self.info("pat@acmehr.example", in_reply_to=mid, refs=f"<older@example.com> {mid}")
        em._apply(i, dry=False)
        m = self.row(i["message_id"])
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"]), (a, "thread", 1))
        self.assertEqual(db.get_job(a)["status"], "interview")  # trusted: the status move ran under auto
        self.assertEqual(db.get_job(b)["status"], "applied")

    def test_a_forged_in_reply_to_from_another_domain_stays_untrusted(self):
        jid = db.add_job("Kramerica", "Analyst"); db.set_status(jid, "applied")
        mid = self.send(jid, "pat@kramerica-hr.example")
        i = self.info("boss@evil.example", in_reply_to=mid)  # DKIM-valid for its own domain, copied our Message-ID
        em._apply(i, dry=False)
        m, job = self.row(i["message_id"]), db.get_job(jid)
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"]), (jid, "thread", 0))  # filed, never trusted
        self.assertEqual((job["status"], job["contact_email"]), ("applied", None))
        self.assertTrue(any(r["kind"] == "set_status" and r["job_id"] == jid for r in db.list_pending()))
        self.assertTrue(all(to != "boss@evil.example" for to, _, _ in self.sent))  # its reply waits in the Inbox

    def test_free_mail_thread_needs_the_exact_address_and_dkim(self):
        jid = db.add_job("Monks Diner", "Cook"); db.set_status(jid, "applied")
        db.update_job(jid, contact_email="jerry@gmail.com")
        mid = self.send(jid, "jerry@gmail.com")
        other = self.info("newman@gmail.com", in_reply_to=mid)
        em._apply(other, dry=False)
        self.assertEqual(self.row(other["message_id"])["trusted"], 0)  # same free-mail domain is anyone
        self.assertFalse(em._match(dict(other))[1])
        unsigned = self.info("jerry@gmail.com", in_reply_to=mid, dkim_pass=False)
        em._apply(unsigned, dry=False)
        self.assertEqual(self.row(unsigned["message_id"])["trusted"], 0)  # the thread never replaces DKIM/DMARC
        self.assertTrue(em._match(dict(unsigned))[1])

    def test_thread_never_overrides_a_different_stored_contact(self):
        jid = db.add_job("Bania Comedy", "Writer"); db.set_status(jid, "applied")
        db.update_job(jid, contact_email="kenny@baniacomedy.com")
        mid = self.send(jid, "agent@talent.example")
        i = self.info("agent@talent.example", in_reply_to=mid)
        em._apply(i, dry=False)
        self.assertEqual(self.row(i["message_id"])["trusted"], 0)  # disagrees with the contact you have
        self.assertEqual(db.get_job(jid)["status"], "applied")


class Unmatched(MailBase):
    def test_unmatched_list_link_dismiss_and_manual_links_never_trust(self):
        from lodestar import web
        jid = db.add_job("Peterman Catalog", "Writer"); db.set_status(jid, "applied")
        i = self.info("recruit@staffing.example", category="assessment", company="Some Startup", subject="Take-home")
        em._apply(i, dry=False)
        m = self.row(i["message_id"])
        self.assertIsNone(m["job_id"])
        self.assertIn(m["id"], [r["id"] for r in db.list_mail(unmatched=True)])
        self.assertIn(m["id"], [r["id"] for r in web.state()["mail_unmatched"]])
        db.link_mail(m["id"], jid)
        m, job = db.get_mail(m["id"]), db.get_job(jid)
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"], job["contact_email"]), (jid, "user", 0, None))
        later = self.info("recruit@staffing.example", company="Peterman Catalog", subject="Interview")
        em._apply(later, dry=False)  # the manual link does not make the sender's next mail trusted
        self.assertEqual((self.row(later["message_id"])["trusted"], db.get_job(jid)["status"]), (0, "applied"))
        with self.assertRaises(SystemExit):
            db.dismiss_mail(m["id"])  # filed under a job: unlink first
        db.unlink_mail(m["id"])
        self.assertIsNone(db.get_mail(m["id"])["job_id"])
        auto = self.row(later["message_id"])
        self.assertEqual((auto["job_id"], auto["linked_by"]), (jid, "auto"))  # the name match files it, weakly
        with self.assertRaises(SystemExit):
            db.unlink_mail(auto["id"])  # only links you made can be undone
        db.dismiss_mail(m["id"])
        self.assertNotIn(m["id"], [r["id"] for r in db.list_mail(unmatched=True)])

    def test_track_as_new_job_sets_the_contact_only_from_trusted_company_mail(self):
        ok = self.info("r@piedpiper.com", category="assessment", company="Pied Piper", title="SRE", subject="Pied Piper assessment")
        em._apply(ok, dry=False)
        m = self.row(ok["message_id"])
        self.assertEqual((m["job_id"], m["trusted"]), (None, 0))  # untracked company: nothing vouches for piedpiper.com
        jid = em.track_mail(m["id"])
        job, m = db.get_job(jid), db.get_mail(m["id"])
        self.assertEqual((job["company"], job["title"], job["contact_email"]), ("Pied Piper", "SRE", None))
        self.assertIn("Pied Piper assessment", job["notes"])
        self.assertEqual((m["job_id"], m["linked_by"]), (jid, "user"))
        with self.assertRaises(SystemExit):
            em.track_mail(m["id"])  # already filed
        forged = self.info("gavin@nucleus.com", category="assessment", company="Nucleus", subject="unsigned", dkim_pass=False)
        em._apply(forged, dry=False)
        jid2 = em.track_mail(self.row(forged["message_id"])["id"], "Nucleus", "")
        self.assertIsNone(db.get_job(jid2)["contact_email"])  # its domain names the company, but unauthenticated: no contact


class Cleanup(MailBase):
    def test_delete_job_removes_its_mail_and_ids_are_not_reused(self):
        jid = db.add_job("Brand X", "Temp")
        self.send(jid, "x@brandx.example")
        db.add_mail(message_id="<orphan@example.com>", direction="in", job_id=jid + 40)  # a leftover from an old database
        db.delete_job(jid)
        self.assertEqual(db.list_mail(jid), [])
        self.assertGreater(db.add_job("Brand Y", "Temp"), jid + 40)
        db.con().execute("DELETE FROM mail WHERE message_id='<orphan@example.com>'"); db.con().commit()

    def test_csv_export_neutralises_formula_cells(self):
        db.add_mail(message_id="<formula@example.com>", direction="in", subject='=HYPERLINK("http://evil.example","x")')
        out = Path(tempfile.mkdtemp(prefix="lodestar-export-"))
        try:
            extras.export_data("csv", out)
            text = next(out.glob("mail-*.csv")).read_text(encoding="utf-8")
            self.assertIn("'=HYPERLINK", text)
            self.assertNotIn(',=HYPERLINK', text)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class Surfaces(MailBase):
    def req(self, method, path, body=None, token=True):
        from lodestar import web
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}", "X-Lodestar-Token": web.TOKEN if token else "no"}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = (r.status, r.read().decode())
        c.close()
        return out

    def test_routes_need_the_token(self):
        from lodestar import desktop, web
        mem = getattr(db._local, "con", None)  # other suites leave an in-memory db on this thread; the server reads the file
        db._local.con = None
        jid = db.add_job("Del Boca Vista", "Manager")
        db.add_mail(message_id="<route@example.com>", direction="in", subject="hi")
        mid = self.row("<route@example.com>")["id"]
        self.port = desktop.free_port(8990)
        srv = web.start_server(self.port)
        try:
            for method, path in (("GET", "/api/mail?unmatched=1"), ("POST", f"/api/mail/{mid}/link"), ("POST", f"/api/mail/{mid}/unlink"),
                                 ("POST", f"/api/mail/{mid}/dismiss"), ("POST", f"/api/mail/{mid}/track")):
                self.assertEqual(self.req(method, path, {"job_id": jid} if method == "POST" else None, token=False)[0], 403, path)
            self.assertIsNone(db.get_mail(mid)["job_id"])
            code, body = self.req("POST", f"/api/mail/{mid}/link", {"job_id": jid})
            self.assertEqual(code, 200, body)
            code, body = self.req("GET", f"/api/mail?job={jid}")
            self.assertEqual((code, [m["id"] for m in json.loads(body)["mail"]]), (200, [mid]))
            self.assertEqual([m["id"] for m in json.loads(self.req("GET", f"/api/jobs/{jid}")[1])["mail"]], [mid])
            self.assertEqual(self.req("POST", f"/api/mail/{mid}/unlink", {})[0], 200)
            self.assertEqual(self.req("POST", f"/api/mail/{mid}/dismiss", {})[0], 200)
        finally:
            srv.shutdown(); srv.server_close()
            db.release()
            db._local.con = mem

    def test_cli_list_link_unlink_dismiss(self):
        jid = db.add_job("Yev Kassem", "Chef")
        db.add_mail(message_id="<cli@example.com>", direction="in", subject="Soup", from_addr="y@example.org")
        mid = self.row("<cli@example.com>")["id"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["mail", "list", "--unmatched"])
            cli.main(["mail", "link", str(mid), str(jid)])
            cli.main(["mail", "list", "--job", str(jid)])
            cli.main(["mail", "unlink", str(mid)])
            cli.main(["mail", "dismiss", str(mid)])
        out = buf.getvalue()
        self.assertIn("Soup", out)
        self.assertIn(f"job #{jid} (user)", out)
        with self.assertRaises(SystemExit):
            db.get_mail(mid)

    def test_mail_text_renders_as_text(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        js = APP_JS.read_text(encoding="utf-8")
        esc = re.search(r"^const esc = .*$", js, re.M).group(0)
        local = re.search(r"^function localTs\(.*?^}", js, re.M | re.S).group(0)
        render = js.split("/* mail-render */")[1].split("/* /mail-render */")[0]
        bad = '<img src=x onerror=alert(1)>'
        m = {"id": 7, "direction": "in", "from_addr": bad, "category": bad, "subject": bad, "summary": bad, "snippet": bad,
             "trusted": 0, "sent_at": "2026-01-02 03:04:05", "linked_by": bad}
        code = f"{esc}\n{local}\n{render}\nprocess.stdout.write(mailItem({json.dumps(m)}, ''));"
        out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("<img", out.stdout)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", out.stdout)
        self.assertIn("unverified", out.stdout)


if __name__ == "__main__":
    unittest.main()
