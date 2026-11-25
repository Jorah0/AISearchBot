"""Model lab learning (pass 59, teacher.py): a premium AI explains your past decisions, your decision stays the label,
a contradiction is flagged and never accepted unedited, accepted examples feed the local model's few-shot memory and a
deterministic SFT dataset that never carries the salary floor. The AI is faked; every patch is put back."""
import json
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
from test_jobmodel import Base  # noqa: E402
from test_pass21_fit import patched  # noqa: E402

from lodestar import ai, config, db, jobmodel, teacher  # noqa: E402


class Teach(Base):
    def setUp(self):
        super().setUp()
        teacher._init()
        self.addCleanup(lambda: db.con().execute("DELETE FROM lab_examples") and db.con().commit())
        db.con().execute("DELETE FROM lab_examples")
        db.con().commit()
        self.prompts = []

    def fake_ai(self, verdicts):
        def ask(prompt, system=None, provider=None, **kw):
            self.prompts.append((prompt, provider))
            return {"items": [{"block": f"J{i}", "score": 70, "verdict": v, "reasons": ["Python matches", "<b>SQL</b>"]}
                              for i, v in enumerate(verdicts)]}
        return patched(ai, ask_json=ask, primary=lambda: {"provider": "anthropic", "model": "claude-x"})

    def test_the_teacher_explains_your_decisions_and_your_decision_stays_the_label(self):
        a, b = self.job("Data Engineer", "interview"), self.job("Sales Rep", "withdrawn")
        mine = [d for d in teacher.pending_decisions() if d["id"] in (f"job:{a}", f"job:{b}")]
        with patched(teacher, pending_decisions=lambda: mine), self.fake_ai(["pursue", "pursue"]):
            r = teacher.propose()
        self.assertEqual((r["proposed"], r["flagged"]), (2, 1))  # the AI said pursue for the job you withdrew
        prompt, prov = self.prompts[0]
        self.assertEqual(prov, "anthropic")  # the premium teacher, never the local student
        self.assertNotIn("123,456", prompt)  # the salary floor never reaches the teacher
        self.assertIn("untrusted data fenced", prompt)
        rows = {e["decision_id"]: e for e in teacher.examples()}
        self.assertEqual(rows[f"job:{a}"]["target"]["verdict"], "pursue")
        self.assertEqual(rows[f"job:{b}"]["target"]["verdict"], "pass")  # your decision, not the AI's verdict
        self.assertEqual(rows[f"job:{b}"]["flag"], "contradicts your decision")
        self.assertEqual(rows[f"job:{a}"]["split"], teacher.split_of(f"job:{a}"))  # stable split by id
        self.assertNotIn("<b>", json.dumps(rows[f"job:{a}"]["target"]))  # labels cleaned
        with self.assertRaises(SystemExit):  # a flagged example is never accepted unedited
            teacher.review(rows[f"job:{b}"]["id"], "accepted")
        ok = teacher.review(rows[f"job:{b}"]["id"], "accepted", {"verdict": "pass", "score": 20, "reasons": ["wrong field"]})
        self.assertIsNone(ok["flag"])
        with patched(teacher, pending_decisions=lambda: []):
            self.assertEqual(teacher.propose()["proposed"], 0)  # nothing new: no AI call

    def test_only_a_premium_ai_teaches_and_full_ai_cannot(self):
        with patched(ai, primary=lambda: {"provider": "ollama", "model": "llama3.2"}, available=lambda: ["ollama"]):
            with self.assertRaises(SystemExit):
                teacher.teacher()
        config.FULL_AI.on = True  # what advisor.auto sets on its thread
        try:
            with self.assertRaises(SystemExit):
                teacher.propose()
        finally:
            config.FULL_AI.on = False

    def test_accepted_examples_build_a_stable_dataset_and_the_few_shot_memory(self):
        with db.con() as c:
            for i, (prompt, split) in enumerate([("Judge job A", "train"), ("Judge job B", "train"), ("Judge job C", "dev"),
                                                  ("Salary floor: $123,456. Judge job D", "train")]):
                c.execute("INSERT INTO lab_examples(source, decision_id, prompt, target, status, split) VALUES"
                          "('teacher', ?, ?, ?, 'accepted', ?)", (f"t:{i}", prompt, json.dumps({"verdict": "pass"}), split))
        d1, d2 = teacher.dataset("train"), teacher.dataset("train")
        self.assertEqual((d1["sha"], d1["rows"], d1["dropped"]), (d2["sha"], 2, 1))  # same inputs, same hash; floor row dropped
        body = Path(d1["path"]).read_text(encoding="utf-8")
        self.assertNotIn("123,456", body)
        self.assertEqual(json.loads(body.splitlines()[0])["messages"][2]["role"], "assistant")
        self.assertEqual(teacher.dataset("dev")["rows"], 1)
        msgs = jobmodel.messages()
        self.assertIn("Judge job A", [m["content"] for m in msgs])  # the local model's memory carries accepted examples
        self.assertEqual(teacher.stats()["by_split"], {"train": 3, "dev": 1})


if __name__ == "__main__":
    unittest.main()
