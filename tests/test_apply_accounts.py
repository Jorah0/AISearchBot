"""Pass 22, builder 'accounts': site accounts (accounts.py) without a browser. The vault (one account per site, the
password only in the OS keyring, never for the forbidden boards), the flows on a site model (FakePage): sign-up filled
and stopped for your Create, never a terms box; a saved account signs in; one per site; a site that already knows your
email; failed and locked sign-ins recorded, never retried, with the site's reset link; a CAPTCHA before anything is
typed; codes and verification links only on your click or on a site you allowed, a link only on the account's host),
codes.py's verification links (memory only, masked), the account window, the routes, the CLI and the static rules.
Real browser runs on local fixture pages are in tests/e2e/e2e_accounts.py. Every patched attribute is put back."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

import keyring  # noqa: E402

from lodestar import accounts, apply_agent, apply_ats, cli, codes, db, extras, profile, vault, web  # noqa: E402

PROF = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com | 512-555-0100\n## Summary\nData engineer.\n## Skills\n"
        "Python, SQL\n## Experience\n### Senior Data Engineer - Globex (2019-01 - Present)\n- Built pipelines\n"
        "## Education\nBS Computer Science\n\n## Preferences\nSalary floor: $123,456\n")
SITE = "acme.wd5.myworkdayjobs.test"
LOGIN = f"https://{SITE}/en-US/External/login"
PASS = "mx.example.com; dkim=pass header.d=myworkday.test; dmarc=pass header.from=myworkday.test"


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class FakePage:
    """The accounts.Page interface over a small site model: states login | signup | code | checkmail | home. opts: bad,
    locked (sign-in verdicts), twostep (a code after sign-in), exists / verify=code|link (after you press Create),
    captcha (a challenge on the sign-up page until you solve it). hook(page) runs on every idle: you, in the window."""
    BUTTONS = {"login": ["Sign In", "Create Account"], "signup": ["Create Account", "Sign In"], "code": ["Verify"]}

    def __init__(self, state="login", hook=None, site=SITE, **opts):
        self.site, self.state, self.hook, self.opts = site, state, hook, opts
        self.typed, self.clicks, self.gone, self.msg, self.ticks = [], [], [], "", 0
        self.vals, self.terms, self.created, self.captcha = {}, False, None, bool(opts.get("captcha"))
        self.tab = types.SimpleNamespace(suspended=False, closed=False, forbidden_hit=None, offsite=None, hosts=[site],
                                         front=lambda: None, goto=self.goto)

    @property
    def url(self):
        return f"https://{self.site}/{self.state}"

    def inputs(self):
        return {"login": [{"a": 0, "frame": 0, "type": "email", "hint": "Email Address email username"},
                          {"a": 1, "frame": 0, "type": "password", "hint": "Password password current-password"}],
                "signup": [{"a": 2, "frame": 0, "type": "email", "hint": "Email Address email"},
                           {"a": 3, "frame": 0, "type": "password", "hint": "Password new-password"},
                           {"a": 4, "frame": 0, "type": "password", "hint": "Verify New Password new-password"},
                           {"a": 5, "frame": 0, "type": "checkbox", "hint": "I agree to the terms"}],
                "code": [{"a": 6, "frame": 0, "type": "text", "hint": "Code otp one-time-code"}]}.get(self.state, [])

    def type(self, d, value, secret=False):
        assert (d["type"] == "password") == secret, d
        assert d["type"] != "checkbox", "never a terms box"
        self.typed.append((self.state, d["a"], value))
        self.vals[d["a"]] = value

    def click(self, rx):
        hits = [b for b in self.BUTTONS.get(self.state, []) if rx.search(b)]
        if len(hits) != 1:
            return False
        b = hits[0]
        assert not (self.state == "signup" and b == "Create Account"), "the agent never presses Create"
        self.clicks.append((self.state, b))
        if self.state == "login" and b == "Create Account":
            self.state, self.msg = "signup", ""
        elif self.state == "signup" and b == "Sign In":
            self.state, self.msg = "login", ""
        elif self.state == "login" and b == "Sign In":
            if self.opts.get("locked"):
                self.msg = "Your account has been locked after too many failed attempts."
            elif self.opts.get("bad"):
                self.msg = "Incorrect email or password."
            elif self.opts.get("unverified"):
                self.msg = "Please verify your email address first."
            else:
                self.state, self.msg = ("code", "") if self.opts.get("twostep") else ("home", "")
        elif self.state == "code" and b == "Verify":
            self.state = "home" if self.vals.get(6) else "code"
        return True

    def you_create(self):
        """You tick the terms box and press Create Account."""
        self.terms, self.created = True, (self.vals.get(2), self.vals.get(3))
        if self.opts.get("exists"):
            self.msg = "An account with this email already exists."
        else:
            self.state = {"code": "code", "link": "checkmail"}.get(self.opts.get("verify"), "home")

    def link(self, rx):
        return f"https://{self.site}/reset-password" if self.state == "login" and rx.search("Forgot your password?") else None

    def goto(self, url):
        assert apply_ats.host(url) == self.site, url
        self.gone.append(url)
        if "activate" in url:
            self.opts["unverified"], self.state, self.msg = False, "login", "Your account is verified. Sign in."
        else:
            self.state, self.msg = "login", ""

    def offsite(self):
        return self.tab.offsite

    def blocker(self):
        if self.captcha:
            return "captcha"
        return "code" if self.state == "code" else "login" if any(d["type"] == "password" for d in self.inputs()) else None

    def text(self):
        return " ".join([{"checkmail": "Check your email: we sent you a link to verify your account.",
                          "code": "Enter the verification code we sent to your email.", "home": "Welcome back"}.get(
            self.state, ""), self.msg])

    def idle(self, ms):
        self.ticks += 1
        assert self.ticks < 400, "a wait nothing ended"
        if self.hook:
            self.hook(self)


class Base(unittest.TestCase):
    def setUp(self):
        profile.write_master(PROF)
        db.release()
        self.store = {}
        for k, f in (("get_password", lambda s, n: self.store.get((s, n))),
                     ("set_password", lambda s, n, v: self.store.__setitem__((s, n), v)),
                     ("delete_password", lambda s, n: self.store.pop((s, n), None))):
            old = getattr(keyring, k)
            setattr(keyring, k, f)
            self.addCleanup(setattr, keyring, k, old)
        self._clear()
        self.addCleanup(self._clear)

    def _clear(self):
        db.release(close=False)
        db.con().execute("DELETE FROM site_accounts")
        db.con().commit()
        idx = vault._index()
        if any(n.startswith("site:") for n in idx):
            vault._save_index({k: v for k, v in idx.items() if not k.startswith("site:")})
        codes._CODES.clear()
        codes._LINKS.clear()
        accounts._REQ.clear()
        accounts._S.clear()

    def pw(self, site=SITE):
        return self.store.get((vault.SERVICE, f"site:{site}"))

    def drive(self, pg, job_id=None, create=True):
        """accounts.handle on pg with the account window's own wait (accounts._swait); returns (result, hint, reasons)."""
        accounts._S.update(action="test", site=pg.site, state="running", needs=[], answers={}, stop=False)
        reasons, real = [], accounts._swait(pg)

        def wait(needs, until, limit=accounts.NEEDS_S):
            reasons.append(needs[0]["reason"])
            return real(needs, until, limit)
        r, hint = accounts.handle(pg, wait, "session", job_id, create)
        return r, hint, reasons


class Vault(Base):
    def test_one_per_site_password_only_in_the_keyring_never_forbidden_boards(self):
        a = accounts.add(LOGIN, "jane@example.com")
        pw = self.pw()
        self.assertEqual(len(pw), 16)
        for pool in (r"[a-z]", r"[A-Z]", r"\d", r"[!@#$%*?_-]"):
            self.assertRegex(pw, pool)
        self.assertEqual(len({accounts.generate() for _ in range(50)}), 50)
        self.assertEqual((a["site"], a["status"], a["label"], a["created_by"]), (SITE, "active", "active", "you"))
        self.assertNotIn(pw, json.dumps(a))
        row = dict(db.con().execute("SELECT * FROM site_accounts WHERE site=?", (SITE,)).fetchone())
        self.assertNotIn(pw, json.dumps(row))  # the row never holds it
        with self.assertRaises(SystemExit):
            accounts.add(f"https://{SITE}/other", "someone@example.com")  # one per site
        other = accounts.add("https://globex.wd1.myworkdayjobs.test/login", "jane@example.com", "Typed-Own-1!")
        self.assertEqual(self.pw("globex.wd1.myworkdayjobs.test"), "Typed-Own-1!")  # another tenant: its own account
        for bad in ("https://www.linkedin.com/login", "https://uk.indeed.co.uk/account", "https://www.glassdoor.com/x",
                    "https://www.ziprecruiter.com/login", "https://www.simplyhired.com/x", "javascript:alert(1)", "acme.test"):
            with self.assertRaises(SystemExit, msg=bad):
                accounts.add(bad, "jane@example.com")
        self.assertEqual(accounts.reveal(a["id"])["password"], pw)
        self.assertEqual([x["site"] for x in accounts.listing("globex")], ["globex.wd1.myworkdayjobs.test"])
        self.assertNotIn("site:", json.dumps(web.state()["vault"]))  # Setup > Other secrets never lists them
        z = extras.backup(Path(tempfile.mkdtemp()))
        with zipfile.ZipFile(z) as zf:
            self.assertFalse([n for n in zf.namelist() if pw.encode() in zf.read(n)])  # never backed up
        accounts._mark(SITE, "failed", error="Incorrect password")
        r = accounts.set_password(a["id"], generate_new=True)
        self.assertEqual((r["password"], accounts.get(a["id"])["status"]), (self.pw(), "active"))  # tried again
        accounts.set_password(a["id"], "Changed-On-Site-9")
        self.assertEqual(self.pw(), "Changed-On-Site-9")
        accounts.set_auto(other["id"], True)
        self.assertTrue(accounts.get(other["id"])["auto_verify"])
        accounts.remove(a["id"])
        self.assertIsNone(self.pw())
        self.assertIsNone(accounts.for_site(SITE))
        with self.assertRaises(SystemExit):
            accounts.reveal(other["id"] + 999)


class Flows(Base):
    def test_signup_is_filled_and_stops_for_your_create_never_a_terms_box(self):
        jid = db.add_job("Acme", "Data Engineer", f"https://{SITE}/job/1", "Python")
        self.addCleanup(db.delete_job, jid)
        seen = {}

        def you(pg):
            if pg.state == "signup" and not pg.terms and pg.vals.get(4):
                seen.update(status=accounts.for_site(SITE)["status"], typed=list(pg.typed), suspended=pg.tab.suspended)
                pg.you_create()
        pg = FakePage(hook=you)
        r, hint, reasons = self.drive(pg, jid)
        self.assertEqual((r, reasons), ("ok", ["account_create"]))
        pw = self.pw()
        self.assertEqual(seen["typed"], [("signup", 2, "jane@example.com"), ("signup", 3, pw), ("signup", 4, pw)])
        self.assertEqual((seen["status"], seen["suspended"]), ("pending", True))  # saved before it was typed
        self.assertEqual(pg.created, ("jane@example.com", pw))
        self.assertEqual(pg.clicks, [("login", "Create Account")])  # never Create on the form: you pressed it
        a = accounts.for_site(SITE)
        self.assertEqual((a["status"], a["created_by"], a["jobs"], a["login_url"]), ("active", "agent", [jid],
                                                                                    f"https://{SITE}/login"))
        self.assertTrue(a["last_login"])

    def test_a_saved_account_signs_in_one_per_site_and_an_existing_one_is_yours(self):
        accounts.add(f"https://{SITE}/login", "jane@example.com", "Saved-Pass-1!")
        pg = FakePage("signup")  # a sign-up form on a site with a saved account: sign in instead
        r, hint, reasons = self.drive(pg)
        self.assertEqual((r, reasons), ("ok", []))
        self.assertEqual(pg.clicks, [("signup", "Sign In"), ("login", "Sign In")])
        self.assertEqual(pg.typed, [("login", 0, "jane@example.com"), ("login", 1, "Saved-Pass-1!")])
        accounts.remove(accounts.for_site(SITE)["id"])

        pg = FakePage(exists=True, hook=lambda p: p.state == "signup" and not p.terms and p.vals.get(4) and p.you_create())
        r, hint, reasons = self.drive(pg)
        self.assertEqual((r, hint), ("yours", accounts.HINT["exists"]))
        self.assertIsNone(accounts.for_site(SITE))  # the unused account and its password are gone
        self.assertIsNone(self.pw())
        self.assertEqual(pg.state, "login")  # sent to the sign-in form, where you sign in with yours

        def own(p):
            if p.state == "signup" and p.vals.get(4) and not accounts._REQ:
                accounts.act("session", "own")
        pg = FakePage(hook=own)
        r, hint, _ = self.drive(pg)
        self.assertEqual((r, hint, accounts.for_site(SITE)), ("yours", accounts.HINT["own"], None))
        pg = FakePage()
        self.assertEqual(self.drive(pg, create=False)[:2], ("yours", accounts.HINT["yours"]))  # Re-login never creates
        self.assertEqual(pg.typed, [])

    def test_failed_and_locked_are_recorded_never_retried_and_offer_the_reset_link(self):
        a = accounts.add(f"https://{SITE}/login", "jane@example.com", "Old-Pass-1!")
        pg = FakePage(bad=True)
        r, hint, _ = self.drive(pg)
        got = accounts.get(a["id"])
        self.assertEqual((r, hint, got["status"], got["reset_url"]), ("yours", accounts.HINT["failed"], "failed",
                                                                      f"https://{SITE}/reset-password"))
        self.assertIn("Incorrect email or password", got["last_error"])
        pg = FakePage(bad=True)
        self.assertEqual(self.drive(pg)[:2], ("yours", accounts.HINT["failed"]))
        self.assertEqual(pg.typed, [])  # never tried again by itself: no lockout
        accounts.set_password(a["id"], "New-Pass-2!")  # you reset it on the site: tried once more
        pg = FakePage()
        self.assertEqual(self.drive(pg)[0], "ok")
        self.assertEqual((pg.typed[-1][2], accounts.get(a["id"])["status"], accounts.get(a["id"])["last_error"]),
                         ("New-Pass-2!", "active", None))
        pg = FakePage(locked=True)
        self.assertEqual(self.drive(pg)[:2], ("yours", accounts.HINT["locked"]))
        self.assertEqual(accounts.get(a["id"])["status"], "locked")

    def test_a_captcha_is_yours_before_anything_is_typed(self):
        seen = []

        def you(pg):
            if pg.captcha and accounts._S.get("state") == "needs_you":
                seen.append(list(pg.typed))
                pg.captcha = False  # you solved it
                accounts.act("session", "continue")
            elif pg.state == "signup" and not pg.terms and pg.vals.get(4):
                pg.you_create()
        pg = FakePage("signup", captcha=True, hook=you)
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons[0], seen), ("ok", "captcha", [[]]))

    def test_codes_and_links_only_on_your_click_or_a_site_you_allowed(self):
        now = datetime.now(timezone.utc)

        def code(c, domain="myworkday.test"):
            codes._CODES[c] = {"id": c, "code": "48" + c[-4:], "sender": f"no-reply@{domain}", "domain": domain,
                               "subject": "Your code", "received": now}
        # 2-step code after sign-in: nothing typed until you click Fill code
        accounts.add(f"https://{SITE}/login", "jane@example.com", "Saved-Pass-1!")
        code("c0001")
        state = {"n": 0}

        def you(pg):
            if pg.state == "code" and accounts._S.get("state") == "needs_you":
                state["n"] += 1
                if state["n"] == 3:
                    self.assertNotIn(6, pg.vals)  # it waited for your click
                    accounts.act("session", "code", "c0001")
        pg = FakePage(twostep=True, hook=you)
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons, pg.vals[6], codes._CODES), ("ok", ["account_code"], "480001", {}))
        self.assertEqual(pg.clicks[-1], ("code", "Verify"))
        with self.assertRaises(SystemExit):
            accounts.act("session", "code", "gone1")  # a code that is not (or no longer) there
        # a site you allowed: a code from its sender is used by itself; one from another sender never
        a = accounts.for_site(SITE)
        accounts.set_auto(a["id"], True)
        code("c0002", domain="evil-mail.test")
        pg = FakePage(twostep=True, hook=lambda p: p.ticks > 20 and accounts.act("session", "continue"))
        with patched(codes, poll=lambda: []):
            self.drive(pg)
        self.assertNotIn(6, pg.vals)
        code("c0003")
        pg = FakePage(twostep=True)
        with patched(codes, poll=lambda: []):
            self.assertEqual(self.drive(pg)[0], "ok")
        self.assertEqual(pg.vals[6], "480003")
        accounts.remove(a["id"])
        # email verification by link: only a link on the account's own host opens, on your click
        codes._LINKS.update({"l0001": {"id": "l0001", "url": "https://evil.test/activate?t=1", "host": "evil.test",
                                       "sender": "x@evil.test", "domain": "evil.test", "subject": "Verify", "received": now},
                             "l0002": {"id": "l0002", "url": f"https://{SITE}/activate?t=2", "host": SITE,
                                       "sender": "no-reply@myworkday.test", "domain": "myworkday.test",
                                       "subject": "Verify your account", "received": now}})
        refused = []

        def you2(pg):
            if pg.state == "signup" and not pg.terms and pg.vals.get(4):
                pg.you_create()
            elif pg.state == "checkmail" and accounts._S.get("state") == "needs_you" and not accounts._REQ:
                with self.assertRaises(SystemExit):
                    accounts.act("session", "link", "l0001")
                refused.append(True)
                accounts.act("session", "link", "l0002")
        pg = FakePage(verify="link", unverified=True, hook=you2)
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons, refused), ("ok", ["account_create", "account_link"], [True]))
        self.assertEqual(pg.gone, [f"https://{SITE}/activate?t=2"])
        self.assertEqual(accounts.for_site(SITE)["status"], "active")
        self.assertNotIn("l0002", codes._LINKS)

    def test_verification_links_from_mail_memory_only_masked_and_authenticated(self):
        def mail(auth=PASS, minutes=0):
            m = EmailMessage()
            m["From"], m["To"], m["Subject"] = "Workday <no-reply@myworkday.test>", "jane@example.com", "Verify your account"
            m["Date"] = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%a, %d %b %Y %H:%M:%S +0000")
            if auth:
                m["Authentication-Results"] = auth
            m.set_content("Welcome to Acme careers.")
            m.add_alternative(f'<p>Welcome.</p><p><a href="https://{SITE}/activate?token=S3cr3t&amp;u=1">Verify my email</a>'
                              '</p><p><a href="https://www.myworkday.test/privacy">Privacy</a></p>', subtype="html")
            return m
        codes.offer(mail())
        self.assertEqual([(x["host"], x["domain"]) for x in codes.links()], [(SITE, "myworkday.test")])
        self.assertNotIn("url", codes.links()[0])  # the page sees the host, never the link
        self.assertEqual(codes.link_url(codes.links()[0]["id"]), f"https://{SITE}/activate?token=S3cr3t&u=1")
        codes._LINKS.clear()
        codes.offer(mail(auth=""))  # a spoofed sender: nothing kept
        codes.offer(mail(minutes=20))  # too old
        self.assertEqual(codes.links(), [])
        _, body = codes.mask("Verify your account", f"Click https://{SITE}/activate?token=S3cr3t to verify. See "
                             "https://www.myworkday.test/careers for jobs and more about the role we posted last week here.")
        self.assertNotIn("S3cr3t", body)
        self.assertIn("[verification link]", body)


class Window(Base):
    def test_the_account_window_refusals_and_a_relogin(self):
        a = accounts.add(f"https://{SITE}/login", "jane@example.com", "Saved-Pass-1!")
        pg, closed = FakePage("home"), []
        pg.BUTTONS = dict(FakePage.BUTTONS, home=["Sign In"])  # the page shows its form behind a Sign in button
        orig = pg.click

        def click(rx):
            if pg.state == "home" and rx.search("Sign In"):
                pg.state = "login"
                return True
            return orig(rx)
        pg.click = click
        browser = types.SimpleNamespace(open=lambda url, hosts: pg.tab, close=lambda: closed.append(1))
        with patched(accounts, Page=lambda tab, site=None: pg), patched(apply_agent, _ensure_worker=lambda: None):
            accounts.start("relogin", a["id"], new_driver=lambda: browser, background=False)
        self.assertEqual((accounts._S["state"], accounts._S["result"], closed), ("done", "ok", [1]))
        self.assertIn("signed in", accounts.session()["step"])
        self.assertTrue(accounts.get(a["id"])["last_login"])
        with self.assertRaises(SystemExit):
            accounts.start("create", url=f"https://{SITE}/login")  # saved already: Re-login
        with self.assertRaises(SystemExit):
            accounts.start("create", url="https://www.linkedin.com/signup")
        jid = db.add_job("Live Co", "Data Engineer", "https://jobs.example-ats.test/live/acct", "Python")
        self.addCleanup(db.delete_job, jid)
        rid = db.add_run(jid, "stop")
        db.update_run(rid, state="running", heartbeat=db._now())
        with self.assertRaises(SystemExit):
            accounts.start("relogin", a["id"])  # the agent holds the profile
        db.update_run(rid, state="stopped")
        accounts._S.update(state="needs_you", site=SITE, answers={})
        with self.assertRaises(SystemExit):
            apply_agent.login_window(f"https://{SITE}/login")  # the account window holds it
        with self.assertRaises(SystemExit):
            apply_agent.forget_logins()
        with self.assertRaises(SystemExit):
            accounts.act("run:%d" % rid, "code", "x")  # not waiting here
        with self.assertRaises(SystemExit):
            accounts.act("session", "code", "nope")  # an expired code
        self.assertEqual(accounts.waiting()[0]["target"], "session")


class Runs(Base):
    def test_the_apply_run_hands_a_sign_in_page_to_the_account_flow(self):
        sys.path.insert(0, str(Path(__file__).parent))
        from test_apply_engine import BASIC, HOST, FakeBrowser  # noqa: E402

        calls = []

        def handle(pg, wait, key, job_id=None, create=True):
            calls.append((key, job_id, pg.site))
            if len(calls) == 1:
                pg.tab.b.model["pages"][0]["blocker"] = None  # signed in
                return "ok", ""
            return "yours", accounts.HINT["failed"]
        old_ats = apply_ats.ATS
        apply_ats.ATS = old_ats | {"exampleats": r"(?:^|\.)example-ats\.test$"}
        self.addCleanup(setattr, apply_ats, "ATS", old_ats)
        self.addCleanup(apply_agent.STOP.unlink, True)
        out = []
        for n in range(2):
            jid = db.add_job("Acme Robotics", "Data Engineer", f"https://{HOST}/acct/{n}", "Python SQL")
            self.addCleanup(db.delete_job, jid)
            from lodestar import resume
            (resume.app_dir(db.get_job(jid)) / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
            hints = []

            def hook(tab, hints=hints):
                run = db.get_run(r["run_id"])
                if run["state"] == "needs_you":
                    hints.append(run["needs"][0]["hint"])
                    apply_agent.stop()
                elif run["state"] == "ready":
                    apply_agent.stop()
            r = apply_agent.enqueue([jid], "stop", start=False)[0]
            b = FakeBrowser({"pages": [{"fields": BASIC, "submit": True, "blocker": "login"}], "hook": hook})
            with patched(accounts, handle=handle, Page=lambda tab, site=None: types.SimpleNamespace(tab=tab, site=tab.host())):
                apply_agent._loop(lambda: b, until_idle=True)
            apply_agent.STOP.unlink(missing_ok=True)
            apply_agent._EVENT.clear()
            out.append((db.get_run(r["run_id"]), hints))
        self.assertEqual(calls, [(f"run:{out[0][0]['id']}", out[0][0]["job_id"], HOST),
                                 (f"run:{out[1][0]['id']}", out[1][0]["job_id"], HOST)])
        self.assertEqual(out[0][0]["plan"][0]["page"], 1)  # signed in: the form was filled
        self.assertEqual(out[1][1][0], accounts.HINT["failed"])  # yours: the usual handoff, with the account's hint


class Surfaces(Base):
    def test_page_types_a_password_only_into_a_password_field_on_its_own_site(self):
        typed = []

        class Loc:
            def __init__(self, t):
                self.t = t

            def get_attribute(self, k):
                return self.t

            def fill(self, v):
                typed.append(v)

        def frame(host, t):
            return types.SimpleNamespace(url=f"https://{host}/x", locator=lambda sel: Loc(t))
        tab = types.SimpleNamespace(url=f"https://{SITE}/login", host=lambda: SITE, forbidden_hit=None, goto=typed.append,
                                    page=types.SimpleNamespace(frames=[frame(SITE, "password")]))
        pg = accounts.Page(tab)
        pg._f = [frame(SITE, "password"), frame("evil.test", "password"), frame(SITE, "email")]
        pg.type({"a": 0, "frame": 0}, "pw", secret=True)
        for d, secret in (({"a": 0, "frame": 0}, False), ({"a": 0, "frame": 2}, True), ({"a": 0, "frame": 1}, True)):
            with self.assertRaises(SystemExit):
                pg.type(d, "x", secret=secret)  # no username in a password field, no password elsewhere, no other host
        tab.forbidden_hit = "www.linkedin.com"
        with self.assertRaises(SystemExit):
            pg.type({"a": 0, "frame": 0}, "pw", secret=True)
        with self.assertRaises(SystemExit):
            pg.goto("https://evil.test/activate")
        self.assertEqual(typed, ["pw"])

    def test_routes_need_the_token_cli_and_static_rules(self):
        import http.client

        srv = web.start_server(0)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]

        def call(method, path, body=None, token=True):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            h = {"Content-Type": "application/json", **({"X-Lodestar-Token": web.TOKEN} if token else {})}
            c.request(method, path, json.dumps(body) if body is not None else None, h)
            resp = c.getresponse()
            return resp.status, json.loads(resp.read() or b"{}")
        for m, p in (("GET", "/api/accounts"), ("POST", "/api/accounts/add"), ("POST", "/api/accounts/create"),
                     ("POST", "/api/accounts/act"), ("POST", "/api/accounts/1/reveal"), ("POST", "/api/accounts/1/remove")):
            self.assertEqual(call(m, p, {} if m == "POST" else None, token=False)[0], 403, p)
        st, a = call("POST", "/api/accounts/add", {"url": f"https://{SITE}/login", "username": "jane@example.com"})
        self.assertEqual((st, a["site"]), (200, SITE))
        st, body = call("GET", "/api/accounts")
        self.assertEqual([x["site"] for x in body["accounts"]], [SITE])
        self.assertNotIn(self.pw(), json.dumps(body))  # never in a listing
        self.assertEqual(call("POST", f"/api/accounts/{a['id']}/reveal", {})[1]["password"], self.pw())
        self.assertEqual(call("POST", "/api/accounts/add", {"url": "https://www.indeed.com/x", "username": "j"})[0], 400)
        self.assertEqual(call("POST", f"/api/accounts/{a['id']}/auto", {"on": True})[1]["auto_verify"], True)
        self.assertEqual(call("POST", f"/api/accounts/{a['id']}/remove", {})[1]["site"], SITE)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["accounts", "add", f"https://{SITE}/login", "jane@example.com", "--password", "Cli-Pass-1!"])
            cli.main(["accounts", "list"])
            aid = accounts.for_site(SITE)["id"]
            cli.main(["accounts", "password", str(aid), "--generate"])
            cli.main(["accounts", "remove", str(aid)])
        text = out.getvalue()
        self.assertIn(f"#{aid} {SITE} jane@example.com [active]", text)
        self.assertNotIn("Cli-Pass-1!", text)
        self.assertIn("new password", text)
        self.assertIsNone(accounts.for_site(SITE))
        src = Path(accounts.__file__).read_text(encoding="utf-8")
        code = "\n".join(ln.split("#")[0] for ln in src.split('"""', 2)[2].splitlines())
        for rx in (r"ignore_default_args", r"add_init_script", r"webdriver\s*=", r"user_agent\s*=", r"stealth",
                   r"2captcha|anti-captcha|capsolver|capmonster", r"\brandom\b", r"--disable-blink-features"):
            self.assertIsNone(re.search(rx, code, re.I), rx)
        for ln in code.splitlines():  # nothing secret is logged
            if "log." in ln:
                self.assertIsNone(re.search(r"pw|password|secret|code\b|_secret", ln.split("log.", 1)[1]), ln)
        self.assertEqual(len(re.findall(r"vault\.get\(", code)), 3)  # Reveal, the sign-in, the general password only


if __name__ == "__main__":
    unittest.main()
