"""Audit log (pass 25, blueprint 17.2): Setup > Audit log lists the central policy's decisions (allowed / waits for you /
blocked, with the reasons in words) and every action run, newest first."""
import unittest

from harness import E2ETestCase, db

from lodestar import approvals  # noqa: E402  (after harness: it sets the temp home first)


class AuditLog(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        jid = db.add_job("Saltmarsh Inn", "Hotel Manager", None, "jd", "e2e")
        db.update_job(jid, contact_email="hr@saltmarsh.example", status="offer")
        approvals.propose("email_reply", "send_email", {"to": "hr@saltmarsh.example", "subject": "Re: offer",
                                                        "body": "Thank you.", "job_id": jid}, "reply about the offer", jid)
        db.release()

    def test_setup_lists_decisions_with_reasons_in_words(self):
        self.go("setup")
        log = self.page.locator("#auditLog")
        row = log.locator(".audit-row", has_text="offer and negotiation mail always waits for you")  # the seed has others
        self.assertEqual(row.count(), 1)
        text = row.inner_text()
        self.assertIn("propose:send_email", text)
        self.assertIn("waits for you", text)
        self.assertIn("policy version 1", self.page.locator("#auditCard").inner_text())


if __name__ == "__main__":
    unittest.main()
