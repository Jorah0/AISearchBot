"""The in-app browser bar (pass 52): in the desktop app a 'Search these yourself' link opens in Lodestar's own browser
window (no system window), the bar shows its address and drives it, Save this job adds the open page to the Board,
and the bar hides. pywebview is faked: the server is this process, so the fake window is what the bar drives."""
import sys
import unittest
from pathlib import Path

from harness import E2ETestCase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from test_browser import FakeWebview  # noqa: E402

from lodestar import browser, db  # noqa: E402  (after harness: it sets the temp home first)


class InAppBrowser(E2ETestCase):
    def test_site_links_open_in_the_app_and_save_a_job(self):
        wv = FakeWebview({"title": "Night Auditor - Pellucid Lodge", "url": "https://jobs.pellucid.example/7",
                          "desc": "Overnight books.", "posting": {"title": "Night Auditor", "company": "Pellucid Lodge"}})
        old = (browser.ON, browser._W, browser._webview)
        browser.ON, browser._W, browser._webview = True, None, (lambda: wv)
        self.addCleanup(lambda: setattr(browser, "ON", old[0]) or setattr(browser, "_W", old[1]) or setattr(browser, "_webview", old[2]))
        self.reload_state()
        popups = []
        self.context.on("page", lambda p: popups.append(p))
        self.go("search")
        self.page.fill("#sQ", "night auditor")
        bar = self.page.locator("#browserBar")
        self.assertTrue(bar.is_hidden())
        self.page.locator('#siteSearch a[data-site="LinkedIn"]').click()
        self.idle()
        self.assertTrue(bar.is_visible())
        self.assertEqual(popups, [])  # not the system browser
        self.assertEqual(len(wv.windows), 1)
        self.assertIn("linkedin.com", wv.windows[0].url)
        self.assertEqual(self.page.input_value("#brUrl"), wv.windows[0].url)
        self.run_click("#brBack")
        self.assertEqual(wv.windows[0].js[-1], "history.back()")
        self.page.fill("#brUrl", "jobs.pellucid.example/7")
        self.page.press("#brUrl", "Enter")
        self.idle()
        self.assertEqual(wv.windows[0].url, "https://jobs.pellucid.example/7")
        self.run_click(bar.get_by_role("button", name="Save this job"))
        self.expect_toast("Saved to your Board: Night Auditor at Pellucid Lodge", "ok")
        self.assertTrue(db.con().execute("SELECT 1 FROM jobs WHERE company='Pellucid Lodge'").fetchone())
        self.run_click(bar.get_by_role("button", name="I applied"))  # pass 53
        self.expect_toast("Marked applied: Night Auditor at Pellucid Lodge", "ok")
        self.assertEqual(db.con().execute("SELECT status FROM jobs WHERE company='Pellucid Lodge'").fetchone()[0], "applied")
        self.run_click(bar.get_by_role("button", name="Keywords"))  # pass 53: the tracked job's own coverage, marked on the page
        self.expect_toast("Match ")
        self.assertIn("LodestarMark(", wv.windows[0].js[-1])
        self.page.click("#brHide")
        self.assertTrue(bar.is_hidden())

    def test_keyword_marks_on_a_page(self):  # pass 53: content.js LodestarMark, the highlighter the popup and bar use
        src = (Path(__file__).resolve().parents[2] / "extension" / "content.js").read_text(encoding="utf-8")
        self.page.evaluate("document.body.insertAdjacentHTML('beforeend', '<div id=kwt>We use SQL and Python; C# too. sqlite is not sql.</div>')")
        self.page.evaluate(src)
        n = self.page.evaluate("LodestarMark(['SQL', 'C#'], ['Python'])")
        marks = self.page.locator("#kwt mark[data-lodestar]")
        self.assertGreaterEqual(n, 4)  # the whole page is marked; this block holds four
        self.assertEqual(marks.count(), 4)
        self.assertEqual([marks.nth(i).text_content() for i in range(4)], ["SQL", "Python", "C#", "sql"])
        self.assertEqual(marks.nth(1).get_attribute("title"), "in your resume")
        self.assertEqual(self.page.evaluate("LodestarMark([], [])"), 0)  # cleared
        self.assertEqual(self.page.locator("#kwt mark").count(), 0)
        self.assertEqual(self.page.text_content("#kwt"), "We use SQL and Python; C# too. sqlite is not sql.")


if __name__ == "__main__":
    unittest.main()
