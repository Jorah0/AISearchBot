"""Hardware for the Model lab (pass 59, part A): what this computer has (GPUs through nvidia-smi, RAM, free disk, the
models Ollama holds loaded) and how much of it a model may use under a profile ("OBS live" keeps 3 GiB of VRAM back).

probe() never raises: a part it cannot read is None and the reason goes in `error`. Only local programs and the
loopback Ollama API are asked; nothing leaves this computer."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import HOME
from .jobmodel import _base_url, _meta, _set_meta

GIB = 2 ** 30
PROFILES_KEY = "lab:profiles"
ACTIVE_KEY = "lab:profile"
DEFAULT_PROFILES = {"Idle": {"reserve_gib": 0, "note": "Nothing else needs the GPU."},
                    "OBS live": {"reserve_gib": 3, "note": "Keeps 3 GiB of VRAM for OBS while streaming or recording."}}
SMI_QUERY = "index,name,memory.total,memory.free,memory.used,driver_version"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------- readers (tests patch these)
def _run_smi() -> str:
    """nvidia-smi's CSV answer (hidden window, tree-killed on timeout); raises when it is missing or fails."""
    from . import updater

    exe = shutil.which("nvidia-smi") or next(
        (str(p) for p in [Path(r"C:\Windows\System32\nvidia-smi.exe")] if os.name == "nt" and p.is_file()), None)
    if not exe:
        raise RuntimeError("nvidia-smi not found (no NVIDIA driver)")
    code, out, err = updater._proc([exe, f"--query-gpu={SMI_QUERY}", "--format=csv,noheader,nounits"], HOME, 10)
    if code:
        raise RuntimeError((err or out).strip()[:200] or f"nvidia-smi exited {code}")
    return out


def _get(path: str, timeout: int = 5) -> dict:
    """GET the local Ollama API (loopback: not util.fetch, whose SSRF guard refuses loopback by design)."""
    from . import jobmodel

    with jobmodel.urlopen(_base_url() + path, timeout=timeout) as r:  # never through a configured HTTP proxy
        return json.loads(r.read() or b"{}")


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None  # "[N/A]" on some boards


def _gib(mib) -> float | None:
    return None if mib is None else round(mib / 1024, 2)


def parse_smi(text: str) -> list[dict]:
    gpus = []
    for line in (text or "").splitlines():
        f = [s.strip() for s in line.split(",")]
        if len(f) < 6 or _num(f[0]) is None:
            continue
        gpus.append({"index": int(_num(f[0])), "name": f[1], "total_gib": _gib(_num(f[2])),
                     "free_gib": _gib(_num(f[3])), "used_gib": _gib(_num(f[4])), "driver": f[5]})
    return gpus


def _ram() -> dict:
    if os.name == "nt":
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MemoryStatusEx()
        m.dwLength = ctypes.sizeof(m)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            raise OSError("GlobalMemoryStatusEx failed")
        return {"total_gib": round(m.ullTotalPhys / GIB, 2), "free_gib": round(m.ullAvailPhys / GIB, 2)}
    kb = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        kb[k] = int(v.split()[0]) if v.split() else 0
    return {"total_gib": round(kb["MemTotal"] / 2 ** 20, 2),
            "free_gib": round(kb.get("MemAvailable", kb.get("MemFree", 0)) / 2 ** 20, 2)}


def _ollama_ps() -> dict:
    running = []
    for m in _get("/api/ps").get("models") or []:
        running.append({"name": m.get("name") or m.get("model"),
                        "size_vram_gib": round((m.get("size_vram") or 0) / GIB, 2),
                        "context": m.get("context_length")})
    return {"running": running}


# ----------------------------------------------------------------------------- probe
def probe() -> dict:
    """{at, gpus:[{index,name,total_gib,free_gib,used_gib,driver}], ram, disk, ollama, source, error}. Never raises."""
    snap = {"at": _utc(), "gpus": None, "ram": None, "disk": None, "ollama": None, "source": "none", "error": None}
    errors = []
    try:
        snap["gpus"] = parse_smi(_run_smi())
        snap["source"] = "nvidia-smi"
    except (Exception, SystemExit) as e:
        errors.append(f"GPU: {e}")
    try:
        snap["ram"] = _ram()
    except (Exception, SystemExit) as e:
        errors.append(f"RAM: {e}")
    try:
        snap["disk"] = {"path": str(HOME), "free_gib": round(shutil.disk_usage(HOME).free / GIB, 2)}
    except (Exception, SystemExit) as e:
        errors.append(f"disk: {e}")
    try:
        snap["ollama"] = _ollama_ps()
    except (Exception, SystemExit) as e:
        errors.append(f"Ollama: {type(e).__name__}")  # usually not running; the URL stays out of the page
    snap["error"] = "; ".join(errors) or None
    return snap


def manual_snapshot(total_gib: float, free_gib: float, name: str = "Manual") -> dict:
    """A snapshot you typed (no NVIDIA card, or planning for another PC); budget() carries manual=True."""
    try:
        total, free = float(total_gib), float(free_gib)
    except (TypeError, ValueError):
        raise SystemExit("Total and free VRAM must be numbers (GiB)") from None
    if not (0 < total <= 1024 and 0 <= free <= total):
        raise SystemExit("VRAM: total must be 0-1024 GiB and free between 0 and total")
    return {"at": _utc(), "manual": True, "source": "manual", "error": None, "ram": None, "disk": None, "ollama": None,
            "gpus": [{"index": 0, "name": name, "total_gib": total, "free_gib": free, "used_gib": round(total - free, 2),
                      "driver": None}]}


# ----------------------------------------------------------------------------- profiles and budget
def profiles() -> dict:
    """{name: {reserve_gib, note}}: the defaults plus yours (yours win)."""
    stored = _meta(PROFILES_KEY) or {}
    return DEFAULT_PROFILES | {k: v for k, v in stored.items() if isinstance(v, dict)}


def save_profile(name: str, reserve_gib, note: str = "") -> dict:
    name = str(name or "").strip()
    if not name or len(name) > 40:
        raise SystemExit("A profile needs a name of 1-40 characters")
    try:
        reserve = float(reserve_gib)
    except (TypeError, ValueError):
        raise SystemExit("Reserve must be a number of GiB") from None
    if not 0 <= reserve <= 256:
        raise SystemExit("Reserve must be between 0 and 256 GiB")
    stored = _meta(PROFILES_KEY) or {}
    stored[name] = {"reserve_gib": reserve, "note": str(note or "")[:200]}
    _set_meta(PROFILES_KEY, stored)
    return profiles()


def delete_profile(name: str) -> dict:
    """Removes your profile (a default one goes back to its default values)."""
    stored = _meta(PROFILES_KEY) or {}
    stored.pop(name, None)
    _set_meta(PROFILES_KEY, stored or None)
    if active_profile() not in profiles():
        _set_meta(ACTIVE_KEY, None)
    return profiles()


def active_profile() -> str:
    name = (_meta(ACTIVE_KEY) or {}).get("name")
    return name if name in profiles() else "Idle"


def set_active(name: str) -> str:
    if name not in profiles():
        raise SystemExit(f"No hardware profile named {name!r}")
    _set_meta(ACTIVE_KEY, {"name": name})
    return name


set_profile = save_profile  # the names modellab calls
use_profile = set_active


def budget(snapshot: dict, profile: str | dict | None = None) -> dict:
    """VRAM a model may use: per GPU effective = max(0, free - reserve). total_gib is the cards' total (for the %),
    effective_gib the sum of the effective figures. Unknown free VRAM stays None (never guessed)."""
    if isinstance(profile, dict):
        name, reserve = profile.get("name") or "custom", float(profile.get("reserve_gib") or 0)
    else:
        name = profile or active_profile()
        reserve = float((profiles().get(name) or {}).get("reserve_gib") or 0)
    per = []
    for g in (snapshot or {}).get("gpus") or []:
        free = g.get("free_gib")
        per.append({"index": g.get("index"), "name": g.get("name"), "total_gib": g.get("total_gib"), "free_gib": free,
                    "effective_gib": None if free is None else round(max(0.0, free - reserve), 2)})
    known = [p for p in per if p["effective_gib"] is not None]
    return {"profile": name, "reserve_gib": reserve, "per_gpu": per, "manual": bool((snapshot or {}).get("manual")),
            "effective_gib": round(sum(p["effective_gib"] for p in known), 2) if known else None,
            "total_gib": round(sum(p["total_gib"] or 0 for p in per), 2) if per else None}
