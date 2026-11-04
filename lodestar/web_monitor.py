"""Watch career pages for changes and query free job APIs (no keys needed) for new listings."""
import hashlib
import urllib.parse

from . import ai, db
from .config import SNAPSHOTS
from .util import fetch, fetch_json, notify, strip_html


def check_watches() -> list[str]:
    """Run every saved watch. 'search:<query>' watches hit the job APIs; anything else is a URL diff."""
    SNAPSHOTS.mkdir(exist_ok=True)
    alerts = []
    for w in db.watches():
        if w["url"].startswith("search:"):
            q = w["url"][7:]
            new = search(q, keywords=w["keywords"] or "", only_new=True)
            for j in new:
                notify(f"NEW LISTING [{q}]: {j['title']} @ {j['company']} ({j['location']}) {j['url']}")
                alerts.append(j["url"])
            if new:
                try:  # AI judgement -> approvals inbox (or straight into the tracker when auto_track is auto)
                    from .apply import auto_track

                    for j in auto_track(new):
                        notify(f"FIT {j['score']}: {j['title']} @ {j['company']} -> {j['proposal'].get('status')}")
                except Exception as e:
                    print(f"  auto_track: {e}")
            db.update_watch(w["id"], "")
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
    return alerts


# --- free job APIs ----------------------------------------------------------
def _listing(title, company, url, location="", salary="", date="", desc="", source=""):
    return dict(title=title or "", company=company or "", url=url or "", location=location or "", salary=salary or "",
                date=(date or "")[:10], desc=strip_html(desc or "")[:3000], source=source)


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


SOURCES = {"remotive": _remotive, "arbeitnow": _arbeitnow, "remoteok": _remoteok}


def search(query: str, keywords: str = "", only_new: bool = False, sources=None) -> list[dict]:
    out, urls = [], set()
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    for name in (sources or SOURCES):
        try:
            jobs = SOURCES[name](query)
        except Exception as e:
            print(f"  {name}: {e}")
            continue
        for j in jobs:
            if not j["url"] or j["url"] in urls:
                continue
            if kws and not any(k in f"{j['title']} {j['desc']}".lower() for k in kws):
                continue
            key = f"listing:{j['url']}"
            if only_new and db.seen(key):
                continue
            urls.add(j["url"])
            out.append(j)
            db.mark_seen(key)
    return out


def rank(listings: list[dict], provider: str | None = None, chunk: int = 15) -> list[dict]:
    """AI fit score (0-100) against the master profile, in chunks so one bad batch cannot sink the rest; best first."""
    from .resume import profile_text

    if not listings:
        return listings
    prof = profile_text()[:6000]
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
        except Exception as e:
            print(f"  rank chunk {start // chunk + 1}: {e}")
            continue
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and isinstance(d.get("i"), int) and 0 <= d["i"] < len(part):
                part[d["i"]] |= {"score": d.get("score", 0), "why": d.get("why", "")}
    listings.sort(key=lambda j: -j.get("score", 0))
    return listings
