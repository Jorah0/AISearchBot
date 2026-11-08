"""Small helpers: HTTP fetch, HTML to text, JSON extraction, notifications."""
import http.client
import json
import re
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser

from .config import ALERTS, setting

UA = "Mozilla/5.0 (compatible; lodestar/0.1; +https://github.com/)"
MAIL_TIMEOUT = 60  # seconds per IMAP/SMTP socket operation: a server that accepts and goes quiet must not hang the loop


def redact_url(url) -> str:
    """url with every query value shown as ***: an API key passed as ?key=... never reaches an error, log or alert."""
    from urllib.parse import parse_qsl, urlsplit

    u = urlsplit(str(url or ""))
    if not u.query:
        return str(url or "")
    return u._replace(query="&".join(f"{k}=***" for k, _ in parse_qsl(u.query, keep_blank_values=True))).geturl()


def _check_url(url: str) -> None:
    """SSRF guard: http(s) only, and the host must not resolve to loopback, link-local, or private ranges.
    Set LODESTAR_ALLOW_PRIVATE_URLS=1 to watch an intranet careers page on purpose."""
    import os
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"only http(s) URLs can be fetched: {redact_url(url)[:80]}")
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


_opener = urllib.request.build_opener(_SafeRedirect, _PinnedHTTPHandler, _PinnedHTTPSHandler)
FETCH_MAX_BYTES = 25_000_000  # a big Greenhouse feed with content=true runs a few MB; nothing we read needs more


def fetch(url: str, timeout: int = 25, headers: dict | None = None, max_bytes: int | None = None) -> str:
    """GET url as text. timeout bounds each socket wait, and the whole read must finish within 4x timeout, so a server
    that trickles a byte at a time cannot hold the loop; more than max_bytes (FETCH_MAX_BYTES) is refused."""
    import time

    _check_url(url)
    cap, shown = max_bytes or FETCH_MAX_BYTES, redact_url(url)
    deadline = time.monotonic() + timeout * 4
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with _opener.open(req, timeout=timeout) as r:
            buf = bytearray()
            while chunk := r.read(65536):
                buf += chunk
                if len(buf) > cap:
                    raise ValueError(f"response from {shown[:80]} is larger than {cap // 1_000_000} MB")
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


def tls_context():
    """Certificate-verifying TLS for IMAP/SMTP. imaplib and smtplib default to an unverified context, which would hand
    the mailbox password to anyone able to intercept the connection."""
    import ssl

    return ssl.create_default_context()


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
            "smtp_mode": mode, "smtp_user": setting("SMTP_USER") or user}


def smtp_open(host: str, port: int, mode: str):
    """Certificate-verified SMTP: implicit TLS (ssl, port 465) or STARTTLS (port 587), with the mail socket timeout."""
    if mode != "starttls":
        return smtplib.SMTP_SSL(host, port, context=tls_context(), timeout=MAIL_TIMEOUT)
    s = smtplib.SMTP(host, port, timeout=MAIL_TIMEOUT)
    try:
        s.starttls(context=tls_context())  # raises SMTPNotSupportedError rather than falling back to plain text
    except BaseException:
        s.close()
        raise
    return s


def send_email(to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
    """Send as the connected account over SMTP and return the Message-ID. The only outbound-mail path in lodestar."""
    from email.utils import formatdate, make_msgid

    c, pw = mail_settings(), setting("IMAP_PASS")
    if not (c["user"] and pw):
        raise RuntimeError("sending needs a connected mailbox: Setup > Connect email, or lodestar email connect")
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, c["user"], to
    m["Date"], m["Message-ID"] = formatdate(localtime=True), make_msgid(domain=c["user"].rpartition("@")[2] or None)
    if in_reply_to:
        m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    with smtp_open(c["smtp_host"], c["smtp_port"], c["smtp_mode"]) as s:
        s.login(c["smtp_user"], pw)
        s.send_message(m)
    return m["Message-ID"]
