"""SQLite application tracker: jobs, events, url watches, dedupe table."""
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .config import DB_PATH

# order matters: callers move a job only forward by index (accepted sits before the two closed states)
STATUSES = ["saved", "applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn"]
POSITIVE = ("screening", "interview", "offer", "accepted")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, url TEXT, status TEXT DEFAULT 'saved',
  jd TEXT, notes TEXT, applied_at TEXT,
  created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id INTEGER, ts TEXT DEFAULT (datetime('now')), kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS watches(id INTEGER PRIMARY KEY, url TEXT UNIQUE, keywords TEXT, last_hash TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY, ts TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS pending(id INTEGER PRIMARY KEY, ts TEXT DEFAULT (datetime('now')), tool TEXT, kind TEXT,
  job_id INTEGER, summary TEXT, payload TEXT, status TEXT DEFAULT 'pending', result TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS ideas(id INTEGER PRIMARY KEY, topic TEXT, title TEXT, body TEXT, score REAL,
  status TEXT DEFAULT 'new', job_id INTEGER, tags TEXT, created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, question TEXT UNIQUE, answer TEXT, tags TEXT,
  updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, vendor TEXT NOT NULL, slug TEXT NOT NULL, name TEXT,
  keywords TEXT, last_seen TEXT, last_error TEXT, UNIQUE(vendor, slug));
CREATE TABLE IF NOT EXISTS postings(key TEXT PRIMARY KEY, url TEXT, first_seen TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS sponsors(key TEXT, year TEXT, name TEXT, approvals INTEGER, PRIMARY KEY(key, year));
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, phone TEXT, linkedin_url TEXT,
  company TEXT, position TEXT, how_met TEXT, source TEXT, last_touch TEXT, next_touch TEXT, notes TEXT,
  created_at TEXT DEFAULT (datetime('now')));
CREATE UNIQUE INDEX IF NOT EXISTS contacts_email ON contacts(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS contacts_linkedin ON contacts(linkedin_url) WHERE linkedin_url IS NOT NULL;
CREATE TABLE IF NOT EXISTS job_contacts(job_id INTEGER NOT NULL, contact_id INTEGER NOT NULL, role TEXT NOT NULL DEFAULT 'other',
  UNIQUE(job_id, contact_id));
CREATE TABLE IF NOT EXISTS interviews(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, round INTEGER, kind TEXT DEFAULT 'other',
  at TEXT, interviewers TEXT, notes TEXT, questions_asked TEXT, outcome TEXT DEFAULT 'pending', ics TEXT,
  created_at TEXT DEFAULT (datetime('now')));
CREATE INDEX IF NOT EXISTS interviews_job ON interviews(job_id);
CREATE TABLE IF NOT EXISTS mock_sessions(id INTEGER PRIMARY KEY, job_id INTEGER, ts TEXT DEFAULT (datetime('now')), answers TEXT,
  averages TEXT);
CREATE TABLE IF NOT EXISTS offers(job_id INTEGER PRIMARY KEY, base INTEGER, bonus_pct REAL, sign_on INTEGER,
  equity_value_estimate INTEGER, vest_years INTEGER, cliff_months INTEGER, retirement_match_pct REAL, remote TEXT,
  start_date TEXT, deadline TEXT, notes TEXT, updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER);  -- 'jobs_max_id': ids are never handed out twice
CREATE TABLE IF NOT EXISTS touches(contact_id INTEGER NOT NULL, day TEXT NOT NULL, UNIQUE(contact_id, day));  -- touches you record (contacts._log_touch)
CREATE TABLE IF NOT EXISTS mail(id INTEGER PRIMARY KEY, message_id TEXT NOT NULL UNIQUE, in_reply_to TEXT, refs TEXT,
  job_id INTEGER, direction TEXT NOT NULL CHECK(direction IN ('in','out')), from_addr TEXT, to_addr TEXT, subject TEXT,
  sent_at TEXT, category TEXT, summary TEXT, snippet TEXT, trusted INTEGER NOT NULL DEFAULT 0,
  linked_by TEXT CHECK(linked_by IN ('auto','thread','user')), company TEXT, title TEXT,
  created_at TEXT DEFAULT (datetime('now')));  -- relevant mail scanned + every mail sent; job_id NULL = unmatched
CREATE INDEX IF NOT EXISTS mail_job ON mail(job_id);
-- pipeline (pipeline.py): one row per (job, stage); stage '_summary' holds the derived board summary of a job
CREATE TABLE IF NOT EXISTS pipeline(job_id INTEGER NOT NULL, stage TEXT NOT NULL,
  state TEXT NOT NULL,             -- done | waiting | error | running | skipped (the rest is derived on read)
  output TEXT, inputs TEXT, fp TEXT, rev INTEGER NOT NULL DEFAULT 0,
  origin TEXT,                     -- user | autopilot | approved | observed
  error TEXT, attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT, PRIMARY KEY(job_id, stage));
CREATE TABLE IF NOT EXISTS pipeline_runs(id INTEGER PRIMARY KEY, job_id INTEGER, stage TEXT,
  ts TEXT DEFAULT (datetime('now')), origin TEXT, outcome TEXT, detail TEXT, ai INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS pipeline_runs_ts ON pipeline_runs(ts);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, key TEXT NOT NULL, text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'text', options TEXT, context TEXT,
  blocking INTEGER NOT NULL DEFAULT 1, apply_to TEXT NOT NULL DEFAULT 'bank', job_id INTEGER,
  status TEXT NOT NULL DEFAULT 'open', answer TEXT, scope TEXT, answer_id INTEGER,
  created_at TEXT DEFAULT (datetime('now')), answered_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS questions_open ON questions(key) WHERE status = 'open';
CREATE TABLE IF NOT EXISTS question_waiters(qid INTEGER NOT NULL, job_id INTEGER NOT NULL, stage TEXT NOT NULL,
  PRIMARY KEY(qid, job_id, stage));
"""
MIGRATIONS = {"resume_hash": "TEXT", "contact_email": "TEXT", "contact_name": "TEXT",  # ponytail: additive only
              # tracker fields (pass 15); every user write goes through set_fields
              "location": "TEXT", "remote": "TEXT", "salary_min": "INTEGER", "salary_max": "INTEGER", "currency": "TEXT",
              "source": "TEXT", "posted_at": "TEXT", "deadline": "TEXT", "excitement": "INTEGER", "tags": "TEXT",
              "match_score": "INTEGER", "next_action": "TEXT", "next_action_at": "TEXT",
              "ats_skip": "TEXT",  # JSON list: keywords marked "not mine" for JD coverage (toggle_ats_skip)
              "ats_feed": "TEXT"}  # 'greenhouse:acme' when tracked from a public job-board feed (code-set, not a user field)
WATCH_MIGRATIONS = {"filters": "TEXT",  # JSON search filters of a saved search (web_monitor.clean_filters)
                    "last_error": "TEXT"}  # what the last run could not read (shown on the watch); NULL after a clean run
ANSWER_MIGRATIONS = {"star": "TEXT",  # JSON STAR fields when the row is a story (interview.save_story); NULL = a form answer
                     "private": "INTEGER NOT NULL DEFAULT 0",  # 1 = for you only: never put in an employer-facing prompt
                     "source": "TEXT"}  # where it came from: "answered for job #12 (answers)", "typed under Answers"
MAIL_MIGRATIONS = {"attachments": "TEXT"}  # JSON [{name, size, type, path?} | {name, skipped}] (mailfiles.py)
BACKFILL_KEY = "backfill:fields-v1"
CONTACTS_KEY = "backfill:contacts-v1"
ATS_FEED_RE = re.compile(r"(greenhouse|lever|ashby):[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def connect(path=None) -> sqlite3.Connection:
    c = sqlite3.connect(path or DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for table, cols in (("jobs", MIGRATIONS), ("watches", WATCH_MIGRATIONS), ("answers", ANSWER_MIGRATIONS),
                        ("mail", MAIL_MIGRATIONS)):
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col in have:
                continue
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:  # another thread/process added it between our check and ALTER
                if "duplicate column" not in str(e).lower():
                    raise
    backfill(c)
    contacts_from_jobs(c)
    return c


def backfill(c: sqlite3.Connection) -> int:
    """Fill source / remote / salary on rows that predate those columns, from their notes and JD. Writes only NULLs and
    leaves updated_at alone, so a rerun changes nothing; the seen-table marker just skips the scan after the first run."""
    if c.execute("SELECT 1 FROM seen WHERE key=?", (BACKFILL_KEY,)).fetchone():
        return 0
    n = 0
    for r in c.execute("SELECT id, jd, notes, source, remote, salary_min, salary_max, currency FROM jobs").fetchall():
        d = {k: v for k, v in derive_fields(r["jd"], r["notes"]).items() if v is not None and r[k] is None}
        if d:
            c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in d)} WHERE id=?", (*d.values(), r["id"]))
            n += 1
    c.execute("INSERT OR IGNORE INTO seen(key) VALUES(?)", (BACKFILL_KEY,))
    c.commit()
    return n


def contacts_from_jobs(c: sqlite3.Connection) -> int:
    """One-time: each job's stored contact (contact_email / contact_name) becomes a contact linked to it as recruiter,
    one contact per address (else per name + company). The job columns stay as they are: they alone drive mail trust."""
    if c.execute("SELECT 1 FROM seen WHERE key=?", (CONTACTS_KEY,)).fetchone():
        return 0
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")  # first connections after an upgrade (loop + request threads) race: one runs it, once
    try:
        n = _contacts_from_jobs(c)
    except BaseException:
        c.rollback()
        raise
    c.commit()
    return n


def _contacts_from_jobs(c: sqlite3.Connection) -> int:
    if c.execute("SELECT 1 FROM seen WHERE key=?", (CONTACTS_KEY,)).fetchone():  # another connection got here first
        return 0
    n = 0
    for j in c.execute("SELECT id, company, contact_email, contact_name FROM jobs WHERE COALESCE(contact_email, '') != '' "
                       "OR COALESCE(contact_name, '') != '' ORDER BY id").fetchall():
        email = (j["contact_email"] or "").strip().lower() or None
        name = (j["contact_name"] or "").strip()[:120] or (email or "").split("@")[0] or "contact"
        row = (c.execute("SELECT id FROM contacts WHERE email=?", (email,)).fetchone() if email else
               c.execute("SELECT id FROM contacts WHERE email IS NULL AND lower(name)=? AND lower(COALESCE(company,''))=?",
                         (name.lower(), (j["company"] or "").lower())).fetchone())
        if not row:
            cid = c.execute("INSERT INTO contacts(name, email, company, source) VALUES(?,?,?,?)",
                            (name, email, j["company"], f"job #{j['id']}")).lastrowid
            n += 1
        else:
            cid = row["id"]
        c.execute("INSERT OR IGNORE INTO job_contacts(job_id, contact_id, role) VALUES(?,?,'recruiter')", (j["id"], cid))
    c.execute("INSERT OR IGNORE INTO seen(key) VALUES(?)", (CONTACTS_KEY,))
    return n


# --- tracker fields ---------------------------------------------------------
REMOTE = ("onsite", "hybrid", "remote")
REMOTE_BOARDS = ("remotive", "remoteok", "jobicy")  # job APIs that only list remote roles
_TEXT = {"location": 120, "source": 60, "next_action": 200}
_INT = {"salary_min": (0, 10_000_000), "salary_max": (0, 10_000_000), "excitement": (1, 5), "match_score": (0, 100)}
_DATE = ("posted_at", "deadline", "next_action_at")
FIELDS = (*_TEXT, *_INT, *_DATE, "remote", "currency", "tags")


def source_of(notes) -> str:
    """Where a job came from, read off the notes add paths write: captured / search:<api> / email / manual."""
    n = notes or ""
    if "captured from" in n:
        return "captured"
    if "via " in n:
        return "search:" + (n.split("via ")[-1].split() or ["?"])[0].strip("()")
    return "email" if "from email" in n else "manual"


# 'hybrid' as a workplace, not 'hybrid cloud' / 'hybrid app' in a tech stack
HYBRID_RE = re.compile(r"\bhybrid\b(?![- ](?:cloud|infrastructure|environments?|apps?|mobile|multi-cloud|architecture|it)\b)")


def remote_kind(text) -> str | None:
    t = (text or "").lower()
    return ("hybrid" if HYBRID_RE.search(t) else "remote" if re.search(r"\bremote\b", t)
            else "onsite" if re.search(r"\bon-?site\b|\bin[- ]office\b", t) else None)


def derive_fields(jd, notes, location="") -> dict:
    """Tracker fields a listing already carries: source from the notes, pay from the JD, remote from location + JD."""
    from .resume import parse_salary

    src = source_of(notes)
    remote = "remote" if src.split(":")[-1] in REMOTE_BOARDS else remote_kind(f"{location or ''}\n{(jd or '')[:1500]}")
    return {"source": src, "remote": remote, **parse_salary(jd or "")}


def tag_list(tags) -> list[str]:
    return [t.strip() for t in (tags or "").split(",") if t.strip()]


def valid_date(k: str, s: str) -> str:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            raise ValueError
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"{k} must be a date, YYYY-MM-DD: {s[:40]}") from None
    return s


def _clean(k: str, v):
    """One user-settable field, validated. Empty clears (None)."""
    if k not in FIELDS:
        raise SystemExit(f"unknown field '{k}'. Fields: {', '.join(FIELDS)}")
    s = "" if v is None else str(v).strip()
    if not s:
        return None
    if k in _INT:
        lo, hi = _INT[k]
        try:
            n = int(s[:-1]) * 1000 if k.startswith("salary") and s[-1] in "kK" else int(s)
        except ValueError:
            raise SystemExit(f"{k} must be a whole number: {s[:40]}") from None
        if not lo <= n <= hi:
            raise SystemExit(f"{k} must be between {lo} and {hi}")
        return n
    if k in _DATE:
        return valid_date(k, s)
    if k == "remote":
        if s.lower() not in REMOTE:
            raise SystemExit(f"remote must be one of {', '.join(REMOTE)}")
        return s.lower()
    if k == "currency":
        if not re.fullmatch(r"[A-Za-z]{3}", s):
            raise SystemExit("currency must be a 3-letter code, e.g. USD")
        return s.upper()
    if k == "tags":
        tags = list(dict.fromkeys(tag_list(s)))
        if len(tags) > 20 or any(len(t) > 40 for t in tags):
            raise SystemExit("tags: at most 20, each up to 40 characters")
        return ",".join(tags) or None
    if len(s) > _TEXT[k]:
        raise SystemExit(f"{k} is longer than {_TEXT[k]} characters")
    return s


def set_fields(job_id: int, **fields) -> dict:
    """Set whitelisted tracker fields (FIELDS); every value is validated first, so a bad one changes nothing."""
    clean = {k: _clean(k, v) for k, v in fields.items()}
    row = get_job(job_id)
    lo, hi = (clean[k] if k in clean else row[k] for k in ("salary_min", "salary_max"))
    if lo is not None and hi is not None and lo > hi:
        raise SystemExit(f"salary_min ({lo}) is above salary_max ({hi})")
    if clean:
        update_job(job_id, touch=False, **clean)  # tracker metadata, not activity: 'stalest first' must stay true
    return clean


def ats_skip(job) -> list[str]:
    """Keywords the user marked "not mine" for this job's JD coverage."""
    try:
        return [str(t) for t in json.loads(job["ats_skip"] or "[]")]
    except (ValueError, TypeError):
        return []


def toggle_ats_skip(job_id: int, term) -> list[str]:
    """Mark a JD keyword "not mine" for this job, or unmark it. Returns the new list."""
    t = " ".join(str(term or "").lower().split())
    if not 0 < len(t) <= 80:
        raise SystemExit("term must be 1-80 characters")
    terms = ats_skip(get_job(job_id))
    terms = [x for x in terms if x != t] if t in terms else [*terms, t]
    if len(terms) > 300:
        raise SystemExit("at most 300 skipped keywords per job")
    update_job(job_id, touch=False, ats_skip=json.dumps(terms) if terms else None)
    return terms


_local = threading.local()  # one connection per thread: the web UI serves requests from a thread pool


def con() -> sqlite3.Connection:
    c = getattr(_local, "con", None)
    if c is None:
        c = _local.con = connect()
    return c


def release(close: bool = True) -> None:
    """Roll back whatever a failed write left open on this thread's connection (an INSERT that hit a UNIQUE index keeps
    its implicit transaction, and with it the database write lock, until rollback), and close it when the thread is
    done: request and task threads end here. A thread-local connection is otherwise freed only by the cyclic GC, so
    an open transaction on it would lock every other writer ('database is locked') until a collection happens."""
    c = getattr(_local, "con", None)
    if c is None:
        return
    try:
        if c.in_transaction:
            c.rollback()
    finally:
        if close:
            _local.con = None
            c.close()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add_job(company, title, url=None, jd=None, notes=None, ats_feed=None, **fields) -> int:
    """fields: tracker fields the caller knows (a listing's location, posted_at). Source, remote and pay are derived
    from the notes and JD; a field given explicitly wins. ats_feed: the public job-board feed it came from."""
    given = {k: v for k, v in ((k, _clean(k, v)) for k, v in fields.items()) if v is not None}  # validated before insert
    if ats_feed:
        if not ATS_FEED_RE.fullmatch(str(ats_feed)):
            raise SystemExit(f"ats_feed must look like greenhouse:slug, lever:slug or ashby:slug: {str(ats_feed)[:60]}")
        given["ats_feed"] = str(ats_feed)
    if url:  # the same posting captured or searched twice is one card, not two
        dup = con().execute("SELECT id FROM jobs WHERE url=? AND status NOT IN ('rejected','withdrawn')", (url,)).fetchone()
        if dup:
            add_event(dup["id"], "duplicate", f"add ignored: {company} - {title}")
            return dup["id"]
    derived = derive_fields(jd, notes, given.get("location"))
    if {"salary_min", "salary_max"} & given.keys():  # a stated range replaces the parsed one whole, never half of it
        derived = {k: v for k, v in derived.items() if not k.startswith("salary") and k != "currency"}
    extra = {k: v for k, v in derived.items() if v is not None} | given
    if extra.get("salary_min", 0) > extra.get("salary_max", 10**9):
        raise SystemExit("salary_min is above salary_max")
    c = con()
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")  # the next id is read and taken in one step, even with the loop adding jobs too
    try:
        # never reuse a deleted job's id: what delete_job leaves behind (sent mail and decided Inbox items, ideas, the
        # applications/<id>-... folder) would attach to the new job. Leftover references count for databases from
        # before the high-water mark existed.
        jid = 1 + max(c.execute("SELECT MAX(COALESCE((SELECT MAX(id) FROM jobs), 0), COALESCE((SELECT MAX(job_id) FROM "
                                "pending), 0), COALESCE((SELECT MAX(job_id) FROM ideas), 0), COALESCE((SELECT MAX(job_id) "
                                "FROM mail), 0), COALESCE((SELECT value FROM meta WHERE key='jobs_max_id'), 0))"
                                ).fetchone()[0], 0)
        c.execute("INSERT INTO jobs(id,company,title,url,jd,notes) VALUES(?,?,?,?,?,?)", (jid, company, title, url, jd, notes))
        c.execute("INSERT INTO meta(key, value) VALUES('jobs_max_id', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (jid,))
        if extra:
            c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in extra)} WHERE id=?", (*extra.values(), jid))
        c.commit()
    except BaseException:
        c.rollback()
        raise
    add_event(jid, "created", f"{company} - {title}")
    return jid


def get_job(job_id: int) -> sqlite3.Row:
    row = con().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"no job #{job_id}")
    return row


def _pay(j):
    return j["salary_max"] if j["salary_max"] is not None else j["salary_min"]


# sort key -> row key; None sorts last, ties keep the most recently updated first
SORTS = {"match": lambda j: (j["match_score"] is None, -(j["match_score"] or 0)),
         "salary": lambda j: (_pay(j) is None, -(_pay(j) or 0)),
         "excitement": lambda j: (j["excitement"] is None, -(j["excitement"] or 0)),
         "deadline": lambda j: (j["deadline"] is None, j["deadline"] or ""),
         "updated": None}


def list_jobs(status=None, sort=None, remote=None, min_salary=None, tag=None):
    q, args = "SELECT * FROM jobs", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    rows = con().execute(q + " ORDER BY updated_at DESC", args).fetchall()
    if remote:
        rows = [j for j in rows if j["remote"] == remote]
    if min_salary:
        rows = [j for j in rows if _pay(j) is None or _pay(j) >= min_salary]  # unknown pay is kept, as search does
    if tag:
        rows = [j for j in rows if tag.strip().lower() in (t.lower() for t in tag_list(j["tags"]))]
    if SORTS.get(sort):
        rows.sort(key=SORTS[sort])
    return rows


def update_job(job_id: int, touch: bool = True, **fields) -> None:
    """touch=False for derived or bookkeeping fields (match score, tags, 'not mine'): they are not 'last activity'."""
    if touch:
        fields["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in fields)
    con().execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
    con().commit()


def set_status(job_id: int, status: str, detail: str = "") -> None:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    get_job(job_id)  # 'no job #N': a typo never writes an orphan timeline event the funnel would count
    # applied_at is the day you applied where you are: an evening application must not be dated tomorrow (UTC)
    extra = {"applied_at": datetime.now().strftime("%Y-%m-%d")} if status == "applied" else {}
    # status proposals waiting in the Inbox were made against the old status: close them (the one running now is not
    # 'pending', so an approved proposal never closes itself)
    con().execute("UPDATE pending SET status='rejected', decided_at=?, result=? WHERE job_id=? AND kind IN "
                  "('set_status', 'run_to') AND status='pending'",
                  (_now(), f"stale: the job moved to {status} before this was decided", job_id))
    if status in ("withdrawn", "rejected", "accepted"):  # 'still very interested' must never go out after the end
        con().execute("UPDATE pending SET status='rejected', decided_at=?, result=? WHERE job_id=? AND kind='send_email' "
                      "AND status='pending' AND json_extract(payload, '$.purpose') IN ('followup', 'thanks')",
                      (_now(), f"stale: the job moved to {status} before this was sent", job_id))
    update_job(job_id, status=status, **extra)
    add_event(job_id, "status", f"{status} {detail}".strip())
    if status == "accepted":  # a hire: offer to close the other live applications, always through the Inbox
        from . import approvals

        for j in list_jobs():
            if j["id"] != job_id and j["status"] in ("applied", "screening", "interview", "offer"):
                approvals.propose("followup", "set_status", {"job_id": j["id"], "status": "withdrawn", "note": "accepted another offer"},
                                  f"withdraw #{j['id']} {j['company']} - {j['title']} (accepted #{job_id})", j["id"],
                                  force_pending=True)


def delete_job(job_id: int) -> None:
    get_job(job_id)  # 'no job #N' instead of reporting a delete that did nothing
    con().execute("DELETE FROM pending WHERE job_id=? AND status='pending'", (job_id,))  # nothing may act for a gone job
    con().execute("DELETE FROM events WHERE job_id=?", (job_id,))
    con().execute("DELETE FROM job_contacts WHERE job_id=?", (job_id,))  # the people stay; only the link goes
    con().execute("DELETE FROM interviews WHERE job_id=?", (job_id,))
    con().execute("DELETE FROM mock_sessions WHERE job_id=?", (job_id,))
    con().execute("DELETE FROM offers WHERE job_id=?", (job_id,))
    con().execute("DELETE FROM mail WHERE job_id=?", (job_id,))  # a reply to its sent mail then reads as unmatched
    for t in ("pipeline", "pipeline_runs", "question_waiters"):
        con().execute(f"DELETE FROM {t} WHERE job_id=?", (job_id,))
    con().execute("UPDATE questions SET status='dismissed', answer='no longer needed', answered_at=? WHERE status='open' "
                  "AND NOT EXISTS (SELECT 1 FROM question_waiters w WHERE w.qid=questions.id)", (_now(),))
    con().execute("DELETE FROM jobs WHERE id=?", (job_id,))
    con().commit()


def add_event(job_id: int, kind: str, detail: str = "") -> None:
    con().execute("INSERT INTO events(job_id,kind,detail) VALUES(?,?,?)", (job_id, kind, detail))
    con().commit()


def events(job_id: int):
    return con().execute("SELECT * FROM events WHERE job_id=? ORDER BY ts", (job_id,)).fetchall()


_GENERIC = {"inc", "corp", "corporation", "llc", "ltd", "the", "group", "company", "co", "labs", "technologies", "software", "team", "careers", "jobs", "recruiting", "talent"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) >= 4 and t not in _GENERIC}


def find_job_by_company(name: str):
    """Loose match for messy sources (email senders like 'Acme Recruiting <careers@acme.com>').
    Matches on whole-string containment or any distinctive word of the tracked company name."""
    name = (name or "").lower().strip()
    if len(name) < 3:
        return None
    toks = _tokens(name)
    for row in list_jobs():
        if row["status"] in ("rejected", "withdrawn"):
            continue
        c = row["company"].lower()
        ct = _tokens(c)
        if not ct:
            continue
        # every distinctive word of the shorter name must appear in the longer one: 'Meta' in 'Meta Platforms', but
        # 'National Grid' is not 'First National Bank'
        short, long_ = (ct, toks) if len(ct) <= len(toks) else (toks, ct)
        if c == name or (short and short <= long_):
            return row
    return None


def applied_ids() -> set[int]:
    """Jobs you actually applied to: applied_at set, or a status of applied or later (now or in the timeline). A saved
    job you withdraw, or one closed as rejected before you applied, is not an application."""
    ids = {r["id"] for r in con().execute(f"SELECT id FROM jobs WHERE applied_at IS NOT NULL OR status IN "
                                          f"({','.join('?' * len(STAGE_ORDER))})", STAGE_ORDER)}
    ids |= {e["job_id"] for e in con().execute("SELECT job_id, detail FROM events WHERE kind='status'")
            if (e["detail"] or "").split(" ")[0] in STAGE_ORDER}
    return ids


def stats() -> dict:
    rows = con().execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    counts = {s: 0 for s in STATUSES} | {r["status"]: r["n"] for r in rows}
    done = applied_ids()
    mine = [j["status"] for j in con().execute("SELECT id, status FROM jobs").fetchall() if j["id"] in done]
    applied = len(mine)
    positive = sum(s in POSITIVE for s in mine)
    responded = positive + mine.count("rejected")
    return {
        "counts": counts,
        "applied_total": applied,
        "response_rate": round(responded / applied, 2) if applied else 0.0,
        "interview_rate": round(positive / applied, 2) if applied else 0.0,
    }


def variant_stats() -> list[dict]:
    """Outcomes per resume variant (hash of the tailored resume), best interview rate first."""
    done, groups = applied_ids(), {}
    for j in con().execute("SELECT id, resume_hash, status FROM jobs WHERE resume_hash IS NOT NULL").fetchall():
        if j["id"] in done:
            g = groups.setdefault(j["resume_hash"], [0, 0, 0])
            g[0], g[1], g[2] = g[0] + 1, g[1] + (j["status"] in POSITIVE), g[2] + (j["status"] == "rejected")
    out = [{"variant": h, "applied": n, "positive": pos, "rejected": neg,
            "response_rate": round((pos + neg) / n, 2), "interview_rate": round(pos / n, 2)}
           for h, (n, pos, neg) in groups.items()]
    return sorted(out, key=lambda v: -v["interview_rate"])


# Timeline entries that are Lodestar's own bookkeeping, not contact with the employer: an Inbox proposal, its rejection,
# a send that failed, a draft nobody sent yet, a reply draft that failed, unverified mail, an approval's result line
# (the real change logs its own 'status' / 'created' / sent-mail event). None of them restarts the follow-up clock.
BOOKKEEPING = ("proposed", "rejected_proposal", "send_failed", "set_status", "add_job", "save_answer", "reply",
               "interview_date", "email_unverified", "followup_draft", "thanks_draft", "withdraw_draft", "counter_draft",
               "reply_draft", "referral_draft", "outreach_draft", "checkin_draft", "referral", "attachments",
               "run_to",  # run_to: an approved pipeline batch (approvals writes the executor's kind as the event)
               # documents built for the job (a drawer click or a pipeline step): your prep, not contact with the employer
               "gap", "research", "bullets", "resume", "coverage", "cover_letter", "interview_prep")


def needs_followup(days: int | None = None):
    if not days:  # the board, digest and loop all follow the followup_days preference unless told otherwise
        from . import settings

        days = int(settings.pref("followup_days") or 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    # a round booked today or later is the next step already: no nudge, no follow-up mail, no 'ghosted' close-out.
    # Round times are local, so today is the local date.
    return con().execute(
        "SELECT j.* FROM jobs j WHERE j.status IN ('applied','screening','interview') "
        f"AND (SELECT MAX(ts) FROM events e WHERE e.job_id=j.id AND e.kind NOT IN ({','.join('?' * len(BOOKKEEPING))})) < ? "
        "AND NOT EXISTS (SELECT 1 FROM interviews i WHERE i.job_id=j.id AND i.at >= ?) ORDER BY updated_at",
        (*BOOKKEEPING, cutoff, datetime.now().strftime("%Y-%m-%d")),
    ).fetchall()


# --- watches & dedupe -------------------------------------------------------
def add_watch(url: str, keywords: str | None = "", filters: dict | None = None) -> bool:
    """filters: a saved search's filters, already validated (web_monitor.clean_filters); None keeps the ones it has
    (re-adding a saved search without filter fields never silently drops them), {} clears them. keywords None keeps
    its keywords too. True when a watch with this url already existed (updated, not added)."""
    old = con().execute("SELECT keywords, filters FROM watches WHERE url=?", (url,)).fetchone()
    if filters is None:
        filters = watch_filters(old) if old else {}
    if keywords is None:
        keywords = old["keywords"] if old else ""
    # an upsert, not INSERT OR REPLACE: re-adding keeps the watch's id, last run, error and a page watch's baseline
    con().execute("INSERT INTO watches(url,keywords,filters) VALUES(?,?,?) ON CONFLICT(url) DO UPDATE SET "
                  "keywords=excluded.keywords, filters=excluded.filters",
                  (url, keywords, json.dumps(filters) if filters else None))
    con().commit()
    return old is not None


def watch_filters(w) -> dict:
    try:
        return json.loads(w["filters"] or "{}")
    except (ValueError, TypeError):
        return {}


def watches():
    return con().execute("SELECT * FROM watches ORDER BY id").fetchall()


def remove_watch(wid: int) -> None:
    n = con().execute("DELETE FROM watches WHERE id=?", (wid,)).rowcount
    con().commit()
    if not n:
        raise SystemExit(f"no watch #{wid}")


def update_watch(wid: int, last_hash: str, error: str = "") -> None:
    """A run that read its source: last_seen moves on. error: what part of it failed (some job boards unreachable)."""
    con().execute("UPDATE watches SET last_hash=?, last_seen=datetime('now'), last_error=? WHERE id=?",
                  (last_hash, error[:300] or None, wid))
    con().commit()


def watch_failed(wid: int, error: str) -> None:
    """Nothing could be read: last_seen stays at the last good run and the error shows on the watch."""
    con().execute("UPDATE watches SET last_error=? WHERE id=?", (error[:300], wid))
    con().commit()


def seen(key: str) -> bool:
    return con().execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None


def mark_seen(key: str) -> None:
    con().execute("INSERT OR IGNORE INTO seen(key) VALUES(?)", (key,))
    con().commit()


# --- watched companies (public job-board feeds), repost memory, H-1B sponsor data ------------------------------------
def add_company(vendor: str, slug: str, name: str, keywords: str = "") -> int:
    """Validated by the caller (web_monitor.add_company). Adding one again updates its name and keywords."""
    con().execute("INSERT INTO companies(vendor,slug,name,keywords) VALUES(?,?,?,?) ON CONFLICT(vendor,slug) "
                  "DO UPDATE SET name=excluded.name, keywords=excluded.keywords", (vendor, slug, name, keywords))
    con().commit()
    return con().execute("SELECT id FROM companies WHERE vendor=? AND slug=?", (vendor, slug)).fetchone()["id"]


def tracked_id(urls) -> int | None:
    """The newest tracked job (any status) at one of these URLs: search marks such results, auto_track skips them."""
    urls = [u for u in urls if u]
    row = urls and con().execute(f"SELECT MAX(id) AS id FROM jobs WHERE url IN ({','.join('?' * len(urls))})", urls).fetchone()
    return row["id"] if row else None


def companies():
    return con().execute("SELECT * FROM companies ORDER BY id").fetchall()


def remove_company(cid: int) -> None:
    n = con().execute("DELETE FROM companies WHERE id=?", (cid,)).rowcount
    con().commit()
    if not n:
        raise SystemExit(f"no watched company #{cid}")


def update_company(cid: int, error: str = "") -> None:
    con().execute("UPDATE companies SET last_seen=datetime('now'), last_error=? WHERE id=?", (error or None, cid))
    con().commit()


def posting(key: str):
    """First sighting of a company+title+location: {url, first_seen} or None (web_monitor.ghost_signals)."""
    return con().execute("SELECT url, first_seen FROM postings WHERE key=?", (key,)).fetchone()


def note_posting(key: str, url: str) -> None:
    con().execute("INSERT OR IGNORE INTO postings(key,url) VALUES(?,?)", (key, url))
    con().commit()


def save_sponsors(rows: dict) -> None:
    """rows: {(key, year): (name, approvals)}. A fiscal year imported again replaces that year; other years stay."""
    con().executemany("INSERT OR REPLACE INTO sponsors(key,year,name,approvals) VALUES(?,?,?,?)",
                      [(k, y, n, a) for (k, y), (n, a) in rows.items()])
    con().commit()


def sponsor(key: str):
    return con().execute("SELECT MAX(name) name, SUM(approvals) approvals, COUNT(*) years FROM sponsors WHERE key=? "
                         "GROUP BY key", (key,)).fetchone()


def clear_sponsors() -> int:
    n = con().execute("DELETE FROM sponsors").rowcount
    con().commit()
    return n


# --- approvals inbox --------------------------------------------------------
def add_pending(tool: str, kind: str, job_id, summary: str, payload: str) -> int:
    cur = con().execute("INSERT INTO pending(tool,kind,job_id,summary,payload) VALUES(?,?,?,?,?)",
                        (tool, kind, job_id, summary, payload))
    con().commit()
    return cur.lastrowid


def get_pending(pid: int):
    row = con().execute("SELECT * FROM pending WHERE id=?", (pid,)).fetchone()
    if not row:
        raise SystemExit(f"no inbox item #{pid}")
    return row


STUCK_MINUTES = 30  # far beyond any SMTP/AI timeout: a 'running' row this old means the process died mid-action


def recover_stuck() -> int:
    """Close out items left 'running' by a crash. Never re-queued automatically: the mail may already have gone."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=STUCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    cur = con().execute(
        "UPDATE pending SET status='error', decided_at=?, result='interrupted: Lodestar stopped while this was running; "
        "check whether it happened (e.g. your Sent folder) before redoing it by hand' "
        "WHERE status='running' AND COALESCE(decided_at, ts) < ?", (_now(), cutoff))
    con().commit()
    return cur.rowcount


def list_pending(status: str | None = "pending", limit: int = 100):
    recover_stuck()
    q, args = "SELECT * FROM pending", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return con().execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()


def claim_pending(pid: int) -> bool:
    """Atomically move pending -> running. False when another thread (or a double-click) got there first."""
    # decided_at doubles as the claim time while running; decide_pending overwrites it
    cur = con().execute("UPDATE pending SET status='running', decided_at=? WHERE id=? AND status='pending'", (_now(), pid))
    con().commit()
    return cur.rowcount == 1


def requeue_pending(pid: int, payload: str, result: str) -> None:
    """A claimed item that failed before acting goes back to the Inbox, edits kept, with the reason in `result`."""
    con().execute("UPDATE pending SET status='pending', payload=?, result=?, decided_at=NULL WHERE id=? AND status='running'",
                  (payload, result, pid))
    con().commit()


def edit_pending(pid: int, payload: str) -> bool:
    """A new payload for an item still pending (an approve that claimed it first wins: False)."""
    cur = con().execute("UPDATE pending SET payload=? WHERE id=? AND status='pending'", (payload, pid))
    con().commit()
    return cur.rowcount == 1


def decide_pending(pid: int, status: str, result: str = "") -> None:
    con().execute("UPDATE pending SET status=?, result=?, decided_at=? WHERE id=?", (status, result, _now(), pid))
    con().commit()


def followup_waiting(job_id: int):
    """The follow-up email for this job already waiting in the Inbox (a pending row), or None: no second one is added."""
    return con().execute("SELECT * FROM pending WHERE job_id=? AND kind='send_email' AND status='pending' "
                         "AND json_extract(payload, '$.purpose')='followup' ORDER BY id LIMIT 1", (job_id,)).fetchone()


# --- answer bank ------------------------------------------------------------
def check_answer(question: str, answer: str, private: bool | None = None) -> tuple[str, bool]:
    """(question, private) once an answer may be saved, else SystemExit. Also run before an Inbox item is claimed."""
    if not str(question or "").strip() or not str(answer or "").strip():
        raise SystemExit("an answer needs both a question and an answer")
    q = question.strip()
    if private is None:
        row = con().execute("SELECT private FROM answers WHERE question=?", (q,)).fetchone()
        private = bool(row and row["private"])
    from .drafts import leaks

    if not private and leaks(answer):
        raise SystemExit("this answer names your salary floor (or your private Preferences), so it would reach an "
                         "employer: mark it private to keep it for yourself, or change it")
    return q, private


def save_answer(question: str, answer: str, tags: str = "", private: bool | None = None, source: str | None = None) -> int:
    """private: True keeps the answer for you only; None (AI proposals) keeps what the question already had. An answer
    that is not private and names your salary floor is refused: it would reach an employer. source: where it came from
    (None keeps the stored one). Returns the row id."""
    q, private = check_answer(question, answer, private)
    con().execute("INSERT INTO answers(question,answer,tags,updated_at,private,source) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(question) DO UPDATE SET answer=excluded.answer, tags=excluded.tags, "
                  "updated_at=excluded.updated_at, private=excluded.private, source=COALESCE(excluded.source, answers.source)",
                  (q, answer, tags, _now(), int(private), source))
    con().commit()
    return con().execute("SELECT id FROM answers WHERE question=?", (q,)).fetchone()["id"]


def list_answers(employer: bool = False):
    """employer=True: only answers safe for an employer-facing prompt or form: not private, not naming the salary floor
    (an answer saved before the guard existed is filtered here too)."""
    rows = con().execute("SELECT * FROM answers ORDER BY updated_at DESC").fetchall()
    if not employer:
        return rows
    from .drafts import leaks

    return [r for r in rows if not r["private"] and not leaks(r["answer"])]


def delete_answer(aid: int) -> None:
    con().execute("DELETE FROM answers WHERE id=?", (aid,))
    con().commit()


PROMPT_SKIP_TAGS = ("eligibility", "eeo")  # your own answers for forms, never material for an AI prompt


def employer_answers():
    """Bank rows an employer-facing AI prompt may see: list_answers(employer=True) minus eligibility / EEO answers, by
    tag or by the question itself (untagged rows and rows saved before this filter too): you type those into forms
    yourself; a model never drafts or adapts them."""
    from .pipeline import for_prompts

    return [r for r in list_answers(employer=True) if for_prompts(r)]


def find_answers(question: str, limit: int = 4, employer: bool = False):
    """Prior answers whose question shares distinctive words with this one (cheap, no embeddings). employer: as in
    employer_answers, for prompts whose output an employer reads."""
    toks = _tokens(question)
    scored = [(len(toks & _tokens(a["question"])), a) for a in (employer_answers() if employer else list_answers())]
    return [a for n, a in sorted(scored, key=lambda x: -x[0]) if n >= 1][:limit]


# --- ideas ------------------------------------------------------------------
IDEA_STATUSES = ["new", "planned", "doing", "done", "dropped"]


def add_idea(topic: str, title: str, body: str, score: float, job_id=None, tags: str = "") -> int:
    cur = con().execute("INSERT INTO ideas(topic,title,body,score,job_id,tags) VALUES(?,?,?,?,?,?)",
                        (topic, title, body, score, job_id, tags))
    con().commit()
    return cur.lastrowid


def get_idea(iid: int):
    row = con().execute("SELECT * FROM ideas WHERE id=?", (iid,)).fetchone()
    if not row:
        raise SystemExit(f"no idea #{iid}")
    return row


def list_ideas(topic: str | None = None, status: str | None = None):
    q, args = "SELECT * FROM ideas WHERE 1=1", []
    if topic:
        q += " AND topic=?"; args.append(topic)
    if status:
        q += " AND status=?"; args.append(status)
    return con().execute(q + " ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'planned' THEN 1 WHEN 'new' THEN 2 ELSE 3 END, score DESC", args).fetchall()


def update_idea(iid: int, **fields) -> None:
    if "status" in fields and fields["status"] not in IDEA_STATUSES:
        raise SystemExit(f"status must be one of {IDEA_STATUSES}")
    fields["updated_at"] = _now()
    con().execute(f"UPDATE ideas SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), iid))
    con().commit()


def delete_idea(iid: int) -> None:
    con().execute("DELETE FROM ideas WHERE id=?", (iid,))
    con().commit()


# --- mail (email_monitor records relevant mail it scans, approvals._send what it sends) -----------------------
MAIL_COLS = ("message_id", "in_reply_to", "refs", "job_id", "direction", "from_addr", "to_addr", "subject", "sent_at",
             "category", "summary", "snippet", "trusted", "linked_by", "company", "title", "attachments")


def add_mail(**fields) -> None:
    """Deduped by Message-ID: the first record of a message wins (a rescan never relinks it)."""
    att = fields.get("attachments")
    f = {k: fields.get(k) for k in MAIL_COLS} | {"trusted": int(bool(fields.get("trusted"))),
                                                 "snippet": (fields.get("snippet") or "")[:1500],
                                                 "attachments": json.dumps(att) if isinstance(att, list) and att else None}
    con().execute(f"INSERT OR IGNORE INTO mail({','.join(f)}) VALUES({','.join('?' * len(f))})", tuple(f.values()))
    con().commit()


def get_mail(mid: int) -> sqlite3.Row:
    row = con().execute("SELECT * FROM mail WHERE id=?", (mid,)).fetchone()
    if not row:
        raise SystemExit(f"no mail #{mid}")
    return row


def list_mail(job_id: int | None = None, unmatched: bool = False, limit: int = 200):
    """A job's mail both ways, or incoming mail no job claims; newest first."""
    q, args = "SELECT * FROM mail", ()
    if job_id is not None:
        q, args = q + " WHERE job_id=?", (job_id,)
    elif unmatched:
        q += " WHERE job_id IS NULL AND direction='in'"
    return con().execute(q + " ORDER BY COALESCE(sent_at, created_at) DESC, id DESC LIMIT ?", (*args, limit)).fetchall()


def thread_mail(ids: list[str]):
    """The newest mail Lodestar sent, for a job, whose Message-ID is among a reply's In-Reply-To / References."""
    ids = ids[-50:]  # References lists the thread oldest first; a forged header with thousands of ids stays bounded
    if not ids:
        return None
    return con().execute(f"SELECT * FROM mail WHERE direction='out' AND job_id IS NOT NULL AND message_id IN "
                         f"({','.join('?' * len(ids))}) ORDER BY id DESC LIMIT 1", tuple(ids)).fetchone()


def mail_by_message_id(message_id: str):
    return con().execute("SELECT * FROM mail WHERE message_id=?", ((message_id or "").strip(),)).fetchone()


def link_mail(mid: int, job_id: int) -> None:
    """Your own link: files the mail under the job. It never sets the job's contact or makes the sender trusted.
    A pending 'track this company' proposal made from the same mail is closed: the mail has its job now."""
    m, _ = get_mail(mid), get_job(job_id)
    if m["direction"] != "in" or (m["job_id"] is not None and m["linked_by"] != "user"):  # relink + unlink would lose it
        raise SystemExit(f"mail #{mid} was filed automatically (or sent by you); only unmatched mail or your own links move")
    con().execute("UPDATE mail SET job_id=?, linked_by='user' WHERE id=?", (job_id, mid))
    con().execute("UPDATE pending SET status='rejected', result=?, decided_at=? WHERE kind='add_job' AND status='pending' "
                  "AND json_extract(payload, '$.message_id')=?", (f"mail filed under job #{job_id}", _now(), m["message_id"]))
    con().commit()


def unlink_mail(mid: int) -> None:
    if get_mail(mid)["linked_by"] != "user":
        raise SystemExit(f"mail #{mid} was not linked by you; only your own links can be undone")
    con().execute("UPDATE mail SET job_id=NULL, linked_by=NULL WHERE id=?", (mid,))
    con().commit()


def dismiss_mail(mid: int) -> None:
    if get_mail(mid)["job_id"] is not None:
        raise SystemExit(f"mail #{mid} belongs to a job; unlink it first")
    con().execute("DELETE FROM mail WHERE id=?", (mid,))  # the seen table keeps the scan from bringing it back
    con().commit()


# --- offers (structured terms; comp.total does the money) ----------------------
_OFFER_NUM = {"base": (0, 10_000_000), "sign_on": (0, 10_000_000), "equity_value_estimate": (0, 100_000_000),
              "vest_years": (1, 10), "cliff_months": (0, 60), "bonus_pct": (0, 200), "retirement_match_pct": (0, 100)}
_OFFER_PCT = ("bonus_pct", "retirement_match_pct")  # may have decimals; the rest are whole numbers
OFFER_FIELDS = (*_OFFER_NUM, "remote", "start_date", "deadline", "notes")


def _offer_val(k: str, v):
    if k not in OFFER_FIELDS:
        raise SystemExit(f"unknown offer field '{k}'. Fields: {', '.join(OFFER_FIELDS)}")
    s = "" if v is None else str(v).strip()
    if not s:
        return None
    if k in _OFFER_NUM:
        lo, hi = _OFFER_NUM[k]
        t = s.replace(",", "").rstrip("%")
        try:
            n = float(t[:-1]) * 1000 if t[-1:] in "kK" and k not in _OFFER_PCT else float(t)
        except ValueError:
            raise SystemExit(f"{k} must be a number: {s[:40]}") from None
        if not lo <= n <= hi:
            raise SystemExit(f"{k} must be between {lo} and {hi}")
        return round(n, 2) if k in _OFFER_PCT else int(round(n))
    if k == "remote":
        if s.lower() not in REMOTE:
            raise SystemExit(f"remote must be one of {', '.join(REMOTE)}")
        return s.lower()
    if k in ("start_date", "deadline"):
        return valid_date(k, s)
    if len(s) > 2000:
        raise SystemExit("notes is longer than 2000 characters")
    return s


def set_offer(job_id: int, **fields) -> dict:
    """Set whitelisted offer fields (OFFER_FIELDS); all validated first, so a bad value changes nothing. Empty clears.
    A job not yet at 'offer' moves there: recording an offer is your own action. All-empty records nothing (and an
    offer whose every field is cleared is removed; the job's status is yours to change)."""
    clean = {k: _offer_val(k, v) for k, v in fields.items()}
    job = get_job(job_id)
    real = any(v is not None for v in clean.values())
    if real:
        con().execute("INSERT INTO offers(job_id) VALUES(?) ON CONFLICT(job_id) DO NOTHING", (job_id,))
    if clean:
        con().execute(f"UPDATE offers SET {', '.join(k + '=?' for k in clean)}, updated_at=? WHERE job_id=?",
                      (*clean.values(), _now(), job_id))
        con().execute(f"DELETE FROM offers WHERE job_id=? AND {' AND '.join(k + ' IS NULL' for k in OFFER_FIELDS)}", (job_id,))
        con().commit()
    if real and STATUSES.index(job["status"]) < STATUSES.index("offer"):
        set_status(job_id, "offer", "(offer recorded)")
    return clean


def get_offer(job_id: int) -> dict | None:
    row = con().execute("SELECT * FROM offers WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


# --- funnel -------------------------------------------------------------------
STAGE_ORDER = ["applied", "screening", "interview", "offer", "accepted"]


def funnel() -> dict:
    """Stage conversion, median days to the next stage, where rejections happen, and outcomes by source."""
    first: dict[int, dict[str, str]] = {}
    for e in con().execute("SELECT job_id, ts, detail FROM events WHERE kind='status' AND job_id IN (SELECT id FROM jobs) "
                           "ORDER BY ts").fetchall():
        st = (e["detail"] or "").split(" ")[0]
        first.setdefault(e["job_id"], {}).setdefault(st, e["ts"])

    def days(a: str, b: str) -> float:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400

    stages = {}
    for i, st in enumerate(STAGE_ORDER):
        later = STAGE_ORDER[i + 1:]
        # a job at a later stage has passed this one, logged or not (applied -> interview skips screening)
        reached = [j for j in first.values() if any(s in j for s in STAGE_ORDER[i:])]
        advanced = [j for j in reached if any(s in j for s in later)]
        durs = sorted(days(j[st], min(j[s] for s in later if s in j)) for j in advanced if st in j)
        stages[st] = {"reached": len(reached), "advanced": len(advanced),
                      "conversion": round(len(advanced) / len(reached), 2) if reached and later else None,
                      "median_days_to_next": round(durs[len(durs) // 2], 1) if durs else None}
    rejected_from: dict[str, int] = {}
    for j in first.values():
        if "rejected" in j:
            before = [s for s in STAGE_ORDER if s in j and j[s] <= j["rejected"]]
            last = max(before, key=lambda s: j[s]) if before else "saved"
            rejected_from[last] = rejected_from.get(last, 0) + 1
    by_source: dict[str, dict] = {}
    for j in list_jobs():
        d = by_source.setdefault(j["source"] or source_of(j["notes"]), {"tracked": 0, "positive": 0})
        d["tracked"] += 1
        d["positive"] += j["status"] in POSITIVE
    return {"stages": stages, "rejected_from": rejected_from, "by_source": by_source}
