"""The full email, formatted (pass 54): the Mail page shows a mail's formatted copy in a sandboxed frame (no scripts,
remote images off until Show images, Plain text and back), and an Inbox card that answers a mail unfolds the same
email under Read the full email, kept open across the Inbox refresh."""
import unittest

from harness import E2ETestCase

from lodestar import approvals, db  # noqa: E402  (after harness: it sets the temp home first)

HTML = ('<h2 style="color:#1F4E79">Interview next week</h2><p>Hi, <b>great news</b>: pick a slot.</p>'
        '<table><tr><td>Tue 10:00</td><td>Wed 14:00</td></tr></table><img src="data:image/png;base64,iVBORw0KGgo=">'
        '<img src="https://track.example/p.gif">')


class MailView(E2ETestCase):
    def test_mail_page_and_inbox_card_show_the_formatted_email(self):
        jid = self.ids["interview"]
        db.add_mail(message_id="<fmt-1@orchid.example>", direction="in", from_addr="Ann <ann@orchid.example>", subject="Formatted slots",
                    body="Interview next week. Hi, great news: pick a slot.", html=HTML, job_id=jid, category="interview")
        pid = approvals.propose("email_reply", "send_email", {"to": "ann@orchid.example", "subject": "Re: Formatted slots", "body": "Tue works.",
                                "in_reply_to": "<fmt-1@orchid.example>", "job_id": jid}, "reply to Ann", jid, force_pending=True)["id"]
        self.reload_state()
        self.go("mail")
        self.page.locator(".mvrow", has_text="Formatted slots").click()
        self.idle()
        read = self.page.locator("#mvRead")
        self.allow_console(r"violates the following Content Security Policy")  # the remote image, blocked as it should be
        frame = read.locator("iframe.mailhtml")
        self.assertEqual(frame.get_attribute("sandbox"), "allow-popups allow-popups-to-escape-sandbox")
        doc = frame.get_attribute("srcdoc")
        self.assertIn("<b>great news</b>", doc)
        self.assertIn("img-src data:;", doc)  # remote images off
        self.assertEqual(self.page.frame_locator("#mvRead iframe.mailhtml").locator("b").text_content(), "great news")
        read.get_by_role("button", name="Plain text").click()
        self.assertIn("Hi, great news", read.locator("pre.mvbody").text_content())
        read.get_by_role("button", name="Show formatted").click()
        self.assertEqual(read.locator("iframe.mailhtml").count(), 1)
        self.page.click('nav button[data-tab="inbox"]')  # not go(): the email frame never lets networkidle settle
        self.page.wait_for_selector("section#inbox.on")
        self.idle()
        card = self.page.locator("#inboxList > .item", has=self.page.locator(f'.hd > b:text-is("#{pid}")'))
        card.locator("summary", has_text="Read the full email").click()
        self.idle()
        self.page.wait_for_selector('#inboxList iframe.mailhtml')
        self.assertIn("<b>great news</b>", card.locator("iframe.mailhtml").get_attribute("srcdoc"))
        self.page.evaluate("renderInbox()")  # the 60 s refresh keeps it open
        self.assertEqual(card.locator("details.mailfold[open] iframe.mailhtml").count(), 1)
        # last: Show images lifts the block for this email (the tracker host never resolves: .example)
        self.allow_console(r"violates the following Content Security Policy|ERR_NAME_NOT_RESOLVED")
        card.get_by_role("button", name="Show images").click()
        self.assertIn("img-src data: https: http:", card.locator("iframe.mailhtml").get_attribute("srcdoc"))


if __name__ == "__main__":
    unittest.main()
