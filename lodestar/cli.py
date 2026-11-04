"""lodestar command line. Run `lodestar -h` or `python -m lodestar -h`."""
import argparse
import getpass
import json
import sys
from pathlib import Path

from . import ai, db, vault
from .config import ALERTS, APPS_DIR, HOME, PROFILE, setting
from .util import read_source

COACH = (
    "You are a sharp, practical career coach and job-search strategist. Use the candidate's profile and application "
    "tracker below to give specific, actionable advice. Be brief and direct."
)


# ---------------------------------------------------------------- helpers
def _p(x):
    print(json.dumps(x, indent=2) if isinstance(x, (dict, list)) else x)


def _job_line(j) -> str:
    return f"#{j['id']:<4} {j['status']:<10} {j['company'][:24]:<24} {j['title'][:38]:<38} {j['updated_at'][:10]}"


def _tracker_summary() -> str:
    rows = db.list_jobs()
    return "\n".join(_job_line(j) for j in rows[:40]) or "(no jobs tracked yet)"


# ---------------------------------------------------------------- commands
def cmd_init(a):
    from .resume import PROFILE_TEMPLATE

    APPS_DIR.mkdir(exist_ok=True)
    if not PROFILE.is_file():
        PROFILE.write_text(PROFILE_TEMPLATE, encoding="utf-8")
    db.con()
    print(f"Lodestar (lodestar) home: {HOME}\n")
    print(f"1. Edit your master resume:   {PROFILE}")
    print("2. Add an AI key:             lodestar vault set ANTHROPIC_API_KEY   (or OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY ...)")
    print("3. Optional email monitor:    lodestar vault set IMAP_USER ; lodestar vault set IMAP_PASS")
    print("4. Track a job:               lodestar jobs add \"Acme\" \"Backend Engineer\" --jd https://acme.com/jobs/123")
    print("5. Tailor + check fit:        lodestar resume tailor 1 ; lodestar resume gap 1 ; lodestar resume cover 1")
    print("6. Automate:                  lodestar run --every 30")


def cmd_providers(a):
    from . import settings

    avail = ai.available()
    if a.op == "models":
        for n in (a.names or avail):
            try:
                ms = ai.list_models(n)
                print(f"{n} ({len(ms)}): " + ", ".join(ms[:40]) + (" ..." if len(ms) > 40 else ""))
            except Exception as e:
                print(f"{n}: {e}")
        return
    if a.op == "local":
        settings.set_pref("provider", "ollama")
        settings.set_pref("council_providers", "ollama")
        print("local-only preset: provider=ollama, council_providers=ollama" + ("" if setting("OLLAMA_MODEL") else
              "  (set OLLAMA_MODEL=<model> in .env to enable Ollama)"))
        return
    for name, p in ai.PROVIDERS.items():
        state = "ready" if name in avail else f"missing {p['key'] or 'OLLAMA_MODEL'}"
        print(f"{name:<11} {ai.model_for(name):<32} {state}")
    if avail:
        print(f"\ndefault: {ai.default_provider()}  (override with LODESTAR_PROVIDER)")
    if a.test:
        for n in avail:
            try:
                print(f"{n} ({ai.model_for(n)}): {ai.ask('Reply with the single word OK.', provider=n).strip()[:40]}")
            except (Exception, SystemExit) as e:
                print(f"{n}: FAIL {e}")


def cmd_usage(a):
    u = ai.usage(a.days)
    print(f"{'provider/model':<40} {'calls':>6} {'input':>10} {'output':>10}")
    for k, v in u.items():
        print(f"{k:<40} {v['calls']:>6} {v['input']:>10} {v['output']:>10}")


def cmd_ask(a):
    print(ai.ask(a.prompt, provider=a.provider))


def cmd_council(a):
    r = ai.council(a.prompt)
    if a.all:
        for n, t in r["answers"].items():
            print(f"\n===== {n} =====\n{t}")
        print("\n===== SYNTHESIS =====")
    print(r["synthesis"])


def cmd_chat(a):
    from .resume import profile_text

    system = f"{COACH}\n\nPROFILE:\n{profile_text()}\n\nTRACKER:\n{_tracker_summary()}\n\nSTATS: {db.stats()}"
    history = []
    print("Career coach ready. Ctrl-C or 'quit' to exit.")
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in ("quit", "exit"):
            break
        history.append({"role": "user", "content": q})
        reply = ai.chat(history, system, a.provider)
        history.append({"role": "assistant", "content": reply})
        print(f"\ncoach> {reply}")


def cmd_vault(a):
    if a.op == "set":
        secret = a.value or getpass.getpass(f"value for {a.name}: ")
        vault.set(a.name, secret, a.user)
        print(f"stored {a.name}")
    elif a.op == "get":
        v = vault.get(a.name)
        u = vault.user(a.name)
        print(f"{a.name}: user={u or '-'} secret={v if a.show else ('*' * 8 if v else '(none)')}")
    elif a.op == "rm":
        vault.delete(a.name)
        print(f"removed {a.name}")
    else:
        for n, u in vault.names():
            print(f"{n:<28} {u}")


def cmd_jobs(a):
    op = a.op
    if op == "add":
        jd = read_source(a.jd) if a.jd else None
        url = a.url or (a.jd if a.jd and a.jd.startswith("http") else None)
        jid = db.add_job(a.company, a.title, url, jd, a.notes)
        print(f"added job #{jid}" + (" (JD captured)" if jd else ""))
    elif op == "list":
        for j in db.list_jobs(a.status):
            print(_job_line(j))
    elif op == "show":
        j = db.get_job(a.id)
        _p({k: (j[k][:800] if isinstance(j[k], str) else j[k]) for k in j.keys()})
        for e in db.events(a.id):
            print(f"  {e['ts']}  {e['kind']:<14} {e['detail'] or ''}")
    elif op == "status":
        db.set_status(a.id, a.status, a.note or "")
        print(f"#{a.id} -> {a.status}")
    elif op == "note":
        j = db.get_job(a.id)
        db.update_job(a.id, notes=((j["notes"] or "") + "\n" + a.text).strip())
        db.add_event(a.id, "note", a.text)
    elif op == "jd":
        db.update_job(a.id, jd=read_source(a.source), **({"url": a.source} if a.source.startswith("http") else {}))
        print(f"#{a.id} JD updated")
    elif op == "rm":
        db.delete_job(a.id)
        print(f"deleted #{a.id}")
    elif op == "contact":
        db.update_job(a.id, contact_email=a.email, contact_name=a.name or "")
        print(f"#{a.id} contact = {a.name or ''} <{a.email}>")
    elif op == "checklist":
        from .apply import checklist

        for c in checklist(db.get_job(a.id)):
            print(f"[{'x' if c['done'] else ' '}] {c['item']}" + ("" if c["done"] else f"   -> {c['next']}"))
    elif op == "stats":
        _p(db.stats())
    elif op == "funnel":
        f = db.funnel()
        print(f"{'stage':<11} {'reached':>8} {'advanced':>9} {'conversion':>11} {'median days':>12}")
        for st, d in f["stages"].items():
            conv = f"{d['conversion']:.0%}" if d["conversion"] is not None else "-"
            med = d["median_days_to_next"] if d["median_days_to_next"] is not None else "-"
            print(f"{st:<11} {d['reached']:>8} {d['advanced']:>9} {conv:>11} {med!s:>12}")
        print("rejected after:", f["rejected_from"] or "none")
        print("by source:", {k: f"{v['positive']}/{v['tracked']} positive" for k, v in f["by_source"].items()})
    elif op == "packet":
        from .extras import packet

        print(f"wrote {packet(db.get_job(a.id))}")
    elif op == "followups":
        rows = db.needs_followup(a.days)
        print(f"{len(rows)} application(s) quiet for {a.days}+ days:")
        for j in rows:
            print(_job_line(j))
    elif op == "search":
        from . import web_monitor

        found = web_monitor.search(a.query, a.keywords or "")
        if a.rank:
            found = web_monitor.rank(found, a.provider)
        for i, j in enumerate(found[: a.limit]):
            score = f"[{j['score']:>3}] " if "score" in j else ""
            print(f"{i:>2}. {score}{j['title']} @ {j['company']} ({j['location'] or 'n/a'}) {j['salary']} <{j['source']}>\n    {j['url']}" + (f"\n    {j['why']}" if j.get("why") else ""))
        if a.save:
            for idx in a.save:
                j = found[idx]
                jid = db.add_job(j["company"], j["title"], j["url"], j["desc"], f"found via {j['source']}")
                print(f"saved #{jid}: {j['title']} @ {j['company']}")
        if a.auto:
            from .apply import auto_track

            for j in auto_track(found[: a.limit], a.provider):
                print(f"fit {j['score']}: {j['title']} @ {j['company']} -> {j['proposal'].get('status')}")


def cmd_resume(a):
    from . import resume

    op = a.op
    if op == "profile":
        print(PROFILE)
        return
    if op == "review":
        print(resume.review(read_source(a.file) if a.file else resume.profile_text(), a.provider))
        return
    if op == "export":
        print(resume.export_docx(a.file))
        return
    if op == "import":
        from .extras import import_document

        text = import_document(Path(a.file).read_bytes(), a.file)
        if a.merge:
            text = resume.merge_into_profile(text, a.provider)
        if a.save:
            PROFILE.write_text(text, encoding="utf-8")
            print(f"profile {'merged and ' if a.merge else ''}saved: {PROFILE}")
        else:
            print(text)
            print("\n(nothing saved; add --save, or --merge --save to fold it into your master profile)")
        return
    if op == "adjust":
        if a.job:
            from .resume import app_dir

            target = app_dir(db.get_job(a.job)) / (a.doc or "resume.md")
            kind = "cover letter" if "cover" in target.name else "resume"
        else:
            target, kind = PROFILE, "master profile"
        new = resume.adjust_text(target.read_text(encoding="utf-8"), a.instruction, kind, a.provider)
        if a.save:
            target.write_text(new, encoding="utf-8")
            print(f"saved {target}")
        else:
            print(new)
            print(f"\n(nothing saved; add --save to write {target})")
        return
    job = db.get_job(a.id)
    if op == "tailor":
        out = resume.tailor(job, a.council, a.provider)
        print(f"wrote {out}")
        if a.docx:
            print(f"wrote {resume.export_docx(out)}")
    elif op == "cover":
        out = resume.cover_letter(job, a.council, a.provider, a.tone, a.words)
        print(f"wrote {out}")
        if a.docx:
            print(f"wrote {resume.export_docx(out)}")
    elif op == "gap":
        _p(resume.gap(job, a.provider))


def cmd_email(a):
    from . import email_monitor

    if a.op == "check":
        found = email_monitor.check(a.days, dry=a.dry, provider=a.provider)
        print(f"\n{len(found)} relevant email(s)")
    elif a.op == "reply":
        print(email_monitor.draft_reply(db.get_job(a.id), a.intent, a.provider))


def cmd_watch(a):
    from . import web_monitor

    if a.op == "add":
        db.add_watch(a.url, a.keywords or "")
        print("watch added; first run takes a baseline snapshot")
    elif a.op == "search-add":
        db.add_watch(f"search:{a.query}", a.keywords or "")
        print(f"will alert on new listings for '{a.query}'")
    elif a.op == "list":
        for w in db.watches():
            print(f"#{w['id']:<3} {w['url']:<60} kw={w['keywords'] or '-'} last={w['last_seen'] or 'never'}")
    elif a.op == "rm":
        db.remove_watch(a.id)
    elif a.op == "run":
        alerts = web_monitor.check_watches()
        print(f"{len(alerts)} alert(s)")


def cmd_interview(a):
    from . import interview

    job = db.get_job(a.id)
    if a.op == "prep":
        print(f"wrote {interview.prep(job, a.council, a.provider)}")
    else:
        interview.mock(job, a.provider)


def cmd_run(a):
    """The automation loop (see loop.py): email -> watches -> follow-ups -> reminders -> sync/digest/backup."""
    from . import loop

    loop.run(a)


def cmd_alerts(a):
    print(ALERTS.read_text(encoding="utf-8")[-4000:] if ALERTS.is_file() else "(no alerts yet)")


def cmd_ui(a):
    from .web import serve

    serve(a.port, open_browser=not a.no_open)


def cmd_app(a):
    """The personal workbot: monitor loop in a background thread + web UI in the foreground, one process."""
    import threading

    from .web import serve

    if not a.no_loop:
        a.once = False
        threading.Thread(target=cmd_run, args=(a,), daemon=True).start()
        print(f"monitor loop running every {a.every} min")
    serve(a.port, open_browser=not a.no_open)


def cmd_doctor(a):
    from .doctor import report

    raise SystemExit(0 if report(a.live) < 2 else 1)


def cmd_desktop(a):
    """The desktop app: server + monitor loop in this process, the UI in a native window. What the shortcut runs."""
    import threading

    from . import desktop
    from .web import start_server

    port = a.port or desktop.free_port()
    srv = start_server(port)
    if not a.no_loop:
        a.once = False
        threading.Thread(target=cmd_run, args=(a,), daemon=True, name="lodestar-loop").start()
    print(f"Lodestar desktop on http://127.0.0.1:{port}  (close the window to stop)")
    try:
        desktop.open_window(port)
    finally:
        srv.shutdown()


def cmd_outreach(a):
    from . import extras

    print(extras.outreach(db.get_job(a.id), a.person or "", a.channel, a.provider))


def cmd_digest(a):
    from . import extras

    print(extras.digest(a.days, a.send, a.provider))


def cmd_ics(a):
    from . import extras

    print(extras.ics(db.get_job(a.id), extras.parse_when(a.when), a.minutes))


def cmd_export(a):
    from . import extras

    if a.target == "obsidian":
        print(f"wrote {extras.export_obsidian(a.folder)}")
    else:
        print(f"wrote {extras.export_data(a.target, Path(a.out) if a.out else None)}")


def cmd_backup(a):
    from . import extras

    print(f"wrote {extras.backup(Path(a.out) if a.out else None, a.keep)}")


def cmd_schedule(a):
    from . import extras

    print(extras.schedule(a.op, a.every))


def cmd_tools(a):
    from . import settings

    if a.op == "list":
        print(f"{'tool':<22} {'enabled':<8} {'auto':<6} description")
        for t in settings.table():
            print(f"{t['tool']:<22} {str(t['enabled']):<8} {str(t['auto']):<6} {t['description']}")
        print("\nprefs:", json.dumps(settings.load()["prefs"]))
        print("enabled+manual = proposes into `lodestar inbox`; enabled+auto = runs immediately; disabled = never")
    elif a.op == "set":
        settings.set_pref(a.name, a.value)
        print(f"{a.name} = {settings.pref(a.name)}")
    else:
        flag = {"enable": dict(enabled=True), "disable": dict(enabled=False), "auto": dict(auto=True), "manual": dict(auto=False)}[a.op]
        print(a.name, settings.set_tool(a.name, **flag))


def cmd_inbox(a):
    rows = db.list_pending(None if a.all else "pending")
    if not rows:
        print("inbox empty")
    for r in rows:
        print(f"#{r['id']:<4} {r['status']:<8} {r['ts'][:16]} [{r['tool']}/{r['kind']}] {r['summary']}")
        if a.verbose:
            p = json.loads(r["payload"])
            for k in ("to", "subject", "body", "chosen_time", "status", "company", "title", "question", "answer"):
                if p.get(k):
                    print(f"       {k}: {str(p[k])[:600]}")


def cmd_approve(a):
    from . import approvals

    edits = {k: v for k, v in (("subject", a.subject), ("body", Path(a.body).read_text(encoding="utf-8") if a.body else None), ("to", a.to)) if v}
    for pid in a.ids:
        r = approvals.approve(pid, edits)
        print(f"#{pid} {r['status']}: {r.get('result', '')}")


def cmd_reject(a):
    from . import approvals

    for pid in a.ids:
        approvals.reject(pid, a.reason or "")
        print(f"#{pid} rejected")


def cmd_answers(a):
    from . import apply

    if a.op == "list":
        for r in db.list_answers():
            print(f"#{r['id']:<3} Q: {r['question'][:90]}\n     A: {r['answer'][:300].replace(chr(10), ' ')}\n")
    elif a.op == "add":
        db.save_answer(a.question, a.answer, a.tags or "")
        print("saved")
    elif a.op == "rm":
        db.delete_answer(a.id)
    elif a.op == "ask":
        r = apply.answer(db.get_job(a.id), a.question, a.provider)
        print(r["answer"])
        print(f"\n[reused: {r['reused'] or 'none'}] [save -> {r['proposal'].get('status')}]")


def cmd_followup(a):
    from . import apply

    r = apply.followup(db.get_job(a.id), a.provider)
    print(f"Subject: {r['draft']['subject']}\n\n{r['draft']['body']}\n\n-> {r['proposal']}")


def cmd_thanks(a):
    from . import apply

    r = apply.thanks(db.get_job(a.id), a.interviewer or "", a.notes or "", a.provider)
    print(f"Subject: {r['draft']['subject']}\n\n{r['draft']['body']}\n\n-> {r['proposal']}")


def cmd_offer(a):
    from . import apply

    print(f"wrote {apply.offer(db.get_job(a.id), a.salary or '', a.bonus or '', a.equity or '', a.benefits or '', a.deadline or '', a.notes or '', a.provider)}")


def cmd_ideas(a):
    from . import ideas

    if a.op == "topics":
        for k, v in ideas.TOPICS.items():
            print(f"{k:<12} {v}")
    elif a.op == "craft":
        job = db.get_job(a.job) if a.job else None
        out = ideas.craft(a.topic, a.extra or "", job, a.role or "", a.n, not a.single, a.provider)
        print(f"{len(out)} idea(s) saved. Next: lodestar ideas status ID planned | lodestar ideas refine ID \"feedback\"\n")
        for i in out:
            print(ideas.render(i), "\n")
    elif a.op == "list":
        rows = [r for r in ideas.rows() if (not a.topic or r["topic"] == a.topic) and (not a.status or r["status"] == a.status)]
        for r in rows:
            print(f"#{r['id']:<4} {r['status']:<8} {r['topic']:<11} {r['score']:>6}  {r['title']}")
        if not rows:
            print("no ideas yet: lodestar ideas craft strategy")
    elif a.op == "show":
        r = db.get_idea(a.id)
        print(ideas.render(dict(r) | json.loads(r["body"])))
    elif a.op == "refine":
        print(ideas.render(ideas.refine(a.id, a.feedback, a.provider)))
    elif a.op == "status":
        db.update_idea(a.id, status=a.status)
        print(f"#{a.id} -> {a.status}")
    elif a.op == "rm":
        db.delete_idea(a.id)


def cmd_research(a):
    from .extras import research

    print(f"wrote {research(db.get_job(a.id), a.provider)}")


def cmd_features(a):
    """Self-generating feature inventory: every command, every automated tool, every preference (inventory.py)."""
    from .inventory import markdown

    text = markdown(build())
    print(text if a.markdown else text.replace("| ", "").replace(" |", "").replace("|---|---|---|---|", "").replace("|---|---|", ""))


def cmd_comp(a):
    from . import comp

    if a.op == "set":
        comp.set_range(a.title, a.city or "*", a.low, a.high)
        print(f"recorded {a.title} / {a.city or '*'}: {a.low}-{a.high}")
    elif a.op == "lookup":
        print(comp.lookup(a.title, a.city or "") or "no match")
    else:
        for t, cities in comp.load().items():
            for c, (lo, hi) in cities.items():
                print(f"{t:<30} {c:<16} {lo:>9} - {hi:<9}")
        if not comp.load():
            print("empty: lodestar comp set \"software engineer\" austin 130000 170000")


def cmd_variants(a):
    rows = db.variant_stats()
    if not rows:
        print("no tailored resumes sent yet (variants appear once tailored applications leave 'saved')")
    for v in rows:
        print(f"{v['variant']}  sent {v['applied']:<3} positive {v['positive']:<3} rejected {v['rejected']:<3} "
              f"response {v['response_rate']:.0%}  interview {v['interview_rate']:.0%}")


# ---------------------------------------------------------------- parser
def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="lodestar", description="AI job-search assistant")
    ap.add_argument("-p", "--provider", help=f"AI provider: {', '.join(ai.PROVIDERS)}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create profile + db, show next steps").set_defaults(f=cmd_init)
    s = sub.add_parser("providers", help="list/test configured AI providers; `models` lists ids; `local` = Ollama-only preset")
    s.add_argument("op", nargs="?", choices=["list", "models", "local"], default="list")
    s.add_argument("names", nargs="*", help="providers to query for `models`")
    s.add_argument("--test", action="store_true")
    s.set_defaults(f=cmd_providers)
    s = sub.add_parser("usage", help="token usage per provider/model from ~/.lodestar/usage.jsonl")
    s.add_argument("--days", type=int, default=30)
    s.set_defaults(f=cmd_usage)
    s = sub.add_parser("ask", help="one-off question to an AI provider")
    s.add_argument("prompt")
    s.set_defaults(f=cmd_ask)
    s = sub.add_parser("council", help="ask ALL providers and synthesize the best answer")
    s.add_argument("prompt")
    s.add_argument("--all", action="store_true", help="also print each provider's answer")
    s.set_defaults(f=cmd_council)
    sub.add_parser("chat", help="career-coach chat with your profile + tracker loaded").set_defaults(f=cmd_chat)
    sub.add_parser("alerts", help="show recent alerts").set_defaults(f=cmd_alerts)
    s = sub.add_parser("ui", help="local web dashboard (http://127.0.0.1:8765)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", help="don't open a browser")
    s.set_defaults(f=cmd_ui)

    s = sub.add_parser("vault", help="OS-keyring credential store (API keys, site logins, email)")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("set"); x.add_argument("name"); x.add_argument("value", nargs="?"); x.add_argument("--user")
    x = v.add_parser("get"); x.add_argument("name"); x.add_argument("--show", action="store_true")
    x = v.add_parser("rm"); x.add_argument("name")
    v.add_parser("list")
    s.set_defaults(f=cmd_vault)

    s = sub.add_parser("jobs", help="application tracker + job search")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add"); x.add_argument("company"); x.add_argument("title"); x.add_argument("--url"); x.add_argument("--jd", help="url, file, or text"); x.add_argument("--notes")
    x = v.add_parser("list"); x.add_argument("--status", choices=db.STATUSES)
    x = v.add_parser("show"); x.add_argument("id", type=int)
    x = v.add_parser("status"); x.add_argument("id", type=int); x.add_argument("status", choices=db.STATUSES); x.add_argument("--note")
    x = v.add_parser("note"); x.add_argument("id", type=int); x.add_argument("text")
    x = v.add_parser("jd"); x.add_argument("id", type=int); x.add_argument("source", help="url, file, or text")
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    x = v.add_parser("contact", help="recruiter / hiring manager email for replies and follow-ups"); x.add_argument("id", type=int); x.add_argument("email"); x.add_argument("--name")
    x = v.add_parser("checklist", help="what is done and what is next for this application"); x.add_argument("id", type=int)
    v.add_parser("stats")
    v.add_parser("funnel", help="stage conversion, median days per stage, rejections by stage, outcomes by source")
    x = v.add_parser("packet", help="zip everything about one application (documents, JD, notes)"); x.add_argument("id", type=int)
    x = v.add_parser("followups"); x.add_argument("--days", type=int, default=7)
    x = v.add_parser("search", help="free job APIs: remotive, arbeitnow, remoteok")
    x.add_argument("query"); x.add_argument("--keywords", help="comma list, must appear in title/desc")
    x.add_argument("--rank", action="store_true", help="AI fit score vs your profile"); x.add_argument("--limit", type=int, default=25)
    x.add_argument("--save", type=int, nargs="*", help="result indexes to add to tracker")
    x.add_argument("--auto", action="store_true", help="AI-judge results and propose/track strong fits (tool: auto_track)")
    s.set_defaults(f=cmd_jobs)

    s = sub.add_parser("resume", help="tailor, gap-check, cover letter, review, export")
    v = s.add_subparsers(dest="op", required=True)
    for name in ("tailor", "cover", "gap"):
        x = v.add_parser(name); x.add_argument("id", type=int); x.add_argument("--council", action="store_true", help="pool all providers")
        if name == "tailor":
            x.add_argument("--docx", action="store_true")
        if name == "cover":
            x.add_argument("--tone", default="confident, warm, specific")
            x.add_argument("--words", type=int, default=300)
            x.add_argument("--docx", action="store_true")
    x = v.add_parser("import", help="bring in an existing resume (.docx/.pdf/.md/.txt); --merge folds it into the profile")
    x.add_argument("file"); x.add_argument("--merge", action="store_true"); x.add_argument("--save", action="store_true")
    x = v.add_parser("adjust", help="AI-revise the master profile or a job document with an instruction")
    x.add_argument("instruction"); x.add_argument("--job", type=int); x.add_argument("--doc", help="resume.md (default) or cover_letter.md"); x.add_argument("--save", action="store_true")
    x = v.add_parser("review"); x.add_argument("file", nargs="?", help="defaults to master profile")
    x = v.add_parser("export"); x.add_argument("file", help="markdown -> .docx")
    v.add_parser("profile", help="print master profile path")
    s.set_defaults(f=cmd_resume)

    s = sub.add_parser("email", help="IMAP monitor: classify replies, update tracker")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("check"); x.add_argument("--days", type=int, default=3); x.add_argument("--dry", action="store_true", help="report only, change nothing")
    x = v.add_parser("reply"); x.add_argument("id", type=int); x.add_argument("--intent", required=True, help="e.g. 'accept interview, propose Tue/Wed afternoons'")
    s.set_defaults(f=cmd_email)

    s = sub.add_parser("watch", help="career-page change alerts + saved job searches")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add"); x.add_argument("url"); x.add_argument("--keywords")
    x = v.add_parser("search-add"); x.add_argument("query"); x.add_argument("--keywords")
    v.add_parser("list")
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    v.add_parser("run")
    s.set_defaults(f=cmd_watch)

    s = sub.add_parser("interview", help="prep pack or live mock interview")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("prep"); x.add_argument("id", type=int); x.add_argument("--council", action="store_true")
    x = v.add_parser("mock"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_interview)

    def loop_args(p):
        p.add_argument("--every", type=int, default=30, help="minutes")
        p.add_argument("--days", type=int, default=2, help="email lookback")
        p.add_argument("--followup", type=int, default=7, help="nudge after N quiet days")
        p.add_argument("--no-email", dest="email", action="store_false")

    s = sub.add_parser("run", help="automation loop: email + watches + follow-up nudges")
    loop_args(s)
    s.add_argument("--once", action="store_true")
    s.set_defaults(f=cmd_run)

    s = sub.add_parser("doctor", help="check the install: Python, modules, WebView2, keyring, data folder, profile, providers, mail")
    s.add_argument("--live", action="store_true", help="also make one real call per configured provider")
    s.set_defaults(f=cmd_doctor)

    s = sub.add_parser("desktop", help="the desktop app: native window + monitor loop in one process (the shortcut)")
    loop_args(s)
    s.add_argument("--port", type=int, default=None, help="default: first free port from 8765")
    s.add_argument("--no-loop", action="store_true", help="window only")
    s.set_defaults(f=cmd_desktop)

    s = sub.add_parser("app", help="the workbot: monitor loop + web UI in one process")
    loop_args(s)
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true")
    s.add_argument("--no-loop", action="store_true", help="UI only")
    s.set_defaults(f=cmd_app)

    s = sub.add_parser("outreach", help="draft a LinkedIn note or email to a recruiter / hiring manager")
    s.add_argument("id", type=int); s.add_argument("--person", help='"Name, title"'); s.add_argument("--channel", choices=["linkedin", "email"], default="linkedin")
    s.set_defaults(f=cmd_outreach)
    s = sub.add_parser("digest", help="weekly summary: moves, follow-ups, alerts, coach plan")
    s.add_argument("--days", type=int, default=7); s.add_argument("--send", action="store_true", help="also email it (LODESTAR_NOTIFY_EMAIL)")
    s.set_defaults(f=cmd_digest)
    s = sub.add_parser("ics", help="calendar file for an interview (+ prep reminder 2 days before)")
    s.add_argument("id", type=int); s.add_argument("--when", required=True, help='"YYYY-MM-DD HH:MM"'); s.add_argument("--minutes", type=int, default=60)
    s.set_defaults(f=cmd_ics)
    s = sub.add_parser("export", help="tracker -> Obsidian vault, or a JSON / CSV dump of all tables")
    s.add_argument("target", choices=["obsidian", "json", "csv"]); s.add_argument("--folder", default="jobs"); s.add_argument("--out")
    s.set_defaults(f=cmd_export)
    s = sub.add_parser("backup", help="zip your data folder (profile, tracker, documents); keeps the last 7")
    s.add_argument("--out"); s.add_argument("--keep", type=int, default=7)
    s.set_defaults(f=cmd_backup)
    s = sub.add_parser("schedule", help="install/remove a background task that runs `lodestar run --once`")
    s.add_argument("op", choices=["install", "remove"]); s.add_argument("--every", type=int, default=30)
    s.set_defaults(f=cmd_schedule)
    sub.add_parser("variants", help="which tailored-resume variant gets responses").set_defaults(f=cmd_variants)
    s = sub.add_parser("comp", help="your market-rate table, used by gap checks and offer evaluation")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    x = v.add_parser("set"); x.add_argument("title"); x.add_argument("city", nargs="?"); x.add_argument("low", type=int); x.add_argument("high", type=int)
    x = v.add_parser("lookup"); x.add_argument("title"); x.add_argument("city", nargs="?")
    s.set_defaults(f=cmd_comp)

    s = sub.add_parser("tools", help="turn automated AI tools on/off, manual (inbox) or auto; set preferences")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    for op in ("enable", "disable", "auto", "manual"):
        x = v.add_parser(op); x.add_argument("name")
    x = v.add_parser("set", help="preference: name, availability, auto_track_min_score, followup_days, reply_to_confirmations, signature")
    x.add_argument("name"); x.add_argument("value")
    s.set_defaults(f=cmd_tools)
    s = sub.add_parser("inbox", help="actions waiting for your approval")
    s.add_argument("--all", action="store_true", help="include decided items"); s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(f=cmd_inbox)
    s = sub.add_parser("approve", help="execute inbox item(s), optionally editing the email first")
    s.add_argument("ids", type=int, nargs="+"); s.add_argument("--subject"); s.add_argument("--body", help="file with the replacement body"); s.add_argument("--to")
    s.set_defaults(f=cmd_approve)
    s = sub.add_parser("reject", help="discard inbox item(s)")
    s.add_argument("ids", type=int, nargs="+"); s.add_argument("--reason")
    s.set_defaults(f=cmd_reject)
    s = sub.add_parser("answers", help="answer bank for application-form questions")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    x = v.add_parser("add"); x.add_argument("question"); x.add_argument("answer"); x.add_argument("--tags")
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    x = v.add_parser("ask", help="draft an answer for a job's form question"); x.add_argument("id", type=int); x.add_argument("question")
    s.set_defaults(f=cmd_answers)
    s = sub.add_parser("followup", help="draft a follow-up email (sent via inbox if a contact is known)")
    s.add_argument("id", type=int); s.set_defaults(f=cmd_followup)
    s = sub.add_parser("thanks", help="draft a post-interview thank-you note")
    s.add_argument("id", type=int); s.add_argument("--interviewer"); s.add_argument("--notes", help="something specific from the conversation")
    s.set_defaults(f=cmd_thanks)
    s = sub.add_parser("offer", help="evaluate an offer against your preferences; negotiation plan")
    s.add_argument("id", type=int)
    for f in ("salary", "bonus", "equity", "benefits", "deadline", "notes"):
        s.add_argument(f"--{f}")
    s.set_defaults(f=cmd_offer)

    s = sub.add_parser("ideas", help="idea crafting: brainstorm across providers, critique, rank, refine, track")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("topics", help="list preset topics")
    x = v.add_parser("craft", help="diverge -> critique -> converge; saves ranked ideas")
    x.add_argument("topic", help="strategy|resume|gap|outreach|stories|pivot|questions|negotiation|tools|custom")
    x.add_argument("--job", type=int, help="ground in a tracked job"); x.add_argument("--role", help="target role")
    x.add_argument("--extra", help="extra instructions / the custom topic text"); x.add_argument("--n", type=int, default=8)
    x.add_argument("--single", action="store_true", help="one provider + critic pass instead of the council")
    x = v.add_parser("list"); x.add_argument("--topic"); x.add_argument("--status", choices=db.IDEA_STATUSES)
    x = v.add_parser("show"); x.add_argument("id", type=int)
    x = v.add_parser("refine", help="rewrite an idea with your feedback"); x.add_argument("id", type=int); x.add_argument("feedback")
    x = v.add_parser("status"); x.add_argument("id", type=int); x.add_argument("status", choices=db.IDEA_STATUSES)
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_ideas)
    s = sub.add_parser("research", help="company research pack for an interview (job page, site, web search)")
    s.add_argument("id", type=int); s.set_defaults(f=cmd_research)
    s = sub.add_parser("features", help="self-generated inventory of every command, tool, preference and topic")
    s.add_argument("--markdown", action="store_true"); s.set_defaults(f=cmd_features)
    return ap


def main(argv=None):
    from . import log

    a = build().parse_args(argv)
    args = list(argv or sys.argv[1:])
    if "vault" in args[:2] and "set" in args[:3]:  # never log a secret given on the command line
        args = args[:args.index("set") + 2] + ["***"] * max(0, len(args) - args.index("set") - 2)
    log.get("cli").info("%s", " ".join(args))
    try:
        a.f(a)
    except SystemExit as e:  # user-facing errors are SystemExit(message); log them too
        if e.code not in (None, 0):
            log.get("cli").warning("%s", e.code)
        raise
    except Exception:
        log.get("cli").exception("unhandled error")
        raise


if __name__ == "__main__":
    main()
