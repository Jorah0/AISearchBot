"""`lodestar doctor`: pass / warn / fail checks for a fresh or broken install, with the fix next to each line."""
import importlib
import os
import sys
from pathlib import Path

from . import ai
from .config import HOME, PROFILE


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
    from . import profile

    text = profile.master_text()
    filled = not profile.is_template(text)
    out.append(("ok" if filled else "warn", "master profile", str(PROFILE) + ("" if filled else " still the template: fill it in or import a resume")))
    bank = profile.load()
    n = {k: len(bank[k]) for k in ("skills", "languages", "experience", "resumes")}
    out.append(("ok" if n["resumes"] or n["skills"] else "warn", "profile bank",
                f"{n['skills']} skills, {n['languages']} languages, {n['experience']} roles, {n['resumes']} saved resume(s)"
                if any(n.values()) else "empty: lodestar profile import <resume> or lodestar profile linkedin <export.zip>"))
    avail = ai.available()
    out.append(("ok" if avail else "fail", "AI providers", ", ".join(f"{n} ({ai.model_for(n)})" for n in avail) or
                "none configured: lodestar keys link anthropic (or another provider)"))
    from . import connections

    try:
        conn = connections.status()
    except (Exception, SystemExit) as e:  # a locked keyring: one row, the other checks still print
        conn = {"keys": {}, "mail": {}}
        out.append(("warn", "key checks", str(e)[:160]))
    for n, k in conn["keys"].items():  # the stored result of the last check: no network here
        if not k["linked"]:
            continue
        when = f"checked {connections.local(k['checked_at'])}" if k["checked_at"] else ""
        if k["status"] == "verified":
            out.append(("ok", f"key {n}", f"verified, {when}, model {k['model']}"))
        elif k["status"] == "failed":
            out.append(("fail", f"key {n}", k["detail"] + (f" ({when})" if when else "")))
        elif k["status"] == "unreachable":
            out.append(("warn", f"key {n}", f"{k['detail']} ({when}): lodestar keys check {n}"))
        else:
            out.append(("warn", f"key {n}", f"not checked yet: lodestar keys check {n}"))
    from . import mailconn

    try:
        c = mailconn.status()
    except (Exception, SystemExit) as e:
        c = None
        out.append(("warn", "email", str(e)[:160]))
    mail = bool(c and c["configured"])
    how = {"google": "Google sign-in", "microsoft": "Microsoft sign-in"}.get(c["oauth_provider"], "app password") if c else ""
    if c:
        out.append(("ok" if mail else "warn", "email", f"{c['user']} ({c['preset'] or 'no preset'}, {how}): IMAP "
                    f"{c['imap_host']}:{c['imap_port']}, SMTP {c['smtp_host']}:{c['smtp_port']} {c['smtp_mode']}" if mail else
                    "not connected (optional): Setup > Connect email, or lodestar email connect"))
    if mail and c["needs_signin"]:
        out.append(("fail", "email sign-in", f"{c['needs_signin'][:120]}: sign in again: lodestar email signin {c['oauth_provider']}"))
    if mail and c["refresh_expires"] and c["refresh_expires"] <= _in_days(7):
        out.append(("warn", "email sign-in", f"Google app in Testing: this sign-in stops working {c['refresh_expires']} UTC; "
                    "publish it (docs/CONNECT.md step 6), then lodestar email signin google"))
    for prov, s in (c["clients"].items() if c else ()):
        if s["set"]:
            out.append(("ok", f"OAuth client {prov}", "set up (lodestar email client " + prov + " to change)"))
    m = conn["mail"]
    if mail and m.get("status") in ("verified", "failed", "unreachable"):
        out.append(({"verified": "ok", "failed": "fail"}.get(m["status"], "warn"), "email check",
                    f"{m['status']} {connections.local(m.get('checked_at', ''))}: {m.get('detail', '')}"))
    old = Path.home() / ".jobbot"
    if old.exists():
        out.append(("warn", "legacy folder", f"{old} still exists; safe to delete once ~/.lodestar has your data"))
    return out


def _in_days(n: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


def live_mail() -> list[tuple[str, str, str]]:
    """One IMAP and one SMTP login (mailconn.test) when a mailbox is connected; nothing otherwise."""
    from . import mailconn

    if not mailconn.status()["configured"]:
        return []
    try:
        r = mailconn.test()
    except (Exception, SystemExit) as e:
        return [("fail", "live mail", str(e)[:160])]
    return [("ok" if r[k]["ok"] else "fail", f"live {k.upper()} login",
             r[k]["detail"] + ("" if r[k]["ok"] or not r["hint"] else " | " + r["hint"])) for k in ("imap", "smtp")]


def live_keys() -> list[tuple[str, str, str]]:
    """Verify every linked key now (no tokens: each provider's model list or key info) and record the result."""
    from . import connections

    rows = []
    for n in ai.available():
        r = connections.check(n)
        rows.append(({"verified": "ok", "failed": "fail"}.get(r["status"], "warn"), f"key check {n}", r["detail"]))
    return rows


def report(live: bool = False) -> int:
    rows = checks()
    if live:
        rows += live_keys()
        rows += (mail := live_mail())
        if not mail and not ai.available():
            rows.append(("warn", "live", "skipped: no AI provider or mailbox configured"))
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
