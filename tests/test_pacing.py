"""Pacing for the job sites you browse yourself (pass 36): LinkedIn, Indeed, Glassdoor, ZipRecruiter and SimplyHired
get a daily and a weekly application cap (yours to change). Lodestar counts the jobs you marked applied whose link is
on that site, and refuses an extension fill there once today's or this week's cap is reached. A company's own site is
never capped. No network; every patched attribute is put back."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import db, pacing  # noqa: E402


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


class Pacing(unittest.TestCase):
    def setUp(self):
        self.made = []
        db.con().execute("DELETE FROM meta WHERE key=?", (pacing.KEY,))
        db.con().commit()

    def tearDown(self):
        for jid in self.made:
            db.delete_job(jid)
        db.con().execute("DELETE FROM meta WHERE key=?", (pacing.KEY,))
        db.con().commit()

    def applied(self, url, apply_url=None):
        jid = db.add_job("Pacing Co", f"Role {len(self.made)}", url, "desc", "test")
        self.made.append(jid)
        if apply_url:
            db.set_fields(jid, apply_url=apply_url)
        db.set_status(jid, "applied")
        return jid

    def test_default_caps_and_your_own(self):
        c = pacing.caps()
        self.assertEqual(set(c), set(pacing.SITES))
        self.assertEqual(c["LinkedIn"], {"day": 10, "week": 40})
        pacing.set_cap("Indeed", 3, 12)
        self.assertEqual(pacing.caps()["Indeed"], {"day": 3, "week": 12})
        with self.assertRaises(SystemExit):
            pacing.set_cap("Monster", 1, 2)  # not one of the five
        with self.assertRaises(SystemExit):
            pacing.set_cap("Indeed", 5, 2)  # a week below a day

    def test_counts_applications_per_site_and_refuses_a_fill_at_the_cap(self):
        pacing.set_cap("LinkedIn", 2, 5)
        self.applied("https://www.linkedin.com/jobs/view/1")
        self.assertIsNone(pacing.check("https://www.linkedin.com/jobs/view/9"))
        self.applied("https://boards.example/x", apply_url="https://de.linkedin.com/jobs/view/2")  # applied via LinkedIn
        self.applied("https://www.indeed.com/viewjob?jk=1")
        self.applied("https://careers.pacingco.example/jobs/1")  # the company's own site: never counted
        u = pacing.usage()
        self.assertEqual((u["LinkedIn"]["day"], u["LinkedIn"]["week"], u["LinkedIn"]["full"]), (2, 2, True))
        self.assertEqual((u["Indeed"]["day"], u["Indeed"]["full"]), (1, False))
        msg = pacing.check("https://www.linkedin.com/jobs/view/9")
        self.assertIn("LinkedIn", msg)
        self.assertIn("2 of 2 today", msg)
        self.assertIsNone(pacing.check("https://careers.pacingco.example/apply"))
        self.assertIsNone(pacing.check("https://www.indeed.com/viewjob?jk=2"))
        self.assertEqual(pacing.for_job(db.get_job(self.made[0]))["site"], "LinkedIn")
        self.assertIsNone(pacing.for_job(db.get_job(self.made[3])))

    def test_the_weekly_cap_counts_the_last_seven_days(self):
        pacing.set_cap("Glassdoor", 2, 2)
        rows = [("https://www.glassdoor.com/job-listing/a", None, ago(3), 1),
                ("https://www.glassdoor.com/job-listing/b", None, ago(8), 2)]  # outside the week
        with patched(pacing, _moves=lambda: rows):
            u = pacing.usage()["Glassdoor"]
            self.assertEqual((u["day"], u["week"], u["full"]), (0, 1, False))
            rows.append(("https://www.glassdoor.com/job-listing/c", None, ago(0), 3))
            self.assertIn("this week", pacing.check("https://www.glassdoor.com/job-listing/d"))


if __name__ == "__main__":
    unittest.main()
