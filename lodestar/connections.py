"""Linkable keys and the connection checks: verify an AI key without spending tokens, remember the result (never the
key), and re-check every stored key and the connected mailbox once per app start in the background.

HOME/connections.json holds {"keys": {name: {status, checked_at, detail, model, quota?, fp}}, "mail": {...}}. status is
verified | failed | unreachable | unchecked; fp is the first 12 hex of sha256(key), so a changed key reads unchecked.
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import ai, settings, vault
from .config import HOME, setting

PATH = HOME / "connections.json"
_LOCK = threading.Lock()

# ponytail: labels, console links and prefix hints per ai.PROVIDERS entry; job-data keys join later with hidden=True
REGISTRY = {
    "anthropic": {"label": "Anthropic (Claude)", "key": "ANTHROPIC_API_KEY", "get": "https://console.anthropic.com/settings/keys",
                  "hint": "starts with sk-ant-", "prefix": "sk-ant-"},
    "openai": {"label": "OpenAI", "key": "OPENAI_API_KEY", "get": "https://platform.openai.com/api-keys",
               "hint": "starts with sk-", "prefix": "sk-"},
    "gemini": {"label": "Google Gemini", "key": "GEMINI_API_KEY", "get": "https://aistudio.google.com/apikey",
               "hint": "starts with AIza", "prefix": "AIza"},
    "groq": {"label": "Groq", "key": "GROQ_API_KEY", "get": "https://console.groq.com/keys", "hint": "starts with gsk_",
             "prefix": "gsk_"},
    "openrouter": {"label": "OpenRouter", "key": "OPENROUTER_API_KEY", "get": "https://openrouter.ai/settings/keys",
                   "hint": "starts with sk-or-", "prefix": "sk-or-", "models": False},  # public model list: /key proves the key
    "mistral": {"label": "Mistral", "key": "MISTRAL_API_KEY", "get": "https://console.mistral.ai/api-keys", "hint": "",
                "prefix": ""},
    "ollama": {"label": "Ollama (local, no key)", "key": None, "get": "https://ollama.com/download",
               "hint": "runs on this computer; no key", "prefix": ""},
    # job-data keys (kind "jobs"): a second value `id` goes with the key; Setup > Job sources links them, never the AI card
    "adzuna": {"label": "Adzuna (job search)", "key": "ADZUNA_APP_KEY", "id": "ADZUNA_APP_ID", "id_label": "Application ID",
               "get": "https://developer.adzuna.com/signup", "hint": "the Application Key and Application ID", "prefix": "",
               "kind": "jobs"},
    "usajobs": {"label": "USAJOBS (US federal jobs)", "key": "USAJOBS_API_KEY", "id": "USAJOBS_EMAIL",
                "id_label": "the email you requested the key with", "get": "https://developer.usajobs.gov/apirequest/",
                "hint": "the Authorization Key USAJOBS emailed you", "prefix": "", "kind": "jobs"},
}
JOBS = "jobs"


def redact(text, *secrets) -> str:
    """text with every given secret shown as *** (empty or short ones skipped: they would mangle every message), then
    URL query values scrubbed."""
    from .util import redact_url

    out = str(text or "")
    for s in secrets:
        if s and len(str(s)) >= 8:
            out = out.replace(str(s), "***")
    return " ".join(redact_url(w) if "?" in w and "://" in w else w for w in out.split(" "))


def fp(key) -> str:
    return hashlib.sha256(str(key or "").encode()).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # UTC, like the database (the UI shows local time)


def local(ts: str) -> str:
    """A stored UTC time as this computer's local 'YYYY-MM-DD HH:MM' (terminal and doctor)."""
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(ts or "")


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8")) if PATH.is_file() else {}
    except (OSError, ValueError):  # a corrupt file reads as "nothing checked yet"
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["keys"] = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    return data


def _save(data: dict) -> None:
    tmp = PATH.with_name(PATH.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def record(kind: str, name: str | None, result: dict, key_fp: str) -> None:
    """Remember a check (kind 'keys' with a provider name, or 'mail'); never the key, only its fingerprint."""
    rec = {k: result[k] for k in ("status", "detail", "model", "quota") if result.get(k) not in (None, "")}
    rec |= {"checked_at": _now(), "fp": key_fp}
    with _LOCK:
        data = _load()
        if kind == "mail":
            data["mail"] = rec
        else:
            data["keys"][name] = rec
        _save(data)


def _forget(name: str) -> None:
    with _LOCK:
        data = _load()
        if data["keys"].pop(name, None) is not None:
            _save(data)


def resolve(name: str) -> str:
    """'anthropic' or 'ANTHROPIC_API_KEY' -> 'anthropic'."""
    n = str(name or "").strip()
    for k, e in REGISTRY.items():
        if n.lower() == k or (e["key"] and n.upper() == e["key"]):
            return k
    raise SystemExit(f"unknown key '{n[:40]}'. One of: {', '.join(REGISTRY)}")


def secret(name: str) -> str | None:
    """The stored key of a registry entry: an AI provider's through ai.api_key, a job-data key from the vault."""
    e = REGISTRY[name]
    return setting(e["key"]) if e.get("kind") == JOBS else ai.api_key(name)


def _verify_jobs(name: str, key: str, ident: str) -> dict:
    """One small search proves a job-data key (Adzuna: 1 result; USAJOBS: 1 result, its documented headers)."""
    from urllib.parse import quote

    if name == "adzuna":
        country = str(settings.pref("adzuna_country") or "us")
        url = (f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?app_id={quote(ident)}&app_key={quote(key)}"
               "&results_per_page=1&what=analyst&content-type=application/json")
        headers = {}
    else:
        url = "https://data.usajobs.gov/api/search?Keyword=analyst&ResultsPerPage=1"
        headers = {"Host": "data.usajobs.gov", "User-Agent": ident, "Authorization-Key": key}
    host = urlsplit(url).hostname
    try:
        with urlopen(Request(url, headers=headers), timeout=15) as r:
            json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (400, 401, 403):
            return {"status": "failed", "detail": f"{REGISTRY[name]['label']} rejected this key or "
                                                  f"{REGISTRY[name]['id_label'].lower()}: copy both again from {REGISTRY[name]['get']}"}
        if e.code == 429:
            return {"status": "failed", "quota": True, "detail": "rate limit reached; the key itself was accepted. Wait"}
        return {"status": "unreachable", "detail": f"{host} answered HTTP {e.code}; will retry"}
    except (urllib.error.URLError, OSError, ValueError):
        return {"status": "unreachable", "detail": f"couldn't reach {host}; will retry"}
    return {"status": "verified", "detail": "key ok (one search with 1 result)"}


def _url(name: str) -> str:
    """The no-token endpoint that proves a key, derived like ai.list_models."""
    if name == "anthropic":
        return "https://api.anthropic.com/v1/models?limit=1000"  # paginated (20 by default): a wanted model may be on page 2
    base = ai.PROVIDERS[name]["url"].rsplit("/chat/completions", 1)[0]
    return base + ("/key" if name == "openrouter" else "/models")


def _headers(name: str, key: str | None) -> dict:
    if name == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"} if key else {}


def _norm(m: str) -> str:
    m = str(m or "").removeprefix("models/")  # Gemini lists 'models/gemini-x'
    return m.removesuffix(":latest")  # Ollama: 'llama3.1' is 'llama3.1:latest'


def verify_key(name: str, key: str | None = None) -> dict:
    """One no-token call to the provider: {status, detail, model?, quota?, pick?}. Never the key, never more than a
    scrubbed 160 characters of what the provider said."""
    entry = REGISTRY[name]
    if entry["key"]:
        key = (key or secret(name) or "").strip()
        if not key:
            return {"status": "unchecked", "detail": "no key stored"}
    else:
        key = None
    if entry.get("kind") == JOBS:
        ident = (setting(entry["id"]) or "").strip()
        if not ident:
            return {"status": "unchecked", "detail": f"no {entry['id_label'].lower()} stored"}
        res = _verify_jobs(name, key, ident)
        return res | {"detail": redact(res["detail"], key, ident)[:160]}
    host = urlsplit(_url(name)).hostname
    try:
        with urlopen(Request(_url(name), headers=_headers(name, key)), timeout=15) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:  # before URLError: HTTPError is one
        try:
            body = e.read(2000).decode(errors="replace")
        except Exception:
            body = ""
        finally:
            e.close()
        if e.code in (401, 403) or (e.code == 400 and "key" in body.lower()):  # Gemini: 400 "API key not valid"
            return {"status": "failed", "detail": "the provider rejected this key: copy the whole key again, or create a "
                                                  f"new one at {entry['get']}"}
        if e.code == 402:
            return {"status": "failed", "detail": "no credit on this account: add billing or credit at the provider"}
        if e.code == 429:
            return {"status": "failed", "quota": True,
                    "detail": "quota or rate limit reached; the key itself was accepted. Wait, or check your plan"}
        if e.code >= 500:
            return {"status": "unreachable", "detail": f"{host} answered HTTP {e.code}; will retry"}
        return {"status": "failed", "detail": redact(f"HTTP {e.code}: {body}", key)[:160]}
    except (urllib.error.URLError, OSError, ValueError):  # offline, DNS, timeout, refused, or a captive portal's HTML
        return {"status": "unreachable", "detail": f"couldn't reach {host}; will retry"}
    if name == "openrouter":
        d = data.get("data") if isinstance(data, dict) else None
        extra = [f"{k} {d[k]}" for k in ("limit", "usage") if isinstance(d, dict) and d.get(k) is not None]
        return {"status": "verified", "detail": redact("key ok" + (f" ({', '.join(extra)})" if extra else ""), key)[:160],
                "model": ai.model_for(name)}
    rows = data.get("data") if isinstance(data, dict) else None
    ids = [m.get("id", "") for m in rows if isinstance(m, dict)] if isinstance(rows, list) else []
    want, out = ai.model_for(name), {"status": "verified"}
    detail = f"{len(ids)} models; using {want}"
    have = {_norm(i) for i in ids}
    if ids and entry.get("models", True) and not data.get("has_more") and _norm(want) not in have:
        if setting(f"{name.upper()}_MODEL"):
            detail = f"{len(ids)} models; model {want} (pinned by {name.upper()}_MODEL) is not offered"
        else:
            pick = ai.pick_from(name, ids)
            detail = f"{len(ids)} models; model {want} is not offered" + (f"; Setup can switch to {pick}" if pick else "")
            if pick:
                out["pick"] = pick
    return out | {"detail": redact(detail, key)[:160], "model": want}


def link(name: str, key: str | None = None, ident: str | None = None) -> dict:
    """Store a key in the vault and verify it at once. A key that fails is still stored (offline, out of credit) and
    shown Failed with the hint. With the user present, a missing model is switched to one the provider offers.
    ident: a job-data key's second value (Adzuna's Application ID, the USAJOBS email), stored beside it."""
    name = resolve(name)
    entry = REGISTRY[name]
    out = {"name": name, "label": entry["label"]}
    if entry["key"]:
        key = "".join(str(key or "").split())  # a pasted key's spaces or line break are never part of it
        if not key:
            raise SystemExit(f"paste the {entry['label']} key ({entry['hint'] or 'from ' + entry['get']})")
        if entry.get("kind") == JOBS:
            ident = "".join(str(ident or "").split()) or setting(entry["id"]) or ""
            if not ident or len(ident) > 200 or (entry["id"].endswith("EMAIL") and "@" not in ident):
                raise SystemExit(f"give the {entry['id_label']} too ({entry['label']})")
            vault.set(entry["id"], ident)
        if entry["prefix"] and not key.startswith(entry["prefix"]):
            out["prefix_warning"] = f"this does not look like an {entry['label']} key ({entry['hint']}); linked anyway"
        vault.set(entry["key"], key)
        env = os.environ.get(entry["key"])
        if env and env != key:
            out["shadowed"] = f"{entry['key']} in .env or the environment overrides this key: remove that line"
    res = verify_key(name, key)
    if res.get("pick") and not setting(f"{name.upper()}_MODEL"):
        settings.set_model(name, res["pick"])
        res |= {"model": res["pick"], "detail": res["detail"].split("; Setup can switch")[0] + f"; switched to {res['pick']}"}
    # Ollama: no key to store, so a link that reached it pins its model (what ai.available() and the card read). A dead
    # Ollama is never pinned: that would switch off the offline templates, as ai.local_preset() also refuses
    if not entry["key"] and res.get("status") == "verified" and name not in ai.available():
        settings.set_model(name, res.get("model") or ai.model_for(name))
    record("keys", name, res, fp(key or secret(name)))
    return out | {k: v for k, v in res.items() if k != "pick"}


def unlink(name: str) -> dict:
    name = resolve(name)
    k = REGISTRY[name]["key"]
    if not k:  # Ollama: no key; unlinking clears the model pin its link saved (an empty entry = no pin)
        settings.set_pref("models", f"{name}=")
        _forget(name)
        if name in ai.available():
            raise SystemExit("Ollama's model pin is cleared, but it stays on: OLLAMA_MODEL is set in .env or the "
                             "environment, or the provider is ollama under Tools > Preferences")
        return status()
    if os.environ.get(k) and not vault.get(k):
        raise SystemExit(f"{k} is set in .env or the environment, not in the vault: remove it there")
    vault.delete(k)
    if REGISTRY[name].get("id") and vault.get(REGISTRY[name]["id"]):  # a job-data key's ID / email goes with it
        vault.delete(REGISTRY[name]["id"])
    _forget(name)
    return status()


def status() -> dict:
    """{keys: {name: {label, linked, source, status, checked_at, detail, model, get, hint}}, mail: {...}, checking}."""
    from . import mailconn, util

    data, avail, keys = _load(), ai.available(), {}
    for n, e in REGISTRY.items():
        if e.get("hidden"):
            continue
        k = secret(n) if e["key"] else None
        linked = (bool(k) and (not e.get("id") or bool(setting(e["id"])))) if e["key"] else n in avail
        s = data["keys"].get(n) or {}
        if not linked or s.get("fp") != fp(k or secret(n)):
            s = {}  # a changed (or removed) key reads unchecked until it is verified again
        keys[n] = {"label": e["label"], "linked": linked, "get": e["get"], "hint": e["hint"],
                   "source": ("env" if e["key"] and os.environ.get(e["key"]) else "vault") if linked and e["key"] else "",
                   "status": s.get("status", "unchecked"), "checked_at": s.get("checked_at", ""),
                   "detail": s.get("detail", ""), "quota": bool(s.get("quota")), "kind": e.get("kind", "ai"),
                   "model": "" if e.get("kind") == JOBS else s.get("model") or (ai.model_for(n) if linked else ""),
                   "id_label": e.get("id_label", "")}
    mail = data.get("mail") if isinstance(data.get("mail"), dict) else {}
    if mail and (mail.get("fp") != mailconn._fingerprint(util.mail_settings()) or not util.mail_login()[1]):
        mail = {}  # another mailbox, or disconnected: an old result says nothing about it
    return {"keys": keys, "mail": {k: mail[k] for k in ("status", "detail", "checked_at") if k in mail} or {"status": "unchecked"},
            "checking": CHECKING.is_set()}


def check(name: str) -> dict:
    """Verify one linked key now and remember the result (never changes settings)."""
    name = resolve(name)
    k = secret(name)
    try:
        res = verify_key(name)
    except (Exception, SystemExit) as e:  # one provider never stops the others
        res = {"status": "unreachable", "detail": redact(str(e), k)[:160]}
    if res["status"] != "unchecked":
        record("keys", name, res, fp(k))
    return res


def check_mail() -> dict | None:
    """One IMAP + one SMTP login (nothing sent): verified, failed (sign-in refused or a setup problem, with the hint) or
    unreachable (network: never un-verifies the mailbox). None when no mailbox is connected."""
    from . import mailconn, util

    if not mailconn.status()["configured"]:
        return None
    mfp = mailconn._fingerprint(util.mail_settings())
    try:
        return mail_result(mailconn.test())  # test() records its own result
    except (Exception, SystemExit) as e:
        res = {"status": "failed", "detail": redact(str(e))[:200]}
    record("mail", None, res, mfp)
    return res


def mail_result(r: dict) -> dict:
    """mailconn.test()'s answer as a stored check. Every test records through here (startup, Re-check all, Connect &
    test, a new sign-in), so a mailbox that was just fixed never keeps showing an old failure."""
    bad = [r[s] for s in ("imap", "smtp") if not r[s]["ok"]]
    if not bad:
        return {"status": "verified", "detail": "IMAP ok, SMTP ok"}
    if any(b.get("kind") != "net" for b in bad):
        return {"status": "failed", "detail": (r.get("hint") or bad[0]["detail"])[:200]}
    return {"status": "unreachable", "detail": "couldn't reach the mail server; will retry"}


def check_all() -> dict:
    """Re-verify every linked key and the mailbox (Setup's Re-check all, doctor, the startup pass)."""
    CHECKING.set()
    try:
        for n in ai.available():  # = the linked entries of status()
            check(n)
        try:
            check_mail()
        except (Exception, SystemExit):
            pass
    finally:
        CHECKING.clear()
    return status()


_STARTED = False
CHECKING = threading.Event()


def start_checks(delay: float = 2.0) -> bool:
    """Once per process: re-verify every linked key and the connected mailbox on a daemon thread. Never raises."""
    global _STARTED
    if _STARTED or os.environ.get("LODESTAR_NO_STARTUP_CHECK") == "1":
        return False
    _STARTED = True
    try:
        threading.Thread(target=_run_checks, args=(delay,), daemon=True, name="lodestar-checks").start()
    except Exception:  # ponytail: a thread that cannot start just means no check this run
        return False
    return True


def _run_checks(delay: float) -> None:
    from . import db

    time.sleep(delay)  # the window and the first /api/state come first
    try:
        # ponytail: one pass; unreachable waits for the next start or a Re-check click (no retry schedule)
        check_all()
    except (Exception, SystemExit):  # status() itself failing (keyring locked) must not kill the thread noisily
        pass
    finally:
        db.release()  # the mail check may have touched the database (same rule as web.start_task)
