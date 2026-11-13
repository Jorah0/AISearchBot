"""Application lifecycle (pass 26, blueprint 11.2 / 11.3 / 6.4 / 6.5): the drawer's fine-grained stage (the board
column follows; on hold keeps it), its stage history with who moved it, when the posting last answered, and the board
coverage under a Jobs search."""
import unittest

from harness import FETCH, E2ETestCase, db

INN = {"title": "Night Auditor", "company_name": "Saltmarsh Inn", "url": "https://jobs.example.com/saltmarsh-inn/na",
       "candidate_required_location": "USA", "description": "Balance the day's accounts overnight at a 90-room hotel."}


class Lifecycle(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        cls.ids["life"] = db.add_job("Saltmarsh Inn", "Front Office Manager", "https://jobs.example.com/saltmarsh-inn/fom",
                                     "Lead the front desk team.", "e2e")
        db.update_job(cls.ids["life"], touch=False, posting_checked_at="2026-11-12")
        cls.addClassCleanup(lambda saved=dict(FETCH): (FETCH.clear(), FETCH.update(saved)))
        FETCH["remotive.com"] = {"jobs": [INN]}
        db.release()

    def test_stage_moves_the_column_and_keeps_its_history(self):
        d = self.open_job(self.ids["life"])
        self.assertIn("posting last answered 2026-11-12", d.locator("#jStage").text_content())
        d.locator("#jStageSel").select_option("technical_interview")
        d.get_by_role("button", name="set stage").click()
        self.idle()
        self.assertEqual(self.state_job(self.ids["life"])["status"], "interview")
        d = self.open_job(self.ids["life"])
        d.locator("#jStageSel").select_option("on_hold")
        d.get_by_role("button", name="set stage").click()
        self.idle()
        job = self.state_job(self.ids["life"])
        self.assertEqual((job["status"], job["stage"]), ("interview", "on_hold"))
        hist = self.open_job(self.ids["life"]).locator("#jStageHist").text_content()
        self.assertIn("saved → technical_interview by you", hist)
        self.assertIn("technical_interview → on_hold by you", hist)

    def test_jobs_search_says_which_boards_were_asked(self):
        self.go("search")
        self.page.fill("#sQ", "night auditor")
        self.run_click(self.page.get_by_role("button", name="Search boards now"))
        cov = self.page.locator("#sRes .coverage").text_content()
        self.assertIn("Boards asked:", cov)
        self.assertIn("never searches every job board", cov)

    def state_job(self, jid):
        return next(j for j in self.state()["jobs"] if j["id"] == jid)


if __name__ == "__main__":
    unittest.main()
