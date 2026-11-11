"""Apply agent (pass 22, docs/APPLY_AGENT.md): fills a job's application form in Lodestar's own browser window and,
depending on the mode, stops before Submit (stop, the default), waits for your approval in the Inbox (review) or
submits within every auto gate (auto). The pipeline's Apply step runs it (_agent_apply).

The rules that hold everywhere:
- LinkedIn, Indeed, Glassdoor, ZipRecruiter and SimplyHired forbid bots: never loaded, in any page, ever (forbidden).
- A run may load only its exact hosts (the apply link's, its ATS siblings, and hosts you allowed with Continue here).
- The page is untrusted data: every safety rule runs here on the label text (build_plan), never on the page's verdict.
- Values come from you (profile, saved answers, questions you answered); a missing one is a pipeline question
  (pipeline.ask), never a guess. Eligibility / EEO only from your own answers; the salary floor never.
- Nothing is submitted without the mode's approval; a run that clicked Submit and lost track is 'unknown', never retried.
- CAPTCHAs, sign-in pages and codes are handed to you; nothing hides that the window is automated.
"""
import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import apply_ats, db, log, pipeline, settings
from .config import HOME

MODES = ("stop", "review", "auto")
LIVE = db.LIVE_RUN
DONE = ("confirmed", "by_user", "stopped", "failed", "unknown")
STOP = HOME / "apply-agent.stop"  # touched by stop() in any process; cleared by the next enqueue
PROFILE_DIR = HOME / "browser-profile"  # sign-ins (cookies) live here: never backed up or exported
KEYSTORE_ARGS = [] if sys.platform.startswith("win") else ["--password-store=basic", "--use-mock-keychain"]  # = Playwright's
FORBIDDEN_RE = re.compile(r"(?:^|\.)(?:(linkedin|indeed|glassdoor|ziprecruiter|simplyhired)\.[a-z.]{2,12}|(lnkd)\.in)$")
SITES = {"linkedin": "LinkedIn", "lnkd": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor",
         "ziprecruiter": "ZipRecruiter", "simplyhired": "SimplyHired"}
# ponytail: constants, prefs when someone hits them
MAX_PAGES, MAX_OPEN, AUTO_AFTER = 12, 3, 2
RUN_S, NEEDS_S, REVIEW_S, WATCH_S, SUBMIT_S, DEAD_S, BEAT_S = 1200, 1800, 7200, 7200, 60, 60, 2
POLL_MS = 1000

_EVENT = threading.Event()  # stop() in this process
_OWNED: set[int] = set()  # runs this process's worker holds (the heartbeat thread beats these)
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_LOGIN: subprocess.Popen | None = None  # the plain sign-in window this process opened


class _End(Exception):
    """A run ends: state + message (stopped, failed, unknown, ...)."""

    def __init__(self, state: str, msg: str = ""):
        super().__init__(msg)
        self.state, self.msg = state, msg


# ----------------------------------------------------------------------------- policy
def forbidden(url_or_host) -> str | None:
    """The site name when the host belongs to a job board whose terms forbid bots (LinkedIn, Indeed, Glassdoor,
    ZipRecruiter, SimplyHired; their regional and country domains, lnkd.in). Over-blocks lookalikes, on purpose."""
    s = str(url_or_host or "")
    h = apply_ats.host(s) if "://" in s else s.lower().rstrip(".")
    m = FORBIDDEN_RE.search(h)
    return SITES[m.group(1) or m.group(2)] if m else None


def _forbidden_msg(site: str) -> str:
    return (f"This job is on {site}, which does not allow bots. Open it in your own browser; if it has 'Apply on company "
            f"website', paste that link into Application link. Easy Apply-only jobs: apply on {site} yourself.")


def available() -> str | None:
    """None when the agent can run here, else what is missing."""
    import importlib.util

    from .resume import _browser

    if importlib.util.find_spec("playwright") is None:
        return "the apply agent needs Playwright: pip install -e .[apply] (no 'playwright install' needed)"
    if not (apply_ats.EXT / "matcher.js").is_file() or not (apply_ats.EXT / "content.js").is_file():
        return "the apply agent needs the source install (the extension/ folder is missing)"
    if not _browser():
        return "no Edge or Chrome found (set LODESTAR_BROWSER to a Chromium browser)"
    return None


def resolve_url(job) -> tuple[str, str]:
    """(url, how) the agent opens for a job: your Application link, else the posting link when it is on a known
    application system. A forbidden site, or any other site without your link, is refused with what to do."""
    apply_url = job["apply_url"] if "apply_url" in job.keys() else None
    if apply_url:
        if site := forbidden(apply_url):
            raise SystemExit(_forbidden_msg(site))
        return apply_url, "your application link"
    if site := forbidden(job["url"] or ""):
        raise SystemExit(_forbidden_msg(site))
    if job["url"] and apply_ats.ats_of(apply_ats.host(job["url"])) and job["url"].lower().startswith(("http://", "https://")):
        return job["url"], "the posting link"
    raise SystemExit(f"#{job['id']}: paste the employer's application link into Application link (jobs set {job['id']} "
                     "apply_url=...): Lodestar opens other sites only from a link you give it")


def _today_auto() -> int:
    return db.con().execute("SELECT COUNT(*) FROM apply_runs WHERE submitted_by='auto' AND state='confirmed' AND "
                            "date(submitted_at, 'localtime') = date('now', 'localtime')").fetchone()[0]


def auto_blockers(job, ats: str | None) -> list[str]:
    """Why auto may not submit this job (empty: every gate passed)."""
    out = []
    if not settings.auto("apply_agent"):
        out.append("the apply_agent tool is not on auto (Tools)")
    allowed = [x.strip() for x in str(settings.pref("apply_agent_auto_ats") or "").split(",") if x.strip()]
    if not ats or ats not in allowed:
        out.append(f"{ats or 'this site'} is not on your list for auto (Setup > Apply agent)")
    fit, need = job["fit_score"], int(settings.pref("apply_agent_min_fit"))
    if fit is None or fit < need:
        out.append(f"fit {fit if fit is not None else 'not scored'} is under {need}")
    if _today_auto() >= int(settings.pref("apply_agent_daily_cap")):
        out.append("today's automatic submissions reached the daily cap")
    n = db.con().execute("SELECT COUNT(*) FROM apply_runs WHERE ats=? AND state='confirmed' AND submitted_by='approved'",
                         (ats or "",)).fetchone()[0]
    if n < AUTO_AFTER:
        out.append(f"auto starts after {AUTO_AFTER} applications you approved went through on {ats or 'this site'} ({n} so far)")
    return out


def effective_mode(job, ats: str | None, requested: str | None = None) -> tuple[str, list[str]]:
    """(mode, why it is not the one asked for)."""
    mode = requested or settings.pref("apply_agent_mode")
    if mode not in MODES:
        raise SystemExit(f"mode is one of: {', '.join(MODES)}")
    if mode != "stop" and not ats:
        return "stop", ["this link is not on a known application system: stop mode only (you press Submit)"]
    if mode != "stop" and not settings.enabled("apply_agent"):
        return "stop", ["the apply_agent tool is off (Tools): stop mode (you press Submit)"]
    if mode == "auto" and (why := auto_blockers(job, ats)):
        return "review", why
    return mode, []


def already_submitted(job_id: int, but: int | None = None) -> str | None:
    """Why the agent must not submit (again) for this job, or None. Checked when queueing and right before the click."""
    job = db.get_job(job_id)
    if job["status"] != "saved":
        return f"#{job_id} is {job['status']}: the agent only applies to saved jobs"
    r = db.con().execute("SELECT id, state FROM apply_runs WHERE job_id=? AND state IN ('confirmed','by_user','unknown') "
                         "AND id IS NOT ? ORDER BY id DESC", (job_id, but)).fetchone()
    if r:
        return (f"run #{r['id']} clicked Submit and lost track: check your mail or the employer's portal; Lodestar will not "
                "submit again" if r["state"] == "unknown" else f"run #{r['id']} already submitted this application")
    m = db.con().execute("SELECT from_addr, trusted, COALESCE(sent_at, created_at) at FROM mail WHERE job_id=? AND "
                         "direction='in' AND category='application_received' ORDER BY id LIMIT 1", (job_id,)).fetchone()
    if m:  # untrusted mail counts too: refusing is the safe direction (a forged mail can only delay an application)
        return (f"a confirmation email arrived on {str(m['at'])[:10]} from {m['from_addr']}"
                + ("" if m["trusted"] else " (unverified sender)"))
    return None


def _cutoff(seconds: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def alive(run) -> bool:
    """The process that owns this run is alive (its heartbeat is fresh)."""
    return run["id"] in _OWNED or bool(run["heartbeat"] and run["heartbeat"] >= _cutoff(DEAD_S))


# ----------------------------------------------------------------------------- queue and control
def enqueue(job_ids, mode: str | None = None, eeo: bool | None = None, start: bool = True) -> list[dict]:
    """Queue runs: [{job_id, run_id, mode, reasons}] or [{job_id, error}] per job (refused jobs queue nothing)."""
    from .config import full_ai_check

    full_ai_check("submits applications")
    STOP.unlink(missing_ok=True)  # a stop from yesterday must not stop today's first run
    _EVENT.clear()
    if eeo is None:
        eeo = bool(settings.pref("apply_agent_eeo"))
    out = []
    for jid in job_ids:
        try:
            jid = int(jid)
            job = db.get_job(jid)
            if why := already_submitted(jid):
                raise SystemExit(why)
            url, how = resolve_url(job)
            ats = apply_ats.ats_of(apply_ats.host(url))
            m, reasons = effective_mode(job, ats, mode)
            rid = db.add_run(jid, m, eeo)
            db.update_run(rid, url=url, ats=ats or "generic", hosts=apply_ats.hosts_for(url), reasons=reasons,
                          step=f"queued ({how})")
            out.append({"job_id": jid, "run_id": rid, "mode": m, "reasons": reasons})
        except (SystemExit, ValueError) as e:
            db.release(close=False)
            out.append({"job_id": jid, "error": str(e)})
    if start and any("run_id" in r for r in out):
        _ensure_worker()
    return out


def _ensure_worker() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_loop, daemon=True, name="lodestar-apply")
        _WORKER.start()


def stop() -> dict:
    """Stop the agent everywhere: live runs end 'stopped' (a submitted one 'unknown'), their tabs stay open for you
    while Lodestar runs, open submit_application items are rejected. Works across processes (the stop file)."""
    STOP.touch()
    _EVENT.set()
    n = db.con().execute("UPDATE apply_runs SET state='stopped', error='stopped by you', step='stopped by you', updated_at=? "
                         "WHERE state='queued'", (db._now(),)).rowcount
    db.con().commit()
    return {"stopped": True, "queued_stopped": n}


def _stopping() -> bool:
    return _EVENT.is_set() or STOP.exists()


def continue_run(rid: int) -> dict:
    """Continue after a handoff (you signed in, typed a code, picked a widget) or allow the host the page wanted to open."""
    run = db.get_run(int(rid))
    if run["state"] != "needs_you":
        raise SystemExit(f"run #{rid} is {run['state']}: nothing to continue")
    db.update_run(run["id"], answers=run["answers"] | {"_continue": True})
    return {"run_id": run["id"], "continue": True}


def _reject(run, why: str) -> None:
    from . import approvals

    if run.get("pending_id"):
        try:
            approvals.reject(run["pending_id"], why)
        except (Exception, SystemExit):
            db.release(close=False)


def _end(rid: int, state: str, msg: str = "") -> None:
    run = db.get_run(rid)
    if run["state"] not in LIVE:
        return
    if state == "stopped" and (run["submit_clicks"] or run["state"] in ("approved", "submitting")):
        state = "unknown"  # Submit was (maybe) clicked: never retried
        msg = (msg + "; " if msg else "") + "check your mail or the employer's portal; Lodestar will not submit again"
    db.update_run(rid, state=state, error=msg[:500] or None, step=msg[:200] or state)
    _reject(run, f"stale: the apply agent run #{rid} ended ({state})")
    log.get("apply").info("run #%s %s: %s", rid, state, msg)


def recover() -> int:
    """Live runs whose owner died (heartbeat older than DEAD_S): 'unknown' once Submit may have been clicked, else
    'stopped'; their Inbox items are rejected. Queued runs wait for the next worker. One UPDATE per dead run."""
    n = 0
    for r in db.con().execute(f"SELECT id FROM apply_runs WHERE state IN {LIVE} AND state != 'queued' AND "
                              "(heartbeat IS NULL OR heartbeat < ?)", (_cutoff(DEAD_S),)).fetchall():
        if r["id"] in _OWNED:
            continue
        _end(r["id"], "stopped", "Lodestar closed while this run was live")
        n += 1
    return n


def status(brief: bool = False) -> dict:
    recover()
    live = db.live_runs()
    out = {"available": available(), "live": [_public(r) for r in live if r["state"] != "queued"],
           "queue": sum(r["state"] == "queued" for r in live), "profile": PROFILE_DIR.is_dir(),
           "login_open": bool(_LOGIN and _LOGIN.poll() is None)}
    if not brief:
        out["recent"] = [_public(db.get_run(r["id"])) for r in db.con().execute(
            f"SELECT id FROM apply_runs WHERE state NOT IN {LIVE} ORDER BY id DESC LIMIT 10")]
    return out


def _public(run) -> dict:
    """A run for the page / CLI: no file paths beyond the evidence folder name, needs and plan labels as data."""
    job = db.con().execute("SELECT company, title FROM jobs WHERE id=?", (run["job_id"],)).fetchone()
    return {k: run[k] for k in ("id", "job_id", "mode", "state", "ats", "url", "step", "needs", "reasons", "submit_clicks",
                                "submitted_by", "submitted_at", "confirmation", "error", "pending_id", "updated_at")} | {
        "company": job["company"] if job else "", "title": job["title"] if job else "",
        "evidence": Path(run["evidence"]).name if run["evidence"] else ""}


# ----------------------------------------------------------------------------- sign-in window, forget
def login_window(url: str | None = None) -> dict:
    """A plain browser window on the agent's profile (no automation flags): you sign in to a site there once, by hand,
    and the agent's window reuses the session. Refused while a run is live (one browser per profile)."""
    global _LOGIN
    from .resume import _browser
    from .web import http_only

    if any(alive(r) for r in db.live_runs() if r["state"] != "queued"):
        raise SystemExit("the apply agent is running: stop it (or let it finish) before opening the sign-in window")
    if _LOGIN and _LOGIN.poll() is None:
        raise SystemExit("the sign-in window is already open")
    u = http_only(url) if url else None
    if url and not u:
        raise SystemExit("the sign-in page must be an http(s) link")
    if u and (site := forbidden(u)):
        raise SystemExit(f"{site} is never opened on the agent's profile")
    binary = _browser()
    if not binary:
        raise SystemExit("no Edge or Chrome found (set LODESTAR_BROWSER)")
    PROFILE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    _LOGIN = subprocess.Popen([binary, f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check",
                               "--disable-sync", *KEYSTORE_ARGS, u or "about:blank"])
    return {"opened": True, "url": u or "about:blank"}


def forget_logins() -> dict:
    """Delete the agent's browser profile (every site sign-in it holds). Refused while a run or the sign-in window is
    live; reports what could not be removed (a browser process still holding files) instead of hiding it."""
    if any(alive(r) for r in db.live_runs() if r["state"] != "queued") or (_LOGIN and _LOGIN.poll() is None):
        raise SystemExit("close the sign-in window and stop the apply agent first")
    if not PROFILE_DIR.exists():
        return {"removed": False, "left": []}
    left = []
    shutil.rmtree(PROFILE_DIR, onexc=lambda fn, path, exc: left.append(str(Path(path).relative_to(PROFILE_DIR))))
    if left:
        raise SystemExit(f"a browser process still uses the agent profile ({len(left)} files left, e.g. {left[0]}): close "
                         "Edge windows on it and try again")
    return {"removed": True, "left": []}


# ----------------------------------------------------------------------------- the field plan (pure, no browser)
DENY_RE = re.compile(r"ssn|social.?security|national.?id|passport|birth|\bdob\b|driver.?s?.?licen[cs]e|tax.?id|iban|"
                     r"routing|bank|card.?number|cvv|password", re.I)  # = extension/matcher.js DENY, on the label here
CONSENT_RE = re.compile(r"\b(?:agree|consent|acknowledge|certify|terms|privacy)", re.I)
# always asked per job (never reused from the bank or guessed), on top of pipeline.classify's eligibility class
ALWAYS_ASK_RE = re.compile(r"criminal|convicted|felony|background check|drug (?:test|screen)|non-?compete|security "
                           r"clearance|disabilit(?:y|ies) .*(?:accommodat|perform)|commute|on-?site|in (?:the )?office|"
                           r"hybrid .* days|(?:previously|ever) (?:been )?employed by|worked (?:for|at) .* before", re.I)
DECLINE_RE = re.compile(r"decline|prefer not|don.?t wish|do not wish|not to (?:say|answer|disclose)|rather not", re.I)
RESUME_RE = re.compile(r"resume|r[ée]sum[ée]|\bcv\b", re.I)
COVER_RE = re.compile(r"cover", re.I)
CONTACT = {"first": "first_name", "last": "last_name", "name": "name", "email": "email", "phone": "phone",
           "location": "location", "linkedin": "linkedin", "github": "github", "website": "website",
           "current_company": "current_company", "current_title": "current_title"}
EEO_KEYS = {"EEO: gender": "gender", "EEO: sex": "sex", "EEO: race": "race", "EEO: hispanic or latino": "hispanic",
            "EEO: veteran status": "veteran", "EEO: disability status": "disability"}


def _norm(v) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).split())


def pick_option(options, value) -> str | None:
    """extension/matcher.js pickOption in Python: the option value for a stored answer, or None (no confident pick)."""
    v = _norm(value)
    opts = [o for o in options or [] if _norm(o.get("t")) and str(o.get("v", "")) != ""]
    if not v or not opts:
        return None
    for test in (lambda o: _norm(o["t"]) == v or _norm(o["v"]) == v, lambda o: _norm(o["t"]).startswith(v),
                 lambda o: re.match(rf"{re.escape(_norm(o['t']))}\b", v), lambda o: v in _norm(o["t"])):
        if hit := next((o for o in opts if test(o)), None):
            return str(hit["v"])
    if DECLINE_RE.search(str(value)) and (hit := next((o for o in opts if DECLINE_RE.search(o["t"])), None)):
        return str(hit["v"])
    return None


def _kind(d) -> str:
    t = (d.get("type") or "").lower()
    if d.get("tag") == "select":
        return "select"
    if t in ("radio", "checkbox", "file"):
        return {"radio": "radio", "checkbox": "check", "file": "file"}[t]
    return "combo" if d.get("tag") == "widget" else "text"


def _needs(x, flag: str, qid: str = "") -> None:
    x.update(status="needs_you", flag=flag, qid=qid, value="")


def _set(x, d, value, source: str) -> None:
    """A value you gave, written the way this field takes it (an option pick for selects and radios)."""
    if x["kind"] in ("select", "radio"):
        pick = pick_option(d.get("options"), value)
        if pick is None:
            return _needs(x, f"no option matches your answer: {str(value)[:80]}")
        value = pick
    elif x["kind"] == "combo":
        return _needs(x, f"pick it in the window: {str(value)[:80]}")
    elif x["kind"] == "check":
        value = str(value).strip().lower() in ("yes", "true", "1", "y", "x")
    x.update(value=value if x["kind"] == "check" else str(value), source=source, status="fill")


def _ask(x, d, job, kind=None, reuse: bool = True) -> None:
    """A pipeline question for this label (the one questions queue); an answer you already gave is used at once."""
    opts = [o["t"] for o in d.get("options") or [] if o.get("t") and str(o.get("v", "")) != ""] or None
    a, src = pipeline.ask(job, "apply", x["label"] or "(a required field with no label)", kind, opts,
                          why=f"the application form on {apply_ats.host(job['_url'])} asks this", reuse=reuse)
    if a is pipeline.SKIP:
        x.update(status="skip", flag="left for you")
    elif a is None:
        _needs(x, "a question for you (Inbox > Questions)", src)
    else:
        _set(x, d, a, "you" if src == "you" else "bank")


def _file(x, d, job, data, files_dir: Path | None, hay: str) -> None:
    from .profile import RESUMES
    from .resume import app_dir

    kind = "Resume" if RESUME_RE.search(hay) else "Cover_Letter" if COVER_RE.search(hay) else None
    if kind is None:
        return _needs(x, "upload it yourself in the window") if x["required"] else x.update(status="skip")
    d_ = app_dir(job)
    names = ("resume",) if kind == "Resume" else ("cover_letter",)
    found = [d_ / f"{n}{e}" for n in names for e in (".pdf", ".docx")] + (
        [RESUMES / "master.pdf", RESUMES / "master.docx"] if kind == "Resume" else [])
    src = next((p for p in found if p.is_file()), None)
    if not src:
        if kind == "Resume":
            return _needs(x, "tailor a resume or build the master resume first")
        return _needs(x, "no cover letter yet: write one (Cover letter step) or upload it in the window") if x["required"] \
            else x.update(status="skip", flag="optional cover letter left out")
    who = "_".join(re.sub(r"[^A-Za-z0-9-]+", "", p) for p in (data.get("first_name"), data.get("last_name")) if p) or "Applicant"
    out = src
    if files_dir:  # the evidence copy is what gets uploaded; recruiters see its name
        files_dir.mkdir(parents=True, exist_ok=True)
        out = files_dir / f"{who}_{kind}{src.suffix}"
        shutil.copyfile(src, out)
    x.update(value=str(out), source="profile", status="fill", sha256=hashlib.sha256(out.read_bytes()).hexdigest(),
             file=out.name)


def _decide(x, d, job, run, data, files_dir) -> None:
    label = x["label"]
    hay = f"{label} {d.get('name') or ''} {d.get('id') or ''} {d.get('placeholder') or ''}"
    if DENY_RE.search(hay) or (d.get("type") or "").lower() == "password":
        return x.update(status="skip", flag="never filled (identity, money or a password)")
    if x["kind"] == "file":
        return _file(x, d, job, data, files_dir, hay)
    if x["kind"] == "check":
        if CONSENT_RE.search(label):  # stop: you tick it; review: ticked only after you approve that exact text
            return x.update(status="consent", value=True, flag=f"consent: {label[:120]}")
        return _ask(x, d, job) if x["required"] else x.update(status="skip")
    cls, key = pipeline.classify(label), d.get("key") or ""
    canon = pipeline.norm_q(label)
    if cls == "eeo" or canon in EEO_KEYS:
        k = EEO_KEYS.get(canon) or (key[4:] if key.startswith("eeo.") else "")
        if (v := (data.get("eeo") or {}).get(k)) and run["eeo"]:
            return _set(x, d, v, "bank")
        if not x["required"]:
            return x.update(status="skip", flag="EEO left blank (not included)")
        if x["kind"] in ("select", "radio") and (dec := next((o for o in d.get("options") or []
                                                             if DECLINE_RE.search(o.get("t") or "")), None)):
            return x.update(value=dec["v"], source="derived", status="fill",
                            flag="EEO: chose decline (you did not include EEO answers)")
        return _ask(x, d, job, "eeo")
    if cls == "salary" or canon == "Desired salary":
        return _set(x, d, data["salary"], "bank") if data.get("salary") else _ask(x, d, job, "salary")
    if ALWAYS_ASK_RE.search(label):
        return _ask(x, d, job, cls if cls in pipeline.CLOSED_KINDS else None, reuse=False)
    if cls in ("eligibility", "private"):
        return _ask(x, d, job, cls)
    if key in CONTACT or key == "city":
        v = data.get(CONTACT.get(key, "")) or (str(data.get("location") or "").split(",")[0] if key == "city" else "")
        if v and key in ("linkedin", "github", "website") and not re.match(r"https?://", v, re.I):
            v = "https://" + v
        if v:
            return _set(x, d, v, "profile")
    if key.startswith(("exp.", "edu.")) and d.get("group"):
        rows = data.get("experience" if key.startswith("exp.") else "education") or []
        n = int(str(d["group"]).split(":")[-1] or 0)
        if n < len(rows) and (v := rows[n].get(key.split(".", 1)[1])):
            return _set(x, d, v, "profile")
    if label and (hit := pipeline.known(label, employer=True)):
        return _set(x, d, hit["answer"], "bank")
    if not x["required"]:
        return x.update(status="skip", flag="optional, left blank")
    return _ask(x, d, job, cls if cls in pipeline.CLOSED_KINDS else None, reuse=cls in pipeline.CLOSED_KINDS)


def build_plan(job, run, fields, data, files_dir: Path | None = None) -> list[dict]:
    """One item per scanned field: {i, frame, label, key, kind, value, source, status, flag, required, qid}. status is
    fill | needs_you | consent | skip. Every safety rule reads the label here; the page's own key is only a hint for
    which profile value to look up. Every value passes the salary-floor guard (drafts.leaks)."""
    from .drafts import leaks

    job = dict(job) | {"_url": run.get("url") or ""}
    items = []
    for d in fields:
        label = " ".join(str(d.get("label") or d.get("aria") or d.get("placeholder") or "").split())[:300]
        x = {"i": d.get("i"), "frame": d.get("frame", 0), "label": label, "key": d.get("key"), "kind": _kind(d),
             "value": "", "source": "", "status": "skip", "flag": "", "required": bool(d.get("required")), "qid": "",
             "prev": "", "shown": str(d.get("value") or "")}
        _decide(x, d, job, run, data, files_dir)
        if x["status"] == "fill" and x["kind"] not in ("file", "check") and leaks(str(x["value"])):
            _needs(x, "would name your salary floor")
        items.append(x)
    return items


def plan_hash(url: str, items: list[dict]) -> str:
    """What an approval covers: the URL, every item (label, key, read-back value, status) and the files' sha256."""
    body = [url, [(x["label"], x["key"], x.get("shown", ""), x["status"]) for x in items],
            [x.get("sha256", "") for x in items if x["kind"] == "file" and x["status"] == "fill"]]
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


# ----------------------------------------------------------------------------- the worker
def _driver(headless: bool = False):
    return apply_ats.open_browser(PROFILE_DIR, forbidden, headless=headless)


def _beat(done: threading.Event) -> None:
    """The heartbeat (its own thread: the worker blocks for long stretches on pages and AI calls). It means 'the owning
    process and its worker are alive'; a stuck page is caught by the run's own timeouts."""
    try:
        while not done.wait(BEAT_S):
            if ids := list(_OWNED):
                db.con().execute(f"UPDATE apply_runs SET heartbeat=? WHERE id IN ({','.join('?' * len(ids))}) AND state IN "
                                 f"{LIVE}", (db._now(), *ids))
                db.con().commit()
    except (Exception, SystemExit) as e:
        log.get("apply").warning("heartbeat stopped: %s", e)
    finally:
        db.release()


def _claim_next() -> int | None:
    for r in db.con().execute("SELECT id FROM apply_runs WHERE state='queued' ORDER BY id").fetchall():
        if db.claim_run(r["id"], "queued", "running", heartbeat=db._now(), step="opening the application"):
            _OWNED.add(r["id"])
            return r["id"]
    return None


def _loop(new_driver=None, until_idle: bool = False) -> None:
    """The worker: one per process, one browser, at most MAX_OPEN application tabs. Takes queued runs one at a time and
    fills them; watches filled tabs (your Submit click, your approval, a code after Submit) without blocking the queue.
    Ends when nothing is live or queued and no window is left (until_idle: when nothing is live or queued)."""
    tabs: dict = {}
    browser, done = None, threading.Event()
    recover()
    threading.Thread(target=_beat, args=(done,), daemon=True, name="lodestar-apply-beat").start()
    try:
        while True:
            if _stopping():
                for rid in list(_OWNED):
                    _end(rid, "stopped", "stopped by you")
                    tabs.pop(rid, None)
                    _OWNED.discard(rid)
            for rid in list(tabs):
                _guarded(rid, tabs, lambda r=rid: _watch(r, tabs))
            rid = None if _stopping() or len(tabs) >= MAX_OPEN else _claim_next()
            if rid:
                if browser is None:
                    try:
                        browser = (new_driver or _driver)()
                    except apply_ats.ProfileBusy as e:
                        db.claim_run(rid, "running", "queued", step=str(e)[:200])
                        _OWNED.discard(rid)
                        log.get("apply").warning("%s", e)
                        break
                _guarded(rid, tabs, lambda r=rid: _start(r, browser, tabs))
                continue
            queued = db.con().execute("SELECT 1 FROM apply_runs WHERE state='queued'").fetchone()
            if not tabs and (not queued or _stopping()) and (until_idle or browser is None or not browser.pages()):
                break
            if browser is not None:
                browser.idle(POLL_MS)
            else:
                _EVENT.wait(POLL_MS / 1000)
    finally:
        done.set()
        for rid in list(tabs):
            _OWNED.discard(rid)
        if browser is not None:
            browser.close()
        db.release()


def _guarded(rid: int, tabs: dict, step) -> None:
    """One step of one run: an _End or any failure ends that run (never the worker)."""
    try:
        step()
    except _End as e:
        _end(rid, e.state, e.msg)
    except (Exception, SystemExit) as e:  # SystemExit: user-facing problems from helpers (template profile, no key)
        db.release(close=False)
        log.get("apply").warning("run #%s failed: %s", rid, e)
        _end(rid, "failed", str(e) or type(e).__name__)
    run = db.get_run(rid)
    if run["state"] not in LIVE:
        tabs.pop(rid, None)
        _OWNED.discard(rid)


def _start(rid: int, browser, tabs: dict) -> None:
    run = db.get_run(rid)
    if forbidden(run["url"]):  # checked at queue time; again before anything opens
        raise _End("failed", _forbidden_msg(forbidden(run["url"])))
    tab = browser.open(run["url"], run["hosts"])
    tabs[rid] = tab
    _fill(rid, tab)


def _evidence_dir(job, rid: int) -> Path:
    from .resume import app_dir

    d = app_dir(job) / "apply" / f"run-{rid}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check(rid: int, tab, started: float | None = None) -> dict:
    """Between every action: the stop file, the run's own row (another process may have ended it), the job, the window,
    the guard's findings and the run deadline. Returns the fresh run."""
    if _stopping():
        raise _End("stopped", "stopped by you")
    run = db.get_run(rid)
    if run["state"] not in LIVE:
        raise _End(run["state"], run["error"] or "")
    db.get_job(run["job_id"])  # 'no job #N': deleted meanwhile
    if tab.closed:
        raise _End("stopped", "you closed the agent's tab")
    if tab.forbidden_hit:
        raise _End("stopped", f"the page tried to open {tab.forbidden_hit}, which Lodestar never opens; use your own browser")
    if started and time.monotonic() - started > RUN_S:
        raise _End("stopped", f"the form took over {RUN_S // 60} minutes; it is left open for you")
    return run


def _wait(rid: int, tab, needs: list[dict], until, limit: int = NEEDS_S) -> dict:
    """needs_you until until(run) is true: questions answered, Continue pressed, the code page gone. Every 2 s; the
    hosts rule is suspended meanwhile (you drive), the forbidden rule never is."""
    from .util import notify

    run = db.get_run(rid)
    job = db.get_job(run["job_id"])
    db.update_run(rid, state="needs_you", needs=needs, step=needs[0].get("hint", "")[:200] if needs else "")
    tab.suspended = True
    try:
        tab.front()
    except Exception:
        pass
    try:
        notify(f"Lodestar needs you: {needs[0].get('hint', 'a question')[:120] if needs else 'a question'} for "
               f"#{job['id']} {job['company']}")
    except Exception:  # an alert that cannot be written never stops the run
        pass
    t0 = time.monotonic()
    while True:
        run = _check(rid, tab)
        if until(run):
            tab.suspended = False
            db.claim_run(rid, "needs_you", "running", needs=[],
                         answers={k: v for k, v in run["answers"].items() if k != "_continue"})
            return run  # as it was when the wait ended (did you press Continue?)
        if time.monotonic() - t0 > limit:
            raise _End("stopped", f"waited {limit // 60} minutes for you; the tab is left open")
        tab.idle(2000)


def _open_questions(job_id: int) -> set:
    return {f"question #{r['qid']}" for r in db.con().execute(
        "SELECT w.qid FROM question_waiters w JOIN questions q ON q.id=w.qid WHERE w.job_id=? AND w.stage='apply' AND "
        "q.status='open'", (job_id,)).fetchall()}


def _handoff(rid: int, tab, reason: str) -> None:
    hints = {"captcha": "solve the check in the agent window, then press Continue",
             "login": "sign in (or create the account) in the agent window, then press Continue",
             "code": "type the code the site sent you in the agent window, then press Continue"}
    _wait(rid, tab, [{"reason": reason, "hint": hints.get(reason, reason)}],
          lambda run: run["answers"].get("_continue") or (reason == "code" and not tab.blocker()))  # then checked again


def _offsite(rid: int, tab) -> None:
    """The page wanted another host: Continue here allows that exact host for this run (your consent), Stop ends it."""
    h, url = tab.offsite
    tab.offsite = None
    _wait(rid, tab, [{"reason": "offsite", "host": h, "hint": f"the page wants to open {h}: Continue here, or Stop"}],
          lambda run: run["answers"].get("_continue"))
    run = db.get_run(rid)
    hosts = list(dict.fromkeys([*run["hosts"], h]))
    db.update_run(rid, hosts=hosts, answers=run["answers"] | {"_added": [*run["answers"].get("_added", []), h]})
    tab.hosts = hosts
    tab.goto(url)


def _fill(rid: int, tab, n: int = 1, pages: list | None = None) -> None:
    """Page by page (at most MAX_PAGES): handoffs, the plan, writes, read-back, a screenshot, then Next or the final
    page (_final). Your questions pause on the page where they occur. n / pages: refill from the open page on."""
    from .extras import ext_autofill

    started, retried, pages, ack = time.monotonic(), False, pages or [], set()
    while n <= MAX_PAGES:
        run = _check(rid, tab, started)
        job = db.get_job(run["job_id"])
        if tab.offsite:
            _offsite(rid, tab)
            continue
        if reason := tab.blocker():
            _handoff(rid, tab, reason)
            continue
        if tab.already_applied():
            raise _End("failed", "the site says you already applied")
        ev = _evidence_dir(job, rid)
        fields = tab.scan()
        data = ext_autofill([f.get("label") or "" for f in fields], eeo=bool(run["eeo"]), salary=True)
        items = build_plan(job, run, fields, data, ev / "files")
        for x in items:  # window tasks (pick a widget, upload) you said you did with Continue
            if x["status"] == "needs_you" and not x["qid"] and x["label"] in ack:
                x.update(status="skip", flag=x["flag"] + " (done by you in the window)")
        if needs := [x for x in items if x["status"] == "needs_you"]:
            qs, tasks = {x["qid"] for x in needs if x["qid"]}, [x for x in needs if not x["qid"]]
            r = _wait(rid, tab, [{"label": x["label"], "hint": x["flag"], "qid": x["qid"]} for x in needs],
                      lambda r: not (qs & _open_questions(r["job_id"])) and (not tasks or r["answers"].get("_continue")))
            if r["answers"].get("_continue"):
                ack |= {x["label"] for x in tasks}
            continue  # rebuilt with your answers
        for x in items:
            if x["status"] == "fill":
                tab.write(x)
        back = tab.values()
        missed = [x for x in items if x["status"] == "fill" and x["kind"] == "text" and back.get(f"{x['frame']}:{x['i']}") == ""]
        for x in missed:  # a widget swallowed it: once more
            tab.write(x)
        back = tab.values()
        for x in items:
            x["shown"] = back.get(f"{x['frame']}:{x['i']}", x["shown"])
        tab.shot(ev / f"page-{n:02d}.png")
        pages = [p for p in pages if p["page"] != n] + [{"page": n, "url": tab.url, "items": items}]
        db.update_run(rid, plan=pages, step=f"page {n}", evidence=str(ev))
        sub, nxt = tab.button("submit"), tab.button("next")
        if sub and not nxt:
            return _final(rid, tab, pages)
        if not nxt:
            _wait(rid, tab, [{"reason": "next", "hint": "could not find the next step: move the form on in the window, "
                                                         "then press Continue"}], lambda r: r["answers"].get("_continue"))
            continue
        url = tab.url
        tab.click(nxt)
        tab.idle(1500)
        if tab.url == url and (errs := tab.errors()) and not tab.button("submit"):
            if not retried:
                retried = True  # a dropped value: this page once more
                continue
            _wait(rid, tab, [{"reason": "errors", "hint": f"the form says: {'; '.join(errs)[:300]}: fix it in the window, "
                                                           "then press Continue"}], lambda r: r["answers"].get("_continue"))
            run = db.get_run(rid)
            db.update_run(rid, answers=run["answers"] | {"_retried": True})
            continue
        n, retried, ack = n + 1, False, set()
    raise _End("stopped", f"more than {MAX_PAGES} pages: left open for you")


def _all_items(run) -> list[dict]:
    return [x for p in run["plan"] or [] for x in p["items"]]


def _page_blockers(run) -> list[str]:
    """At the final page, what sends an auto run to review: anything uncertain, and any value the AI wrote."""
    items, out = _all_items(run), []
    if any(x["status"] == "needs_you" or x["flag"] and x["status"] == "fill" for x in items):
        out.append("a field carries a flag")
    if any(x["status"] == "consent" for x in items):
        out.append("a consent box to tick")
    if any(x["source"] == "ai" for x in items):
        out.append("a value the AI wrote")
    if run["answers"].get("_added"):
        out.append("you allowed another host on the way")
    if run["answers"].get("_retried"):
        out.append("the form showed errors")
    return out


def _final(rid: int, tab, pages) -> None:
    run = db.get_run(rid)
    mode = run["mode"]
    if mode == "auto" and (why := _page_blockers(run)):
        mode = "review"
        db.update_run(rid, mode=mode, reasons=[*run["reasons"], *why])
    if mode == "stop":
        db.update_run(rid, state="ready", step="filled: check the window and press Submit yourself")
        _summary(rid)
        return
    _propose(rid)


def _propose(rid: int) -> None:
    from . import approvals

    run = db.get_run(rid)
    job = db.get_job(run["job_id"])
    items = _all_items(run)
    h = plan_hash(run["url"], items)
    db.update_run(rid, state="awaiting_approval", plan_hash=h, step="waiting for your approval in the Inbox")
    shown = [x for x in items if x["status"] in ("fill", "consent")]
    payload = {"run_id": rid, "job_id": job["id"], "plan_hash": h, "ats": run["ats"], "host": apply_ats.host(run["url"]),
               "url": run["url"], "shots": sorted(p.name for p in Path(run["evidence"]).glob("page-*.png")),
               "fields": [{"label": x["label"], "value": "(tick)" if x["status"] == "consent" else
                           x.get("file") or x.get("shown") or str(x["value"]), "source": x["source"], "flag": x["flag"]}
                          for x in shown],
               "files": [{"label": x["label"], "name": x.get("file", "")} for x in shown if x["kind"] == "file"],
               "warnings": [x["flag"] for x in items if x["flag"] and x["status"] in ("fill", "consent")]}
    k = sum(x["source"] == "ai" for x in shown)
    summary = (f"submit application: #{job['id']} {job['company']} - {job['title']} on {payload['host']} "
               f"({len(shown)} fields, {k} written by AI)")
    _summary(rid)
    r = approvals.propose("apply_agent", "submit_application", payload, summary, job["id"], force_pending=run["mode"] == "review")
    if r.get("id"):
        db.update_run(rid, pending_id=r["id"])
    if r["status"] == "disabled":
        db.update_run(rid, state="ready", mode="stop", step="the apply_agent tool is off: press Submit yourself")
    elif r["status"] not in ("pending", "done"):
        raise _End("stopped", f"the Inbox refused it: {r.get('result') or r['status']}")


def _watch(rid: int, tabs: dict) -> None:
    """One look at a filled run, without blocking the queue."""
    tab = tabs[rid]
    run = db.get_run(rid)
    if run["state"] not in LIVE:
        return
    if _stopping():
        raise _End("stopped", "stopped by you")
    if tab.closed:
        raise _End("stopped", "you closed the agent's tab")
    age = time.time() - datetime.strptime(run["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    if run["state"] == "ready" or (run["state"] == "needs_you" and run["submit_clicks"]):
        if text := tab.confirmed():
            return _confirmed(rid, tab, text)
        if age > WATCH_S:
            raise _End("stopped", "no confirmation page within 2 hours; the tab is left open")
    elif run["state"] == "awaiting_approval":
        item = db.get_pending(run["pending_id"]) if run["pending_id"] else None
        if run["answers"].get("_refill"):
            _reject(run, "stale: superseded by your edits")
            db.update_run(rid, state="running", pending_id=None, answers={k: v for k, v in run["answers"].items() if k != "_refill"})
            return _fill(rid, tab, len(run["plan"]) or 1, run["plan"][:-1])
        if item and item["status"] in ("rejected", "error"):
            raise _End("stopped", f"not approved: {item['result'] or item['status']}")
        if age > REVIEW_S:
            raise _End("stopped", "expired: the form was open 2 hours without an approval")
    elif run["state"] == "approved":
        _submit(rid, tab)


def _submit(rid: int, tab) -> None:
    """The one Submit click of an approved run."""
    if not db.claim_run(rid, "approved", "submitting", step="submitting"):
        return
    run = db.get_run(rid)
    last = run["plan"][-1]["items"] if run["plan"] else []
    tab.scan()  # re-tag the page's fields (the final page is the open one)
    back = tab.values()
    if any(x["status"] == "fill" and back.get(f"{x['frame']}:{x['i']}", x.get("shown")) != x.get("shown") for x in last):
        for x in last:  # what the window shows now is what the new proposal (and its screenshot) covers
            x["shown"] = back.get(f"{x['frame']}:{x['i']}", x.get("shown"))
        tab.shot(Path(run["evidence"]) / f"page-{run['plan'][-1]['page']:02d}.png")
        db.update_run(rid, state="running", plan=run["plan"], step="the form changed in the window: proposed again")
        _reject(run, "stale: the form changed in the window since you approved it")
        return _propose(rid)
    if why := already_submitted(run["job_id"], but=rid):
        raise _End("failed", why)
    for x in last:
        if x["status"] == "consent":  # your approval covered this exact text
            tab.write(x | {"kind": "check", "value": True})
    b = tab.button("submit")
    if not b:
        raise _End("stopped", "the Submit button is gone: nothing was sent")
    db.update_run(rid, submit_clicks=1, submitted_at=db._now())
    tab.accept_confirm = True
    tab.click(b)
    t0 = time.monotonic()
    while time.monotonic() - t0 < SUBMIT_S:
        tab.idle(1000)
        if text := tab.confirmed():
            tab.accept_confirm = False
            return _confirmed(rid, tab, text)
        if (reason := tab.blocker()) or tab.errors():
            tab.accept_confirm = False
            db.update_run(rid, state="needs_you", needs=[{"reason": reason or "errors", "hint": (
                "type the code in the window" if reason == "code" else "finish it in the agent window and press Submit "
                "there yourself")}], step="after Submit: the site needs you")
            return
    tab.accept_confirm = False
    raise _End("unknown", "no confirmation page after Submit")


def _confirmed(rid: int, tab, text: str) -> None:
    from . import approvals

    run = db.get_run(rid)
    ev = Path(run["evidence"] or _evidence_dir(db.get_job(run["job_id"]), rid))
    try:
        tab.shot(ev / "confirmation.png")
    except Exception:
        pass
    (ev / "confirmation.txt").write_text(text[:4000], encoding="utf-8")
    m = apply_ats.REF_RE.search(text)
    by = run["submitted_by"] or ("user" if run["mode"] == "stop" or not run["submit_clicks"] else "approved")
    state = "by_user" if by == "user" else "confirmed"
    db.update_run(rid, state=state, submitted_by=by, submitted_at=run["submitted_at"] or db._now(),
                  confirmation=m.group(1) if m else "", step="confirmation page seen")
    _summary(rid)
    if state == "confirmed":
        approvals.record_submission(rid)


def _summary(rid: int) -> None:
    """plan.json and summary.md in the run's evidence folder (fields with their source; nothing private)."""
    run = db.get_run(rid)
    if not run["evidence"]:
        return
    ev, job = Path(run["evidence"]), db.get_job(run["job_id"])
    items = _all_items(run)
    (ev / "plan.json").write_text(json.dumps(run["plan"], indent=1, default=str), encoding="utf-8")
    who = {"user": "you clicked Submit", "approved": f"you approved Inbox #{run['pending_id']}",
           "auto": "automatic (tool apply_agent on auto)"}.get(run["submitted_by"], "not submitted")
    lines = [f"# Apply agent run #{rid}", "", f"- Job: #{job['id']} {job['company']} - {job['title']}",
             f"- Site: {apply_ats.host(run['url'])} ({run['ats']}) {run['url']}", f"- Mode: {run['mode']}",
             f"- State: {run['state']}", f"- Submitted: {who} {run['submitted_at'] or ''}".rstrip(),
             f"- Confirmation: {run['confirmation'] or '-'}", "", "## Fields", ""]
    lines += [f"- {x['label'] or '(no label)'}: {x.get('file') or x.get('shown') or x['value']} ({x['source'] or x['status']}"
              + (f"; {x['flag']}" if x["flag"] else "") + ")" for x in items if x["status"] in ("fill", "consent")]
    lines += ["", "## Left for you", ""] + [f"- {x['label'] or '(no label)'}: {x['flag'] or x['status']}" for x in items
                                             if x["status"] in ("needs_you", "skip") and x["flag"]]
    (ev / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_foreground(job_ids, mode: str | None = None, eeo: bool | None = None, headless: bool = False) -> list[dict]:
    """The CLI: queue, then work the queue in this thread. Ctrl+C stops (the window closes with Lodestar)."""
    res = enqueue(job_ids, mode, eeo, start=False)
    if any("run_id" in r for r in res):
        try:
            _loop(lambda: _driver(headless))
        except KeyboardInterrupt:
            stop()
            for rid in list(_OWNED):
                _end(rid, "stopped", "stopped (Ctrl+C)")
            _OWNED.clear()
    return [r | ({"state": db.get_run(r["run_id"])["state"]} if "run_id" in r else {}) for r in res]


# ----------------------------------------------------------------------------- the pipeline's Apply step
def _agent_apply(job, ctx):
    """The Apply step's run (a click): queue the agent for this job (or join its live run). The step waits while the
    run is live; it is done when the job moves to applied (_agent_observe)."""
    live = db.con().execute(f"SELECT id FROM apply_runs WHERE job_id=? AND state IN {LIVE}", (job["id"],)).fetchone()
    if live:
        rid = live["id"]
    else:
        r = enqueue([job["id"]])[0]
        if "error" in r:
            raise SystemExit(r["error"])
        rid = r["run_id"]
    ctx.waiting = True
    return {"run_id": rid, "via": "agent", "state": db.get_run(rid)["state"]}


def _agent_observe(job, ctx):
    o = pipeline._apply_observe(job, ctx)
    if o is None:
        return None
    r = db.con().execute("SELECT id, evidence, confirmation, submitted_at FROM apply_runs WHERE job_id=? AND state IN "
                         "('confirmed','by_user') ORDER BY id DESC LIMIT 1", (job["id"],)).fetchone()
    return o | ({"via": "agent", "run_id": r["id"], "evidence_dir": r["evidence"], "confirmation": r["confirmation"],
                 "submitted_at": r["submitted_at"]} if r else {})


def _agent_wait(job, ctx):
    live = db.con().execute(f"SELECT id, state, step FROM apply_runs WHERE job_id=? AND state IN {LIVE}", (job["id"],)).fetchone()
    if live:
        on = "employer" if live["state"] in ("approved", "submitting") else "you"
        return on, f"apply agent run #{live['id']}: {live['state']} ({live['step'] or ''})"[:200]
    if available() is not None:
        return pipeline._apply_wait(job, ctx)
    return None


pipeline.register(dataclasses.replace(pipeline.REGISTRY["apply"], run=_agent_apply, observe=_agent_observe, wait=_agent_wait))
