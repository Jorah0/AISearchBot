"""Watch career pages for changes, poll public job-board feeds of companies you name, and query free job APIs (no keys
needed) for new listings. Search filters, cross-source de-dup, stale/repost signals and H-1B sponsor hints live here."""
import hashlib
import html
import re
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone
from functools import lru_cache

from . import ai, db, settings
from .config import SNAPSHOTS
from .util import fetch, fetch_json, notify, strip_html

GHOST_SHOW, GHOST_SKIP = 30, 60  # "possibly stale" chip from 30; auto_track leaves listings at 60+ alone


def _urls(j) -> list[str]:
    return j.get("urls") or [j["url"]]


def _hits(label: str, new: list[dict]) -> list[str]:
    """New listings from a saved search or a watched company: alert once each, AI-judge (auto_track), and mark them seen
    only once judged, so a failing provider retries next cycle instead of losing them."""
    alerts = []
    for j in new:  # alert once per listing; only the AI judgement is retried while it keeps failing
        if not db.seen(f"alerted:{j['url']}"):
            notify(f"NEW LISTING [{label}]: {j['title']} @ {j['company']} ({j['location']}) {j['url']}")
            db.mark_seen(f"alerted:{j['url']}")
            alerts.append(j["url"])
    judging = bool(new) and settings.enabled("auto_track") and bool(ai.available())
    if judging:
        try:  # AI judgement -> approvals inbox (or straight into the tracker when auto_track is auto)
            from .apply import auto_track

            for j in auto_track(new):
                notify(f"FIT {j['score']}: {j['title']} @ {j['company']} -> {j['proposal'].get('status')}")
        except (Exception, SystemExit) as e:  # ai signals "no key / model rejected" with SystemExit
            print(f"  auto_track: {e}")
    for j in new:  # rank() scores in place; an unjudged listing stays new and is retried next cycle
        if not judging or "score" in j:
            for u in _urls(j):
                db.mark_seen(f"listing:{u}")
    return alerts


def _robots_ok(url: str, cache: dict) -> bool:
    """robots.txt says a generic page may be fetched. One robots.txt per host per cycle (cache). 401/403 on robots.txt
    means keep out, any other HTTP error means no rules (the urllib.robotparser convention)."""
    from urllib.robotparser import RobotFileParser

    u = urllib.parse.urlparse(url)
    base = f"{u.scheme}://{u.netloc}"
    if base not in cache:
        rp = RobotFileParser()
        try:
            rp.parse(fetch(base + "/robots.txt", timeout=15).splitlines())
        except urllib.error.HTTPError as e:
            rp.disallow_all = e.code in (401, 403)
            rp.allow_all = not rp.disallow_all
        except Exception:  # ponytail: robots.txt unreachable; the page fetch itself reports the real problem
            rp.allow_all = True
        cache[base] = rp
    return cache[base].can_fetch("lodestar", url)


def check_watches() -> list[str]:
    """Run every saved watch and watched company. 'search:<query>' watches hit the job APIs with their saved filters;
    companies poll their public job-board feed (one request each); anything else is a page diff, if robots.txt allows."""
    SNAPSHOTS.mkdir(exist_ok=True)
    alerts, robots = [], {}
    for w in db.watches():
        if w["url"].startswith("search:"):
            q = w["url"][7:]
            new = search(q, keywords=w["keywords"] or "", only_new=True, mark=False, **db.watch_filters(w))
            alerts += _hits(q, new)
            db.update_watch(w["id"], "")
            continue
        if not _robots_ok(w["url"], robots):
            msg = f"SKIPPED watch #{w['id']} {w['url']}: the site's robots.txt does not allow automated fetching of this page"
            if db.seen(f"robots:{w['url']}"):
                print(f"  {msg}")
            else:  # alert once; the watch stays so it resumes if the site changes its rules
                notify(msg)
                db.mark_seen(f"robots:{w['url']}")
            continue
        try:
            text = strip_html(fetch(w["url"]))
        except Exception as e:
            print(f"  watch #{w['id']} fetch failed: {e}")
            continue
        h = hashlib.sha256(text.encode()).hexdigest()
        snap = SNAPSHOTS / f"{w['id']}.txt"
        if w["last_hash"] and h != w["last_hash"]:
            old = set(snap.read_text(encoding="utf-8").splitlines()) if snap.is_file() else set()
            added = [ln for ln in text.splitlines() if ln.strip() and ln not in old]
            kws = [k.strip().lower() for k in (w["keywords"] or "").split(",") if k.strip()]
            hits = [ln for ln in added if not kws or any(k in ln.lower() for k in kws)]
            if hits:
                notify(f"CHANGED {w['url']}:\n  " + "\n  ".join(hits[:15]))
                alerts.append(w["url"])
        snap.write_text(text, encoding="utf-8")
        db.update_watch(w["id"], h)
    for c in db.companies():
        try:
            jobs = feed(c["vendor"], c["slug"], c["name"])
        except Exception as e:
            print(f"  company #{c['id']} {c['vendor']}:{c['slug']} failed: {e}")
            db.update_company(c["id"], str(e)[:200])
            continue
        base = f"baseline:{c['vendor']}:{c['slug']}"
        if db.seen(base):
            alerts += _hits(c["name"], annotate([j for j in refine(jobs, keywords=c["keywords"] or "") if not _seen(j)]))
        else:  # first good poll: what is already open is the baseline (one summary line); only later postings alert
            for j in annotate(jobs):
                for u in _urls(j):
                    db.mark_seen(f"listing:{u}")
            notify(f"WATCHING {c['name']}: {len(jobs)} open role(s) now; new postings alert from the next cycle")
            db.mark_seen(base)
        db.update_company(c["id"], "")
    return alerts


# --- public job-board feeds (Greenhouse, Lever, Ashby) ----------------------
FEEDS = {"greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
         "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
         "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"}
ATS_HOSTS = {"boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse", "jobs.lever.co": "lever",
             "jobs.ashbyhq.com": "ashby"}
NO_FEED = {"myworkdayjobs.com": "Workday", "myworkdaysite.com": "Workday", "workday.com": "Workday", "taleo.net": "Taleo",
           "icims.com": "iCIMS"}
NO_FEED_NOTE = ("Workday, Taleo and iCIMS have no public job feed: add the careers page as a page watch instead "
                "(lodestar watch add URL, or Monitor > Watches).")
SLUG = r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}"


def detect_ats(src) -> tuple[str, str] | None:
    """('greenhouse'|'lever'|'ashby', slug) for a board or posting URL (boards.greenhouse.io/<slug>,
    job-boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, jobs.ashbyhq.com/<slug>) or 'vendor:slug'; else None."""
    s = str(src or "").strip()
    m = re.fullmatch(rf"(greenhouse|lever|ashby):({SLUG})", s, re.I)
    if m:
        return m.group(1).lower(), m.group(2)
    u = urllib.parse.urlparse(s if "://" in s else "https://" + s)
    vendor = ATS_HOSTS.get((u.hostname or "").lower())
    if not vendor or u.scheme not in ("http", "https"):
        return None
    parts = [p for p in u.path.split("/") if p]
    slug = (urllib.parse.parse_qs(u.query).get("for") or [""])[0] if parts[:1] == ["embed"] else (parts[0] if parts else "")
    return (vendor, slug) if re.fullmatch(SLUG, slug) else None


def add_company(src: str, name: str = "", keywords: str = "") -> dict:
    """Watch a company's public job board: a careers / posting URL or 'vendor:slug'. Validated here for CLI and web."""
    s, name, keywords = str(src or "").strip(), " ".join(str(name or "").split()), str(keywords or "").strip()
    found = detect_ats(s)
    if not found:
        host = (urllib.parse.urlparse(s if "://" in s else "https://" + s).hostname or "").lower()
        vendor = next((v for h, v in NO_FEED.items() if host == h or host.endswith("." + h)), None)
        raise SystemExit((f"{vendor} detected. " if vendor else f"not a Greenhouse, Lever or Ashby board: {s[:80]}. ")
                         + NO_FEED_NOTE + " Supported: boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, "
                         "jobs.ashbyhq.com/<slug>, or greenhouse:<slug> / lever:<slug> / ashby:<slug>.")
    if len(name) > 80 or len(keywords) > 200:
        raise SystemExit("name: at most 80 characters; keywords: at most 200")
    vendor, slug = found
    name = name or slug.replace("-", " ").replace("_", " ").title()
    return {"id": db.add_company(vendor, slug, name, keywords), "vendor": vendor, "slug": slug, "name": name}


def _feed_listing(vendor, slug, ats_id, **kw) -> dict:
    return _listing(**kw, source=vendor) | {"ats_id": str(ats_id or ""), "ats_feed": f"{vendor}:{slug}"}


def _greenhouse(slug, company):
    from .resume import salary_mentions

    out = []
    for j in fetch_json(FEEDS["greenhouse"].format(slug=urllib.parse.quote(slug))).get("jobs", []):
        text = strip_html(html.unescape(j.get("content") or ""))  # the board API sends entity-escaped HTML
        out.append(_feed_listing("greenhouse", slug, j.get("id"), title=j.get("title"), company=j.get("company_name") or company,
                                 url=j.get("absolute_url"), location=(j.get("location") or {}).get("name"),
                                 salary=(salary_mentions(text) or [""])[0],  # pay often sits past the 3,000-char cut
                                 date=j.get("first_published") or j.get("updated_at"), desc=text))
    return out


def _with_workplace(loc, kind) -> str:
    """'Berlin' + 'remote' -> 'Berlin (remote)', so the location and remote filters see what the feed says."""
    loc, kind = str(loc or "").strip(), str(kind or "").strip().lower()
    if kind not in ("remote", "hybrid") or kind in loc.lower():
        return loc
    return f"{loc} ({kind})" if loc else kind


def _lever(slug, company):
    d = fetch_json(FEEDS["lever"].format(slug=urllib.parse.quote(slug)))
    out = []
    for j in d if isinstance(d, list) else []:
        cat = j.get("categories") or {}
        parts = [j.get("descriptionPlain") or strip_html(j.get("description") or "")]
        for sec in j.get("lists") or []:
            parts += [sec.get("text") or "", strip_html(sec.get("content") or "")]
        parts.append(j.get("additionalPlain") or "")
        sr, sal = j.get("salaryRange") or {}, ""
        if sr.get("min") and sr.get("max"):
            per = str(sr.get("interval") or "")
            sal = f"{sr.get('currency') or ''} {sr['min']}-{sr['max']}".strip() + ("" if not per or "year" in per else f" ({per})")
        ts = j.get("createdAt")
        posted = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d") if isinstance(ts, (int, float)) else ""
        out.append(_feed_listing("lever", slug, j.get("id"), title=j.get("text"), company=company, url=j.get("hostedUrl"),
                                 location=_with_workplace(cat.get("location"), j.get("workplaceType")), salary=sal,
                                 date=posted, desc="\n\n".join(p for p in parts if p)))
    return out


def _ashby(slug, company):
    out = []
    for j in fetch_json(FEEDS["ashby"].format(slug=urllib.parse.quote(slug))).get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        kind = j.get("workplaceType") or ("remote" if j.get("isRemote") else "")
        out.append(_feed_listing("ashby", slug, j.get("id"), title=j.get("title"), company=company, url=j.get("jobUrl"),
                                 location=_with_workplace(j.get("location"), kind),
                                 salary=comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary") or "",
                                 date=j.get("publishedAt"), desc=j.get("descriptionPlain") or j.get("descriptionHtml") or ""))
    return out


FEED_PARSERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def feed(vendor: str, slug: str, company: str) -> list[dict]:
    """Every live posting on a company's public board (one request), as the same listing dicts the job APIs give."""
    return [j for j in FEED_PARSERS[vendor](slug, company) if j["url"]]


def _posting_id(url) -> str:
    """The id a posting URL carries: Greenhouse gh_jid= / embed token=, else the last path segment (/jobs/123, lever or
    ashby uuid) ignoring a trailing /apply or /application. "" for a board root (/<slug>) that names no posting."""
    u = urllib.parse.urlparse(str(url or ""))
    q = urllib.parse.parse_qs(u.query)
    if q.get("gh_jid") or q.get("token"):
        return (q.get("gh_jid") or q["token"])[0]
    parts = [p for p in u.path.split("/") if p]
    while parts and parts[-1].lower() in ("apply", "application"):
        parts.pop()
    return parts[-1] if len(parts) > 1 else ""


def recheck_postings(now: datetime | None = None) -> list[int]:
    """At most weekly: saved, not-yet-applied jobs from a Greenhouse / Lever / Ashby feed are looked up in the live feed
    (one request per feed). A posting that is gone is recorded on the job and withdrawing it is PROPOSED (Inbox, always
    waits); the status never changes here. Returns the ids proposed."""
    from . import approvals

    now = now or datetime.now()
    week = f"feedcheck:{now:%G-%V}"
    if db.seen(week) or not settings.enabled("posting_check"):
        return []
    groups: dict[tuple[str, str], list] = {}
    for j in db.list_jobs("saved"):
        f = tuple(j["ats_feed"].split(":", 1)) if j["ats_feed"] else detect_ats(j["url"])
        if f and j["url"]:
            groups.setdefault(f, []).append(j)
    proposed = []
    for (vendor, slug), jobs in groups.items():
        try:
            live = feed(vendor, slug, "")
        except Exception as e:  # unreachable or renamed board: try again next week, never guess
            print(f"  posting check {vendor}:{slug}: {e}")
            continue
        if not live:  # ponytail: an empty board is more often a renamed slug than every role closed at once
            continue
        ids = {j["ats_id"] for j in live} | {_posting_id(j["url"]) for j in live}
        for j in jobs:
            pid = _posting_id(j["url"])
            # a URL naming no posting cannot be proven gone
            if not pid or pid in ids or any(e["kind"] == "posting_removed" for e in db.events(j["id"])):
                continue
            db.add_event(j["id"], "posting_removed", f"not in the {vendor} feed for {slug} on {now:%Y-%m-%d}")
            approvals.propose("posting_check", "set_status", {"job_id": j["id"], "status": "withdrawn", "note": "posting removed"},
                              f"withdraw #{j['id']} {j['company']} - {j['title']} (posting removed from {vendor})", j["id"],
                              force_pending=True)
            proposed.append(j["id"])
    db.mark_seen(week)
    return proposed


# --- free job APIs ----------------------------------------------------------
def _listing(title, company, url, location="", salary="", date="", desc="", source=""):
    return dict(title=title or "", company=company or "", url=url or "", location=location or "", salary=salary or "",
                date=(date or "")[:10], desc=strip_html(desc or "")[:3000], source=source)


def jd_with_salary(j: dict) -> str:
    """The listing text to store as the job description. The jobs table has no salary column, so a listing's salary
    field rides along as a first line that resume.salary_mentions reads (app.js saveListing builds the same line)."""
    return (f"Salary (from {j.get('source') or 'listing'}): {j['salary']}\n\n" if j.get("salary") else "") + (j.get("desc") or "")


def listing_fields(j: dict) -> dict:
    """Tracker fields a listing carries beyond its JD (db.add_job derives pay and remote from the JD). Lenient: a value
    the tracker would reject is dropped, so a messy API field never blocks tracking the job."""
    posted = _day(j.get("posted_at") or j.get("date"))
    out = {"location": " ".join(str(j.get("location") or "").split())[:120], "posted_at": posted.isoformat() if posted else ""}
    if db.ATS_FEED_RE.fullmatch(str(j.get("ats_feed") or "")):  # lets the weekly posting check find it again
        out["ats_feed"] = j["ats_feed"]
    return out


def _day(s) -> date | None:
    """'2026-11-02...' -> date; anything else None."""
    s = str(s or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
    except ValueError:
        return None


def _remotive(q):
    d = fetch_json(f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(q)}&limit=30")
    return [_listing(j["title"], j["company_name"], j["url"], j.get("candidate_required_location"), j.get("salary"),
                     j.get("publication_date"), j.get("description"), "remotive") for j in d.get("jobs", [])]


def _arbeitnow(q):
    d = fetch_json(f"https://www.arbeitnow.com/api/job-board-api?search={urllib.parse.quote(q)}")
    return [_listing(j["title"], j["company_name"], j["url"], j.get("location"), "", "", j.get("description"), "arbeitnow")
            for j in d.get("data", [])]


def _remoteok(q):
    d = fetch_json("https://remoteok.com/api")
    words = q.lower().split()
    out = []
    for j in (d or [])[1:]:  # element 0 is a legal notice
        blob = f"{j.get('position', '')} {' '.join(j.get('tags', []))} {j.get('company', '')}".lower()
        if all(w in blob for w in words):
            sal = f"{j.get('salary_min', '')}-{j.get('salary_max', '')}".strip("-")
            out.append(_listing(j.get("position"), j.get("company"), j.get("url"), j.get("location"), sal, j.get("date"),
                                j.get("description"), "remoteok"))
    return out


def _hn(q):
    """Hacker News 'Who is hiring?' (monthly thread) via the Algolia API. Top-level comments are the postings and
    conventionally start with 'Company | Role | Location'."""
    s = fetch_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query="
                   + urllib.parse.quote('"Ask HN: Who is hiring"') + "&hitsPerPage=1")
    hits = s.get("hits") or []
    if not hits:
        return []
    sid = str(hits[0]["objectID"])
    words = q.lower().split()
    out = []
    for page in range(3):  # ponytail: 600 newest postings is plenty for a keyword search
        c = fetch_json(f"https://hn.algolia.com/api/v1/search_by_date?tags=comment,story_{sid}&hitsPerPage=200&page={page}")
        for h in c.get("hits", []):
            if str(h.get("parent_id")) != sid:
                continue  # a reply, not a posting
            text = strip_html(h.get("comment_text") or "")
            if not all(w in text.lower() for w in words):
                continue
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            header = next((ln for ln in lines[:4] if "|" in ln), lines[0] if lines else "")[:200]
            parts = [p.strip() for p in header.split("|")]
            if len(parts) >= 2:
                company, title = parts[0] or h.get("author", ""), parts[1]
                location = parts[2] if len(parts) > 2 else ""
            else:  # no recognisable header: the poster is the company, the first line is the pitch
                company, title, location = f"HN: {h.get('author', '')}", header[:120], ""
            out.append(_listing(title, company, f"https://news.ycombinator.com/item?id={h['objectID']}", location, "",
                                h.get("created_at", ""), text, "hn"))
        if len(c.get("hits", [])) < 200:
            break
    return out


def _jobicy(q):
    words = q.lower().split()
    d = fetch_json(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={urllib.parse.quote(words[0] if words else 'remote')}")
    out = []
    for j in d.get("jobs", []):
        blob = f"{j.get('jobTitle', '')} {j.get('jobExcerpt', '')} {j.get('jobIndustry', '')}".lower()
        if all(w in blob for w in words):
            sal = f"{j.get('annualSalaryMin', '')}-{j.get('annualSalaryMax', '')}".strip("-")
            out.append(_listing(j.get("jobTitle"), j.get("companyName"), j.get("url"), j.get("jobGeo"), sal,
                                j.get("pubDate"), j.get("jobDescription"), "jobicy"))
    return out


MUSE_CATEGORIES = {"engineer": "Software Engineering", "developer": "Software Engineering", "software": "Software Engineering",
                   "data": "Data and Analytics", "design": "Design and UX", "product": "Product Management",
                   "marketing": "Marketing", "sales": "Sales", "finance": "Accounting and Finance", "hr": "HR",
                   "support": "Customer Service", "project": "Project Management", "security": "IT"}


def _muse(q):
    words = q.lower().split()
    cat = next((c for w in words for k, c in MUSE_CATEGORIES.items() if k in w), None)
    out, seen_urls = [], set()
    for page in (1, 2):
        d = fetch_json(f"https://www.themuse.com/api/public/jobs?page={page}" + (f"&category={urllib.parse.quote(cat)}" if cat else ""))
        for r in d.get("results", []):
            desc = strip_html(r.get("contents") or "")
            blob = f"{r.get('name', '')} {' '.join(c.get('name', '') for c in r.get('categories', []))} {desc[:4000]}".lower()
            url = (r.get("refs") or {}).get("landing_page") or ""
            if all(w in blob for w in words) and url not in seen_urls:  # the API can repeat a job across pages
                seen_urls.add(url)
                out.append(_listing(r.get("name"), (r.get("company") or {}).get("name"), url,
                                    ", ".join(loc.get("name", "") for loc in r.get("locations", [])[:2]), "",
                                    r.get("publication_date"), r.get("contents"), "themuse"))
    return out


SOURCES = {"remotive": _remotive, "arbeitnow": _arbeitnow, "remoteok": _remoteok, "hn": _hn, "jobicy": _jobicy, "themuse": _muse}


def search(query: str, keywords: str = "", only_new: bool = False, sources=None, mark: bool | None = None,
           **filters) -> list[dict]:
    """Listings from the free job APIs: keyword filter, your private dealbreakers, cross-source de-dup, then the
    search filters (location / remote, min_salary, posted_within days, seniority; see refine), each annotated with
    stale signals and a sponsor hint. only_new skips listings seen before; `mark` (default: only_new) records the
    results as seen. A manual search never marks, so it cannot use up listings a watch has not judged yet."""
    mark = only_new if mark is None else mark
    raw = []
    for name in (sources or SOURCES):
        try:
            raw += SOURCES[name](query)
        except Exception as e:
            print(f"  {name}: {e}")
    out = [j for j in refine(dedupe([j for j in raw if j["url"]]), keywords=keywords, **filters) if not (only_new and _seen(j))]
    if mark:
        for j in out:
            for u in _urls(j):
                db.mark_seen(f"listing:{u}")
    return annotate(out)


def _seen(j) -> bool:
    return any(db.seen(f"listing:{u}") for u in _urls(j))


# --- normalisation, de-dup, filters -----------------------------------------
_SUFFIXES = {"inc", "llc", "ltd", "gmbh", "corp", "corporation", "co", "company", "plc", "limited", "incorporated", "llp",
             "lp", "ag", "bv", "sa", "srl", "pty"}
_TITLE_ABBR = {"sr": "senior", "jr": "junior"}


def _words(s) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", str(s or "").casefold().replace("'", "").replace("’", "").replace("&", " and "))


def norm_company(s) -> str:
    """'Acme, Inc.' / 'ACME GmbH' -> 'acme': casefolded, punctuation and legal suffixes gone."""
    w = _words(s)
    return " ".join(x for x in w if x not in _SUFFIXES) or " ".join(w)


def norm_title(s) -> str:
    return " ".join(_TITLE_ABBR.get(x, x) for x in _words(s))


def norm_location(s) -> str:
    return " ".join(_words(s))


def posting_key(j) -> str:
    return f"{norm_company(j['company'])}|{norm_title(j['title'])}|{norm_location(j.get('location'))}"


def dedupe(listings: list[dict]) -> list[dict]:
    """One listing per posting across sources: same URL, or the same normalised company + title + location found by
    another source (one source listing two such roles means two openings; differing ats_ids too). The richest
    description wins, empty salary / date / location are filled from the others, every source URL is kept (`urls`,
    primary first) and `sources` names where it was found."""
    out, by_key, by_url = [], {}, {}
    for j in listings:
        k, first = posting_key(j), by_url.get(j["url"])
        if first is None and k in by_key:
            f = by_key[k]
            if j["source"] not in f["sources"] and not (j.get("ats_id") and f.get("ats_id") and j["ats_id"] != f["ats_id"]):
                first = f
        if first is None:
            j = {**j, "urls": [j["url"]], "sources": [j["source"]]}
            out.append(j)
            by_key.setdefault(k, j)
            by_url[j["url"]] = j
            continue
        if j["url"] not in first["urls"]:
            first["urls"].append(j["url"])
        if j["source"] not in first["sources"]:
            first["sources"].append(j["source"])
        if len(j["desc"]) > len(first["desc"]):
            first["desc"] = j["desc"]
        for f in ("salary", "date", "location", "ats_id", "ats_feed"):
            if j.get(f) and not first.get(f):
                first[f] = j[f]
        by_url[j["url"]] = first
    return out


SENIORITY = ("intern", "junior", "mid", "senior", "staff", "lead", "manager")
_LEVEL_RX = [("intern", r"\bintern(ship)?s?\b|\bco-?op\b|\btrainee\b|\bapprentice"),
             ("manager", r"\b(head of|director|vp|vice president|chief)\b|(?<!product )(?<!program )(?<!project )(?<!account )"
                         r"(?<!marketing )(?<!community )\bmanager\b"),
             ("staff", r"\b(staff|principal|distinguished)\b"),
             ("lead", r"\blead\b"),
             ("senior", r"\b(senior|sr)\b"),
             ("junior", r"\b(junior|jr|entry[ -]level|graduate|new grad)\b"),
             ("mid", r"\b(mid[ -]?level|intermediate)\b")]


def seniority_of(title) -> str:
    """Level read off the title, first match wins (a 'Senior Engineering Manager' is a manager); no marker is 'mid'.
    ponytail: title regex only; 'Product Manager' and friends stay individual contributors."""
    t = " ".join(str(title or "").casefold().replace(".", " ").split())
    return next((lvl for lvl, rx in _LEVEL_RX if re.search(rx, t)), "mid")


def clean_filters(location="", min_salary=None, posted_within=None, seniority="") -> dict:
    """Search filters, validated (web, CLI and saved searches all pass through here). Empty values drop out."""
    out, loc, lvl = {}, " ".join(str(location or "").split()), str(seniority or "").strip().lower()
    if loc:
        if len(loc) > 80:
            raise SystemExit("location filter: at most 80 characters")
        out["location"] = loc
    for k, v, hi in (("min_salary", min_salary, 10_000_000), ("posted_within", posted_within, 3650)):
        if v not in (None, ""):
            try:
                n = int(str(v).strip()[:-1]) * 1000 if k == "min_salary" and str(v).strip()[-1:] in "kK" else int(str(v).strip())
            except ValueError:
                raise SystemExit(f"{k} must be a whole number: {str(v)[:40]}") from None
            if not 0 < n <= hi:
                raise SystemExit(f"{k} must be between 1 and {hi}")
            out[k] = n
    if lvl:
        if lvl not in SENIORITY:
            raise SystemExit(f"seniority must be one of {', '.join(SENIORITY)}")
        out["seniority"] = lvl
    return out


def _prefs_list(key) -> list[str]:
    return [x.strip() for x in str(settings.pref(key) or "").split(",") if x.strip()]


def refine(listings: list[dict], keywords: str = "", today: date | None = None, **filters) -> list[dict]:
    """Keyword filter, private dealbreakers (prefs excluded_companies / excluded_title_words), then the search filters.
    A listing whose salary, location or date is UNKNOWN passes and is marked (salary_unknown / location_unknown /
    date_unknown): nothing is dropped for lack of data. Pay is the top of the stated range, currency not converted."""
    from .resume import parse_salary

    f, today = clean_filters(**filters), today or date.today()
    kws = [k.strip().lower() for k in (keywords or "").split(",") if k.strip()]
    bad_co = {norm_company(c) for c in _prefs_list("excluded_companies")}
    bad_words = [norm_title(w) for w in _prefs_list("excluded_title_words")]
    loc = f.get("location", "").casefold()
    out = []
    for j in listings:
        title = norm_title(j["title"])
        if kws and not any(k in f"{j['title']} {j['desc']}".lower() for k in kws):
            continue
        if norm_company(j["company"]) in bad_co or any(re.search(rf"(?<!\S){re.escape(w)}(?!\S)", title) for w in bad_words if w):
            continue
        if loc == "remote":
            kind = "remote" if j["source"] in db.REMOTE_BOARDS else db.remote_kind(f"{j['location']}\n{j['desc'][:1500]}")
            if kind is None and not j["location"].strip():
                j["location_unknown"] = True
            elif kind != "remote":
                continue
        elif loc:
            if not j["location"].strip():
                j["location_unknown"] = True
            elif loc not in j["location"].casefold():
                continue
        if "min_salary" in f:
            pay = parse_salary(jd_with_salary(j))
            if not pay:
                j["salary_unknown"] = True
            elif pay["salary_max"] < f["min_salary"]:
                continue
        if "posted_within" in f:
            d = _day(j["date"])
            if d is None:
                j["date_unknown"] = True
            elif (today - d).days > f["posted_within"]:
                continue
        if "seniority" in f and seniority_of(j["title"]) != f["seniority"]:
            continue
        out.append(j)
    return out


# --- stale / repost signals, sponsor hints, coverage ------------------------
@lru_cache(maxsize=1024)
def _vague(desc: str) -> bool:
    """No hard skill, certification or degree named: boilerplate. Cached: the board asks again on every refresh."""
    from .ats import claims_in

    return not claims_in(desc)


def ghost_signals(x, today: date | None = None) -> dict:
    """{score 0-100, reasons}: how likely a listing (or a tracked job) is stale or a ghost posting. Posted over 30 days
    ago; the same company + title + location first seen over 21 days ago under another link (a repost); a very short
    description or one naming no concrete skill; for a feed job, its posting gone from the live board (strong)."""
    g, today = dict(x), today or date.today()
    is_job = "jd" in g
    score, reasons = 0, []
    posted = _day(g.get("posted_at") if is_job else g.get("date"))
    if posted and (age := (today - posted).days) > 30:
        score += 30
        reasons.append(f"posted {age} days ago")
    first = db.posting(posting_key(g)) if g.get("company") and g.get("title") else None
    if first and first["url"] not in (g.get("urls") or [g.get("url")]):
        seen_on = _day(first["first_seen"])
        if seen_on and (age := (today - seen_on).days) > 21:
            score += 30
            reasons.append(f"reposted: the same role was first seen {age} days ago under another link")
    desc = str((g.get("jd") if is_job else g.get("desc")) or "")
    if desc.strip() or not is_job:  # a job added without a JD is not suspicious, a listing without one is
        words = len(desc.split())
        if words < 80:
            score += 20
            reasons.append(f"very short description ({words} words)")
        elif _vague(desc):
            score += 20
            reasons.append("description names no concrete skill, tool or qualification")
    if is_job and g.get("id"):
        gone = next((e for e in db.events(g["id"]) if e["kind"] == "posting_removed"), None)
        if gone:
            score += 60
            reasons.append(f"posting removed: {gone['detail']}")
    return {"score": min(score, 100), "reasons": reasons}


def sponsor_hint(company) -> dict | None:
    """{name, approvals} when your imported USCIS H-1B data names an employer matching this company. A hint only:
    names are matched loosely and past approvals say nothing about a given role."""
    k = norm_company(company)
    r = db.sponsor(k) if k else None
    return {"name": r["name"], "approvals": r["approvals"]} if r and r["approvals"] else None


def annotate(listings: list[dict]) -> list[dict]:
    """Stale signals and sponsor hint on each listing, then remember the posting (for repost detection next time)."""
    for j in listings:
        j["ghost"], j["sponsor"], j["seniority"] = ghost_signals(j), sponsor_hint(j["company"]), seniority_of(j["title"])
        db.note_posting(posting_key(j), j["url"])
    return listings


def with_coverage(listings: list[dict]) -> list[dict]:
    """Cheap JD coverage (ats.match) of each listing against your profile as an employer sees it, with the top 3
    matched and missing terms. Skipped while the profile is still the template. No AI."""
    from . import ats
    from .resume import candidate_text

    try:
        text = candidate_text(private=False)
    except SystemExit:  # no profile yet: nothing to compare with
        return listings
    for j in listings:
        m = ats.match(text, j["desc"], j["title"], company=j["company"])
        kws = [k for k in m["keywords"] if not k["skipped"]]
        j["coverage"] = {"score": m["score"], "matched": [k["term"] for k in kws if k["matched"]][:3],
                         "missing": [k["term"] for k in kws if not k["matched"]][:3]}
    return listings


# --- H-1B sponsor data (user-supplied USCIS export) ---------------------------
def import_sponsors(raw: bytes) -> dict:
    """Load the USCIS H-1B Employer Data Hub export (CSV, or the tab-separated UTF-16 file the hub sometimes gives):
    approvals summed per normalised employer and fiscal year. Nothing is downloaded; you supply the file."""
    import csv
    import io

    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig", errors="replace")
    first = text.split("\n", 1)[0]
    rows = csv.reader(io.StringIO(text), delimiter="\t" if first.count("\t") > first.count(",") else ",")
    header = [re.sub(r"[^a-z]", "", h.lower()) for h in next(rows, [])]
    find = lambda *pre: [i for i, h in enumerate(header) if h.startswith(pre)]  # noqa: E731
    emp, year = find("employer")[:1], find("fiscalyear")[:1]
    # every "... Approval" column: Initial/Continuing (old hub), New Employment/Continuation/Change of Employer/... (current)
    appr = [i for i, h in enumerate(header) if re.search(r"approvals?$", h) and not h.startswith("total")]
    if not emp or not appr:
        raise SystemExit("not a USCIS H-1B Employer Data Hub export: need an Employer (or Employer (Petitioner) Name) "
                         "column and ... Approval columns. Columns seen: " + ", ".join(header)[:300])
    agg: dict[tuple[str, str], list] = {}
    for r in rows:
        if len(r) <= max(emp + appr + year):
            continue
        name, k = r[emp[0]].strip(), norm_company(r[emp[0]])
        if not k:
            continue
        n = sum(int(re.sub(r"\D", "", r[i]) or 0) for i in appr)
        cell = agg.setdefault((k, r[year[0]].strip()[:9] if year else ""), [name, 0])
        cell[1] += n
    db.save_sponsors({key: (v[0], v[1]) for key, v in agg.items()})
    return {"employers": len({k for k, _ in agg}), "rows": len(agg), "approvals": sum(v[1] for v in agg.values())}


def rank(listings: list[dict], provider: str | None = None, chunk: int = 15) -> list[dict]:
    """AI fit score (0-100) against the master profile, in chunks so one bad batch cannot sink the rest; best first."""
    from .resume import candidate_text

    if not listings:
        return listings
    prof = candidate_text(6000)
    for start in range(0, len(listings), chunk):
        part = listings[start:start + chunk]
        brief = "\n".join(f"[{i}] {j['title']} @ {j['company']} ({j['location']}) :: {j['desc'][:600]}" for i, j in enumerate(part))
        try:
            data = ai.ask_json(
                f"""Score each listing 0-100 for fit with the candidate (skills, seniority, location/remote, stated preferences).
Return a JSON list: [{{"i": 0, "score": 85, "why": "one line"}}, ...] covering every index.

CANDIDATE:
{prof}

LISTINGS:
{brief}""",
                provider=provider,
            )
        except (Exception, SystemExit) as e:
            print(f"  rank chunk {start // chunk + 1}: {e}")
            continue
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and isinstance(d.get("i"), int) and 0 <= d["i"] < len(part):
                part[d["i"]] |= {"score": d.get("score", 0), "why": d.get("why", "")}
    listings.sort(key=lambda j: -j.get("score", 0))
    return listings
