"""The council switch (pass 54): pref council_on (default on); off, ai.council answers with the primary AI alone and
the AI cross-check is paused (unchecked, saying why); explicit providers still run; Full AI cannot flip it; the page
action and state carry it. No network: ask / ask_json are faked."""
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

from lodestar import ai, config, settings, web  # noqa: E402


class CouncilSwitch(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.calls = []
        p = patched(ai, available=lambda: ["anthropic", "ollama"],
                    ask=lambda prompt, system=None, provider=None, **kw: self.calls.append(("ask", provider)) or "an answer",
                    ask_json=lambda prompt, system=None, provider=None, **kw: self.calls.append(("review", provider)) or {"agree": True})
        p.__enter__()
        self.addCleanup(p.__exit__, None, None, None)

    def test_on_by_default_and_off_uses_the_primary_alone(self):
        self.assertIs(settings.PREFS["council_on"], True)
        self.assertTrue(ai.council_on())
        web._do("council_on", {"on": False})
        self.assertFalse(settings.pref("council_on"))
        self.assertFalse(web.state()["council_on"])
        r = ai.council("pool ideas")
        self.assertEqual((r["synthesis"], r.get("council_off")), ("an answer", True))
        self.assertEqual(self.calls, [("ask", None)])  # one call, the primary

    def test_off_pauses_the_cross_check_but_explicit_reviewers_still_run(self):
        ai.set_council_on(False)
        r = ai.crosscheck("task", "answer", rounds=1)
        self.assertEqual(r["status"], "unchecked")
        self.assertIn("council is off", r["issues"][0])
        self.assertEqual(self.calls, [])
        self.assertEqual(ai.crosscheck("task", "answer", writer="anthropic", rounds=0, reviewers=["ollama"])["status"], "agreed")

    def test_back_on_and_full_ai_cannot_flip_it(self):
        ai.set_council_on(False)
        self.assertTrue(web._do("council_on", {"on": True})["on"])
        config.FULL_AI.on = True
        try:
            with self.assertRaisesRegex(SystemExit, "Full AI never"):
                ai.set_council_on(False)
        finally:
            config.FULL_AI.on = False
        self.assertTrue(ai.council_on())


if __name__ == "__main__":
    unittest.main()
