"""The Board's Map (pass 53): open jobs with a U.S. place become dots and rows (miles from the home place when the
search profile has one), remote ones are listed apart, a row opens the job, and the button hides it again."""
import unittest

from harness import E2ETestCase


class BoardMap(E2ETestCase):
    def test_map_dots_rows_and_open_a_job(self):
        self.go("board")
        btn = self.page.locator("#fMap")
        btn.click()
        self.idle()
        box = self.page.locator("#boardMap")
        self.assertTrue(box.is_visible())
        self.assertGreater(box.locator("svg.bmap circle.mdot").count(), 2)
        self.assertIn("Portland, OR", box.locator("table.mlist").text_content())
        self.assertIn("Remote:", box.text_content())
        self.assertIn("Census", box.text_content())
        box.locator("table.mlist a").first.click()
        self.idle()
        self.page.wait_for_selector("#drawer.open")
        self.page.keyboard.press("Escape")
        btn.click()
        self.assertTrue(box.is_hidden())
        self.assertEqual(btn.get_attribute("aria-pressed"), "false")


if __name__ == "__main__":
    unittest.main()
