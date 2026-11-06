"""SQLite application tracker: jobs, events, url watches, dedupe table."""
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
"""
MIGRATIONS = {"resume_hash": "TEXT", "contact_email": "TEXT", "contact_name": "TEXT"}  # ponytail: additive only


def connect(path=None) -> sqlite3.Connection:
    c = sqlite3.connect(path or DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    have = {r["name"] for r in c.execute("PRAGMA table_info(jobs)")}
    for col, typ in MIGRATIONS.items():
        if col not in have:
            try:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError as e:  # another thread/process added it between our check and ALTER
                if "duplicate column" not in str(e).lower():
                    raise
    return c


_local = threading.local()  # one connection per thread: the web UI serves requests from a thread pool


def con() -> sqlite3.Connection:
    c = getattr(_local, "con", None)
    if c is None:
        c = _local.con = connect()
    return c


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add_job(company, title, url=None, jd=None, notes=None) -> int:
    if url:  # the same posting captured or searched twice is one card, not two
        dup = con().execute("SELECT id FROM jobs WHERE url=? AND status NOT IN ('rejected','withdrawn')", (url,)).fetchone()
        if dup:
            add_event(dup["id"], "duplicate", f"add ignored: {company} - {title}")
            return dup["id"]
    cur = con().execute("INSERT INTO jobs(company,title,url,jd,notes) VALUES(?,?,?,?,?)", (company, title, url, jd, notes))
    con().commit()
    add_event(cur.lastrowid, "created", f"{company} - {title}")
    return cur.lastrowid


def get_job(job_id: int) -> sqlite3.Row:
    row = con().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"no job #{job_id}")
    return row


def list_jobs(status=None):
    q, args = "SELECT * FROM jobs", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return con().execute(q + " ORDER BY updated_at DESC", args).fetchall()


def update_job(job_id: int, **fields) -> None:
    fields["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in fields)
    con().execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
    con().commit()


def set_status(job_id: int, status: str, detail: str = "") -> None:
    if status not in STATUSES:
        raise SystemExit(f"status must be one of {STATUSES}")
    extra = {"applied_at": _now()[:10]} if status == "applied" else {}
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
    con().execute("DELETE FROM pending WHERE job_id=? AND status='pending'", (job_id,))  # nothing may act for a gone job
    con().execute("DELETE FROM events WHERE job_id=?", (job_id,))
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


def stats() -> dict:
    rows = con().execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    counts = {s: 0 for s in STATUSES} | {r["status"]: r["n"] for r in rows}
    applied = sum(counts[s] for s in STATUSES if s != "saved")
    positive = sum(counts[s] for s in POSITIVE)
    responded = positive + counts["rejected"]
    return {
        "counts": counts,
        "applied_total": applied,
        "response_rate": round(responded / applied, 2) if applied else 0.0,
        "interview_rate": round(positive / applied, 2) if applied else 0.0,
    }


def variant_stats() -> list[dict]:
    """Outcomes per resume variant (hash of the tailored resume), best interview rate first."""
    rows = con().execute(
        "SELECT resume_hash h, COUNT(*) n, SUM(status IN ('screening','interview','offer','accepted')) pos, "
        "SUM(status='rejected') neg FROM jobs WHERE resume_hash IS NOT NULL AND status != 'saved' GROUP BY resume_hash"
    ).fetchall()
    out = [{"variant": r["h"], "applied": r["n"], "positive": r["pos"], "rejected": r["neg"],
            "response_rate": round((r["pos"] + r["neg"]) / r["n"], 2), "interview_rate": round(r["pos"] / r["n"], 2)}
           for r in rows]
    return sorted(out, key=lambda v: -v["interview_rate"])


def needs_followup(days: int | None = None):
    if not days:  # the board, digest and loop all follow the followup_days preference unless told otherwise
        from . import settings

        days = int(settings.pref("followup_days") or 7)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return con().execute(
        "SELECT j.* FROM jobs j WHERE j.status IN ('applied','screening','interview') "
        "AND (SELECT MAX(ts) FROM events e WHERE e.job_id=j.id) < ? ORDER BY updated_at",
        (cutoff,),
    ).fetchall()


# --- watches & dedupe -------------------------------------------------------
def add_watch(url: str, keywords: str = "") -> None:
    con().execute("INSERT OR REPLACE INTO watches(url,keywords) VALUES(?,?)", (url, keywords))
    con().commit()


def watches():
    return con().execute("SELECT * FROM watches ORDER BY id").fetchall()


def remove_watch(wid: int) -> None:
    con().execute("DELETE FROM watches WHERE id=?", (wid,))
    con().commit()


def update_watch(wid: int, last_hash: str) -> None:
    con().execute("UPDATE watches SET last_hash=?, last_seen=datetime('now') WHERE id=?", (last_hash, wid))
    con().commit()


def seen(key: str) -> bool:
    return con().execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone() is not None


def mark_seen(key: str) -> None:
    con().execute("INSERT OR IGNORE INTO seen(key) VALUES(?)", (key,))
    con().commit()


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


def decide_pending(pid: int, status: str, result: str = "") -> None:
    con().execute("UPDATE pending SET status=?, result=?, decided_at=? WHERE id=?", (status, result, _now(), pid))
    con().commit()


# --- answer bank ------------------------------------------------------------
def save_answer(question: str, answer: str, tags: str = "") -> None:
    con().execute("INSERT INTO answers(question,answer,tags,updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(question) DO UPDATE SET answer=excluded.answer, tags=excluded.tags, updated_at=excluded.updated_at",
                  (question.strip(), answer, tags, _now()))
    con().commit()


def list_answers():
    return con().execute("SELECT * FROM answers ORDER BY updated_at DESC").fetchall()


def delete_answer(aid: int) -> None:
    con().execute("DELETE FROM answers WHERE id=?", (aid,))
    con().commit()


def find_answers(question: str, limit: int = 4):
    """Prior answers whose question shares distinctive words with this one (cheap, no embeddings)."""
    toks = _tokens(question)
    scored = [(len(toks & _tokens(a["question"])), a) for a in list_answers()]
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


# --- funnel -------------------------------------------------------------------
STAGE_ORDER = ["applied", "screening", "interview", "offer", "accepted"]


def funnel() -> dict:
    """Stage conversion, median days to the next stage, where rejections happen, and outcomes by source."""
    first: dict[int, dict[str, str]] = {}
    for e in con().execute("SELECT job_id, ts, detail FROM events WHERE kind='status' ORDER BY ts").fetchall():
        st = (e["detail"] or "").split(" ")[0]
        first.setdefault(e["job_id"], {}).setdefault(st, e["ts"])

    def days(a: str, b: str) -> float:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400

    stages = {}
    for i, st in enumerate(STAGE_ORDER):
        nxt = STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None
        reached = [j for j in first.values() if st in j]
        advanced = [j for j in reached if nxt and nxt in j]
        durs = sorted(days(j[st], j[nxt]) for j in advanced)
        stages[st] = {"reached": len(reached), "advanced": len(advanced),
                      "conversion": round(len(advanced) / len(reached), 2) if reached and nxt else None,
                      "median_days_to_next": round(durs[len(durs) // 2], 1) if durs else None}
    rejected_from: dict[str, int] = {}
    for j in first.values():
        if "rejected" in j:
            before = [s for s in STAGE_ORDER if s in j and j[s] <= j["rejected"]]
            last = max(before, key=lambda s: j[s]) if before else "saved"
            rejected_from[last] = rejected_from.get(last, 0) + 1
    by_source: dict[str, dict] = {}
    for j in list_jobs():
        n = j["notes"] or ""
        src = ("captured" if "captured from" in n else "search:" + n.split("via ")[-1].split()[0].strip("()") if "via " in n
               else "email" if "from email" in n else "manual")
        d = by_source.setdefault(src, {"tracked": 0, "positive": 0})
        d["tracked"] += 1
        d["positive"] += j["status"] in POSITIVE
    return {"stages": stages, "rejected_from": rejected_from, "by_source": by_source}
