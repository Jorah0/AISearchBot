"""Connections pass 16.2, final review: one regression test per confirmed finding (code-1..5, live-1..3). No network
beyond 127.0.0.1 and no real keyring: the shared temp home, an in-memory keyring, fake IMAP/SMTP and a plaintext IMAP
listener on loopback. Every patched attribute is put back."""
import contextlib
import imaplib
import io
import os
import re
import socket
import threading
import unittest
from pathlib import Path
from urllib.robotparser import RobotFileParser

from test_connections_mail import FLOOR, Base, Box, mail_with, patched  # noqa: E402  (sets the temp home first)

from lodestar import codes, connections, db, email_monitor as em, extras, mailconn, mailfiles, oauth, util, vault, web  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "lodestar" / "static"
MAIL_ENV = ("EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", "EMAIL_AUTH", "EMAIL_VERIFIED", *oauth.STATE_KEYS, *oauth.CLIENT_KEYS,
            *mailconn.KEYS.values())


class MailBase(Base):
    """Base with the mail settings of a .env (the repo's or the shared home's) out of the way, put back afterwards."""

    def setUp(self):
        super().setUp()
        env = {n: os.environ.pop(n) for n in MAIL_ENV if n in os.environ}
        self.addCleanup(os.environ.update, env)


class ImapStartTLS(MailBase):  # code-1: Proton Mail Bridge serves IMAP on 1143 with STARTTLS by default
    def test_starttls_mode_sends_starttls_in_plain_text_before_any_tls(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port, lines = srv.getsockname()[1], []

        def bridge():  # a default Bridge: plaintext greeting, STARTTLS offered, then (here) no TLS at all
            c, _ = srv.accept()
            c.settimeout(5)
            f = c.makefile("rb")
            c.sendall(b"* OK [CAPABILITY IMAP4rev1 STARTTLS] Bridge ready\r\n")
            try:
                for _ in range(2):
                    line = f.readline()
                    lines.append(line)
                    tag = line.split(b" ")[0]
                    if b"CAPABILITY" in line:
                        c.sendall(b"* CAPABILITY IMAP4rev1 STARTTLS\r\n" + tag + b" OK done\r\n")
                    elif b"STARTTLS" in line:
                        c.sendall(tag + b" OK begin TLS\r\n")
            finally:
                c.close()
                srv.close()

        t = threading.Thread(target=bridge, daemon=True)
        t.start()
        with self.assertRaises(OSError):  # the fake has no TLS: the handshake fails, but only after STARTTLS
            util.imap_open("127.0.0.1", port, "starttls")
        t.join(5)
        self.assertTrue(lines and lines[-1].rstrip().endswith(b"STARTTLS"), lines)

    def test_proton_preset_stores_starttls_and_every_imap_site_uses_it(self):
        self.assertEqual(mailconn.PRESETS["proton"]["imap_mode"], "starttls")
        mailconn.connect("proton", "pat@proton.me", "bridge-pass-123")
        c = util.mail_settings()
        self.assertEqual((c["imap_mode"], c["imap_port"]), ("starttls", 1143))
        mailconn.connect("gmail", "pat@gmail.com", "abcdabcdabcdabcd")  # ssl is the default and is not stored
        self.assertEqual(util.mail_settings()["imap_mode"], "ssl")
        self.assertIsNone(vault.get("IMAP_MODE"))
        with self.assertRaises(SystemExit):
            mailconn.connect("custom", "pat@example.com", "x", imap_host="imap.example.com", smtp_host="smtp.example.com",
                             imap_mode="plain")
        mailconn.connect("proton", "pat@proton.me", "bridge-pass-123")
        opened = []

        class B(Box):
            def search(self, *a):
                return "OK", [b""]

        def rec(host, port, mode=None):
            opened.append((host, port, mode or vault.get("IMAP_MODE")))
            return B({})

        cfg = util.mail_settings()
        with patched(util, imap_open=rec, imap_login=lambda *a: None):
            mailconn._imap(cfg, "pw")
            em._scan("127.0.0.1", "pat@proton.me", "pw", 3, 50, True, None, 1143)
            codes.poll()
        self.assertEqual(opened, [("127.0.0.1", 1143, "starttls")] * 3)


class CodesNeverReachTheAI(MailBase):  # code-2: a sign-in code is masked before relevance, classification and storage
    CODE = "482913"

    def scan(self, m, cat="application_received"):
        prompts = []

        def classify(subject, sender, body, provider=None):
            prompts.append(subject + body)
            return {"category": cat, "company": self.company, "title": "Engineer", "summary": "s", "action": "none",
                    "deadline": None}

        with patched(imaplib, IMAP4_SSL=lambda host, **kw: Box({1: m.as_bytes()})), \
                patched(em, classify=classify, notify=lambda msg: None), contextlib.redirect_stdout(io.StringIO()):
            found = em._scan("imap.example.com", "me@example.com", "p", 3, 50, False, None)
        return prompts, found

    def test_a_code_mail_is_classified_with_the_code_masked_and_stored_masked(self):
        m = mail_with([], frm="Acme Careers <careers@acme.example>", subject="Sign in to your candidate account",
                      body=f"Use this verification code to sign in to your candidate account: {self.CODE}")
        prompts, found = self.scan(m)
        self.assertEqual([c["code"] for c in codes.current()], [self.CODE])  # still offered in the Codes panel
        self.assertTrue(prompts)  # hiring mail with a code is still classified and filed...
        self.assertNotIn(self.CODE, " ".join(prompts))  # ...but the AI never sees the code
        self.assertNotIn(self.CODE, repr(found))
        row = db.mail_by_message_id(m["Message-ID"])
        self.assertIsNotNone(row)
        self.assertNotIn(self.CODE, str(dict(row)))
        self.assertIn("******", str(dict(row)))

    def test_an_expired_or_unauthenticated_code_is_masked_too(self):
        m = mail_with([], frm="Acme Careers <careers@acme.example>", subject="Your application login code",
                      body=f"Your login code is {self.CODE}", auth="")  # no DKIM: never offered, still never sent
        m.replace_header("Date", "Mon, 02 Nov 2026 10:00:00 +0000")
        prompts, found = self.scan(m)
        self.assertEqual(codes.current(), [])
        self.assertNotIn(self.CODE, " ".join(prompts) + repr(found))

    def test_mask_leaves_ordinary_numbers(self):
        self.assertEqual(codes.mask("Interview", "Call 555-123-4567. Order #123456 shipped. Code: 7F3K9Q"),
                         ("Interview", "Call 555-123-4567. Order #123456 shipped. Code: ******"))


class WikipediaApi(unittest.TestCase):  # code-3: Wikipedia's robots.txt has Disallow: /api/ for every crawler
    ROBOTS = "User-agent: *\nAllow: /w/api.php?action=mobileview&\nAllow: /api/rest_v1/?doc\nDisallow: /w/\nDisallow: /api/\n"

    def test_the_wikimedia_rest_api_is_read_although_robots_txt_disallows_api(self):
        rp = RobotFileParser()
        rp.parse(self.ROBOTS.splitlines())
        self.assertFalse(rp.can_fetch("lodestar", "https://en.wikipedia.org/api/rest_v1/page/summary/Acme"))  # the rule
        got, prompt = [], []

        def fetch(u, timeout=20, **kw):
            got.append(u)
            if u.endswith("/robots.txt"):
                return self.ROBOTS if "wikipedia" in u else "User-agent: *\nDisallow: /\n"
            if "wikipedia" in u:
                return '{"extract": "Acme makes anvils.", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Acme"}}}'
            raise AssertionError(f"robots.txt said no: {u}")

        job = {"id": 1, "company": "Acme", "title": "Engineer", "url": "https://acme.example/jobs/1"}
        from lodestar import resume

        with patched(util, fetch=fetch), patched(extras.ai, ask=lambda p, **k: prompt.append(p) or "pack"), \
                patched(extras, _job_dir=lambda j: Path(self._tmp()) / "job"), \
                patched(resume, candidate_text=lambda *a, **k: "Jane Doe, Python"):
            extras.research(job)
        self.assertIn("Acme makes anvils.", prompt[0])
        self.assertNotIn("SKIPPED https://en.wikipedia.org", prompt[0])
        self.assertIn("SKIPPED https://acme.example/jobs/1: robots.txt", prompt[0])  # every other source still asks
        self.assertNotIn("https://en.wikipedia.org/robots.txt", got)

    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp(prefix="lodestar-research-")
        self.addCleanup(__import__("shutil").rmtree, d, True)
        return d


class ChunkedVault(Base):  # code-4: a crash mid-write or a lost index never yields a mixed or truncated secret
    def test_crash_before_the_head_keeps_the_old_secret_whole(self):
        old, new = "A" * 2500, "B" * 1500
        vault.set("OAUTH_REFRESH", old)
        real = vault.keyring.set_password

        def crash(svc, name, v):
            if name == "OAUTH_REFRESH":
                raise RuntimeError("power cut")
            real(svc, name, v)

        with patched(vault.keyring, set_password=crash), self.assertRaises(RuntimeError):
            vault.set("OAUTH_REFRESH", new)
        self.assertEqual(vault.get("OAUTH_REFRESH"), old)
        vault.set("OAUTH_REFRESH", new)
        with patched(vault, _save_index=lambda idx: (_ for _ in ()).throw(OSError("disk full"))), self.assertRaises(OSError):
            vault.set("OAUTH_REFRESH", "C" * 2200)  # head written, index not: the head alone describes the secret
        self.assertEqual(vault.get("OAUTH_REFRESH"), "C" * 2200)

    def test_a_corrupt_index_or_a_swapped_piece_never_reads_as_a_secret(self):
        vault.set("OAUTH_REFRESH", "D" * 2500)
        vault.INDEX.write_text("{corrupt")
        self.assertEqual(vault.get("OAUTH_REFRESH"), "D" * 2500)  # the count lives in the head, not the index
        piece = next(k for k in self.store if k[1].startswith("OAUTH_REFRESH~"))
        self.store[piece] = "E" * len(self.store[piece])
        self.assertIsNone(vault.get("OAUTH_REFRESH"))  # the hash catches a mixed piece
        vault.delete("OAUTH_REFRESH")
        self.assertFalse([k for k in self.store if k[1].startswith("OAUTH_REFRESH")])
        self.assertFalse(vault.INDEX.with_suffix(".tmp").exists())  # the index is replaced atomically


class KeyDocs(unittest.TestCase):  # code-5: CONNECT.md says what the code does
    def test_rate_limit_row_and_loopback_listeners_match_the_code(self):
        from email.message import Message
        from unittest import mock

        from lodestar import connections as conn

        err = conn.urllib.error.HTTPError("https://api.example.com", 429, "Too Many Requests", Message(), io.BytesIO(b"{}"))
        with mock.patch.object(conn, "urlopen", side_effect=err), mock.patch.object(conn.ai, "api_key", return_value="sk-ant-x"):
            self.assertEqual(conn.verify_key("anthropic")["status"], "failed")  # what the docs must say for a 429
        doc = (ROOT / "docs" / "CONNECT.md").read_text(encoding="utf-8")
        rows = {r.split("|")[1].strip(): r for r in doc.splitlines() if r.startswith("| ")}
        self.assertIn("rate limit", rows["Failed (quota or rate limit)"])
        self.assertNotIn("rate limit", rows["Couldn't reach, will retry"])
        listener = next(p for p in doc.split("\n- ") if "sign-in listener" in p)
        self.assertIn("::1", listener)
        self.assertNotIn("127.0.0.1 only", doc)


class EmailGuess(unittest.TestCase):  # live-1: every inline handler names a function app.js defines
    JS_NAMES = {"if", "return", "event", "this", "confirm", "alert", "Number", "String", "parseInt", "encodeURIComponent",
                "Boolean", "Math", "await", "window", "location", "history", "document", "setTimeout", "navigator", "fetch",
                "$", "$$", "includes", "open"}

    def test_every_inline_handler_is_defined(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        defined = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", js)) | set(
            re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", js)) | set(re.findall(r"window\.(\w+)\s*=", js))
        missing = set()
        for src in (html, js):
            for h in re.findall(r'\bon[a-z]+="([^"]*)"', src):
                h = re.sub(r"\$\{[^}]*\}", "0", h)  # a template value (app.js builds handlers in `...`) is data
                h = re.sub(r"'(?:[^'\\]|\\.)*'", "''", h)  # so is a quoted string ('relevant email(s)')
                for name in re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(", h):
                    if name not in defined and name not in self.JS_NAMES:
                        missing.add(name)
        self.assertEqual(missing, set())
        self.assertIn('onchange="emailGuess()"', html)

    def test_email_guess_picks_the_preset_from_the_domain(self):
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        body = js[js.index("function emailGuess"):js.index("function emailPreset")]
        self.assertIn("if (!EM) return", body)
        self.assertIn(".domains", body)
        self.assertIn("emailPreset()", body)
        self.assertIn("outlook.com", mailconn.PRESETS["outlook"]["domains"])


class StoredMailCheck(MailBase):  # live-2: any successful test replaces a stored failure; disconnect hides it
    def fake_servers(self):
        class IMAP:
            def __init__(self, *a, **k):
                pass

            def login(self, u, p):
                pass

            def select(self, *a, **k):
                return "OK", [b"0"]

            def search(self, *a):
                return "OK", [b""]

            def logout(self):
                pass

        class SMTP:
            def __init__(self, *a, **k):
                pass

            def login(self, u, p):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        stack = contextlib.ExitStack()
        stack.enter_context(patched(imaplib, IMAP4_SSL=IMAP))
        stack.enter_context(patched(util.smtplib, SMTP_SSL=SMTP))
        return stack

    def test_a_passing_test_or_sign_in_clears_the_stale_failure(self):
        mailconn.connect("gmail", "pat@gmail.com", "abcdabcdabcdabcd")
        fpr = mailconn._fingerprint(util.mail_settings())
        connections.record("mail", None, {"status": "failed", "detail": "Your Google sign-in has expired"}, fpr)
        self.assertIn("expired", web.setup_status()["email_problem"])
        with self.fake_servers():
            mailconn.test()  # what /api/email/test, /api/email/connect's test and the email_signin task all run
        self.assertEqual(web.setup_status()["email_problem"], "")
        self.assertEqual(connections.status()["mail"]["status"], "verified")
        connections.record("mail", None, {"status": "failed", "detail": "stale"}, fpr)
        with self.fake_servers(), patched(oauth, signin=lambda *x, **k: {"ok": True}):
            out = web._act("email_signin", {"provider": "google"})
        self.assertTrue(out["test"]["imap"]["ok"])
        self.assertEqual(web.setup_status()["email_problem"], "")

    def test_disconnect_hides_the_old_result(self):
        mailconn.connect("gmail", "pat@gmail.com", "abcdabcdabcdabcd")
        connections.record("mail", None, {"status": "failed", "detail": "refused"},
                           mailconn._fingerprint(util.mail_settings()))
        mailconn.disconnect()
        self.assertEqual(connections.status()["mail"], {"status": "unchecked"})
        self.assertEqual(web.setup_status()["email_problem"], "")


class BlockedAttachments(Base):  # live-3: the Inbox list flags a file the salary-floor guard always refuses
    def test_attachable_flags_a_floor_naming_cover_letter(self):
        self.put("cover_letter.pdf")
        self.put("cover_letter.md", f"Dear team, my salary floor is {FLOOR}.".encode())
        self.put("resume.pdf")
        self.put("resume.md", b"# Jane Doe\nPython")
        rows = {r["name"]: r for r in mailfiles.attachable(self.job)}
        self.assertIn("salary floor", rows["cover_letter.pdf"]["blocked"])
        self.assertNotIn("blocked", rows["resume.pdf"])
        with self.assertRaises(SystemExit):
            mailfiles.resolve(self.job, ["cover_letter.pdf"])  # the same rule
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("f.blocked ?", js)
        self.assertIn("!f.blocked", js[js.index("function attAdd"):][:200])


if __name__ == "__main__":
    unittest.main()
