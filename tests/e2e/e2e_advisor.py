"""AI advisor toolbar (pass 19): Recommend / Apply suggestions / Full AI / Undo AI changes on every tab header and
component card a scope covers; the suggestion cards (checkbox, current -> proposed diff, reason, impact / risk, the
guard's flags left unticked); Full AI's first-use confirm, never a send, a move or an Inbox item, and its undo; a card
whose field changed since turns stale; without a provider every AI control says so; Setup > Data lists the AI change
history with an Undo per batch; Inbox drafts and STAR stories round-trip; all of it at 420px. The AI is faked: each
test sets the reply (ask_json) it needs."""
import re
import unittest

from harness import E2ETestCase, FakeMail, ai, db, profile, resume

from lodestar import advisor

FULL = ["Recommend", "Apply suggestions", "Full AI", "Undo AI changes"]
XSS = '<img src=x onerror="window.__xss=1">'


class Advisor(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        saved = db.get_job(cls.ids["saved"])
        d = resume.app_dir(saved)
        resume.write_doc(d / "resume.md", resume._employer_copy(resume._source()))
        resume.write_doc(d / "cover_letter.md", resume.letter(saved, "I rebuild pipelines that teams trust.\n\nI would like to talk."))
        b = profile.load()
        b["summary"] = "Data engineer building batch and streaming pipelines."
        b["experience"] = [{"title": "Senior Data Engineer", "company": "Tidewater Logistics",
                            "bullets": ["Rebuilt the nightly freight ETL on Spark and Airflow"]}]
        profile.save(b)

    # --- helpers
    def reply(self, *items):
        """The next Recommend's AI reply: (field, proposed[, reason])."""
        type(self).ai_json = {"recommendations": [{"field": f, "proposed": p, "reason": (r or ["clearer"])[0],
                                                    "impact": "medium", "risk": "low"} for f, p, *r in items]}

    def field(self, scope, part, target=None):
        """The id of the scope's field whose label holds part, and its current value."""
        sc, t = advisor.check(scope, target)
        f, (_, v) = next((f, x) for f, x in sc.gather(t).items() if part in x[0])
        return f, v

    def bar(self, scope, target=None, within="main"):
        k = f"{scope}_{target or 0}"
        return (self.page.locator(f'{within} .aibar[data-adv="{k}"]').first, self.page.locator(f'{within} [data-advp="{k}"]').first)

    def press_ai(self, bar, name):
        self.run_click(bar.get_by_role("button", name=name, exact=True))

    def show(self, where, target=None):
        """Bring the toolbar's tab or drawer up: a tab name, 'drawer' (a job) or 'contact'."""
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
        return f"#{where}"

    # --- every scope has its toolbar, with the right buttons
    def test_every_tab_and_card_has_the_toolbar(self):
        j = self.ids
        cases = [("home", "today", None, ["Recommend"]), ("inbox", "inbox", None, FULL), ("inbox", "inbox", j["p_reply"], FULL),
                 ("contacts", "contacts", None, FULL), ("search", "searches", None, FULL[:2] + FULL[3:]),
                 ("monitor", "searches", None, FULL[:2] + FULL[3:]), ("answers", "answers", None, FULL),
                 ("answers", "stories", None, FULL), ("answers", "stories", j["story"], FULL), ("insights", "insights", None, ["Recommend"]),
                 ("profile", "profile", None, FULL), ("profile", "bank", None, FULL)]
        for tab, scope, target, buttons in cases:
            with self.subTest(scope=scope, target=target):
                self.go(tab)
                bar, _ = self.bar(scope, target, f"#{tab}")
                self.assertTrue(bar.is_visible())
                self.assertEqual(bar.locator("button").all_text_contents(), buttons)
                self.assertIn("AI for", bar.get_attribute("aria-label"))
        for where, scopes, target in (("drawer", ("job", "docs"), j["saved"]), ("contact", ("contacts",), j["c_maya"])):
            within = self.show(where, target)
            for scope in scopes:
                bar, _ = self.bar(scope, target, within)
                self.assertEqual(bar.locator("button").all_text_contents(), FULL, scope)
        # the import review's 'Apply selected' is a different button: no toolbar uses that name
        self.assertEqual(self.page.locator(".aibar button", has_text="Apply selected").count(), 0)

    def test_recommend_on_every_scope_shows_cards_with_a_diff(self):
        j = self.ids
        cases = [("profile", None, "profile", "Summary"), ("bank", None, "profile", "summary"), ("job", j["saved"], "drawer", "Your notes"),
                 ("docs", j["saved"], "drawer", "cover_letter"), ("answers", None, "answers", "Why do you want"),
                 ("stories", j["story"], "answers", "result"), ("contacts", j["c_maya"], "contact", "notes"),
                 ("searches", None, "monitor", "Saved search"), ("today", None, "home", "Advice"),
                 ("insights", None, "insights", "Advice"), ("inbox", j["p_reply"], "inbox", "body")]
        for scope, target, where, part in cases:
            with self.subTest(scope=scope):
                f, v = self.field(scope, part, target)
                advice = f in advisor.SCOPES[scope].advice
                mark = f"Edited by the advisor for {scope}"
                self.reply((f, mark if advice else (v.rstrip("\n") + "\n" + mark)))
                calls = len(self.ai_calls)
                within = self.show(where, target)
                bar, panel = self.bar(scope, target, within)
                self.press_ai(bar, "Recommend")
                self.assertEqual(len(self.ai_calls), calls + 1, "one AI call per Recommend")
                card = panel.locator(".advcard").first
                self.assertIn(mark, card.text_content())
                if advice:
                    self.assertEqual(card.locator("input[type=checkbox]").count(), 0)
                    self.assertIn("advice only", panel.text_content())
                else:
                    self.assertIn(mark, card.locator("pre.advdiff ins").last.text_content())
                    self.assertIn("current → proposed", card.text_content())
                self.assertIn("Nothing has changed yet" if not advice else "advice only", panel.locator(".advmsg").text_content())
                panel.get_by_role("button", name="Close suggestions").click()
                self.assertEqual(panel.locator(".advcard").count(), 0)

    # --- Apply suggestions and Undo AI changes, on profile.md
    def test_apply_suggestions_and_undo_round_trip_on_profile(self):
        before = profile.master_text()
        summary, v = self.field("profile", "Summary")
        skills, _ = self.field("profile", "Skills")
        new = "## Summary\nData engineer building batch and streaming pipelines for health and logistics teams for 7 years."
        self.reply((summary, new, "leads with the work"), (skills, "## Skills\nPython, SQL, Spark, Kubernetes", XSS))
        self.go("profile")
        bar, panel = self.bar("profile", None, "#profile")
        self.press_ai(bar, "Recommend")
        cards = panel.locator(".advcard")
        self.assertEqual(cards.count(), 2)
        self.assertTrue(cards.nth(0).locator("input[type=checkbox]").is_checked())
        self.assertIn("leads with the work", cards.nth(0).text_content())
        self.assertIn("- Data engineer with 7 years", cards.nth(0).locator("pre.advdiff del").text_content())
        flagged = cards.nth(1)  # an invented skill: flagged, high risk, left unticked; the reason is text, never markup
        self.assertIn("flag", flagged.get_attribute("class"))
        self.assertFalse(flagged.locator("input[type=checkbox]").is_checked())
        self.assertIn("risk high", flagged.text_content())
        self.assertIn("Apply refuses this one", flagged.text_content())
        self.assertIn(XSS, flagged.text_content())
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.press_ai(bar, "Apply suggestions")
        self.assertIn("applied", cards.nth(0).locator(".pill").text_content())
        self.assertIn("Applied 1 change(s)", panel.locator(".advmsg").text_content())
        self.assertIn(new, profile.master_text())
        self.page.wait_for_function("t => $('#pText').value.includes(t)", arg=new.split("\n")[1])  # the editor shows it
        # ticking the flagged one anyway: the guard still refuses it at Apply
        flagged.locator("input[type=checkbox]").check()
        self.press_ai(bar, "Apply suggestions")
        self.assertIn("not applied", flagged.locator(".pill").text_content())
        self.assertIn("blocked", flagged.text_content())
        self.assertNotIn("Kubernetes", profile.master_text())
        self.press_ai(bar, "Undo AI changes")
        self.assertIn("Undid 1 change(s)", panel.locator(".advmsg").text_content())
        self.assertEqual(profile.master_text(), before)  # byte for byte
        self.page.wait_for_function("t => $('#pText').value.includes(t)", arg=v.split("\n")[1])

    # --- Full AI: the first-use confirm, never a send / move / Inbox item, and Undo
    def test_full_ai_confirms_first_never_sends_and_undoes(self):
        jid = self.ids["saved"]
        job = db.get_job(jid)
        self.reply(("tags", "python, spark, data platform"), ("next_action", "Ask Riley Gomez for a referral"))
        pending, sent = len(db.list_pending("pending")), len(FakeMail.SENT)
        self.open_job(jid)
        bar, panel = self.bar("job", jid, "#drawer")
        calls = len(self.ai_calls)
        self.answer(False)  # declined: nothing runs
        bar.get_by_role("button", name="Full AI", exact=True).click()
        self.idle()
        self.assertIn("never sends mail", self.dialogs[-1])
        self.assertIn("Undo AI changes", self.dialogs[-1])
        self.assertEqual(len(self.ai_calls), calls)
        self.answer(True)
        self.press_ai(bar, "Full AI")
        after = db.get_job(jid)
        self.assertIn("data platform", after["tags"])
        self.assertEqual(after["next_action"], "Ask Riley Gomez for a referral")
        self.assertEqual(after["status"], job["status"])  # never moves the job
        self.assertEqual(len(db.list_pending("pending")), pending)  # never proposes
        self.assertEqual(len(FakeMail.SENT), sent)  # never sends
        self.assertIn("Full AI made 2 change(s)", panel.locator(".advmsg").text_content())
        self.assertEqual(self.page.input_value("#d_next_action"), "Ask Riley Gomez for a referral")  # the drawer shows it
        self.assertEqual(panel.locator(".pill", has_text="applied").count(), 2)
        n = len(self.dialogs)  # asked once: the second Full AI goes straight on (nothing left to change this time)
        self.reply()
        self.press_ai(bar, "Full AI")
        self.assertEqual(len(self.dialogs), n)
        self.press_ai(bar, "Undo AI changes")
        back = db.get_job(jid)
        self.assertEqual((back["tags"], back["next_action"]), (job["tags"], job["next_action"]))
        self.assertEqual(self.page.input_value("#d_next_action"), job["next_action"])

    # --- a card whose field changed since: stale, never written
    def test_a_changed_field_turns_its_card_stale(self):
        f, _ = self.field("answers", "Why do you want")
        self.reply((f, "Your data platform serves patients directly, and I want to work on that impact."))
        self.go("answers")
        bar, panel = self.bar("answers", None, "#answers")
        self.press_ai(bar, "Recommend")
        mine = "I want to build the pipelines your clinicians rely on."
        db.con().execute("UPDATE answers SET answer=? WHERE id=?", (mine, int(f[1:])))  # edited elsewhere meanwhile
        db.con().commit()
        self.press_ai(bar, "Apply suggestions")
        card = panel.locator(".advcard").first
        self.assertIn("stale", card.locator(".pill").text_content())
        self.assertIn("changed since", card.text_content())
        self.assertEqual(db.con().execute("SELECT answer FROM answers WHERE id=?", (int(f[1:]),)).fetchone()[0], mine)

    # --- no provider: every AI control says so
    def test_without_a_provider_every_ai_control_says_so(self):
        real = ai.available
        ai.available = lambda: []
        self.allow_console()  # the API's 400 for the no-provider run below
        try:
            self.reload_state()
            calls = len(self.ai_calls)
            self.go("profile")
            bar, panel = self.bar("profile", None, "#profile")
            self.assertIn("needs an AI provider", bar.get_by_role("button", name="Recommend").get_attribute("title"))
            for name in ("Recommend", "Full AI"):
                bar.get_by_role("button", name=name, exact=True).click()
                self.assertIn("needs an AI provider", panel.locator(".advmsg").text_content())
                self.assertIn("Ollama", panel.locator(".advmsg").text_content())
            bar.get_by_role("button", name="Apply suggestions").click()
            self.assertIn("Click Recommend first", panel.locator(".advmsg").text_content())
            self.assertEqual(self.dialogs, [])  # Full AI's confirm never came up
            r = self.api("/api/run/advise", {"scope": "profile"})
            self.assertIn("AI provider", r["error"])
            self.assertEqual(len(self.ai_calls), calls)
        finally:
            ai.available = real
            self.reload_state()

    # --- Setup > Data: the AI change history, with an Undo per batch
    def test_setup_data_lists_the_history_and_undoes_a_batch(self):
        cid = self.ids["c_maya"]
        f, _ = self.field("contacts", "position", cid)
        self.reply((f, "Senior Technical Recruiter"))
        within = self.show("contact", cid)
        bar, panel = self.bar("contacts", cid, within)
        self.press_ai(bar, "Recommend")
        self.press_ai(bar, "Apply suggestions")
        self.assertEqual(db.con().execute("SELECT position FROM contacts WHERE id=?", (cid,)).fetchone()[0], "Senior Technical Recruiter")
        self.assertEqual(self.page.input_value("#c_position"), "Senior Technical Recruiter")  # the drawer shows it
        self.go("setup")
        batch = self.page.locator("#aiHist details.aihist").first
        self.assertIn("Apply suggestions", batch.locator("summary").text_content())
        self.assertIn("contacts", batch.locator("summary").text_content())
        batch.locator("summary").click()
        self.assertIn("Maya Chen: position", batch.text_content())
        self.assertIn("+ Senior Technical Recruiter", batch.locator("pre.advdiff ins").text_content())
        self.run_click(batch.get_by_role("button", name="Undo this batch"))
        self.assertEqual(db.con().execute("SELECT position FROM contacts WHERE id=?", (cid,)).fetchone()[0], "Technical Recruiter")
        self.assertIn("undone", self.page.locator("#aiHist details.aihist").first.locator("summary").text_content())
        self.assertEqual(self.page.locator("#aiHist details.aihist").first.get_by_role("button", name="Undo this batch").count(), 0)

    # --- Inbox drafts and STAR stories: per-card toolbars round-trip
    def test_inbox_draft_and_story_cards_apply_and_undo(self):
        pid, sid = self.ids["p_reply"], self.ids["story"]
        f, v = self.field("inbox", "body", pid)
        body = "Hi Maya, Thursday 14:00 or Friday 10:00 both work for me. Best, Pat"
        self.reply((f, body))
        self.go("inbox")
        bar, panel = self.bar("inbox", pid, "#inbox")
        self.press_ai(bar, "Recommend")
        self.press_ai(bar, "Apply suggestions")
        self.assertEqual(self.page.input_value(f"#body{pid}"), body)
        row = db.get_pending(pid)
        self.assertEqual(row["status"], "pending")  # still waits for your approval
        self.press_ai(self.bar("inbox", pid, "#inbox")[0], "Undo AI changes")
        self.assertEqual(self.page.input_value(f"#body{pid}"), v)
        f, v = self.field("stories", "result", sid)
        self.reply((f, "40% lower spend with the same report latency"))
        self.go("answers")
        bar, panel = self.bar("stories", sid, "#storyList")
        self.press_ai(bar, "Recommend")
        self.press_ai(bar, "Apply suggestions")
        self.assertIn("applied", panel.locator(".pill").text_content())
        self.assertIn("40% lower spend with the same report latency", self.page.text_content("#storyList"))
        self.press_ai(self.bar("stories", sid, "#storyList")[0], "Undo AI changes")
        self.assertEqual(next(s for s in self.state()["stories"] if s["id"] == sid)["result"], v)

    # --- typed, unsaved text survives an AI change: the job drawer is not re-rendered over it, and the Profile editor's
    # message says how Save gets going again (Undo AI changes)
    def test_unsaved_text_survives_an_ai_change(self):
        jid = self.ids["saved"]
        job = db.get_job(jid)
        self.reply(("next_action", "Email the hiring manager on Monday"))
        self.open_job(jid)
        bar, panel = self.bar("job", jid, "#drawer")
        self.press_ai(bar, "Recommend")
        self.page.evaluate("$('#rForm').open = true")
        self.page.fill("#r_notes", "UNSAVED ROUND NOTE")
        self.press_ai(bar, "Apply suggestions")
        self.assertEqual(db.get_job(jid)["next_action"], "Email the hiring manager on Monday")
        self.expect_toast("drawer keeps your unsaved text", "err")
        self.assertEqual(self.page.input_value("#r_notes"), "UNSAVED ROUND NOTE")
        self.press_ai(bar, "Undo AI changes")
        self.assertEqual(db.get_job(jid)["next_action"], job["next_action"])
        self.assertEqual(self.page.input_value("#r_notes"), "UNSAVED ROUND NOTE")
        self.page.fill("#r_notes", "")
        self.page.evaluate("closeDrawer()")
        before = profile.master_text()
        summary, _ = self.field("profile", "Summary")
        self.reply((summary, "## Summary\nData engineer building batch and streaming pipelines for health and logistics teams for 7 years."))
        self.go("profile")
        self.page.fill("#pText", before + "\nMY UNSAVED EDIT\n")
        bar, panel = self.bar("profile", None, "#profile")
        self.press_ai(bar, "Recommend")
        self.press_ai(bar, "Apply suggestions")
        self.expect_toast("Save is refused until the editor matches the file", "err")
        self.assertIn("MY UNSAVED EDIT", self.page.input_value("#pText"))
        self.allow_console()  # the 409 below
        self.page.click("button[onclick=\"saveProfile()\"]")
        self.expect_toast("an import or an AI change wrote it", "err")
        self.press_ai(bar, "Undo AI changes")
        self.assertEqual(profile.master_text(), before)
        self.page.click("button[onclick=\"saveProfile()\"]")
        self.expect_toast("profile saved", "ok")
        self.assertIn("MY UNSAVED EDIT", profile.master_text())
        profile.write_master(before)
        self.page.evaluate("loadProfile()")

    # --- narrow window
    def test_narrow_window_420(self):
        self.set_viewport(420)
        self.settle()
        f, v = self.field("profile", "Experience")
        self.reply((f, v.rstrip("\n") + "\n- " + "Rebuilt " * 40 + re.sub(r"\s", "", "averylongunbrokenwordthatmustwrap" * 4)))
        self.go("profile")
        bar, panel = self.bar("profile", None, "#profile")
        self.press_ai(bar, "Recommend")
        self.assertEqual(panel.locator(".advcard").count(), 1)
        self.assertEqual(self.overflow(), [])
        self.open_job(self.ids["saved"])
        self.assertTrue(self.bar("job", self.ids["saved"], "#drawer")[0].is_visible())
        self.assertEqual(self.overflow(), [])
        self.page.evaluate("closeDrawer()")
        self.go("setup")
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
