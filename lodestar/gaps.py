"""The skill-gap planner (blueprint 13.3, pass 29): what your open jobs keep asking for that your profile does not show,
from their stored fits (required skills missing, hard requirements not met or unknown), most repeated first, each with
possible actions; a legal requirement (a license, a clearance) is kept apart from an employer's preference. And
analytics by career track and career class (13.1). Deterministic, private, no AI; small samples are said (13.2)."""
import json

from . import db, fit
from .extras import MIN_N

OPEN = ("saved", "applied", "screening", "interview", "offer")
LEGAL = ("license", "licence", "certification", "certificate", "registration", "clearance", "authorization")


def _lex() -> dict:
    from .ats import DATA

    d = json.loads(DATA.read_text(encoding="utf-8"))
    return {"cert": {t.casefold() for t in d["certifications"]}, "degree": {t.casefold() for t, _ in d["degrees"]},
            "soft": {t.casefold() for t in d["soft"]}}


def _actions(term: str, legal: bool, lex: dict) -> list[str]:
    t = term.casefold()
    if legal or t in lex["cert"]:
        return ["certification"]
    if t in lex["degree"]:
        return ["degree"]
    if t in lex["soft"]:
        return ["project", "supervised_experience"]
    return ["project", "short_course"]


def plan(job_ids=None) -> list[dict]:
    """[{requirement, count, mandatory, legal, actions, jobs}] over your open jobs (or job_ids), most repeated first."""
    lex, rows = _lex(), {}
    jobs = [j for j in db.list_jobs() if (j["id"] in job_ids if job_ids else j["status"] in OPEN)]
    for j in jobs:
        f = fit.stored(j)
        if not f:
            continue
        need = [(t, False) for t in ((f.get("parts") or {}).get("skills") or {}).get("missing") or []]
        need += [(g["requirement"], any(w in g["requirement"].casefold() for w in LEGAL))
                 for g in f.get("gates") or [] if g["state"] != "met" and not g["requirement"].startswith(("Excluded", "Deal-breaker"))]
        for term, legal in need:
            r = rows.setdefault(term.casefold(), {"requirement": term, "count": 0, "mandatory": True, "legal": legal,
                                                  "actions": _actions(term, legal, lex), "jobs": []})
            if j["id"] not in r["jobs"]:
                r["jobs"].append(j["id"])
                r["count"] += 1
    return sorted(rows.values(), key=lambda r: (-r["count"], not r["legal"], r["requirement"].casefold()))


def report(job_ids=None) -> dict:
    """{rows, jobs, note}: the plan with the sample it rests on (fewer than MIN_N jobs is said, never a trend)."""
    n = len([j for j in db.list_jobs() if (j["id"] in job_ids if job_ids else j["status"] in OPEN) and fit.stored(j)])
    rows = plan(job_ids)
    note = (f"based on {n} job{'s' * (n != 1)}: fewer than {MIN_N}, so read it as a list, not a trend" if n < MIN_N
            else f"based on {n} open jobs")
    return {"rows": rows, "jobs": n, "note": note}


def by_track() -> list[dict]:
    """[{track, listings, tracked, classes: {career class: n}}] per career track: listings its searches found, the
    ones you track, and those jobs by career class (fit.job_class)."""
    from .careers import tracks

    out = []
    for t in tracks():
        rows = db.con().execute("SELECT job_id FROM postings WHERE track_id=?", (t["id"],)).fetchall()
        jids = {r["job_id"] for r in rows if r["job_id"]}
        classes: dict[str, int] = {}
        for jid in jids:
            try:
                c = fit.job_class(fit.stored(db.get_job(jid)))
            except SystemExit:  # the job was deleted meanwhile
                continue
            if c:
                classes[c] = classes.get(c, 0) + 1
        out.append({"track": t["label"], "id": t["id"], "listings": len(rows), "tracked": len(jids), "classes": classes})
    return out
