"""Local web dashboard: `lodestar ui` -> http://127.0.0.1:8765  (stdlib only, binds localhost only).

Long-running AI actions run in a thread and are polled via /api/tasks/<id> so the page never blocks.
"""
import json
import secrets
import threading
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import ai, apply, approvals, db, extras, log, settings, vault
from .config import ALERTS, PROFILE

STATIC = Path(__file__).parent / "static"
TOKEN = secrets.token_urlsafe(24)          # per launch: the page embeds it, every API call must present it
PUBLIC = {"/api/capture", "/api/autofill"}  # the only routes other origins (bookmarklets) may call; they carry ?t=TOKEN
TASKS: dict[str, dict] = {}
COACH = ("You are a sharp, practical career coach and job-search strategist. Use the candidate's profile and tracker "
         "below to give specific, actionable advice. Be brief and direct.")


# ----------------------------------------------------------------------------- actions (run in threads)
def _coach_system() -> str:
    from .resume import profile_text

    tracker = "\n".join(f"#{j['id']} {j['status']} {j['company']} - {j['title']}" for j in db.list_jobs()[:40])
    return f"{COACH}\n\nPROFILE:\n{profile_text()}\n\nTRACKER:\n{tracker or '(empty)'}\n\nSTATS: {db.stats()}"


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
        case "tailor":
            out = resume.tailor(job, council, prov)
            if p.get("docx"):
                resume.export_docx(out)
            return {"path": str(out), "docs": _docs(job)}
        case "cover":
            return {"path": str(resume.cover_letter(job, council, prov, p.get("tone") or "confident, warm, specific")), "docs": _docs(job)}
        case "gap":
            return {"gap": resume.gap(job, prov), "docs": _docs(job)}
        case "prep":
            return {"path": str(interview.prep(job, council, prov)), "docs": _docs(job)}
        case "review":
            return {"text": resume.review(p.get("text") or resume.profile_text(), prov)}
        case "reply":
            return {"text": email_monitor.draft_reply(job, p.get("intent", "polite follow-up"), prov)}
        case "email_check":
            return {"found": email_monitor.check(int(p.get("days", 3)), dry=bool(p.get("dry")), provider=prov)}
        case "watch_run":
            return {"alerts": web_monitor.check_watches()}
        case "search":
            found = web_monitor.search(p["query"], p.get("keywords") or "")
            if p.get("rank"):
                found = web_monitor.rank(found, prov)
            return {"results": found[:40]}
        case "chat":
            return {"reply": ai.chat(p["messages"], _coach_system(), prov)}
        case "mock":
            from . import interview

            return {"reply": ai.chat(p["messages"], interview.mock_system(job), prov)}
        case "council":
            return ai.council(p["prompt"])
        case "outreach":
            return {"text": extras.outreach(job, p.get("person", ""), p.get("channel", "linkedin"), prov)}
        case "ics":
            return {"path": str(extras.ics(job, extras.parse_when(p["when"]), int(p.get("minutes", 60)))), "docs": _docs(job)}
        case "digest":
            return {"text": extras.digest(int(p.get("days", 7)), bool(p.get("send")), prov)}
        case "obsidian":
            return {"path": str(extras.export_obsidian())}
        case "answer":
            return apply.answer(job, p["question"], prov)
        case "checklist":
            return {"checklist": apply.checklist(job)}
        case "followup":
            return apply.followup(job, prov)
        case "thanks":
            return apply.thanks(job, p.get("interviewer", ""), p.get("notes", ""), prov)
        case "offer":
            out = apply.offer(job, p.get("salary", ""), p.get("bonus", ""), p.get("equity", ""), p.get("benefits", ""),
                              p.get("deadline", ""), p.get("notes", ""), prov)
            return {"path": str(out), "text": out.read_text(encoding="utf-8"), "docs": _docs(job)}
        case "auto_track":
            found = web_monitor.search(p["query"], p.get("keywords") or "")
            return {"results": apply.auto_track(found[:40], prov)}
        case "craft":
            from . import ideas

            return {"ideas": ideas.craft(p.get("topic", "strategy"), p.get("extra", ""), job, p.get("role", ""),
                                         int(p.get("n", 8)), not p.get("single"), prov)}
        case "refine":
            from . import ideas

            return {"idea": ideas.refine(int(p["idea_id"]), p.get("feedback", ""), prov)}
        case "research":
            out = extras.research(job, prov)
            return {"path": str(out), "text": out.read_text(encoding="utf-8"), "docs": _docs(job)}
        case "providers_test":
            res: dict[str, str] = {}
            for n in ai.available():
                try:
                    res[n] = ai.ask("Reply with the single word OK.", provider=n).strip()[:40]
                except Exception as e:
                    res[n] = f"FAIL {e}"
            return res
    raise ValueError(f"unknown action {action}")


def start_task(action: str, params: dict) -> str:
    tid = uuid.uuid4().hex[:8]
    while len(TASKS) > 200:  # ponytail: keep the last 200 results; job actions are also logged as events
        TASKS.pop(next(iter(TASKS)))
    TASKS[tid] = {"status": "running", "action": action}

    def run():
        try:
            TASKS[tid] = {"status": "done", "action": action, "result": _act(action, params)}
        except BaseException as e:  # SystemExit from helpers carries the user-facing message
            log.get("tasks").exception("%s failed", action)
            TASKS[tid] = {"status": "error", "action": action, "error": str(e) or traceback.format_exc()[-400:]}

    threading.Thread(target=run, daemon=True).start()
    return tid


def split_title(page_title: str) -> tuple[str, str]:
    """'Role - Company | LinkedIn' / 'Role - Company - City | Indeed.com' -> (role, company). Best effort."""
    t = page_title.split("|")[0].strip()
    for sep in (" - ", " – ", " at ", " @ "):
        if sep in t:
            role, rest = t.split(sep, 1)
            return role.strip(), rest.split(" - ")[0].split(" – ")[0].strip()
    return t, ""


# ----------------------------------------------------------------------------- state
def state() -> dict:
    return {
        "jobs": [dict(j) for j in db.list_jobs()],
        "statuses": db.STATUSES,
        "stats": db.stats(),
        "followups": [j["id"] for j in db.needs_followup(7)],
        "variants": db.variant_stats(),
        "pending": [dict(r) | {"payload": json.loads(r["payload"])} for r in db.list_pending("pending")],
        "decided": [dict(r) for r in db.list_pending(None, 15) if r["status"] != "pending"],
        "tools": settings.table(),
        "prefs": settings.load()["prefs"],
        "answers": [dict(r) for r in db.list_answers()],
        "ideas": [dict(r) | json.loads(r["body"]) for r in db.list_ideas()],
        "idea_statuses": db.IDEA_STATUSES,
        "providers": {n: (n in ai.available()) for n in ai.PROVIDERS},
        "watches": [dict(w) for w in db.watches()],
        "alerts": ALERTS.read_text(encoding="utf-8").splitlines()[-30:] if ALERTS.is_file() else [],
        "vault": [{"name": n, "user": u} for n, u in vault.names()],
        "profile_path": str(PROFILE),
        "usage_today": ai.usage(1)["total"],
    }


# ----------------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):  # terminal stays quiet; the rotating log keeps the access line
        log.get("web").info(fmt, *a)

    def _public(self) -> bool:
        return urlparse(self.path).path in PUBLIC

    def _cors(self):  # bookmarklets post from linkedin.com / indeed.com tabs: only the public routes get CORS
        if self._public():
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _authed(self) -> bool:
        """Same-origin page sends X-Lodestar-Token; bookmarklets send ?t=. Static files and / need nothing."""
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return True
        from urllib.parse import parse_qs

        return self.headers.get("X-Lodestar-Token") == TOKEN or parse_qs(u.query).get("t", [None])[0] == TOKEN

    def do_OPTIONS(self):
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
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._authed():
            return self._json({"error": "missing or wrong token; reload the Lodestar page"}, 403)
        try:
            if path == "/":
                html = (STATIC / "index.html").read_bytes().replace(b"__TOKEN__", TOKEN.encode())
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif path == "/logo.svg" or path.startswith("/static/"):
                name = "logo.svg" if path == "/logo.svg" else path[8:]
                f = STATIC / name
                if "/" in name or not f.is_file():
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
                job = db.get_job(int(path.split("/")[3]))
                self._json({"job": dict(job), "events": [dict(e) for e in db.events(job["id"])], "docs": _docs(job)})
            elif path.startswith("/api/tasks/"):
                self._json(TASKS.get(path.split("/")[3], {"status": "unknown"}))
            elif path == "/api/profile":
                self._json({"text": PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else ""})
            elif path == "/api/autofill":  # the autofill bookmarklet reads this; it never submits a form
                self._json(extras.autofill_data())
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path, p = urlparse(self.path).path, {}
        if not self._authed():
            return self._json({"error": "missing or wrong token; reload the Lodestar page"}, 403)
        try:
            p = self._body()
            parts = path.split("/")
            if path == "/api/jobs":
                from .util import read_source

                jd = read_source(p["jd"]) if p.get("jd") else None
                url = p.get("url") or (p["jd"] if p.get("jd", "").startswith("http") else None)
                self._json({"id": db.add_job(p["company"], p["title"], url, jd, p.get("notes"))})
            elif path == "/api/capture":  # bookmarklet: {title, url, desc} from the open tab
                title, company = split_title(p.get("title", ""))
                jid = db.add_job(company or "Unknown company", title or "Unknown role", p.get("url"),
                                 (p.get("desc") or "")[:12000], f"captured from {p.get('url', '')}")
                self._json({"id": jid, "company": company, "title": title})
            elif path.startswith("/api/jobs/") and len(parts) == 5:
                jid, op = int(parts[3]), parts[4]
                if op == "status":
                    db.set_status(jid, p["status"], p.get("note", ""))
                elif op == "note":
                    j = db.get_job(jid)
                    db.update_job(jid, notes=((j["notes"] or "") + "\n" + p["text"]).strip())
                    db.add_event(jid, "note", p["text"])
                elif op == "jd":
                    from .util import read_source

                    db.update_job(jid, jd=read_source(p["source"]))
                elif op == "delete":
                    db.delete_job(jid)
                self._json({"ok": True})
            elif path == "/api/watches":
                db.add_watch(p["url"] if not p.get("search") else f"search:{p['url']}", p.get("keywords", ""))
                self._json({"ok": True})
            elif path.startswith("/api/watches/"):
                db.remove_watch(int(parts[3]))
                self._json({"ok": True})
            elif path == "/api/profile":
                PROFILE.write_text(p["text"], encoding="utf-8")
                self._json({"ok": True})
            elif path.startswith("/api/approvals/") and len(parts) == 5:
                pid, op = int(parts[3]), parts[4]
                self._json(approvals.approve(pid, p.get("edits")) if op == "approve" else (approvals.reject(pid, p.get("reason", "")) or {"ok": True}))
            elif path == "/api/tools":
                self._json(settings.set_tool(p["tool"], p.get("enabled"), p.get("auto")))
            elif path == "/api/prefs":
                settings.set_pref(p["key"], p["value"])
                self._json({"ok": True, "prefs": settings.load()["prefs"]})
            elif path == "/api/answers":
                db.save_answer(p["question"], p["answer"], p.get("tags", ""))
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
            elif path == "/api/vault":
                vault.set(p["name"], p["value"], p.get("user"))
                self._json({"ok": True})
            elif path.startswith("/api/run/"):
                self._json({"task": start_task(parts[3], p)})
            else:
                self._json({"error": "not found"}, 404)
        except BaseException as e:
            self._json({"error": str(e)}, 400)


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
