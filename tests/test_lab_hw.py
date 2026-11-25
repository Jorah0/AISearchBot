"""Model lab hardware (pass 59, part A): nvidia-smi parsing through updater._proc, a probe that never raises, hardware
profiles in meta and the VRAM budget (handbook: total 24, free 18, reserve 3 -> 15). No network, no real nvidia-smi;
every patched attribute is put back."""
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))

from lodestar import hwprofile, updater  # noqa: E402

SMI = "0, NVIDIA GeForce RTX 4090, 24576, 18432, 6144, 566.36\n"
PS = {"models": [{"name": "qwen3:8b", "size_vram": 6 * 2 ** 30, "context_length": 8192}]}


@contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


class Probe(unittest.TestCase):
    def test_parse_smi_mib_to_gib(self):
        g = hwprofile.parse_smi(SMI + "garbage line\n1, Old card, [N/A], [N/A], [N/A], 470.1\n")
        self.assertEqual(len(g), 2)
        self.assertEqual(g[0], {"index": 0, "name": "NVIDIA GeForce RTX 4090", "total_gib": 24.0, "free_gib": 18.0,
                                "used_gib": 6.0, "driver": "566.36"})
        self.assertIsNone(g[1]["total_gib"])  # unknown stays unknown

    def test_probe_reads_gpu_and_ollama(self):
        with patched(hwprofile, _run_smi=lambda: SMI, _get=lambda path, timeout=5: PS):
            s = hwprofile.probe()
        self.assertEqual(s["source"], "nvidia-smi")
        self.assertEqual(s["gpus"][0]["free_gib"], 18.0)
        self.assertEqual(s["ollama"]["running"], [{"name": "qwen3:8b", "size_vram_gib": 6.0, "context": 8192}])
        self.assertIsNotNone(s["disk"]["free_gib"])
        self.assertTrue(s["at"])

    def test_probe_never_raises(self):
        for exc in (RuntimeError("nvidia-smi not found"), SystemExit("nvidia-smi took longer than 10 s")):
            with patched(hwprofile, _run_smi=_raise(exc), _get=_raise(urllib.error.URLError("refused"))):
                s = hwprofile.probe()
            self.assertIsNone(s["gpus"])
            self.assertIsNone(s["ollama"])
            self.assertEqual(s["source"], "none")
            self.assertIn("GPU:", s["error"])
            self.assertIn("Ollama:", s["error"])

    def test_smi_runs_hidden_through_updater_proc(self):
        got = {}

        def fake_proc(cmd, cwd, timeout, env=None):
            got.update(cmd=cmd, timeout=timeout)
            return 0, SMI, ""
        with patched(updater, _proc=fake_proc), patched(hwprofile.shutil, which=lambda name: "nvidia-smi"):
            out = hwprofile._run_smi()
        self.assertEqual(out, SMI)
        self.assertIn("--query-gpu=index,name,memory.total,memory.free,memory.used,driver_version", got["cmd"])
        self.assertIn("--format=csv,noheader,nounits", got["cmd"])
        with patched(updater, _proc=lambda *a, **k: (9, "", "NVML failed")), \
                patched(hwprofile.shutil, which=lambda name: "nvidia-smi"):
            with self.assertRaises(RuntimeError):
                hwprofile._run_smi()


class Budget(unittest.TestCase):
    def tearDown(self):
        hwprofile._set_meta(hwprofile.PROFILES_KEY, None)
        hwprofile._set_meta(hwprofile.ACTIVE_KEY, None)

    def snap(self):
        return {"gpus": hwprofile.parse_smi(SMI)}

    def test_handbook_budget_24_18_3_is_15(self):
        b = hwprofile.budget(self.snap(), "OBS live")
        self.assertEqual(b["effective_gib"], 15.0)
        self.assertEqual(b["total_gib"], 24.0)
        self.assertEqual(b["per_gpu"][0]["effective_gib"], 15.0)
        self.assertFalse(b["manual"])
        self.assertEqual(hwprofile.budget(self.snap(), "Idle")["effective_gib"], 18.0)
        self.assertEqual(hwprofile.budget(self.snap(), {"reserve_gib": 30})["effective_gib"], 0.0)  # never negative

    def test_profiles_saved_in_meta_and_active_one_used(self):
        self.assertEqual(hwprofile.active_profile(), "Idle")
        hwprofile.save_profile("Gaming", 8, "a game on the side")
        self.assertEqual(hwprofile.profiles()["Gaming"]["reserve_gib"], 8.0)
        hwprofile.set_active("Gaming")
        self.assertEqual(hwprofile.budget(self.snap())["effective_gib"], 10.0)
        hwprofile.delete_profile("Gaming")
        self.assertEqual(hwprofile.active_profile(), "Idle")
        self.assertIn("OBS live", hwprofile.profiles())

    def test_bad_profile_input_is_refused(self):
        for args in (("", 1), ("X", -1), ("X", "lots"), ("X", 999)):
            with self.assertRaises(SystemExit):
                hwprofile.save_profile(*args)
        with self.assertRaises(SystemExit):
            hwprofile.set_active("No such profile")

    def test_manual_snapshot_is_flagged(self):
        b = hwprofile.budget(hwprofile.manual_snapshot(24, 18), "OBS live")
        self.assertTrue(b["manual"])
        self.assertEqual(b["effective_gib"], 15.0)
        with self.assertRaises(SystemExit):
            hwprofile.manual_snapshot(24, 30)

    def test_unknown_free_vram_stays_unknown(self):
        b = hwprofile.budget({"gpus": None}, "Idle")
        self.assertIsNone(b["effective_gib"])
        self.assertIsNone(b["total_gib"])


if __name__ == "__main__":
    unittest.main()
