"""Quick swap of the primary AI (pass 49): the provider and model every AI call uses unless a call names its own.
ai.set_primary validates the provider (configured, inside council_providers when that allowlist is set) and the model
id, saves pref provider + prefs.models, and for Ollama picks between the job model and a model you name (choosing one
switches pref jobmodel). Full AI cannot swap it. No network; every patch and setting is put back."""
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

from lodestar import ai, config, jobmodel, settings, web  # noqa: E402


class Primary(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.addCleanup(jobmodel._set_meta, jobmodel.KEY, jobmodel._meta(jobmodel.KEY))
        jobmodel.forget()
        p = patched(ai, available=lambda: ["anthropic", "ollama"])
        p.__enter__()
        self.addCleanup(p.__exit__, None, None, None)

    def test_swap_provider_and_model(self):
        out = ai.set_primary("Anthropic", "claude-opus-5-5")
        self.assertEqual(out, {"provider": "anthropic", "model": "claude-opus-5-5"})
        self.assertEqual((settings.pref("provider"), settings.pref("models")["anthropic"]), ("anthropic", "claude-opus-5-5"))
        self.assertEqual(ai.primary(), out)
        self.assertEqual(ai.set_primary("ollama")["provider"], "ollama")  # no model: its current one stays

    def test_ollama_job_model_or_a_named_model(self):
        with self.assertRaisesRegex(SystemExit, "not built yet"):
            ai.set_primary("ollama", jobmodel.NAME)
        jobmodel._set_meta(jobmodel.KEY, {"base": "llama3.2:latest", "fp": "x", "built_at": "2026-11-18 00:00:00",
                                          "examples": 0, "held": 0})
        self.assertEqual(ai.set_primary("ollama", jobmodel.NAME)["model"], jobmodel.NAME)
        self.assertTrue(settings.pref("jobmodel"))
        self.assertEqual(ai.set_primary("ollama", "qwen3.6:latest")["model"], "qwen3.6:latest")
        self.assertFalse(settings.pref("jobmodel"))  # your pick wins over the job model

    def test_refusals(self):
        with self.assertRaisesRegex(SystemExit, "not linked"):
            ai.set_primary("openai")
        with self.assertRaisesRegex(SystemExit, "unknown AI provider"):
            ai.set_primary("skynet")
        for bad in ("", "x" * 201, "model; rm -rf /", "a b"):
            with self.assertRaisesRegex(SystemExit, "model id"):
                ai.set_primary("anthropic", bad)
        settings.set_pref("council_providers", "ollama")
        with self.assertRaisesRegex(SystemExit, "council_providers"):
            ai.set_primary("anthropic")
        settings.set_pref("council_providers", "")
        config.FULL_AI.on = True
        try:
            with self.assertRaisesRegex(SystemExit, "Full AI never"):
                ai.set_primary("anthropic")
        finally:
            config.FULL_AI.on = False

    def test_the_page_action_and_state(self):
        self.assertEqual(web._do("ai_primary", {"provider": "anthropic", "model": "claude-haiku-5-5"})["model"],
                         "claude-haiku-5-5")
        self.assertEqual(web.state()["primary"]["model"], "claude-haiku-5-5")


if __name__ == "__main__":
    unittest.main()
