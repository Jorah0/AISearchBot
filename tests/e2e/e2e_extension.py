"""Browser extension (extension/), client side: the unpacked extension loaded into a Playwright-launched persistent
context (its own temp profile), paired through its popup with this class's temp-home server, then Capture and Fill on
the fictional fixture forms in extension/test/fixtures, served from 127.0.0.1. Every fixture page records submits,
clicks and key presses; Fill must cause none. The popup is opened as a tab with its ?url= test hook (a 127.0.0.1 tab).

LODESTAR_E2E_UPDATE=1 rewrites extension/test/fixtures/*.descriptors.json from the real scan (the node matcher tests
replay those)."""
import functools
import hashlib
import http.server
import json
import os
import re
import tempfile
import threading
import types
import unittest
from urllib.parse import quote

import harness
from harness import FETCH_HOOK, PWError, ROOT, E2ETestCase, db, extras, sync_playwright
from lodestar import extension

EXT = ROOT / "extension"
FIX = EXT / "test" / "fixtures"
SPY = """(() => { window.__acts = []; for (const t of ['submit', 'click', 'keydown', 'mousedown'])
  document.addEventListener(t, (e) => __acts.push(t + ':' + (e.target.id || e.target.tagName)), true); })()"""


def ext_id(path) -> str:
    """Chromium's id for an unpacked extension: SHA-256 of its absolute path (UTF-16 on Windows), 32 hex digits as a-p."""
    raw = str(path).encode("utf-16-le" if os.name == "nt" else "utf-8")
    return "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(raw).hexdigest()[:32])


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # no favicon: a 204 instead of a 404 the console guard would report
        if self.path == "/favicon.ico":
            self.send_response(204)
            return self.end_headers()
        return super().do_GET()


class Extension(E2ETestCase):
    paired = False

    @classmethod
    def _browser(cls):  # an extension needs a persistent context: one per class, temp profile, the unpacked extension
        kind = os.environ.get("LODESTAR_E2E_BROWSER", "msedge").strip().lower()
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        try:
            cls.ctx = cls.pw.chromium.launch_persistent_context(
                tempfile.mkdtemp(prefix="ext-profile-", dir=harness._BASE), channel=kind,  # 'chromium': new headless
                # (Playwright's default headless shell cannot load extensions)
                headless=os.environ.get("LODESTAR_E2E_HEADED") != "1",
                args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        except PWError as e:
            if os.environ.get("CI"):
                raise
            raise unittest.SkipTest(f"no {kind} browser for Playwright: {str(e).splitlines()[0][:200]}")
        cls.addClassCleanup(cls.ctx.close)
        # the popup scans 8765-8774 for Lodestar: never let a test reach a real Lodestar running on this machine
        cls.blocked = []
        cls.ctx.route(re.compile(r"^http://127\.0\.0\.1:87(6[5-9]|7[0-4])/"),
                      lambda route: (cls.blocked.append(route.request.url), route.abort()))
        cls.keeper = cls.ctx.pages[0] if cls.ctx.pages else cls.ctx.new_page()  # the window stays open between tests
        cls.ext = f"chrome-extension://{ext_id(EXT)}"
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(FIX)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        cls.addClassCleanup(lambda: (srv.shutdown(), srv.server_close()))
        cls.fix = f"http://127.0.0.1:{srv.server_address[1]}/"
        cls.asked = []  # the questions the popup sent to /api/ext/autofill
        real = extras.ext_autofill
        cls._patch(extras, "ext_autofill", lambda qs, *a, **kw: cls.asked.append(list(qs)) or real(qs, *a, **kw))

    @classmethod
    def seed(cls):
        super().seed()
        for q, a, tags in (("Are you willing to relocate?", "Yes, within the Pacific Northwest.", ""),
                           ("EEO: gender", "Decline to self-identify", "eeo"), ("Desired salary", "$172,000", "salary")):
            db.save_answer(q, a, tags, source="typed under Answers")

    def setUp(self):  # the base setUp opens a fresh context; the extension lives in the class's persistent one
        self.errors, self.dialogs, self._answers, self._allowed = [], [], [], []
        self.context = types.SimpleNamespace(close=lambda: [p.close() for p in self.ctx.pages if p is not self.keeper])
        self.page = self.open(self.base + "/", FETCH_HOOK)
        self.page.wait_for_function("() => S !== null")
        self.idle()

    def open(self, url, init=None):
        page = self.ctx.new_page()
        page.set_default_timeout(10_000)
        page.on("console", lambda m: m.type == "error" and self.errors.append(f"console: {m.text} @ {m.location}"))
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("dialog", self._dialog)
        if init:
            page.add_init_script(init)
        page.goto(url)
        return page

    def form(self, name):
        """The fixture page and a popup aimed at it (paired with this server; pairs through the UI the first time)."""
        tab = self.open(self.fix + name)
        tab.evaluate(SPY)
        popup = self.open(f"{self.ext}/popup.html?url={quote(self.fix + name, safe='')}")
        if not type(self).paired:
            self.pair(popup)
        self.status(popup, "connected")
        return tab, popup

    def pair(self, popup):
        popup.evaluate("chrome.storage.local.clear()")  # the class shares one profile: start unpaired
        popup.reload()
        self.go("setup")
        self.run_click(self.page.locator("#extCard").get_by_role("button", name="Pair a browser"))
        type(self).code = self.page.text_content("#extCode")
        popup.fill("#pairing", type(self).code)
        popup.click("#pair")
        type(self).paired = True

    def status(self, popup, text):
        popup.wait_for_function("t => document.getElementById('status').textContent.includes(t)", arg=text, timeout=20_000)
        return popup.text_content("#status")

    def press(self, popup, button, done=("Filled", "Tracked", "Already", "cannot", "did not")):
        popup.evaluate("document.getElementById('status').textContent = ''")
        popup.click(button)
        popup.wait_for_function("ws => ws.some((w) => document.getElementById('status').textContent.includes(w))",
                                arg=list(done), timeout=20_000)
        return popup.text_content("#status")

    def panel(self, tab, act):
        """Click a button of the in-page panel (a closed shadow root, out of Playwright's reach) through CDP."""
        cdp = self.ctx.new_cdp_session(tab)
        try:
            def find(n):
                a = n.get("attributes") or []
                if n.get("nodeName") == "BUTTON" and "data-act" in a and a[a.index("data-act") + 1] == act:
                    return n
                for c in (n.get("children") or []) + (n.get("shadowRoots") or []):
                    if hit := find(c):
                        return hit
            node = find(cdp.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"])
            self.assertIsNotNone(node, f"no panel button {act}")
            q = cdp.send("DOM.getBoxModel", {"nodeId": node["nodeId"]})["model"]["content"]
            tab.mouse.click(sum(q[0::2]) / 4, sum(q[1::2]) / 4)  # a real (trusted) click, as yours would be
        finally:
            cdp.detach()

    def val(self, tab, css):
        return tab.eval_on_selector(css, "e => e.value")

    def lit(self, tab):
        return tab.evaluate("[...document.querySelectorAll('input, textarea, select')].filter(e => e.style.outline.includes('solid')).map(e => e.id || e.name)")

    # --- tests
    def test_pairs_through_the_popup_and_captures_the_postings_own_data(self):
        type(self).paired = False  # this test pairs through the UI whatever ran before
        tab, popup = self.form("greenhouse.html")
        self.assertRegex(self.status(popup, "connected"), r"^Lodestar 0\.2\.0 connected \(port \d+\)\.$")
        mine = [e for e in extension.paired() if e["origin"] == self.ext]
        self.assertTrue(mine and mine[-1]["label"] in ("Edge", "Chrome"))  # pinned to this extension's own Origin
        self.page.wait_for_function("document.getElementById('extCode').textContent === ''")  # the used code goes away
        self.assertRegex(self.page.text_content("#extLeft"), r"^paired: (Edge|Chrome)$")
        self.assertIn(mine[-1]["label"], self.page.text_content("#extList"))
        with self.assertRaises(SystemExit):  # the code was single use
            extension.pair(type(self).code.split("-", 1)[1], self.ext, "again")
        self.assertIn("This tab: 127.0.0.1", popup.text_content("#host"))
        said = self.press(popup, "#capture")
        self.assertRegex(said, r"^Tracked #\d+: Harborview Robotics - Platform Data Engineer$")
        jid = int(said.split("#")[1].split(":")[0])
        job = db.con().execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        self.assertEqual((job["location"], job["url"]), ("Tacoma, WA, US", self.fix + "greenhouse.html"))
        self.assertIn("USD 150000-185000 YEAR", job["jd"])
        self.assertIn("telemetry lake for our warehouse robots", job["jd"])
        self.assertNotIn("&lt;", job["jd"])
        self.assertEqual(self.press(popup, "#capture"), f"Already on your Board (#{jid}).")
        self.assertEqual(tab.evaluate("__acts"), [])  # capture only reads the page

    def test_fill_types_empty_fields_highlights_and_never_submits(self):
        tab, popup = self.form("greenhouse.html")
        tab.fill("#phone", "555-0199")  # typed by you before Fill: never overwritten
        tab.evaluate("__acts.length = 0")
        said = self.press(popup, "#fill")
        self.assertIn("Nothing was submitted", said)
        self.assertEqual(tab.evaluate("__acts"), [])  # no click, submit or key press reached the page
        self.assertEqual(tab.url, self.fix + "greenhouse.html")
        for css, want in (("#first_name", "Pat"), ("#last_name", "Rivera"), ("#email", "pat.rivera@example.com"),
                          ("#job_application_location", "Portland"), ("#phone", "555-0199"),
                          ("#q_linkedin", "https://linkedin.com/in/pat-rivera-example"),
                          ("#q_why", "Your data platform serves patients directly; I want that impact."),
                          ("#q_auth", "1"), ("#gender", ""), ("#q_hear", ""), ("#q_website", "")):
            self.assertEqual(self.val(tab, css), want, css)
        self.assertEqual(sorted(self.lit(tab)), sorted(["first_name", "last_name", "email", "job_application_location",
                                                        "q_linkedin", "q_why", "q_auth"]))
        self.assertIn("Filled 5 from your profile, 2 from your answers", said)
        self.assertIn("Resume/CV: upload your resume", popup.text_content("#needs"))
        sent = self.asked[-1]
        self.assertIn("Why do you want to work here?", sent)
        self.assertFalse({"Gender", "Veteran Status", "First Name", "Email"} & set(sent))  # only unclassified questions go
        # per-field Undo: back to empty and unhighlighted; after your own edit, Undo leaves the edit alone
        self.panel(tab, "undo:First Name")
        self.assertEqual(self.val(tab, "#first_name"), "")
        self.assertNotIn("first_name", self.lit(tab))
        tab.fill("#last_name", "Rivera-Diaz")
        self.panel(tab, "undo:Last Name")
        self.assertEqual(self.val(tab, "#last_name"), "Rivera-Diaz")
        # EEO only when ticked on this click; a second Fill only fills what is still empty
        popup.check("#eeo")
        self.press(popup, "#fill")
        self.assertEqual((self.val(tab, "#gender"), self.val(tab, "#first_name")), ("3", "Pat"))
        self.assertEqual(self.val(tab, "#last_name"), "Rivera-Diaz")
        self.panel(tab, "close")
        self.assertEqual(self.lit(tab), [])
        self.assertEqual(self.val(tab, "#first_name"), "Pat")  # Close keeps the values

    def test_hidden_honeypots_and_denied_fields_stay_empty_and_are_never_asked(self):
        tab, popup = self.form("generic.html")
        said = self.press(popup, "#fill")
        for css, want in (("#g1", "Pat"), ("#g2", "Rivera"), ("#g3", "pat.rivera@example.com"), ("#g10", "555-0100"),
                          ("#g8", ""), ("#g11", "Your data platform serves patients directly; I want that impact.")):
            self.assertEqual(self.val(tab, css), want, css)
        self.assertTrue(self.val(tab, "#g5") and self.val(tab, "#g6"))  # current company and title from the master
        for css in ("#h0", "#h1", "#h2", "#h3", "#h4", "#h5", "#h6", "#h7", "#d1", "#d2", "#d3"):
            self.assertEqual(self.val(tab, css), "", css)
        self.assertFalse(tab.eval_on_selector("[name=consent]", "e => e.checked"))
        self.assertEqual(tab.evaluate("[...document.querySelectorAll('[name=reloc]')].filter(r => r.checked).length"), 0)
        needs = popup.text_content("#needs")
        self.assertIn("Are you willing to relocate?: your stored answer: Yes, within the Pacific Northwest.", needs)
        sent = self.asked[-1]
        for label in ("Email (leave blank)", "Social Security Number", "Date of birth", "Last name again", "Your full name",
                      "Website", "Create a password"):
            self.assertNotIn(label, sent)  # a hidden or denied field's label never leaves the page
        self.assertEqual(tab.evaluate("__acts"), [])
        self.assertNotIn("withheld", said)
        popup.check("#salary")  # desired salary only when ticked
        self.press(popup, "#fill")
        self.assertEqual(self.val(tab, "#g8"), "$172,000")

    def test_fill_reaches_shadow_roots_and_work_history_groups(self):
        tab, popup = self.form("smartrecruiters.html")
        self.press(popup, "#fill")
        shadow = "([h, id]) => document.querySelectorAll('spl-input')[h].shadowRoot.getElementById(id).value"
        self.assertEqual([tab.evaluate(shadow, [i, n]) for i, n in enumerate(
            ("first-name", "last-name", "email", "confirm-email", "phone-number", "linkedin"))],
            ["Pat", "Rivera", "pat.rivera@example.com", "pat.rivera@example.com", "", "https://linkedin.com/in/pat-rivera-example"])
        tab, popup = self.form("workday.html")
        self.press(popup, "#fill")
        v = lambda i: self.val(tab, f'[id="{i}"]')  # noqa: E731
        self.assertEqual((v("name--legalName--firstName"), v("address--city"), v("emailAddress--emailAddress")),
                         ("Pat", "Portland", "pat.rivera@example.com"))
        self.assertEqual((v("workExperience-1--jobTitle"), v("workExperience-1--companyName")),
                         ("Senior Data Engineer", "Tidewater Logistics"))
        self.assertEqual((v("workExperience-2--jobTitle"), v("workExperience-2--companyName")),
                         ("Data Engineer", "Mapleleaf Clinics"))
        self.assertEqual((v("workExperience-1--startDate-dateSectionYear-input"),
                          v("workExperience-2--startDate-dateSectionYear-input"),
                          v("workExperience-2--endDate-dateSectionYear-input")), ("2021", "2018", "2021"))
        self.assertEqual(v("workExperience-1--location"), "")  # never your own location
        self.assertIn("Oregon State University", v("education-1--school"))
        self.assertIn("Month: month (stored: 2021)", popup.text_content("#needs"))
        self.assertEqual(tab.evaluate("__acts"), [])

    def test_scan_matches_the_committed_descriptors(self):
        """The node matcher tests replay extension/test/fixtures/*.descriptors.json: they must be what the real scan
        reads from each fixture (LODESTAR_E2E_UPDATE=1 rewrites them)."""
        for f in sorted(FIX.glob("*.html")):
            tab, popup = self.form(f.name)
            got = popup.evaluate("""async (u) => {
              const tab = (await chrome.tabs.query({})).find((t) => t.url === u);
              await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['matcher.js', 'content.js'] });
              const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => LodestarScan() });
              return result; }""", self.fix + f.name)
            want = f.with_suffix(".descriptors.json")
            if os.environ.get("LODESTAR_E2E_UPDATE") == "1":
                want.write_text(json.dumps(got["fields"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(got["fields"], json.loads(want.read_text(encoding="utf-8")), f.name)
            tab.close()
            popup.close()

    def test_revoked_browser_is_told_and_keeps_its_pairing_until_unpair(self):
        tab, popup = self.form("lever.html")
        mine = [e for e in extension.paired() if e["origin"] == self.ext]
        for e in mine:
            self.assertEqual(self.api("/api/extension/revoke", {"id": e["id"]}), {"ok": True})
        self.allow_console(r"Failed to load resource")  # the 401 and the port scan (8765-8774, aborted here)
        popup.reload()
        said = self.status(popup, "does not know this browser")
        self.assertRegex(said, r"^Lodestar on port \d+ does not know this browser\. Pair again from Lodestar > Setup, or Unpair\.$")
        self.assertTrue(popup.is_disabled("#fill") and popup.is_visible("#paired"))  # a 401 never clears the pairing
        self.assertEqual(len({u.split("/")[2] for u in self.blocked}), 10)  # it scanned 8765-8774 (blocked in tests)
        popup.click("#unpair")
        self.status(popup, "Unpaired here")
        self.assertTrue(popup.is_visible("#unpaired"))
        type(self).paired = False
