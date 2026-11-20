"""The viewer's look gallery (pass 53): every render.LOOKS entry is a valid style (clean_style, strict) and is offered
by viewer.choices; the AI pick answers only a listed look and sends only the job's title and company."""
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

from lodestar import ai, db, render, viewer, web  # noqa: E402


class Looks(unittest.TestCase):
    def test_every_look_is_a_valid_style_and_offered(self):
        self.assertGreaterEqual(len(render.LOOKS), 8)
        for name, look in render.LOOKS.items():
            notes = []
            self.assertEqual(render.clean_style(look, notes, strict=True), look, name)
            self.assertEqual(notes, [], name)
        self.assertEqual(viewer.choices()["looks"], render.LOOKS)

    def test_ai_pick_is_a_listed_look_from_title_and_company_only(self):
        jid = db.add_job("Cobalt Ledger", "Staff Accountant", "https://jobs.cobalt.example/3", "SECRET POSTING TEXT", "test")
        self.addCleanup(db.delete_job, jid)
        seen = []
        with patched(ai, ask_json_light=lambda prompt, **kw: seen.append(prompt) or {"look": "Traditional", "why": "finance <b>"}):
            r = web._do("look_pick", {"id": jid})
        self.assertEqual(r, {"look": "Traditional", "why": "finance b"})
        self.assertIn("Staff Accountant at Cobalt Ledger", seen[0])
        self.assertNotIn("SECRET POSTING TEXT", seen[0])
        with patched(ai, ask_json_light=lambda prompt, **kw: {"look": "Comic Sans Party"}):
            with self.assertRaisesRegex(ValueError, "did not name"):
                web._do("look_pick", {"id": jid})


if __name__ == "__main__":
    unittest.main()
