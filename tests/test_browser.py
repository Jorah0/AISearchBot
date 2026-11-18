"""The in-app browser (pass 52): off outside the desktop app; in it, one reused window, http(s) only, the bar's
navigation, and Save this job reads the open page once (the extension's reader) and adds a Board card through
web.capture. A fake pywebview; no window, no network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import browser, db, web  # noqa: E402


class FakeWindow:
    def __init__(self, url, page=None):
        self.url, self.page, self.js = url, page, []

    def load_url(self, url):
        self.url = url

    def get_current_url(self):
        return self.url

    def evaluate_js(self, js):
        self.js.append(js)
        return self.page if "LodestarReadPosting" in js else None


class FakeWebview:
    def __init__(self, page=None):
        self.windows, self.page = [], page

    def create_window(self, title, url, **kw):
        w = FakeWindow(url, self.page)
        self.windows.append(w)
        return w


class Browser(unittest.TestCase):
    def setUp(self):
        self.wv = FakeWebview({"title": "Night Auditor - Quillfeather Inn | Board", "url": "https://jobs.quillfeather.example/1",
                               "desc": "Balance the books overnight.", "apply_links": ["https://boards.greenhouse.io/quill/jobs/1"],
                               "posting": {"title": "Night Auditor", "company": "Quillfeather Inn", "location": "Remote"}})
        p = patched(browser, ON=True, _W=None, _webview=lambda: self.wv)
        p.__enter__()
        self.addCleanup(p.__exit__, None, None, None)

    def test_off_outside_the_desktop_app(self):
        browser.ON = False
        self.assertEqual(browser.open_url("https://www.linkedin.com/jobs/search?keywords=x")["opened"], False)
        self.assertEqual(self.wv.windows, [])
        with self.assertRaisesRegex(ValueError, "not open"):
            browser.act("back")

    def test_one_window_reused_and_http_only(self):
        r = browser.act("open", "https://www.indeed.com/jobs?q=auditor")
        self.assertEqual((r["opened"], r["open"], r["url"]), (True, True, "https://www.indeed.com/jobs?q=auditor"))
        browser.act("go", "https://www.linkedin.com/jobs/")
        self.assertEqual(len(self.wv.windows), 1)
        self.assertEqual(browser.state()["url"], "https://www.linkedin.com/jobs/")
        for bad in ("javascript:alert(1)", "file:///c:/x", ""):
            with self.assertRaisesRegex(ValueError, "http"):
                browser.act("open", bad)
        self.wv.windows.clear()  # the user closed it: the next link makes a new one
        self.assertFalse(browser.state()["open"])
        browser.act("open", "https://example.com/")
        self.assertEqual(len(self.wv.windows), 1)

    def test_navigation_is_only_the_bar_buttons(self):
        browser.act("open", "https://example.com/a")
        for op, js in (("back", "history.back()"), ("forward", "history.forward()"), ("reload", "location.reload()")):
            browser.act(op)
            self.assertEqual(self.wv.windows[0].js[-1], js)
        with self.assertRaisesRegex(ValueError, "unknown"):
            browser.act("click")

    def test_save_this_job_reads_the_page_once_and_adds_a_card(self):
        browser.act("open", "https://jobs.quillfeather.example/1")
        r = browser.act("save")
        w = self.wv.windows[0]
        self.assertEqual(len(w.js), 1)
        self.assertIn("LodestarReadPosting", w.js[0])
        self.assertIn("function jsonLd", w.js[0])  # the extension's own reader, not a second one
        job = db.get_job(r["id"])
        self.assertEqual((job["company"], job["title"]), ("Quillfeather Inn", "Night Auditor"))
        self.assertEqual(r["ats"], "greenhouse")
        self.assertTrue(browser.act("save")["duplicate"])
        w.page = {"title": "x", "url": "about:blank"}
        with self.assertRaisesRegex(ValueError, "could not be read"):
            browser.act("save")

    def test_state_flag(self):
        self.assertTrue(web.state()["browser"])
        browser.ON = False
        self.assertFalse(web.state()["browser"])


if __name__ == "__main__":
    unittest.main()
