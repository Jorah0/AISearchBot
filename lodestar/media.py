"""Local generation runtimes (pass 59, plan docs/superpowers/plans/2026-11-24-model-lab.md section G).

ComfyUI, LocalAI and Ollama's experimental image generation, listed in data/media_runtimes.json. Every request goes to
loopback only (127.0.0.1 / localhost / ::1), without a proxy and without following redirects. probe() never raises;
submit() runs on your click only (Full AI refused), records the job in media_jobs and saves what the runtime made
under HOME/media/<job>/. Nothing here sends a prompt or an artifact anywhere else. VRAM figures in the registry are
the publisher's (labelled "publisher-reported"), never a measurement of this computer."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import config, db

REGISTRY = Path(__file__).parent / "data" / "media_runtimes.json"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PLACEHOLDER = "YOUR_SDXL_CHECKPOINT.safetensors"
POLL_MAX = 300  # ComfyUI history polls per job
POLL_PAUSE = 1.0  # seconds between polls (tests set 0 and put it back)

_SCHEMA = """CREATE TABLE IF NOT EXISTS media_jobs(id TEXT PRIMARY KEY, runtime TEXT NOT NULL, operation TEXT,
  recipe_hash TEXT, status TEXT NOT NULL, artifacts TEXT DEFAULT '[]', peak TEXT, error TEXT,
  created_at TEXT DEFAULT (datetime('now')))"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a loopback service never sends us to another host
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def registry() -> dict:
    return {k: v for k, v in json.loads(REGISTRY.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def _loopback(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "http" or (u.hostname or "").lower() not in LOOPBACK:
        raise ValueError(f"media runtimes are reached on this computer only (loopback), not {u.hostname or url!r}")
    return url


def _get(url: str, timeout: float = 10, raw: bool = False):
    with _OPENER.open(_loopback(url), timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data or b"{}")


def _post(url: str, body: dict, timeout: float = 60, raw: bool = False):
    req = urllib.request.Request(_loopback(url), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        data = r.read()
    return data if raw else json.loads(data or b"{}")


def _models(d) -> list[str]:
    if isinstance(d, list):
        return [str(x) for x in d][:200]
    items = (d or {}).get("data") or (d or {}).get("models") or []
    return [str(m.get("id") or m.get("name") or m.get("model")) if isinstance(m, dict) else str(m) for m in items][:200]


def _version(health: bytes):
    try:
        d = json.loads(health or b"{}")
    except ValueError:
        return None  # LocalAI's /readyz answers plain text: version unknown
    if not isinstance(d, dict):
        return None
    return (d.get("system") or {}).get("comfyui_version") or d.get("version")


def probe() -> dict:
    """-> {runtime: {up, version, models, error}}. Loopback only; never raises."""
    out = {}
    for name, rt in registry().items():
        res = {"up": False, "version": None, "models": [], "error": None}
        try:
            base = _loopback(rt["base"]).rstrip("/")
            health = _get(base + rt["health"], timeout=3, raw=True)
            res["up"], res["version"] = True, _version(health)
            try:
                res["models"] = _models(_get(base + rt["models"], timeout=5))
            except Exception as e:  # noqa: BLE001 - up, but the model list failed
                res["error"] = f"models: {e}"[:300]
        except Exception as e:  # noqa: BLE001 - down, refused or not loopback: say so, never raise
            res["error"] = str(e)[:300] or type(e).__name__
        out[name] = res
    return out


def sdxl_workflow(prompt: str, checkpoint: str, negative: str = "", width: int = 1024, height: int = 1024,
                  steps: int = 30, cfg: float = 7.0, seed: int = 0) -> dict:
    """The registry's minimal SDXL text-to-image graph (ComfyUI API format) with your checkpoint file name filled in."""
    if not (256 <= width <= 2048 and 256 <= height <= 2048 and width % 8 == 0 and height % 8 == 0):
        raise ValueError("width and height: 256-2048, multiples of 8")
    if not 1 <= steps <= 150:
        raise ValueError("steps: 1-150")
    wf = copy.deepcopy(registry()["comfyui"]["templates"]["sdxl_text_to_image"])
    wf.pop("_fill_in", None)
    wf["4"]["inputs"]["ckpt_name"] = checkpoint
    wf["5"]["inputs"].update(width=width, height=height)
    wf["6"]["inputs"]["text"], wf["7"]["inputs"]["text"] = prompt, negative
    wf["3"]["inputs"].update(seed=int(seed), steps=int(steps), cfg=float(cfg))
    return wf


def _prepare(runtime: str, rt: dict, recipe: dict):
    """Check a recipe before anything is recorded or sent; -> the request body."""
    op = recipe.get("operation")
    if op not in rt["operations"]:
        raise SystemExit(f"{rt['label']} does not do {op!r} here ({', '.join(rt['operations'])})")
    if runtime == "comfyui":
        wf = recipe.get("workflow")
        if wf is None:
            if not recipe.get("prompt") or not recipe.get("checkpoint"):
                raise SystemExit("a ComfyUI text-to-image recipe needs a prompt and your checkpoint file name")
            keys = ("negative", "width", "height", "steps", "cfg", "seed")
            wf = sdxl_workflow(recipe["prompt"], recipe["checkpoint"], **{k: recipe[k] for k in keys if k in recipe})
        if not isinstance(wf, dict):
            raise SystemExit("workflow must be a ComfyUI API-format graph (an object)")
        if PLACEHOLDER in json.dumps(wf):
            raise SystemExit("fill in your SDXL checkpoint file name first")
        return wf
    if runtime == "localai":
        if not recipe.get("model"):
            raise SystemExit("a LocalAI recipe names the model to use")
        if op == "text->image":
            if not recipe.get("prompt"):
                raise SystemExit("a text->image recipe needs a prompt")
            return {"model": recipe["model"], "prompt": recipe["prompt"], "size": recipe.get("size") or "1024x1024",
                    "response_format": "b64_json"}
        if not recipe.get("text"):
            raise SystemExit("a text->speech recipe needs the text to speak")
        return {"model": recipe["model"], "input": recipe["text"]} | ({"voice": recipe["voice"]} if recipe.get("voice") else {})
    raise SystemExit(f"{rt['label']} cannot run jobs from Lodestar")


def _save(folder: Path, name: str, data: bytes) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(str(name)).name).lstrip(".")[:100] or "artifact"
    path, n = folder / safe, 1
    while path.exists():
        path, n = folder / f"{n}-{safe}", n + 1
    path.write_bytes(data)
    return str(path)


def _comfy(base: str, wf: dict, folder: Path, job_id: str) -> list[str]:
    pid = (_post(base + "/prompt", {"prompt": wf, "client_id": job_id}) or {}).get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI did not queue the workflow")
    for _ in range(POLL_MAX):
        entry = (_get(base + "/history/" + urllib.parse.quote(str(pid), safe="")) or {}).get(pid)
        if entry:
            if (entry.get("status") or {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI reported an error running the workflow")
            if entry.get("outputs"):
                break
        time.sleep(POLL_PAUSE)
    else:
        raise TimeoutError("ComfyUI did not finish in time")
    arts = []
    for out in entry["outputs"].values():
        for items in out.values():
            for f in items if isinstance(items, list) else []:
                if isinstance(f, dict) and f.get("filename"):
                    q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                                "type": f.get("type", "output")})
                    arts.append(_save(folder, f["filename"], _get(base + "/view?" + q, timeout=60, raw=True)))
    return arts


def _localai(base: str, rt: dict, op: str, body: dict, folder: Path) -> list[str]:
    url = base + rt["endpoints"][op]
    if op == "text->speech":
        return [_save(folder, "speech.wav", _post(url, body, timeout=600, raw=True))]
    d = ((_post(url, body, timeout=600) or {}).get("data") or [{}])[0]
    if d.get("b64_json"):
        return [_save(folder, "image.png", base64.b64decode(d["b64_json"]))]
    if d.get("url"):  # a link only if it is on this computer too (_get refuses anything else)
        return [_save(folder, Path(urllib.parse.urlsplit(d["url"]).path).name or "image.png",
                      _get(d["url"], timeout=60, raw=True))]
    raise RuntimeError("LocalAI returned no image")


def _peak(rt: dict, recipe: dict) -> str:
    for v in rt.get("vram") or []:
        if v["operation"] == recipe.get("operation") and v["model"].lower() in json.dumps(recipe).lower():
            figs = ", ".join(f"{k} {n} {v['unit']}" for k, n in v["figures"].items())
            return f"{v['label']}: {v['model']} {figs}"
    return "not measured"


def submit(runtime: str, recipe: dict) -> dict:
    """Run one job on a local runtime (your click). -> {id, runtime, operation, status done|failed|timeout, artifacts,
    peak, error}. Unknown runtime, probe-only runtime or a bad recipe: SystemExit before anything is recorded."""
    config.full_ai_check("starts media jobs")
    rt = registry().get(runtime)
    if rt is None:
        raise SystemExit(f"unknown media runtime {runtime!r}")
    if rt.get("probe_only"):
        raise SystemExit(f"{rt['label']} is probe only: Lodestar does not run jobs on it")
    if not isinstance(recipe, dict):
        raise SystemExit("recipe must be an object")
    base = _loopback(rt["base"]).rstrip("/")
    body = _prepare(runtime, rt, recipe)
    job = {"id": uuid.uuid4().hex[:12], "runtime": runtime, "operation": recipe["operation"], "status": "running",
           "artifacts": [], "peak": _peak(rt, recipe), "error": None}
    rhash = hashlib.sha256(json.dumps(recipe, sort_keys=True, default=str).encode()).hexdigest()
    c = db.con()
    c.execute(_SCHEMA)
    with c:
        c.execute("INSERT INTO media_jobs(id, runtime, operation, recipe_hash, status, peak) VALUES(?,?,?,?,?,?)",
                  (job["id"], runtime, job["operation"], rhash, "running", job["peak"]))
    folder = Path(config.HOME) / "media" / job["id"]
    try:
        if runtime == "comfyui":
            job["artifacts"] = _comfy(base, body, folder, job["id"])
        else:
            job["artifacts"] = _localai(base, rt, job["operation"], body, folder)
        job["status"] = "done"
    except TimeoutError as e:
        job["status"], job["error"] = "timeout", str(e)[:300]
    except (Exception, SystemExit) as e:  # noqa: BLE001 - recorded on the job, shown to you
        job["status"], job["error"] = "failed", str(e)[:300] or type(e).__name__
    with c:
        c.execute("UPDATE media_jobs SET status=?, artifacts=?, error=? WHERE id=?",
                  (job["status"], json.dumps(job["artifacts"]), job["error"], job["id"]))
    return job


def jobs(limit: int = 20) -> list[dict]:
    c = db.con()
    c.execute(_SCHEMA)
    rows = c.execute("SELECT * FROM media_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) | {"artifacts": json.loads(r["artifacts"] or "[]")} for r in rows]
