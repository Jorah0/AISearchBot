"""Choosing the council's models (pass 50): pref council_members ('provider=model', several models of one provider are
fine) set from the AI switcher (ai.set_council); council() asks exactly those models, the cross-check reviews with them
(never the writer's own model), and council_providers stays the boundary (a member outside it, or not linked, is never
asked). Empty: every allowed provider with its current model, as before. No network; every patch is put back."""
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


class Council(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.asked = []
        p = patched(ai, available=lambda: ["anthropic", "ollama"],
                    _post=lambda url, headers, body, retries=2: self.asked.append(body["model"]) or (
                        {"content": [{"text": f"from {body['model']}"}], "stop_reason": "end_turn"} if "anthropic" in url
                        else {"choices": [{"message": {"content": f"from {body['model']}"}, "finish_reason": "stop"}]}),
                    api_key=lambda n: "k")
        p.__enter__()
        self.addCleanup(p.__exit__, None, None, None)
        settings.set_model("anthropic", "claude-sonnet-5-5")
        settings.set_pref("jobmodel", False)

    def test_set_and_ask_exactly_the_chosen_models(self):
        got = ai.set_council(["ollama=llama3.2:latest", "ollama=qwen3.6:latest", "anthropic=claude-haiku-5-5",
                              "ollama=llama3.2:latest"])  # a repeat counts once
        self.assertEqual(got, ["ollama=llama3.2:latest", "ollama=qwen3.6:latest", "anthropic=claude-haiku-5-5"])
        self.assertEqual(ai.council_members(), [("ollama", "llama3.2:latest"), ("ollama", "qwen3.6:latest"),
                                                ("anthropic", "claude-haiku-5-5")])
        r = ai.council("task")
        self.assertEqual(list(r["answers"]), ["ollama/llama3.2:latest", "ollama/qwen3.6:latest", "anthropic/claude-haiku-5-5"])
        self.assertEqual(self.asked[:3], ["llama3.2:latest", "qwen3.6:latest", "claude-haiku-5-5"])
        self.assertEqual(self.asked[3], "llama3.2:latest")  # the synthesis: the first member that answered
        self.assertEqual(web.state()["council"], got)

    def test_empty_is_every_allowed_provider_and_the_allowlist_is_the_boundary(self):
        ai.set_council([])
        self.assertEqual(ai.council_members(), [("anthropic", None), ("ollama", None)])
        settings.set_pref("council_members", "anthropic=claude-haiku-5-5, ollama=llama3.2:latest")
        settings.set_pref("council_providers", "ollama")
        self.assertEqual(ai.council_members(), [("ollama", "llama3.2:latest")])  # anthropic is outside the allowlist
        with self.assertRaisesRegex(SystemExit, "council_providers"):
            ai.set_council(["anthropic=claude-haiku-5-5"])
        settings.set_pref("council_members", "anthropic=claude-haiku-5-5")
        with self.assertRaisesRegex(SystemExit, "none of your council members"):
            ai.council_members()

    def test_refusals(self):
        with self.assertRaisesRegex(SystemExit, "not linked"):
            ai.set_council(["openai=gpt-5"])
        with self.assertRaisesRegex(SystemExit, "model id"):
            ai.set_council(["ollama=bad id"])
        with self.assertRaisesRegex(SystemExit, "at most 6"):
            ai.set_council([f"ollama=m{i}" for i in range(7)])
        config.FULL_AI.on = True
        try:
            with self.assertRaisesRegex(SystemExit, "Full AI never"):
                ai.set_council(["ollama=llama3.2:latest"])
        finally:
            config.FULL_AI.on = False

    def test_the_cross_check_reviews_with_the_members_but_never_the_writer_s_model(self):
        ai.set_council(["anthropic=claude-sonnet-5-5", "ollama=llama3.2:latest", "ollama=qwen3.6:latest"])
        seen = []
        with patched(ai, ask_json=lambda prompt, system=None, provider=None, **kw: seen.append(
                (provider, getattr(ai._TL, "model", None))) or {"agree": True, "issues": []}):
            r = ai.crosscheck("task", "answer", writer="anthropic")
        self.assertEqual(r["status"], "agreed")
        self.assertEqual(seen, [("ollama", "llama3.2:latest"), ("ollama", "qwen3.6:latest")])


if __name__ == "__main__":
    unittest.main()
