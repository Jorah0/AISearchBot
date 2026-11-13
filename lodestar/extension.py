"""The browser extension's credential (docs/CAPTURE.md): a one-time pairing code shown in Setup, then a per-browser
secret that signs every /api/ext/* request. Stdlib only.

- Pairing: Setup shows '<port>-<code>' (8 Crockford base32 symbols, 5 min, single use, dead after 5 wrong tries). Only
  a request whose Origin is a chrome-extension:// id may pair (a web page cannot set that header), and the Origin seen
  then is pinned to the new credential (trust on first use: no extension id is configured anywhere).
- Signing: X-Lodestar-Ext: <id>.<unix ts>.<hex HMAC-SHA256(secret, "<ts>\\n<METHOD>\\n<port>\\n<path>\\n" + raw
  body)>, within 120 s, from the pinned Origin. <port> is the port the popup dialled, checked against the port this
  server listens on (never the Host header); the ping's proof is HMAC(secret, "pong\\n<ts>\\n<port>"). So a process
  squatting a scanned port can neither relay signed calls to the real server nor pass its proof off as its own. The
  secret authorizes /api/ext/* only (web.Handler._ext_post); never the page routes.
- Storage: HOME/extension.json, owner-only, atomic; unreadable = no pairings (every signed call 401 until paired again).
  Never in backups (extras.backup skips it), so a restored zip never resurrects a revoked browser.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import datetime

from . import util
from .config import HOME

ORIGIN_RE = re.compile(r"chrome-extension://[a-p]{32}")  # ponytail: + moz-extension://<uuid> when Firefox lands
PATH = HOME / "extension.json"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
CODE_TTL, MAX_TRIES, SKEW, LABEL_MAX = 300, 5, 120, 40
BAD_CODE = "pairing code wrong or expired"  # one text for every cause
_CODE = {"code": None, "expires": 0.0, "tries": 0}  # the one live code, memory only
_LOCK = threading.Lock()
_TOUCHED: dict[str, float] = {}  # id -> last last_used write (one write a minute)
now = time.time  # tests patch the clock


def new_code() -> dict:
    """A fresh pairing code; it replaces any live one."""
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    with _LOCK:
        _CODE.update(code=code, expires=now() + CODE_TTL, tries=0)
    return {"code": f"{code[:4]}-{code[4:]}", "expires_in": CODE_TTL}


def _norm(code) -> bytes:
    """What the user typed, as the code is stored: upper case, no separators, O->0, I/L->1."""
    return re.sub(r"[\s-]", "", str(code)).upper().translate(str.maketrans("OIL", "011")).encode()


def pair(code, origin, label) -> dict:
    """{id, secret} for a browser whose Origin is an extension and whose code is the live one. SystemExit(BAD_CODE)
    otherwise. A non-extension Origin is refused before the code is compared, so it burns no try."""
    if not ORIGIN_RE.fullmatch(str(origin or "")):
        raise SystemExit(BAD_CODE)
    with _LOCK:
        if not _CODE["code"] or now() > _CODE["expires"]:
            _CODE["code"] = None
            raise SystemExit(BAD_CODE)
        if not hmac.compare_digest(_norm(code), _CODE["code"].encode()):
            _CODE["tries"] += 1
            if _CODE["tries"] >= MAX_TRIES:
                _CODE["code"] = None
            raise SystemExit(BAD_CODE)
        _CODE["code"] = None  # single use
        at = datetime.now().isoformat(timespec="seconds")
        entry = {"id": secrets.token_hex(4), "origin": origin, "label": " ".join(str(label or "").split())[:LABEL_MAX] or "Browser",
                 "secret": secrets.token_urlsafe(32), "paired_at": at, "last_used": at}
        d = _load()
        d["paired"].append(entry)
        _save(d)
    return {"id": entry["id"], "secret": entry["secret"]}


def _sign(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify(header, origin, method: str, port: int, path: str, body: bytes) -> str | None:
    """The paired entry's id when the signature header is good, else None. port = the port this server listens on."""
    parts = str(header or "").split(".")
    if len(parts) != 3 or not (parts[1].isascii() and parts[1].isdigit()) or len(parts[1]) > 12:
        return None
    eid, ts, sig = parts
    e = next((x for x in _load()["paired"] if x["id"] == eid), None)
    if not e or str(origin or "") != e["origin"] or abs(now() - int(ts)) > SKEW:
        return None
    if not hmac.compare_digest(sig.encode(), _sign(e["secret"], f"{ts}\n{method}\n{int(port)}\n{path}\n".encode() + body).encode()):
        return None
    if now() - _TOUCHED.get(eid, 0) > 60:  # last_used for Setup's list, at most one write a minute
        _TOUCHED[eid] = now()
        with _LOCK:
            d = _load()
            for x in d["paired"]:
                if x["id"] == eid:
                    x["last_used"] = datetime.now().isoformat(timespec="seconds")
            _save(d)
    return eid


def proof(eid: str, msg: str) -> str:
    """HMAC(secret, msg): the ping's answer, which only the real server (it holds the secret) can give."""
    e = next((x for x in _load()["paired"] if x["id"] == eid), None)
    if not e:
        raise SystemExit("not paired")
    return _sign(e["secret"], msg.encode())


def paired() -> list[dict]:
    """For state() and Setup: never the secret."""
    return [{k: x.get(k, "") for k in ("id", "label", "origin", "paired_at", "last_used")} for x in _load()["paired"]]


def revoke(eid) -> bool:
    with _LOCK:
        d = _load()
        keep = [x for x in d["paired"] if x["id"] != str(eid)]
        if len(keep) == len(d["paired"]):
            return False
        _save({"paired": keep})
    return True


LINKEDIN = ("Lodestar does not capture or fill on LinkedIn: its User Agreement bans browser add-ons that scrape or "
            "copy it. Open the job on the company's own careers page instead.")


def linkedin(url) -> bool:
    """A linkedin.com page (any subdomain): the extension never captures or fills there."""
    from urllib.parse import urlparse

    try:
        host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def bookmarklets_on() -> bool:
    """The ?t= capture token (the bookmarklets) works: pref 'bookmarklets' on, or auto while no browser is paired."""
    from .settings import pref

    v = pref("bookmarklets")
    return v == "on" or (v not in ("on", "off") and not _load()["paired"])


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        rows = [x for x in d["paired"] if isinstance(x, dict) and all(isinstance(x.get(k), str) and x.get(k)
                                                                         for k in ("id", "origin", "secret"))]
        return {"paired": rows}
    except (OSError, ValueError, KeyError, TypeError):  # missing or corrupt: no pairings (fail closed)
        return {"paired": []}


def _save(d: dict) -> None:
    util.write_atomic(PATH, json.dumps(d, indent=1), private=True)  # owner-only, with the Windows retry
