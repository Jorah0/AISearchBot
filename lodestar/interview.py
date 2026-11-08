"""Interviews: rounds per job (with the questions you were asked), your question bank, STAR stories, the prep pack, and
the mock interview with a per-answer score card. Everything here is read by the candidate only."""
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from . import ai, db
from .resume import app_dir, candidate_text, write_doc

SYSTEM = "You are a veteran hiring manager and interview coach. Be concrete, honest, and grounded in the candidate's real history."
KINDS = ("phone", "technical", "onsite", "panel", "final", "other")
OUTCOMES = ("pending", "passed", "rejected", "unknown")
COMPETENCIES = ("leadership", "conflict", "failure", "ambiguity", "influence", "ownership", "customer", "data-driven",
                "teamwork", "deadline")
QUESTIONS = Path(__file__).parent / "data" / "questions.json"  # beside the module, like ats.DATA
ICS_RE = re.compile(r"interview-(\d{8}-\d{4})[.]ics$")


def _resume(job, strict: bool = True) -> str:
    p = app_dir(job) / "resume.md"
    return p.read_text(encoding="utf-8") if p.is_file() else candidate_text(strict=strict)


def _notes(job) -> str:
    """Research pack and gap check from the job's folder, when they exist. Prep and mock are read by the candidate only."""
    d, out = app_dir(job), ""
    if (d / "research.md").is_file():
        out += "\n\nCOMPANY RESEARCH:\n" + (d / "research.md").read_text(encoding="utf-8")[:2500]
    if (d / "gap.json").is_file():
        g = json.loads((d / "gap.json").read_text(encoding="utf-8"))
        out += "\n\nGAP CHECK: " + json.dumps({k: g.get(k) for k in ("missing_keywords", "weak_areas")})
    return out


def _pay(job) -> str:
    """Real pay figures only: what the posting states, your recorded market range, your Preferences (private)."""
    from . import comp
    from .profile import preferences_text
    from .resume import salary_mentions

    jd = job["jd"] or ""
    m = comp.lookup(job["title"], jd)
    market = f"{m['low']}-{m['high']} ({m['city']})" if m else "none recorded"
    return (f"PAY FIGURES: stated in the posting: {', '.join(salary_mentions(jd)) or 'none stated'}; "
            f"recorded market range: {market}.\n"
            f"CANDIDATE PREFERENCES (private, includes the salary floor):\n{preferences_text() or '(none stated)'}")


# ----------------------------------------------------------------------------- rounds
_RTEXT = {"interviewers": 300, "notes": 5000, "questions_asked": 20000}
ROUND_FIELDS = ("round", "kind", "at", "interviewers", "notes", "questions_asked", "outcome")


def when_text(s: str) -> str:
    """'2026-11-12 14:00' / '2026-11-12T14:00' / '2026-11-12 2:00 PM' -> '2026-11-12 14:00'; a bare date stays a date."""
    from .extras import parse_when

    dt = parse_when(s)  # SystemExit with a clear message when it is not a date
    return f"{dt:%Y-%m-%d}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()) else f"{dt:%Y-%m-%d %H:%M}"


def _round_val(k: str, v):
    """One user-settable round field, validated. Empty clears (None); kind and outcome fall back to their defaults."""
    if k not in ROUND_FIELDS:
        raise SystemExit(f"unknown round field '{k}'. Fields: {', '.join(ROUND_FIELDS)}")
    s = "" if v is None else str(v).strip()
    if k == "round":
        if not s:
            return None
        if not s.isdigit() or not 1 <= int(s) <= 50:
            raise SystemExit("round must be a whole number from 1 to 50")
        return int(s)
    if k in ("kind", "outcome"):
        s, ok = (s.lower() or "other", KINDS) if k == "kind" else (s.lower() or "pending", OUTCOMES)
        if s not in ok:
            raise SystemExit(f"{k} must be one of {', '.join(ok)}")
        return s
    if not s:
        return None
    if k == "at":
        return when_text(s)
    if k == "questions_asked":  # one question per line
        lines = [" ".join(ln.split()) for ln in s.splitlines() if ln.strip()]
        if len(lines) > 200 or any(len(ln) > 500 for ln in lines):
            raise SystemExit("questions: at most 200 lines, each up to 500 characters")
        s = "\n".join(lines)
    if len(s) > _RTEXT[k]:
        raise SystemExit(f"{k} is longer than {_RTEXT[k]} characters")
    return s


def _round_taken(job_id: int, n, rid=None) -> None:
    if n and db.con().execute("SELECT 1 FROM interviews WHERE job_id=? AND round=? AND id IS NOT ?", (job_id, n, rid)).fetchone():
        raise SystemExit(f"job #{job_id} already has a round {n}")


def log_round(job_id: int, **fields) -> int:
    """Add a round to a job, or update round N when `round` names one it already has. Every value is validated first,
    so a bad one changes nothing. Returns the round's id."""
    clean = {k: _round_val(k, v) for k, v in fields.items()}
    db.get_job(job_id)
    n = clean.get("round")
    row = db.con().execute("SELECT id FROM interviews WHERE job_id=? AND round=?", (job_id, n)).fetchone() if n else None
    if row:
        edit_round(row["id"], **{k: v for k, v in fields.items() if k != "round"})
        return row["id"]
    clean["round"] = n or _next_round(job_id)
    rid = db.con().execute(f"INSERT INTO interviews(job_id, {', '.join(clean)}) VALUES(?, {', '.join('?' * len(clean))})",
                           (job_id, *clean.values())).lastrowid
    db.con().commit()
    db.add_event(job_id, "interview_round", f"round {clean['round']} {clean.get('kind') or 'other'} {clean.get('at') or ''}".strip())
    return rid


def _next_round(job_id: int) -> int:
    return (db.con().execute("SELECT MAX(round) n FROM interviews WHERE job_id=?", (job_id,)).fetchone()["n"] or 0) + 1


def get_round(rid: int) -> sqlite3.Row:
    row = db.con().execute("SELECT * FROM interviews WHERE id=?", (rid,)).fetchone()
    if not row:
        raise SystemExit(f"no interview round #{rid}")
    return row


def edit_round(rid: int, **fields) -> dict:
    clean = {k: _round_val(k, v) for k, v in fields.items()}
    r = get_round(rid)
    if "round" in clean:
        if not clean["round"]:
            raise SystemExit("a round needs a number")
        _round_taken(r["job_id"], clean["round"], rid)
    if clean:
        db.con().execute(f"UPDATE interviews SET {', '.join(k + '=?' for k in clean)} WHERE id=?", (*clean.values(), rid))
        db.con().commit()
    return clean


def delete_round(rid: int) -> None:
    get_round(rid)
    db.con().execute("DELETE FROM interviews WHERE id=?", (rid,))
    db.con().commit()


def rounds(job_id: int) -> list[dict]:
    sync_ics()
    return [dict(r) for r in db.con().execute("SELECT * FROM interviews WHERE job_id=? ORDER BY round, at", (job_id,))]


def booked(job_id: int, at: str, ics: str | None = None, note: str = "", once: bool = False) -> int | None:
    """A scheduled interview from the calendar paths (.ics written, interview email): the job's round at that time, else
    its date-only round of that day (which gains the time), else a new round. A re-scanned mail adds nothing.
    once: the .ics import (sync_ics): a calendar file another thread or process imported meanwhile is skipped (None)."""
    c = db.con()
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")  # check-then-insert as one step: the loop, a page poll and `run --once` race here
    try:
        rid = _booked(c, job_id, at, ics, note, once)
    except BaseException:
        c.rollback()
        raise
    c.commit()
    return rid


def _booked(c, job_id: int, at: str, ics: str | None, note: str, once: bool) -> int | None:
    if once and ics and c.execute("SELECT 1 FROM seen WHERE key=?", ("ics:" + ics,)).fetchone():
        return None
    if len(at) > 10:
        row = c.execute("SELECT id, at FROM interviews WHERE job_id=? AND at IN (?, ?) ORDER BY length(at) DESC",
                        (job_id, at, at[:10])).fetchone()
    else:
        row = c.execute("SELECT id, at FROM interviews WHERE job_id=? AND substr(at, 1, 10)=?", (job_id, at)).fetchone()
    if not row and len(at) > 10 and not once:
        # a new time while the job's only upcoming round is still pending is that round moved (a reschedule mail, or
        # accepting another of the offered slots), not a second round: move it, so old reminders/clashes go away.
        # ponytail: a round-2 invite that arrives before round 1 happens moves round 1 too; the note keeps the old time
        fut = c.execute("SELECT id, at, notes FROM interviews WHERE job_id=? AND length(at)=16 AND at >= ? "
                        "AND COALESCE(outcome, 'pending')='pending'", (job_id, f"{datetime.now():%Y-%m-%d %H:%M}")).fetchall()
        if len(fut) == 1:
            row = fut[0]
            moved = f"rescheduled from {row['at']}"
            c.execute("UPDATE interviews SET notes=? WHERE id=?", ("\n".join(x for x in (row["notes"], moved) if x)[:5000], row["id"]))
    if row:
        sets = {"at": at} if len(at) > 10 and row["at"] != at else {}
        if ics:
            sets["ics"] = ics
        if sets:
            c.execute(f"UPDATE interviews SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), row["id"]))
        rid = row["id"]
    else:
        rid = c.execute("INSERT INTO interviews(job_id, round, at, ics, notes) VALUES(?,?,?,?,?)",
                        (job_id, _next_round(job_id), at, ics, note[:500] or None)).lastrowid
    if ics:
        c.execute("INSERT OR IGNORE INTO seen(key) VALUES(?)", ("ics:" + ics,))
    return rid


def sync_ics() -> int:
    """Calendar events from before rounds existed (or written by hand) become rounds, each once (seen 'ics:<path>'),
    so their reminders keep working. A round you delete later stays deleted."""
    rows = db.con().execute("SELECT e.job_id, e.detail FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.kind='calendar' "
                            "AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.key='ics:' || e.detail)").fetchall()
    n = 0
    for e in rows:
        if m := ICS_RE.search(e["detail"] or ""):
            if booked(e["job_id"], f"{datetime.strptime(m.group(1), '%Y%m%d-%H%M'):%Y-%m-%d %H:%M}", e["detail"], once=True):
                n += 1
    return n


# ----------------------------------------------------------------------------- question bank
@lru_cache(maxsize=1)
def universal() -> list[dict]:
    """The small bundled behavioural set: [{q, competency}]."""
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def question_bank(job=None, with_universal: bool = True) -> list[dict]:
    """[{q, source, where}]: questions you logged for this company first, then for similar titles (every word of the
    shorter core title in the longer), then the bundled behavioural set. Without a job: every logged question, newest
    first. The same question (case and punctuation aside) is listed once."""
    from .ats import CONNECTORS, core_title
    from .web_monitor import norm_company

    def words(title):
        return set(core_title(title).split()) - CONNECTORS

    co, tw = (norm_company(job["company"]), words(job["title"])) if job else (None, set())
    tiers: dict[str, list] = {"company": [], "similar title": [], "logged": []}
    for r in db.con().execute("SELECT i.questions_asked, i.round, i.job_id, j.company, j.title FROM interviews i "
                              "JOIN jobs j ON j.id=i.job_id WHERE COALESCE(i.questions_asked, '') != '' ORDER BY i.id DESC"):
        ow = words(r["title"])
        short, long_ = (tw, ow) if len(tw) <= len(ow) else (ow, tw)
        tier = ("logged" if not job else "company" if norm_company(r["company"]) == co
                else "similar title" if short and short <= long_ else None)
        if tier:
            where = f"#{r['job_id']} {r['company']} - {r['title']}, round {r['round']}"
            tiers[tier] += [{"q": q, "source": tier, "where": where} for q in r["questions_asked"].splitlines() if q.strip()]
    pool = tiers["company"] + tiers["similar title"] + tiers["logged"]
    if with_universal:
        pool += [{"q": u["q"], "source": "universal", "where": u.get("competency") or ""} for u in universal()]
    seen, out = set(), []
    for x in pool:
        k = re.sub(r"[^a-z0-9 ]", "", x["q"].lower()).strip()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _asked(job) -> str:
    qs = question_bank(job, with_universal=False)[:25]
    return ("\n\nQUESTIONS ACTUALLY ASKED (the candidate logged these from real interviews at this company or for "
            "similar roles; use them first, adapted, before inventing new ones):\n"
            + "\n".join(f"- {x['q']} ({x['source']})" for x in qs)) if qs else ""


# ----------------------------------------------------------------------------- STAR stories (rows of the answers table)
STAR = ("situation", "task", "action", "result")
STORY_PREFIX = "Story: "
# ponytail: a small keyword table, a prompt for the user rather than a classifier; grow the lists when they miss
COMPETENCY_WORDS = {
    "leadership": r"lead(?:s|ing|er|ership)?\b|mentor|coach|manag(?:e|ing) (?:a )?team|people manag",
    "conflict": r"conflict|disagree|difficult conversation|push(?:ed)? back|negotiat",
    "failure": r"fail|mistake|setback|post-?mortem|resilien|learn(?:ed|ing)? from",
    "ambiguity": r"ambigu|uncertain|fast[- ]paced|startup|self[- ]starter|changing priorities|evolving",
    "influence": r"influenc|persua|stakeholder|cross[- ]functional|buy-?in|align",
    "ownership": r"ownership|owner\b|end[- ]to[- ]end|accountab|autonom|initiative|proactive",
    "customer": r"customer|client|user[- ](?:focus|centric|experience|needs)|empath",
    "data-driven": r"data[- ]driven|metrics?\b|analytics|a/b test|kpis?\b|insights?\b|measur",
    "teamwork": r"collaborat|team ?player|teamwork|partner(?:ing)? with|work(?:ing)? closely",
    "deadline": r"deadline|prioriti[sz]|time management|under pressure|multi-?task|tight timeline|multiple projects",
}
_CRX = {k: re.compile(r"\b(?:" + v + ")", re.I) for k, v in COMPETENCY_WORDS.items()}


def competencies_in(text) -> list[str]:
    """The competencies a text keeps coming back to, most mentioned first (keyword table above)."""
    hits = {k: len(rx.findall(text or "")) for k, rx in _CRX.items()}
    return [k for k, n in sorted(hits.items(), key=lambda x: -x[1]) if n]


def _comps(v) -> list[str]:
    tags = [t.strip().lower() for t in (v.split(",") if isinstance(v, str) else (v or [])) if str(t).strip()]
    bad = [t for t in tags if t not in COMPETENCIES]
    if bad:
        raise SystemExit(f"unknown competency {bad[0][:40]!r}: use {', '.join(COMPETENCIES)}")
    return list(dict.fromkeys(tags))


def render_story(s: dict) -> str:
    return "\n".join(f"{k.capitalize()}: {s[k]}" for k in (*STAR, "metrics") if s.get(k))


def save_story(title, situation="", task="", action="", result="", metrics="", competencies=(), sid=None) -> int:
    """A STAR story in the answers table: question 'Story: <title>', answer the readable text (so form answers can reuse
    it), tags 'story,<competencies>', star the fields as JSON. sid: update that story."""
    t = " ".join(str(title or "").split())
    if not 0 < len(t) <= 120:
        raise SystemExit("a story needs a title of 1-120 characters")
    star = {k: str(v or "").strip() for k, v in zip((*STAR, "metrics"), (situation, task, action, result, metrics))}
    for k, v in star.items():
        if len(v) > (500 if k == "metrics" else 4000):
            raise SystemExit(f"{k} is too long")
    if not any(star[k] for k in STAR):
        raise SystemExit("write at least one of situation, task, action, result")
    star["competencies"] = _comps(competencies)
    args = (STORY_PREFIX + t, render_story(star), ",".join(["story", *star["competencies"]]), json.dumps(star))
    try:
        if sid:
            if not db.con().execute("SELECT 1 FROM answers WHERE id=? AND star IS NOT NULL", (sid,)).fetchone():
                raise SystemExit(f"no story #{sid}")
            db.con().execute("UPDATE answers SET question=?, answer=?, tags=?, star=?, updated_at=datetime('now') WHERE id=?",
                             (*args, sid))
        else:
            sid = db.con().execute("INSERT INTO answers(question, answer, tags, star) VALUES(?,?,?,?)", args).lastrowid
    except sqlite3.IntegrityError:
        db.con().rollback()  # or the failed write's transaction keeps the database write-locked
        raise SystemExit(f"another story or saved answer is already called {args[0]!r}") from None
    db.con().commit()
    return sid


def stories() -> list[dict]:
    out = []
    for r in db.con().execute("SELECT id, question, star, updated_at FROM answers WHERE star IS NOT NULL ORDER BY updated_at DESC"):
        try:
            s = json.loads(r["star"])
        except ValueError:
            continue
        out.append({"id": r["id"], "title": r["question"].removeprefix(STORY_PREFIX), "updated_at": r["updated_at"],
                    **{k: s.get(k, "") for k in (*STAR, "metrics")}, "competencies": s.get("competencies", []),
                    "missing": [k for k in STAR if not s.get(k)]})
    return out


def story_from_idea(idea_id: int) -> int:
    """'Save as story' for an idea of the ideas 'stories' topic: its title and sketch become an (incomplete) story with
    the competencies its text names; you fill in the rest. No second AI drafter."""
    row = db.get_idea(idea_id)
    if row["topic"] != "stories":
        raise SystemExit(f"idea #{idea_id} is a '{row['topic']}' idea; only ideas of the 'stories' topic become stories")
    b = json.loads(row["body"])
    text = " ".join(str(b.get(k) or "") for k in ("idea", "why_it_works"))
    return save_story(row["title"][:120], situation=str(b.get("idea") or row["title"])[:4000], competencies=competencies_in(text))


def story_prompt(job) -> dict:
    """What the posting stresses (up to 4 competencies) and which of those no story is tagged with yet."""
    stressed = competencies_in(job["jd"])[:4]
    have = {c for s in stories() for c in s["competencies"]}
    return {"stressed": stressed, "missing": [c for c in stressed if c not in have]}


def _stories_text(job, limit: int = 3500) -> str:
    """The candidate's own stories, those tagged with what the posting stresses first."""
    stressed = set(competencies_in(job["jd"]))
    ss = sorted(stories(), key=lambda s: -len(stressed & set(s["competencies"])))
    text = "\n\n".join(f"[{s['title']}] ({', '.join(s['competencies']) or 'untagged'})\n{render_story(s)}" for s in ss)
    return ("\n\nCANDIDATE'S OWN STAR STORIES (real material: build behavioural answers from these; never invent "
            "others):\n" + text[:limit]) if text else ""


# ----------------------------------------------------------------------------- prep pack
def prep(job, use_council: bool = False, provider: str | None = None) -> Path:
    prompt = f"""Prepare the candidate for an interview: {job['title']} at {job['company']}.
Produce Markdown with these sections:
1. 10 likely role-specific technical/skill questions, each with a strong model answer built from the candidate's real experience. Start from the questions actually asked, when given.
2. 6 behavioral questions with STAR answers drawn from the candidate's actual history (use their own STAR stories when given).
3. The 3 toughest questions given gaps between the resume and the job description (use the gap check if given), with honest strategies.
4. 5 sharp questions to ask the interviewer that signal seniority, grounded in the company research when given.
5. A 60-second "tell me about yourself" pitch.
6. Salary negotiation notes: quote the PAY FIGURES and the salary floor below. Never invent market data; if a number is unknown, say what to look up.

JOB DESCRIPTION:
{job['jd'] or '(none on file - infer from title)'}

CANDIDATE:
{_resume(job)}

{_pay(job)}{_notes(job)}{_asked(job)}{_stories_text(job)}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider, max_tokens=8000)
    out = write_doc(app_dir(job) / "interview_prep.md", text)
    db.add_event(job["id"], "interview_prep", str(out))
    return out


# ----------------------------------------------------------------------------- mock interview + score card
WPM, TARGET = 140, (60, 120)  # speaking pace for the time estimate; a behavioural answer of 1-2 minutes
RUBRIC = ('{"situation": 0-2, "task": 0-2, "action": 0-2, "result": 0-2, "relevance": 0-2, "specificity": 0-2, '
          '"metrics_used": true or false, "one_fix": "the single most useful change, one sentence", '
          '"suggested_rewrite": "the answer rewritten, under 150 words"}')


def mock_system(job) -> str:
    return (
        SYSTEM + f" Conduct a realistic mock interview for {job['title']} at {job['company']}. Ask ONE question at a time, "
        "wait for the answer, give two lines of feedback, then ask the next. Mix technical and behavioral; ask the "
        "questions actually asked (below) first, before inventing new ones. When the candidate says 'done', give a "
        "scored (1-10) debrief with specific improvements.\n\n"
        f"JOB DESCRIPTION:\n{job['jd'] or '(infer from title)'}\n\nCANDIDATE:\n{_resume(job, strict=False)}"
        f"{_notes(job)}{_asked(job)}{_stories_text(job, 2500)}"
    )


def answer_metrics(answer: str, job=None, seconds=None) -> dict:
    """Offline numbers for one answer: words, estimated speaking time (~140 wpm) against the 60-120 s target, the most
    repeated words, the posting's keywords it names, and words per minute when a dictation duration is known."""
    from .ats import STOP, match

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'+#-]*", answer)
    est = round(len(words) / WPM * 60)
    took = seconds or est
    counts = Counter(w.lower() for w in words if len(w) >= 4 and w.lower() not in STOP)
    return {"words": len(words), "est_seconds": est, "seconds": round(seconds) if seconds else None,
            "pace": "short" if took < TARGET[0] else "long" if took > TARGET[1] else "ok",
            "repeated": [w for w, n in counts.most_common(3) if n >= 3],
            "jd_keywords": [k["term"] for k in match(answer, job["jd"], job["title"], company=job["company"])["keywords"]
                            if k["matched"]][:10] if job and job["jd"] else [],
            "wpm": round(len(words) / (seconds / 60)) if seconds else None}


def _rubric(r) -> dict:
    """The AI's rubric, clamped: 0-2 integers, a boolean, bounded strings. Anything malformed scores 0."""
    if isinstance(r, list):
        r = r[0] if r else {}
    r = r if isinstance(r, dict) else {}

    def n(k):
        try:
            return max(0, min(2, int(r.get(k))))
        except (TypeError, ValueError):
            return 0
    out = {k: n(k) for k in (*STAR, "relevance", "specificity")}
    out |= {"star": round(sum(out[k] for k in STAR) / 4, 2), "metrics_used": r.get("metrics_used") in (True, "true", "yes", 1),
            "one_fix": str(r.get("one_fix") or "")[:400], "suggested_rewrite": str(r.get("suggested_rewrite") or "")[:2000]}
    return out


def averages(cards: list[dict]) -> dict:
    scored = [c["rubric"] for c in cards if c.get("rubric")]

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None
    return {"answers": len(cards), "scored": len(scored), "star": mean([r["star"] for r in scored]),
            "relevance": mean([r["relevance"] for r in scored]), "specificity": mean([r["specificity"] for r in scored]),
            "metrics_used": mean([1 if r["metrics_used"] else 0 for r in scored]),
            "words": mean([c["words"] for c in cards]), "est_seconds": mean([c["est_seconds"] for c in cards])}


def score_answer(job, question, answer, seconds=None, session=None, provider: str | None = None) -> dict:
    """Score one mock answer: offline metrics always, the rubric when an AI provider answers (one ask_json). The card is
    appended to the mock session (a new one when session is None) and returned with the session id and averages."""
    q, a = str(question or "").strip()[:2000], str(answer or "").strip()[:8000]
    if not a:
        raise SystemExit("nothing to score: the answer is empty")
    try:
        seconds = float(seconds) if seconds not in (None, "") else None
    except (TypeError, ValueError):
        raise SystemExit("seconds must be a number") from None
    if seconds is not None and not 0 < seconds <= 3600:
        raise SystemExit("seconds must be between 0 and 3600")
    c = db.con()
    row = None
    if session:
        row = c.execute("SELECT answers FROM mock_sessions WHERE id=? AND job_id=?", (int(session), job["id"])).fetchone()
        if not row:
            raise SystemExit(f"no mock session #{session} for job #{job['id']}")
    card = {"question": q, "answer": a, **answer_metrics(a, job, seconds), "rubric": None}
    try:
        card["rubric"] = _rubric(ai.ask_json(
            f"""Score this mock-interview answer for {job['title']} at {job['company']}. Score only what the answer says.
STAR parts 0-2 each (0 missing, 1 vague, 2 clear), relevance to the question 0-2, specificity 0-2, metrics_used if it
gives a number for the outcome. The rewrite may only reorder and tighten the candidate's own facts; never add a fact or
a number (write [number] where one is missing). Return JSON only: {RUBRIC}

QUESTION: {q or '(not given)'}
ANSWER: {a}

JOB DESCRIPTION (excerpt):
{(job['jd'] or '')[:1500]}""", SYSTEM, provider))
    except (Exception, SystemExit) as e:  # no key, model rejected, bad JSON: the offline half of the card still stands
        card["rubric_error"] = str(e)[:200]
    cards = (json.loads(row["answers"]) if row else []) + [card]
    avg = averages(cards)
    if row:
        c.execute("UPDATE mock_sessions SET answers=?, averages=? WHERE id=?", (json.dumps(cards), json.dumps(avg), int(session)))
        sid = int(session)
    else:
        sid = c.execute("INSERT INTO mock_sessions(job_id, answers, averages) VALUES(?,?,?)",
                        (job["id"], json.dumps(cards), json.dumps(avg))).lastrowid
    c.commit()
    return card | {"session": sid, "averages": avg}


def sessions(limit: int = 30) -> list[dict]:
    """Mock sessions, oldest first (the Coach tab's trend): id, job, time, averages."""
    rows = db.con().execute("SELECT m.id, m.job_id, m.ts, m.averages, j.company, j.title FROM mock_sessions m "
                            "LEFT JOIN jobs j ON j.id=m.job_id ORDER BY m.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) | {"averages": json.loads(r["averages"] or "{}")} for r in reversed(rows)]


def render_card(card: dict) -> str:
    took = f"{card['seconds']} s spoken" if card.get("seconds") else f"~{card['est_seconds']} s"
    lines = [f"  {card['words']} words, {took} (target {TARGET[0]}-{TARGET[1]} s: {card['pace']})"
             + (f", {card['wpm']} wpm" if card.get("wpm") else "")]
    r = card.get("rubric")
    if r:
        lines += [f"  STAR S{r['situation']} T{r['task']} A{r['action']} R{r['result']} (avg {r['star']}/2) · relevance "
                  f"{r['relevance']}/2 · specificity {r['specificity']}/2 · metrics {'yes' if r['metrics_used'] else 'no'}",
                  f"  one fix: {r['one_fix']}", f"  rewrite: {r['suggested_rewrite']}"]
    else:
        lines.append(f"  (no rubric: {card.get('rubric_error') or 'no AI provider'})")
    if card.get("repeated"):
        lines.append(f"  repeated: {', '.join(card['repeated'])}")
    if card.get("jd_keywords"):
        lines.append(f"  posting keywords used: {', '.join(card['jd_keywords'])}")
    return "\n".join(lines)


def save_mock(job, history: list[dict]) -> Path:
    """Transcript plus the scored debrief -> mock_interview.md (the previous one moves to history/), and a timeline event."""
    who = {"assistant": "Interviewer", "user": "You"}
    lines = [f"# Mock interview: {job['title']} at {job['company']}", f"_{datetime.now():%Y-%m-%d %H:%M}_", ""]
    lines += [f"**{who.get(m['role'], m['role'])}:** {m['content']}\n" for m in history]
    out = write_doc(app_dir(job) / "mock_interview.md", "\n".join(lines))
    db.add_event(job["id"], "mock_interview", f"{len(history) // 2} turns, saved {out.name}")
    return out


def mock_turn(job, msgs: list[dict], provider: str | None = None) -> str:
    """The interviewer's next line. Without any AI provider the questions come from question_bank (this company's
    logged questions first, then the bundled set) in order, so practice and the offline score card still work."""
    try:
        return ai.chat(msgs, mock_system(job), provider)
    except SystemExit:
        if provider or ai.available():  # a provider is set up but refused: say so, don't pretend to be offline
            raise
    if msgs and str(msgs[-1].get("content", "")).strip().lower() == "done":
        return "Offline mock finished (no AI provider, so no debrief). Each answer's card is saved in this session."
    n = sum(m.get("role") == "assistant" for m in msgs)
    bank = question_bank(job)
    q = bank[n % len(bank)]["q"]
    return q if n else f"(No AI provider: questions come from your question bank; each answer gets the offline card.) {q}"


def mock(job, provider: str | None = None) -> None:
    history = [{"role": "user", "content": "Please start the interview."}]
    session, avg = None, {}
    print("(type 'done' to finish)\n")
    while True:
        reply = mock_turn(job, history, provider)
        history.append({"role": "assistant", "content": reply})
        print(f"\nINTERVIEWER: {reply}\n")
        if history[-2]["content"].strip().lower() == "done":
            break
        try:
            answer = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        history.append({"role": "user", "content": answer or "(no answer)"})
        if answer and answer.lower() != "done":
            card = score_answer(job, reply, answer, session=session, provider=provider)
            session, avg = card["session"], card["averages"]
            print(render_card(card))
    save_mock(job, history)
    if session:
        print(f"\nsession #{session}: {avg['answers']} answer(s), STAR average "
              f"{avg['star'] if avg['star'] is not None else '-'}/2")
