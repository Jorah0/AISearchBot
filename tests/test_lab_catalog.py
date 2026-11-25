"""Model lab catalog (pass 59, part B): the curated catalog, Ollama variants (model_info keys prefixed by the
architecture), the VRAM estimate (KV = 2 x layers x kv_heads x head_dim x bytes x positions), fit against the budget
(handbook fixtures), search (exact first, words, typos, filters, image input vs output) and the appropriateness score
(handbook 73 / 69). No network: Ollama is faked through modelcat._get / _post, Hugging Face through util.fetch; every
patched attribute is put back."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_lab_hw import _raise, patched  # noqa: E402

from lodestar import modelcat, util  # noqa: E402

GIB = 2 ** 30
SNAP = {"gpus": [{"index": 0, "name": "RTX 4090", "total_gib": 24.0, "free_gib": 18.0, "used_gib": 6.0}]}
OLLAMA_DOWN = {"_get": _raise(urllib.error.URLError("refused")), "_post": _raise(urllib.error.URLError("refused"))}
TAGS = {"models": [
    {"name": "qwen2.5:7b", "digest": "d1", "size": int(4.7e9),
     "details": {"family": "qwen2", "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
    {"name": "mystery:1b", "digest": "d2", "size": int(1e9),
     "details": {"family": "mystery", "parameter_size": "1.2B", "quantization_level": "Q8_0"}}]}
SHOW = {"qwen2.5:7b": {"model_info": {"general.architecture": "qwen2", "qwen2.block_count": 28,
                                      "qwen2.attention.head_count": 28, "qwen2.attention.head_count_kv": 4,
                                      "qwen2.embedding_length": 3584, "qwen2.context_length": 32768}},
        "mystery:1b": {"model_info": {"general.architecture": "mystery"}}}


def ollama_up():
    return {"_get": lambda path, timeout=5: TAGS, "_post": lambda path, body: SHOW[body["model"]]}


def est(lo, hi):
    return {"lo_gib": lo, "hi_gib": hi, "basis": []}


class Fit(unittest.TestCase):
    """The handbook's regression fixtures: total 24, free 18, reserve 3 -> budget 15."""

    def test_8_to_10_fits_33_to_42_percent_5_to_7_left(self):
        f = modelcat.fit(est(8, 10), 15, 24)
        self.assertEqual((f["status"], f["pct_lo"], f["pct_hi"]), ("fits", 33, 42))
        self.assertEqual((f["headroom_lo"], f["headroom_hi"]), (5, 7))

    def test_14_to_17_is_borderline(self):
        self.assertEqual(modelcat.fit(est(14, 17), 15, 24)["status"], "borderline")

    def test_26_to_30_incompatible_108_to_125_short_11_to_15(self):
        f = modelcat.fit(est(26, 30), 15, 24)
        self.assertEqual((f["status"], f["pct_lo"], f["pct_hi"]), ("incompatible", 108, 125))
        self.assertEqual((f["headroom_lo"], f["headroom_hi"]), (-15, -11))
        self.assertIn("short 11-15 GiB", f["reasons"][0])

    def test_unknown_arch_is_unknown_never_a_range(self):
        v = modelcat.variant(id="x", params_b=7, quant="Q4_K_M", arch={"layers": 32})
        e = modelcat.estimate(v)
        self.assertEqual(e["confidence"], "unknown")
        self.assertIsNone(e["lo_gib"])
        self.assertIsNone(e["hi_gib"])
        f = modelcat.fit(e, 15, 24)
        self.assertEqual(f["status"], "unknown")
        self.assertIsNone(f["pct_lo"])
        self.assertEqual(modelcat.fit(est(8, 10), None, 24)["status"], "unknown")  # no GPU read: unknown too


class Estimate(unittest.TestCase):
    V = modelcat.variant(id="m", size_gib=4.0, context_max=131072, arch={"layers": 32, "kv_heads": 8, "head_dim": 128})

    def test_kv_example_is_one_gib(self):
        self.assertEqual(2 * 32 * 8 * 128 * 2 * 8192, GIB)
        e = modelcat.estimate(self.V, {"context": 8192})
        self.assertEqual(e["parts"]["kv"], 1.0)
        self.assertEqual(e["parts"]["weights"], 4.0)
        self.assertEqual(e["lo_gib"], round((5.0 + 0.5) * 1.05, 2))
        self.assertEqual(e["hi_gib"], round((5.0 + 1.5) * 1.15, 2))
        self.assertEqual(modelcat.estimate(self.V, {"context": 8192, "kv_bytes": 0.5, "concurrency": 2})["parts"]["kv"], 0.5)

    def test_weights_from_params_when_no_size(self):
        v = modelcat.variant(id="m", params_b=8, quant="Q8_0", arch={"layers": 32, "kv_heads": 8, "head_dim": 128})
        e = modelcat.estimate(v, {"context": 8192})
        self.assertAlmostEqual(e["parts"]["weights"], round(8e9 * 1.0625 / GIB, 2))
        self.assertEqual(e["confidence"], "low")

    def test_bad_workload_is_refused(self):
        for w in ({"operation": "fly"}, {"kv_bytes": 3}, {"concurrency": 0}, {"context": "lots"}):
            with self.assertRaises(SystemExit):
                modelcat.estimate(self.V, w)

    def test_training_and_export_ranges(self):
        v = modelcat.variant(id="m", params_b=8, size_gib=4.6, arch={"layers": 32, "kv_heads": 8, "head_dim": 128,
                                                                       "hidden": 4096})
        lora, full = modelcat.estimate(v, {"operation": "adapter_train"}), modelcat.estimate(v, {"operation": "full_train"})
        self.assertLess(lora["hi_gib"], full["lo_gib"])
        self.assertGreater(full["lo_gib"], 8e9 * 16 / GIB)  # 16 B / param before activations
        self.assertEqual(modelcat.estimate(v, {"operation": "export"})["confidence"], "low")
        no_hidden = modelcat.variant(id="m", params_b=8, size_gib=4.6, arch={"layers": 32, "kv_heads": 8, "head_dim": 128})
        self.assertEqual(modelcat.estimate(no_hidden, {"operation": "full_train"})["confidence"], "unknown")

    def test_hunyuan3d_publisher_figures(self):
        h = modelcat.get("hunyuan3d-2.1", modelcat.curated())
        self.assertEqual(h["vram_published"], {"shape": 10, "texture": 21, "shape+texture": 29})
        shape = modelcat.estimate(h, {"mode": "shape"})
        self.assertEqual((shape["hi_gib"], shape["confidence"]), (10.0, "publisher-reported"))
        both = modelcat.estimate(h, {"mode": "shape+texture"})
        self.assertEqual(modelcat.fit(both, 15, 24)["status"], "incompatible")
        self.assertEqual(modelcat.estimate(h)["hi_gib"], 29.0)


class Catalog(unittest.TestCase):
    def test_every_entry_is_labelled(self):
        data = json.loads(modelcat.CATALOG.read_text(encoding="utf-8"))
        ids = [e["id"] for e in data["variants"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(15 <= len(ids) <= 25)
        for e in data["variants"]:
            self.assertIn("not checked live", e["verified"], e["id"])
            self.assertTrue(e["provenance"], e["id"])
            self.assertTrue(set(e["provenance"].values()) <= {"publisher", "estimated", "local", "unknown"}, e["id"])
        for need in ("nomic-embed-text", "qwen2.5vl:7b", "sdxl-base-1.0", "flux.1-schnell", "kokoro-82m",
                     "ace-step-v1-3.5b", "hunyuan3d-2.1", "qwen3:30b-a3b", "mistral-nemo:12b"):
            self.assertIn(need, ids)

    def test_arch_from_show_prefixed_keys_and_head_dim(self):
        arch, ctx = modelcat.arch_from_show({"model_info": {
            "general.architecture": "qwen3moe", "qwen3moe.block_count": 48, "qwen3moe.attention.head_count": 32,
            "qwen3moe.attention.head_count_kv": 4, "qwen3moe.embedding_length": 2048,
            "qwen3moe.attention.key_length": 128, "qwen3moe.context_length": 40960}})
        self.assertEqual(arch, {"layers": 48, "kv_heads": 4, "head_dim": 128, "hidden": 2048})
        self.assertEqual(ctx, 40960)
        arch, _ = modelcat.arch_from_show({"model_info": {
            "general.architecture": "llama", "llama.block_count": 32, "llama.attention.head_count": 32,
            "llama.attention.head_count_kv": 8, "llama.embedding_length": 4096}})
        self.assertEqual(arch["head_dim"], 128)  # 4096 / 32 without key_length

    def test_installed_merges_with_curated_and_unknown_stays_unknown(self):
        modelcat._SHOW.clear()
        try:
            with patched(modelcat, **ollama_up()):
                items, sources = modelcat.all_variants()
        finally:
            modelcat._SHOW.clear()
        self.assertTrue(sources["ollama"]["ok"])
        q = modelcat.get("qwen2.5:7b", items)
        self.assertEqual((q["installed"], q["source"], q["digest"], q["name"]), (True, "ollama", "d1", "Qwen2.5 7B Instruct"))
        self.assertEqual(q["provenance"]["arch"], "local")
        self.assertEqual(sum(v["id"] == "qwen2.5:7b" for v in items), 1)
        m = modelcat.get("mystery:1b", items)
        self.assertEqual(m["params_b"], 1.2)
        self.assertEqual(modelcat.estimate(m)["confidence"], "unknown")

    def test_unknown_id_is_refused(self):
        with self.assertRaises(SystemExit):
            modelcat.get("no-such-model", modelcat.curated())


class Search(unittest.TestCase):
    def find(self, q="", **filters):
        with patched(modelcat, **OLLAMA_DOWN):
            return modelcat.search(q, filters, profile="OBS live", snapshot=SNAP)

    def ids(self, r):
        return [v["id"] for v in r["items"]]

    def test_ollama_down_never_raises_and_everything_stays_visible(self):
        r = self.find()
        self.assertFalse(r["sources"]["ollama"]["ok"])
        self.assertEqual(r["budget"]["effective_gib"], 15.0)
        self.assertIn("hunyuan3d-2.1", self.ids(r))  # incompatible ones too
        self.assertEqual(r["counts"]["view"]["all"], len(r["items"]))
        self.assertEqual(r["counts"]["view"]["installed"], 0)

    def test_exact_id_first_then_words(self):
        r = self.find("qwen3:8b")
        self.assertEqual(self.ids(r)[0], "qwen3:8b")
        self.assertEqual(r["items"][0]["match"], 0)
        self.assertEqual(self.ids(self.find("Llama 3.1 8B Instruct"))[0], "llama3.1:8b")
        self.assertEqual(set(self.ids(self.find("qwen3"))), {"qwen3:8b", "qwen3:14b", "qwen3:30b-a3b"})

    def test_typo_tolerance(self):
        r = self.find("mistrel")
        self.assertIn("mistral-nemo:12b", self.ids(r))
        self.assertEqual(r["items"][0]["match"], 2)
        self.assertEqual(self.ids(self.find("zzzzqqq")), [])

    def test_describes_images_is_input_not_output(self):
        r = self.find("describes images")
        self.assertEqual(r["filters"]["input"], "image")
        self.assertIn("qwen2.5vl:7b", self.ids(r))
        self.assertNotIn("sdxl-base-1.0", self.ids(r))
        self.assertTrue(all("image" in v["inputs"] for v in r["items"]))

    def test_generates_images_is_output(self):
        r = self.find("generates images")
        self.assertEqual(set(self.ids(r)), {"sdxl-base-1.0", "flux.1-schnell"})
        self.assertNotIn("qwen2.5vl:7b", self.ids(r))

    def test_filters_and_counts(self):
        r = self.find(view="fits")
        self.assertTrue(r["items"])
        self.assertTrue(all(v["fit"]["status"] == "fits" for v in r["items"]))
        self.assertEqual(r["counts"]["view"]["fits"], len(r["items"]))
        self.assertEqual(self.ids(self.find(task="embedding")), ["nomic-embed-text"])
        self.assertEqual(self.ids(self.find(output="mesh")), ["hunyuan3d-2.1"])
        self.assertTrue(all(v["quant"] == "Q4_K_M" for v in self.find(quant="Q4_K_M")["items"]))
        self.assertEqual(self.find(source="ollama")["items"], [])
        all_ = self.find()
        self.assertEqual(all_["counts"]["output"]["image"], 2)
        self.assertGreaterEqual(all_["counts"]["input"]["image"], 2)  # the VL model and Hunyuan3D
        self.assertEqual(self.find("music")["filters"]["task"], "music")

    def test_installed_view_and_private_candidates(self):
        modelcat._SHOW.clear()
        try:
            with patched(modelcat, **ollama_up()):
                r = modelcat.search("", {"view": "installed"}, "OBS live", SNAP,
                                    extra=[{"id": "lodestar-jobs:cand-1", "size_gib": 5}])
                p = modelcat.search("cand-1", None, "OBS live", SNAP, extra=[{"id": "lodestar-jobs:cand-1"}])
        finally:
            modelcat._SHOW.clear()
        self.assertEqual(set(self.ids(r)), {"qwen2.5:7b", "mystery:1b"})
        self.assertEqual(p["items"][0]["source"], "private")


class HuggingFace(unittest.TestCase):
    def tearDown(self):
        modelcat._db().execute("DELETE FROM catalog_hf")
        modelcat._db().commit()

    def test_hf_metadata_on_click_stored_and_searchable(self):
        rows = [{"id": "acme/tiny-chat", "pipeline_tag": "text-generation", "tags": ["gguf"]},
                {"id": "bad id with spaces", "pipeline_tag": "text-generation"}]
        with patched(util, fetch=lambda url, **k: json.dumps(rows)):
            r = modelcat.hf_search("tiny chat")
        self.assertEqual([v["id"] for v in r["items"]], ["hf:acme/tiny-chat"])
        self.assertEqual(r["added"], 1)
        self.assertIs(modelcat.sync_hf, modelcat.hf_search)
        with patched(modelcat, **OLLAMA_DOWN):
            s = modelcat.search("tiny-chat", None, "Idle", SNAP)
        self.assertEqual(s["items"][0]["fit"]["status"], "unknown")
        with patched(util, fetch=_raise(OSError("down"))):
            self.assertTrue(modelcat.hf_search("x")["error"])
        with self.assertRaises(SystemExit):
            modelcat.hf_search("  ")


class Score(unittest.TestCase):
    W = {"f1": 0.5, "support": 0.3, "latency": 0.2}
    B = {"f1": {"kind": "benefit", "floor": 0.70, "target": 0.90},
         "support": {"kind": "benefit", "floor": 0.90, "target": 1.00},
         "latency": {"kind": "cost", "target": 1.2, "ceiling": 2.8}}

    def test_handbook_73_and_69(self):
        r = modelcat.score([{"id": "b", "metrics": {"f1": 0.88, "support": 0.98, "latency": 2.8}},
                            {"id": "a", "metrics": {"f1": 0.84, "support": 0.96, "latency": 1.2}},
                            {"id": "c", "metrics": {"f1": 0.95}}], self.W, self.B)
        self.assertEqual([(x["id"], x["score"]) for x in r], [("a", 73), ("b", 69), ("c", None)])
        self.assertEqual(r[2]["unmeasured"], ["support", "latency"])

    def test_bad_bounds_and_weights_are_refused(self):
        for b in ({**self.B, "f1": {"kind": "benefit", "floor": 0.9, "target": 0.9}},
                  {**self.B, "latency": {"kind": "cost", "target": 2.8, "ceiling": 1.2}},
                  {**self.B, "f1": {"kind": "benefit", "floor": 0.9, "target": 0.7}},
                  {k: v for k, v in self.B.items() if k != "support"}):
            with self.assertRaises(SystemExit):
                modelcat.score([], self.W, b)
        for w in ({"f1": 0.5, "support": 0.3, "latency": 0.3}, {"f1": 1.2, "support": -0.2, "latency": 0}, {}):
            with self.assertRaises(SystemExit):
                modelcat.score([], w, self.B)


if __name__ == "__main__":
    unittest.main()
