"""Model catalog for the Model lab (pass 59, part B): variants from Ollama (installed), the curated list
(`data/model_catalog.json`), Hugging Face metadata (on your click only) and lab-built candidates (passed in by the
caller); a VRAM estimate per variant and workload, a fit against the hardware budget, search, and an
appropriateness score.

Every figure says where it came from (`provenance`: publisher | local | estimated | unknown). An estimate is a
range labelled as one; a variant whose architecture is unknown gets no range at all ("unknown"), never a made-up one.
search() and the Ollama readers never raise; SystemExit is only for your own input errors (bounds, weights, an unknown
model id)."""
from __future__ import annotations

import copy
import difflib
import json
import re
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import db, hwprofile
from .hwprofile import _get  # a module attribute here: tests patch modelcat._get
from .jobmodel import _post as _ollama_post

GIB = 2 ** 30
CATALOG = Path(__file__).parent / "data" / "model_catalog.json"
OPERATIONS = ("run", "adapter_train", "full_train", "export")
# Bytes per parameter by quantisation (GGUF block formats include their scales: Q4_K_M is about 4.85 bits / weight).
BYTES_PER_PARAM = {"F32": 4.0, "F16": 2.0, "BF16": 2.0, "FP16": 2.0, "FP8": 1.0, "Q8_0": 1.0625, "Q6_K": 0.82,
                   "Q5_K_M": 0.71, "Q5_K_S": 0.69, "Q5_0": 0.69, "Q4_K_M": 0.606, "Q4_K_S": 0.57, "Q4_0": 0.5625,
                   "Q3_K_M": 0.49, "Q3_K_S": 0.43, "Q2_K": 0.41}
SYNONYMS = [  # phrase in the query -> filter; longest phrases are tried first
    (("describes images", "describe images", "image to text", "image-to-text", "reads images", "read images",
      "sees images", "vision", "ocr"), {"input": "image"}),
    (("generates images", "generate images", "text to image", "text-to-image", "image generation", "make images",
      "makes images"), {"output": "image"}),
    (("text to speech", "text-to-speech", "tts", "speech", "voice"), {"task": "speech", "output": "audio"}),
    (("music", "songs", "song"), {"task": "music"}),
    (("image to 3d", "image-to-3d", "3d", "mesh"), {"output": "mesh"}),
    (("embeddings", "embedding", "embed"), {"task": "embedding"}),
]
FILTERS = ("task", "input", "output", "quant", "source")
KEEP_CURATED = ("name", "family", "task", "inputs", "outputs", "tags", "specialization", "notes", "aliases")
FIT_ORDER = {"fits": 0, "borderline": 1, "unknown": 2, "incompatible": 3}
HF_TASKS = {"text-generation": ("text", ["text"], ["text"]), "image-text-to-text": ("vision", ["text", "image"], ["text"]),
            "text-to-image": ("image", ["text"], ["image"]), "text-to-speech": ("speech", ["text"], ["audio"]),
            "text-to-audio": ("music", ["text"], ["audio"]), "feature-extraction": ("embedding", ["text"], ["embedding"]),
            "sentence-similarity": ("embedding", ["text"], ["embedding"]), "image-to-3d": ("3d", ["image"], ["mesh"])}


def _post(path: str, body: dict) -> dict:
    return _ollama_post(path, body, timeout=10)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def variant(**kw) -> dict:
    """A variant record with every field present (unknown = None / empty)."""
    v: dict = {"id": "", "family": None, "name": "", "aliases": [], "source": "curated", "publisher": None, "revision": None,
         "digest": None, "runtime": None, "task": "text", "inputs": ["text"], "outputs": ["text"], "specialization": "",
         "tags": [], "params_b": None, "quant": None, "size_gib": None, "context_max": None, "arch": {},
         "license": None, "installed": False, "notes": "", "provenance": {}, "verified": None}
    v.update(kw)
    v["name"] = v["name"] or v["id"]
    return v


# ----------------------------------------------------------------------------- sources
@lru_cache(maxsize=1)
def _curated_raw() -> tuple:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return data.get("verified"), tuple(json.dumps(e) for e in data["variants"])


def curated() -> list[dict]:
    return [variant(**json.loads(e), source="curated") for e in _curated_raw()[1]]


def _params(s) -> float | None:
    m = re.fullmatch(r"\s*([\d.]+)\s*([MBK])\s*", str(s or ""), re.I)
    if not m:
        return None
    return round(float(m.group(1)) * {"K": 1e-6, "M": 1e-3, "B": 1.0}[m.group(2).upper()], 4)


def arch_from_show(show: dict) -> tuple[dict, int | None]:
    """({layers, kv_heads, head_dim, hidden}, context_max) from /api/show model_info, whose keys carry the
    architecture as prefix ("qwen3moe.block_count"). head_dim = key_length, else embedding_length / head_count."""
    info = (show or {}).get("model_info") or {}
    a = info.get("general.architecture")

    def g(k):
        val = info.get(f"{a}.{k}") if a else None
        return max(val) if isinstance(val, list) and val else val  # per-layer lists (some archs): the largest

    layers, kvh, heads, hidden = g("block_count"), g("attention.head_count_kv"), g("attention.head_count"), g("embedding_length")
    head_dim = g("attention.key_length") or (hidden // heads if hidden and heads else None)
    kvh = kvh or heads  # no GQA key: every head has its own KV
    arch = {k: int(val) for k, val in {"layers": layers, "kv_heads": kvh, "head_dim": head_dim, "hidden": hidden}.items()
            if isinstance(val, (int, float)) and val > 0}
    ctx = g("context_length")
    return arch, int(ctx) if isinstance(ctx, (int, float)) and ctx > 0 else None


_SHOW: dict = {}  # digest -> /api/show answer (a model's digest pins its contents)


def ollama_variants() -> tuple[list[dict], str | None]:
    """Installed Ollama models as variants; ([], reason) when Ollama is not reachable. Never raises."""
    try:
        tags = _get("/api/tags").get("models") or []
    except (Exception, SystemExit) as e:
        return [], f"Ollama not reachable ({type(e).__name__})"
    out = []
    for m in tags:
        name = m.get("name") or m.get("model") or ""
        d, digest = m.get("details") or {}, m.get("digest")
        show = _SHOW.get(digest) if digest else None
        if show is None:
            try:
                show = _post("/api/show", {"model": name})
                if digest:
                    _SHOW[digest] = show
            except (Exception, SystemExit):
                show = {}
        arch, ctx = arch_from_show(show)
        sd = show.get("details") or d
        fam = d.get("family") or sd.get("family")
        prov = {"size_gib": "local", "quant": "local", "params_b": "local", "context_max": "local" if ctx else "unknown",
                "arch": "local" if len(arch) == 4 else "unknown"}
        out.append(variant(id=name, family=fam, name=name, source="ollama", runtime="ollama", digest=digest,
                           installed=True, params_b=_params(sd.get("parameter_size") or d.get("parameter_size")),
                           quant=sd.get("quantization_level") or d.get("quantization_level"),
                           size_gib=round((m.get("size") or 0) / GIB, 2) or None, context_max=ctx, arch=arch,
                           task="embedding" if "embed" in name.lower() or "bert" in str(fam).lower() else "text",
                           outputs=["embedding"] if "embed" in name.lower() else ["text"], provenance=prov))
    return out, None


def _db():
    c = db.con()
    c.execute("CREATE TABLE IF NOT EXISTS catalog_hf(id TEXT PRIMARY KEY, data TEXT NOT NULL, fetched_at TEXT NOT NULL)")
    return c


def hf_search(q: str, limit: int = 20) -> dict:
    """On your click: Hugging Face's public model metadata (no weights) for q, stored in catalog_hf. A network
    failure comes back as {items: [], error}; an empty query is your error (SystemExit)."""
    from . import util

    q = str(q or "").strip()
    if not q or len(q) > 100:
        raise SystemExit("Type what to look for on Hugging Face (up to 100 characters)")
    url = "https://huggingface.co/api/models?" + urllib.parse.urlencode({"search": q, "limit": max(1, min(int(limit), 50))})
    try:
        rows = json.loads(util.fetch(url, timeout=20))
    except Exception as e:
        return {"items": [], "added": 0, "error": f"Hugging Face: {type(e).__name__}"}
    items, c = [], _db()
    for r in rows if isinstance(rows, list) else []:
        rid = str(r.get("id") or r.get("modelId") or "")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", rid):
            continue
        task, ins, outs = HF_TASKS.get(r.get("pipeline_tag"), (r.get("pipeline_tag") or "unknown", [], []))
        v = variant(id=f"hf:{rid}", name=rid, family=rid.split("/")[1], publisher=rid.split("/")[0], source="hf",
                    task=task, inputs=ins, outputs=outs, tags=[t for t in r.get("tags") or [] if isinstance(t, str)][:12],
                    provenance={"task": "publisher", "arch": "unknown", "size_gib": "unknown"})
        c.execute("INSERT INTO catalog_hf(id, data, fetched_at) VALUES(?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                  "data=excluded.data, fetched_at=excluded.fetched_at", (v["id"], json.dumps(v), _utc()))
        items.append(v)
    c.commit()
    return {"items": items, "added": len(items), "error": None}


sync_hf = hf_search  # the name modellab calls


def hf_variants() -> list[dict]:
    try:
        return [variant(**json.loads(r["data"])) for r in _db().execute("SELECT data FROM catalog_hf ORDER BY id")]
    except (Exception, SystemExit):
        return []


def all_variants(extra: list | None = None) -> tuple[list[dict], dict]:
    """(variants, sources). An installed Ollama model that the curated list knows (id or alias, ':latest' dropped)
    is one entry: installed facts win, the curated description stays. `extra` = lab-built (private) candidates."""
    verified, cur = _curated_raw()[0], curated()
    inst, err = ollama_variants()
    by_key: dict = {}
    for v in cur:
        for k in [v["id"], *v["aliases"]]:
            by_key.setdefault(k.lower(), v)
    out, merged = [], set()
    for v in inst:
        key = v["id"].lower()
        c = by_key.get(key) or by_key.get(key.removesuffix(":latest"))
        if c is not None and c["id"] not in merged:
            merged.add(c["id"])
            known = {k: val for k, val in v.items() if val not in (None, {}, [], "") and k not in KEEP_CURATED}
            if len(v["arch"]) < 4:  # Ollama did not say: keep the publisher's figures
                known.pop("arch", None)
            out.append(c | known | {"provenance": c["provenance"] | {k: p for k, p in v["provenance"].items()
                                                                       if p != "unknown"}, "id": v["id"],
                                    "aliases": sorted({*c["aliases"], c["id"]} - {v["id"]})})
        else:
            out.append(v)
    out += [v for v in cur if v["id"] not in merged]
    hf = hf_variants()
    out += hf
    priv = [variant(**{**v, "source": "private"}) for v in extra or [] if isinstance(v, dict) and v.get("id")]
    out += priv
    sources = {"ollama": {"ok": err is None, "count": len(inst), "error": err},
               "curated": {"ok": True, "count": len(cur), "verified": verified},
               "hf": {"ok": True, "count": len(hf)}, "private": {"ok": True, "count": len(priv)}}
    return out, sources


def get(vid: str, items: list | None = None) -> dict:
    """The variant with this id (or alias); SystemExit when there is none."""
    key = str(vid or "").strip().lower()
    for v in items if items is not None else all_variants()[0]:
        if key and key in {v["id"].lower(), *(a.lower() for a in v.get("aliases") or [])}:
            return v
    raise SystemExit(f"Unknown model {vid!r}: pick one from the catalog")


# ----------------------------------------------------------------------------- estimate and fit
def _weights_gib(v: dict) -> tuple[float | None, str]:
    if v.get("size_gib"):
        return float(v["size_gib"]), "weights = file size"
    bpp = BYTES_PER_PARAM.get(str(v.get("quant") or "").upper())
    if v.get("params_b") and bpp:
        return v["params_b"] * 1e9 * bpp / GIB, f"weights = {v['params_b']}B params x {bpp} B ({v['quant']})"
    return None, "weights unknown (no size, or no parameter count / quantisation)"


def _unknown(basis: list) -> dict:
    return {"lo_gib": None, "hi_gib": None, "parts": {"weights": None, "kv": None, "workspace": None},
            "confidence": "unknown", "basis": basis}


def estimate(v: dict, workload: dict | None = None) -> dict:
    """{lo_gib, hi_gib, parts:{weights, kv, workspace}, confidence, basis}. workload: {operation run|adapter_train|
    full_train|export, context, concurrency, kv_bytes (2 f16 | 1 q8 | 0.5 q4), placement gpu|mixed|cpu, mode
    (a publisher figure's label)}. KV = 2 x layers x kv_heads x head_dim x kv_bytes x context x concurrency."""
    w: dict = {"operation": "run", "context": None, "concurrency": 1, "kv_bytes": 2, "placement": "gpu", "mode": None}
    w |= {k: val for k, val in (workload or {}).items() if val is not None}
    if w["operation"] not in OPERATIONS:
        raise SystemExit(f"Operation must be one of {', '.join(OPERATIONS)}")
    try:
        conc, kvb = int(w["concurrency"]), float(w["kv_bytes"])
        ctx = int(w["context"]) if w["context"] else None
    except (TypeError, ValueError):
        raise SystemExit("Context, concurrency and KV bytes must be numbers") from None
    if conc < 1 or kvb not in (2.0, 1.0, 0.5) or (ctx is not None and ctx < 1):
        raise SystemExit("Concurrency must be 1 or more, KV bytes 2 (f16), 1 (q8) or 0.5 (q4), context positive")
    placement = f"placement {w['placement']}"
    pub, rng = v.get("vram_published"), v.get("vram_estimate_gib")
    if pub and w["operation"] == "run":
        figs = [pub[w["mode"]]] if w["mode"] in pub else list(pub.values())
        # Publisher 'GB': the range covers both readings (decimal GB and GiB).
        return {"lo_gib": round(min(figs) * 1e9 / GIB, 2), "hi_gib": float(max(figs)),
                "parts": {"weights": None, "kv": None, "workspace": None}, "confidence": "publisher-reported",
                "basis": [f"publisher figure {', '.join(f'{k} {val} GB' for k, val in pub.items())}", placement]}
    if rng and w["operation"] == "run":
        return {"lo_gib": float(rng[0]), "hi_gib": float(rng[1]), "parts": {"weights": None, "kv": None, "workspace": None},
                "confidence": "low", "basis": ["catalog estimate (not a publisher figure)", placement]}
    arch = v.get("arch") or {}
    missing = [k for k in ("layers", "kv_heads", "head_dim") if not arch.get(k)]
    weights, wbasis = _weights_gib(v)
    if w["operation"] == "run":
        if missing or weights is None:
            return _unknown([f"architecture unknown ({', '.join(missing)})" if missing else wbasis])
        ctx = ctx or min(v.get("context_max") or 4096, 8192)
        kv = 2 * arch["layers"] * arch["kv_heads"] * arch["head_dim"] * kvb * ctx * conc / GIB
        base = weights + kv
        return {"lo_gib": round((base + 0.5) * 1.05, 2), "hi_gib": round((base + 1.5) * 1.15, 2),
                "parts": {"weights": round(weights, 2), "kv": round(kv, 3), "workspace": [0.5, 1.5]},
                "confidence": "medium" if v.get("size_gib") else "low",
                "basis": [wbasis, f"KV 2 x {arch['layers']} x {arch['kv_heads']} x {arch['head_dim']} x {kvb:g} B x "
                          f"{ctx} x {conc}", "workspace 0.5-1.5 GiB + 5-15% margin", placement]}
    params = v.get("params_b")
    if not params:
        return _unknown(["parameter count unknown"])
    if w["operation"] == "export":  # merging an adapter works on f16 weights
        f16 = params * 1e9 * 2 / GIB
        return {"lo_gib": round(f16, 2), "hi_gib": round(f16 * 1.2, 2), "parts": {"weights": round(f16, 2), "kv": 0,
                "workspace": None}, "confidence": "low", "basis": ["f16 weights for the merge (mostly RAM)", placement]}
    hidden = arch.get("hidden")
    if missing or not hidden:
        return _unknown([f"architecture unknown ({', '.join(missing + ([] if hidden else ['hidden']))})"])
    ctx = ctx or min(v.get("context_max") or 2048, 2048)
    act = [2 * arch["layers"] * hidden * ctx * conc * k / GIB for k in (4, 16)]  # checkpointing on .. off
    if w["operation"] == "adapter_train":
        if weights is None:
            return _unknown([wbasis])
        lora = [params * 1e9 * share * 16 / GIB for share in (0.005, 0.01)]  # adapter weights + grads + AdamW
        lo, hi = weights + lora[0] + act[0], weights + lora[1] + act[1]
        basis = [wbasis, "LoRA 0.5-1% of params x 16 B", "activations 2 B x layers x hidden x tokens x 4-16"]
    else:
        full = params * 1e9 * 16 / GIB  # fp32 master + grads + AdamW moments
        lo, hi, basis = full + act[0], full + act[1], ["16 B / param (weights, grads, AdamW)",
                                                       "activations 2 B x layers x hidden x tokens x 4-16"]
    return {"lo_gib": round(lo + 0.5, 2), "hi_gib": round((hi + 1.5) * 1.15, 2),
            "parts": {"weights": round(weights or 0, 2), "kv": 0, "workspace": [0.5, 1.5]}, "confidence": "low",
            "basis": basis + [placement]}


def fit(est: dict, budget_gib: float | None, total_gib: float | None) -> dict:
    """{status fits|borderline|incompatible|unknown, pct_lo, pct_hi (of the card total), headroom_lo, headroom_hi
    (budget minus need; negative = short), reasons}. Upper bound within budget fits; lower bound above it does not."""
    lo, hi = (est or {}).get("lo_gib"), (est or {}).get("hi_gib")
    if lo is None or hi is None:
        return {"status": "unknown", "pct_lo": None, "pct_hi": None, "headroom_lo": None, "headroom_hi": None,
                "reasons": ["no estimate: " + "; ".join((est or {}).get("basis") or ["unknown"])]}
    if budget_gib is None or not total_gib:
        return {"status": "unknown", "pct_lo": None, "pct_hi": None, "headroom_lo": None, "headroom_hi": None,
                "reasons": [f"needs {lo:g}-{hi:g} GiB; free VRAM unknown (no GPU read)"]}
    r = {"pct_lo": round(100 * lo / total_gib), "pct_hi": round(100 * hi / total_gib),
         "headroom_lo": round(budget_gib - hi, 2), "headroom_hi": round(budget_gib - lo, 2)}
    if hi <= budget_gib:
        status, why = "fits", f"{r['headroom_lo']:g}-{r['headroom_hi']:g} GiB left of the {budget_gib:g} GiB budget"
    elif lo > budget_gib:
        status, why = "incompatible", (f"short {-r['headroom_hi']:g}-{-r['headroom_lo']:g} GiB of the "
                                        f"{budget_gib:g} GiB budget")
    else:
        status, why = "borderline", f"may fit: needs {lo:g}-{hi:g} GiB against a {budget_gib:g} GiB budget"
    return {"status": status, **r, "reasons": [why]}


# ----------------------------------------------------------------------------- search
def _synonyms(q: str) -> tuple[str, dict]:
    found: dict = {}
    pairs = sorted(((p, f) for ps, f in SYNONYMS for p in ps), key=lambda x: -len(x[0]))
    for phrase, f in pairs:
        pat = r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])"
        if re.search(pat, q, re.I):
            q = re.sub(pat, " ", q, flags=re.I)
            for k, val in f.items():
                found.setdefault(k, val)
    return " ".join(q.split()), found


def _rank(v: dict, q: str) -> int | None:
    """0 exact id / name / alias, 1 every word found, 2 every word found or close (a typo), None no match."""
    if not q:
        return 0
    ql = q.lower()
    if ql in {v["id"].lower(), str(v["name"]).lower(), *(a.lower() for a in v.get("aliases") or [])}:
        return 0
    hay = " ".join(str(x) for x in [v["id"], v["name"], *(v.get("aliases") or []), v.get("publisher") or "",
                                    v.get("family") or "", v.get("specialization") or "", v.get("task") or "",
                                    *(v.get("tags") or [])]).lower()
    toks = ql.split()
    if all(t in hay for t in toks):
        return 1
    words = set(re.findall(r"[a-z0-9.+-]+", hay)) | set(re.findall(r"[a-z]+", hay))
    if all(t in hay or difflib.get_close_matches(t, words, n=1, cutoff=0.75) for t in toks):
        return 2
    return None


def _keep(v: dict, f: dict) -> bool:
    view = f.get("view") or "all"
    if view == "fits" and v["fit"]["status"] != "fits" or view == "installed" and not v.get("installed"):
        return False
    for k in FILTERS:
        want = str(f.get(k) or "").strip().lower()
        if not want:
            continue
        have = v.get(k + "s") if k in ("input", "output") else [v.get(k)]
        if want not in [str(h).lower() for h in have or []]:
            return False
    return True


def search(q: str = "", filters: dict | None = None, profile: str | None = None, snapshot: dict | None = None,
           extra: list | None = None) -> dict:
    """{items, counts, sources, budget, query, filters}. Exact id / name first, then word matches; close (typo)
    matches only when nothing matched as typed; every entry stays (incompatible ones too) unless a filter says otherwise. filters: view
    all|fits|installed, task, input, output, quant, source; 'describes images' = input image, 'generates images' =
    output image. snapshot: hwprofile.probe() when not given. Never raises."""
    f = {k: val for k, val in (filters or {}).items() if val not in (None, "")}
    q, syn = _synonyms(str(q or "")[:200])
    for k, val in syn.items():
        f.setdefault(k, val)
    items, sources = all_variants(extra)
    try:
        bud = hwprofile.budget(snapshot if snapshot is not None else hwprofile.probe(), profile)
    except (Exception, SystemExit):
        bud = {"profile": profile, "effective_gib": None, "total_gib": None, "per_gpu": [], "manual": False}
    ranked = []
    for v in items:
        r = _rank(v, q)
        if r is None:
            continue
        v = copy.deepcopy(v)
        try:
            v["estimate"] = estimate(v)
        except (Exception, SystemExit) as e:
            v["estimate"] = _unknown([str(e)])
        v["fit"] = fit(v["estimate"], bud.get("effective_gib"), bud.get("total_gib"))
        v["match"] = r
        ranked.append(v)
    if any(v["match"] < 2 for v in ranked):  # typo matches only when nothing matched as typed ('qwen3' != 'qwen2')
        ranked = [v for v in ranked if v["match"] < 2]
    ranked.sort(key=lambda v: (v["match"], FIT_ORDER.get(v["fit"]["status"], 9), str(v["name"]).lower()))
    counts = {"view": {"all": len(ranked), "fits": sum(v["fit"]["status"] == "fits" for v in ranked),
                       "installed": sum(bool(v.get("installed")) for v in ranked)}}
    for k in FILTERS:
        c: Counter = Counter()
        for v in ranked:
            c.update({str(x) for x in (v.get(k + "s") if k in ("input", "output") else [v.get(k)]) or [] if x})
        counts[k] = dict(sorted(c.items()))
    return {"items": [v for v in ranked if _keep(v, f)], "counts": counts, "sources": sources, "budget": bud,
            "query": q, "filters": f}


# ----------------------------------------------------------------------------- appropriateness score
def score(cands: list, weights: dict, bounds: dict) -> list[dict]:
    """Rank candidates [{id, metrics:{name: value}}] by a weighted 0-100 score. bounds per metric: benefit
    {kind:'benefit', floor, target} -> clamp((v-floor)/(target-floor)); cost {kind:'cost', target, ceiling} ->
    clamp((ceiling-v)/(ceiling-target)). Weights sum to 1. A candidate missing a weighted metric is unmeasured:
    score None (ranked last), never a guessed number. SystemExit on bad weights or bounds."""
    if not isinstance(weights, dict) or not weights:
        raise SystemExit("Give each metric a weight")
    try:
        w = {k: float(val) for k, val in weights.items()}
    except (TypeError, ValueError):
        raise SystemExit("Weights must be numbers") from None
    if any(val < 0 for val in w.values()) or abs(sum(w.values()) - 1) > 1e-6:
        raise SystemExit(f"Weights must be 0 or more and add up to 1 (they add up to {sum(w.values()):g})")
    norm = {}
    for m in w:
        b = (bounds or {}).get(m)
        if not isinstance(b, dict) or b.get("kind") not in ("benefit", "cost"):
            raise SystemExit(f"{m}: bounds need kind benefit (floor, target) or cost (target, ceiling)")
        try:
            if b["kind"] == "benefit":
                lo, hi = float(b["floor"]), float(b["target"])
            else:
                lo, hi = float(b["target"]), float(b["ceiling"])
        except (KeyError, TypeError, ValueError):
            raise SystemExit(f"{m}: bounds must be numbers") from None
        if lo >= hi:
            raise SystemExit(f"{m}: {'floor must be below target' if b['kind'] == 'benefit' else 'target must be below ceiling'}")
        norm[m] = (b["kind"], lo, hi)
    out = []
    for c in cands or []:
        metrics = c.get("metrics") or {}
        parts, missing = {}, []
        for m, (kind, lo, hi) in norm.items():
            val = metrics.get(m)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                missing.append(m)
                continue
            x = (val - lo) / (hi - lo) if kind == "benefit" else (hi - val) / (hi - lo)
            parts[m] = min(1.0, max(0.0, x))
        s = None if missing else round(100 * sum(w[m] * parts[m] for m in norm))
        out.append({"id": c.get("id"), "score": s, "parts": {k: round(x, 4) for k, x in parts.items()},
                    "unmeasured": missing})
    out.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    return out
