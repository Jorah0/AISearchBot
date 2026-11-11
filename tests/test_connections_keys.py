"""Connections pass, builder A: linking AI keys, verifying them without spending tokens (at link time and once per app
start), statuses in /api/state, Setup, Getting started and doctor, the `lodestar keys` CLI, a network failure never
un-verifying the mailbox, and the research fetch fix (NEVER_FETCH on every hop, robots.txt). No network and no real
keyring: urlopen, keyring and the mail logins are faked; every patched attribute is put back."""
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
import threading
import time
import unittest
import urllib.error
import urllib.request

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, cli, connections, doctor, extras, mailconn, settings, util, vault  # noqa: E402

KEY = "sk-ant-api03-SECRETSECRETSECRET"
PW = "abcdefghijklmnop"
ENV = [e["key"] for e in connections.REGISTRY.values() if e["key"]] + [f"{n.upper()}_MODEL" for n in ai.PROVIDERS] + [
    "LODESTAR_PROVIDER", "LODESTAR_NO_STARTUP_CHECK", "EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", *mailconn.KEYS.values()]
MODELS = {  # url fragment -> body of a 200 answer
    "api.anthropic.com": {"data": [{"id": "claude-sonnet-5-5"}, {"id": "claude-haiku-5"}], "has_more": False},
    "api.openai.com": {"data": [{"id": "gpt-5"}, {"id": "gpt-4.1"}]},
    "generativelanguage": {"data": [{"id": "models/gemini-2.5-flash"}]},
    "api.groq.com": {"data": [{"id": "llama-3.3-70b-versatile"}]},
    "openrouter.ai": {"data": {"label": "x", "limit": 10, "usage": 1.5}},
    "api.mistral.ai": {"data": [{"id": "mistral-large-latest"}]},
    "localhost:11434": {"data": [{"id": "llama3.1:latest"}]},
}


def body(url):
    return next(v for k, v in MODELS.items() if k in url)


class Base(unittest.TestCase):
    def setUp(self):
        self.store, self.calls, self.reply = {}, [], None
        k, t = vault.keyring, self

        def delete(svc, name):
            if (svc, name) not in self.store:
                raise k.errors.PasswordDeleteError("not there")
            del self.store[(svc, name)]

        def urlopen(req, timeout=None):
            t.calls.append((req.full_url, dict(req.header_items())))
            r = t.reply(req.full_url) if t.reply else (200, body(req.full_url))
            if isinstance(r, BaseException):
                raise r
            code, data = r
            raw = (data if isinstance(data, str) else json.dumps(data)).encode()
            if code != 200:
                raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(raw))
            return contextlib.nullcontext(io.BytesIO(raw))

        self.files = {p: (p.read_bytes() if p.is_file() else None) for p in (settings.PATH, connections.PATH)}
        self.real = (k.get_password, k.set_password, k.delete_password, vault._index(), connections.urlopen,
                     connections._STARTED, settings.set_model)
        self.env = {n: os.environ.pop(n) for n in ENV if n in os.environ}
        k.get_password = lambda svc, name: self.store.get((svc, name))
        k.set_password = lambda svc, name, v: self.store.__setitem__((svc, name), v)
        k.delete_password = delete
        connections.urlopen = urlopen
        settings.PATH.write_text("{}", encoding="utf-8")
        connections.PATH.unlink(missing_ok=True)
        self.set_model = []
        settings.set_model = lambda n, m: self.set_model.append((n, m))

    def tearDown(self):
        k = vault.keyring
        (k.get_password, k.set_password, k.delete_password, idx, connections.urlopen, connections._STARTED,
         settings.set_model) = self.real
        vault._save_index(idx)
        connections.CHECKING.clear()
        for n in ENV:
            os.environ.pop(n, None)
        os.environ.update(self.env)
        for p, b in self.files.items():
            p.write_bytes(b) if b is not None else p.unlink(missing_ok=True)

    def stored_texts(self) -> str:
        return (connections.PATH.read_text(encoding="utf-8") if connections.PATH.is_file() else "") + json.dumps(connections.status())


class Registry(Base):
    def test_registry_covers_every_provider_with_its_key_and_https_links(self):
        ai_keys = {n: e for n, e in connections.REGISTRY.items() if e.get("kind") != "jobs"}  # pass 21: + job-data keys
        self.assertEqual(set(ai_keys), set(ai.PROVIDERS))
        for n, e in ai_keys.items():
            self.assertEqual(e["key"], ai.PROVIDERS[n]["key"], n)
            self.assertTrue(e["get"].startswith("https://"), n)
        self.assertEqual(connections.resolve("ANTHROPIC_API_KEY"), "anthropic")
        with self.assertRaises(SystemExit):
            connections.resolve("nope")


class Verify(Base):
    def test_each_provider_hits_its_documented_path_with_its_auth(self):
        expect = {"anthropic": "https://api.anthropic.com/v1/models?limit=1000",
                  "openai": "https://api.openai.com/v1/models",
                  "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/models",
                  "groq": "https://api.groq.com/openai/v1/models", "openrouter": "https://openrouter.ai/api/v1/key",
                  "mistral": "https://api.mistral.ai/v1/models", "ollama": "http://localhost:11434/v1/models"}
        for n, url in expect.items():
            self.calls.clear()
            r = connections.verify_key(n, None if n == "ollama" else "key-" + n + "-123456")
            self.assertEqual(r["status"], "verified", (n, r))
            self.assertEqual(self.calls[0][0], url)
            h = self.calls[0][1]
            if n == "anthropic":
                self.assertEqual((h.get("X-api-key"), h.get("Anthropic-version")), ("key-anthropic-123456", "2023-06-01"))
            elif n == "ollama":
                self.assertNotIn("Authorization", h)
            else:
                self.assertEqual(h.get("Authorization"), f"Bearer key-{n}-123456")
        self.assertIn("key ok", connections.verify_key("openrouter", "sk-or-abcdefgh")["detail"])
        self.assertIn("2 models", connections.verify_key("anthropic", KEY)["detail"])
        # normalized ids: 'models/gemini-x' is gemini-x, 'llama3.1:latest' is llama3.1 (no "not offered")
        self.assertNotIn("not offered", connections.verify_key("gemini", "AIzaabcdefgh")["detail"])
        self.assertNotIn("not offered", connections.verify_key("ollama")["detail"])
        self.assertEqual(connections.verify_key("openai", "")["status"], "verified" if ai.api_key("openai") else "unchecked")

    def test_failures_map_to_plain_statuses_and_never_carry_the_key(self):
        cases = [((401, f"bad key {KEY}"), "failed", "rejected"), ((403, ""), "failed", "rejected"),
                 ((402, ""), "failed", "credit"), ((429, ""), "failed", "quota"),
                 ((500, KEY), "unreachable", "will retry"), ((418, f"teapot {KEY}"), "failed", "HTTP 418"),
                 (urllib.error.URLError("no route"), "unreachable", "couldn't reach"),
                 (TimeoutError("timed out"), "unreachable", "couldn't reach"),
                 ((200, "<html>captive portal</html>"), "unreachable", "couldn't reach")]
        for reply, status, word in cases:
            self.reply = lambda url, r=reply: r
            r = connections.link("anthropic", KEY)
            self.assertEqual((r["status"], word in r["detail"]), (status, True), (reply, r))
            self.assertNotIn(KEY, json.dumps(r))
            self.assertNotIn(KEY, self.stored_texts())
            self.assertEqual(r.get("quota", False), reply == (429, ""))
        self.assertEqual(self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")], KEY)  # a failed key is still stored
        self.reply = lambda url: (400, '{"error": {"message": "API key not valid. Please pass a valid API key."}}')
        self.assertIn("rejected", connections.verify_key("gemini", "AIzaWRONGWRONG")["detail"])

    def test_missing_model_switches_only_when_linking_and_never_when_pinned(self):
        settings.PATH.write_text(json.dumps({"prefs": {"models": {"openai": "gpt-9"}}}), encoding="utf-8")
        r = connections.verify_key("openai", "sk-abcdefgh")
        self.assertIn("model gpt-9 is not offered; Setup can switch to gpt-5", r["detail"])
        connections.PATH.unlink(missing_ok=True)
        os.environ["OPENAI_API_KEY"] = "sk-abcdefgh"
        connections.check_all()  # the startup pass and Re-check never change settings
        self.assertEqual(self.set_model, [])
        os.environ.pop("OPENAI_API_KEY")
        r = connections.link("openai", "sk-abcdefgh")
        self.assertEqual((self.set_model, r["model"]), ([("openai", "gpt-5")], "gpt-5"))
        self.assertIn("switched to gpt-5", r["detail"])
        self.set_model.clear()
        os.environ["OPENAI_MODEL"] = "gpt-9"
        r = connections.link("openai", "sk-abcdefgh")
        self.assertEqual((r["status"], self.set_model), ("verified", []))
        self.assertIn("pinned by OPENAI_MODEL", r["detail"])

    def test_a_changed_key_reads_unchecked_and_env_keys_say_so(self):
        connections.link("anthropic", KEY)
        st = connections.status()["keys"]["anthropic"]
        self.assertEqual((st["linked"], st["status"], st["source"]), (True, "verified", "vault"))
        self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")] = KEY + "X"
        self.assertEqual(connections.status()["keys"]["anthropic"]["status"], "unchecked")
        os.environ["GROQ_API_KEY"] = "gsk_envenvenv"
        self.assertEqual(connections.status()["keys"]["groq"]["source"], "env")
        with self.assertRaises(SystemExit):
            connections.unlink("groq")  # set in .env, not the vault
        r = connections.link("anthropic", "  other-key-12345  \n")
        self.assertIn("does not look like", r["prefix_warning"])
        self.assertEqual(self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")], "other-key-12345")
        connections.unlink("anthropic")
        self.assertNotIn((vault.SERVICE, "ANTHROPIC_API_KEY"), self.store)
        self.assertNotIn("anthropic", json.loads(connections.PATH.read_text(encoding="utf-8"))["keys"])

    def test_redact_skips_empty_and_short_secrets(self):
        self.assertEqual(connections.redact("abc", ""), "abc")
        self.assertEqual(connections.redact("a short xy text", "xy"), "a short xy text")
        self.assertEqual(connections.redact(f"key {KEY} at https://h.example/x?key=v"), f"key {KEY} at https://h.example/x?key=***")
        self.assertEqual(connections.redact(f"key {KEY}", KEY), "key ***")


class Startup(Base):
    def test_start_checks_runs_once_in_the_background_and_one_failure_never_stops_the_rest(self):
        connections._STARTED = False
        os.environ["OPENAI_API_KEY"], os.environ["GROQ_API_KEY"] = "sk-abcdefgh", "gsk_abcdefgh"
        self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")] = KEY
        seen = []

        def verify(name, key=None):
            seen.append(name)
            time.sleep(0.3)
            if name == "anthropic":
                raise SystemExit("model rejected")
            if name == "openai":
                raise RuntimeError(f"boom {os.environ['OPENAI_API_KEY']}")
            return {"status": "verified", "detail": "ok", "model": "m"}
        real = connections.verify_key, connections.check_mail
        connections.verify_key, connections.check_mail = verify, lambda: None
        try:
            t0 = time.monotonic()
            self.assertTrue(connections.start_checks(delay=0))
            self.assertLess(time.monotonic() - t0, 0.2)
            self.assertFalse(connections.start_checks(delay=0))  # once per process
            th = next(t for t in threading.enumerate() if t.name == "lodestar-checks")
            self.assertTrue(th.daemon)
            th.join(10)
        finally:
            connections.verify_key, connections.check_mail = real
        self.assertEqual(sorted(seen), ["anthropic", "groq", "openai"])
        st = json.loads(connections.PATH.read_text(encoding="utf-8"))["keys"]
        self.assertEqual({n: st[n]["status"] for n in seen}, {"anthropic": "unreachable", "openai": "unreachable", "groq": "verified"})
        self.assertNotIn("sk-abcdefgh", connections.PATH.read_text(encoding="utf-8"))
        self.assertEqual(self.set_model, [])
        os.environ["LODESTAR_NO_STARTUP_CHECK"] = "1"
        connections._STARTED = False
        self.assertFalse(connections.start_checks(delay=0))


class Mail(Base):
    def setUp(self):
        super().setUp()
        self.mreal = (mailconn._imap, mailconn._smtp)
        mailconn._imap = lambda c, pw: "logged in"
        mailconn._smtp = lambda c, pw: "logged in"
        mailconn.connect("gmail", "me@example.com", PW)

    def tearDown(self):
        mailconn._imap, mailconn._smtp = self.mreal
        super().tearDown()

    def fail_imap(self, e):
        def f(c, pw):
            raise e
        mailconn._imap = f

    def test_network_failures_keep_the_mailbox_verified_and_refusals_do_not(self):
        self.assertEqual(connections.check_mail()["status"], "verified")
        self.assertTrue(mailconn.status()["verified"])
        for e in (socket.timeout("timed out"), imaplib.IMAP4.abort("socket error"), socket.gaierror("no dns")):
            self.fail_imap(e)
            r = mailconn.test()
            self.assertEqual((r["imap"]["kind"], r["reachable"]), ("net", False), e)
            self.assertTrue(mailconn.status()["verified"], e)
            self.assertEqual(connections.check_mail()["status"], "unreachable")
        self.fail_imap(imaplib.IMAP4.error(f"AUTHENTICATIONFAILED {PW}"))
        r = connections.check_mail()
        self.assertEqual(r["status"], "failed")
        self.assertIn("app password", r["detail"])
        self.assertFalse(mailconn.status()["verified"])
        self.assertNotIn(PW, self.stored_texts())
        self.assertEqual(connections.status()["mail"]["status"], "failed")

    def test_kind_orders_the_exception_classes(self):
        k = mailconn._kind
        self.assertEqual(k(imaplib.IMAP4.abort("x")), "net")
        self.assertEqual(k(imaplib.IMAP4.error("x")), "auth")
        self.assertEqual(k(smtplib.SMTPAuthenticationError(535, b"no")), "auth")
        self.assertEqual(k(SystemExit("sign in again")), "auth")
        self.assertEqual(k(smtplib.SMTPSenderRefused(550, b"no", "a@example.com")), "other")
        self.assertEqual(k(smtplib.SMTPServerDisconnected("gone")), "net")
        self.assertEqual(k(ssl.SSLCertVerificationError("host")), "other")
        self.assertEqual(k(ConnectionResetError()), "net")
        self.assertEqual(k(ValueError()), "other")


class SetupAndRoutes(Base):
    def test_setup_status_counts_unreachable_and_quota_as_usable(self):
        from lodestar import web

        def conn(status, quota=False):
            return {"keys": {"anthropic": {"label": "Anthropic (Claude)", "status": status, "detail": "d", "quota": quota}},
                    "mail": {"status": "failed", "detail": "sign-in refused"}}
        real = ai.available
        ai.available = lambda: ["anthropic"]
        try:
            s = web.setup_status(conn("failed"))
            self.assertEqual((s["provider_ready"], s["provider_problems"][0]["label"]), (False, "Anthropic (Claude)"))
            self.assertEqual(s["email_problem"], "sign-in refused")
            self.assertTrue(web.setup_status(conn("unreachable"))["provider_ready"])
            self.assertTrue(web.setup_status(conn("unchecked"))["provider_ready"])
            self.assertTrue(web.setup_status(conn("failed", quota=True))["provider_ready"])
        finally:
            ai.available = real

    def req(self, method, path, body=None, token=True, raw=None):
        from lodestar import web
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}", "X-Lodestar-Token": web.TOKEN if token else "no"}
        c.request(method, path, raw if raw is not None else (json.dumps(body) if body is not None else None), h)
        r = c.getresponse()
        out = (r.status, r.read().decode())
        c.close()
        return out

    def test_routes_need_the_token_never_echo_the_key_and_redact_errors(self):
        from lodestar import desktop, web
        self.port = desktop.free_port(8990)
        srv = web.start_server(self.port)
        try:
            for method, path in (("GET", "/api/keys"), ("POST", "/api/keys/link"), ("POST", "/api/keys/check"),
                                 ("POST", "/api/keys/remove")):
                self.assertEqual(self.req(method, path, {} if method == "POST" else None, token=False)[0], 403, path)
            self.assertEqual(self.store, {})
            code, text = self.req("POST", "/api/keys/link", {"name": "anthropic", "key": KEY})
            self.assertEqual((code, json.loads(text)["status"]), (200, "verified"), text)
            for method, path in (("GET", "/api/keys"), ("GET", "/api/state"), ("POST", "/api/keys/check")):
                code, text = self.req(method, path, {"name": "anthropic"} if method == "POST" else None)
                self.assertEqual(code, 200, text)
                self.assertNotIn(KEY, text)
            st = json.loads(self.req("GET", "/api/state")[1])
            self.assertEqual(st["connections"]["keys"]["anthropic"]["status"], "verified")
            self.assertNotIn("ANTHROPIC_API_KEY", [v["name"] for v in st["vault"]])  # on the keys card instead
            task = json.loads(self.req("POST", "/api/keys/check", {})[1])["task"]
            for _ in range(100):  # the background check must finish while urlopen is still the fake
                t = json.loads(self.req("GET", f"/api/tasks/{task}")[1])
                if t["status"] != "running":
                    break
                time.sleep(0.05)
            self.assertEqual(t["result"]["keys"]["anthropic"]["status"], "verified", t)
            real = connections.link
            connections.link = lambda name, key: (_ for _ in ()).throw(SystemExit(f"cannot use {key}"))
            try:
                code, text = self.req("POST", "/api/keys/link", {"name": "anthropic", "key": KEY})
            finally:
                connections.link = real
            self.assertEqual((code, json.loads(text)["error"]), (400, "cannot use ***"))
            code, text = self.req("POST", "/api/keys/link", raw="[]")
            self.assertEqual(code, 400)
            self.assertIn("error", json.loads(text))
            code, text = self.req("POST", "/api/keys/remove", {"name": "anthropic"})
            self.assertEqual((code, (vault.SERVICE, "ANTHROPIC_API_KEY") in self.store), (200, False))
        finally:
            srv.shutdown()
            srv.server_close()
        from pathlib import Path
        static = Path(__file__).resolve().parent.parent / "lodestar" / "static"
        html, js = (static / "index.html").read_text(encoding="utf-8"), (static / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="kVal" type="password" autocomplete="off"', html)
        self.assertIn('<select id="kProv"', html)
        card = js[js.index("function renderKeys()"):js.index("/* ---- connect email")]
        self.assertIn('target="_blank" rel="noopener"', card)
        self.assertIn("safeUrl(k.get)", card)
        self.assertNotIn("'${n}'", card)  # markup carries indexes, never names
        self.assertIn("$('#kVal').value = ''", card)
        self.assertIn("provider_problems", js)


class Ollama(Base):
    def test_linking_ollama_shows_it_linked_when_it_answers_and_unlink_clears_the_pin(self):
        # Setup > Link an AI key > Ollama > Link said Verified while the card still read "not linked": Ollama has no key
        # to store and ai.available() lists it only for a pinned model or the provider pref, so the link now pins its
        # model (pass 17.1)
        from lodestar import apply

        settings.set_model = self.real[-1]  # the real one: tearDown puts settings.json back
        self.assertFalse(connections.status()["keys"]["ollama"]["linked"])
        r = connections.link("ollama")
        k = connections.status()["keys"]["ollama"]
        self.assertEqual((r["status"], k["linked"], k["status"], k["model"]), ("verified", True, "verified", "llama3.1"))
        self.assertIn("ollama", ai.available())
        self.assertEqual(settings.PREFS["models"], {})  # the pin went to settings.json, never into the shared defaults
        # unlink clears that pin (it used to refuse: "Ollama has no key")
        connections.unlink("ollama")
        self.assertNotIn("ollama", ai.available())
        self.assertFalse(connections.status()["keys"]["ollama"]["linked"])
        # still on through the provider pref: the pin is cleared and the message names what keeps it on
        settings.set_pref("provider", "ollama")
        with self.assertRaises(SystemExit) as e:
            connections.unlink("ollama")
        self.assertIn("provider is ollama", str(e.exception))
        # not running: never pinned, so ai.available() and the offline templates stay as they were (review code-1)
        settings.PATH.write_text("{}", encoding="utf-8")
        connections.PATH.unlink(missing_ok=True)
        self.reply = lambda url: urllib.error.URLError("refused")
        self.assertEqual(connections.link("ollama")["status"], "unreachable")
        self.assertFalse(connections.status()["keys"]["ollama"]["linked"])
        self.assertNotIn("ollama", ai.available())
        self.assertEqual(settings.pref("models"), {})
        self.assertTrue(apply._offline(False))


class Cli(Base):
    def test_keys_link_list_check_and_rm(self):
        real = cli.getpass.getpass
        cli.getpass.getpass = lambda prompt="": KEY
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cli.main(["keys", "link", "anthropic"])
                cli.main(["keys"])
                cli.main(["keys", "list"])
                cli.main(["keys", "check", "anthropic"])
        finally:
            cli.getpass.getpass = real
        self.assertEqual(self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")], KEY)
        text = out.getvalue()
        self.assertIn("Anthropic (Claude): verified", text)
        self.assertIn("console.anthropic.com", text)
        self.assertNotIn(KEY, text)
        os.environ["GROQ_API_KEY"] = "gsk_envenvenv"
        with self.assertRaises(SystemExit) as e:
            cli.main(["keys", "rm", "groq"])
        self.assertIn(".env", str(e.exception))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["keys", "rm", "ANTHROPIC_API_KEY"])
        self.assertNotIn((vault.SERVICE, "ANTHROPIC_API_KEY"), self.store)


class Doctor(Base):
    def test_doctor_rows_follow_the_stored_status(self):
        self.store[(vault.SERVICE, "ANTHROPIC_API_KEY")] = KEY
        rows = {w: (s, d) for s, w, d in doctor.checks()}
        self.assertEqual(rows["key anthropic"][0], "warn")
        self.assertIn("lodestar keys check anthropic", rows["key anthropic"][1])
        connections.check("anthropic")
        rows = {w: (s, d) for s, w, d in doctor.checks()}
        self.assertEqual(rows["key anthropic"][0], "ok")
        self.reply = lambda url: (401, "")
        self.assertEqual(doctor.live_keys(), [("fail", "key check anthropic", connections.verify_key("anthropic")["detail"])])
        rows = {w: (s, d) for s, w, d in doctor.checks()}
        self.assertEqual(rows["key anthropic"][0], "fail")
        self.assertIn("rejected", rows["key anthropic"][1])


class Fetch(unittest.TestCase):
    def test_never_fetch_sites_are_refused_on_the_first_url_and_every_hop(self):
        for u in ("https://www.linkedin.com/jobs/view/1", "https://ca.indeed.com/x", "https://uk.indeed.co.uk/x",
                  "https://www.glassdoor.com/x", "https://ZipRecruiter.com./x"):
            with self.assertRaises(ValueError) as e:
                util._check_url(u)
            self.assertIn("terms forbid automated access", str(e.exception), u)
        os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = "1"  # opens intranets, never these sites
        try:
            with self.assertRaises(ValueError):
                util._check_url("https://www.linkedin.com/in/x")
            for u in ("https://linkedinfluence.example.com/a", "https://jobs.indeedcareers.example.com/a"):
                util._check_url(u)  # names that only contain the word pass
        finally:
            os.environ.pop("LODESTAR_ALLOW_PRIVATE_URLS")
        req = urllib.request.Request("https://lnkd.example.com/abc")
        with self.assertRaises(ValueError):
            util._SafeRedirect().redirect_request(req, None, 302, "Found", {}, "https://www.linkedin.com/jobs/view/1")

    def test_research_respects_robots_and_never_fetches_never_fetch_sites(self):
        from lodestar import db

        fetched = []

        def fake(url, *a, **k):
            util._check_url(url) if "linkedin" in url else None  # what the real fetch does first
            fetched.append(url)
            if url.endswith("/robots.txt"):
                return "User-agent: *\nDisallow: /about\n" if "globex" in url else ""
            return '{"extract": "Globex makes widgets."}' if "wikipedia" in url else "<p>page</p>"
        from lodestar import resume

        prompts, real = [], (util.fetch, ai.ask, resume.candidate_text)
        util.fetch, ai.ask = fake, (lambda p, *a, **k: prompts.append(p) or "pack")
        resume.candidate_text = lambda *a, **k: "Python engineer"
        try:
            jid = db.add_job("Globex", "Eng", url="https://globex.example.com/jobs/1")
            text = extras.research(db.get_job(jid)).read_text(encoding="utf-8")
            self.assertIn("https://globex.example.com/jobs/1", fetched)
            self.assertNotIn("https://globex.example.com/about", fetched)
            self.assertIn("SKIPPED https://globex.example.com/about: robots.txt", prompts[0])
            self.assertNotIn("- https://globex.example.com/about", text)
            fetched.clear()
            jid = db.add_job("Initrode", "Eng", url="https://www.linkedin.com/jobs/view/123")
            extras.research(db.get_job(jid))
            self.assertFalse([u for u in fetched if "linkedin" in u], fetched)
        finally:
            util.fetch, ai.ask, resume.candidate_text = real


if __name__ == "__main__":
    unittest.main()
