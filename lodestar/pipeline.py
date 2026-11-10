"""The pipeline: every step of an application as a named stage, run one click (or one Autopilot cycle) at a time.

A stage wraps a function that already exists (resume.gap, extras.research, resume.tailor_bullets, resume.cover_letter,
apply.answer, interview.prep, apply.thanks, apply.offer) or only observes work done elsewhere (mark applied, the
confirmation mail, follow-ups, rounds, closing). Per job, one row per stage records its output, what it was built from
(the fingerprints of what it reads) and its own fingerprint, so a later stage reads earlier results (ctx.out / ctx.file)
and turns stale, never silently redone, when an earlier result changes. A stage that lacks a fact asks once through
the questions queue (ctx.ask); the answer is saved for reuse and the waiting stage resumes.

Rules (later passes too): stage functions never send, submit, add a job or change a status (approvals.propose does);
employer text comes from candidate_text(private=False) / the tailored resume and db.employer_answers(); eligibility and
EEO answers are never AI-drafted; pipeline bookkeeping never goes to `events` (the follow-up clock reads it).
"""
import hashlib
import json
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import ai, db, log, settings

AUTO = False  # True: kicks run in a daemon thread. Set by the cli ui / app / desktop commands only (never start_server)
STUCK_MINUTES = 30  # a 'running' row this old: Lodestar closed while it ran (reads as error, can be claimed again)
CLICK_BUDGET = 8  # AI calls one clicked run may spend (the answers stage drafts at most this many labels)
CLOSED = ("accepted", "rejected", "withdrawn")
LIVE = ("saved", "applied", "screening", "interview", "offer")
ROOTS = ("jd", "profile", "stories")  # fingerprints that are not stages
# the two intake steps before a job exists: global loop steps, documented here and not registered per job
GLOBAL = {"discover": "saved searches, page watches and company boards (loop step 'watches', Search tab)",
          "shortlist": "auto_track proposes strong fits for the Board (Inbox add_job), or you track a listing"}
NONE_FP = "none"  # the fingerprint of an answers step with no form questions: done, and never stale
NEVER_AI_MSG = "Lodestar never drafts eligibility or EEO answers: write your own under Answers"


class _Skip:
    def __repr__(self):
        return "SKIP"


SKIP = _Skip()  # ctx.ask: you chose "I'll fill it in myself"


class Skipped(Exception):
    """Raised by a stage function: the step does not apply now (state 'skipped', the message says why)."""


@dataclass(frozen=True)
class Stage:
    name: str
    label: str
    statuses: tuple  # job statuses in which the stage is relevant
    needs: tuple = ()  # stages that must be done (stale or skipped counts) before it can run
    reads: tuple = ()  # stages and ROOTS whose fingerprints it records: a change makes it stale
    tool: str | None = None  # settings tool for unattended runs; None = runs only on a click
    ai: int = 0  # estimated AI calls per run (budget pre-check, proposal summaries); the log records the real count
    run: Callable | None = None  # (job, ctx) -> output dict; None = yours or another loop step's (never run here)
    observe: Callable | None = None  # (job, ctx) -> output with 'fp' when done, read from files / mail / rounds / status
    blocked: Callable | None = None  # (job, ctx) -> reason | None
    wait: Callable | None = None  # (job, ctx) -> (on: 'you' | 'employer', why) | None
    na: Callable | None = None  # (job, ctx) -> ('later' | 'skipped', why) | None: not due now (thank-you before a round)


REGISTRY: dict[str, Stage] = {}  # insertion order = pipeline order


def register(st: Stage) -> None:
    """Add a stage, or replace one by name (later passes swap run / observe). needs and reads name earlier stages or
    ROOTS."""
    names = list(REGISTRY)
    earlier = names[:names.index(st.name)] if st.name in REGISTRY else names
    for r in (*st.needs, *st.reads):
        if r not in earlier and r not in ROOTS:
            raise ValueError(f"stage {st.name}: {r!r} is neither an earlier stage nor a root ({', '.join(ROOTS)})")
    REGISTRY[st.name] = st


# ----------------------------------------------------------------------------- small helpers
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")  # sub-second: the claim compares it


def _h(text) -> str:
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:12]


def _dir(job):
    """The job's folder (resume.app_dir) without creating it: status() reads every job each cycle."""
    from . import resume
    from .util import slug

    return resume.APPS_DIR / f"{job['id']}-{slug(job['company'])}-{slug(job['title'])}"


def _file_fp(job, name: str) -> str | None:
    p = _dir(job) / name
    return _h(p.read_text(encoding="utf-8")) if p.is_file() else None


def _doc(name: str, **extra) -> Callable:
    """observe for a document stage: done when the file exists; fp hashes the file, so an edit is a new version."""
    def observe(job, ctx):
        fp = _file_fp(job, name)
        return {"file": name, "fp": fp, **extra} if fp else None
    return observe


def _ai_ok(ctx) -> bool:
    if ctx.ai_ok is None:
        ctx.ai_ok = bool(ctx.provider or ai.available())
    return ctx.ai_ok


def _need_ai(job, ctx):
    return None if _ai_ok(ctx) else "needs an AI provider: Setup > Link an AI key"


def _shared_roots() -> dict:
    """The profile and stories fingerprints, read once per status() / advance(). '?' never makes anything stale."""
    from . import profile

    try:
        m = profile.master_text()
        prof = "?" if profile.is_template(m) else _h(profile.drop_preferences(m) + json.dumps(profile.load(), sort_keys=True, default=str))
    except (Exception, SystemExit):
        prof = "?"
    rows = db.con().execute("SELECT id, updated_at FROM answers WHERE star IS NOT NULL ORDER BY id").fetchall()
    return {"profile": prof, "stories": _h(json.dumps([[r["id"], r["updated_at"]] for r in rows]))}


def _load(v, default):
    try:
        return json.loads(v) if v else default
    except ValueError:
        return default


def _rows(job_id: int) -> dict:
    out = {}
    for r in db.con().execute("SELECT * FROM pipeline WHERE job_id=?", (job_id,)).fetchall():
        d = dict(r)
        d["output"], d["inputs"] = _load(d["output"], {}), _load(d["inputs"], {})
        out[d["stage"]] = d
    return out


def _begin():
    c = db.con()
    if c.in_transaction:
        c.commit()
    c.execute("BEGIN IMMEDIATE")
    return c


# ----------------------------------------------------------------------------- questions: classify, normalise, match
ELIGIBILITY = re.compile(r"authori[sz]ed to work|work authori[sz]ation|right to work|sponsor|\bvisa\b|citizen|green card|"
                         r"work permit|criminal|convicted|conviction|felony|background check|drug (?:test|screen)|"
                         r"over 18|at least 18|date of birth|\bage\b|security clearance|export control|\bitar\b", re.I)
EEO = re.compile(r"gender|\bsex\b|\brace\b|ethnic|hispanic|latin[oax]\b|veteran|disabilit|pronoun|sexual orientation|"
                 r"transgender", re.I)
PRIVATE = re.compile(r"health|medical|pregnan|religio|marital|minimum salary|salary floor", re.I)
SALARY = re.compile(r"salary|compensation|\bpay\b|\bwages?\b", re.I)
NUMBER = re.compile(r"how many|number of|years of|how much|\bgpa\b", re.I)
DATE = re.compile(r"\bdate\b|when can you start|available to start", re.I)
CLOSED_KINDS = ("eligibility", "eeo", "salary", "private", "number", "date", "choice")
_W = r"[a-z]+(?: (?!without|and|or|if|who|with|for|on|now)[a-z]+){0,2}"  # a country: up to three words
# ponytail: regex canon covers the common screening questions; add rows (or an AI match on click) when the run log
# shows the same question asked twice
CANON = [
    (re.compile(r"\bhispanic\b|\blatin[oax]\b"), "EEO: hispanic or latino"),
    (re.compile(r"\bgender\b"), "EEO: gender"),
    (re.compile(r"\bsex\b"), "EEO: sex"),  # 'sex assigned at birth' is a different question from 'gender identity'
    (re.compile(r"\brace\b|\bethnicity\b"), "EEO: race"),
    (re.compile(r"\bveteran"), "EEO: veteran status"),
    (re.compile(r"\bdisabilit"), "EEO: disability status"),
    (re.compile(r"^(?=.*\bsponsor)(?=.*\b(?:visa|work|employment|immigration|h ?1 ?b)\b)"), "Visa sponsorship required"),
    (re.compile(rf"\b(?:authori[sz]ed|eligible|permitted|legally able) to work (?:in|for) (?:the )?({_W})$"), "Work authorization: {}"),
    (re.compile(rf"\bwork authori[sz]ation (?:in|for) (?:the )?({_W})$"), "Work authorization: {}"),
    (re.compile(rf"\bright to work in (?:the )?({_W})$"), "Work authorization: {}"),
    (re.compile(r"^work authorization (?!status$)([a-z]+(?: [a-z]+){0,2})$"), "Work authorization: {}"),  # the key itself
    (re.compile(r"\b(?:authori[sz]ed|eligible|permitted|legally able) to work\b|\bwork authori[sz]ation\b|\bright to work\b"),
     "Work authorization"),
    (re.compile(r"\breloca"), "Willing to relocate"),
    (re.compile(r"\b(?:earliest|desired|preferred|expected|possible|proposed|available|availability) (?:\w+ )?start date\b|"
                r"\bwhen can you start\b|\bavailable to start\b|\bearliest\b.*\bstart\b"), "Earliest start date"),
    (re.compile(r"\bnotice period\b"), "Notice period"),
    (re.compile(r"\b(?:desired|expected|target)\b.*\b(?:salary|compensation|pay)\b|\bsalary (?:expectations?|requirements?)\b|"
                r"\bcompensation expectations?\b"), "Desired salary"),
    (re.compile(r"\bconvicted\b|\bconviction\b|\bfelony\b|\bcriminal record\b"), "Criminal record"),  # not 'pending charges'
    (re.compile(r"\b(?:over|at least) 18\b|\b18 years\b"), "Over 18"),
]
CANON_KEYS = {k for _, k in CANON if "{}" not in k}
LEGAL_KEYS = ("Visa sponsorship required", "Work authorization", "Criminal record", "Over 18")  # + 'Work authorization: *'


def classify(text) -> str:
    """eligibility | eeo | private | salary | number | date | text (first match wins, in that order). A question whose
    CANON key is a legal or EEO one counts too ('legally eligible to work in', 'Are you 18 years or older?')."""
    t = str(text or "")
    if ELIGIBILITY.search(t):
        return "eligibility"
    if EEO.search(t):
        return "eeo"
    k = norm_q(t)
    if k.startswith("EEO: "):
        return "eeo"
    if k in LEGAL_KEYS or k.startswith("Work authorization: "):
        return "eligibility"
    for kind, rx in (("private", PRIVATE), ("salary", SALARY), ("number", NUMBER), ("date", DATE)):
        if rx.search(t):
            return kind
    return "text"


def never_ai(text) -> bool:
    return classify(text) in ("eligibility", "eeo")


def yours(source) -> bool:
    """A bank row you wrote (Answers tab, CLI, a question you answered), not an approved AI draft. Rows from before the
    source column (None) do not count, so an eligibility / EEO answer saved then is asked once more."""
    return bool(source) and not str(source).startswith("AI")


def for_prompts(r) -> bool:
    """A bank row an AI prompt may see: not tagged eligibility / EEO, and not such a question whatever its tags."""
    return not set(db.tag_list(r["tags"])) & set(db.PROMPT_SKIP_TAGS) and not never_ai(r["question"])


def _lit(text) -> str:
    """NFKC, lower case, no (required)/(optional)/*/please, no punctuation, single spaces."""
    t = unicodedata.normalize("NFKC", str(text or "")).lower()
    t = re.sub(r"\((?:required|optional)\)|\*|\bplease\b", " ", t)
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def norm_q(text) -> str:
    """The canonical key of a question: _lit, then CANON ('Are you willing to relocate?' and 'willing to relocate' are
    both 'Willing to relocate')."""
    t = _lit(text)
    for rx, key in CANON:
        if m := rx.search(t):
            return key.format(*m.groups())
    return t


def _canon(key: str) -> bool:
    return key in CANON_KEYS or key.startswith("Work authorization: ")


def _merge_labels(*lists) -> list[str]:
    """Deduped on the wording (_lit): two labels that share a CANON key still both stay on the form."""
    out, seen = [], set()
    for lst in lists:
        for x in lst or []:
            x = " ".join(str(x).split())[:300]
            k = _lit(x)
            if x and k not in seen:
                seen.add(k)
                out.append(x)
    return out[:100]


def _bank_rows():
    return db.con().execute("SELECT id, question, answer, tags, private, source FROM answers WHERE star IS NULL").fetchall()


def known(text, employer: bool = True) -> dict | None:
    """{answer, answer_id, source} of the bank row with the same canonical key. employer: private rows and rows naming
    the salary floor never count. An eligibility / EEO question takes only an answer you wrote (yours())."""
    from .drafts import leaks

    key, legal = norm_q(text), never_ai(text)
    for r in _bank_rows():
        if (norm_q(r["question"]) == key and not (employer and (r["private"] or leaks(r["answer"])))
                and (not legal or yours(r["source"]))):
            return {"answer": r["answer"], "answer_id": r["id"], "source": f"bank #{r['id']}"}
    return None


def suggestions(text, n: int = 3) -> list[dict]:
    """Near matches from the bank (shown as 'Use this', never used on their own): Jaccard >= 0.5 over distinctive words,
    at least 2 shared. Never for eligibility or EEO, never a private, eligibility or EEO row."""
    if never_ai(text):
        return []
    from .drafts import leaks

    toks, out = db._tokens(text), []
    for r in _bank_rows():
        t = db._tokens(r["question"])
        both = toks & t
        if (r["private"] or not for_prompts(r) or leaks(r["answer"])
                or len(both) < 2 or len(both) / len(toks | t) < 0.5):
            continue
        out.append({"id": r["id"], "question": r["question"], "answer": r["answer"], "score": round(len(both) / len(toks | t), 2)})
    return sorted(out, key=lambda x: -x["score"])[:n]


def _key(job_id: int, text: str, apply_to: str) -> str:
    if apply_to == "bank":
        return norm_q(text)
    if apply_to.startswith(("job:", "offer:")) or apply_to == "contact":
        return f"job{job_id}:{apply_to}"  # two jobs at one company never share a JD or contact question
    return apply_to  # story:<competency>


def _answered(key: str) -> dict | None:
    """A reusable answer from the queue whose bank row still stands (and is not private now)."""
    r = db.con().execute("SELECT answer_id FROM questions WHERE key=? AND status='answered' AND scope='reusable' "
                         "AND answer_id IS NOT NULL ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    b = r and db.con().execute("SELECT id, answer, private, source FROM answers WHERE id=?", (r["answer_id"],)).fetchone()
    ok = b and not b["private"] and (yours(b["source"]) or not never_ai(key))  # overwritten by an AI draft since: ask
    return {"answer": b["answer"], "answer_id": b["id"], "source": f"bank #{b['id']}"} if ok else None


def ask(job, stage: str, text, kind=None, options=None, why: str = "", blocking: bool = True,
        apply_to: str = "bank", reuse: bool = True) -> tuple:
    """(answer | None | SKIP, source). Order: the bank (closed-form kinds and CANON keys by exact key; any reusable
    answer this queue saved for the same key), this job's own answer, a dismissal for this job (SKIP), an open question
    with the same key (this job joins it), else a new open question. None: asked, nothing to use yet.
    reuse=False: an open-ended form label (no AI to adapt an earlier answer): never taken from the bank, and answered for
    this job by default."""
    text = " ".join(str(text or "").split())[:300]
    kind = kind or classify(text)
    key = _key(job["id"], text, apply_to)
    c = db.con()
    if apply_to == "bank" and reuse:
        hit = _answered(key)
        if not hit and (kind in CLOSED_KINDS or options or _canon(key)):
            hit = known(text)
        if hit:
            return hit["answer"], hit["source"]
        if not known(text) and any(norm_q(r["question"]) == key and r["private"] for r in _bank_rows()):
            text, kind = f"This one is marked private: what should the form say? ({text})"[:300], "private"
    r = c.execute("SELECT answer FROM questions WHERE key=? AND job_id=? AND status='answered' AND scope='job' "
                  "ORDER BY id DESC LIMIT 1", (key, job["id"])).fetchone()
    if r:
        return r["answer"], "you"
    if c.execute("SELECT 1 FROM questions q JOIN question_waiters w ON w.qid=q.id WHERE q.key=? AND q.status='dismissed' "
                 "AND w.job_id=?", (key, job["id"])).fetchone():
        return SKIP, "left for you"
    context = {"stage": stage, "why": why[:300], "job_title": job["title"], "company": job["company"], "reuse": reuse}
    c.execute("INSERT OR IGNORE INTO questions(key, text, kind, options, context, blocking, apply_to, job_id) "
              "VALUES(?,?,?,?,?,?,?,?)", (key, text, "choice" if options else kind, json.dumps(options) if options else None,
                                          json.dumps(context), int(blocking), apply_to, job["id"]))
    qid = c.execute("SELECT id FROM questions WHERE key=? AND status='open'", (key,)).fetchone()["id"]
    c.execute("INSERT OR IGNORE INTO question_waiters(qid, job_id, stage) VALUES(?,?,?)", (qid, job["id"], stage))
    c.commit()
    return None, f"question #{qid}"


# ----------------------------------------------------------------------------- the context a stage receives
class Ctx:
    def __init__(self, job, stage, rows, partial=None, budget=CLICK_BUDGET, origin="user", provider=None):
        self.job, self.stage, self.rows = job, stage, rows
        self.partial = partial or {}
        self.budget, self.spent, self.origin, self.provider = budget, 0, origin, provider
        self.waiting, self.ai_ok = False, None

    def out(self, name) -> dict:
        return (self.rows.get(name) or {}).get("output") or {}

    def file(self, name):
        f = self.out(name).get("file")
        p = _dir(self.job) / f if f else None
        return p if p and p.is_file() else None

    def ask_src(self, text, kind=None, options=None, why="", blocking=True, apply_to="bank", reuse=True) -> tuple:
        a, src = ask(self.job, self.stage, text, kind, options, why, blocking, apply_to, reuse)
        if a is None and blocking:
            self.waiting = True
        return a, src

    def ask(self, text, kind=None, options=None, why="", blocking=True, apply_to="bank"):
        return self.ask_src(text, kind, options, why, blocking, apply_to)[0]


# ----------------------------------------------------------------------------- stage adapters
def _score(job, ctx):
    from . import resume

    if not (job["jd"] or "").strip():
        a = ctx.ask(f"Paste the job description or its URL for {job['company']} - {job['title']}", "jd",
                    why="the fit check and every document read it", apply_to="job:jd")
        if a is None:
            return {}
        if a is SKIP:
            raise Skipped("no job description: add one in the drawer to run the fit check")
        job = db.get_job(job["id"])
    resume.gap(job, ctx.provider)
    ctx.spent += _ai_ok(ctx)
    return {}


def _score_observe(job, ctx):
    p = _dir(job) / "gap.json"
    if not p.is_file():
        return None
    g = _load(p.read_text(encoding="utf-8"), None)
    if not isinstance(g, dict):
        return None
    # only the judgement: coverage() rewrites the keyword fields after every tailor, which must not stale anything
    fp = _h(json.dumps({k: g.get(k) for k in ("verdict", "why", "weak_areas", "red_flags", "suggestions")}, sort_keys=True))
    return {"file": "gap.json", "fp": fp, "score": g.get("match_score"), "verdict": g.get("verdict"), "why": g.get("why"),
            "missing": (g.get("missing_keywords") or [])[:15], "weak_areas": g.get("weak_areas") or []}


def _research(job, ctx):
    from . import extras

    extras.research(job, ctx.provider)
    ctx.spent += 1
    return {}


def _tailor(job, ctx):
    """Tailor by bullet; only rewrites with no flag (and no drop) are applied. Pass 17 replaces this with the studio."""
    from . import resume

    data = resume.tailor_bullets(job, provider=ctx.provider)
    ctx.spent += 1
    r = resume.apply_bullets(job, accept=[x["id"] for x in data["proposals"] if x["accepted"]], docx=True)
    return {"coverage": r["coverage"], "accepted": len(r["accepted"]), "docx": "resume.docx",
            "flagged": sum(bool(x["flags"]) for x in data["proposals"])}


def _letter(job, ctx):
    from . import resume

    out = resume.cover_letter(job, provider=ctx.provider)
    ctx.spent += 1
    resume.export_docx(out)
    return {"docx": "cover_letter.docx"}


def _flags(text: str, facts: str) -> list[str]:
    """The guess guard: a number or a skill the facts never mention."""
    from . import ats, resume

    flags = ["new number"] if resume._numbers(text) - resume._numbers(facts) else []
    return flags + (["unsupported"] if any(not ats.mentions(t, facts) for t in ats.claims_in(text)) else [])


def _answers(job, ctx):
    """Every form label gets an answer: closed-form ones (eligibility, EEO, salary, numbers, dates, choices, CANON keys)
    come from your answers only, open-ended ones are AI-drafted per job (never saved to the bank from here)."""
    from . import apply, resume
    from .profile import employer_safe

    stored = (_rows(job["id"]).get("answers") or {}).get("output") or {}  # labels added since this run was claimed
    form = _merge_labels(ctx.partial.get("form"), stored.get("form"))
    done = {a["key"]: a for a in ctx.partial.get("answers") or [] if isinstance(a, dict) and a.get("key")}
    waiting, facts, notes = set(), None, _job_notes(job["id"])
    for label in form:
        key = norm_q(label)
        if key in done:
            continue
        kind, flags = classify(label), []
        if kind in CLOSED_KINDS or _canon(key):
            a, src = ctx.ask_src(label, kind, why="a form question only you can answer")
        elif not _ai_ok(ctx):
            a, src = ctx.ask_src(label, kind, why="no AI provider: write this job's answer", reuse=False)
        else:
            if ctx.spent >= ctx.budget:
                continue  # the rest on the next run (the row then reads ready)
            r = apply.answer(job, label, ctx.provider, need_facts=True, propose=False, notes=notes)
            ctx.spent += 1
            if r["missing"]:
                m, src = ctx.ask_src(r["missing"], classify(r["missing"]), why=f"needed to answer '{label[:80]}'")
                a = None if m is None else SKIP if m is SKIP else f"(left for you: the draft still lacked '{r['missing'][:120]}')"
                src = "left for you" if a else src
            else:
                if facts is None:
                    facts = "\n".join((resume._current_resume(job), job["jd"] or "", notes,
                                       "\n".join(f"{x['question']} {x['answer']}" for x in db.employer_answers())))
                a, src, flags = r["answer"], "ai", _flags(r["answer"], facts)
        if a is None:
            waiting.add(key)
            continue
        text = "(left for you)" if a is SKIP else str(a)
        try:
            employer_safe(f"{label}: {text}", any_line=True)
        except SystemExit:
            text, flags = "(withheld: names your salary floor)", []
        done[key] = {"key": key, "label": label, "answer": text, "source": src, "flags": flags}
    lines = [f"# Form answers: {job['company']} - {job['title']}", ""]
    for label in form:
        a = done.get(norm_q(label))
        lines += [f"## {label}", ""]
        if a:
            note = f"_source: {a['source']}" + (f"; check this: {', '.join(a['flags'])}" if a["flags"] else "") + "_"
            lines += [a["answer"], "", note]
        else:
            lines.append("(waiting for you)" if norm_q(label) in waiting else "(not drafted yet)")
        lines.append("")
    text = "\n".join(lines)
    resume.write_doc(resume.app_dir(job) / "form_answers.md", text)
    return {"form": form, "answers": [done[k] for k in dict.fromkeys(map(norm_q, form)) if k in done],
            "file": "form_answers.md", "fp": _h(text)}


def _job_notes(job_id: int) -> str:
    """Facts you gave for this job only (a draft's missing fact answered 'only this job'), for the redraft's prompt.
    Never an eligibility, EEO or private one, never the salary floor."""
    from .drafts import leaks

    rows = db.con().execute("SELECT text, kind, answer FROM questions WHERE job_id=? AND status='answered' AND scope='job' "
                            "AND apply_to='bank' ORDER BY id", (job_id,)).fetchall()
    return "\n".join(f"Q: {r['text']}\nA: {r['answer']}" for r in rows
                     if r["kind"] not in ("eligibility", "eeo", "private") and not never_ai(r["text"]) and not leaks(r["answer"]))


def _answers_observe(job, ctx):
    row = ctx.rows.get("answers")
    o = (row or {}).get("output") or {}
    if not o.get("form") and (not row or row["state"] in ("done", "waiting")):
        return {"form": [], "answers": [], "fp": NONE_FP, "note": "no form questions yet"}  # nothing to answer = done
    return dict(o) if row and row["state"] == "done" else None


def _new_labels(output: dict) -> list[str]:
    have = {a.get("key") for a in output.get("answers") or [] if isinstance(a, dict)}
    return [x for x in output.get("form") or [] if norm_q(x) not in have]


def _apply_observe(job, ctx):
    if not (job["applied_at"] or job["status"] in db.STAGE_ORDER):
        return None
    return {"applied_at": job["applied_at"], "via": "manual", "url": job["url"], "fp": job["applied_at"] or job["status"]}


def _apply_wait(job, ctx):
    return "you", "send the application (posting link, resume, letter, form_answers.md), then Mark applied"


REF_RE = re.compile(r"(?i)\b(?:reference|ref|confirmation|application|requisition|req|candidate)(?:\s+(?:number|no\.?|id|code))?"
                    r"\s*(?:[:#]|is)?\s*#?\s*([A-Z0-9][A-Z0-9-]{3,24})\b")


def confirmation_ref(job_id: int) -> str:
    """The confirmation number in the job's trusted 'application received' mail (subject or text), or ''. Weak-tie or
    spoofed mail filed to the job never supplies the reference a follow-up quotes."""
    for m in db.con().execute("SELECT subject, snippet FROM mail WHERE job_id=? AND direction='in' AND trusted=1 "
                              "AND category='application_received' ORDER BY id DESC", (job_id,)).fetchall():
        for x in REF_RE.finditer(f"{m['subject'] or ''}\n{m['snippet'] or ''}"):
            if re.search(r"\d", x.group(1)):
                return x.group(1)
    return ""


def _confirm_observe(job, ctx):
    m = db.con().execute("SELECT id, COALESCE(sent_at, created_at) at FROM mail WHERE job_id=? AND direction='in' AND trusted=1 "
                         "AND category='application_received' ORDER BY id LIMIT 1", (job["id"],)).fetchone()
    return {"mail_id": m["id"], "at": m["at"], "ref": confirmation_ref(job["id"]), "via": "email", "fp": str(m["id"])} if m else None


def _confirm_wait(job, ctx):
    return "employer", "the confirmation mail is not in yet"


def _last_status_ts(job_id: int) -> str:
    r = db.con().execute("SELECT MAX(ts) t FROM events WHERE job_id=? AND kind='status'", (job_id,)).fetchone()
    return r["t"] or ""


def _followup_observe(job, ctx):
    rows = db.con().execute("SELECT ts FROM events WHERE job_id=? AND kind='followup' AND COALESCE(detail, '') != 'drafted' "
                            "AND ts >= ? ORDER BY ts", (job["id"], _last_status_ts(job["id"]))).fetchall()
    return {"last": rows[-1]["ts"], "nudges": len(rows), "fp": rows[-1]["ts"]} if rows else None


def _followup_wait(job, ctx):
    if w := db.followup_waiting(job["id"]):
        return "you", f"follow-up draft waiting in the Inbox #{w['id']}"
    r = db.con().execute("SELECT MIN(at) at FROM interviews WHERE job_id=? AND at >= ?",  # as db.needs_followup: local date
                         (job["id"], datetime.now().strftime("%Y-%m-%d"))).fetchone()
    if r["at"]:
        return "employer", f"no follow-up needed: an interview is booked for {r['at'][:16]}"
    last =db.con().execute("SELECT MAX(ts) t FROM events WHERE job_id=? AND kind NOT IN "
                            f"({','.join('?' * len(db.BOOKKEEPING))})", (job["id"], *db.BOOKKEEPING)).fetchone()["t"]
    days = int(settings.pref("followup_days") or 7)
    due = (datetime.fromisoformat(last[:19]) + timedelta(days=days)).strftime("%b %d") if last else "soon"
    return "employer", f"no reply yet: follow-up due {due} (the monitor loop drafts it)"


def _schedule_observe(job, ctx):
    rows = db.con().execute("SELECT id, round, kind, at, interviewers FROM interviews WHERE job_id=? AND at IS NOT NULL "
                            "ORDER BY at", (job["id"],)).fetchall()
    if not rows:
        return None
    rr = [dict(r) for r in rows]
    return {"rounds": rr, "fp": _h(json.dumps([[r["id"], r["at"]] for r in rr]))}


def _schedule_wait(job, ctx):
    return "employer", "no interview booked yet (interview mail and the Rounds group add them)"


def _prep(job, ctx):
    from . import interview

    for c in interview.story_prompt(job)["missing"][:2]:  # optional: prep runs anyway, a story added later stales it
        ctx.ask(f"A STAR story for {c}: what happened, what you did, the result", "story", blocking=False,
                why=f"the posting stresses {c} and no story of yours is tagged with it", apply_to=f"story:{c}")
    interview.prep(job, provider=ctx.provider)
    ctx.spent += 1
    r = db.con().execute("SELECT id FROM interviews WHERE job_id=? AND at >= ? ORDER BY at LIMIT 1",
                         (job["id"], f"{datetime.now():%Y-%m-%d}")).fetchone()
    return {"round_id": r["id"] if r else None}


def _utc(at: str) -> str:
    """A local round time ('YYYY-MM-DD HH:MM' or a date) as the UTC text events use."""
    d = datetime.strptime(at[:16], "%Y-%m-%d %H:%M") if len(at) >= 16 else datetime.strptime(at[:10], "%Y-%m-%d")
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _thanks_events(job, kind: str) -> list:
    from .apply import last_round

    r = last_round(job["id"])
    if not r:
        return []
    return db.con().execute("SELECT ts FROM events WHERE job_id=? AND kind=? AND ts >= ?", (job["id"], kind, _utc(r["at"]))).fetchall()


def _thanks_pending(job):
    return db.con().execute("SELECT id FROM pending WHERE job_id=? AND kind='send_email' AND status='pending' "
                            "AND json_extract(payload, '$.purpose')='thanks' ORDER BY id LIMIT 1", (job["id"],)).fetchone()


def _thanks_observe(job, ctx):
    ev = _thanks_events(job, "thanks")  # written when the mail is sent
    return {"sent": ev[-1]["ts"], "fp": ev[-1]["ts"]} if ev else None


def _thanks_na(job, ctx):
    from .apply import last_round

    r = last_round(job["id"])
    if not r:
        nxt = db.con().execute("SELECT at FROM interviews WHERE job_id=? AND at > ? ORDER BY at LIMIT 1",
                               (job["id"], f"{datetime.now():%Y-%m-%d %H:%M}")).fetchone()
        return "later", f"after the interview{' on ' + nxt['at'] if nxt else ''}"
    if r["at"][:10] < f"{datetime.now() - timedelta(days=3):%Y-%m-%d}":
        return "skipped", f"n/a: the last interview ({r['at'][:10]}) was more than 3 days ago"
    if _thanks_events(job, "thanks_draft") and not _thanks_pending(job):
        return "skipped", "the drafted thank-you was set aside (rejected, or no address to send it to)"
    return None


def _thanks_wait(job, ctx):
    p = _thanks_pending(job)
    return ("you", f"thank-you waiting in the Inbox #{p['id']}") if p else None


def _thanks(job, ctx):
    from . import apply

    r = apply.last_round(job["id"])
    if not (job["contact_email"] or "").strip():
        a = ctx.ask(f"Who should the thank-you for {job['company']} go to (email)?", "contact", apply_to="job:contact_email",
                    why="the job has no contact email")
        if a is None:
            return {}
        if a is SKIP:
            raise Skipped("no address: you send the thank-you yourself")
        job = db.get_job(job["id"])
    res = apply.thanks(job, provider=ctx.provider, review=ctx.origin != "user")  # unattended: always waits in the Inbox
    ctx.spent += _ai_ok(ctx)
    return {"round_id": r["id"] if r else None, "inbox_id": res["proposal"].get("id")}


def _offer(job, ctx):
    from . import apply

    if not (db.get_offer(job["id"]) or {}).get("base"):
        a = ctx.ask(f"What base salary did {job['company']} offer?", "number", apply_to="offer:base",
                    why="the evaluation weighs the structured offer")
        if a is None:
            return {}
    apply.offer(job, provider=ctx.provider)
    ctx.spent += 1
    return {}


def _close_observe(job, ctx):
    return {"status": job["status"], "at": job["updated_at"], "fp": job["status"]} if job["status"] in CLOSED else None


for _st in (
    Stage("score", "Fit check", ("saved",), reads=("jd", "profile"), tool="fit_check", ai=1, run=_score,
          observe=_score_observe),
    Stage("research", "Research", ("saved", "interview"), needs=("score",), tool="research", ai=1, run=_research,
          observe=_doc("research.md"), blocked=_need_ai),
    Stage("tailor", "Tailor resume", ("saved",), needs=("score",), reads=("jd", "profile"), tool="tailor", ai=1,
          run=_tailor, observe=_doc("resume.md", docx="resume.docx"), blocked=_need_ai),
    Stage("letter", "Cover letter", ("saved",), needs=("tailor", "research"), reads=("tailor", "research", "score"),
          tool="cover_letter", ai=1, run=_letter, observe=_doc("cover_letter.md", docx="cover_letter.docx"), blocked=_need_ai),
    Stage("answers", "Form answers", ("saved",), needs=("score",), reads=("research", "tailor"), tool="form_answers", ai=1,
          run=_answers, observe=_answers_observe),
    Stage("apply", "Apply", ("saved",), needs=("tailor", "letter", "answers"), observe=_apply_observe, wait=_apply_wait),
    Stage("confirm", "Confirmation", ("applied", "screening"), needs=("apply",), observe=_confirm_observe,
          wait=_confirm_wait),
    Stage("followup", "Follow-up", ("applied", "screening", "interview"), needs=("apply",), observe=_followup_observe,
          wait=_followup_wait),
    Stage("schedule", "Schedule", ("screening", "interview"), needs=("apply",), observe=_schedule_observe,
          wait=_schedule_wait),
    Stage("prep", "Interview prep", ("interview",), needs=("research",),
          reads=("research", "tailor", "schedule", "score", "stories"), tool="interview_prep", ai=1, run=_prep,
          observe=_doc("interview_prep.md"), blocked=_need_ai),
    Stage("thanks", "Thank-you", ("interview",), needs=("schedule",), tool="thank_you", ai=1,  # done per round: no reads
          run=_thanks, observe=_thanks_observe, na=_thanks_na, wait=_thanks_wait),
    Stage("offer", "Offer", ("offer",), ai=1, run=_offer, observe=_doc("offer.md"), blocked=_need_ai),
    Stage("close", "Close", LIVE, observe=_close_observe),
):
    register(_st)
MANUAL = ("apply", "offer", "close")  # run_to stops here whatever an approval lists


# ----------------------------------------------------------------------------- state
def _cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=STUCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S.%f")


def _adopt(job_id: int, name: str, obs: dict, inputs: dict) -> dict:
    """Work found done outside a run (a drawer button, a hand edit, a sent mail): the row becomes done, origin
    'observed', built from what exists now."""
    db.con().execute(
        "INSERT INTO pipeline(job_id, stage, state, output, inputs, fp, rev, origin, updated_at) VALUES(?,?,'done',?,?,?,1,"
        "'observed',?) ON CONFLICT(job_id, stage) DO UPDATE SET state='done', output=excluded.output, inputs=excluded.inputs, "
        "fp=excluded.fp, rev=pipeline.rev+1, origin='observed', error=NULL, attempts=0, updated_at=excluded.updated_at "
        "WHERE pipeline.state != 'running'",
        (job_id, name, json.dumps(obs), json.dumps(inputs), obs.get("fp"), _now()))
    db.con().commit()
    return _rows(job_id).get(name)


def _relevance(job, s: Stage) -> tuple | None:
    if job["status"] in s.statuses:
        return None
    i = db.STATUSES.index(job["status"])
    if any(db.STATUSES.index(x) > i for x in s.statuses):
        return "later", f"relevant again at {next(x for x in s.statuses if db.STATUSES.index(x) > i)}"
    return "skipped", f"n/a while the job is {job['status']}"


def _status(job_id: int, save: bool = True, shared: dict | None = None) -> tuple[list[dict], dict]:
    job = db.get_job(job_id)
    rows = _rows(job_id)
    cur = {**(shared or _shared_roots()), "jd": _h(job["jd"] or "")}
    asks = {r["stage"]: r for r in db.con().execute(
        "SELECT w.stage, q.id, q.text FROM question_waiters w JOIN questions q ON q.id=w.qid WHERE w.job_id=? AND "
        "q.status='open' AND q.blocking=1 ORDER BY q.id DESC", (job_id,)).fetchall()}
    run_tos = {}
    for p in db.con().execute("SELECT id, payload FROM pending WHERE job_id=? AND kind='run_to' AND status='pending'", (job_id,)):
        for n in _load(p["payload"], {}).get("stages") or []:
            run_tos.setdefault(n, p["id"])
    ctx = Ctx(job, None, rows)
    out, by, cutoff = [], {}, _cutoff()
    for s in REGISTRY.values():
        row = rows.get(s.name)
        running = bool(row and row["state"] == "running")
        obs = None
        if s.observe and not running:
            try:
                obs = s.observe(job, ctx)
            except (Exception, SystemExit) as x:  # a corrupt file costs this stage's 'done', never the whole status
                log.get("pipeline").warning("#%s %s observe failed: %s", job_id, s.name, x)
        if obs is not None and (not row or row["state"] != "done" or row["fp"] != obs.get("fp")):
            inputs = {r: cur.get(r, "") for r in s.reads}
            row = (_adopt(job_id, s.name, obs, inputs) if save else
                   {**(row or {"rev": 0, "error": None, "attempts": 0, "updated_at": None}), "state": "done",
                    "output": obs, "inputs": inputs, "fp": obs.get("fp"), "origin": "observed"})
            rows[s.name] = row
        is_done = obs is not None if s.observe else bool(row and row["state"] == "done")
        cur[s.name] = (row["fp"] or "") if is_done else ""
        state, on, why = _derive(job, s, row, is_done, running, cur, by, asks, run_tos, ctx, cutoff)
        e = {"name": s.name, "label": s.label, "state": state, "on": on, "why": why, "tool": s.tool, "ai": s.ai,
             "unattended": bool(s.tool and s.run), "manual": s.run is None or s.name in MANUAL,
             "output": {k: v for k, v in ((row or {}).get("output") or {}).items() if k != "_resume"},
             "inputs": (row or {}).get("inputs") or {}, "fp": cur[s.name], "rev": (row or {}).get("rev", 0),
             "origin": (row or {}).get("origin"), "updated_at": (row or {}).get("updated_at"),
             "error": (row or {}).get("error"), "attempts": (row or {}).get("attempts", 0)}
        by[s.name] = e
        out.append(e)
    if save:
        _save_summary(job, out, rows.get("_summary"))
    return out, cur


def _derive(job, s, row, is_done, running, cur, by, asks, run_tos, ctx, cutoff) -> tuple:
    if running:
        if (row["updated_at"] or "") < cutoff:
            return "error", None, "interrupted (Lodestar closed while this ran): run it again"
        return "running", None, f"running since {row['updated_at'][:16]} UTC"
    if is_done:
        for r in s.reads if row.get("fp") != NONE_FP else ():  # nothing built yet cannot be out of date
            was, now = (row.get("inputs") or {}).get(r), cur.get(r)
            if was is not None and now and was != now and "?" not in (was, now):
                what = REGISTRY[r].label.lower() if r in REGISTRY else {"jd": "the job description", "profile": "your profile",
                                                                        "stories": "your stories"}[r]
                return "stale", None, f"{what} changed since this was built (from {r} {was[:6] or 'none'})"
        if new := _new_labels(row.get("output") or {}) if s.name == "answers" else []:
            return "ready", None, f"{len(new)} form question(s) not answered yet"
        return "done", None, (row.get("output") or {}).get("note") or f"done (rev {row.get('rev') or 1}, {row.get('origin') or 'run'})"
    if row and row["state"] == "skipped":
        return "skipped", None, row.get("error") or "skipped by you"
    if job["status"] in CLOSED:
        return "skipped", None, f"n/a: the job is {job['status']}"
    if rel := _relevance(job, s):
        return rel[0], None, rel[1]
    for n in s.needs:
        if by[n]["state"] not in ("done", "stale", "skipped"):
            return "todo", None, f"after {REGISTRY[n].label.lower()}"
    if s.na and (na := s.na(job, ctx)):
        return na[0], None, na[1]
    if row and row["state"] == "error":
        return "error", None, row.get("error") or "failed"
    if s.name in run_tos:
        return "waiting", "you", f"waiting for your approval in the Inbox #{run_tos[s.name]}"
    if s.run is None:
        if s.wait and (w := s.wait(job, ctx)):
            return "waiting", w[0], w[1]
        return "later", None, "when the job ends (accepted, rejected or withdrawn)" if s.name == "close" else "later"
    if s.blocked and (b := s.blocked(job, ctx)):
        return "blocked", None, b
    if row and row["state"] == "waiting" and s.name in asks:
        return "waiting", "you", f"question #{asks[s.name]['id']}: {asks[s.name]['text'][:120]}"
    if s.wait and (w := s.wait(job, ctx)):
        return "waiting", w[0], w[1]
    return "ready", None, "ready to run"


def fit_skip(entries: list[dict]) -> bool:
    """The fit gate: a 'skip' verdict keeps Autopilot away from the job (a click is the override)."""
    return next((e["output"].get("verdict") for e in entries if e["name"] == "score"), None) == "skip"


def _summary_of(entries: list[dict]) -> dict:
    st = [e["state"] for e in entries]
    nxt = next((e["name"] for e in entries if e["state"] == "ready"), None)
    return {"next": nxt, "you": sum(e["state"] == "waiting" and e["on"] == "you" for e in entries),
            "stale": st.count("stale"), "errors": st.count("error"), "done": st.count("done"),
            "total": sum(x not in ("later", "skipped") for x in st), "fit_skip": fit_skip(entries)}


def _save_summary(job, entries, old) -> None:
    summ = _summary_of(entries)
    if old and old.get("output") == summ:
        return  # only a changed summary is written
    db.con().execute("INSERT INTO pipeline(job_id, stage, state, output, updated_at) VALUES(?, '_summary', 'done', ?, ?) "
                     "ON CONFLICT(job_id, stage) DO UPDATE SET output=excluded.output, updated_at=excluded.updated_at",
                     (job["id"], json.dumps(summ), _now()))
    db.con().commit()


def status(job_id: int, save: bool = True, shared: dict | None = None) -> list[dict]:
    """Per stage: {name, label, state, on, why, output, inputs, fp, rev, origin, updated_at, error, attempts, tool,
    unattended, manual}. save: adopt work found done and write the board summary."""
    return _status(job_id, save, shared)[0]


def context(job_id: int) -> dict:
    """The one record per job: the job, the root fingerprints and every stage's state and output."""
    entries, cur = _status(job_id, save=False)
    return {"job": dict(db.get_job(job_id)), "roots": {r: cur[r] for r in ROOTS},
            "stages": {e["name"]: {k: e[k] for k in ("state", "why", "output", "inputs", "fp", "rev", "origin")} for e in entries}}


def next_stage(job_id: int) -> str | None:
    return next((e["name"] for e in status(job_id) if e["state"] == "ready"), None)


def summary() -> dict:
    """{job_id: {next, you, stale, errors, done, total, fit_skip}} from the stored summaries (one query)."""
    return {r["job_id"]: _load(r["output"], {}) for r in db.con().execute(
        "SELECT p.job_id, p.output FROM pipeline p JOIN jobs j ON j.id=p.job_id WHERE p.stage='_summary'").fetchall()}


# ----------------------------------------------------------------------------- running
def _claim(job_id: int, stage: str, seen) -> bool:
    """One statement: a stage another thread changed since `seen` (or is running, unless it is stuck) is not claimed."""
    c = db.con()
    if c.in_transaction:
        c.commit()
    cur = c.execute("INSERT INTO pipeline(job_id, stage, state, updated_at) VALUES(?, ?, 'running', ?) ON CONFLICT(job_id, stage) "
                    "DO UPDATE SET state='running', updated_at=excluded.updated_at WHERE pipeline.updated_at IS ? AND "
                    "(pipeline.state != 'running' OR pipeline.updated_at < ?)", (job_id, stage, _now(), seen, _cutoff()))
    c.commit()
    return cur.rowcount == 1


@contextmanager
def claimed(job_id: int, stage: str, origin: str = "user"):
    """The same claim for a drawer button doing a stage's work by hand: refused while a run (yours, Autopilot's or an
    approval's) holds that step; on exit the step's state comes back and the result is adopted through observe."""
    row = _rows(job_id).get(stage)
    if not _claim(job_id, stage, row["updated_at"] if row else None):
        raise SystemExit(f"this step is already running for #{job_id}: try again when it is done")
    try:
        yield
    finally:
        db.release(close=False)
        c = db.con()
        if row:
            c.execute("UPDATE pipeline SET state=?, updated_at=? WHERE job_id=? AND stage=?",
                      ("error" if row["state"] == "running" else row["state"], _now(), job_id, stage))
        else:
            c.execute("DELETE FROM pipeline WHERE job_id=? AND stage=? AND state='running'", (job_id, stage))
        c.commit()
        try:
            status(job_id)
        except (Exception, SystemExit):
            db.release(close=False)


def _keep_on_rerun(output: dict) -> dict:
    """A re-run keeps only the form labels: every answer is looked up again (a bank row changed or marked private since,
    your job answers and dismissals through ask()), and the AI drafts are redone."""
    return {"form": output.get("form") or []}


def _finish(job_id: int, stage: str, state: str, output=None, inputs=None, fp=None, origin=None, error=None,
            ok: bool = False) -> None:
    c = _begin()  # with add_form_questions: labels added while this ran are unioned in, never lost
    try:
        old = c.execute("SELECT output FROM pipeline WHERE job_id=? AND stage=?", (job_id, stage)).fetchone()
        if output is not None and (oform := _load(old["output"] if old else None, {}).get("form")):
            output["form"] = _merge_labels(output.get("form"), oform)
        c.execute("UPDATE pipeline SET state=?, output=COALESCE(?, output), inputs=COALESCE(?, inputs), fp=COALESCE(?, fp), "
                  "rev=rev+?, origin=COALESCE(?, origin), error=?, attempts=CASE WHEN ? THEN 0 WHEN ?='error' THEN attempts+1 "
                  "ELSE attempts END, updated_at=? WHERE job_id=? AND stage=?",
                  (state, json.dumps(output) if output is not None else None, json.dumps(inputs) if inputs is not None else None,
                   fp, int(ok), origin, error, int(ok), state, _now(), job_id, stage))
        c.commit()
    except BaseException:
        c.rollback()
        raise


def _log_run(job_id, stage, origin, outcome, detail, n) -> None:
    db.con().execute("INSERT INTO pipeline_runs(job_id, stage, origin, outcome, detail, ai) VALUES(?,?,?,?,?,?)",
                     (job_id, stage, origin, outcome, str(detail)[:500], int(n)))
    db.con().commit()


def run(job_id: int, stage: str, origin: str = "user", provider: str | None = None, rerun: bool = False,
        budget: int = CLICK_BUDGET, _to: str | None = None, _only=None) -> dict:
    """One stage now: {job_id, stage, outcome: done | waiting | skipped | error, detail, ai}. SystemExit when the stage
    cannot run (not relevant, waiting on you, a need not done, manual, already done without rerun, claimed)."""
    s = REGISTRY.get(stage)
    if not s:
        raise SystemExit(f"unknown step '{str(stage)[:30]}'. Steps: {', '.join(REGISTRY)}")
    if s.run is None:
        raise SystemExit(f"{s.label} is a step you (or the monitor loop) do: Lodestar never runs it")
    entries, cur = _status(job_id)
    e = next(x for x in entries if x["name"] == stage)
    if e["state"] in ("done", "stale") and not rerun:
        raise SystemExit(f"#{job_id} {s.label} is {e['state']} ({e['why']}): re-run it to build it again")
    if e["state"] not in ("ready", "error", "done", "stale"):
        raise SystemExit(f"#{job_id} {s.label} cannot run now: {e['state']} ({e['why']})")
    if origin == "approved":  # an approved batch (and its resumes) spends from the same daily budget as Autopilot
        per_day = int(settings.pref("autopilot_ai_per_day"))
        left = per_day - spent_today()
        if s.ai and left < 1:
            raise SystemExit(_budget_note(f"daily AI budget reached ({per_day - left}/{per_day} in 24 h): #{job_id} "
                                          f"{s.label} waits; run it yourself or raise the budget in Setup > Autopilot"))
        budget = min(budget, left)
    rows = _rows(job_id)
    row = rows.get(stage)
    inputs = {r: cur.get(r, "") for r in s.reads}  # at claim time: an upstream change during the run reads as stale after
    if not _claim(job_id, stage, row["updated_at"] if row else None):
        raise SystemExit(f"#{job_id} {s.label} is already running, or changed meanwhile: refresh")
    prev = {k: v for k, v in ((row or {}).get("output") or {}).items() if k != "_resume"}
    ctx = Ctx(db.get_job(job_id), stage, rows, _keep_on_rerun(prev) if rerun and e["state"] in ("done", "stale") else prev,
              budget, origin, provider)
    try:
        out = s.run(ctx.job, ctx) or {}
        if ctx.waiting:
            outcome, detail = "waiting", "waiting for your answer (Inbox > Questions)"
            _finish(job_id, stage, "waiting", {**out, "_resume": {"to": _to, "only": sorted(_only) if _only else None}},
                    origin=origin)
        else:
            if "fp" not in out and s.observe:
                out = {**(s.observe(db.get_job(job_id), ctx) or {}), **out}
            outcome, detail = "done", out.get("file") or "done"
            _finish(job_id, stage, "done", out, inputs, out.get("fp") or _h(json.dumps(out, sort_keys=True, default=str)),
                    origin, ok=True)
    except Skipped as x:
        outcome, detail = "skipped", str(x)
        _finish(job_id, stage, "skipped", origin=origin, error=str(x)[:500])
    except (Exception, SystemExit) as x:  # SystemExit from helpers is the user-facing message
        db.release(close=False)
        outcome, detail = "error", str(x) or type(x).__name__
        _finish(job_id, stage, "error", origin=origin, error=detail[:500])
        log.get("pipeline").warning("#%s %s failed: %s", job_id, stage, detail)
    _log_run(job_id, stage, origin, outcome, detail, ctx.spent)
    try:
        status(job_id)  # the board summary follows what just ran (Autopilot, a resumed step, a click)
    except (Exception, SystemExit):
        db.release(close=False)
    return {"job_id": job_id, "stage": stage, "outcome": outcome, "detail": detail, "ai": ctx.spent}


def run_to(job_id: int, target: str, origin: str = "user", provider: str | None = None, rerun: bool = False,
           only=None) -> list[dict]:
    """Run the ready stages in order up to target; stop at the first waiting, error, blocked or manual stage, and at a
    stale one unless rerun. only: the stages an approval covered (others are passed over)."""
    if target not in REGISTRY:
        raise SystemExit(f"unknown step '{str(target)[:30]}'. Steps: {', '.join(REGISTRY)}")
    names = list(REGISTRY)[:list(REGISTRY).index(target) + 1]
    results, ran = [], set()
    while True:
        st = {e["name"]: e for e in status(job_id)}
        nxt = None
        for n in names:
            e = st[n]
            if e["state"] in ("done", "skipped", "later"):
                continue
            if n in MANUAL or REGISTRY[n].run is None:
                break
            if only and n not in only and e["state"] != "todo":
                continue
            if e["state"] == "ready" or (e["state"] == "stale" and rerun):
                nxt = n
            break
        if not nxt or nxt in ran:
            return results
        ran.add(nxt)
        r = run(job_id, nxt, origin, provider, rerun=st[nxt]["state"] == "stale", _to=target, _only=only)
        results.append(r)
        if r["outcome"] != "done":
            return results


def skip(job_id: int, stage: str, on: bool = True) -> None:
    """Skip a step for this job (no letter for this one), or undo it."""
    if stage not in REGISTRY:
        raise SystemExit(f"unknown step '{str(stage)[:30]}'. Steps: {', '.join(REGISTRY)}")
    db.get_job(job_id)
    row = _rows(job_id).get(stage)
    if row and row["state"] == "running":
        raise SystemExit(f"#{job_id} {REGISTRY[stage].label} is running right now")
    c = db.con()
    if on:
        c.execute("INSERT INTO pipeline(job_id, stage, state, origin, error, updated_at) VALUES(?,?,'skipped','user',?,?) "
                  "ON CONFLICT(job_id, stage) DO UPDATE SET state='skipped', origin='user', error=excluded.error, "
                  "updated_at=excluded.updated_at", (job_id, stage, "skipped by you", _now()))
    elif row and row["state"] == "skipped":
        if row["output"]:
            c.execute("UPDATE pipeline SET state='waiting', error=NULL, updated_at=? WHERE job_id=? AND stage=?", (_now(), job_id, stage))
        else:
            c.execute("DELETE FROM pipeline WHERE job_id=? AND stage=?", (job_id, stage))
    c.commit()
    status(job_id)


def kick(job_id: int, stage: str | None = None, origin: str = "user", to: str | None = None, only=None) -> None:
    """Run a stage (and then on to `to`) now: a daemon thread when AUTO (the app), inline otherwise (CLI, tests).
    stage and to both None: run to the next stop."""
    def go():
        try:
            if stage:
                run(job_id, stage, origin=origin, _to=to, _only=only)
            if to or not stage:
                run_to(job_id, to or list(REGISTRY)[-1], origin=origin, only=only)
        except (Exception, SystemExit) as e:
            log.get("pipeline").warning("#%s kick %s failed: %s", job_id, stage or to, e)
        finally:
            db.release(close=AUTO)  # a worker thread's connection goes with it
    if AUTO:
        threading.Thread(target=go, daemon=True, name=f"pipeline-{job_id}").start()
    else:
        go()


def log_runs(job_id: int | None = None, limit: int = 50) -> list[dict]:
    q, args = "SELECT * FROM pipeline_runs", ()
    if job_id is not None:
        q, args = q + " WHERE job_id=?", (job_id,)
    return [dict(r) for r in db.con().execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()]


# ----------------------------------------------------------------------------- answering
TARGET_SCOPE_JOB = ("job:", "offer:", "contact")


def _apply_target(target: str, job_id: int, text: str) -> None:
    """Write an answer where the asking stage reads it: the job's JD or contact, the offer, a story."""
    if target == "job:jd":
        from .resume import set_jd
        from .util import read_source

        set_jd(job_id, read_source(text, allow_files=False))
    elif target == "job:contact_email":
        from .contacts import EMAIL_RE, from_job_contact

        if len(text) > 254 or not EMAIL_RE.fullmatch(text):
            raise SystemExit("give one email address, like name@company.com")
        db.update_job(job_id, touch=False, contact_email=text)
        from_job_contact(job_id, db.get_job(job_id)["contact_name"] or "", text)
    elif target.startswith("offer:"):
        db.set_offer(job_id, **{target.split(":", 1)[1]: text})
    elif target.startswith("story:"):
        from .interview import save_story

        c = target.split(":", 1)[1]
        save_story(f"{c.capitalize()} story ({datetime.now():%Y-%m-%d %H%M%S})", situation=text, competencies=[c])


def _scope_default(q) -> str:
    if q["kind"] == "private" or q["apply_to"].startswith(TARGET_SCOPE_JOB) or _load(q["context"], {}).get("reuse") is False:
        return "job"
    return "reusable"


def _question(qid: int):
    q = db.con().execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        raise SystemExit(f"no question #{qid}")
    if q["status"] != "open":
        raise SystemExit(f"question #{qid} is already {q['status']}")
    return q


def _resume_waiters(pairs) -> list[tuple]:
    """Waiting stages with no other open blocking question read as ready again. Your own runs and approved batches
    continue now; Autopilot's wait for the next cycle (inside its budgets and switches)."""
    out = []
    for jid, stage in dict.fromkeys(pairs):
        row = _rows(jid).get(stage)
        if not row or row["state"] != "waiting" or db.con().execute(
                "SELECT 1 FROM question_waiters w JOIN questions q ON q.id=w.qid WHERE w.job_id=? AND w.stage=? AND "
                "q.status='open' AND q.blocking=1", (jid, stage)).fetchone():
            continue
        out.append((jid, stage))
        if row["origin"] in ("user", "approved"):
            r = row["output"].get("_resume") or {}
            kick(jid, stage, row["origin"], r.get("to"), set(r["only"]) if r.get("only") else None)
    return out


def answer(qid: int, text, scope: str | None = None, private: bool | None = None, job_id: int | None = None) -> dict:
    """Answer a question: {resumed: [(job_id, stage)], answer_id}. scope 'reusable' (every job: saved to the answer bank)
    or 'job' (this job only, never in the bank); private forces 'job'. A job, offer or contact question is always 'job'."""
    q = _question(qid)
    text = str(text or "").strip()
    if not 0 < len(text) <= 4000:
        raise SystemExit("an answer is 1-4000 characters")
    opts = _load(q["options"], None)
    if opts and text not in opts:
        raise SystemExit(f"pick one of: {', '.join(map(str, opts))}")
    if scope not in (None, "reusable", "job"):
        raise SystemExit("scope is reusable (every job) or job (this job only)")
    target = q["apply_to"]
    job_only = target.startswith(TARGET_SCOPE_JOB) or q["kind"] == "private"  # private: what this one form says
    scope = "job" if private or job_only else scope or _scope_default(q)
    if q["kind"] == "salary":  # the figure you state on forms, never the private floor
        from .profile import employer_safe

        try:
            employer_safe(f"{q['text']}: {text}", any_line=True)
        except SystemExit:
            raise SystemExit("this is your private floor; give the figure you want to state on forms") from None
    c = db.con()
    waiters = [(w["job_id"], w["stage"]) for w in c.execute("SELECT job_id, stage FROM question_waiters WHERE qid=? ORDER BY rowid",
                                                            (qid,)).fetchall()]
    jid = job_id or q["job_id"] or (waiters[0][0] if waiters else None)
    stage = (_load(q["context"], {}) or {}).get("stage") or "?"
    if target != "bank":
        _apply_target(target, jid, text)
    answer_id, now = None, db._now()
    if scope == "reusable":
        if target == "bank":
            key = q["key"]
            answer_id = db.save_answer(key if _canon(key) else q["text"], text,
                                       q["kind"] if q["kind"] in ("eeo", "eligibility", "salary") else "", private=False,
                                       source=f"answered for job #{jid} ({stage})")
        c.execute("UPDATE questions SET status='answered', answer=?, scope='reusable', answer_id=?, answered_at=? WHERE id=?",
                  (text, answer_id, now, qid))
        resumed = waiters
    else:
        others = [w for w in waiters if w[0] != jid]
        if others:  # the question stays open for the other jobs; this job keeps its own answered row
            c.execute("INSERT INTO questions(key, text, kind, options, context, blocking, apply_to, job_id, status, answer, scope, "
                      "answered_at) VALUES(?,?,?,?,?,?,?,?,'answered',?,'job',?)",
                      (q["key"], q["text"], q["kind"], q["options"], q["context"], q["blocking"], target, jid, text, now))
            c.execute("DELETE FROM question_waiters WHERE qid=? AND job_id=?", (qid, jid))
            c.execute("UPDATE questions SET job_id=? WHERE id=?", (others[0][0], qid))
        else:
            c.execute("UPDATE questions SET status='answered', answer=?, scope='job', job_id=?, answered_at=? WHERE id=?",
                      (text, jid, now, qid))
        resumed = [w for w in waiters if w[0] == jid]
    c.commit()
    return {"resumed": _resume_waiters(resumed), "answer_id": answer_id}


def dismiss(qid: int) -> dict:
    """'I'll fill it in myself': the waiting stages go on without it (the answers stage writes '(left for you)')."""
    _question(qid)
    db.con().execute("UPDATE questions SET status='dismissed', answered_at=? WHERE id=?", (db._now(), qid))
    db.con().commit()
    pairs = [(w["job_id"], w["stage"]) for w in db.con().execute("SELECT job_id, stage FROM question_waiters WHERE qid=?", (qid,))]
    return {"resumed": _resume_waiters(pairs)}


def questions(all: bool = False, job: int | None = None, limit: int = 100) -> list[dict]:
    """Open questions (all: answered and dismissed too), blocking first, each with the jobs waiting on it and near
    matches from the bank."""
    q, args = "SELECT * FROM questions WHERE 1=1", []
    if not all:
        q += " AND status='open'"
    if job is not None:
        q += " AND (job_id=? OR id IN (SELECT qid FROM question_waiters WHERE job_id=?))"
        args += [job, job]
    out = []
    for r in db.con().execute(q + " ORDER BY status='open' DESC, blocking DESC, id LIMIT ?", (*args, limit)).fetchall():
        jobs = [dict(w) for w in db.con().execute(
            "SELECT DISTINCT w.job_id, w.stage, j.company, j.title FROM question_waiters w JOIN jobs j ON j.id=w.job_id "
            "WHERE w.qid=?", (r["id"],)).fetchall()]
        d = dict(r) | {"options": _load(r["options"], None), "context": _load(r["context"], {}), "jobs": jobs,
                       "waiting": len({j["job_id"] for j in jobs})}
        d["suggestions"] = suggestions(r["text"]) if r["status"] == "open" and r["apply_to"] == "bank" else []
        d["scope_default"] = _scope_default(r)
        out.append(d)
    return out


def add_form_questions(job_id: int, labels, source: str = "user") -> int:
    """Form questions for a job (drawer paste, CLI; passes 19 and 21 call this too): merged by canonical key, at most
    100, each up to 300 characters. New labels make a done answers step ready again. Returns how many were new."""
    db.get_job(job_id)
    c = _begin()
    try:
        row = c.execute("SELECT state, output FROM pipeline WHERE job_id=? AND stage='answers'", (job_id,)).fetchone()
        out = _load(row["output"] if row else None, {})
        before = out.get("form") or []
        out["form"] = _merge_labels(before, [x for x in labels or [] if str(x).strip()])
        n = len(out["form"]) - len(before)
        if row:
            c.execute("UPDATE pipeline SET output=? WHERE job_id=? AND stage='answers'", (json.dumps(out), job_id))
        elif n:
            c.execute("INSERT INTO pipeline(job_id, stage, state, output, origin, updated_at) VALUES(?, 'answers', 'waiting', ?, ?, ?)",
                      (job_id, json.dumps(out), "user", _now()))
        c.commit()
    except BaseException:
        c.rollback()
        raise
    log.get("pipeline").info("#%s %d form question(s) added (%s)", job_id, n, source)
    return n


# ----------------------------------------------------------------------------- Autopilot (the monitor loop step)
def _next_action(entries: list[dict]):
    """('run' | 'propose', entry) for the first stage Autopilot may take, in order, or None. Steps that are not
    Autopilot's (manual, loop-driven, tool off) and steps still waiting on an earlier one are passed over; a waiting,
    blocked, running or failed Autopilot step stops the job (an auto step's error is retried once, on a later cycle)."""
    for e in entries:
        s = REGISTRY[e["name"]]
        if not (s.tool and s.run) or e["name"] in MANUAL or not settings.enabled(s.tool):
            continue
        if e["state"] in ("done", "skipped", "later", "stale", "todo"):
            continue
        retry = e["state"] == "error" and settings.auto(s.tool) and (e["attempts"] or 0) < 2
        if e["state"] == "ready" or retry:
            return ("run" if settings.auto(s.tool) else "propose"), e
        return None
    return None


def _batch(entries: list[dict], first: str) -> list[str]:
    """The consecutive stages, from `first`, that one Inbox approval covers: enabled, not auto, ready or waiting on a
    stage in the same batch."""
    out = []
    for e in entries[[x["name"] for x in entries].index(first):]:
        s = REGISTRY[e["name"]]
        if e["state"] in ("done", "skipped", "later"):
            continue
        if (e["state"] not in ("ready", "todo") or e["name"] in MANUAL or not (s.tool and s.run)
                or not settings.enabled(s.tool) or settings.auto(s.tool)):
            break
        out.append(e["name"])
    return out


def _propose(job, entries, first: str):
    from . import approvals

    stages = _batch(entries, first)
    to = stages[-1]
    reuse = _reuse(next(e for e in entries if e["name"] == "answers")) if "answers" in stages else []
    if db.con().execute("SELECT 1 FROM pending WHERE job_id=? AND kind='run_to' AND (status='pending' OR (status='rejected' "
                        "AND json_extract(payload, '$.to')=? AND COALESCE(result, '') NOT LIKE 'stale:%'))",
                        (job["id"], to)).fetchone():
        return None  # one at a time, and never again after you said no (a 'stale: the job moved' close does not count)
    n = sum(_estimate(e) for e in entries if e["name"] in stages)
    return approvals.propose(REGISTRY[stages[0]].tool, "run_to",
                             {"job_id": job["id"], "to": to, "stages": stages, "from_status": job["status"], "reuse": reuse},
                             f"run #{job['id']} {job['company']} to {REGISTRY[to].label.lower()} ({' -> '.join(stages)}, "
                             f"about {n} AI call{'s' if n != 1 else ''}"
                             + (f"; fills in {len(reuse)} saved answer{'s' if len(reuse) != 1 else ''}" if reuse else "") + ")",
                             job["id"], force_pending=True)


def _closed_form(label) -> bool:
    return classify(label) in CLOSED_KINDS or _canon(norm_q(label))


def _estimate(e: dict) -> int:
    """AI calls a step will spend: the answers step drafts each open-ended label not answered yet, at most CLICK_BUDGET."""
    if e["name"] != "answers":
        return REGISTRY[e["name"]].ai
    return min(sum(not _closed_form(x) for x in _new_labels(e["output"])), CLICK_BUDGET)


def _reuse(e: dict) -> list[dict]:
    """The saved answers the answers step would fill closed-form labels with (eligibility, EEO, salary...), as ask()
    finds them, for the approval to show: [{label, answer, source}]. Read only: nothing is asked here."""
    out = []
    for label in _new_labels(e["output"]):
        if _closed_form(label) and (hit := _answered(norm_q(label)) or known(label)):
            out.append({"label": label[:150], "answer": str(hit["answer"])[:300], "source": hit["source"]})
    return out[:20]


def _budget_note(msg: str) -> str:
    """The budget stop goes where the Setup card and `pipeline autopilot status` read it."""
    from . import loop

    loop.STATUS["last_error"] = f"{time.strftime('%H:%M')} pipeline: {msg}"
    LAST["note"] = loop.STATUS["last_error"]
    return msg


def spent_today() -> int:
    """AI calls Autopilot and approved runs made in the last 24 hours. ponytail: rolling 24 h, not the calendar day."""
    return db.con().execute("SELECT COALESCE(SUM(ai), 0) n FROM pipeline_runs WHERE origin IN ('autopilot', 'approved') "
                            "AND ts >= datetime('now', '-1 day')").fetchone()["n"]


def _drop_moot(states: dict) -> None:
    """A question a stage no longer waits for (the job was applied by hand, or closed) loses its waiter; a question no
    job waits for is dismissed as no longer needed."""
    c = db.con()
    c.execute("DELETE FROM question_waiters WHERE job_id NOT IN (SELECT id FROM jobs)")  # deleted while its step ran
    for jid, entries in states.items():
        st = {e["name"]: e["state"] for e in entries}
        for w in c.execute("SELECT w.qid, w.stage FROM question_waiters w JOIN questions q ON q.id=w.qid WHERE w.job_id=? "
                           "AND q.status='open' AND q.blocking=1", (jid,)).fetchall():
            if st.get(w["stage"]) in ("done", "later", "skipped"):
                c.execute("DELETE FROM question_waiters WHERE qid=? AND job_id=?", (w["qid"], jid))
    c.execute(f"DELETE FROM question_waiters WHERE job_id IN (SELECT id FROM jobs WHERE status IN ({','.join('?' * len(CLOSED))})) "
              "AND qid IN (SELECT id FROM questions WHERE status='open')", CLOSED)
    c.execute("UPDATE questions SET status='dismissed', answer='no longer needed', answered_at=? WHERE status='open' AND NOT "
              "EXISTS (SELECT 1 FROM question_waiters w WHERE w.qid=questions.id)", (db._now(),))
    c.commit()


LAST = {"at": None, "ran": 0, "proposed": 0, "note": ""}  # the last advance(), for `pipeline autopilot status`


def advance(provider: str | None = None, now=None) -> dict:
    """The loop step. Always: refresh every live job's states (adopts manual work, writes the board summary, drops moot
    questions). With Autopilot on: for up to autopilot_jobs_per_cycle jobs, run auto steps inside both AI budgets and
    propose one Inbox run_to per job for the steps that are not on auto. Fit-gated jobs are left alone."""
    shared = _shared_roots()
    # ponytail: refreshes every live job each cycle (file reads, no AI); limit to recently changed jobs past a few hundred
    live = [j for j in db.list_jobs() if j["status"] not in CLOSED]
    states = {}
    for j in live:
        try:
            states[j["id"]] = status(j["id"], True, shared)
        except (Exception, SystemExit) as x:
            db.release(close=False)
            log.get("pipeline").warning("#%s status failed: %s", j["id"], x)
    _drop_moot(states)
    res: dict = {"refreshed": len(states), "ran": [], "proposed": [], "budget": False}
    LAST.update(at=time.strftime("%Y-%m-%d %H:%M"), ran=0, proposed=0, note="")
    if not settings.pref("autopilot"):
        LAST["note"] = "Autopilot is off"
        return res
    per_cycle, per_day = int(settings.pref("autopilot_ai_per_cycle")), int(settings.pref("autopilot_ai_per_day"))
    day, cycle = spent_today(), 0
    cands = [j for j in live if j["id"] in states and not fit_skip(states[j["id"]]) and _next_action(states[j["id"]])]
    cands.sort(key=lambda j: (j["deadline"] is None, j["deadline"] or "", -(j["excitement"] or 0), j["updated_at"]))
    for j in cands[:int(settings.pref("autopilot_jobs_per_cycle"))]:
        try:
            for _ in range(len(REGISTRY)):
                entries = status(j["id"], True, shared)
                act = _next_action(entries)
                if not act:
                    break
                kind, e = act
                if kind == "propose":
                    if p := _propose(j, entries, e["name"]):
                        res["proposed"].append(p)
                        status(j["id"], True, shared)  # the board reads 'waiting on you' now, not next cycle
                    break
                left = min(per_cycle - cycle, per_day - day)
                if REGISTRY[e["name"]].ai > left:
                    _budget_note(f"per-cycle AI budget reached ({cycle}/{per_cycle} this cycle; {day}/{per_day} today)"
                                 if per_cycle - cycle < per_day - day else f"daily AI budget reached ({day}/{per_day} in 24 h)")
                    res["budget"] = True
                    LAST.update(ran=len(res["ran"]), proposed=len(res["proposed"]))
                    return res
                r = run(j["id"], e["name"], "autopilot", provider, budget=left)
                cycle, day = cycle + r["ai"], day + r["ai"]
                res["ran"].append(r)
                if r["outcome"] != "done":
                    break
        except (Exception, SystemExit) as x:  # one job never stops the others
            db.release(close=False)
            log.get("pipeline").warning("#%s autopilot failed: %s", j["id"], x)
    LAST.update(ran=len(res["ran"]), proposed=len(res["proposed"]))
    return res
