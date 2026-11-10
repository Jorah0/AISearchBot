"""Connections pass, builder C: attachments out (an employer-safe set only, checked on propose, before the Inbox claim and
at send), attachments in (kept types, caps, saved under the job with Mark-of-the-Web, never opened), .ics invites under
the unchanged trust rules, the emailed-code assist (memory only), the routes, the UI pieces and docs/CONNECT.md.
No network and no real keyring: IMAP, SMTP, AI and keyring are faked; every patched attribute is put back."""
import imaplib
import contextlib
import email
import email.policy
import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import approvals, codes, db, drafts, email_monitor as em, mailfiles, profile, settings, util, vault  # noqa: E402
from lodestar.config import HOME, PROFILE  # noqa: E402
from lodestar.resume import app_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "lodestar" / "static"
FLOOR = "$187,000"
REAL = ("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"
        f"\n## Preferences\nSalary floor: {FLOOR} | Deal-breakers: none\n")
PASS = "mx.example.com; dkim=pass header.d=acme.example; dmarc=pass header.from=acme.example"


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def docx_bytes(text: str) -> bytes:
    from docx import Document

    d, buf = Document(), io.BytesIO()
    d.add_paragraph(text)
    d.save(buf)
    return buf.getvalue()


class Base(unittest.TestCase):
    """An in-memory tracker, the real-looking profile (floor $187,000), an in-memory keyring, a job folder per test."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")
        k, self.store = vault.keyring, {}
        self.real_keyring = (k.get_password, k.set_password, k.delete_password, vault._index())
        k.get_password = lambda svc, name: self.store.get((svc, name))
        k.set_password = lambda svc, name, v: self.store.__setitem__((svc, name), v)
        k.delete_password = lambda svc, name: self.store.pop((svc, name), None)
        self.company = "Acme" + uuid.uuid4().hex[:8]
        self.jid = db.add_job(self.company, "Engineer")
        db.update_job(self.jid, contact_email="jane@acme.example", contact_name="Jane")
        db.set_status(self.jid, "applied")
        self.job = db.get_job(self.jid)
        self.dir = app_dir(self.job)
        codes._CODES.clear()

    def tearDown(self):
        codes._CODES.clear()
        shutil.rmtree(self.dir, ignore_errors=True)
        k = vault.keyring
        k.get_password, k.set_password, k.delete_password, idx = self.real_keyring
        vault._save_index(idx)
        c = getattr(db._local, "con", None)
        if c is not None:
            c.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def put(self, name: str, data: bytes = b"%PDF-1.4 test") -> Path:
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def pending(self):
        return [dict(r) for r in db.list_pending("pending")]


class Outgoing(Base):
    def test_only_the_employer_safe_set_is_attachable(self):
        for n in ("resume.pdf", "resume.md", "interview_prep.md", "offer.md", "research.md", "gap.json", "interview-1.ics",
                  "mail/20261109-ab12cd34/offer.pdf", "history/resume-old.pdf", "attach/portfolio.pdf", "attach/run.exe",
                  "notes.html"):
            self.put(n)
        self.assertEqual(sorted(f["name"] for f in mailfiles.attachable(self.job)), ["attach/portfolio.pdf", "resume.pdf"])
        self.assertEqual([p.name for p in mailfiles.resolve(self.job, ["resume.pdf", "attach/portfolio.pdf", "resume.pdf"])],
                         ["resume.pdf", "portfolio.pdf"])  # duplicates dropped
        for bad in ("resume.md", "interview_prep.md", "offer.md", "research.md", "gap.json", "interview-1.ics",
                    "mail/20261109-ab12cd34/offer.pdf", "history/resume-old.pdf", "attach/run.exe", "notes.html",
                    "attach/../offer.md", "attach/../resume.pdf", "attach/a/b.pdf", "resume.pdf:evil", "attach/x.pdf:evil",
                    "../x.pdf", "..\\x.pdf", "/etc/passwd", "C:\\Windows\\win.ini", "resume.pdf\x00.txt",
                    "attach/missing.pdf", "cover_letter.pdf"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                mailfiles.resolve(self.job, [bad])
        for bad in ("resume.pdf", {"name": "resume.pdf"}, [1]):
            with self.assertRaises(SystemExit):
                mailfiles.resolve(self.job, bad)

    def test_size_and_count_caps(self):
        self.put("attach/big.pdf", b"0" * (mailfiles.MAX_FILE + 1))
        self.put("attach/a.pdf", b"0" * 6_000_000)
        self.put("attach/b.pdf", b"0" * 6_000_000)
        for names in (["attach/big.pdf"], ["attach/a.pdf", "attach/b.pdf"], [f"attach/f{i}.pdf" for i in range(11)]):
            with self.assertRaises(SystemExit):
                mailfiles.resolve(self.job, names)

    def test_links_out_of_the_job_folder_are_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="lodestar-outside-"))
        try:
            (outside / "secret.pdf").write_bytes(b"%PDF secret")
            (self.dir / "attach").mkdir(exist_ok=True)
            try:
                os.symlink(outside / "secret.pdf", self.dir / "attach" / "link.pdf")
                with self.assertRaises(SystemExit):
                    mailfiles.resolve(self.job, ["attach/link.pdf"])
                self.assertNotIn("attach/link.pdf", [f["name"] for f in mailfiles.attachable(self.job)])
            except (OSError, NotImplementedError):
                pass  # no symlink privilege here; the junction below covers Windows
            if sys.platform.startswith("win"):
                import _winapi

                shutil.rmtree(self.dir / "attach", ignore_errors=True)
                _winapi.CreateJunction(str(outside), str(self.dir / "attach"))
                try:
                    with self.assertRaises(SystemExit):
                        mailfiles.resolve(self.job, ["attach/secret.pdf"])
                finally:
                    os.rmdir(self.dir / "attach")
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_the_floor_guard_reads_what_is_attached(self):
        self.put("resume.pdf")
        self.put("resume.md", f"# Jane Doe\nLooking for at least {FLOOR}.\n".encode())
        with self.assertRaises(SystemExit) as e:
            mailfiles.resolve(self.job, ["resume.pdf"])
        self.assertIn("salary floor", str(e.exception))
        self.put("attach/letter.docx", docx_bytes(f"My floor is {FLOOR}."))
        with self.assertRaises(SystemExit):
            mailfiles.resolve(self.job, ["attach/letter.docx"])
        self.put("attach/ok.docx", docx_bytes("Portfolio: data pipelines."))
        self.assertEqual(len(mailfiles.resolve(self.job, ["attach/ok.docx"])), 1)
        with patched(mailfiles, MAX_DOCX_XML=100):  # a zip bomb's text part: refused before it is unpacked
            with self.assertRaises(SystemExit) as e:
                mailfiles.resolve(self.job, ["attach/ok.docx"])
        self.assertIn("too large", str(e.exception))
        self.put("attach/fake.docx", b"not a zip")
        with self.assertRaises(SystemExit):
            mailfiles.resolve(self.job, ["attach/fake.docx"])

    def test_mime_round_trip(self):
        pdf, docx = self.put("resume.pdf", b"%PDF-1.4 resume bytes"), self.put("cover_letter.docx", b"PK docx bytes")
        sent = []

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def send_message(self, m):
                sent.append(m)

        cfg = {"user": "me@example.com", "smtp_host": "smtp.example.com", "smtp_port": 465, "smtp_mode": "ssl",
               "smtp_user": "me@example.com"}
        with patched(util, mail_settings=lambda: cfg, mail_login=lambda get=None: ("pw", True),
                     smtp_open=lambda *a: S(), smtp_login=lambda *a: None):
            util.send_email("jane@acme.example", "Hello", "Body text", attachments=[pdf, docx])
        m = email.message_from_bytes(sent[0].as_bytes(), policy=email.policy.default)
        parts = [(p.get_content_type(), p.get_filename(), p.get_payload(decode=True)) for p in m.walk()
                 if p.get_content_disposition() == "attachment"]
        self.assertEqual(parts, [("application/pdf", "resume.pdf", b"%PDF-1.4 resume bytes"),
                                 (mailfiles.TYPES[".docx"], "cover_letter.docx", b"PK docx bytes")])
        self.assertIn("Body text", m.get_body(("plain",)).get_content())

    def test_propose_precheck_and_send_each_check_the_files(self):
        self.put("resume.pdf")
        pay = {"to": "jane@acme.example", "subject": "Hi", "body": "Hello", "job_id": self.jid}
        for bad, force in ((["../../vault_index.json"], True), (["resume.pdf"], False)):  # bad path / auto tool
            with self.assertRaises(SystemExit):
                approvals.propose("email_reply", "send_email", pay | {"attachments": bad}, "s", self.jid, force_pending=force)
        with self.assertRaises(SystemExit):  # a job other than the payload's
            approvals.propose("email_reply", "send_email", pay | {"attachments": ["resume.pdf"]}, "s", None, force_pending=True)
        self.assertEqual(self.pending(), [])
        r = approvals.propose("email_reply", "send_email", pay | {"attachments": ["resume.pdf"]}, "mail", self.jid,
                              force_pending=True)
        self.assertIn("+ 1 attachment", db.get_pending(r["id"])["summary"])
        sent = []
        with patched(approvals, send_email=lambda *a, **k: sent.append(k) or "<out-1@example.com>"):
            for edits in ({"attachments": ["../../vault_index.json"]}, {"attachments": "resume.pdf"}):
                with self.assertRaises(SystemExit):
                    approvals.approve(r["id"], edits | {"subject": "Hi", "body": "Hello"})
            row = db.get_pending(r["id"])
            self.assertEqual((row["status"], json.loads(row["payload"])["attachments"]), ("pending", ["resume.pdf"]))
            self.put("resume.md", f"Floor {FLOOR}".encode())  # the floor turns up in the resume after proposing
            with self.assertRaises(SystemExit):
                approvals.approve(r["id"], {"subject": "Hi", "body": "Hello"})
            (self.dir / "resume.md").unlink()
            real_pre = approvals._precheck

            def gone(row, edits):  # the file vanishes between the claim and the send
                real_pre(row, edits)
                (self.dir / "resume.pdf").unlink()

            with patched(approvals, _precheck=gone):
                out = approvals.approve(r["id"], {"subject": "Hi", "body": "Hello"})
            self.assertEqual((out["status"], sent), ("pending", []))
            self.assertIn("not found", db.get_pending(r["id"])["result"])
            self.put("resume.pdf")
            out = approvals.approve(r["id"], {"subject": "Hi", "body": "Hello"})
        self.assertEqual(out["status"], "done", out)
        self.assertEqual([p.name for p in sent[0]["attachments"]], ["resume.pdf"])
        row = db.mail_by_message_id("<out-1@example.com>")
        self.assertEqual([a["name"] for a in json.loads(row["attachments"])], ["resume.pdf"])

    def test_requested_drafts_suggest_the_resume_except_replies_to_unverified_mail(self):
        self.put("resume.pdf")
        with patched(approvals, send_email=lambda *a, **k: None):
            r = drafts.use("outreach", {"job": self.jid}, {"subject": "Hello", "body": "Short note"})
        row = db.get_pending(r["proposal"]["id"])
        self.assertEqual((row["status"], json.loads(row["payload"])["attachments"]), ("pending", ["resume.pdf"]))
        approvals.reject(row["id"])
        for trusted, want in ((False, None), (True, ["resume.pdf"])):
            mid = f"<in-{trusted}@acme.example>"
            db.add_mail(message_id=mid, job_id=self.jid, direction="in", from_addr="jane@acme.example", subject="Chat?",
                        trusted=trusted)
            r = drafts.use("reply", {"job": self.jid, "mail_id": db.mail_by_message_id(mid)["id"]},
                           {"subject": "Re: Chat?", "body": "Happy to talk."})
            p = json.loads(db.get_pending(r["proposal"]["id"])["payload"])
            self.assertEqual(p.get("attachments"), want, trusted)
            approvals.reject(r["proposal"]["id"])
        self.put("resume.md", f"Floor {FLOOR}".encode())  # a resume that names the floor is never suggested
        self.assertEqual(mailfiles.suggest(self.job), [])


def invite(start="20261112T150000Z", tz=""):
    tzp = f";TZID={tz}" if tz else ""
    return (f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Interview with\r\n  Acme\r\nDTSTART{tzp}:{start}\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def mail_with(files, frm="Jane <jane@acme.example>", subject="Interview invite", body="Please see the invite.",
              mid=None, auth=PASS):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, "me@example.com", subject
    m["Message-ID"] = mid or f"<{uuid.uuid4().hex}@acme.example>"
    m["Date"] = email.utils.format_datetime(datetime.now(timezone.utc))
    if auth:
        m["Authentication-Results"] = auth
    m.set_content(body)
    for name, ctype, data, disp in files:
        main, sub = ctype.split("/")
        m.add_attachment(data, maintype=main, subtype=sub, filename=name, disposition=disp)
    return m


class Box:
    def __init__(self, msgs):
        self.msgs, self.log = msgs, []

    def login(self, *a):
        pass

    def select(self, *a, **k):
        self.log.append(("select", a, k))

    def logout(self):
        pass

    def uid(self, op, *a):
        self.log.append((op, *a))
        if op == "search":
            return "OK", [b" ".join(str(u).encode() for u in self.msgs)]
        return "OK", [(a[0], self.msgs[int(a[0])])]


class Incoming(Base):
    def test_extract_keeps_allowed_types_and_skips_the_rest(self):
        m = mail_with([("../../evil.pdf", "application/pdf", b"%PDF a", "attachment"),
                       ("CON.pdf", "application/pdf", b"%PDF b", "attachment"),
                       ("invoice.exe", "application/octet-stream", b"MZ", "attachment"),
                       ("page.html", "text/html", b"<script>", "attachment"),
                       ("run.js", "application/javascript", b"x", "attachment"),
                       ("logo.png", "image/png", b"\x89PNG", "inline"),
                       ("big.pdf", "application/pdf", b"0" * 2000, "attachment")])
        cal = EmailMessage()
        cal.set_content(invite().decode(), subtype="calendar")  # an invite part with no filename
        m.attach(cal)
        fwd, part = EmailMessage(), EmailMessage()
        fwd["Subject"] = "forwarded"
        fwd.add_attachment(b"%PDF inner", maintype="application", subtype="pdf", filename="inner.pdf")
        part.set_content(fwd)  # message/rfc822: forwarded mail
        m.attach(part)
        with patched(mailfiles, MAX_FILE=1000):
            items, skipped = mailfiles.extract(m)
        self.assertEqual([i["name"] for i in items], ["evil.pdf", "_CON.pdf", "invite.ics"])
        why = {s["name"]: s["skipped"] for s in skipped}
        self.assertEqual(why["invoice.exe"], "type not kept")
        self.assertEqual(why["page.html"], "type not kept")
        self.assertIn("over", why["big.pdf"])
        self.assertIn("forwarded mail", " ".join(why.values()))
        self.assertNotIn("logo.png", why)
        self.assertNotIn("inner.pdf", [i["name"] for i in items])
        many = mail_with([(f"f{i}.pdf", "application/pdf", b"%PDF", "attachment") for i in range(12)])
        items, skipped = mailfiles.extract(many)
        self.assertEqual((len(items), len(skipped)), (10, 2))
        with patched(mailfiles, MAX_IN_TOTAL=10):
            items, skipped = mailfiles.extract(many)
        self.assertEqual(len(items), 2)  # 4 + 4 bytes fit, the rest go over the per-message total

    def test_save_writes_under_the_job_never_overwrites_and_marks_the_web(self):
        items = [{"name": "offer.pdf", "type": "application/pdf", "data": b"%PDF 1"}]
        when = datetime(2026, 11, 9, 10, 0)
        a = mailfiles.save(items, self.job, "<m1@acme.example>", when)
        b = mailfiles.save(items, self.job, "<m1@acme.example>", when)
        self.assertEqual([a[0]["name"], b[0]["name"]], ["offer.pdf", "offer (2).pdf"])
        path = HOME / a[0]["path"]
        self.assertTrue(path.is_relative_to(self.dir / "mail"))
        self.assertRegex(path.parent.name, r"^20261109-[0-9a-f]{8}$")
        if sys.platform.startswith("win"):
            try:
                with open(f"{path}:Zone.Identifier", encoding="ascii") as f:
                    self.assertIn("ZoneId=3", f.read())
            except OSError:
                self.skipTest("this temp folder is not on NTFS")
        self.assertEqual(mailfiles.save(items, None, "<m2@x>", when), [])

    def scan(self, msgs, cat="interview", deadline=None, dry=False):
        def classify(subject, sender, body, provider=None):
            return {"category": cat, "company": self.company, "title": "Engineer", "summary": "s", "action": "none",
                    "deadline": deadline}

        self.uid = getattr(self, "uid", 0)
        box = Box({self.uid + i + 1: m.as_bytes() for i, m in enumerate(msgs)})  # new UIDs: a seen one is skipped
        self.uid += len(msgs)
        with patched(imaplib, IMAP4_SSL=lambda host, **kw: box), patched(em, classify=classify, notify=lambda m: None), \
                contextlib.redirect_stdout(io.StringIO()):
            return em._scan("imap.example.com", "me@example.com", "p", 3, 50, dry, None)

    def quiet(self):
        for t in ("interview_scheduling", "email_reply", "calendar"):
            settings.set_tool(t, enabled=False)

    def test_scanned_mail_saves_files_for_a_job_and_lists_them(self):
        self.quiet()
        m = mail_with([("offer.pdf", "application/pdf", b"%PDF offer", "attachment"),
                       ("setup.exe", "application/octet-stream", b"MZ", "attachment")])
        self.scan([m], dry=True)
        self.assertFalse((self.dir / "mail").exists())  # a dry run writes nothing
        found = self.scan([m])
        self.assertNotIn("_files", found[0])  # file bytes never reach the scan result
        row = db.mail_by_message_id(m["Message-ID"])
        att = json.loads(row["attachments"])
        self.assertEqual([a["name"] for a in att], ["offer.pdf", "setup.exe"])
        self.assertEqual(att[1]["skipped"], "type not kept")
        self.assertEqual((HOME / att[0]["path"]).read_bytes(), b"%PDF offer")
        self.assertIn("1 attachment(s) saved: offer.pdf", [e["detail"] for e in db.events(self.jid)])
        # mail no job claims: nothing written, the names listed
        stray = mail_with([("cv.pdf", "application/pdf", b"%PDF", "attachment")], frm="Pat <pat@other.example>", auth="")
        before = set(HOME.rglob("cv.pdf"))
        with patched(db, find_job_by_company=lambda *a: None):
            self.scan([stray], cat="recruiter_outreach")
        self.assertEqual(set(HOME.rglob("cv.pdf")), before)
        att = json.loads(db.mail_by_message_id(stray["Message-ID"])["attachments"])
        self.assertIn("not filed under a job", att[0]["skipped"])
        # a write failure still files the mail
        bad = mail_with([("x.pdf", "application/pdf", b"%PDF", "attachment")])

        def boom(*a, **k):
            raise OSError("disk full")

        with patched(mailfiles, save=boom):
            self.scan([bad])
        self.assertIn("not saved", json.loads(db.mail_by_message_id(bad["Message-ID"])["attachments"])[0]["skipped"])

    def rounds(self):
        return [r["at"] for r in db.con().execute("SELECT at FROM interviews WHERE job_id=?", (self.jid,))]

    def test_an_invite_fills_the_time_and_the_trust_rules_decide(self):
        self.quiet()
        local = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        self.scan([mail_with([("invite.ics", "text/calendar", invite(), "attachment")], auth="")])  # unverified
        self.assertEqual(self.rounds(), [])
        self.assertTrue(any(e["kind"] == "interview_date" for e in db.events(self.jid)))
        self.scan([mail_with([("invite.ics", "text/calendar", invite(), "attachment")])])  # aligned DKIM, stored contact
        self.assertEqual([a[:16] for a in self.rounds()], [f"{local:%Y-%m-%d %H:%M}"])

    def test_ics_times(self):
        ics = lambda data: mailfiles.ics_start([{"name": "a.ics", "data": data}])  # noqa: E731
        self.assertEqual(ics(invite("20261112T150000")), datetime(2026, 11, 12, 15, 0))  # floating: local
        self.assertIsNone(ics(invite("20261112T150000", "Eastern Standard Time")))  # unknown zone: no time, not "local"
        self.assertIsNone(ics(invite("20261112")))  # date only
        self.assertIsNone(ics(b"BEGIN:VCALENDAR\r\nDTSTART:20261112T150000Z\r\n"))  # no VEVENT
        self.assertIsNone(mailfiles.ics_start([{"name": "a.pdf", "data": invite()}]))


class Codes(Base):
    NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)

    def find(self, subject, body, age=60):
        return codes.find(subject, "no-reply@greenhouse-mail.example", body, self.NOW - timedelta(seconds=age), now=self.NOW)

    def test_find(self):
        for subject, body, code in (("Sign in", "Your verification code is 482913", "482913"),
                                    ("Greenhouse security code", "Code: 7F3K9Q", "7F3K9Q"),
                                    ("Hello", "Use 5521 to sign in. It expires soon.", "5521"),
                                    ("482913 is your login code", "", "482913")):
            hit = self.find(subject, body)
            self.assertEqual(hit and hit["code"], code, body)
            self.assertEqual(hit["domain"], "greenhouse-mail.example")
        for subject, body in (("Your code", "Call 555-123-4567 any time"), ("Interview", "Interview on 2026-11-12 at 10:30"),
                              ("Order", "Order #123456 has shipped"), ("Verification code", "Visit https://x.example/123456 now"),
                              ("Verification code", "WELCOME ABOARD"), ("Code", "Your code is 2026")):
            self.assertIsNone(self.find(subject, body), body)
        self.assertIsNone(self.find("Sign in", "Your verification code is 482913", age=codes.TTL + 1))

    def test_offer_only_from_authenticated_senders_and_current_expires(self):
        self.NOW = datetime.now(timezone.utc)
        good = mail_with([], frm="Acme <noreply@acme.example>", subject="Your sign-in code", body="Code: 7F3K9Q")
        self.assertIsNotNone(codes.offer(good, self.NOW))
        spoof = mail_with([], frm="Acme <noreply@acme.example>", subject="Your sign-in code", body="Code: 9X9X9X", auth="")
        self.assertIsNone(codes.offer(spoof, self.NOW))
        self.assertEqual([c["code"] for c in codes.current(self.NOW + timedelta(minutes=5))], ["7F3K9Q"])
        self.assertEqual(codes.current(self.NOW + timedelta(minutes=16)), [])  # expired from the mail's received time
        codes.offer(good, self.NOW)
        cid = codes.current(self.NOW)[0]["id"]
        codes.dismiss(cid)
        self.assertEqual(codes.current(self.NOW), [])
        self.assertIsNone(codes.offer("not a message"))  # never raises

    def test_scan_keeps_a_code_from_irrelevant_mail_and_writes_it_nowhere(self):
        code = "730194"
        m = mail_with([], frm="Portal <security@acme.example>", subject="Your one-time code",
                      body=f"Your one-time code is {code}.")
        notes, classified = [], []
        box = Box({1: m.as_bytes()})
        with patched(imaplib, IMAP4_SSL=lambda host, **kw: box), patched(em, notify=notes.append,
                     classify=lambda *a, **k: classified.append(a) or {"category": "other"}, looks_relevant=lambda *a: False), \
                contextlib.redirect_stdout(io.StringIO()):
            em._scan("imap.example.com", "me@example.com", "p", 3, 50, False, None)
        self.assertEqual([c["code"] for c in codes.current()], [code])
        self.assertEqual((notes, classified), ([], []))  # not relevant: never classified, never notified
        self.assertFalse(any(op == "store" for op, *_ in box.log))  # no flags changed
        self.assertIsNone(db.mail_by_message_id(m["Message-ID"]))
        for p in HOME.rglob("*"):
            if p.is_file() and p.stat().st_size < 5_000_000 and p.suffix != ".db":
                self.assertNotIn(code.encode(), p.read_bytes(), p)

    def test_poll_peeks_since_yesterday_and_skips_large_mail(self):
        when = datetime.now().astimezone().strftime("%d-%b-%Y %H:%M:%S %z").encode()
        small = mail_with([], frm="Acme <noreply@acme.example>", subject="Login code", body="Code: 4K7Q2Z").as_bytes()
        log = []

        class P:
            def __init__(self, host, port=993, **kw):
                pass

            def select(self, box, readonly=False):
                log.append(("select", readonly))

            def uid(self, op, *a):
                log.append((op, *a))
                if op == "search":
                    return "OK", [b"1 2"]
                if a[1] == "(INTERNALDATE RFC822.SIZE)":
                    size = 2_000_000 if a[0] == b"2" else len(small)
                    return "OK", [b'%s (UID %s INTERNALDATE "%s" RFC822.SIZE %d)' % (a[0], a[0], when, size)]
                return "OK", [(b"1 (UID 1 BODY[] {%d}" % len(small), small), b")"]

            def logout(self):
                pass

        logins = []
        cfg = {"user": "me@example.com", "imap_host": "imap.example.com", "imap_port": 993}
        with patched(codes.imaplib, IMAP4_SSL=P), patched(util, mail_settings=lambda: cfg, mail_login=lambda get=None: (None, True),
                                                          imap_login=lambda box, user, pw: logins.append((user, pw))):
            out = codes.poll()
        self.assertEqual([c["code"] for c in out], ["4K7Q2Z"])
        self.assertEqual(logins, [("me@example.com", None)])  # through util.imap_login (XOAUTH2 when signed in)
        self.assertIn(("select", True), log)
        since = (datetime.now().date() - timedelta(days=1)).strftime("%d-%b-%Y")
        self.assertIn(("search", None, f"(SINCE {since})"), log)
        bodies = [e for e in log if e[0] == "fetch" and e[2] != "(INTERNALDATE RFC822.SIZE)"]
        self.assertEqual(bodies, [("fetch", b"1", "(BODY.PEEK[])")])  # the 2 MB message is never downloaded
        with patched(util, mail_login=lambda get=None: (None, False)), self.assertRaises(SystemExit):
            codes.poll()


class Routes(Base):
    def req(self, method, path, body=None, token=True):
        from lodestar import web

        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}", "X-Lodestar-Token": web.TOKEN if token else "no"}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = (r.status, r.read().decode())
        c.close()
        return out

    def test_routes_need_the_token_and_never_carry_a_code_or_bytes(self):
        from lodestar import desktop, web

        mem = db._local.con
        db._local.con = self._con  # the server threads use the file database
        db.con()
        jid = db.add_job(self.company + "R", "Engineer")
        d = app_dir(db.get_job(jid))
        (d / "resume.pdf").write_bytes(b"%PDF route bytes")
        codes._CODES["abc"] = {"id": "abc", "code": "918273", "sender": "x@acme.example", "domain": "acme.example",
                               "subject": "code", "received": datetime.now(timezone.utc)}
        opened = []
        self.port = desktop.free_port(8990)
        srv = web.start_server(self.port)
        try:
            for method, path in (("GET", f"/api/jobs/{jid}/files"), ("GET", "/api/codes"), ("POST", "/api/codes/check"),
                                 ("POST", "/api/codes/abc/dismiss")):
                self.assertEqual(self.req(method, path, {} if method == "POST" else None, token=False)[0], 403, path)
            code, body = self.req("GET", f"/api/jobs/{jid}/files")
            self.assertEqual((code, [f["name"] for f in json.loads(body)["files"]]), (200, ["resume.pdf"]))
            self.assertNotIn("route bytes", body)
            code, body = self.req("GET", "/api/state")
            self.assertEqual((code, json.loads(body)["codes_count"]), (200, 1))
            self.assertNotIn("918273", body)
            self.assertIn("918273", self.req("GET", "/api/codes")[1])
            self.assertEqual(self.req("POST", "/api/codes/abc/dismiss", {})[0], 200)
            self.assertEqual(json.loads(self.req("GET", "/api/codes")[1])["codes"], [])
            with patched(os, startfile=lambda p: opened.append(p)) if hasattr(os, "startfile") else \
                    patched(subprocess, Popen=lambda a: opened.append(a[-1])):
                code, body = self.req("POST", "/api/open_folder", {"which": "job", "id": jid, "sub": "attach"})
                self.assertEqual(code, 200, body)
                self.assertEqual(self.req("POST", "/api/open_folder", {"which": "job", "id": jid, "sub": "../.."})[0], 400)
            self.assertEqual([Path(p) for p in opened], [d / "attach"])
        finally:
            srv.shutdown()
            srv.server_close()
            db.delete_job(jid)
            shutil.rmtree(d, ignore_errors=True)
            db._local.con = mem


class Ui(unittest.TestCase):
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    def fn(self, name):
        return re.search(rf"^(async )?function {name}\(.*?^}}", self.js, re.M | re.S).group(0)

    def node(self, code):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        esc = re.search(r"^const esc = .*$", self.js, re.M).group(0)
        kb = re.search(r"^const kb = .*$", self.js, re.M).group(0)
        r = subprocess.run([node, "-e", f"{esc}\n{kb}\n{code}"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_server_strings_render_as_text(self):
        bad = '<img src=x onerror=alert(1)>'
        m = {"id": 3, "job_id": 4, "direction": "in",
             "attachments": json.dumps([{"name": bad, "size": 10, "path": "x"}, {"name": bad, "skipped": bad}])}
        out = self.node(f"{self.fn('mailFiles')}\nprocess.stdout.write(mailFiles({json.dumps(m)}));")
        self.assertNotIn("<img", out)
        self.assertIn("Show in folder", out)
        box = "const els = {}; const $ = s => (els[s] = els[s] || {style: {}}); let CODES = [];"
        c = [{"id": "a", "code": bad, "domain": bad, "subject": bad, "expires_s": 600}]
        out = self.node(f"{box}\n{self.fn('codesPaint')}\ncodesPaint({json.dumps(c)}); process.stdout.write(els['#codesList'].innerHTML);")
        self.assertNotIn("<img", out)
        self.assertIn("Never read it out", out)
        r = {"id": 5, "job_id": 4, "payload": {"attachments": [bad], "unverified": True}}
        out = self.node(f"const ATT = {{}}, JFILES = {{4: [{{name: {json.dumps(bad)}, size: 5}}]}};\n{self.fn('attHtml')}\n"
                        f"process.stdout.write(attHtml({json.dumps(r)}));")
        self.assertNotIn("<img", out)
        self.assertIn("not verified", out)
        st = {"configured": True, "auth": "oauth", "oauth_provider": "google", "user": bad, "label": "Gmail",
              "imap_host": "h", "imap_port": 993, "smtp_host": "h", "smtp_port": 465, "smtp_mode": "ssl",
              "needs_signin": bad, "refresh_expires": "2026-11-16 10:00:00"}
        out = self.node(f"const EM = {{status: {json.dumps(st)}}}; const box = {{}}; const $ = () => box;\n"
                        f"{self.fn('emailLine')}\nemailLine(); process.stdout.write(box.innerHTML);")
        self.assertNotIn("<img", out)
        for want in ("Signed in with Google", "Sign-in expired", "Sign in again", "in Testing", "2026-11-16"):
            self.assertIn(want, out)

    def test_markup_rules(self):
        self.assertIn('target="_blank" rel="noopener">Open the sign-in page', self.fn("emailSigninLink"))
        self.assertNotIn("createObjectURL", self.js)
        self.assertNotIn("<iframe", self.js)
        for needle in ('id="eCsec" type="password" autocomplete="off"', 'id="codesPanel"', 'id="codesPill"', 'id="eCafile"',
                       "Other secrets (OS keyring)"):
            self.assertIn(needle, self.html)
        self.assertIn("attachments = ATT[id]", self.fn("decide"))


class Docs(unittest.TestCase):
    def test_connect_guide(self):
        from lodestar import mailconn, oauth

        text = (ROOT / "docs" / "CONNECT.md").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\]\((http://[^)]*)\)", text), [])  # links are https only
        for p in mailconn.PRESETS.values():
            self.assertIn(p["label"], text)
        for k in oauth.HINTS:
            self.assertIn(k, text)
        for n in ("lodestar keys link", "lodestar email client google", "lodestar email signin microsoft", "--cafile",
                  "app password", "Codes", "10 MB"):
            self.assertIn(n, text)
        commands = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        for n in ("lodestar keys", "email client", "email signin", "--cafile", "/api/codes", "/api/jobs/ID/files"):
            self.assertIn(n, commands)


if __name__ == "__main__":
    unittest.main()
