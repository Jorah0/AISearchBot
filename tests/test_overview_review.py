"""Overview review fixes (pass 16.1): a counter-offer may cite a competing figure that happens to equal the salary
floor, a rebuild keeps hand-typed education and certification lines, an edited answer naming the floor stays in the
Inbox, the provider allowlist ignores case, an empty vault entry is one line (and a blank key is refused), a
clashing interview slot is refused before the acceptance is sent, Save as watch keeps a saved search's keywords and
filters, a stray IMAP_HOST is named when it overrides the chosen provider, one follow-up at a time, Email digest says
where it went, one unreachable board is a note, not a failed run, and the main controls have names. No network: AI,
SMTP, IMAP and the keyring are faked and every patched attribute is put back."""
import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import (ai, apply, approvals, cli, config, db, drafts, interview, mailconn, profile, settings,  # noqa: E402
                      util, vault, web, web_monitor)
from lodestar.config import PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL = ("# Jane Example\n## Skills\nPython, SQL\n## Experience\n### Engineer - Acme (2020-01 - Present)\n- Built pipelines\n"
        "\n## Preferences\nSalary floor: $150,000 | Deal-breakers: none\n")


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


def env(**values):
    """setting() stand-in: only these values, never the real vault or environment."""
    return lambda k, d=None: values.get(k, d)


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH, vault.INDEX) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")
        self.sent = []

    def tearDown(self):
        c = getattr(db._local, "con", None)
        if c is not None:
            c.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH, vault.INDEX):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def send(self, to, subject, body, *a, **k):
        self.sent.append((to, subject, body))


class Counter(Base):  # code-counter-floor-collision
    def test_a_cited_offer_equal_to_the_floor_can_be_countered_but_the_ask_is_still_guarded(self):
        mine, other = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "Data Engineer")
        db.set_offer(mine, base=140000)
        db.set_offer(other, base=150000)
        for j in (mine, other):
            db.set_status(j, "offer")
        r = apply.counter(db.get_job(mine), [f"{other}:base"], template=True)  # was: SystemExit 'names your salary floor'
        self.assertEqual(r["proposal"]["status"], "draft_only")
        self.assertIn("a base salary of 150,000", r["draft"]["body"])
        with self.assertRaises(SystemExit):  # the ask is not a cited figure: still refused
            apply.counter(db.get_job(mine), [f"{other}:base"], "a base of $150,000", template=True)
        db.update_job(mine, contact_email="hr@acme.example")
        r = apply.counter(db.get_job(mine), [f"{other}:base"], template=True)
        pid = r["proposal"]["id"]
        self.assertEqual(json.loads(db.get_pending(pid)["payload"])["cited"], ["a base salary of 150,000"])
        approvals.edit(pid, body=r["draft"]["body"] + "\nThanks again.")  # an edit that keeps the citation is fine
        with self.assertRaises(SystemExit):
            approvals.edit(pid, body="I will not go below $150,000.")
        with patched(ai, available=lambda: []):  # no provider: the template, as the one option
            opts = drafts.options("counter", {"job": mine, "cite": [f"{other}:base"]})
        self.assertEqual(drafts.use("counter", {"job": mine, "cite": [f"{other}:base"]}, opts[0])["proposal"]["status"], "pending")
        with patched(approvals, send_email=self.send):
            self.assertEqual(approvals.approve(pid, {"subject": "Re: offer"})["status"], "done")
        self.assertEqual(len(self.sent), 1)


class Rebuild(Base):  # code-rebuild-drops-edu-certs
    def test_rebuild_keeps_education_and_certification_lines_without_keywords(self):
        profile.write_master(REAL.replace("## Preferences", "## Education\n- Stanford, Computer Science\n- Hogwarts\n\n"
                                          "## Certifications\n- Six Sigma Green Belt\n- Google Analytics\n\n## Preferences"))
        profile.rebuild_master()
        out = PROFILE.read_text(encoding="utf-8")
        for s in ("Stanford, Computer Science", "Hogwarts", "Six Sigma Green Belt", "Google Analytics", "Salary floor"):
            self.assertIn(s, out)
        profile.rebuild_master()
        self.assertEqual(PROFILE.read_text(encoding="utf-8").count("Hogwarts"), 1)
        li = "Contact\nx@y.io\nTop Skills\nKafka\nCertifications\nAWS Certified Data Engineer\nDana Example\n"
        self.assertEqual([c["name"] for c in profile.extract_heuristic(li)["certifications"]], ["AWS Certified Data Engineer"])


class AnswerEdit(Base):  # code-approve-save-answer-error
    def test_an_edited_answer_naming_the_floor_stays_pending(self):
        pid = approvals.propose("answers", "save_answer", {"question": "Q1?", "answer": "fine answer"}, "save", force_pending=True)["id"]
        with self.assertRaises(SystemExit):
            approvals.approve(pid, {"answer": "I need at least $150,000"})
        row = db.get_pending(pid)
        self.assertEqual((row["status"], row["decided_at"]), ("pending", None))
        self.assertEqual(approvals.approve(pid, {"answer": "Open to discussing it."})["status"], "done")


class Allowlist(Base):  # code-allowlist-case
    def test_a_mixed_case_allowlist_still_lets_its_provider_through(self):
        settings.set_pref("council_providers", "Anthropic, OpenAI")
        settings.set_pref("provider", "anthropic")
        with patched(ai, available=lambda: ["anthropic"], setting=env()):
            self.assertEqual(ai.default_provider(), "anthropic")
            self.assertEqual(ai.council_providers(), ["anthropic"])


class Vault(Base):  # code-vault-empty-traceback, live-3
    def test_blank_secret_is_refused_trimmed_and_the_cli_says_so_in_one_line(self):
        store = {}

        def boom(*a):
            raise AssertionError("keyring must not be written")
        with patched(vault.keyring, set_password=lambda s, n, v: store.__setitem__(n, v)):
            with self.assertRaises(ValueError):
                vault.set("X_API_KEY", "   ")
            vault.set("X_API_KEY", " sk-1 \n")
        self.assertEqual(store, {"X_API_KEY": "sk-1"})
        with patched(vault.keyring, set_password=boom), patched(cli.getpass, getpass=lambda *a: ""), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as e:  # not a ValueError traceback
                cli.main(["vault", "set", "ANTHROPIC_API_KEY"])
        self.assertIn("give both a name", str(e.exception.code))


class Clash(Base):  # live-1
    def test_a_clashing_slot_is_refused_before_the_reply_is_sent(self):
        acme, globex = db.add_job("Acme Robotics", "Engineer"), db.add_job("Globex", "Engineer")
        slot = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d 10:00")
        interview.log_round(acme, at=slot)
        mail = {"to": "rita@globex.com", "subject": "Re: interview", "body": "Tuesday 10:00 works", "job_id": globex,
                "chosen_time": None}
        pid = approvals.propose("email_reply", "send_email", mail, "reply", globex, force_pending=True)["id"]
        with patched(approvals, send_email=self.send):
            with self.assertRaises(SystemExit) as e:
                approvals.approve(pid, {"chosen_time": slot})
            self.assertIn("clashes with Acme Robotics", str(e.exception))
            self.assertEqual((self.sent, db.get_pending(pid)["status"]), ([], "pending"))
            settings.set_tool("email_reply", auto=True)  # on auto it waits in the Inbox instead
            r = approvals.propose("email_reply", "send_email", mail | {"chosen_time": slot}, "reply", globex)
            self.assertEqual((r["status"], self.sent), ("pending", []))
            self.assertEqual(approvals.approve(pid, {"chosen_time": None})["status"], "done")
        self.assertEqual(len(self.sent), 1)


class Followups(Base):  # live-5
    def test_one_follow_up_at_a_time_and_a_sent_one_closes_the_rest(self):
        jid = db.add_job("Initech", "Engineer")
        db.update_job(jid, contact_email="bob@initech.com", contact_name="Bob")
        a = apply.followup(db.get_job(jid), template=True)
        b = apply.followup(db.get_job(jid), template=True)
        self.assertEqual(b["proposal"]["id"], a["proposal"]["id"])
        self.assertIn("already waiting", b["proposal"]["reason"])
        pending = lambda: [r for r in db.con().execute("SELECT * FROM pending WHERE status='pending'")]  # noqa: E731
        self.assertEqual(len(pending()), 1)
        dup = approvals.propose("followup", "send_email", json.loads(pending()[0]["payload"]), "dup", jid, force_pending=True)
        with patched(approvals, send_email=self.send):
            approvals.approve(a["proposal"]["id"])
        self.assertEqual(db.get_pending(dup["id"])["status"], "rejected")
        self.assertEqual((len(self.sent), pending()), (1, []))


class Digest(Base):  # live-6
    def test_email_digest_says_where_it_went(self):
        with patched(ai, available=lambda: []), patched(config, setting=env(IMAP_USER="jordan@yahoo.com")), \
                patched(util, send_email=self.send):
            r = web._act("digest", {"days": 7, "send": True})
        self.assertEqual((r["sent_to"], self.sent[0][0]), ("jordan@yahoo.com", "jordan@yahoo.com"))
        html = (ROOT / "lodestar" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("'digest emailed to '+r.sent_to", html)


class PartialRun(Base):  # live-7
    def test_one_unreachable_board_is_a_note_and_the_run_still_alerts(self):
        db.add_watch("search:data engineer", "")

        def search(q, errors=None, **k):
            errors.append("remoteok: host unreachable")
            return [{"url": "https://e.co/1", "title": "DE", "company": "Hooli", "location": "Remote"}]
        with patched(web_monitor, search=search, _hits=lambda q, new: [j["url"] for j in new], SOURCES={"a": 1, "remoteok": 2}):
            alerts = web_monitor.check_watches()
        w = db.watches()[0]
        self.assertEqual(alerts, ["https://e.co/1"])
        self.assertTrue(w["last_error"].startswith("partial:"), w["last_error"])
        self.assertIsNotNone(w["last_seen"])
        js = (ROOT / "lodestar" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("'some boards unreachable'", js)


class MailHost(Base):  # live-4
    def test_a_stray_imap_host_is_named_when_it_overrides_the_preset(self):
        c = {"preset": "yahoo", "user": "j@yahoo.com", "imap_host": "imap.gmail.com", "imap_port": 993,
             "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_mode": "ssl", "smtp_user": "j@yahoo.com"}

        def refuse(c, pw):
            raise OSError("login failed")
        old = os.environ.get("IMAP_HOST")
        os.environ["IMAP_HOST"] = "imap.gmail.com"
        try:
            with patched(mailconn.util, mail_settings=lambda: dict(c)), patched(mailconn, setting=env(IMAP_PASS="pw"), _imap=refuse,
                                                                                _smtp=refuse), \
                    patched(vault, get=lambda n: {"IMAP_HOST": "imap.mail.yahoo.com"}.get(n), set=lambda *a, **k: None,
                            delete=lambda *a: None):
                r = mailconn.test()
                st = mailconn.status()
        finally:
            os.environ.pop("IMAP_HOST") if old is None else os.environ.__setitem__("IMAP_HOST", old)
        self.assertIn("IMAP_HOST=imap.gmail.com", r["hint"])
        self.assertIn("Yahoo Mail", r["hint"])
        self.assertEqual(len(st["conflicts"]), 1)


class Labels(unittest.TestCase):  # live-8, code-docs-count-digest
    def test_main_controls_have_names_and_the_digest_doc_matches(self):
        html = (ROOT / "lodestar" / "static" / "index.html").read_text(encoding="utf-8")
        for i in ("pText", "cMode", "cJob", "aJob", "iTopic", "iJob"):
            self.assertRegex(html, rf'id="{i}"[^>]*aria-label="[^"]+"')
        cmds = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        self.assertIn("connected mailbox", next(ln for ln in cmds.splitlines() if "digest" in ln and "--send" in ln))


class SaveSearch(unittest.TestCase):  # live-2, through the real route
    def setUp(self):
        from lodestar import desktop

        self._con = getattr(db._local, "con", None)
        db._local.con = None
        self.port = desktop.free_port(8890)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        db.release()
        db._local.con = self._con

    def call(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN,
                                                     "Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def test_save_as_watch_with_blank_fields_keeps_the_saved_keywords_and_filters(self):
        url = "search:data engineer review"
        db.add_watch(url, "python", {"location": "remote", "min_salary": 120000})
        try:
            st, r = self.call("/api/watches", {"search": True, "url": "data engineer review", "keywords": "", "location": "",
                                               "min_salary": "", "posted_within": "", "seniority": ""})
            self.assertEqual((st, r), (200, {"ok": True, "updated": True}))
            w = next(w for w in db.watches() if w["url"] == url)
            self.assertEqual((w["keywords"], db.watch_filters(w)), ("python", {"location": "remote", "min_salary": 120000}))
        finally:
            db.remove_watch(next(w for w in db.watches() if w["url"] == url)["id"])


if __name__ == "__main__":
    unittest.main()
