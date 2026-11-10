"""The job drawer's people and mail: People (link with role, unlink, Ask for referral, options, open a contact), Mail
(trusted / unverified pills, attachments, Show in folder, Reply with options, Unlink, outbound mail) and Communicate
(reply, outreach, follow-up, thank-you, withdrawal, plain template, Options by kind)."""
import unittest
from pathlib import Path

from harness import E2ETestCase, db

AI = {"options": [
    {"label": "Two slots", "tone": "brief", "subject": "Re: Technical interview availability", "recommended": True,
     "why": "answers the question asked", "body": "Hi Maya, Thursday 14:00 or Friday 10:00 both work for me. Best, Pat"},
    {"label": "Warm", "tone": "warm", "subject": "Re: availability", "recommended": False, "why": "",
     "body": "Hi Maya, thanks for reaching out! Thursday afternoon works well. Best, Pat"}],
    "subject": "Following up", "body": "Hi, a short note to follow up. Best, Pat", "score": 80, "verdict": "good fit",
    "why": "skills match", "category": "other", "summary": "fake"}


class DrawerComms(E2ETestCase):
    ai_json = AI

    def button(self, name, scope="#drawer"):
        return self.page.locator(scope).get_by_role("button", name=name, exact=True)

    def new_pending(self, before):
        return [p for p in self.state()["pending"] if p["id"] not in before]

    def pending_ids(self):
        return {p["id"] for p in self.state()["pending"]}

    # --- People
    def test_people_unlink_link_with_role_referral_and_contact(self):
        jid, dev = self.ids["offer"], self.ids["c_dev"]
        self.open_job(jid)
        row = self.page.locator("#drawer .group", has_text="People").locator(".row", has_text="Dev Patel")
        self.assertIn("hiring manager", row.text_content())
        self.assertIn("dev.patel@juniperrobotics.example", row.text_content())
        self.run_click(row.get_by_role("button", name="unlink"))
        self.expect_toast("unlinked", "ok")
        self.assertEqual(self.api(f"/api/jobs/{jid}")["people"], [])
        self.assertIn("nobody linked to this job yet", self.page.text_content("#drawer"))
        # still someone you know there: link again, as a referrer
        self.assertIn("you know 1 person here", self.page.text_content("#drawer"))
        self.page.select_option(f"#jRole{dev}", "referrer")
        self.run_click(self.page.locator("#drawer .row", has_text="Dev Patel").get_by_role("button", name="link"))
        self.expect_toast("linked", "ok")
        self.assertEqual([(p["name"], p["role"]) for p in self.api(f"/api/jobs/{jid}")["people"]], [("Dev Patel", "referrer")])
        # ask for a referral: an email to their address, always reviewed in the Inbox
        before = self.pending_ids()
        self.run_click(self.page.locator("#drawer .row", has_text="Dev Patel").get_by_role("button", name="Ask for referral"))
        new = self.new_pending(before)
        self.assertEqual([(p["kind"], p["payload"]["to"], p["job_id"]) for p in new],
                         [("send_email", "dev.patel@juniperrobotics.example", jid)])
        self.assertIn(f"inbox #{new[0]['id']}", self.page.text_content("#jOut"))
        self.run_click(self.page.locator("#drawer .row", has_text="Dev Patel").get_by_role("button", name="options"))
        self.assertEqual(self.page.locator("#jOpts .opt").count(), 2)
        # the name opens their contact drawer
        self.page.locator("#drawer a", has_text="Dev Patel").click()
        self.page.wait_for_function("id => CT && CT.contact.id === id", arg=dev)
        self.assertEqual(self.page.get_attribute("#drawer", "aria-label"), "Contact details")

    # --- Mail
    def test_trusted_mail_with_attachment_folder_and_reply_options(self):
        jid = self.ids["interview"]
        self.open_job(jid)
        mail = self.page.locator("#drawer .group", has_text="Mail").locator(".item").first
        head = mail.locator(".hd").text_content()
        for want in ("Maya Chen <maya.chen@orchidhealth.example>", "interview", "trusted", "linked by auto"):
            self.assertIn(want, head)
        self.assertEqual(mail.locator(".pill.ok").text_content(), "trusted")
        mail.locator("summary").click()
        self.assertIn("Asks for two slots this week", mail.text_content())
        self.assertIn("Could you share two times?", mail.locator("pre").text_content())
        self.assertEqual(mail.locator(".pill", has_text="interview-agenda.pdf").text_content(), "interview-agenda.pdf · 1 KB")
        self.assertEqual(self.button("Unlink", scope="#drawer .group:has(h4:text('Mail'))").count(), 0)  # auto-filed
        opened = len(self.opened)
        self.run_click(mail.get_by_role("button", name="Show in folder"))
        kind, path = self.opened[opened]
        self.assertEqual(kind, "folder")
        self.assertEqual(Path(path).name, "mail")
        self.assertTrue(any(Path(path).rglob("interview-agenda.pdf")))
        before = self.pending_ids()
        self.run_click(mail.get_by_role("button", name="Reply with options"))
        opts = self.page.locator("#jOpts .opt")
        self.assertEqual(opts.count(), 2)
        self.assertIn("recommended", opts.nth(0).text_content())
        self.run_click(opts.nth(0).get_by_role("button", name="Use this"))
        new = self.new_pending(before)
        self.assertEqual(len(new), 1)
        p = new[0]["payload"]
        self.assertEqual((p["to"], p["in_reply_to"], p["subject"]),
                         ("maya.chen@orchidhealth.example", "<orchid-1@orchidhealth.example>", AI["options"][0]["subject"]))
        self.assertFalse(p.get("unverified"))

    def test_mail_you_linked_is_unverified_and_can_be_unlinked(self):
        jid = self.ids["saved"]
        zephyr = next(m["id"] for m in self.state()["mail_unmatched"] if "Zephyr" in m["subject"])
        self.assertTrue(self.api(f"/api/mail/{zephyr}/link", {"job_id": jid})["ok"])
        self.reload_state()
        self.open_job(jid)
        mail = self.page.locator(f"#drawer #mail{zephyr}")
        self.assertEqual(mail.locator(".pill.warn").text_content(), "unverified")
        self.assertIn("linked by user", mail.text_content())
        self.assertEqual(db.get_job(jid)["contact_email"], "recruiting@northwindanalytics.example")  # linking never sets it
        self.run_click(mail.get_by_role("button", name="Unlink"))
        self.expect_toast(f"mail #{zephyr}: unlink done", "ok")
        self.assertEqual(self.page.locator(f"#drawer #mail{zephyr}").count(), 0)
        self.assertIn(zephyr, [m["id"] for m in self.state()["mail_unmatched"]])

    def test_outbound_mail_shows_recipient_without_reply(self):
        self.open_job(self.ids["applied"])
        mail = self.page.locator("#drawer .group", has_text="Mail").locator(".item").first
        self.assertIn("→ to recruiting@bluefinlabs.example", mail.locator(".hd b").text_content())
        self.assertEqual(mail.locator(".pill").count(), 0)  # trust is about mail you receive
        self.assertEqual(mail.get_by_role("button", name="Reply with options").count(), 0)

    # --- Communicate
    def test_communicate_drafts_go_to_the_inbox(self):
        jid = self.ids["screening"]
        self.open_job(jid)
        to = "recruiting@cobaltfreight.example"

        def drafted(click, **expect):
            before, calls = self.pending_ids(), len(self.ai_calls)
            click()
            new = self.new_pending(before)
            self.assertEqual(len(new), 1, expect)
            p = new[0]
            self.assertEqual((p["kind"], p["job_id"], p["payload"]["to"]), ("send_email", jid, to))
            self.assertIn(f"inbox #{p['id']}", self.page.text_content("#jOut"))
            return p, len(self.ai_calls) - calls

        self.page.fill("#jIntent", "propose Tuesday afternoon")
        p, calls = drafted(lambda: self.run_click(self.button("Draft reply")))
        self.assertEqual(calls, 1)
        self.assertIn("propose Tuesday afternoon", str(self.ai_calls[-1]["messages"]))
        # outreach: a LinkedIn note is text only; an email goes to the Inbox
        self.page.fill("#jPerson", "Morgan Lee, Data Manager")
        before = self.pending_ids()
        self.run_click(self.button("Draft outreach"))
        self.assertEqual(self.page.text_content("#jOut"), self.ai_text)
        self.assertEqual(self.pending_ids(), before)
        self.assertIn("Morgan Lee, Data Manager", str(self.ai_calls[-1]["messages"]))
        self.page.select_option("#jChannel", "email")
        drafted(lambda: self.run_click(self.button("Draft outreach")))
        # plain template: no AI call at all (each action re-renders the drawer, so tick it each time)
        self.page.check("#jTpl")
        p, calls = drafted(lambda: self.run_click(self.button("Follow-up email")))
        self.assertEqual(calls, 0)
        self.assertIn("Data Platform Engineer", p["payload"]["subject"] + p["payload"]["body"])
        self.page.fill("#jInt", "Ravi Iyer")
        self.page.fill("#jTnotes", "the Kafka migration story")
        self.page.check("#jTpl")
        p, calls = drafted(lambda: self.run_click(self.button("Thank-you note")))
        self.assertEqual(calls, 0)
        self.assertIn("Ravi", p["payload"]["body"])
        self.page.check("#jTpl")
        p, calls = drafted(lambda: self.run_click(self.button("Withdrawal email")))
        self.assertEqual(calls, 0)
        self.assertFalse(self.page.is_checked("#jTpl"))
        self.page.fill("#jInt", "Ravi Iyer")
        self.page.fill("#jTnotes", "the Kafka migration story")
        _, calls = drafted(lambda: self.run_click(self.button("Thank-you note")))
        self.assertEqual(calls, 1)
        self.assertIn("the Kafka migration story", str(self.ai_calls[-1]["messages"]))
        # Options by kind: the thank-you uses the interviewer and notes above (the last action cleared them)
        self.page.fill("#jInt", "Ravi Iyer")
        self.page.fill("#jTnotes", "the Kafka migration story")
        self.page.select_option("#jOk", "thanks")
        before = self.pending_ids()
        self.run_click(self.button("Options"))
        self.assertEqual(self.page.locator("#jOpts .opt").count(), 2)
        self.assertIn("Ravi Iyer", str(self.ai_calls[-1]["messages"]))
        self.assertEqual(self.pending_ids(), before)  # nothing proposed until you use one
        self.run_click(self.page.locator("#jOpts .opt").nth(1).get_by_role("button", name="Use this"))
        new = self.new_pending(before)
        self.assertEqual([(x["payload"]["to"], x["payload"]["subject"]) for x in new], [(to, AI["options"][1]["subject"])])


if __name__ == "__main__":
    unittest.main()
