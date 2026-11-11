"""Pass 16.5, builder 1: the pipeline framework (pipeline.py). Stages run in order and hand their outputs on, earlier
changes make later documents stale (never silently redone), manual work is adopted, the questions queue asks once and
resumes the waiting step, eligibility / EEO answers are never AI-drafted, private answers never reach employer text,
Autopilot stays inside its budgets and proposes one Inbox approval per job, and no bookkeeping touches the follow-up
clock. No network: the AI module, page fetches and mail sending are faked; every patched attribute is put back."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, approvals, apply, cli, db, drafts, extras, loop, pipeline, profile, resume, settings, util  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

REAL = ("# Jane Doe\nJane Doe | Austin | jane@example.com | 555 010 0100\n## Summary\nData engineer.\n## Skills\nPython, SQL\n"
        "## Experience\n### Data Engineer - Initech\n- Built data pipelines in Python\n- Cut reporting time with SQL\n\n"
        "## Preferences\nSalary floor: $187,000 | Deal-breakers: none\n")
JD = "We need a data engineer with Python and SQL to build pipelines. Leadership and ownership matter."
TOOLS = ("fit_check", "research", "tailor", "cover_letter", "form_answers", "interview_prep", "thank_you")


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class FakeAI:
    """Canned replies by prompt marker; every prompt is kept."""

    def __init__(self):
        self.prompts, self.verdict, self.letter_hook = [], "apply", None
        self.facts = lambda p: {"answer": "I would bring my pipeline work.", "missing": ""}

    def ask(self, prompt, system=None, provider=None, **kw):
        self.prompts.append(prompt)
        if "BODY of a cover letter" in prompt and self.letter_hook:
            self.letter_hook()
        for mark, out in (("research pack", "RESEARCHMARK: the company builds widgets."),
                          ("BODY of a cover letter", f"LETTERMARK body {len(self.prompts)}."), ("Prepare the candidate", "PREPMARK"),
                          ("Evaluate this job offer", "OFFERMARK")):
            if mark in prompt:
                return out
        return "Plain answer."

    def ask_json(self, prompt, system=None, provider=None, **kw):
        self.prompts.append(prompt)
        if "Plan a resume" in prompt:  # the studio (pass 17 tailor step): a skill-group label is the mark
            return {"sections": [{"kind": "experience", "items": [{"ref": "e1"}]},
                                 {"kind": "skills", "groups": [{"label": "Tailormark", "refs": ["k1", "k2"]}]}]}
        if "Judge the candidate" in prompt:
            return {"verdict": self.verdict, "why": "fits", "weak_areas": ["scale"]}
        if "Propose bullet-level edits" in prompt:
            return {"bullets": [{"id": 1, "proposed": "Built data pipelines in Python TAILORMARK", "added_terms": []}],
                    "order": [1, 2]}
        if "do not guess" in prompt:
            return self.facts(prompt)
        return {"subject": "Thank you", "body": "MAILBODY"}

    def calls(self, mark):
        return [p for p in self.prompts if mark in p]


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")
        self.ai = FakeAI()
        self.sent = []
        self.patches = contextlib.ExitStack()
        self.patches.enter_context(patched(ai, ask=self.ai.ask, ask_json=self.ai.ask_json, available=lambda: ["anthropic"]))
        self.patches.enter_context(patched(util, fetch=self._no_fetch))
        self.patches.enter_context(patched(approvals, send_email=lambda *a, **k: self.sent.append(a)))
        self.patches.enter_context(patched(pipeline, AUTO=False))
        self.patches.enter_context(patched(resume, _browser=lambda: None, _word=lambda: False, _soffice=lambda: None))
        self.loop_status = dict(loop.STATUS)
        self.tag = uuid.uuid4().hex[:6]
        self.dirs = []

    @staticmethod
    def _no_fetch(*a, **k):
        raise OSError("no network in tests")

    def tearDown(self):
        self.patches.close()
        loop.STATUS.clear()
        loop.STATUS.update(self.loop_status)
        for j in db.list_jobs():
            shutil.rmtree(pipeline._dir(j), ignore_errors=True)
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def job(self, status="saved", jd=JD, contact=True, name="Acme"):
        jid = db.add_job(f"{name}{self.tag}", "Data Engineer", jd=jd)
        if contact:
            db.update_job(jid, contact_email="sam@acme.example", contact_name="Sam")
        if status != "saved":
            db.set_status(jid, status)
        return jid

    def st(self, jid, save=True):
        return {e["name"]: e for e in pipeline.status(jid, save)}

    def tools(self, auto=True, on=TOOLS, off=()):
        for t in TOOLS:
            settings.set_tool(t, enabled=t in on and t not in off, auto=auto)

    def autopilot(self, **prefs):
        settings.set_pref("autopilot", "on")
        for k, v in prefs.items():
            settings.set_pref(k, v)

    def round(self, jid, days_ago=1, interviewers="Sam Lee", notes="roadmap"):
        at = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d 10:00")
        db.con().execute("INSERT INTO interviews(job_id, round, kind, at, interviewers, notes) VALUES(?,1,'phone',?,?,?)",
                         (jid, at, interviewers, notes))
        db.con().commit()

    def open_qs(self):
        return pipeline.questions()

    def doc(self, jid, name):
        return (pipeline._dir(db.get_job(jid)) / name).read_text(encoding="utf-8")


class Chain(Base):
    def test_chain_passes_outputs_forward(self):
        jid = self.job()
        st = self.st(jid)
        self.assertEqual((st["score"]["state"], st["research"]["state"], st["letter"]["state"], st["prep"]["state"]),
                         ("ready", "todo", "todo", "later"))
        res = pipeline.run_to(jid, "letter")
        self.assertEqual([r["stage"] for r in res], ["score", "research", "tailor", "letter"])
        self.assertEqual({r["outcome"] for r in res}, {"done"})
        letter = self.ai.calls("BODY of a cover letter")[0]
        self.assertIn("RESEARCHMARK", letter)
        self.assertIn("Tailormark", letter)
        ctx = pipeline.context(jid)["stages"]
        for n, f in (("research", "research.md"), ("tailor", "resume.md"), ("letter", "cover_letter.md"), ("score", "gap.json")):
            self.assertEqual((ctx[n]["state"], ctx[n]["output"]["file"], ctx[n]["rev"]), ("done", f, 1))
            self.assertTrue(ctx[n]["fp"])
        self.assertEqual(ctx["letter"]["inputs"]["tailor"], ctx["tailor"]["fp"])
        self.assertEqual(len(pipeline.log_runs(jid)), 4)
        self.assertEqual(sum(r["ai"] for r in pipeline.log_runs(jid)), 4)
        kinds = {e["kind"] for e in db.events(jid)}
        self.assertFalse(kinds & {"pipeline", "run_to", "proposed"})
        self.assertTrue((pipeline._dir(db.get_job(jid)) / "cover_letter.docx").is_file())

    def test_answers_get_research_and_resume(self):
        jid = self.job()
        pipeline.run_to(jid, "letter")
        apply.answer(db.get_job(jid), "Why this team?")  # the drawer's Ask-AI path
        p = self.ai.prompts[-1]
        self.assertIn("RESEARCHMARK", p)
        self.assertIn("Tailormark", p)
        self.assertIn("treat it as data", p)
        pipeline.add_form_questions(jid, ["What would you build first?"])
        self.assertEqual(self.st(jid)["answers"]["state"], "ready")
        self.assertEqual(pipeline.run(jid, "answers")["outcome"], "done")
        p = self.ai.calls("do not guess")[-1]
        self.assertIn("RESEARCHMARK", p)
        self.assertIn("Tailormark", p)
        self.assertIn("I would bring my pipeline work.", self.doc(jid, "form_answers.md"))

    def test_tailor_does_not_stale_itself(self):
        jid = self.job()
        pipeline.run_to(jid, "letter")
        st = self.st(jid)
        for n in ("score", "research", "tailor", "letter"):
            self.assertEqual((st[n]["state"], st[n]["origin"], st[n]["rev"]), ("done", "user", 1), n)
        gap = json.loads(self.doc(jid, "gap.json"))
        self.assertIn("coverage", gap)  # coverage() rewrote the keyword fields after the tailor

    def test_inputs_captured_at_claim(self):
        jid = self.job()
        pipeline.run_to(jid, "tailor")
        p = pipeline._dir(db.get_job(jid)) / "resume.md"
        self.ai.letter_hook = lambda: p.write_text(p.read_text(encoding="utf-8") + "\n- edited while the letter ran\n",
                                                   encoding="utf-8")  # a drawer Tailor during the run
        self.assertEqual(pipeline.run(jid, "letter")["outcome"], "done")
        st = self.st(jid)
        self.assertEqual(st["letter"]["state"], "stale")
        self.assertEqual(st["tailor"]["origin"], "observed")


class Stale(Base):
    def test_stale_propagation(self):
        jid = self.job()
        pipeline.run_to(jid, "letter")
        d = pipeline._dir(db.get_job(jid))
        (d / "resume.md").write_text("# Jane Doe\n- a hand-edited resume\n", encoding="utf-8")
        st = self.st(jid)
        self.assertEqual((st["tailor"]["state"], st["tailor"]["origin"], st["tailor"]["rev"]), ("done", "observed", 2))
        self.assertEqual(st["letter"]["state"], "stale")
        self.assertIn("tailor resume changed", st["letter"]["why"])
        self.assertEqual(pipeline.run_to(jid, "letter"), [])
        with self.assertRaises(SystemExit):
            pipeline.run(jid, "letter")
        self.tools(auto=True)
        self.autopilot()
        n = len(self.ai.calls("BODY of a cover letter"))
        pipeline.advance()
        self.assertEqual(len(self.ai.calls("BODY of a cover letter")), n)
        self.assertEqual(self.st(jid)["letter"]["state"], "stale")
        self.assertEqual(pipeline.run(jid, "letter", rerun=True)["outcome"], "done")
        st = self.st(jid)
        self.assertEqual((st["letter"]["state"], st["letter"]["rev"]), ("done", 2))
        self.assertTrue(list((d / "history").glob("cover_letter-*.md")))

    def test_jd_change_stales_score_and_tailor(self):
        jid = self.job()
        pipeline.run_to(jid, "tailor")
        resume.set_jd(jid, JD + " Also Kafka.")
        st = self.st(jid)
        self.assertEqual((st["score"]["state"], st["tailor"]["state"], st["research"]["state"]), ("stale", "stale", "done"))
        self.assertIn("job description changed", st["score"]["why"])

    def test_manual_work_is_adopted(self):
        jid = self.job()
        resume.tailor(db.get_job(jid))  # the drawer's whole-document Tailor
        st = self.st(jid)
        self.assertEqual((st["tailor"]["state"], st["tailor"]["origin"]), ("done", "observed"))
        self.assertEqual(st["score"]["state"], "ready")
        self.assertEqual(st["letter"]["state"], "todo")  # research is still missing


class Questions(Base):
    def test_question_raised_answered_resumes(self):
        jid = self.job()
        pipeline.skip(jid, "score")
        replies = iter([{"answer": "", "missing": "How many years have you worked with Kubernetes?"},
                        {"answer": "I have run Kubernetes clusters in production.", "missing": ""}])
        self.ai.facts = lambda p: next(replies)
        pipeline.add_form_questions(jid, ["Describe your experience with Kubernetes"])
        self.assertEqual(pipeline.run(jid, "answers")["outcome"], "waiting")
        qs = self.open_qs()
        self.assertEqual([(q["text"], q["kind"], q["waiting"]) for q in qs],
                         [("How many years have you worked with Kubernetes?", "number", 1)])
        st = self.st(jid)["answers"]
        self.assertEqual((st["state"], st["on"]), ("waiting", "you"))
        self.assertIn("(waiting for you)", self.doc(jid, "form_answers.md"))
        r = pipeline.answer(qs[0]["id"], "4 years")
        self.assertEqual(r["resumed"], [(jid, "answers")])
        self.assertEqual(self.st(jid)["answers"]["state"], "done")
        row = db.con().execute("SELECT * FROM answers WHERE id=?", (r["answer_id"],)).fetchone()
        self.assertEqual((row["answer"], row["source"]), ("4 years", f"answered for job #{jid} (answers)"))
        self.assertIn("I have run Kubernetes clusters in production.", self.doc(jid, "form_answers.md"))
        self.assertFalse([p for p in db.list_pending() if p["kind"] == "save_answer"])
        self.assertEqual(self.open_qs(), [])

    def test_no_duplicate_questions(self):
        self.assertEqual(pipeline.norm_q("Are you willing to relocate?"), "Willing to relocate")
        self.assertEqual(pipeline.norm_q("willing to relocate"), "Willing to relocate")
        a, b, c = self.job(name="A"), self.job(name="B"), self.job(name="C")
        for j, label in ((a, "Are you willing to relocate?"), (b, "willing to relocate")):
            pipeline.skip(j, "score")
            pipeline.add_form_questions(j, [label])
            self.assertEqual(pipeline.run(j, "answers")["outcome"], "waiting")
        qs = self.open_qs()
        self.assertEqual((len(qs), qs[0]["waiting"]), (1, 2))
        pipeline.ask(db.get_job(a), "answers", "Are you willing to relocate?")  # asking again adds nothing
        self.assertEqual((len(self.open_qs()), self.open_qs()[0]["waiting"]), (1, 2))
        r = pipeline.answer(qs[0]["id"], "Yes")
        self.assertEqual(sorted(r["resumed"]), [(a, "answers"), (b, "answers")])
        self.assertEqual((self.st(a)["answers"]["state"], self.st(b)["answers"]["state"]), ("done", "done"))
        pipeline.skip(c, "score")
        pipeline.add_form_questions(c, ["Would you relocate?"])
        self.assertEqual(pipeline.run(c, "answers")["outcome"], "done")
        out = self.st(c)["answers"]["output"]["answers"][0]
        self.assertEqual((out["answer"], out["source"]), ("Yes", f"bank #{r['answer_id']}"))
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM questions").fetchone()[0], 1)

    def test_job_scope_answer_keeps_question_for_others(self):
        a, b = self.job(name="A"), self.job(name="B")
        for j in (a, b):
            pipeline.skip(j, "score")
            pipeline.add_form_questions(j, ["Are you willing to relocate?"])
            pipeline.run(j, "answers")
        q = self.open_qs()[0]
        r = pipeline.answer(q["id"], "Only to Austin", scope="job", job_id=a)
        self.assertEqual((r["resumed"], r["answer_id"]), ([(a, "answers")], None))
        out = self.st(a)["answers"]["output"]["answers"][0]
        self.assertEqual((out["answer"], out["source"]), ("Only to Austin", "you"))
        left = self.open_qs()
        self.assertEqual([(x["id"], x["waiting"], x["job_id"]) for x in left], [(q["id"], 1, b)])
        self.assertEqual(self.st(b)["answers"]["state"], "waiting")
        self.assertIsNone(pipeline.known("Are you willing to relocate?"))

    def test_eligibility_never_ai(self):
        label = "Are you legally authorized to work in the United States?"
        self.assertEqual(pipeline.classify(label), "eligibility")
        self.assertEqual(pipeline.classify("What is your gender?"), "eeo")
        guard = self.ai.ask_json

        def no_label(prompt, *a, **k):
            self.assertNotIn("legally authorized", prompt)
            return guard(prompt, *a, **k)
        db.save_answer("Are you authorized to work in Canada for us", "No")  # a near match: never offered
        a, b = self.job(name="A"), self.job(name="B")
        with patched(ai, ask_json=no_label, ask=no_label):
            pipeline.skip(a, "score")
            pipeline.add_form_questions(a, [label, "What is your gender?"])
            self.assertEqual(pipeline.run(a, "answers")["outcome"], "waiting")
            for fn in (lambda: apply.answer(db.get_job(a), label),
                       lambda: drafts.options("answer", {"job": a, "question": label})):
                with self.assertRaisesRegex(SystemExit, "never drafts eligibility or EEO"):
                    fn()
            self.assertEqual(pipeline.suggestions(label), [])
            qs = {q["text"]: q for q in self.open_qs()}
            self.assertEqual(qs[label]["suggestions"], [])
            pipeline.answer(qs[label]["id"], "Yes")
            row = db.con().execute("SELECT * FROM answers WHERE question='Work authorization: united states'").fetchone()
            self.assertEqual(row["tags"], "eligibility")
            pipeline.skip(b, "score")
            pipeline.add_form_questions(b, ["Are you authorized to work in the United States?"])
            self.assertEqual(pipeline.run(b, "answers")["outcome"], "done")
        self.assertEqual(self.st(b)["answers"]["output"]["answers"][0]["answer"], "Yes")
        self.assertNotIn("Work authorization", "".join(self.ai.prompts))  # never handed to a model as a prior answer
        apply.answer(db.get_job(b), "Why this role?")
        self.assertNotIn("Work authorization", self.ai.prompts[-1])

    def test_private_never_in_employer_text(self):
        db.save_answer("Minimum salary I'd accept", "150k", private=True)
        jid = self.job()
        apply.answer(db.get_job(jid), "What salary would you accept?")
        self.assertNotIn("150k", self.ai.prompts[-1])
        self.assertNotIn("150k", drafts._situation("answer", db.get_job(jid), {"question": "minimum salary accept"}))
        self.assertEqual(pipeline.suggestions("The minimum salary you'd accept"), [])
        self.assertIsNone(pipeline.known("Minimum salary I'd accept", employer=True))
        self.assertIsNotNone(pipeline.known("Minimum salary I'd accept", employer=False))
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, ["Minimum salary I'd accept", "Desired salary"])
        self.assertEqual(pipeline.run(jid, "answers")["outcome"], "waiting")
        qs = {q["kind"]: q for q in self.open_qs()}
        self.assertIn("marked private", qs["private"]["text"])
        self.assertEqual(qs["private"]["scope_default"], "job")
        with self.assertRaisesRegex(SystemExit, "private floor"):
            pipeline.answer(qs["salary"]["id"], "$187,000")
        pipeline.answer(qs["salary"]["id"], "$170,000")
        pipeline.answer(qs["private"]["id"], "Open to discussing it", scope="reusable")  # private: this job only
        st = self.st(jid)["answers"]
        self.assertEqual(st["state"], "done")
        self.assertEqual({a["answer"] for a in st["output"]["answers"]}, {"Open to discussing it", "$170,000"})
        self.assertEqual(self.open_qs(), [])  # the private one is not asked again
        self.assertEqual(db.con().execute("SELECT answer, private FROM answers WHERE question=?",
                                          ("Minimum salary I'd accept",)).fetchone()["answer"], "150k")

    def test_open_ended_label_not_reused_verbatim(self):
        db.save_answer("Why do you want to work here?", "Because Globex rocks")
        jid = self.job()
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, ["Why do you want to work here?"])
        pipeline.run(jid, "answers")
        self.assertIn("Because Globex rocks", self.ai.calls("do not guess")[-1])
        out = self.st(jid)["answers"]["output"]["answers"][0]
        self.assertEqual((out["source"], out["answer"]), ("ai", "I would bring my pipeline work."))
        nokey = self.job(name="NoKey")  # no AI provider: you write it for this job; the bank row is not copied
        pipeline.skip(nokey, "score")
        pipeline.add_form_questions(nokey, ["Why do you want to work here?"])
        with patched(ai, available=lambda: []):
            self.assertEqual(pipeline.run(nokey, "answers")["outcome"], "waiting")
        q = self.open_qs()[0]
        self.assertEqual(q["scope_default"], "job")
        pipeline.answer(q["id"], "For the data platform")
        self.assertEqual(db.con().execute("SELECT answer FROM answers WHERE question=?",
                                          ("Why do you want to work here?",)).fetchone()["answer"], "Because Globex rocks")

    def test_rerun_redrafts_ai_answers_keeps_user_answers(self):
        jid = self.job()
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, ["Why this role?", "Are you willing to relocate?"])
        pipeline.run(jid, "answers")
        pipeline.answer(self.open_qs()[0]["id"], "Yes, to Austin", scope="job")
        self.assertEqual(self.st(jid)["answers"]["state"], "done")
        d = resume.app_dir(db.get_job(jid))
        (d / "resume.md").write_text("# Jane Doe\n- NEWRESUME pipelines\n", encoding="utf-8")
        self.assertEqual(self.st(jid)["answers"]["state"], "stale")
        n = len(self.ai.calls("do not guess"))
        self.assertEqual(pipeline.run(jid, "answers", rerun=True)["outcome"], "done")
        self.assertEqual(len(self.ai.calls("do not guess")), n + 1)
        self.assertIn("NEWRESUME", self.ai.calls("do not guess")[-1])
        got = {a["label"]: (a["answer"], a["source"]) for a in self.st(jid)["answers"]["output"]["answers"]}
        self.assertEqual(got["Are you willing to relocate?"], ("Yes, to Austin", "you"))

    def test_labels_added_during_run_survive(self):
        jid = self.job()
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, ["Why this role?"])

        def facts(prompt):  # the drawer (or the extension) adds a label while the stage runs
            pipeline.add_form_questions(jid, ["What is your favourite tool?"])
            return {"answer": "Because of the pipelines.", "missing": ""}
        self.ai.facts = facts
        pipeline.run(jid, "answers")
        st = self.st(jid)["answers"]
        self.assertEqual(st["output"]["form"], ["Why this role?", "What is your favourite tool?"])
        self.assertEqual(st["state"], "ready")
        self.assertIn("1 form question", st["why"])

    def test_delete_job_cleans_up(self):
        a, b = self.job(name="A"), self.job(name="B")
        for j, labels in ((a, ["Notice period?", "Are you willing to relocate?"]), (b, ["Willing to relocate"])):
            pipeline.skip(j, "score")
            pipeline.add_form_questions(j, labels)
            pipeline.run(j, "answers")
        db.delete_job(a)
        for t in ("pipeline", "pipeline_runs", "question_waiters"):
            self.assertEqual(db.con().execute(f"SELECT COUNT(*) FROM {t} WHERE job_id=?", (a,)).fetchone()[0], 0, t)
        qs = {q["key"]: q["status"] for q in pipeline.questions(all=True)}
        self.assertEqual(qs, {"Notice period": "dismissed", "Willing to relocate": "open"})


class Mail(Base):
    def test_thanks_uses_round_details(self):
        jid = self.job("interview")
        self.round(jid)
        self.tools(on=("thank_you",))
        st = self.st(jid)
        self.assertEqual(st["thanks"]["state"], "ready")
        pipeline.run(jid, "thanks")
        p = self.ai.calls("thank-you email")[-1]
        self.assertIn("Sam Lee", p)
        self.assertIn("roadmap", p)
        self.assertEqual(self.st(jid)["thanks"]["on"], "you")
        apply.thanks(db.get_job(jid))  # the drawer / CLI path gets the round too
        self.assertIn("roadmap", self.ai.calls("thank-you email")[-1])
        b = self.job("interview", name="B")
        self.round(b)
        settings.set_tool("email_reply", auto=True)
        self.autopilot()
        pipeline.advance()
        items = [p for p in db.list_pending() if p["job_id"] == b]
        self.assertEqual([(p["kind"], json.loads(p["payload"])["purpose"]) for p in items], [("send_email", "thanks")])
        self.assertEqual(self.sent, [])
        approvals.reject(items[0]["id"])
        self.assertEqual(self.st(b)["thanks"]["state"], "skipped")
        for _ in range(3):
            pipeline.advance()
        self.assertEqual(len([p for p in db.list_pending(None) if p["job_id"] == b]), 1)
        c = self.job("interview", name="C")
        self.round(c, days_ago=4)
        self.assertEqual(self.st(c)["thanks"]["state"], "skipped")
        d = self.job("interview", name="D", contact=False)
        self.round(d)
        pipeline.run(d, "thanks")
        q = self.open_qs()[0]
        self.assertEqual(q["apply_to"], "job:contact_email")
        with self.assertRaisesRegex(SystemExit, "one email address"):
            pipeline.answer(q["id"], "not an address")
        pipeline.answer(q["id"], "kim@d.example")
        self.assertEqual(db.get_job(d)["contact_email"], "kim@d.example")
        self.assertEqual(self.st(d)["thanks"]["state"], "done")  # your own run with email_reply on auto: sent
        self.assertEqual(self.sent[-1][0], "kim@d.example")

    def test_followup_carries_application_facts(self):
        jid = self.job("applied")
        db.add_mail(message_id=f"<c-{self.tag}@acme.example>", direction="in", job_id=jid, from_addr="jobs@acme.example",
                    subject="Application received", category="application_received", snippet="Your reference number: ABC123.",
                    trusted=True, linked_by="auto")
        self.assertEqual(pipeline.confirmation_ref(jid), "ABC123")
        self.assertEqual(self.st(jid)["confirm"]["output"]["ref"], "ABC123")
        db.con().execute("UPDATE events SET ts=datetime('now', '-30 days') WHERE job_id=?", (jid,))
        db.con().commit()
        loop._followups(SimpleNamespace(followup=None, provider=None))
        p = self.ai.calls("follow-up email")[-1]
        applied = db.get_job(jid)["applied_at"]
        self.assertIn("ABC123", p)
        self.assertIn(applied, p)
        for item in db.list_pending():
            approvals.reject(item["id"])
        with patched(ai, available=lambda: []):
            body = apply.followup(db.get_job(jid))["draft"]["body"]
        self.assertIn("(reference ABC123)", body)
        self.assertIn(applied, body)


class Autopilot(Base):
    def test_approvals_gate_everything(self):
        jid = self.job("interview")
        self.round(jid)
        self.tools(auto=True)
        settings.set_tool("email_reply", auto=True)
        self.autopilot()

        def boom(*a, **k):
            raise AssertionError("Autopilot acted directly")
        with patched(db, set_status=boom, add_job=boom), patched(approvals, send_email=boom):
            res = pipeline.advance()
        self.assertEqual([r["stage"] for r in res["ran"]], ["research", "prep", "thanks"])
        p = [x for x in db.list_pending() if x["job_id"] == jid]
        self.assertEqual([(x["kind"], x["status"]) for x in p], [("send_email", "pending")])
        st = self.st(jid)
        self.assertEqual((st["apply"]["state"], st["thanks"]["on"]), ("done", "you"))
        self.assertIn("PREPMARK", self.doc(jid, "interview_prep.md"))

    def test_non_auto_tools_propose_one_run_to(self):
        a = self.job(name="A")
        self.autopilot()
        pipeline.advance()
        items = [p for p in db.list_pending() if p["job_id"] == a]
        self.assertEqual([p["kind"] for p in items], ["run_to"])
        pl = json.loads(items[0]["payload"])
        self.assertEqual((pl["to"], pl["stages"], pl["from_status"]), ("letter", ["score", "research", "tailor", "letter"], "saved"))
        self.assertIn("about 4 AI calls", items[0]["summary"])
        self.assertEqual(self.st(a)["score"]["on"], "you")
        pipeline.advance()
        approvals.reject(items[0]["id"])
        pipeline.advance()
        self.assertEqual(len([p for p in db.list_pending(None) if p["job_id"] == a]), 1)
        self.assertEqual(self.ai.prompts, [])
        b = self.job(name="B")
        pipeline.advance()
        pb = next(p for p in db.list_pending() if p["job_id"] == b)
        r = approvals.approve(pb["id"])
        self.assertEqual(r["status"], "done")
        self.assertTrue(r["result"].startswith(f"started #{b} to letter"))
        self.assertEqual(self.st(b)["letter"]["state"], "done")
        self.assertEqual({x["origin"] for x in pipeline.log_runs(b)}, {"approved"})
        c = self.job(name="C")
        pipeline.advance()
        pc = next(p for p in db.list_pending() if p["job_id"] == c)
        db.set_status(c, "applied")
        row = db.get_pending(pc["id"])
        self.assertEqual(row["status"], "rejected")
        self.assertTrue(row["result"].startswith("stale:"))
        d = self.job("applied", name="D")
        db.con().execute("UPDATE events SET ts=datetime('now', '-30 days') WHERE job_id=?", (d,))
        db.con().commit()
        self.assertIn(d, [j["id"] for j in db.needs_followup(7)])
        pid = approvals.propose("fit_check", "run_to", {"job_id": d, "to": "letter", "stages": []}, "x", d,
                                force_pending=True)["id"]
        approvals.reject(pid)
        pid = approvals.propose("fit_check", "run_to", {"job_id": d, "to": "letter", "stages": []}, "x", d,
                                force_pending=True)["id"]
        approvals.approve(pid)
        self.assertIn(d, [j["id"] for j in db.needs_followup(7)])
        with self.assertRaises(approvals.Stale):
            approvals._run_to({"job_id": d, "to": "letter", "from_status": "saved"})
        with self.assertRaisesRegex(SystemExit, "unknown step"):
            approvals._run_to({"job_id": d, "to": "nope"})

    def test_budget_respected(self):
        jobs = [self.job(name=n) for n in "ABC"]
        self.tools(auto=True)
        self.autopilot(autopilot_ai_per_cycle=2)
        res = pipeline.advance()
        self.assertEqual(sum(r["ai"] for r in res["ran"]), 2)
        self.assertEqual(len(res["ran"]), 2)
        self.assertIn("per-cycle AI budget reached (2/2 this cycle", loop.STATUS["last_error"])
        db.con().execute("INSERT INTO pipeline_runs(job_id, stage, origin, outcome, ai) VALUES(?, 'x', 'autopilot', 'done', 1)",
                         (jobs[0],))
        db.con().commit()
        self.autopilot(autopilot_ai_per_cycle=6, autopilot_ai_per_day=3)
        self.assertEqual(pipeline.advance()["ran"], [])
        self.assertIn("daily AI budget reached (3/3 in 24 h)", loop.STATUS["last_error"])
        self.autopilot(autopilot_ai_per_day=30, autopilot_jobs_per_cycle=1)
        res = pipeline.advance()
        self.assertEqual(len({r["job_id"] for r in res["ran"]}), 1)
        settings.set_pref("autopilot", "off")
        last = jobs[-1]
        (resume.app_dir(db.get_job(last)) / "resume.md").write_text("# Jane Doe\n- by hand\n", encoding="utf-8")
        n = len(self.ai.prompts)
        self.assertEqual(pipeline.advance()["ran"], [])
        self.assertEqual(len(self.ai.prompts), n)
        self.assertEqual(self.st(last, save=False)["tailor"]["origin"], "observed")

    def test_answers_budget_counts_real_calls(self):
        jid = self.job()
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, [f"Tell us about project number {i}?" for i in range(5)])
        self.tools(auto=True, on=("form_answers",))
        self.autopilot(autopilot_ai_per_cycle=3)
        res = pipeline.advance()
        self.assertEqual([(r["stage"], r["ai"]) for r in res["ran"]], [("answers", 3)])
        self.assertEqual(pipeline.log_runs(jid)[0]["ai"], 3)
        st = self.st(jid)["answers"]
        self.assertEqual((st["state"], len(st["output"]["answers"])), ("ready", 3))
        pipeline.advance()
        st = self.st(jid)["answers"]
        self.assertEqual((st["state"], len(st["output"]["answers"])), ("done", 5))

    def test_autopilot_waiter_not_kicked(self):
        jid = self.job()
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, ["Why us?", "Are you willing to relocate?"])
        self.tools(auto=True, on=("form_answers",))
        self.autopilot()
        pipeline.advance()
        self.assertEqual(self.st(jid)["answers"]["state"], "waiting")
        settings.set_pref("autopilot", "off")
        n = len(self.ai.prompts)
        r = pipeline.answer(self.open_qs()[0]["id"], "Yes")
        self.assertEqual(r["resumed"], [(jid, "answers")])
        self.assertEqual(len(self.ai.prompts), n)
        self.assertEqual(self.st(jid)["answers"]["state"], "ready")
        u = self.job(name="U")
        pipeline.skip(u, "score")
        pipeline.add_form_questions(u, ["Notice period?"])
        pipeline.run(u, "answers")  # your click: answering continues it at once
        pipeline.answer(self.open_qs()[0]["id"], "Two weeks")
        self.assertEqual(self.st(u)["answers"]["state"], "done")

    def test_failure_isolated_and_retry(self):
        a, b = self.job(name="A"), self.job(name="B")
        for j in (a, b):
            pipeline.run(j, "score")
        self.tools(auto=True, on=("research",))
        self.autopilot()
        real, tries = extras.research, []

        def research(job, provider=None):
            if job["id"] == a:
                tries.append(1)
                raise SystemExit("no key")
            return real(job, provider)
        with patched(extras, research=research):
            pipeline.advance()
            st = self.st(a)["research"]
            self.assertEqual((st["state"], st["error"]), ("error", "no key"))
            self.assertEqual(self.st(b)["research"]["state"], "done")
            pipeline.advance()
            pipeline.advance()
            self.assertEqual(len(tries), 2)
        self.assertEqual(pipeline.run(a, "research")["outcome"], "done")

    def test_fit_gate_autopilot_only(self):
        jid = self.job()
        self.ai.verdict = "skip"
        pipeline.run(jid, "score")
        self.assertTrue(pipeline.fit_skip(pipeline.status(jid)))
        self.assertTrue(pipeline.summary()[jid]["fit_skip"])
        self.tools(auto=True)
        self.autopilot()
        self.assertEqual(pipeline.advance()["ran"], [])
        self.assertEqual([r["stage"] for r in pipeline.run_to(jid, "letter")], ["research", "tailor", "letter"])


class Engine(Base):
    def test_claim_prevents_double_run(self):
        jid = self.job()
        self.assertTrue(pipeline._claim(jid, "score", None))  # another thread holds it
        with self.assertRaisesRegex(SystemExit, "running"):
            pipeline.run(jid, "score")
        with self.assertRaisesRegex(SystemExit, "already running"):
            with pipeline.claimed(jid, "score"):
                pass
        self.assertFalse(pipeline._claim(jid, "score", None))
        db.con().execute("UPDATE pipeline SET state='error' WHERE job_id=?", (jid,))
        db.con().commit()
        self.assertFalse(pipeline._claim(jid, "score", "2000-01-01 00:00:00.000000"))  # read before the row changed
        self.assertEqual(self.ai.prompts, [])
        with pipeline.claimed(jid, "tailor"):  # a drawer button doing the work by hand
            resume.tailor(db.get_job(jid))
        st = self.st(jid)["tailor"]
        self.assertEqual((st["state"], st["origin"]), ("done", "observed"))

    def test_interrupted_running_reads_error_and_can_rerun(self):
        jid = self.job()
        old = (datetime.now(timezone.utc) - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S.%f")
        db.con().execute("INSERT INTO pipeline(job_id, stage, state, updated_at) VALUES(?, 'score', 'running', ?)", (jid, old))
        db.con().commit()
        st = self.st(jid)["score"]
        self.assertEqual(st["state"], "error")
        self.assertIn("interrupted", st["why"])
        self.assertEqual(pipeline.run(jid, "score")["outcome"], "done")

    def test_pipeline_writes_no_events(self):
        jid = self.job("applied")
        before = [tuple(e) for e in db.events(jid)]
        pipeline.status(jid)
        pipeline.skip(jid, "letter")
        pipeline.skip(jid, "letter", on=False)
        pipeline.advance()
        self.autopilot()
        pipeline.advance()
        self.assertEqual([tuple(e) for e in db.events(jid)], before)
        s = self.job()
        n = len(db.events(s))
        pipeline.run(s, "score")
        self.assertEqual({e["kind"] for e in db.events(s)[n:]}, {"gap"})  # the stage function's own event only

    def test_relevance_skip_and_registry(self):
        jid = self.job("interview")
        st = self.st(jid)
        self.assertEqual((st["score"]["state"], st["research"]["state"], st["offer"]["state"], st["close"]["state"]),
                         ("skipped", "ready", "later", "later"))
        pipeline.skip(jid, "research")
        self.assertEqual(self.st(jid)["prep"]["state"], "ready")  # a skipped need counts
        pipeline.skip(jid, "research", on=False)
        self.assertEqual(self.st(jid)["research"]["state"], "ready")
        db.set_status(jid, "rejected")
        st = self.st(jid)
        self.assertEqual((st["close"]["state"], st["research"]["state"]), ("done", "skipped"))
        with self.assertRaises(ValueError):
            pipeline.register(pipeline.Stage("bad", "Bad", ("saved",), needs=("later_one",)))
        with self.assertRaisesRegex(SystemExit, "unknown step"):
            pipeline.run(jid, "nope")


class Fixes(Base):
    """Pass 16.5 review findings: one regression test each."""

    def answers_job(self, labels, name="A"):
        jid = self.job(name=name)
        pipeline.skip(jid, "score")
        pipeline.add_form_questions(jid, labels)
        return jid

    def test_canon_legal_wording_is_never_ai_and_ai_rows_are_not_reused(self):  # code-1
        legal = ("Are you legally eligible to work in Canada?", "Are you 18 years or older?",
                 "Are you permitted to work in the UK?", "Are you legally able to work in the United States?")
        for q in legal:
            self.assertTrue(pipeline.never_ai(q), q)
            self.assertEqual(pipeline.classify(q), "eligibility")
            with self.assertRaisesRegex(SystemExit, "never drafts eligibility or EEO"):
                apply.answer(db.get_job(self.job(name="X")), q)
        self.assertEqual(self.ai.prompts, [])
        r = apply.answer(db.get_job(self.job(name="Y")), "Why this role?")  # an AI draft proposed for the bank says so
        approvals.approve(r["proposal"]["id"])
        self.assertTrue(db.con().execute("SELECT source FROM answers WHERE question='Why this role?'").fetchone()[0].startswith("AI"))
        db.save_answer(legal[0], "Plain answer.", "Beta", source="AI draft for job #1")  # an approved AI draft
        db.save_answer(legal[1], "Yes")  # a row from before the source column
        a = self.answers_job(list(legal[:2]))
        self.assertEqual(pipeline.run(a, "answers")["outcome"], "waiting")
        self.assertNotIn("Plain answer.", self.doc(a, "form_answers.md"))
        self.assertEqual(len(self.open_qs()), 2)
        for q in self.open_qs():
            pipeline.answer(q["id"], "Yes, no sponsorship needed" if "Canada" in q["text"] else "Yes")
        b = self.answers_job([legal[0]], name="B")
        self.assertEqual(pipeline.run(b, "answers")["outcome"], "done")
        self.assertEqual(self.st(b)["answers"]["output"]["answers"][0]["answer"], "Yes, no sponsorship needed")
        db.save_answer("Typed eligibility", "x", source="typed under Answers")
        self.assertTrue(pipeline.yours("typed under Answers") and not pipeline.yours(None) and not pipeline.yours("AI draft"))

    def test_untagged_eeo_and_eligibility_rows_stay_out_of_prompts(self):  # code-2
        db.save_answer("Do you have a disability?", "Yes: ADHD, I need extra time")
        db.save_answer("What is your gender?", "Female")
        db.save_answer("Are you authorized to work in the US?", "Yes WORKAUTH")
        db.save_answer("Why do you like data?", "LIKEDATA")
        self.assertEqual([r["question"] for r in db.employer_answers()], ["Why do you like data?"])
        jid = self.answers_job(["Tell us about yourself"])
        pipeline.run(jid, "answers")
        apply.answer(db.get_job(jid), "Why do you like this data role?")
        for p in self.ai.calls("PRIOR ANSWERS"):
            for secret in ("ADHD", "Female", "WORKAUTH"):
                self.assertNotIn(secret, p)
        self.assertIn("LIKEDATA", self.ai.prompts[-1])
        self.assertEqual(pipeline.suggestions("Do you have a disability we should know about?"), [])
        self.assertEqual(pipeline.suggestions("What is your gender identity?"), [])

    def test_different_legal_questions_keep_their_own_keys(self):  # code-3
        pairs = (("Do you have any pending criminal charges?", "Have you ever been convicted of a felony?"),
                 ("What is your gender identity?", "What was your sex assigned at birth?"),
                 ("Will you sponsor your own relocation costs?", "Will you require visa sponsorship?"),
                 ("Start date of your current role", "What is your earliest start date?"))
        for x, y in pairs:
            self.assertNotEqual(pipeline.norm_q(x), pipeline.norm_q(y), (x, y))
        self.assertEqual(pipeline.norm_q("When can you start?"), "Earliest start date")
        self.assertEqual(pipeline.norm_q("Will you now or in the future require sponsorship for employment?"),
                         "Visa sponsorship required")
        a = self.job(name="A")
        self.assertEqual(pipeline.add_form_questions(a, list(pairs[0])), 2)  # both labels stay on the form
        db.save_answer(pairs[0][1], "No", source="typed under Answers")
        b = self.answers_job([pairs[0][0]], name="B")
        self.assertEqual(pipeline.run(b, "answers")["outcome"], "waiting")  # never answered from the felony row
        self.assertEqual([q["text"] for q in self.open_qs()], [pairs[0][0]])
        c = self.answers_job(["Have you been convicted of a felony?"], name="C")
        self.assertEqual(pipeline.run(c, "answers")["outcome"], "done")

    def test_rerun_looks_bank_answers_up_again(self):  # code-4
        db.save_answer("Desired salary", "$150,000", source="typed under Answers")
        jid = self.answers_job(["What are your salary expectations?"])
        pipeline.run(jid, "answers")
        self.assertIn("$150,000", self.doc(jid, "form_answers.md"))
        db.save_answer("Desired salary", "$160,000", source="typed under Answers")
        pipeline.run(jid, "answers", rerun=True)
        self.assertIn("$160,000", self.doc(jid, "form_answers.md"))
        db.save_answer("Desired salary", "$165,000", private=True, source="typed under Answers")
        self.assertEqual(pipeline.run(jid, "answers", rerun=True)["outcome"], "waiting")
        doc = self.doc(jid, "form_answers.md")
        self.assertNotIn("$16", doc)
        self.assertIn("(waiting for you)", doc)

    def test_approved_batch_spends_inside_the_daily_budget_and_is_estimated(self):  # code-5, live-6
        jid = self.job()
        pipeline.add_form_questions(jid, [f"Describe project {w} in detail" for w in "abcdefghijkl"])
        self.autopilot(autopilot_ai_per_day=2, autopilot_ai_per_cycle=2)
        pipeline.advance()
        item = next(p for p in db.list_pending() if p["job_id"] == jid)
        self.assertIn("about 12 AI calls", item["summary"])  # 4 documents + 8 drafted labels (the click budget)
        approvals.approve(item["id"])
        self.assertEqual(pipeline.spent_today(), 2)
        self.assertIn("daily AI budget reached (2/2 in 24 h)", loop.STATUS["last_error"])
        self.assertEqual(self.st(jid)["tailor"]["state"], "ready")

    def test_untrusted_confirmation_is_never_quoted(self):  # code-6
        jid = self.job("applied")
        db.add_mail(message_id=f"<u-{self.tag}@acme-careers.example>", direction="in", job_id=jid, from_addr="x@acme-careers.example",
                    subject="Application received", category="application_received", snippet="Reference number: EVIL-0666.",
                    trusted=False, linked_by="auto")
        self.assertEqual(pipeline.confirmation_ref(jid), "")
        self.assertNotEqual(self.st(jid)["confirm"]["state"], "done")
        with patched(ai, available=lambda: []):
            self.assertNotIn("EVIL", apply.followup(db.get_job(jid))["draft"]["body"])

    def backdated_interview_job(self, round_days_ago):
        jid = self.job("interview")
        self.round(jid, days_ago=round_days_ago)
        db.con().execute("UPDATE events SET ts=datetime('now', '-10 days') WHERE job_id=?", (jid,))
        db.con().commit()
        return jid

    def test_research_and_prep_runs_leave_the_followup_clock(self):  # code-7, live-1
        jid = self.backdated_interview_job(10)
        self.assertIn(jid, [j["id"] for j in db.needs_followup(7)])
        for stage in ("research", "prep"):
            self.assertEqual(pipeline.run(jid, stage, "autopilot")["outcome"], "done")
        self.assertTrue({"research", "interview_prep"} <= {e["kind"] for e in db.events(jid)})
        self.assertIn(jid, [j["id"] for j in db.needs_followup(7)])

    def test_followup_line_names_a_booked_round(self):  # live-3
        jid = self.backdated_interview_job(-3)
        self.assertNotIn(jid, [j["id"] for j in db.needs_followup(7)])
        f = self.st(jid)["followup"]
        self.assertEqual((f["state"], f["on"]), ("waiting", "employer"))
        self.assertIn("interview is booked", f["why"])
        self.assertNotIn("monitor loop drafts it", f["why"])

    def test_job_only_fact_reaches_the_redraft(self):  # code-8
        self.ai.facts = lambda p: ({"answer": "I ran three EKS clusters.", "missing": ""} if "Three EKS" in p
                                   else {"answer": "", "missing": "Which Kubernetes clusters have you run?"})
        jid = self.answers_job(["Describe your experience with Kubernetes"])
        self.assertEqual(pipeline.run(jid, "answers")["outcome"], "waiting")
        q = self.open_qs()[0]
        pipeline.answer(q["id"], "Three EKS clusters at Initech", scope="job")
        doc = self.doc(jid, "form_answers.md")
        self.assertIn("I ran three EKS clusters.", doc)
        self.assertNotIn("left for you", doc)
        self.assertIsNone(pipeline.known("Which Kubernetes clusters have you run?"))  # never in the bank

    def test_question_of_a_job_deleted_mid_run_is_dropped(self):  # code-9
        jid = self.answers_job(["Which cloud do you know best and why?"])

        def gone(p):
            db.delete_job(jid)
            return {"answer": "", "missing": "Which cloud do you know best?"}
        self.ai.facts = gone
        pipeline.run(jid, "answers")
        pipeline.advance()
        self.assertEqual(self.open_qs(), [])
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM question_waiters").fetchone()[0], 0)

    def test_run_to_approval_lists_the_saved_answers_it_fills_in(self):  # live-2, live-7
        label = "Are you legally authorized to work in the United States?"
        aid = db.save_answer(label, "Yes, without sponsorship.", source="typed under Answers")
        jid = self.job()
        pipeline.add_form_questions(jid, [label, "Why us?"])
        self.autopilot()
        pipeline.advance()
        item = next(p for p in db.list_pending() if p["job_id"] == jid)
        self.assertIn("about 5 AI calls; fills in 1 saved answer", item["summary"])
        self.assertEqual(json.loads(item["payload"])["reuse"],
                         [{"label": label, "answer": "Yes, without sponsorship.", "source": f"bank #{aid}"}])
        self.assertEqual(pipeline.summary()[jid]["you"], 1)
        approvals.reject(item["id"])
        self.assertEqual((pipeline.summary()[jid]["you"], pipeline.summary()[jid]["next"]), (0, "score"))


class Cli(Base):
    def out(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["pipeline", *map(str, argv)])
        return buf.getvalue()

    def test_cli_smoke(self):
        jid = self.job()
        self.assertIn("next: score", self.out("status"))
        self.assertIn("ready", self.out("status", jid))
        self.assertIn("research: done", self.out("run", jid, "--to", "research"))
        self.assertIn("letter: skipped", self.out("skip", jid, "letter").replace("#" + str(jid) + " ", ""))
        f = Path(tempfile.mkdtemp()) / "q.txt"
        f.write_text("Are you willing to relocate?\n\n", encoding="utf-8")
        self.assertIn("1 new form question", self.out("add-questions", jid, f))
        self.out("run", jid, "--stage", "answers")
        listing = self.out("questions")
        self.assertIn("Willing to relocate", listing.replace("Are you willing to relocate?", "Willing to relocate"))
        qid = self.open_qs()[0]["id"]
        self.assertIn(f"#{jid} answers", self.out("answer", qid, "Yes"))
        self.assertIn("Autopilot: on", self.out("autopilot", "on"))
        self.assertIn("Autopilot: off", self.out("autopilot", "off"))
        self.assertIn("research", self.out("log", jid))
        shutil.rmtree(f.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
