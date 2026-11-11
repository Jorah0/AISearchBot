"""Browser extension, server side (pass 20, docs/CAPTURE.md): pairing codes, the pinned Origin, HMAC-signed /api/ext/*
routes kept apart from the page token, capture() shared with the bookmarklet, the employer-safe autofill data (pipeline
answers and CANON keys; the salary floor, Preferences and private answers never leave), the bookmarklets pref and
backups without extension.json. A real server on a free 127.0.0.1 port; time is the only thing faked, and every
patched attribute and touched file is put back."""
import contextlib
import hashlib
import hmac
import http.client
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import db, desktop, extension, extras, profile, settings, web  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

EXT = "chrome-extension://" + "abcdefghijklmnop" * 2
EXT2 = "chrome-extension://" + "ponmlkjihgfedcba" * 2
SRC = "typed under Answers"
MASTER = """# Jane Example
Jane Example | Springfield, IL | jane@example.org | +1 555 010 0199 | linkedin.com/in/jane-example

## Summary
Data engineer.

## Experience
### Senior Data Engineer - Example Corp (2021 - Present)
- Built the pipeline that cut load time 40%

### Data Analyst - Sample LLC (2018 - 2021)
- Wrote the reports

## Education
### BSc Computer Science - State University (2014 - 2018)

## Preferences
Salary floor: 150000
Deal-breakers: night shifts
"""


@contextlib.contextmanager
def kept(*paths):
    old = {p: p.read_bytes() if p.is_file() else None for p in paths}
    try:
        yield
    finally:
        for p, b in old.items():
            if b is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(b)


def sign(secret, ts, path, body: bytes, port: int) -> str:
    return hmac.new(secret.encode(), f"{ts}\nPOST\n{port}\n{path}\n".encode() + body, hashlib.sha256).hexdigest()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = desktop.free_port(8975)
        cls.srv = web.start_server(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        extension.PATH.unlink(missing_ok=True)
        self.addCleanup(extension.PATH.unlink, missing_ok=True)  # a pairing left behind would turn the bookmarklets off
        extension._CODE.update(code=None, expires=0.0, tries=0)
        extension._TOUCHED.clear()
        old = getattr(db._local, "con", None)  # this thread reads the file database the server threads write
        db._local.con = db.connect()
        self.addCleanup(lambda: (db._local.con.close(), setattr(db._local, "con", old)))

    def call(self, method, path, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        c.request(method, path, data, {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        out = r.read()
        c.close()
        return r.status, (json.loads(out) if out else {}), dict(r.getheaders())

    def pair(self, origin=EXT, label="Edge"):
        code = extension.new_code()["code"]
        st, out, _ = self.call("POST", "/api/ext/pair", {"code": code, "label": label}, {"Origin": origin})
        self.assertEqual(st, 200, out)
        return out

    def ext(self, cred, path, obj, origin=EXT, ts=None, secret=None, tamper=None, eid=None, port=None):
        body = json.dumps(obj).encode()
        ts = int(time.time()) if ts is None else ts
        h = f"{eid or cred['id']}.{ts}.{sign(secret or cred['secret'], ts, path, body, port or self.port)}"
        st, out, hdrs = self.call("POST", path, headers={"Origin": origin, "X-Lodestar-Ext": h},
                                  raw=tamper if tamper is not None else body)
        return st, out, hdrs


class Pairing(Base):
    def test_code_is_single_use_expires_and_dies_after_five_wrong_tries(self):
        code = extension.new_code()["code"]
        self.assertRegex(code, r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")
        self.assertTrue(extension.pair(code.lower().replace("-", " "), EXT, "Edge")["secret"])  # normalised input
        with self.assertRaises(SystemExit):
            extension.pair(code, EXT, "Edge")  # single use
        extension._CODE.update(code="K7QX0M1D", expires=time.time() + 300, tries=0)
        self.assertTrue(extension.pair("k7qx-om-id", EXT, "x"))  # O -> 0, I -> 1, separators dropped
        old = extension.new_code()["code"]
        new = extension.new_code()["code"]  # a new code replaces the old one
        if old != new:
            with self.assertRaises(SystemExit):
                extension.pair(old, EXT, "x")
        real = extension.now
        try:
            extension.now = lambda: real() + 301
            with self.assertRaises(SystemExit):
                extension.pair(new, EXT, "x")  # expired
        finally:
            extension.now = real
        code = extension.new_code()["code"]
        for _ in range(5):
            with self.assertRaises(SystemExit):
                extension.pair("0000-0000", EXT, "x")
        with self.assertRaises(SystemExit) as e:
            extension.pair(code, EXT, "x")  # dead after five misses
        self.assertEqual(str(e.exception), extension.BAD_CODE)

    def test_only_an_extension_origin_pairs_and_a_bad_one_burns_no_try(self):
        code = extension.new_code()["code"]
        for origin in ("https://evil.example", "null", "", "chrome-extension://SHORT", EXT.upper(), EXT + "/x"):
            st, out, _ = self.call("POST", "/api/ext/pair", {"code": code}, {"Origin": origin} if origin else {})
            self.assertEqual((st, out["error"]), (403, extension.BAD_CODE), origin)
        self.assertEqual(extension._CODE["tries"], 0)
        st, out, _ = self.call("POST", "/api/ext/pair", {"code": code, "label": "L" * 400}, {"Origin": EXT})
        self.assertEqual(st, 200, out)
        self.assertEqual(set(out), {"id", "secret", "version"})
        listed = extension.paired()
        self.assertEqual(len(listed[0]["label"]), 40)
        self.assertEqual(listed[0]["origin"], EXT)
        self.assertNotIn(out["secret"], json.dumps(listed))
        st, state, _ = self.call("GET", "/api/state", headers={"X-Lodestar-Token": web.TOKEN})
        self.assertEqual([e["id"] for e in state["extensions"]], [out["id"]])
        self.assertNotIn(out["secret"], json.dumps(state))
        st, polled, _ = self.call("GET", "/api/extension/paired", headers={"X-Lodestar-Token": web.TOKEN})  # Setup's poll
        self.assertEqual((st, [e["id"] for e in polled["extensions"]]), (200, [out["id"]]))
        self.assertNotIn(out["secret"], json.dumps(polled))
        self.assertEqual(self.call("GET", "/api/extension/paired")[0], 403)
        st, made, _ = self.call("POST", "/api/extension/code", {}, {"X-Lodestar-Token": web.TOKEN})
        self.assertEqual((st, made["port"], made["expires_in"]), (200, self.port, 300))
        self.assertEqual(self.call("POST", "/api/extension/code", {})[0], 403)  # the page token only

    def test_corrupt_store_fails_closed_and_pairing_still_works(self):
        cred = self.pair()
        extension.PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.ext(cred, "/api/ext/ping", {})[0], 401)
        self.assertEqual(extension.paired(), [])
        again = self.pair()
        self.assertEqual(self.ext(again, "/api/ext/ping", {})[0], 200)


class Signing(Base):
    def test_signature_origin_clock_and_body_are_all_checked(self):
        cred, other = self.pair(), self.pair(EXT2, "Chrome")
        st, out, hdrs = self.ext(cred, "/api/ext/ping", {})
        self.assertEqual(st, 200, out)
        self.assertEqual(out["proof"], hmac.new(cred["secret"].encode(), f"pong\n{out['ts']}\n{self.port}".encode(), hashlib.sha256).hexdigest())
        self.assertNotIn("Access-Control-Allow-Origin", hdrs)  # never CORS on ext routes
        now = int(time.time())
        bad = {
            "wrong secret": self.ext(cred, "/api/ext/ping", {}, secret="nope"),
            "tampered body": self.ext(cred, "/api/ext/capture", {"url": "https://a.example/1"}, tamper=b'{"url": "https://a.example/2"}'),
            "clock skew": self.ext(cred, "/api/ext/ping", {}, ts=now - 121),
            "other id": self.ext(cred, "/api/ext/ping", {}, eid=other["id"]),
            "other pinned origin": self.ext(cred, "/api/ext/ping", {}, origin=EXT2),
            "page origin": self.ext(cred, "/api/ext/ping", {}, origin="https://evil.example"),
        }
        for why, (st, out, _) in bad.items():
            self.assertEqual((st, out), (401, {"error": "not paired"}), why)
        body = b"{}"
        ts = now
        h = f"{cred['id']}.{ts}.{sign(cred['secret'], ts, '/api/ext/capture', body, self.port)}"  # signed for another path
        self.assertEqual(self.call("POST", "/api/ext/ping", headers={"Origin": EXT, "X-Lodestar-Ext": h}, raw=body)[0], 401)
        self.assertEqual(self.call("POST", "/api/ext/ping", {}, {"Origin": EXT})[0], 401)  # no header
        for h in ("", "a.b", "a.12x.c", f"{cred['id']}.²³.ab", "x" * 5000):
            self.assertEqual(self.call("POST", "/api/ext/ping", {}, {"Origin": EXT, "X-Lodestar-Ext": h})[0], 401, h)
        self.assertEqual(self.ext(other, "/api/ext/ping", {}, origin=EXT2)[0], 200)  # the other browser, its own origin

    def test_a_relay_on_another_port_gets_neither_answers_nor_a_usable_proof(self):
        """A local process squatting a scanned port forwards the popup's signed calls (Host rewritten) to the real
        server: the signature names the port the popup dialled, so the real server refuses it, and a proof the real
        server gives names its own port, so the popup's check for the relay's port fails."""
        import http.server
        import threading

        real = self.port

        class Relay(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
                c = http.client.HTTPConnection("127.0.0.1", real, timeout=10)
                c.request("POST", self.path, body, {**hdrs, "Host": f"127.0.0.1:{real}"})
                r = c.getresponse()
                out = r.read()
                c.close()
                self.send_response(r.status)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        relay = http.server.ThreadingHTTPServer(("127.0.0.1", desktop.free_port(real + 50)), Relay)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (relay.shutdown(), relay.server_close()))
        rport = relay.server_address[1]
        cred = self.pair()

        def via_relay(path, obj):  # what popup.js sends when it dials the relay's port
            body = json.dumps(obj).encode()
            ts = int(time.time())
            c = http.client.HTTPConnection("127.0.0.1", rport, timeout=10)
            c.request("POST", path, body, {"Host": f"127.0.0.1:{rport}", "Content-Type": "application/json", "Origin": EXT,
                                           "X-Lodestar-Ext": f"{cred['id']}.{ts}.{sign(cred['secret'], ts, path, body, rport)}"})
            r = c.getresponse()
            out = json.loads(r.read() or b"{}")
            c.close()
            return r.status, out

        self.assertEqual(via_relay("/api/ext/ping", {}), (401, {"error": "not paired"}))
        self.assertEqual(via_relay("/api/ext/autofill", {"url": "https://a.example/apply"}), (401, {"error": "not paired"}))
        st, out, _ = self.ext(cred, "/api/ext/ping", {})  # a ping signed for the real port: the proof names that port
        self.assertEqual(st, 200)
        mac = lambda port: hmac.new(cred["secret"].encode(), f"pong\n{out['ts']}\n{port}".encode(), hashlib.sha256).hexdigest()  # noqa: E731
        self.assertEqual(out["proof"], mac(self.port))
        self.assertNotEqual(out["proof"], mac(rport))  # relayed back, it fails popup.js's check for the relay's port
        self.assertEqual(self.ext(cred, "/api/ext/ping", {}, port=rport)[0], 401)

    def test_ext_routes_and_page_routes_never_share_a_credential(self):
        cred = self.pair()
        body = b"{}"
        ts = int(time.time())
        for path in ("/api/state", "/api/jobs", "/api/extension/code", "/api/extension/revoke", "/api/capture"):
            h = f"{cred['id']}.{ts}.{sign(cred['secret'], ts, path, body, self.port)}"
            self.assertEqual(self.call("POST", path, headers={"Origin": EXT, "X-Lodestar-Ext": h}, raw=body)[0], 403, path)
        self.assertEqual(self.call("POST", "/api/ext/capture", {}, {"X-Lodestar-Token": web.TOKEN})[0], 401)
        self.assertEqual(self.call("POST", f"/api/ext/capture?t={web.CAPTURE_TOKEN}", {})[0], 401)
        self.assertEqual(self.call("GET", "/api/ext/ping")[0], 403)  # GET goes through the page token
        self.assertEqual(self.call("GET", "/api/ext/ping", headers={"X-Lodestar-Token": web.TOKEN})[0], 404)
        self.assertEqual(self.ext(cred, "/api/ext/nope", {})[0], 404)
        st, out, _ = self.call("POST", "/api/ext/ping", headers={"Origin": EXT, "Content-Type": "application/json"}, raw=b"[1]")
        self.assertEqual(st, 400)
        self.assertEqual(self.ext(cred, "/api/ext/ping", [1])[0], 400)  # a signed array body
        self.assertEqual(self.call("POST", "/api/ext/ping", headers={"Origin": EXT, "Content-Type": "text/plain"}, raw=b"{}")[0], 400)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.putrequest("POST", "/api/ext/ping")
        c.putheader("Host", f"127.0.0.1:{self.port}")
        c.putheader("Content-Length", "2000000")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 413)
        c.close()
        for path in ("/api/ext/pair", "/api/ext/capture"):
            self.assertEqual(self.call("POST", path, {}, {"Host": f"attacker.example:{self.port}", "Origin": EXT})[0], 421)
        st, _, hdrs = self.call("OPTIONS", "/api/ext/capture", headers={"Origin": EXT})
        self.assertEqual(st, 404)
        self.assertNotIn("Access-Control-Allow-Origin", hdrs)

    def test_revoke_needs_the_page_token_and_kills_the_credential(self):
        cred = self.pair()
        self.assertEqual(self.call("POST", "/api/extension/revoke", {"id": cred["id"]})[0], 403)
        st, out, _ = self.call("POST", "/api/extension/revoke", {"id": cred["id"]}, {"X-Lodestar-Token": web.TOKEN})
        self.assertEqual((st, out), (200, {"ok": True}))
        self.assertEqual(self.ext(cred, "/api/ext/ping", {})[0], 401)
        self.assertFalse(extension.revoke(cred["id"]))


class Capture(Base):
    def test_capture_reads_json_ld_and_is_shared_with_the_bookmarklet(self):
        cred, made = self.pair(), []
        self.addCleanup(lambda: [db.delete_job(j) for j in made])
        url = "https://boards.example.org/jobs/ext-capture-1"
        post = {"title": "Data Engineer", "company": "Ld Co", "location": "Springfield, IL", "posted_at": "2026-11-01",
                "salary": "USD 120000-150000 YEAR", "description": "&lt;p&gt;We use Python.&lt;/p&gt;&lt;p&gt;And SQL.&lt;/p&gt;",
                "ats_feed": "greenhouse:evil", "notes": "x"}
        st, out, _ = self.ext(cred, "/api/ext/capture", {"title": "ignored | LinkedIn", "url": url, "desc": "body", "posting": post})
        self.assertEqual(st, 200, out)
        made.append(out["id"])
        self.assertEqual((out["company"], out["title"], out["duplicate"]), ("Ld Co", "Data Engineer", False))
        j = db.get_job(out["id"])
        self.assertEqual((j["location"], j["posted_at"], j["ats_feed"]), ("Springfield, IL", "2026-11-01", None))
        self.assertIn("USD 120000-150000 YEAR", j["jd"])
        self.assertRegex(j["jd"], r"We use Python\.\s*\n\s*And SQL\.")  # paragraphs kept apart, no tags
        self.assertNotIn("<p>", j["jd"])
        again = self.ext(cred, "/api/ext/capture", {"title": "x", "url": url})[1]
        self.assertEqual((again["id"], again["duplicate"]), (out["id"], True))
        db.set_status(out["id"], "rejected")
        fresh = self.ext(cred, "/api/ext/capture", {"title": "x", "url": url, "posting": post})[1]
        made.append(fresh["id"])
        self.assertNotEqual(fresh["id"], out["id"])
        self.assertFalse(fresh["duplicate"])
        weird = self.ext(cred, "/api/ext/capture", {"title": "Analyst - Split Co", "url": "javascript:alert(1)",
                                                    "posting": [1, 2]})
        self.assertEqual(weird[0], 200, weird[1])
        made.append(weird[1]["id"])
        self.assertEqual((weird[1]["company"], weird[1]["title"]), ("Split Co", "Analyst"))
        self.assertIsNone(db.get_job(weird[1]["id"])["url"])
        titled = self.ext(cred, "/api/ext/capture", {"title": "Role X - Title Co", "url": "https://a.example/t2",
                                                     "posting": {"title": "Role X"}})[1]
        made.append(titled["id"])
        self.assertEqual(titled["company"], "Title Co")  # a posting without a company falls back to the page title
        bm = web.capture({"title": "BI Dev - Mark Co", "url": "https://a.example/bm"})  # the bookmarklet's shape
        made.append(bm["id"])
        self.assertEqual((bm["company"], bm["title"]), ("Mark Co", "BI Dev"))

    def test_linkedin_is_never_captured_or_filled(self):
        cred = self.pair()
        for path in ("/api/ext/capture", "/api/ext/autofill"):
            for u in ("https://www.linkedin.com/jobs/view/1", "https://linkedin.com/x", "https://de.LinkedIn.com./y"):
                st, out, _ = self.ext(cred, path, {"title": "Role - Co", "url": u})
                self.assertEqual((st, out["error"]), (400, extension.LINKEDIN), (path, u))
        self.assertFalse(extension.linkedin("https://notlinkedin.com/x"))
        self.assertFalse(extension.linkedin("https://linkedin.com.evil.example/x"))


class Autofill(Base):
    def setUp(self):
        super().setUp()
        ctx = kept(PROFILE, profile.BANK)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        before = {r["id"] for r in db.list_answers()}
        self.addCleanup(lambda: [db.delete_answer(r["id"]) for r in db.list_answers() if r["id"] not in before])

    def test_no_floor_preferences_or_private_answer_ever_leaves(self):
        db.save_answer("Why do you want to work here?", "I like building data platforms.", source=SRC)
        db.save_answer("Are you willing to relocate?", "Yes, within the US.", source=SRC)
        db.save_answer("Are you legally authorized to work in the United States?", "Yes", source=SRC)
        db.save_answer("What is your notice period?", "Two weeks.", private=True, source=SRC)
        db.save_answer("Desired salary", "135000", source=SRC)
        db.save_answer("EEO: gender", "Decline to self-identify", tags="eeo", source=SRC)
        db.save_answer("EEO: race", "Prefer not to say", tags="eeo", private=True, source=SRC)
        db.save_answer("EEO: veteran status", "I am not a veteran", tags="eeo", source="AI draft for job #1")
        db.save_answer("Tell me about a conflict you resolved", "STAR story text", source=SRC)
        db.con().execute("UPDATE answers SET star=1 WHERE question='Tell me about a conflict you resolved'")
        db.con().execute("INSERT INTO answers(question,answer,tags,updated_at,private,source) VALUES(?,?,?,?,?,?)",
                         ("Salary expectation", "150000", "", "2026-01-01", 0, SRC))  # saved before the guard
        db.con().commit()
        qs = ["Why do you want to work here?", "Willing to relocate", "Are you authorized to work in the United States?",
              "Notice period", "What are your salary expectations?", "Gender", "Tell me about a conflict you resolved",
              "Pets?", "Why do you want to work for us here"]
        d = extras.ext_autofill(qs)
        dump = json.dumps(d)
        for bad in ("150000", "Preferences", "night shifts", "Two weeks", "STAR story", "Decline", "135000"):
            self.assertNotIn(bad, dump, bad)
        self.assertEqual((d["first_name"], d["last_name"], d["email"]), ("Jane", "Example", "jane@example.org"))
        a = d["answers"]
        self.assertEqual(a["Why do you want to work here?"], {"answer": "I like building data platforms.",
                                                             "question": "Why do you want to work here?", "match": "exact"})
        self.assertEqual(a["Willing to relocate"]["answer"], "Yes, within the US.")  # the CANON key, not the wording
        self.assertEqual(a["Are you authorized to work in the United States?"]["answer"], "Yes")
        self.assertEqual(a["Why do you want to work for us here"]["match"], "suggested")
        self.assertEqual(set(a), {"Why do you want to work here?", "Willing to relocate",
                                  "Are you authorized to work in the United States?", "Why do you want to work for us here"})
        self.assertNotIn("eeo", d)
        self.assertNotIn("salary", d)
        d = extras.ext_autofill(["Gender", "What are your salary expectations?"], eeo=True, salary=True)
        self.assertEqual(d["eeo"], {"gender": "Decline to self-identify"})  # private and AI-drafted EEO rows stay home
        self.assertEqual(d["salary"], "135000")
        self.assertEqual(d["answers"]["Gender"]["answer"], "Decline to self-identify")
        self.assertEqual(d["answers"]["What are your salary expectations?"]["answer"], "135000")
        self.assertNotIn("150000", json.dumps(d))

    def test_a_desired_salary_equal_to_the_floor_and_a_preferences_line_are_withheld(self):
        db.con().execute("INSERT INTO answers(question,answer,tags,updated_at,private,source) VALUES(?,?,?,?,?,?)",
                         ("Desired salary", "150k", "salary", "2026-01-01", 0, SRC))
        db.con().commit()
        bank = profile.load()
        bank["experience"] = [{"title": "Engineer", "company": "Bank Co", "start": "2020", "end": "",
                               "bullets": ["Shipped things", "Salary preferences:", "remote only"]},
                              {"title": "Intern", "company": "Old Co", "start": "2019", "end": "2020", "bullets": ["Learned"]}]
        bank["education"] = [{"school": "State University", "degree": "BSc"}]
        profile.save(bank)
        d = extras.ext_autofill([], salary=True)
        self.assertNotIn("salary", d)
        self.assertEqual([e["company"] for e in d["experience"]], ["Old Co"])  # never sent trimmed
        self.assertGreaterEqual(d["withheld"], 1)
        self.assertEqual(d["education"][0]["school"], "State University")

    def test_history_falls_back_to_the_master_and_the_route_answers(self):
        cred = self.pair()
        st, d, _ = self.ext(cred, "/api/ext/autofill", {"url": "https://a.example/apply", "questions": ["x" * 500, 3, None],
                                                        "eeo": "yes"})
        self.assertEqual(st, 200, d)
        self.assertEqual((d["current_company"], d["current_title"]), ("Example Corp", "Senior Data Engineer"))
        self.assertEqual([e["company"] for e in d["experience"]], ["Example Corp", "Sample LLC"])
        self.assertIn("40%", d["experience"][0]["description"])
        self.assertTrue(d["education"])
        self.assertNotIn("eeo", d)  # only a JSON true ticks it
        self.assertNotIn("150000", json.dumps(d))
        PROFILE.write_text("", encoding="utf-8")
        st, d, _ = self.ext(cred, "/api/ext/autofill", {})
        self.assertEqual(st, 400)  # a template profile: its message, not a crash
        self.assertTrue(d["error"])


class Bookmarklets(Base):
    def test_auto_turns_off_once_paired_and_the_pref_overrides(self):
        def autofill():
            return self.call("GET", f"/api/autofill?t={web.CAPTURE_TOKEN}")

        with kept(settings.PATH, PROFILE):
            PROFILE.write_text(MASTER, encoding="utf-8")
            settings.set_pref("bookmarklets", "auto")
            self.assertEqual(autofill()[0], 200)
            cred = self.pair()
            st, _, hdrs = autofill()
            self.assertEqual(st, 403)
            self.assertNotIn("150000", json.dumps(self.call("GET", "/api/state", headers={"X-Lodestar-Token": web.TOKEN})[1]["extensions"]))
            settings.set_pref("bookmarklets", "on")
            self.assertEqual(autofill()[0], 200)
            settings.set_pref("bookmarklets", "off")
            extension.revoke(cred["id"])
            self.assertEqual(autofill()[0], 403)
            self.assertEqual(self.call("POST", f"/api/capture?t={web.CAPTURE_TOKEN}", {"title": "x"})[0], 403)
            with self.assertRaises(SystemExit):
                settings.set_pref("bookmarklets", "maybe")

    def test_backups_leave_out_extension_json(self):
        self.pair()
        out = Path(tempfile.mkdtemp(prefix="ext-backup-"))
        z = extras.backup(out)
        with zipfile.ZipFile(z) as f:
            self.assertFalse([n for n in f.namelist() if n.endswith("extension.json")])
        self.assertTrue(extension.PATH.is_file())


if __name__ == "__main__":
    unittest.main()
