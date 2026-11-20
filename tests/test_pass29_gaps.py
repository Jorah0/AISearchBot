"""Pass 29: the skill-gap planner (blueprint 13.3) across your tracked jobs: repeated requirements, required vs typical,
legal requirements apart from employer preferences, each with possible actions, and the sample size said (13.2); and
analytics by career track and career class (13.1). No network, no AI; every patched attribute is put back."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import JD, Base, run_cli  # noqa: E402

from lodestar import careers, db, extras, fit, gaps  # noqa: E402

CDL = JD.replace("Requirements:\n", "Requirements:\n- Must hold a valid Class A CDL license\n")


class Planner(Base):
    def test_repeated_required_skills_rank_first_with_actions(self):
        self.job()
        self.job(company="Globex Two")
        fit.refresh()
        rows = gaps.plan()
        by = {r["requirement"]: r for r in rows}
        k = by["kubernetes"]
        self.assertEqual((k["count"], k["mandatory"], k["legal"]), (2, True, False))
        self.assertIn("project", k["actions"])
        self.assertEqual(rows[0]["count"], 2)  # most repeated first
        self.assertEqual(sorted(k["jobs"]), sorted(j["id"] for j in db.list_jobs()))

    def test_a_required_license_is_a_legal_gap_with_a_credential_action(self):
        self.job(jd=CDL, title="Truck Driver")
        fit.refresh()
        row = next(r for r in gaps.plan() if "cdl" in r["requirement"].lower())
        self.assertTrue(row["legal"])
        self.assertTrue(row["mandatory"])
        self.assertEqual(row["actions"], ["certification"])

    def test_closed_jobs_are_left_out_and_a_small_sample_is_said(self):
        jid = self.job()
        fit.refresh()
        db.set_status(jid, "rejected")
        out = gaps.report()
        self.assertEqual((out["rows"], out["jobs"]), ([], 0))
        self.job()
        fit.refresh()
        out = gaps.report()
        self.assertEqual(out["jobs"], 1)
        self.assertIn(f"fewer than {extras.MIN_N}", out["note"])
        self.assertIn("kubernetes", run_cli("gaps"))


class ByTrack(Base):
    def test_listings_and_tracked_jobs_per_track_and_class(self):
        tid = careers.add_track("Data", "desired_field", titles=["Data Engineer"])
        jid = self.job()
        fit.refresh()
        db.con().execute("INSERT INTO postings(key, url, track_id, job_id) VALUES ('t1', 'https://x.test/1', ?, ?)", (tid, jid))
        db.con().execute("INSERT INTO postings(key, url, track_id) VALUES ('t2', 'https://x.test/2', ?)", (tid,))
        db.con().commit()
        row = next(r for r in gaps.by_track() if r["track"] == "Data")
        self.assertEqual((row["listings"], row["tracked"]), (2, 1))
        self.assertEqual(sum(row["classes"].values()), 1)
        self.assertTrue(set(row["classes"]) <= set(careers.CLASSES))


if __name__ == "__main__":
    unittest.main()
