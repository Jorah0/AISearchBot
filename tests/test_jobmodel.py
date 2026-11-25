"""The local job model (pass 46): what it learns from (decisions), the held-out split, its message history (never the
salary floor), building it in Ollama (skipped when unchanged), using it as Ollama's model, falling back when Ollama lost
it, the daily loop step, and the held-out evaluation. Ollama is faked (jobmodel._post, ai._post); every patch and
setting is put back."""
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import ai, approvals, db, jobmodel, profile, settings  # noqa: E402

PROF = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com\n## Summary\nData engineer.\n## Skills\nPython, SQL, Spark\n"
        "## Experience\n### Data Engineer - Globex (2019-01 - Present)\n- Built pipelines\n## Education\nBS Computer Science\n\n"
        "## Preferences\nSalary floor: $123,456\nTarget roles: Data Engineer\n")


class Base(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        had = profile.PROFILE.read_text(encoding="utf-8") if profile.PROFILE.is_file() else None
        self.addCleanup(lambda: profile.PROFILE.write_text(had, encoding="utf-8") if had is not None else None)
        profile.write_master(PROF)
        self.made = []
        self.addCleanup(lambda: [db.delete_job(j) for j in self.made])
        self.addCleanup(jobmodel._set_meta, jobmodel.KEY, jobmodel._meta(jobmodel.KEY))
        self.addCleanup(jobmodel._set_meta, jobmodel.EVAL_KEY, jobmodel._meta(jobmodel.EVAL_KEY))
        jobmodel.forget()
        settings.set_pref("jobmodel_base", "llama3.2:latest")
        self.posts = []

    def job(self, title, status):
        jid = db.add_job(f"Co {title}", title, f"https://x.example/jm/{title}", f"{title}: build things with Python", None)
        self.made.append(jid)
        if status != "saved":
            db.set_status(jid, status)
        return jid

    def ollama(self, fail=None):
        def fake(path, body, timeout=600):
            if fail:
                raise fail
            self.posts.append((path, body))
            return {"status": "success"}
        return patched(jobmodel, _post=fake)


class Learn(Base):
    def test_decisions_split_and_the_message_history(self):
        a, b = self.job("Data Engineer", "interview"), self.job("Analytics Engineer", "applied")
        c = self.job("Sales Rep", "withdrawn")
        pid = approvals.propose("auto_track", "add_job", {"company": "Nope Inc", "title": "Night Cashier", "jd": "Tills"},
                                "track Night Cashier", force_pending=True)["id"]
        self.addCleanup(db.con().execute, "DELETE FROM pending WHERE id=?", (pid,))
        approvals.reject(pid)
        rows = {r["id"]: r for r in jobmodel.decisions()}
        self.assertEqual((rows[f"job:{a}"]["label"], rows[f"job:{a}"]["strength"]), ("pursued", 2))
        self.assertEqual(rows[f"job:{b}"]["label"], "pursued")
        self.assertEqual(rows[f"job:{c}"]["label"], "passed")
        self.assertEqual(rows[f"proposal:{pid}"]["title"], "Night Cashier")
        learn, held = jobmodel.split(list(range(10)))
        self.assertEqual(held, [3, 7])
        self.assertEqual(len(learn) + len(held), 10)
        text = jobmodel.messages()[0]["content"]
        self.assertIn("Built pipelines", text)
        self.assertIn("Target roles: Data Engineer", text)
        self.assertNotIn("123,456", text)  # the salary floor never reaches the model
        self.assertNotIn("123456", text)


class Build(Base):
    def test_build_once_skip_when_unchanged_and_rebuild_on_change(self):
        with self.ollama():
            r = jobmodel.build()
            self.assertTrue(r["changed"])
            path, body = self.posts[0]
            self.assertEqual((path, body["model"], body["from"]), ("/api/create", "lodestar-jobs", "llama3.2:latest"))
            self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant"])
            self.assertEqual(jobmodel.build()["changed"], False)  # nothing it carries changed
            self.assertEqual(len(self.posts), 1)
            self.job("Platform Engineer", "applied")  # a new decision: something to learn
            self.assertTrue(jobmodel.build()["changed"])
            self.assertTrue(jobmodel.build(force=True)["changed"])
        self.assertEqual(len(self.posts), 3)

    def test_ollama_down_says_so(self):
        with self.ollama(fail=urllib.error.URLError("refused")), self.assertRaisesRegex(SystemExit, "not answering"):
            jobmodel.build()
        self.assertIsNone(jobmodel.built())

    def test_the_built_model_is_ollama_s_model_and_a_lost_one_falls_back(self):
        settings.set_model("ollama", "llama3.2:latest")
        with self.ollama():
            jobmodel.build()
        self.assertEqual(ai.model_for("ollama"), "lodestar-jobs")
        settings.set_pref("jobmodel", False)
        self.assertEqual(ai.model_for("ollama"), "llama3.2:latest")
        settings.set_pref("jobmodel", True)
        sent = []

        def post(url, headers, body, retries=2):
            sent.append(body["model"])
            if body["model"] == "lodestar-jobs":
                raise SystemExit("ollama: the model 'lodestar-jobs' was rejected (not found).")
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        with patched(ai, _post=post, api_key=lambda n: "k"):
            self.assertEqual(ai.ask("hi", provider="ollama"), "ok")
        self.assertEqual(sent, ["lodestar-jobs", "llama3.2:latest"])
        self.assertIsNone(jobmodel.built())  # forgotten until the next build
        self.assertEqual(settings.pref("models")["ollama"], "llama3.2:latest")  # your choice untouched

    def test_using_asks_exactly_that_model_and_saves_nothing(self):
        sent = []
        with patched(ai, _post=lambda url, headers, body, retries=2: sent.append(body["model"]) or
                     {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}, api_key=lambda n: "k"):
            with ai.using("qwen3:8b"):
                ai.ask("hi", provider="ollama")
        self.assertEqual(sent, ["qwen3:8b"])
        self.assertNotEqual(settings.pref("models").get("ollama"), "qwen3:8b")

    def test_the_loop_step_is_off_without_ollama_and_daily(self):
        with self.ollama(), patched(ai, available=lambda: ["anthropic"]):
            self.assertIsNone(jobmodel.tick())
        with self.ollama(), patched(ai, available=lambda: ["ollama"]):
            self.assertTrue(jobmodel.tick()["changed"])
            self.job("Data Architect", "applied")
            self.assertIsNone(jobmodel.tick())  # built today: tomorrow's cycle picks the change up
            settings.set_pref("jobmodel", False)
            jobmodel.forget()
            self.assertIsNone(jobmodel.tick())
        self.assertEqual(len(self.posts), 1)


class Evaluate(Base):
    def test_held_out_pairs_are_scored_for_both_models(self):
        with self.ollama():
            jobmodel.build()
        rows = [{"id": f"r{i}", "label": "pursued" if i % 2 else "passed", "strength": 1, "title": f"T{i}", "company": "C",
                 "location": "", "jd": "x"} for i in range(8)]  # held out: r3 (pursued), r7 (pursued) ... see split
        rows[3]["label"], rows[7]["label"] = "pursued", "passed"
        good = {"r3": 90, "r7": 20}

        def scores(model, held):
            return good if model == "lodestar-jobs" else {"r3": 40, "r7": 60}
        with patched(jobmodel, decisions=lambda: rows, _scores=scores):
            out = jobmodel.evaluate()
        self.assertEqual(out["models"]["lodestar-jobs"]["accuracy"], 1.0)
        self.assertEqual(out["models"]["llama3.2:latest"]["accuracy"], 0.0)
        self.assertEqual(jobmodel.status()["eval"]["pairs"], 1)
        with patched(jobmodel, decisions=lambda: rows[:3]), self.assertRaisesRegex(SystemExit, "not enough held-out"):
            jobmodel.evaluate()


class Playbook(Base):  # pass 47: the evidence-graded strategies it learns from
    def test_every_entry_is_graded_and_sourced(self):
        rows = jobmodel.playbook()
        self.assertGreaterEqual(len(rows), 10)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        for r in rows:
            self.assertIn(r["grade"], ("strong", "moderate", "weak", "myth"), r["id"])
            self.assertTrue(r["url"].startswith("https://") and r["source"] and r["do"], r["id"])

    def test_the_model_learns_strong_and_moderate_as_advice_myths_as_myths_and_never_weak(self):
        text = jobmodel.messages()[0]["content"]
        rows = {r["id"]: r for r in jobmodel.playbook()}
        self.assertIn(rows["referrals"]["do"], text)
        self.assertIn(rows["apply_early"]["do"], text)
        self.assertIn("(strong evidence:", text)
        self.assertIn("MYTHS TO CORRECT", text)
        self.assertIn(rows["ats_75_percent"]["do"], text)
        self.assertNotIn(rows["thank_you_notes"]["do"], text)  # weak: never given as fact
        self.assertNotIn(rows["timing_hours"]["do"], text)


if __name__ == "__main__":
    unittest.main()
