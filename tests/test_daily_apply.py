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

from lodestar import ai, apply_agent, db, pipeline, settings, web  # noqa: E402


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


class Shown(Base):
    def stage(self, jid, name):
        return next(e for e in pipeline.status(jid, save=False) if e["name"] == name)

    def test_a_copy_of_an_applied_role_is_blocked_on_the_board_with_its_reason(self):
        done = self.job("Acme Robotics", location="Austin, TX")
        db.set_status(done, "applied")
        twin = self.job("Acme Robotics Inc", location="Austin")
        e = self.stage(twin, "score")  # the first step: Autopilot spends nothing on it
        self.assertEqual(e["state"], "blocked")
        self.assertIn(f"same role as #{done}", e["why"])

    def test_two_saved_copies_the_newer_waits_for_the_older(self):
        old, new = self.job("Acme Robotics"), self.job("ACME Robotics")
        self.assertNotEqual(self.stage(old, "score")["state"], "blocked")
        e = self.stage(new, "score")
        self.assertEqual(e["state"], "blocked")
        self.assertIn(f"tracked earlier as #{old}", e["why"])
        self.assertIn("run_id", apply_agent.enqueue([new], "stop", start=False)[0])  # your click may still use this copy


class AiCheck(Base):
    """The AI judges a company + title copy (same / similar / different); a shared link is never sent to it."""

    def pair(self):
        done = self.job("Acme Robotics", location="Austin, TX")
        db.set_status(done, "applied")
        return done, self.job("Acme Robotics", location="Austin, TX")

    def ask(self, verdict, why="the descriptions name different teams"):
        calls = []

        def fake(prompt, provider=None, **kw):
            calls.append(prompt)
            return {"verdict": verdict, "why": why}
        return calls, patched(ai, ask_json=fake, available=lambda: True)

    def test_different_lifts_the_block_and_the_prompt_is_fenced(self):
        done, copy = self.pair()
        self.assertIn("not checked by AI yet", apply_agent.same_role(db.get_job(copy)))
        calls, p = self.ask("different")
        with p:
            out = apply_agent.check_dups(copy)
        self.assertEqual([(r["other"], r["verdict"]) for r in out], [(done, "different")])
        self.assertIn("untrusted", calls[0])
        self.assertIn("BLOCK A", calls[0])
        self.assertIsNone(apply_agent.same_role(db.get_job(copy)))
        self.assertIn("run_id", apply_agent.enqueue([copy], "stop", start=False)[0])
        log = db.con().execute("SELECT ai, detail FROM pipeline_runs WHERE job_id=? ORDER BY id DESC", (copy,)).fetchone()
        self.assertEqual(log["ai"], 1)
        self.assertIn(f"#{done}: different", log["detail"])

    def test_same_and_similar_keep_the_block_with_the_reason(self):
        done, copy = self.pair()
        for verdict, word in (("same", "the same opening"), ("similar", "similar")):
            calls, p = self.ask(verdict, "same team and duties")
            with p:
                apply_agent.check_dups(copy, recheck=True)
            why = apply_agent.same_role(db.get_job(copy))
            self.assertIn(f"AI: {word}", why)
            self.assertIn("same team and duties", why)

    def test_a_shared_link_is_never_asked_and_a_changed_posting_is_asked_again(self):
        url = "https://jobs.example-ats.test/acme/one"
        a = self.job("Acme Robotics", url=url)
        db.set_status(a, "applied")
        b = db.add_job("Other Name", "Other Title", "https://x.example/1", "x", None, apply_url=url)
        self.made.append(b)
        calls, p = self.ask("different")
        with p:
            self.assertEqual(apply_agent.check_dups(b), [])
        self.assertEqual(calls, [])
        done, copy = self.pair()
        _, p = self.ask("different")
        with p:
            apply_agent.check_dups(copy)
        self.assertIsNone(apply_agent.same_role(db.get_job(copy)))
        db.update_job(copy, jd="A different description now")
        self.assertIn("not checked by AI yet", apply_agent.same_role(db.get_job(copy)))

    def test_an_unusable_answer_keeps_the_block(self):
        done, copy = self.pair()
        calls, p = self.ask("maybe")
        with p, self.assertRaises(SystemExit):
            apply_agent.check_dups(copy)
        self.assertIn("not checked by AI yet", apply_agent.same_role(db.get_job(copy)))

    def test_autopilot_checks_copies_within_its_ai_budget(self):
        done, copy = self.pair()
        settings.set_pref("autopilot", True)
        settings.set_pref("autopilot_jobs_per_cycle", 0)
        before = pipeline.spent_today()
        calls, p = self.ask("different")
        with p:
            res = pipeline.advance()
        self.assertEqual([(r["job_id"], r["verdict"]) for r in res["dup_checks"]], [(copy, "different")])
        self.assertEqual(pipeline.spent_today(), before + 1)
        settings.set_pref("autopilot_ai_per_day", 0)
        _, p2 = self.ask("same")
        with p2:
            self.assertEqual(pipeline.advance().get("dup_checks"), [])  # no budget left: nothing asked

    def test_the_check_with_ai_action(self):
        done, copy = self.pair()
        calls, p = self.ask("different")
        with p:
            out = web._do("dup_check", {"id": copy})
        self.assertEqual(out["checks"][0]["verdict"], "different")


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
