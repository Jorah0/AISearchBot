"""Local web dashboard: `lodestar ui` -> http://127.0.0.1:8765  (stdlib only, binds localhost only).

Long-running AI actions run in a thread and are polled via /api/tasks/<id> so the page never blocks.
"""
import json
import re
import secrets
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, advisor, ai, apply, apply_agent, approvals, codes, comp, connections, db, extension, extras, log, loop, mailconn, oauth, paydata, pipeline, settings, vault
from .config import ALERTS, PROFILE

STATIC = Path(__file__).parent / "static"
# read once: an update fast-forwards these files while this server runs (and may roll them back after its tests), so the
# server keeps serving the front end it started with, the one that matches its routes, until it restarts
ASSETS = {f.name: f.read_bytes() for f in STATIC.iterdir() if f.is_file()}
TOKEN = secrets.token_urlsafe(24)          # per launch: the page embeds it, every API call must present it in a header


def _capture_token() -> str:
    """Low-power token the bookmarklets carry as ?t= (valid only on PUBLIC routes). Kept in ~/.lodestar/capture.token so
    a dragged-out bookmarklet keeps working across restarts; delete the file to revoke it."""
    from .config import HOME

    f = HOME / "capture.token"
    try:
        tok = f.read_text(encoding="utf-8").strip()
        if len(tok) >= 20:
            return tok
    except OSError:
        pass
    import os

    tok = secrets.token_urlsafe(18)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only on POSIX (Windows ignores the mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(tok)
    return tok


CAPTURE_TOKEN = _capture_token()
PUBLIC = {"/api/capture", "/api/autofill"}  # the only routes other origins may call
TASK_LOCK = threading.Lock()
DOC_NAMES = {"resume.md", "cover_letter.md", "interview_prep.md", "research.md", "offer.md", "mock_interview.md", "form_answers.md"}  # editable per-job files
TASKS: dict[str, dict] = {}
RESTART = None  # lodestar desktop sets this (desktop.relaunch): Setup > Updates then offers a Restart button
COACH = ("You are a sharp, practical career coach and job-search strategist. Use the candidate's profile and tracker "
         "below to give specific, actionable advice. Be brief and direct.")


# ----------------------------------------------------------------------------- actions (run in threads)
def _coach_system() -> str:
    from .resume import candidate_text

    tracker = "\n".join(f"#{j['id']} {j['status']} {j['company']} - {j['title']}" for j in db.list_jobs()[:40])
    return f"{COACH}\n\nPROFILE:\n{candidate_text(strict=False)}\n\nTRACKER:\n{tracker or '(empty)'}\n\nSTATS: {db.stats()}"


def _bank_view() -> dict:
    from . import profile

    master = profile.master_text()
    bank = profile.load()
    return {"bank": bank, "template": profile.is_template(master), "on_file": profile.extras_text(master),
            "linkedin_export_url": profile.LINKEDIN_EXPORT_URL, "titles": profile.TITLES,
            "labels": {k: [profile.entry_label(k, e) for e in bank[k]] for k in profile.FIELDS}}


def _bases() -> list[dict]:
    from .profile import saved_resumes

    return saved_resumes()


def _docs(job) -> dict:
    from .resume import app_dir

    d = app_dir(job)
    return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.iterdir())
            if p.suffix in (".md", ".json", ".txt")}


def _doc_index() -> list[dict]:
    """[{label, ref}] for the command palette: viewer refs only (openViewer), never file contents or paths."""
    from . import profile, studio
    from .viewer import JOB_DOCS

    out = [{"label": "Master resume", "ref": {"type": "master"}}] if (profile.RESUMES / "master.md").is_file() else []
    out += [{"label": f"Studio version {v['vid']}" + (f" ({' '.join(str(v['request']).split())[:60]})" if v.get("request") else ""),
             "ref": {"type": "studio", "vid": v["vid"]}} for v in studio.versions(30)]
    for j in db.list_jobs():
        d = extras._job_dir(j)  # never created here
        out += [{"label": f"{n} · #{j['id']} {j['company']} - {j['title']}", "ref": {"type": "job", "id": j["id"], "name": n}}
                for n in JOB_DOCS if (d / n).is_file()]
    return out


CLAIM = {"research": "research", "tailor": "tailor", "bullets": "tailor", "bullets_apply": "tailor",
         "cover": "letter", "prep": "prep", "thanks": "thanks"}  # drawer buttons doing a pipeline step's work by hand


def _act(action: str, p: dict):
    """A background action. A drawer button doing a pipeline step's work takes that step's claim, so it never runs while
    Autopilot runs the same step (double AI spend, two writers of resume.md), and its result is adopted on exit."""
    if action in CLAIM and p.get("id"):
        with pipeline.claimed(int(p["id"]), CLAIM[action]):
            return _do(action, p)
    return _do(action, p)


def _pipe_run(jid: int, p: dict, prov) -> list[dict]:
    """One step (stage), the ready steps up to `to`, or else the next ready step. A click is the fit-gate override."""
    rerun = bool(p.get("rerun"))
    if p.get("stage"):
        return [pipeline.run(jid, p["stage"], provider=prov, rerun=rerun)]
    if p.get("to"):
        return pipeline.run_to(jid, p["to"], provider=prov, rerun=rerun)
    if nxt := pipeline.next_stage(jid):
        return [pipeline.run(jid, nxt, provider=prov)]
    return []  # nothing ready: an error for one job (pipeline_run), a skip in a bulk run


def _check_mock(p: dict) -> None:
    """The mock's client values, checked before the task starts: asked = up to 100 question keys of at most 300
    characters, focus one of interview.QCOMP, qkey a string (looked up server-side, never trusted)."""
    from .interview import QCOMP

    a = p.get("asked") or []
    if not isinstance(a, list) or len(a) > 100 or any(not isinstance(x, str) or len(x) > 300 for x in a):
        raise ValueError("asked: up to 100 question keys of at most 300 characters")
    if p.get("focus") and p["focus"] not in QCOMP:
        raise ValueError(f"focus must be one of {', '.join(QCOMP)}")
    if p.get("qkey") is not None and (not isinstance(p["qkey"], str) or len(p["qkey"]) > 300):
        raise ValueError("qkey must be a question key")


def _ready_short(job) -> dict | None:
    """{score, band, label} after a scored answer; None when it cannot be computed (the card still stands)."""
    from . import readiness

    try:
        r = readiness.readiness(job)
    except (Exception, SystemExit):
        return None
    return {"score": r["score"], "band": r["band"], "chance": r["chance"]["band"],
            "practised": r["parts"]["practised"]["chips"][0].lstrip("· ") if r["parts"]["practised"]["chips"] else "",
            "label": f"Readiness for #{job['id']} {job['company']}: {r['score']} · chance estimate "
                     f"{r['chance']['band'].capitalize()} (not a probability)"}


def _with_fit(listings: list[dict]) -> list[dict]:
    """The fit of each search result (not stored: results are not tracked yet), light: score, known, top chips."""
    from . import fit

    try:
        ctx = None
        for j in listings:  # listings.store scored each result already; a row it could not score is scored here
            f = j.pop("fit", None) or fit.for_listing({k: v for k, v in j.items() if k != "id"}, ctx := ctx or fit.context())
            j |= fit.light(f)
    except (Exception, SystemExit) as e:  # results still show without a fit
        log.get("web").warning("search fit failed: %s", e)
    return listings


def track_posting(pid: int) -> int:
    """Today's Top new fits / All jobs > Track: a user click, so the job is added directly and the row linked."""
    from . import listings

    return listings.track(pid)


def sources_view() -> dict:
    """Setup > Job sources and the Jobs tab: each board, ready or needing keys (vault names), its throttle and credit."""
    from . import web_monitor
    from .config import setting

    ready, out = set(web_monitor.sources_ready()), {}
    for n in web_monitor.SOURCES:
        label, home = web_monitor.ATTRIBUTION.get(n, (n, ""))
        row = db.con().execute("SELECT value FROM meta WHERE key=?", (f"src:{n}",)).fetchone()
        out[n] = {"label": label, "home": home, "ready": n in ready, "every_h": round(web_monitor.EVERY.get(n, 0) / 3600, 1),
                  "global": n in web_monitor.GLOBAL, "last": row["value"] if row else None,
                  "keys": [{"name": k, "set": bool(setting(k))} for k in web_monitor.KEYED.get(n, ())]}
    return out


def use_live_jd(jid: int) -> bool:
    """Replace the job's JD with the posting's current description (the listing monitor's snapshot): the user's click,
    since they may have tailored against the old one. False when there is nothing newer on file."""
    from .config import SNAPSHOTS
    from .resume import set_jd

    snap = SNAPSHOTS / f"job-{int(jid)}.json"
    desc = json.loads(snap.read_text(encoding="utf-8")).get("desc", "") if snap.is_file() else ""
    if not desc.strip():
        raise ValueError("no live description on file yet: the listing monitor has not read this posting")
    if desc == (db.get_job(jid)["jd"] or ""):
        return False
    set_jd(jid, desc)
    db.add_event(jid, "note", "job description replaced by the live posting's")
    return True


def alert_sites() -> dict:
    """{site: {label, last, n}}: when Lodestar last read that site's alert mail and how many jobs it held (meta)."""
    from . import alerts

    return {n: {"label": s["label"], "last": db.meta_get(f"alerts:{n}:last") or None, "n": db.meta_get(f"alerts:{n}:n")}
            for n, s in alerts.SITES.items()}


def _job_extras(job) -> dict:
    """GET /api/jobs/<id>: Job intelligence and Chance boosters (pass 21), the readiness breakdown and a summary of the
    practice set (counts, never the questions)."""
    from . import boosters, intel

    out = {}
    for k, f in (("intel", intel.view), ("boosters", boosters.view)):
        try:
            out[k] = f(job)
        except (Exception, SystemExit) as e:  # the drawer still opens; its group says it could not be worked out
            log.get("web").warning("%s #%s failed: %s", k, job["id"], e)
            out[k] = None
    return out | _ready_extras(job)


def _ready_extras(job) -> dict:
    from . import readiness
    from .interview import question_set

    try:
        s = question_set(job)
        r = readiness.readiness(job, s)
    except (Exception, SystemExit) as e:
        log.get("web").warning("readiness #%s failed: %s", job["id"], e)
        return {"readiness": None, "qset": None}
    return {"readiness": r, "qset": {k: s[k] for k in ("by_source", "built_at", "ai_at", "stale", "emphasis_text", "ai_error")}
            | {"dropped": len(s["dropped"])}}


def _check_pipeline(action: str, p: dict) -> None:
    """Checked before the task starts, so a bad request is a 400 and not a failed background task."""
    for k in ("stage", "to"):
        if p.get(k) and p[k] not in pipeline.REGISTRY:
            raise ValueError(f"unknown step {str(p[k])[:30]!r}")
    if action == "pipeline_run":
        db.get_job(int(p["id"]))
    elif not isinstance(p.get("ids"), list) or not 0 < len(p["ids"]) <= 25:
        raise ValueError("pick 1 to 25 jobs")
    else:
        p["ids"] = [int(i) for i in p["ids"]]


def _do(action: str, p: dict):
    from . import email_monitor, interview, resume, web_monitor

    job = db.get_job(int(p["id"])) if p.get("id") else None
    prov, council = p.get("provider") or None, bool(p.get("council"))
    match action:
        case "tailor":  # base: a saved resume id from the profile bank to start from instead of the master
            out = resume.tailor(job, council, prov, p.get("base") or None)
            if p.get("docx"):
                resume.export_docx(out)
            return {"path": str(out), "docs": _docs(job)}
        case "bullets":  # per-bullet proposals into bullets.json; resume.md is untouched until bullets_apply
            return resume.tailor_bullets(job, p.get("base") or None, prov) | {"docs": _docs(job)}
        case "bullets_apply":  # {accept: [bullet ids]}: build resume.md (+docx) from the accepted rows
            return resume.apply_bullets(job, p.get("accept") or [], docx=True) | {"docs": _docs(job)}
        case "export_pdf":  # Word, else LibreOffice, else an HTML print page opened in the system browser
            return resume.export_pdf(resume.app_dir(job) / "resume.md") | {"docs": _docs(job)}
        case "cover":
            out = resume.cover_letter(job, council, prov, p.get("tone") or "confident, warm, specific", int(p.get("words") or 300))
            if p.get("docx"):
                resume.export_docx(out)
            return {"path": str(out), "text": out.read_text(encoding="utf-8"), "docs": _docs(job)}
        case "adjust":  # returns the revised text; nothing is saved until the user clicks Save
            return {"text": resume.adjust_text(p["text"], p["instruction"], p.get("kind") or "document", prov)}
        case "merge_profile":  # merge into what is in the editor (unsaved edits included), not the file on disk
            return {"text": resume.merge_into_profile(p["text"], prov, p.get("current"))}
        case "profile_import":  # {name, data: base64, ai?: bool}: resume file, LinkedIn zip or LinkedIn profile PDF
            import base64

            from . import profile

            raw = base64.b64decode(p.get("data") or "")
            if not raw or len(raw) > 15_000_000:
                raise ValueError("empty file or larger than 15 MB")
            source = "linkedin" if p.get("linkedin") or str(p.get("name", "")).lower().endswith(".zip") else "resume"
            if p.get("review"):  # staged: nothing reaches the bank or profile.md until the review is applied
                return {"pending": profile.stage_import(raw, p.get("name") or "resume.txt", source, prov, p.get("ai"))}
            imported = profile.import_file(raw, p.get("name") or "resume.txt", source, prov, p.get("ai"))
            return imported | _bank_view()
        case "profile_reread":  # profile.md itself into a review (fixes v1 entries); offline
            from . import profile

            return {"pending": profile.reread_master()}
        case "studio_build":  # {request?, req?, id?, jd?, parent?, ai?}: one studio version (ai false: offline)
            from . import studio

            return studio.build(p.get("request") or "", p.get("req") if isinstance(p.get("req"), dict) else None,
                                p.get("id") or None, p.get("jd") or None, p.get("parent") or None, prov,
                                None if p.get("ai") is None else bool(p.get("ai")))
        case "master_sync":  # Update now: rebuild the master resume from the saved profile
            from . import studio

            studio.sync_master(force=True)
            return studio.master_status()
        case "profile_rebuild":
            from . import profile

            out = profile.rebuild_master()
            return {"path": str(out), "text": out.read_text(encoding="utf-8")} | _bank_view()
        case "gap":
            return {"gap": resume.gap(job, prov), "docs": _docs(job)}
        case "match":  # deterministic JD coverage of the job's current resume; no AI
            return {"coverage": resume.coverage(job), "docs": _docs(job)}
        case "lint":  # {text}: the editor's resume text (master profile or a job's resume.md); defaults to profile.md
            from .lint import lint

            if "text" in p and not str(p["text"] or "").strip():
                raise SystemExit("nothing to check: the text is empty")
            return lint(p.get("text") or resume.profile_text())
        case "audit":  # {id}: the job's generated resume.docx; no id: the newest .docx/.pdf saved in the profile bank
            from . import profile
            from .lint import audit

            if job:
                f, name = resume.app_dir(job) / "resume.docx", "resume.docx"
                if not f.is_file():
                    raise SystemExit("no resume.docx for this job yet: run 'Tailor resume (+docx)' first")
            else:
                saved = [r for r in profile.load()["resumes"] if str(r.get("file", "")).lower().endswith((".docx", ".pdf"))
                         and Path(r["file"]).name == r["file"]]  # a bare file name inside resumes/, nothing else
                if not saved:
                    raise SystemExit("no .docx or .pdf resume saved in the profile bank yet: import one on the Profile tab")
                newest = max(saved, key=lambda r: r.get("added", ""))
                f, name = profile.RESUMES / newest["file"], newest.get("name") or newest["file"]
            return audit(f.read_bytes(), name)
        case "prep":
            return {"path": str(interview.prep(job, council, prov)), "docs": _docs(job)}
        case "review":
            if "text" in p and not str(p["text"] or "").strip():  # an empty editor must not silently review profile.md
                raise SystemExit("nothing to review: the text is empty")
            return {"text": resume.review(p.get("text") or resume.profile_text(), prov)}
        case "reply":
            return email_monitor.draft_reply(job, p.get("intent", "polite follow-up"), prov)
        case "email_check":
            found = email_monitor.check(int(p.get("days", 3)), dry=bool(p.get("dry")), provider=prov)
            return {"found": found, "alerts": getattr(found, "alerts", 0), "note": "" if prov or ai.available() else  # say why nothing else was classified
                    "no AI provider: only replies tied to a job were filed; other mail waits until you link a key in Setup > Link an AI key"}
        case "watch_run":
            return {"alerts": web_monitor.check_watches()}
        case "fit_refresh":  # stale fits (profile, preferences or weights changed): no AI
            from . import fit

            return fit.refresh()
        case "listing_ai":  # {listing}: All jobs > AI fit (a user click): one rank() call, stored as the row's AI part
            from . import fit

            return {"fit": fit.ai_listing(int(p["listing"]), prov)}
        case "intel":  # {id, refresh?}: Job intelligence > Gather public facts (company site + its feed, Wikipedia)
            from . import intel

            intel.gather(job, bool(p.get("refresh")))
            return intel.view(job)
        case "intel_ai":  # {id}: one AI summary of the panel's items, every line citing its sources
            from . import intel

            return intel.summarize(job, prov)
        case "boost_ai":  # {id}: Chance boosters > More from AI: up to 3 job-specific additions with their basis
            from . import boosters

            boosters.ai_add(job, prov)
            return boosters.view(job)
        case "job_ai":  # {id}: the drawer's AI fit: one rank() call on this job, stored as its AI part
            from . import fit

            return {"fit": fit.ai_judge(job["id"], prov)}
        case "careers_explore":  # {interests}: tier 6, one AI call (careers.explore)
            from . import careers

            return careers.explore(str(p.get("interests") or ""), prov)
        case "careers_search":  # {track, location?}: one career track's titles on the job boards, with the coverage
            from . import careers

            return careers.search_track(int(p["track"]), location=str(p.get("location") or "") or None)
        case "search":  # filters: location (or 'remote'), min_salary, posted_within (days), seniority
            from .contacts import with_warm

            errs: list[str] = []  # boards that could not be read: 'nothing found' must not hide 'nothing checked'
            query = str(p.get("query") or "").strip() or web_monitor.defaults()["query"]  # blank: your roles
            if not query:
                raise ValueError("type the roles to search for, or add Target roles (Jobs > Search profile)")
            found = with_warm(web_monitor.search(query, p.get("keywords") or "", errors=errs, ran=(ran := []),
                                                 **_filters(p))[:40])
            _with_fit(found)
            if p.get("rank") and found:
                try:
                    found = web_monitor.rank(found, prov)
                except SystemExit as e:  # no provider / rejected model: the listings still show, unranked, with why
                    errs.append(f"AI rank: {e}")
            return {"results": found, "errors": errs, "boards": len(ran), "ids": [j["id"] for j in found if j.get("id")],
                    "query": query}
        case "chat":
            return {"reply": ai.chat(p["messages"], _coach_system(), prov)}
        case "mock":
            if not job:
                raise ValueError("pick a job to interview for (add one on the Board first)")
            msgs = p["messages"]
            _check_mock(p)
            turn = interview.mock_next(job, msgs, p.get("asked") or (), p.get("focus") or None, prov)
            reply = turn["reply"]
            if msgs and str(msgs[-1].get("content", "")).strip().lower() == "done":  # the debrief: keep it with the job
                return {"reply": reply, "path": str(interview.save_mock(job, [*msgs, {"role": "assistant", "content": reply}]))}
            out = {"reply": reply, "question": turn["question"]}  # the server's pick, with its source label
            if len(msgs) >= 2 and msgs[-2].get("role") == "assistant" and msgs[-1].get("role") == "user":  # an answer
                out["card"] = interview.score_answer(job, msgs[-2].get("content"), msgs[-1].get("content"), p.get("seconds"),
                                                     p.get("session"), prov, qkey=p.get("qkey"))
                out["readiness"] = _ready_short(job)
            return out
        case "qset":  # {id, refresh?}: read the company's pages (refresh: refetch) + one AI build of the practice set
            if not job:
                raise ValueError("pick a job")
            s = interview.question_set(job, build=True, refresh=bool(p.get("refresh")), provider=prov)
            return {k: s[k] for k in ("by_source", "dropped", "ai_error", "stale", "ai_at", "emphasis_text")}
        case "readiness_explain":  # the five preparation parts only (never the fit cap or fit chips), as advice
            from . import readiness

            if not job:
                raise ValueError("pick a job")
            return {"text": readiness.explain(job, prov)}
        case "council":
            if p.get("messages"):  # coach chat in council mode: same profile, tracker and conversation as plain chat
                convo = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in p["messages"][-12:])
                return ai.council(f"Conversation so far (answer the last USER message):\n\n{convo}", _coach_system())
            return ai.council(p["prompt"])
        case "outreach":
            return extras.outreach(job, p.get("person", ""), p.get("channel", "linkedin"), prov)
        case "draft_options":  # {kind, id?, mail_id?, pending_id?, contact_id?, ...}: up to 3 options from one AI call
            from . import drafts

            return {"options": drafts.options(p.get("kind", ""), _draft_ctx(p), int(p.get("n") or 3), prov)}
        case "draft_rewrite":  # {kind, subject?, body, how}: preset (shorter / warmer / formal / direct) or your words
            from . import drafts

            return drafts.rewrite(p.get("body", ""), p.get("how", ""), p.get("kind") or "email", p.get("subject"), prov)
        case "draft_use":  # {kind, ...context, subject, body}: proposed for review (recipient from the server, not here)
            from . import drafts

            return drafts.use(p.get("kind", ""), _draft_ctx(p), {"subject": p.get("subject"), "body": p.get("body")})
        case "referral":  # {id, contact_id}: ask a contact for a referral; email -> Inbox (always reviewed), else a note
            from .contacts import referral

            if not job:
                raise ValueError("pick a job")
            return referral(job, int(p["contact_id"]), prov)
        case "contacts_import":  # {name, data: base64}: LinkedIn export zip or Connections.csv
            import base64

            from .contacts import import_connections

            raw = base64.b64decode(p.get("data") or "")
            if not raw or len(raw) > 15_000_000:
                raise ValueError("empty file or larger than 15 MB (a full LinkedIn archive is big: upload Connections.csv alone)")
            return import_connections(raw, p.get("name") or "")
        case "ics":
            return {"path": str(extras.ics(job, extras.parse_when(p["when"]), int(p.get("minutes", 60)))), "docs": _docs(job)}
        case "digest":
            text = extras.digest(int(p.get("days", 7)), bool(p.get("send")), prov)
            return {"text": text} | ({"sent_to": extras.digest_to()} if p.get("send") else {})
        case "obsidian":
            return {"path": str(extras.export_obsidian())}
        case "answer":
            return apply.answer(job, p["question"], prov)
        case "checklist":
            return {"checklist": apply.checklist(job)}
        case "followup":  # template: the plain offline draft even when a provider is configured
            return apply.followup(job, prov, bool(p.get("template")))
        case "thanks":
            return apply.thanks(job, p.get("interviewer", ""), p.get("notes", ""), prov, bool(p.get("template")))
        case "withdraw":
            return apply.withdraw(job, prov, bool(p.get("template")))
        case "notify_test":  # sent even with the preference off: you asked for it
            from .util import desktop_notify

            return {"ok": desktop_notify("Lodestar", "Test notification: desktop notifications work on this computer.")}
        case "offer":
            out = apply.offer(job, p.get("salary", ""), p.get("bonus", ""), p.get("equity", ""), p.get("benefits", ""),
                              p.get("deadline", ""), p.get("notes", ""), prov)
            return {"path": str(out), "text": out.read_text(encoding="utf-8"), "docs": _docs(job)}
        case "market_pay":  # {id, ai?}: AI occupation pick (on your click), then the job's next BLS figure; cache first
            if not job:
                raise ValueError("pick a job")
            if not settings.pref("market_pay"):
                raise SystemExit("market pay is off: turn it on first (Setup > Preferences, or the drawer's Market pay)")
            if p.get("ai") and not paydata.match_ai(job, prov):
                raise SystemExit("AI could not match an occupation: pick one from the list")
            job, err, tried = db.get_job(job["id"]), None, set()
            # BLS publishes nothing for the metro: the state is next, then national (one query each, all cached)
            while not err and (nxt := paydata.for_job(job).get("next")) and tuple(nxt) not in tried and len(tried) < 3:
                tried.add(tuple(nxt))
                err = paydata.fetch([nxt]).get("error")
            return {"pay": paydata.for_job(job), "error": err}
        case "counter":  # {id, cite: ['JOB_ID:field', ...], ask?, template?}: always waits in the Inbox
            if not job or not isinstance(p.get("cite", []), list):
                raise ValueError("pick the offer to counter; cite is a list of JOB_ID:field")
            return apply.counter(job, p.get("cite") or [], str(p.get("ask") or ""), prov, bool(p.get("template")))
        case "activity":  # {from, to, fmt?: csv|html}: the activity report; fmt also writes it to ~/.lodestar/exports
            rep = extras.activity_report(p.get("from"), p.get("to"))
            if p.get("fmt"):
                out = extras.activity_export(p.get("from"), p.get("to"), str(p["fmt"]))
                if out.suffix == ".html":  # a print page in the system browser, as resume PDF export falls back to
                    webbrowser.open(out.as_uri())
                rep["path"] = str(out)
            return rep
        case "auto_track":
            errs = []
            found = web_monitor.search(p["query"], p.get("keywords") or "", errors=errs, ran=(ran := []), **_filters(p))
            if not found and ran and len(errs) >= len(ran):
                raise SystemExit("no job board could be reached, so nothing was judged: " + "; ".join(errs)[:400])
            return {"results": apply.auto_track(found[:40], prov), "errors": errs}
        case "craft":
            from . import ideas

            return {"ideas": ideas.craft(p.get("topic", "strategy"), p.get("extra", ""), job, p.get("role", ""),
                                         int(p.get("n", 8)), not p.get("single"), prov)}
        case "refine":
            from . import ideas

            return {"idea": ideas.refine(int(p["idea_id"]), p.get("feedback", ""), prov)}
        case "packet":
            return {"path": str(extras.packet(job))}
        case "research":
            out = extras.research(job, prov)
            return {"path": str(out), "text": out.read_text(encoding="utf-8"), "docs": _docs(job)}
        case "pipeline_run":  # {id, stage? | to?, rerun?}: one step, the ready steps up to `to`, else the next step
            if not (runs := _pipe_run(job["id"], p, prov)) and not p.get("to"):
                raise SystemExit(f"#{job['id']}: nothing is ready to run")
            return {"runs": runs}
        case "pipeline_bulk":  # {ids: [<= 25], to?}: the next step (or up to `to`) per job; one failure never stops the rest
            out = []
            for jid in p["ids"]:
                try:
                    out.append({"id": jid, "runs": _pipe_run(jid, {"to": p.get("to")}, prov)})
                except (Exception, SystemExit) as e:
                    db.release(close=False)
                    out.append({"id": jid, "error": str(e) or type(e).__name__})
            return {"jobs": out}
        case "doctor":
            from .doctor import checks

            rows = [{"status": s, "what": w, "detail": d} for s, w, d in checks()]
            if p.get("live"):
                from .doctor import live_keys

                rows += [{"status": s, "what": w, "detail": d} for s, w, d in live_keys()]
                for n in ai.available():
                    try:
                        ai.ask("Reply with the single word OK.", provider=n)
                        rows.append({"status": "ok", "what": f"live call {n}", "detail": ai.model_for(n)})
                    except BaseException as e:
                        rows.append({"status": "fail", "what": f"live call {n}", "detail": str(e)[:160]})
                from .doctor import live_mail

                rows += [{"status": s, "what": w, "detail": d} for s, w, d in live_mail()]
            return {"rows": rows}
        case "backup":
            return {"path": str(extras.backup())}
        case "restore":  # {name}: a zip in the backups folder (Setup > Data); the page never names a path
            return extras.restore(extras.backup_file(p.get("name")))
        case "update_check":  # fetches the origin (up to 3 min): never on an HTTP thread
            from . import updater

            return updater.check(updater.ROOT)
        case "update_apply":  # {target}: only the commit range the user saw; a moved origin asks for a new check
            from . import updater

            plan = updater.check(updater.ROOT, record=False)
            if p.get("target") and plan["target"] != p["target"]:
                why = "the origin changed since your check: check again to see what the update brings"
                updater._done(False, plan["current"], p["target"], f"refused: {why}")  # the card and the log say so
                raise SystemExit(why)
            return updater.apply(updater.ROOT, plan)
        case "export":  # {fmt: json|csv}; CSV writes one file per table into ~/.lodestar/exports
            return {"path": str(extras.export_data("csv" if p.get("fmt") == "csv" else "json"))}
        case "email_signin":  # {provider, account?, login_hint?}: waits for the browser, then tests IMAP and SMTP
            from . import oauth

            st = oauth.signin(p.get("provider", ""), p.get("account") or "personal", p.get("login_hint") or "")
            try:
                test = mailconn.test()
            except (Exception, SystemExit) as e:  # signed in either way; the test result is shown next to it
                test = {"error": connections.redact(str(e))[:300]}
            return {"status": st, "test": test}
        case "advise":  # {scope, target?}: one AI call; the recommendations are stored (nothing is changed)
            return {"recommendations": advisor.recommend(p.get("scope"), p.get("target"), prov)}
        case "advise_auto":  # Full AI {scope, target?}: recommend + apply what passes the guards, one undoable batch
            return advisor.auto(p.get("scope"), p.get("target"), prov)
        case "ai_help":  # {helper, target?}: one AI call; text you read, or suggestion cards for Apply suggestions
            return advisor.assist(p.get("helper"), p.get("target"), prov)
        case "keys_check":  # Setup's Re-check all: every linked key and the mailbox, no tokens spent
            return connections.check_all()
        case "providers_local":
            return {"text": ai.local_preset()}
        case "models":  # the ids each configured provider offers, to pin one under Tools > Preferences > models
            ms: dict[str, list[str] | str] = {}
            for n in _configured():
                try:
                    ms[n] = ai.list_models(n)
                except (Exception, SystemExit) as e:  # a rejected model is SystemExit: one bad provider never hides the rest
                    ms[n] = f"FAIL {e}"
            return ms
        case "providers_test":
            res: dict[str, str] = {}
            for n in _configured():
                try:
                    res[n] = ai.ask("Reply with the single word OK.", provider=n).strip()[:40]
                except (Exception, SystemExit) as e:
                    res[n] = f"FAIL {e}"
            return res
    raise ValueError(f"unknown action {action}")


DRAFT_CTX = ("mail_id", "pending_id", "contact_id", "interviewer", "notes", "person", "cite", "ask", "question", "tone", "words")


def _draft_ctx(p: dict) -> dict:
    """The context keys draft options read, from a request (drafts.options / use whitelist what they use)."""
    return {"job": p.get("id") or None} | {k: p[k] for k in DRAFT_CTX if p.get(k) not in (None, "", [])}


def _configured() -> list[str]:
    if not (names := ai.available()):
        raise SystemExit("no AI provider configured: link a key in Setup > Link an AI key, or click "
                         "'Local only (Ollama)'")
    return names


FILTER_KEYS = ("location", "min_salary", "posted_within", "seniority")


def _filters(p: dict) -> dict:
    """The search filters of a request, validated (web_monitor.clean_filters)."""
    from .web_monitor import clean_filters

    return clean_filters(**{k: p.get(k) for k in FILTER_KEYS})


def _job_view(j, idx=None, revs=None, pidx=None, frev=None) -> dict:
    """A tracked job for the board: its row plus a sponsor hint, the people you know there and, while it is still only
    saved, stale signals. idx: contacts.warm_index(), built once per board. revs: profile.section_revs(), read once per
    board: profile_changed names the profile sections its resume.md drew on that changed since it was made.
    pidx: paydata.index(), read once per board: the cached BLS market pay (never the network). frev: fit.rev(), read
    once per board: the fit travels light (score, known, stale, top chips); GET /api/jobs/<id> has the breakdown."""
    from . import fit
    from .contacts import warm
    from .profile import changed_sections
    from .web_monitor import ghost_signals, sponsor_hint

    changed = changed_sections(j["profile_rev"], revs) if revs is not None else []
    row = {k: v for k, v in dict(j).items() if k not in ("fit", "ai_fit")}
    return row | fit.light(fit.stored(j), frev) | {
        "ghost": ghost_signals(j) if j["status"] == "saved" else None, "sponsor": sponsor_hint(j["company"]),
        "warm": warm(j["company"], idx), "profile_changed": changed, "pay": _pay_view(j, pidx)}


def _pay_view(j, pidx=None) -> dict:
    """paydata.for_job that never costs the board or the drawer."""
    try:
        return paydata.for_job(j, pidx)
    except (Exception, SystemExit) as e:
        log.get("web").warning("market pay #%s: %s", j["id"], e)
        return {"state": "error"}


def _studio_view() -> dict:
    """GET /api/studio: the master card, the versions, the catalogue ids (the 'leave out' picker) and the form choices."""
    from . import ai, render, settings, studio
    from .resume import STYLES, engine_name

    try:
        from .profile import structured

        doc = structured()
        cat = [{"id": e["id"], "kind": k, "label": studio._label(k, e), "on_file": bool(e.get("on_file"))}
               for k in ("experience", "projects", "education", "certifications", "volunteering", "awards", "publications",
                         "patents", "speaking", "other") for e in doc.get(k) or []]
        err = ""
    except (Exception, SystemExit) as e:  # a floor leak or an empty profile: the tab still opens and says why
        cat, err = [], str(e)
    return {"master": studio.master_status(), "versions": studio.versions(), "catalogue": cat, "catalogue_error": err,
            "engine": engine_name(), "ai": bool(ai.available()), "look": settings.pref("resume_look") or {},
            "choices": {"template": list(STYLES), "font": list(render.FONTS), "accent": list(render.ACCENTS),
                        "date_format": list(render.DATE_FORMATS), "sections": list(render.KINDS),
                        "formats": list(render.FORMATS), **{k: list(v) for k, v in render.CHOICES.items() if k != "date_format"}},
            "defaults": render.full_style(render.clean_style(settings.pref("resume_look") or {}))}


def start_task(action: str, params: dict) -> str:
    tid = uuid.uuid4().hex[:8]
    with TASK_LOCK:
        while len(TASKS) > 200:  # ponytail: keep the last 200 results; job actions are also logged as events
            TASKS.pop(next(iter(TASKS)))
        TASKS[tid] = {"status": "running", "action": action}

    def run():
        try:
            TASKS[tid] = {"status": "done", "action": action, "result": _act(action, params)}
        except BaseException as e:  # SystemExit from helpers carries the user-facing message
            log.get("tasks").exception("%s failed", action)
            TASKS[tid] = {"status": "error", "action": action, "error": str(e) or traceback.format_exc()[-400:]}
        finally:
            db.release()  # a failed write must not keep the database locked after the task thread is gone

    threading.Thread(target=run, daemon=True).start()
    return tid


def http_only(url) -> str | None:
    """Only http(s) URLs are stored; anything else (javascript:, file:, data:) is dropped."""
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) and len(u) < 2048 else None


def split_title(page_title: str) -> tuple[str, str]:
    """'Role - Company | LinkedIn', '(3) Role | Company | LinkedIn', 'Company hiring Role in City | LinkedIn',
    'Role - Company - City | Indeed.com' -> (role, company). Workplace words (Remote, Hybrid) are never the company.
    Best effort: the company can be edited after capture."""
    parts = [p.strip() for p in re.sub(r"^\s*\(\d+\)\s*", "", page_title).split("|")]  # '(3) ': unread notifications
    if len(parts) >= 3 and parts[-1].lower().startswith("linkedin"):
        return parts[0], parts[1]
    t = parts[0]
    if m := re.fullmatch(r"(.+?) hiring (.+?)(?: in .+)?", t):
        return m[2].strip(), m[1].strip()
    for sep in (" - ", " – ", " at ", " @ "):
        if sep in t:
            role, rest = t.split(sep, 1)
            bits = [b.strip() for b in re.split(r" - | – ", rest)]
            return role.strip(), next((b for b in bits if b.lower() not in ("remote", "hybrid", "on-site", "onsite")), "")
    return t, ""


def capture(p: dict) -> dict:
    """The posting on the user's open tab -> a Board card (a user click, like a manual add: no approval). Used by the
    bookmarklet (/api/capture: {title, url, desc}) and the extension (/api/ext/capture: + posting, the page's JSON-LD
    JobPosting reduced to strings). Everything here is page-controlled: whitelisted keys, strings only, capped."""
    from html import unescape

    from .util import strip_html
    from .web_monitor import jd_with_salary, listing_fields

    raw = p.get("posting") if isinstance(p.get("posting"), dict) else {}
    post = {k: str(raw.get(k) or "")[:n] for k, n in (("title", 300), ("company", 200), ("location", 200),
                                                         ("posted_at", 40), ("salary", 200), ("description", 100_000))}
    t_role, t_company = split_title(str(p.get("title") or ""))
    title, company = post["title"].strip() or t_role, post["company"].strip() or t_company
    url = http_only(p.get("url"))
    d = post["description"]
    desc = strip_html(unescape(d) if "&lt;" in d else d) if d.strip() else str(p.get("desc") or "")  # escaped JSON-LD HTML
    jd = jd_with_salary({"salary": " ".join(post["salary"].split()), "desc": desc})[:12000]
    dup = url and db.con().execute("SELECT 1 FROM jobs WHERE url=? AND status NOT IN ('rejected','withdrawn')",
                                   (url,)).fetchone()  # add_job's own dedup predicate
    # ponytail: the pre-check and the insert are not one transaction; two simultaneous captures of one URL can both say
    # duplicate: false, and add_job still stores one card
    jid = db.add_job(company or "Unknown company", title or "Unknown role", url, jd,
                     f"captured from {str(p.get('url') or '')[:2048]}", **listing_fields(post))
    try:  # All jobs gets the posting too, linked to the job (merged with any feed or search copy of it)
        from . import listings

        listings.store([{"title": title or "Unknown role", "company": company, "url": url, "location": post["location"],
                         "salary": " ".join(post["salary"].split()), "date": post["posted_at"], "desc": desc}],
                       source="capture", job_id=jid)
    except (Exception, SystemExit) as e:  # the card is what the click asked for; the listing copy is a bonus
        log.get("web").warning("capture: listing not stored: %s", e)
    return {"id": jid, "company": company, "title": title, "duplicate": bool(dup)}


# ----------------------------------------------------------------------------- state
def update_view() -> dict:
    """Setup > Updates and the top-bar badge, from the update log (no network): the last check still offers an update
    unless a later update succeeded; failed: the last update failed or was refused (Getting started notes it)."""
    from . import updater

    try:
        s = updater.status(updater.ROOT)
    except (Exception, SystemExit) as e:  # the state must load whatever the install looks like
        return {"kind": "none", "error": str(e)[:200], "log": [], "available": False, "failed": None,
                "restart_needed": False, "restart": False, "updating": False}
    c, u = s["last_check"], s["last_update"]
    newer = lambda a, b: a and (not b or a["at"] >= b["at"])  # noqa: E731
    return s | {"log": updater.entries(20), "restart": RESTART is not None,
                "available": bool(c and c["result"].startswith("update available") and
                                  not (u and u.get("ok") and newer(u, c))),
                "failed": u if u and not u.get("ok") and u["result"].startswith(("failed", "refused")) else None}


def setup_status(conn: dict | None = None) -> dict:
    """What a new user still has to do before the AI features work. conn: connections.status(), when already read."""
    from .profile import is_template, master_text

    text = master_text()
    conn = conn or connections.status()
    st, avail = conn["keys"], ai.available()
    failed = [n for n in avail if st.get(n, {}).get("status") == "failed"]
    mail = mailconn.status()
    return {
        "profile_ready": not is_template(text),  # same rule prompts use; a short real profile counts
        # unchecked and unreachable count as usable (offline never hides AI features), and so does a quota failure
        "provider_ready": any(n not in failed or st[n].get("quota") for n in avail),
        "provider_problems": [{"name": n, "label": st[n]["label"], "detail": st[n]["detail"]} for n in failed],
        "email_ready": mail["verified"],  # saved AND a Connect & test sign-in passed
        "email_needs_signin": mail["needs_signin"],  # a Google / Microsoft sign-in that expired or was revoked
        "email_problem": conn["mail"].get("detail", "") if conn["mail"].get("status") == "failed" else "",
    }


def _pipeline_summary() -> dict:
    """The board's per-job step summary; a live job with none stored yet gets its first one here (written, so once)."""
    summ = pipeline.summary()
    for j in db.list_jobs():
        if j["id"] not in summ and j["status"] not in pipeline.CLOSED:
            try:
                summ[j["id"]] = pipeline._summary_of(pipeline.status(j["id"]))
            except (Exception, SystemExit):  # one unreadable job never costs the page
                db.release(close=False)
    return summ


def _apply_state() -> dict:
    try:
        return apply_agent.status(brief=True)
    except (Exception, SystemExit) as e:  # the page never fails on the agent's state
        db.release(close=False)
        return {"available": f"apply agent state unavailable: {e}"[:200], "live": [], "queue": 0}


SHOT_RE = re.compile(r"(?:page-\d{2}|confirmation)\.png")


def state() -> dict:
    from . import interview
    from .ideas import merged as ideas_merged
    from .contacts import ROLES, warm_index

    idx, conn = warm_index(), connections.status()
    try:
        from . import profile

        revs = profile.section_revs()
    except (Exception, SystemExit):  # an unreadable profile never costs the board
        revs = None
    linked = {k for e in connections.REGISTRY.values() for k in (e["key"], e.get("id")) if k}  # shown on the Link an AI key card instead
    try:
        pidx = paydata.index()
    except (Exception, SystemExit):
        pidx = {"on": False, "home": [], "rows": {}}
    from . import fit

    try:
        frev = fit.rev()
        fstale = fit.stale_count(frev)
    except (Exception, SystemExit):  # the board never waits on the fit
        frev, fstale = None, 0
    return {
        "version": __version__,
        "setup": setup_status(conn),
        "connections": conn,
        "codes_count": len(codes.current()),  # the count only: a code never travels in the state
        "apply": _apply_state(),  # the apply agent: available, live runs, queue (apply_agent.status)
        "loop": dict(loop.STATUS),
        "jobs": [_job_view(j, idx, revs, pidx, frev) for j in db.list_jobs()],
        "fit_rev": frev,  # a job whose fit was scored at another rev is stale (dimmed); the page asks for a refresh
        "fit_stale": fstale,
        "sources": sources_view(),  # Setup > Job sources and the Jobs tab: ready / needs keys, throttle, credit
        "alert_sites": alert_sites(),  # Setup > Job alerts: per site, the last alert mail read and its job count
        "contact_roles": ROLES,
        "statuses": db.STATUSES,
        "doc_names": sorted(DOC_NAMES),  # the drawer offers Edit / Adjust for these only
        "stats": db.stats(),
        "followups": [j["id"] for j in db.needs_followup()],
        "variants": db.variant_stats(),
        "funnel": db.funnel(),
        "pending": [dict(r) | {"payload": json.loads(r["payload"])} for r in db.list_pending("pending")],
        "decided": [dict(r) for r in db.list_pending(None, 15) if r["status"] != "pending"],
        "mail_unmatched": [dict(r) for r in db.list_mail(unmatched=True, limit=50)],  # Inbox: Unmatched mail
        "tools": settings.table(),
        "prefs": settings.load()["prefs"],
        "pref_choices": settings.CHOICES,
        "pref_help": settings.PREF_HELP,
        "ai_helpers": advisor.helpers(),  # each component's AI help menu (advisor.HELPERS)
        "ai_topics": advisor.topics(),  # Explain this setting: Setup's cards and the preferences
        "bases": _bases(),
        "answers": [dict(r) for r in db.list_answers() if r["star"] is None],  # stories are listed apart
        "stories": interview.stories(),
        "competencies": interview.COMPETENCIES,
        "round_kinds": interview.KINDS,
        "qcomp": interview.QCOMP,  # the mock's Focus choices
        "round_outcomes": interview.OUTCOMES,
        "mock_sessions": interview.sessions(),
        "ideas": [ideas_merged(r) for r in db.list_ideas()],
        "idea_statuses": db.IDEA_STATUSES,
        "providers": {n: (n in ai.available()) for n in ai.PROVIDERS},
        "watches": [dict(w) | {"filters": db.watch_filters(w)} for w in db.watches()],
        "companies": [dict(c) for c in db.companies()],
        "alerts": ALERTS.read_text(encoding="utf-8").splitlines()[-30:] if ALERTS.is_file() else [],
        "vault": [{"name": n, "user": u} for n, u in vault.names() if n not in mailconn.MANAGED and n not in oauth.CLIENT_KEYS
                  and n not in linked and not n.startswith("site:")],  # site passwords: Setup > Site accounts
        "obsidian_dir": str(extras.vault_root() / "jobs"),  # Export tracker to Obsidian asks before writing there
        "comp": comp.load(),
        "upcoming": [i | {"when": f"{i['when']:%a %Y-%m-%d %H:%M}"} for i in extras.upcoming_interviews(14)],
        "today": loop.agenda(),
        "profile_path": str(PROFILE),
        "usage_today": ai.usage(1)["total"],
        "usage": ai.usage(30),
        "update": update_view(),
        "pipeline": _pipeline_summary(),  # {job_id: {next, you, stale, errors, done, total, fit_skip}}
        "pipeline_stages": [{"name": s.name, "label": s.label, "tool": s.tool, "ai": s.ai, "run": s.run is not None,
                             "manual": s.run is None or s.name in pipeline.MANUAL} for s in pipeline.REGISTRY.values()],
        "questions": pipeline.questions(),  # open, blocking first (Inbox > Questions for you)
        "autopilot": {"spent": pipeline.spent_today(), "last": dict(pipeline.LAST)},
        "extensions": extension.paired(),  # paired browsers for Setup; never a secret
        "bookmarklets_on": extension.bookmarklets_on(),
    }


# ----------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # terminal stays quiet; the rotating log keeps the access line, minus any token
        log.get("web").info(fmt, *[str(x).split("?t=")[0] for x in a])

    def finish(self):
        try:
            super().finish()
        finally:  # one thread per request: roll back what a failed write left open and close its connection
            db.release()

    def _public(self) -> bool:
        return urlparse(self.path).path in PUBLIC

    def _cors(self):  # bookmarklets post from linkedin.com / indeed.com tabs: only the public routes get CORS
        if self._public():
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _host_ok(self) -> bool:
        """DNS rebinding defence: the Host header must name this loopback server, nothing else."""
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    def _authed(self) -> bool:
        """Page requests carry the header token; bookmarklets carry the capture token as ?t= on PUBLIC routes only."""
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return True
        if secrets.compare_digest(self.headers.get("X-Lodestar-Token") or "", TOKEN):
            return True
        from urllib.parse import parse_qs

        t = parse_qs(u.query).get("t", [""])[0]
        return (u.path in PUBLIC and bool(t) and secrets.compare_digest(t, CAPTURE_TOKEN)
                and extension.bookmarklets_on())  # pref 'bookmarklets' (auto: off once an extension is paired)

    def do_OPTIONS(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 421)
        self.send_response(204 if self._public() else 404)
        self._cors()
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n and "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("POST bodies must be application/json")  # no-preflight text/plain posts carry no weight
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._host_ok():
            return self._json({"error": "bad host"}, 421)
        if not self._authed():
            return self._json({"error": "missing or wrong token; reload the Lodestar page"}, 403)
        try:
            if path == "/":
                html = ASSETS["index.html"].replace(b"__TOKEN__", TOKEN.encode()).replace(b"__CAPTURE__", CAPTURE_TOKEN.encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")  # the page embeds the API token: never framed (clickjacking)
                self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif path == "/logo.svg" or path.startswith("/static/"):
                name = "logo.svg" if path == "/logo.svg" else path[8:]
                body = ASSETS.get(name)  # only files sitting directly in static/: no path ever reaches the disk
                if body is None:
                    return self._json({"error": "not found"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", {".svg": "image/svg+xml", ".css": "text/css", ".js": "text/javascript"}.get(Path(name).suffix, "application/octet-stream") + "; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._json(state())
            elif path.startswith("/api/jobs/") and path.endswith("/files"):  # what a mail for this job may attach
                from .mailfiles import attachable

                self._json({"files": attachable(db.get_job(int(path.split("/")[3])))})  # names and sizes, never bytes
            elif path.startswith("/api/jobs/") and len(path.split("/")) == 5 and path.split("/")[4] in ("questions", "qsources"):
                from . import interview

                try:
                    job = db.get_job(int(path.split("/")[3]))
                except (ValueError, SystemExit) as e:
                    return self._json({"error": str(e) or "bad job id"}, 400)
                if path.endswith("/qsources"):  # the company's sources: site, pages with status, pastes (preview)
                    return self._json(interview.sources(job))
                s = interview.question_set(job)  # the full set: every string is escaped client-side
                self._json({k: s[k] for k in ("questions", "emphasis", "emphasis_text", "hits", "dropped", "by_source",
                                              "stale", "built_at", "ai_at", "ai_error", "site")})
            elif path == "/api/apply/status":  # the apply agent: live runs, the queue, the last 10 runs
                self._json(apply_agent.status())
            elif re.fullmatch(r"/api/apply/\d+/shot/[^/]+", path):  # a run's screenshot, by exact name only
                rid, name = int(path.split("/")[3]), path.split("/")[5]
                ev = db.get_run(rid)["evidence"]
                if not SHOT_RE.fullmatch(name) or not ev or not (Path(ev) / name).is_file():
                    return self._json({"error": "not found"}, 404)
                body = (Path(ev) / name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/boosters":  # Insights: chance boosters across the search (rules only, no AI, no network)
                from . import boosters

                self._json({"boosters": boosters.across(12)})
            elif path == "/api/readiness/calibration":  # your record: evidence table, state, caveat (Insights)
                from . import readiness

                self._json(readiness.calibration())
            elif path == "/api/accounts":  # site accounts (accounts.py): rows, the account window, waits; never a password
                from urllib.parse import parse_qs

                from . import accounts

                self._json(accounts.overview(parse_qs(urlparse(self.path).query).get("q", [""])[0]))
            elif path == "/api/search/defaults":  # the Jobs tab's start: roles and place from Preferences / your resume
                from . import web_monitor

                self._json(web_monitor.defaults())
            elif path == "/api/codes":  # emailed sign-in codes, memory only (codes.py)
                self._json({"codes": codes.current()})
            elif path.startswith("/api/jobs/"):
                from . import interview
                from .contacts import job_people, warm

                job = db.get_job(int(path.split("/")[3]))
                from . import fit, listings

                self._json({"job": {k: v for k, v in dict(job).items() if k not in ("fit", "ai_fit")}
                            | fit.light(fit.stored(job), fit.rev()), "fit": fit.stored(job), "events": [dict(e) for e in db.events(job["id"])], "docs": _docs(job),
                            "people": job_people(job["id"]), "warm": warm(job["company"]),
                            "rounds": interview.rounds(job["id"]), "bank": interview.question_bank(job, False)[:30],
                            "stress": interview.story_prompt(job), "mail": [dict(r) for r in db.list_mail(job["id"])],
                            "pipeline": pipeline.status(job["id"]), "questions": pipeline.questions(job=job["id"]),
                            "runs": pipeline.log_runs(job["id"], 10), "pay": _pay_view(job),
                            "occupations": paydata.data()["occupations"], "activity": listings.activity(job["id"]),
                            "posting": listings.posting_of(job), **_job_extras(job)})
            elif path.startswith("/api/advise"):  # the AI advisor (advisor.py): scopes | ?scope=&target= | history
                from urllib.parse import parse_qs

                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                if path == "/api/advise/scopes":
                    self._json({"scopes": advisor.scopes(), "ai": bool(ai.available()), "no_ai": ai.NO_PROVIDER})
                elif path == "/api/advise/history":
                    self._json({"batches": advisor.history(int(q["limit"]) if q.get("limit", "").isdigit() else 30)})
                elif path == "/api/advise":
                    self._json({"recommendations": advisor.pending(q.get("scope", ""), q.get("target")),
                                "ai": bool(ai.available())})
                else:
                    self._json({"error": "not found"}, 404)
            elif path == "/api/audit":  # Setup > Audit log: policy decisions and action runs, newest first (policy.py)
                from . import policy

                self._json({"rows": policy.log(100), "reasons": policy.REASONS, "version": policy.VERSION})
            elif path == "/api/careers":  # Careers tab: suggestions, your tracks, labels; missing O*NET data is said, not a 500
                from . import careers

                out = {"classes": careers.CLASSES, "tiers": careers.TIERS, "tracks": careers.tracks(), "suggestions": []}
                try:
                    out["tracks"] = [t | {"search_titles": careers.search_titles(t)} for t in out["tracks"]]
                    out |= careers.suggest()
                except SystemExit as e:
                    out["error"] = str(e)
                self._json(out)
            elif path == "/api/listings":  # All jobs: ?q&source(,)&min_fit&remote&min_salary&days&new&show&sort&offset
                from urllib.parse import parse_qs

                from . import listings

                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                num = lambda k: int(q[k]) if q.get(k, "").isdigit() else 0  # noqa: E731
                try:
                    self._json(listings.query(q.get("q", ""), [s for s in q.get("source", "").split(",") if s],
                                              num("min_fit"), q.get("remote", ""), q.get("min_salary") or None,
                                              q.get("days") or None, q.get("new") in ("1", "true"), q.get("show", "open"),
                                              q.get("sort", "fit"), num("offset")) | {"boards": sources_view()})
                except SystemExit as e:  # a bad filter value: said, not a 500
                    self._json({"error": str(e)}, 400)
            elif path.startswith("/api/listings/") and path.split("/")[3].isdigit():
                from . import listings

                try:
                    self._json(listings.get(int(path.split("/")[3])))
                except SystemExit as e:
                    self._json({"error": str(e)}, 404)
            elif path == "/api/questions":  # ?all=1 (answered and dismissed too) &job=ID
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                job = q.get("job", [""])[0]
                self._json({"questions": pipeline.questions(bool(q.get("all")), int(job) if job else None)})
            elif path == "/api/pipeline/log":  # ?job=ID&limit=N (default 50)
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                job, n = q.get("job", [""])[0], q.get("limit", ["50"])[0]
                self._json({"runs": pipeline.log_runs(int(job) if job else None, min(int(n), 500) if n.isdigit() else 50)})
            elif path == "/api/mail":  # ?job=ID (that job's mail, both ways) or ?unmatched=1
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                job = q.get("job", [""])[0]
                self._json({"mail": [dict(r) for r in db.list_mail(int(job) if job else None, bool(q.get("unmatched")))]})
            elif path == "/api/contacts":
                from .contacts import ROLES, rows

                self._json({"contacts": rows(), "roles": ROLES})
            elif path == "/api/extension/paired":  # Setup polls this while a pairing code is on screen
                self._json({"extensions": extension.paired()})
            elif path == "/api/backups":  # Setup > Data: Restore from backup picks one of these
                self._json({"backups": extras.backups()})
            elif path == "/api/docs":  # the command palette's documents: the master, studio versions, each job's files
                self._json({"docs": _doc_index()})
            elif path == "/api/analytics":  # Insights tab: weekly series, response rates, funnel, variants, goals
                from urllib.parse import parse_qs

                weeks = parse_qs(urlparse(self.path).query).get("weeks", ["12"])[0]  # the Insights range picker
                self._json(extras.analytics(int(weeks) if weeks.isdigit() else 12) | {"goal_keys": settings.GOALS})
            elif path == "/api/offers":  # live offers side by side; includes the private floor gap (this page only)
                self._json(comp.compare() | {"fields": db.OFFER_FIELDS, "cite": list(apply.COUNTER_CITE)})
            elif path.startswith("/api/contacts/"):
                from .contacts import contact_events, contact_jobs, get

                cid = int(path.split("/")[3])
                self._json({"contact": dict(get(cid)), "jobs": contact_jobs(cid), "events": contact_events(cid)})
            elif path.startswith("/api/tasks/"):
                self._json(TASKS.get(path.split("/")[3], {"status": "unknown"}))
            elif path == "/api/profile":  # base: the stale-check token POST /api/profile hands back
                from .profile import master_base

                text = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else ""
                self._json({"text": text, "base": master_base(text)})
            elif path == "/api/profile/imports":  # staged imports waiting for review
                from .profile import pending_imports

                self._json({"imports": pending_imports()})
            elif path == "/api/studio":  # the master card, versions, the fact catalogue for the picker, the form's choices
                self._json(_studio_view())
            elif path.startswith("/api/studio/"):  # <vid>: plan.json + the preview page + the text | <vid>/file?name=
                from urllib.parse import parse_qs

                from . import studio

                bits = path.split("/")
                try:  # an unknown version or a name that is not one of its files: 404, never a path on disk
                    v = studio.version(bits[3]) if len(bits) in (4, 5) else None
                    f = (studio.file_path(bits[3], parse_qs(urlparse(self.path).query).get("name", [""])[0])
                         if len(bits) == 5 and bits[4] == "file" else None)
                except SystemExit as e:
                    return self._json({"error": str(e)}, 404)
                if f is not None:  # a version's own file as bytes (the viewer's PDF tab)
                    body = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", {".pdf": "application/pdf", ".html": "text/html; charset=utf-8",
                                                      ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                                     .get(f.suffix, "text/plain; charset=utf-8"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if len(bits) != 4:
                    return self._json({"error": "not found"}, 404)
                read = lambda ext: (studio.file_path(v["vid"], v["files"][ext]).read_text(encoding="utf-8")  # noqa: E731
                                    if ext in v["files"] else "")
                self._json(v | {"html": read("html"), "md": read("md"), "txt": read("txt")})
            elif path == "/api/profile/bank":
                self._json(_bank_view())
            elif path == "/api/keys":  # linked AI keys and their last check; never a key
                self._json(connections.status())
            elif path == "/api/email/status":  # connection and presets; never the password, a token or a client id
                from . import mailconn, oauth

                self._json({"status": mailconn.status(), "presets": mailconn.PRESETS,
                            "clients": oauth.client_status(), "oauth": oauth.LABELS})
            elif path == "/api/email/signin":  # a waiting sign-in's page: the fallback link when no browser opened
                from . import oauth

                pend = dict(oauth.PENDING)
                self._json({"pending": bool(pend), "url": pend.get("url", ""), "provider": pend.get("provider", "")})
            elif path == "/api/update/status":  # no network: install kind, prefs, last check and update, the log
                self._json(update_view())
            elif path == "/api/update/log":  # ?limit=N (default 50)
                from urllib.parse import parse_qs

                from .updater import entries

                n = parse_qs(urlparse(self.path).query).get("limit", ["50"])[0]
                self._json({"log": entries(min(int(n), 500) if n.isdigit() else 50)})
            elif path == "/api/autofill":  # the autofill bookmarklet reads this; it never submits a form
                # CORS-open to the page you are on: send only the fields it types, not the private answer bank
                self._json({k: v for k, v in extras.autofill_data().items() if k != "answers"})
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:
            self._json({"error": str(e)}, 500)

    EXT_ROUTES = ("/api/ext/pair", "/api/ext/ping", "/api/ext/capture", "/api/ext/autofill")

    def _ext_post(self, path: str):
        """The browser extension's routes, a closed table: signed with its own secret (extension.verify), never the page
        token, never CORS headers (an extension page with host permission needs none; a web page gets no preflight
        answer). Nothing under /api/ext/ falls through to the page routes."""
        n = self.headers.get("Content-Length") or "0"
        if not (n.isascii() and n.isdigit()) or int(n) > 1_000_000:
            self.close_connection = True  # the body is left unread: drop the connection
            return self._json({"error": "request body too large"}, 413)
        raw = self.rfile.read(int(n))
        if path not in self.EXT_ROUTES:
            return self._json({"error": "not found"}, 404)
        try:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError
            p = json.loads(raw or b"{}")
            if not isinstance(p, dict):
                raise ValueError
        except (ValueError, RecursionError):
            return self._json({"error": "send a JSON object"}, 400)
        origin = self.headers.get("Origin") or ""
        if path == "/api/ext/pair":
            try:
                return self._json(extension.pair(p.get("code", ""), origin, str(p.get("label") or "")[:40])
                                  | {"version": __version__})
            except SystemExit as e:
                return self._json({"error": str(e)}, 403)
        port = self.server.server_address[1]  # the port we listen on: a relay on another port fails the signature
        eid = extension.verify(self.headers.get("X-Lodestar-Ext"), origin, "POST", port, path, raw)
        if not eid:
            return self._json({"error": "not paired"}, 401)
        if path != "/api/ext/ping" and extension.linkedin(p.get("url")):
            return self._json({"error": extension.LINKEDIN}, 400)
        try:
            if path == "/api/ext/ping":
                import time

                t = int(time.time())
                return self._json({"ok": True, "version": __version__, "ts": t, "proof": extension.proof(eid, f"pong\n{t}\n{port}")})
            if path == "/api/ext/capture":
                return self._json(capture(p))
            qs = p.get("questions") if isinstance(p.get("questions"), list) else []
            qs = list(dict.fromkeys(" ".join(q.split())[:200] for q in qs if isinstance(q, str) and q.strip()))[:100]
            return self._json(extras.ext_autofill(qs, p.get("eeo") is True, p.get("salary") is True, p.get("url")))
        except SystemExit as e:  # a user-facing message (template profile, Full AI on)
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            log.get("web").exception("extension route %s failed", path)
            return self._json({"error": f"{type(e).__name__}: {e}"[:300]}, 500)

    def do_POST(self):
        path, p = urlparse(self.path).path, {}
        if not self._host_ok():
            n = self.headers.get("Content-Length") or ""
            self.rfile.read(min(int(n), 1_000_000) if n.isdigit() else 0)  # drained: an unread body resets the socket on Windows
            return self._json({"error": "bad host"}, 421)
        if path.startswith("/api/ext/"):  # before _authed: these routes carry their own signature, never the page token
            return self._ext_post(path)
        if not self._authed():
            n = self.headers.get("Content-Length") or ""
            self.rfile.read(min(int(n), 1_000_000) if n.isdigit() else 0)  # drained: an unread body resets the socket on Windows
            return self._json({"error": "missing or wrong token; reload the Lodestar page"}, 403)
        try:
            p = self._body()
            parts = path.split("/")
            if path.startswith("/api/apply/"):  # the apply agent (apply_agent.py): every route needs the page token
                if path == "/api/apply/start":  # {ids: [...], mode?, eeo?}
                    ids = p.get("ids") if isinstance(p.get("ids"), list) else [p.get("id")]
                    mode = p.get("mode") if p.get("mode") in apply_agent.MODES else None
                    eeo = p.get("eeo") if isinstance(p.get("eeo"), bool) else None
                    runs = apply_agent.enqueue(ids[:200], mode, eeo)
                    return self._json({"runs": [r for r in runs if "run_id" in r], "refused": [r for r in runs if "error" in r]})
                if path == "/api/apply/stop":
                    return self._json(apply_agent.stop())
                if path == "/api/apply/login":  # {url?}: the plain sign-in window on the agent's profile
                    return self._json(apply_agent.login_window(p.get("url") or None))
                if path == "/api/apply/forget":
                    return self._json(apply_agent.forget_logins())
                if re.fullmatch(r"/api/apply/\d+/continue", path):
                    return self._json(apply_agent.continue_run(int(parts[3])))
                return self._json({"error": "not found"}, 404)
            if path == "/api/search/profile":  # {roles, location}: into Preferences (private; fit and search read it)
                from . import profile, web_monitor

                return self._json(profile.set_pref_fields({"Target roles": p.get("roles") or "",
                                                           "Locations / remote": p.get("location") or ""})
                                  | {"defaults": web_monitor.defaults()})
            if path.startswith("/api/accounts/"):  # site accounts (accounts.py): the password comes back only on reveal
                from . import accounts

                if path == "/api/accounts/add":  # {url, username, password?}: no password = a generated one
                    return self._json(accounts.add(p.get("url"), p.get("username"), p.get("password") or ""))
                if path == "/api/accounts/general":  # {username?, password} | {clear: true}: never sent back
                    return self._json(accounts.set_general(p.get("username") or "", p.get("password") or "",
                                                           p.get("clear") is True))
                if path == "/api/accounts/create":  # {url}: the agent's window fills the sign-up form; you press Create
                    return self._json(accounts.start("create", url=p.get("url")))
                if path == "/api/accounts/act":  # {target: session | run:<id>, action, id?}
                    return self._json(accounts.act(str(p.get("target") or ""), str(p.get("action") or ""), str(p.get("id") or "")))
                if m := re.fullmatch(r"/api/accounts/(\d+)/(reveal|password|auto|relogin|open|reset|remove)", path):
                    aid, op = int(m[1]), m[2]
                    if op == "reveal":
                        return self._json(accounts.reveal(aid))
                    if op == "password":  # {password} | {generate: true}
                        return self._json(accounts.set_password(aid, p.get("password") or "", p.get("generate") is True))
                    if op == "auto":
                        return self._json(accounts.set_auto(aid, p.get("on") is True))
                    if op == "relogin":
                        return self._json(accounts.start("relogin", aid))
                    if op in ("open", "reset"):  # the plain sign-in window (no automation) on the agent's profile
                        a = accounts.get(aid)
                        return self._json(apply_agent.login_window(a["reset_url"] if op == "reset" and a["reset_url"] else a["login_url"]))
                    return self._json(accounts.remove(aid))
                return self._json({"error": "not found"}, 404)
            if path == "/api/jobs":
                from html import unescape

                from .util import fetch, strip_html
                from .web_monitor import listing_fields  # a saved search listing carries location and posting date

                src, jd = str(p.get("jd") or "").strip(), None
                company, title = str(p.get("company") or "").strip(), str(p.get("title") or "").strip()
                if src.startswith(("http://", "https://")):  # a link: its page title names the role and company
                    page = fetch(src)
                    jd = strip_html(page)
                    if m := re.search(r"(?is)<title[^>]*>(.*?)</title>", page):
                        t, c = split_title(" ".join(unescape(m[1]).split()))  # same parse as the capture bookmarklet
                        company, title = company or c, title or t
                elif src:
                    jd = src
                if not (company or title or jd):
                    raise ValueError("type a company and title, or paste a job description or its link")
                url = http_only(p.get("url") or (src if src.startswith("http") else None))
                self._json({"id": db.add_job(company, title, url, jd, p.get("notes"), **listing_fields(p))})
            elif path == "/api/capture":  # bookmarklet: {title, url, desc} from the open tab
                self._json(capture(p))
            elif path == "/api/extension/code":  # Setup > Browser extension > Pair a browser (page token)
                self._json(extension.new_code() | {"port": self.server.server_address[1]})
            elif path == "/api/extension/revoke":
                self._json({"ok": extension.revoke(str(p.get("id") or ""))})
            elif path == "/api/careers/tracks":  # {label, intent, titles, codes?, tiers?, exclusions?, location?, ...}
                from . import careers

                self._json({"id": careers.add_track(
                    str(p.get("label") or ""), str(p.get("intent") or ""), titles=p.get("titles") or (),
                    codes=p.get("codes") or (), tiers=p.get("tiers"), exclusions=p.get("exclusions") or (),
                    location=str(p.get("location") or ""), training=str(p.get("training") or "none"),
                    priority=str(p.get("priority") or "medium"))})
            elif path.startswith("/api/careers/tracks/") and len(parts) == 6 and parts[4].isdigit() and parts[5] == "delete":
                from . import careers

                careers.remove_track(int(parts[4]))
                self._json({"ok": True})
            elif path.startswith("/api/listings/") and len(parts) == 5 and parts[4] == "track":
                self._json({"id": track_posting(int(parts[3]))})
            elif path.startswith("/api/listings/") and len(parts) == 5 and parts[4] == "dismiss":
                from . import listings

                listings.dismiss(int(parts[3]), p.get("on", True) is not False)
                self._json({"ok": True})
            elif path == "/api/listings/visit":  # Mark all seen
                from . import listings

                self._json({"visit": listings.visit()})
            elif path.startswith("/api/jobs/") and len(parts) == 5:
                jid, op, out = int(parts[3]), parts[4], {"ok": True}
                if op == "status":
                    db.set_status(jid, p["status"], p.get("note", ""))
                elif op == "note":
                    text = str(p.get("text") or "").strip()
                    if not text:
                        raise ValueError("type a note first")
                    j = db.get_job(jid)
                    db.update_job(jid, notes=((j["notes"] or "") + "\n" + text).strip())
                    db.add_event(jid, "note", text)
                elif op == "jd":
                    from .resume import set_jd
                    from .util import read_source

                    url = http_only(p["source"]) if not db.get_job(jid)["url"] else None  # a JD link is the posting link
                    set_jd(jid, read_source(p["source"], allow_files=False), **({"url": url} if url else {}))
                elif op == "contact":  # the address follow-ups, thank-yous and replies are sent to
                    from .contacts import EMAIL_RE, from_job_contact

                    email, name = str(p.get("email") or "").strip(), str(p.get("name") or "").strip()
                    if email and not EMAIL_RE.fullmatch(email):
                        raise ValueError(f"not an email address: {email[:80]}")
                    db.update_job(jid, contact_email=email or None, contact_name=name[:120])
                    out["contact_id"] = from_job_contact(jid, name, email)  # also filed under Contacts (recruiter)
                elif op == "live_jd":  # Use live description: the listing monitor's last copy of the posting
                    out["changed"] = use_live_jd(jid)
                elif op == "fields":  # tracker details; db.set_fields whitelists and validates every key
                    from .resume import refit

                    db.set_fields(jid, **{str(k): v for k, v in p.items()})
                    refit(jid)  # location, workplace and pay are fit inputs
                elif op == "skip":  # {term}: JD coverage keyword "not mine" on/off; answers with the recomputed coverage
                    from .resume import toggle_skip

                    out["coverage"] = toggle_skip(db.get_job(jid), p.get("term"))
                elif op == "rounds":  # {round?, kind, at, interviewers, notes, questions_asked, outcome}: validated
                    from .interview import log_round

                    out["round_id"] = log_round(jid, **{str(k): v for k, v in p.items()})
                elif op == "qsources":  # {op: paste, label, text, url?} | {op: delete, sid} | {op: site, url}
                    from . import interview

                    j, what = db.get_job(jid), p.get("op")
                    if what == "paste":
                        out["sid"] = interview.add_paste(j, p.get("label"), p.get("text"), p.get("url"))
                    elif what == "delete":
                        interview.delete_source(j, int(p.get("sid")))  # another company's source: refused
                    elif what == "site":
                        out |= interview.set_site(j, p.get("url"))
                    else:
                        raise ValueError("op is paste, delete or site")
                    out["sources"] = interview.sources(j)
                elif op == "soc":  # {soc: 'NN-NNNN' | 'none' | ''}: the BLS occupation for market pay (yours wins)
                    paydata.set_soc(jid, p.get("soc"))
                    out["pay"] = _pay_view(db.get_job(jid))
                elif op == "delete":
                    db.delete_job(jid)
                else:
                    raise ValueError(f"unknown job operation {op}")
                self._json(out)
            elif path == "/api/watches":  # a saved search keeps its filters; a page watch has none
                url = str(p.get("url") or "").strip()
                if not url:
                    raise ValueError("a URL or a search query is required")
                kw = str(p.get("keywords") or "").strip() or None  # blank: an existing watch keeps its keywords
                if p.get("search"):
                    # blank filter fields (the Search tab sends all four) count as none: the saved filters stay
                    keep = not any(str(p.get(k) or "").strip() for k in FILTER_KEYS)
                    updated = db.add_watch(f"search:{url}", kw, None if keep else _filters(p))
                elif not http_only(url):
                    raise ValueError("a page watch needs an http(s) URL (tick 'is a search' for a query)")
                else:
                    updated = db.add_watch(url, kw)
                self._json({"ok": True, "updated": updated})
            elif path.startswith("/api/watches/"):
                db.remove_watch(int(parts[3]))
                self._json({"ok": True})
            elif path == "/api/companies":  # {source: careers URL or vendor:slug, name?, keywords?}
                from .web_monitor import add_company

                self._json(add_company(p.get("source", ""), p.get("name", ""), p.get("keywords", "")))
            elif path == "/api/contacts":  # {name, email, ...}: contacts._clean whitelists and validates every key
                from . import contacts

                self._json({"id": contacts.add(**{str(k): v for k, v in p.items()})})
            elif path.startswith("/api/contacts/") and len(parts) == 5:
                from . import contacts

                cid, op = int(parts[3]), parts[4]
                if op == "edit":
                    contacts.edit(cid, **{str(k): v for k, v in p.items()})
                elif op == "delete":
                    contacts.remove(cid)
                elif op == "link":  # {job_id, role}
                    contacts.link(cid, int(p["job_id"]), str(p.get("role") or "other"))
                elif op == "unlink":
                    contacts.unlink(cid, int(p["job_id"]))
                else:
                    raise ValueError(f"unknown contact operation {op}")
                self._json({"ok": True})
            elif path.startswith("/api/rounds/") and len(parts) == 5:
                from . import interview

                rid, op = int(parts[3]), parts[4]
                if op == "edit":
                    interview.edit_round(rid, **{str(k): v for k, v in p.items()})
                elif op == "delete":
                    interview.delete_round(rid)
                else:
                    raise ValueError(f"unknown round operation {op}")
                self._json({"ok": True})
            elif path == "/api/stories":  # {id?, title, situation, task, action, result, metrics, competencies} or {from_idea}
                from . import interview

                if p.get("from_idea"):
                    sid = interview.story_from_idea(int(p["from_idea"]))
                else:
                    keys = {"title", "situation", "task", "action", "result", "metrics", "competencies"}
                    if extra := set(p) - keys - {"id"}:
                        raise ValueError(f"unknown story field {sorted(extra)[0]!r}")
                    sid = interview.save_story(sid=int(p["id"]) if p.get("id") else None, **{k: p[k] for k in keys & set(p)})
                self._json({"id": sid})
            elif path.startswith("/api/offers/") and len(parts) == 4:  # {base, bonus_pct, ...}: db.set_offer validates every key
                self._json({"ok": True, "set": db.set_offer(int(parts[3]), **{str(k): v for k, v in p.items()})})
            elif path.startswith("/api/companies/") and len(parts) == 4:
                db.remove_company(int(parts[3]))
                self._json({"ok": True})
            elif path == "/api/profile":  # {text, base?}; the old file is snapshotted to profile-history/ first
                from . import profile

                with profile._LOCK:  # the same lock an import holds while it writes profile.md
                    if p.get("base") and p["base"] != profile.master_base():
                        return self._json({"error": "profile.md changed since you opened it (an import or an AI "
                                                    "change wrote it): copy your text, reload, then redo your edit", "stale": True}, 409)
                    profile.write_master(p["text"])
                self._json({"ok": True, "base": profile.master_base()})
            elif path.startswith("/api/profile/imports/") and len(parts) == 6:  # <pid>/apply {accept, take, to_master} | discard
                from . import profile

                pid, op = parts[4], parts[5]
                if not profile.PID_RE.fullmatch(pid):
                    raise ValueError("bad import id")
                if op == "apply":
                    take = p.get("take") if isinstance(p.get("take"), dict) else {}
                    r = profile.apply_import(pid, p.get("accept") or "new", take, p.get("to_master", True) is not False)
                    self._json(r | _bank_view())
                elif op == "discard":
                    profile.discard_import(pid)
                    self._json({"ok": True})
                else:
                    raise ValueError(f"unknown import operation {op}")
            elif path.startswith("/api/studio/") and len(parts) == 5:  # <vid>/open {file} | use {job_id} | delete | default_look
                from . import studio

                vid, op = parts[3], parts[4]
                if op == "open":
                    f = studio.file_path(vid, p.get("file"))
                    _open_path(f)
                    self._json({"ok": True, "path": str(f)})
                elif op == "use":  # the job's resume becomes this version; the pipeline's Tailor step is held meanwhile
                    jid = db.get_job(int(p.get("job_id") or 0))["id"]
                    with pipeline.claimed(jid, "tailor"):
                        self._json(studio.use_for_job(vid, jid))
                elif op == "delete":
                    studio.delete(vid)
                    self._json({"ok": True})
                elif op == "default_look":
                    self._json({"look": studio.default_look(vid)})
                else:
                    raise ValueError(f"unknown studio operation {op[:20]}")
            elif path == "/api/master/open":  # {ext}: open one master resume file in its default program
                from . import studio

                ext = str(p.get("ext") or "")
                if ext not in {"pdf", "docx", "txt", "md", "html"}:
                    raise ValueError("ext must be pdf, docx, txt, md or html")
                f = studio.files().get(ext)
                if not f:
                    raise SystemExit(f"no master.{ext} yet: Update now builds it")
                _open_path(Path(f))
                self._json({"ok": True, "path": f})
            elif path == "/api/profile/bank":  # {op: add|remove|contact, kind, name, detail} / {op: contact, field, value}
                from . import profile

                op, changed = p.get("op"), 1
                if op == "add":
                    changed = profile.add(p["kind"], p["name"], p.get("detail", ""))["added"]
                elif op == "remove":
                    changed = profile.remove(p["kind"], p["name"])["removed"]
                elif op == "remove_at":  # {kind, index, label}: one role / education / ... entry
                    changed = profile.remove_at(p["kind"], int(p["index"]), str(p.get("label") or ""))["removed"]
                elif op == "contact":
                    profile.set_contact(p["field"], p.get("value", ""))
                else:
                    raise ValueError(f"unknown op {op}")
                self._json({"ok": True, "changed": changed} | _bank_view())
            elif path == "/api/open_folder":  # desktop convenience: reveal a Lodestar folder in the file manager
                import subprocess
                import sys as _sys

                from .config import HOME

                if p.get("which") == "job":  # {id, sub: attach | mail | ""}: a job's folder; never a file in it
                    from .resume import app_dir

                    sub = {"attach": "attach", "mail": "mail", "": ""}[str(p.get("sub") or "")]
                    target = app_dir(db.get_job(int(p["id"]))) / sub
                else:
                    target = {"data": HOME, "exports": HOME / "exports", "backups": HOME / "backups",
                              "applications": HOME / "applications", "log": HOME / "lodestar.log",
                              "resumes": HOME / "resumes", "studio": HOME / "studio"}[p.get("which", "data")]
                if target.suffix != ".log":
                    target.mkdir(parents=True, exist_ok=True)
                elif not target.exists():
                    target.touch()
                if _sys.platform.startswith("win"):
                    import os as _os

                    _os.startfile(str(target))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["open" if _sys.platform == "darwin" else "xdg-open", str(target)])
                self._json({"ok": True, "path": str(target)})
            elif path == "/api/upload":  # {"name": "resume.docx", "data": "<base64>"} -> {"text": ...}
                import base64

                raw = base64.b64decode(p.get("data") or "")
                if len(raw) > 15_000_000:
                    raise ValueError("file too large (15 MB max)")
                self._json({"text": extras.import_document(raw, p.get("name") or "resume.txt")})
            elif path.startswith("/api/docs/") and len(parts) == 4:  # save an edited per-job document
                from .resume import save_doc

                job = db.get_job(int(parts[3]))
                name = p.get("name") or ""
                if name not in DOC_NAMES:
                    raise ValueError(f"not an editable document: {name}")
                save_doc(job, name, p.get("text") or "")  # the version it replaces moves to history/
                self._json({"ok": True, "docs": _docs(job)})
            elif path.startswith("/api/approvals/") and len(parts) == 5:
                pid, op = int(parts[3]), parts[4]
                if op == "approve":
                    self._json(approvals.approve(pid, p.get("edits")))
                elif op == "edit":  # {subject?, body?}: only those two change; the item stays pending
                    self._json(approvals.edit(pid, p.get("subject"), p.get("body")))
                elif op == "reject":
                    approvals.reject(pid, p.get("reason", ""))
                    self._json({"ok": True})
                else:
                    raise ValueError(f"unknown inbox operation {op}")
            elif path == "/api/suggest/dismiss":  # {job_id, kind}: Today's suggested email snoozed for 3 days
                from .drafts import snooze

                snooze(int(p["job_id"]), str(p.get("kind") or ""))
                self._json({"ok": True})
            elif path == "/api/tools":
                self._json(settings.set_tool(p["tool"], p.get("enabled"), p.get("auto")))
            elif path == "/api/prefs":
                settings.set_pref(p["key"], p["value"])
                self._json({"ok": True, "prefs": settings.load()["prefs"]})
            elif path == "/api/comp":  # {op: set|delete, title, city, low, high}: your own market-rate table
                if p.get("op") == "delete":
                    comp.delete(p.get("title", ""), p.get("city") or "*")
                else:
                    comp.set_range(p.get("title", ""), p.get("city") or "*", p["low"], p["high"])
                self._json({"ok": True, "comp": comp.load()})
            elif path == "/api/answers":
                db.save_answer(p["question"], p["answer"], p.get("tags", ""), bool(p.get("private")), source="typed under Answers")
                self._json({"ok": True})
            elif path.startswith("/api/answers/"):
                db.delete_answer(int(parts[3]))
                self._json({"ok": True})
            elif path.startswith("/api/ideas/") and len(parts) == 5:
                iid, op = int(parts[3]), parts[4]
                if op == "status":
                    db.update_idea(iid, status=p["status"])
                elif op == "delete":
                    db.delete_idea(iid)
                self._json({"ok": True})
            elif path == "/api/vault":  # {name, value, user?} stores; {name, delete: true} removes
                if p.get("delete"):
                    vault.delete(p["name"])
                else:
                    vault.set(p["name"], p["value"], p.get("user"))
                self._json({"ok": True})
            elif path.startswith("/api/keys/") and len(parts) == 4:  # link {name, key} | check {name?} | remove {name}
                op = parts[3]
                if op == "link":  # the key goes into the vault and is verified at once; it never comes back
                    self._json(connections.link(p.get("name", ""), p.get("key"), **({"ident": p["id"]} if p.get("id") else {})))
                elif op == "check" and p.get("name"):
                    connections.check(p["name"])
                    self._json(connections.status())
                elif op == "check":  # every linked key + the mailbox: 7 x 15 s must not hold an HTTP thread
                    self._json({"task": start_task("keys_check", {})})
                elif op == "remove":
                    self._json(connections.unlink(p.get("name", "")))
                else:
                    self._json({"error": "not found"}, 404)
            elif path.startswith("/api/email/") and len(parts) == 4:  # connect | test | test_send | disconnect | client | signin | signin_cancel
                from . import mailconn, oauth

                op = parts[3]
                if op == "connect":  # {preset, user, password?, imap_host?, imap_port?, smtp_host?, smtp_port?, smtp_mode?, smtp_user?}
                    keys = {k: p[k] for k in mailconn.KEYS if p.get(k) not in (None, "")}
                    self._json(mailconn.connect(p.get("preset", ""), p.get("user", ""), p.get("password") or None, **keys))
                elif op == "test":
                    self._json(mailconn.test())
                elif op == "test_send":
                    self._json(mailconn.test_send(p.get("to")))
                elif op == "disconnect":
                    self._json(mailconn.disconnect())
                elif op == "client":  # {provider, client_id, client_secret?}: the user's own OAuth client
                    self._json({"clients": oauth.set_client(p.get("provider", ""), p.get("client_id", ""),
                                                            p.get("client_secret") or None)})
                elif op == "signin":  # the browser opens on this machine (the server is bound to 127.0.0.1)
                    oauth._provider(p.get("provider", ""))  # an unknown provider fails here, not in the task
                    self._json({"task": start_task("email_signin", p)})
                elif op == "signin_cancel":
                    self._json({"cancelled": oauth.cancel()})
                else:
                    self._json({"error": "not found"}, 404)
            elif path.startswith("/api/mail/") and len(parts) == 5:  # link {job_id} | unlink | dismiss | track {company?, title?}
                mid, op, out = int(parts[3]), parts[4], {"ok": True}
                if op == "link":  # your own link: never sets the job's contact, never makes the sender trusted
                    db.link_mail(mid, int(p["job_id"]))
                elif op == "unlink":
                    db.unlink_mail(mid)
                elif op == "dismiss":
                    db.dismiss_mail(mid)
                elif op == "track":
                    from .email_monitor import track_mail

                    out["id"] = track_mail(mid, str(p.get("company") or ""), str(p.get("title") or ""))
                else:
                    raise ValueError(f"unknown mail operation {op}")
                self._json(out)
            elif path == "/api/codes/check":  # inline, never start_task: task results are kept in memory
                self._json({"codes": codes.poll()})
            elif path.startswith("/api/codes/") and len(parts) == 5 and parts[4] == "dismiss":
                codes.dismiss(parts[3])
                self._json({"ok": True})
            elif path in ("/api/update/check", "/api/update/apply"):  # background: a fetch, then tests on apply
                self._json({"task": start_task("update_" + parts[3], {"target": str(p.get("target") or "")})})
            elif path == "/api/update/restart":  # desktop app only: relaunch on the new code once nothing is in flight
                from .updater import busy

                if RESTART is None:
                    raise ValueError("restart is offered in the desktop app only: close Lodestar and start it again")
                if why := busy(include_update=True):  # never mid-update: that would leave untested code installed
                    raise ValueError(f"not now: {why}; try again in a moment")
                threading.Timer(0.5, RESTART).start()  # after this answer has left
                self._json({"ok": True})
            elif path.startswith("/api/pipeline/") and len(parts) == 5:  # skip {stage, on} | questions {lines}
                jid, op = int(parts[3]), parts[4]
                if op == "skip":
                    pipeline.skip(jid, str(p.get("stage") or ""), bool(p.get("on", True)))
                    self._json({"ok": True})
                elif op == "questions":  # form questions, one per line (the drawer box)
                    self._json({"added": pipeline.add_form_questions(jid, str(p.get("lines") or "").splitlines(), "drawer")})
                else:
                    raise ValueError(f"unknown pipeline operation {op}")
            elif path.startswith("/api/questions/") and len(parts) == 5:  # answer {text, scope?, private?} | dismiss
                qid, op = int(parts[3]), parts[4]
                if op == "answer":
                    self._json(pipeline.answer(qid, p.get("text"), p.get("scope") or None, bool(p.get("private")) or None))
                elif op == "dismiss":
                    self._json(pipeline.dismiss(qid))
                else:
                    raise ValueError(f"unknown question operation {op}")
            elif path.startswith("/api/view"):  # the document viewer (viewer.py): {ref, opts?, text?, ...}
                from . import viewer

                ref, opts, text = p.get("ref"), p.get("opts"), p.get("text")
                text = None if text is None else str(text)
                try:
                    if path == "/api/view":  # {save?: keep opts for this document, compare?: another ref}
                        self._json(viewer.view(ref, opts, text, bool(p.get("save")), p.get("compare")))
                    elif path == "/api/view/file":  # {fmt, confirm?}: the file's bytes (download, the PDF tab)
                        name, data, info = viewer.export(ref, str(p.get("fmt") or ""), opts, text, bool(p.get("confirm")))
                        self.send_response(200)
                        self.send_header("Content-Type", {"pdf": "application/pdf", "html": "text/html; charset=utf-8",
                                                          "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
                                         .get(name.rsplit(".", 1)[-1], "text/plain; charset=utf-8"))
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("X-Pages", str(info.get("pages") or ""))
                        self.end_headers()
                        self.wfile.write(data)
                    elif path == "/api/view/open":  # {fmt}: written to exports/ and opened (Open in new window)
                        out = viewer.open_file(ref, str(p.get("fmt") or "html"), opts, text, bool(p.get("confirm")))
                        _open_path(Path(out))
                        self._json({"ok": True, "path": out})
                    elif path == "/api/view/save":  # {text, confirm?}: a job document's edit, after the floor + fact guards
                        self._json(viewer.save_text(ref, text or "", bool(p.get("confirm"))))
                    else:
                        self._json({"error": "not found"}, 404)
                except viewer.Unconfirmed as e:  # the fact guard: the UI asks, then sends confirm
                    self._json({"error": str(e), "confirm": True}, 409)
            elif path.startswith("/api/advise/") and len(parts) == 4:  # apply {ids} | reject {ids} | undo {batch}
                if parts[3] == "apply":
                    self._json(advisor.apply(p.get("ids")))
                elif parts[3] == "reject":
                    self._json({"rejected": advisor.decide(p.get("ids"), "rejected")})
                elif parts[3] == "undo":
                    self._json(advisor.undo(p.get("batch")))
                else:
                    self._json({"error": "not found"}, 404)
            elif path.startswith("/api/run/"):
                if parts[3] in ("advise", "advise_auto"):  # a bad scope / target or no provider: 400 before a task starts
                    sc, _ = advisor.check(p.get("scope"), p.get("target"))
                    if parts[3] == "advise_auto" and not sc.auto:
                        raise SystemExit(f"Full AI does not change {sc.label}: use Recommend, then Apply suggestions")
                    if not ai.available():
                        raise SystemExit(f"AI recommendations need an AI provider. {ai.NO_PROVIDER}")
                if parts[3] == "ai_help":  # a bad helper / target or no provider: 400 before a task starts
                    advisor.helper_check(p.get("helper"), p.get("target"))
                if parts[3] in ("pipeline_run", "pipeline_bulk"):
                    _check_pipeline(parts[3], p)
                if parts[3] == "careers_explore":  # no interests or no AI provider: 400 before a task starts
                    if not str(p.get("interests") or "").strip():
                        raise SystemExit("say what interests you: work you enjoy, settings, people, values")
                    if not ai.available():
                        raise SystemExit(f"Explore further needs an AI provider. {ai.NO_PROVIDER}")
                if parts[3] == "careers_search":  # an unknown track: 400 before a task starts
                    from . import careers

                    careers.get_track(int(p.get("track") or 0))
                if parts[3] == "restore":  # a bad pick, a bad zip or something in flight: refused before a task starts
                    if why := extras.restore_busy():
                        raise SystemExit(f"restore refused: {why}; nothing was changed")
                    extras.restore_check(extras.backup_file(p.get("name")))
                if parts[3] == "mock":
                    _check_mock(p)
                if parts[3] in ("qset", "readiness_explain", "job_ai", "intel", "intel_ai", "boost_ai"):
                    db.get_job(int(p.get("id")))
                if parts[3] in ("intel_ai", "boost_ai") and not ai.available():  # said now, not as a failed task
                    raise SystemExit(f"This needs an AI provider. {ai.NO_PROVIDER}")
                self._json({"task": start_task(parts[3], p)})
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:  # a pasted secret never comes back in an error string
            q = p if isinstance(p, dict) else {}
            # "key" is a secret only on /api/keys/ (an AI key); /api/prefs uses it for the preference name, which an
            # error message must still show
            names = ("password", "value", "client_secret") + (("key",) if path.startswith("/api/keys/") else ())
            self._json({"error": connections.redact(str(e), *(str(q.get(k) or "") for k in names))}, 400)


def _open_path(target: Path) -> None:
    """Open a file or folder in the system's default program (desktop convenience)."""
    import os
    import subprocess
    import sys

    if sys.platform.startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])


def start_server(port: int = 8765) -> ThreadingHTTPServer:
    """Serve on a daemon thread and return the server (the desktop window and tests use this)."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="lodestar-http").start()
    return srv


def serve(port: int = 8765, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Lodestar ui at {url}  (Ctrl-C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
