"""Small helpers: HTTP fetch, HTML to text, JSON extraction, notifications."""
import http.client
import json
import os
import re
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser

from .config import ALERTS, full_ai_check, setting

UA = "Mozilla/5.0 (compatible; lodestar/0.1; +https://github.com/)"
MAIL_TIMEOUT = 60  # seconds per IMAP/SMTP socket operation: a server that accepts and goes quiet must not hang the loop


_DTD_RE = re.compile(rb"<!(DOCTYPE|ENTITY)", re.I)


def parse_xml(text):
    """xml.etree root for untrusted feed XML. Any DOCTYPE/ENTITY declaration is refused (ValueError) before parsing:
    RSS, Atom and job feeds never need one, and refusing it rules out entity-expansion and external-entity tricks
    whatever the bundled expat version. Size is already capped by fetch()."""
    import xml.etree.ElementTree as ET

    raw = text.encode("utf-8", "replace") if isinstance(text, str) else bytes(text)
    if _DTD_RE.search(raw):
        raise ValueError("refused XML with a DOCTYPE or ENTITY declaration")
    return ET.fromstring(raw)


def redact_url(url) -> str:
    """url with every query value shown as ***: an API key passed as ?key=... never reaches an error, log or alert."""
    from urllib.parse import parse_qsl, urlsplit

    u = urlsplit(str(url or ""))
    if not u.query:
        return str(url or "")
    return u._replace(query="&".join(f"{k}=***" for k, _ in parse_qsl(u.query, keep_blank_values=True))).geturl()


# ponytail: these sites' terms forbid automated access; the capture bookmarklet reads a page the user has open instead
NEVER_FETCH = re.compile(r"(^|\.)(linkedin|indeed|glassdoor|ziprecruiter|simplyhired|teamblind)\.[a-z]{2,3}(\.[a-z]{2})?$")


def _check_url(url: str) -> None:
    """SSRF guard: http(s) only, never a NEVER_FETCH site, and the host must not resolve to loopback, link-local, or
    private ranges. Set LODESTAR_ALLOW_PRIVATE_URLS=1 to watch an intranet careers page on purpose (it never opens the
    NEVER_FETCH sites). Runs on the first URL and on every redirect hop."""
    import os
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"only http(s) URLs can be fetched: {redact_url(url)[:80]}")
    if NEVER_FETCH.search(u.hostname.lower().rstrip(".")):
        raise ValueError(f"Lodestar does not fetch pages from {u.hostname}: the site's terms forbid automated access. "
                         "Use the capture bookmarklet on the page, or paste the description.")
    if os.environ.get("LODESTAR_ALLOW_PRIVATE_URLS") == "1":
        return
    _public_addrs(u.hostname, u.port or (443 if u.scheme == "https" else 80))


def _public_addrs(host: str, port: int) -> list:
    """getaddrinfo for host, refusing the lot when any address is loopback, private, link-local or otherwise not public."""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"cannot resolve {host}: {e}") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"refusing to fetch a non-public address for {host} ({ip})")
    return infos


def _pinned_connect(address, timeout=None, source_address=None, **_):
    """http.client's connect, but to an address that passed the public-address check in this same lookup: a DNS name
    that answers a public IP for the check and 127.0.0.1 for the connect (rebinding) never reaches the second.
    TLS still verifies the certificate and sends SNI for the host name (http.client wraps this socket with it).
    ponytail: with a proxy configured the proxy resolves the name, so only the URL check applies then"""
    import os
    import socket

    if os.environ.get("LODESTAR_ALLOW_PRIVATE_URLS") == "1" or urllib.request.getproxies():
        return socket.create_connection(address, timeout, source_address)
    err = None
    for family, kind, proto, _, sa in _public_addrs(*address):
        s = socket.socket(family, kind, proto)
        try:
            if timeout is not None and timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                s.settimeout(timeout)
            if source_address:
                s.bind(source_address)
            s.connect(sa)
            return s
        except OSError as e:
            err = e
            s.close()
    raise err or OSError(f"cannot connect to {address[0]}")


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _pinned_connect


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _pinned_connect


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTP, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPS, req, context=self._context)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)  # every hop is re-validated, so a public host cannot bounce us to 127.0.0.1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # the 3xx surfaces as an HTTPError (Location in e.headers): the caller vets each hop itself


_opener = urllib.request.build_opener(_SafeRedirect, _PinnedHTTPHandler, _PinnedHTTPSHandler)
_opener_nofollow = urllib.request.build_opener(_NoRedirect, _PinnedHTTPHandler, _PinnedHTTPSHandler)
FETCH_MAX_BYTES = 25_000_000  # a big Greenhouse feed with content=true runs a few MB; nothing we read needs more


def fetch(url: str, timeout: int = 25, headers: dict | None = None, max_bytes: int | None = None, follow: bool = True,
          data: bytes | None = None) -> str:
    """GET url as text; a POST of `data` when given (urllib never re-sends a body on a redirect). timeout bounds each
    socket wait, and the whole read must finish within 4x timeout, so a server that trickles a byte at a time cannot
    hold the loop; more than max_bytes (FETCH_MAX_BYTES) is refused.
    follow=False: a redirect raises HTTPError 3xx with its Location, for callers that check each hop (robots, host)."""
    import time

    _check_url(url)
    cap, shown = max_bytes or FETCH_MAX_BYTES, redact_url(url)
    deadline = time.monotonic() + timeout * 4
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    try:
        with (_opener if follow else _opener_nofollow).open(req, timeout=timeout) as r:
            buf = bytearray()
            while chunk := r.read(65536):
                buf += chunk
                if len(buf) > cap:
                    raise ValueError(f"response from {shown[:80]} is larger than {cap / 1_000_000:g} MB")
                if time.monotonic() > deadline:
                    raise ValueError(f"response from {shown[:80]} took longer than {timeout * 4} s")
            return buf.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except Exception as e:  # urllib / http.client errors can quote the URL: scrub query values, keep the exception type
        if shown != url:
            e.args = tuple(a.replace(url, shown) if isinstance(a, str) else a for a in e.args)
            for k in ("reason", "filename", "url"):  # URLError.reason; HTTPError keeps the URL in filename / url
                v = getattr(e, k, None)
                if isinstance(v, str):
                    try:
                        setattr(e, k, v.replace(url, shown))
                    except AttributeError:  # a read-only property: nothing stored there to scrub
                        pass
        raise


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw))


def origin(url: str) -> str:
    """'scheme://host[:port]' with the default port dropped and the host lowercased: 'http://Acme.example:80/x' and
    'http://acme.example/' are one origin (one robots.txt, one site)."""
    import urllib.parse

    u = urllib.parse.urlparse(str(url or ""))
    host = (u.hostname or "").rstrip(".")
    host = f"[{host}]" if ":" in host else host
    port = u.port if u.port and u.port != {"http": 80, "https": 443}.get(u.scheme.lower()) else None
    return f"{u.scheme.lower()}://{host}" + (f":{port}" if port else "")


def robots_ok(url: str, cache: dict, get=None) -> bool:
    """robots.txt says a generic page may be fetched. One robots.txt per host per cycle (cache). 401/403 on robots.txt
    means keep out, any other HTTP error means no rules (the urllib.robotparser convention). get: the fetch to use
    (callers pass their own so their tests can fake it)."""
    import urllib.error
    from urllib.robotparser import RobotFileParser

    base = origin(url)
    if base not in cache:
        rp = RobotFileParser()
        try:
            rp.parse((get or fetch)(base + "/robots.txt", timeout=15).splitlines())
        except urllib.error.HTTPError as e:
            rp.disallow_all = e.code in (401, 403)
            rp.allow_all = not rp.disallow_all
        except Exception:  # ponytail: robots.txt unreachable; the page fetch itself reports the real problem
            rp.allow_all = True
        cache[base] = rp
    return cache[base].can_fetch("lodestar", url)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def strip_html(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def read_source(src: str, allow_files: bool = True) -> str:
    """URL -> page text; existing file -> contents (CLI only); otherwise the literal string."""
    from pathlib import Path

    if src.startswith(("http://", "https://")):
        return strip_html(fetch(src))
    p = Path(src)
    if allow_files and len(src) < 400 and p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
    # one word with a folder separator or a document extension is a mistyped path, not a job description: say so
    # (cli.main turns this into 'cannot open ...') instead of storing the path as the text
    if allow_files and not re.search(r"\s", src.strip()) and re.search(r"[\\/]|\.(txt|md|pdf|docx?|html?|rtf)$", src.strip(), re.I):
        import errno

        raise FileNotFoundError(errno.ENOENT, "no such file (give a URL, an existing file, or the text in quotes)", src)
    return src


def extract_json(text: str):
    """Pull the first JSON object/array out of an LLM reply (tolerates ``` fences and prose)."""
    text = re.sub(r"```(?:json)?", "", text)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in reply")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start : end + 1])


def slug(s: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "x"


def notify(msg: str) -> None:
    """Print, append to alerts.log, and email yourself if LODESTAR_NOTIFY_EMAIL is set."""
    line = f"[{datetime.now():%Y-%m-%d %H:%M}] {msg}"
    print(line)
    from .log import get

    get("alerts").info("%s", msg)
    with ALERTS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    to = setting("LODESTAR_NOTIFY_EMAIL")
    if not to:
        return
    try:
        send_email(to, f"[lodestar] {(msg.strip().splitlines() or [''])[0][:60]}", msg)  # a header may not hold a newline
    except Exception as e:  # ponytail: notification failure must never kill the watch loop
        print(f"  (email notify failed: {e})")


# Windows toast through PowerShell's WinRT bridge, shown under PowerShell's own AppUserModelID (Lodestar registers none).
# The text arrives in environment variables, never spliced into the script.
_TOAST_PS = r"""$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$t = $x.GetElementsByTagName('text')
[void]$t.Item(0).AppendChild($x.CreateTextNode($env:LS_TITLE))
[void]$t.Item(1).AppendChild($x.CreateTextNode($env:LS_BODY))
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))"""


def desktop_notify(title: str, body: str) -> bool:
    """Best-effort OS notification: Windows toast, macOS osascript, Linux notify-send. True if the OS accepted it.
    Never raises: a missing tool, a locked-down shell or a timeout is just False."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "LS_TITLE": str(title)[:120], "LS_BODY": str(body)[:400]}
    try:
        if sys.platform.startswith("win"):
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _TOAST_PS]
        elif sys.platform == "darwin":
            cmd = ["osascript", "-e", 'display notification (system attribute "LS_BODY") with title (system attribute "LS_TITLE")']
        else:
            cmd = ["notify-send", "--", env["LS_TITLE"], env["LS_BODY"]]
        r = subprocess.run(cmd, env=env, capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:  # ponytail: a notification is a nicety; nothing upstream may fail because of it
        return False


def tls_context(host: str | None = None):
    """Certificate-verifying TLS for IMAP/SMTP. imaplib and smtplib default to an unverified context, which would hand
    the mailbox password to anyone able to intercept the connection. MAIL_CAFILE (Proton Mail Bridge's exported
    certificate, or a self-hosted server's own CA) replaces the system store: only that certificate is trusted. On a
    loopback IP (Bridge on 127.0.0.1) the host-name match is skipped, since a self-signed Bridge certificate may name no
    IP; the certificate itself is still required, so this pins it rather than bypassing verification."""
    import ipaddress
    import os
    import ssl

    cafile = setting("MAIL_CAFILE")
    if not (cafile and os.path.isfile(cafile)):
        return ssl.create_default_context()
    ctx = ssl.create_default_context(cafile=cafile)
    try:
        if ipaddress.ip_address(str(host or "")).is_loopback:
            ctx.check_hostname = False  # verify_mode stays CERT_REQUIRED
    except ValueError:  # a host name keeps the full check
        pass
    return ctx


class run_lock:
    """Cross-process lock file (the desktop loop, a UI action and the scheduled task can all run a mail scan).
    `with run_lock("email"):` raises SystemExit if another holder is live; a lock older than `stale` seconds is stolen."""

    def __init__(self, name: str, stale: int = 1800):
        from .config import HOME

        self.path, self.stale = HOME / f".{name}.lock", stale

    def __enter__(self):
        import os
        import time

        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()  # a crashed holder; take over
                        continue
                except FileNotFoundError:
                    continue
                raise SystemExit(f"another {self.path.stem.lstrip('.')} run is in progress; skipped") from None
        raise SystemExit(f"could not take {self.path.name}")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def mail_settings() -> dict:
    """The connected mailbox (mailconn.connect stores it; Gmail servers when nothing is set). Never the password."""
    user = setting("IMAP_USER") or ""
    mode = (setting("SMTP_MODE") or "ssl").lower()
    return {"preset": setting("EMAIL_PRESET") or "", "user": user,
            "imap_host": setting("IMAP_HOST", "imap.gmail.com"), "imap_port": int(setting("IMAP_PORT") or 993),
            "smtp_host": setting("SMTP_HOST", "smtp.gmail.com"),
            "smtp_port": int(setting("SMTP_PORT") or (587 if mode == "starttls" else 465)),
            "imap_mode": (setting("IMAP_MODE") or "ssl").lower(),  # starttls: Proton Mail Bridge's default
            "smtp_mode": mode, "smtp_user": setting("SMTP_USER") or user, "cafile": setting("MAIL_CAFILE") or "",
            "auth": (setting("EMAIL_AUTH") or "password").lower()}  # oauth: signed in with Google or Microsoft


def mail_login(get=None) -> tuple[str | None, bool]:
    """(app password, a login is stored). The password is None when the mailbox signs in with Google or Microsoft
    (XOAUTH2 with a token minted from the stored refresh token). get: the caller's setting lookup."""
    get = get or setting
    oauth = (get("EMAIL_AUTH") or "password").lower() == "oauth"
    pw = None if oauth else get("IMAP_PASS")
    return pw, bool(get("IMAP_USER") and (pw or (oauth and get("OAUTH_REFRESH"))))


def imap_login(box, user: str, pw: str | None) -> None:
    """Sign an open IMAP connection in: app password, or XOAUTH2 when the mailbox is connected by provider sign-in."""
    if pw:
        box.login(user, pw)
    else:
        from . import oauth

        oauth.imap_auth(box, user)


def smtp_login(s, user: str, pw: str | None) -> None:
    """Same split for SMTP. With a provider sign-in the login name is the account address."""
    if pw:
        s.login(user, pw)
    else:
        from . import oauth

        oauth.smtp_auth(s, user)


def imap_open(host: str, port: int, mode: str | None = None):
    """Certificate-verified IMAP: implicit TLS (ssl, port 993) or STARTTLS (Proton Mail Bridge on 1143 by default), with
    the mail socket timeout. mode None: the stored IMAP_MODE. Every IMAP connection in lodestar opens here."""
    import imaplib

    if (mode or setting("IMAP_MODE") or "ssl").lower() != "starttls":
        return imaplib.IMAP4_SSL(host, port=port, ssl_context=tls_context(host), timeout=MAIL_TIMEOUT)
    box = imaplib.IMAP4(host, port, timeout=MAIL_TIMEOUT)
    try:
        box.starttls(ssl_context=tls_context(host))  # raises rather than falling back to plain text
    except BaseException:
        box.shutdown()
        raise
    return box


def smtp_open(host: str, port: int, mode: str):
    """Certificate-verified SMTP: implicit TLS (ssl, port 465) or STARTTLS (port 587), with the mail socket timeout."""
    if mode != "starttls":
        return smtplib.SMTP_SSL(host, port, context=tls_context(host), timeout=MAIL_TIMEOUT)
    s = smtplib.SMTP(host, port, timeout=MAIL_TIMEOUT)
    try:
        s.starttls(context=tls_context(host))  # raises SMTPNotSupportedError rather than falling back to plain text
    except BaseException:
        s.close()
        raise
    return s


def send_email(to: str, subject: str, body: str, in_reply_to: str | None = None, attachments=None) -> str:
    """Send as the connected account over SMTP and return the Message-ID. The only outbound-mail path in lodestar.
    attachments: Paths already validated by mailfiles.resolve (approvals._send)."""
    full_ai_check("sends mail")
    from email.utils import formatdate, make_msgid

    c, (pw, ready) = mail_settings(), mail_login()
    if not ready:
        raise RuntimeError("sending needs a connected mailbox: Setup > Connect email, or lodestar email connect")
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, c["user"], to
    m["Date"], m["Message-ID"] = formatdate(localtime=True), make_msgid(domain=c["user"].rpartition("@")[2] or None)
    if in_reply_to:
        m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    if attachments:
        from .mailfiles import attach

        attach(m, attachments)
    with smtp_open(c["smtp_host"], c["smtp_port"], c["smtp_mode"]) as s:
        smtp_login(s, c["smtp_user"] if pw else c["user"], pw)
        s.send_message(m)
    return m["Message-ID"]


# --- one home per small helper (pass 31): the modules' old private names are aliases of these -----------------------
def short_hash(s, n: int = 12) -> str:
    """sha1 of str(s), first n hex digits: fingerprints and cache keys, never security."""
    import hashlib

    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:n]


def load_json(v, default):
    """A JSON column value, or default when it is empty or not JSON."""
    try:
        return json.loads(v) if v else default
    except ValueError:
        return default


def word_in(word: str, text: str) -> bool:
    """word (or a phrase) as a whole word in text, any case: 'sales' is in 'Sales Manager', never in 'Wholesale'."""
    return bool(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text or "", re.I))


def utc_stamp() -> str:
    """Now in UTC as the database writes it (datetime('now')): 'YYYY-MM-DD HH:MM:SS'."""
    from datetime import timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def utc_to_local(ts) -> datetime:
    """A UTC time (a datetime('now') column, ISO text with Z or an offset, or an aware datetime) as a naive local
    datetime. Naive input is UTC."""
    from datetime import timezone

    d = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone().replace(tzinfo=None)


def write_atomic(path, text: str, private: bool = False, tries: int = 40) -> None:
    """Write-then-rename: a crash never leaves a torn file. private: owner-only on POSIX (Windows: the profile ACL).
    Windows refuses the rename while another thread reads the file at that instant, so it is retried briefly."""
    import time
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o666)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    for i in range(tries):
        try:
            return os.replace(tmp, path)
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.025)


# --- registrable domains: one rule for mail trust and company-page vetting (moved from email_monitor, pass 31) ---
TWO_PART_SUFFIXES = {"co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "me.uk", "com.au", "net.au", "org.au",
                     "co.nz", "org.nz", "co.jp", "ne.jp", "or.jp", "co.in", "net.in", "org.in", "com.br", "com.mx",
                     "com.ar", "com.cn", "com.hk", "com.sg", "com.tw", "com.tr", "co.kr", "co.il", "co.id", "com.my",
                     "com.ph", "co.th", "co.za", "com.ua", "com.pl", "com.es", "com.co", "com.pe", "com.vn", "com.sa"}


def registrable(dom: str) -> str:
    """The domain its owner registered, label plus public suffix: careers.globex.com -> globex.com, a.globex.co.uk ->
    globex.co.uk ('' for a bare name)."""
    parts = [p for p in (dom or "").lower().strip(".").split(".") if p]
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_PART_SUFFIXES else 2
    return ".".join(parts[-n:]) if len(parts) >= n else ""


def org_label(dom: str) -> str:
    """The label a domain's owner registered, hyphens dropped: careers.globex.com / globex.co.uk -> 'globex'. Only
    this label can name a company: globex.attacker.net -> 'attacker', globex-hiring.com -> 'globexhiring'."""
    return registrable(dom).split(".")[0].replace("-", "")
