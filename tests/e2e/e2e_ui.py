"""Pass 32 UI overhaul: the grouped sidebar (blueprint 18.1; seven sections like the best tools in the class), with
every existing tab kept under its section heading and still opening its own page."""
import unittest

from harness import E2ETestCase

GROUPS = {"Pipeline": ["board", "contacts"], "Discover": ["search", "careers", "monitor"],
          "Resume": ["profile", "studio"], "Prepare": ["answers", "coach", "ideas"], "Progress": ["insights"],
          "Settings": ["tools", "setup"]}


class UI(E2ETestCase):
    def test_sidebar_groups_every_tab_under_its_section(self):
        for heading, tabs in GROUPS.items():
            group = self.page.locator("nav .nav-group", has=self.page.locator(".nav-h", has_text=heading))
            self.assertEqual(group.count(), 1, heading)
            self.assertEqual(group.locator("button[data-tab]").evaluate_all("bs => bs.map(b => b.dataset.tab)"), tabs, heading)
        self.assertEqual(self.page.locator("nav button[data-tab] svg.ico").count(), self.page.locator("nav button[data-tab]").count())
        for tabs in GROUPS.values():
            for tab in tabs:
                self.go(tab)  # every old tab still opens its own page
        self.assertEqual(self.page.locator("nav [role=group]").count(), len(GROUPS))

    def test_today_is_the_home_page(self):
        self.assertEqual(self.page.locator("nav button[data-tab]").first.get_attribute("data-tab"), "home")
        self.page.wait_for_selector("section#home.on")  # the page opens on Today
        for block in ("#onboard", "#today", "#upcoming"):
            self.assertEqual(self.page.locator(f"section#home {block}").count(), 1, block)
            self.assertEqual(self.page.locator(f"section#board {block}").count(), 0, block)
        self.go("board")
        self.assertTrue(self.page.locator("#nCo").is_visible())  # Board starts with its tracker
        self.go("home")

    def test_theme_switch_changes_the_colours_and_is_kept(self):
        bg = lambda: self.page.evaluate("getComputedStyle(document.body).backgroundColor")  # noqa: E731
        before, theme = bg(), self.page.evaluate("document.documentElement.dataset.theme || ''")
        self.page.click("#themeBtn")
        after = self.page.evaluate("document.documentElement.dataset.theme")
        self.assertIn(after, ("light", "dark"))
        self.assertNotEqual(after, theme)
        self.assertNotEqual(bg(), before)
        self.page.reload()
        self.page.wait_for_selector("section#home.on")
        self.assertEqual(self.page.evaluate("document.documentElement.dataset.theme"), after)  # kept for this browser
        self.page.set_viewport_size({"width": 420, "height": 800})
        self.assertEqual(self.overflow(), [])

    def test_job_drawer_header_stays_and_the_index_jumps(self):
        d = self.open_job(self.ids["saved"])
        idx = d.locator("nav.jIndex")
        self.assertEqual(idx.get_by_role("link").all_text_contents()[:2], ["Fit", "Documents"])
        idx.get_by_role("link", name="Documents").click()
        self.page.wait_for_function("() => { const g = document.querySelector('#jDocs').getBoundingClientRect(); return g.top < innerHeight / 2 && g.bottom > 0; }")
        top = self.page.evaluate("document.querySelector('#drawer .head').getBoundingClientRect().top")
        self.assertLess(abs(top - self.page.evaluate("document.querySelector('#drawer').getBoundingClientRect().top")), 40)  # still on top


    def test_go_to_keys_and_the_cheat_sheet(self):
        self.page.locator("body").click(position={"x": 5, "y": 300})
        self.page.keyboard.press("g")
        self.page.keyboard.press("b")
        self.page.wait_for_selector("section#board.on")
        self.page.keyboard.press("g")
        self.page.keyboard.press("t")
        self.page.wait_for_selector("section#home.on")
        self.go("search")
        self.page.fill("#sQ", "")
        self.page.focus("#sQ")
        self.page.keyboard.type("gb")  # typing in a field never navigates
        self.assertTrue(self.page.locator("section#search.on").count())
        self.assertEqual(self.page.input_value("#sQ"), "gb")
        self.page.locator("body").click(position={"x": 5, "y": 300})
        self.page.keyboard.press("?")
        sheet = self.page.locator("#keysHelp")
        self.assertTrue(sheet.is_visible())
        self.assertIn("g then b", sheet.text_content())
        self.page.keyboard.press("Escape")
        self.assertFalse(sheet.is_visible())


if __name__ == "__main__":
    unittest.main()
