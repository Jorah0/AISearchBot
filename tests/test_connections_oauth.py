"""Connections pass, builder B: Google and Microsoft sign-in (authorization code + PKCE through a one-shot loopback
listener), refresh and revoke, XOAUTH2 for IMAP and SMTP, the chunked keyring vault, the new presets, routes, CLI and
doctor. No network beyond 127.0.0.1: a fake OAuth token server runs in the test, IMAP/SMTP and the keyring are faked
(the fake keyring refuses blobs over 1280 characters, like Windows), and every patched attribute is put back."""
import base64
import contextlib
import copy
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
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, doctor, email_monitor, mailconn, oauth, util, vault  # noqa: E402
from lodestar.config import HOME  # noqa: E402

GID = "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
GSECRET = "GOCSPX-testsecret0123456789"
MSID = "1b2c3d4e-0000-4000-8000-123456789abc"
ACCESS = "ya29.ACCESS-TOKEN-SECRET-0123456789"
ACCESS2 = "ya29.SECOND-ACCESS-TOKEN-0123456789"
REFRESH = "1//REFRESH-TOKEN-SECRET-0123456789"
CODE = "4/CODE-SECRET-0123456789"
PW = "abcdefghijklmnop"
ME = "me@example.com"
ENV = ("EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", "EMAIL_AUTH", "EMAIL_VERIFIED", *oauth.STATE_KEYS, *oauth.CLIENT_KEYS,
       *mailconn.KEYS.values())


def jwt(claims: dict) -> str:
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{b({'alg': 'RS256'})}.{b(claims)}.c2ln"


class TokenServer:
    """The provider's token and revoke endpoints on 127.0.0.1: records every form it is sent."""

    def __init__(self, reply):
        self.requests, self.reply, self.delay, t = [], reply, 0, self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
                t.requests.append((self.path, form))
                time.sleep(t.delay)
                code, body = t.reply(self.path, form)
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def grants(self, kind):
        return [f for p, f in self.requests if f.get("grant_type") == kind]


class Base(unittest.TestCase):
    def setUp(self):
        self.store, self.log, self.sent = {}, [], []
        self.imap_reject, self.smtp_reject = 0, 0
        k, t = vault.keyring, self

        def set_password(svc, name, v):
            if len(v) > 1280:  # Windows Credential Manager: 2560 bytes of UTF-16
                raise k.errors.PasswordSetError("blob too large")
            self.store[(svc, name)] = v

        def delete(svc, name):
            if (svc, name) not in self.store:
                raise k.errors.PasswordDeleteError("not there")
            del self.store[(svc, name)]

        class IMAP:
            def __init__(self, host, port=993, **kw):
                t.log.append(("imap", host, port))

            def login(self, user, pw):
                t.log.append(("imap-login", user, pw))

            def authenticate(self, mech, cb):
                first = cb(b"")
                t.log.append(("imap-auth", mech, first.decode() if isinstance(first, bytes) else first))
                if t.imap_reject:
                    t.imap_reject -= 1
                    t.log.append(("imap-challenge", cb(b'{"status":"401"}')))
                    raise imaplib.IMAP4.error("AUTHENTICATE failed")
                return "OK", [b""]

            def select(self, box, readonly=False):
                return "OK", [b"3"]

            def search(self, charset, crit):
                return "OK", [b"1 2 3"]

            def uid(self, op, *a):
                return "OK", [b""]

            def logout(self):
                pass

        class SMTP:
            def __init__(self, host, port, context=None, timeout=None):
                t.log.append(("smtp", host, port))

            def starttls(self, context=None):
                t.log.append(("starttls",))

            def ehlo_or_helo_if_needed(self):
                t.log.append(("ehlo",))

            def login(self, user, pw):
                t.log.append(("smtp-login", user, pw))

            def auth(self, mech, obj, initial_response_ok=True):
                t.log.append(("smtp-auth", mech, obj(), obj(b"challenge"), initial_response_ok))
                if t.smtp_reject:
                    t.smtp_reject -= 1
                    raise smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")
                return 235, b"ok"

            def send_message(self, m):
                t.sent.append(m)

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        self.real = (k.get_password, k.set_password, k.delete_password, vault._index(), imaplib.IMAP4_SSL, smtplib.SMTP,
                     smtplib.SMTP_SSL, copy.deepcopy(oauth.PROVIDERS), oauth.webbrowser.open)
        self.env = {n: os.environ.pop(n) for n in ENV if n in os.environ}
        k.get_password = lambda svc, name: self.store.get((svc, name))
        k.set_password, k.delete_password = set_password, delete
        imaplib.IMAP4_SSL, smtplib.SMTP, smtplib.SMTP_SSL = IMAP, SMTP, SMTP
        vault._save_index({})
        self.claims = {"iss": "https://accounts.google.com", "aud": GID, "exp": time.time() + 3600, "email": ME,
                       "email_verified": True}
        self.extra = {}
        self.srv = TokenServer(self.reply)
        for p in ("google", "microsoft"):
            oauth.PROVIDERS[p]["token"] = self.srv.base + ("/token" if p == "google" else "/{tenant}/token")
        oauth.PROVIDERS["google"]["revoke"] = self.srv.base + "/revoke"
        oauth.webbrowser.open = lambda url: self.fail("a test must never open the real browser")

    def tearDown(self):
        k = vault.keyring
        (k.get_password, k.set_password, k.delete_password, idx, imaplib.IMAP4_SSL, smtplib.SMTP, smtplib.SMTP_SSL,
         provs, oauth.webbrowser.open) = self.real
        oauth.PROVIDERS.clear()
        oauth.PROVIDERS.update(provs)
        vault._save_index(idx)
        os.environ.update(self.env)
        oauth._TOKEN.clear()
        oauth.PENDING.clear()
        oauth._CURRENT = None
        self.srv.close()

    def reply(self, path, form):
        if path == "/revoke":
            return 200, {}
        if form.get("grant_type") == "refresh_token":
            return 200, {"access_token": ACCESS2, "expires_in": 3599, "token_type": "Bearer"}
        return 200, {"access_token": ACCESS, "expires_in": 3599, "refresh_token": REFRESH, "id_token": jwt(self.claims),
                     "token_type": "Bearer"} | self.extra

    def stored(self, name):
        return vault.get(name)

    def browser(self, url, **extra):
        """The user's browser: the provider says yes and sends it back to the redirect URI."""
        self.auth_url = url
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.auth_q = q
        u = urlsplit(q["redirect_uri"])  # like a browser: no proxy, and an empty path is "/"
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
        c.request("GET", (u.path or "/") + "?" + urlencode({"code": CODE, "state": q["state"]} | extra))
        self.browser_status = c.getresponse().status
        c.close()

    def google(self, **kw):
        oauth.set_client("google", GID, GSECRET)
        return oauth.signin("google", open_browser=self.browser, **kw)

    def microsoft(self, tid=oauth.MSA_TID, **kw):
        oauth.set_client("microsoft", MSID)
        self.claims = {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "aud": MSID, "exp": time.time() + 3600,
                       "preferred_username": ME, "tid": tid}
        return oauth.signin("microsoft", open_browser=self.browser, **kw)

    def signed_in(self, provider="google"):
        """A stored Google sign-in without going through the browser."""
        oauth.set_client(provider, GID if provider == "google" else MSID, GSECRET if provider == "google" else None)
        vault.set("OAUTH_REFRESH", REFRESH)
        vault.set("OAUTH_PROVIDER", provider)
        vault.set("EMAIL_AUTH", "oauth")
        mailconn.connect_oauth("gmail" if provider == "google" else "outlook", ME)


def get(port, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
    r = c.getresponse()
    out = (r.status, r.read().decode())
    c.close()
    return out


class SignIn(Base):
    def test_pkce_and_the_sign_in_urls(self):
        v, ch = oauth.pkce()
        self.assertTrue(43 <= len(v) <= 128 and set(v) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"))
        import hashlib
        self.assertEqual(ch, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode())
        oauth.set_client("google", GID, GSECRET)
        oauth.set_client("microsoft", MSID)
        url, redirect = oauth.auth_url("google", 5555, "st8", ch, login_hint=ME)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        self.assertTrue(url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
        self.assertEqual((redirect, q["redirect_uri"], q["code_challenge_method"], q["code_challenge"], q["state"]),
                         ("http://127.0.0.1:5555/", redirect, "S256", ch, "st8"))
        self.assertEqual((q["scope"], q["access_type"], q["prompt"], q["login_hint"], q["client_id"], q["response_type"]),
                         ("openid email https://mail.google.com/", "offline", "consent", ME, GID, "code"))
        self.assertNotIn(GSECRET, url)
        for account, tenant in (("personal", "consumers"), ("work", "organizations")):
            url, redirect = oauth.auth_url("microsoft", 5555, "st8", ch, account)
            q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
            self.assertTrue(url.startswith(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"))
            self.assertEqual((redirect, q["scope"]), ("http://localhost:5555", oauth.PROVIDERS["microsoft"]["scope"]))
            self.assertIn("offline_access", q["scope"])
            self.assertIn("https://outlook.office.com/SMTP.Send", q["scope"])

    def test_google_sign_in_end_to_end_keeps_only_the_refresh_token(self):
        mailconn.connect("gmail", ME, PW)
        self.assertEqual(self.stored("IMAP_PASS"), PW)
        st = self.google(login_hint=ME)
        self.assertEqual(self.browser_status, 200)
        (form,) = self.srv.grants("authorization_code")
        self.assertEqual((form["code"], form["client_id"], form["client_secret"], form["redirect_uri"]),
                         (CODE, GID, GSECRET, self.auth_q["redirect_uri"]))
        import hashlib
        self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode(),
                         self.auth_q["code_challenge"])
        self.assertEqual((st["signed_in_as"], st["configured"], st["auth"], st["oauth_provider"], st["preset"]),
                         (ME, True, "oauth", "google", "gmail"))
        self.assertEqual((st["imap_host"], st["smtp_host"], st["smtp_port"], st["smtp_mode"]),
                         ("imap.gmail.com", "smtp.gmail.com", 465, "ssl"))
        self.assertEqual((self.stored("OAUTH_REFRESH"), self.stored("EMAIL_AUTH"), self.stored("IMAP_USER"),
                          self.stored("IMAP_PASS"), self.stored("OAUTH_ACCOUNT")), (REFRESH, "oauth", ME, None, None))
        self.assertNotIn("expires_warning", st)
        self.assertEqual(oauth.PENDING, {})
        for secret in (ACCESS, REFRESH, CODE, GSECRET):  # nothing secret in what the UI gets back
            self.assertNotIn(secret, json.dumps(st))
        for f in HOME.rglob("*"):  # the access token never reaches disk (index, connections.json, logs, anything)
            if f.is_file():
                self.assertNotIn(ACCESS.encode(), f.read_bytes(), f)
        self.assertNotIn(ACCESS, str(self.store))
        self.assertEqual(oauth.access_token(), ACCESS)  # cached in memory from the sign-in
        self.assertEqual(self.srv.grants("refresh_token"), [])

    def test_microsoft_sign_in_sends_no_secret_and_the_account_decides_the_servers(self):
        st = self.microsoft()
        (form,) = self.srv.grants("authorization_code")
        self.assertNotIn("client_secret", form)
        self.assertEqual(self.srv.requests[0][0], "/consumers/token")
        self.assertTrue(self.auth_q["redirect_uri"].startswith("http://localhost:"))
        self.assertEqual((st["preset"], st["smtp_host"], st["smtp_port"], st["smtp_mode"], st["imap_host"]),
                         ("outlook", "smtp-mail.outlook.com", 587, "starttls", "outlook.office365.com"))
        self.assertEqual(self.stored("OAUTH_ACCOUNT"), "personal")
        st = self.microsoft(tid="72f988bf-0000-4000-8000-000000000000")  # picked personal, the token says work
        self.assertEqual((st["preset"], st["smtp_host"], self.stored("OAUTH_ACCOUNT")), ("m365", "smtp.office365.com", "work"))

    def test_the_listener_waits_for_its_own_state_and_host_and_ignores_idle_sockets(self):
        codes = []

        def browser(url):
            q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
            port = urlsplit(q["redirect_uri"]).port
            idle = socket.create_connection(("127.0.0.1", port))  # a browser's preconnect: never sends a byte
            try:
                codes.append(get(port, "/?" + urlencode({"code": "stolen", "state": "wrong"}))[0])
                codes.append(get(port, "/?" + urlencode({"error": "access_denied", "state": "wrong"}))[0])
                codes.append(get(port, "/?" + urlencode({"code": CODE, "state": q["state"]}), host=f"evil.example:{port}")[0])
                codes.append(get(port, "/favicon.ico")[0])
                codes.append(get(port, "/?" + urlencode({"code": CODE, "state": q["state"]}))[0])
                self.port, page = port, get(port, "/?" + urlencode({"code": "again", "state": q["state"]}))
                self.assertIn("already finished", page[1])
                self.assertNotIn(CODE, page[1])
            finally:
                idle.close()

        oauth.set_client("google", GID, GSECRET)
        started = time.time()
        oauth.signin("google", open_browser=browser)
        self.assertLess(time.time() - started, 5)
        self.assertEqual(codes, [400, 400, 400, 404, 200])
        self.assertEqual(self.srv.grants("authorization_code")[0]["code"], CODE)  # never "stolen"
        with self.assertRaises(OSError):  # the port is closed once the sign-in is over
            socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
        self.assertEqual(oauth.PENDING, {})

    def test_a_refusal_a_timeout_and_a_cancel_each_end_cleanly(self):
        oauth.set_client("google", GID, GSECRET)
        with self.assertRaises(SystemExit) as e:
            oauth.signin("google", open_browser=lambda u: self.browser(u, error="access_denied"))
        self.assertIn("publish the app", str(e.exception))
        self.assertEqual(self.srv.requests, [])
        seen = []
        with self.assertRaises(SystemExit) as e:
            oauth.signin("google", open_browser=seen.append, timeout=1)
        self.assertIn("timed out", str(e.exception))
        port = urlsplit(parse_qs(urlsplit(seen[0]).query)["redirect_uri"][0]).port
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        self.assertEqual((oauth.PENDING, oauth._CURRENT), ({}, None))
        threading.Timer(0.3, oauth.cancel).start()
        with self.assertRaises(SystemExit) as e:
            oauth.signin("google", open_browser=lambda u: None, timeout=10)
        self.assertIn("cancelled", str(e.exception))
        self.assertIsNone(self.stored("OAUTH_REFRESH"))

    def test_the_id_token_must_be_for_this_client_verified_and_current(self):
        for bad, words in (({"aud": "someone-else"}, "audience"), ({"email_verified": False}, "confirm"),
                           ({"exp": time.time() - 10}, "expired"), ({"iss": "https://evil.example"}, "issuer")):
            self.claims = {"iss": "https://accounts.google.com", "aud": GID, "exp": time.time() + 3600, "email": ME,
                           "email_verified": True} | bad
            with self.assertRaises(SystemExit) as e:
                self.google()
            self.assertIn(words, str(e.exception))
            self.assertIsNone(self.stored("OAUTH_REFRESH"))

    def test_a_google_testing_app_is_warned_about(self):
        self.extra = {"refresh_token_expires_in": 604799}
        st = self.google()
        self.assertIn("Testing", st["expires_warning"])
        self.assertTrue(self.stored("OAUTH_REFRESH_EXPIRES"))
        self.assertTrue(mailconn.status()["refresh_expires"])
        row = [r for r in doctor.checks() if r[1] == "email sign-in"]
        self.assertEqual(row[0][0], "warn")
        self.extra = {}
        self.google()
        self.assertIsNone(self.stored("OAUTH_REFRESH_EXPIRES"))

    def test_token_exchange_errors_are_plain_and_never_carry_secrets(self):
        self.reply = lambda path, form: (400, {"error": "redirect_uri_mismatch",
                                                "error_description": f"bad {form.get('code')} {form.get('client_secret')}"})
        self.srv.reply = self.reply
        with self.assertRaises(SystemExit) as e:
            self.google()
        msg = str(e.exception)
        self.assertIn("Desktop app", msg)
        self.assertNotIn(CODE, msg)
        self.assertNotIn(GSECRET, msg)

    def test_no_refresh_token_is_refused(self):
        self.extra = {"refresh_token": ""}
        with self.assertRaises(SystemExit) as e:
            self.google()
        self.assertIn("myaccount.google.com/connections", str(e.exception))


class Vault(Base):
    def test_long_secrets_are_chunked_and_read_back_whole(self):
        long = "M.R3_BAY." + "x" * 2991
        vault.set("OAUTH_REFRESH", long)
        self.assertEqual(vault.get("OAUTH_REFRESH"), long)
        self.assertTrue(all(len(v) <= 1280 for v in self.store.values()))
        self.assertEqual([n for n, _ in vault.names()], ["OAUTH_REFRESH"])
        tails = lambda: sorted(n for _, n in self.store if n.startswith("OAUTH_REFRESH~"))  # noqa: E731
        self.assertEqual(len(tails()), 2)
        vault.set("OAUTH_REFRESH", "y" * 1500)  # shorter: the old pieces go
        self.assertEqual(vault.get("OAUTH_REFRESH"), "y" * 1500)
        self.assertEqual(len(tails()), 1)
        del self.store[(vault.SERVICE, tails()[0])]
        self.assertIsNone(vault.get("OAUTH_REFRESH"))  # a missing piece is no token, never half a token
        vault.set("OAUTH_REFRESH", "z" * 2500)
        vault.delete("OAUTH_REFRESH")
        self.assertEqual(self.store, {})
        vault.set("SHORT", "abc")
        self.assertEqual((vault.get("SHORT"), list(self.store)), ("abc", [(vault.SERVICE, "SHORT")]))


class Tokens(Base):
    def test_cached_until_a_minute_before_expiry_then_refreshed(self):
        self.signed_in()
        vault.set("EMAIL_VERIFIED", "x")
        self.assertEqual(oauth.access_token(), ACCESS2)
        (form,) = self.srv.grants("refresh_token")
        self.assertEqual((form["refresh_token"], form["client_id"], form["client_secret"]), (REFRESH, GID, GSECRET))
        self.assertNotIn("scope", form)
        self.assertEqual(oauth.access_token(), ACCESS2)
        self.assertEqual(len(self.srv.grants("refresh_token")), 1)
        oauth._TOKEN["exp"] = time.time() + 30
        oauth.access_token()
        self.assertEqual(len(self.srv.grants("refresh_token")), 2)

    def test_microsoft_refresh_sends_the_scope_and_a_rotated_token_replaces_the_stored_one(self):
        self.signed_in("microsoft")
        vault.set("OAUTH_ACCOUNT", "work")
        self.srv.reply = lambda p, f: (200, {"access_token": ACCESS2, "expires_in": 3599, "refresh_token": "ROTATED-REFRESH-TOKEN-1"})
        oauth.access_token()
        (path, form), = self.srv.requests
        self.assertEqual((path, form["scope"], "client_secret" in form), ("/organizations/token", oauth.PROVIDERS["microsoft"]["scope"], False))
        self.assertEqual(self.stored("OAUTH_REFRESH"), "ROTATED-REFRESH-TOKEN-1")

    def test_a_revoked_sign_in_asks_to_sign_in_again_and_an_outage_does_not(self):
        self.signed_in()
        vault.set("EMAIL_VERIFIED", "x")
        self.srv.reply = lambda p, f: (503, {})
        with self.assertRaises(oauth.Transient):
            oauth.access_token()
        self.assertEqual((self.stored("EMAIL_VERIFIED"), self.stored("OAUTH_NEEDS_SIGNIN")), ("x", None))
        self.assertEqual(mailconn._kind(oauth.Transient("x")), "net")
        self.srv.reply = lambda p, f: (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
        with self.assertRaises(SystemExit) as e:
            oauth.access_token()
        self.assertIn("lodestar email signin google", str(e.exception))
        self.assertTrue(self.stored("OAUTH_NEEDS_SIGNIN"))
        self.assertIsNone(self.stored("EMAIL_VERIFIED"))
        n = len(self.srv.requests)
        with self.assertRaises(SystemExit):  # flagged: no more calls until the user signs in again
            oauth.access_token()
        self.assertEqual(len(self.srv.requests), n)
        self.assertTrue(mailconn.status()["needs_signin"])
        row = [r for r in doctor.checks() if r[1] == "email sign-in"]
        self.assertEqual(row[0][0], "fail")
        self.assertIn("lodestar email signin google", row[0][2])

    def test_a_token_rotated_by_another_process_is_retried_once(self):
        self.signed_in("microsoft")

        def reply(path, form):
            if form["refresh_token"] == REFRESH:
                vault.set("OAUTH_REFRESH", "ROTATED-BY-THE-OTHER-PROCESS")  # the scheduled run refreshed meanwhile
                return 400, {"error": "invalid_grant", "error_description": "AADSTS70000: token used"}
            return 200, {"access_token": ACCESS2, "expires_in": 3599}
        self.srv.reply = reply
        self.assertEqual(oauth.access_token(), ACCESS2)
        self.assertEqual([f["refresh_token"] for _, f in self.srv.requests], [REFRESH, "ROTATED-BY-THE-OTHER-PROCESS"])
        self.assertIsNone(self.stored("OAUTH_NEEDS_SIGNIN"))

    def test_two_threads_at_once_refresh_once(self):
        self.signed_in()
        self.srv.delay = 0.3
        got = []
        ts = [threading.Thread(target=lambda: got.append(oauth.access_token())) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(5)
        self.assertEqual((got, len(self.srv.requests)), ([ACCESS2, ACCESS2], 1))


class XOAuth2(Base):
    def test_the_wire_strings_and_one_retry_after_a_rejection(self):
        self.assertEqual(oauth.xoauth2(ME, "tok"), "user=me@example.com\x01auth=Bearer tok\x01\x01")
        self.signed_in()
        oauth._TOKEN.update(token="STALE", exp=time.time() + 3000, provider="google")
        self.imap_reject = 1
        box = imaplib.IMAP4_SSL("imap.gmail.com")
        oauth.imap_auth(box, ME)
        auths = [x for x in self.log if x[0] in ("imap-auth", "imap-challenge")]
        self.assertEqual(auths, [("imap-auth", "XOAUTH2", oauth.xoauth2(ME, "STALE")), ("imap-challenge", b""),
                                 ("imap-auth", "XOAUTH2", oauth.xoauth2(ME, ACCESS2))])
        self.log.clear()
        self.smtp_reject = 1
        oauth._TOKEN.update(token="STALE", exp=time.time() + 3000)
        oauth.smtp_auth(smtplib.SMTP("smtp.gmail.com", 465), ME)
        self.assertEqual(self.log, [("smtp", "smtp.gmail.com", 465), ("ehlo",),
                                    ("smtp-auth", "XOAUTH2", oauth.xoauth2(ME, "STALE"), "", True),
                                    ("smtp-auth", "XOAUTH2", oauth.xoauth2(ME, ACCESS2), "", True)])

    def test_test_send_and_scan_use_xoauth2_with_the_account_address(self):
        self.signed_in()
        r = mailconn.test()
        self.assertTrue(r["imap"]["ok"] and r["smtp"]["ok"], r)
        self.assertTrue(mailconn.status()["verified"])
        kinds = [x[0] for x in self.log]
        self.assertNotIn("imap-login", kinds)
        self.assertNotIn("smtp-login", kinds)
        self.assertIn(("smtp-auth", "XOAUTH2", oauth.xoauth2(ME, ACCESS2), "", True), self.log)
        self.log.clear()
        util.send_email("you@example.com", "hi", "body")
        self.assertEqual((self.sent[0]["From"], [x for x in self.log if x[0] == "smtp-auth"][0][2]),
                         (ME, oauth.xoauth2(ME, ACCESS2)))
        self.log.clear()
        real = email_monitor.classify
        email_monitor.classify = lambda *a, **k: {"category": "other"}
        try:
            email_monitor.check(days=1, dry=True)
        finally:
            email_monitor.classify = real
        self.assertEqual([x[:2] for x in self.log if x[0] == "imap-auth"], [("imap-auth", "XOAUTH2")])
        vault.set("OAUTH_NEEDS_SIGNIN", "invalid_grant")
        with self.assertRaises(SystemExit) as e:
            email_monitor.check(days=1, dry=True)
        self.assertIn("sign in again", str(e.exception).lower())
        r = mailconn.test()  # needs sign-in: both sides say so, and the mailbox is no longer verified
        self.assertEqual((r["imap"]["kind"], r["smtp"]["kind"], mailconn.status()["verified"]), ("auth", "auth", False))
        self.assertIn("lodestar email signin google", r["hint"])

    def test_password_mailboxes_are_unchanged(self):
        mailconn.connect("fastmail", ME, PW)
        util.send_email("you@example.com", "hi", "body")
        self.assertIn(("smtp-login", ME, PW), self.log)
        self.assertFalse([x for x in self.log if x[0] == "smtp-auth"])


class Presets(Base):
    def test_microsoft_needs_sign_in_and_a_password_connect_ends_an_oauth_one(self):
        with self.assertRaises(SystemExit) as e:
            mailconn.connect("outlook", "me@outlook.com", PW)
        self.assertIn("sign in with Microsoft", str(e.exception))
        self.assertEqual(self.store, {})
        self.google()
        mailconn.connect("gmail", ME, PW)
        self.assertEqual([p for p, _ in self.srv.requests], ["/token", "/revoke"])
        self.assertEqual(self.srv.requests[1][1]["token"], REFRESH)
        self.assertEqual((self.stored("OAUTH_REFRESH"), self.stored("EMAIL_AUTH"), self.stored("IMAP_PASS")),
                         (None, "password", PW))
        self.assertEqual(mailconn.status()["auth"], "password")

    def test_microsoft_refusals_get_plain_next_steps(self):
        c = {"auth": "oauth", "preset": "m365", "imap_host": "outlook.office365.com", "smtp_host": "smtp.office365.com"}
        off = smtplib.SMTPAuthenticationError(535, b"5.7.139 Authentication unsuccessful, SmtpClientAuthentication is disabled")
        self.assertIn("SMTP AUTH turned off", mailconn.hint(off, c))
        self.assertIn("Turn on IMAP", mailconn.hint(imaplib.IMAP4.error("User is authenticated but not connected."), c))
        vault.set("OAUTH_PROVIDER", "microsoft")
        self.assertIn("Sign in with Microsoft", mailconn.hint(imaplib.IMAP4.error("AUTHENTICATE failed."), c))
        self.assertNotIn("app password", mailconn.hint(imaplib.IMAP4.abort("socket closed"), c))

    def test_disconnect_revokes_google_notes_microsoft_and_keeps_the_clients(self):
        self.google()
        st = mailconn.disconnect()
        self.assertEqual((st["revoked"], st["configured"], self.srv.requests[-1]), (True, False, ("/revoke", {"token": REFRESH})))
        for n in (*oauth.STATE_KEYS, "EMAIL_VERIFIED"):
            self.assertIsNone(self.stored(n), n)
        self.assertEqual((self.stored("GOOGLE_CLIENT_ID"), self.stored("GOOGLE_CLIENT_SECRET"), self.stored("IMAP_USER")),
                         (GID, GSECRET, ME))
        self.assertEqual(oauth._TOKEN, {})
        self.microsoft()
        st = mailconn.disconnect()
        self.assertIn("account.live.com/consent/Manage", st["note"])
        self.claims = {"iss": "https://accounts.google.com", "aud": GID, "exp": time.time() + 3600, "email": ME,
                       "email_verified": True}
        self.google()
        self.srv.reply = lambda p, f: (500, {})
        st = mailconn.disconnect()
        self.assertIn("myaccount.google.com/connections", st["note"])
        self.assertIsNone(self.stored("OAUTH_REFRESH"))

    def test_client_ids_are_checked_and_never_shown(self):
        for prov, cid, sec in (("google", "not-a-client", None), ("google", GID, "bad/secret!"),
                               ("microsoft", "nope", None), ("microsoft", MSID, "a-secret-1234"), ("yahoo", GID, None)):
            with self.assertRaises(SystemExit):
                oauth.set_client(prov, cid, sec)
        self.assertEqual(self.store, {})
        self.assertEqual(oauth.set_client("google", GID), {"google": {"set": True}, "microsoft": {"set": False}})
        self.assertIsNone(self.stored("GOOGLE_CLIENT_SECRET"))  # optional for a Desktop client
        oauth.set_client("google", GID, GSECRET)
        oauth.set_client("google", GID.replace("1234", "9999"))  # a new client drops the old client's secret
        self.assertIsNone(self.stored("GOOGLE_CLIENT_SECRET"))
        with self.assertRaises(SystemExit) as e:
            oauth.signin("microsoft", open_browser=self.browser)
        self.assertIn("lodestar email client microsoft", str(e.exception))

    def test_mail_cafile_pins_a_loopback_certificate_only(self):
        import pip
        pem = Path(pip.__file__).parent / "_vendor" / "certifi" / "cacert.pem"
        if not pem.is_file():
            self.skipTest("no PEM file to load")
        vault.set("MAIL_CAFILE", str(pem))
        for host, check in (("127.0.0.1", False), ("mail.example.com", True)):
            ctx = util.tls_context(host)
            self.assertEqual((ctx.verify_mode, ctx.check_hostname), (ssl.CERT_REQUIRED, check), host)
        vault.delete("MAIL_CAFILE")
        self.assertTrue(util.tls_context("127.0.0.1").check_hostname)
        with self.assertRaises(SystemExit):
            mailconn.connect("proton", "me@proton.me", PW, cafile=str(HOME / "missing.pem"))
        st = mailconn.connect("proton", "me@proton.me", PW, cafile=str(pem))
        self.assertEqual((st["imap_host"], st["imap_port"], st["smtp_port"], self.stored("MAIL_CAFILE")),
                         ("127.0.0.1", 1143, 1025, str(pem)))


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

    def task(self, tid):
        for _ in range(100):
            r = json.loads(self.req("GET", f"/api/tasks/{tid}")[1])
            if r["status"] != "running":
                return r
            time.sleep(0.1)
        self.fail("task never finished")

    def test_routes_need_the_token_and_a_sign_in_runs_as_a_task(self):
        from lodestar import desktop, web
        self.port = desktop.free_port(8990)
        srv = web.start_server(self.port)
        try:
            for method, path in (("POST", "/api/email/client"), ("POST", "/api/email/signin"), ("GET", "/api/email/signin"),
                                 ("POST", "/api/email/signin_cancel")):
                self.assertEqual(self.req(method, path, {} if method == "POST" else None, token=False)[0], 403, path)
            code, body = self.req("POST", "/api/email/client", {"provider": "google", "client_id": GID, "client_secret": GSECRET})
            self.assertEqual((code, json.loads(body)["clients"]["google"]["set"]), (200, True))
            code, body = self.req("POST", "/api/email/client", {"provider": "google", "client_id": "bad", "client_secret": GSECRET})
            self.assertEqual(code, 400)
            self.assertNotIn(GSECRET, body)
            self.assertEqual(self.req("POST", "/api/email/signin", {"provider": "yahoo"})[0], 400)
            oauth.webbrowser.open = self.browser  # the task opens "the browser": ours completes the round trip
            code, body = self.req("POST", "/api/email/signin", {"provider": "google", "login_hint": ME})
            r = self.task(json.loads(body)["task"])
            self.assertEqual(r["status"], "done", r)
            self.assertEqual((r["result"]["status"]["signed_in_as"], r["result"]["test"]["imap"]["ok"],
                              r["result"]["test"]["smtp"]["ok"]), (ME, True, True))
            for method, path in (("GET", "/api/email/status"), ("GET", "/api/state"), ("GET", "/api/email/signin")):
                code, body = self.req(method, path)
                self.assertEqual(code, 200, body)
                for secret in (GID, GSECRET, REFRESH, ACCESS, ACCESS2, CODE):
                    self.assertNotIn(secret, body, (path, secret))
            st = json.loads(self.req("GET", "/api/email/status")[1])
            self.assertEqual((st["clients"]["google"]["set"], st["status"]["auth"], set(st["oauth"])),
                             (True, "oauth", {"google", "microsoft"}))
            self.assertNotIn("GOOGLE_CLIENT_ID", [v["name"] for v in json.loads(self.req("GET", "/api/state")[1])["vault"]])
            oauth.webbrowser.open = lambda url: None  # nobody comes back: the UI shows the link, then the user cancels
            tid = json.loads(self.req("POST", "/api/email/signin", {"provider": "google"})[1])["task"]
            for _ in range(50):
                pend = json.loads(self.req("GET", "/api/email/signin")[1])
                if pend["pending"]:
                    break
                time.sleep(0.1)
            self.assertTrue(pend["url"].startswith("https://accounts.google.com/") and pend["provider"] == "google", pend)
            self.assertEqual(json.loads(self.req("POST", "/api/email/signin_cancel", {})[1]), {"cancelled": True})
            r = self.task(tid)
            self.assertEqual(r["status"], "error")
            self.assertIn("cancelled", r["error"])
        finally:
            srv.shutdown()
            srv.server_close()


class Cli(Base):
    def test_client_and_signin_from_the_terminal(self):
        import builtins
        real = (cli.getpass.getpass,)
        real_input = builtins.input
        builtins.input, cli.getpass.getpass = (lambda prompt="": GID), (lambda prompt="": GSECRET)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                cli.main(["email", "client", "google"])
        finally:
            builtins.input, cli.getpass.getpass = real_input, real[0]
        self.assertEqual((self.stored("GOOGLE_CLIENT_ID"), self.stored("GOOGLE_CLIENT_SECRET")), (GID, GSECRET))
        self.assertNotIn(GSECRET, out.getvalue())

        def finish():  # --no-browser: the user opens the printed page by hand
            for _ in range(100):
                if oauth.PENDING.get("url"):
                    return self.browser(oauth.PENDING["url"])
                time.sleep(0.05)
        t = threading.Thread(target=finish)
        t.start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["email", "signin", "google", "--no-browser", "--hint", ME])
        t.join(5)
        text = out.getvalue()
        self.assertIn("Visit this page", text)
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth?", text)
        self.assertIn(f"signed in as {ME}", text)
        self.assertIn("IMAP  ok", text)
        for secret in (GSECRET, REFRESH, ACCESS, CODE):
            self.assertNotIn(secret, text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["email", "status"])
            cli.main(["email", "disconnect"])
        self.assertIn("signed in with Google (OAuth)", out.getvalue())
        self.assertIn("revoked at Google", out.getvalue())
        with self.assertRaises(SystemExit) as e:
            cli.main(["email", "connect", "--user", "me@outlook.com"])
        self.assertIn("lodestar email signin microsoft", str(e.exception))


if __name__ == "__main__":
    unittest.main()
