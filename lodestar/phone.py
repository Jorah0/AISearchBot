"""Phone access (pass 53): Lodestar on your phone over your home Wi-Fi. Off by default (pref `phone_access`).

When on, a second listener binds this computer's private LAN address only (never 0.0.0.0, never a public address).
Every request there needs a phone session cookie, won by typing a one-time pairing code that Setup shows on this
computer (8 characters, 5 minutes, 5 tries). Sessions are stored hashed in HOME/phone.json (never in backups), and
Setup's "Sign out all phones" drops them. Secrets stay on this computer: the phone listener refuses keys, vault,
accounts, sign-in codes, mail sign-in, backups / restore / updates, uploads, folders, the extension and the in-app
browser. ponytail: plain HTTP on the LAN (no certificate to install); anyone on the same Wi-Fi who can read its
traffic can read the session, so this is for a home network, not a cafe. Add TLS if that ever matters."""
import hashlib
import ipaddress
import json
import secrets
import socket
import threading
import time
from http.server import ThreadingHTTPServer

from .config import HOME

PATH = HOME / "phone.json"
COOKIE = "ls_phone"
CODE_TTL, CODE_TRIES, PORT = 300, 5, 8780
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
DENY = ("/api/keys", "/api/vault", "/api/accounts", "/api/codes", "/api/email", "/api/backups", "/api/update",
        "/api/upload", "/api/open_folder", "/api/extension", "/api/ext/", "/api/browser", "/api/phone")
DENY_RUN = {"restore", "backup", "update_apply", "update_check", "export", "email_signin", "obsidian", "profile_import",
            "contacts_import", "doctor", "keys_check", "providers_test", "providers_local", "notify_test"}
_CODE: dict = {}
_SRV = None
_LOCK = threading.Lock()


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("sessions"), list) else {"sessions": []}
    except (OSError, ValueError):
        return {"sessions": []}


def _save(d: dict) -> None:
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    tmp.replace(PATH)


def lan_ip() -> str | None:
    """This computer's private LAN address (the route a packet would take; nothing is sent), else None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: never routed, no packet leaves for a UDP connect
            ip = s.getsockname()[0]
    except OSError:
        return None
    a = ipaddress.ip_address(ip)
    return ip if a.is_private and not a.is_loopback and not a.is_link_local else None


def new_code() -> dict:
    """A fresh one-time pairing code (replaces any earlier one)."""
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    with _LOCK:
        _CODE.clear()
        _CODE.update(hash=_h(code), until=time.time() + CODE_TTL, tries=0)
    return {"code": f"{code[:4]}-{code[4:]}", "expires_in": CODE_TTL}


def pair(code: str, label: str = "phone") -> str | None:
    """The typed code -> a new session token (set as the cookie), or None. The code works once; 5 wrong tries end it."""
    c = "".join(ch for ch in str(code or "").upper() if ch in ALPHABET)
    with _LOCK:
        if not _CODE or time.time() > _CODE["until"]:
            _CODE.clear()
            return None
        if not secrets.compare_digest(_h(c), _CODE["hash"]):
            _CODE["tries"] += 1
            if _CODE["tries"] >= CODE_TRIES:
                _CODE.clear()
            return None
        _CODE.clear()
    tok = secrets.token_urlsafe(32)
    d = _load()
    d["sessions"].append({"hash": _h(tok), "label": " ".join(str(label or "phone").split())[:60],
                          "created": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())})
    _save(d)
    return tok


def valid(cookie_header: str | None) -> bool:
    tok = ""
    for part in str(cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            tok = v
    return bool(tok) and any(secrets.compare_digest(_h(tok), s.get("hash", "")) for s in _load()["sessions"])


def revoke_all() -> int:
    n = len(_load()["sessions"])
    _save({"sessions": []})
    return n


def allowed(path: str, action: str | None = None) -> bool:
    """What a phone may reach: everything but the secret-bearing and machine-level routes."""
    if path.startswith(DENY):
        return False
    return not (path.startswith("/api/run/") and path[len("/api/run/"):].split("/")[0] in DENY_RUN)


def status() -> dict:
    ip = lan_ip()
    srv = _SRV
    return {"on": srv is not None, "url": f"http://{srv.server_address[0]}:{srv.server_address[1]}/phone" if srv else None,
            "lan_ip": ip, "phones": [{"label": s["label"], "created": s["created"]} for s in _load()["sessions"]],
            "code_live": bool(_CODE) and time.time() < _CODE.get("until", 0)}


def start(port: int = PORT) -> dict:
    """Bind the phone listener to the LAN address (idempotent). Refused without a private LAN address."""
    global _SRV
    from . import web

    with _LOCK:
        if _SRV is None:
            ip = lan_ip()
            if not ip:
                raise SystemExit("no private home-network address found: connect this computer to your Wi-Fi first")
            for p in range(port, port + 20):
                try:
                    _SRV = ThreadingHTTPServer((ip, p), web.PhoneHandler)
                    break
                except OSError:
                    continue
            else:
                raise SystemExit(f"no free port between {port} and {port + 19}")
            threading.Thread(target=_SRV.serve_forever, daemon=True, name="lodestar-phone").start()
    return status()


def stop() -> dict:
    global _SRV
    with _LOCK:
        srv, _SRV = _SRV, None
    if srv is not None:
        srv.shutdown()
        srv.server_close()
    return status()
