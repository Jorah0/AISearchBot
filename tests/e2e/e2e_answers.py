"""Answers and Stories, and the mock interview: draft a form answer (blank refused, private answers never used, saved
through the Inbox), Options and Use this, the answer bank (blank, private, allow for employers, remove), the STAR form
(blank and title-only refused, competencies, edit, New story, incomplete chip, untagged list, remove), the mock
interview (job picker, Enter to send, score card with the STAR rubric, session summary, dictation with words per minute,
spoken replies, 'done' saves the debrief, trend chart, mode switch resets), keyboard and 420px."""
import json
import unittest

from harness import FLOOR, E2ETestCase, db, interview

AI = {"options": [
    {"label": "Direct", "tone": "direct", "subject": "", "recommended": True, "why": "answers the question",
     "body": "Your platform serves patients directly, and I build pipelines people rely on."},
    {"label": "Story", "tone": "warm", "subject": "", "recommended": False, "why": "",
     "body": "At Mapleleaf Clinics I built HIPAA-compliant ingestion for 40 clinics; I want that impact again."}],
    "situation": 2, "task": 1, "action": 2, "result": 2, "relevance": 2, "specificity": 1, "metrics_used": True,
    "one_fix": "Lead with the 40% number.", "suggested_rewrite": "I cut warehouse spend 40% by moving cold tables."}


class Answers(E2ETestCase):
    ai_json = AI

    def setUp(self):
        super().setUp()
        self.go("answers")

    def answers(self):
        return {a["question"]: a for a in self.state()["answers"]}

    def stories(self):
        return {s["title"]: s for s in self.state()["stories"]}

    # --- draft a form answer
    def test_draft_answer_blank_private_and_inbox(self):
        self.allow_console()
        self.page.select_option("#aJob", str(self.ids["interview"]))
        calls = len(self.ai_calls)
        self.run_click(self.page.locator("#answers").get_by_role("button", name="Draft", exact=True))
        self.expect_toast("error: type the application-form question first", "err")
        self.run_click(self.page.locator("#answers").get_by_role("button", name="Options", exact=True))
        self.expect_toast("error: type the application-form question first", "err")
        self.assertEqual(len(self.ai_calls), calls)  # nothing sent to the AI for a blank question
        before = {p["id"] for p in self.state()["pending"]}
        self.page.fill("#aQ", "What salary are you looking for?")
        self.run_click(self.page.locator("#answers").get_by_role("button", name="Draft", exact=True))
        out = self.page.text_content("#aOut2")
        self.assertTrue(out.startswith(self.ai_text))
        self.assertIn("[reused: ", out)
        self.assertIn("[save -> pending]", out)
        prompt = str(self.ai_calls[-1]["messages"])
        self.assertIn("Orchid Health", prompt)
        self.assertIn("Why do you want to work here?", prompt)  # prior answers are reused
        for private in ("What is my walk-away number?", "Private: my floor", FLOOR):  # never a private answer or the floor
            self.assertNotIn(private, prompt)
        new = [p for p in self.state()["pending"] if p["id"] not in before]
        self.assertEqual([(p["kind"], p["payload"]["question"]) for p in new],
                         [("save_answer", "What salary are you looking for?")])

    def test_answer_options_fill_the_bank_form(self):
        self.page.select_option("#aJob", str(self.ids["interview"]))
        self.page.fill("#aQ", "Why Orchid Health?")
        self.run_click(self.page.locator("#answers").get_by_role("button", name="Options", exact=True))
        opts = self.page.locator("#aOpts .opt")
        self.assertEqual(opts.count(), 2)
        self.assertIn("recommended", opts.nth(0).text_content())
        self.assertNotIn("Subject:", opts.nth(0).text_content())  # a form answer has no subject
        self.assertIn("QUESTION: Why Orchid Health?", str(self.ai_calls[-1]["messages"]))
        opts.nth(1).get_by_role("button", name="Use this").click()
        self.expect_toast("filled in under Answer bank: edit it, then Save", "ok")
        self.assertEqual(self.page.input_value("#bQ"), "Why Orchid Health?")
        self.assertEqual(self.page.input_value("#bA"), AI["options"][1]["body"])
        self.assertEqual(self.page.locator("#aOpts .opt").count(), 0)
        self.run_click(self.page.locator("#answers .panel", has_text="Answer bank").get_by_role("button", name="Save"))
        self.assertEqual(self.answers()["Why Orchid Health?"]["answer"], AI["options"][1]["body"])

    # --- the answer bank
    def test_answer_bank_save_private_toggle_and_remove(self):
        bank = self.page.locator("#answers .panel", has_text="Answer bank")
        save = bank.get_by_role("button", name="Save")
        save.click()
        self.expect_toast("type both a question and an answer", "err")
        seeded = self.page.locator("#bank .list > div", has_text="What is my walk-away number?")
        self.assertEqual(seeded.locator(".pill").text_content(), "private")
        self.assertEqual(seeded.get_by_role("button", name="allow for employers").count(), 1)
        self.page.fill("#bQ", "Notice period?")
        self.page.fill("#bA", "Two weeks.")
        self.page.fill("#bT", "logistics, notice")
        self.page.check("#bP")
        self.run_click(save)
        self.expect_toast("answer saved", "ok")
        a = self.answers()["Notice period?"]
        self.assertEqual((a["answer"], a["tags"], a["private"]), ("Two weeks.", "logistics, notice", 1))
        self.assertEqual([self.page.input_value(s) for s in ("#bQ", "#bA", "#bT")], ["", "", ""])
        self.assertFalse(self.page.is_checked("#bP"))
        row = self.page.locator("#bank .list > div", has_text="Notice period?")
        self.assertEqual(row.locator(".pill").text_content(), "private")
        self.run_click(row.get_by_role("button", name="allow for employers"))
        self.assertEqual(self.answers()["Notice period?"]["private"], 0)
        self.assertEqual(row.locator(".pill").count(), 0)
        self.run_click(row.get_by_role("button", name="make private"))
        self.assertEqual(self.answers()["Notice period?"]["private"], 1)
        self.run_click(row.get_by_role("button", name="remove"))
        self.assertNotIn("Notice period?", self.answers())
        self.assertEqual(row.count(), 0)

    # --- STAR stories
    def test_star_form_validation_competencies_edit_and_remove(self):
        self.allow_console()
        save = self.page.get_by_role("button", name="Save story")
        save.click()
        self.idle()
        self.expect_toast("error: a story needs a title of 1-120 characters", "err")
        self.page.fill("#stTitle", "Kafka migration with zero data loss")
        save.click()
        self.idle()
        self.expect_toast("error: write at least one of situation, task, action, result", "err")
        self.assertNotIn("Kafka migration with zero data loss", self.stories())
        self.page.fill("#stSituation", "The freight team ran on a fragile queue")
        self.page.fill("#stTask", "Move every producer to Kafka without losing an event")
        self.page.fill("#stAction", "I planned a dual-write cut-over and led 3 engineers through it")
        self.page.fill("#stResult", "Migrated in 6 weeks with zero data loss")
        self.page.fill("#stMetrics", "6 weeks, 0 lost events")
        self.page.check("#stComps input[value=leadership]")
        self.page.check("#stComps input[value=deadline]")
        self.run_click(save)
        self.expect_toast("story saved", "ok")
        s = self.stories()["Kafka migration with zero data loss"]
        self.assertEqual((s["result"], sorted(s["competencies"]), s["missing"]),
                         ("Migrated in 6 weeks with zero data loss", ["deadline", "leadership"], []))
        self.assertEqual(self.page.text_content("#stHint"), f"editing story #{s['id']}")
        item = self.page.locator("#storyList .list > div", has_text="Kafka migration with zero data loss")
        self.assertEqual(item.locator(".pill").all_text_contents(), ["leadership", "deadline"])
        untagged = self.page.text_content("#storyList > .muted")
        self.assertNotIn("leadership", untagged)
        self.assertIn("conflict", untagged)
        # saving again updates the same story
        self.page.fill("#stResult", "Migrated in 5 weeks with zero data loss")
        self.run_click(save)
        self.assertEqual(self.stories()["Kafka migration with zero data loss"]["id"], s["id"])
        self.assertEqual(self.stories()["Kafka migration with zero data loss"]["result"], "Migrated in 5 weeks with zero data loss")
        # New story clears the form; a story with gaps shows what it lacks
        self.page.get_by_role("button", name="New story").click()
        self.assertEqual([self.page.input_value(x) for x in ("#stId", "#stTitle", "#stResult")], ["", "", ""])
        self.assertEqual(self.page.locator("#stComps input:checked").count(), 0)
        self.page.fill("#stTitle", "Half-written story")
        self.page.fill("#stSituation", "A late vendor feed")
        self.run_click(save)
        half = self.page.locator("#storyList .list > div", has_text="Half-written story")
        self.assertIn("incomplete: no task, action, result", half.locator(".chip").text_content())
        # edit loads the seeded story into the form
        seeded = self.page.locator("#storyList .list > div", has_text="Cut warehouse spend 40%")
        seeded.get_by_role("button", name="edit").click()
        self.assertEqual(self.page.input_value("#stTitle"), "Cut warehouse spend 40%")
        self.assertEqual(self.page.input_value("#stAction"), "Moved cold tables to Iceberg on S3 and added usage dashboards")
        self.assertEqual(sorted(self.page.locator("#stComps input:checked").evaluate_all("l => l.map(e => e.value)")),
                         ["data-driven", "ownership"])
        self.assertEqual(self.page.text_content("#stHint"), f"editing story #{self.ids['story']}")
        self.page.get_by_role("button", name="New story").click()
        # remove: cancel keeps it, confirm removes it
        self.answer(False)
        half.get_by_role("button", name="remove").click()
        self.assertIn('Remove the story "Half-written story"?', self.dialogs[-1])
        self.idle()
        self.assertIn("Half-written story", self.stories())
        self.answer(True)
        self.run_click(half.get_by_role("button", name="remove"))
        self.expect_toast("story removed", "ok")
        self.assertNotIn("Half-written story", self.stories())

    # --- mock interview
    def test_mock_interview_score_card_dictation_debrief_and_trend(self):
        jid = self.ids["interview"]
        self.go("coach")
        self.assertFalse(self.page.is_visible("#cJob"))
        self.page.select_option("#cMode", "mock")
        self.assertTrue(self.page.is_visible("#cJob"))
        self.assertTrue(self.page.is_visible("#cSpeakL"))
        self.assertIn("Mock interview ready", self.page.text_content("#chat"))
        self.page.select_option("#cJob", str(jid))
        calls = len(self.ai_calls)
        self.page.click("#cGo")  # empty: nothing is sent
        self.idle()
        self.assertEqual(len(self.ai_calls), calls)
        self.page.evaluate("() => { window.__spoken = []; speechSynthesis.speak = u => __spoken.push(u.text); }")
        self.page.check("#cSpeak")
        self.page.fill("#cIn", "Ready when you are")
        self.page.press("#cIn", "Enter")
        self.idle()
        self.assertEqual(self.page.locator("#chat .msg.ai").last.text_content(), self.ai_text)
        self.assertIn("Staff Data Engineer at Orchid Health", self.ai_calls[-1]["system"])
        self.assertEqual(self.page.evaluate("__spoken"), [self.ai_text])  # spoken aloud when ticked
        self.assertEqual(self.page.locator("#chat .mcard").count(), 0)  # the first message is not an answer
        # an answer, dictated: the card adds words per minute from the dictation time
        self.page.evaluate("""() => { const real = performance.now.bind(performance); let skew = 0;
            performance.now = () => real() + skew;
            window.SpeechRecognition = class { start() { skew += 30000;
              setTimeout(() => { this.onresult({ results: [[{ transcript: 'At Tidewater I cut warehouse spend 40 percent by moving cold tables to Iceberg on S3' }]] }); this.onend(); }, 0); } }; }""")
        self.page.click("#cMic")
        self.page.wait_for_function("() => $('#cIn').value.includes('Tidewater') && !$('#cMic').disabled")
        self.page.click("#cGo")
        self.idle()
        card = self.page.locator("#chat .mcard").last
        text = card.text_content()
        self.assertIn("STAR S2 T1 A2 R2 (average 1.75/2)", text)
        self.assertIn("relevance 2/2", text)
        self.assertIn("numbers yes", text)
        self.assertIn("one fix: Lead with the 40% number.", text)
        self.assertRegex(text, r"\d+ words · 30(\.\d+)? s spoken")
        self.assertRegex(text, r"\d+ wpm")
        session = db.con().execute("SELECT id, answers FROM mock_sessions WHERE job_id=? ORDER BY id DESC", (jid,)).fetchone()
        self.assertEqual(json.loads(session["answers"])[0]["rubric"]["star"], 1.75)
        self.assertIn(f"session #{session['id']}: 1 answer(s), 1 scored · STAR average 1.75/2", self.page.text_content("#mockSum"))
        self.assertTrue(self.page.is_visible("#mockTrend"))
        self.assertGreaterEqual(self.page.locator("#trendSvg circle").count(), 1)
        self.assertIn("latest 1.75 of 2", self.page.get_attribute("#trendSvg svg", "aria-label"))
        # done: the debrief is saved with the job
        self.page.fill("#cIn", "done")
        self.page.press("#cIn", "Enter")
        self.idle()
        self.expect_toast("transcript and debrief saved to mock_interview.md in the job", "ok")
        self.assertIn("mock_interview.md", self.api(f"/api/jobs/{jid}")["docs"])
        # no speech recognition in this browser: says so
        self.page.evaluate("delete window.SpeechRecognition; delete window.webkitSpeechRecognition")
        self.page.click("#cMic")
        self.expect_toast("this browser has no speech recognition", "err")
        # switching mode starts a fresh chat
        self.page.select_option("#cMode", "coach")
        self.assertEqual(self.page.locator("#chat .msg").count(), 1)
        self.assertFalse(self.page.is_visible("#cJob"))
        self.assertFalse(self.page.is_visible("#mockSum"))
        self.assertEqual(interview.sessions()[-1]["averages"]["star"], 1.75)

    def test_keyboard_and_420px(self):
        self.page.focus("#bQ")
        self.page.keyboard.type("Earliest start date?")
        self.press("Tab")
        self.page.keyboard.type("Four weeks after an offer.")
        self.tab_to("#answers .panel:nth-of-type(2) button.b.ghost")  # Answer bank > Save
        self.press("Enter")
        self.idle()
        self.assertEqual(self.answers()["Earliest start date?"]["answer"], "Four weeks after an offer.")
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])
        self.go("coach")
        self.page.select_option("#cMode", "mock")
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
