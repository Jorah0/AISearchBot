"""Contacts: the people in your search (recruiters, hiring managers, referrers, LinkedIn connections), the jobs they are
linked to, and when you last / next talk. Warm paths: who you know at a company you track or find in a search.

Never part of mail trust: email_monitor trusts only a job's own stored contact (jobs.contact_email) and nothing here
writes that column. The one thing incoming mail changes here is a contact's last_touch.
"""
import re
import sqlite3
from datetime import date

from . import db

ROLES = ("recruiter", "hiring_manager", "referrer", "interviewer", "other")
_TEXT = {"name": 120, "email": 254, "phone": 40, "linkedin_url": 200, "company": 120, "position": 120, "how_met": 200,
         "notes": 5000}
FIELDS = (*_TEXT, "last_touch", "next_touch")
EMAIL_RE = re.compile(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+")
REFERRAL = ("a referral. The candidate knows this person: ask plainly and briefly whether they would refer the candidate "
            "or pass the application to the hiring manager, and make saying no easy")


def _clean(k: str, v):
    """One user-settable field, validated. Empty clears (None)."""
    if k not in FIELDS:
        raise SystemExit(f"unknown contact field '{k}'. Fields: {', '.join(FIELDS)}")
    s = ("" if v is None else str(v)).strip()
    if k != "notes":
        s = " ".join(s.split())
    if not s:
        return None
    if k in ("last_touch", "next_touch"):
        return db.valid_date(k, s)
    if len(s) > _TEXT[k]:
        raise SystemExit(f"{k} is longer than {_TEXT[k]} characters")
    if k == "email":
        if not EMAIL_RE.fullmatch(s):
            raise SystemExit(f"not an email address: {s[:80]}")
        return s.lower()
    if k == "linkedin_url":
        from .profile import _linkedin_url

        if not (u := _linkedin_url(s)):
            raise SystemExit("linkedin_url must be a profile link like https://www.linkedin.com/in/name")
        return u
    return s


def _write(sql: str, args) -> int:
    try:
        cur = db.con().execute(sql, args)
    except sqlite3.IntegrityError:
        raise SystemExit("another contact already has this email address or LinkedIn URL") from None
    db.con().commit()
    return cur.lastrowid or 0


def _log_touch(cid: int, day: str | None) -> None:
    """Touches you record yourself (a last-touch date, "Touched today"), one per day: the history insights, weekly goals
    and the activity log count; last_touch keeps only the latest. Mail is counted from the mail itself, not here."""
    # ponytail: manual touches only; mail touches would double-count the sent mail the activity log already lists
    if day and day <= date.today().isoformat():
        db.con().execute("INSERT OR IGNORE INTO touches(contact_id, day) VALUES(?,?)", (cid, day))
        db.con().commit()


def add(source: str = "manual", **fields) -> int:
    clean = {k: _clean(k, v) for k, v in fields.items()}
    if not clean.get("name"):
        raise SystemExit("a contact needs a name")
    clean["source"] = str(source)[:40]
    cid = _write(f"INSERT INTO contacts({', '.join(clean)}) VALUES({', '.join('?' * len(clean))})", tuple(clean.values()))
    _log_touch(cid, clean.get("last_touch"))
    return cid


def get(cid: int) -> sqlite3.Row:
    row = db.con().execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not row:
        raise SystemExit(f"no contact #{cid}")
    return row


def edit(cid: int, **fields) -> dict:
    """Set whitelisted fields (FIELDS); every value is validated first, so a bad one changes nothing."""
    clean = {k: _clean(k, v) for k, v in fields.items()}
    if "name" in clean and not clean["name"]:
        raise SystemExit("a contact needs a name")
    old = get(cid)["last_touch"]
    if clean:
        _write(f"UPDATE contacts SET {', '.join(k + '=?' for k in clean)} WHERE id=?", (*clean.values(), cid))
    if clean.get("last_touch") and clean["last_touch"] != old:  # "Touched today" / a date you typed
        _log_touch(cid, clean["last_touch"])
    return clean


def remove(cid: int) -> None:
    get(cid)
    db.con().execute("DELETE FROM job_contacts WHERE contact_id=?", (cid,))
    db.con().execute("DELETE FROM touches WHERE contact_id=?", (cid,))
    db.con().execute("DELETE FROM contacts WHERE id=?", (cid,))
    db.con().commit()


def rows(q: str = "", due_only: bool = False) -> list[dict]:
    """Every contact, name A-Z, with its linked jobs ('jobs': count, 'job_list': '#3 Acme, #7 Globex').
    q: case-insensitive substring of name, company, position or email."""
    out = [dict(r) for r in db.con().execute(
        "SELECT c.*, (SELECT COUNT(*) FROM job_contacts jc WHERE jc.contact_id=c.id) jobs, "
        "(SELECT GROUP_CONCAT('#' || j.id || ' ' || j.company, ', ') FROM job_contacts jc JOIN jobs j ON j.id=jc.job_id "
        "WHERE jc.contact_id=c.id) job_list FROM contacts c ORDER BY c.name COLLATE NOCASE").fetchall()]
    if q := (q or "").strip().lower():
        out = [c for c in out if q in " ".join(c[k] or "" for k in ("name", "company", "position", "email")).lower()]
    if due_only:
        ids = {c["id"] for c in due()}
        out = [c for c in out if c["id"] in ids]
    return out


def due(today: str | None = None) -> list[sqlite3.Row]:
    """Contacts whose next_touch has come and who have not been in touch on or after that day. Surfaced only (Today
    panel, `lodestar contacts due`): nothing is drafted or sent for them automatically."""
    return db.con().execute("SELECT * FROM contacts WHERE next_touch <= ? AND (last_touch IS NULL OR last_touch < next_touch) "
                            "ORDER BY next_touch, name COLLATE NOCASE", (today or date.today().isoformat(),)).fetchall()


def touch(email: str, when: str | None = None) -> int:
    """Mail from or to exactly this address: the contact who has it gets last_touch = that day (never moved back, never
    in the future). Returns how many contacts changed (0 or 1). Changes no job and no trust decision."""
    e = (email or "").strip().lower()
    if not EMAIL_RE.fullmatch(e):
        return 0
    today = date.today().isoformat()
    when = min(when or today, today)
    cur = db.con().execute("UPDATE contacts SET last_touch=? WHERE email=? AND (last_touch IS NULL OR last_touch < ?)",
                           (when, e, when))
    db.con().commit()
    return cur.rowcount


# --- contacts <-> jobs --------------------------------------------------------
def link(cid: int, job_id: int, role: str = "other", keep_role: bool = False) -> None:
    """Link a contact to a job with a role (again: changes the role, unless keep_role)."""
    if role not in ROLES:
        raise SystemExit(f"role must be one of {', '.join(ROLES)}")
    get(cid), db.get_job(job_id)
    db.con().execute("INSERT INTO job_contacts(job_id, contact_id, role) VALUES(?,?,?) ON CONFLICT(job_id, contact_id) "
                     + ("DO NOTHING" if keep_role else "DO UPDATE SET role=excluded.role"), (job_id, cid, role))
    db.con().commit()


def unlink(cid: int, job_id: int) -> None:
    db.con().execute("DELETE FROM job_contacts WHERE job_id=? AND contact_id=?", (job_id, cid))
    db.con().commit()


def job_people(job_id: int) -> list[dict]:
    return [dict(r) for r in db.con().execute(
        "SELECT c.id, c.name, c.email, c.company, c.position, c.linkedin_url, jc.role FROM job_contacts jc "
        "JOIN contacts c ON c.id=jc.contact_id WHERE jc.job_id=? ORDER BY c.name COLLATE NOCASE", (job_id,)).fetchall()]


def contact_jobs(cid: int) -> list[dict]:
    return [dict(r) for r in db.con().execute(
        "SELECT j.id, j.company, j.title, j.status, jc.role FROM job_contacts jc JOIN jobs j ON j.id=jc.job_id "
        "WHERE jc.contact_id=? ORDER BY j.updated_at DESC", (cid,)).fetchall()]


def contact_events(cid: int, limit: int = 30) -> list[dict]:
    """Recent job timeline entries that mention this contact's email address (mail sent to them, replies)."""
    e = get(cid)["email"]
    return [dict(r) for r in db.con().execute(
        "SELECT e.ts, e.kind, e.detail, e.job_id, j.company FROM events e LEFT JOIN jobs j ON j.id=e.job_id "
        "WHERE instr(lower(e.detail), ?) > 0 ORDER BY e.ts DESC, e.id DESC LIMIT ?", (e, limit)).fetchall()] if e else []


def from_job_contact(job_id: int, name: str, email: str) -> int | None:
    """The job's own contact field (drawer, `jobs contact`) also files the person under Contacts, linked as recruiter:
    one contact per address (else per name + company); a known one keeps its record and its role on the job.
    Only this direction: no contact ever becomes a job's contact by itself."""
    job = db.get_job(job_id)
    e = (email or "").strip().lower()
    name = " ".join((name or "").split()) or e.split("@")[0]
    if not name:
        return None
    row = (db.con().execute("SELECT id FROM contacts WHERE email=?", (e,)).fetchone() if e else
           db.con().execute("SELECT id FROM contacts WHERE email IS NULL AND lower(name)=? AND lower(COALESCE(company,''))=?",
                            (name.lower(), job["company"].lower())).fetchone())
    cid = row["id"] if row else add(f"job #{job_id}", name=name[:120], email=e, company=job["company"][:120])
    link(cid, job_id, "recruiter", keep_role=True)
    return cid


# --- warm paths ---------------------------------------------------------------
def warm_index() -> tuple[dict, dict]:
    """Contacts by normalised company name and by its distinctive words; built once per board or search refresh."""
    from .web_monitor import norm_company

    exact: dict[str, list] = {}
    words: dict[str, list] = {}
    for c in db.con().execute("SELECT id, name, position, company FROM contacts WHERE COALESCE(company, '') != ''"):
        p = {"id": c["id"], "name": c["name"], "position": c["position"] or ""}
        if k := norm_company(c["company"]):
            exact.setdefault(k, []).append(p)
        toks = frozenset(db._tokens(c["company"]))
        for t in toks:
            words.setdefault(t, []).append((toks, p))
    return exact, words


def warm(company: str, idx: tuple[dict, dict] | None = None) -> list[dict]:
    """Contacts at this company: the same normalised name ('Acme, Inc.' = 'ACME'), or every distinctive word of the
    shorter name inside the longer ('Amazon' ~ 'Amazon Web Services'), the rule db.find_job_by_company uses."""
    # ponytail: loose name match, a hint; a contact at an agency named after its client can show up too
    from .web_monitor import norm_company

    exact, words = idx or warm_index()
    k = norm_company(company or "")
    out = {p["id"]: p for p in exact.get(k, [])} if k else {}
    jt = db._tokens(company or "")
    for t in jt:
        for ct, p in words.get(t, []):
            if (ct <= jt) if len(ct) <= len(jt) else (jt <= ct):
                out[p["id"]] = p
    return sorted(out.values(), key=lambda p: p["name"].lower())


def with_warm(listings: list[dict]) -> list[dict]:
    """Search results gain 'warm': the people you know at each listing's company."""
    idx = warm_index()
    for j in listings:
        j["warm"] = warm(j.get("company") or "", idx)
    return listings


def referral(job, cid: int, provider: str | None = None) -> dict:
    """Draft a referral ask to a contact about this job through extras.outreach. With their email it is proposed via
    the Inbox and always waits for your review; without one it is a LinkedIn note you send yourself. The contact is
    linked as referrer unless they already have a role on this job."""
    from .extras import outreach

    c = get(cid)
    person = ", ".join(x for x in (c["name"], c["position"]) if x)
    r = outreach(job, person, "email" if c["email"] else "linkedin", provider, to=c["email"] or "", goal=REFERRAL)
    link(cid, job["id"], "referrer", keep_role=True)
    db.add_event(job["id"], "referral", f"referral ask drafted for {c['name']}")
    return r


# --- LinkedIn connections import ------------------------------------------------
def import_connections(data: bytes, filename: str = "") -> dict:
    """Your LinkedIn Connections.csv (or the export zip holding it) into contacts. De-dup by LinkedIn URL, then email,
    then name + company (only when URL and email do not contradict). A known contact only gains the fields it lacks,
    so your edits stay. No next_touch: a follow-up cadence is opt-in per contact."""
    from .profile import linkedin_connections
    from .web_monitor import norm_company

    def ok(k, v):  # a malformed field is dropped, not the whole row
        try:
            return _clean(k, v)
        except SystemExit:
            return None

    have = [dict(r) for r in db.con().execute("SELECT * FROM contacts").fetchall()]
    by_url = {c["linkedin_url"]: c for c in have if c["linkedin_url"]}
    by_email = {c["email"]: c for c in have if c["email"]}
    by_name = {(c["name"].lower(), norm_company(c["company"] or "")): c for c in have}
    n = {"rows": 0, "added": 0, "updated": 0, "skipped": 0}
    for r in linkedin_connections(data, filename):
        n["rows"] += 1
        f = {k: ok(k, r.get(k)) for k in ("name", "linkedin_url", "email", "company", "position")}
        if not f["name"]:
            n["skipped"] += 1
            continue
        if r.get("connected_on"):
            f["how_met"] = ok("how_met", f"LinkedIn connection since {r['connected_on']}")
        key = (f["name"].lower(), norm_company(f["company"] or ""))
        c = by_url.get(f["linkedin_url"]) or by_email.get(f["email"])
        if not c and (c := by_name.get(key)) and any(f[k] and c[k] and f[k] != c[k] for k in ("linkedin_url", "email")):
            c = None  # same name at the same company, but a different person
        if c:
            fill = {k: v for k, v in f.items() if v and not c[k]
                    and not (k == "email" and v in by_email) and not (k == "linkedin_url" and v in by_url)}
            if fill:
                db.con().execute(f"UPDATE contacts SET {', '.join(k + '=?' for k in fill)} WHERE id=?", (*fill.values(), c["id"]))
                c.update(fill)
                n["updated"] += 1
            else:
                n["skipped"] += 1
        else:
            c = {k: v for k, v in f.items() if v} | {"source": "linkedin"}
            c["id"] = db.con().execute(f"INSERT INTO contacts({', '.join(c)}) VALUES({', '.join('?' * len(c))})",
                                       tuple(c.values())).lastrowid
            c = {k: c.get(k) for k in ("id", "name", "linkedin_url", "email", "company", "position", "how_met")}
            n["added"] += 1
        for m, k in ((by_url, c["linkedin_url"]), (by_email, c["email"])):
            if k:
                m[k] = c
        by_name.setdefault((c["name"].lower(), norm_company(c["company"] or "")), c)
    db.con().commit()  # one commit: thousands of connections import in a blink
    return n
