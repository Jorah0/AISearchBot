"""Model lab integration (pass 59, modellab.py): versioned selections with a revision guard, the fit judged against the
effective budget (free minus the profile's reserve), preflight gates with remedies, candidates built under their own
tag, promotion only on a better held-out score with rollback, the training job chained to its export, and the tab's
one action. Ollama, nvidia-smi and the training env are faked; every patch is put back."""
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

from lodestar import db, hwprofile, jobmodel, labtrain, modelcat, modellab, teacher  # noqa: E402

# the handbook profile: a 24 GiB card with 18 GiB free (assessed under a profile reserving 3 GiB: budget 15)
SNAP = {"at": "2026-11-24 10:00:00", "gpus": [{"index": 0, "name": "RTX 4090", "total_gib": 24.0, "free_gib": 18.0,
                                               "used_gib": 6.0, "driver": "621"}],
        "ram": {"total_gib": 128, "free_gib": 100}, "disk": {"path": "x", "free_gib": 500}, "ollama": {"running": []},
        "source": "nvidia-smi", "error": None}
VAR = {"id": "qwen2.5:7b", "name": "qwen2.5:7b", "installed": True, "context_max": 32768, "task": "text"}


class LabBase(unittest.TestCase):
    def setUp(self):
        modellab._init()
        for key in (modellab.REL_KEY, modellab.SEL_KEY, modellab.HW_KEY, "lab:profiles", "lab:profile"):
            self.addCleanup(jobmodel._set_meta, key, jobmodel._meta(key))
            jobmodel._set_meta(key, None)
        self.addCleanup(jobmodel._set_meta, jobmodel.KEY, jobmodel._meta(jobmodel.KEY))
        self.addCleanup(lambda: db.con().execute("DELETE FROM lab_selections") and db.con().commit())
        db.con().execute("DELETE FROM lab_selections")
        db.con().commit()
        hwprofile.save_profile("Streaming", 3)
        self.posts = []
        self.p = [patched(hwprofile, probe=lambda: dict(SNAP)), patched(modelcat, get=lambda vid, items=None: dict(VAR)),
                  patched(jobmodel, _post=lambda path, body, timeout=600: self.posts.append((path, body)) or {"status": "success"})]
        for x in self.p:
            x.__enter__()
            self.addCleanup(x.__exit__, None, None, None)

    def existing(self, **kw):
        return {"variant_id": "qwen2.5:7b", "num_ctx": 8192, "profile": "Streaming"} | kw


class Lab(LabBase):

    def test_selections_are_versioned_and_a_stale_editor_is_refused(self):
        s = modellab.save("existing", self.existing())
        self.assertEqual((s["rev"], s["spec"]["route"], s["spec"]["kv_type"]), (1, "inference", "f16"))
        s2 = modellab.save("existing", self.existing(num_ctx=4096), sel_id=s["id"], expected_rev=1)
        self.assertEqual((s2["id"], s2["rev"]), (s["id"], 2))
        with self.assertRaises(SystemExit):  # another tab still editing revision 1
            modellab.save("existing", self.existing(), sel_id=s["id"], expected_rev=1)
        self.assertEqual(modellab.get(s["id"], 1)["spec"]["num_ctx"], 8192)  # revision 1 kept as it was
        for bad in ({"num_ctx": 100}, {"route": "magic"}, {"kv_type": "q2"}, {"variant_id": ""}):
            with self.assertRaises(SystemExit):
                modellab.clean_spec("existing", self.existing(**bad))
        with self.assertRaises(SystemExit):  # 7 heads do not divide a 512 width
            modellab.clean_spec("scratch", {"heads": 7})
        sc = modellab.clean_spec("scratch", {})
        self.assertEqual(labtrain.scratch_params(sc)["total"], 26_354_176)  # the handbook preset by default

    def test_fit_is_judged_against_the_budget_after_the_reserve(self):
        sel = {"id": 0, "rev": 0, "mode": "existing", "spec": modellab.clean_spec("existing", self.existing())}
        est = {"lo_gib": 14.0, "hi_gib": 17.0, "parts": {}, "confidence": "medium", "basis": []}
        with patched(modelcat, estimate=lambda v, w=None: dict(est)):
            a = modellab.assess(sel, dict(SNAP))
        self.assertEqual(a["budget"]["effective_gib"], 15.0)  # 18 free - 3 reserve
        self.assertEqual(a["status"], "borderline")  # 14-17 against 15, not against the card's 24
        with patched(modelcat, estimate=lambda v, w=None: est | {"lo_gib": 26.0, "hi_gib": 30.0}):
            self.assertEqual(modellab.assess(sel, dict(SNAP))["status"], "incompatible")

    def test_preflight_names_each_gate_and_its_remedy(self):
        s = modellab.save("existing", self.existing(route="adapter", num_ctx=65536))
        with patched(modelcat, estimate=lambda v, w=None: {"lo_gib": 6, "hi_gib": 8, "parts": {}, "confidence": "medium", "basis": []}), \
                patched(labtrain, env_status=lambda cached=False: {"exists": False, "packages": {}}), \
                patched(teacher, stats=lambda: {"by_split": {"train": 3}}):
            pf = modellab.preflight(s["id"], snapshot=dict(SNAP))
        g = {x["gate"]: x for x in pf["gates"]}
        self.assertEqual(g["fits this computer"]["status"], "pass")
        self.assertEqual(g["context"]["status"], "fail")  # 65536 over the model's 32768
        self.assertEqual(g["trainable weights"]["status"], "fail")  # an Ollama tag is not a trainable checkpoint
        self.assertIn("hf_repo", g["trainable weights"]["remedy"])
        self.assertEqual(g["training environment"]["status"], "fail")
        self.assertEqual(g["training data"]["status"], "fail")
        self.assertFalse(pf["ready"])
        with self.assertRaises(SystemExit):  # nothing is built while a gate fails
            modellab.build_candidate(s["id"])

    def test_a_candidate_goes_live_only_when_it_beats_the_live_model_and_rolls_back(self):
        s = modellab.save("existing", self.existing())
        with patched(modelcat, estimate=lambda v, w=None: {"lo_gib": 6, "hi_gib": 8, "parts": {}, "confidence": "medium", "basis": []}):
            c = modellab.build_candidate(s["id"])
        self.assertEqual(c["tag"], "lodestar-jobs:cand-1")
        create = [b for pth, b in self.posts if pth == "/api/create"][-1]
        self.assertEqual((create["model"], create["from"], create["parameters"]["num_ctx"]), (c["tag"], "qwen2.5:7b", 8192))
        self.assertIsNone(jobmodel.built())  # a candidate never replaces the live model by itself
        with self.assertRaises(SystemExit):
            modellab.promote(c["tag"])  # not evaluated yet
        jobmodel._set_meta(jobmodel.KEY, {"base": "llama3.2", "fp": "x", "built_at": "2026-11-24 09:00:00"})
        scores = {c["tag"]: 0.5, jobmodel.NAME: 0.75}
        with patched(jobmodel, accuracy=lambda m: {"accuracy": scores[m], "scored": 4, "pairs": 4}):
            modellab.evaluate(c["tag"])
            with self.assertRaises(SystemExit):  # worse than the live model: it stays a candidate
                modellab.promote(c["tag"])
            scores[c["tag"]] = 0.9
            modellab.evaluate(c["tag"])
            rel = modellab.promote(c["tag"])
        copies = [(b["source"], b["destination"]) for pth, b in self.posts if pth == "/api/copy"]
        self.assertEqual(copies, [(jobmodel.NAME, "lodestar-jobs:prev-1"), (c["tag"], jobmodel.NAME)])
        self.assertEqual(rel["active"]["tag"], c["tag"])
        modellab.rollback()
        self.assertEqual([(b["source"], b["destination"]) for pth, b in self.posts if pth == "/api/copy"][-1],
                         ("lodestar-jobs:prev-1", jobmodel.NAME))
        with self.assertRaises(SystemExit):
            modellab.rollback()  # nothing older left

    def test_a_finished_training_job_is_exported_under_the_candidate_tag(self):
        planned, started = [], []
        jobs = {7: {"id": 7, "status": "done", "idem_key": "a" * 32, "plan": {"spec": {"base": "Qwen/Qwen2.5-7B-Instruct"}}, "progress": {}},
                8: {"id": 8, "status": "done", "idem_key": "b" * 32, "plan": {}, "progress": {"msg": "ollama model lodestar-jobs:cand-1 created"}}}
        modellab._save_rel({"candidates": [{"n": 1, "tag": "lodestar-jobs:cand-1", "sel_id": 1, "rev": 1, "kind": "lora",
                                            "job_id": 7, "status": "training"}]})
        s = modellab.save("existing", self.existing(route="adapter", hf_repo="Qwen/Qwen2.5-7B-Instruct"))
        cand = modellab.releases()["candidates"][0]
        cand["sel_id"] = s["id"]
        modellab._save_rel(modellab.releases() | {"candidates": [cand]})
        with patched(labtrain, get=lambda i: jobs[i], start=lambda i: started.append(i),
                     plan=lambda kind, sid, rev, spec, **kw: planned.append((kind, spec, kw["hyper"])) or {"id": 8}):
            modellab._sync_jobs()
            self.assertEqual(modellab.releases()["candidates"][0]["status"], "exporting")
            kind, spec, hyper = planned[0]
            self.assertEqual((kind, spec["base"], hyper["tag"], started), ("export", "Qwen/Qwen2.5-7B-Instruct", "lodestar-jobs:cand-1", [8]))
            self.assertTrue(spec["adapter"].endswith("adapter"))
            modellab._sync_jobs()
        self.assertEqual(modellab.releases()["candidates"][0]["status"], "built")

    def test_the_tab_state_needs_no_network_and_unknown_actions_are_refused(self):
        with patched(labtrain, env_status=lambda cached=False: {"exists": False, "packages": {}}):
            st = modellab.do("state", {})
        for k in ("profiles", "catalog", "selections", "releases", "teacher", "examples", "env", "jobs", "evidence"):
            self.assertIn(k, st)
        self.assertIn("Streaming", st["profiles"])
        with self.assertRaises(SystemExit):
            modellab.do("format_disk", {})
        r = modellab.do("scratch_calc", {"spec": {}})
        self.assertEqual(r["params"]["total"], 26_354_176)


class ReviewFixes(LabBase):
    """Regressions found by the pass-59 review: each test names the failure it prevents."""

    def promoted(self, n):
        """n promotions in a row; returns the /api/copy destinations."""
        jobmodel._set_meta(jobmodel.KEY, {"base": "llama3.2", "fp": "x", "built_at": "2026-11-24 09:00:00"})
        acc = {"v": 0.5}
        for i in range(1, n + 1):
            tag = f"lodestar-jobs:cand-{i}"
            with modellab._REL_LOCK:
                r = modellab.releases()
                r.setdefault("candidates", []).append({"n": i, "tag": tag, "sel_id": 1, "rev": 1, "kind": "inference", "status": "built"})
                modellab._save_rel(r)
            acc["v"] += 0.01
            with patched(jobmodel, accuracy=lambda m, a=acc["v"]: {"accuracy": a if m != jobmodel.NAME else a - 0.01, "scored": 4, "pairs": 4}):
                modellab.evaluate(tag)
                modellab.promote(tag)
        return [b["destination"] for pth, b in self.posts if pth == "/api/copy"]

    def test_the_daily_rebuild_never_overwrites_a_promoted_release(self):
        self.promoted(1)
        self.posts.clear()
        self.assertIsNone(jobmodel.tick())  # the loop step leaves the lab's release alone
        r = jobmodel.build()  # Setup's Build now without force: refused with the reason
        self.assertFalse(r["changed"])
        self.assertIn("Model lab release", r["note"])
        self.assertEqual([p for p, _ in self.posts], [])

    def test_rollback_names_are_never_reused_after_many_promotions(self):
        dests = [d for d in self.promoted(7) if ":prev-" in d]
        self.assertEqual(len(dests), len(set(dests)))  # prev-1 .. prev-7, none overwritten
        self.assertEqual(dests[-1], "lodestar-jobs:prev-7")
        st = [c["status"] for c in modellab.releases()["candidates"]]
        self.assertEqual(st.count("live"), 1)  # the older live candidates say replaced

    def test_a_stale_evaluation_cannot_beat_a_newer_live_model(self):
        self.promoted(1)
        with modellab._REL_LOCK:
            r = modellab.releases()
            r["candidates"].append({"n": 9, "tag": "lodestar-jobs:cand-9", "sel_id": 1, "rev": 1, "kind": "inference",
                                    "status": "built", "eval": {"at": "2026-01-01 00:00:00", "candidate": {"accuracy": 0.99}}})
            modellab._save_rel(r)
        with self.assertRaises(SystemExit):
            modellab.promote("lodestar-jobs:cand-9")  # evaluated before the live one went live

    def test_the_revision_guard_needs_the_revision_you_loaded(self):
        s = modellab.save("existing", self.existing())
        with self.assertRaises(SystemExit):  # an edit without expected_rev is refused, never a blind overwrite
            modellab.save("existing", self.existing(), sel_id=s["id"])

    def test_qlora_needs_bitsandbytes_and_cuda_before_it_starts(self):
        s = modellab.save("existing", self.existing(route="adapter", hf_repo="Qwen/Qwen2.5-7B-Instruct"))
        env = {"exists": True, "packages": {"torch": "2.14.1", "bitsandbytes": None}, "cuda": "12.6"}
        with patched(modelcat, estimate=lambda v, w=None: {"lo_gib": 6, "hi_gib": 8, "parts": {}, "confidence": "low", "basis": []}), \
                patched(labtrain, env_status=lambda cached=False: env), patched(teacher, stats=lambda: {"by_split": {"train": 50}}):
            g = {x["gate"]: x for x in modellab.preflight(s["id"], snapshot=dict(SNAP))["gates"]}
        self.assertEqual(g["4-bit fine-tuning (QLoRA)"]["status"], "fail")

    def test_a_scratch_model_trains_on_your_decisions_text_without_the_floor(self):
        self.assertEqual(modellab.clean_spec("scratch", {})["corpus"], "decisions")
        with self.assertRaises(SystemExit):
            modellab.clean_spec("scratch", {"corpus": "Z:/no/such/folder"})
        rows = [{"id": "job:1", "title": "Data Engineer", "company": "Acme", "location": "", "jd": "Python",
                 "label": "pursued", "strength": 1},
                {"id": "job:2", "title": "Salary floor: $123,456", "company": "X", "location": "", "jd": "", "label": "passed",
                 "strength": 1}]
        with patched(jobmodel, decisions=lambda: rows), patched(teacher, accepted=lambda split: []):
            path = Path(modellab._scratch_corpus({}))
        body = path.read_text(encoding="utf-8")
        self.assertIn("Data Engineer at Acme", body)
        self.assertNotIn("123,456", body)

    def test_training_never_sees_the_held_out_decisions_or_a_mail_password(self):
        from lodestar import extras

        with patched(teacher, held_out=lambda: {"t:held"}):
            with db.con() as c:
                c.execute("DELETE FROM lab_examples")
                for d in ("t:held", "t:ok"):
                    c.execute("INSERT INTO lab_examples(source, decision_id, prompt, target, status, split) VALUES"
                              "('teacher', ?, 'Judge it', '{\"verdict\": \"pass\"}', 'accepted', 'train')", (d,))
            try:
                self.assertEqual([r["decision_id"] for r in teacher.accepted("train")], ["t:ok"])
            finally:
                db.con().execute("DELETE FROM lab_examples")
                db.con().commit()
        os.environ["IMAP_PASS"] = "app-password"
        try:
            self.assertNotIn("IMAP_PASS", labtrain.worker_env())
        finally:
            os.environ.pop("IMAP_PASS", None)
        self.assertFalse(extras.in_backup(Path("train-env/Lib/site-packages/torch/x.dll")))
        self.assertFalse(extras.in_backup(Path("lab/jobs/abc/ckpt/state.pt")))
        self.assertFalse(extras.in_backup(Path("media/7/image.png")))
        self.assertTrue(extras.in_backup(Path("lab/datasets/train-abc.jsonl")))  # small and yours: kept


if __name__ == "__main__":
    unittest.main()
