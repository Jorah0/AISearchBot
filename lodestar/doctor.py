"""`lodestar doctor`: pass / warn / fail checks for a fresh or broken install, with the fix next to each line."""
import importlib
import os
import sys
from pathlib import Path

from . import ai
from .config import HOME, PROFILE, setting


def checks() -> list[tuple[str, str, str]]:
    """[(status, what, detail)] where status is ok | warn | fail."""
    out: list[tuple[str, str, str]] = []
    v = sys.version_info
    out.append(("ok" if v >= (3, 11) else "fail", "Python", f"{v.major}.{v.minor}.{v.micro} (3.11+ required)"))
    for mod, extra in (("keyring", ""), ("docx", ""), ("webview", " (pip install -e .[desktop])"), ("pypdf", " (pip install -e .[pdf])")):
        try:
            importlib.import_module(mod)
            out.append(("ok", f"module {mod}", "installed"))
        except ImportError:
            out.append(("warn" if extra else "fail", f"module {mod}", f"missing{extra}"))
    try:
        import keyring

        kr = keyring.get_keyring()
        name = type(kr).__name__
        out.append(("warn" if "fail" in name.lower() or "null" in name.lower() else "ok", "keyring backend", name))
    except Exception as e:
        out.append(("fail", "keyring backend", str(e)))
    if os.name == "nt":
        wv = [p for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "EdgeWebView" / "Application",
                          Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "EdgeWebView" / "Application") if p.is_dir()]
        out.append(("ok" if wv else "warn", "WebView2 runtime", "found" if wv else "not found; the desktop window falls back to the browser"))
    try:
        test = HOME / ".doctor-write-test"
        test.write_text("x", encoding="utf-8")
        test.unlink()
        out.append(("ok", "data folder", f"{HOME} (writable)"))
    except OSError as e:
        out.append(("fail", "data folder", f"{HOME} not writable: {e}"))
    text = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else ""
    filled = len(text) > 400 and "Full Name" not in text
    out.append(("ok" if filled else "warn", "master profile", str(PROFILE) + ("" if filled else " still the template: fill it in or import a resume")))
    avail = ai.available()
    out.append(("ok" if avail else "fail", "AI providers", ", ".join(f"{n} ({ai.model_for(n)})" for n in avail) or
                "none configured: lodestar vault set ANTHROPIC_API_KEY (or another provider key)"))
    mail = bool(setting("IMAP_USER") and setting("IMAP_PASS"))
    out.append(("ok" if mail else "warn", "email monitor", "IMAP credentials present" if mail else "not configured (optional): vault set IMAP_USER / IMAP_PASS"))
    old = Path.home() / ".jobbot"
    if old.exists():
        out.append(("warn", "legacy folder", f"{old} still exists; safe to delete once ~/.lodestar has your data"))
    return out


def report(live: bool = False) -> int:
    rows = checks()
    if live:
        for n in ai.available():
            try:
                ai.ask("Reply with the single word OK.", provider=n)
                rows.append(("ok", f"live call {n}", ai.model_for(n)))
            except BaseException as e:
                rows.append(("fail", f"live call {n}", str(e)[:160]))
    worst = 0
    for status, what, detail in rows:
        mark = {"ok": "PASS", "warn": "WARN", "fail": "FAIL"}[status]
        worst = max(worst, {"ok": 0, "warn": 1, "fail": 2}[status])
        print(f"[{mark}] {what:<18} {detail}")
    print({0: "all good", 1: "usable; see WARN lines", 2: "something is broken; see FAIL lines"}[worst])
    return worst
