"""The drawer's To-dos (pass 53): add one with a due date, it shows on Today, tick it, delete it, and AI suggestions
are added only by a click."""
import unittest
from datetime import date

from harness import E2ETestCase

from lodestar import db  # noqa: E402  (after harness: it sets the temp home first)


class Todos(E2ETestCase):
    ai_json = {"todos": ["Research the hiring manager", "Prepare two STAR stories"]}

    def test_add_today_tick_delete_and_ai_suggestions(self):
        jid = self.ids["saved"]
        self.open_job(jid)
        box = self.page.locator("#jTodoG")
        self.assertIn("No to-dos yet", box.text_content())
        self.page.fill("#jTodoText", "Ask Sam for a referral")
        self.page.fill("#jTodoDue", date.today().isoformat())
        self.page.press("#jTodoText", "Enter")
        self.idle()
        self.assertIn("Ask Sam for a referral", box.text_content())
        self.assertEqual(db.tasks(jid)[0]["due"], date.today().isoformat())
        self.page.keyboard.press("Escape")
        self.go("home")
        self.assertIn("Ask Sam for a referral", self.page.text_content("#home"))
        self.open_job(jid)
        box.locator("input[type=checkbox]").first.check()
        self.idle()
        self.assertTrue(db.tasks(jid)[0]["done_at"])
        self.run_click(box.get_by_role("button", name="AI: suggest to-dos"))
        self.assertEqual(len(db.tasks(jid)), 1)  # nothing added by the AI itself
        self.run_click(box.get_by_role("button", name="+ Research the hiring manager"))
        self.assertEqual([t["text"] for t in db.tasks(jid)], ["Research the hiring manager", "Ask Sam for a referral"])
        self.run_click(box.get_by_role("button", name="delete to-do: Research the hiring manager"))
        self.assertEqual([t["text"] for t in db.tasks(jid)], ["Ask Sam for a referral"])


if __name__ == "__main__":
    unittest.main()
