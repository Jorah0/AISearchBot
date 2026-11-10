"""Ideas (craft with a job focus, status, refine, Save as story, remove) and Coach (chat, council mode, mode switch)."""
import json
import unittest

from harness import E2ETestCase, db

HOSTILE = '<img src=x onerror="window.__xss=1">'
IDEAS = [  # what the fake AI answers every ask_json with: the drafts, the critic pass and the converged list
    {"title": "Tell the warehouse cost story", "idea": f"Lead with ownership: the 40% cut {HOSTILE}",
     "why_it_works": "Orchid stresses ownership", "effort": 1, "impact": 5, "fit": 90,
     "plan": ["Write the STAR notes", "Rehearse it aloud"], "metric": "used in the next round", "time": "1 hour"},
    {"title": "Prepare an Airflow outage story", "idea": "A data-driven incident review", "why_it_works": "on call",
     "effort": 3, "impact": 3, "fit": 60, "plan": ["Pick the incident"], "metric": "story saved", "time": "2 hours"},
]


class Ideas(E2ETestCase):
    ai_json = IDEAS

    @classmethod
    def seed(cls):
        super().seed()
        body = {"title": "Rebuilt the nightly pipeline", "idea": "Took ownership of a failing nightly pipeline",
                "why_it_works": "shows ownership", "effort": 2, "impact": 4, "fit": 80, "plan": ["Outline it"],
                "metric": "story in the bank", "time": "1 hour"}
        cls.ids["story_idea"] = db.add_idea("stories", body["title"], json.dumps(body), 160.0, None, "")

    def panel(self, title):
        return self.page.locator("#ideaList > .panel", has_text=title)

    def test_craft_with_a_job_focus_saves_ranked_escaped_ideas(self):
        self.go("ideas")
        self.page.select_option("#iTopic", "stories")
        self.page.select_option("#iJob", str(self.ids["interview"]))
        self.page.fill("#iRole", "Staff Data Engineer")
        self.page.fill("#iN", "2")
        self.page.check("#iSingle")
        calls = len(self.ai_calls)
        self.run_click("#ideas button.b:has-text('Craft')")
        self.expect_toast("2 idea(s) saved", "ok")
        self.assertEqual(len(self.ai_calls) - calls, 3)  # one provider: drafts, a critic pass, then the converge
        first = str(self.ai_calls[calls]["messages"])
        self.assertIn("Orchid Health", first)  # the job focus reaches the prompt
        self.assertIn("Staff Data Engineer", first)
        saved = [i for i in self.state()["ideas"] if i["topic"] == "stories" and i["id"] != self.ids["story_idea"]]
        self.assertEqual([i["title"] for i in saved], ["Tell the warehouse cost story", "Prepare an Airflow outage story"])
        self.assertTrue(all(i["status"] == "new" for i in saved))
        best = self.panel("Tell the warehouse cost story")
        self.assertIn("score 450", best.text_content())  # impact 5 x fit 90 / effort 1
        self.assertIn(HOSTILE, best.text_content())  # the model's text is shown as text ...
        self.assertEqual(self.page.locator("#ideaList img").count(), 0)  # ... never as markup
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertEqual(best.locator("button", has_text="Save as story").count(), 1)  # a stories idea offers it

    def test_status_refine_save_as_story_and_remove(self):
        iid, title = self.ids["story_idea"], "Rebuilt the nightly pipeline"
        self.go("ideas")
        self.panel(title).locator("select").select_option("doing")
        self.page.wait_for_function("id => S.ideas.find(i => i.id === id)?.status === 'doing'", arg=iid)
        self.assertEqual(db.get_idea(iid)["status"], "doing")
        # refine: the feedback reaches the AI and the saved idea takes the new title and score
        cls = type(self)
        old, cls.ai_json = cls.ai_json, [IDEAS[0] | {"title": "Rebuilt the nightly pipeline, with numbers"}]
        try:
            self.page.fill(f"#rf{iid}", "add the before and after run times")
            calls = len(self.ai_calls)
            self.run_click(self.panel(title).locator("button", has_text="Refine"))
            self.expect_toast("refined: Rebuilt the nightly pipeline, with numbers", "ok")
        finally:
            cls.ai_json = old
        self.assertEqual(len(self.ai_calls) - calls, 1)
        self.assertIn("add the before and after run times", str(self.ai_calls[-1]["messages"]))
        row = db.get_idea(iid)
        self.assertEqual((row["title"], row["score"], row["status"]), ("Rebuilt the nightly pipeline, with numbers", 450.0, "doing"))
        # Save as story: an (incomplete) STAR story opens in Answers for you to finish
        self.page.wait_for_selector(f"#rf{iid}")
        self.panel("with numbers").locator("button", has_text="Save as story").click()
        self.page.wait_for_selector("section#answers.on")
        self.expect_toast("saved as a story", "ok")
        story = next(s for s in self.state()["stories"] if s["title"] == "Rebuilt the nightly pipeline, with numbers")
        self.assertIn("ownership", story["competencies"])
        self.assertEqual(self.page.input_value("#stTitle"), "Rebuilt the nightly pipeline, with numbers")
        # remove
        self.go("ideas")
        self.panel("with numbers").locator("button", has_text="remove").click()
        self.page.wait_for_function("id => !S.ideas.some(i => i.id === id)", arg=iid)
        self.assertEqual(self.panel("with numbers").count(), 0)
        self.assertNotIn(iid, [r["id"] for r in db.list_ideas()])


class Coach(E2ETestCase):
    ai_text = "Follow up with Bluefin Labs first: it has been quiet longest."

    def test_chat_sees_profile_and_tracker_and_council_answers_the_conversation(self):
        self.go("coach")
        calls = len(self.ai_calls)
        self.page.press("#cIn", "Enter")  # empty: nothing is sent
        self.idle()
        self.assertEqual(len(self.ai_calls), calls)
        self.assertEqual(self.page.locator("#chat .msg.me").count(), 0)
        self.page.fill("#cIn", "Which <b>application</b> should I chase first?")
        self.page.press("#cIn", "Enter")
        self.idle()
        chat = self.page.locator("#chat")
        self.assertEqual(chat.locator(".msg.me").last.text_content(), "Which <b>application</b> should I chase first?")
        self.assertEqual(chat.locator("b").count(), 0)  # your text is shown as text
        self.assertEqual(chat.locator(".msg.ai").last.text_content(), self.ai_text)
        system = self.ai_calls[-1]["system"]
        self.assertIn("Pat Rivera", system)  # profile ...
        self.assertIn("Orchid Health - Staff Data Engineer", system)  # ... and tracker
        self.assertEqual(self.page.input_value("#cIn"), "")
        # council: every provider answers the whole conversation, then one synthesis
        self.page.check("#cCouncil")
        calls = len(self.ai_calls)
        self.page.fill("#cIn", "And after that?")
        self.run_click("#cGo")
        self.assertGreaterEqual(len(self.ai_calls) - calls, 2)
        self.assertIn("Conversation so far", str(self.ai_calls[calls]["messages"]))
        self.assertIn("should I chase first", str(self.ai_calls[calls]["messages"]))  # the earlier turn goes along
        self.assertEqual(chat.locator(".msg.ai").count(), 3)  # greeting + two replies
        # switching to a mock interview starts a fresh conversation and shows the job picker
        self.page.select_option("#cMode", "mock")
        self.assertTrue(self.page.locator("#cJob").is_visible())
        self.assertEqual(chat.locator(".msg").count(), 1)
        self.assertIn("Mock interview ready", chat.text_content())
        self.page.select_option("#cMode", "coach")
        self.assertFalse(self.page.locator("#cJob").is_visible())
        self.assertIn("Ask me anything", chat.text_content())


if __name__ == "__main__":
    unittest.main()
