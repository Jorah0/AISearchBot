"""Import logins from a password manager (pass 48): the CSV export Chrome, Edge, Firefox, Bitwarden, 1Password, LastPass,
Dashlane or KeePass write. Only job-application sites are kept (an application system such as Greenhouse or Workday,
or the site of a job you track), never LinkedIn / Indeed / Glassdoor / ZipRecruiter / SimplyHired (accounts.site_of
refuses them), never over a site already saved, one login per site.

Where the passwords go, and where they never go:
- stage() parses the file and returns a review (sites and usernames only). The rows wait in this process's memory for
  at most TTL seconds under a random id; nothing is written to disk, the database or a log.
- apply() saves the rows you kept through accounts.add: the password goes to the OS keyring (Windows Credential
  Manager, encrypted with your Windows sign-in; the Secret Service or Keychain elsewhere) and the database row holds
  only the site and username. The staged copy is then dropped.
- No AI ever sees a password: there is no AI call here, and only accounts.Page.type types one, into a password field
  on that account's own site, when the apply agent signs in. Full AI (advisor.auto) cannot import (accounts.add calls
  full_ai_check).
ponytail: Python cannot zero a str in memory; the staged rows are dropped after use or expiry, not overwritten.
The export file itself is plain text: delete it after importing (the page and the CLI say so)."""
import csv
import io
import secrets
import threading
import time
from collections import Counter

from . import accounts, apply_ats, db

URL_COLS = {"url", "login_uri", "website", "web site", "uri", "login url", "web address", "address"}
USER_COLS = {"username", "login_username", "user name", "email", "login", "user", "login name", "e-mail"}
PW_COLS = {"password", "login_password", "pass"}
MAX_BYTES = 2_000_000
MAX_ROWS = 5000
TTL = 600  # seconds a review waits for Import
_STAGED: dict[str, tuple[float, dict]] = {}  # id -> (expires, {site: (url, username, password)}): memory only
_LOCK = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _col(header, names) -> str | None:
    return next((h for h in header if str(h or "").strip().lower() in names), None)


def parse(text: str) -> list[tuple[str, str, str]]:
    """(url, username, password) rows of a password manager's CSV export."""
    text = str(text or "")
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise SystemExit("this export is too large (over 2 MB): export only your logins, or split the file")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    head = reader.fieldnames or []
    u, n, p = _col(head, URL_COLS), _col(head, USER_COLS), _col(head, PW_COLS)
    if not (u and p):
        raise SystemExit("this is not a password export Lodestar knows: it needs a URL column and a password column "
                         "(the CSV export of Chrome, Edge, Firefox, Bitwarden, 1Password, LastPass, Dashlane or KeePass)")
    out = []
    for row in reader:
        if row.get(u) and row.get(p):
            out.append((str(row[u]).strip(), str(row.get(n) or "").strip() if n else "", str(row[p])))
        if len(out) >= MAX_ROWS:
            break
    return out


def _job_hosts() -> set[str]:
    hosts = set()
    for j in db.con().execute("SELECT url, apply_url FROM jobs WHERE status NOT IN ('rejected','withdrawn')").fetchall():
        hosts |= {apply_ats.host(x) for x in (j["url"], j["apply_url"]) if x}
    return hosts


def _sweep() -> None:
    with _LOCK:
        for sid in [s for s, (exp, _) in _STAGED.items() if exp < _now()]:
            _STAGED.pop(sid)[1].clear()


def stage(text: str) -> dict:
    """Parse an export and hold the job-site logins for review: {id, rows, sites: [{site, username, ats}], skipped:
    {reason: count}}. Never a password in the answer."""
    _sweep()
    rows = parse(text)
    keep: dict[str, tuple[str, str, str]] = {}
    skipped: Counter = Counter()
    hosts = _job_hosts()
    for url, user, pw in rows:
        try:
            site = accounts.site_of(url)
        except SystemExit as e:
            skipped["a big job board Lodestar never signs in to" if "does not allow bots" in str(e) else "not a web link"] += 1
            continue
        if not user:
            skipped["no username"] += 1
        elif not (apply_ats.ats_of(site) or site in hosts):
            skipped["not a job-application site"] += 1
        elif accounts.for_site(site):
            skipped["already saved in Lodestar"] += 1
        elif site in keep:
            skipped["a second login for the same site"] += 1
        else:
            keep[site] = (url, user, pw)
    sid = secrets.token_urlsafe(16)
    with _LOCK:
        _STAGED[sid] = (_now() + TTL, keep)
    return {"id": sid, "rows": len(rows), "skipped": dict(skipped),
            "sites": [{"site": s, "username": u, "ats": apply_ats.ats_of(s)} for s, (_, u, _) in sorted(keep.items())]}


def _take(sid: str) -> dict:
    _sweep()
    with _LOCK:
        entry = _STAGED.pop(str(sid or ""), None)
    if not entry:
        raise SystemExit("this import expired or was used: choose the export file again")
    return entry[1]


def apply(sid: str, sites: list[str] | None = None) -> dict:
    """Save the reviewed logins you kept (sites; None: all) through accounts.add, then drop the staged copy.
    {saved: [site], failed: {site: why}}."""
    keep = _take(sid)
    saved, failed = [], {}
    try:
        for site, (url, user, pw) in keep.items():
            if sites is not None and site not in sites:
                continue
            try:
                accounts.add(url, user, pw, by="import")
                saved.append(site)
            except SystemExit as e:  # Full AI, a site saved meanwhile: the reason, never the password
                failed[site] = str(e)[:160]
    finally:
        keep.clear()
    return {"saved": saved, "failed": failed}


def discard(sid: str) -> dict:
    """Drop a review without saving anything."""
    try:
        _take(sid).clear()
    except SystemExit:
        pass
    return {"ok": True}
