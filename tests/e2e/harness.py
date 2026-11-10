"""Browser test harness: the real Lodestar server in-process, driven by Playwright (installed Edge by default).

Per test class: a fresh temp LODESTAR_HOME, fictional data seeded through the app's own write paths, every outside
service faked (AI, IMAP/SMTP, OAuth, job-site fetches, keyring, desktop toasts, the default browser), the server on a
free 127.0.0.1 port and one browser. Per test: a fresh browser context and page, a console-error guard, and a
screenshot + the page HTML in tests/e2e/_artifacts/ when the test fails.

Env: LODESTAR_E2E_BROWSER=chromium (CI; default msedge), LODESTAR_E2E_HEADED=1 (watch it), LODESTAR_E2E_SLOWMO=ms.
Run:  .venv\\Scripts\\python.exe -m unittest discover -s tests/e2e -p "e2e_*.py"
"""
import atexit
import imaplib
import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).resolve().parent / "_artifacts"

# --- before any lodestar import: a throwaway home, and nothing real from a .env (config.py loads them with setdefault,
# so a key set here, even to "", wins). The suite runs in its own process (its own discover command).
_BASE = tempfile.mkdtemp(prefix="lodestar-e2e-")
atexit.register(shutil.rmtree, _BASE, True)
os.environ["LODESTAR_HOME"] = _BASE
os.environ["LODESTAR_NO_STARTUP_CHECK"] = "1"  # no background key/mailbox checks
for _env in {Path.cwd() / ".env", ROOT / ".env"}:
    if _env.is_file():
        for _ln in _env.read_text(encoding="utf-8").splitlines():
            _k = _ln.split("=", 1)[0].lstrip("# ").strip()
            if "=" in _ln and re.fullmatch(r"[A-Z][A-Z0-9_]*", _k) and _k != "LODESTAR_HOME":
                os.environ[_k] = ""
for _k in ("LODESTAR_NOTIFY_EMAIL", "LODESTAR_PROVIDER", "OBSIDIAN_VAULT"):
    os.environ[_k] = ""

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright
    NO_PLAYWRIGHT = ""
except ImportError as _e:  # the suite skips cleanly without it
    NO_PLAYWRIGHT = f"playwright is not installed ({_e}); pip install -e .[e2e]"

import lodestar  # noqa: E402
from lodestar import config  # noqa: E402

for _m in pkgutil.iter_modules(lodestar.__path__):  # every module now, so the per-class home rebinding sees them all
    if _m.name not in ("__main__", "desktop"):
        importlib.import_module(f"lodestar.{_m.name}")
from lodestar import (ai, approvals, codes, comp, connections, contacts, db, extras, interview, mailconn,  # noqa: E402
                      mailfiles, oauth, profile, resume, util, vault, web, web_monitor)

TABS = ("board", "inbox", "contacts", "search", "monitor", "ideas", "answers", "coach", "insights", "profile", "tools",
        "setup")
FLOOR = "$165,000"
PROFILE_MD = f"""# Pat Rivera
Pat Rivera | Portland, OR | pat.rivera@example.com | linkedin.com/in/pat-rivera-example

## Summary
Data engineer with 7 years building batch and streaming pipelines for health and logistics teams.

## Skills
Python, SQL, Spark, Airflow, dbt, Kafka, AWS, Terraform, PostgreSQL

## Experience
### Senior Data Engineer, Tidewater Logistics (2021-present)
- Rebuilt the nightly freight ETL on Spark and Airflow, cutting runtime from 6 hours to 50 minutes
- Cut warehouse spend 40% by moving cold tables to Iceberg on S3
- Led a team of 3 engineers through a Kafka migration with zero data loss

### Data Engineer, Mapleleaf Clinics (2018-2021)
- Built HIPAA-compliant ingestion for 40 clinics in Python and PostgreSQL
- Introduced dbt tests that caught 120 data-quality issues before reporting

## Education
B.S. Computer Science, Oregon State University

## Preferences
Salary floor: {FLOOR} | Deal-breakers: on-call every week
"""


def day(n=0) -> str:
    """Today plus n days, as the YYYY-MM-DD the app stores."""
    return (date.today() + timedelta(days=n)).isoformat()


# ----------------------------------------------------------------------------- fakes
def _resp(obj):
    """What urlopen returns, for the bits Lodestar reads."""
    import io

    class R(io.BytesIO):
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    return R(json.dumps(obj).encode())


class FakeMail:
    """imaplib.IMAP4(_SSL) and smtplib.SMTP(_SSL): logins succeed, an empty mailbox, sent mail is kept in SENT and every
    other call's name in CALLS (so a test can tell the mailbox was really opened). FAIL = an exception makes every login
    raise it (a refused or dropped mailbox). The real exception classes stay on it: the app checks imaplib.IMAP4.error
    and .abort, and imaplib.IMAP4 is this class while the fake is in."""
    SENT: list = []
    CALLS: list = []
    FAIL: BaseException | None = None
    error, abort, readonly = imaplib.IMAP4.error, imaplib.IMAP4.abort, imaplib.IMAP4.readonly

    def __init__(self, *a, **kw):
        self.capabilities = ("IMAP4REV1", "AUTH=PLAIN")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a, **kw):
        FakeMail.CALLS.append("login")
        if FakeMail.FAIL is not None:
            raise FakeMail.FAIL
        return "OK", [b"logged in"]

    def send_message(self, msg, *a, **kw):
        FakeMail.SENT.append(msg)
        return {}

    def __getattr__(self, name):  # login, select, uid, search, logout, ehlo, starttls, quit ...: all OK, nothing in it
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: FakeMail.CALLS.append(name) or ("OK", [b""])


FETCH = {  # util.fetch canned by URL substring; first match wins, else a plain posting page
    "boards-api.greenhouse.io": {"jobs": [{"id": 4101, "title": "Senior Data Engineer", "company_name": "Northwind Analytics",
                                           "absolute_url": "https://boards.greenhouse.io/northwind/jobs/4101",
                                           "location": {"name": "Remote (US)"}, "first_published": "2026-11-01",
                                           "content": "&lt;p&gt;Python, Spark, Airflow. $150,000 - $180,000&lt;/p&gt;"}]},
    "api.lever.co": [],
    "api.ashbyhq.com": {"jobs": []},
    "remotive.com": {"jobs": [{"title": "Data Engineer", "company_name": "Saltmarsh Data", "url": "https://jobs.example.com/saltmarsh/de",
                               "candidate_required_location": "USA", "salary": "$140k - $170k",
                               "publication_date": "2026-11-05", "description": "Python, SQL, Airflow, dbt"}]},
    "arbeitnow.com": {"data": []},
    "remoteok.com": [{"legal": "notice"}],
    "hn.algolia.com": {"hits": []},
    "jobicy.com": {"jobs": []},
    "themuse.com": {"results": [], "page_count": 0},
}
FETCH_HOOK = """(() => {  // counts API requests in flight and background tasks still running, for E2ETestCase.idle()
  const ls = window.__ls = { inflight: 0, tasks: new Set() }, real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String((input && input.url) || input), m = /\\/api\\/(run|tasks)\\/([^/?]+)/.exec(url);
    ls.inflight++;
    let r;
    try { r = await real(input, init); } catch (e) { ls.inflight--; throw e; }
    if (m) {
      const j = await r.clone().json().catch(() => ({}));
      if (m[1] === 'run' && j.task != null) ls.tasks.add(String(j.task));
      if (m[1] === 'tasks' && j.status !== 'running') ls.tasks.delete(m[2]);
    }
    const json = r.json.bind(r); let done = false;  // in flight until the app has read the body (api() always does)
    r.json = () => json().finally(() => { if (!done) { done = true; ls.inflight--; } });
    return r;
  };
})();"""
POSTING = ("<html><head><title>Data Engineer - Example Co</title></head><body><h1>Data Engineer</h1><p>We use Python, "
           "SQL and Airflow. Salary $140,000 - $170,000. Remote within the US.</p></body></html>")


# ----------------------------------------------------------------------------- the test case
class E2ETestCase(unittest.TestCase):
    """Subclass it. self.page is a loaded Lodestar page; cls.ids holds the seeded ids; helpers below."""
    browser = None
    ai_text = "Fake AI reply: keep it short and specific."  # what ai.ask / ai.chat return
    ai_json: object = {"subject": "Thanks", "body": "Thank you for your time.", "options": [], "score": 80,
                       "verdict": "good fit", "why": "skills match", "category": "other", "summary": "fake"}  # ask_json

    # --- class lifetime: home, fakes, seed, server, browser
    @classmethod
    def setUpClass(cls):
        if NO_PLAYWRIGHT:
            raise unittest.SkipTest(NO_PLAYWRIGHT)
        cls.ai_calls, cls.urls, cls.opened = [], [], []
        cls._home()
        cls._fakes()
        cls.ids = {}
        cls.seed()
        db.release()  # the seeding thread's connection; server threads open their own
        cls.server = web.start_server(0)
        cls.addClassCleanup(lambda: (cls.server.shutdown(), cls.server.server_close()))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls._browser()

    @classmethod
    def _patch(cls, obj, attr, value):
        old = getattr(obj, attr)
        setattr(obj, attr, value)
        cls.addClassCleanup(setattr, obj, attr, old)

    @classmethod
    def _home(cls):
        """A fresh LODESTAR_HOME for this class: every module-level path under the current home moves to the new one."""
        old, new = Path(config.HOME), Path(tempfile.mkdtemp(prefix="lodestar-e2e-", dir=_BASE))
        db.release()
        for name, mod in list(sys.modules.items()):
            if name == "lodestar" or name.startswith("lodestar."):
                for attr, v in list(vars(mod).items()):
                    if isinstance(v, Path) and v.is_relative_to(old):
                        cls._patch(mod, attr, new / v.relative_to(old))
        cls.addClassCleanup(db.release)  # registered last: runs first, before the paths move back
        cls.home = new
        codes._CODES.clear()

    @classmethod
    def _swap(cls, original, fake):
        """Replace a function everywhere a lodestar module holds it (util.fetch is also web_monitor.fetch, ...)."""
        for name, mod in list(sys.modules.items()):
            if name == "lodestar" or name.startswith("lodestar."):
                for attr, v in list(vars(mod).items()):
                    if v is original:
                        cls._patch(mod, attr, fake)

    @classmethod
    def _fakes(cls):
        import smtplib
        import urllib.request
        import webbrowser

        import keyring

        store = {}
        cls.keyring = store
        cls._patch(keyring, "get_password", lambda svc, name: store.get((svc, name)))
        cls._patch(keyring, "set_password", lambda svc, name, v: store.__setitem__((svc, name), v))
        cls._patch(keyring, "delete_password", lambda svc, name: store.pop((svc, name), None))

        def chat(messages, system=None, provider=None, max_tokens=4000):
            cls.ai_calls.append({"system": system, "messages": messages, "provider": provider})
            want_json = "valid JSON only" in (system or "")
            return json.dumps(cls.ai_json) if want_json else cls.ai_text

        cls._swap(ai.chat, chat)  # ai.ask, ask_json and council all go through chat

        def fetch(url, timeout=25, headers=None, max_bytes=None):
            cls.urls.append(url)
            hit = next((v for k, v in FETCH.items() if k in url), None)
            return POSTING if hit is None else json.dumps(hit)

        cls._swap(util.fetch, fetch)

        def urlopen(req, *a, **kw):  # AI key checks, ai._post and OAuth token calls: canned, never the network
            url = getattr(req, "full_url", req)
            cls.urls.append(url)
            if "token" in url:
                return _resp({"access_token": "e2e-access", "refresh_token": "e2e-refresh", "expires_in": 3600,
                              "token_type": "Bearer", "scope": "openid email https://mail.google.com/"})
            return _resp({"data": [], "content": [{"type": "text", "text": cls.ai_text}]})

        for mod in (urllib.request, connections, oauth):
            cls._patch(mod, "urlopen", urlopen)
        for name in ("IMAP4", "IMAP4_SSL"):
            cls._patch(imaplib, name, FakeMail)
        for name in ("SMTP", "SMTP_SSL"):
            cls._patch(smtplib, name, FakeMail)
        FakeMail.SENT, FakeMail.CALLS, FakeMail.FAIL = [], [], None
        cls._swap(util.desktop_notify, lambda title, body: cls.opened.append(("toast", title)) or True)
        cls._patch(webbrowser, "open", lambda url, *a, **kw: cls.opened.append(("browser", url)) or True)
        # nothing outside the temp home: the Obsidian export's default is the real vault in Documents, PDF export would
        # drive Word or LibreOffice, and Open folder would pop Explorer
        cls._swap(extras.vault_root, lambda: cls.home / "obsidian-vault")
        cls._patch(resume, "_word", lambda: False)
        cls._patch(resume, "_soffice", lambda: None)
        if hasattr(os, "startfile"):
            cls._patch(os, "startfile", lambda path, *a, **kw: cls.opened.append(("folder", str(path))))
        else:  # web.py opens folders with open / xdg-open off Windows; every other process still runs
            real_popen = subprocess.Popen

            def popen(args, *a, **kw):
                if isinstance(args, list) and args and args[0] in ("open", "xdg-open"):
                    return cls.opened.append(("folder", str(args[-1])))
                return real_popen(args, *a, **kw)

            cls._patch(subprocess, "Popen", popen)

    @classmethod
    def _browser(cls):
        kind = os.environ.get("LODESTAR_E2E_BROWSER", "msedge").strip().lower()
        headed = os.environ.get("LODESTAR_E2E_HEADED") == "1"
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        try:
            cls.browser = cls.pw.chromium.launch(channel=None if kind == "chromium" else kind, headless=not headed,
                                                 slow_mo=int(os.environ.get("LODESTAR_E2E_SLOWMO") or (250 if headed else 0)))
        except PWError as e:
            msg = f"no {kind} browser for Playwright: {str(e).splitlines()[0][:200]}"
            if os.environ.get("CI"):  # ponytail: CI installed one on purpose, so a missing browser is a failure there
                raise RuntimeError(msg) from None
            raise unittest.SkipTest(msg + " (LODESTAR_E2E_BROWSER=chromium + python -m playwright install chromium)")
        cls.addClassCleanup(cls.browser.close)

    # --- seed: fictional data through the app's own write paths
    @classmethod
    def seed(cls):
        today = date.today()
        d = lambda n: (today + timedelta(days=n)).isoformat()  # noqa: E731
        profile.write_master(PROFILE_MD)
        comp.set_range("data engineer", "*", 140_000, 190_000)
        jobs = [  # (key, status, company, title, fields)
            ("saved", "saved", "Northwind Analytics", "Senior Data Engineer",
             {"location": "Portland, OR", "remote": "hybrid", "salary_min": "150k", "salary_max": "180k", "excitement": 4,
              "tags": "python,spark", "deadline": d(10), "next_action": "Tailor resume", "next_action_at": d(2)}),
            ("applied", "applied", "Bluefin Labs", "Analytics Engineer",
             {"location": "Remote (US)", "remote": "remote", "salary_min": "135k", "salary_max": "160k", "excitement": 3}),
            ("screening", "screening", "Cobalt Freight", "Data Platform Engineer",
             {"location": "Seattle, WA", "remote": "onsite", "match_score": 72, "next_action": "Prep recruiter call",
              "next_action_at": d(1)}),
            ("interview", "interview", "Orchid Health", "Staff Data Engineer",
             {"location": "Remote (US)", "remote": "remote", "salary_min": "170k", "salary_max": "205k", "excitement": 5,
              "tags": "health,airflow"}),
            ("offer", "offer", "Juniper Robotics", "ML Data Engineer", {"location": "Boston, MA", "remote": "hybrid"}),
            ("accepted", "accepted", "Harbor & Pine", "Data Engineer", {"location": "Portland, OR"}),
            ("rejected", "rejected", "Quarry Games", "Data Engineer II", {"location": "Austin, TX"}),
            ("withdrawn", "withdrawn", "Tandem Freightworks", "Senior Data Engineer", {"location": "Denver, CO"}),
        ]
        for key, status, company, title, fields in jobs:
            slug = re.sub(r"[^a-z]+", "", company.lower())
            jid = db.add_job(company, title, f"https://jobs.example.com/{slug}/{key}",
                             f"{title} at {company}. Python, SQL, Spark, Airflow and dbt. Build reliable pipelines.",
                             "via e2e seed", **fields)
            db.update_job(jid, contact_email=f"recruiting@{slug}.example", contact_name="Recruiting team")
            if status != "saved":
                db.set_status(jid, status)
            cls.ids[key] = jid
        j = cls.ids
        interview.log_round(j["interview"], kind="phone", at=d(-6) + " 10:00", interviewers="Maya Chen", outcome="passed",
                            notes="Recruiter screen went well", questions_asked="Why Orchid?\nTell me about a pipeline you rebuilt")
        interview.log_round(j["interview"], kind="technical", at=d(3) + " 14:00", interviewers="Ravi Iyer, Lena Brooks")
        db.set_offer(j["offer"], base="182k", bonus_pct="10", sign_on="15k", equity_value_estimate="60k", vest_years=4,
                     cliff_months=12, remote="hybrid", start_date=d(30), deadline=d(5), notes="Negotiable sign-on")
        maya = contacts.add(name="Maya Chen", email="maya.chen@orchidhealth.example", company="Orchid Health",
                            position="Technical Recruiter", how_met="inbound", last_touch=d(-6), next_touch=d(1))
        dev = contacts.add(name="Dev Patel", email="dev.patel@juniperrobotics.example", company="Juniper Robotics",
                           position="Engineering Manager", how_met="meetup")
        sam = contacts.add(name="Sam Okafor", linkedin_url="https://www.linkedin.com/in/sam-okafor-example",
                           company="Bluefin Labs", position="Senior Analyst", how_met="former colleague", next_touch=d(0))
        contacts.link(maya, j["interview"], "recruiter")
        contacts.link(dev, j["offer"], "hiring_manager")
        contacts.link(sam, j["applied"], "referrer")
        j |= {"c_maya": maya, "c_dev": dev, "c_sam": sam}
        db.save_answer("Are you legally authorized to work in the United States?", "Yes, without sponsorship.", "work-auth")
        db.save_answer("Why do you want to work here?", "Your data platform serves patients directly; I want that impact.",
                       "motivation")
        db.save_answer("What is my walk-away number?", f"Private: my floor is {FLOOR} base.", "comp", private=True)
        j["story"] = interview.save_story("Cut warehouse spend 40%", situation="Warehouse bills doubled in a year",
                                          task="Bring cost down without slowing reports",
                                          action="Moved cold tables to Iceberg on S3 and added usage dashboards",
                                          result="40% lower spend, same report latency", metrics="40%",
                                          competencies=("ownership", "data-driven"))
        db.add_watch("search:data engineer", "python spark",
                     web_monitor.clean_filters(location="Remote", min_salary="140k", posted_within=14, seniority="senior"))
        j["company_board"] = web_monitor.add_company("greenhouse:northwind", "Northwind Analytics", "data")["id"]
        j["idea"] = db.add_idea("outreach", "Ask Sam for a Bluefin referral", "Sam works on the analytics team.", 0.8,
                                j["applied"], "referral")
        # mail: trusted with an attachment saved the way the scanner saves it, one sent, one unmatched
        orchid = db.get_job(j["interview"])
        mid = "<orchid-1@orchidhealth.example>"
        att = mailfiles.save([{"name": "interview-agenda.pdf", "data": b"%PDF-1.4 e2e agenda", "type": "application/pdf"}],
                             orchid, mid, datetime.now())
        db.add_mail(message_id=mid, job_id=j["interview"], direction="in", from_addr="Maya Chen <maya.chen@orchidhealth.example>",
                    to_addr="pat.rivera@example.com", subject="Technical interview availability", sent_at=d(-1) + " 09:12:00",
                    category="interview", summary="Asks for two slots this week", snippet="Could you share two times?",
                    trusted=True, linked_by="auto", company="Orchid Health", attachments=att)
        db.add_mail(message_id="<out-1@example.com>", job_id=j["applied"], direction="out", from_addr="pat.rivera@example.com",
                    to_addr="recruiting@bluefinlabs.example", subject="Application: Analytics Engineer", sent_at=d(-8) + " 16:40:00",
                    trusted=True, linked_by="auto")
        db.add_mail(message_id="<zephyr-1@zephyr.example>", direction="in", from_addr="talent@zephyr.example",
                    subject="Exciting data role at Zephyr AI", sent_at=d(-2) + " 11:00:00", category="recruiter_outreach",
                    summary="Recruiter outreach", snippet="Your profile caught our eye", company="Zephyr AI",
                    title="Data Engineer")
        # Inbox: a reply to the trusted mail and a follow-up (both wait for review)
        r = approvals.propose("email_reply", "send_email",
                              {"to": "maya.chen@orchidhealth.example", "subject": "Re: Technical interview availability",
                               "body": "Hi Maya, Thursday 14:00 or Friday 10:00 both work. Best, Pat",
                               "job_id": j["interview"], "in_reply_to": mid}, "reply to Maya at Orchid Health",
                              j["interview"], force_pending=True)
        f = approvals.propose("followup", "send_email",
                              {"to": "recruiting@bluefinlabs.example", "subject": "Following up: Analytics Engineer",
                               "body": "Hi, I wanted to follow up on my application. Happy to share more. Best, Pat",
                               "job_id": j["applied"], "purpose": "followup"}, "follow-up at Bluefin Labs", j["applied"],
                              force_pending=True)
        assert r["status"] == f["status"] == "pending", (r, f)
        j |= {"p_reply": r["id"], "p_followup": f["id"]}
        # connections: one verified key, one failed, a verified mailbox (records only: no check ever runs)
        for name, key, res in (("anthropic", "sk-ant-e2e-fake-key-0001", {"status": "verified", "detail": "12 models"}),
                               ("openai", "sk-e2e-fake-key-0002", {"status": "failed", "detail": "the provider rejected this key"})):
            vault.set(connections.REGISTRY[name]["key"], key)
            connections.record("keys", name, res | {"model": ai.model_for(name)}, connections.fp(key))
        mailconn.connect("fastmail", "pat.rivera@example.com", "e2e-app-password")
        mfp = mailconn._fingerprint(util.mail_settings())
        vault.set("EMAIL_VERIFIED", mfp)
        connections.record("mail", None, {"status": "verified", "detail": "IMAP ok, SMTP ok"}, mfp)

    # --- per test: a fresh context and page, console guard, artifacts on failure
    def setUp(self):
        self.errors, self.dialogs, self._answers, self._allowed = [], [], [], []
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        self.context.add_init_script(FETCH_HOOK)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10_000)
        self.page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text} @ {m.location}"))
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("dialog", self._dialog)
        self.page.goto(self.base + "/")
        self.page.wait_for_function("() => S !== null")  # app.js has loaded /api/state
        self.idle()

    def _dialog(self, d):
        """confirm / prompt / alert: answered from self.answer(...) in order, else dismissed (confirm() is false)."""
        self.dialogs.append(d.message)
        if d.type == "beforeunload":
            return d.accept()
        a = self._answers.pop(0) if self._answers else False
        if a is False:
            return d.dismiss()
        return d.accept(a) if isinstance(a, str) else d.accept()

    def allow_console(self, pattern=r"status of 4\d\d"):
        """This test expects console errors matching pattern (by default the 4xx the API answers bad input with, which
        the browser logs as 'Failed to load resource'); anything else still fails the test."""
        self._allowed.append(pattern)

    def answer(self, *answers):
        """Queue answers for the next dialogs: True accepts a confirm, False dismisses, a string fills a prompt."""
        self._answers.extend(answers)

    def idle(self, timeout=20_000):
        """Wait until no API request is in flight and no background task (run()) is still being polled."""
        self.page.wait_for_function("() => window.__ls && __ls.inflight === 0 && __ls.tasks.size === 0", timeout=timeout)

    def run_click(self, target, timeout=20_000):
        """Click a button (selector or locator) that starts background work, then wait for all of it to finish."""
        (self.page.locator(target) if isinstance(target, str) else target).click()
        self.idle(timeout)

    def reload_state(self):
        """Re-read /api/state into the page (after a change made outside the UI) and wait for it."""
        self.page.evaluate("load()")
        self.idle()

    def state(self):
        return self.api("/api/state")

    def tearDown(self):
        # ponytail: unittest records a failure on the result before tearDown runs (3.11+); _outcome is its private handle
        res = getattr(getattr(self, "_outcome", None), "result", None)
        errors = [e for e in self.errors if not any(re.search(a, e) for a in self._allowed)]
        failed = errors or any(t is self for t, _ in getattr(res, "failures", []) + getattr(res, "errors", []))
        try:
            if failed:
                ARTIFACTS.mkdir(exist_ok=True)
                stem = ARTIFACTS / re.sub(r"[^\w.-]+", "_", self.id())
                self.page.screenshot(path=f"{stem}.png", full_page=True)
                Path(f"{stem}.html").write_text(self.page.content(), encoding="utf-8")
        finally:
            try:  # let requests still in flight finish: a cut-off one prints a server traceback into the test output
                self.idle(5_000)
            except Exception:  # ponytail: a test that left work running still closes
                pass
            self.context.close()
        if errors:
            self.fail("browser errors:\n" + "\n".join(errors))

    # --- helpers
    def api(self, path, body=None):
        """Call the API from the page, with the page's own token."""
        return self.page.evaluate("([p, b]) => api(p, b || undefined)", [path, body])

    def go(self, tab):
        self.page.click(f'nav button[data-tab="{tab}"]')
        self.page.wait_for_selector(f"section#{tab}.on")
        self.settle()

    def settle(self):
        """networkidle alone returns at once after the first load, so also wait for the API loads a tab or a resize
        started (the fetch hook's count)."""
        self.page.wait_for_load_state("networkidle")
        self.idle()

    def open_job(self, jid):
        self.go("board")
        self.page.evaluate("closeDrawer()")  # an open drawer covers the right-hand columns
        self.page.click(f'.card[data-id="{int(jid)}"]')
        self.page.wait_for_selector("#drawer.open")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=int(jid))
        return self.page.locator("#drawer")

    def click_and_wait(self, selector, url_part="/api/"):
        """Click and wait for the first response whose URL contains url_part; returns the response."""
        with self.page.expect_response(lambda r: url_part in r.url) as info:
            self.page.click(selector)
        return info.value

    def expect_toast(self, text="", kind=None):
        """kind: 'ok' | 'err' | '' (plain). Returns the toast text."""
        t = self.page.locator("#toast")
        t.wait_for(state="visible")
        if text:
            self.page.wait_for_function("s => document.querySelector('#toast').textContent.includes(s)", arg=text)
        if kind is not None:
            self.assertEqual(t.get_attribute("class") or "", kind)
        return t.text_content()

    def set_viewport(self, width, height=900):
        self.page.set_viewport_size({"width": width, "height": height})

    def press(self, *keys):
        for k in keys:
            self.page.keyboard.press(k)

    def focused(self) -> str:
        """The focused element as 'tag#id.class "text"', for keyboard assertions."""
        return self.page.evaluate("""() => { const e = document.activeElement; if (!e) return '';
            return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string'
              ? '.' + e.className.trim().split(/\\s+/).join('.') : '') + ' "' + (e.textContent || e.value || '').trim().slice(0, 40) + '"'; }""")

    def tab_to(self, selector, limit=80):
        """Press Tab until the element matching selector has focus (fails after limit presses)."""
        for _ in range(limit):
            if self.page.evaluate("s => document.activeElement && document.activeElement.matches(s)", selector):
                return
            self.page.keyboard.press("Tab")
        self.fail(f"Tab never reached {selector}; focus is on {self.focused()}")

    def overflow(self) -> list[str]:
        """What scrolls sideways: the page itself, <main> (it scrolls on its own, so the page alone never shows it) and the
        open drawer. Lists the elements sticking out past such a region's right edge, skipping anything inside a
        scroller of its own (the nav row, a wide <pre>): those scroll on purpose. Empty when nothing scrolls sideways."""
        return self.page.evaluate("""() => {
            const name = e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string'
              ? '.' + e.className.trim().split(/ +/).join('.') : '') + ' right=' + Math.round(e.getBoundingClientRect().right);
            const roots = [[document.documentElement, document.body], [document.querySelector('main')], [document.querySelector('#drawer.open')]];
            const out = [];
            for (const [root, top = root] of roots) {
              if (!root || root.scrollWidth <= root.clientWidth + 1) continue;
              const edge = root === document.documentElement ? root.clientWidth : root.getBoundingClientRect().left + root.clientWidth;
              const clipped = e => { for (let p = e.parentElement; p && p !== top; p = p.parentElement)
                if (getComputedStyle(p).overflowX !== 'visible') return true; return false; };  // inside its own scroller
              out.push(...[...top.querySelectorAll('*')].filter(e => { const r = e.getBoundingClientRect();
                return r.width && r.right > edge + 1 && (root !== document.documentElement || getComputedStyle(e).position !== 'fixed') && !clipped(e); })
                .slice(0, 8).map(e => (root === document.documentElement ? 'page: ' : root.tagName.toLowerCase() + (root.id ? '#' + root.id : '') + ': ') + name(e)));
            }
            return out; }""")
