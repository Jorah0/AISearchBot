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


if __name__ == "__main__":
    unittest.main()
