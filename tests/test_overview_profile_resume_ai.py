"""Overview fixes, profile / resume / AI: the salary floor kept out of cover letters (gap fields and the saved letter),
provider names checked, the local preset applied only when Ollama answers, the allowlist binding the default provider,
LinkedIn PDF sidebars not read as certifications, a council judge that cannot sink the synthesis, every send_email /
save_answer proposal screened, master rebuilds that keep hand-typed roles, edited job documents kept in history/, and
private answers that never reach an employer-facing prompt or form. Plus small improvements: LinkedIn dates, bullet
drops unchecked, the template sign-off name, refined idea scores.
No network: AI calls are faked; every patched attribute and environment variable is put back."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, approvals, cli, db, drafts, extras, ideas, profile, resume, settings  # noqa: E402
from lodestar.config import APPS_DIR, PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AI_REAL = {n: getattr(ai, n) for n in ("ask", "chat", "default_provider")}  # at import: some older tests leave fakes behind
REAL = ("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Summary\nData engineer.\n## Skills\nPython, SQL\n"
        "## Experience\n### Data Engineer - Globex (2020-01 - Present)\n- Built data pipelines in Python\n"
        "\n## Preferences\nSalary floor: $187,000 | Deal-breakers: no crypto\n")
JD = "Build data pipelines in Python and SQL. Kafka a plus."
LINKEDIN_PDF = """Contact
dana@example.com
www.linkedin.com/in/dana-ex
Top Skills
Apache Kafka
Languages
French (Native)
Certifications
AWS Certified Data Engineer
Dana Example
Senior Data Engineer at Acme Corp
Austin, Texas, United States
Summary
I build data platforms.
Experience
Acme Corp
Senior Data Engineer
Education
University of Texas at Austin
Bachelor of Science, Computer Science (2012 - 2016)
Page 1 of 2
"""


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_cli(*argv) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(argv))
    return out.getvalue()


class Base(unittest.TestCase):
    """In-memory database, a profile with a private salary floor, an empty bank and default settings; all put back."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")
        self.jid = db.add_job("Floorco Overview", "Data Engineer", jd=JD)
        self.job = db.get_job(self.jid)
        self.dir = resume.app_dir(self.job)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)


class CoverLetter(Base):
    def test_cover_letter_keeps_the_floor_out_of_prompt_and_letter(self):  # row 01
        (self.dir / "gap.json").write_text(json.dumps({"missing_keywords": ["kafka"], "weak_areas": [
            "posting pay is below your $187,000 salary floor", "no Kafka in production"]}), encoding="utf-8")
        prompts, reply = [], ["Hello. I built data pipelines in Python."]

        def ask(prompt, system=None, provider=None, **kw):
            prompts.append(prompt)
            return reply[0]
        with patched(ai, ask=ask):
            out = resume.cover_letter(self.job)
            self.assertNotIn("187", prompts[0])
            self.assertNotIn("salary floor", prompts[0])
            self.assertIn("no Kafka in production", prompts[0])  # the rest of the gap check still helps
            self.assertIn("I built data pipelines", out.read_text(encoding="utf-8"))
            reply[0] = "I would need at least $187,000 to make this move."
            with self.assertRaises(SystemExit) as e:
                resume.cover_letter(self.job)
        self.assertIn("salary floor", str(e.exception))
        self.assertNotIn("187", out.read_text(encoding="utf-8"))  # the earlier letter is untouched


class Providers(Base):
    def test_provider_names_are_checked_not_a_keyerror(self):  # row 02
        with self.assertRaises(SystemExit) as e:
            settings.set_pref("provider", "bogus")
        self.assertIn("anthropic", str(e.exception))
        settings.set_pref("provider", " Anthropic ")
        self.assertEqual(settings.pref("provider"), "anthropic")
        self.assertIn("", settings.CHOICES["provider"])  # the Setup field is a select: '' = automatic
        self.assertIn("ollama", settings.CHOICES["provider"])
        settings.save({"tools": {}, "prefs": {"provider": "bogus"}})  # an old settings.json
        with patched(ai, **AI_REAL), self.assertRaises(SystemExit) as e:
            run_cli("ask", "hi")
        self.assertIn("unknown AI provider 'bogus'", str(e.exception))
        with patched(ai, **AI_REAL), self.assertRaises(SystemExit):
            ai.chat([{"role": "user", "content": "x"}], provider="nosuch")

    def test_local_preset_changes_nothing_when_ollama_does_not_answer(self):  # row 03
        before = ai.available()
        with env(OLLAMA_MODEL=None), patched(ai, pick_model=lambda name: None):
            msg = ai.local_preset()
            self.assertIn("NOT applied", msg)
            self.assertEqual((settings.pref("provider"), settings.pref("council_providers")), ("", ""))
            self.assertEqual(ai.available(), before)
        with env(OLLAMA_MODEL=None), patched(ai, pick_model=lambda name: "llama3.1:8b"):
            self.assertIn("llama3.1:8b", ai.local_preset())
        self.assertEqual((settings.pref("provider"), settings.pref("council_providers")), ("ollama", "ollama"))

    def test_allowlist_binds_the_default_provider(self):  # row 04
        with env(OPENAI_API_KEY="k", LODESTAR_PROVIDER=None), patched(ai, **AI_REAL):
            settings.set_pref("council_providers", "anthropic")
            settings.set_pref("provider", "openai")
            with self.assertRaises(SystemExit) as e:
                ai.default_provider()
            self.assertIn("council_providers", str(e.exception))
            settings.set_pref("provider", "")
            with env(LODESTAR_PROVIDER="openai"), self.assertRaises(SystemExit):
                ai.default_provider()
            self.assertEqual(ai.default_provider(), "anthropic")
            settings.set_pref("provider", "anthropic")
            self.assertEqual(ai.default_provider(), "anthropic")

    def test_council_judge_failure_keeps_the_synthesis(self):  # row 06
        seen = []

        def ask(prompt, system=None, provider=None, **kw):
            seen.append(provider)
            if provider == "openai":
                raise RuntimeError("openai down")
            return "synth" if "Several assistants" in prompt else f"{provider} answer"
        settings.set_pref("council_judge", True)
        with patched(ai, ask=ask):
            r = ai.council("q", providers=["anthropic", "openai"])
        self.assertEqual(r["synthesis"], "synth")
        self.assertEqual(seen, ["anthropic", "openai", "anthropic"])  # no judge: the only other provider just failed

        def ask2(prompt, system=None, provider=None, **kw):
            seen.append(provider)
            if "independent judge" in prompt:
                raise SystemExit("gemini: the model 'x' was rejected")
            return "synth" if "Several assistants" in prompt else "a"
        seen.clear()
        with patched(ai, ask=ask2):
            r = ai.council("q", providers=["anthropic", "gemini"])
        self.assertEqual((r["synthesis"], seen[-1]), ("synth", "gemini"))  # judged by the other one; failure kept it


class Guards(Base):
    def test_every_send_email_and_save_answer_proposal_is_screened(self):  # row 07
        with self.assertRaises(SystemExit):
            approvals.propose("followup", "send_email", {"to": "pat@globex.example", "subject": "Hi",
                                                         "body": "I need at least $187,000."}, "x", self.jid)
        with self.assertRaises(SystemExit):
            approvals.propose("answers", "save_answer", {"question": "Pay?", "answer": "My minimum is $187k."}, "x")
        self.assertEqual(db.list_pending("pending"), [])
        db.update_job(self.jid, contact_email="pat@globex.example")
        with patched(ai, ask_json=lambda *a, **k: {"subject": "Following up", "body": "I need at least $187,000."}), \
                patched(ai, available=lambda: ["anthropic"]), self.assertRaises(SystemExit):
            apply.followup(db.get_job(self.jid))
        self.assertEqual(db.list_pending("pending"), [])
        ok = approvals.propose("answers", "save_answer", {"question": "Why us?", "answer": "Your data platform."}, "x")
        self.assertEqual(ok["status"], "pending")

    def test_a_refused_mail_reply_is_logged_and_the_scan_goes_on(self):  # row 07, background path
        from lodestar import email_monitor
        info = {"category": "interview", "from": "pat@globex.example", "subject": "Interview", "body": "Tuesday?",
                "sender_email": "pat@globex.example", "trusted": True, "message_id": "<m1@globex.example>"}
        with patched(ai, ask_json=lambda *a, **k: {"subject": "Re: Interview", "body": "Fine, at $187,000 minimum."}), \
                patched(email_monitor, notify=lambda *a, **k: None):
            email_monitor._maybe_reply(info, self.job)  # no SystemExit escapes into the mailbox loop
        self.assertEqual(db.list_pending("pending"), [])
        self.assertTrue(any(e["detail"].startswith("draft refused") for e in db.events(self.jid)))

    def test_linkedin_pdf_sidebar_is_not_read_as_certifications(self):  # row 05
        f = profile.extract_heuristic(LINKEDIN_PDF)
        self.assertEqual([c["name"] for c in f["certifications"]], ["AWS Certified Data Engineer"])
        self.assertEqual([e["school"] for e in f["education"]],
                         ["University of Texas at Austin", "Bachelor of Science, Computer Science (2012 - 2016)"])
        self.assertEqual([s["name"] for s in f["skills"]], ["Apache Kafka"])
        md = profile.extract_heuristic("## Certifications\n- CKA (2021)\n- Scrum Master\n## Education\nBSc, MIT, 2016\n")
        self.assertEqual([c["name"] for c in md["certifications"]], ["CKA (2021)", "Scrum Master"])
        self.assertEqual(len(md["education"]), 1)


class Master(Base):
    def test_rebuild_keeps_roles_typed_into_the_master(self):  # row 14
        bank = profile.load()
        profile.merge(bank, {"skills": [{"name": "Kafka"}], "education": [{"school": "UT Austin", "degree": "BSc"}],
                             "certifications": [{"name": "CKA", "issuer": "CNCF"}]}, "resume:docx")
        profile.save(bank)
        profile.write_master(REAL.replace("## Preferences", "### Lead Engineer - Beta Labs (2017-01 - 2019-12)\n"
                                          "- Led a team of 4\n\n## Preferences"))
        profile.rebuild_master()
        once = PROFILE.read_text(encoding="utf-8")
        for s in ("Beta Labs", "Led a team of 4", "Globex", "Kafka", "Data engineer.", "Salary floor: $187,000"):
            self.assertIn(s, once)
        profile.rebuild_master()
        twice = PROFILE.read_text(encoding="utf-8")
        self.assertEqual(twice.count("UT Austin"), 1)  # a rebuild re-reading its own lines adds nothing
        self.assertEqual(twice.count("CKA"), 1)
        self.assertEqual(twice.count("Data engineer."), 1)

    def test_adjust_save_and_editor_save_keep_the_old_version(self):  # row 24
        resume.write_doc(self.dir / "resume.md", "# Jane Doe\nv1 Python\n")
        with patched(ai, ask=lambda *a, **k: "# Jane Doe\nv2 Python SQL\n"):
            run_cli("resume", "adjust", "shorter", "--job", str(self.jid), "--save")
        self.assertEqual((self.dir / "resume.md").read_text(encoding="utf-8"), "# Jane Doe\nv2 Python SQL\n")
        old = list((self.dir / "history").glob("resume-*.md"))
        self.assertEqual([p.read_text(encoding="utf-8") for p in old], ["# Jane Doe\nv1 Python\n"])
        self.assertTrue(db.get_job(self.jid)["resume_hash"])
        resume.save_doc(db.get_job(self.jid), "cover_letter.md", "letter 1")
        resume.save_doc(db.get_job(self.jid), "cover_letter.md", "letter 2")
        self.assertEqual(len(list((self.dir / "history").glob("cover_letter-*.md"))), 1)
        web = (ROOT / "lodestar" / "web.py").read_text(encoding="utf-8")
        self.assertIn("save_doc(job, name,", web)  # the drawer's Save document goes through the same path
        self.assertNotIn("/ name).write_text(", web)


class PrivateAnswers(Base):
    def setUp(self):
        super().setUp()
        db.save_answer("Desired salary?", "187000", private=True)  # allowed: it stays yours
        db.save_answer("Notice period?", "Two weeks, but I would leave sooner for the right deal.", private=True)
        db.save_answer("Why data engineering?", "I like building reliable pipelines.")
        db.con().execute("INSERT INTO answers(question, answer) VALUES('Old pay answer', 'My expected pay is 187k')")
        db.con().commit()  # saved before the guard existed

    def test_private_and_floor_answers_never_reach_employer_prompts(self):
        self.assertEqual([a["question"] for a in db.list_answers(employer=True)], ["Why data engineering?"])
        with self.assertRaises(SystemExit) as e:
            db.save_answer("Expected salary?", "$187,000")
        self.assertIn("private", str(e.exception))
        prompts = []
        with patched(ai, ask=lambda p, *a, **k: prompts.append(p) or "Two weeks."):
            apply.answer(self.job, "What is your notice period and desired salary?")
        self.assertNotIn("sooner for the right deal", prompts[0])
        self.assertNotIn("187", prompts[0])
        self.assertIn("reliable pipelines", prompts[0])
        situation = drafts._situation("answer", self.job, {"question": "notice period salary"})
        self.assertNotIn("sooner", situation)
        self.assertNotIn("187", situation)
        self.assertEqual(list(extras.autofill_data()["answers"]), ["Why data engineering?"])

    def test_ai_proposal_keeps_a_private_question_private_and_ui_can_mark_one(self):
        approvals.approve(approvals.propose("answers", "save_answer",
                                            {"question": "Notice period?", "answer": "Two weeks."}, "x")["id"])
        row = next(a for a in db.list_answers() if a["question"] == "Notice period?")
        self.assertEqual((row["answer"], row["private"]), ("Two weeks.", 1))
        out = run_cli("answers", "add", "Visa?", "I hold a work permit.", "--private")
        self.assertIn("private", out)
        self.assertNotIn("Visa?", [a["question"] for a in db.list_answers(employer=True)])
        js = (ROOT / "lodestar" / "static" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "lodestar" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="bP"', html)
        self.assertIn("private: $('#bP').checked", js)
        self.assertIn("function answerPrivate(", js)


class Improvements(Base):
    def test_linkedin_dates_become_year_month(self):  # row 11
        self.assertEqual((profile._ym("Jan 2016"), profile._ym("2021-03"), profile._ym("")), ("2016-01", "2021-03", ""))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Positions.csv", "Company Name,Title,Started On,Finished On\nAcme,Engineer,Jan 2016,Dec 2017\n")
        e = profile.linkedin_facts(buf.getvalue())["experience"][0]
        self.assertEqual((e["start"], e["end"]), ("2016-01", "2017-12"))

    def test_ai_drop_starts_unchecked(self):  # row 18
        reply = {"bullets": [{"id": 1, "drop": True, "reason": "not relevant"}], "order": [1]}
        with patched(ai, ask_json=lambda *a, **k: reply):
            rows = resume.tailor_bullets(self.job)["proposals"]
        self.assertTrue(rows[0]["drop"] and rows[0]["changed"])
        self.assertFalse(rows[0]["accepted"])

    def test_template_sign_off_falls_back_to_the_master_contact_line(self):  # row 30
        self.assertTrue(apply.template_mail("followup", self.job)["body"].endswith("Best regards,\nJane Doe"))
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")
        self.assertTrue(apply.template_mail("followup", self.job)["body"].endswith("Best regards,"))  # never "Full Name"

    def test_refine_recomputes_the_score(self):  # row 32
        iid = db.add_idea("tools", "Idea", json.dumps({"title": "Idea", "impact": 5, "fit": 100, "effort": 1}), 500.0)
        with patched(ai, ask_json=lambda *a, **k: {"title": "Idea", "impact": 2, "fit": 50, "effort": 4}):
            r = ideas.refine(iid, "less ambitious")
        self.assertEqual(r["score"], 25.0)
        self.assertEqual(db.get_idea(iid)["score"], 25.0)


class Docs(unittest.TestCase):
    def test_docs_describe_the_allowlist_and_private_answers(self):
        auto = (ROOT / "docs" / "AUTOMATION.md").read_text(encoding="utf-8")
        self.assertNotIn("limits which providers ever receive your profile", auto)
        self.assertIn("`LODESTAR_PROVIDER` outside the list stops with an error", auto)
        self.assertIn("[--private]", (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8"))
        self.assertTrue(APPS_DIR)


if __name__ == "__main__":
    unittest.main()
