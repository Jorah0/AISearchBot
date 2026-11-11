"""Command palette (Ctrl+K / Cmd+K): keyboard only from open to result (arrows, Enter, Esc, focus given back), the
dialog / combobox / listbox roles with aria-activedescendant, fuzzy matching, every kind of entry (tab, job, contact,
document, setting, preference, actions: Add job, Check email, Run watches, Recommend on this tab, Open Today), the
drawer staying open under it, labels escaped, and 420px."""
import unittest

from harness import E2ETestCase, db, extras


class Palette(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        cls.ids["xss"] = db.add_job('<img src=x onerror="window.__pwned=1">Evil Co', "<b>Bold</b> Engineer", None, "jd")
        d = extras._job_dir(db.get_job(cls.ids["interview"]))
        d.mkdir(parents=True, exist_ok=True)
        (d / "cover_letter.md").write_text("Dear Orchid Health,\n\nI would like to join your data team.\n\nPat", encoding="utf-8")

    def open(self, key="Control+k"):
        self.page.keyboard.press(key)
        self.page.wait_for_selector("#palette:not([hidden])")
        self.assertEqual(self.focused().split(" ")[0], "input#palQ")
        self.idle()  # contacts and documents arrive

    def pick(self, query, expect):
        """Type a query, check the active option, press Enter."""
        self.page.keyboard.type(query)
        active = self.page.locator("#palList [aria-selected=true]")
        self.assertIn(expect, active.text_content())
        self.page.keyboard.press("Enter")
        self.page.wait_for_selector("#palette", state="hidden")

    def test_keyboard_only_opens_moves_runs_and_esc_gives_focus_back(self):
        self.tab_to('nav button[data-tab="inbox"]')
        self.open()
        d = self.page.locator("#palette")
        self.assertEqual((d.get_attribute("role"), d.get_attribute("aria-modal")), ("dialog", "true"))
        q = self.page.locator("#palQ")
        self.assertEqual((q.get_attribute("role"), q.get_attribute("aria-controls")), ("combobox", "palList"))
        self.assertEqual(self.page.get_attribute("#palList", "role"), "listbox")
        self.assertEqual(q.get_attribute("aria-activedescendant"), "palO0")
        self.assertEqual(self.page.locator("#palO0").get_attribute("aria-selected"), "true")
        self.press("ArrowDown")
        self.assertEqual(q.get_attribute("aria-activedescendant"), "palO1")
        self.assertEqual(self.page.locator("#palO1").get_attribute("aria-selected"), "true")
        self.assertEqual(self.page.locator("#palO0").get_attribute("aria-selected"), "false")
        self.press("ArrowUp", "ArrowUp")  # wraps to the last
        n = self.page.locator("#palList [role=option]").count()
        self.assertEqual(q.get_attribute("aria-activedescendant"), f"palO{n - 1}")
        self.press("Tab")
        self.assertEqual(self.focused().split(" ")[0], "input#palQ", "Tab stays in the dialog")
        self.press("Escape")
        self.page.wait_for_selector("#palette", state="hidden")
        self.assertIn('data-tab="inbox"', self.page.evaluate("document.activeElement.outerHTML"))
        # fuzzy: the letters in order, across words
        self.open()
        self.pick("orch staff", "Orchid Health - Staff Data Engineer")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=self.ids["interview"])
        self.assertIn("open", self.page.get_attribute("#drawer", "class"))
        # Esc with the drawer open closes the palette only
        self.open()
        self.press("Escape")
        self.page.wait_for_selector("#palette", state="hidden")
        self.assertIn("open", self.page.get_attribute("#drawer", "class"))
        # Meta+K (Cmd+K) toggles too
        self.open("Meta+k")
        self.press("Meta+k")
        self.page.wait_for_selector("#palette", state="hidden")

    def test_tabs_contacts_documents_settings_and_preferences(self):
        self.open()
        self.pick("go to setup", "Go to Setup")
        self.page.wait_for_selector("section#setup.on")
        self.assertIn('data-tab="setup"', self.page.evaluate("document.activeElement.outerHTML"))
        self.open()
        self.pick("maya", "Maya Chen (Orchid Health)")
        self.page.wait_for_selector("section#contacts.on")
        self.page.wait_for_function("id => CT && CT.contact.id === id", arg=self.ids["c_maya"])
        self.open()
        self.pick("cover_letter orchid", "cover_letter.md · #")
        self.page.wait_for_selector("#viewer:not([hidden])")
        self.idle()
        self.page.click("#vwClose")
        self.page.wait_for_selector("#viewer", state="hidden")
        self.open()
        self.pick("connect email", "Connect email")
        self.page.wait_for_selector("section#setup.on")
        self.assertTrue(self.page.evaluate("document.querySelector('#emailCard').contains(document.activeElement)"))
        label = self.page.evaluate("S.pref_help.followup_days[0]")
        i = self.page.evaluate("Object.keys(S.prefs).indexOf('followup_days')")
        self.open()
        self.pick(label, label)
        self.page.wait_for_selector("section#tools.on")
        self.assertEqual(self.page.evaluate("document.activeElement.getAttribute('aria-labelledby')"), f"pl{i}")

    def test_actions_add_job_check_email_watches_recommend_and_today(self):
        self.allow_console()  # the fake AI's Recommend answer may be refused (a 4xx): the click is what is tested here
        self.open()
        self.pick("add job", "Add job")
        self.assertEqual(self.focused().split(" ")[0], "input#nCo")
        self.open()
        with self.page.expect_request(lambda r: r.url.endswith("/api/run/email_check")):
            self.pick("check email", "Check email")
        self.idle()
        self.page.wait_for_function("document.activeElement.id === 'topEmail'")  # a keyboard user keeps their place
        self.open()
        with self.page.expect_request(lambda r: r.url.endswith("/api/run/watch_run")):
            self.pick("run watches", "Run watches")
        self.idle()
        self.page.wait_for_function("document.activeElement.id === 'topWatches'")
        self.go("inbox")
        self.open()
        with self.page.expect_request(lambda r: r.url.endswith("/api/run/advise")) as req:
            self.pick("recommend", "Recommend on this tab")
        self.assertEqual(req.value.post_data_json["scope"], "inbox")
        self.idle()
        self.go("tools")  # no AI toolbar here
        self.open()
        self.pick("recommend", "Recommend on this tab")
        self.expect_toast("This tab has no AI recommendations", "err")
        self.open()
        self.pick("open today", "Open Today")
        self.page.wait_for_selector("section#board.on")
        self.assertEqual(self.focused().split(" ")[0], "div#today.panel.today")

    def test_labels_are_escaped_and_no_match_says_so(self):
        self.open()
        self.page.keyboard.type("evil")
        opt = self.page.locator("#palList [role=option]").first
        self.assertIn('<img src=x onerror="window.__pwned=1">Evil Co - <b>Bold</b> Engineer', opt.text_content())
        self.assertEqual(self.page.locator("#palList img, #palList b").count(), 0)
        self.assertIsNone(self.page.evaluate("window.__pwned"))
        self.page.fill("#palQ", "zzqqxxjj")
        self.assertEqual(self.page.text_content("#palN"), "No matches")
        self.assertIsNone(self.page.get_attribute("#palQ", "aria-activedescendant"))
        self.press("Enter")  # nothing to run: stays open
        self.assertTrue(self.page.is_visible("#palette"))
        self.page.mouse.click(5, 5)  # beside the box
        self.page.wait_for_selector("#palette", state="hidden")

    def test_420px(self):
        self.set_viewport(420)
        self.open()
        self.page.keyboard.type("data engineer")
        box = self.page.locator(".palbox").bounding_box()
        self.assertLessEqual(box["x"] + box["width"], 420)
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
