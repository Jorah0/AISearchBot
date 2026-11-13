"""Emailed-code assist: verification codes that job and ATS sites email you, spotted by a regex (no AI) in mail from
the last 15 minutes whose sender passes aligned DKIM/DMARC, shown in the Inbox's Codes panel with the sender's domain.

Verification links ("verify your email", "activate your account") from the same mail are kept the same way (links(),
link_url()); the page sees only the link's host. A site account (accounts.py) uses a code or a link only when you click
Fill code / Open link for it, or by itself on a site where you allowed that, and a link only on the account's own host.

Memory only: never written to disk, logged, notified, put in /api/state (only a count) or sent to an AI provider, and
never entered anywhere else. Lodestar never stores an authenticator (TOTP) secret: that would put both factors on one
computer (docs/CONNECT.md)."""
import email
import hashlib
import imaplib
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlparse

TTL = 900  # 15 minutes, from the mail's received time
CODE_RE = re.compile(r"(?<![\w-])(\d{4,8}|[A-Z0-9]{6,8})(?![\w-])")
CUE_RE = re.compile(r"(verification|security|one[- ]time|login|log-in|sign[- ]in|confirmation|access|authentication)"
                    r"\s*(code|passcode|pin)|\b(otp|2fa|mfa|passcode)\b|\bcode\s*(is\b|:)|\bto (sign|log)[- ]?in\b", re.I)
WINDOW = 120  # characters around a candidate that must hold a cue (when the subject has none)
MAX_POLL_SIZE = 1_000_000  # code mails are tiny: never download a large message just to look for one
_CODES: dict[str, dict] = {}  # id -> {"id", "code", "sender", "domain", "subject", "received"}; memory only
_LINKS: dict[str, dict] = {}  # id -> {"id", "url", "host", "sender", "domain", "subject", "received"}; memory only
_LOCK = threading.Lock()
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]{4,2000}", re.I)
LINK_CUE = re.compile(r"verif|activat|confirm", re.I)
ANCHOR_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.astimezone()


def _plausible(text: str, m: re.Match) -> bool:
    c = m.group(1)
    if not re.search(r"\d", c) or re.fullmatch(r"(19|20)\d\d", c):
        return False  # all-letter words are not codes; a bare year is not one either
    before, after = text[m.start() - 1:m.start()] if m.start() else "", text[m.end():m.end() + 2]
    if before and before in "/=?&#.:$@%+" or after[:1] in ("/", "=", "@", ":", "%") or re.match(r"[.,]\w", after):
        return False  # part of a URL, an amount, an address, a time or a decimal
    s, e = text.rfind(" ", 0, m.start()) + 1, text.find(" ", m.end())
    token = text[s:e if e >= 0 else len(text)].lower()
    return not ("://" in token or "www." in token)


def find(subject: str, sender_addr: str, body: str, received: datetime, now: datetime | None = None) -> dict | None:
    """A verification code from mail received within TTL: a cue in the subject, or within WINDOW characters of the
    candidate; the candidate has a digit and is not a year, a phone number piece, a time, an amount or part of a URL.
    First match wins. No AI."""
    now, received = _aware(now or datetime.now(timezone.utc)), _aware(received)
    if not -300 <= (now - received).total_seconds() <= TTL:  # 5 minutes of clock skew allowed into the future
        return None
    subject, body = str(subject or ""), str(body or "")[:20000]
    cue_subject = bool(CUE_RE.search(subject))
    for text in (subject, body):
        for m in CODE_RE.finditer(text):
            near = text[max(0, m.start() - WINDOW):m.end() + WINDOW]
            if _plausible(text, m) and (cue_subject or CUE_RE.search(near)):
                code, sender = m.group(1), (sender_addr or "").lower()
                return {"id": hashlib.sha1(f"{sender}|{subject}|{code}".encode()).hexdigest()[:10], "code": code,
                        "sender": sender, "domain": sender.rpartition("@")[2], "subject": subject[:200],
                        "received": received}
    return None


def mask(subject: str, body: str) -> tuple[str, str]:
    """subject and body with every code find() would accept (same cue rule, no age or sender check) as ******."""
    subject, body = str(subject or ""), str(body or "")
    cue = bool(CUE_RE.search(subject))

    def hide(text: str) -> str:
        out, last = [], 0
        for m in CODE_RE.finditer(text):
            if _plausible(text, m) and (cue or CUE_RE.search(text[max(0, m.start() - WINDOW):m.end() + WINDOW])):
                out += [text[last:m.start()], "******"]
                last = m.end()
        return "".join(out) + text[last:]

    return hide(subject), _hide_links(hide(body))


def _cued(text: str):
    """(url, start, end) of every link in plain text with a cue in the link, its line or the line before it."""
    lines, pos, out = text.split("\n"), 0, []
    for n, line in enumerate(lines):
        for m in URL_RE.finditer(line):
            if LINK_CUE.search(m.group(0)) or LINK_CUE.search(line) or (n and LINK_CUE.search(lines[n - 1])):
                out.append((m.group(0), pos + m.start(), pos + m.end()))
        pos += len(line) + 1
    return out


def _hide_links(text: str) -> str:
    """Verification links (find_links' rule) as [verification link]: they sign you in as surely as a code."""
    for _, a, b in reversed(_cued(text)):
        text = text[:a] + "[verification link]" + text[b:]
    return text


def find_links(subject: str, sender_addr: str, html: str, text: str, received: datetime,
               now: datetime | None = None) -> list[dict]:
    """Verification links in mail received within TTL: http(s) links with a cue (verify, activate, confirm) in the link
    or its anchor text (markup), or in the link, its line or the line before (plain text). No AI."""
    now, received = _aware(now or datetime.now(timezone.utc)), _aware(received)
    if not -300 <= (now - received).total_seconds() <= TTL:
        return []
    found = [u for u, label in ANCHOR_RE.findall(str(html or "")[:200000]) if LINK_CUE.search(u) or LINK_CUE.search(label)]
    found += [u for u, _, _ in _cued(str(text or "")[:200000])]
    out, sender = [], (sender_addr or "").lower()
    for url in dict.fromkeys(u.replace("&amp;", "&").rstrip(".,;") for u in found):
        host = (urlparse(url).hostname or "").lower() if URL_RE.fullmatch(url) else ""
        if host:
            out.append({"id": hashlib.sha1(f"{sender}|{url}".encode()).hexdigest()[:10], "url": url, "host": host,
                        "sender": sender, "domain": sender.rpartition("@")[2], "subject": str(subject or "")[:200],
                        "received": received})
    return out[:5]


def links(now: datetime | None = None) -> list[dict]:
    """Unexpired verification links for the page: {"id", "host", "domain", "subject", "age_s", "expires_s"}, never the
    link itself (it is a sign-in)."""
    now = _aware(now or datetime.now(timezone.utc))
    out = []
    with _LOCK:
        for k, c in list(_LINKS.items()):
            age = (now - c["received"]).total_seconds()
            if age > TTL:
                del _LINKS[k]
                continue
            out.append({k2: c[k2] for k2 in ("id", "host", "domain", "subject")} | {"age_s": max(0, int(age)),
                                                                                 "expires_s": int(TTL - age)})
    return sorted(out, key=lambda c: c["age_s"])


def link_url(lid: str) -> str | None:
    """The link itself, for accounts.py only (opened in the agent's window on the account's own host)."""
    with _LOCK:
        c = _LINKS.get(str(lid))
    return c["url"] if c and (datetime.now(timezone.utc) - _aware(c["received"])).total_seconds() <= TTL else None


def offer(msg, received: datetime | None = None) -> dict | None:
    """Keep the code in a fetched message (email_monitor._scan calls this for every message, before relevance).
    Only aligned DKIM/DMARC senders count: a spoofed 'security code' never shows. Never raises."""
    try:
        from .email_monitor import _body, _hdr, mail_authenticated

        sender = parseaddr(_hdr(msg, "From"))[1]
        if not mail_authenticated(msg.get_all("Authentication-Results") or [], sender):
            return None
        if received is None:
            try:
                received = parsedate_to_datetime(_hdr(msg, "Date"))
            except (TypeError, ValueError, IndexError):
                received = datetime.now(timezone.utc)
        from .email_monitor import _html

        hit = find(_hdr(msg, "Subject"), sender, _body(msg), received)
        found = find_links(_hdr(msg, "Subject"), sender, _html(msg), _body(msg), received)
        with _LOCK:
            if hit:
                _CODES[hit["id"]] = hit
            _LINKS.update((x["id"], x) for x in found)
        return hit
    except Exception:  # bookkeeping for a convenience: never costs the scan a message
        return None


def current(now: datetime | None = None) -> list[dict]:
    """Unexpired codes, newest first: {"id", "code", "domain", "sender", "subject", "age_s", "expires_s"}."""
    now = _aware(now or datetime.now(timezone.utc))
    out = []
    with _LOCK:
        for k, c in list(_CODES.items()):
            age = (now - c["received"]).total_seconds()
            if age > TTL:
                del _CODES[k]
                continue
            out.append({k2: c[k2] for k2 in ("id", "code", "domain", "sender", "subject")}
                       | {"age_s": max(0, int(age)), "expires_s": int(TTL - age)})
    return sorted(out, key=lambda c: c["age_s"])


def dismiss(cid: str) -> None:
    with _LOCK:
        _CODES.pop(str(cid), None)
        _LINKS.pop(str(cid), None)


def poll() -> list[dict]:
    """A quick look for a code: INBOX read-only, UIDs since yesterday (IMAP SINCE is a date in the server's zone), the
    last 30, received within TTL, under 1 MB; BODY.PEEK[] never marks anything read. Records no mail, classifies
    nothing. Runs inline from POST /api/codes/check (never start_task: task results are kept in memory)."""
    from .util import imap_login, imap_open, mail_login, mail_settings

    c, (pw, ready) = mail_settings(), mail_login()
    if not ready:
        raise SystemExit("email is not connected: Setup > Connect email, or lodestar email connect")
    box = imap_open(c["imap_host"], int(c["imap_port"] or 993), c.get("imap_mode"))
    try:
        imap_login(box, c["user"], pw)
        box.select("INBOX", readonly=True)
        since = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
        _, data = box.uid("search", None, f"(SINCE {since})")  # type: ignore[arg-type]
        now = datetime.now(timezone.utc)
        for uid in reversed(((data or [b""])[0] or b"").split()[-30:]):
            _, meta = box.uid("fetch", uid, "(INTERNALDATE RFC822.SIZE)")
            head = meta[0][0] if isinstance(meta[0], tuple) else meta[0]
            size, tt = re.search(rb"RFC822\.SIZE (\d+)", head or b""), imaplib.Internaldate2tuple(head or b"")
            received = datetime.fromtimestamp(time.mktime(tt)).astimezone() if tt else now
            if (size and int(size[1]) > MAX_POLL_SIZE) or (now - received).total_seconds() > TTL:
                continue
            _, raw = box.uid("fetch", uid, "(BODY.PEEK[])")
            if raw and isinstance(raw[0], tuple):
                offer(email.message_from_bytes(raw[0][1]), received)
    finally:
        try:
            box.logout()
        except Exception:  # ponytail: a failed goodbye changes nothing
            pass
    return current()
