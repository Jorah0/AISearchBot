"""Self-update (pass 16.4). A git install (install.ps1 / editable checkout) follows its configured origin, fast-forward
only: check() fetches and shows the commit range and the CHANGELOG excerpt between the versions; apply() refuses a
dirty tree, local commits (HEAD ahead of or diverged from the origin) and a mail scan / send / background action in
flight, takes a data backup, fast-forwards, reinstalls only when pyproject.toml changed, then runs the offline unit
suite and `lodestar doctor` on the new code in subprocesses. Any failure resets the install to the exact previous
commit (the only `git reset --hard` in Lodestar, run on a tree it saw clean). The -Exe build cannot replace itself:
it reads a version manifest and only links to the download. Every check and update goes to the update log
(HOME/update-log.jsonl), shown by `lodestar update log` and `lodestar doctor`. The monitor loop calls tick()."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__, db, settings
from .config import HOME

ROOT = Path(__file__).resolve().parent.parent  # the install: a git checkout for install.ps1 / editable installs
LOG = HOME / "update-log.jsonl"
BOOT = time.time()  # an update applied after this needs a restart (loop.py imports this module at start)
GATE_TIMEOUT = 1800  # the unit suite takes about a minute; a hung test must not hold the update lock forever
REF = "refs/lodestar/update"  # the fetched target lives in a private ref: the user's branches and tags are untouched


def kind(repo: Path = ROOT) -> str:
    """exe (PyInstaller build: notify only) | git (can update itself) | none (a plain site-packages install)."""
    if getattr(sys, "frozen", False):
        return "exe"
    return "git" if (Path(repo) / ".git").exists() else "none"


def scrub(text) -> str:
    """https://user:token@host -> https://***@host: an origin URL may carry a credential; never print or log it."""
    return re.sub(r"(://)[^/@\s]+@", r"\1***@", str(text))


def _git(repo: Path, *args, timeout: int = 120) -> str:
    # a private origin fails at once instead of waiting for a password (terminal or Git Credential Manager window)
    env = os.environ | {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise SystemExit("git is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        raise SystemExit(f"git {args[0]} took longer than {timeout} s") from None
    if r.returncode:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise SystemExit(scrub(f"git {args[0]}: {msg[-1] if msg else f'exit code {r.returncode}'}"))
    return r.stdout.strip()


def allowed_origin(url: str) -> str:
    """The origin, if updates may come from it: an https:// URL or a local folder (tests, a mirror on disk)."""
    u = str(url or "").strip()
    if u.lower().startswith("https://") or ("://" not in u and "@" not in u and u and Path(u).is_dir()):
        return u
    raise SystemExit(f"updates come only from an https:// origin or a local folder, not {scrub(u)[:120] or '(none)'}")


def origin(repo: Path = ROOT) -> str:
    """update_origin, else the checkout's own `origin` remote."""
    url = settings.pref("update_origin") or ""
    if not url:
        try:
            url = _git(repo, "config", "--get", "remote.origin.url")
        except SystemExit:
            raise SystemExit("this install has no origin remote; set update_origin (Tools > Preferences)") from None
    return allowed_origin(url)


def _changelog(repo: Path, cur: str, target: str) -> str:
    """The CHANGELOG sections the target adds: its text up to the first heading the current version already has."""
    def read(rev):
        try:
            return _git(repo, "show", f"{rev}:docs/CHANGELOG.md")
        except SystemExit:
            return ""
    old = {ln for ln in read(cur).splitlines() if ln.startswith("## ")}
    out, started = [], False
    for ln in read(target).splitlines():
        if ln.startswith("## "):
            if ln in old:
                break
            started = True
        if started:
            out.append(ln)
    return "\n".join(out).strip()[:8000]


def busy() -> str | None:
    """Why an update must wait: a mail scan (util.run_lock files), an Inbox send claimed and running, or a background
    action of this process (web TASKS). None when nothing is in flight."""
    for lock in HOME.glob(".*.lock"):
        name = lock.stem.lstrip(".")
        try:
            fresh = time.time() - lock.stat().st_mtime < 1800  # run_lock's own stale limit
        except FileNotFoundError:
            continue
        if fresh and name != "update":
            return f"another {name} run is in progress"
    if db.list_pending("running"):
        return "an Inbox action is being sent"
    web = sys.modules.get("lodestar.web")
    if web and any(t.get("status") == "running" and not str(t.get("action", "")).startswith("update")
                   for t in list(web.TASKS.values())):  # the UI's own update task is not in the way
        return "a background action is running"
    return None


def _blocked(repo: Path, target: str) -> str | None:
    if _git(repo, "status", "--porcelain"):
        return "the install folder has uncommitted changes"
    ahead = int(_git(repo, "rev-list", "--count", f"{target}..HEAD"))
    if ahead:
        return f"this install has {ahead} commit(s) the origin does not (fast-forward only)"
    return busy()


def _manifest() -> dict:
    """-Exe build: {version, url, notes} from update_manifest_url; never downloads or replaces anything."""
    from . import util

    url = settings.pref("update_manifest_url") or ""
    if not url.lower().startswith("https://"):
        raise SystemExit("no https update_manifest_url set (Tools > Preferences)")
    m = util.fetch_json(url, timeout=20, max_bytes=100_000)
    ver = str(m.get("version") or "")
    if not re.fullmatch(r"\d+(\.\d+)*", ver):
        raise SystemExit("the update manifest has no version")
    dl = str(m.get("url") or "")
    return {"version": ver, "url": dl if dl.lower().startswith("https://") else "", "notes": str(m.get("notes") or "")[:4000]}


def _newer(a: str, b: str) -> bool:
    return tuple(map(int, a.split("."))) > tuple(map(int, b.split(".")))


def check(repo: Path = ROOT, record: bool = True) -> dict:
    """What an update would bring. Never raises: a network or git problem is result 'could not check: ...'."""
    repo = Path(repo)
    k = kind(repo)
    out = {"kind": k, "current": "", "target": "", "behind": 0, "ahead": 0, "commits": [], "changelog": "",
           "available": False, "blocked": None, "origin": "", "result": ""}
    try:
        if k == "exe":
            m = _manifest()
            out.update(current=__version__, target=m["version"], changelog=m["notes"], url=m["url"],
                       available=_newer(m["version"], __version__))
            out["result"] = (f"update available: {__version__} -> {m['version']} (download: {m['url'] or 'see the project page'})"
                             if out["available"] else f"up to date ({__version__})")
        elif k == "none":
            out["result"] = "not a git install: reinstall with install.ps1 / install.sh to get updates"
        else:
            url = origin(repo)
            out["origin"] = scrub(url)
            branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            if branch == "HEAD":
                raise SystemExit("the install is not on a branch")
            channel = settings.pref("update_channel")
            specs = [f"+refs/heads/{branch}:{REF}"] + (["+refs/tags/v*:refs/lodestar/tags/v*"] if channel == "releases" else [])
            _git(repo, "fetch", "--no-tags", "--quiet", url, *specs, timeout=180)
            target = _git(repo, "rev-parse", REF)
            if channel == "releases":  # newest version tag on the origin; none yet: nothing to update to
                tags = _git(repo, "for-each-ref", "--sort=-v:refname", "--format=%(objectname)", "refs/lodestar/tags/")
                tagged = [t for t in tags.splitlines() if t]
                target = _git(repo, "rev-parse", tagged[0] + "^{commit}") if tagged else _git(repo, "rev-parse", "HEAD")
            cur = _git(repo, "rev-parse", "HEAD")
            behind = int(_git(repo, "rev-list", "--count", f"HEAD..{target}"))
            ahead = int(_git(repo, "rev-list", "--count", f"{target}..HEAD"))
            out.update(current=cur, target=target, behind=behind, ahead=ahead, available=bool(behind))
            if behind:
                out["commits"] = _git(repo, "log", "--format=%h %s", "-n", "50", f"HEAD..{target}").splitlines()
                out["changelog"] = _changelog(repo, cur, target)
                out["blocked"] = _blocked(repo, target)
                out["result"] = f"update available: {behind} commit(s) {cur[:7]}..{target[:7]}"
            else:
                out["result"] = "up to date" + (f" ({ahead} local commit(s) not on the origin)" if ahead else "")
    except (Exception, SystemExit) as e:  # offline, origin gone, git missing: the app goes on, the log says so
        out["result"] = f"could not check: {scrub(e)[:300]}"
    if record:
        _log("check", out["current"], out["target"], out["result"])
    return out


def _run(cmd: list, cwd: Path, timeout: int, env: dict | None = None) -> str:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise SystemExit(f"{' '.join(map(str, cmd[1:4]))} took longer than {timeout} s") from None
    if r.returncode:
        tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise SystemExit(f"{' '.join(map(str, cmd[1:4]))} failed: {' | '.join(tail)[:400]}")
    return r.stdout


def _pip(repo: Path) -> None:
    """pyproject.toml changed: reinstall the checkout in this interpreter (dependencies and the lodestar command)."""
    _run([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(repo)], repo, 900)


def _gate(repo: Path) -> None:
    """The new code must pass its own offline unit suite (on a throwaway data folder, never yours) and `lodestar
    doctor` must run to its verdict. Raises SystemExit with the failure."""
    env = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}  # no __pycache__ left behind to make the tree look dirty
    if (repo / "tests").is_dir():
        with tempfile.TemporaryDirectory(prefix="lodestar-update-gate-", ignore_cleanup_errors=True) as home:
            _run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], repo, GATE_TIMEOUT,
                 env | {"LODESTAR_HOME": home})
    r = subprocess.run([sys.executable, "-m", "lodestar", "doctor"], cwd=str(repo), capture_output=True, text=True,
                       timeout=300, env=env, encoding="utf-8", errors="replace")
    last = (r.stdout.strip().splitlines() or [""])[-1]
    if last not in ("all good", "usable; see WARN lines", "something is broken; see FAIL lines"):  # it crashed
        raise SystemExit(f"lodestar doctor did not finish: {(r.stderr.strip().splitlines() or [last])[-1][:300]}")


def _pin_modules() -> None:
    """Import every lodestar module now, so this running process keeps the code it started with: a lazy import after
    the fast-forward would otherwise mix new files into old ones until the restart."""
    import importlib
    import pkgutil

    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if m.name.startswith("_"):  # __main__ would run the CLI
            continue
        try:
            importlib.import_module(f"lodestar.{m.name}")
        except (Exception, SystemExit):  # optional extras (webview) may be missing; nothing to pin then
            pass


def apply(repo: Path = ROOT, plan: dict | None = None) -> dict:
    """Update the git install to plan['target'] (a fresh check() when none). Returns {ok, result, from, to, backup?}."""
    from .extras import backup
    from .util import run_lock

    repo = Path(repo)
    with run_lock("update", stale=GATE_TIMEOUT + 1200):
        p = plan or check(repo, record=False)
        cur, target = p.get("current", ""), p.get("target", "")
        if p["kind"] != "git":
            return _done(False, cur, target, "refused: " + (p["result"] if p["kind"] == "none" else
                         "the standalone build cannot update itself; download the new version"))
        if not p["available"]:
            return _done(False, cur, target, p["result"])
        head = _git(repo, "rev-parse", "HEAD")
        why = _blocked(repo, target) if head == cur else "the install moved since the check; check again"
        if why:
            return _done(False, cur, target, f"refused: {why}")
        try:
            saved = backup()  # the data folder, before any new code touches it (migrations are additive)
        except (Exception, SystemExit) as e:
            return _done(False, cur, target, f"refused: the backup failed: {e}")
        _pin_modules()
        try:
            _git(repo, "merge", "--ff-only", "--quiet", target)
        except SystemExit as e:  # git refused before changing anything (an untracked file in the way)
            return _done(False, cur, target, f"failed: {e}", backup=str(saved))
        piped = False
        try:
            if _git(repo, "diff", "--name-only", cur, target, "--", "pyproject.toml"):
                piped = True
                _pip(repo)
            _gate(repo)
        except (Exception, SystemExit) as e:
            _git(repo, "reset", "--hard", cur)  # tree was clean (checked above): this restores exactly the old commit
            if piped:
                try:
                    _pip(repo)  # the old dependency set and command back
                except (Exception, SystemExit) as e2:
                    e = f"{e}; reinstalling the previous version also failed: {e2}"
            return _done(False, cur, target, f"failed, rolled back to {cur[:7]}: {scrub(e)[:500]}", backup=str(saved))
        return _done(True, cur, target, f"updated {cur[:7]} -> {target[:7]}; restart Lodestar to use it", backup=str(saved))


def _done(ok: bool, frm: str, to: str, result: str, **kw) -> dict:
    _log("apply", frm, to, result, ok=ok)
    return {"ok": ok, "result": result, "from": frm, "to": to, **kw}


def _log(kind_: str, frm: str, to: str, result: str, ok: bool | None = None) -> None:
    row = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "kind": kind_, "from": frm[:12], "to": to[:12],
           "result": scrub(result)[:600]} | ({} if ok is None else {"ok": ok})
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines() if LOG.is_file() else []
        tmp = LOG.with_name(LOG.name + ".tmp")
        tmp.write_text("\n".join([*lines[-499:], json.dumps(row)]) + "\n", encoding="utf-8")  # the last 500 entries
        os.replace(tmp, LOG)
    except OSError:
        pass  # a log write must never break an update


def entries(limit: int = 50) -> list[dict]:
    """The update log, newest first."""
    out = []
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines() if LOG.is_file() else []
    except OSError:
        lines = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def status(repo: Path = ROOT) -> dict:
    """No network: install kind, preferences, the last check and update, and whether a restart is needed."""
    log = entries(500)
    last_apply = next((e for e in log if e["kind"] == "apply"), None)
    boot = datetime.fromtimestamp(BOOT).strftime("%Y-%m-%d %H:%M:%S")
    return {"kind": kind(repo), "version": __version__, "mode": settings.pref("update_mode"),
            "every_hours": settings.pref("update_every_hours"), "channel": settings.pref("update_channel"),
            "last_check": next((e for e in log if e["kind"] == "check"), None), "last_update": last_apply,
            "restart_needed": any(e["kind"] == "apply" and e.get("ok") and e["at"] >= boot for e in log)}


def due(now: datetime | None = None) -> bool:
    last = next((e for e in entries(500) if e["kind"] == "check"), None)
    if not last:
        return True
    hours = int(settings.pref("update_every_hours") or 24)
    return datetime.strptime(last["at"], "%Y-%m-%d %H:%M:%S") + timedelta(hours=hours) <= (now or datetime.now())


def tick(repo: Path = ROOT, now: datetime | None = None) -> dict | None:
    """The monitor loop's step: off | notify (one alert per new target) | auto (apply when nothing blocks it; the
    -Exe build only ever notifies). Returns the check, or None when not due."""
    from .util import notify

    mode = settings.pref("update_mode")
    if mode == "off" or not due(now):
        return None
    p = check(repo)
    if not p["available"]:
        return p
    if mode == "auto" and p["kind"] == "git" and not p["blocked"]:
        r = apply(repo, p)
        notify(f"UPDATE {r['result']}")
        return p | {"applied": r}
    key = f"update:{p['target']}"
    if not db.seen(key):
        how = ("download it" if p["kind"] == "exe" else
               f"not applied automatically: {p['blocked']}" if p["blocked"] else "lodestar update apply")
        notify(f"UPDATE available: {p['result'].removeprefix('update available: ')} ({how})")
        db.mark_seen(key)
    return p


def doctor_rows(repo: Path = ROOT) -> list[tuple[str, str, str]]:
    s = status(repo)
    desc = {"git": "git install", "exe": "standalone build (notify only)", "none": "not a git install"}[s["kind"]]
    rows = [("ok" if s["kind"] != "none" else "warn", "updates",
             f"{desc}, {__version__}; mode {s['mode']}, every {s['every_hours']} h, channel {s['channel']}")]
    if c := s["last_check"]:
        rows.append(("warn" if c["result"].startswith("could not") else "ok", "update check", f"{c['at']}: {c['result']}"))
    if u := s["last_update"]:
        rows.append(("ok" if u.get("ok") else "warn", "last update", f"{u['at']}: {u['result']}"))
    if s["restart_needed"]:
        rows.append(("warn", "restart", "an update was applied: restart Lodestar to run the new code"))
    return rows
