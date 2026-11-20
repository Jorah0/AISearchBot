"""One command for "is this change done?" (engineering loop, definition of done). Runs the checks this repository
actually uses, in order, and prints one line per step plus a summary; exit 1 when any required step fails.

  python scripts/verify.py           fast: lint, secret scan, JS syntax, extension tests, every unit test
  python scripts/verify.py --full    + browser tests (Edge/Playwright) and the Android build with its tests and lint
  python scripts/verify.py --json R  also write the results to R (evals and the engineering loop read it)

A step whose tool is missing (Playwright, node, the Android toolchain) is SKIPPED and said so, never reported as a
pass. Unit and browser tests run with the repo's own .venv when there is one."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(VENV) if VENV.is_file() else sys.executable


def has(mod: str) -> bool:
    return subprocess.run([PY, "-c", f"import {mod}"], capture_output=True).returncode == 0


def steps(full: bool) -> list[tuple[str, list[str] | None, dict, str]]:
    """(name, command or None when skipped, extra env, why skipped)."""
    node = shutil.which("node")
    out = [
        ("lint (pyflakes)", [PY, "-m", "pyflakes", "lodestar", "tests", "scripts"] if has("pyflakes") else None, {}, "pyflakes not installed"),
        ("secret scan", [PY, "scripts/secret_scan.py"], {}, ""),
        ("JS syntax", [node, "-e", "for (const f of ['lodestar/static/app.js','extension/content.js','extension/popup.js',"
                       "'extension/matcher.js']) require('child_process').execFileSync(process.execPath, ['--check', f])"]
         if node else None, {}, "node not installed"),
        ("extension tests", [node, "--test", "extension/test/*.test.mjs"] if node else None, {}, "node not installed"),
        ("unit tests", [PY, "-W", "ignore::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
         {"PYTHONIOENCODING": "utf-8"}, ""),
    ]
    if full:
        e2e_ok = has("playwright")
        out.append(("browser tests", [PY, "-m", "unittest", "discover", "-s", "tests/e2e", "-p", "e2e_*.py"] if e2e_ok else None,
                    {"PYTHONPATH": str(ROOT / "tests" / "e2e")}, "pip install -e .[e2e]"))
        tools = Path(os.environ.get("USERPROFILE", Path.home())) / "Android"
        android = os.name == "nt" and (tools / "sdk" / "platforms" / "android-35").is_dir()
        out.append(("android build + tests + lint",
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", "android/build.ps1", "-Test"] if android else None,
                    {}, "no Android toolchain (android/README.md)"))
    return out


def nothing_ran(text: str) -> str:
    """Why a run that exited 0 tested nothing ('' when it did): unittest 'Ran 0 tests' or every test skipped (a missing
    browser makes the browser suite skip itself), node --test 'tests 0'."""
    import re

    ran = re.findall(r"^Ran (\d+) tests?", text, re.M)
    skipped = re.findall(r"OK \(skipped=(\d+)\)", text)
    if ran and int(ran[-1]) == 0:
        return "ran 0 tests"
    if ran and skipped and int(skipped[-1]) >= int(ran[-1]):
        return f"all {ran[-1]} tests skipped (a tool or browser is missing)"
    if re.search(r"^\W*tests 0\s*$", text, re.M):
        return "ran 0 tests"
    return ""


def run(full: bool = False) -> list[dict]:
    results = []
    for name, cmd, env, why in steps(full):
        if cmd is None:
            results.append({"step": name, "status": "SKIPPED", "seconds": 0, "detail": why})
            print(f"SKIPPED  {name}: {why}", flush=True)
            continue
        t = time.time()
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=os.environ | env)
        tail = [l for l in (p.stdout + "\n" + p.stderr).strip().splitlines() if l.strip()][-6:]
        ok = p.returncode == 0
        if ok and (why := nothing_ran(p.stdout + "\n" + p.stderr)):  # exit 0 but nothing tested: never a pass
            results.append({"step": name, "status": "SKIPPED", "seconds": round(time.time() - t, 1), "detail": why})
            print(f"SKIPPED  {name}: {why}", flush=True)
            continue
        results.append({"step": name, "status": "PASS" if ok else "FAIL", "seconds": round(time.time() - t, 1),
                        "detail": " | ".join(tail[-2:] if ok else tail)})
        print(f"{'PASS' if ok else 'FAIL'}     {name} ({results[-1]['seconds']} s)" + ("" if ok else "\n    " + "\n    ".join(tail)),
              flush=True)
    return results


def _git(*args) -> bytes:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return p.stdout if p.returncode == 0 else b""


def fingerprint() -> str:
    """Hash of the tree beyond HEAD (tracked changes + untracked, not-ignored files). The Stop hook
    ~/.claude/hooks/engineering-loop-gate.py computes the same value and lets Claude finish only when it matches the
    last passing run's: keep the two identical."""
    import hashlib

    h = hashlib.sha256(_git("diff", "HEAD", "--binary", "--no-ext-diff", "--no-color"))
    for rel in sorted(p for p in _git("ls-files", "-o", "--exclude-standard", "-z").decode("utf-8", "replace").split("\0") if p):
        h.update(rel.encode() + b"\0")
        try:
            h.update((ROOT / rel).read_bytes())
        except OSError:
            pass
    return h.hexdigest()


def record(fp: str, results: list[dict]) -> str:
    """Write .verify/last.json for the gate: passed only when every step passed (a SKIPPED step is not a pass) on a
    tree the run did not change under it."""
    failed = any(r["status"] != "PASS" for r in results)
    moved = fingerprint() != fp
    (ROOT / ".verify").mkdir(exist_ok=True)
    (ROOT / ".verify" / "last.json").write_text(json.dumps({
        "fingerprint": fp, "passed": not failed and not moved, "tree_changed_during_run": moved,
        "skipped": [r["step"] for r in results if r["status"] == "SKIPPED"], "at": time.strftime("%Y-%m-%dT%H:%M:%S")}),
        encoding="utf-8")
    return "the tree changed while verify ran: run it again" if moved else ""


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # a Windows console cannot print every character a tool writes
    except (AttributeError, ValueError):
        pass
    fp = fingerprint()
    results = run("--full" in argv)
    if note := record(fp, results):
        print(f"\nverify: {note}")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(results, indent=1), encoding="utf-8")
    failed = [r["step"] for r in results if r["status"] == "FAIL"]
    skipped = [r["step"] for r in results if r["status"] == "SKIPPED"]
    print(f"\nverify: {len(results) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped"
          + (f" (failed: {', '.join(failed)})" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
