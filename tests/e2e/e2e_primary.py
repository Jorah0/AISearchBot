"""The primary AI switcher in the top bar (pass 49): the pill names the provider and model, the switcher lists the
linked providers, a typed model id is used, the pill and the saved preferences follow, Escape closes it, and a bad id
is refused in place."""
import unittest

from harness import E2ETestCase

from lodestar import settings  # noqa: E402  (after harness: it sets the temp home first)


class Primary(E2ETestCase):
    def test_switch_provider_and_model_from_the_top_bar(self):
        snap = settings.load()
        self.addCleanup(settings.save, snap)
        pill = self.page.locator("#aiPill")
        self.assertRegex(pill.text_content(), r"^AI: \w+ · \S+")
        pill.click()
        box = self.page.locator("#aiSwitch")
        self.assertTrue(box.is_visible())
        self.assertIn("anthropic", box.locator("#aiProv").text_content())
        self.page.select_option("#aiProv", "anthropic")
        self.page.fill("#aiModelOwn", "claude-opus-5-5")
        self.run_click(box.get_by_role("button", name="Use"))
        self.expect_toast("primary AI: anthropic · claude-opus-5-5", "ok")
        self.assertEqual(pill.text_content(), "AI: anthropic · claude-opus-5-5")
        self.assertTrue(box.is_hidden())
        self.assertEqual((settings.pref("provider"), settings.pref("models")["anthropic"]), ("anthropic", "claude-opus-5-5"))
        pill.click()
        self.page.keyboard.press("Escape")
        self.assertTrue(box.is_hidden())
        self.allow_console()  # the refused id below is a 400
        pill.click()
        self.page.fill("#aiModelOwn", "bad id; rm")
        self.run_click(box.get_by_role("button", name="Use"))
        self.expect_toast("model id", "err")
        self.assertEqual(settings.pref("models")["anthropic"], "claude-opus-5-5")

    def test_choose_the_council_models(self):  # pass 50
        snap = settings.load()
        self.addCleanup(settings.save, snap)
        self.page.locator("#aiPill").click()
        box = self.page.locator("#aiSwitch")
        self.assertIn("every linked provider", box.locator("#aiCouncil").text_content())
        self.page.select_option("#aiCProv", "anthropic")
        for model in ("claude-haiku-5-5", "claude-opus-5-5"):
            self.page.fill("#aiCModelOwn", model)
            self.run_click(box.get_by_role("button", name="Add to the council"))
            self.expect_toast("council:", "ok")
        self.assertEqual(settings.pref("council_members"), "anthropic=claude-haiku-5-5, anthropic=claude-opus-5-5")
        self.assertIn("anthropic · claude-opus-5-5", box.locator("#aiCouncil").text_content())
        self.run_click(box.get_by_role("button", name="remove anthropic=claude-haiku-5-5 from the council"))
        self.page.wait_for_function("() => S.council.length === 1")
        self.assertEqual(settings.pref("council_members"), "anthropic=claude-opus-5-5")
        self.run_click(box.get_by_role("button", name="Reset: every provider"))
        self.expect_toast("council: every linked provider", "ok")
        self.assertEqual(settings.pref("council_members"), "")

    def test_turn_the_council_off_and_on(self):  # pass 54
        snap = settings.load()
        self.addCleanup(settings.save, snap)
        self.page.locator("#aiPill").click()
        box = self.page.locator("#aiSwitch")
        self.assertTrue(self.page.is_checked("#aiCouncilOn"))
        self.page.uncheck("#aiCouncilOn")
        self.idle()
        self.expect_toast("council off", "ok")
        self.assertFalse(settings.pref("council_on"))
        self.assertIn("dim", box.locator("#aiCouncilBox").get_attribute("class"))
        self.page.keyboard.press("Escape")
        self.go("coach")
        self.assertTrue(self.page.locator("#cCouncil").is_hidden())
        self.page.locator("#aiPill").click()
        self.page.check("#aiCouncilOn")
        self.idle()
        self.assertTrue(settings.pref("council_on"))
        self.page.keyboard.press("Escape")
        self.assertTrue(self.page.locator("#cCouncil").is_visible())
        self.page.locator("#aiPill").click()
        self.page.select_option("#aiCProv", "anthropic")
        self.page.fill("#aiCModelOwn", "claude-haiku-5-5")
        self.run_click(box.get_by_role("button", name="Add to the council"))
        self.page.fill("#aiCModelOwn", "claude-haiku-5-5")
        box.get_by_role("button", name="Add to the council").click()
        self.expect_toast("already in the council", "err")


if __name__ == "__main__":
    unittest.main()
