"""Applying to jobs found on the big boards, with you in the loop (pass 43). The company-site bridge: a capture keeps
the posting's own 'apply on the company site' link (an ATS first, never a board host) as the application link, and a
run on it is never submitted unseen. AI drafts in Fill: open questions on a saved job get the pipeline's drafter
(apply.answer, need_facts), never eligibility / EEO / salary / private ones, at most AI_FILL_MAX, every text through the
floor guard; a missing fact comes back as 'needs you'. The AI cross-check: other linked AIs review an answer, the writer
revises on any objection, up to the rounds pref; not all agreeing is said. No network; every patch is put back."""
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
from test_pass21_fit import patched  # noqa: E402

from lodestar import ai, apply, apply_agent, db, extras, profile, settings, web  # noqa: E402

PROF = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com | 512-555-0100\n## Summary\nData engineer.\n## Skills\n"
        "Python, SQL\n## Experience\n### Data Engineer - Globex (2019-01 - Present)\n- Built pipelines\n"
        "## Education\nBS Computer Science\n")


class Base(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        had = profile.PROFILE.read_text(encoding="utf-8") if profile.PROFILE.is_file() else None
        self.addCleanup(lambda: profile.PROFILE.write_text(had, encoding="utf-8") if had is not None else None)
        profile.write_master(PROF)
        self.made = []
        self.addCleanup(lambda: [db.delete_job(j) for j in self.made])

    def capture(self, url, links):
        out = web.capture({"title": "Data Engineer - Acme Robotics | LinkedIn", "url": url, "desc": "word " * 60,
                           "posting": {"title": "Data Engineer", "company": "Acme Robotics"}, "apply_links": links})
        self.made.append(out["id"])
        return out


class Bridge(Base):
    def test_the_posting_s_company_link_becomes_the_application_link(self):
        out = self.capture("https://www.linkedin.com/jobs/view/1001", [
            "https://www.linkedin.com/jobs/view/1001/apply", "https://careers.acme.example/jobs/9",
            "https://boards.greenhouse.io/acme/jobs/9", "javascript:alert(1)"])
        self.assertEqual(out["apply_url"], "https://boards.greenhouse.io/acme/jobs/9")  # an application system first
        job = db.get_job(out["id"])
        self.assertEqual(job["apply_url"], "https://boards.greenhouse.io/acme/jobs/9")
        self.assertTrue(apply_agent.link_from_page(job, job["apply_url"]))  # never submitted unseen

    def test_only_board_links_leave_it_for_the_employer_site_search(self):
        out = self.capture("https://www.indeed.com/viewjob?jk=77", ["https://www.indeed.com/applystart?jk=77",
                                                                     "https://uk.indeed.com/x", "ftp://acme.example/x"])
        self.assertIsNone(out["apply_url"])
        self.assertFalse(db.get_job(out["id"])["apply_url"])

    def test_a_link_you_typed_later_is_yours(self):
        out = self.capture("https://www.linkedin.com/jobs/view/1002", ["https://careers.acme.example/jobs/10"])
        db.set_fields(out["id"], apply_url="https://careers.acme.example/jobs/10-mine")
        job = db.get_job(out["id"])
        self.assertFalse(apply_agent.link_from_page(job, job["apply_url"]))


class AiFill(Base):
    QS = ["Why do you want to work here?", "Describe a pipeline you built.", "Are you legally authorized to work in the US?",
          "Desired salary", "What is your gender?"]

    def drafter(self, missing=""):
        seen = []

        def fake(job, question, provider=None, need_facts=False, propose=True, notes=""):
            seen.append((question, need_facts, propose))
            return {"answer": "" if missing else f"Draft for: {question}", "missing": missing, "proposal": None,
                    "reused": [], "crosscheck": {"status": "agreed", "rounds": 0, "issues": []}}
        return seen, patched(apply, answer=fake)

    def test_open_questions_on_a_saved_job_get_drafts_and_never_the_closed_kinds(self):
        out = self.capture("https://www.linkedin.com/jobs/view/2001", [])
        seen, p = self.drafter()
        with p:
            got = extras.ext_autofill(self.QS, url="https://www.linkedin.com/jobs/view/2001", ai=True)
        self.assertEqual([q for q, *_ in seen], self.QS[:2])
        self.assertTrue(all(nf and not prop for _, nf, prop in seen))  # facts asked for, nothing proposed
        a = got["answers"]["Why do you want to work here?"]
        self.assertEqual((a["match"], a["answer"]), ("ai", "Draft for: Why do you want to work here?"))
        self.assertEqual(a["check"], "agreed")
        for q in self.QS[2:]:
            self.assertNotEqual((got["answers"].get(q) or {}).get("match"), "ai")
        self.assertEqual(got["job"]["id"], out["id"])

    def test_off_unsaved_missing_facts_and_the_cap(self):
        self.capture("https://www.linkedin.com/jobs/view/2002", [])
        seen, p = self.drafter()
        with p:
            extras.ext_autofill(self.QS, url="https://www.linkedin.com/jobs/view/2002")  # not ticked
            self.assertEqual(seen, [])
            got = extras.ext_autofill(self.QS, url="https://www.linkedin.com/jobs/view/none", ai=True)
        self.assertEqual(seen, [])
        self.assertIn("Save", got["ai_note"])
        seen, p = self.drafter(missing="How many years of Spark have you used?")
        with p:
            got = extras.ext_autofill(self.QS[:1], url="https://www.linkedin.com/jobs/view/2002", ai=True)
        self.assertEqual(got["missing"], {self.QS[0]: "How many years of Spark have you used?"})
        many = [f"Tell us about project {i}." for i in range(9)]
        seen, p = self.drafter()
        with p:
            extras.ext_autofill(many, url="https://www.linkedin.com/jobs/view/2002", ai=True)
        self.assertEqual(len(seen), extras.AI_FILL_MAX)

    def test_a_draft_the_floor_guard_changes_is_withheld(self):
        self.capture("https://www.linkedin.com/jobs/view/2003", [])
        seen, p = self.drafter()
        with p, patched(extras, _unchanged_by_guard=lambda text, any_line=True: "Draft for" not in text):
            got = extras.ext_autofill(self.QS[:1], url="https://www.linkedin.com/jobs/view/2003", ai=True)
        self.assertNotIn(self.QS[0], got["answers"])
        self.assertGreaterEqual(got["withheld"], 1)


class CrossCheck(Base):
    def setUp(self):
        super().setUp()  # a real profile: the form-answer test drafts from it
        self.calls = []

    def fakes(self, verdicts):
        """verdicts: {provider: [reply per round]} for reviewers; the writer's revisions are 'revised N'."""
        rounds = {n: iter(v) for n, v in verdicts.items()}

        def ask_json(prompt, system=None, provider=None, **kw):
            self.calls.append(("review", provider))
            return next(rounds[provider])

        def ask(prompt, system=None, provider=None, **kw):
            self.calls.append(("revise", provider))
            return f"revised {sum(1 for c in self.calls if c[0] == 'revise')}"
        return patched(ai, ask_json=ask_json, ask=ask)

    def test_all_reviewers_agree_at_once(self):
        with self.fakes({"openai": [{"agree": True, "issues": []}], "gemini": [{"agree": True, "issues": []}]}):
            r = ai.crosscheck("task", "draft", writer="anthropic", reviewers=["openai", "gemini"], rounds=2)
        self.assertEqual((r["answer"], r["status"], r["rounds"]), ("draft", "agreed", 0))

    def test_an_objection_is_revised_until_everyone_agrees(self):
        with self.fakes({"openai": [{"agree": False, "issues": ["invents 8 years of Spark"]}, {"agree": True}],
                         "gemini": [{"agree": True}, {"agree": True}]}):
            r = ai.crosscheck("task", "draft", writer="anthropic", reviewers=["openai", "gemini"], rounds=2)
        self.assertEqual((r["answer"], r["status"], r["rounds"]), ("revised 1", "agreed", 1))
        self.assertIn(("revise", "anthropic"), self.calls)

    def test_no_agreement_after_the_rounds_is_said_and_bounded(self):
        no = {"agree": False, "issues": ["still wrong"]}
        with self.fakes({"openai": [no, no, no]}):
            r = ai.crosscheck("task", "draft", writer="anthropic", reviewers=["openai"], rounds=2)
        self.assertEqual(r["status"], "disagreed")
        self.assertEqual(r["issues"], ["openai: still wrong"])
        self.assertEqual(len(self.calls), 3 + 2)  # three reviews, two revisions: never more

    def test_one_ai_only_or_a_reviewer_that_fails(self):
        r = ai.crosscheck("task", "draft", writer="anthropic", reviewers=[])
        self.assertEqual(r["status"], "unchecked")

        def boom(prompt, system=None, provider=None, **kw):
            raise SystemExit("openai: missing key")
        with patched(ai, ask_json=boom):
            r = ai.crosscheck("task", "draft", writer="anthropic", reviewers=["openai"], rounds=1)
        self.assertEqual((r["answer"], r["status"]), ("draft", "unchecked"))

    def test_form_answers_are_cross_checked_only_with_the_pref_on(self):
        jid = db.add_job("Crosscheck Co", "Data Engineer", "https://x.example/cc", "word " * 60, None)
        self.addCleanup(db.delete_job, jid)
        got = []
        with patched(ai, ask=lambda prompt, system=None, provider=None, **kw: "my draft",
                     crosscheck=lambda prompt, answer, writer=None, **kw: got.append(answer) or
                     {"answer": "checked draft", "status": "agreed", "rounds": 0, "issues": []}):
            r = apply.answer(db.get_job(jid), "Why us?", propose=False)
            self.assertEqual((r["answer"], got), ("my draft", []))
            settings.set_pref("ai_crosscheck", True)
            r = apply.answer(db.get_job(jid), "Why us?", propose=False)
        self.assertEqual((r["answer"], r["crosscheck"]["status"]), ("checked draft", "agreed"))


if __name__ == "__main__":
    unittest.main()
