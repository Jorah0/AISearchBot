"""The job drawer: Details form, Match (+ "not mine"), Documents (tailor, check, audit, export, editor, cover, prep,
research, checklist, gap, options), Tailor by bullet, Interview rounds, Offer and calendar, Admin, status move, focus /
inert / Escape / Tab trap, and the drawer at 420px."""
import re
import unittest
import zipfile
from pathlib import Path

from harness import PROFILE_MD, E2ETestCase, db, day, interview, profile, resume

AI = {  # every JSON-asking AI call gets this: draft options, bullet proposals, the gap verdict
    "options": [
        {"label": "Confident", "tone": "confident", "subject": "Hello", "recommended": True, "why": "fits the stage",
         "body": "Dear team, I build reliable pipelines in Python and Airflow and would love to do that for you. Pat"},
        {"label": "Brief", "tone": "brief", "subject": "Hi", "recommended": False, "why": "",
         "body": "Hello, a short note on why I fit: Spark, Airflow, dbt. Pat"}],
    "bullets": [
        {"id": 1, "proposed": "Rebuilt the nightly freight ETL on Spark, Airflow and dbt, cutting runtime from 6 hours to 50 minutes",
         "added_terms": ["dbt"], "reason": "names dbt, which the posting asks for"},
        {"id": 2, "proposed": "Cut warehouse spend 75% by moving cold tables to Iceberg on S3", "reason": "a bigger number"}],
    "verdict": "good fit", "why": "skills match", "weak_areas": ["streaming at scale"], "suggestions": ["lead with Airflow"],
    "red_flags": [], "subject": "Thanks", "body": "Thank you for your time.", "score": 80, "category": "other", "summary": "fake"}


ALT = PROFILE_MD.replace("Cut warehouse spend 40%", "Shipped a Flink fraud-scoring pipeline; cut warehouse spend 40%")


class Drawer(E2ETestCase):
    ai_json = AI

    @classmethod
    def seed(cls):
        super().seed()
        # a saved resume in the profile bank: the drawer offers it as the base to tailor from
        profile.import_file(ALT.encode(), "alt-resume.md", "resume", None, False)

    # --- helpers
    def button(self, name):
        return self.page.locator("#drawer").get_by_role("button", name=name, exact=True)

    def act(self, name):
        """Click a drawer button that runs a background action and wait for it and the drawer refresh."""
        self.run_click(self.button(name))

    def folder(self, jid) -> Path:
        return resume.app_dir(db.get_job(jid))

    def docs(self, jid):
        return self.api(f"/api/jobs/{jid}")["docs"]

    def tab(self, name):
        self.page.locator("#docTabs button", has_text=re.compile(rf"^{re.escape(name)}$")).click()

    def new_job(self, company, title="Data Engineer"):
        jid = self.api("/api/jobs", {"company": company, "title": title, "jd": "Python, Airflow and dbt pipelines."})["id"]
        self.reload_state()
        return jid

    # --- Details
    def test_details_form_saves_validates_and_clears(self):
        self.allow_console()
        jid = self.ids["screening"]
        self.open_job(jid)
        for k, v in {"location": "Tacoma, WA", "salary_min": "120000", "salary_max": "140000", "currency": "usd",
                     "match_score": "65", "deadline": day(7), "posted_at": day(-3), "source": "referral",
                     "tags": "platform, kafka", "next_action": "Email the hiring manager", "next_action_at": day(2)}.items():
            self.page.fill(f"#d_{k}", v)
        self.page.select_option("#d_remote", "hybrid")
        self.page.select_option("#d_excitement", "3")
        self.run_click(self.button("Save details"))
        self.expect_toast("details saved", "ok")
        j = db.get_job(jid)
        self.assertEqual((j["location"], j["remote"], j["salary_min"], j["salary_max"], j["currency"], j["excitement"]),
                         ("Tacoma, WA", "hybrid", 120000, 140000, "USD", 3))
        self.assertEqual((j["match_score"], j["deadline"], j["posted_at"], j["source"], j["tags"], j["next_action"], j["next_action_at"]),
                         (65, day(7), day(-3), "referral", "platform,kafka", "Email the hiring manager", day(2)))
        self.assertIn("USD 120k–140k", self.page.text_content(f'.card[data-id="{jid}"]'))
        # bad input: refused with the reason, nothing changes
        for field, bad, why in (("currency", "US1", "3-letter code"), ("salary_min", "200000", "above salary_max"),
                                ("match_score", "150", "between 0 and 100")):
            self.open_job(jid)
            self.page.fill(f"#d_{field}", bad)
            self.run_click(self.button("Save details"))
            self.expect_toast(why, "err")
            self.assertEqual(db.get_job(jid)["currency"], "USD")
            self.assertEqual((db.get_job(jid)["salary_min"], db.get_job(jid)["match_score"]), (120000, 65))
        # an emptied field clears it
        self.open_job(jid)
        self.page.fill("#d_tags", "")
        self.page.select_option("#d_excitement", "")
        self.run_click(self.button("Save details"))
        self.assertEqual((db.get_job(jid)["tags"], db.get_job(jid)["excitement"]), (None, None))

    # --- Match
    def test_jd_coverage_and_not_mine_toggle(self):
        jid = self.ids["interview"]
        self.open_job(jid)
        self.assertEqual(self.button("Compute JD coverage").count(), 1)
        self.act("Compute JD coverage")
        score = int(self.page.text_content("#jMatch .cov-score").rstrip("%"))
        self.assertEqual(db.get_job(jid)["match_score"], score)
        self.assertEqual(self.page.input_value("#d_match_score"), str(score))
        self.assertIn("coverage.json", self.docs(jid))
        rows = self.page.locator("#jMatch table.kw tbody tr")
        self.assertGreater(rows.count(), 0)
        term = rows.nth(0).locator("td").nth(0).text_content()
        self.run_click(self.page.locator("#jMatch").get_by_role("button", name=f"not mine: {term}"))
        self.expect_toast(f'not counting "{term}"', "ok")
        self.assertIn(term.lower(), db.ats_skip(db.get_job(jid)))
        self.assertIn("skip", rows.nth(0).get_attribute("class"))
        self.run_click(self.page.locator("#jMatch").get_by_role("button", name=f"count again: {term}"))
        self.assertNotIn(term.lower(), db.ats_skip(db.get_job(jid)))
        self.open_job(jid)  # saved coverage: the button now offers a recompute
        self.assertEqual(self.button("Recompute JD coverage").count(), 1)
        self.tab("coverage.json")
        self.button("Edit document").click()
        self.expect_toast("computed by Lodestar and cannot be edited", "err")

    # --- Documents: tailor, check, audit, export, style
    def test_tailor_check_audit_export_and_style(self):
        jid = self.ids["saved"]
        self.open_job(jid)
        self.button("Check resume").click()  # nothing tailored yet
        self.expect_toast("no tailored resume yet", "err")
        self.act("Audit resume.docx")
        self.expect_toast("no resume.docx for this job yet", "err")
        self.button("Export PDF").click()
        self.expect_toast("no tailored resume yet", "err")
        self.act("Tailor resume (+docx)")
        d = self.folder(jid)
        self.assertTrue((d / "resume.md").is_file() and (d / "resume.docx").is_file())
        self.assertEqual(self.page.locator("#docTabs button", has_text="resume.md").count(), 1)
        self.assertIn("wrote", self.page.text_content("#jOut"))
        self.act("Check resume")
        self.assertIn("Resume check", self.page.text_content("#jCheck"))
        self.assertRegex(self.page.text_content("#jCheck"), r"score \d+/100")
        self.act("Audit resume.docx")
        self.assertIn("File audit: resume.docx", self.page.text_content("#jCheck"))
        opened = len(self.opened)
        self.act("Export PDF")  # no Word or LibreOffice here: a print page in the default browser
        self.expect_toast("opened a print page", "ok")
        self.assertEqual(self.opened[opened][0], "browser")
        self.assertTrue((d / "resume.html").is_file())
        self.assertIn("print page", self.page.text_content("#jOut"))
        styles = self.page.eval_on_selector_all("#jStyle option", "o => o.map(x => x.value)")
        pick = next(s for s in styles if s != self.page.input_value("#jStyle"))
        self.page.select_option("#jStyle", pick)
        self.idle()
        self.assertEqual(self.state()["prefs"]["resume_style"], pick)

    def test_tailor_by_bullet_accept_unflagged_and_build(self):
        jid = self.ids["applied"]
        self.open_job(jid)
        self.act("Tailor by bullet")
        box = self.page.locator("#jBullets details")
        self.assertIsNotNone(box.get_attribute("open"))
        self.assertIn("2 of 5 bullets rewritten, 1 flagged", box.locator("summary").text_content())
        self.assertIn("bullets.json", self.docs(jid))
        good, flagged = self.page.locator("#bul0"), self.page.locator("#bul1")  # rows follow the suggested order
        self.assertIn("dbt", box.locator("tbody tr").nth(0).locator("mark").text_content())
        self.assertIn("new number: 75 ", box.locator("tbody tr").nth(1).text_content())
        self.assertIn("flag", box.locator("tbody tr").nth(1).get_attribute("class"))
        self.assertFalse(flagged.is_checked())  # flagged rows start rejected
        good.uncheck()
        flagged.check()
        self.button("Accept all unflagged").click()
        self.assertTrue(good.is_checked())
        self.assertFalse(flagged.is_checked())
        self.act("Build resume")
        self.expect_toast("resume built: 1 rewrite(s)", "ok")
        text = (self.folder(jid) / "resume.md").read_text(encoding="utf-8")
        self.assertIn("Spark, Airflow and dbt", text)
        self.assertNotIn("75%", text)
        self.assertIn("40%", text)  # the rejected row kept its original

    def test_document_editor_edit_adjust_review(self):
        jid = self.ids["offer"]
        self.open_job(jid)
        self.act("Tailor resume (+docx)")
        md = self.folder(jid) / "resume.md"
        self.button("Edit document").click()  # the timeline tab is open
        self.expect_toast("pick a document tab first", "err")
        self.button("Review").click()
        self.expect_toast("open the resume tab first", "err")
        self.tab("resume.md")
        self.assertEqual(self.page.text_content("#docView"), md.read_text(encoding="utf-8"))
        self.button("Edit document").click()
        self.assertTrue(self.page.locator("#docEdit").is_visible())
        self.page.fill("#docEdit", self.page.input_value("#docEdit") + "\n- Mentored two junior engineers")
        self.run_click(self.button("Save document"))
        self.expect_toast("saved resume.md", "ok")
        self.assertIn("Mentored two junior engineers", md.read_text(encoding="utf-8"))
        self.assertTrue(any((self.folder(jid) / "history").glob("*resume*")))  # the replaced version is kept
        self.assertTrue(self.page.locator("#docEdit").is_hidden())
        self.button("Adjust").click()
        self.expect_toast("type an instruction first", "err")
        self.page.fill("#dAdj", "shorter, lead with Airflow")
        self.act("Adjust")
        self.expect_toast("adjusted; review, then Save document", "ok")
        self.assertEqual(self.page.input_value("#docEdit"), self.ai_text)  # in the editor only
        self.assertIn("Mentored two junior engineers", md.read_text(encoding="utf-8"))
        self.assertIn("shorter, lead with Airflow", str(self.ai_calls[-1]["messages"]))
        self.act("Review")  # reviews the editor's unsaved text
        self.assertEqual(self.page.text_content("#jOut"), self.ai_text)
        self.assertIn(self.ai_text, str(self.ai_calls[-1]["messages"]))

    def test_gap_cover_prep_research_checklist_and_council(self):
        jid = self.ids["accepted"]
        self.open_job(jid)
        self.act("Gap check (coverage + AI verdict)")
        self.assertIn("Verdict: good fit - skills match", self.page.text_content("#jOut"))
        self.assertIn("lead with Airflow", self.page.text_content("#jOut"))
        self.assertIn("gap.json", self.docs(jid))
        self.page.fill("#jTone", "warm, plain")
        self.page.fill("#jWords", "250")
        self.act("Cover letter (+docx)")
        d = self.folder(jid)
        self.assertTrue((d / "cover_letter.md").is_file() and (d / "cover_letter.docx").is_file())
        self.assertIn("warm, plain", str(self.ai_calls[-1]["messages"]))
        self.assertIn("250", str(self.ai_calls[-1]["messages"]))
        self.act("Interview prep")
        self.assertTrue((d / "interview_prep.md").is_file())
        self.act("Company research")
        self.assertTrue((d / "research.md").is_file())
        self.assertEqual(self.page.text_content("#jOut"), (d / "research.md").read_text(encoding="utf-8"))
        for name in ("cover_letter.md", "interview_prep.md", "research.md", "gap.json"):
            self.assertEqual(self.page.locator("#docTabs button", has_text=name).count(), 1, name)
        self.act("Checklist")
        self.assertRegex(self.page.text_content("#jOut"), r"\[[ x-]\] ")
        calls = len(self.ai_calls)
        self.page.check("#jCouncil")  # every configured provider answers, then one synthesis
        self.act("Interview prep")
        self.assertGreater(len(self.ai_calls) - calls, 1)

    def test_cover_options_use_this_opens_the_editor(self):
        jid = self.ids["rejected"]
        self.open_job(jid)
        self.act("Cover options")
        opts = self.page.locator("#jOpts .opt")
        self.assertEqual(opts.count(), 2)
        opts.nth(1).get_by_role("button", name="Use this").click()
        self.expect_toast("the letter is in the editor", "ok")
        letter = self.page.input_value("#docEdit")
        self.assertIn(AI["options"][1]["body"], letter)  # the chosen body, in the letter layout
        self.assertIn("Dear Recruiting team", letter)
        self.assertEqual(opts.count(), 0)
        self.page.fill("#docEdit", letter + "\nP.S. Available from January.")
        self.run_click(self.button("Save document"))
        saved = (self.folder(jid) / "cover_letter.md").read_text(encoding="utf-8")
        self.assertIn(AI["options"][1]["body"], saved)
        self.assertIn("P.S. Available from January.", saved)

    def test_tailor_from_a_saved_resume(self):
        jid = self.ids["withdrawn"]
        self.open_job(jid)
        opts = self.page.eval_on_selector_all("#jBase option", "o => o.map(x => x.textContent)")
        self.assertEqual(opts[0], "master profile")
        self.assertTrue(any(o.startswith("saved: alt-resume.md") for o in opts), opts)
        self.act("Tailor resume (+docx)")  # from the master profile
        self.assertNotIn("Flink fraud-scoring", str(self.ai_calls[-1]["messages"]))
        self.page.select_option("#jBase", index=1)
        self.act("Tailor resume (+docx)")
        self.assertIn("Flink fraud-scoring", str(self.ai_calls[-1]["messages"]))

    def test_story_prompt_for_what_the_posting_stresses(self):
        jid = self.api("/api/jobs", {"company": "Mentorly", "title": "Lead Data Engineer",
                                     "jd": "You will mentor engineers and collaborate closely with stakeholders. Python."})["id"]
        self.reload_state()
        self.open_job(jid)
        stress = self.api(f"/api/jobs/{jid}")["stress"]
        self.assertIn("leadership", stress["missing"])
        text = self.page.text_content("#drawer .group:has(h4:text('Interview rounds'))")
        self.assertIn("This posting stresses " + ", ".join(stress["stressed"]), text)
        self.assertIn("No story tagged " + ", ".join(stress["missing"]), text)
        self.button("Add a story").click()  # to Answers > Stories, the first missing competency ticked
        self.page.wait_for_selector("section#answers.on")
        self.assertEqual(self.page.eval_on_selector_all("#stComps input:checked", "c => c.map(x => x.value)"), [stress["missing"][0]])
        self.assertTrue(self.page.evaluate("document.activeElement.id === 'stTitle'"))
        self.assertFalse(self.page.locator("#drawer.open").count())

    # --- Interview rounds
    def test_interview_rounds_log_edit_delete(self):
        self.allow_console()
        jid = self.ids["interview"]
        self.open_job(jid)
        n = len(interview.rounds(jid))
        self.idle()  # the practice set (Interview readiness > Questions) loads after the drawer opens
        self.assertIn("You logged 2", self.page.text_content("#jQcounts"))
        self.page.click("#rForm summary")
        self.page.select_option("#r_kind", "onsite")
        self.page.fill("#r_at", "next tuesday-ish")  # bad: refused, nothing logged
        self.run_click(self.button("Save round"))
        self.expect_toast("error", "err")
        self.assertEqual(len(interview.rounds(jid)), n)
        self.page.fill("#r_at", day(5) + " 09:30")
        self.page.fill("#r_interviewers", "Priya Shah")
        self.page.fill("#r_questions_asked", "Design a CDC pipeline\nHow do you test dbt models?")
        self.page.fill("#r_notes", "Bring a laptop")
        self.run_click(self.button("Save round"))
        self.expect_toast("round logged", "ok")
        rounds = interview.rounds(jid)
        self.assertEqual(len(rounds), n + 1)
        r = rounds[-1]
        self.assertEqual((r["kind"], r["at"], r["interviewers"], r["notes"]), ("onsite", day(5) + " 09:30", "Priya Shah", "Bring a laptop"))
        self.assertIn("How do you test dbt models?", self.page.text_content("#drawer"))
        # edit round 2: the form fills in, the time field takes focus
        self.button("edit").nth(1).click()
        self.assertEqual(self.page.text_content("#rMode"), "editing round 2")
        self.assertTrue(self.page.evaluate("document.activeElement.id === 'r_at'"))
        self.assertEqual(self.page.input_value("#r_interviewers"), "Ravi Iyer, Lena Brooks")
        self.page.select_option("#r_outcome", "passed")
        self.run_click(self.button("Save round"))
        self.expect_toast("round saved", "ok")
        self.assertEqual(interview.rounds(jid)[1]["outcome"], "passed")
        self.assertEqual(len(interview.rounds(jid)), n + 1)
        # delete asks first
        self.button("delete").nth(n).click()
        self.assertIn(f"Delete round {r['round']}", self.dialogs[-1])
        self.idle()
        self.assertEqual(len(interview.rounds(jid)), n + 1)
        self.answer(True)
        self.run_click(self.button("delete").nth(n))
        self.expect_toast("round deleted", "ok")
        self.assertEqual(len(interview.rounds(jid)), n)

    # --- Offer and calendar
    def test_evaluate_offer_and_calendar_file(self):
        jid = self.ids["offer"]
        self.open_job(jid)
        for k, v in {"#oSal": "185000", "#oBon": "10%", "#oEq": "60k", "#oBen": "health, 401k", "#oDl": day(5),
                     "#oNotes": "flexible start"}.items():
            self.page.fill(k, v)
        self.act("Evaluate offer")
        self.assertTrue((self.folder(jid) / "offer.md").is_file())
        out = self.page.text_content("#jOut")
        self.assertIn(self.ai_text, out)
        self.assertIn("base: 185000 | bonus: 10% | equity: 60k", out)
        prompt = str(self.ai_calls[-1]["messages"])
        for v in ("185000", "60k", "flexible start"):
            self.assertIn(v, prompt)
        self.page.fill("#jWhen", "whenever suits")
        self.act("Calendar .ics")
        self.expect_toast("could not parse date", "err")
        self.page.fill("#jWhen", day(3) + " 14:00")
        self.page.fill("#jMin", "45")
        self.act("Calendar .ics")
        out = self.page.text_content("#jOut")
        self.assertTrue(out.startswith("wrote "), out)
        ics = Path(out[6:].strip()).read_text(encoding="utf-8")
        self.assertIn("DTSTART", ics)
        self.assertIn(day(3).replace("-", "") + "T1445", ics.replace(":", ""))  # 45 minutes long

    # --- Admin and the status move
    def test_admin_note_contact_jd_packet_move_and_delete(self):
        self.allow_console()
        jid = self.new_job("Pinecrest Labs")
        self.open_job(jid)
        self.button("note").click()
        self.expect_toast("type a note first", "err")
        self.page.fill("#jNote", "Called the recruiter")
        self.run_click(self.button("note"))
        self.expect_toast("note added", "ok")
        self.assertIn("Called the recruiter", db.get_job(jid)["notes"])
        self.assertIn("Called the recruiter", self.page.text_content("#docView"))  # the timeline
        self.page.fill("#jCe", "not-an-email")
        self.run_click(self.button("set contact"))
        self.expect_toast("not an email address", "err")
        self.assertIsNone(db.get_job(jid)["contact_email"])
        self.page.fill("#jCn", "Lee Wong")
        self.page.fill("#jCe", "lee.wong@pinecrest.example")
        self.run_click(self.button("set contact"))
        self.expect_toast("contact saved", "ok")
        self.assertEqual((db.get_job(jid)["contact_name"], db.get_job(jid)["contact_email"]), ("Lee Wong", "lee.wong@pinecrest.example"))
        self.assertIn(("Lee Wong", "recruiter"), [(p["name"], p["role"]) for p in self.api(f"/api/jobs/{jid}")["people"]])
        self.button("set JD").click()  # blank asks before clearing: dismissed
        self.assertIn("Clear the stored job description", self.dialogs[-1])
        self.idle()
        self.assertTrue(db.get_job(jid)["jd"])
        self.page.fill("#jJd", "Pinecrest Labs: Snowflake, dbt and Airflow. Hybrid in Portland.")
        self.run_click(self.button("set JD"))
        self.expect_toast("job description saved", "ok")
        self.assertIn("Snowflake", db.get_job(jid)["jd"])
        self.tab("description")
        self.assertIn("Snowflake", self.page.text_content("#docView"))
        self.answer(True)
        self.run_click(self.button("set JD"))
        self.expect_toast("job description cleared", "ok")
        self.assertFalse(db.get_job(jid)["jd"])
        self.act("export packet (zip)")
        out = self.page.text_content("#jOut")
        self.assertTrue(out.startswith("wrote ") and out.strip().endswith(".zip"), out)
        self.assertTrue(zipfile.is_zipfile(out[6:].strip()))
        # the head's status select + move: forward at once, backward asks
        self.page.select_option("#jStatus", "applied")
        self.run_click(self.button("move"))
        self.assertEqual(db.get_job(jid)["status"], "applied")
        self.page.select_option("#jStatus", "saved")
        self.run_click(self.button("move"))
        self.assertIn('back from "applied" to "saved"', self.dialogs[-1])
        self.assertEqual(db.get_job(jid)["status"], "applied")
        self.assertEqual(self.page.input_value("#jStatus"), "applied")  # reset after the cancelled move
        # delete asks; yes closes the drawer and removes the job everywhere
        self.button("delete job").click()
        self.idle()
        self.assertTrue(db.con().execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone())
        self.answer(True)
        self.run_click(self.button("delete job"))
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertIsNone(db.con().execute("SELECT 1 FROM jobs WHERE id=?", (jid,)).fetchone())
        self.assertEqual(self.page.locator(f'.card[data-id="{jid}"]').count(), 0)

    # --- focus, inert, Escape, Tab trap
    def test_focus_inert_escape_and_tab_trap(self):
        jid = self.ids["interview"]
        drawer = self.page.locator("#drawer")
        self.assertTrue(self.page.evaluate("document.querySelector('#drawer').inert"))
        self.go("board")  # pass 32: the page opens on Today
        self.page.focus(f'.card[data-id="{jid}"]')
        self.press("Enter")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=jid)
        self.idle()
        self.assertFalse(self.page.evaluate("document.querySelector('#drawer').inert"))
        self.assertEqual(drawer.get_attribute("aria-modal"), "true")
        self.assertEqual(drawer.get_attribute("aria-label"), "Job details")
        self.assertTrue(self.page.evaluate("document.activeElement.matches('#drawer .close')"))
        ends = "() => { const f = [...document.querySelectorAll('#drawer a[href], #drawer button:not([disabled]), #drawer input:not([disabled]):not([type=hidden]), #drawer select:not([disabled]), #drawer textarea:not([disabled]), #drawer summary, #drawer [tabindex=\"0\"]')].filter(x => x.offsetParent !== null); return f; }"
        self.page.evaluate(f"({ends})().at(-1).focus()")
        self.press("Tab")  # past the last: back to the first
        self.assertTrue(self.page.evaluate(f"document.activeElement === ({ends})()[0]"), self.focused())
        self.press("Shift+Tab")  # before the first: round to the last
        self.assertTrue(self.page.evaluate(f"document.activeElement === ({ends})().at(-1)"), self.focused())
        # typed but not saved: Escape asks first
        self.page.fill("#jNote", "half a thought")
        self.press("Escape")
        self.assertIn("discard what you typed", self.dialogs[-1])
        self.assertIn("open", drawer.get_attribute("class"))
        self.answer(True)
        self.press("Escape")
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertTrue(self.page.evaluate("document.querySelector('#drawer').inert"))
        self.assertIsNone(drawer.get_attribute("aria-modal"))
        self.assertTrue(self.page.evaluate(f"document.activeElement.matches('.card[data-id=\"{jid}\"]')"), self.focused())
        # the close button too, and a closed drawer takes no focus
        self.page.click(f'.card[data-id="{jid}"]')
        self.page.wait_for_selector("#drawer.open")
        self.button("Close job details").click()
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.page.evaluate("document.querySelector('#drawer .close').focus()")
        self.assertFalse(self.page.evaluate("document.activeElement.matches('#drawer *')"))

    def test_drawer_at_420px(self):
        self.set_viewport(420)
        self.open_job(self.ids["interview"])
        self.idle()
        self.page.wait_for_function("() => getComputedStyle(document.querySelector('#drawer')).transform === 'none'")
        self.assertEqual(self.overflow(), [])
        self.assertLessEqual(self.page.evaluate("document.querySelector('#drawer').getBoundingClientRect().width"), 420)


if __name__ == "__main__":
    unittest.main()
