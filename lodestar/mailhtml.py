"""The formatted copy of a received mail (pass 54): its text/html part, cleaned by an allowlist, with inline (cid:)
images embedded as data: URIs, so the Mail page and Inbox cards can show the email as it was written.

Safe by construction, twice: clean() keeps only formatting tags and attributes (no script, iframe, object, form,
svg, event handlers, javascript: or other non-web links), and the page shows the result in an iframe with
sandbox="allow-popups allow-popups-to-escape-sandbox" (no scripts, no same-origin) and a CSP that blocks every remote
load until you press Show images (tracking pixels stay off by default). Sign-in codes are masked like the text copy."""
import base64
import re
from html import escape
from html.parser import HTMLParser

MAX_HTML = 600_000
MAX_IMAGE, MAX_IMAGES = 1_500_000, 4_000_000  # bytes per inline image, all inline images together
TAGS = {"a", "abbr", "b", "big", "blockquote", "br", "caption", "center", "cite", "code", "col", "colgroup", "dd", "del",
        "div", "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li", "mark",
        "ol", "p", "pre", "q", "s", "small", "span", "strike", "strong", "style", "sub", "sup", "table", "tbody", "td",
        "tfoot", "th", "thead", "tr", "tt", "u", "ul", "html", "head", "body", "title"}
VOID = {"br", "hr", "img", "col"}
DROP = {"script", "iframe", "object", "embed", "form", "input", "button", "textarea", "select", "option", "svg", "math",
        "link", "meta", "base", "frame", "frameset", "applet", "audio", "video", "source", "template", "noscript"}
ATTRS = {"style", "href", "src", "alt", "title", "width", "height", "align", "valign", "colspan", "rowspan", "bgcolor",
         "color", "border", "cellpadding", "cellspacing", "face", "size", "dir", "lang", "class"}
LINK = re.compile(r"^(https?:|mailto:)", re.I)
IMG = re.compile(r"^(https?:|data:image/(png|jpe?g|gif|webp);base64,)", re.I)
BAD_CSS = re.compile(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding|@import", re.I)


class _Clean(HTMLParser):
    def __init__(self, cids: dict):
        super().__init__(convert_charrefs=False)
        self.out, self.skip, self.cids, self.style = [], 0, cids, False

    def handle_starttag(self, tag, attrs):
        if tag in DROP:
            self.skip += tag not in VOID and tag not in ("input", "link", "meta", "base", "source")
            return
        if self.skip or tag not in TAGS:
            return
        keep = []
        for k, v in attrs:
            k, v = k.lower(), (v or "")
            if k not in ATTRS:
                continue
            if k == "href" and not LINK.match(v.strip()):
                continue
            if k == "src":
                v = self.cids.get(v.strip()[4:].strip("<>"), "") if v.strip().lower().startswith("cid:") else v.strip()
                if not IMG.match(v):
                    continue
            if k == "style" and BAD_CSS.search(v):
                continue
            keep.append(f' {k}="{escape(v, quote=True)}"')
        if tag == "a":
            keep.append(' target="_blank" rel="noopener noreferrer"')
        if tag == "img" and not any(k.startswith(" src=") for k in keep):
            return  # an image whose source was refused (oversized, a cid: we lack, not http(s)) is left out
        self.style = tag == "style"
        self.out.append(f"<{tag}{''.join(keep)}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in DROP:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in TAGS and tag not in VOID:
            self.out.append(f"</{tag}>")
        if tag == "style":
            self.style = False

    def handle_data(self, data):
        if not self.skip:
            if self.style:  # raw CSS (entities are not decoded in <style>); nothing that could close the element
                if not BAD_CSS.search(data) and "<" not in data:
                    self.out.append(data)
                return
            self.out.append(escape(data, quote=False))

    def handle_entityref(self, name):
        if not self.skip:
            self.out.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip:
            self.out.append(f"&#{name};")


def _cids(msg) -> dict:
    """Content-ID -> data: URI for inline images, within the size caps."""
    out, total = {}, 0
    for p in msg.walk() if msg.is_multipart() else []:
        cid, ct = (p.get("Content-ID") or "").strip().strip("<>"), p.get_content_type()
        if not cid or ct not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            continue
        data = p.get_payload(decode=True) or b""
        if len(data) > MAX_IMAGE or total + len(data) > MAX_IMAGES:
            continue
        total += len(data)
        out[cid] = f"data:{ct};base64,{base64.b64encode(data).decode()}"
    return out


def clean(html: str, cids: dict | None = None) -> str:
    """The allowlisted markup of an email ('' for none)."""
    if not (html or "").strip():
        return ""
    c = _Clean(cids or {})
    c.feed(html[:MAX_HTML])
    c.close()
    return "".join(c.out)


def of(msg) -> str:
    """A parsed email.message -> its cleaned HTML ('' when it has no HTML part)."""
    from .email_monitor import _html

    return clean(_html(msg), _cids(msg))
