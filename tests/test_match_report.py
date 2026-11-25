"""The match report (pass 53): JD coverage shown as a match rate with a 75% target, plus the applicant-tracking system
the job's apply link is on and its general tips. Deterministic; no AI, no network."""
import os
import sys
import tempfile
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ats, db, resume  # noqa: E402


class MatchReport(unittest.TestCase):
    def test_ats_detected_from_the_apply_link_with_tips(self):
        self.assertEqual(ats.ats_info("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1")["name"], "workday")
        self.assertTrue(ats.ats_info("https://boards.greenhouse.io/acme/jobs/1")["tips"])
        self.assertIsNone(ats.ats_info("https://careers.acme.example/jobs/1"))
        self.assertIsNone(ats.ats_info(""))
        self.assertTrue(set(ats.ATS_TIPS) <= set(__import__("lodestar.apply_ats", fromlist=["ATS"]).ATS))

    def test_coverage_carries_the_target_and_the_ats(self):
        jid = db.add_job("Larkspur Mills", "Data Analyst", "https://jobs.lever.co/larkspur/1",
                         "We need SQL, Python and Tableau. Strong communication.", "test")
        db.set_fields(jid, apply_url="https://jobs.lever.co/larkspur/1/apply")
        cov = resume.coverage(db.get_job(jid), "Data Analyst with SQL and Python.", save=False)
        self.assertEqual(cov["target"], 75)
        self.assertEqual(cov["ats"]["name"], "lever")
        self.assertIn("note", cov)


if __name__ == "__main__":
    unittest.main()
