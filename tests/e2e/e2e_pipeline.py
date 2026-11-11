"""The pipeline (pass 16.5): the drawer's stage strip (every state as text), Run next step, a step's line (Run, Re-run,
Retry, Skip, Unskip, its document, the apply packet and Mark applied), Run to with and without stale steps, the fit
gate's Continue anyway, form questions, the Questions panel at the top of the Inbox (answer for every job or this job
only, private, Use this, I'll fill it in myself, escaped text), the board chip, the table's Next step column and bulk
runs, the Autopilot pill and the Setup card (switch, budgets, per-step switches, run log), and 420px."""
import re
import unittest

from harness import E2ETestCase, ai, db, extras, resume

from lodestar import pipeline, settings  # noqa: E402  (after harness: it sets the temp home first)

AI = {  # every JSON-asking AI call: the fit verdict, bullet proposals, form-answer drafts, mail
    "verdict": "apply", "why": "skills match", "weak_areas": ["streaming at scale"], "suggestions": [], "red_flags": [],
    "bullets": [{"id": 1, "proposed": "Rebuilt the nightly freight ETL on Spark, Airflow and dbt, cutting runtime from 6 hours to 50 minutes",
                 "added_terms": ["dbt"], "reason": "names dbt"}],
    "order": [], "answer": "I rebuilt the nightly freight ETL on Spark and Airflow.", "missing": "",
    "subject": "Thanks", "body": "Thank you for your time.", "options": [], "score": 80, "category": "other", "summary": "fake"}
JD = "Senior data engineer. Python, SQL, Spark, Airflow and dbt pipelines. Ownership and leadership matter."


class Pipeline(E2ETestCase):
    ai_json = AI

    @classmethod
    def seed(cls):
        super().seed()
        settings.set_pref("auto_track_min_score", 0)  # pass 21: the fit gate reads the deterministic fit; 0 = always 'go'

    # --- helpers
    def new_job(self, company, status="saved", jd=JD):
        jid = db.add_job(company, "Data Engineer", f"https://jobs.example.com/{company.lower().replace(' ', '')}", jd, "e2e")
        db.update_job(jid, contact_email="hiring@example.org", contact_name="Hiring team")
        if status != "saved":
            db.set_status(jid, status)
        db.release()
        self.reload_state()
        return jid

    def stage(self, label):
        return self.page.locator("#pGroup .stage", has_text=re.compile(rf"^\S+ {re.escape(label)}( \d+)?$"))

    def state_of(self, label):
        """The step's state as the page says it: its aria-label 'Label: state (why)'."""
        return self.stage(label).get_attribute("aria-label").split(": ", 1)[1]

    def line_button(self, name):
        return self.page.locator("#pLine").get_by_role("button", name=name, exact=True)

    def ran(self, jid, stage):
        return [r for r in pipeline.log_runs(jid) if r["stage"] == stage]

    def tools_back(self):
        snap = settings.load()
        self.addCleanup(lambda: [settings.set_tool(t, v["enabled"], v["auto"]) for t, v in snap["tools"].items()])
        self.addCleanup(lambda: [settings.set_pref(k, snap["prefs"][k]) for k in
                                 ("autopilot", "autopilot_ai_per_cycle", "autopilot_ai_per_day", "autopilot_jobs_per_cycle")])

    # --- the strip
    def test_strip_shows_every_state_as_text_and_run_next_step_runs_one(self):
        jid = self.new_job("Strip Co")
        self.open_job(jid)
        self.assertTrue(self.state_of("Fit check").startswith("ready"))
        self.assertTrue(self.state_of("Research").startswith("todo"))
        self.assertTrue(self.state_of("Form answers").startswith("done"))  # no form questions yet
        self.assertTrue(self.state_of("Interview prep").startswith("later"))
        self.assertEqual(self.page.text_content("#pNext"), "Run next step (Fit check)")
        self.run_click("#pNext")
        self.expect_toast("Fit check: done", "ok")
        self.assertTrue(self.state_of("Fit check").startswith("done"))
        self.assertEqual(self.page.text_content("#pNext"), "Run next step (Research)")
        self.assertEqual([r["outcome"] for r in self.ran(jid, "score")], ["done"])
        self.assertFalse(self.ran(jid, "research"))  # one step, not the whole chain
        self.page.locator("#pGroup summary", has_text="Run log").click()
        self.assertIn("Fit check", self.page.locator("#pGroup table.log").text_content())
        # an applied job: steps for a saved job read n/a, the confirmation waits on the employer, nothing is ready
        self.open_job(self.ids["applied"])
        self.assertTrue(self.state_of("Fit check").startswith("skipped"))
        self.assertTrue(self.state_of("Apply").startswith("done"))
        self.assertTrue(self.state_of("Confirmation").startswith("waiting on the employer"))
        self.assertIn("… Confirmation", self.stage("Confirmation").text_content())
        self.assertTrue(self.page.locator("#pNext").is_disabled())
        self.assertIn("waiting on", self.page.text_content("#pWhy"))

    def test_step_line_run_rerun_document_skip_and_unskip(self):
        jid = self.new_job("Line Co")
        self.open_job(jid)
        self.stage("Research").click()
        self.assertIn("Research: todo", self.page.text_content("#pLine"))
        self.line_button("Skip").click()
        self.expect_toast("Research skipped for this job", "ok")
        self.page.wait_for_function("() => document.querySelector('#pLine') && /Unskip/.test(document.querySelector('#pLine').textContent)")
        self.assertTrue(self.state_of("Research").startswith("skipped"))
        self.line_button("Unskip").click()
        self.expect_toast("Research back in the pipeline", "ok")
        self.page.wait_for_function("() => /Research: todo/.test(document.querySelector('#pLine').textContent)")
        self.stage("Fit check").click()
        self.run_click(self.line_button("Run"))
        self.assertTrue(self.state_of("Fit check").startswith("done"))
        self.assertIn("rev 1", self.page.text_content("#pLine"))  # the line stays open across the refresh
        self.assertIsNotNone(db.get_job(jid)["fit_score"])  # pass 21: the Fit check stores the fit score (no file)
        self.run_click(self.line_button("Re-run"))
        self.assertIn("rev 2", self.page.text_content("#pLine"))
        self.assertEqual(len(self.ran(jid, "score")), 2)

    def test_error_reads_as_error_with_retry_and_no_provider_reads_blocked(self):
        jid = self.new_job("Retry Co")
        self.open_job(jid)
        self.run_click("#pNext")  # fit check
        real = extras.research

        def down(job, provider=None):
            raise SystemExit("the company site could not be reached")
        extras.research = down
        try:
            self.run_click("#pNext")
            self.expect_toast("Research: error (the company site could not be reached)", "err")
        finally:
            extras.research = real
        self.assertTrue(self.state_of("Research").startswith("error"))
        self.stage("Research").click()
        self.assertIn("the company site could not be reached", self.page.text_content("#pLine .pill"))
        self.run_click(self.line_button("Retry"))
        self.assertTrue(self.state_of("Research").startswith("done"))
        avail = ai.available
        ai.available = lambda: []
        try:
            self.open_job(jid)
            self.assertIn("blocked (needs an AI provider", self.state_of("Tailor resume"))
            self.assertIn("⛔ Tailor resume", self.stage("Tailor resume").text_content())
        finally:
            ai.available = avail

    def test_run_to_stops_at_a_stale_step_until_stale_steps_are_included(self):
        jid = self.new_job("Chain Co")
        self.open_job(jid)
        self.page.select_option("#pTo", "letter")
        self.run_click(self.page.locator("#pGroup").get_by_role("button", name="Go", exact=True))
        self.expect_toast("Fit check: done; Research: done; Tailor resume: done; Cover letter: done", "ok")
        self.assertTrue(self.state_of("Cover letter").startswith("done"))
        self.assertIn("Fake AI reply", str(self.ai_calls[-1]["messages"]))  # the research pack went into the letter prompt
        self.api(f"/api/docs/{jid}", {"name": "resume.md", "text": resume.app_dir(db.get_job(jid)).joinpath("resume.md")
                                      .read_text(encoding="utf-8") + "\n- Mentored two juniors\n"})
        self.open_job(jid)
        self.assertTrue(self.state_of("Cover letter").startswith("stale"))
        self.assertIn("↻ Cover letter", self.stage("Cover letter").text_content())
        self.page.select_option("#pTo", "letter")
        self.run_click(self.page.locator("#pGroup").get_by_role("button", name="Go", exact=True))
        self.expect_toast("nothing ran", "err")
        self.assertEqual(len(self.ran(jid, "letter")), 1)
        self.page.select_option("#pTo", "letter")
        self.page.check("#pStale")
        self.run_click(self.page.locator("#pGroup").get_by_role("button", name="Go", exact=True))
        self.expect_toast("Cover letter: done", "ok")
        self.assertTrue(self.state_of("Cover letter").startswith("done"))
        self.assertEqual(len(self.ran(jid, "letter")), 2)
        self.assertEqual({e["name"]: e["rev"] for e in pipeline.status(jid)}["letter"], 2)

    def test_fit_gate_says_so_and_continue_anyway_runs_the_next_step(self):
        settings.set_pref("auto_track_min_score", 100)  # pass 21: a fit under the threshold is the gate's 'skip'
        self.addCleanup(settings.set_pref, "auto_track_min_score", 0)
        jid = self.new_job("Gate Co")
        self.open_job(jid)
        self.run_click("#pNext")
        group = self.page.locator("#pGroup")
        self.assertIn("fit: skip", group.text_content())
        self.assertIn(": Autopilot leaves this job alone", group.text_content())
        self.answer(True)
        self.run_click(group.get_by_role("button", name="Continue anyway"))
        self.assertIn("this click is the override", self.dialogs[-1])
        self.assertTrue(self.state_of("Research").startswith("done"))

    def test_apply_line_has_the_packet_and_mark_applied(self):
        jid = self.new_job("Apply Co")
        self.open_job(jid)
        self.stage("Apply").click()
        line = self.page.locator("#pLine")
        self.assertEqual(line.get_by_role("link", name="Open posting ↗").get_attribute("href"), "https://jobs.example.com/applyco")
        n = len(self.opened)
        self.line_button("Show folder").click()
        self.page.wait_for_function("() => __ls.inflight === 0")
        self.assertTrue([p for k, p in self.opened[n:] if k == "folder" and f"{jid}-apply-co" in p])
        self.line_button("Mark applied").click()
        self.expect_toast(f"#{jid} → applied", "ok")
        self.page.wait_for_function("id => cur && cur.job.id === id && cur.job.status === 'applied'", arg=jid)
        self.assertTrue(self.state_of("Apply").startswith("done"))

    # --- questions
    def test_form_questions_ask_you_and_an_inbox_answer_resumes_the_step(self):
        jid = self.new_job("Form Co")
        self.open_job(jid)
        self.run_click("#pNext")  # fit check
        self.page.locator("#pGroup summary", has_text="Form questions").click()
        self.page.fill("#pForm", "Are you legally authorized to work in Canada?\nDescribe a pipeline you are proud of")
        self.page.locator("#pGroup").get_by_role("button", name="Add form questions").click()
        self.expect_toast("2 new form question(s)", "ok")
        self.page.wait_for_function("() => /Form answers: ready/.test([...document.querySelectorAll('#pGroup .stage')].map(b => b.getAttribute('aria-label')).join('|'))")
        self.stage("Form answers").click()
        n = len(self.ai_calls)
        self.run_click(self.line_button("Run"))
        self.assertTrue(self.state_of("Form answers").startswith("waiting on you"))
        self.assertEqual(self.stage("Form answers").text_content(), "? Form answers 1")
        self.assertFalse([c for c in self.ai_calls[n:] if "Canada" in str(c["messages"])])  # never AI-drafted
        card = self.page.locator("#drawer .item.q", has_text="authorized to work in Canada")
        self.assertIn("Lodestar never drafts eligibility answers", card.text_content())
        self.assertGreaterEqual(int(self.page.text_content("#inboxN")), len(self.state()["pending"]) + 1)
        self.page.evaluate("closeDrawer()")
        self.assertIn("question", self.page.locator("#today").text_content())
        self.go("inbox")
        card = self.page.locator("#questions .item.q", has_text="authorized to work in Canada")
        self.assertIn(f"#{jid} Form Co - Form answers", card.text_content())
        card.locator("textarea").fill("Yes, I am a Canadian citizen.")
        self.assertEqual(card.locator("select").input_value(), "reusable")
        self.run_click(card.get_by_role("button", name="Save answer"))
        self.expect_toast("answer saved; 1 waiting step(s) can go on", "ok")
        self.assertEqual(card.count(), 0)
        st = {e["name"]: e for e in pipeline.status(jid)}
        self.assertEqual(st["answers"]["state"], "done")
        text = resume.app_dir(db.get_job(jid)).joinpath("form_answers.md").read_text(encoding="utf-8")
        self.assertIn("Yes, I am a Canadian citizen.", text)
        self.assertIn("I rebuilt the nightly freight ETL", text)
        self.assertTrue(db.con().execute("SELECT 1 FROM answers WHERE question='Work authorization: canada'").fetchone())
        self.open_job(jid)
        self.assertIn("form_answers.md", self.page.locator("#docTabs").text_content())

    def test_question_card_use_this_job_only_private_and_fill_it_myself(self):
        jid = self.new_job("Ask Co")
        db.save_answer("How did you first hear about this opening?", "A former colleague told me about it.", "")
        job = db.get_job(jid)
        a, _ = pipeline.ask(job, "answers", "How did you first hear about this role?", "text")
        b, _ = pipeline.ask(job, "answers", "What is your current employer's name?", "text")
        c, _ = pipeline.ask(job, "answers", "Anything else we should know?", "text")
        self.assertEqual((a, b, c), (None, None, None))
        qid = {q["text"]: q["id"] for q in pipeline.questions(job=jid)}
        db.release()
        self.reload_state()
        self.go("inbox")
        card = lambda t: self.page.locator(f'#questions .item.q[data-q="{qid[t]}"]')  # noqa: E731
        hear = card("How did you first hear about this role?")
        hear.get_by_role("button", name=re.compile("^Use this: A former colleague")).click()
        self.assertEqual(hear.locator("textarea").input_value(), "A former colleague told me about it.")
        hear.locator("select").select_option("job")
        hear.get_by_role("button", name="Save answer").click()
        self.expect_toast("answer saved", "ok")
        self.page.wait_for_function("id => !document.querySelector(`#questions [data-q=\"${id}\"]`)", arg=qid["How did you first hear about this role?"])
        row = db.con().execute("SELECT status, scope, answer_id FROM questions WHERE id=?", (qid["How did you first hear about this role?"],)).fetchone()
        self.assertEqual(tuple(row), ("answered", "job", None))  # this job only: nothing new in the bank
        emp = card("What is your current employer's name?")
        emp.locator("textarea").fill("Tidewater Logistics")
        emp.locator('input[type="checkbox"]').check()
        emp.get_by_role("button", name="Save answer").click()
        self.expect_toast("answer saved", "ok")
        self.page.wait_for_function("id => !document.querySelector(`#questions [data-q=\"${id}\"]`)", arg=qid["What is your current employer's name?"])
        self.assertEqual(db.con().execute("SELECT scope FROM questions WHERE id=?", (qid["What is your current employer's name?"],)).fetchone()[0], "job")
        self.assertFalse(db.con().execute("SELECT 1 FROM answers WHERE answer='Tidewater Logistics'").fetchone())
        card("Anything else we should know?").get_by_role("button", name="I'll fill it in myself").click()
        self.expect_toast("left for you to fill in", "ok")
        self.page.wait_for_function("() => !document.querySelector('#questions .item.q')")
        self.assertEqual(db.con().execute("SELECT status FROM questions WHERE id=?", (qid["Anything else we should know?"],)).fetchone()[0], "dismissed")

    def test_question_text_renders_as_text_and_typing_survives_the_refresh(self):
        jid = self.new_job("Esc Co")
        evil = '<img src=x onerror="window.__xss=1">Why us?'
        pipeline.ask(db.get_job(jid), "answers", evil, "text")
        db.release()
        self.reload_state()
        self.go("inbox")
        card = self.page.locator("#questions .item.q", has_text="Why us?")
        self.assertIn('<img src=x onerror="window.__xss=1">Why us?', card.locator(".hd b").text_content())
        self.assertEqual(self.page.locator("#questions img").count(), 0)
        card.locator("textarea").fill("Half typed")
        self.reload_state()  # the 60 s refresh
        self.assertEqual(card.locator("textarea").input_value(), "Half typed")
        self.open_job(jid)
        self.assertIn("Why us?", self.page.locator("#drawer .item.q .hd b").text_content())
        self.assertIsNone(self.page.evaluate("window.__xss"))
        qid = pipeline.questions(job=jid)[0]["id"]
        pipeline.dismiss(qid)
        db.release()

    # --- board
    def test_board_chip_table_column_and_bulk_run_next_step_and_run_to(self):
        a, b = self.new_job("Bulk One"), self.new_job("Bulk Two")
        self.go("board")
        self.assertIn("next: Fit check", self.page.locator(f'.card[data-id="{a}"]').text_content())
        self.page.click("#fView")
        self.assertIn("Next step", self.page.locator("#jobTable thead").text_content())
        for jid in (a, b):
            self.page.check(f'input[aria-label="select #{jid}"]')
        self.answer(True)
        self.run_click(self.page.locator("#bulk").get_by_role("button", name="Run next step"))
        self.assertIn("Run the next step for 2 job(s)? About 2 AI calls.", self.dialogs[-1])
        self.expect_toast("ran steps for 2 of 2 job(s)", "ok")
        for jid in (a, b):
            self.assertTrue(self.ran(jid, "score"))
            self.assertIn("next: Research", self.page.locator("#jobTable tr", has=self.page.locator(f'input[aria-label="select #{jid}"]')).text_content())
        for jid in (a, b):
            self.page.check(f'input[aria-label="select #{jid}"]')
        self.page.select_option("#bulkTo", "tailor")
        self.answer(True)
        self.run_click(self.page.locator("#bulk").get_by_role("button", name="Run to"))
        self.assertIn("Run to Tailor resume for 2 job(s)? About 4 AI calls.", self.dialogs[-1])
        for jid in (a, b):
            self.assertEqual([r["outcome"] for r in self.ran(jid, "tailor")], ["done"])
        self.page.check(f'input[aria-label="select #{a}"]')
        self.answer(False)  # cancelled: nothing runs
        self.page.locator("#bulk").get_by_role("button", name="Run next step").click()
        self.assertFalse(self.ran(a, "letter"))

    def test_bulk_job_with_nothing_ready_is_counted_not_an_error(self):
        ready, idle = self.new_job("Bulk Ready"), self.new_job("Bulk Idle", "applied")
        self.go("board")
        self.page.click("#fView")
        for jid in (ready, idle):
            self.page.check(f'input[aria-label="select #{jid}"]')
        self.answer(True)
        self.run_click(self.page.locator("#bulk").get_by_role("button", name="Run next step"))
        self.expect_toast("ran steps for 1 of 2 job(s); 1 had nothing ready", "ok")
        self.assertNotIn(f"#{idle} #{idle}", self.page.text_content("#toast"))

    def test_run_to_inbox_card_lists_the_saved_answers_it_fills_in(self):
        label = "Are you legally authorized to work in the United States?"  # typed under Answers by the harness
        jid = self.new_job("Reuse Co")
        pipeline.add_form_questions(jid, [label, "Why <b>us</b>?"])
        prop = pipeline._propose(db.get_job(jid), pipeline.status(jid), "score")
        db.release()
        self.reload_state()
        self.go("inbox")
        card = self.page.locator("#inboxList .item", has_text=f"run #{jid} Reuse Co")
        self.assertIn("fills in 1 saved answer", card.text_content())
        reuse = card.locator(".reuse")
        self.assertIn("Saved answers this fills in on the form", reuse.text_content())
        self.assertIn(f"{label} → Yes, without sponsorship.", reuse.text_content())
        self.assertNotIn("Why", reuse.text_content())  # an AI-drafted label is not a saved answer
        card.get_by_role("button", name="Reject").click()
        self.page.wait_for_function(f"() => !S.pending.some(p => p.id === {prop['id']})")
        self.idle()
        self.assertEqual(pipeline.summary()[jid]["you"], 0)

    # --- Autopilot
    def test_autopilot_pill_switch_budgets_step_switches_and_run_log(self):
        self.tools_back()
        jid = self.new_job("Log Co")
        pipeline.run(jid, "score")
        db.release()
        pill = self.page.locator("#apPill")
        self.assertEqual(pill.text_content(), "Autopilot: off")
        pill.click()
        self.page.wait_for_selector("section#setup.on")
        self.assertTrue(self.page.locator("#apCard").is_visible())
        self.page.check("#apOn")
        self.page.wait_for_function("() => /^Autopilot: on · \\d+ of 30 AI calls today$/.test(document.querySelector('#apPill').textContent)")
        self.assertTrue(settings.pref("autopilot"))
        self.page.fill("#apDay", "12")
        self.page.press("#apDay", "Tab")
        self.page.wait_for_function("() => / of 12 AI calls today$/.test(document.querySelector('#apPill').textContent)")
        self.page.fill("#apCycle", "4")
        self.page.press("#apCycle", "Tab")
        self.page.wait_for_function("() => S.prefs.autopilot_ai_per_cycle === 4")
        self.assertEqual(settings.pref("autopilot_ai_per_cycle"), 4)
        self.page.uncheck('#apStages input[aria-label="Research enabled"]')
        self.page.check('#apStages input[aria-label="Cover letter auto"]')
        self.page.wait_for_function("() => S.tools.find(t => t.tool === 'cover_letter').auto && !S.tools.find(t => t.tool === 'research').enabled")
        self.assertFalse(settings.enabled("research"))
        self.assertTrue(settings.auto("cover_letter"))
        self.assertIn("no Autopilot cycle", self.page.text_content("#apLast"))
        self.page.locator("#apCard").get_by_role("button", name="Show the run log").click()
        self.page.wait_for_selector("#apLog table.log")
        self.assertIn(f"#{jid}", self.page.text_content("#apLog"))
        self.assertIn("Fit check", self.page.text_content("#apLog"))
        self.page.uncheck("#apOn")
        self.page.wait_for_function("() => document.querySelector('#apPill').textContent === 'Autopilot: off'")
        self.go("tools")
        self.assertIn("Autopilot may use this step", self.page.text_content("#tools .sub"))

    def test_narrow_window_strip_line_and_questions_do_not_scroll_sideways(self):
        jid = self.new_job("Narrow Co")
        pipeline.ask(db.get_job(jid), "answers", "A rather long open-ended question about the most complex data platform "
                     "migration you led end to end, and what you would do differently next time?", "text")
        db.release()
        self.set_viewport(420)
        self.open_job(jid)
        self.stage("Apply").click()
        self.page.locator("#pGroup summary", has_text="Run log").click()
        self.assertEqual(self.overflow(), [])
        self.page.evaluate("closeDrawer()")
        self.go("inbox")
        self.assertEqual(self.overflow(), [])
        pipeline.dismiss(pipeline.questions(job=jid)[0]["id"])
        db.release()


if __name__ == "__main__":
    unittest.main()
