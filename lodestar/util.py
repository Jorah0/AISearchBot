"""Small helpers: HTTP fetch, HTML to text, JSON extraction, notifications."""
import json
import re
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser

from .config import ALERTS, setting

UA = "Mozilla/5.0 (compatible; lodestar/0.1; +https://github.com/)"


def fetch(url: str, timeout: int = 25, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")


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


def read_source(src: str) -> str:
    """URL -> page text; existing file -> contents; otherwise the literal string."""
    from pathlib import Path

    if src.startswith(("http://", "https://")):
        return strip_html(fetch(src))
    p = Path(src)
    if p.is_file():
        return p.read_text(encoding="utf-8", errors="replace")
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
        send_email(to, f"[lodestar] {msg[:60]}", msg)
    except Exception as e:  # ponytail: notification failure must never kill the watch loop
        print(f"  (email notify failed: {e})")


def send_email(to: str, subject: str, body: str, in_reply_to: str | None = None) -> None:
    """Send as the IMAP account over SMTP (Gmail app password works). The only outbound-mail path in lodestar."""
    user, pw = setting("IMAP_USER"), setting("IMAP_PASS")
    if not (user and pw):
        raise RuntimeError("sending needs IMAP_USER + IMAP_PASS (SMTP uses the same login): lodestar vault set IMAP_PASS")
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, user, to
    if in_reply_to:
        m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    with smtplib.SMTP_SSL(setting("SMTP_HOST", "smtp.gmail.com"), 465) as s:
        s.login(user, pw)
        s.send_message(m)
