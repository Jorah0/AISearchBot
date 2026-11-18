"""Application pacing for the job sites you browse yourself (pass 36): LinkedIn, Indeed, Glassdoor, ZipRecruiter and
SimplyHired. Lodestar never opens these sites itself (apply_agent.forbidden); you browse, save postings with the
extension and apply there. Each site gets a daily and a weekly cap (yours to change): Lodestar counts the jobs you
marked applied whose link (or application link) is on that site, warns on Today and in the job drawer at the cap, and
refuses an extension fill on that site until the window passes. A company's own careers site is never capped."""
import json
import re
from datetime import datetime, timedelta, timezone

from . import db

KEY = "pacing:caps"  # meta row: {"LinkedIn": {"day": n, "week": n}, ...} (only the sites you changed)
DEFAULT = {"LinkedIn": (10, 40), "Indeed": (15, 60), "Glassdoor": (10, 40), "ZipRecruiter": (10, 40),
           "SimplyHired": (10, 40)}
SITES = tuple(DEFAULT)


def site_of(url) -> str | None:
    """'LinkedIn' for a linkedin.com (any country) link, and so on; None for anything else."""
    from .apply_agent import forbidden

    return forbidden(url) if url else None


def caps() -> dict:
    row = db.con().execute("SELECT value FROM meta WHERE key=?", (KEY,)).fetchone()
    try:
        mine = json.loads(row["value"]) if row and isinstance(row["value"], str) else {}
    except ValueError:
        mine = {}
    return {s: {"day": int((mine.get(s) or {}).get("day", d)), "week": int((mine.get(s) or {}).get("week", w))}
            for s, (d, w) in DEFAULT.items()}


def set_cap(site: str, day, week) -> dict:
    if site not in DEFAULT:
        raise SystemExit(f"caps are for {', '.join(SITES)}, not {str(site)[:40]}")
    try:
        day, week = int(day), int(week)
    except (TypeError, ValueError):
        raise SystemExit("a cap is a whole number") from None
    if not (0 <= day <= 200 and day <= week <= 1000):
        raise SystemExit("caps: 0-200 a day, and a week at least the day's cap (up to 1000)")
    c = caps()
    c[site] = {"day": day, "week": week}
    db.con().execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (KEY, json.dumps(c)))
    db.con().commit()
    return c[site]


def _moves():
    """(url, apply_url, at UTC, job id) for every move to applied in the last 8 days (the stage history)."""
    since = (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
    return [tuple(r) for r in db.con().execute(
        "SELECT j.url, j.apply_url, MIN(e.at), j.id FROM stage_events e JOIN jobs j ON j.id = e.job_id "
        "WHERE e.to_stage='applied' AND e.at >= ? GROUP BY j.id", (since,)).fetchall()]


def usage() -> dict:
    """{site: {day, week, cap_day, cap_week, full}}: applications today (since local midnight) and in the last 7 days."""
    from .util import utc_to_local

    now = datetime.now()
    midnight, week_ago = now.replace(hour=0, minute=0, second=0, microsecond=0), now - timedelta(days=7)
    out = {s: {"day": 0, "week": 0} for s in SITES}
    for url, apply_url, at, _jid in _moves():
        site = site_of(apply_url) if apply_url else site_of(url)  # a company link: never the board you found it on
        when = utc_to_local(at) if at else None
        if site and when and when >= week_ago:
            out[site]["week"] += 1
            out[site]["day"] += when >= midnight
    for s, c in caps().items():
        out[s] |= {"cap_day": c["day"], "cap_week": c["week"], "full": out[s]["day"] >= c["day"] or out[s]["week"] >= c["week"]}
    return out


def check(url) -> str | None:
    """Why a fill on this page must wait (its site is at today's or this week's cap), else None."""
    site = site_of(url)
    if not site:
        return None
    u = usage()[site]
    if u["day"] >= u["cap_day"]:
        return (f"{site}: {u['day']} of {u['cap_day']} today, so Lodestar pauses here until tomorrow. Spacing "
                f"applications out keeps your account in good standing; change the cap under Accounts > Job sites.")
    if u["week"] >= u["cap_week"]:
        return (f"{site}: {u['week']} of {u['cap_week']} this week, so Lodestar pauses here for a few days; change "
                f"the cap under Accounts > Job sites.")
    return None


def for_job(job) -> dict | None:
    """The job drawer's line: {site, day, cap_day, week, cap_week, full} when the job lives on one of the five sites."""
    apply_url = job["apply_url"] if "apply_url" in job.keys() else None
    site = site_of(apply_url) if apply_url else site_of(job["url"])
    return {"site": site, **usage()[site]} if site else None


# ----------------------------------------------------------------------------- AI search ideas (pass 37)
_BOOL_RX = re.compile(r'[^\w .,:/()"-]')


def site_queries(level: str = "", location: str = "", provider: str | None = None) -> dict:
    """{queries: [{query, why}] (up to 6), boolean, level, location}: searches to run yourself on the five sites, from
    one AI call over your profile (never the salary floor) and saved searches. The AI never sees those sites and
    Lodestar never fetches them: the page turns each query into links to their own search."""
    from . import ai
    from .advisor import _h_search

    if not ai.available():
        raise SystemExit("search ideas need an AI provider: link a key under Setup > Link an AI key")
    ctx = "\n\n".join(f"{label.upper()}:\n{text}" for _key, label, text in _h_search(None))
    r = ai.ask_json_light(
        f"""Suggest up to 6 searches this candidate can run themselves on LinkedIn, Indeed, Glassdoor, ZipRecruiter and
SimplyHired. Each query is a job title (2-6 words) the candidate qualifies for: their own titles, real synonyms and
adjacent titles, or a title plus one core skill. No company names, no links, no salary. Skip what the saved searches
already cover. Level wanted: {level or 'any'}. Place: {location or 'any'}.
Also give one boolean keyword string for the LinkedIn / Indeed search box (quoted titles joined with OR, optionally
AND a skill group, optionally NOT words to exclude).
Return JSON: {{"queries": [{{"query": "...", "why": "one short line"}}], "boolean": "..."}}

{ctx}""", provider=provider) or {}
    out, seen = [], set()
    for q in r.get("queries") or [] if isinstance(r, dict) else []:
        if not isinstance(q, dict):
            continue
        text = ai.clean_label(re.sub(r"<[^>]*>", " ", str(q.get("query") or "")), 80)
        if not text or re.search(r"https?:|www\.|\.com\b", text, re.I) or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append({"query": text, "why": ai.clean_label(re.sub(r"<[^>]*>.*?</[^>]*>|<[^>]*>", " ", str(q.get("why") or "")), 160)})
        if len(out) == 6:
            break
    raw = str(r.get("boolean") or "") if isinstance(r, dict) else ""
    boolean = " ".join(_BOOL_RX.sub("", re.sub(r"<[^>]*>", " ", raw)).split())[:200]
    return {"queries": out, "boolean": boolean, "level": level, "location": location}
