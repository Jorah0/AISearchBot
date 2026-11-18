"""Your to-dos per job (pass 53): add / tick / delete scoped to their job, due ones join Today's actions, delete_job
removes them, never an event (the follow-up clock), and the AI suggestions are cleaned, deduplicated and capped."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import ai, db, loop, web  # noqa: E402


class Todos(unittest.TestCase):
    def setUp(self):
        self.jid = db.add_job("Marigold Freight", "Planner", "https://jobs.marigold.example/7", "Plan loads.", "test")
        self.other = db.add_job("Saffron Port", "Clerk", "https://jobs.saffron.example/2", "File things.", "test")
        self.addCleanup(lambda: [db.delete_job(j) for j in (self.jid, self.other) if db.con().execute("SELECT 1 FROM jobs WHERE id=?", (j,)).fetchone()])

    def test_add_tick_delete_scoped_to_the_job(self):
        events = len(db.events(self.jid))
        t = db.add_task(self.jid, "  Ask   Sam for a referral ", "2026-11-20")
        self.assertEqual(db.tasks(self.jid)[0]["text"], "Ask Sam for a referral")
        db.set_task(self.other, t, True)  # another job's id: nothing changes
        self.assertIsNone(db.tasks(self.jid)[0]["done_at"])
        db.set_task(self.jid, t, True)
        self.assertTrue(db.tasks(self.jid)[0]["done_at"])
        db.delete_task(self.other, t)
        self.assertEqual(len(db.tasks(self.jid)), 1)
        db.delete_task(self.jid, t)
        self.assertEqual(db.tasks(self.jid), [])
        self.assertEqual(len(db.events(self.jid)), events)
        for bad in (("", None), ("x", "20/11/2026")):
            with self.assertRaises(ValueError):
                db.add_task(self.jid, *bad)

    def test_due_todos_join_today_and_go_with_the_job(self):
        db.add_task(self.jid, "Send portfolio link", "2026-01-02")
        db.add_task(self.jid, "Later thing", "2999-01-01")
        acts = [a for a in loop.agenda(datetime(2026, 1, 3))["actions"] if a.get("task")]
        self.assertEqual([(a["id"], a["what"], a["overdue"]) for a in acts if a["id"] == self.jid], [(self.jid, "Send portfolio link", True)])
        db.delete_job(self.jid)
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM tasks WHERE job_id=?", (self.jid,)).fetchone()[0], 0)

    def test_ai_ideas_cleaned_deduplicated_and_capped(self):
        db.add_task(self.jid, "Ask Sam for a referral")
        seen = []
        fake = lambda prompt, **kw: seen.append(prompt) or {"todos": ["ask sam for a referral", "Tailor <b>resume</b>", "Tailor resume", "a", "b", "c", "d", "e"]}
        with patched(ai, ask_json_light=fake):
            ideas = web._do("task_ideas", {"id": self.jid})["ideas"]
        self.assertEqual(ideas, ["Tailor bresume/b", "Tailor resume", "a", "b", "c"])
        self.assertLessEqual(len(ideas), 5)
        self.assertNotIn("ask sam for a referral", [i.lower() for i in ideas])
        self.assertIn("Planner at Marigold Freight", seen[0])
        self.assertNotIn("Plan loads.", seen[0])  # the posting text is not sent


if __name__ == "__main__":
    unittest.main()
