"""Job-alert emails (LinkedIn, Indeed, Glassdoor, ZipRecruiter) into All jobs. The user subscribes to alerts on those
sites; the mail monitor recognises an alert by its DKIM/DMARC-aligned sender domain PLUS a known alert sender address
(InMail notifications and 'application submitted' mail from the same domains still go the normal way) and this module
reads the listed jobs out of it with a structure-agnostic anchor parser. Nothing here fetches anything: alert links are
never opened (their sites' terms; tracking pixels and one-click sign-in tokens), redirects are unwrapped offline only,
and a stored link is treated as a secret (never logged or notified). Alert mails are not stored in the mail table."""
import re
import time
import urllib.parse
from collections import Counter
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

from . import db
from .util import notify

# domain suffixes match the authenticated From domain; alert_from = local parts of the alert senders (casefolded, +tag
# removed). Data: the Indeed, Glassdoor and ZipRecruiter senders and link shapes are unconfirmed until checked on a real
# alert (`lodestar email parse-alert FILE.eml` prints the sender so a missing one is a one-line fix here).
SITES = {
    "linkedin": {"domains": ("linkedin.com",), "label": "LinkedIn",
                 # not jobs-noreply: LinkedIn sends 'Your application was sent to X' from it (the classifier's mail)
                 "alert_from": ("jobalerts-noreply", "jobs-listings"),
                 "job": r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", "url": "https://www.linkedin.com/jobs/view/{id}/"},
    "indeed": {"domains": ("indeed.com", "indeedemail.com", "indeedmail.com"), "label": "Indeed",
               "alert_from": ("alert", "alerts", "jobalerts", "donotreply-jobalert"),
               "job": r"indeed\.[a-z.]+/.*?[?&](?:jk|vjk)=([0-9a-f]{10,20})", "url": "https://www.indeed.com/viewjob?jk={id}"},
    "glassdoor": {"domains": ("glassdoor.com", "glassdoor.co.uk", "glassdoor.ca", "glassdoor.de"), "label": "Glassdoor",
                  "alert_from": ("noreply", "jobalerts"),
                  "job": r"glassdoor\.[a-z.]+/.*?(?:jobListingId=|[?&]jl=)(\d+)", "url": None},
    "ziprecruiter": {"domains": ("ziprecruiter.com",), "label": "ZipRecruiter", "alert_from": ("alerts", "jobalerts"),
                     "job": r"ziprecruiter\.com/(?:c|k|ekm|km|jobs?|job-redirect)/", "url": None},
}
MAX_ROWS = 50
NOISE = {"view job", "view jobs", "apply", "apply now", "easy apply", "see all jobs", "see all", "view all jobs", "new",
         "promoted", "actively recruiting", "be an early applicant", "save", "save job", "unsubscribe", "view more jobs",
         "see more jobs", "manage alerts", "manage job alerts", "edit alert", "help", "privacy policy", "privacy",
         "terms", "user agreement", "settings", "job alert", "your job alert", "1-click apply", "quick apply", "learn more",
         "recommended for you", "jobs for you", "view details", "easily apply", "responsive employer",
         "urgently hiring", "new to you", "top applicant", "your profile matches this job"}
NOISE_RX = re.compile(r"©|\bunsubscribe\b|\bprivacy\b|\bcopyright\b|\ball rights reserved\b|\bmanage (?:your )?(?:job )?alerts?\b"
                      r"|\bthis email was (?:sent|intended)\b|\bjob alert\b|\byou are receiving\b|\bnotification settings\b"
                      r"|^\d+ new jobs?\b|^jobs? (?:you may|matching)\b", re.I)
REDIRECT_KEYS = ("url", "u", "dest", "redirect", "redirect_url", "target")
TRACKING = re.compile(r"^(?:utm_.*|trk.*|trackingid|refid|lipi|midtoken|midsig|eid|otptoken|mcid|cid|sid|tk|from|alid|"
                      r"src|source|campaign.*|click.*|email.*|ref|rf|ao|jrtk|acct)$", re.I)
REMOTE_RX = re.compile(r"\b(?:remote|hybrid|on-?site|work from home)\b", re.I)
CITY_RX = re.compile(r"^[A-Z][\w.'-]*(?: [A-Z][\w.'-]*)*, (?:[A-Z]{2}\b|[A-Z][a-z]+)")  # Austin, TX / Berlin, Germany
LEGAL_RX = re.compile(r",\s*(?:inc|llc|ltd|gmbh|corp|plc|bv)\.?$", re.I)  # 'Acme, Inc' names a company
AGO_RX = re.compile(r"\b(\d{1,2})\+?\s*(day|hour|week)s?\s+ago\b|\b(today|just posted|yesterday)\b", re.I)
SPLIT_RX = re.compile(r"\s+[·•|]\s+|\s+-\s+|\s*·\s*")
URL_RX = re.compile(r"https?://[^\s<>\"')\]]+")
BLOCK = {"p", "div", "td", "th", "tr", "li", "ul", "ol", "table", "tbody", "h1", "h2", "h3", "h4", "h5", "h6", "br",
         "section", "article", "header", "footer", "center", "hr"}


def site_of(addr: str) -> str | None:
    """The alert site whose domain (equal, or a subdomain) AND alert sender local part this From address matches; None
    otherwise. Only the address counts: never the display name or the subject. Trust (DKIM/DMARC) is checked apart."""
    if "@" not in (addr or ""):
        return None
    local, dom = addr.casefold().strip().rsplit("@", 1)
    local = local.split("+", 1)[0]
    for name, s in SITES.items():
        if any(dom == d or dom.endswith("." + d) for d in s["domains"]) and local in s["alert_from"]:
            return name
    return None


# ----------------------------------------------------------------------------- parsing
class _Walk(HTMLParser):
    """Anchors (href, [text segments]) and text nodes in document order. No classes, ids or table positions."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items, self.buf, self.a, self.skip = [], [], None, 0

    def _flush(self):
        t = " ".join("".join(self.buf).split())
        self.buf = []
        if not t:
            return
        if self.a is not None:
            self.a[1].append(t)
        else:
            self.items.append(("t", t))

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif tag == "a":
            self._flush()
            self.a = [dict(attrs).get("href") or "", []]
        elif tag in BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.a is not None:
            self._flush()
            self.items.append(("a", self.a[0], self.a[1]))
            self.a = None
        elif tag in BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def close(self):
        super().close()
        if self.a is not None:
            self.handle_endtag("a")
        self._flush()


def _noise(t: str) -> bool:
    t = " ".join(str(t or "").split())
    return not t or t.casefold().strip(" .:!>»›") in NOISE or bool(NOISE_RX.search(t))


def unwrap(href: str) -> str:
    """A redirector's target when it sits in a query parameter (url=, u=, dest=, redirect=; at most 2 levels), offline.
    Opaque click trackers stay as they are: they are never fetched."""
    u = str(href or "").strip()
    for _ in range(2):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
        nxt = next((v[0] for k in REDIRECT_KEYS for v in [q.get(k)] if v and v[0].startswith(("http://", "https://"))), None)
        if not nxt:
            break
        u = nxt
    return u


def canonical(site: str, href: str, job_id: str | None) -> str:
    """The site's own job URL when an id was read; otherwise the link with tracking parameters removed (unknown
    parameters stay: a broken link is worse than a long one). Only https is kept; '' otherwise."""
    tmpl = SITES[site]["url"]
    if job_id and tmpl:
        return tmpl.format(id=job_id)
    u = urllib.parse.urlparse(str(href or ""))
    if u.scheme != "https" or not u.hostname:
        return ""
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q), fragment=""))


def _posted(t: str, today: date) -> str:
    m = AGO_RX.search(t)
    if not m:
        return ""
    if m.group(3):
        return (today - timedelta(days=1 if m.group(3).lower() == "yesterday" else 0)).isoformat()
    n, unit = int(m.group(1)), m.group(2).lower()
    return (today - timedelta(days=n * 7 if unit == "week" else n if unit == "day" else 0)).isoformat()


def _fields(title: str, lines: list[str], today: date) -> dict:
    """salary / location / posted / company from the short text lines after a job's title."""
    from .resume import salary_mentions

    out = {"title": title, "company": "", "location": "", "salary": "", "date": ""}
    parts = []
    for ln in lines:
        if not out["salary"] and (s := salary_mentions(ln)):  # before splitting: '$120,000 - $140,000' is one figure
            out["salary"] = s[0]
            ln = ln.replace(s[0], " ")
        parts += [p.strip(" ,;") for p in SPLIT_RX.split(ln) if p.strip(" ,;")]
    rest = []
    for p in parts:
        if p.casefold() == title.casefold() or _noise(p):
            continue
        if not out["date"] and (d := _posted(p, today)):
            out["date"] = d
        elif not out["location"] and (REMOTE_RX.search(p) or CITY_RX.search(p)) and not LEGAL_RX.search(p):
            out["location"] = p[:200]
        elif not AGO_RX.search(p):
            rest.append(p)
    out["company"] = (rest[0] if rest else "")[:200]
    return out


def _groups_html(site: str, html: str) -> list[tuple[str, str, list]]:
    """[(url, title, [context lines])] per job, in document order, from the HTML part: job anchors grouped by job id
    (or cleaned link), the title their longest first line, the context the text up to the next job's first anchor."""
    w = _Walk()
    w.feed(html or "")
    w.close()
    items = w.items
    rx = re.compile(SITES[site]["job"], re.I)
    anchors = [(i, unwrap(it[1]), it[2]) for i, it in enumerate(items) if it[0] == "a"]
    keyed = []  # (item index, group key, url, id)
    for i, href, _ in anchors:
        m = rx.search(href)
        if m:
            jid = m.group(1) if m.groups() else None
            keyed.append((i, jid or canonical(site, href, None) or href, href, jid))
    if not keyed:  # opaque click trackers: anchors on a site host or the mail's own link host, grouped by their text
        hosts = Counter((urllib.parse.urlparse(h).hostname or "").lower() for _, h, _ in anchors if h.startswith("http"))
        top = hosts.most_common(1)[0][0] if hosts else ""
        doms = SITES[site]["domains"]
        for i, href, segs in anchors:
            host = (urllib.parse.urlparse(href).hostname or "").lower()
            text = next((s for s in segs if not _noise(s)), "")
            if text and 3 <= len(text) <= 120 and (host == top or any(host == d or host.endswith("." + d) for d in doms)):
                keyed.append((i, text.casefold(), href, ""))  # "": no id; the link is kept minus its token parameters
    order, by = [], {}
    for i, k, href, jid in keyed:
        if k not in by:
            by[k] = {"first": i, "idx": [], "href": href, "id": jid}
            order.append(k)
        by[k]["idx"].append(i)
    starts = sorted(by[k]["first"] for k in order)
    job_idx = {i for k in order for i in by[k]["idx"]}
    out = []
    for k in order:
        g = by[k]
        texts = [s for i in g["idx"] for s in items[i][2] if not _noise(s)]
        title = max((items[i][2][0] for i in g["idx"] if items[i][2] and not _noise(items[i][2][0])), key=len, default="")
        title = title or max(texts, key=len, default="")
        nxt = next((s for s in starts if s > g["first"]), len(items))
        ctx = [s for i in g["idx"] for s in items[i][2][1:]]  # a card-wide anchor: its later lines are context
        for i, it in enumerate(items[g["first"] + 1:nxt], g["first"] + 1):
            if it[0] == "t":
                ctx.append(it[1])
            elif i not in job_idx:  # a company-page link names the company
                ctx += it[2]
        ctx = [c for c in ctx if len(c) <= 120 and not _noise(c) and c != title][:6]
        out.append((canonical(site, g["href"], g["id"] or None), title, ctx))  # a tracker loses its sign-in token too
    return out


def _groups_text(site: str, text: str) -> list[tuple[str, str, list]]:
    """Plain-text fallback: each line holding a job link is one job; the up-to-3 non-empty lines above it are title,
    company and location."""
    rx = re.compile(SITES[site]["job"], re.I)
    doms = SITES[site]["domains"]
    out, above = [], []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        urls = URL_RX.findall(ln)
        hit = next((u for u in urls if rx.search(unwrap(u)) or any(d in (urllib.parse.urlparse(u).hostname or "") for d in doms)), None)
        if hit:
            href = unwrap(hit)
            m = rx.search(href)
            lines = [x for x in above[-3:] if not _noise(x)]
            if lines:
                out.append((canonical(site, href, m.group(1) if m and m.groups() else None), lines[0], lines[1:]))
            above = []
        elif urls:
            above = []
        elif ln:
            above.append(ln)
    return out


def parse(site: str, html: str, text: str = "", today: date | None = None) -> list[dict]:
    """The listed jobs as listing dicts (title, company, location, salary, date, url, source). HTML first, plain text
    when the HTML has no job anchor. Each needs a title of 3+ characters and a company; at most MAX_ROWS."""
    today = today or date.today()
    groups = _groups_html(site, html) if html else []
    if not groups:
        groups = _groups_text(site, text)
    rows, seen = [], set()
    for url, title, ctx in groups:
        f = _fields(" ".join(title.split())[:300], ctx, today)
        if len(f["title"]) < 3 or not f["company"] or (url and url in seen):
            continue
        seen.add(url)
        rows.append(f | {"url": url, "desc": "", "source": f"{site}_alert"})
    return rows[:MAX_ROWS]


# ----------------------------------------------------------------------------- the mail monitor's side
def ingest(site: str, html: str, text: str, msgid: str = "", date_hdr: str = "") -> list[dict]:
    """Store an authenticated alert mail's jobs in All jobs (merged with every other source's copy). One notify per
    mail, never with a link; a listing_seen event on each tracked job it names (once per job and Message-ID). Returns
    the rows not seen before, for judge() after the mailbox is closed."""
    from . import listings

    s = SITES[site]
    try:
        day = parsedate_to_datetime(date_hdr).date()
    except (TypeError, ValueError, IndexError):
        day = date.today()
    rows = parse(site, html, text, day)
    db.meta_set(f"alerts:{site}:last", int(time.time()))
    db.meta_set(f"alerts:{site}:n", len(rows))
    if not rows:
        key = f"alertfail:{site}:{date.today().isoformat()}"
        if not db.seen(key):
            notify(f"{s['label']} alert could not be read (its format may have changed). Run `lodestar email parse-alert "
                   f"FILE.eml` to see what was found.")
            db.mark_seen(key)
        return []
    for h in {urllib.parse.urlparse(r["url"]).hostname for r in rows if r["url"]}:
        db.mark_seen(f"alerthost:{h.lower()}")  # web_monitor.no_fetch: a host alert mail linked to is never opened
    stored = listings.store(rows, source=f"{site}_alert")
    fresh = []
    for r, x in zip(rows, stored):
        if not x:
            continue
        if x["new"]:
            fresh.append(r | {"id": x["id"], "key": x["key"], "first_seen": x["first_seen"]})
        if x["job_id"]:
            seen = f"alertseen:{x['job_id']}:{msgid or r['url']}"
            if not db.seen(seen):
                db.add_event(x["job_id"], "listing_seen", f"in {s['label']} alert {day.isoformat()}: {r['title']}")
                db.mark_seen(seen)
    scored = [((x["fit"] or {}).get("score") or 0, r) for r, x in zip(rows, stored) if x]
    best = max(scored, key=lambda t: t[0]) if scored else None
    tail = f", best fit {best[0]} {best[1]['title']} @ {best[1]['company']}" if best and best[0] else ""
    notify(f"{s['label']} alert: {len(rows)} jobs ({len(fresh)} new){tail}")  # no URL: it may carry a sign-in token
    return fresh


def judge(fresh: list[dict]) -> None:
    """auto_track over new alert rows (fit, AI on the best few): run by the mail monitor after the IMAP session closed,
    so AI calls never hold the mailbox open. quiet: one notify per mail was enough. ponytail: a crash between ingest
    and judge leaves rows unjudged in All jobs (a watch hit or a manual 'AI fit' covers them); upgrade: a judged column."""
    from .web_monitor import _hits

    rows = [r for r in fresh if r.get("url")]
    if rows:
        try:
            _hits("job alerts", rows, quiet=True)
        except (Exception, SystemExit) as e:
            print(f"  job alerts: judging skipped: {e}")


def parse_file(raw: bytes, trust: bool = False) -> dict:
    """`lodestar email parse-alert FILE.eml`: what the parser reads from a saved alert, changing nothing. {sender,
    local, site, authenticated, rows}. trust skips the DKIM/DMARC check (a saved file's headers may be stripped)."""
    import email
    from email.utils import parseaddr

    from .email_monitor import _hdr, _html, _text, mail_authenticated

    msg = email.message_from_bytes(raw)
    addr = parseaddr(_hdr(msg, "From"))[1]
    site = site_of(addr)
    auth = trust or mail_authenticated(msg.get_all("Authentication-Results") or [], addr)
    try:
        day = parsedate_to_datetime(_hdr(msg, "Date")).date()
    except (TypeError, ValueError, IndexError):
        day = None
    rows = parse(site, _html(msg), _text(msg), day) if site and auth else []
    return {"sender": addr, "local": addr.split("@", 1)[0].casefold() if "@" in addr else "", "site": site,
            "authenticated": auth, "rows": rows}
