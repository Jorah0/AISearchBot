"""Limited daily applying (pass 40): a per-site daily limit on the apply agent (every site it applies on, by application
system or company host), the same role never applied for twice (cross-posted, tracked twice: same link or same company +
title + place), and Autopilot starting the agent only when you switch it on, best fit first, a few a day. No browser
(start=False), no network; every patched attribute and setting is put back."""
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
from test_apply_engine import Base, patched  # noqa: E402

from lodestar import apply_agent, db, pipeline, settings  # noqa: E402


class SiteLimit(Base):
    def test_a_site_stops_at_its_daily_limit_and_other_sites_go_on(self):
        settings.set_pref("apply_agent_site_daily_cap", 2)
        a = [self.job(f"Co{i}") for i in range(3)]  # all on jobs.example-ats.test (the 'exampleats' system)
        out = apply_agent.enqueue(a, "stop", start=False)
        self.assertEqual(["run_id" in r for r in out], [True, True, False])
        self.assertIn("exampleats: 2 of 2 applications started today", out[2]["error"])
        other = self.job("Elsewhere", apply_url="https://careers.elsewhere.example/jobs/1")
        self.assertIn("run_id", apply_agent.enqueue([other], "stop", start=False)[0])  # its own site, its own count

    def test_site_key_is_the_application_system_else_the_host(self):
        self.assertEqual(apply_agent.site_key("https://jobs.example-ats.test/acme/1"), "exampleats")
        self.assertEqual(apply_agent.site_key("https://www.Careers.Acme.example/a"), "careers.acme.example")


class SameRole(Base):
    def test_the_same_role_tracked_twice_is_applied_for_once(self):
        first = self.job("Acme Robotics", location="Austin, TX")
        twin = self.job("ACME Robotics, Inc.", location="Austin, Texas")  # another board's copy of the same opening
        self.assertIn("run_id", apply_agent.enqueue([first], "stop", start=False)[0])
        err = apply_agent.enqueue([twin], "stop", start=False)[0]["error"]
        self.assertIn(f"same role as #{first}", err)

    def test_an_applied_copy_with_the_same_link_blocks_the_other(self):
        url = "https://jobs.example-ats.test/acme/shared-1"
        done = self.job("Acme Robotics", url=url + "?utm_source=board")
        db.set_status(done, "applied")
        copy = db.add_job("Acme (via alert)", "Data Engineer II", "https://another.example/x", "Python", None, apply_url=url + "/")
        self.made.append(copy)
        self.assertIn(f"same role as #{done}", apply_agent.already_submitted(copy))

    def test_other_places_titles_and_job_ids_in_the_link_stay_apart(self):
        a = self.job("Acme Robotics", location="Austin, TX")
        b = self.job("Acme Robotics", location="Denver, CO")
        db.set_status(a, "applied")
        self.assertIsNone(apply_agent.already_submitted(b))
        c = db.add_job("Acme Robotics", "Data Engineer", "https://acme.example/careers?gh_jid=1", "x", None, location="Denver, CO")
        d = db.add_job("Acme Robotics", "ML Engineer", "https://acme.example/careers?gh_jid=2", "x", None, location="Denver, CO")
        self.made += [c, d]
        db.set_status(c, "applied")
        self.assertIsNone(apply_agent.already_submitted(d))


class Autopilot(Base):
    def states(self, *ids, ready=True, verdict="apply"):
        return {i: [{"name": "score", "state": "done", "output": {"verdict": verdict}},
                    {"name": "apply", "state": "ready" if ready else "waiting", "output": {}}] for i in ids}

    def test_off_by_default_then_best_fit_first_within_the_daily_number(self):
        lo, hi, mid = self.job("Lo"), self.job("Hi"), self.job("Mid")
        for jid, f in ((lo, 60), (hi, 95), (mid, 80)):
            db.con().execute("UPDATE jobs SET fit_score=? WHERE id=?", (f, jid))
        db.con().commit()
        with patched(apply_agent, available=lambda: None, _ensure_worker=lambda: None):
            self.assertEqual(apply_agent.autopilot_apply(self.states(lo, hi, mid)), [])  # autopilot_apply is off
            settings.set_pref("autopilot_apply", True)
            settings.set_pref("autopilot_apply_daily", 2)
            settings.set_pref("apply_agent_site_daily_cap", 10)
            out = apply_agent.autopilot_apply(self.states(lo, hi, mid))
        self.assertEqual([r["job_id"] for r in out if "run_id" in r], [hi, mid])

    def test_skips_fit_gated_unprepared_and_linkless_jobs(self):
        gated, unready, ok = self.job("Gated"), self.job("Unready"), self.job("Ok")
        linkless = db.add_job("Nolink", "Data Engineer", None, "x", None)
        self.made.append(linkless)
        settings.set_pref("autopilot_apply", True)
        states = self.states(gated, verdict="skip") | self.states(unready, ready=False) | self.states(ok, linkless)
        with patched(apply_agent, available=lambda: None, _ensure_worker=lambda: None):
            out = apply_agent.autopilot_apply(states)
        self.assertEqual([r["job_id"] for r in out], [ok])

    def test_advance_hands_its_states_to_the_apply_step(self):
        got = []
        settings.set_pref("autopilot", True)
        settings.set_pref("autopilot_jobs_per_cycle", 0)
        with patched(apply_agent, autopilot_apply=lambda states: got.append(states) or []):
            pipeline.advance()
        self.assertTrue(got and isinstance(got[0], dict))


if __name__ == "__main__":
    unittest.main()
