"""The local job model's Setup card (pass 46): not built yet, Build now (Ollama faked: jobmodel._post), the status line
with its base model, a second Build that has nothing new to learn, Evaluate refused without held-out decisions, and the
'use it' switch."""
import contextlib
import unittest

from harness import E2ETestCase

from lodestar import jobmodel, settings  # noqa: E402  (after harness: it sets the temp home first)


@contextlib.contextmanager
def ollama(calls):
    real = jobmodel._post
    jobmodel._post = lambda path, body, timeout=600: calls.append((path, body["model"], body["from"])) or {"status": "success"}
    try:
        yield
    finally:
        jobmodel._post = real


class JobModel(E2ETestCase):
    def test_setup_card_build_evaluate_and_switch(self):
        settings.set_pref("jobmodel_base", "llama3.2:latest")
        self.addCleanup(settings.set_pref, "jobmodel_base", "")
        self.addCleanup(jobmodel.forget)
        jobmodel.forget()
        self.reload_state()
        self.go("setup")
        card = self.page.locator("#jmCard")
        self.assertIn("lodestar-jobs is not built yet", card.text_content())
        calls = []
        with ollama(calls):
            self.run_click(card.get_by_role("button", name="Build now"))
            self.expect_toast("built on llama3.2:latest", "ok")
            self.assertEqual(calls, [("/api/create", "lodestar-jobs", "llama3.2:latest")])
            self.assertIn("built", self.page.text_content("#jmStatus"))
            self.assertIn("on llama3.2:latest", self.page.text_content("#jmStatus"))
            self.run_click(card.get_by_role("button", name="Build now"))
            self.expect_toast("already up to date", "ok")
            self.assertEqual(len(calls), 1)
        self.allow_console()  # Evaluate's refusal is a 400
        self.run_click(card.get_by_role("button", name="Evaluate"))
        self.expect_toast("not enough held-out decisions", "err")
        self.assertTrue(self.page.is_checked("#jmOn"))
        self.page.uncheck("#jmOn")
        self.page.wait_for_function("() => S.prefs.jobmodel === false")
        self.addCleanup(settings.set_pref, "jobmodel", True)
        self.assertFalse(settings.pref("jobmodel"))


if __name__ == "__main__":
    unittest.main()
