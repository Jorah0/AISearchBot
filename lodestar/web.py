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

from . import __version__, ai, apply, approvals, comp, db, extras, log, loop, mailconn, settings, vault
from .config import ALERTS, PROFILE

STATIC = Path(__file__).parent / "static"
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
DOC_NAMES = {"resume.md", "cover_letter.md", "interview_prep.md", "research.md", "offer.md", "mock_interview.md"}  # editable per-job files
TASKS: dict[str, dict] = {}
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
    return {"bank": profile.load(), "template": profile.is_template(master), "on_file": profile.extras_text(master),
            "linkedin_export_url": profile.LINKEDIN_EXPORT_URL}


def _bases() -> list[dict]:
    from .profile import saved_resumes

    return saved_resumes()


def _docs(job) -> dict:
    from .resume import app_dir

    d = app_dir(job)
    return {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.iterdir())
            if p.suffix in (".md", ".json", ".txt")}


def _act(action: str, p: dict):
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
            imported = profile.import_file(raw, p.get("name") or "resume.txt", source, prov, p.get("ai"))
            return imported | _bank_view()
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
            return {"found": found, "note": "" if prov or ai.available() else  # say why nothing else was classified
                    "no AI provider: only replies tied to a job were filed; other mail waits until you add a key in Setup > Vault"}
        case "watch_run":
            return {"alerts": web_monitor.check_watches()}
        case "search":  # filters: location (or 'remote'), min_salary, posted_within (days), seniority
            from .contacts import with_warm

            errs: list[str] = []  # boards that could not be read: 'nothing found' must not hide 'nothing checked'
            found = with_warm(web_monitor.with_coverage(web_monitor.search(p["query"], p.get("keywords") or "", errors=errs,
                                                                           **_filters(p))[:40]))
            if p.get("rank") and found:
                try:
                    found = web_monitor.rank(found, prov)
                except SystemExit as e:  # no provider / rejected model: the listings still show, unranked, with why
                    errs.append(f"AI rank: {e}")
            return {"results": found, "errors": errs, "boards": len(web_monitor.SOURCES)}
        case "chat":
            return {"reply": ai.chat(p["messages"], _coach_system(), prov)}
        case "mock":
            if not job:
                raise ValueError("pick a job to interview for (add one on the Board first)")
            msgs = p["messages"]
            reply = interview.mock_turn(job, msgs, prov)
            if msgs and str(msgs[-1].get("content", "")).strip().lower() == "done":  # the debrief: keep it with the job
                return {"reply": reply, "path": str(interview.save_mock(job, [*msgs, {"role": "assistant", "content": reply}]))}
            if len(msgs) >= 2 and msgs[-2].get("role") == "assistant" and msgs[-1].get("role") == "user":  # an answer
                return {"reply": reply, "card": interview.score_answer(job, msgs[-2].get("content"), msgs[-1].get("content"),
                                                                       p.get("seconds"), p.get("session"), prov)}
            return {"reply": reply}
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
            found = web_monitor.search(p["query"], p.get("keywords") or "", errors=errs, **_filters(p))
            if not found and len(errs) >= len(web_monitor.SOURCES):
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
        case "doctor":
            from .doctor import checks

            rows = [{"status": s, "what": w, "detail": d} for s, w, d in checks()]
            if p.get("live"):
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
        case "export":  # {fmt: json|csv}; CSV writes one file per table into ~/.lodestar/exports
            return {"path": str(extras.export_data("csv" if p.get("fmt") == "csv" else "json"))}
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
        raise SystemExit("no AI provider configured: store a key such as ANTHROPIC_API_KEY in Setup > Vault, or click "
                         "'Local only (Ollama)'")
    return names


FILTER_KEYS = ("location", "min_salary", "posted_within", "seniority")


def _filters(p: dict) -> dict:
    """The search filters of a request, validated (web_monitor.clean_filters)."""
    from .web_monitor import clean_filters

    return clean_filters(**{k: p.get(k) for k in FILTER_KEYS})


def _job_view(j, idx=None) -> dict:
    """A tracked job for the board: its row plus a sponsor hint, the people you know there and, while it is still only
    saved, stale signals. idx: contacts.warm_index(), built once per board."""
    from .contacts import warm
    from .web_monitor import ghost_signals, sponsor_hint

    return dict(j) | {"ghost": ghost_signals(j) if j["status"] == "saved" else None, "sponsor": sponsor_hint(j["company"]),
                      "warm": warm(j["company"], idx)}


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


# ----------------------------------------------------------------------------- state
def setup_status() -> dict:
    """What a new user still has to do before the AI features work."""
    from .profile import is_template, master_text

    text = master_text()
    return {
        "profile_ready": not is_template(text),  # same rule prompts use; a short real profile counts
        "provider_ready": bool(ai.available()),
        "email_ready": mailconn.status()["verified"],  # saved AND a Connect & test sign-in passed
    }


def state() -> dict:
    from . import interview
    from .ideas import merged as ideas_merged
    from .contacts import ROLES, warm_index

    idx = warm_index()
    return {
        "version": __version__,
        "setup": setup_status(),
        "loop": dict(loop.STATUS),
        "jobs": [_job_view(j, idx) for j in db.list_jobs()],
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
        "bases": _bases(),
        "answers": [dict(r) for r in db.list_answers() if r["star"] is None],  # stories are listed apart
        "stories": interview.stories(),
        "competencies": interview.COMPETENCIES,
        "round_kinds": interview.KINDS,
        "round_outcomes": interview.OUTCOMES,
        "mock_sessions": interview.sessions(),
        "ideas": [ideas_merged(r) for r in db.list_ideas()],
        "idea_statuses": db.IDEA_STATUSES,
        "providers": {n: (n in ai.available()) for n in ai.PROVIDERS},
        "watches": [dict(w) | {"filters": db.watch_filters(w)} for w in db.watches()],
        "companies": [dict(c) for c in db.companies()],
        "alerts": ALERTS.read_text(encoding="utf-8").splitlines()[-30:] if ALERTS.is_file() else [],
        "vault": [{"name": n, "user": u} for n, u in vault.names() if n not in mailconn.MANAGED],  # Disconnect manages those
        "obsidian_dir": str(extras.vault_root() / "jobs"),  # Export tracker to Obsidian asks before writing there
        "comp": comp.load(),
        "upcoming": [i | {"when": f"{i['when']:%a %Y-%m-%d %H:%M}"} for i in extras.upcoming_interviews(14)],
        "today": loop.agenda(),
        "profile_path": str(PROFILE),
        "usage_today": ai.usage(1)["total"],
        "usage": ai.usage(30),
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
        return u.path in PUBLIC and bool(t) and secrets.compare_digest(t, CAPTURE_TOKEN)

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
                html = (STATIC / "index.html").read_bytes().replace(b"__TOKEN__", TOKEN.encode()).replace(b"__CAPTURE__", CAPTURE_TOKEN.encode())
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
                f = (STATIC / name)
                if not f.is_file() or f.resolve().parent != STATIC.resolve():  # resolved path must sit directly in static/
                    return self._json({"error": "not found"}, 404)
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", {".svg": "image/svg+xml", ".css": "text/css", ".js": "text/javascript"}.get(f.suffix, "application/octet-stream") + "; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._json(state())
            elif path.startswith("/api/jobs/"):
                from . import interview
                from .contacts import job_people, warm

                job = db.get_job(int(path.split("/")[3]))
                self._json({"job": dict(job), "events": [dict(e) for e in db.events(job["id"])], "docs": _docs(job),
                            "people": job_people(job["id"]), "warm": warm(job["company"]),
                            "rounds": interview.rounds(job["id"]), "bank": interview.question_bank(job, False)[:30],
                            "stress": interview.story_prompt(job), "mail": [dict(r) for r in db.list_mail(job["id"])]})
            elif path == "/api/mail":  # ?job=ID (that job's mail, both ways) or ?unmatched=1
                from urllib.parse import parse_qs

                q = parse_qs(urlparse(self.path).query)
                job = q.get("job", [""])[0]
                self._json({"mail": [dict(r) for r in db.list_mail(int(job) if job else None, bool(q.get("unmatched")))]})
            elif path == "/api/contacts":
                from .contacts import ROLES, rows

                self._json({"contacts": rows(), "roles": ROLES})
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
            elif path == "/api/profile":
                self._json({"text": PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else ""})
            elif path == "/api/profile/bank":
                self._json(_bank_view())
            elif path == "/api/email/status":  # connection and presets; never the password
                from . import mailconn

                self._json({"status": mailconn.status(), "presets": mailconn.PRESETS})
            elif path == "/api/autofill":  # the autofill bookmarklet reads this; it never submits a form
                # CORS-open to the page you are on: send only the fields it types, not the private answer bank
                self._json({k: v for k, v in extras.autofill_data().items() if k != "answers"})
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path, p = urlparse(self.path).path, {}
        if not self._host_ok():
            return self._json({"error": "bad host"}, 421)
        if not self._authed():
            n = self.headers.get("Content-Length") or ""
            self.rfile.read(min(int(n), 1_000_000) if n.isdigit() else 0)  # drained: an unread body resets the socket on Windows
            return self._json({"error": "missing or wrong token; reload the Lodestar page"}, 403)
        try:
            p = self._body()
            parts = path.split("/")
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
                title, company = split_title(p.get("title", ""))
                jid = db.add_job(company or "Unknown company", title or "Unknown role", http_only(p.get("url")),
                                 (p.get("desc") or "")[:12000], f"captured from {p.get('url', '')}")
                self._json({"id": jid, "company": company, "title": title})
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
                elif op == "fields":  # tracker details; db.set_fields whitelists and validates every key
                    db.set_fields(jid, **{str(k): v for k, v in p.items()})
                elif op == "skip":  # {term}: JD coverage keyword "not mine" on/off; answers with the recomputed coverage
                    from .resume import toggle_skip

                    out["coverage"] = toggle_skip(db.get_job(jid), p.get("term"))
                elif op == "rounds":  # {round?, kind, at, interviewers, notes, questions_asked, outcome}: validated
                    from .interview import log_round

                    out["round_id"] = log_round(jid, **{str(k): v for k, v in p.items()})
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
            elif path == "/api/profile":  # the old file is snapshotted to profile-history/ first
                from .profile import write_master

                write_master(p["text"])
                self._json({"ok": True})
            elif path == "/api/profile/bank":  # {op: add|remove|contact, kind, name, detail} / {op: contact, field, value}
                from . import profile

                op, changed = p.get("op"), 1
                if op == "add":
                    changed = profile.add(p["kind"], p["name"], p.get("detail", ""))["added"]
                elif op == "remove":
                    changed = profile.remove(p["kind"], p["name"])["removed"]
                elif op == "contact":
                    profile.set_contact(p["field"], p.get("value", ""))
                else:
                    raise ValueError(f"unknown op {op}")
                self._json({"ok": True, "changed": changed} | _bank_view())
            elif path == "/api/open_folder":  # desktop convenience: reveal a Lodestar folder in the file manager
                import subprocess
                import sys as _sys

                from .config import HOME

                target = {"data": HOME, "exports": HOME / "exports", "backups": HOME / "backups",
                          "applications": HOME / "applications", "log": HOME / "lodestar.log"}[p.get("which", "data")]
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
                db.save_answer(p["question"], p["answer"], p.get("tags", ""), bool(p.get("private")))
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
            elif path.startswith("/api/email/") and len(parts) == 4:  # connect | test | test_send | disconnect
                from . import mailconn

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
            elif path.startswith("/api/run/"):
                self._json({"task": start_task(parts[3], p)})
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:
            self._json({"error": str(e)}, 400)


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
