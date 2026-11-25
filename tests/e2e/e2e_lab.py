"""Model lab tab (pass 59): opening it never probes the computer (fits stay unknown), Check this computer shows the GPU
and the budget under a reserve profile, the catalog judges each model against it (the handbook's 24 GiB card with 18
GiB free and 3 GiB reserved), a scratch design shows its exact parameter count, and saving a selection runs its
preflight. nvidia-smi and Ollama are faked in-process (hwprofile.probe, modelcat.ollama_variants)."""
import contextlib
import unittest

from harness import E2ETestCase

from lodestar import hwprofile, jobmodel, modelcat  # noqa: E402  (after harness: it sets the temp home first)

SNAP = {"at": "2026-11-24 10:00:00", "gpus": [{"index": 0, "name": "RTX 4090", "total_gib": 24.0, "free_gib": 18.0,
                                               "used_gib": 6.0, "driver": "621"}],
        "ram": {"total_gib": 128, "free_gib": 100}, "disk": {"path": "x", "free_gib": 500}, "ollama": {"running": []},
        "source": "nvidia-smi", "error": None}


@contextlib.contextmanager
def fakes(probes):
    real = hwprofile.probe, modelcat.ollama_variants
    hwprofile.probe = lambda: probes.append(1) or dict(SNAP)
    modelcat.ollama_variants = lambda: ([], "Ollama faked off")
    try:
        yield
    finally:
        hwprofile.probe, modelcat.ollama_variants = real


class Lab(E2ETestCase):
    def setUp(self):
        for k in ("lab:hw", "lab:profiles", "lab:profile", "lab:selected"):
            self.addCleanup(jobmodel._set_meta, k, jobmodel._meta(k))
            jobmodel._set_meta(k, None)
        super().setUp()

    def test_check_the_computer_browse_by_fit_and_design_a_scratch_model(self):
        probes = []
        with fakes(probes):
            self.go("lab")
            self.idle()
            self.assertEqual(probes, [])  # opening the tab never runs nvidia-smi
            self.assertIn("not checked yet", self.page.text_content("#labHw"))
            self.assertGreater(self.page.locator("#labCat .labvar").count(), 5)  # every catalog model stays visible
            self.page.select_option("#labProfile", "OBS live")  # the default 3 GiB reserve
            self.idle()
            self.run_click("#labProbe")
            self.assertEqual(probes, [1])
            hw = self.page.text_content("#labHw")
            self.assertIn("RTX 4090", hw)
            self.assertIn("15 GiB", hw)  # 18 free - 3 reserved
            qwen = self.page.locator('#labCat .labvar[data-id="qwen2.5:7b"]')
            self.assertIn("fits", qwen.text_content())
            self.assertRegex(qwen.text_content(), r"\d+–\d+% of your GPU")
            self.page.select_option("#labView", "installed")
            self.idle()
            self.assertEqual(self.page.locator("#labCat .labvar").count(), 0)  # Ollama is off: nothing installed
            self.assertIn("no model matches", self.page.text_content("#labCat"))
            self.page.check("input[name=labMode][value=scratch]")
            self.run_click(self.page.get_by_role("button", name="Estimate"))
            self.assertIn("26,354,176", self.page.text_content("#labEst"))  # the handbook preset, counted exactly
            self.page.fill("#lsHeads", "7")
            self.allow_console()  # the refusal is a 400
            self.run_click(self.page.get_by_role("button", name="Estimate"))
            self.expect_toast("must divide evenly by heads", "err")
            self.page.fill("#lsHeads", "8")
            self.run_click(self.page.get_by_role("button", name="Save as a new selection"))
            self.expect_toast("saved selection", "ok")
            self.assertIn("training environment", self.page.text_content("#labGates"))
            self.assertIn("scratch", self.page.text_content("#labSels"))


if __name__ == "__main__":
    unittest.main()
