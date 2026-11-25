"""Local generation runtimes (pass 59, plan section G): the registry (ComfyUI, LocalAI, Ollama image probe-only, VRAM
figures labelled publisher-reported), loopback only (any other host refused before a request), probe() never raising,
submit() refused under Full AI and saving artifacts under HOME/media/<job>/ with a media_jobs row. The HTTP layer is
faked by patching media._get / media._post; every patched attribute is put back."""
import base64
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

from lodestar import config, db, media  # noqa: E402


class Patch:
    """Set module attributes for a with-block and put them back."""

    def __init__(self, **attrs):
        self.attrs, self.old = attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.old[k] = getattr(media, k)
            setattr(media, k, v)

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(media, k, v)


def refuse(*a, **k):
    raise AssertionError("no request expected")


def job_row(job_id):
    return db.con().execute("SELECT * FROM media_jobs WHERE id=?", (job_id,)).fetchone()


class Registry(unittest.TestCase):
    def test_runtimes_and_publisher_reported_vram(self):
        reg = media.registry()
        self.assertEqual(reg["comfyui"]["base"], "http://127.0.0.1:8188")
        self.assertEqual(reg["localai"]["base"], "http://127.0.0.1:8080")
        self.assertTrue(reg["ollama_image"]["probe_only"] and reg["ollama_image"]["experimental"])
        for name, rt in reg.items():
            media._loopback(rt["base"])  # every runtime is on this computer
            self.assertTrue(rt["health"].startswith("/") and rt["operations"], name)
        hy = next(v for v in reg["comfyui"]["vram"] if v["model"] == "Hunyuan3D 2.1")
        self.assertEqual(hy["figures"], {"shape": 10, "texture": 21, "combined": 29})
        self.assertEqual((hy["unit"], hy["label"]), ("GB", "publisher-reported"))
        wf = media.sdxl_workflow("a lighthouse", "sdxl_base.safetensors", width=768, seed=7)
        self.assertEqual(wf["4"]["inputs"]["ckpt_name"], "sdxl_base.safetensors")
        self.assertEqual((wf["5"]["inputs"]["width"], wf["3"]["inputs"]["seed"]), (768, 7))
        self.assertNotIn("_fill_in", wf)
        with self.assertRaises(ValueError):
            media.sdxl_workflow("x", "y", width=1001)


class Loopback(unittest.TestCase):
    def test_non_loopback_host_is_refused_before_any_request(self):
        class Opener:
            def open(self, *a, **k):
                raise AssertionError("opened a connection")

        with Patch(_OPENER=Opener()):
            for url in ("http://example.com/x", "http://10.0.0.5:8188/system_stats", "https://127.0.0.1:8188/",
                        "http://127.0.0.1.evil.example/", "file:///C:/Windows/win.ini"):
                with self.assertRaises(ValueError, msg=url):
                    media._get(url)
                with self.assertRaises(ValueError, msg=url):
                    media._post(url, {})
        far = {"comfyui": dict(media.registry()["comfyui"], base="http://192.168.1.20:8188")}
        with Patch(registry=lambda: far, _get=refuse):
            r = media.probe()["comfyui"]
        self.assertFalse(r["up"])
        self.assertIn("loopback", r["error"])


class Probe(unittest.TestCase):
    def test_down_runtime_gives_up_false_without_raising(self):
        def down(url, timeout=10, raw=False):
            raise ConnectionRefusedError("refused")

        with Patch(_get=down):
            out = media.probe()
        self.assertEqual(set(out), {"comfyui", "localai", "ollama_image"})
        for r in out.values():
            self.assertEqual((r["up"], r["models"], r["version"]), (False, [], None))
            self.assertIn("refused", r["error"])

    def test_up_runtimes_report_version_and_models(self):
        answers = {
            "http://127.0.0.1:8188/system_stats": json.dumps({"system": {"comfyui_version": "0.3.60"}}).encode(),
            "http://127.0.0.1:8188/models/checkpoints": ["sdxl_base.safetensors"],
            "http://127.0.0.1:8080/readyz": b"OK",
            "http://127.0.0.1:8080/v1/models": {"data": [{"id": "stablediffusion"}, {"id": "piper"}]},
            "http://127.0.0.1:11434/api/version": b'{"version": "0.13.0"}',
            "http://127.0.0.1:11434/api/tags": {"models": [{"name": "x/z-image-turbo"}]},
        }
        with Patch(_get=lambda url, timeout=10, raw=False: answers[url]):
            out = media.probe()
        self.assertEqual(out["comfyui"], {"up": True, "version": "0.3.60", "models": ["sdxl_base.safetensors"], "error": None})
        self.assertEqual((out["localai"]["version"], out["localai"]["models"]), (None, ["stablediffusion", "piper"]))
        self.assertEqual(out["ollama_image"]["version"], "0.13.0")


class Submit(unittest.TestCase):
    def setUp(self):
        self.pause, media.POLL_PAUSE = media.POLL_PAUSE, 0

    def tearDown(self):
        media.POLL_PAUSE = self.pause

    def test_full_ai_refuses_submit(self):
        config.FULL_AI.on = True
        try:
            with Patch(_post=refuse, _get=refuse), self.assertRaises(SystemExit):
                media.submit("comfyui", {"operation": "text->image", "prompt": "x", "checkpoint": "y.safetensors"})
        finally:
            config.FULL_AI.on = False

    def test_bad_requests_are_refused_before_anything_is_recorded(self):
        before = len(media.jobs(1000))
        with Patch(_post=refuse, _get=refuse):
            for runtime, recipe in (("nope", {"operation": "text->image"}),
                                    ("ollama_image", {"operation": "text->image", "prompt": "x"}),
                                    ("comfyui", {"operation": "text->speech", "prompt": "x"}),
                                    ("comfyui", {"operation": "text->image", "prompt": "x",
                                                 "checkpoint": media.PLACEHOLDER}),
                                    ("localai", {"operation": "text->image", "prompt": "x"})):
                with self.assertRaises(SystemExit, msg=runtime):
                    media.submit(runtime, recipe)
        self.assertEqual(len(media.jobs(1000)), before)

    def test_comfyui_job_saves_artifacts_under_home_media(self):
        posted, polls = [], []

        def post(url, body, timeout=60, raw=False):
            posted.append((url, body))
            return {"prompt_id": "p-1"}

        def get(url, timeout=10, raw=False):
            if "/history/" in url:
                polls.append(url)
                if len(polls) < 2:
                    return {}
                return {"p-1": {"status": {"status_str": "success"}, "outputs": {"9": {"images": [
                    {"filename": "lodestar_00001_.png", "subfolder": "", "type": "output"},
                    {"filename": "../../escape.png", "subfolder": "", "type": "output"}]}}}}
            self.assertTrue(url.startswith("http://127.0.0.1:8188/view?"))
            return b"PNGDATA"

        with Patch(_post=post, _get=get):
            job = media.submit("comfyui", {"operation": "text->image", "prompt": "a lighthouse at dusk",
                                           "checkpoint": "sdxl_base.safetensors"})
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(posted[0][0], "http://127.0.0.1:8188/prompt")
        wf = posted[0][1]["prompt"]
        self.assertEqual((wf["4"]["inputs"]["ckpt_name"], wf["6"]["inputs"]["text"]),
                         ("sdxl_base.safetensors", "a lighthouse at dusk"))
        folder = (Path(config.HOME) / "media" / job["id"]).resolve()
        self.assertEqual(len(job["artifacts"]), 2)
        for a in job["artifacts"]:
            self.assertEqual(Path(a).resolve().parent, folder)  # a hostile file name stays in the job folder
            self.assertEqual(Path(a).read_bytes(), b"PNGDATA")
        row = job_row(job["id"])
        self.assertEqual((row["status"], row["runtime"], row["operation"]), ("done", "comfyui", "text->image"))
        self.assertEqual(len(row["recipe_hash"]), 64)
        self.assertEqual(json.loads(row["artifacts"]), job["artifacts"])
        self.assertEqual(row["peak"], "not measured")
        self.assertEqual(media.jobs(1)[0]["id"], job["id"])

    def test_comfyui_that_never_finishes_times_out(self):
        with Patch(_post=lambda *a, **k: {"prompt_id": "p-2"}, _get=lambda *a, **k: {}, POLL_MAX=3):
            job = media.submit("comfyui", {"operation": "text->image", "prompt": "x", "checkpoint": "y.safetensors"})
        self.assertEqual(job["status"], "timeout")
        self.assertEqual(job_row(job["id"])["status"], "timeout")

    def test_localai_image_and_speech(self):
        def post(url, body, timeout=60, raw=False):
            if url.endswith("/v1/audio/speech"):
                self.assertTrue(raw)
                self.assertEqual(body, {"model": "piper", "input": "Hello there"})
                return b"RIFFWAVE"
            self.assertEqual(url, "http://127.0.0.1:8080/v1/images/generations")
            return {"data": [{"b64_json": base64.b64encode(b"IMG").decode()}]}

        with Patch(_post=post, _get=refuse):
            img = media.submit("localai", {"operation": "text->image", "model": "sd", "prompt": "a cat"})
            speech = media.submit("localai", {"operation": "text->speech", "model": "piper", "text": "Hello there"})
        self.assertEqual(Path(img["artifacts"][0]).read_bytes(), b"IMG")
        self.assertEqual(Path(speech["artifacts"][0]).read_bytes(), b"RIFFWAVE")

    def test_runtime_failure_is_recorded_not_raised(self):
        def down(*a, **k):
            raise ConnectionRefusedError("refused")

        with Patch(_post=down, _get=down):
            job = media.submit("localai", {"operation": "text->image", "model": "sd", "prompt": "x"})
        self.assertEqual(job["status"], "failed")
        self.assertIn("refused", job_row(job["id"])["error"])

    def test_peak_note_is_the_publisher_figure(self):
        rt = media.registry()["comfyui"]
        note = media._peak(rt, {"operation": "image->mesh", "workflow": {"1": {"model": "Hunyuan3D 2.1"}}})
        self.assertTrue(note.startswith("publisher-reported: Hunyuan3D 2.1"))
        self.assertIn("combined 29 GB", note)


def tearDownModule():  # the shared test home: no media_jobs rows left behind
    from lodestar import db

    db.con().execute("DELETE FROM media_jobs")
    db.con().commit()


if __name__ == "__main__":
    unittest.main()
