"""Pass 15, group F: interview rounds, the question bank, STAR stories and mock scoring. Rounds replace the .ics scan for
reminders (old calendar events are imported once), interview mail records rounds, prep and mock use logged questions
and the user's own stories, and each mock answer gets a rubric (AI) plus offline metrics, saved per session.
No network: AI calls are faked and every patched attribute is put back."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, db, email_monitor as em, extras, interview, profile, settings  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

REAL_PROFILE = "# Jane Doe\njane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"
JD = ("We need a data engineer who resolves conflict with stakeholders, works cross-functional, and handles ambiguity "
      "in a fast-paced startup. Python and SQL required. Stakeholder alignment matters.")
RUBRIC = {"situation": 2, "task": 1, "action": 5, "result": "x", "relevance": 2, "specificity": 1, "metrics_used": True,
          "one_fix": "Lead with the result.", "suggested_rewrite": "I cut costs by [number]."}


class Base(unittest.TestCase):
    """In-memory database; settings and profile put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text(REAL_PROFILE, encoding="utf-8")

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def cli(self, *argv) -> str:
        a, out = build().parse_args(list(argv)), io.StringIO()
        with contextlib.redirect_stdout(out):
            a.f(a)
        return out.getvalue()


class Rounds(Base):
    def test_log_validate_number_update_delete(self):
        jid = db.add_job("Acme", "Data Engineer", jd=JD)
        r1 = interview.log_round(jid, kind="Phone", at="2026-12-01 2:30 PM", questions_asked="Why us?\n\n  Tell me  about SQL ")
        r = interview.get_round(r1)
        self.assertEqual((r["round"], r["kind"], r["at"], r["outcome"], r["questions_asked"]),
                         (1, "phone", "2026-12-01 14:30", "pending", "Why us?\nTell me about SQL"))
        for bad in ({"kind": "lunch"}, {"outcome": "great"}, {"at": "next tuesday"}, {"round": "0"}, {"round": "x"},
                    {"colour": "red"}, {"questions_asked": "q" * 501}):
            with self.assertRaises(SystemExit, msg=bad):
                interview.log_round(jid, **bad)
        self.assertEqual(len(interview.rounds(jid)), 1)                       # a bad value changed nothing
        r2 = interview.log_round(jid, kind="technical", at="2026-12-08")
        self.assertEqual((interview.get_round(r2)["round"], interview.get_round(r2)["at"]), (2, "2026-12-08"))
        self.assertEqual(interview.log_round(jid, round=2, outcome="passed", interviewers="Sam"), r2)  # round N again: update
        self.assertEqual((interview.get_round(r2)["outcome"], interview.get_round(r2)["kind"]), ("passed", "technical"))
        with self.assertRaises(SystemExit):
            interview.edit_round(r2, round=1)                                 # round 1 is taken
        interview.edit_round(r2, notes="")                                    # empty clears
        interview.delete_round(r1)
        self.assertEqual([x["round"] for x in interview.rounds(jid)], [2])
        db.delete_job(jid)
        self.assertEqual(db.con().execute("SELECT COUNT(*) n FROM interviews").fetchone()["n"], 0)

    def test_ics_and_legacy_calendar_events_feed_reminders(self):
        jid = db.add_job("Initech", "SRE")
        when = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
        out = extras.ics(db.get_job(jid), when)                               # .ics creation still works and logs the round
        self.assertTrue(out.is_file())
        rs = interview.rounds(jid)
        self.assertEqual((len(rs), rs[0]["at"], rs[0]["ics"]), (1, f"{when:%Y-%m-%d %H:%M}", str(out)))
        extras.ics(db.get_job(jid), when)                                     # same slot again: no second round
        self.assertEqual(len(interview.rounds(jid)), 1)
        up = extras.upcoming_interviews(2)
        self.assertEqual([(u["job_id"], u["when"], u["path"]) for u in up], [(jid, when, str(out))])
        # an event written before rounds existed: imported once on the next read; deleting the round keeps it deleted
        old = when + timedelta(hours=3)
        db.add_event(jid, "calendar", f"/x/interview-{old:%Y%m%d-%H%M}.ics")
        self.assertEqual(len(extras.upcoming_interviews(2)), 2)
        legacy = next(r for r in interview.rounds(jid) if r["ics"].startswith("/x/"))
        interview.delete_round(legacy["id"])
        self.assertEqual(len(extras.upcoming_interviews(2)), 1)
        # a round you log yourself with a time reminds too; a date-only round never does
        at = f"{when + timedelta(hours=5):%Y-%m-%d %H:%M}"
        rid = interview.log_round(jid, at=at)
        interview.log_round(jid, at=f"{when:%Y-%m-%d}")
        self.assertIn(f"round:{rid}:{at}", [u["path"] for u in extras.upcoming_interviews(2)])
        self.assertEqual(len(extras.upcoming_interviews(2)), 2)
        # rescheduled: a new key, so the once-only reminder and toast fire again for the new time
        moved = f"{when + timedelta(hours=6):%Y-%m-%d %H:%M}"
        interview.edit_round(rid, at=moved)
        ics_round = interview.rounds(jid)[0]
        interview.edit_round(ics_round["id"], at=moved)
        paths = [u["path"] for u in extras.upcoming_interviews(2)]
        self.assertIn(f"round:{rid}:{moved}", paths)
        self.assertIn(f"round:{ics_round['id']}:{moved}", paths)              # an .ics round moved off its file's time

    def test_interview_mail_records_a_round_once(self):
        jid = db.add_job("Globex", "Eng")
        db.update_job(jid, contact_email="r@globex.com")
        db.set_status(jid, "interview")
        day = datetime.now() + timedelta(days=3)
        base = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Interview",
                "from": "r@globex.com", "sender_email": "r@globex.com", "sender_name": "R", "message_id": "<m>",
                "body": "b", "dkim_pass": True}
        real = em.ai.ask_json
        em.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        try:
            em._apply(base | {"deadline": f"{day:%Y-%m-%d}"}, dry=False)       # a bare date (often reply-by): no round
            self.assertEqual(interview.rounds(jid), [])
            self.assertTrue(any(e["kind"] == "interview_date" for e in db.events(jid)))
            em._apply(base | {"deadline": f"{day:%Y-%m-%d} 14:30", "dkim_pass": False}, dry=False)  # unverified: no round
            self.assertEqual(interview.rounds(jid), [])
            em._apply(base | {"deadline": f"{day:%Y-%m-%d} 14:30"}, dry=False)  # trusted mail with a time: one round
            em._apply(base | {"deadline": f"{day:%Y-%m-%d} 14:30"}, dry=False)  # re-scanned: nothing new
            em._apply(base | {"deadline": "soon"}, dry=True)
        finally:
            em.ai.ask_json = real
        rs = interview.rounds(jid)
        self.assertEqual([(r["round"], r["at"]) for r in rs], [(1, f"{day:%Y-%m-%d} 14:30")])
        self.assertTrue(rs[0]["ics"])
        self.assertEqual(len(extras.upcoming_interviews(14)), 1)


class Questions(Base):
    def test_bank_order_and_prep_mock_use_it(self):
        a = db.add_job("Acme Inc.", "Senior Data Engineer", jd=JD)
        b = db.add_job("ACME", "Analyst")                                     # same company, other title
        c = db.add_job("Globex", "Data Engineer II")                          # similar title
        d = db.add_job("Initech", "Nurse")                                    # unrelated
        interview.log_round(b, questions_asked="How do you model churn?\nWhy Acme?")
        interview.log_round(c, questions_asked="Design a pipeline for late data.\nwhy acme")
        interview.log_round(d, questions_asked="Describe triage.")
        bank = interview.question_bank(db.get_job(a))
        self.assertEqual([x["q"] for x in bank[:3]], ["How do you model churn?", "Why Acme?", "Design a pipeline for late data."])
        self.assertEqual([x["source"] for x in bank[:3]], ["company", "company", "similar title"])
        self.assertNotIn("Describe triage.", [x["q"] for x in bank])
        self.assertNotIn("why acme", [x["q"] for x in bank])                  # duplicates listed once
        self.assertEqual(len([x for x in bank if x["source"] == "universal"]), len(interview.universal()))
        self.assertTrue(25 <= len(interview.universal()) <= 35)
        self.assertEqual(len(interview.question_bank(None, False)), 4)        # no job: every logged question, once
        self.assertIn("company", self.cli("questions", str(a)))
        seen = []
        real = ai.ask
        ai.ask = lambda prompt, *x, **k: seen.append(prompt) or "pack"
        try:
            interview.prep(db.get_job(a))
        finally:
            ai.ask = real
        self.assertIn("QUESTIONS ACTUALLY ASKED", seen[0])
        self.assertIn("How do you model churn?", seen[0])
        self.assertIn("Design a pipeline for late data.", interview.mock_system(db.get_job(a)))


class Stories(Base):
    def test_store_tag_prompt_and_injection(self):
        jid = db.add_job("Acme", "Data Engineer", jd=JD)
        job = db.get_job(jid)
        self.assertEqual(interview.story_prompt(job)["stressed"][:1], ["influence"])   # stakeholder x2 + cross-functional
        self.assertIn("conflict", interview.story_prompt(job)["missing"])
        for bad in ({"title": ""}, {"title": "T"}, {"title": "T", "action": "a", "competencies": "bravery"},
                    {"title": "T", "action": "a" * 4001}):
            with self.assertRaises(SystemExit, msg=bad):
                interview.save_story(**bad)
        sid = interview.save_story("Settled the schema fight", situation="Two teams disagreed", action="I ran a review",
                                   result="Shipped in 2 weeks", metrics="2 weeks", competencies="conflict, influence")
        s = interview.stories()[0]
        self.assertEqual((s["id"], s["competencies"], s["missing"]), (sid, ["conflict", "influence"], ["task"]))
        self.assertNotIn("conflict", interview.story_prompt(job)["missing"])
        with self.assertRaises(SystemExit):
            interview.save_story("Settled the schema fight", action="dup")    # one title, one story
        interview.save_story("Settled the schema dispute", task="Unblock launch", action="I ran a review", sid=sid)
        self.assertEqual(interview.stories()[0]["title"], "Settled the schema dispute")
        db.save_answer("Why Acme?", "Because data.")                          # an ordinary form answer stays one
        self.assertEqual([x["title"] for x in interview.stories()], ["Settled the schema dispute"])
        self.assertIn("I ran a review", interview.mock_system(job))
        self.assertIn("Settled the schema dispute", interview.prep.__globals__["_stories_text"](job))
        iid = db.add_idea("stories", "Rescued the migration", json.dumps({"idea": "Led a data migration under a tight "
                          "deadline with stakeholders", "why_it_works": "ownership"}), 9.0)
        new = interview.story_from_idea(iid)
        got = next(x for x in interview.stories() if x["id"] == new)
        self.assertEqual((got["title"], got["missing"]), ("Rescued the migration", ["task", "action", "result"]))
        self.assertTrue({"deadline", "influence", "ownership"} <= set(got["competencies"]))
        other = db.add_idea("strategy", "Apply more", "{}", 1.0)
        with self.assertRaises(SystemExit):
            interview.story_from_idea(other)


class Mock(Base):
    def test_score_card_session_and_offline_fallback(self):
        jid = db.add_job("Acme", "Data Engineer", jd=JD)
        job = db.get_job(jid)
        answer = ("I led the pipeline rebuild in Python and SQL. The pipeline was slow, the pipeline failed nightly, so I "
                  "rewrote the pipeline and cut runtime by 40 percent.")
        real = ai.ask_json
        ai.ask_json = lambda *a, **k: RUBRIC
        try:
            c1 = interview.score_answer(job, "Tell me about a project.", answer, seconds="30")
        finally:
            ai.ask_json = real
        r = c1["rubric"]
        self.assertEqual((r["situation"], r["task"], r["action"], r["result"], r["star"]), (2, 1, 2, 0, 1.25))  # clamped
        self.assertTrue(r["metrics_used"])
        self.assertEqual((c1["words"], c1["est_seconds"], c1["seconds"], c1["wpm"], c1["pace"]), (28, 12, 30, 56, "short"))
        self.assertEqual(c1["repeated"], ["pipeline"])
        self.assertTrue({"python", "sql"} <= set(c1["jd_keywords"]))
        self.assertFalse({"filler", "fillers", "um"} & set(c1))                  # no filler-word counting
        ai.ask_json = lambda *a, **k: (_ for _ in ()).throw(SystemExit("No AI provider configured"))
        try:
            c2 = interview.score_answer(job, "Why us?", "Because. " * 300, session=c1["session"])
        finally:
            ai.ask_json = real
        self.assertEqual((c2["rubric"], c2["session"], c2["pace"]), (None, c1["session"], "long"))
        self.assertIn("No AI provider", c2["rubric_error"])
        self.assertEqual((c2["averages"]["answers"], c2["averages"]["scored"], c2["averages"]["star"]), (2, 1, 1.25))
        for bad in ({"answer": " "}, {"answer": "x", "seconds": "fast"}, {"answer": "x", "seconds": 0},
                    {"answer": "x", "session": 999}):
            with self.assertRaises(SystemExit, msg=bad):
                interview.score_answer(job, "q", **bad)
        other = db.add_job("Globex", "Eng")
        with self.assertRaises(SystemExit):                                   # a session belongs to its job
            interview.score_answer(db.get_job(other), "q", "a", session=c1["session"])
        s = interview.sessions()
        self.assertEqual((len(s), s[0]["averages"]["answers"]), (1, 2))
        self.assertIn("STAR S2 T1 A2 R0", interview.render_card(c1))
        self.assertIn("no rubric", interview.render_card(c2))

    def test_web_mock_scores_answers_and_keeps_the_transcript(self):
        from lodestar import web
        jid = db.add_job("Acme", "Data Engineer", jd=JD)
        real_chat, real_json = ai.chat, ai.ask_json
        ai.chat = lambda *a, **k: "Next question?"
        ai.ask_json = lambda *a, **k: RUBRIC
        try:
            first = web._act("mock", {"id": jid, "messages": [{"role": "user", "content": "start"}]})
            self.assertNotIn("card", first)                                   # nothing answered yet
            msgs = [{"role": "user", "content": "start"}, {"role": "assistant", "content": "Tell me about X."},
                    {"role": "user", "content": "I did X with Python."}]
            r = web._act("mock", {"id": jid, "messages": msgs, "seconds": 12})
            self.assertEqual((r["reply"], r["card"]["question"], r["card"]["seconds"]), ("Next question?", "Tell me about X.", 12))
            r2 = web._act("mock", {"id": jid, "messages": msgs + [{"role": "assistant", "content": "Q2"},
                                                                  {"role": "user", "content": "A2"}], "session": r["card"]["session"]})
            self.assertEqual(r2["card"]["averages"]["answers"], 2)
            done = web._act("mock", {"id": jid, "messages": msgs + [{"role": "assistant", "content": "Q2"},
                                                                    {"role": "user", "content": "done"}]})
            self.assertTrue(Path(done["path"]).is_file())                     # mock_interview.md still saved
            self.assertNotIn("card", done)
        finally:
            ai.chat, ai.ask_json = real_chat, real_json
        st = web.state()
        self.assertEqual(len(st["mock_sessions"]), 1)
        self.assertIn("deadline", st["competencies"])


class Cli(Base):
    def test_interview_questions_and_stories_commands(self):
        jid = db.add_job("Acme", "Data Engineer", jd=JD)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q.txt"
            f.write_text("Why Acme?\nDesign a pipeline.\n", encoding="utf-8")
            out = self.cli("interview", "log", str(jid), "--kind", "phone", "--at", "2026-12-01 10:00", "--questions-file", str(f))
        self.assertIn("round 1", out); self.assertIn("2 question(s)", out)
        self.assertIn("passed", self.cli("interview", "log", str(jid), "--round", "1", "--outcome", "passed"))
        out = self.cli("interview", "rounds", str(jid))
        self.assertIn("Q: Design a pipeline.", out); self.assertIn("phone", out)
        with self.assertRaises(SystemExit):
            self.cli("interview", "log", str(jid), "--at", "someday")
        self.assertIn("Why Acme?", self.cli("questions"))
        self.assertIn("universal:", self.cli("questions", str(jid)))
        self.assertIn("saved story #", self.cli("stories", "add", "--title", "Ship it", "--action", "I shipped", "--tags", "deadline"))
        sid = interview.stories()[0]["id"]
        self.assertIn("deadline", self.cli("stories", "list"))
        self.assertIn("Action: I shipped", self.cli("stories", "show", str(sid)))
        with self.assertRaises(SystemExit):
            self.cli("stories", "add", "--title", "X", "--action", "a", "--tags", "luck")
        iid = db.add_idea("stories", "Idea story", json.dumps({"idea": "A customer escalation"}), 5.0)
        self.assertIn("from idea", self.cli("stories", "add", "--from-idea", str(iid)))
        self.assertIn(f"removed story #{sid}", self.cli("stories", "rm", str(sid)))
        with self.assertRaises(SystemExit):
            self.cli("stories", "rm", str(sid))


class Routes(unittest.TestCase):
    def test_round_and_story_routes(self):
        import http.client
        from lodestar import desktop, web

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        port = desktop.free_port(8960); srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        jid, sids = None, []
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            def call(path, body=None, headers=h):
                c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse(); return r.status, json.loads(r.read())
            jid = db.add_job("Zzinit", "Data Engineer", jd=JD)
            st, r = call(f"/api/jobs/{jid}/rounds", {"round": "", "kind": "panel", "at": "2026-12-02 09:00",
                                                       "questions_asked": "<img src=x onerror=alert(1)>", "outcome": "pending"})
            self.assertEqual(st, 200); rid = r["round_id"]
            self.assertEqual(call(f"/api/jobs/{jid}/rounds", {"kind": "brunch"})[0], 400)
            self.assertEqual(call(f"/api/jobs/{jid}/rounds", {"admin": "1"})[0], 400)
            self.assertEqual(call(f"/api/rounds/{rid}/edit", {"outcome": "passed"})[0], 200)
            self.assertEqual(call(f"/api/rounds/{rid}/edit", {"at": "nope"})[0], 400)
            st, r = call(f"/api/jobs/{jid}")
            self.assertEqual((r["rounds"][0]["outcome"], r["rounds"][0]["kind"]), ("passed", "panel"))
            self.assertEqual(r["bank"][0]["q"], "<img src=x onerror=alert(1)>")
            self.assertIn("conflict", r["stress"]["stressed"])
            st, r = call("/api/stories", {"title": "Zz story", "action": "I did it", "competencies": ["conflict"]})
            self.assertEqual(st, 200); sids.append(r["id"])
            self.assertEqual(call("/api/stories", {"title": "Zz2", "action": "a", "sql": "drop"})[0], 400)
            self.assertEqual(call("/api/stories", {"title": "Zz3", "action": "a", "competencies": ["luck"]})[0], 400)
            self.assertEqual(call("/api/stories", {"id": sids[0], "title": "Zz story v2", "result": "won"})[0], 200)
            s = call("/api/state")[1]
            self.assertIn("Zz story v2", [x["title"] for x in s["stories"]])
            self.assertNotIn(sids[0], [a["id"] for a in s["answers"]])        # stories are not listed as form answers
            self.assertEqual((s["round_kinds"][0], s["round_outcomes"][0]), ("phone", "pending"))
            self.assertEqual(call(f"/api/rounds/{rid}/delete", {})[0], 200)
            self.assertEqual(call(f"/api/rounds/{rid}/delete", {})[0], 400)
            self.assertEqual(call(f"/api/answers/{sids[0]}", {})[0], 200)      # a story is removed like an answer
            sids.clear()
            self.assertEqual(call("/api/stories", {"title": "X", "action": "a"}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            c.close()
        finally:
            srv.shutdown()
            if jid:
                db.delete_job(jid)
            for i in sids:
                db.delete_answer(i)
            db._local.con.close()
            db._local.con = saved


if __name__ == "__main__":
    unittest.main()
