"""Self-update (pass 16.4). A git install (install.ps1 / editable checkout) follows its configured origin, fast-forward
only: check() fetches and shows the commit range and the CHANGELOG excerpt between the versions; apply() refuses a
dirty tree, local commits (HEAD ahead of or diverged from the origin) and a mail scan / send / background action in
flight, takes a data backup, fast-forwards, reinstalls only when pyproject.toml changed, then runs the offline unit
suite and `lodestar doctor` on the new code in subprocesses. Any failure resets the install to the exact previous
commit (the only `git reset --hard` in Lodestar, run on a tree it saw clean). The -Exe build cannot replace itself:
it reads a version manifest and only links to the download. Every check and update goes to the update log
(HOME/update-log.jsonl), shown by `lodestar update log` and `lodestar doctor`. The monitor loop calls tick().
An update in progress is journalled (HOME/update-state.json): one cut off mid-way (killed, power loss, Restart) is rolled
back by recover() at the next start. Every long-running Lodestar process registers itself (HOME/procs); apply() waits
while another one lives, since that process would otherwise run a mix of old and new files."""
import atexit
import json
import os
import re
import signal
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
STATE = HOME / "update-state.json"  # {repo, from, to, backup, pid, started} from the fast-forward until the outcome
PROCS = HOME / "procs"  # <pid>.pid per running app / desktop / loop process (register())
LOCK = HOME / ".update.lock"  # util.run_lock("update")
RETRIES, RETRY_WAIT = 3, 2  # a rollback is retried: a file held open by an antivirus scan or an indexer fails one try


def _alive(pid: int, since: float | None = None) -> bool:
    """pid is a running process (and, with `since`, one that started by then: a reused pid is not the old holder)."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":  # os.kill(pid, 0) would TerminateProcess on Windows
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype, k.OpenProcess.argtypes = wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return False
            t = [wintypes.FILETIME() for _ in range(4)]
            if since is not None and k.GetProcessTimes(h, *map(ctypes.byref, t)):
                created = ((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime) / 1e7 - 11644473600
                return created <= since + 2
            return True
        finally:
            k.CloseHandle(h)
    try:  # ponytail: no start-time check off Windows; a reused pid reads as alive until it ends
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def register() -> None:
    """This process runs Lodestar for a while (the app, the desktop window, the loop). An update applied by another
    process would change the files under it, so apply() waits while it lives (_others)."""
    try:
        PROCS.mkdir(exist_ok=True)
        (PROCS / f"{os.getpid()}.pid").write_text(f"{time.time():.0f}", encoding="utf-8")
    except OSError:
        return
    atexit.register(unregister)


def unregister() -> None:
    (PROCS / f"{os.getpid()}.pid").unlink(missing_ok=True)


def _others() -> str | None:
    for f in PROCS.glob("*.pid") if PROCS.is_dir() else ():
        try:
            pid, since = int(f.stem), float(f.read_text(encoding="utf-8") or 0)
        except (ValueError, OSError):
            continue
        if pid == os.getpid():
            continue
        if _alive(pid, since):
            return (f"another Lodestar process is running (pid {pid}: the app, the desktop window or the loop); "
                    "update from that window, or close it first")
        f.unlink(missing_ok=True)  # ended without unregistering (killed, os._exit)
    return None


def startup() -> None:
    """The app, the desktop window and the loop call this as they start: finish an interrupted update (recover), then
    register. Never stops the start."""
    try:
        recover()
    except (Exception, SystemExit) as e:
        _log("apply", "", "", f"failed: could not finish an interrupted update: {scrub(e)[:300]}", ok=False)
    register()


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


def updating() -> str | None:
    """An update in flight: a live update lock (any process) or one of this process's update tasks (web TASKS)."""
    try:
        if time.time() - LOCK.stat().st_mtime < GATE_TIMEOUT + 1200:
            pid = LOCK.read_text(encoding="utf-8").strip()
            if not pid.isdigit() or _alive(int(pid), LOCK.stat().st_mtime):
                return "an update is running"
    except OSError:
        pass
    web = sys.modules.get("lodestar.web")
    if web and any(t.get("status") == "running" and str(t.get("action", "")).startswith("update")
                   for t in list(web.TASKS.values())):
        return "an update is running"
    return None


def busy(include_update: bool = False) -> str | None:
    """Why an update (or, with include_update, a Restart) must wait: a mail scan (util.run_lock files), an Inbox send
    claimed and running, or a background action of this process (web TASKS). apply() leaves include_update off: it
    holds the update lock itself. None when nothing is in flight."""
    if include_update and (why := updating()):
        return why
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
    return busy() or _others()


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
            # --prune: a release tag the origin deleted (a pulled release) goes from refs/lodestar/tags too
            _git(repo, "fetch", "--no-tags", "--prune", "--quiet", url, *specs, timeout=180)
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


def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=60)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
        p.wait(10)
    except (OSError, subprocess.SubprocessError):
        pass


def _proc(cmd: list, cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). Output goes to temp files, not pipes, so a helper process a test leaves running
    cannot hold the wait open; on a timeout the whole process tree is killed."""
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, **group)
        try:
            code = p.wait(timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            raise SystemExit(f"{' '.join(map(str, cmd[1:4]))} took longer than {timeout} s") from None
        out.seek(0)
        err.seek(0)
        return code, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def _run(cmd: list, cwd: Path, timeout: int, env: dict | None = None) -> str:
    code, out, err = _proc(cmd, cwd, timeout, env)
    if code:
        lines = (err or out).strip().splitlines()
        failed = [ln.strip() for ln in lines if ln.startswith(("FAIL: ", "ERROR: "))]  # unittest names the tests
        names = ", ".join(failed[:5]) + (f" and {len(failed) - 5} more" if len(failed) > 5 else "") + " | " if failed else ""
        raise SystemExit(f"{' '.join(map(str, cmd[1:4]))} failed: {names}{' | '.join(lines[-3:])}"[:700])
    return out


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
    _, out, err = _proc([sys.executable, "-m", "lodestar", "doctor"], repo, 300, env)
    last = (out.strip().splitlines() or [""])[-1]
    if last not in ("all good", "usable; see WARN lines", "something is broken; see FAIL lines"):  # it crashed
        raise SystemExit(f"lodestar doctor did not finish: {(err.strip().splitlines() or [last])[-1][:300]}")


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


def _restore(repo: Path, cur: str, target: str) -> None:
    """Put the install back exactly on cur, whose tree was clean before the update: reset, then delete the files the
    target adds that a failed or half-done fast-forward left behind untracked (git can update part of the tree and
    then fail on a file it cannot unlink). Retried: a file held open by another program can fail one attempt."""
    added = set(filter(None, _git(repo, "diff", "-z", "--name-only", "--diff-filter=A", cur, target).split("\0")))
    for attempt in range(RETRIES):
        try:
            _git(repo, "reset", "--hard", "--quiet", cur)
            for f in filter(None, _git(repo, "ls-files", "-z", "--others", "--exclude-standard").split("\0")):
                if f in added:
                    (repo / f).unlink(missing_ok=True)
            return
        except (OSError, SystemExit) as e:
            if attempt == RETRIES - 1:
                raise SystemExit(str(e)) from None
            time.sleep(RETRY_WAIT)


def _rollback(repo: Path, cur: str, target: str, why, backup: str, repip: bool, restart: bool = False) -> dict:
    """The update failed after the tree may have changed: restore cur and log the outcome. A rollback that itself
    fails keeps STATE, so the next start tries again, and is logged as ROLLBACK FAILED (a doctor FAIL row)."""
    try:
        _restore(repo, cur, target)
    except (Exception, SystemExit) as e2:
        try:
            at = _git(repo, "rev-parse", "--short", "HEAD")
        except (Exception, SystemExit):
            at = "?"
        return _done(False, cur, target, f"failed, ROLLBACK FAILED at {at}: {scrub(why)[:250]}; {scrub(e2)[:150]}. "
                     f"Run: git -C \"{repo}\" reset --hard {cur}", backup=backup, restart=restart)
    if repip:
        try:
            _pip(repo)  # the old dependency set and command back
        except (Exception, SystemExit) as e2:
            why = f"{why}; reinstalling the previous version also failed: {e2}"
    STATE.unlink(missing_ok=True)
    return _done(False, cur, target, f"failed, rolled back to {cur[:7]}: {scrub(why)[:500]}", backup=backup,
                 restart=restart)


def apply(repo: Path = ROOT, plan: dict | None = None) -> dict:
    """Update the git install to plan['target'] (a fresh check() when none). Returns {ok, result, from, to, backup?}."""
    from .util import run_lock

    try:  # an earlier update cut off mid-way goes back first (and frees its dead holder's lock)
        recover()
    except (Exception, SystemExit):  # startup() logged why; a dirty or moved tree refuses this update below
        pass
    lock = run_lock("update", stale=GATE_TIMEOUT + 1200)
    try:
        lock.__enter__()
    except SystemExit as e:  # another update is running: logged, so the card, the log and doctor say why
        p = plan or {}
        return _done(False, p.get("current", ""), p.get("target", ""), f"refused: {e}")
    try:
        return _apply(Path(repo), plan)
    finally:
        lock.__exit__()


def _apply(repo: Path, plan: dict | None) -> dict:
    from .extras import backup

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
        saved = str(backup())  # the data folder, before any new code touches it (migrations are additive)
    except (Exception, SystemExit) as e:
        return _done(False, cur, target, f"refused: the backup failed: {e}")
    _pin_modules()
    try:  # the journal recover() reads if this process dies before the outcome
        STATE.write_text(json.dumps({"repo": str(repo), "from": cur, "to": target, "backup": saved,
                                     "pid": os.getpid(), "started": time.time()}), encoding="utf-8")
    except OSError as e:
        return _done(False, cur, target, f"refused: could not record the update in progress: {e}", backup=saved)
    piped = False
    try:
        _git(repo, "merge", "--ff-only", "--quiet", target)
        if _git(repo, "diff", "--name-only", cur, target, "--", "pyproject.toml"):
            piped = True
            _pip(repo)
        _gate(repo)
    except (Exception, SystemExit) as e:  # the tree was clean (checked above): the rollback restores exactly cur
        return _rollback(repo, cur, target, e, saved, piped)
    STATE.unlink(missing_ok=True)
    return _done(True, cur, target, f"updated {cur[:7]} -> {target[:7]}; restart Lodestar to use it", backup=saved)


def recover() -> str | None:
    """An update whose process died before its outcome (killed, power loss, Restart mid-gate) left STATE behind: put
    the install back on the commit it came from and log it. None when there was nothing to do (or the update is
    still running in a live process)."""
    from .util import run_lock

    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        repo, cur, target = Path(st["repo"]), str(st["from"]), str(st["to"])
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        STATE.unlink(missing_ok=True)  # unreadable: nothing to act on
        return None
    if _alive(int(st.get("pid") or 0), st.get("started")):
        return None
    try:  # the dead holder's lock: free it now, not after the stale limit (a live holder keeps it)
        pid = LOCK.read_text(encoding="utf-8").strip()
        if pid.isdigit() and not _alive(int(pid), LOCK.stat().st_mtime):
            LOCK.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        lock = run_lock("update", stale=GATE_TIMEOUT + 1200).__enter__()
    except SystemExit:
        return None
    try:
        head = _git(repo, "rev-parse", "HEAD")
        if head not in (cur, target):  # someone moved the install since: leave it as it is
            STATE.unlink(missing_ok=True)
            return _done(False, cur, target, f"failed: an interrupted update {cur[:7]} -> {target[:7]} was found, but "
                         f"the install is now at {head[:7]}; left as it is")["result"]
        why = "the update was interrupted (Lodestar was closed or stopped during it); restart Lodestar"
        repip = bool(_git(repo, "diff", "--name-only", cur, target, "--", "pyproject.toml"))
        # restart: this process may already have imported the new modules before the rollback
        return _rollback(repo, cur, target, why, str(st.get("backup") or ""), repip, restart=True)["result"]
    finally:
        lock.__exit__()


def _done(ok: bool, frm: str, to: str, result: str, restart: bool = False, **kw) -> dict:
    _log("apply", frm, to, result, ok=ok, **({"restart": True} if restart else {}))
    return {"ok": ok, "result": result, "from": frm, "to": to, **kw}


def _log(kind_: str, frm: str, to: str, result: str, ok: bool | None = None, **extra) -> None:
    row = {"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "kind": kind_, "from": frm[:12], "to": to[:12],
           "result": scrub(result)[:600]} | ({} if ok is None else {"ok": ok}) | extra
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
            "restart_needed": any(e["kind"] == "apply" and (e.get("ok") or e.get("restart")) and e["at"] >= boot
                                  for e in log),
            "updating": bool(updating())}


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

    try:  # whatever the mode: an interrupted update never stays on untested code
        recover()
    except (Exception, SystemExit):  # startup() logged why
        pass
    mode = settings.pref("update_mode")
    if mode == "off" or not due(now):
        return None
    p = check(repo)
    if not p["available"]:
        return p
    failed = f"update-failed:{p['target']}"  # auto mode tries a version once: no backup + test run every interval
    if mode == "auto" and p["kind"] == "git" and not p["blocked"] and not db.seen(failed):
        r = apply(repo, p)
        if r["result"].startswith("failed"):
            db.mark_seen(failed)
            db.mark_seen(f"update:{p['target']}")  # this alert already says what to do
            notify(f"UPDATE {r['result']} (not retried automatically; run lodestar update apply to try again)")
        else:
            notify(f"UPDATE {r['result']}")
        return p | {"applied": r}
    key = f"update:{p['target']}"
    if not db.seen(key):
        how = ("download it" if p["kind"] == "exe" else
               f"not applied automatically: {p['blocked']}" if p["blocked"] else
               "it failed its tests before; lodestar update apply to try again" if db.seen(failed) else
               "lodestar update apply")
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
        bad = "ROLLBACK FAILED" in u["result"]  # the install may sit on code that failed its tests
        rows.append(("ok" if u.get("ok") else "fail" if bad else "warn", "last update", f"{u['at']}: {u['result']}"))
    if s["restart_needed"]:
        rows.append(("warn", "restart", "an update was applied: restart Lodestar to run the new code"))
    return rows
