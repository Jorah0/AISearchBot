"""The apply agent in a real browser (Playwright on the installed Edge, headless), against fictional local fixture forms
only (tests/fixtures/apply, served from 127.0.0.1). Fictional hosts (apply.example-ats.test ...) reach the local server
through a test-only host-resolver rule (MAP * 127.0.0.1): nothing leaves this machine, and the forbidden boards fail to
resolve before that rule. Each test uses its own temporary browser profile, never the agent's real one. The 'user' acts
from the worker's idle hook (the only thread that may touch the page): pressing Submit, solving the fake challenge,
typing a code, approving in the Inbox."""
import contextlib
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from harness import NO_PLAYWRIGHT, E2ETestCase, PROFILE_MD
from lodestar import apply_agent, apply_ats, approvals, db, profile, resume, settings, util

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "apply"
KIND = os.environ.get("LODESTAR_E2E_BROWSER", "msedge").strip().lower()
LAUNCH = {} if KIND == "chromium" else {"channel": KIND}


class ApplyAgent(E2ETestCase):
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
        handler = functools.partial(Quiet, directory=str(FIXTURES))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(lambda: (cls.srv.shutdown(), cls.srv.server_close()))
        cls.port = cls.srv.server_address[1]
        try:  # the browser is there and Playwright drives it: else the class skips (as the harness does)
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

    def tearDown(self):
        while self.held:
            self.held.pop()()
        db.release(close=False)

    def job(self, query: str = "", host: str = "apply.example-ats.test", page: str = "form.html") -> int:
        jid = db.add_job("Example Robotics", "Data Engineer", f"https://jobs.example.com/robotics/{self.id()}/{page}?{query}",
                         "Python SQL")
        db.set_fields(jid, apply_url=f"http://{host}:{self.port}/{page}{'?' + query if query else ''}")
        (resume.app_dir(db.get_job(jid)) / "resume.pdf").write_bytes(b"%PDF-1.4 fictional resume")
        return jid

    def work(self, jid: int, mode: str, hook) -> dict:
        """Queue the job and run the worker here until nothing is live; hook(tab, run) acts as you."""
        r = apply_agent.enqueue([jid], mode, start=False)[0]
        self.assertIn("run_id", r, r)
        while self.held:  # one Playwright per thread at a time: the previous run's browser closes first
            self.held.pop()()
        profile_dir = Path(tempfile.mkdtemp(dir=self.home)) / "browser-profile"
        self.addCleanup(shutil.rmtree, profile_dir.parent, True)
        b = apply_ats.open_browser(profile_dir, apply_agent.forbidden, os.environ.get("LODESTAR_E2E_HEADED") != "1",
                                   LAUNCH, resolver=["MAP * 127.0.0.1"])
        opened, idle = b.open, b.idle

        def act(tab):
            if tab is not None and not tab.closed:
                hook(tab, db.get_run(r["run_id"]))

        def open_(url, hosts):
            t = opened(url, hosts)
            t_idle = t.idle
            t.idle = lambda ms: (t_idle(min(ms, 300)), act(t))[0]
            self.tabs.append(t)
            return t
        b.open = open_
        self.held.append(b.close)  # after the asserts: the worker's own close is held so the test can read the page
        b.close = lambda: None
        b.idle = lambda ms: (idle(min(ms, 300)), act(self.tabs[-1] if self.tabs else None))[0]
        with contextlib.ExitStack() as st:
            st.enter_context(_patched(apply_agent, RUN_S=120, NEEDS_S=60, WATCH_S=60, REVIEW_S=60))
            apply_agent._loop(lambda: b, until_idle=True)
        return db.get_run(r["run_id"])

    @staticmethod
    def dom(tab, js: str):
        return tab.page.evaluate(js)

    # --- stop mode: filled, never submitted by the agent
    def test_stop_mode_fills_both_steps_and_never_presses_submit(self):
        seen = {}

        def you(tab, run):
            if run["state"] == "ready" and not seen:
                seen.update(self.dom(tab, """() => ({first: first_name.value, last: last_name.value, email: email.value,
                    files: [...resume.files].map(f => f.name), consent: consent.checked, gender: gender.value,
                    submitted: Boolean(window.__submitted)})"""))
                tab.page.check("#consent")  # you tick the box and press Submit yourself
                tab.page.click("#submit")
        run = self.work(self.job(), "stop", you)
        self.assertEqual(seen, {"first": "Pat", "last": "Rivera", "email": "pat.rivera@example.com",
                                "files": ["Pat_Rivera_Resume.pdf"], "consent": False, "gender": "", "submitted": False})
        self.assertEqual((run["state"], run["submitted_by"], run["submit_clicks"]), ("by_user", "user", 0))
        self.assertRegex(run["confirmation"], r"^FIX-\d+$")
        ev = Path(run["evidence"])
        self.assertTrue({"page-01.png", "page-02.png", "confirmation.png", "plan.json", "summary.md"} <= {p.name for p in ev.iterdir()})
        self.assertTrue((ev / "files" / "Pat_Rivera_Resume.pdf").is_file())
        self.assertEqual(db.get_job(run["job_id"])["status"], "saved")

    # --- review mode: one approval, one Submit click, the confirmation recorded
    def test_review_mode_submits_once_after_your_approval_with_its_confirmation(self):
        settings.set_tool("apply_agent", enabled=True, auto=False)
        state = {}

        def you(tab, run):
            if run["state"] == "awaiting_approval" and not state:
                item = db.get_pending(run["pending_id"])
                state["payload"] = json.loads(item["payload"])
                state["before"] = self.dom(tab, "() => Boolean(window.__submitted)")
                approvals.approve(run["pending_id"])
        run = self.work(self.job(), "review", you)
        self.assertFalse(state["before"])  # nothing went out before the approval
        self.assertEqual(state["payload"]["shots"], ["page-01.png", "page-02.png"])
        self.assertIn("(tick)", [f["value"] for f in state["payload"]["fields"] if f["label"].startswith("I agree")])
        self.assertEqual((run["state"], run["submitted_by"], run["submit_clicks"]), ("confirmed", "approved", 1))
        tab = self.tabs[0]
        self.assertTrue(self.dom(tab, "() => window.__submitted === true"))
        self.assertEqual(self.dom(tab, "() => window.__files"), ["Pat_Rivera_Resume.pdf"])
        job = db.get_job(run["job_id"])
        self.assertEqual(job["status"], "applied")
        self.assertTrue(any(run["confirmation"] in (e["detail"] or "") for e in db.events(job["id"])))

    # --- the guard: forbidden boards never load; another host only with your Continue
    def test_forbidden_board_is_refused_and_another_host_needs_your_continue(self):
        run = self.work(self.job("offsite=1"), "stop", lambda tab, run: None)
        self.assertEqual(run["state"], "stopped")
        self.assertIn("www.linkedin.com", run["error"])
        self.assertNotIn("linkedin", self.tabs[0].url)
        asked = []

        def you(tab, run):
            if run["state"] == "needs_you" and not asked:
                asked.append(run["needs"][0]["hint"])
                apply_agent.continue_run(run["id"])
            elif run["state"] == "ready":
                apply_agent.stop()  # enough: the second host's step was filled
        self.tabs = []
        run = self.work(self.job("elsewhere=1"), "stop", you)
        self.assertIn("careers.example-robotics.test", asked[0])
        self.assertEqual(run["hosts"], ["apply.example-ats.test", "careers.example-robotics.test"])
        self.assertEqual([p["page"] for p in run["plan"]], [1, 2])

    # --- handoffs: a challenge, a sign-in page and a code after Submit go to you
    def test_challenge_sign_in_and_code_are_handed_to_you(self):
        settings.set_tool("apply_agent", enabled=True, auto=False)
        did = []

        def you(tab, run):
            if run["state"] == "needs_you" and not run["submit_clicks"] and "captcha" not in did:
                self.assertEqual(run["needs"][0]["reason"], "captcha")
                did.append("captcha")
                tab.page.evaluate("() => document.getElementById('captcha').remove()")  # you solved it
                apply_agent.continue_run(run["id"])
            elif run["state"] == "needs_you" and not run["submit_clicks"] and "login" not in did:
                self.assertEqual(run["needs"][0]["reason"], "login")
                did.append("login")
                self.assertEqual(self.dom(tab, "() => pw.value"), "")  # the agent never types a password
                tab.page.click("#signin")
                apply_agent.continue_run(run["id"])
            elif run["state"] == "awaiting_approval" and db.get_pending(run["pending_id"])["status"] == "pending":
                approvals.approve(run["pending_id"])
            elif run["state"] == "needs_you" and run["submit_clicks"] and "code" not in did:
                did.append("code")
                tab.page.fill("#otp", "482913")  # the code from your mail, typed by you
                tab.page.click("#verify")
        run = self.work(self.job("captcha=1&login=1&code=1"), "review", you)
        self.assertEqual(did, ["captcha", "login", "code"])
        self.assertEqual((run["state"], run["submit_clicks"]), ("confirmed", 1))
        self.assertTrue(any(k == "notify" and "solve the check" in m for k, m in self.opened))

    # --- strict CSP: the scan still runs (CDP evaluation); service workers never run; 'already applied' is refused
    def test_strict_csp_page_is_filled_and_an_already_applied_page_is_refused(self):
        def you(tab, run):
            if run["state"] == "ready":
                apply_agent.stop()
        run = self.work(self.job("sw=1", host="127.0.0.1", page="csp.html"), "stop", you)  # a secure context: workers exist
        tab = self.tabs[0]
        self.assertEqual(self.dom(tab, "() => first_name.value"), "Pat")
        self.assertEqual(self.dom(tab, "() => document.body.dataset.sw"), "registered")  # register() resolves ...
        self.assertFalse(self.dom(tab, "() => Boolean(navigator.serviceWorker.controller)"))  # ... but no worker runs
        self.assertEqual([p["page"] for p in run["plan"]], [1, 2])
        self.tabs = []
        run = self.work(self.job("applied=1"), "stop", lambda tab, run: None)
        self.assertEqual((run["state"], run["error"]), ("failed", "the site says you already applied"))


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


if __name__ == "__main__":
    unittest.main()
