"""Mail page (pass 33): every filed mail sorted by type with counts, one opened in full (headers, sender check, the
classifier's summary / next step / date, the whole text, attachments), and a reply composer: your own text sent for
review, the AI's improvements to your text, or AI-written replies (one recommended) used as is or edited first.
Nothing is sent from the page: every reply lands in the Inbox as a pending email."""
import unittest

from harness import FLOOR, E2ETestCase, db

LONG = ("Hi Pat,\n\nThanks for your time on the phone. We would love to have you meet the team for a technical "
        "interview.\n\n" + "Here is what to expect during the session. " * 40 + "\n\nBest,\nMaya")
OPTIONS = {"options": [
    {"label": "Accept, two slots", "tone": "warm", "subject": "Re: Technical interview availability", "recommended": True,
     "why": "answers the ask directly", "body": "Hi Maya, Thursday 14:00 or Friday 10:00 both work for me. Best, Pat"},
    {"label": "Short", "tone": "direct", "subject": "Re: Technical interview availability", "recommended": False, "why": "",
     "body": "Hi Maya, Thursday 14:00 works. Best, Pat"},
    {"label": "Names my number", "tone": "direct", "subject": "Re: pay", "recommended": False, "why": "",
     "body": f"Hi Maya, before we meet: my floor is {FLOOR}. Best, Pat"}],
    "subject": "Re: Technical interview availability", "body": "Hi Maya, Thursday 14:00 works well for me. Best regards, Pat"}


class Mail(E2ETestCase):
    ai_json = OPTIONS

    @classmethod
    def seed(cls):
        super().seed()
        db.con().execute("UPDATE mail SET body=?, action=?, deadline=? WHERE message_id=?",
                         (LONG, "Reply with two times this week", "2026-11-20", "<orchid-1@orchidhealth.example>"))
        db.add_mail(message_id="<evil-1@example.net>", direction="in", from_addr="x@evil.example", category="other",
                    subject="<img src=x onerror=alert(1)> hello", snippet="<script>alert(2)</script> text",
                    body="<script>alert(2)</script> text")
        db.con().commit()
        cls.ids["orchid_mail"] = db.con().execute("SELECT id FROM mail WHERE message_id='<orchid-1@orchidhealth.example>'").fetchone()["id"]

    def open_mail(self, subject):
        self.go("mail")
        self.page.locator(".mvrow", has_text=subject).click()
        self.idle()
        return self.page.locator("#mvRead")

    def test_types_counts_search_and_full_text(self):
        self.go("mail")
        types = self.page.locator("#mvTypes button")
        labels = types.all_text_contents()
        for want in ("All", "Interview", "Recruiter", "Sent", "Not filed under a job"):
            self.assertTrue(any(t.startswith(want) for t in labels), (want, labels))
        self.page.locator("#mvTypes button", has_text="Sent").click()
        rows = self.page.locator(".mvrow")
        self.assertEqual(rows.count(), 1)
        self.assertIn("Application: Analytics Engineer", rows.first.text_content())
        self.page.locator("#mvTypes button", has_text="All").click()
        self.page.fill("#mvQ", "zephyr")
        self.assertEqual(self.page.locator(".mvrow").count(), 1)
        self.page.fill("#mvQ", "")
        read = self.open_mail("Technical interview availability")
        text = read.text_content()
        for want in ("verified sender", "Orchid Health", "Asks for two slots this week", "Reply with two times this week",
                     "2026-11-20", "Here is what to expect during the session.", "Best,", "interview-agenda.pdf"):
            self.assertIn(want, text)
        self.assertEqual(read.locator(".mvbody").text_content(), LONG)  # the whole text, not a snippet

    def test_mail_text_is_shown_as_text(self):
        read = self.open_mail("hello")
        self.assertIn("<script>alert(2)</script>", read.locator(".mvbody").text_content())
        self.assertEqual(self.page.locator("#mvRead script, #mvRead img").count(), 0)
        self.assertIn("File this mail under a job first", read.text_content())  # unmatched: link before replying

    def test_own_reply_goes_to_the_inbox_for_review(self):
        before = len(self.api("/api/state")["pending"])
        read = self.open_mail("Technical interview availability")
        read.locator("#mvBody").fill("Hi Maya, Thursday at 14:00 works for me. Best, Pat")
        self.run_click(read.get_by_role("button", name="Send for review"))
        pend = self.api("/api/state")["pending"]
        self.assertEqual(len(pend), before + 1)
        p = pend[0]["payload"] if "Thursday at 14:00" in pend[0]["payload"]["body"] else next(
            x["payload"] for x in pend if "Thursday at 14:00" in x["payload"]["body"])
        self.assertEqual(p["to"], "maya.chen@orchidhealth.example")  # the recipient comes from the server

    def test_ai_writes_replies_and_improves_your_text(self):
        read = self.open_mail("Technical interview availability")
        self.run_click(read.get_by_role("button", name="AI: write replies"))
        opts = read.locator("#mvOpts .opt")
        self.assertEqual(opts.count(), 2)  # the option naming the salary floor is never offered
        self.assertIn("recommended", opts.first.text_content())
        opts.first.get_by_role("button", name="Edit first").click()
        self.assertIn("Thursday 14:00 or Friday 10:00", read.locator("#mvBody").input_value())
        self.run_click(read.get_by_role("button", name="shorter"))
        self.assertEqual(read.locator("#mvBody").input_value(), OPTIONS["body"])
        before = len(self.api("/api/state")["pending"])
        self.run_click(read.get_by_role("button", name="AI: write replies"))
        self.run_click(read.locator("#mvOpts .opt").first.get_by_role("button", name="Use this"))
        self.assertEqual(len(self.api("/api/state")["pending"]), before + 1)

    def test_drawer_mail_opens_in_the_mail_page_and_420px(self):
        self.open_job(self.ids["interview"])
        self.page.locator("#drawer button", has_text="Read in Mail").first.click()
        self.page.wait_for_selector("section#mail.on")
        self.idle()
        self.assertIn("Technical interview availability", self.page.locator("#mvRead h3").text_content())
        self.set_viewport(420)
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
