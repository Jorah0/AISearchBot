"""Today: the agenda (next actions, deadlines, interviews, follow-ups, contacts due, Inbox) and Suggested emails."""
import unittest
from datetime import datetime, timedelta

from harness import FLOOR, E2ETestCase, contacts, db, day, interview

OPTIONS = {"options": [
    {"label": "Warm and brief", "tone": "warm", "subject": "A quick favour", "recommended": True, "why": "short and friendly",
     "body": "Hi, I am applying for the Senior Data Engineer role. Would you be open to referring me? Best, Pat"},
    {"label": "More formal", "tone": "formal", "subject": "Referral request", "recommended": False, "why": "",
     "body": "Dear Riley, I would be grateful for a referral for the Senior Data Engineer opening. Kind regards, Pat"},
    {"label": "Names my number", "tone": "direct", "subject": "Referral and pay", "recommended": False, "why": "",
     "body": f"Hi, could you refer me? For context my floor is {FLOOR} base. Best, Pat"}]}


class Today(E2ETestCase):
    ai_json = OPTIONS

    @classmethod
    def seed(cls):
        super().seed()
        j = cls.ids
        db.set_fields(j["saved"], next_action_at=day(-1))  # overdue next action
        db.set_fields(j["screening"], deadline=day(1))  # deadline tomorrow
        soon = (datetime.now() + timedelta(hours=26)).strftime("%Y-%m-%d %H:%M")
        j["soon"] = soon
        interview.log_round(j["interview"], kind="final", at=soon, interviewers="Ana Ruiz")  # within 48 hours
        # referral suggestions: someone you know at a saved job's company, with an address
        contacts.add(name="Riley Gomez", email="riley.gomez@northwind.example", company="Northwind Analytics", position="Data Lead")
        j["kestrel"] = db.add_job("Kestrel Maps", "Data Engineer", "https://jobs.example.com/kestrel/de", "Python and Spark.", "seed")
        contacts.add(name="Jo Park", email="jo.park@kestrelmaps.example", company="Kestrel Maps", position="Engineer")
        # Cobalt has been quiet past followup_days: a follow-up item and a suggested follow-up email
        db.con().execute("UPDATE events SET ts=datetime('now','-10 days') WHERE job_id=?", (j["screening"],))
        db.con().commit()

    def suggestion(self, job_id, kind):
        """The Suggested emails row for (job, kind), as a locator, and its index in S.today.emails."""
        emails = self.page.evaluate("S.today.emails")
        i = next(k for k, s in enumerate(emails) if s["job_id"] == job_id and s["kind"] == kind)
        return self.page.locator("#today h4 ~ .row").nth(i), emails[i]

    def test_agenda_lists_what_is_due_and_opens_it(self):
        j, today = self.ids, self.page.locator("#today")
        self.assertTrue(today.is_visible())
        expect = {  # label part -> the job it opens
            "overdue " + day(-1) + ": Tailor resume": j["saved"],
            "deadline in 1d": j["screening"],
            "interview " + datetime.strptime(j["soon"], "%Y-%m-%d %H:%M").strftime("%a %Y-%m-%d %H:%M"): j["interview"],
            "follow up · #%d Cobalt Freight" % j["screening"]: j["screening"],
        }
        for label, jid in expect.items():
            btn = today.locator("button", has_text=label)
            self.assertEqual(btn.count(), 1, label)
            btn.click()
            self.page.wait_for_function("id => cur && cur.job.id === id", arg=jid)
            self.idle()
            self.press("Escape")
            self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertIn("due", today.locator("button", has_text="overdue").get_attribute("class"))
        # a contact whose next touch has come opens their contact drawer
        today.locator("button", has_text="get in touch (due " + day(0) + ") · Sam Okafor (Bluefin Labs)").click()
        self.page.wait_for_function("id => CT && CT.contact.id === id", arg=j["c_sam"])
        self.assertEqual(self.page.get_attribute("#drawer", "aria-label"), "Contact details")
        self.press("Escape")
        # the Inbox count, and the button goes there
        n = len(self.state()["pending"])
        today.locator("button", has_text=f"{n} waiting in the Inbox").click()
        self.page.wait_for_selector("section#inbox.on")
        self.assertEqual(self.page.locator("#inboxList .item").count(), n)

    def test_agenda_item_opens_from_the_keyboard(self):
        btn = self.page.locator("#today button", has_text="deadline in 1d")
        btn.focus()
        self.press("Enter")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=self.ids["screening"])
        self.assertTrue(self.page.evaluate("document.activeElement.matches('#drawer .close')"))
        self.press("Escape")
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertTrue(self.page.evaluate("document.activeElement.textContent.includes('deadline in 1d')"), self.focused())

    def test_draft_options_then_use_proposes_a_reviewed_email(self):
        jid = self.ids["saved"]
        row, s = self.suggestion(jid, "referral")
        self.assertEqual(s["to"], "riley.gomez@northwind.example")
        self.assertIn("you know Riley Gomez at Northwind Analytics", row.text_content())
        pending, calls = {p["id"] for p in self.state()["pending"]}, len(self.ai_calls)
        self.run_click(row.locator("button", has_text="Draft options"))
        self.assertEqual(self.page.evaluate("cur.job.id"), jid)  # the job's drawer, options under Communicate
        opts = self.page.locator("#jOpts .opt")
        self.assertEqual(opts.count(), 2)
        self.assertIn("recommended", opts.nth(0).text_content())
        self.assertIn("A quick favour", opts.nth(0).text_content())
        self.assertEqual(len(self.ai_calls), calls + 1)  # one AI call made the options
        self.run_click(opts.nth(0).locator("button", has_text="Use this"))
        new = [p for p in self.state()["pending"] if p["id"] not in pending]
        self.assertEqual(len(new), 1)
        p = new[0]
        self.assertEqual((p["kind"], p["job_id"], p["payload"]["to"]), ("send_email", jid, "riley.gomez@northwind.example"))
        self.assertEqual(p["payload"]["subject"], "A quick favour")
        self.assertIn("-> pending (inbox #%d)" % p["id"], self.page.text_content("#jOut"))
        self.assertIn("referrer", [r["role"] for r in self.api(f"/api/jobs/{jid}")["people"] if r["name"] == "Riley Gomez"])
        self.assertFalse(any(e["job_id"] == jid for e in self.page.evaluate("S.today.emails")))  # waiting in the Inbox now

    def test_an_option_naming_the_salary_floor_is_never_offered(self):
        jid = self.ids["kestrel"]
        row, _ = self.suggestion(jid, "referral")
        pending = len(self.state()["pending"])
        self.run_click(row.locator("button", has_text="Draft options"))
        opts = self.page.locator("#jOpts .opt")
        self.assertEqual(opts.count(), 2)  # the AI offered 3; the one with the private floor is dropped
        self.assertNotIn(FLOOR, self.page.text_content("#jOpts"))
        self.assertNotIn("165", self.page.text_content("#jOpts"))
        self.assertEqual(len(self.state()["pending"]), pending)  # options alone propose nothing
        self.page.locator("#jOpts button", has_text="close options").click()
        self.assertEqual(opts.count(), 0)

    def test_dismiss_for_now_snoozes_the_suggestion(self):
        jid = self.ids["screening"]
        row, s = self.suggestion(jid, "followup")
        self.assertIn("quiet since", row.text_content())
        self.run_click(row.locator("button", has_text="Dismiss for now"))
        self.expect_toast("dismissed for 3 days", "ok")
        self.assertFalse(any(e["job_id"] == jid and e["kind"] == "followup" for e in self.state()["today"]["emails"]))
        self.assertTrue(db.con().execute("SELECT 1 FROM seen WHERE key=?", (f"suggest:{jid}:followup",)).fetchone())
        self.page.reload()
        self.page.wait_for_function("() => S !== null")
        self.assertNotIn("quiet since", self.page.text_content("#today"))

    def test_today_at_420px(self):
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
