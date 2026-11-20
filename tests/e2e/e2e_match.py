"""The drawer's Match report (pass 53): the match rate with its 75% target, the applicant-tracking system the apply
link is on with its tips, and the AI button that reuses the guarded bullet tailoring."""
import unittest

from harness import E2ETestCase

from lodestar import db  # noqa: E402  (after harness: it sets the temp home first)


class Match(E2ETestCase):
    def test_match_rate_target_ats_tips_and_ai_fix(self):
        jid = self.ids["interview"]
        db.set_fields(jid, apply_url="https://boards.greenhouse.io/orchid/jobs/42")
        self.open_job(jid)
        box = self.page.locator("#jMatchG")
        self.assertIn("Match report", box.locator("h4").first.text_content())
        self.run_click(box.get_by_role("button", name="Compute JD coverage"))
        self.assertIn("target 75%+", box.text_content())
        self.assertIn("Applies on greenhouse", box.locator(".atsbox").text_content())
        ai = box.locator("#jMatchAI")
        if self.page.evaluate("[...document.querySelectorAll('#jMatch tr.miss')].some(r => r.children[1].textContent !== 'other')"):
            self.assertRegex(ai.text_content(), r"AI: work in \d+ missing keyword")
        else:
            self.assertEqual(ai.count(), 0)


if __name__ == "__main__":
    unittest.main()
