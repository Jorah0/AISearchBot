"""Model lab training (pass 59, section E): scratch parameter count and validation, memory and token plans, the
training environment's setup commands (venv, the CUDA torch index, no keys passed), immutable idempotent jobs, the
single GPU lease, the worker's stripped environment, progress polling and recovery, Full AI refusals, and a worker
module that imports without torch. No network, no torch, no real subprocess; every patched attribute is put back."""
import ast
import importlib
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
from test_pass21_fit import patched  # noqa: E402

from lodestar import config, db, labtrain, updater  # noqa: E402

PRESET = {"arch": "llama", "vocab": 8192, "layers": 8, "hidden": 512, "mlp": 1376, "heads": 8, "kv_heads": 2,
          "head_dim": 64, "context": 1024, "tied": True, "seed": 7}
TINY = PRESET | {"vocab": 256, "layers": 2, "hidden": 64, "mlp": 128, "heads": 4, "kv_heads": 2, "head_dim": 16,
                 "context": 64}


class Env:
    """Fake env vars for one test; put back after."""
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Sizes(unittest.TestCase):
    def test_the_handbook_preset_has_26_354_176_parameters_and_untied_adds_vd(self):
        got = labtrain.scratch_params(PRESET)
        self.assertEqual(got["total"], 26_354_176)
        self.assertEqual(sum(got["breakdown"].values()), got["total"])
        self.assertEqual(labtrain.scratch_params(PRESET | {"tied": False})["total"] - got["total"], 4_194_304)

    def test_validation_names_each_broken_rule(self):
        self.assertEqual(labtrain.validate_scratch(PRESET), [])
        self.assertTrue(any("positive" in e for e in labtrain.validate_scratch(PRESET | {"layers": 0})))
        self.assertTrue(any("positive" in e for e in labtrain.validate_scratch(PRESET | {"hidden": "512"})))
        self.assertTrue(any("hidden must divide" in e for e in labtrain.validate_scratch(PRESET | {"hidden": 516, "head_dim": 64})))
        self.assertTrue(any("kv_heads" in e for e in labtrain.validate_scratch(PRESET | {"kv_heads": 3})))
        self.assertTrue(any("even" in e for e in labtrain.validate_scratch(PRESET | {"hidden": 504, "head_dim": 63})))
        self.assertTrue(any("equal hidden" in e for e in labtrain.validate_scratch(PRESET | {"head_dim": 32})))
        self.assertTrue(any("context" in e for e in labtrain.validate_scratch(PRESET | {"context": 8})))
        self.assertTrue(any("vocab" in e for e in labtrain.validate_scratch(PRESET | {"vocab": 100})))
        self.assertTrue(any("seed" in e for e in labtrain.validate_scratch(PRESET | {"seed": 1.5})))

    def test_token_plan_matches_the_handbook(self):
        self.assertEqual(labtrain.token_plan(50_000_000, 1024, 2, 8, 1),
                         {"per_update": 16_384, "updates": 3_052, "hours": None})
        self.assertEqual(labtrain.token_plan(50_000_000, 1024, 2, 8, 1, tok_per_s=600)["hours"], 23.1)

    def test_train_memory_is_a_labelled_range(self):
        for args in ((PRESET, "scratch"), (26_354_176, "scratch"), ({"params_b": 8}, "lora"), (PRESET, "lora")):
            m = labtrain.train_memory(*args)
            self.assertLess(0, m["lo_gib"])
            self.assertLessEqual(m["lo_gib"], m["hi_gib"])
            self.assertTrue(m["estimate"])
            self.assertIn("estimate", m["basis"])
            self.assertIn("activations", m["parts"])
        full = labtrain.train_memory(PRESET, "scratch")
        self.assertAlmostEqual(full["parts"]["states"], 16 * 26_354_176 / 2 ** 30, places=2)
        q = labtrain.train_memory({"params_b": 8}, "lora")
        self.assertAlmostEqual(q["parts"]["weights"], 0.55 * 8e9 / 2 ** 30, places=1)
        self.assertLess(q["hi_gib"], 24)  # an 8B QLoRA fits a 24 GB card by this estimate


class Setup(unittest.TestCase):
    def setUp(self):
        self.env = Path(tempfile.mkdtemp(prefix="train-env-")) / "train-env"

    def test_setup_runs_venv_then_pinned_pip_with_the_cuda_index_and_no_keys(self):
        calls = []
        rec = lambda cmd, cwd, timeout, env=None: calls.append((cmd, env)) or (0, "", "")  # noqa: E731
        with Env(OPENAI_API_KEY="sk-test", GITHUB_TOKEN="t", MAIL_PASSWORD="p", HF_TOKEN="h"), \
                patched(labtrain, ENV_DIR=self.env), patched(updater, _proc=rec):
            got = labtrain.setup_env()
        self.assertTrue(got["ok"])
        self.assertEqual(got["summary"], "training environment ready")
        cmds = [c for c, _ in calls]
        self.assertEqual(cmds[0][1:], ["-m", "venv", str(self.env)])
        py = str(self.env / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        self.assertTrue(all(c[0] == py for c in cmds[1:]))
        torch = next(c for c in cmds if labtrain.TORCH in c)
        self.assertEqual(torch[torch.index("--index-url") + 1], labtrain.TORCH_INDEX)
        self.assertRegex(labtrain.TORCH_INDEX, r"^https://download\.pytorch\.org/whl/cu12\d$")
        flat = [a for c in cmds for a in c]
        for pkg in ("transformers==", "peft==", "trl==", "datasets==", "accelerate==", "safetensors==", "sentencepiece==",
                    "tokenizers==", "bitsandbytes=="):
            self.assertTrue(any(a.startswith(pkg) for a in flat), pkg)
        for _, env in calls:
            self.assertIsNotNone(env)
            for k in ("OPENAI_API_KEY", "GITHUB_TOKEN", "MAIL_PASSWORD", "HF_TOKEN", "ANTHROPIC_API_KEY"):
                self.assertNotIn(k, env)
        self.assertTrue(labtrain.LOG.exists())

    def test_a_failed_optional_package_is_reported_alone(self):
        rec = lambda cmd, cwd, timeout, env=None: (1, "", "no wheel") if "bitsandbytes" in " ".join(cmd) else (0, "", "")  # noqa: E731
        with patched(labtrain, ENV_DIR=self.env), patched(updater, _proc=rec):
            got = labtrain.setup_env()
        self.assertTrue(got["ok"])
        self.assertEqual([f["step"] for f in got["optional_failed"]], ["optional bitsandbytes"])
        self.assertIn("optional bitsandbytes failed", got["summary"])

    def test_env_status_without_an_environment_runs_nothing(self):
        with patched(labtrain, ENV_DIR=self.env), patched(updater, _proc=lambda *a, **k: self.fail("ran")):
            st = labtrain.env_status()
        self.assertFalse(st["exists"])
        self.assertEqual(set(st["packages"]), {"torch", "transformers", "peft", "trl", "datasets", "accelerate", "bitsandbytes"})

    def test_env_status_reads_the_probe_line(self):
        py = self.env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        py.parent.mkdir(parents=True)
        py.write_text("")
        line = json.dumps({"packages": {"torch": "2.14.1", "trl": None}, "cuda": {"available": True, "version": "12.6"}})
        seen = []
        rec = lambda cmd, cwd, timeout, env=None: seen.append(cmd) or (0, "noise\n" + line, "")  # noqa: E731
        with patched(labtrain, ENV_DIR=self.env), patched(updater, _proc=rec):
            st = labtrain.env_status()
        self.assertEqual((st["packages"]["torch"], st["packages"]["trl"], st["cuda"]["available"]), ("2.14.1", None, True))
        self.assertEqual(seen[0][:3], [str(py), "-I", "-c"])
        with patched(labtrain, ENV_DIR=self.env), patched(updater, _proc=lambda *a, **k: self.fail("ran")):
            self.assertEqual(labtrain.env_status(cached=True)["packages"]["torch"], "2.14.1")  # the last probe, no run

    def test_full_ai_refuses_setup_and_start(self):
        job = labtrain.plan("probe", 9001, 1, TINY)
        config.FULL_AI.on = True
        try:
            with patched(updater, _proc=lambda *a, **k: self.fail("ran")):
                with self.assertRaisesRegex(SystemExit, "Full AI never"):
                    labtrain.setup_env()
                with self.assertRaisesRegex(SystemExit, "Full AI never"):
                    labtrain.start(job["id"])
        finally:
            config.FULL_AI.on = False


class FakePopen:
    seen = []

    def __init__(self, cmd, **kw):
        self.pid = os.getpid()  # a live pid
        FakePopen.seen.append((cmd, kw))


class Jobs(unittest.TestCase):
    def tearDown(self):
        db.meta_set(labtrain.LEASE, None)

    def test_plan_is_immutable_and_idempotent(self):
        a = labtrain.plan("scratch", 9100, 1, PRESET | {"tokens_budget": 50_000_000})
        b = labtrain.plan("scratch", 9100, 1, PRESET | {"tokens_budget": 50_000_000})
        self.assertEqual((a["id"], a["idem_key"]), (b["id"], b["idem_key"]))
        self.assertEqual(a["status"], "planned")
        self.assertEqual(a["plan"]["expected_params"], 26_354_176)
        self.assertEqual(a["plan"]["hyper"]["lr"], 3e-4)
        c = labtrain.plan("scratch", 9100, 1, PRESET | {"tokens_budget": 50_000_000}, hyper={"lr": 1e-4})
        d = labtrain.plan("scratch", 9100, 2, PRESET | {"tokens_budget": 50_000_000})
        self.assertEqual(len({a["id"], c["id"], d["id"]}), 3)
        with self.assertRaisesRegex(SystemExit, "unknown job kind"):
            labtrain.plan("dpo", 9100, 1, PRESET)
        with self.assertRaisesRegex(SystemExit, "does not hold"):
            labtrain.plan("scratch", 9100, 1, PRESET | {"kv_heads": 3})
        with self.assertRaisesRegex(SystemExit, "dataset"):
            labtrain.plan("lora", 9100, 1, {"base": "org/model"})
        lo = labtrain.plan("lora", 9100, 1, {"base": "org/model"}, "d.jsonl", "abc")
        self.assertEqual((lo["plan"]["hyper"]["rank"], lo["plan"]["hyper"]["accum"]), (16, 16))

    def test_start_refuses_while_a_live_job_holds_the_lease(self):
        a = labtrain.plan("probe", 9200, 1, TINY)
        b = labtrain.plan("probe", 9200, 2, TINY)
        labtrain._set(a["id"], status="running", progress={"pid": os.getpid()})
        db.meta_set(labtrain.LEASE, a["id"])
        with patched(labtrain.subprocess, Popen=lambda *x, **k: self.fail("spawned")):
            with self.assertRaisesRegex(SystemExit, f"in use by training job #{a['id']}"):
                labtrain.start(b["id"])
        labtrain._set(a["id"], status="failed")

    def test_start_spawns_the_worker_hidden_with_a_stripped_env_and_takes_the_lease(self):
        env_dir = Path(tempfile.mkdtemp(prefix="train-env-")) / "train-env"
        py = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        py.parent.mkdir(parents=True)
        py.write_text("")
        job = labtrain.plan("probe", 9300, 1, TINY)
        FakePopen.seen.clear()
        with Env(OPENAI_API_KEY="sk-test", SOME_SECRET="s", GH_TOKEN="t", SMTP_PASSWORD="p"), \
                patched(labtrain, ENV_DIR=env_dir), patched(labtrain.subprocess, Popen=FakePopen):
            got = labtrain.start(job["id"])
        cmd, kw = FakePopen.seen[0]
        self.assertEqual(cmd[:3], [str(py), "-I", str(labtrain.WORKER)])
        spec = json.loads(Path(cmd[3]).read_text(encoding="utf-8"))
        self.assertEqual((spec["kind"], spec["expected_params"]), ("probe", labtrain.scratch_params(TINY)["total"]))
        self.assertEqual(kw["creationflags"], labtrain.NO_WINDOW)
        for k in ("OPENAI_API_KEY", "SOME_SECRET", "GH_TOKEN", "SMTP_PASSWORD", "ANTHROPIC_API_KEY"):
            self.assertNotIn(k, kw["env"])
        self.assertIn("PATH", {k.upper() for k in kw["env"]})
        self.assertEqual(got["status"], "running")
        self.assertEqual(db.meta_get(labtrain.LEASE), job["id"])
        labtrain._set(job["id"], status="failed")

    def test_worker_env_drops_every_secret_looking_name(self):
        with Env(OPENAI_API_KEY="a", HF_TOKEN="b", CLIENT_SECRET="c", MAIL_PASSWORD="d", LODESTAR_HOME_X="keep"):
            env = labtrain.worker_env()
        self.assertEqual({"OPENAI_API_KEY", "HF_TOKEN", "CLIENT_SECRET", "MAIL_PASSWORD"} & set(env), set())
        self.assertEqual(env["LODESTAR_HOME_X"], "keep")

    def _running(self, sel, lines, pid=0):
        job = labtrain.plan("probe", sel, 1, TINY)
        d = labtrain.job_dir(job)
        d.mkdir(parents=True, exist_ok=True)
        (d / "progress.jsonl").write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
        labtrain._set(job["id"], status="running", progress={"pid": pid})
        db.meta_set(labtrain.LEASE, job["id"])
        return job

    def test_poll_reads_the_last_progress_line(self):
        step = json.dumps({"step": 10, "loss": 2.5, "tokens": 163840, "tok_per_s": 600, "vram_peak_gib": 3.1,
                           "status": "running", "msg": ""})
        done = json.dumps({"step": 20, "loss": 2.1, "tokens": 327680, "tok_per_s": 610, "vram_peak_gib": 3.2,
                           "status": "done", "msg": "ok"})
        job = self._running(9400, [step, "{torn", done])
        got = labtrain.poll(job["id"])
        self.assertEqual(got["status"], "done")
        self.assertEqual((got["progress"]["last"]["step"], got["progress"]["lines"]), (20, 2))
        self.assertTrue(got["finished"])
        self.assertEqual(db.meta_get(labtrain.LEASE), 0)
        paused = self._running(9401, [step, json.dumps({"status": "paused", "step": 10})])
        self.assertEqual(labtrain.poll(paused["id"])["status"], "paused")
        bad = self._running(9402, [json.dumps({"status": "failed", "msg": "non-finite loss; stopped"})])
        got = labtrain.poll(bad["id"])
        self.assertEqual((got["status"], got["progress"]["reason"]), ("failed", "non-finite loss; stopped"))

    def test_a_running_job_whose_process_is_gone_fails_with_process_ended(self):
        live = self._running(9500, [json.dumps({"status": "running", "step": 1})], pid=os.getpid())
        self.assertEqual(labtrain.poll(live["id"])["status"], "running")
        labtrain._set(live["id"], status="failed")
        gone = self._running(9501, [json.dumps({"status": "running", "step": 1})], pid=0)
        labtrain.recover()
        got = labtrain.get(gone["id"])
        self.assertEqual((got["status"], got["progress"]["reason"]), ("failed", "process ended"))
        self.assertEqual(db.meta_get(labtrain.LEASE), 0)

    def test_pause_writes_the_flag_and_cancel_releases_the_lease(self):
        job = self._running(9600, [], pid=0)
        labtrain.pause(job["id"])
        self.assertTrue((labtrain.job_dir(job) / "pause").exists())
        got = labtrain.cancel(job["id"])
        self.assertEqual(got["status"], "cancelled")
        self.assertTrue((labtrain.job_dir(job) / "cancel").exists())
        self.assertEqual(db.meta_get(labtrain.LEASE), 0)


class NoTorch(unittest.TestCase):
    def test_the_worker_module_imports_without_torch(self):
        saved = {k: sys.modules.pop(k) for k in list(sys.modules)
                 if k in ("torch", "lodestar.labtrain_worker") or k.startswith("torch.")}
        sys.modules["torch"] = None  # `import torch` now raises ImportError
        try:
            w = importlib.import_module("lodestar.labtrain_worker")
            self.assertEqual(set(w.MODES), {"probe", "scratch", "lora", "export"})
            self.assertIsNone(w.vram_peak())
        finally:
            sys.modules.pop("torch", None)
            sys.modules.pop("lodestar.labtrain_worker", None)
            sys.modules.update(saved)

    def test_the_app_side_never_imports_torch_or_lodestar_in_the_worker(self):
        root = Path(labtrain.__file__).parent
        for name in ("labtrain.py", "labtrain_worker.py"):
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            mods = {a.name.split(".")[0] for n in top if isinstance(n, ast.Import) for a in n.names}
            mods |= {(n.module or "").split(".")[0] for n in top if isinstance(n, ast.ImportFrom)}
            self.assertFalse(mods & {"torch", "transformers", "peft", "trl", "datasets"}, name)
        worker = ast.parse((root / "labtrain_worker.py").read_text(encoding="utf-8"))
        self.assertFalse([n for n in ast.walk(worker) if isinstance(n, ast.ImportFrom) and (n.level or n.module == "lodestar")])
        app = ast.parse((root / "labtrain.py").read_text(encoding="utf-8"))
        self.assertFalse([n for n in ast.walk(app) if isinstance(n, ast.Import) and any(a.name == "torch" for a in n.names)])


def tearDownModule():  # the shared test home: no lab_jobs rows or GPU lease left behind (a failed assertion too)
    from lodestar import db

    db.con().execute("DELETE FROM lab_jobs")
    db.con().execute("DELETE FROM meta WHERE key='lab:lease'")
    db.con().commit()


if __name__ == "__main__":
    unittest.main()
