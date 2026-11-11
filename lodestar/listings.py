"""All jobs: every listing any source found (job APIs, company feeds, saved searches, captures, job-alert mail), one
row per posting in the `postings` table, merged across sources: the first URL ever seen stays `url`, `urls` keeps every
link, `sources` every source. Each row carries its fit (fit.py). Untracked rows unseen for 45 days are pruned; tracked
rows never are. Rows are third-party listings: never exported (Himalayas' terms), never sent anywhere."""
import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from . import db

REPOST_DAYS = 21  # a new link on the same site for a role first seen longer ago than this is a repost
KEEP_DAYS = 45  # untracked rows not seen again for this long are pruned
PAGE = 100
SHOWS = ("open", "tracked", "dismissed", "all")
SORTS = ("fit", "new", "salary", "company")
LIGHT = ("key", "url", "title", "company", "location", "salary", "posted_at", "urls", "sources", "first_seen", "last_seen",
         "seen_count", "fit_score", "fit", "fit_rev", "ai_fit", "job_id", "dismissed", "closed_at", "reposted_at")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # UTC, like first_seen's datetime('now')


def _jl(v) -> list:
    try:
        x = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return []
    return [str(i) for i in x if i] if isinstance(x, list) else []


def _host(u) -> str:
    return (urllib.parse.urlparse(str(u or "")).hostname or "").lower()


def _date(s) -> str | None:
    s = str(s or "")[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def same_place(a, b) -> bool:
    """Two locations name the same place for merging: either is empty, both say remote, or the first city word agrees
    ('Austin, TX' = 'Austin, Texas, United States')."""
    from .web_monitor import norm_location

    a, b = norm_location(a).split(), norm_location(b).split()
    if not a or not b:
        return True
    if "remote" in a and "remote" in b:
        return True
    return a[0] == b[0]


def _like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _find(c, key: str, location, ats_id: str = ""):
    """The stored row for this posting: its exact key, else the same company and title at the same place. Two ATS
    posting ids that differ are two openings (as web_monitor.dedupe keeps them), never one row and never a repost.
    ponytail: exact normalised titles only ('Data Engineer' and 'Data Engineer, Payments' stay apart); two identical
    openings without ATS ids at one company collapse into one row. Upgrade: core_title."""
    def same_ats(r):
        return not (ats_id and r["ats_id"] and r["ats_id"] != ats_id)

    row = c.execute("SELECT rowid AS id, * FROM postings WHERE key=?", (key,)).fetchone()
    co, title, _ = key.split("|", 2)
    if row and same_ats(row):
        return row
    if not co or not title:
        return None
    for r in c.execute("SELECT rowid AS id, * FROM postings WHERE key LIKE ? ESCAPE '\\' ORDER BY first_seen",
                       (f"{_like(co)}|{_like(title)}|%",)):
        if same_ats(r) and same_place(r["location"] if r["location"] is not None else r["key"].split("|", 2)[2], location):
            return r
    return None


def store(rows, source: str | None = None, job_id: int | None = None) -> list[dict | None]:
    """Upsert listings (dicts as web_monitor._listing gives them, plus urls / sources / ats_id / ats_feed / closes_at)
    in one transaction, then score each (fit.for_listing, one context per call). Returns one entry per row: None for a
    row with no title, else {id (rowid), key, first_seen, job_id, fit, new}. source: names the source for every row
    (an alert, a capture); job_id: the job the rows belong to (capture / track); otherwise a row inherits the job whose
    URL is among its links. A new link on the same site for a row first seen over REPOST_DAYS ago is a repost
    (reposted_at, and a posting_reposted event on its job)."""
    from .web_monitor import posting_key

    c, now, today = db.con(), _now(), date.today().isoformat()
    if c.in_transaction:
        c.commit()
    keys, events = [], []
    c.execute("BEGIN IMMEDIATE")
    try:
        for j in rows:
            title = " ".join(str(j.get("title") or "").split())[:300]
            if not title:
                keys.append(None)
                continue
            j = dict(j) | {"title": title, "company": " ".join(str(j.get("company") or "").split())[:200]}
            urls = list(dict.fromkeys(str(u) for u in (j.get("urls") or [j.get("url")]) if u))
            srcs = list(dict.fromkeys(str(s) for s in ([source] if source else (j.get("sources") or [j.get("source")])) if s))
            jd = str(j.get("desc") or j.get("jd") or "")
            loc = str(j.get("location") or "")[:200]
            fill = {"location": loc, "salary": str(j.get("salary") or "")[:200], "ats_id": str(j.get("ats_id") or ""),
                    "posted_at": _date(j.get("posted_at") or j.get("date")) or "", "ats_feed": str(j.get("ats_feed") or ""),
                    "closed_at": _date(j.get("closes_at") or j.get("closed_at")) or ""}
            key = posting_key(j)
            row = _find(c, key, loc, fill["ats_id"])
            if row is None:
                if c.execute("SELECT 1 FROM postings WHERE key=?", (key,)).fetchone():
                    key = f"{key}#{fill['ats_id']}"  # another opening (other ATS id) already holds the plain key
                jid = job_id or db.tracked_id(urls)
                c.execute("INSERT INTO postings(key, url, title, company, jd, urls, sources, last_seen, seen_count, job_id, "
                          "location, salary, ats_id, posted_at, ats_feed, closed_at) VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)",
                          (key, urls[0] if urls else None, title, j["company"], jd, json.dumps(urls), json.dumps(srcs),
                           now, jid, *(v or None for v in fill.values())))
                keys.append((key, True))
                continue
            old = _jl(row["urls"]) or ([row["url"]] if row["url"] else [])
            add = [u for u in urls if u not in old]
            first = datetime.strptime(str(row["first_seen"] or now)[:19], "%Y-%m-%d %H:%M:%S")
            repost = bool(add) and (datetime.now(timezone.utc).replace(tzinfo=None) - first).days > REPOST_DAYS and \
                bool({_host(u) for u in add} & {_host(u) for u in old})
            jid = job_id or row["job_id"] or db.tracked_id(old + add)
            upd = {"urls": json.dumps(old + add), "sources": json.dumps(list(dict.fromkeys(_jl(row["sources"]) + srcs))),
                   "last_seen": now, "seen_count": (row["seen_count"] or 0) + 1, "job_id": jid,
                   "title": row["title"] or title, "company": row["company"] or j["company"], "url": row["url"] or (urls or [None])[0]}
            if len(jd) > len(row["jd"] or ""):
                upd["jd"] = jd
            upd |= {k: v for k, v in fill.items() if v and not row[k]}
            if repost:
                upd["reposted_at"] = today
                if jid:
                    events.append((jid, f"new link for {title}: {_host(add[0])} (first seen {first:%Y-%m-%d})"))
            c.execute(f"UPDATE postings SET {', '.join(k + '=?' for k in upd)} WHERE rowid=?", (*upd.values(), row["id"]))
            keys.append((row["key"], False))
        c.commit()
    except BaseException:
        c.rollback()
        raise
    for jid, text in events:
        db.add_event(jid, "posting_reposted", text)
    return _score(keys)


def _score(keys: list) -> list[dict | None]:
    from . import fit

    try:
        ctx = fit.context() if any(keys) else None
    except (Exception, SystemExit) as e:  # an unreadable profile: stored unscored; the loop's fit step catches up
        print(f"  all jobs: fit skipped: {e}")
        ctx = False
    out = []
    for k in keys:
        if not k:
            out.append(None)
            continue
        r = db.con().execute("SELECT rowid AS id, * FROM postings WHERE key=?", (k[0],)).fetchone()
        f = None
        if ctx is not False:
            try:
                f = fit.for_listing(r, ctx)
            except (Exception, SystemExit) as e:  # one bad row costs only itself
                print(f"  all jobs: fit of #{r['id']}: {e}")
        out.append({"id": r["id"], "key": r["key"], "first_seen": r["first_seen"], "job_id": r["job_id"], "fit": f, "new": k[1]})
    return out


# ----------------------------------------------------------------------------- reading
def visit_time() -> int:
    row = db.con().execute("SELECT value FROM meta WHERE key='alljobs_visit'").fetchone()
    return int(row["value"] or 0) if row else 0


def visit() -> int:
    """Mark all seen: rows first seen before now are no longer 'new'."""
    t = int(time.time())
    db.con().execute("INSERT INTO meta(key, value) VALUES('alljobs_visit', ?) ON CONFLICT(key) DO UPDATE SET "
                     "value=excluded.value", (t,))
    db.con().commit()
    return t


def _first_ts(s) -> float:
    try:
        return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _view(r, visit_at: int, cur_rev: str | None, pay: dict | None) -> dict:
    from . import fit

    srcs, urls = _jl(r["sources"]), _jl(r["urls"]) or ([r["url"]] if r["url"] else [])
    f = fit.stored(r)
    return {"id": r["id"], "title": r["title"], "company": r["company"] or "", "location": r["location"] or "",
            "salary": r["salary"] or "", "posted_at": r["posted_at"] or "", "first_seen": r["first_seen"],
            "last_seen": r["last_seen"] or r["first_seen"], "url": r["url"] or (urls[0] if urls else ""), "urls": urls,
            "sources": srcs, "job_id": r["job_id"], "dismissed": bool(r["dismissed"]), "closed_at": r["closed_at"] or "",
            "reposted_at": r["reposted_at"] or "", "new": _first_ts(r["first_seen"]) > visit_at,
            "pay_max": (pay or {}).get("salary_max"), **fit.light(f, cur_rev)}


def query(q: str = "", sources=(), min_fit=0, remote: str = "", min_salary=None, days=None, new: bool = False,
          show: str = "open", sort: str = "fit", offset: int = 0, limit: int = PAGE) -> dict:
    """The All jobs list: {rows, total, sources: {name: n}, visit, stale}. Rows carry no description (the payload stays
    small) and only the light fit. show: open (untracked, not dismissed, not closed) | tracked | dismissed | all; new:
    first seen since the last 'Mark all seen'; sources: any of them (the counts ignore this filter, so every chip
    keeps its number). Sort: best fit (unscored last), newest, top of the pay range, company.
    ponytail: filtered and sorted in Python per call, fine under ~5k rows; upgrade to SQL paging past that."""
    from . import fit
    from .resume import parse_salary
    from .web_monitor import clean_filters, jd_with_salary

    show = show if show in SHOWS else "open"
    sort = sort if sort in SORTS else "fit"
    where, args = ["title IS NOT NULL", "title != ''"], []
    if show == "open":
        where += ["job_id IS NULL", "COALESCE(dismissed, 0) = 0", "(closed_at IS NULL OR closed_at >= date('now', 'localtime'))"]
    elif show == "tracked":
        where.append("job_id IS NOT NULL")
    elif show == "dismissed":
        where.append("COALESCE(dismissed, 0) = 1")
    if str(q or "").strip():
        where.append("(title LIKE ? ESCAPE '\\' OR company LIKE ? ESCAPE '\\')")
        args += [f"%{_like(str(q).strip()[:100])}%"] * 2
    if int(min_fit or 0) > 0:
        where.append("fit_score >= ?")
        args.append(int(min_fit))
    f = clean_filters(min_salary=min_salary or None, posted_within=days or None)  # validated like search filters
    if f.get("posted_within"):
        where.append("COALESCE(posted_at, substr(first_seen, 1, 10)) >= date('now', 'localtime', ?)")
        args.append(f"-{f['posted_within']} days")
    visit_at = visit_time()
    rows = db.con().execute(f"SELECT rowid AS id, {', '.join(LIGHT)}, substr(jd, 1, 1500) AS head FROM postings "
                            f"WHERE {' AND '.join(where)}", args).fetchall()
    remote = str(remote or "").strip().lower()
    floor = f.get("min_salary", 0)
    want = {str(s) for s in (sources or ()) if s}
    try:
        cur = fit.rev()
    except (Exception, SystemExit):
        cur = None
    kept, counts, stale = [], {}, 0
    for r in rows:
        if new and _first_ts(r["first_seen"]) <= visit_at:
            continue
        srcs = _jl(r["sources"])
        if remote:
            kind = "remote" if any(s in db.REMOTE_BOARDS for s in srcs) else db.remote_kind(f"{r['location'] or ''}\n{r['head'] or ''}")
            if kind != remote:
                continue
        pay = parse_salary(jd_with_salary({"salary": r["salary"], "desc": r["head"] or ""})) or {}
        if floor and (pay.get("salary_max") or 0) < floor:
            continue
        for s in srcs:
            counts[s] = counts.get(s, 0) + 1
        if want and not want & set(srcs):
            continue
        kept.append((r, pay))
    key = {"fit": lambda x: (x[0]["fit_score"] is None, -(x[0]["fit_score"] or 0), -_first_ts(x[0]["first_seen"])),
           "new": lambda x: -_first_ts(x[0]["first_seen"]),
           "salary": lambda x: (-(x[1].get("salary_max") or -1), -(x[0]["fit_score"] or 0)),
           "company": lambda x: ((x[0]["company"] or "").casefold(), (x[0]["title"] or "").casefold())}[sort]
    kept.sort(key=key)
    page = kept[max(0, int(offset or 0)):max(0, int(offset or 0)) + max(1, min(500, int(limit or PAGE)))]
    out = [_view(r, visit_at, cur, pay) for r, pay in page]
    for r, _ in kept:
        stale += bool(cur and r["fit_rev"] != cur)
    from .contacts import with_warm
    from .web_monitor import sponsor_hint

    for v in with_warm(out):
        v["sponsor"] = sponsor_hint(v["company"])
    return {"rows": out, "total": len(kept), "sources": counts, "visit": visit_at, "stale": stale}


def get(pid: int) -> dict:
    """One row with its description (first 1,500 characters for the expanded row) and the full fit breakdown."""
    from . import fit

    r = db.con().execute("SELECT rowid AS id, * FROM postings WHERE rowid=?", (int(pid),)).fetchone()
    if not r or not r["title"]:
        raise SystemExit(f"no listing #{pid}")
    try:
        cur = fit.rev()
    except (Exception, SystemExit):
        cur = None
    return _view(r, visit_time(), cur, None) | {"desc": (r["jd"] or "")[:1500], "fit": fit.stored(r)}


# ----------------------------------------------------------------------------- user actions
def track(pid: int) -> int:
    """Track: a user click, so the job is added directly (as the old Search tab's track did) and the row linked."""
    from .resume import refit
    from .web_monitor import jd_with_salary, listing_fields

    r = db.con().execute("SELECT rowid AS id, * FROM postings WHERE rowid=?", (int(pid),)).fetchone()
    if not r or not r["title"]:
        raise SystemExit(f"no listing #{pid}")
    srcs = _jl(r["sources"])
    row = dict(r) | {"desc": r["jd"] or "", "source": (srcs or [""])[0], "date": r["posted_at"] or ""}
    jid = db.add_job(r["company"] or "Unknown company", r["title"], r["url"], jd_with_salary(row),
                     f"found via {', '.join(srcs) or 'a listing'}", **listing_fields(row))
    db.con().execute("UPDATE postings SET job_id=? WHERE rowid=?", (jid, int(pid)))
    db.con().commit()
    refit(jid)
    return jid


def dismiss(pid: int, on: bool = True) -> None:
    n = db.con().execute("UPDATE postings SET dismissed=? WHERE rowid=? AND title IS NOT NULL", (1 if on else 0, int(pid))).rowcount
    db.con().commit()
    if not n:
        raise SystemExit(f"no listing #{pid}")


def prune(days: int = KEEP_DAYS) -> int:
    """Untracked rows not seen for `days`, or past their closing date (Himalayas: remove expired jobs). Never a row
    linked to a job. The monitor loop runs it once a day."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    n = db.con().execute("DELETE FROM postings WHERE job_id IS NULL AND (COALESCE(last_seen, first_seen) < ? OR "
                         "(closed_at IS NOT NULL AND closed_at < date('now', 'localtime')))", (cutoff,)).rowcount
    db.con().commit()
    return n


# ----------------------------------------------------------------------------- one listing, both ways
ACTIVITY = ("created", "status", "posting_removed", "posting_changed", "posting_reopened", "posting_reposted",
            "listing_seen", "proposed", "duplicate", "interview_date", "calendar")


def activity(job_id: int) -> list[dict]:
    """The drawer's Listing activity, newest first: posting checks (web), alert sightings (alert), the job's own
    events (app) and its mail both ways (mail; the 'email' events are those same mails, so they are left out)."""
    out = []
    for e in reversed(db.events(job_id)):  # newest first, so same-second entries keep that order in the stable sort
        if e["kind"] in ACTIVITY:
            src = "web" if e["kind"].startswith("posting_") else "alert" if e["kind"] == "listing_seen" else "app"
            out.append({"at": e["ts"], "src": src, "kind": e["kind"], "text": e["detail"] or ""})
    for m in db.list_mail(job_id):
        out.append({"at": m["sent_at"] or m["created_at"], "src": "mail", "dir": m["direction"], "kind": m["category"] or "",
                    "text": m["subject"] or "", "from": m["from_addr"] if m["direction"] == "in" else m["to_addr"],
                    "trusted": bool(m["trusted"]), "reason": m["link_reason"] or m["linked_by"] or "", "mail_id": m["id"]})
    return sorted(out, key=lambda x: str(x["at"] or ""), reverse=True)


def posting_of(job) -> dict:
    """The drawer's posting line for a job: {sources, urls, last_seen (All jobs), closed (posting_removed, unless it
    reopened), checked (the listing monitor's last read), seen_alert (newest alert sighting), no_fetch}."""
    from .config import SNAPSHOTS
    from .web_monitor import no_fetch, removed_event

    r = db.con().execute("SELECT * FROM postings WHERE job_id=? ORDER BY COALESCE(last_seen, first_seen) DESC LIMIT 1",
                         (job["id"],)).fetchone()
    ev = db.events(job["id"])
    seen = next((e["ts"] for e in reversed(ev) if e["kind"] == "listing_seen"), None)
    gone = removed_event(job["id"])
    snap = SNAPSHOTS / f"job-{job['id']}.json"
    checked = datetime.fromtimestamp(snap.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if snap.is_file() else None
    return {"sources": _jl(r["sources"]) if r else [], "urls": _jl(r["urls"]) if r else [],
            "last_seen": (r["last_seen"] or r["first_seen"]) if r else None, "closed": gone["ts"] if gone else None,
            "checked": checked, "seen_alert": seen, "no_fetch": bool(job["url"]) and no_fetch(job["url"])}
