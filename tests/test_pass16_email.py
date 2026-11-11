"""Pass 16, builder 1: connecting the mailbox. Provider presets, stored settings, STARTTLS vs implicit TLS, login error
hints, the password never leaving the keyring, test sends only to yourself, token-protected routes, the CLI and doctor.
No network and no real keyring: imaplib, smtplib and keyring are faked; every patched attribute is put back."""
import contextlib
import http.client
import imaplib
import io
import json
import os
import smtplib
import socket
import ssl
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, doctor, extras, mailconn, util, vault  # noqa: E402
from lodestar.config import HOME  # noqa: E402

PW = "abcdefghijklmnop"
STATIC = Path(__file__).resolve().parent.parent / "lodestar" / "static"
ENV = ("EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", *mailconn.KEYS.values())


class Mail(unittest.TestCase):
    """An in-memory keyring, a fake IMAP server and fake SMTP servers that record what was asked of them."""

    def setUp(self):
        self.store, self.log, self.sent, self.imap_fail = {}, [], [], None
        k, t = vault.keyring, self

        def delete(svc, name):
            if (svc, name) not in self.store:
                raise k.errors.PasswordDeleteError("not there")
            del self.store[(svc, name)]

        class IMAP:
            def __init__(self, host, port=993, **kw):
                t.log.append(("imap", host, port, kw.get("timeout"), isinstance(kw.get("ssl_context"), ssl.SSLContext)))

            def login(self, user, pw):
                if t.imap_fail:
                    raise t.imap_fail
                t.log.append(("imap-login", user, pw))

            def select(self, box, readonly=False):
                t.log.append(("select", box, readonly))
                return "OK", [b"3"]

            def search(self, charset, crit):
                return "OK", [b"1 2 3"]

            def uid(self, op, *a):
                return "OK", [b""]

            def logout(self):
                pass

        class SMTP:
            kind = "smtp"

            def __init__(self, host, port, context=None, timeout=None):
                t.log.append((self.kind, host, port, timeout))

            def starttls(self, context=None):
                t.log.append(("starttls", isinstance(context, ssl.SSLContext)))

            def login(self, user, pw):
                t.log.append(("smtp-login", user, pw))

            def send_message(self, m):
                t.sent.append(m)

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        class SMTPSSL(SMTP):
            kind = "smtp_ssl"

        self.real = (k.get_password, k.set_password, k.delete_password, vault._index(),
                     imaplib.IMAP4_SSL, smtplib.SMTP, smtplib.SMTP_SSL)
        self.env = {n: os.environ.pop(n) for n in ENV if n in os.environ}
        k.get_password = lambda svc, name: self.store.get((svc, name))
        k.set_password = lambda svc, name, v: self.store.__setitem__((svc, name), v)
        k.delete_password = delete
        imaplib.IMAP4_SSL, smtplib.SMTP, smtplib.SMTP_SSL = IMAP, SMTP, SMTPSSL

    def tearDown(self):
        k = vault.keyring
        k.get_password, k.set_password, k.delete_password, idx, imaplib.IMAP4_SSL, smtplib.SMTP, smtplib.SMTP_SSL = self.real
        vault._save_index(idx)
        os.environ.update(self.env)

    def stored(self, name):
        return self.store.get((vault.SERVICE, name))


class Presets(Mail):
    def test_every_supported_preset_is_complete(self):
        for k, p in mailconn.PRESETS.items():
            if k in ("outlook", "custom"):
                continue
            self.assertTrue(p["imap_host"] and p["smtp_host"] and p["steps"] and p["help"].startswith("https://"), k)
            if k == "proton":  # Proton Mail Bridge listens on its own local ports (pass 17 preset)
                self.assertEqual((p["imap_host"], p["imap_port"], p["smtp_port"]), ("127.0.0.1", 1143, 1025))
                continue
            self.assertEqual((p["imap_port"], {"ssl": 465, "starttls": 587}[p["smtp_mode"]]), (993, p["smtp_port"]), k)
        self.assertEqual((mailconn.PRESETS["icloud"]["smtp_host"], mailconn.PRESETS["icloud"]["smtp_mode"]), ("smtp.mail.me.com", "starttls"))
        self.assertEqual([mailconn.guess(a) for a in ("a@gmail.com", "a@ME.com", "a@hotmail.com", "a@example.com")],
                         ["gmail", "icloud", "outlook", ""])

    def test_outlook_is_refused_with_the_reason(self):
        with self.assertRaises(SystemExit) as e:
            mailconn.connect("outlook", "me@outlook.com", PW)
        self.assertIn("OAuth", str(e.exception))
        self.assertEqual(self.store, {})


class Connect(Mail):
    def test_connect_stores_settings_and_nothing_returns_the_password(self):
        st = mailconn.connect("gmail", "me@example.com", "abcd efgh ijkl mnop")
        self.assertEqual(self.stored("IMAP_PASS"), PW)                    # Google's grouped display, spaces dropped
        self.assertTrue(st["configured"])
        self.assertEqual((st["imap_host"], st["smtp_port"], st["smtp_mode"], st["smtp_user"]), ("imap.gmail.com", 465, "ssl", "me@example.com"))
        self.assertNotIn(PW, json.dumps(st))
        st = mailconn.connect("gmail", "me@example.com")                   # no password, same servers: the stored one stays
        self.assertEqual((st["configured"], self.stored("IMAP_PASS")), (True, PW))
        st = mailconn.connect("icloud", "me@example.com")                  # other servers: the Gmail password is dropped
        self.assertEqual((st["smtp_host"], st["smtp_port"], st["smtp_mode"], self.stored("IMAP_PASS")), ("smtp.mail.me.com", 587, "starttls", None))
        with self.assertRaises(SystemExit):
            mailconn.connect("custom", "me@example.com")                   # custom needs its servers
        with self.assertRaises(SystemExit):
            mailconn.connect("custom", "me@example.com", imap_host="imap.example.com", smtp_host="smtp.example.com", smtp_port="99999")
        with self.assertRaises(SystemExit):
            mailconn.connect("gmail", "not an address", PW)
        st = mailconn.connect("custom", "me@example.com", "pass word", imap_host="imap.example.com", smtp_host="smtp.example.com",
                              smtp_mode="starttls", smtp_user="login-name")
        self.assertEqual((st["smtp_port"], st["smtp_user"], self.stored("IMAP_PASS")), (587, "login-name", "pass word"))
        st = mailconn.disconnect()
        self.assertEqual((st["configured"], self.stored("IMAP_PASS"), st["imap_host"]), (False, None, "imap.example.com"))


class Transport(Mail):
    def test_icloud_uses_starttls_on_587_and_gmail_implicit_tls_on_465(self):
        mailconn.connect("icloud", "me@example.com", PW)
        r = mailconn.test()
        self.assertTrue(r["imap"]["ok"] and r["smtp"]["ok"], r)
        self.assertIn("3 message(s)", r["imap"]["detail"])
        self.assertEqual(self.log, [("imap", "imap.mail.me.com", 993, util.MAIL_TIMEOUT, True), ("imap-login", "me@example.com", PW),
                                    ("select", "INBOX", True), ("smtp", "smtp.mail.me.com", 587, util.MAIL_TIMEOUT),
                                    ("starttls", True), ("smtp-login", "me@example.com", PW)])
        self.assertEqual(self.sent, [])                                    # a test logs in, it never sends
        self.log.clear()
        mailconn.connect("gmail", "me@example.com", PW)  # new servers need the password again (pass 16 review)
        mailconn.test()
        self.assertEqual([x for x in self.log if x[0].startswith("smtp") or x[0] == "starttls"],
                         [("smtp_ssl", "smtp.gmail.com", 465, util.MAIL_TIMEOUT), ("smtp-login", "me@example.com", PW)])

    def test_only_a_passing_test_counts_as_connected(self):
        from lodestar import web

        mailconn.connect("gmail", "me@example.com", PW)
        self.assertFalse(mailconn.status()["verified"])                   # saved, never tested
        self.imap_fail = imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
        mailconn.test()
        self.assertFalse(mailconn.status()["verified"])                   # refused sign-in
        self.assertFalse(web.setup_status()["email_ready"])
        self.imap_fail = None
        mailconn.test()
        self.assertTrue(mailconn.status()["verified"])
        self.assertTrue(web.setup_status()["email_ready"])
        mailconn.connect("gmail", "me@example.com", PW)                    # any reconnect needs its own passing test
        self.assertFalse(mailconn.status()["verified"])
        mailconn.test()
        mailconn.disconnect()
        self.assertFalse(mailconn.status()["verified"])

    def test_sent_mail_has_message_id_and_date(self):
        mailconn.connect("fastmail", "me@example.com", PW)
        mid = util.send_email("you@example.com", "hi", "body", in_reply_to="<x@example.com>")
        m = self.sent[0]
        self.assertEqual((m["Message-ID"], m["To"], m["From"], m["In-Reply-To"]), (mid, "you@example.com", "me@example.com", "<x@example.com>"))
        self.assertTrue(mid.startswith("<") and mid.endswith("@example.com>") and m["Date"])

    def test_the_monitor_reads_the_configured_imap_port(self):
        from lodestar import email_monitor as em
        mailconn.connect("custom", "me@example.com", PW, imap_host="imap.example.com", imap_port="1993", smtp_host="smtp.example.com")
        real = em.classify
        em.classify = lambda *a, **k: {"category": "other"}
        try:
            em.check(days=1, dry=True)
        finally:
            em.classify = real
        self.assertEqual(self.log[0][:3], ("imap", "imap.example.com", 1993))


class Hints(Mail):
    def test_errors_become_plain_next_steps(self):
        c = util.mail_settings() | {"preset": "gmail"}
        auth = mailconn.hint(imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)"), c)
        self.assertIn("app password", auth)
        self.assertIn("2-Step Verification", auth)
        self.assertIn("2-Step", mailconn.hint(smtplib.SMTPAuthenticationError(534, b"5.7.9 Application-specific password required"), c))
        self.assertIn("app password", mailconn.hint(smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted"), c))
        self.assertIn("IMAP access is turned off", mailconn.hint(imaplib.IMAP4.error(b"[ALERT] Your account is not enabled for IMAP use."), c))
        self.assertIn("host names", mailconn.hint(socket.gaierror(11001, "getaddrinfo failed"), c))
        self.assertIn("did not answer", mailconn.hint(TimeoutError("timed out"), c))
        self.assertIn("port or mode", mailconn.hint(ssl.SSLError(1, "WRONG_VERSION_NUMBER"), c))
        self.assertIn("certificate", mailconn.hint(ssl.SSLCertVerificationError(1, "hostname mismatch"), c))

    def test_a_dropped_connection_is_not_a_refused_password(self):  # IMAP4.abort is an IMAP4.error (found by the E2E suite)
        for preset in ("gmail", "fastmail", "custom"):
            h = mailconn.hint(imaplib.IMAP4.abort("socket error: EOF"), util.mail_settings() | {"preset": preset})
            self.assertIn("dropped the connection", h)
            self.assertNotIn("refused", h)

    def test_a_refused_login_reports_the_hint_and_hides_the_password(self):
        mailconn.connect("yahoo", "me@example.com", PW)
        self.imap_fail = imaplib.IMAP4.error(f"AUTHENTICATIONFAILED for {PW}")
        r = mailconn.test()
        self.assertFalse(r["imap"]["ok"])
        self.assertTrue(r["smtp"]["ok"])
        self.assertIn("login.yahoo.com", r["hint"])
        self.assertNotIn(PW, json.dumps(r))


class TestSend(Mail):
    def test_a_test_email_only_goes_to_your_own_address(self):
        mailconn.connect("gmail", "me@example.com", PW)
        with self.assertRaises(SystemExit):
            mailconn.test_send("someone@example.com")
        self.assertEqual((self.sent, self.log), ([], []))
        r = mailconn.test_send("ME@example.com")
        self.assertEqual((r["to"], self.sent[0]["To"], r["message_id"]), ("me@example.com", "me@example.com", self.sent[0]["Message-ID"]))


class Routes(Mail):
    def req(self, method, path, body=None, token=True):
        from lodestar import web
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}", "X-Lodestar-Token": web.TOKEN if token else "no"}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = (r.status, r.read().decode())
        c.close()
        return out

    def test_routes_need_the_token_and_never_return_the_password(self):
        from lodestar import desktop, web
        self.port = desktop.free_port(8970)
        srv = web.start_server(self.port)
        try:
            for method, path in (("GET", "/api/email/status"), ("POST", "/api/email/connect"), ("POST", "/api/email/test"),
                                 ("POST", "/api/email/test_send"), ("POST", "/api/email/disconnect")):
                self.assertEqual(self.req(method, path, {} if method == "POST" else None, token=False)[0], 403, path)
            self.assertEqual(self.store, {})
            code, body = self.req("POST", "/api/email/connect", {"preset": "gmail", "user": "me@example.com", "password": PW})
            self.assertEqual((code, json.loads(body)["configured"]), (200, True))
            for method, path in (("GET", "/api/email/status"), ("GET", "/api/state"), ("POST", "/api/email/test")):
                code, body = self.req(method, path, {} if method == "POST" else None)
                self.assertEqual(code, 200, body)
                self.assertNotIn(PW, body)
            self.assertIn("presets", json.loads(self.req("GET", "/api/email/status")[1]))
            code, body = self.req("POST", "/api/email/test_send", {"to": "other@example.com"})
            self.assertEqual((code, self.sent), (400, []))
            code, body = self.req("POST", "/api/email/disconnect", {})
            self.assertEqual((code, json.loads(body)["configured"], self.stored("IMAP_PASS")), (200, False, None))
        finally:
            srv.shutdown()
        html, js = (STATIC / "index.html").read_text(encoding="utf-8"), (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="ePass" type="password" autocomplete="off"', html)
        self.assertIn("loadEmail()", js)


class CliDoctorBackup(Mail):
    def test_cli_connect_prompts_without_echo_and_prints_no_password(self):
        real = cli.getpass.getpass
        cli.getpass.getpass = lambda prompt="": PW
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli.main(["email", "connect", "--user", "me@example.com"])  # preset guessed: example.com is unknown -> custom
        except SystemExit as e:
            self.assertIn("host", str(e))
        finally:
            cli.getpass.getpass = real
        cli.getpass.getpass = lambda prompt="": PW
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli.main(["email", "connect", "--preset", "zoho", "--user", "me@example.com"])
                cli.main(["email", "status"])
        finally:
            cli.getpass.getpass = real
        self.assertEqual(self.stored("IMAP_PASS"), PW)
        self.assertIn("imap.zoho.com", out.getvalue())
        self.assertIn("IMAP  ok", out.getvalue())
        self.assertNotIn(PW, out.getvalue())

    def test_doctor_reports_the_server_and_live_logs_in_once_each(self):
        self.assertEqual(doctor.live_mail(), [])
        mailconn.connect("aol", "me@example.com", PW)
        row = next(r for r in doctor.checks() if r[1] == "email")
        self.assertEqual(row[0], "ok")
        self.assertIn("imap.aol.com:993", row[2])
        self.assertEqual([r[:2] for r in doctor.live_mail()], [("ok", "live IMAP login"), ("ok", "live SMTP login")])
        self.assertEqual([x[0] for x in self.log].count("imap-login") + [x[0] for x in self.log].count("smtp-login"), 2)

    def test_backups_leave_out_env_files(self):
        env = HOME / ".env"
        had = env.read_bytes() if env.is_file() else None
        env.write_text("IMAP_PASS=" + PW + "\n", encoding="utf-8")
        out = Path(tempfile.mkdtemp(prefix="lodestar-bak-"))
        try:
            with zipfile.ZipFile(extras.backup(out)) as z:
                self.assertNotIn(".env", [Path(n).name for n in z.namelist()])
        finally:
            env.write_bytes(had) if had is not None else env.unlink()


if __name__ == "__main__":
    unittest.main()
