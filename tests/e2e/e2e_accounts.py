"""Site accounts in a real browser (Playwright on the installed Edge, headless) against a fictional local account portal
(tests/fixtures/apply/account.html, served from 127.0.0.1 under fictional hosts via MAP * 127.0.0.1), plus the Setup >
Site accounts card. Each flow uses its own temporary browser profile, never the agent's real one. 'You' act from the
worker's / account window's idle hook (the only thread that may touch the page): ticking the terms box and pressing
Create, solving the fake challenge, clicking Fill code or Open link."""
import contextlib
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness import NO_PLAYWRIGHT, PROFILE_MD, E2ETestCase
from lodestar import accounts, apply_agent, apply_ats, codes, db, profile, resume, settings, util, vault

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "apply"
KIND = os.environ.get("LODESTAR_E2E_BROWSER", "msedge").strip().lower()
LAUNCH = {} if KIND == "chromium" else {"channel": KIND}
HOST = "apply.example-ats.test"
EMAIL = "pat.rivera@example.com"


@contextlib.contextmanager
def _patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class AccountFlows(E2ETestCase):
    """No Lodestar page here: the agent drives its own browser. The harness gives the temp home, fakes and seed."""

    @classmethod
    def setUpClass(cls):
        if NO_PLAYWRIGHT:
            raise unittest.SkipTest(NO_PLAYWRIGHT)
        cls.ai_calls, cls.urls, cls.opened = [], [], []
        cls._home()
        cls._fakes()
        cls.ids = {}
        profile.write_master(PROFILE_MD)
        db.release()
        cls._patch(apply_ats, "ATS", apply_ats.ATS | {"exampleats": r"(?:^|\.)example-ats\.test$"})
        cls._patch(util, "notify", lambda msg: cls.opened.append(("notify", msg)))

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(FIXTURES)))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(lambda: (cls.srv.shutdown(), cls.srv.server_close()))
        cls.port = cls.srv.server_address[1]
        try:
            b = apply_ats.open_browser(Path(tempfile.mkdtemp(dir=cls.home)) / "probe", apply_agent.forbidden, True, LAUNCH)
            b.close()
        except Exception as e:
            raise unittest.SkipTest(f"no {KIND} browser for Playwright: {str(e).splitlines()[0][:200]}") from None

    def setUp(self):
        self.tabs, self.held = [], []
        st = settings.load()
        self.addCleanup(settings.save, st)
        apply_agent.STOP.unlink(missing_ok=True)
        apply_agent._EVENT.clear()
        codes._CODES.clear()
        codes._LINKS.clear()
        accounts._REQ.clear()
        accounts._S.clear()
        self.profile_dir = Path(tempfile.mkdtemp(dir=self.home)) / "browser-profile"  # one per test: its own localStorage
        self.addCleanup(shutil.rmtree, self.profile_dir.parent, True)

    def tearDown(self):
        while self.held:
            self.held.pop()()
        for a in accounts.listing():
            accounts.remove(a["id"])
        db.release(close=False)

    def url(self, query="", page="account.html"):
        return f"http://{HOST}:{self.port}/{page}{'?' + query if query else ''}"

    def browser(self, hook, state):
        """The agent's browser on this test's profile, every tab's idle calling hook(tab, state())."""
        b = apply_ats.open_browser(self.profile_dir, apply_agent.forbidden, os.environ.get("LODESTAR_E2E_HEADED") != "1",
                                   LAUNCH, resolver=["MAP * 127.0.0.1"])
        opened, idle = b.open, b.idle

        def act(tab):
            if tab is not None and not tab.closed:
                hook(tab, state())

        def open_(url, hosts):
            t = opened(url, hosts)
            t_idle = t.idle
            t.idle = lambda ms: (t_idle(min(ms, 300)), act(t))[0]
            self.tabs.append(t)
            return t
        b.open = open_
        b.idle = lambda ms: (idle(min(ms, 300)), act(self.tabs[-1] if self.tabs else None))[0]
        return b

    def work(self, jid: int, hook) -> dict:
        """Queue the job (stop mode) and run the worker here until nothing is live; hook(tab, run) acts as you."""
        r = apply_agent.enqueue([jid], "stop", start=False)[0]
        self.assertIn("run_id", r, r)
        b = self.browser(hook, lambda: db.get_run(r["run_id"]))
        self.held.append(b.close)  # the real close, after the asserts: the test reads the page first
        b.close = lambda: None
        with _patched(apply_agent, RUN_S=120, NEEDS_S=60, WATCH_S=60, REVIEW_S=60):
            apply_agent._loop(lambda: b, until_idle=True)
        return db.get_run(r["run_id"])

    def window(self, action, hook, aid=None, url=None) -> dict:
        """An account window (Re-login / Create) run here, in this thread; hook(tab, session) acts as you."""
        while self.held:  # one Playwright per thread at a time
            self.held.pop()()
        self.tabs = []
        b = self.browser(hook, accounts.session)
        self.held.append(b.close)
        b.close = lambda: None
        with _patched(accounts, NEEDS_S=60), _patched(apply_agent, _ensure_worker=lambda: None):
            accounts.start(action, aid, url, new_driver=lambda: b, background=False)
        return accounts.session()

    def job(self, query: str) -> int:
        jid = db.add_job("Example Robotics", "Data Engineer", f"https://jobs.example.com/robotics/{self.id()}", "Python SQL")
        db.set_fields(jid, apply_url=self.url(query))
        (resume.app_dir(db.get_job(jid)) / "resume.pdf").write_bytes(b"%PDF-1.4 fictional resume")
        return jid

    @staticmethod
    def dom(tab, js: str):
        return tab.page.evaluate(js)

    def secret(self):
        return vault.get(f"site:{HOST}")

    # --- in an application: the agent fills the sign-up form and stops; you press Create; the run goes on
    def test_the_agent_fills_the_sign_up_you_press_create_and_the_application_goes_on(self):
        seen = {}

        def you(tab, run):
            n = (run["needs"] or [{}])[0]
            if run["state"] == "needs_you" and n.get("reason") == "account_create" and not seen:
                seen.update(self.dom(tab, """() => ({email: su_email.value, pw: su_pw.value, pw2: su_pw2.value,
                    terms: terms.checked, created: window.__created || null})"""), site=n["site"])
                tab.page.check("#terms")  # you agree to the terms and press Create
                tab.page.click("#su_btn")
            elif run["state"] == "ready":
                apply_agent.stop()
        jid = self.job("next=form.html")
        run = self.work(jid, you)
        pw = self.secret()
        self.assertEqual(seen, {"email": EMAIL, "pw": pw, "pw2": pw, "terms": False, "created": None, "site": HOST})
        self.assertEqual(self.dom(self.tabs[0], "() => window.__created || null"), None)  # navigated on: the form page
        a = accounts.for_site(HOST)
        self.assertEqual((a["status"], a["created_by"], a["username"], a["jobs"]), ("active", "agent", EMAIL, [jid]))
        self.assertTrue(a["last_login"])
        self.assertEqual(self.dom(self.tabs[0], "() => first_name.value"), "Pat")  # signed in: the application was filled
        self.assertEqual([p["page"] for p in run["plan"]], [1, 2])

    # --- a CAPTCHA is yours before anything is typed; a site that already knows your email is yours too
    def test_a_captcha_is_handed_to_you_first_and_an_existing_email_leaves_no_account(self):
        did, hints = [], []

        def you(tab, run):
            n = (run["needs"] or [{}])[0]
            if run["state"] != "needs_you":
                return
            if n.get("reason") == "captcha" and "captcha" not in did:
                did.append("captcha")
                hints.append(self.dom(tab, "() => su_email.value"))  # nothing typed yet
                tab.page.evaluate("() => document.getElementById('captcha').remove()")  # you solved it
                apply_agent.continue_run(run["id"])
            elif n.get("reason") == "account_create" and "create" not in did:
                did.append("create")
                tab.page.check("#terms")
                tab.page.click("#su_btn")
            elif n.get("reason") == "login" and "login" not in did:
                did.append("login")
                hints.append(n["hint"])
                apply_agent.stop()
        run = self.work(self.job("captcha=1&exists=1"), you)
        self.assertEqual(did, ["captcha", "create", "login"])
        self.assertEqual(hints, ["", accounts.HINT["exists"]])
        self.assertIsNone(accounts.for_site(HOST))  # the unused account and its password are gone
        self.assertIsNone(self.secret())
        self.assertEqual(self.dom(self.tabs[0], "() => window.__created.email"), EMAIL)
        self.assertFalse(self.dom(self.tabs[0], "() => document.querySelector('#signin').hidden"))  # sent to Sign In
        self.assertEqual(run["state"], "stopped")

    # --- the account window: create with an emailed code (your click), re-login, a wrong password recorded
    def test_create_with_a_code_relogin_and_a_failed_sign_in_with_its_reset_link(self):
        codes._CODES["c1"] = {"id": "c1", "code": "482913", "sender": "no-reply@example-ats.test", "domain": "example-ats.test",
                              "subject": "Your verification code", "received": datetime.now(timezone.utc)}
        did = []

        def you(tab, s):
            n = (s.get("needs") or [{}])[0]
            if s.get("state") != "needs_you":
                return
            if n.get("reason") == "account_create" and "create" not in did:
                did.append("create")
                tab.page.check("#terms")
                tab.page.click("#su_btn")
            elif n.get("reason") == "account_code" and "code" not in did:
                did.append("code")
                self.assertEqual(self.dom(tab, "() => otp.value"), "")  # waits for your click
                accounts.act("session", "code", "c1")
        s = self.window("create", you, url=self.url("verify=code"))
        self.assertEqual((did, s["state"], s["result"]), (["create", "code"], "done", "ok"))
        a = accounts.for_site(HOST)
        self.assertEqual((a["status"], a["created_by"]), ("active", "agent"))
        self.assertEqual(codes._CODES, {})  # used once
        first = a["last_login"]
        s = self.window("relogin", lambda tab, s: None, aid=a["id"])  # the same profile: the portal remembers the account
        self.assertEqual((s["state"], s["result"]), ("done", "ok"))
        self.assertTrue(accounts.get(a["id"])["last_login"] >= first)
        accounts.set_password(a["id"], "Wrong-Pass-1!")
        s = self.window("relogin", lambda tab, s: s.get("state") == "needs_you" and accounts.act("session", "continue"),
                        aid=a["id"])
        got = accounts.get(a["id"])
        self.assertEqual((got["status"], got["last_error"]), ("failed", "Incorrect email or password."))
        self.assertEqual(got["reset_url"], self.url("verify=code") + "#reset")  # the site's own reset link
        self.assertEqual(self.dom(self.tabs[0], "() => window.__signins"), 1)
        self.assertEqual(s["result"], "yours")
        signins = []
        self.window("relogin", lambda tab, s: s.get("state") == "needs_you" and (signins.append(
            self.dom(tab, "() => window.__signins || 0")), accounts.act("session", "continue")), aid=a["id"])
        self.assertEqual(signins[:1], [0])  # never tried again by itself: no lockout

    # --- a verification link opens only on the account's own site, on your click
    def test_a_verification_link_opens_only_on_the_accounts_site(self):
        now = datetime.now(timezone.utc)
        codes._LINKS.update({
            "evil1": {"id": "evil1", "url": f"http://careers.example-robotics.test:{self.port}/account.html?activate=1",
                      "host": "careers.example-robotics.test", "sender": "x@example-robotics.test",
                      "domain": "example-robotics.test", "subject": "Verify", "received": now},
            "good1": {"id": "good1", "url": self.url("activate=1"), "host": HOST, "sender": "no-reply@example-ats.test",
                      "domain": "example-ats.test", "subject": "Verify your account", "received": now}})
        did = []

        def you(tab, s):
            n = (s.get("needs") or [{}])[0]
            if s.get("state") != "needs_you":
                return
            if n.get("reason") == "account_create" and "create" not in did:
                did.append("create")
                tab.page.check("#terms")
                tab.page.click("#su_btn")
            elif n.get("reason") == "account_link" and "link" not in did:
                did.append("link")
                self.assertEqual(accounts.for_site(HOST)["status"], "needs_verification")
                with self.assertRaises(SystemExit):
                    accounts.act("session", "link", "evil1")
                accounts.act("session", "link", "good1")
        s = self.window("create", you, url=self.url("verify=link"))
        self.assertEqual((did, s["result"]), (["create", "link"], "ok"))
        self.assertEqual(accounts.for_site(HOST)["status"], "active")
        self.assertIn("evil1", codes._LINKS)
        self.assertNotIn("good1", codes._LINKS)


class AccountsPanel(E2ETestCase):
    """Accounts > Site accounts: list, search, copy, reveal, change password, inbox switch, reset, re-login, remove, save a
    login, create; waiting steps with Fill code and Continue; every page string escaped."""

    @classmethod
    def seed(cls):
        super().seed()
        a = accounts.add("https://acme.wd5.myworkdayjobs.example/en-US/External/login", "pat.rivera@example.com", "Seed-Pass-1!")
        b = accounts.add("https://careers-globex.icims.example/jobs/login", "<b>pat</b>", "Seed-Pass-2!")
        accounts.link_job(a["site"], cls.ids["saved"])
        accounts._mark(b["site"], "failed", error="<img src=x onerror=alert(1)>Incorrect password",
                       reset="https://careers-globex.icims.example/reset")
        cls.ids |= {"acct_a": a["id"], "acct_b": b["id"]}

    def setUp(self):
        super().setUp()
        self.calls = []
        for name, fn in (("start", lambda action, aid=None, url=None, **kw: self.calls.append((action, aid, url)) or {}),):
            old = getattr(accounts, name)
            setattr(accounts, name, fn)
            self.addCleanup(setattr, accounts, name, old)
        old = apply_agent.login_window
        apply_agent.login_window = lambda url=None: self.calls.append(("window", url)) or {"opened": True, "url": url}
        self.addCleanup(setattr, apply_agent, "login_window", old)
        self.go("accounts")
        self.page.wait_for_selector("#acctList .acct")

    def row(self, site):
        return self.page.locator("#acctList .acct", has_text=site)

    def test_list_search_reveal_change_password_reset_relogin_and_remove(self):
        self.assertEqual(self.page.locator("#acctList .acct").count(), 2)
        a = self.row("acme.wd5.myworkdayjobs.example")
        self.assertIn("active", a.text_content())
        self.assertIn("Northwind Analytics", a.text_content())  # the job it was used for
        b = self.row("careers-globex.icims.example")
        self.assertIn("sign-in failed", b.text_content())
        self.assertIn("<b>pat</b>", b.text_content())  # escaped, shown as text
        self.assertEqual(self.page.locator("#acctList img").count(), 0)
        self.assertEqual(a.get_by_role("button", name="Reset password on the site").count(), 0)
        self.page.fill("#acctQ", "icims")
        self.assertEqual(self.page.locator("#acctList .acct").count(), 1)
        self.page.fill("#acctQ", "")
        a.get_by_role("button", name="Reveal").click()
        self.idle()
        self.assertEqual(self.page.text_content(f"#acctShow{self.ids['acct_a']}"), "Seed-Pass-1!")
        a.get_by_role("button", name="Hide").click()
        self.assertEqual(self.page.text_content(f"#acctShow{self.ids['acct_a']}"), "")
        self.assertNotIn("Seed-Pass", json.dumps(self.api("/api/accounts")))  # never in the listing
        a.locator("summary", has_text="Change password").click()
        a.get_by_role("button", name="Generate a new one").click()
        self.idle()
        a = self.row("acme.wd5.myworkdayjobs.example")
        new = self.page.text_content(f"#acctShow{self.ids['acct_a']}")
        self.assertEqual(len(new), 16)
        self.assertEqual(vault.get("site:acme.wd5.myworkdayjobs.example"), new)
        a.locator("input[type=checkbox]").check()
        self.idle()
        self.assertTrue(accounts.get(self.ids["acct_a"])["auto_verify"])
        self.run_click(b.get_by_role("button", name="Reset password on the site"))
        self.answer(True)
        self.run_click(a.get_by_role("button", name="Re-login"))
        self.assertEqual(self.calls, [("window", "https://careers-globex.icims.example/reset"),
                                      ("relogin", self.ids["acct_a"], None)])
        self.answer(True)
        self.run_click(b.get_by_role("button", name="Remove"))
        self.assertEqual(self.page.locator("#acctList .acct").count(), 1)
        self.assertIsNone(vault.get("site:careers-globex.icims.example"))

    def test_general_login_and_finish_sign_ups_switch(self):
        self.addCleanup(lambda: accounts.general()["set"] and accounts.set_general(clear=True))
        self.addCleanup(settings.set_pref, "accounts_auto_create", False)
        self.page.click("#acctGen summary")
        self.assertEqual(self.page.text_content("#acctGenState"), "(not set)")
        self.page.fill("#acctGenUser", "pat.rivera")
        self.page.fill("#acctGenPw", "General-Pass-9!")
        self.run_click("#acctGen >> text=Save")
        self.expect_toast("general login saved", "ok")
        self.assertEqual((vault.get(accounts.GENERAL), self.page.input_value("#acctGenPw")), ("General-Pass-9!", ""))
        self.assertIn("set, pat.rivera", self.page.text_content("#acctGenState"))
        self.assertNotIn("General-Pass-9!", json.dumps(self.api("/api/accounts")) + self.page.content())
        self.answer(False)  # the switch asks first: no, it stays off
        self.page.click("#acctAutoCreate")
        self.idle()
        self.assertFalse(settings.pref("accounts_auto_create") or self.page.is_checked("#acctAutoCreate"))
        self.answer(True)
        self.page.check("#acctAutoCreate")
        self.idle()
        self.assertTrue(settings.pref("accounts_auto_create"))
        self.assertIn("finishes sign-ups", self.page.text_content("#acctGenState"))
        self.answer(True)
        self.run_click("#acctGen >> text=Clear")
        self.assertIsNone(vault.get(accounts.GENERAL))
        self.assertEqual(self.page.text_content("#acctGenState"), "(not set)")

    def test_save_a_login_create_and_a_waiting_step_with_fill_code(self):
        self.allow_console()
        self.page.click("#acctNew summary")
        self.page.fill("#acctUrl", "https://www.linkedin.com/login")
        self.page.fill("#acctUser", "pat")
        self.run_click("#acctNew >> text=Save login")
        self.expect_toast("does not allow bots", "err")
        self.page.fill("#acctUrl", "https://hire.lever.example/acme/login")
        self.page.fill("#acctUser", "pat.rivera@example.com")
        self.run_click("#acctNew >> text=Save login")
        self.assertEqual(len(vault.get("site:hire.lever.example") or ""), 16)  # empty: a generated one
        self.page.fill("#acctUrl", "https://jobs.smartrecruiters.example/acme")
        self.answer(True)
        self.run_click("#acctNew >> text=Create an account there")
        self.assertEqual(self.calls[-1], ("create", None, "https://jobs.smartrecruiters.example/acme"))
        # a run waiting on an emailed code, worked by this process
        jid = self.ids["saved"]
        rid = db.add_run(jid, "stop")
        db.update_run(rid, state="needs_you", needs=[{"reason": "account_code", "site": "acme.wd5.myworkdayjobs.example",
                                                      "hint": "<img src=x onerror=alert(2)>type the code"}])
        apply_agent._OWNED.add(rid)
        self.addCleanup(apply_agent._OWNED.discard, rid)
        self.addCleanup(lambda: db.update_run(rid, state="stopped"))
        codes._CODES["k1"] = {"id": "k1", "code": "482913", "sender": "x@myworkday.example", "domain": "myworkday.example",
                              "subject": "code", "received": datetime.now(timezone.utc)}
        self.addCleanup(codes._CODES.clear)
        self.page.evaluate("acctLoad()")
        self.idle()
        w = self.page.locator("#acctWait .acctwait")
        self.assertIn("<img src=x onerror=alert(2)>type the code", w.text_content())
        self.assertEqual(self.page.locator("#acctWait img").count(), 0)
        self.run_click(w.get_by_role("button", name="Fill code from myworkday.example"))
        self.assertEqual(accounts._REQ.pop(f"run:{rid}"), {"action": "code", "id": "k1"})
        self.run_click(w.get_by_role("button", name="Continue"))
        self.assertTrue(db.get_run(rid)["answers"].get("_continue"))


if __name__ == "__main__":
    unittest.main()
