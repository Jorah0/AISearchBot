"""AI: fill this page (pass 54): the button sits on every tab; its cards start unticked; Fill only this types into
the field (outlined) without saving anything; a revise goes back to the AI with a note and comes back into the card."""
import unittest

from harness import E2ETestCase


class PageFill(E2ETestCase):
    ai_json = {"fills": [{"id": "wKw", "value": "python, sql", "reason": "from your profile"}]}

    def test_every_tab_has_it_and_fill_never_saves(self):
        self.assertGreaterEqual(self.page.locator(".pfbar").count(), 15)
        self.go("monitor")
        before = len(self.state()["watches"])
        self.run_click(self.page.locator('.pfbar[data-pf="monitor"] button'))
        panel = self.page.locator('[data-pfp="monitor"]')
        card = panel.locator(".advcard").first
        self.assertFalse(card.locator("input[type=checkbox]").is_checked())
        self.assertIn("+ python, sql", card.locator("pre.advdiff").text_content())
        self.addCleanup(setattr, type(self), "ai_json", type(self).ai_json)
        type(self).ai_json = {"fills": [{"id": "wKw", "value": "python, sql, dbt", "reason": "added dbt"}]}
        card.locator("input.grow").fill("add dbt")
        self.run_click(card.get_by_role("button", name="Revise with AI: ", exact=False))
        self.assertIn("python, sql, dbt", card.locator("pre.advdiff").text_content())
        card.get_by_role("button", name="Fill only this", exact=False).click()
        self.assertEqual(self.page.input_value("#wKw"), "python, sql, dbt")
        self.assertIn("ai-filled", self.page.get_attribute("#wKw", "class"))
        self.assertIn("nothing was saved or sent", panel.text_content())
        self.assertEqual(len(self.state()["watches"]), before)


if __name__ == "__main__":
    unittest.main()
