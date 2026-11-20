"""Accounts tab (pass 34): every connection's state grouped (email, AI, job boards, site accounts), job sources, site
accounts and job alerts in one place, links that stopped working flagged on the tab, its nav badge and Today, the
history of changes, Check all now; and the Jobs tab starts from your target level."""
import unittest

from harness import E2ETestCase

from lodestar import connections, settings


class Connections(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        connections.track("boards", "remotive", "ok")
        connections.track("boards", "remotive", "failed", "HTTP 503 <b>down</b>")  # was working: lost since now
        connections.track("boards", "jobicy", "ok")
        connections.track("sites", "acme.wd1.myworkdayjobs.com", "ok")

    def test_tab_groups_every_connection_and_holds_the_linking_cards(self):
        self.go("accounts")
        page = self.page.locator("section#accounts")
        for card in ("#connCard", "#srcCard", "#acctCard", "#alertCard"):
            self.assertEqual(page.locator(card).count(), 1, card)
            self.assertEqual(self.page.locator(f"section#setup {card}").count(), 0, card)  # moved, not copied
        heads = page.locator("#connList h4").all_text_contents()
        for g in ("Job boards", "Site accounts"):
            self.assertIn(g, heads)
        row = page.locator(".connrow[data-name='jobicy']")
        self.assertIn("Working", row.text_content())
        self.assertIn("Needs a key", page.locator(".connrow[data-name='adzuna']").text_content())
        self.assertIn("cannot be linked", page.locator("#connCard").text_content())
        self.run_click("#connCheck")
        self.expect_toast("checked every key", "ok")

    def test_a_link_that_stopped_working_is_flagged_everywhere(self):
        badge = self.page.locator("#lostN")
        self.assertEqual(badge.text_content(), "1")
        self.assertIn("1 connection stopped working", self.page.locator("#homeLost").text_content())  # Today
        self.page.locator("#homeLost").get_by_role("button", name="Open Accounts").click()
        self.page.wait_for_selector("section#accounts.on")
        row = self.page.locator(".connrow[data-name='remotive']")
        self.assertIn("Disconnected since", row.text_content())
        self.assertIn("HTTP 503 <b>down</b>", row.text_content())  # escaped text, never markup
        self.assertEqual(self.page.locator("#connCard b:text-is('down')").count(), 0)
        self.page.click("#connHistD summary")
        hist = self.page.locator("#connHist").text_content()
        self.assertIn("Working → Failed", hist)
        self.set_viewport(420)
        self.assertEqual(self.overflow(), [])

    def test_jobs_tab_starts_from_your_target_level(self):
        settings.set_pref("target_seniority", "senior")
        self.addCleanup(settings.set_pref, "target_seniority", "")
        self.reload_state()
        self.page.evaluate("$('#sLevel').value = ''")
        self.go("search")
        self.idle()
        self.assertEqual(self.page.input_value("#sLevel"), "senior")


if __name__ == "__main__":
    unittest.main()
