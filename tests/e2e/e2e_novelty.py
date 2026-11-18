"""All jobs labels the AI's new-listing verdicts (pass 55): another copy of a job you have, a repost, a new opening,
and a resembling listing the AI has not checked; a copy is not counted as new."""
import unittest

from harness import E2ETestCase

from lodestar import db, listings  # noqa: E402  (after harness: it sets the temp home first)


class Novelty(E2ETestCase):
    def test_all_jobs_shows_each_verdict(self):
        rows = listings.store([{"title": t, "company": "Thimble Works", "url": f"https://jobs.thimble.example/{i}", "location": "Austin, TX",
                                "desc": "SQL dashboards for the shop floor.", "source": "test"}
                               for i, t in enumerate(("Line Analyst A", "Line Analyst B", "Line Analyst C", "Line Analyst D"))])
        for r, (v, by, why) in zip(rows, (("same", "ai", "same requisition"), ("repost", "ai", "advertised again"),
                                          ("new", "ai", "a different team"), ("new", "unchecked", "looks like Line Analyst A: not checked by AI"))):
            db.con().execute("UPDATE postings SET novelty=?, novelty_by=?, novelty_why=? WHERE key=?", (v, by, why, r["key"]))
        db.con().commit()
        self.go("search")
        self.page.fill("#ajQ", "Thimble")
        self.page.evaluate("loadAllJobs()")
        self.idle()
        box = self.page.locator("#allJobs")
        for chip, tip in (("AI: same job as one you have", "same requisition"), ("AI: repost", "advertised again"),
                          ("AI: new opening", "a different team"), ("looks like one you have", "not checked by AI")):
            c = box.locator(".chip", has_text=chip).first
            self.assertTrue(c.is_visible(), chip)
            self.assertIn(tip, c.get_attribute("title"))


if __name__ == "__main__":
    unittest.main()
