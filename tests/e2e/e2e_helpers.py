"""AI help menus (pass 19): every component's "✦ AI help" menu (Board, a job drawer, Contacts and a contact's drawer,
each story, Insights, Search, Monitor, Setup and Tools) lists its helpers; each one is a single AI call whose answer is
an escaped card that changes nothing; Fill STAR from my notes puts suggestion cards in the story's AI toolbar, which
only Apply suggestions writes (and Undo puts back); Explain this setting explains the setting you pick; without a
provider every helper says it needs one and calls nothing; all of it at 420px. The AI is faked."""
import unittest

from harness import E2ETestCase, ai, db, interview

from lodestar import advisor

XSS = '<img src=x onerror="window.__xss=1">'


class Helpers(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        cls.ids["notes"] = interview.save_story("Migrated the warehouse", situation="Moved 200 tables to Iceberg over a "
                                                "quarter; I wrote the plan and costs fell by a third")

    # --- helpers
    def menu(self, where, target=None, within="main"):
        """The menu (opened) and its result panel."""
        k = f"{where}_{target or 0}"
        m = self.page.locator(f'{within} details.aimenu[data-aim="{k}"]').first
        if not m.evaluate("e => e.open"):
            m.locator("summary").click()
        return m, self.page.locator(f'{within} [data-aimp="{k}"]').first

    def show(self, where, target=None):
        if where == "drawer":
            self.open_job(target)
            return "#drawer"
        if where == "contact":
            self.go("contacts")
            self.page.evaluate(f"openContact({int(target)})")
            self.page.wait_for_selector("#drawer.open")
            self.idle()
            return "#drawer"
        self.go(where)
        return "#storyList" if where == "answers" else f"#{where}"

    def counts(self):
        c = db.con()
        return [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("recommendations", "ai_changes", "pending")]

    # --- every menu, every text helper: one call, an escaped card, nothing changed
    def test_every_menu_lists_its_helpers_and_answers_in_a_card(self):
        j = self.ids
        old = type(self).ai_text
        type(self).ai_text = f"Start with #{j['saved']}. {XSS}"
        self.addCleanup(setattr, type(self), "ai_text", old)
        cases = [("board", "board", None), ("drawer", "job", j["saved"]), ("contacts", "contacts", None),
                 ("contact", "contact", j["c_maya"]), ("answers", "stories", j["story"]), ("insights", "insights", None),
                 ("search", "search", None), ("monitor", "monitor", None), ("setup", "setup", None), ("tools", "setup", None)]
        before = self.counts()
        seen = set()
        for where, menu, target in cases:
            within = self.show(where, target)
            m, out = self.menu(menu, target, within)
            names = [n for n, h in advisor.HELPERS.items() if h.where == menu]
            labels = [advisor.HELPERS[n].label for n in names]
            self.assertEqual(m.get_by_role("group").locator("button").all_text_contents(), labels, menu)
            self.assertIn("AI help for", m.get_by_role("group").get_attribute("aria-label"))
            for n in names:
                if advisor.HELPERS[n].scope:
                    continue
                with self.subTest(helper=n, where=where):
                    m, out = self.menu(menu, target, within)
                    calls = len(self.ai_calls)
                    self.run_click(m.get_by_role("button", name=advisor.HELPERS[n].label, exact=True))
                    self.assertEqual(len(self.ai_calls), calls + 1, "one AI call per helper")
                    card = out.locator(".advcard.aiout")
                    self.assertTrue(card.locator("b").text_content().startswith(advisor.HELPERS[n].label))
                    self.assertIn("nothing was changed", card.text_content())
                    self.assertIn(XSS, card.locator(".advtext").text_content())  # text, never markup
                    seen.add(n)
            if out.locator(".advcard").count():
                out.get_by_role("button", name="Close").click()
                self.assertEqual(out.locator(".advcard").count(), 0)
        self.assertEqual(seen, {n for n, h in advisor.HELPERS.items() if not h.scope})
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertEqual(self.counts(), before)  # no recommendation, AI change or Inbox item

    def test_job_helpers_send_the_posting_fenced(self):
        jid = self.ids["saved"]
        within = self.show("drawer", jid)
        m, out = self.menu("job", jid, within)
        self.run_click(m.get_by_role("button", name="Red flags", exact=True))
        prompt = self.ai_calls[-1]["messages"][0]["content"]
        self.assertIn("BLOCK posting", prompt)
        self.assertIn("Build reliable pipelines", prompt)
        self.assertIn(f"Red flags · #{jid} Northwind Analytics", out.text_content())

    # --- Fill STAR from my notes: cards in the story's toolbar, written only by Apply suggestions
    def test_fill_star_suggestions_apply_and_undo_through_the_story_toolbar(self):
        sid = self.ids["notes"]
        type(self).ai_json = {"recommendations": [
            {"field": f"s{sid}.action", "proposed": "I wrote the plan and moved 200 tables to Iceberg", "reason": "moved",
             "impact": "high", "risk": "low"},
            {"field": f"s{sid}.result", "proposed": "Costs fell by a third", "reason": "moved", "impact": "high", "risk": "low"}]}
        self.go("answers")
        m, out = self.menu("stories", sid, "#storyList")
        self.run_click(m.get_by_role("button", name="Fill STAR from my notes", exact=True))
        self.assertIn("Apply suggestions", out.text_content())
        panel = self.page.locator(f'#storyList [data-advp="stories_{sid}"]')
        self.assertEqual(panel.locator(".advcard").count(), 2)
        story = lambda: next(s for s in self.state()["stories"] if s["id"] == sid)  # noqa: E731
        self.assertEqual(story()["action"], "")  # nothing written yet
        bar = self.page.locator(f'#storyList .aibar[data-adv="stories_{sid}"]')
        self.run_click(bar.get_by_role("button", name="Apply suggestions", exact=True))
        self.assertEqual((story()["action"], story()["result"]), ("I wrote the plan and moved 200 tables to Iceberg", "Costs fell by a third"))
        self.assertIn("I wrote the plan and moved 200 tables", self.page.text_content("#storyList"))
        self.run_click(self.page.locator(f'#storyList .aibar[data-adv="stories_{sid}"]').get_by_role("button", name="Undo AI changes"))
        self.assertEqual((story()["action"], story()["result"]), ("", ""))

    # --- Explain this setting: the setting you pick, on Setup and Tools
    def test_explain_this_setting_explains_the_setting_you_pick(self):
        for tab, topic, text in (("setup", "autopilot", "The step-by-step pipeline"), ("tools", "pref:followup_days", "Follow-up after")):
            self.go(tab)
            m, out = self.menu("setup", None, f"#{tab}")
            m.locator("select.aitopic").select_option(topic)
            self.run_click(m.get_by_role("button", name="Explain this setting", exact=True))
            self.assertIn(text, self.ai_calls[-1]["messages"][0]["content"])
            self.assertIn("Explain this setting · ", out.text_content())

    # --- no provider: every helper says so and calls nothing
    def test_without_a_provider_every_helper_says_so(self):
        real = ai.available
        ai.available = lambda: []
        self.allow_console()  # the API's 400 below
        try:
            self.reload_state()
            calls = len(self.ai_calls)
            for where, menu, target in (("board", "board", None), ("drawer", "job", self.ids["saved"]), ("setup", "setup", None)):
                within = self.show(where, target)
                m, out = self.menu(menu, target, within)
                for b in m.get_by_role("group").locator("button").all():
                    self.assertIn("needs an AI provider", b.get_attribute("title"))
                    b.click()
                    self.assertIn("needs an AI provider", out.locator(".advmsg").text_content())
                    self.assertIn("Ollama", out.locator(".advmsg").text_content())
                if where == "drawer":
                    self.page.evaluate("closeDrawer()")
            r = self.api("/api/run/ai_help", {"helper": "next"})
            self.assertIn("AI provider", r["error"])
            self.assertEqual(len(self.ai_calls), calls)
        finally:
            ai.available = real
            self.reload_state()

    # --- narrow window
    def test_narrow_window_420(self):
        self.set_viewport(420)
        self.settle()
        old = type(self).ai_text
        type(self).ai_text = "Ask about on-call. " + "averylongunbrokenwordthatmustwrap" * 6
        self.addCleanup(setattr, type(self), "ai_text", old)
        within = self.show("drawer", self.ids["saved"])
        m, out = self.menu("job", self.ids["saved"], within)
        self.run_click(m.get_by_role("button", name="Questions to ask them", exact=True))
        self.assertTrue(out.locator(".advcard").is_visible())
        self.assertEqual(self.overflow(), [])
        self.page.evaluate("closeDrawer()")
        self.go("setup")
        self.menu("setup", None, "#setup")
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
