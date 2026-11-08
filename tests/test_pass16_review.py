"""Pass 16, review fixes: mail trust needs something Lodestar already holds (not a lookalike TLD), threads only vouch
for senders we trusted, closed jobs never get rounds or replies, a new mail server never reuses the old app password,
an add_job proposal and its Unmatched mail stay one job, a reply to unverified mail moves nothing and says so, and
the Setup/Answers UI fixes. No network: the sender, the AI, the keyring and the mail servers are faked and restored."""
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

from lodestar import approvals, db, email_monitor as em, mailconn, resume, settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))  # discover puts tests/ on the path; a dotted run does not
from test_pass16_email import Mail as FakeServers  # noqa: E402

SEQ = itertools.count(1)
STATIC = Path(__file__).resolve().parent.parent / "lodestar" / "static"
TOOLS = ("email_classify", "interview_scheduling", "email_reply", "calendar")


class Base(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.real = (approvals.send_email, em.ai.ask_json, resume.candidate_text, em.notify,
                     {t: dict(settings.load()["tools"][t]) for t in TOOLS})
        approvals.send_email = lambda to, subject, body, in_reply_to=None: (
            self.sent.append((to, subject)) or f"<rv{len(self.sent)}.{id(self)}@example.com>")
        em.ai.ask_json = lambda *a, **k: {"subject": "Re: interview", "body": "That time works.", "chosen_time": "2026-12-01 10:00"}
        resume.candidate_text = lambda *a, **k: "Alex Rivera"
        em.notify = lambda *a, **k: None
        for t in TOOLS:
            settings.set_tool(t, enabled=True, auto=True)

    def tearDown(self):
        approvals.send_email, em.ai.ask_json, resume.candidate_text, em.notify, tools = self.real
        for t, v in tools.items():
            settings.set_tool(t, enabled=v["enabled"], auto=v["auto"])

    @staticmethod
    def info(sender, **kw):
        return {"category": "interview", "company": "", "title": "", "summary": "s", "action": "", "subject": "Interview",
                "from": sender, "sender_email": sender, "sender_name": "Pat", "body": "How about 2026-12-01 10:00?",
                "deadline": "2026-12-01 10:00", "message_id": f"<rv-in-{next(SEQ)}-{os.getpid()}@example.net>",
                "dkim_pass": True} | kw

    @staticmethod
    def mail(message_id):
        return db.mail_by_message_id(message_id)

    @staticmethod
    def rounds(jid):
        return db.con().execute("SELECT at FROM interviews WHERE job_id=?", (jid,)).fetchall()

    def send(self, jid, to, in_reply_to=None):
        approvals.EXECUTORS["send_email"]({"to": to, "subject": "Following up", "body": "Hello", "job_id": jid,
                                           "in_reply_to": in_reply_to})
        return db.list_mail(jid)[0]["message_id"]


class TldLookalike(Base):  # code-mail-tld-lookalike-still-trusted
    def test_a_company_name_under_another_suffix_is_never_trusted(self):
        jid = db.add_job("Brindlewick", "Engineer"); db.set_status(jid, "applied")
        i = self.info("r@brindlewick.xyz")
        em._apply(i, dry=False)
        job, m = db.get_job(jid), self.mail(i["message_id"])
        self.assertEqual((m["job_id"], m["trusted"]), (jid, 0))                  # filed under Brindlewick, weakly
        self.assertEqual((job["status"], job["contact_email"], self.rounds(jid)), ("applied", None, []))
        self.assertTrue(any(r["kind"] == "set_status" and r["job_id"] == jid for r in db.list_pending()))
        self.assertNotIn("r@brindlewick.xyz", [to for to, _ in self.sent])             # its reply waits in the Inbox

    def test_the_company_site_held_for_the_job_is_a_strong_tie(self):
        jid = db.add_job("Fennimore", "Engineer", "https://careers.fennimore.com/jobs/42"); db.set_status(jid, "applied")
        self.assertEqual(em._match({"sender_email": "r@fennimore.xyz"})[1], False)
        i = self.info("gavin@mail.fennimore.com")
        em._apply(i, dry=False)
        job = db.get_job(jid)
        self.assertEqual((job["status"], job["contact_email"], len(self.rounds(jid))), ("interview", "gavin@mail.fennimore.com", 1))
        self.assertEqual(em._match({"sender_email": "gavin@fennimore.co.uk"})[1], False)  # other suffix, same name: weak

    def test_outreach_about_an_untracked_company_is_never_trusted(self):
        before = len(db.list_jobs())
        i = self.info("r@ostrander.xyz", category="recruiter_outreach", company="Ostrander", title="SRE")
        em._apply(i, dry=False)
        self.assertEqual(len(db.list_jobs()), before)                            # proposed, not created
        p = next(json.loads(r["payload"]) for r in db.list_pending() if r["kind"] == "add_job" and "Ostrander" in r["summary"])
        self.assertNotIn("contact_email", p)                                      # the sender never becomes the contact


class ThreadVouching(Base):  # code-thread-reply-trusts-unverified-sender
    def test_a_reply_you_approved_to_an_unverified_sender_vouches_for_nobody(self):
        jid = db.add_job("Initech", "Engineer"); db.set_status(jid, "applied")
        first = self.info("mallory@evil-recruit.example", category="recruiter_outreach", company="", deadline=None)
        em._apply(first, dry=False)
        m = self.mail(first["message_id"])
        self.assertEqual((m["job_id"], m["trusted"]), (None, 0))
        db.link_mail(m["id"], jid)                                                # your link
        ours = self.send(jid, "mallory@evil-recruit.example", in_reply_to=first["message_id"])  # your approved reply
        reply = self.info("mallory@evil-recruit.example", in_reply_to=ours)
        em._apply(reply, dry=False)
        r, job = self.mail(reply["message_id"]), db.get_job(jid)
        self.assertEqual((r["job_id"], r["linked_by"], r["trusted"]), (jid, "thread", 0))
        self.assertEqual((job["status"], job["contact_email"], self.rounds(jid)), ("applied", None, []))

    def test_a_reply_to_our_answer_to_trusted_mail_is_strong(self):
        jid = db.add_job("Vehement Capital", "Analyst", "https://vehementcapital.com/jobs/1"); db.set_status(jid, "applied")
        first = self.info("hr@vehementcapital.com", deadline=None, category="assessment")
        em._apply(first, dry=False)
        self.assertEqual(self.mail(first["message_id"])["trusted"], 1)
        ours = self.send(jid, "hr@vehementcapital.com", in_reply_to=first["message_id"])
        self.assertTrue(em._match(self.info("lead@vehementcapital.com", in_reply_to=ours))[1])


class ClosedThread(Base):  # code-thread-matches-withdrawn-jobs
    def test_a_threaded_invite_on_a_withdrawn_job_books_and_sends_nothing(self):
        jid = db.add_job("Initrode", "Engineer"); db.set_status(jid, "applied")
        db.update_job(jid, contact_email="pm@initrode.example")
        ours = self.send(jid, "pm@initrode.example")
        db.set_status(jid, "withdrawn")
        self.sent.clear()
        i = self.info("pm@initrode.example", in_reply_to=ours)
        em._apply(i, dry=False)
        m = self.mail(i["message_id"])
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"]), (jid, "thread", 0))  # filed, never trusted
        self.assertEqual((self.rounds(jid), self.sent, db.get_job(jid)["status"]), ([], [], "withdrawn"))
        self.assertFalse(any(r["kind"] == "send_email" and r["job_id"] == jid for r in db.list_pending()))


class NewServerNeedsPassword(FakeServers):  # code-mail-password-reused-for-new-host
    def test_switching_servers_without_a_password_drops_the_old_one(self):
        mailconn.connect("gmail", "dana@example.com", "gmailapppassword1")
        st = mailconn.connect("custom", "dana@example.com", None, imap_host="imap.other-provider.example",
                              smtp_host="smtp.other-provider.example")
        self.assertEqual((st["configured"], self.stored("IMAP_PASS")), (False, None))
        with self.assertRaises(SystemExit):
            mailconn.test()                                                       # nothing logs in anywhere
        self.assertFalse([x for x in self.log if "login" in x[0]])
        mailconn.connect("gmail", "dana@example.com", "gmailapppassword1")
        mailconn.connect("gmail", "other@example.com")                           # another address: same rule
        self.assertIsNone(self.stored("IMAP_PASS"))


class TrackedOnce(Base):  # live-track-mail-duplicates-pending-add-job
    def outreach(self, who, company):
        settings.set_tool("email_classify", auto=False)  # untrusted either way; manual makes the intent plain
        i = self.info(who, category="recruiter_outreach", company=company, title="Platform Engineer", deadline=None)
        em._apply(i, dry=False)
        pid = next(r["id"] for r in db.list_pending() if r["kind"] == "add_job" and company in r["summary"])
        return self.mail(i["message_id"]), pid

    def count(self, company):
        return sum(1 for j in db.list_jobs() if j["company"] == company)

    def test_tracking_the_mail_closes_its_proposal(self):
        m, pid = self.outreach("art@zorblax.example", "Zorblax Logistics")
        self.assertIsNone(m["job_id"])
        jid = em.track_mail(m["id"])
        self.assertEqual(db.get_pending(pid)["status"], "rejected")
        approvals.approve(pid)                                                    # a stale click does nothing
        self.assertEqual(self.count("Zorblax Logistics"), 1)
        self.assertEqual(db.get_mail(m["id"])["job_id"], jid)

    def test_approving_the_proposal_files_the_mail(self):
        m, pid = self.outreach("kel@quillfeather.example", "Quillfeather Partners")
        self.assertEqual(approvals.approve(pid)["status"], "done")
        jid = next(j["id"] for j in db.list_jobs() if j["company"] == "Quillfeather Partners")
        self.assertEqual((db.get_mail(m["id"])["job_id"], db.get_job(jid)["contact_email"]), (jid, None))
        self.assertNotIn(m["id"], [r["id"] for r in db.list_mail(unmatched=True)])


class UnverifiedReply(Base):  # live-forged-thread-reply-moves-job-unflagged
    def test_approving_a_reply_to_untrusted_offer_mail_moves_nothing(self):
        jid = db.add_job("Initech Labs", "Engineer"); db.set_status(jid, "interview")
        db.update_job(jid, contact_email="jane@initechlabs.example")
        ours = self.send(jid, "jane@initechlabs.example")
        i = self.info("hr@initech-careers.example", category="offer", in_reply_to=ours, deadline=None)
        em._apply(i, dry=False)
        row = next(r for r in db.list_pending() if r["kind"] == "send_email" and r["job_id"] == jid)
        p = json.loads(row["payload"])
        self.assertEqual((p["to"], p.get("unverified"), "new_status" in p), ("hr@initech-careers.example", True, False))
        # chosen_time cleared: in the shared home another test's round may hold that slot, and a clash is refused first
        approvals.approve(row["id"], {"chosen_time": None})
        self.assertEqual(db.get_job(jid)["status"], "interview")

    def test_any_reply_to_unverified_mail_is_flagged(self):
        jid = db.add_job("Penske", "Engineer")
        db.add_mail(message_id="<rv-untrusted@example.net>", direction="in", job_id=jid, trusted=False)
        r = approvals.propose("email_reply", "send_email", {"to": "x@example.net", "subject": "Re", "body": "b", "job_id": jid,
                                                            "in_reply_to": "<rv-untrusted@example.net>", "new_status": "offer"},
                              "reply", jid, force_pending=True)
        p = json.loads(db.get_pending(r["id"])["payload"])
        self.assertEqual((p.get("unverified"), "new_status" in p), (True, False))


class SetupAndAnswersUi(unittest.TestCase):
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    def fn(self, name):
        return re.search(rf"^function {name}\(.*?^}}", self.js, re.M | re.S).group(0)

    def test_a_failed_sign_in_is_not_reported_as_connected(self):  # live-failed-login-reported-connected
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        esc = re.search(r"^const esc = .*$", self.js, re.M).group(0)
        st = {"configured": True, "user": "alex@example.com", "label": "Fastmail", "imap_host": "imap.example.com",
              "imap_port": 993, "smtp_host": "smtp.example.com", "smtp_port": 465, "smtp_mode": "ssl"}
        out = {}
        for key, ok in (("bad", False), ("good", True)):
            t = {"imap": {"ok": ok, "detail": "d"}, "smtp": {"ok": ok, "detail": "d"}, "hint": ""}
            code = (f"{esc}\nconst EM = {{status: {json.dumps(st)}}}; const box = {{}}; const $ = () => box;\n"
                    f"{self.fn('emailLine')}\nemailLine({json.dumps(t)}); process.stdout.write(box.innerHTML);")
            r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            out[key] = r.stdout
        self.assertIn("sign-in failed", out["bad"])
        self.assertNotIn("Connected as", out["bad"])
        self.assertIn("Connected as", out["good"])

    def test_the_answer_field_keeps_line_breaks(self):  # live-answer-option-loses-newlines
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<textarea id="bA"')
        self.assertNotRegex(html, r'<input id="bA"')

    def test_an_unsupported_provider_never_locks_the_address(self):  # live-outlook-guess-locks-address-field
        body = self.fn("emailPreset")
        self.assertIn("'#ePass'", body)
        self.assertNotIn("'#eUser'", body)

    def test_the_inbox_card_flags_unverified_replies(self):  # live-forged-thread-reply-moves-job-unflagged
        self.assertIn("p.unverified", self.fn("renderInbox"))


if __name__ == "__main__":
    unittest.main()
