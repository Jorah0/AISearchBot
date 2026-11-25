"""Missing packages: find them and, in a source install's venv, pip install exactly what pyproject.toml declares.
A standalone exe (PyInstaller) has no pip and its packages are fixed at build time: it never installs anything.
Never the system Python, never a spec that pyproject.toml does not list, never user input in the pip command."""
import datetime
import importlib.util
import re
import sys
import tomllib
from pathlib import Path

from . import config, updater

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"  # the exe bundles it at its root (build_exe.ps1)
LOG = config.HOME / "logs" / "deps.log"
IMPORTS = {"pywebview": "webview", "python-docx": "docx"}  # distribution -> import name, where they differ
FROZEN_MSG = ("this standalone exe bundles its packages at build time: rebuild it "
              "(scripts\\build_exe.ps1 -Force / install.ps1 -Exe)")


def _load() -> dict[str, list[str]]:
    try:
        p = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return {}
    return {"core": list(p.get("dependencies", [])), **{k: list(v) for k, v in p.get("optional-dependencies", {}).items()}}


REQUIREMENTS = _load()  # {"core": [...], "desktop": ["pywebview>=5"], "apply": [...], ...}


def module_of(spec: str) -> str:
    name = re.match(r"[A-Za-z0-9_.-]+", spec).group(0).lower()
    return IMPORTS.get(name, name.replace("-", "_"))


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def missing(extra: str | None = None) -> list[str]:
    """The specs of `extra` (None = the core dependencies) whose module is not importable. find_spec only: nothing is
    imported (every name here is top level)."""
    if (extra or "core") not in REQUIREMENTS:
        raise SystemExit(f"unknown extra {extra!r}: one of {', '.join(REQUIREMENTS) or '(pyproject.toml not found)'}")
    return [s for s in REQUIREMENTS[extra or "core"] if importlib.util.find_spec(module_of(s)) is None]


def _shown(cmd: list[str]) -> str:
    return " ".join(f'"{c}"' if re.search(r"[\s<>]", c) else c for c in cmd)


def ensure(extra: str | None = None, auto: bool = True) -> dict:
    """Install what `extra` is missing into this interpreter's venv. {installed, missing, frozen, log, error}."""
    config.full_ai_check("installs packages")
    miss = missing(extra)
    out = {"installed": [], "missing": miss, "frozen": frozen(), "log": str(LOG), "error": None}
    if not miss:
        return out
    if out["frozen"]:
        return out | {"error": FROZEN_MSG}
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *miss]
    if sys.prefix == sys.base_prefix:
        return out | {"error": f"Lodestar installs only into a virtual environment, never the system Python; run: {_shown(cmd)}"}
    if not auto:
        return out | {"error": f"missing {', '.join(miss)}; run: {_shown(cmd)}"}
    try:
        code, so, se = updater._proc(cmd, config.HOME, 900)  # hidden (NO_WINDOW), tree-killed on the timeout
    except SystemExit as e:
        code, so, se = -1, "", str(e)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {_shown(cmd)} -> exit {code}\n{so}{se}\n")
    importlib.invalidate_caches()
    out["missing"] = missing(extra)
    out["installed"] = [s for s in miss if s not in out["missing"]]
    if code or out["missing"]:
        out["error"] = f"pip install failed (exit {code}); see {LOG}"
    return out
