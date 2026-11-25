"""Model lab (pass 59, docs/superpowers/plans/2026-11-24-model-lab.md section C): the model you choose or design,
whether it fits this computer, the candidates built from it and the release Lodestar runs.

- A selection is versioned (lab_selections: one row per revision). Saving with an `expected_rev` older than the
  latest is refused, so two tabs cannot overwrite each other; every edit is a new revision; a job keeps the revision
  it was planned from (labtrain.plan pins sel_id + rev).
- Two modes (a tagged union): existing (an installed Ollama model or catalog variant, inference or a training route)
  and scratch (an architecture you design, trained from random weights by the training worker).
- preflight() answers pass / fail / unmeasured / inapplicable per gate with the remedy; a candidate is built only
  when no gate fails, and goes live (promote) only when its held-out accuracy beats the live model's.
- Releases (meta lab:release): the live tag stays `lodestar-jobs` (what ai.model_for returns); promote copies the
  candidate onto it after saving the old live weights as lodestar-jobs:prev-N, so rollback is one copy back."""
import json
import threading
from datetime import datetime, timezone

from . import db
from .config import full_ai_check

MODES = ("existing", "scratch")
ROUTES = ("inference", "adapter", "full")
KV_TYPES = {"f16": 2.0, "q8_0": 1.0, "q4_0": 0.5}
SCHEMA = """
CREATE TABLE IF NOT EXISTS lab_selections(id INTEGER NOT NULL, rev INTEGER NOT NULL, mode TEXT NOT NULL, spec TEXT NOT NULL,
  note TEXT, created_at TEXT DEFAULT (datetime('now')), PRIMARY KEY(id, rev));
"""
REL_KEY, SEL_KEY = "lab:release", "lab:selected"


def _init():
    db.con().executescript(SCHEMA)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _meta(key):
    from .jobmodel import _meta

    return _meta(key)


def _set_meta(key, value):
    from .jobmodel import _set_meta

    _set_meta(key, value)


# ----------------------------------------------------------------------------- selections
def _int(spec, key, lo, hi, default=None):
    v = spec.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise SystemExit(f"{key} must be a whole number") from None
    if not lo <= v <= hi:
        raise SystemExit(f"{key} must be between {lo} and {hi}")
    return v


def _corpus_ref(v) -> str:
    """'decisions' (your decisions' text, written at build time) or an existing file / folder of .txt files."""
    from pathlib import Path

    from .config import HOME

    v = str(v or "decisions").strip()[:400]
    if v == "decisions":
        return v
    root = (HOME / "lab" / "corpus").resolve()
    p = Path(v).resolve()
    # only files you put in HOME/lab/corpus: never your data folder (profile.md, Preferences) or anywhere else
    if not p.exists() or (p != root and root not in p.parents):
        raise SystemExit(f"corpus must be 'decisions' or a file / folder inside {root} (copy the text there first)")
    return str(p)


def clean_spec(mode: str, spec: dict) -> dict:
    """A selection spec, validated (the UI, CLI and API all pass through here)."""
    if mode not in MODES:
        raise SystemExit(f"mode is one of {', '.join(MODES)}")
    if not isinstance(spec, dict):
        raise SystemExit("spec must be an object")
    if mode == "existing":
        vid = str(spec.get("variant_id") or "").strip()
        if not vid:
            raise SystemExit("choose a model (variant_id)")
        route = str(spec.get("route") or "inference")
        if route not in ROUTES:
            raise SystemExit(f"route is one of {', '.join(ROUTES)}")
        kv = str(spec.get("kv_type") or "f16")
        if kv not in KV_TYPES:
            raise SystemExit(f"kv_type is one of {', '.join(KV_TYPES)}")
        out = {"variant_id": vid[:200], "route": route, "kv_type": kv,
               "num_ctx": _int(spec, "num_ctx", 512, 262144, 8192), "concurrency": _int(spec, "concurrency", 1, 8, 1),
               "profile": str(spec.get("profile") or "")[:60]}
        if hf := str(spec.get("hf_repo") or "").strip():  # the trainable checkpoint behind an Ollama tag (adapter/full)
            import re

            if not re.fullmatch(r"[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}", hf):  # a Hub id: never ../, a folder or URL
                raise SystemExit("hf_repo is a Hugging Face model id like Qwen/Qwen2.5-7B-Instruct")
            out["hf_repo"] = hf
            out["hf_revision"] = str(spec.get("hf_revision") or "main")[:80]
        return out
    from .labtrain import validate_scratch

    keys = {"vocab": (256, 262144, 8192), "layers": (1, 128, 8), "hidden": (32, 16384, 512), "mlp": (32, 65536, 1376),
            "heads": (1, 256, 8), "kv_heads": (1, 256, 2), "head_dim": (8, 512, 64), "context": (16, 131072, 1024),
            "seed": (0, 2**31 - 1, 42), "tokens_budget": (1000, 10**12, 50_000_000)}
    out = {k: _int(spec, k, lo, hi, d) for k, (lo, hi, d) in keys.items()}
    out |= {"arch": "llama", "tied": bool(spec.get("tied", True)),
            "tokenizer": str(spec.get("tokenizer") or "new")[:200], "corpus": _corpus_ref(spec.get("corpus")),
            "profile": str(spec.get("profile") or "")[:60]}
    if errs := validate_scratch(out):
        raise SystemExit("; ".join(errs))
    return out


def save(mode: str, spec: dict, sel_id: int | None = None, expected_rev: int | None = None, note: str = "") -> dict:
    """A new selection (sel_id None) or a new revision of one. expected_rev must be the latest revision (revision
    guard: a stale editor is refused instead of overwriting newer work)."""
    spec = clean_spec(mode, spec)
    _init()
    con = db.con()
    with con:
        if sel_id is None:
            sel_id = (con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM lab_selections").fetchone()[0])
            rev = 1
        else:
            cur = con.execute("SELECT MAX(rev) FROM lab_selections WHERE id=?", (int(sel_id),)).fetchone()[0]
            if cur is None:
                raise SystemExit(f"no selection #{sel_id}")
            if expected_rev is None or int(expected_rev) != cur:  # editing needs the revision you loaded
                raise SystemExit(f"selection #{sel_id} changed (now revision {cur}, you edited {expected_rev}): reload it")
            rev = cur + 1
        con.execute("INSERT INTO lab_selections(id, rev, mode, spec, note) VALUES(?, ?, ?, ?, ?)",
                    (int(sel_id), rev, mode, json.dumps(spec, sort_keys=True), str(note or "")[:300]))
    return get(sel_id, rev)


def get(sel_id: int, rev: int | None = None) -> dict:
    _init()
    q = "SELECT * FROM lab_selections WHERE id=?" + (" AND rev=?" if rev else "") + " ORDER BY rev DESC LIMIT 1"
    r = db.con().execute(q, (int(sel_id), int(rev)) if rev else (int(sel_id),)).fetchone()
    if not r:
        raise SystemExit(f"no selection #{sel_id}" + (f" revision {rev}" if rev else ""))
    return {"id": r["id"], "rev": r["rev"], "mode": r["mode"], "spec": json.loads(r["spec"]), "note": r["note"],
            "created_at": r["created_at"]}


def selections() -> list[dict]:
    """The latest revision of every selection, newest first."""
    _init()
    rows = db.con().execute("SELECT id, MAX(rev) rev FROM lab_selections GROUP BY id ORDER BY id DESC").fetchall()
    return [get(r["id"], r["rev"]) for r in rows]


def choose(sel_id: int) -> dict:
    """Mark a selection as the one the lab works on (it does not change the live model: promote does)."""
    s = get(sel_id)
    _set_meta(SEL_KEY, {"id": s["id"], "rev": s["rev"], "at": _utc()})
    return s


def chosen() -> dict | None:
    m = _meta(SEL_KEY)
    try:
        return get(m["id"]) if m else None
    except SystemExit:
        return None


# ----------------------------------------------------------------------------- fit and preflight
def _variant(vid: str) -> dict | None:
    from . import modelcat

    try:
        return modelcat.get(vid)
    except (Exception, SystemExit):
        return None


def assess(sel: dict, snapshot: dict | None = None) -> dict:
    """The selection's estimated memory and fit on this computer (hwprofile budget under the selection's profile)."""
    from . import hwprofile, labtrain, modelcat

    snap = snapshot or hwprofile.probe()
    prof = sel["spec"].get("profile") or None
    bud = hwprofile.budget(snap, prof)
    total = sum(g.get("total_gib") or 0 for g in snap.get("gpus") or []) or None
    if sel["mode"] == "scratch":
        mem = labtrain.train_memory(sel["spec"], "full", seq=sel["spec"]["context"],  # what the job runs
                                    microbatch=labtrain.DEFAULTS["scratch"]["microbatch"])
        est = {"lo_gib": mem["lo_gib"], "hi_gib": mem["hi_gib"], "parts": mem.get("parts"), "confidence": "estimated",
               "basis": mem.get("basis")}
        params = labtrain.scratch_params(sel["spec"])
        op = "full_train"
    else:
        v = _variant(sel["spec"]["variant_id"])
        if v is None:
            return {"status": "unknown", "reasons": [f"{sel['spec']['variant_id']} is not in the catalog (sync it)"],
                    "budget": bud, "snapshot_at": snap.get("at")}
        op = {"inference": "run", "adapter": "adapter_train", "full": "full_train"}[sel["spec"]["route"]]
        est = modelcat.estimate(v, {"operation": op, "context": sel["spec"]["num_ctx"],
                                    "concurrency": sel["spec"]["concurrency"],
                                    "kv_bytes": KV_TYPES[sel["spec"]["kv_type"]], "placement": "gpu"})
        params = None
    f = modelcat.fit(est, bud.get("effective_gib"), bud.get("total_gib") or total)
    return {"operation": op, "estimate": est, "fit": f, "status": f.get("status"), "budget": bud, "params": params,
            "manual": bool(snap.get("manual")), "snapshot_at": snap.get("at")}


def preflight(sel_id: int, rev: int | None = None, snapshot: dict | None = None) -> dict:
    """Every gate for the selection: {gate, status pass|fail|unmeasured|inapplicable, detail, remedy}."""
    from . import labtrain, teacher

    sel = get(sel_id, rev)
    gates = []

    def gate(name, status, detail, remedy=""):
        gates.append({"gate": name, "status": status, "detail": detail, "remedy": remedy})

    a = assess(sel, snapshot)
    st = a.get("status")
    gate("fits this computer", {"fits": "pass", "incompatible": "fail"}.get(st, "unmeasured"),
         "; ".join(a.get("fit", {}).get("reasons") or a.get("reasons") or []) or str(st),
         "" if st == "fits" else "lower the context or concurrency, pick a smaller quantization, or a profile with less reserve")
    training = sel["mode"] == "scratch" or sel["spec"].get("route") in ("adapter", "full")
    if sel["mode"] == "existing":
        v = _variant(sel["spec"]["variant_id"])
        installed = bool(v and v.get("installed"))
        gate("runtime", "pass" if installed else "fail",
             "installed in Ollama" if installed else "not installed in Ollama",
             "" if installed else f"`ollama pull {sel['spec']['variant_id']}`")
        ctx_max = (v or {}).get("context_max")
        if ctx_max:
            ok = sel["spec"]["num_ctx"] <= ctx_max
            gate("context", "pass" if ok else "fail", f"{sel['spec']['num_ctx']} of {ctx_max} tokens",
                 "" if ok else f"use at most {ctx_max}")
        else:
            gate("context", "unmeasured", "the model's maximum context is not known", "")
        if training:
            gate("trainable weights", "pass" if sel["spec"].get("hf_repo") else "fail",
                 sel["spec"].get("hf_repo") or "an Ollama tag is not a trainable checkpoint",
                 "" if sel["spec"].get("hf_repo") else "name the Hugging Face checkpoint (hf_repo) these weights came from")
    else:
        gate("runtime", "unmeasured", "a scratch model runs in Ollama once exported (the export job tests it)", "")
    if training:
        env = labtrain.env_status()
        pk = env.get("packages") or {}
        gate("training environment", "pass" if ok else "fail",
             "ready" + (" (CUDA)" if env.get("cuda") else " (no CUDA: CPU only)") if ok else (env.get("error") or "not set up"),
             "" if ok else "Model lab > Training > Set up the training environment")
        if sel["mode"] == "existing" and ok:  # QLoRA loads the base in 4-bit on the GPU: bitsandbytes + CUDA or it fails
            q = bool(pk.get("bitsandbytes") and env.get("cuda"))
            gate("4-bit fine-tuning (QLoRA)", "pass" if q else "fail",
                 "bitsandbytes and CUDA present" if q else ("no CUDA GPU in the training environment" if not env.get("cuda")
                                                           else "bitsandbytes is not installed (no wheel for this Python?)"),
                 "" if q else "Set up the training environment again, or choose an inference-only route")
        n = teacher.stats()["by_split"].get("train", 0)
        need = 20 if sel["mode"] == "existing" else 1
        gate("training data", "pass" if n >= need else "fail", f"{n} accepted training examples",
             "" if n >= need else f"accept at least {need} under Learning (Teach from my decisions)")
    else:
        gate("training environment", "inapplicable", "inference only", "")
    return {"selection": sel, "assessment": a, "gates": gates,
            "ready": not any(g["status"] == "fail" for g in gates)}


# ----------------------------------------------------------------------------- candidates and releases
_REL_LOCK = threading.RLock()  # every read-modify-write of lab:release (each tab action is its own thread)


def releases() -> dict:
    return _meta(REL_KEY) or {"active": None, "previous": [], "candidates": []}


def _save_rel(r: dict) -> None:
    r["candidates"] = r.get("candidates", [])[-20:]
    r["previous"] = r.get("previous", [])[-5:]
    _set_meta(REL_KEY, r)


def _update_cand(tag: str, **fields) -> dict:
    """Set fields on one candidate in a freshly read record (after slow work done outside the lock)."""
    with _REL_LOCK:
        r = releases()
        c = _cand(tag, r)
        c.update(fields)
        _save_rel(r)
        return c


def _scratch_corpus(spec: dict) -> str:
    """The text a scratch model pretrains on when its corpus is 'decisions': your decisions and accepted examples
    (job titles, companies, descriptions, the teacher's reasons), each line through drafts.leaks, written once per
    content hash under HOME/lab/corpus/. Any other corpus must be an existing file or folder."""
    import hashlib

    from .config import HOME
    from .drafts import leaks
    from .jobmodel import decisions
    from .teacher import accepted

    from .teacher import held_out

    held = held_out()  # the evaluation set never enters pretraining either
    lines = [f"{d['title']} at {d['company']} ({d['location'] or 'place not stated'}). {' '.join(str(d['jd']).split())}"
             for d in decisions() if d["id"] not in held]
    lines += [f"{e['prompt']}\n{json.dumps(e['target'], sort_keys=True)}" for e in accepted(None)]
    lines = [x for x in lines if x.strip() and not leaks(x)]
    if not lines:
        raise SystemExit("nothing to pretrain on yet: apply to or pass on some jobs (or name a corpus folder)")
    body = "\n\n".join(lines) + "\n"
    out = HOME / "lab" / "corpus" / f"decisions-{hashlib.sha256(body.encode()).hexdigest()[:12]}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text(body, encoding="utf-8")
    return str(out)


def build_candidate(sel_id: int) -> dict:
    """Build a candidate from the selection when no preflight gate fails. Inference: an Ollama model under
    lodestar-jobs:cand-N from the chosen base and context (with your accepted examples). Training routes: plans
    and starts the training job (labtrain); its export step creates the candidate tag. The candidate number is
    reserved under the lock first, so two builds never share a tag."""
    from . import jobmodel, labtrain

    full_ai_check("builds a model candidate")
    pf = preflight(sel_id)
    if not pf["ready"]:
        bad = [f"{g['gate']}: {g['detail']}" for g in pf["gates"] if g["status"] == "fail"]
        raise SystemExit("not ready: " + "; ".join(bad))
    sel = pf["selection"]
    inference = sel["mode"] == "existing" and sel["spec"]["route"] == "inference"
    kind = "inference" if inference else "scratch" if sel["mode"] == "scratch" else "lora"
    with _REL_LOCK:
        r = releases()
        r["next_cand"] = n = max(int(r.get("next_cand") or 0), max([c.get("n", 0) for c in r.get("candidates", [])] or [0])) + 1
        tag = f"{jobmodel.NAME}:cand-{n}"
        r.setdefault("candidates", []).append({"n": n, "tag": tag, "sel_id": sel["id"], "rev": sel["rev"], "kind": kind,
                                               "status": "building", "built_at": None})
        _save_rel(r)
    try:
        if inference:
            rec = jobmodel.build(force=True, tag=tag, base_model=sel["spec"]["variant_id"], num_ctx=sel["spec"]["num_ctx"])
            return _update_cand(tag, status="built", built_at=rec["built_at"], base=rec["base"])
        ds = None
        if sel["mode"] == "existing":
            from .teacher import dataset

            ds = dataset("train")
            spec = sel["spec"] | {"base": sel["spec"]["hf_repo"], "revision": sel["spec"].get("hf_revision")}
        else:  # the worker reads the corpus as a file or folder; 'decisions' becomes your decisions' text
            spec = sel["spec"] | {"corpus": _scratch_corpus(sel["spec"]) if sel["spec"].get("corpus", "decisions") == "decisions"
                                  else sel["spec"]["corpus"]}
        job = labtrain.plan(kind, sel["id"], sel["rev"], spec, dataset_path=ds and ds["path"], dataset_sha=ds and ds["sha"],
                            hyper={"seq": sel["spec"]["context"]} if kind == "scratch" else None)
        labtrain.start(job["id"])
        return _update_cand(tag, status="training", job_id=job["id"])
    except (Exception, SystemExit) as e:
        _update_cand(tag, status="failed", error=str(e)[:300])
        raise


def _cand(tag: str, r: dict) -> dict:
    for c in r.get("candidates", []):  # the record the caller saves, not a fresh copy
        if c["tag"] == tag:
            return c
    raise SystemExit(f"no candidate {tag}")


def evaluate(tag: str) -> dict:
    """The candidate and the live model on the same held-out decisions (jobmodel.accuracy); stored on the candidate.
    The scoring (minutes of Ollama calls) runs outside the lock; the result goes into a freshly read record."""
    from . import jobmodel

    full_ai_check("evaluates a model candidate")
    _cand(tag, releases())
    out = {"at": _utc(), "candidate": jobmodel.accuracy(tag)}
    if releases().get("active") or jobmodel.built():  # the live model, judged on the same held-out decisions
        try:
            out["live"] = jobmodel.accuracy(jobmodel.NAME)
        except SystemExit as e:
            out["live_error"] = str(e)
    _update_cand(tag, eval=out)
    return out


def promote(tag: str, force: bool = False) -> dict:
    """Make a candidate the live model: only when it was evaluated after the current live model went live, and beats
    its held-out accuracy (both the one measured then and the live release's own); force (your click after seeing the
    numbers) allows a tie. The old live weights are kept as lodestar-jobs:prev-N (N never reused) for rollback."""
    from . import jobmodel

    full_ai_check("changes the live model")
    with _REL_LOCK:
        r = releases()
        c = _cand(tag, r)
        ev = c.get("eval")
        if not ev or ev["candidate"].get("accuracy") is None:
            raise SystemExit("evaluate the candidate first: it goes live only when it beats the current model")
        act = r.get("active") or {}
        if act and ev["at"] < act.get("at", ""):
            raise SystemExit(f"{act['tag']} went live after this evaluation: evaluate the candidate again")
        if ev.get("live_error") and (act or jobmodel.built()):
            raise SystemExit(f"the live model could not be scored ({ev['live_error']}): evaluate again")
        cand = ev["candidate"]["accuracy"]
        lives = [x for x in ((ev.get("live") or {}).get("accuracy"), act.get("accuracy")) if x is not None]
        live = max(lives) if lives else None
        if live is not None and (cand < live or (cand == live and not force)):
            raise SystemExit(f"the candidate scored {cand} against the live model's {live}: it stays a candidate")
        prev = None
        if jobmodel.built() or act:
            r["prev_n"] = int(r.get("prev_n") or len(r.get("previous", []))) + 1
            prev = f"{jobmodel.NAME}:prev-{r['prev_n']}"
            jobmodel.copy(jobmodel.NAME, prev)
        jobmodel.copy(tag, jobmodel.NAME)
        if prev:
            r.setdefault("previous", []).append({"tag": prev, "was": r.get("active"), "at": _utc()})
        for o in r.get("candidates", []):
            if o.get("status") == "live":
                o["status"] = "replaced"
        r["active"] = {"tag": tag, "sel_id": c["sel_id"], "rev": c["rev"], "at": _utc(), "accuracy": cand}
        c["status"] = "live"
        _save_rel(r)
        built = jobmodel.built() or {}
        jobmodel._set_meta(jobmodel.KEY, built | {"built_at": _utc(), "base": c.get("base") or built.get("base"),
                                                  "tag": jobmodel.NAME, "fp": f"lab:{tag}", "promoted_from": tag})
        return r


def rollback() -> dict:
    """Put the previous live weights back on lodestar-jobs (the most recent prev-N)."""
    from . import jobmodel

    full_ai_check("changes the live model")
    with _REL_LOCK:
        r = releases()
        if not r.get("previous"):
            raise SystemExit("there is no earlier live model to go back to")
        p = r["previous"].pop()
        jobmodel.copy(p["tag"], jobmodel.NAME)
        for c in r.get("candidates", []):
            if r.get("active") and c["tag"] == r["active"]["tag"]:
                c["status"] = "rolled back"
            if p.get("was") and c["tag"] == p["was"].get("tag"):
                c["status"] = "live"
        r["active"] = p.get("was")
        _save_rel(r)
        return r


def help_me_choose(snapshot: dict | None = None, limit: int = 8) -> dict:
    """Installed and catalog text models ranked for this computer: fitting ones first, then by measured accuracy where
    a candidate built on them was evaluated, then by size. Never picks for you."""
    from . import hwprofile, modelcat

    snap = snapshot or hwprofile.probe()
    res = modelcat.search("", {"task": "text"}, None, snapshot=snap)
    measured = {}
    for c in releases().get("candidates", []):
        acc = ((c.get("eval") or {}).get("candidate") or {}).get("accuracy")
        if acc is not None and c.get("base"):
            measured[c["base"]] = max(acc, measured.get(c["base"], 0))
    order = {"fits": 0, "borderline": 1, "unknown": 2, "incompatible": 3}
    items = sorted(res["items"], key=lambda v: (order.get((v.get("fit") or {}).get("status"), 2),
                                                -(measured.get(v["id"]) or 0), -(v.get("params_b") or 0)))
    out = []
    for v in items[:limit]:
        st = (v.get("fit") or {}).get("status")
        why = [f"{st}" + (f" ({v['fit'].get('pct_lo')}-{v['fit'].get('pct_hi')}% of your GPU)" if v.get("fit", {}).get("pct_lo") is not None else "")]
        if v["id"] in measured:
            why.append(f"held-out accuracy {measured[v['id']]} as a candidate")
        else:
            why.append("not measured here yet: build a candidate and evaluate it")
        out.append({"variant": v, "why": why})
    return {"items": out, "snapshot_at": snap.get("at")}


def status() -> dict:
    """The Model lab tab's summary (no network)."""
    from . import teacher

    return {"chosen": chosen(), "selections": selections()[:20], "releases": releases(), "teacher": teacher.stats()}


# ----------------------------------------------------------------------------- the tab's one action (web: run('lab'))
HW_KEY, MEDIA_KEY = "lab:hw", "lab:media"  # the last hardware snapshot (probe on your click; the tab shows its age)


def _snapshot() -> dict | None:
    return _meta(HW_KEY)


def _hw_part(snap: dict | None) -> dict:
    from . import hwprofile

    prof = hwprofile.active_profile()
    return {"hw": snap, "profiles": hwprofile.profiles(), "profile": prof,
            "budget": hwprofile.budget(snap, prof) if snap else {}}


def _catalog(q: str = "", view: str = "all", snap: dict | None = None) -> dict:
    from . import modelcat

    snap = snap if snap is not None else _snapshot()
    # never probe behind your back: before "Check this computer" every fit is unknown (the cards say so)
    snap = snap or {"at": None, "gpus": None, "ram": None, "disk": None, "ollama": None, "source": "none",
                    "error": "not checked yet"}
    res = modelcat.search(q, {"view": view}, None, snapshot=snap)
    out = {"catalog": res}
    if q or view != "all":
        out["catalog_all"] = modelcat.search("", {"view": "all"}, None, snapshot=snap)["items"]
    return out


def _jobs() -> list[dict]:
    from . import labtrain

    try:
        return labtrain.jobs()[:20]
    except Exception:
        return []


def do(op: str, p: dict) -> dict:
    """Model lab operations for the tab (one background task each). Network only where the op says: probe (this
    computer and loopback Ollama), hf_sync (public Hugging Face metadata), teach (your premium AI), media_probe
    (loopback), env_setup (package downloads), build/evaluate/promote (local Ollama)."""
    from . import broker, hwprofile, labtrain, media, modelcat, teacher

    snap = _snapshot()
    match op:
        case "state":
            out = _hw_part(snap) | _catalog(snap=snap) | status() | {"examples": teacher.examples(limit=60),
                                                                      "env": labtrain.env_status(cached=True),
                                                                      "jobs": _jobs(), "evidence": _evidence(),
                                                                      "media": _meta(MEDIA_KEY)}
            return out
        case "probe":
            snap = hwprofile.probe()
            _set_meta(HW_KEY, snap)
            return _hw_part(snap) | _catalog(snap=snap)
        case "profile_set":
            hwprofile.set_profile(str(p.get("name") or ""), p.get("reserve_gib"))
            return _hw_part(snap) | _catalog(snap=snap)
        case "profile_use":
            hwprofile.use_profile(str(p.get("name") or ""))
            return _hw_part(snap) | _catalog(snap=snap)
        case "search":
            return _catalog(str(p.get("q") or ""), str(p.get("view") or "all"), snap)
        case "hf_sync":
            r = modelcat.sync_hf(str(p.get("q") or ""))
            return _catalog(str(p.get("q") or ""), "all", snap) | {"note": f"Hugging Face: {r.get('added', 0)} models listed"}
        case "estimate":
            mode = str(p.get("mode") or "existing")
            sel = {"id": 0, "rev": 0, "mode": mode, "spec": clean_spec(mode, p.get("spec") or {})}
            a = assess(sel, snap or hwprofile.probe())
            if mode == "scratch":
                tp = labtrain.token_plan(sel["spec"]["tokens_budget"], sel["spec"]["context"], 2, 8, 1)
                a["plan"] = (f"{tp['per_update']:,} tokens per update, about {tp['updates']:,} updates; time needs a "
                             "measured throughput (the probe job measures it)")
            return {"assessment": a}
        case "save":
            s = save(str(p.get("mode") or "existing"), p.get("spec") or {}, p.get("sel_id"), p.get("expected_rev"),
                     str(p.get("note") or ""))
            choose(s["id"])
            return status() | {"editing": None, "preflight": preflight(s["id"], snapshot=snap),
                               "note": f"saved selection #{s['id']} revision {s['rev']}"}
        case "choose":
            choose(int(p["sel_id"]))
            return status()
        case "preflight":
            return {"preflight": preflight(int(p["sel_id"]), snapshot=snap)}
        case "build":
            c = build_candidate(int(p["sel_id"]))
            return status() | {"jobs": _jobs(), "note": f"candidate {c['tag']}: {c['status']}"}
        case "help":
            return {"help": help_me_choose(snap or hwprofile.probe())}
        case "teach":
            r = teacher.propose(int(p.get("n") or 8))
            return {"teacher": teacher.stats(), "examples": teacher.examples(limit=60),
                    "note": f"{r['proposed']} examples to review" + (f" ({r['flagged']} disagree with you)" if r.get("flagged") else "")}
        case "review":
            teacher.review(int(p["id"]), str(p.get("status") or ""), p.get("target"))
            return {"teacher": teacher.stats(), "examples": teacher.examples(limit=60)}
        case "dataset":
            d = teacher.dataset("train")
            return {"teacher": teacher.stats(), "note": f"training set: {d['rows']} rows ({d['dropped']} dropped), sha {d['sha'][:12]}"}
        case "evaluate":
            evaluate(str(p["tag"]))
            return {"releases": releases()}
        case "promote":
            promote(str(p["tag"]), bool(p.get("force")))
            return {"releases": releases(), "note": f"{p['tag']} is live"}
        case "rollback":
            rollback()
            return {"releases": releases(), "note": "the previous model is live again"}
        case "env":
            return {"env": labtrain.env_status()}
        case "env_setup":
            r = labtrain.setup_env()
            return {"env": labtrain.env_status(), "note": r.get("summary") if isinstance(r, dict) else "set up"}
        case "job_poll":
            labtrain.poll(int(p["id"]))
            _sync_jobs()
            return {"jobs": _jobs(), "releases": releases()}
        case "job_pause":
            labtrain.pause(int(p["id"]))
            return {"jobs": _jobs()}
        case "job_cancel":
            labtrain.cancel(int(p["id"]))
            return {"jobs": _jobs()}
        case "ev_publish":
            r = broker.publish("owner")
            return {"evidence": _evidence(), "note": f"published {r.get('upserted', 0)} new or changed records, {r.get('retracted', 0)} retracted"}
        case "ev_retract":
            broker.retract("me", str(p["evidence_id"]))
            return {"evidence": _evidence()}
        case "media_probe":
            m = _media(media.probe())
            _set_meta(MEDIA_KEY, m)
            return {"media": m}
        case "media_submit":
            return {"media_job": media.submit(str(p["runtime"]), p.get("recipe") or {}), "media": _meta(MEDIA_KEY)}
        case "scratch_calc":
            spec = clean_spec("scratch", p.get("spec") or {})
            return {"params": labtrain.scratch_params(spec), "memory": labtrain.train_memory(spec, "full")}
    raise SystemExit(f"unknown Model lab action: {op[:40]}")


def _evidence() -> dict:
    """Evidence heads for the tab, with what each record's policy allows it to be used for."""
    from . import broker

    out, pol = [], {}
    for r in broker.records("me")[:200]:
        if r["policy_id"] not in pol:
            pol[r["policy_id"]] = broker.policy(r["policy_id"]) or {}
        flags = pol[r["policy_id"]].get("flags") or {}
        out.append(r | {"uses": [k for k, v in flags.items() if v]})
    return {"records": out}


def _media(probed: dict) -> dict:
    """media.probe() joined with the registry's labels and operations, stamped with the time it was checked."""
    from . import media

    reg = media.registry()
    return {"at": _utc(), "runtimes": [{"name": reg.get(k, {}).get("label") or k, "key": k,
                                        "operations": reg.get(k, {}).get("operations") or [], **(v or {})}
                                       for k, v in (probed or {}).items()]}


def _llama_cpp() -> dict:
    """llama.cpp's converter and quantizer for the export step, from LLAMA_CPP_DIR (.env or the environment); without
    it the export stops at a merged Hugging Face model and says so."""
    from pathlib import Path

    from .config import setting

    d = str(setting("LLAMA_CPP_DIR") or "").strip()
    if not d:
        return {}
    root = Path(d)
    q = next((x for x in (root / "llama-quantize.exe", root / "build" / "bin" / "llama-quantize.exe",
                          root / "llama-quantize") if x.is_file()), None)
    out = {"converter": str(root / "convert_hf_to_gguf.py")} if (root / "convert_hf_to_gguf.py").is_file() else {}
    return out | ({"quantize": str(q)} if q else {})


def _sync_jobs() -> None:
    with _REL_LOCK:  # one writer of lab:release at a time
        _sync_jobs_locked()


def _sync_jobs_locked() -> None:
    """A training job that finished its export step makes its candidate 'exported' (ready to evaluate)."""
    from . import labtrain

    r = releases()
    changed = False
    for c in r.get("candidates", []):
        if c.get("status") not in ("training", "exporting"):
            continue
        jid = c.get("export_job_id") if c["status"] == "exporting" else c.get("job_id")
        try:
            j = labtrain.get(jid)
        except (Exception, SystemExit):
            continue
        if j.get("status") in ("failed", "cancelled", "canceled"):
            c["status"], changed = f"{c['status']} {j['status']}", True
        elif j.get("status") == "done" and c["status"] == "training":
            # training finished: export it (merge the adapter, convert to GGUF, `ollama create <tag>`)
            out = labtrain.job_dir(j)
            spec = ({"model": str(out / "model")} if c["kind"] == "scratch" else
                    {"base": j["plan"]["spec"].get("base"), "revision": j["plan"]["spec"].get("revision"),
                     "adapter": str(out / "adapter")})
            sel = get(c["sel_id"], c["rev"])
            ex = labtrain.plan("export", c["sel_id"], c["rev"], spec,
                               hyper={"tag": c["tag"], "num_ctx": sel["spec"].get("num_ctx") or sel["spec"].get("context") or 4096,
                                      "temperature": 0.2} | _llama_cpp())
            labtrain.start(ex["id"])
            c["status"], c["export_job_id"], changed = "exporting", ex["id"], True
        elif j.get("status") == "done":
            msg = (j.get("progress") or {}).get("msg") or ""
            c["status"] = "built" if "ollama model" in msg else "trained (no GGUF: set LLAMA_CPP_DIR to a llama.cpp folder)"
            c["built_at"], changed = _utc(), True
    if changed:
        _save_rel(r)
