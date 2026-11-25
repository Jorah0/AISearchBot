"""Model lab training (pass 59, section E): the training environment, the job planner and the worker's lifecycle.

The app never imports torch: sizes and memory are pure arithmetic here, the environment is probed by running its own
python, and every job runs `labtrain_worker.py` inside `HOME/train-env` as a hidden subprocess with no API keys in its
environment. One GPU lease (meta `lab:lease` = the job id) at a time. Full AI cannot set up the environment or start a
job. Memory figures are estimates, labelled so; only a run on this machine is measured (the worker's vram_peak_gib)."""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config, db, updater
from .util import NO_WINDOW

ENV_DIR = config.HOME / "train-env"
JOBS_DIR = config.HOME / "lab" / "jobs"
LOG = config.HOME / "logs" / "train-env.log"
WORKER = Path(__file__).with_name("labtrain_worker.py")
KINDS = ("lora", "scratch", "export", "probe")
LEASE = "lab:lease"
GIB = 2 ** 30

# Pinned set, checked against PyPI metadata on 2026-11-24 (transformers 5.24.1 wants tokenizers 0.23.x, hub >= 1.31;
# trl 1.18.2 wants datasets >= 4.7, accelerate >= 1.11). torch comes from the CUDA 12.6 index: the newest torch with
# Python 3.14 wheels there (cu128 stops at 2.11), and 12.6 runs on any recent driver for an RTX 40xx (sm_89).
TORCH = "torch==2.14.1"
TORCH_INDEX = "https://download.pytorch.org/whl/cu126"
PACKAGES = ["transformers==5.24.1", "peft==0.22.0", "trl==1.18.2", "datasets==5.2.0", "accelerate==1.16.0",
            "safetensors==0.8.0", "sentencepiece==0.2.3", "tokenizers==0.23.3"]
OPTIONAL = ["bitsandbytes==0.50.2"]  # QLoRA only; its failure is reported on its own and the rest still works
PROBED = ("torch", "transformers", "peft", "trl", "datasets", "accelerate", "bitsandbytes")
SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|PASS|PWD|CREDENTIAL|AUTH|COOKIE|SESSION", re.I)  # PASS: IMAP_PASS (.env)

# Run by the environment's own python (a list argument, never a shell): versions + CUDA as one JSON line.
STATUS_PY = """
import json
from importlib import metadata
out = {"packages": {}, "cuda": None}
for name in NAMES:
    try:
        out["packages"][name] = metadata.version(name)
    except Exception:
        out["packages"][name] = None
try:
    import torch
    ok = torch.cuda.is_available()
    out["cuda"] = {"available": ok, "version": torch.version.cuda,
                   "device": torch.cuda.get_device_name(0) if ok else None}
except Exception as e:
    out["cuda"] = {"available": False, "error": type(e).__name__}
print(json.dumps(out))
"""

SCHEMA = """CREATE TABLE IF NOT EXISTS lab_jobs(id INTEGER PRIMARY KEY, sel_id INTEGER, rev INTEGER, kind TEXT,
status TEXT, plan TEXT, progress TEXT, log TEXT, idem_key TEXT UNIQUE, started TEXT, finished TEXT,
created_at TEXT DEFAULT (datetime('now')))"""

DEFAULTS = {
    "lora": {"rank": 16, "alpha": 32, "dropout": 0.05, "lr": 1e-4, "warmup": 0.03, "epochs": 1, "seq": 1024,
             "microbatch": 1, "accum": 16, "grad_ckpt": True, "seed": 0},
    "scratch": {"lr": 3e-4, "betas": [0.9, 0.95], "wd": 0.1, "clip": 1.0, "warmup": 0.02, "seq": 1024, "microbatch": 2,
                "accum": 8, "ckpt_every": 200, "log_every": 10},
    "export": {"dtype": "bf16", "quant": "Q4_K_M", "num_ctx": 4096, "temperature": 0.2},
    "probe": {},
}


# ---- sizes, memory and tokens (pure arithmetic) ----

def scratch_params(spec: dict) -> dict:
    """Bias-free Llama: Vd + L(2d^2 + 2dk + 3dm + 2d) + d, k = kv_heads x head_dim; untied adds the lm_head Vd."""
    V, L, d, m = spec["vocab"], spec["layers"], spec["hidden"], spec["mlp"]
    k = spec["kv_heads"] * spec["head_dim"]
    parts = {"embedding": V * d, "attention": L * (2 * d * d + 2 * d * k), "mlp": L * 3 * d * m,
             "norms": L * 2 * d + d, "lm_head": 0 if spec.get("tied", True) else V * d}
    return {"total": sum(parts.values()), "breakdown": parts}


def validate_scratch(spec: dict) -> list:
    errors = []
    for key in ("vocab", "layers", "hidden", "mlp", "heads", "kv_heads", "head_dim", "context"):
        v = spec.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            errors.append(f"{key} must be a positive whole number")
    if errors:
        return errors
    if spec["hidden"] % spec["heads"]:
        errors.append("hidden must divide evenly by heads")
    if spec["heads"] % spec["kv_heads"]:
        errors.append("heads must divide evenly by kv_heads")
    if spec["head_dim"] % 2:
        errors.append("head_dim must be even (rotary embeddings rotate pairs)")
    if spec["head_dim"] * spec["heads"] != spec["hidden"]:
        errors.append("head_dim x heads must equal hidden in this design")
    if spec["context"] < 16:
        errors.append("context must be at least 16")
    if spec["vocab"] < 256:
        errors.append("vocab must be at least 256")
    seed = spec.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        errors.append("seed must be a whole number")
    return errors


def train_memory(spec_or_params, kind: str, seq: int = 1024, microbatch: int = 1, rank: int = 16) -> dict:
    """GPU memory range for training, an estimate. kind 'scratch' / 'full': 16 B/param (bf16 weights + grads, fp32
    master + two AdamW moments) + activations; 'lora' / 'qlora': a 4-bit base (~0.55 B/param) + the adapter at
    16 B/param + activations with gradient checkpointing. Arch fields (layers, hidden, ...) sharpen the activations;
    without them the activation part is a wide guess and the basis says so."""
    spec = spec_or_params if isinstance(spec_or_params, dict) else {"params": int(spec_or_params)}
    arch = all(isinstance(spec.get(k), int) for k in ("layers", "hidden", "vocab"))
    if "params" in spec:
        P = int(spec["params"])
    elif "params_b" in spec:
        P = int(spec["params_b"] * 1e9)
    else:
        P = scratch_params(spec)["total"]
    tok = seq * microbatch
    parts = {}
    if kind in ("scratch", "full"):
        parts["states"] = 16 * P
        if arch:
            L, d, h = spec["layers"], spec["hidden"], spec.get("heads", 1)
            hi = tok * L * d * 34 + 5 * h * seq * tok * L + tok * spec["vocab"] * 4  # Korthikanti, no recompute, + fp32 logits
            act = (tok * L * d * 2 + tok * spec["vocab"] * 4, hi)
        else:
            act = (0.05 * 16 * P, 0.5 * 16 * P)
    elif kind in ("lora", "qlora"):
        parts["weights"] = 0.55 * P
        if arch:
            L, d = spec["layers"], spec["hidden"]
            k = spec.get("kv_heads", 1) * spec.get("head_dim", d)
            m = spec.get("mlp", 4 * d)
            adapter = L * rank * (2 * (d + d) + 2 * (d + k) + 3 * (d + m))  # q, o, k, v, gate, up, down
            act = (tok * L * d * 2 * 2 + tok * spec["vocab"] * 4, tok * L * d * 2 * 8 + tok * spec["vocab"] * 4 * 2)
        else:
            adapter = 0.005 * P
            act = (0.5 * GIB * tok / 1024, 3 * GIB * tok / 1024)
        parts["adapter"] = adapter * 4
        parts["optimizer"] = adapter * 12  # fp32 grads + two AdamW moments
    else:
        raise ValueError(kind)
    fixed = sum(parts.values())
    lo, hi = fixed + act[0] + 0.5 * GIB, (fixed + act[1] + 1.5 * GIB) * 1.1
    parts = {k: round(v / GIB, 2) for k, v in parts.items()} | {
        "activations": [round(act[0] / GIB, 2), round(act[1] / GIB, 2)], "workspace": [0.5, 1.5]}
    basis = (f"estimate: {P:,} params, {kind}, seq {seq} x microbatch {microbatch}; "
             + ("activations from the architecture" if arch else "activations guessed (no architecture given)")
             + "; +10% margin on the high end. Only a run on this machine is measured.")
    return {"lo_gib": round(lo / GIB, 1), "hi_gib": round(hi / GIB, 1), "parts": parts, "basis": basis, "estimate": True}


def token_plan(tokens: int, seq: int, microbatch: int, accum: int, devices: int = 1, tok_per_s=None) -> dict:
    per = seq * microbatch * accum * devices
    return {"per_update": per, "updates": math.ceil(tokens / per),
            "hours": round(tokens / tok_per_s / 3600, 1) if tok_per_s else None}


# ---- environment ----

def env_python() -> Path:
    return ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def worker_env() -> dict:
    """os.environ without anything that looks like a key, token, secret or password: the worker never sees one."""
    return {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}


_LAST: dict = {}  # the last full probe, for pages that redraw often (env_status(cached=True))


def env_status(cached: bool = False) -> dict:
    """Packages and CUDA as the environment's own python sees them (a subprocess: seconds, since it imports torch).
    cached=True returns the last probe (or just whether the environment exists) without running anything."""
    py = env_python()
    out = {"exists": py.exists(), "python": str(py), "packages": dict.fromkeys(PROBED), "cuda": None, "error": None}
    if cached and _LAST.get("python") == str(py) and _LAST.get("exists") == out["exists"]:
        return dict(_LAST)
    if not out["exists"] or cached:
        return out
    script = f"NAMES = {list(PROBED)!r}\n" + STATUS_PY
    try:
        code, so, se = updater._proc([str(py), "-I", "-c", script], ENV_DIR, 180, worker_env())
        if code:
            out["error"] = ((se or so).strip().splitlines() or ["probe failed"])[-1][:300]
            return out
        got = json.loads(so.strip().splitlines()[-1])
        out["packages"].update(got["packages"])
        out["cuda"] = got["cuda"]
    except (OSError, ValueError, IndexError, SystemExit) as e:
        out["error"] = str(e)[:300]
    _LAST.clear()
    _LAST.update(out)
    return out


def _base_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        exe = exe.with_name("python.exe")  # the windowless launcher's interpreter; output is captured either way
    return str(exe)


def setup_commands() -> list:
    """[(label, argv, optional, timeout)] that setup_env runs, in order."""
    py = str(env_python())
    pip = [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    return [("create venv", [_base_python(), "-m", "venv", str(ENV_DIR)], False, 600),
            ("upgrade pip", pip + ["--upgrade", "pip"], False, 600),
            ("torch (CUDA 12.6)", pip + [TORCH, "--index-url", TORCH_INDEX], False, 3600),
            ("training packages", pip + PACKAGES, False, 3600),
            *[(f"optional {p.split('==')[0]}", pip + [p], True, 1800) for p in OPTIONAL]]


def setup_env(progress=None) -> dict:
    """Create HOME/train-env and install the pinned set (gigabytes; the owner's click). Log: HOME/logs/train-env.log."""
    config.full_ai_check("sets up the training environment")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    steps, optional_failed, ok = [], [], True
    env = worker_env()
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n== setup {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        for label, cmd, optional, timeout in setup_commands():
            if progress:
                progress(label)
            log.write(f"$ {' '.join(map(str, cmd))}\n")
            log.flush()
            try:
                code, out, err = updater._proc(cmd, config.HOME, timeout, env)
            except (OSError, SystemExit) as e:
                code, out, err = -1, "", str(e)
            log.write(out + err + f"-> exit {code}\n")
            log.flush()
            steps.append({"step": label, "ok": code == 0, "code": code})
            if code and optional:
                optional_failed.append({"step": label, "detail": (err or out).strip()[-300:]})
            elif code:
                ok = False
                break
    failed = next((st["step"] for st in steps if not st["ok"] and not st["step"].startswith("optional")), None)
    summary = (f"setup stopped at {failed}; see {LOG}" if failed else "training environment ready"
               + "".join(f"; {f['step']} failed" for f in optional_failed))
    return {"ok": ok, "summary": summary, "steps": steps, "optional_failed": optional_failed, "log": str(LOG),
            "torch_index": TORCH_INDEX, "status": env_status() if ok else None}


# ---- jobs ----

def _c():
    c = db.con()
    c.execute(SCHEMA)
    return c


def _row(r) -> dict | None:
    if r is None:
        return None
    job = dict(r)
    job["plan"] = json.loads(job["plan"] or "{}")
    job["progress"] = json.loads(job["progress"] or "{}")
    return job


def get(job_id: int) -> dict | None:
    return _row(_c().execute("SELECT * FROM lab_jobs WHERE id=?", (job_id,)).fetchone())


def jobs(limit: int = 50) -> list:
    return [_row(r) for r in _c().execute("SELECT * FROM lab_jobs ORDER BY id DESC LIMIT ?", (limit,))]


def job_dir(job: dict) -> Path:
    return JOBS_DIR / job["idem_key"][:16]


def plan(kind: str, sel_id: int, rev: int, spec: dict, dataset_path=None, dataset_sha=None, hyper=None) -> dict:
    """An immutable job for selection sel_id at revision rev. The same inputs give the same idem_key and the same job."""
    if kind not in KINDS:
        raise SystemExit(f"unknown job kind {kind!r}: one of {', '.join(KINDS)}")
    body = {"kind": kind, "sel_id": sel_id, "rev": rev, "spec": spec, "dataset_path": dataset_path,
            "dataset_sha": dataset_sha, "hyper": DEFAULTS[kind] | (hyper or {})}
    if kind in ("scratch", "probe"):
        errors = validate_scratch(spec)
        if errors:
            raise SystemExit("the design does not hold: " + "; ".join(errors))
        body["expected_params"] = scratch_params(spec)["total"]
    if kind == "lora" and not (dataset_path and dataset_sha):
        raise SystemExit("a LoRA job needs a dataset (path and hash)")
    idem = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    c = _c()
    old = c.execute("SELECT * FROM lab_jobs WHERE idem_key=?", (idem,)).fetchone()
    if old:
        return _row(old)
    log = JOBS_DIR / idem[:16] / "worker.log"
    c.execute("INSERT OR IGNORE INTO lab_jobs(sel_id, rev, kind, status, plan, progress, log, idem_key) "
              "VALUES(?, ?, ?, 'planned', ?, '{}', ?, ?)", (sel_id, rev, kind, json.dumps(body), str(log), idem))
    c.commit()
    return _row(c.execute("SELECT * FROM lab_jobs WHERE idem_key=?", (idem,)).fetchone())


def _set(job_id: int, **fields) -> None:
    for k in ("plan", "progress"):
        if k in fields:
            fields[k] = json.dumps(fields[k])
    c = _c()
    c.execute(f"UPDATE lab_jobs SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), job_id))
    c.commit()


def _alive(job: dict) -> bool:
    p = job["progress"]
    return bool(p.get("pid")) and updater._alive(int(p["pid"]), p.get("since"))


def _release(job_id: int) -> None:
    if db.meta_get(LEASE) == job_id:
        db.meta_set(LEASE, None)


def start(job_id: int) -> dict:
    """Spawn the worker for this job inside train-env, hidden, with stdout to the job log. One GPU job at a time."""
    config.full_ai_check("starts a training job")
    job = get(job_id)
    if not job:
        raise SystemExit(f"no training job #{job_id}")
    if job["status"] == "done":
        raise SystemExit(f"job #{job_id} is done; plan a new one to run it again")
    held = db.meta_get(LEASE)
    if held and held != job_id:
        other = get(held)
        if other and other["status"] == "running" and _alive(other):
            raise SystemExit(f"the GPU is in use by training job #{held}; pause or cancel it first")
        if other and other["status"] == "running":
            poll(held)  # its process is gone: recorded as failed, lease released
    if job["status"] == "running" and _alive(job):
        raise SystemExit(f"job #{job_id} is already running")
    py = env_python()
    if not py.exists():
        raise SystemExit("set up the training environment first (Model lab > Training)")
    d = job_dir(job)
    (d / "out").mkdir(parents=True, exist_ok=True)
    for flag in ("pause", "cancel"):
        (d / flag).unlink(missing_ok=True)
    spec = {"id": job_id, **job["plan"], "progress": str(d / "progress.jsonl"), "pause": str(d / "pause"),
            "cancel": str(d / "cancel"), "out_dir": str(d / "out")}
    path = d / "job.json"
    path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    with open(job["log"], "ab") as log:
        # -I: the script's folder (lodestar/, whose profile.py would shadow the stdlib one) is not put on sys.path
        p = subprocess.Popen([str(py), "-I", str(WORKER), str(path)], cwd=str(d), stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, env=worker_env(), creationflags=NO_WINDOW)
    db.meta_set(LEASE, job_id)
    keep = {k: v for k, v in job["progress"].items() if k not in ("pid", "since")}
    _set(job_id, status="running", started=datetime.now().isoformat(timespec="seconds"), finished=None,
         progress=keep | {"pid": p.pid, "since": time.time()})
    return get(job_id)


def read_progress(path) -> list:
    """The worker's progress JSON lines; a torn or foreign line is skipped."""
    rows = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def poll(job_id: int) -> dict:
    """Read the progress file; a final line sets done / failed / paused; a running job whose process is gone is
    failed with 'process ended'. A finished job gives the lease back."""
    job = get(job_id)
    if not job or job["status"] != "running":
        return job
    rows = read_progress(job_dir(job) / "progress.jsonl")
    last = rows[-1] if rows else None
    prog = job["progress"] | {"lines": len(rows)} | ({"last": last} if last else {})
    status = last.get("status") if last else None
    if status not in ("done", "failed", "paused", "cancelled"):
        status = "running" if _alive(job) else "failed"
        if status == "failed":
            prog["reason"] = "process ended"
    elif status == "failed":
        prog["reason"] = last.get("msg") or "failed"
    fields = {"status": status, "progress": prog}
    if status != "running":
        fields["finished"] = datetime.now().isoformat(timespec="seconds")
        _release(job_id)
    _set(job_id, **fields)
    return get(job_id)


def recover() -> list:
    """Every running job is polled: one whose process is gone becomes failed ('process ended')."""
    return [poll(r["id"]) for r in _c().execute("SELECT id FROM lab_jobs WHERE status='running'").fetchall()]


def pause(job_id: int) -> dict:
    """The worker checks this flag at step boundaries: it saves a checkpoint, reports paused and exits."""
    job = get(job_id)
    if not job or job["status"] != "running":
        raise SystemExit(f"job #{job_id} is not running")
    (job_dir(job) / "pause").write_text("pause", encoding="utf-8")
    return job


def pause_all() -> list[int]:
    """Lodestar is quitting or restarting: every running job gets the pause flag (a checkpoint at the next step, then
    the worker exits), so no training keeps running on its own after the app closes. Never raises."""
    paused = []
    try:
        for job in jobs(200):
            if job and job["status"] == "running":
                try:
                    (job_dir(job) / "pause").write_text("pause", encoding="utf-8")
                    paused.append(job["id"])
                except OSError:
                    pass
    except Exception:
        pass
    return paused


def cancel(job_id: int) -> dict:
    """Stop now: the flag for a worker between steps, then the process tree; the lease is released."""
    job = get(job_id)
    if not job:
        raise SystemExit(f"no training job #{job_id}")
    if job["status"] == "running":
        (job_dir(job) / "cancel").write_text("cancel", encoding="utf-8")
        if _alive(job) and os.name == "nt":
            updater._proc(["taskkill", "/T", "/F", "/PID", str(job["progress"]["pid"])], config.HOME, 60)
        elif _alive(job):
            os.kill(int(job["progress"]["pid"]), 9)
    if job["status"] not in ("done", "failed"):
        _set(job_id, status="cancelled", finished=datetime.now().isoformat(timespec="seconds"))
    _release(job_id)
    return get(job_id)
