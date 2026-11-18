"""Token savings (pass 41): short structured judgements (mail sorting, the duplicate check, picking a link, a pay
occupation, search ideas) run on the provider's light model inside ai.light(); writing stays on the main model. Pref
ai_light (on) switches it off; a light model the provider rejects falls back to the main one and is never saved as it.
Mail sorting lists only open jobs. No network (ai._post is faked); every patched attribute and setting is put back."""
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

from lodestar import ai, db, email_monitor, settings  # noqa: E402

REPLY = {"content": [{"text": '{"category": "other", "summary": "x", "verdict": "same", "why": "w"}'}],
         "stop_reason": "end_turn", "usage": {}}


class Light(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.bodies = []

    def post(self, reject=()):
        def fake(url, headers, body, retries=2):
            self.bodies.append(body)
            if body["model"] in reject:
                raise SystemExit(f"anthropic: the model '{body['model']}' was rejected (not found).")
            return REPLY
        return patched(ai, _post=fake, api_key=lambda n: "k")

    def test_inside_light_the_light_model_outside_the_main_one(self):
        with self.post():
            ai.ask_json("q", provider="anthropic")
            with ai.light():
                ai.ask_json("q", provider="anthropic")
            ai.ask_json("q", provider="anthropic")
        self.assertEqual([b["model"] for b in self.bodies],
                         [ai.model_for("anthropic"), ai.LIGHT["anthropic"], ai.model_for("anthropic")])

    def test_the_pref_off_and_a_provider_without_a_light_model_use_the_main_one(self):
        settings.set_pref("ai_light", False)
        with self.post(), ai.light():
            ai.ask_json("q", provider="anthropic")
        self.assertEqual(self.bodies[0]["model"], ai.model_for("anthropic"))
        settings.set_pref("ai_light", True)
        self.assertIsNone(ai.light_model("mistral"))

    def test_a_rejected_light_model_falls_back_and_is_never_saved(self):
        main = ai.model_for("anthropic")
        with self.post(reject=(ai.LIGHT["anthropic"],)), ai.light():
            ai.ask_json("q", provider="anthropic")
        self.assertEqual([b["model"] for b in self.bodies], [ai.LIGHT["anthropic"], main])
        self.assertEqual(ai.model_for("anthropic"), main)

    def test_mail_sorting_is_light_and_lists_only_open_jobs(self):
        live = db.add_job("Openco Light", "Data Engineer", "https://x.example/open-light", "x", None)
        closed = db.add_job("Closedco Light", "Data Engineer", "https://x.example/closed-light", "x", None)
        db.set_status(closed, "rejected")
        self.addCleanup(lambda: [db.delete_job(j) for j in (live, closed)])
        with self.post():
            email_monitor.classify("Interview", "hr@openco.example", "Let us talk", provider="anthropic")
        body = self.bodies[0]
        self.assertEqual(body["model"], ai.LIGHT["anthropic"])
        prompt = body["messages"][0]["content"]
        self.assertIn("Openco Light", prompt)
        self.assertNotIn("Closedco Light", prompt)


if __name__ == "__main__":
    unittest.main()
