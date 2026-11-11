"""Pass 16.5, builder 2: the pipeline's routes and UI server side. Every new route needs the page token and validates
its input (a bad step name or id is a 400, never a failed background task); a drawer button doing a step's work takes
that step's claim; Run next step / Run to / bulk runs refresh the board summary; the state and the job view carry the
pipeline; start_server never switches pipeline.AUTO on; settings.json survives a rename Windows refuses for a moment.
No network: the AI module is faked (test_pipeline.FakeAI); every patched attribute is put back."""
import http.client
import json
import os
import time
import unittest

from test_pipeline import Base, patched

from lodestar import db, desktop, pipeline, settings, web


class Routes(unittest.TestCase):
    """The real server on the shared temp home's database (server threads open their own connections)."""

    def setUp(self):
        old = getattr(db._local, "con", None)  # an earlier test may have left this thread on an in-memory database
        db._local.con = db.connect()
        self.addCleanup(lambda: (db._local.con.close(), setattr(db._local, "con", old)))
        self.port = desktop.free_port(9110)
        self.srv = web.start_server(self.port)
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.jid = db.add_job("Routes Co", "Data Engineer", None, "Python and SQL pipelines.")
        self.addCleanup(db.delete_job, self.jid)

    def req(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}", **({"X-Lodestar-Token": web.TOKEN} if token else {})}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = (r.status, json.loads(r.read().decode() or "{}"))
        c.close()
        return out

    def test_routes_need_token_and_validate(self):
        j = self.jid
        routes = [("GET", "/api/questions", None), ("GET", "/api/pipeline/log", None), ("GET", f"/api/jobs/{j}", None),
                  ("POST", f"/api/pipeline/{j}/skip", {"stage": "research"}), ("POST", f"/api/pipeline/{j}/questions", {"lines": "Why us?"}),
                  ("POST", "/api/questions/1/answer", {"text": "x"}), ("POST", "/api/questions/1/dismiss", {}),
                  ("POST", "/api/run/pipeline_run", {"id": j}), ("POST", "/api/run/pipeline_bulk", {"ids": [j]})]
        for method, path, body in routes:
            self.assertEqual(self.req(method, path, body, token=False)[0], 403, path)
        self.assertEqual(pipeline.status(j)[1]["state"], "todo")  # nothing above ran: research is untouched
        for path, body in (("/api/run/pipeline_run", {"id": j, "stage": "bogus"}), ("/api/run/pipeline_run", {"id": j, "to": "nope"}),
                           ("/api/run/pipeline_run", {"id": "abc"}), ("/api/run/pipeline_bulk", {"ids": list(range(1, 27))}),
                           ("/api/run/pipeline_bulk", {"ids": []}), ("/api/run/pipeline_bulk", {"ids": ["x"]}),
                           (f"/api/pipeline/{j}/skip", {"stage": "bogus"}), ("/api/pipeline/abc/skip", {"stage": "research"}),
                           (f"/api/pipeline/{j}/frobnicate", {}), ("/api/questions/abc/answer", {"text": "x"}),
                           ("/api/questions/999999/answer", {"text": "x"}), ("/api/questions/1/frobnicate", {})):
            code, r = self.req("POST", path, body)
            self.assertEqual(code, 400, (path, body, r))
            self.assertNotIn("task", r)
        self.assertIn("unknown step 'bogus'", self.req("POST", "/api/run/pipeline_run", {"id": j, "stage": "bogus"})[1]["error"])
        code, r = self.req("GET", f"/api/jobs/{j}")
        self.assertEqual(code, 200, r)
        self.assertEqual([e["name"] for e in r["pipeline"]][:2], ["score", "research"])
        self.assertEqual((r["questions"], r["runs"]), ([], []))
        self.assertEqual(self.req("POST", f"/api/pipeline/{j}/questions", {"lines": "Why us?\n\nWhy now?"})[1], {"added": 2})
        self.assertEqual(self.req("POST", f"/api/pipeline/{j}/skip", {"stage": "letter", "on": True})[1], {"ok": True})
        self.assertEqual({e["name"]: e["state"] for e in pipeline.status(j)}["letter"], "skipped")
        self.assertEqual(self.req("GET", "/api/pipeline/log?limit=abc")[0], 200)
        _, s = self.req("GET", "/api/state")
        self.assertEqual(s["pipeline"][str(j)]["next"], "score")  # JSON keys are strings
        self.assertEqual([x["name"] for x in s["pipeline_stages"]], list(pipeline.REGISTRY))
        self.assertTrue({"spent", "last"} <= set(s["autopilot"]))
        self.assertIn("form_answers.md", s["doc_names"])

    def test_start_server_leaves_auto_off(self):
        with patched(pipeline, AUTO=False):  # the cli ui / app / desktop commands set it; start_server never does
            srv = web.start_server(0)
            srv.shutdown()
            srv.server_close()
            self.assertFalse(pipeline.AUTO)


class Actions(Base):
    def test_drawer_action_takes_claim(self):
        jid = self.job()
        now = pipeline._now()
        db.con().execute("INSERT INTO pipeline(job_id, stage, state, origin, updated_at) VALUES(?, 'tailor', 'running', "
                         "'autopilot', ?)", (jid, now))
        db.con().commit()
        for action in ("tailor", "bullets", "bullets_apply"):
            with self.assertRaises(SystemExit) as e:
                web._act(action, {"id": jid})
            self.assertIn(f"this step is already running for #{jid}", str(e.exception))
        self.assertEqual(self.ai.prompts, [])  # no AI call was made
        self.assertEqual(pipeline._rows(jid)["tailor"]["updated_at"], now)  # the runner's claim is untouched
        web._act("research", {"id": jid})  # another step is free; its result is adopted on exit
        st = self.st(jid)
        self.assertEqual((st["research"]["state"], st["research"]["origin"]), ("done", "observed"))
        self.assertFalse([r for r in pipeline._rows(jid).values() if r["stage"] == "research" and r["state"] == "running"])

    def test_run_next_run_to_and_bulk_refresh_the_board(self):
        a, b = self.job(name="One"), self.job(name="Two")
        r = web._act("pipeline_run", {"id": a})
        self.assertEqual([(x["stage"], x["outcome"]) for x in r["runs"]], [("score", "done")])
        self.assertEqual(pipeline.summary()[a]["next"], "research")  # the summary follows what just ran
        r = web._act("pipeline_run", {"id": a, "to": "tailor"})
        self.assertEqual([x["stage"] for x in r["runs"]], ["research", "tailor"])
        r = web._act("pipeline_run", {"id": a, "stage": "score", "rerun": True})
        self.assertEqual(self.st(a)["score"]["rev"], 2)
        with self.assertRaises(SystemExit):
            web._act("pipeline_run", {"id": a, "stage": "score"})  # done: a re-run must be asked for
        p = {"ids": [b, 999999], "to": "research"}
        web._check_pipeline("pipeline_bulk", p)
        r = web._act("pipeline_bulk", p)
        self.assertEqual([x["stage"] for x in r["jobs"][0]["runs"]], ["score", "research"])
        self.assertIn("999999", r["jobs"][1]["error"])  # one bad job never stops the rest
        self.assertEqual(pipeline.summary()[b]["next"], "tailor")
        self.assertEqual(sum(x["ai"] for x in pipeline.log_runs()), 3)  # pass 21: the fit check spends none

    def test_bulk_job_with_nothing_ready_is_a_skip_not_an_error(self):  # live-4
        ready, idle = self.job(name="Ready"), self.job("applied", name="Idle")
        r = web._act("pipeline_bulk", {"ids": [ready, idle]})
        self.assertEqual([x["stage"] for x in r["jobs"][0]["runs"]], ["score"])
        self.assertEqual(r["jobs"][1], {"id": idle, "runs": []})
        with self.assertRaisesRegex(SystemExit, f"#{idle}: nothing is ready to run"):
            web._act("pipeline_run", {"id": idle})  # one job asked for by name still says so

    def test_state_carries_questions_and_a_first_summary(self):
        jid = self.job()
        pipeline.add_form_questions(jid, ["Are you legally authorized to work in Canada?"])
        pipeline.run(jid, "score")
        pipeline.run(jid, "answers")
        s = web.state()
        self.assertEqual([q["kind"] for q in s["questions"]], ["eligibility"])
        self.assertEqual(s["pipeline"][jid]["you"], 1)
        fresh = self.job(name="Fresh")
        self.assertNotIn(fresh, pipeline.summary())
        self.assertEqual(web.state()["pipeline"][fresh]["next"], "score")  # written on the first state read
        self.assertIn(fresh, pipeline.summary())


class SettingsFile(unittest.TestCase):
    def test_save_retries_a_rename_refused_while_another_thread_reads(self):
        real, calls = os.replace, []

        def busy(src, dst):
            calls.append(dst)
            if len(calls) < 3:
                raise PermissionError(5, "Access is denied")  # what Windows says while a reader has the file open
            return real(src, dst)
        snap = settings.load()
        with patched(os, replace=busy), patched(time, sleep=lambda s: None):
            settings.set_pref("autopilot_jobs_per_cycle", 7)
        try:
            self.assertEqual(len(calls), 3)
            self.assertEqual(settings.pref("autopilot_jobs_per_cycle"), 7)
        finally:
            settings.set_pref("autopilot_jobs_per_cycle", snap["prefs"]["autopilot_jobs_per_cycle"])


if __name__ == "__main__":
    unittest.main()
