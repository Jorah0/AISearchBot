"""Phone access (pass 53): off by default; a one-time pairing code (5 tries, 5 minutes, once) wins a hashed session
cookie; the phone listener checks Host and the cookie on every request, keeps the page token on /api/, and refuses the
secret-bearing routes; phone.json stays out of backups. The listener here binds loopback (no LAN needed)."""
import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import extras, phone, settings, web  # noqa: E402


class Pairing(unittest.TestCase):
    def setUp(self):
        self.addCleanup(phone.revoke_all)
        self.addCleanup(phone._CODE.clear)

    def test_off_by_default_and_out_of_backups(self):
        self.assertIs(settings.PREFS["phone_access"], False)
        self.assertFalse(phone.status()["on"])
        self.assertFalse(extras.in_backup(Path("phone.json")))

    def test_code_once_tries_and_expiry(self):
        c = phone.new_code()["code"]
        self.assertRegex(c, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        tok = phone.pair(c.lower(), "Pixel")
        self.assertTrue(tok)
        self.assertIsNone(phone.pair(c))  # once
        self.assertTrue(phone.valid(f"x=1; {phone.COOKIE}={tok}"))
        self.assertFalse(phone.valid(f"{phone.COOKIE}=forged"))
        self.assertNotIn(tok, phone.PATH.read_text(encoding="utf-8"))  # stored hashed
        c = phone.new_code()["code"]
        for _ in range(phone.CODE_TRIES):
            self.assertIsNone(phone.pair("AAAA-AAAA"))
        self.assertIsNone(phone.pair(c))  # five wrong tries end the code
        c = phone.new_code()["code"]
        phone._CODE["until"] = 0
        self.assertIsNone(phone.pair(c))
        self.assertEqual(phone.revoke_all(), 1)
        self.assertFalse(phone.valid(f"{phone.COOKIE}={tok}"))

    def test_allowed_routes(self):
        for ok in ("/", "/api/state", "/api/jobs/3", "/api/run/tailor", "/api/map"):
            self.assertTrue(phone.allowed(ok), ok)
        for no in ("/api/keys/anthropic", "/api/vault", "/api/accounts/3/reveal", "/api/codes", "/api/run/restore",
                   "/api/run/update_apply", "/api/phone", "/api/ext/capture", "/api/browser", "/api/open_folder"):
            self.assertFalse(phone.allowed(no), no)

    def test_start_needs_a_private_lan_address(self):
        with patched(phone, lan_ip=lambda: None):
            with self.assertRaisesRegex(SystemExit, "home-network"):
                phone.start()


class Listener(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), web.PhoneHandler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(phone.revoke_all)
        self.port = self.srv.server_address[1]

    def call(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"} | (headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    def test_pair_then_use_with_cookie_and_token(self):
        st, h, _ = self.call("GET", "/")
        self.assertEqual((st, h["Location"]), (303, "/phone"))
        self.assertEqual(self.call("GET", "/api/state")[0], 401)
        st, _, page = self.call("GET", "/phone")
        self.assertEqual(st, 200)
        self.assertNotIn(web.TOKEN.encode(), page)
        form = {"Content-Type": "application/x-www-form-urlencoded"}
        self.assertIn(b"wrong or expired", self.call("POST", "/phone", b"code=NOPE-NOPE", form)[2])
        code = phone.new_code()["code"]
        st, h, _ = self.call("POST", "/phone", f"code={code}&label=Pixel".encode(), form)
        self.assertEqual(st, 303)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Strict", h["Set-Cookie"])
        cookie = {"Cookie": h["Set-Cookie"].split(";")[0]}
        st, _, page = self.call("GET", "/", headers=cookie)
        self.assertEqual(st, 200)
        self.assertIn(web.TOKEN.encode(), page)
        self.assertEqual(self.call("GET", "/api/state", headers=cookie)[0], 403)  # the page token is still needed
        both = cookie | {"X-Lodestar-Token": web.TOKEN}
        self.assertEqual(self.call("GET", "/api/state", headers=both)[0], 200)
        self.assertEqual(self.call("GET", "/api/vault", headers=both)[0], 403)
        self.assertEqual(self.call("POST", "/api/run/restore", b"{}", both | {"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.call("POST", "/api/phone", b'{"op": "code"}', both | {"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.call("GET", "/", headers=cookie, host=f"evil.example:{self.port}")[0], 421)
        self.assertEqual(self.call("OPTIONS", "/api/state", headers=both)[0], 404)


if __name__ == "__main__":
    unittest.main()
