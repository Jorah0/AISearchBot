"""Golden-task evaluations for Claude-based development on this repository (engineering loop, P3).

Each task in evals/dataset/*.json runs in a throwaway copy of the repo (tracked + untracked files, never ignored ones such
as .env, and never evals/ or this runner: the agent must not see answers or hidden tests), optionally after a `setup`
that plants a defect or hostile text. An agent (Claude Code, headless) works on the `prompt`; then `hidden_tests` are
copied in, the `checks` run, and `forbidden` rules (paths that must not change, text that must not be added) are
applied against the setup commit, so committing, renaming or writing ignored files cannot hide a change. A task
passes when every check passes and nothing forbidden happened. Results: evals/reports/<time>.jsonl, compared with
evals/baseline.json.

  python scripts/eval.py list
  python scripts/eval.py validate [--task ID]        the task itself is sound: fails as planted, passes with the reference
  python scripts/eval.py run [--task ID] [--split dev|heldout] [--model sonnet] [--repeat N] [--save-baseline]
  python scripts/eval.py run --agent none            plumbing only: no agent, so every planted-defect task fails
  python scripts/eval.py run --allow-tests ...       the agent may also run the repo's tests itself (see below)

Isolation. The agent runs `claude -p --restricted --strict-mcp-config` in the copy: no Bash or other code-running tool,
file tools confined to the copy, your user / project / local settings ignored (so none of your hooks, plugins or
permission rules apply), no MCP servers, bypassPermissions refused, and none of your API keys, tokens or passwords in
its environment. The checks run with a temp HOME / USERPROFILE and LODESTAR_HOME and a null keyring.
--allow-tests adds Bash for `<repo python> -m unittest` only. That is NOT a sandbox: a test file the agent writes runs
as you, with your files, keyring and network. Use it only on tasks you wrote, or inside a container / separate account.
A real run spends Claude Code usage: run it after changing CLAUDE.md, rules, skills, agents or the model."""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, REPORTS, BASELINE = ROOT / "evals" / "dataset", ROOT / "evals" / "reports", ROOT / "evals" / "baseline.json"
VENV = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = str(VENV) if VENV.is_file() else sys.executable
HIDDEN = ("evals/", "scripts/eval.py")  # never in the agent's copy: tasks hold the answers and hidden tests
NOISE = re.compile(r"(^|/)(__pycache__/|\.pytest_cache/)|\.py[co]$")  # written by running Python, not by the agent
SECRET_ENV = re.compile(r"(_API_KEY|_TOKEN|_SECRET|SECRET_|PASSWORD|_PASS$|^AWS_|CREDENTIAL)", re.I)


def tasks(only: str | None = None, split: str | None = None) -> list[dict]:
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DATA.glob("*.json"))]
    return [t for t in out if (not only or t["id"] == only) and (not split or t.get("split") == split)]


def _git(cwd, *a) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _commit(d: Path, msg: str) -> str:
    _git(d, "add", "-A")
    _git(d, "-c", "user.email=eval@local", "-c", "user.name=eval", "commit", "-qm", msg, "--allow-empty")
    return _git(d, "rev-parse", "HEAD").strip()


def _rmtree(path) -> None:
    """Remove a temp copy, read-only git objects included (Windows refuses those to plain rmtree)."""
    def again(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if path and Path(path).exists():
        shutil.rmtree(path, onerror=again)


def snapshot() -> Path:
    """A copy of the working tree (no ignored files: no .env, no data; never evals/ or this runner) as its own repo."""
    d = Path(tempfile.mkdtemp(prefix="lodestar-eval-"))
    for rel in _git(ROOT, "ls-files", "-co", "--exclude-standard", "-z").split("\0"):
        src = ROOT / rel
        if rel and src.is_file() and not rel.replace("\\", "/").startswith(HIDDEN):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, d / rel)
    _git(d, "init", "-q")
    _commit(d, "base")
    return d


def _replace(d: Path, edits: list[dict]) -> None:
    for e in edits or []:
        p = d / e["file"]
        if "create" in e:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(e["create"], encoding="utf-8")
            continue
        s = p.read_text(encoding="utf-8")
        if e["old"] not in s:
            raise SystemExit(f"{e['file']}: the text to replace is not there (the task is out of date with the code)")
        p.write_text(s.replace(e["old"], e["new"], 1), encoding="utf-8")


def _env(home: Path, isolate_home: bool = False) -> dict:
    """Your environment minus every key, token, secret and password; Lodestar pointed at a temp home and a null keyring.
    isolate_home: also HOME / USERPROFILE (the checks; not the agent, whose Claude Code sign-in lives in your profile)."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k) and k != "LODESTAR_HOME"}
    env |= {"LODESTAR_HOME": str(home / "lodestar"), "LODESTAR_VAULT_SERVICE": "", "LODESTAR_NO_STARTUP_CHECK": "1",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring", "PYTHONIOENCODING": "utf-8"}
    if isolate_home:
        env |= {"HOME": str(home), "USERPROFILE": str(home)}
    return env


def changed(d: Path, base: str) -> list[str]:
    """Every path that differs from the setup commit: edits, deletions, renames (both names), later commits by the
    agent, and new files, ignored ones included. Python's own caches are left out."""
    diff = _git(d, "diff", "--name-only", "--no-renames", "-z", base).split("\0")
    new = _git(d, "ls-files", "-o", "-z").split("\0")  # every untracked file, ignored ones too
    return sorted({p for p in diff + new if p and not NOISE.search(p)})


def forbidden(d: Path, t: dict, base: str) -> list[str]:
    f = t.get("forbidden") or {}
    paths = changed(d, base)
    hit = lambda p, rules: any(p == r or p.startswith(r.rstrip("/") + "/") for r in rules)  # noqa: E731
    out = [f"changed {p}" for p in paths if hit(p, f.get("unchanged", []))]
    if f.get("only_change"):
        out += [f"changed {p} (outside {', '.join(f['only_change'])})" for p in paths if not hit(p, f["only_change"])]
    added = "\n".join(l[1:] for l in _git(d, "diff", "-U0", "--no-renames", base).splitlines()
                      if l.startswith("+") and not l.startswith("+++"))
    for p in _git(d, "ls-files", "-o", "-z").split("\0"):  # new files: their whole text counts as added
        if p and not NOISE.search(p) and (d / p).is_file():
            added += "\n" + (d / p).read_text(encoding="utf-8", errors="replace")
    out += [f"added forbidden text: {x}" for x in f.get("added_text", []) if x.lower() in added.lower()]
    return out


def checks(d: Path, t: dict) -> list[dict]:
    for rel, body in (t.get("hidden_tests") or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(body, encoding="utf-8")
    home = Path(tempfile.mkdtemp(prefix="lodestar-eval-home-"))
    out = []
    try:
        for cmd in t["checks"]:
            argv = [PY if a == "{python}" else a for a in cmd]
            try:
                p = subprocess.run(argv, cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   env=_env(home, isolate_home=True), timeout=600)
                tail = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()][-3:]
                out.append({"cmd": " ".join(cmd), "ok": p.returncode == 0, "tail": " | ".join(tail)})
            except subprocess.TimeoutExpired:
                out.append({"cmd": " ".join(cmd), "ok": False, "tail": "timed out after 600 s"})
    finally:
        _rmtree(home)
    return out


def agent_cmd(t: dict, model: str | None, allow_tests: bool) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("Claude Code (claude) is not on PATH: install it, or run with --agent none / reference")
    py = PY.replace("\\", "/")
    tools = ["Read", "Edit", "Write", "Glob", "Grep"] + (["Bash"] if allow_tests else [])
    cmd = [exe, "-p", t["prompt"], "--output-format", "json", "--max-turns", str(t.get("max_turns", 30)),
           "--restricted", "--strict-mcp-config", "--tools", ",".join(tools), "--permission-mode", "acceptEdits",
           "--append-system-prompt", "You work in a disposable copy of the repository. "
           + (f"You may run the tests with: {py} -m unittest <module>." if allow_tests else
              "You cannot run commands here; reason from the code and the existing tests, and say what you could not run.")]
    if allow_tests:
        cmd += ["--allowedTools", f"Bash({py} -m unittest:*)"]
    if model:
        cmd += ["--model", model]
    return cmd


def agent(d: Path, t: dict, kind: str, model: str | None, allow_tests: bool = False) -> dict:
    if kind == "none":
        return {"ran": False}
    if kind == "reference":
        _replace(d, t.get("reference"))
        return {"ran": "reference"}
    home = Path(tempfile.mkdtemp(prefix="lodestar-eval-home-"))
    t0 = time.time()
    try:
        p = subprocess.run(agent_cmd(t, model, allow_tests), cwd=d, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=_env(home), timeout=t.get("timeout", 1200))
        meta = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {}
    except subprocess.TimeoutExpired:
        return {"ran": True, "timeout": True, "seconds": round(time.time() - t0)}
    finally:
        _rmtree(home)
    return {"ran": True, "seconds": round(time.time() - t0), "turns": meta.get("num_turns"),
            "cost_usd": meta.get("total_cost_usd"), "is_error": meta.get("is_error"),
            "result": str(meta.get("result") or p.stderr)[-400:]}


def run_task(t: dict, kind: str, model: str | None, allow_tests: bool = False, keep: bool = False) -> dict:
    d = snapshot()
    try:
        _replace(d, t.get("setup"))
        base = _commit(d, "setup")
        a = agent(d, t, kind, model, allow_tests)
        bad = forbidden(d, t, base)
        res = checks(d, t)
        ok = all(c["ok"] for c in res) and not bad
        return {"id": t["id"], "category": t["category"], "split": t.get("split"), "passed": ok, "agent": a,
                "checks": res, "forbidden": bad, "model": model or "default", "tests_allowed": allow_tests,
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    finally:
        if not keep:
            _rmtree(d)


def cmd_validate(only):
    bad = 0
    for t in tasks(only):
        base = run_task(t, "none", None)
        ref = run_task(t, "reference", None)
        sound = not base["passed"] and ref["passed"]
        bad += not sound
        print(f"{'OK  ' if sound else 'BAD '} {t['id']}: planted -> {'pass' if base['passed'] else 'fail'}, "
              f"reference -> {'pass' if ref['passed'] else 'fail'}" + ("" if sound else f"  {ref['checks']} {ref['forbidden']}"))
    return 1 if bad else 0


def cmd_run(only, split, kind, model, repeat, save, allow_tests):
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rows = []
    for t in tasks(only, split):
        for i in range(repeat):
            r = run_task(t, kind, model, allow_tests) | {"repeat": i}
            rows.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'} {t['id']} [{t['category']}] "
                  f"{r['agent'].get('seconds', 0)} s, turns {r['agent'].get('turns')}, ${r['agent'].get('cost_usd')}"
                  + ("" if r["passed"] else f"\n    checks: {[c['tail'] for c in r['checks'] if not c['ok']]}  forbidden: {r['forbidden']}"),
                  flush=True)
    (REPORTS / f"{stamp}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    rate = {tid: sum(r["passed"] for r in rows if r["id"] == tid) / max(1, sum(r["id"] == tid for r in rows))
            for tid in dict.fromkeys(r["id"] for r in rows)}
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    worse = [f"{k}: {base['rates'][k]:.0%} -> {v:.0%}" for k, v in rate.items() if k in base.get("rates", {}) and v < base["rates"][k]]
    total = sum(r["passed"] for r in rows) / max(1, len(rows))
    print(f"\npass rate {total:.0%} ({sum(r['passed'] for r in rows)} of {len(rows)}); report evals/reports/{stamp}.jsonl"
          + (f"\nREGRESSED vs baseline: {'; '.join(worse)}" if worse else "\nno regression against the baseline" if base else ""))
    if save:
        BASELINE.write_text(json.dumps({"at": stamp, "model": model or "default", "tests_allowed": allow_tests, "rates": rate},
                                       indent=1), encoding="utf-8")
        print("baseline saved")
    return 1 if worse else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("list", "validate", "run"))
    ap.add_argument("--task")
    ap.add_argument("--split", choices=("dev", "heldout"))
    ap.add_argument("--agent", default="claude", choices=("claude", "none", "reference"))
    ap.add_argument("--model")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--allow-tests", action="store_true", help="the agent may run <repo python> -m unittest (not a sandbox)")
    a = ap.parse_args(argv)
    if a.action == "list":
        for t in tasks():
            print(f"{t['id']:<28} {t['category']:<18} {t.get('split', ''):<8} {t['title']}")
        return 0
    if a.action == "validate":
        return cmd_validate(a.task)
    return cmd_run(a.task, a.split, a.agent, a.model, a.repeat, a.save_baseline, a.allow_tests)


if __name__ == "__main__":
    sys.exit(main())
