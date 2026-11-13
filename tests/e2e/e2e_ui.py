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


if __name__ == "__main__":
    unittest.main()
