"""lodestar command line. Run `lodestar -h` or `python -m lodestar -h`."""
import argparse
import getpass
import json
import sys
from pathlib import Path

from . import ai, db, settings, vault
from .config import ALERTS, APPS_DIR, HOME, PROFILE
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


def _details(j) -> str:
    """Tracker fields worth a glance on a list line: pay, fit, JD coverage, excitement, workplace, deadline, tags."""
    lo, hi = j["salary_min"], j["salary_max"]
    pay = (f"{j['currency'] or ''} {lo:,}-{hi:,}" if lo is not None and hi is not None and lo != hi
           else f"{j['currency'] or ''} {(hi if hi is not None else lo):,}" if (lo, hi) != (None, None) else "")
    bits = [pay.strip(), f"fit {j['fit_score']}" if j["fit_score"] is not None else "",
            f"coverage {j['match_score']}" if j["match_score"] is not None else "",
            "*" * (j["excitement"] or 0), j["remote"] or "", f"due {j['deadline']}" if j["deadline"] else "",
            f"[{j['tags']}]" if j["tags"] else ""]
    return "  ".join(b for b in bits if b)


def _file_text(path: str) -> str:
    """A resume file (.docx / .pdf / .md / .txt) as plain text, the way the profile importer reads it."""
    from .extras import import_document

    return import_document(Path(path).read_bytes(), path)


def _coverage_text(cov: dict) -> str:
    c = cov["categories"]
    lines = [f"JD coverage {cov['score']}/100"]
    lines += [f"  {k:<10} {c[k]['score']:>3}%  {c[k]['matched']}/{c[k]['total']}" for k in ("hard", "soft", "title", "education", "other")
              if c[k]["total"]]
    if cov["title_match"]:
        lines.append(f"  title \"{cov['title_match']['title']}\": {'found' if cov['title_match']['found'] else 'not found'} in the resume")
    if cov["education_required"]:
        lines.append(f"  posting names {', '.join(cov['education_required'])}: {'covered' if c['education']['matched'] else 'not found in the resume'}")
    miss = [k for k in cov["keywords"] if not k["matched"] and not k["skipped"]]
    lines.append("missing (most mentioned first): " + (", ".join(f"{k['term']} ({k['jd_count']}x)" for k in miss) or "none"))
    lines.append("matched: " + (", ".join(k["term"] for k in cov["keywords"] if k["matched"] and not k["skipped"]) or "none"))
    if skipped := [k["term"] for k in cov["keywords"] if k["skipped"]]:
        lines.append("not mine (left out of the score): " + ", ".join(skipped))
    if cov["stuffing"]:
        lines.append("repeated far more often than the posting does (reads as stuffing): " + ", ".join(cov["stuffing"]))
    return "\n".join(lines + [cov["note"]])


def _issues_text(r: dict) -> str:
    out = []
    for sev in ("high", "medium", "low", "info"):
        if items := [i for i in r["issues"] if i["severity"] == sev]:
            out.append(f"{sev.upper()} ({len(items)})")
            out += [f"  {'line ' + str(i['line']) + ': ' if i.get('line') else ''}{i['text']}\n      -> {i['hint']}" for i in items]
    return "\n".join(out) or "no issues found"


def _bullets_text(job, data: dict) -> str:
    rows = data["proposals"]
    out = [f"#{job['id']} {job['company']} - {job['title']}: {sum(r['changed'] for r in rows)} of {len(rows)} bullets rewritten "
           f"(coverage now {data['coverage']}); bullets follow the suggested order within each role"]
    for r in rows:
        out.append(f"{r['id']:>3}. [{r['role']}] {'accept' if r['accepted'] else 'keep original' if r['changed'] else 'unchanged'}")
        out.append(f"     was: {r['original']}")
        if r["changed"]:
            out.append(f"     now: {r['proposed'] or '(drop this bullet)'}" + (f"   + {', '.join(r['added_terms'])}" if r["added_terms"] else ""))
        if r["reason"]:
            out.append(f"     why: {r['reason']}")
        if r["unsupported"]:
            out.append(f"     FLAG unsupported (not found in your profile or bank): {', '.join(r['unsupported'])}")
        if r["new_numbers"]:
            out.append(f"     FLAG new number (not in the original bullet): {', '.join(r['new_numbers'])}")
    out.append(f"saved bullets.json. Build the resume: lodestar resume tailor {job['id']} --accept unflagged  (or all, or 1,3,5)")
    return "\n".join(out)


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
    print("2. Link an AI key:            lodestar keys link anthropic   (or openai, gemini, groq, openrouter, mistral; checked at once)")
    print("3. Optional email:            lodestar email connect   (app password: Gmail, Yahoo, iCloud, Fastmail, Zoho, AOL, Proton, custom)")
    print("                              or lodestar email signin google|microsoft   (any 2-step method; docs/CONNECT.md)")
    print("4. Track a job:               lodestar jobs add \"Acme\" \"Backend Engineer\" --jd https://acme.com/jobs/123")
    print("5. Tailor + check fit:        lodestar resume tailor 1 ; lodestar resume gap 1 ; lodestar resume cover 1")
    print("6. Automate:                  lodestar run --every 30")


def cmd_providers(a):
    avail = ai.available()
    if a.op == "models":
        for n in (a.names or avail):
            try:
                ms = ai.list_models(n)
                print(f"{n} ({len(ms)}): " + ", ".join(ms[:40]) + (" ..." if len(ms) > 40 else ""))
            except (Exception, SystemExit) as e:  # one provider's rejected key or model never hides the others
                print(f"{n}: {e}")
        return
    if a.op == "local":
        print(ai.local_preset())
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
    from .resume import candidate_text

    system = f"{COACH}\n\nPROFILE:\n{candidate_text(strict=False)}\n\nTRACKER:\n{_tracker_summary()}\n\nSTATS: {db.stats()}"
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
        try:
            vault.set(a.name, secret, a.user)
        except ValueError as e:  # Enter at the prompt: one line, not a traceback
            raise SystemExit(str(e)) from None
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
        url = a.url or (a.jd if a.jd and a.jd.startswith("http") else None)
        jd, failed = None, ""
        try:
            jd = read_source(a.jd) if a.jd else None
        except Exception as e:  # an unreachable posting still gets its card, with the URL; only a fetch lands here
            if not (a.jd or "").startswith(("http://", "https://")):
                raise
            failed = str(getattr(e, "reason", "") or e)[:160]
        jid = db.add_job(a.company, a.title, url, jd, a.notes)
        print(f"added job #{jid}" + (" (JD captured)" if jd else ""))
        if failed:
            print(f"could not fetch the posting ({failed}); add the JD later with: lodestar jobs jd {jid} <url|file>")
    elif op == "list":
        for j in db.list_jobs(a.status, a.sort, a.remote, a.min_salary, a.tag):
            unknown = "  pay unknown" if a.min_salary and db._pay(j) is None else ""
            print(f"{_job_line(j)}  {_details(j)}{unknown}".rstrip())
    elif op == "set":
        changed = db.set_fields(a.id, **_kv(a.pairs, db.FIELDS))
        print(f"#{a.id} " + ", ".join(f"{k}={'' if v is None else v}" for k, v in changed.items()))
    elif op == "show":
        j = db.get_job(a.id)
        _p({k: (j[k][:800] if isinstance(j[k], str) else j[k]) for k in j.keys()})
        from .connections import local
        from .listings import activity

        print("listing activity (newest first):")
        for x in activity(a.id):
            how = ""
            if x["src"] == "mail":
                how = ("verified sender" if x["trusted"] else "unverified") + (f", {x['reason']}" if x["reason"] else "")
            print(f"  {local(x['at'] or '')}  {x['src']:<5} {x.get('dir', ''):<3} {x['kind'][:18]:<18} {x['text'] or ''}"
                  + (f"  ({how})" if how else ""))
    elif op == "status":
        db.set_status(a.id, a.status, a.note or "")
        print(f"#{a.id} -> {a.status}")
    elif op == "note":
        j = db.get_job(a.id)
        db.update_job(a.id, notes=((j["notes"] or "") + "\n" + a.text).strip())
        db.add_event(a.id, "note", a.text)
    elif op == "jd":
        from .resume import set_jd

        set_jd(a.id, read_source(a.source), **({"url": a.source} if a.source.startswith("http") else {}))
        print(f"#{a.id} JD updated")
    elif op == "rm":
        db.delete_job(a.id)
        print(f"deleted #{a.id}")
    elif op == "contact":
        from .contacts import EMAIL_RE, from_job_contact

        if not EMAIL_RE.fullmatch(a.email.strip()):
            raise SystemExit(f"not an email address: {a.email[:80]}")
        db.update_job(a.id, contact_email=a.email.strip(), contact_name=a.name or "")
        cid = from_job_contact(a.id, a.name or "", a.email)
        print(f"#{a.id} contact = {a.name or ''} <{a.email.strip()}>  (contact #{cid}, linked as recruiter)")
    elif op == "checklist":
        from .apply import checklist

        for c in checklist(db.get_job(a.id)):
            mark = "x" if c["done"] else "-" if c["na"] else " "
            print(f"[{mark}] {c['item']}" + (" (n/a yet)" if c["na"] else "" if c["done"] else f"   -> {c['next']}"))
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
    elif op == "all":  # All jobs: every listing any source found
        from . import listings

        r = listings.query(min_fit=a.min_fit or 0, sources=[a.source] if a.source else (), new=a.new, show=a.show,
                           sort=a.sort, offset=a.offset)
        print(f"{r['total']} listing(s)" + (f", showing {a.offset + 1}-{a.offset + len(r['rows'])}" if r["rows"] else "")
              + (" · sources: " + ", ".join(f"{k} {v}" for k, v in sorted(r["sources"].items())) if r["sources"] else ""))
        for x in r["rows"]:
            fit = "fit  - " if x["fit_score"] is None else f"fit {x['fit_score']:>2}" + ("~" if x.get("fit_partial") else " ")
            flags = "".join(f" [{t}]" for t, on in (("new", x["new"]), (f"tracked #{x['job_id']}", x["job_id"]),
                                                     ("dismissed", x["dismissed"]), ("reposted", x["reposted_at"])) if on)
            print(f"L{x['id']:<5} {fit} {x['title']} @ {x['company']} ({x['location'] or 'n/a'}) {x['salary']}"
                  f" <{', '.join(x['sources'])}>{flags}\n         {x['url']}"
                  + "".join(f"\n         {c}" for c in x.get("fit_chips", [])))
    elif op == "track-listing":
        from . import listings

        jid = listings.track(a.id)
        print(f"tracked as #{jid}")
    elif op == "followups":
        from . import settings

        days = a.days or int(settings.pref("followup_days") or 7)
        rows = db.needs_followup(days)
        print(f"{len(rows)} application(s) quiet for {days}+ days:")
        for j in rows:
            print(_job_line(j))
    elif op == "search":
        from . import web_monitor

        from .contacts import with_warm

        errs: list[str] = []
        ran: list[str] = []
        found = with_warm(web_monitor.search(a.query, a.keywords or "", errors=errs, ran=ran, **_search_filters(a))[: a.limit])
        if errs:
            print(("no job board could be reached, nothing was checked: " if len(errs) >= len(ran)
                   else "could not read: ") + "; ".join(errs), file=sys.stderr)
        if bad := [i for i in a.save or [] if not 0 <= i < len(found)]:  # checked before anything is printed or saved
            raise SystemExit(f"--save {' '.join(map(str, bad))}: no such result (this search returned {len(found)}, "
                             f"numbered from 0)")
        if a.rank:
            try:
                found = web_monitor.rank(found, a.provider)
            except SystemExit as e:  # no provider / rejected model: show the listings unranked and say why (as the web does)
                print(f"not ranked: {e}", file=sys.stderr)
        for i, j in enumerate(found):
            score = f"[{j['score']:>3}] " if "score" in j else ""
            print(f"{i:>2}. {score}{j['title']} @ {j['company']} ({j['location'] or 'n/a'}) {j['salary']} <{', '.join(j['sources'])}>\n    {j['url']}"
                  + (f"\n    {j['why']}" if j.get("why") else "") + "".join(f"\n    {x}" for x in _listing_notes(j)))
        if a.save:
            for idx in a.save:
                j = found[idx]
                jid = db.add_job(j["company"], j["title"], j["url"], web_monitor.jd_with_salary(j), f"found via {j['source']}",
                                 **web_monitor.listing_fields(j))
                print(f"saved #{jid}: {j['title']} @ {j['company']}")
        if a.auto:
            from .apply import auto_track

            for j in auto_track(found[: a.limit], a.provider):
                print(f"fit {j['score']}: {j['title']} @ {j['company']} -> {j['proposal'].get('status')}")


def _search_filters(a) -> dict:
    from .web_monitor import clean_filters

    return clean_filters(a.location, a.min_salary, a.posted_within, a.seniority)


def _listing_notes(j) -> list[str]:
    """The extra lines a search result carries: coverage, unknown fields, stale signals, sponsor hint, other links."""
    from .web_monitor import GHOST_SHOW

    out = [f"tracked as #{j['tracked']}"] if j.get("tracked") else []
    if (f := j.get("fit")) and isinstance(f, dict):
        out.append(f"fit {f['score']}" + (" (partial)" if f.get("partial") else "") + ": "
                   + "; ".join(f"{c['sign']} {c['text']}" for c in f.get("chips", []) if not c.get("info"))[:300])
    unknown = [k.split("_")[0] for k in ("salary_unknown", "location_unknown", "date_unknown") if j.get(k)]
    if unknown:
        out.append(f"unknown {', '.join(unknown)} (kept: the filter could not tell)")
    if (g := j.get("ghost")) and g["score"] >= GHOST_SHOW:
        out.append(f"possibly stale ({g['score']}): {'; '.join(g['reasons'])}")
    if s := j.get("sponsor"):
        out.append(f"possible H-1B sponsor ({s['approvals']} approvals in your USCIS data)")
    if w := j.get("warm"):
        out.append(f"you know {len(w)} here: " + ", ".join(p["name"] for p in w[:5]) + (" ..." if len(w) > 5 else ""))
    out += [f"also at {u}" for u in j.get("urls", [])[1:]]
    return out


def cmd_companies(a):
    from . import web_monitor

    if a.op == "add":
        c = web_monitor.add_company(a.source, a.name or "", a.keywords or "")
        print(f"watching #{c['id']} {c['name']} ({c['vendor']}:{c['slug']}); the next monitor cycle records what is open, later postings alert")
    elif a.op == "list":
        for c in db.companies():
            print(f"#{c['id']:<3} {c['name'][:28]:<28} {c['vendor'] + ':' + c['slug']:<36} kw={c['keywords'] or '-'} "
                  f"last={c['last_seen'] or 'never'}" + (f"  ERROR {c['last_error']}" if c["last_error"] else ""))
        if not db.companies():
            print("none yet: lodestar companies add https://boards.greenhouse.io/<slug>")
        print(web_monitor.NO_FEED_NOTE)
    elif a.op == "rm":
        db.remove_company(a.id)
        print(f"removed #{a.id}")


def _tiers(v: str) -> list[int]:
    try:
        return [int(x) for x in str(v).replace(" ", "").split(",") if x != ""]
    except ValueError:
        raise SystemExit("tiers are numbers 0-6, comma-separated (e.g. 0,1)") from None


def _print_suggestion(sg: dict) -> None:
    print(f"  {sg['code']}  {sg['title']}  [{sg['tier_label']}]  ({sg['source']})")
    for head, key in (("Why it fits", "why"), ("What is missing", "missing"), ("What does not transfer", "not_transfer"),
                      ("To close the gap", "close_gap")):
        if sg[key]:
            print(f"      {head}: " + "; ".join(sg[key]))


def cmd_careers(a):
    """lodestar careers ...: career discovery (careers.py): suggestions from your profile, career tracks, track search."""
    from . import careers, occupations

    if a.op == "suggest":
        out = careers.suggest(tiers=tuple(_tiers(a.tiers)), limit=a.limit, show_excluded=a.show_excluded)
        if out["note"]:
            print(out["note"])
        for key, label in careers.CLASSES.items():
            group = [sg for sg in out["suggestions"] if sg["cls"] == key]
            if group:
                print(f"\n{label}")
                for sg in group:
                    _print_suggestion(sg)
        print("\n" + occupations.meta().get("credit", ""))
    elif a.op == "explore":
        out = careers.explore(a.interests, a.provider)
        print("Explore further (one AI call; each role is matched to O*NET, or labelled when it is not)")
        for sg in out["suggestions"]:
            print(f"  [{sg['cls_label']}]")
            _print_suggestion(sg)
        if not out["suggestions"]:
            print("  nothing usable came back")
    elif a.op == "occupation":
        o = occupations.get(a.code)
        if not o:
            raise SystemExit(f"unknown O*NET occupation: {a.code}")
        print(f"{o['code']}  {o['title']}  (Job Zone {o.get('zone') or '?'}: {occupations.ZONE_PREP.get(o.get('zone'), 'unknown')})")
        print(o.get("desc") or "")
        for head, key in (("Also called", "titles"), ("Core tasks", "tasks"), ("Technology", "tech")):
            if o.get(key):
                print(f"{head}: " + "; ".join(o[key][:8]))
        rel = [f"{c} {(occupations.get(c) or {}).get('title', '')}" for c in o.get("related") or []][:8]
        if rel:
            print("Related: " + "; ".join(rel))
        if note := careers.regulated(a.code):
            print(f"Licensing: {note}")
        print(occupations.meta().get("credit", ""))
    elif a.op == "tracks":
        ts = careers.tracks()
        for t in ts:
            tiers = ", ".join(careers.TIERS[x] for x in t["tiers"])
            print(f"#{t['id']:<3} {t['label'][:28]:<28} {t['intent']:<13} {'on ' if t['enabled'] else 'off'} tiers: {tiers}")
            print(f"     titles: {', '.join(t['titles']) or '-'}  occupations: {', '.join(t['codes']) or '-'}"
                  + (f"  location: {t['location']}" if t["location"] else ""))
        if not ts:
            print("no career tracks yet: lodestar careers track-add NAME --intent desired_field --titles \"a, b\"")
    elif a.op == "track-add":
        tid = careers.add_track(a.label, a.intent, titles=a.titles or "", codes=a.codes or "",
                                tiers=_tiers(a.tiers) if a.tiers else None, exclusions=a.exclude or "",
                                location=a.location or "", training=a.training, priority=a.priority)
        t = careers.get_track(tid)
        print(f"track #{tid} {t['label']}: searches {', '.join(careers.search_titles(t))}")
    elif a.op == "track-set":
        fields = _kv(a.pairs, ("label", "intent", "titles", "codes", "tiers", "exclusions", "location", "training",
                               "priority", "enabled"))
        if "tiers" in fields:
            fields["tiers"] = _tiers(fields["tiers"])
        t = careers.update_track(a.id, **fields)
        print(f"track #{t['id']} {t['label']}: searches {', '.join(careers.search_titles(t))}")
    elif a.op == "track-rm":
        careers.remove_track(a.id)
        print(f"removed track #{a.id}")
    elif a.op == "search":
        out = careers.search_track(a.id, location=a.location)
        print(f"searched: {', '.join(out['titles'])}")
        for r in out["results"]:
            print(f"  {r.get('title', '')[:50]:<50} {r.get('company', '')[:24]:<24} {r.get('url', '')}")
        cov = out["coverage"]
        if not cov["checked"]:
            print("nothing was checked: no job board answered")
        print(f"boards asked: {', '.join(cov['asked']) or 'none'} ({len(cov['asked'])} of {cov['total']})")
        if cov["failed"]:
            print("failed: " + "; ".join(cov["failed"]))
        if cov["not_ready"]:
            print("not set up (need a key): " + ", ".join(cov["not_ready"]))
        print(cov["note"])


def cmd_audit(a):
    """lodestar audit: the append-only trail of policy decisions and executor runs (policy.py)."""
    import json as _json

    from . import policy

    rows = policy.log(a.limit)
    for r in rows:
        why = ", ".join(_json.loads(r["reasons"] or "[]"))
        print(f"{r['at']}  {r['action']:<26} {r['result']:<17} {r['tool'] or '-':<18} {r['target'] or '-':<9}"
              + (f" inbox #{r['approval_id']}" if r["approval_id"] else "") + (f"  ({why})" if why else ""))
    if not rows:
        print("nothing recorded yet: decisions appear here when a tool proposes an action")
    print(f"policy version {policy.VERSION}")


def _kv(pairs: list[str], fields) -> dict:
    kv = [p.partition("=") for p in pairs]
    if bad := [k for k, sep, _ in kv if not sep or not k.strip()]:
        raise SystemExit(f"use key=value (empty value clears), not: {' '.join(bad)}. Fields: {', '.join(fields)}")
    return {k.strip(): v for k, _, v in kv}


def _contact_line(c) -> str:
    touch = f"last {c['last_touch'] or '-'}  next {c['next_touch'] or '-'}"
    return (f"#{c['id']:<4} {c['name'][:26]:<26} {(c['company'] or '')[:22]:<22} {(c['position'] or '')[:26]:<26} {touch}"
            + (f"  jobs: {c['job_list']}" if c.get("job_list") else ""))


def cmd_contacts(a):
    from . import contacts

    if a.op == "add":
        cid = contacts.add(name=a.name, email=a.email, phone=a.phone, linkedin_url=a.linkedin, company=a.company,
                           position=a.position, how_met=a.how_met, notes=a.notes, next_touch=a.next_touch)
        print(f"added contact #{cid} {a.name}")
    elif a.op == "list":
        rows = contacts.rows(a.q or "", a.due)
        for c in rows:
            print(_contact_line(c))
        print(f"{len(rows)} contact(s)" if rows else "no contacts yet: lodestar contacts add \"Name\" or lodestar contacts import <Connections.csv|zip>")
    elif a.op == "show":
        c = contacts.get(a.id)
        _p({k: c[k] for k in c.keys()})
        for j in contacts.contact_jobs(a.id):
            print(f"  job #{j['id']:<4} {j['role']:<15} {j['status']:<10} {j['company']} - {j['title']}")
        for e in contacts.contact_events(a.id, 15):
            print(f"  {e['ts']}  #{e['job_id']} {e['kind']:<12} {e['detail'] or ''}")
    elif a.op == "edit":
        changed = contacts.edit(a.id, **_kv(a.pairs, contacts.FIELDS))
        print(f"contact #{a.id} " + ", ".join(f"{k}={'' if v is None else v}" for k, v in changed.items()))
    elif a.op == "rm":
        contacts.remove(a.id)
        print(f"removed contact #{a.id} (jobs stay; only the links went)")
    elif a.op == "import":
        n = contacts.import_connections(Path(a.file).read_bytes(), Path(a.file).name)
        print(f"{n['rows']} row(s): {n['added']} added, {n['updated']} updated (blank fields filled), {n['skipped']} unchanged "
              "or skipped. No follow-up dates were set: lodestar contacts edit ID next_touch=YYYY-MM-DD")
    elif a.op == "due":
        rows = contacts.due()
        for c in rows:
            print(f"#{c['id']:<4} due {c['next_touch']}  {c['name']}" + (f" ({c['company']})" if c["company"] else "")
                  + (f"  last touch {c['last_touch']}" if c["last_touch"] else ""))
        print(f"{len(rows)} contact(s) to get in touch with" if rows else "nobody due")
    elif a.op == "link":
        if a.remove:
            contacts.unlink(a.id, a.job)
            print(f"unlinked contact #{a.id} from job #{a.job}")
        else:
            contacts.link(a.id, a.job, a.role)
            print(f"linked contact #{a.id} to job #{a.job} as {a.role}")


def cmd_sponsors(a):
    from . import web_monitor

    if a.op == "import":
        r = web_monitor.import_sponsors(Path(a.file).read_bytes())
        print(f"loaded {r['approvals']:,} approvals for {r['employers']:,} employers ({r['rows']:,} employer-years). Search "
              "results and board cards now show 'possible H-1B sponsor' as a hint (loose name match, not a promise).")
    elif a.op == "lookup":
        h = web_monitor.sponsor_hint(a.company)
        print(f"possible H-1B sponsor: {h['name']} ({h['approvals']} approvals)" if h else "no match in your imported data")
    elif a.op == "clear":
        print(f"removed {db.clear_sponsors()} rows")


def _item_label(it: dict) -> str:
    v = it["incoming"]
    if not isinstance(v, dict):
        return f"{it.get('field') or it['kind']}: {str(v)[:70]}"
    bits = [v.get(f) for f in ("title", "role", "name", "degree", "heading", "label") if v.get(f)][:1]
    bits += [v.get(f) for f in ("company", "organization", "school", "issuer", "venue", "event", "url") if v.get(f)][:1]
    dates = " - ".join(x for x in (v.get("start"), v.get("end")) if x) or v.get("date") or ""
    return " - ".join(map(str, bits)) + (f" ({dates})" if dates else "")


def _print_review(p: dict) -> None:
    print(f"import {p['id']}: {p['file']} ({'AI' if p['used_ai'] else 'offline'} extraction)")
    for it in p["items"]:
        mark = "[x]" if it["default"] else "[ ]" if it["status"] != "duplicate" else "   "
        print(f"  {mark} {it['id']:<4} {it['status']:<9} {it['kind']:<14} {_item_label(it)}")
        for f, (mine, new) in (it.get("fields") or {}).items():
            print(f"{'':<36}{f}: yours {mine!r} | incoming {new!r}")
        for fl in it["flags"]:
            print(f"{'':<36}! {fl}")
    if p.get("dropped"):
        print("not stored: " + ", ".join(f"{d['label']}" + (f" (line {d['line']})" if d.get("line") else "") for d in p["dropped"])
              + ". Lodestar never puts personal details like these in a resume.")
    if p.get("unread"):
        print("lines not read into the profile: " + " | ".join(p["unread"][:10]))
    for n in p.get("notes") or []:
        print(n)


def _take(text: str | None) -> dict:
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


def _apply_review(pid: str, a) -> None:
    from . import profile

    r = profile.apply_import(pid, a.accept, _take(a.take), not a.no_master)
    got = ", ".join(f"{n} {k}" for k, n in r["added"].items()) or "nothing new"
    print(f"applied {pid}: added {got}; {r['updated']} updated; profile.md {'updated' if r['master_changed'] else 'unchanged'}")
    for n in r["notes"]:
        print(f"  note: {n}")
    _sync_master()


def _sync_master() -> None:
    """After a command that changed the profile: rebuild the master resume once (offline)."""
    from . import studio

    try:
        m = studio.sync_master()
    except (Exception, SystemExit) as e:
        return print(f"master resume not updated: {e}")
    if m.get("last_error"):
        print(f"master resume not updated: {m['last_error']}")
    elif m.get("files"):
        main = m["files"].get("pdf") or m["files"].get("html") or m["files"].get("docx")
        print(f"master resume: {main}" + (f" ({'; '.join(m.get('diff') or [])})" if m.get("diff") else ""))


def cmd_profile(a):
    from . import profile

    if a.op == "show":
        print(profile.summary_text())
    elif a.op in ("import", "linkedin"):
        src = Path(a.file)
        p = profile.stage_import(src.read_bytes(), src.name, "linkedin" if a.op == "linkedin" else "resume", a.provider,
                                 False if a.no_ai else None)
        _print_review(p)
        if a.accept:
            _apply_review(p["id"], a)
        else:
            print(f"nothing saved to the bank yet: lodestar profile review {p['id']} --accept new  (or all, none, i1,i3)")
    elif a.op == "review":
        if a.pid and a.discard:
            profile.discard_import(a.pid)
            print(f"discarded {a.pid}")
        elif a.pid and a.accept:
            _apply_review(a.pid, a)
        elif a.pid:
            _print_review(profile._pending(a.pid))
        else:
            rows = profile.pending_imports()
            for p in rows:
                print(f"{p['id']}  {p['created']}  {p['file']}  ({len(p['items'])} items)")
            print("" if rows else "no imports waiting for review")
    elif a.op == "reread":
        p = profile.reread_master()
        _print_review(p)
        print(f"lodestar profile review {p['id']} --accept new  applies it")
    elif a.op == "link":
        print(f"LinkedIn linked: {profile.link_linkedin(a.url)}")
        print(f"to import your LinkedIn profile, request 'Download your data' at {profile.LINKEDIN_EXPORT_URL}\n"
              "then run: lodestar profile linkedin <the .zip>   (or use the profile's 'Save to PDF')")
    elif a.op == "add":
        print(f"added {profile.add(a.kind, a.name, a.detail or '')['added']} {a.kind}")
    elif a.op == "remove":
        print(f"removed {profile.remove(a.kind, a.name)['removed']} {a.kind}")
    elif a.op == "rebuild":
        print(f"rebuilt {profile.rebuild_master()} from the bank (previous version in profile-history/)")
    if a.op in ("add", "remove", "rebuild", "link"):
        _sync_master()


def _studio_cli(a) -> None:
    """lodestar resume build / versions / open / catalogue: the AI resume studio."""
    from . import profile, studio

    if a.op == "catalogue":
        print(studio.catalogue_text(profile.structured(), cap=0, contact=True))
        return
    if a.op == "versions":
        for v in studio.versions():
            print(f"{v['vid']}  {(str(v['pages']) + ' p') if v['pages'] else '? p':<4} {'AI' if v['used_ai'] else 'offline':<7} "
                  f"{'job #' + str(v['job_id']) if v['job_id'] else '':<8} {(v['request'] or '')[:50]}"
                  + ("  [profile changed since]" if v["profile_changed"] else ""))
        return
    if a.op == "open":
        v = studio.version(a.vid)
        ext = a.format or ("pdf" if "pdf" in v["files"] else "html")
        if ext not in v["files"]:
            raise SystemExit(f"version {a.vid} has no .{ext} (it has {', '.join(v['files'])})")
        f = studio.file_path(a.vid, v["files"][ext])
        from .web import _open_path

        _open_path(f)
        print(f)
        return
    req = {k: v for k, v in {"pages": a.pages, "template": a.style, "font": a.font, "size": a.size, "accent": a.accent,
                             "margins": a.margins, "line_spacing": a.spacing, "paper": a.paper, "date_format": a.date_format,
                             "contact_layout": a.contact, "sections": a.sections, "bullets_per_role": a.bullets,
                             "drop": a.drop, "since": a.since, "formats": a.format, "density": a.density,
                             "include_on_file": a.on_file or None}.items() if v is not None}
    jd = read_source(a.jd) if a.jd else None
    v = studio.build(a.request or "", req, a.job, jd, getattr(a, "from"), a.provider, False if a.no_ai else None)
    d = studio.STUDIO / v["vid"]
    print(f"version {v['vid']} ({'AI' if v['used_ai'] else 'offline'}; {v['pages'] or '?'} page(s); "
          f"{v['engine'] or 'no PDF engine'})")
    for name in v["files"].values():
        print(f"  {d / name}")
    if v.get("coverage"):
        print(f"  JD coverage {v['coverage']['score']}%" + (f"; missing: {', '.join(v['coverage']['missing'][:8])}"
                                                           if v["coverage"]["missing"] else ""))
    for x in v["notes"] + v["events"] + v["warnings"]:
        print(f"  - {x}")
    if a.use_for_job:
        if not v.get("job_id"):
            raise SystemExit("--use-for-job needs --job ID")
        r = studio.use_for_job(v["vid"], v["job_id"])
        print(f"job #{v['job_id']}: resume.md, resume.docx" + (", resume.pdf" if r.get("pdf") else "") + " now come from this version")


def cmd_resume(a):
    from . import resume

    op = a.op
    if op == "profile":
        print(PROFILE)
        return
    if op == "master":
        from . import studio

        m = studio.sync_master(force=True) if a.rebuild else studio.master_status()
        m = studio.master_status() if a.rebuild else m
        for ext, f in (m.get("files") or {}).items():
            print(f"{ext:<5} {f}")
        print(f"built {m.get('built') or 'never'} with {m.get('engine') or '-'}"
              + (f", {m['pages']} page(s)" if m.get("pages") else "") + (" | STALE: the profile changed since" if m.get("stale") else ""))
        for line in (m.get("diff") or [])[:12]:
            print(f"  {line}")
        for w in m.get("warnings") or []:
            print(f"  warning: {w}")
        if m.get("last_error"):
            print(f"  problem: {m['last_error']}")
        return
    if op in ("build", "versions", "open", "catalogue"):
        return _studio_cli(a)
    if op == "review":
        print(resume.review(read_source(a.file) if a.file else resume.profile_text(), a.provider))
        return
    if op == "export":  # a job id exports that job's resume.md; anything else is a markdown file
        md = resume.app_dir(db.get_job(int(a.file))) / "resume.md" if a.file.isdigit() and not Path(a.file).is_file() else Path(a.file)
        if not a.pdf:
            print(resume.export_docx(md, a.style))
            return
        r = resume.export_pdf(md, a.style)
        print(f"wrote {r['path']}  ({r['note']})")
        for t in r["tried"]:
            print(f"  tried {t}")
        return
    if op == "lint":
        from .lint import lint

        if a.job:
            p = resume.app_dir(db.get_job(a.job)) / "resume.md"
            if not p.is_file():
                raise SystemExit(f"job #{a.job} has no tailored resume yet: lodestar resume tailor {a.job}")
            text = p.read_text(encoding="utf-8-sig")
        else:
            text = _file_text(a.file) if a.file else resume.profile_text()
        r = lint(text)
        print(_issues_text(r))
        print(f"\nscore {r['score']}/100 (secondary: the list above is what to fix)")
        return
    if op == "audit":
        from .lint import audit

        r = audit(Path(a.file).read_bytes(), a.file)
        print(_issues_text(r))
        print(f"\n{r['note']}\n\n--- what a parser sees ---\n{r['text']}")
        return
    if op == "import":
        from .extras import import_document

        text = import_document(Path(a.file).read_bytes(), a.file)
        if a.merge:
            text = resume.merge_into_profile(text, a.provider)
        if a.save:
            from .profile import write_master

            write_master(text)
            print(f"profile {'merged and ' if a.merge else ''}saved: {PROFILE} (previous version in profile-history/)")
            _sync_master()
        else:
            print(text)
            print("\n(nothing saved; add --save, or --merge --save to fold it into your master profile)")
        return
    if op == "adjust":
        if a.job:
            from .resume import app_dir

            job = db.get_job(a.job)
            target = app_dir(job) / (a.doc or "resume.md")
            kind = "cover letter" if "cover" in target.name else "resume"
        else:
            target, kind = PROFILE, "master profile"
        new = resume.adjust_text(target.read_text(encoding="utf-8-sig"), a.instruction, kind, a.provider)
        if a.save:
            if target == PROFILE:
                from .profile import write_master

                write_master(new)
                _sync_master()
            else:
                resume.save_doc(job, target.name, new)  # the old version moves to history/; resume.md is re-scored
            print(f"saved {target}")
        else:
            print(new)
            print(f"\n(nothing saved; add --save to write {target})")
        return
    job = db.get_job(a.id)
    if op == "tailor" and (a.bullets or a.accept):
        if a.bullets:
            print(_bullets_text(job, resume.tailor_bullets(job, a.base, a.provider)))
        if a.accept:
            r = resume.apply_bullets(job, a.accept, a.docx)
            print(f"wrote {r['path']}: {len(r['accepted'])} rewrite(s) accepted, coverage {r['coverage']['before']} -> {r['coverage']['after']}")
    elif op == "tailor":
        out = resume.tailor(job, a.council, a.provider, a.base)
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


def cmd_match(a):
    from . import resume

    for term in a.skip or ():
        resume.toggle_skip(db.get_job(a.id), term)
    job = db.get_job(a.id)
    cov = resume.coverage(job, _file_text(a.file), save=False) if a.file else resume.coverage(job)
    print(f"#{job['id']} {job['company']} - {job['title']}" + (f"  (scored {a.file}; not saved)" if a.file else ""))
    print(_coverage_text(cov))


def cmd_fit(a):
    """`lodestar fit ID`: the fit breakdown (scored now when missing or stale); `lodestar fit refresh`: every stale fit."""
    from . import fit

    if a.target == "refresh":
        r = fit.refresh(a.limit)
        print(f"re-scored {r['jobs']} job(s) and {r['listings']} listing(s); {r['left']} left")
        return
    if not a.target.isdigit():
        raise SystemExit("lodestar fit ID | lodestar fit refresh")
    job = db.get_job(int(a.target))
    if fit.stored(job) is None or job["fit_rev"] != fit.rev():
        fit.for_job(job)
        job = db.get_job(job["id"])
    print(fit.breakdown_text(job))


def cmd_apply_agent(a):
    """`lodestar apply-agent run|status|stop|continue|login|forget|runs`: the apply agent (docs/APPLY_AGENT.md)."""
    from . import apply_agent

    if a.op == "run":
        for r in apply_agent.run_foreground(a.ids, a.mode, True if a.eeo else None, a.headless):
            print(f"#{r['job_id']}: " + (f"refused: {r['error']}" if "error" in r else
                                         f"run #{r['run_id']} {r['mode']} -> {r['state']}"
                                         + (f" ({'; '.join(r['reasons'])})" if r.get("reasons") else "")))
    elif a.op == "status":
        st = apply_agent.status()
        print(st["available"] or "the apply agent is available")
        for r in st["live"] + st["recent"]:
            print(f"run #{r['id']} #{r['job_id']} {r['company']} - {r['title']}: {r['state']} ({r['mode']}) {r['step'] or ''}"
                  + (f" confirmation {r['confirmation']}" if r["confirmation"] else "") + (f" error: {r['error']}" if r["error"] else ""))
            for n in r["needs"] or []:
                print(f"    needs you: {n.get('label') or n.get('reason')}: {n.get('hint')}")
        print(f"{st['queue']} queued")
    elif a.op == "stop":
        r = apply_agent.stop()
        print(f"stop sent (works across processes); {r['queued_stopped']} queued run(s) stopped")
    elif a.op == "continue":
        apply_agent.continue_run(a.run)
        print(f"run #{a.run}: continuing")
    elif a.op == "login":
        r = apply_agent.login_window(a.url)
        print(f"sign-in window open at {r['url']}: sign in, then close the window before running the agent")
    elif a.op == "forget":
        r = apply_agent.forget_logins()
        print("the agent's browser profile (its sign-ins) was deleted" if r["removed"] else "no agent profile to delete")
    elif a.op == "runs":
        for r in db.runs_for(a.id):
            print(f"run #{r['id']} {r['state']} ({r['mode']}, {r['submitted_by'] or 'not submitted'}) {r['submitted_at'] or ''} "
                  f"{r['confirmation'] or ''} {r['evidence'] or ''}".rstrip())


def cmd_accounts(a):
    """`lodestar accounts list|add|password|remove`: your site accounts (docs/APPLY_AGENT.md > Site accounts). Re-login and
    Create run in the agent's window from Setup > Site accounts."""
    from . import accounts

    if a.op in (None, "list"):
        rows = accounts.listing(getattr(a, "q", "") or "")
        for r in rows:
            jobs = ", ".join(f"#{j['id']}" for j in r["jobs"])
            print(f"#{r['id']} {r['site']} {r['username']} [{r['label']}] created {str(r['created_at'])[:10]} last sign-in "
                  f"{str(r['last_login'] or 'never')[:16]}" + (f" jobs {jobs}" if jobs else "")
                  + (f" ({r['last_error']})" if r["last_error"] else ""))
        if not rows:
            print("no site accounts yet")
    elif a.op == "add":
        import getpass

        pw = a.password if a.password is not None else getpass.getpass("password (empty: Lodestar makes one): ")
        r = accounts.add(a.url, a.username, pw)
        print(f"saved #{r['id']} {r['site']} ({r['username']}); the password is in the OS keyring")
    elif a.op == "password":
        import getpass

        r = accounts.set_password(a.id, "" if a.generate else (a.password or getpass.getpass("new password: ")), a.generate)
        print(f"#{a.id}: new password {r['password']} (type it into the site's change-password form)" if a.generate
              else f"#{a.id}: password changed")
    elif a.op == "remove":
        r = accounts.remove(a.id)
        print(f"removed {r['site']} (its password is gone from the OS keyring)")


def cmd_intel(a):
    """`lodestar intel ID [--gather|--refresh] [--summary]`: the job's public facts with their sources and dates."""
    from . import intel

    job = db.get_job(a.id)
    if a.gather or a.refresh:
        intel.gather(job, a.refresh)
    if a.summary:
        intel.summarize(job, a.provider)
    print(intel.text(job))


def cmd_boosters(a):
    """`lodestar boosters [ID] [--ai]`: chance boosters for one job (rules, plus AI additions with --ai), else across
    the search. Expected effect only, never a probability."""
    from . import boosters

    job = db.get_job(a.id) if a.id else None
    if a.ai:
        if not job:
            raise SystemExit("--ai needs a job id: lodestar boosters ID --ai")
        boosters.ai_add(job, a.provider)
    print(boosters.text(job))


def _mail_test_text(r: dict) -> str:
    lines = [f"{k.upper():<5} {'ok  ' if r[k]['ok'] else 'FAIL'} {r[k]['detail']}" for k in ("imap", "smtp")]
    return "\n".join(lines + ([f"hint: {r['hint']}"] if r["hint"] else []))


def cmd_email(a):
    from . import email_monitor, mailconn

    if a.op == "connect":
        user = (a.user or input("email address: ")).strip()
        preset = a.preset or mailconn.guess(user) or "custom"
        p = mailconn.PRESETS[preset]
        if p.get("oauth_only"):
            raise SystemExit(f"{p['label']}: Microsoft accepts no passwords for IMAP and SMTP. Sign in instead:\n"
                             f"  lodestar email signin microsoft{' --work' if preset == 'm365' else ''} --hint {user}")
        print(f"{p['label']}: {p.get('steps', '')}" + (f"\n  {p['help']}" if p.get("help") else ""))
        keys = {k: getattr(a, k) for k in mailconn.KEYS if getattr(a, k, None)}
        pw = getpass.getpass("app password (not shown; Enter keeps the stored one): ")
        st = mailconn.connect(preset, user, pw or None, **keys)
        print(f"stored {st['user']} ({st['label']}): IMAP {st['imap_host']}:{st['imap_port']}, "
              f"SMTP {st['smtp_host']}:{st['smtp_port']} {st['smtp_mode']}")
        if st["shadowed"]:
            print(f"note: {', '.join(st['shadowed'])} set in the environment / .env win over these values")
        for x in st["conflicts"]:
            print(f"WARNING: {x}")
        if st["configured"]:
            print(_mail_test_text(mailconn.test()))
    elif a.op == "parse-alert":  # the debugging tool for alert format changes: reads a saved .eml, changes nothing
        from . import alerts

        r = alerts.parse_file(Path(a.file).read_bytes(), a.trust)
        print(f"sender: {r['sender'] or '(none)'} (local part '{r['local']}')  site: {r['site'] or 'not a known alert sender'}"
              f"  authenticated: {'yes' if r['authenticated'] else 'no (use --trust for a saved file)'}")
        if not r["site"]:
            print("  add the local part to that site's alert_from in lodestar/alerts.py if this is a job alert")
        for i, x in enumerate(r["rows"], 1):
            print(f"{i:>3}. {x['title']} @ {x['company']} | {x['location'] or '-'} | {x['salary'] or '-'} | "
                  f"{x['date'] or '-'}\n     {x['url'] or '(no https link kept)'}")
        print(f"{len(r['rows'])} job(s) read")
    elif a.op == "test":
        print(_mail_test_text(mailconn.test()))
    elif a.op == "test-send":
        r = mailconn.test_send()
        print(f"test email sent to {r['to']} ({r['message_id']}); check that inbox")
    elif a.op == "status":
        st = mailconn.status()
        how = f"signed in with {st['oauth_provider'].title()} (OAuth)" if st["oauth_provider"] else "app password"
        print(f"{'connected' if st['configured'] else 'not connected'}: {st['user'] or '(no address)'} ({st['label'] or 'no preset'})"
              + (f", {how}" if st["configured"] else "")
              + f"\n  IMAP {st['imap_host']}:{st['imap_port']}  SMTP {st['smtp_host']}:{st['smtp_port']} {st['smtp_mode']}"
              f" as {(st['user'] if st['oauth_provider'] else st['smtp_user']) or '-'}"
              + (f"\n  overridden by env: {', '.join(st['shadowed'])}" if st["shadowed"] else ""))
        if st["needs_signin"]:
            print(f"  needs sign-in: {st['needs_signin']}\n  lodestar email signin {st['oauth_provider']}")
        if st["refresh_expires"]:
            print(f"  WARNING: Google app in Testing: this sign-in stops working {st['refresh_expires']} UTC. Publish the app "
                  "(docs/CONNECT.md step 6) and sign in again.")
    elif a.op == "disconnect":
        oauth_on = mailconn.status()["oauth_provider"]
        r = mailconn.disconnect()
        if oauth_on:
            print("signed out: the sign-in is forgotten" + (" and revoked at Google" if r.get("revoked") else "")
                  + " (server settings kept)")
        else:
            print("app password removed from the keyring (server settings kept)")
        if r.get("note"):
            print(r["note"])
    elif a.op == "client":
        from . import oauth

        if a.provider == "google":
            cid = input("Google OAuth client ID (ends in .apps.googleusercontent.com): ")
            sec = getpass.getpass("client secret (not shown; Enter for none): ")
        else:
            cid, sec = input("Microsoft Application (client) ID: "), None
        oauth.set_client(a.provider, cid, sec or None)
        print(f"{a.provider} client stored in the keyring; next: lodestar email signin {a.provider}")
    elif a.op == "signin":
        import webbrowser

        from . import oauth

        def show(url):
            print(("Visit this page to sign in" if a.no_browser else "Opening your browser to sign in... If it did not open, visit")
                  + f":\n{url}\nWaiting up to 5 minutes (Ctrl-C to stop).", flush=True)
            return False if a.no_browser else webbrowser.open(url)

        st = oauth.signin(a.provider, "work" if a.work else "personal", a.hint or "", open_browser=show)
        print(f"signed in as {st['signed_in_as']} ({st['label']})")
        if st.get("expires_warning"):
            print(f"WARNING: {st['expires_warning']}")
        print(_mail_test_text(mailconn.test()))
    elif a.op == "check":
        found = email_monitor.check(a.days, dry=a.dry, provider=a.provider)
        print(f"\n{len(found)} relevant email(s)")
        if getattr(found, "alerts", 0):
            print(f"{found.alerts} new listing(s) from job alerts in All jobs (lodestar jobs all)")
    elif a.op == "reply":
        _print_mail(email_monitor.draft_reply(db.get_job(a.id), a.intent, a.provider))


def cmd_mail(a):
    if a.op == "list":
        rows = db.list_mail(a.job, a.unmatched)
        for m in rows:
            who = f"from {m['from_addr']}" if m["direction"] == "in" else f"to {m['to_addr']}"
            where = f"job #{m['job_id']} ({m['linked_by']})" if m["job_id"] else "unmatched"
            print(f"#{m['id']:<5} {(m['sent_at'] or m['created_at'] or '')[:16]}  {m['direction']:<3} {m['category'] or '-':<20} "
                  f"{'trusted' if m['trusted'] else 'unverified':<10} {where:<18} {who}: {m['subject'] or ''}")
        print(f"{len(rows)} message(s)" if rows else "no mail recorded yet (lodestar email check records relevant mail)")
    elif a.op == "link":
        db.link_mail(a.id, a.job)
        print(f"mail #{a.id} filed under job #{a.job} (the job's contact and trust are unchanged)")
    elif a.op == "unlink":
        db.unlink_mail(a.id)
        print(f"mail #{a.id} unlinked (back under unmatched mail)")
    elif a.op == "dismiss":
        db.dismiss_mail(a.id)
        print(f"mail #{a.id} dismissed")


def cmd_watch(a):
    from . import web_monitor

    if a.op == "add":
        if not a.url.strip().lower().startswith(("http://", "https://")):  # the same rule as POST /api/watches
            raise SystemExit("a page watch needs an http(s) URL (for a job search use: lodestar watch search-add QUERY)")
        db.add_watch(a.url.strip(), a.keywords or "")
        print("watch added; first run takes a baseline snapshot")
    elif a.op == "search-add":
        f = _search_filters(a)
        db.add_watch(f"search:{a.query}", a.keywords or "", f or None)  # no filter flags: keep the saved ones
        f = db.watch_filters(next(w for w in db.watches() if w["url"] == f"search:{a.query}"))
        print(f"will alert on new listings for '{a.query}'" + (f" ({', '.join(f'{k}={v}' for k, v in f.items())})" if f else ""))
    elif a.op == "list":
        for w in db.watches():
            f = db.watch_filters(w)
            print(f"#{w['id']:<3} {w['url']:<60} kw={w['keywords'] or '-'} last={w['last_seen'] or 'never'}"
                  + (f" filters={','.join(f'{k}={v}' for k, v in f.items())}" if f else "")
                  + (f"\n     {'note' if w['last_error'].startswith('partial:') else 'last run failed'}: {w['last_error']}"
                     if w["last_error"] else ""))
    elif a.op == "rm":
        db.remove_watch(a.id)
    elif a.op == "run":
        alerts = web_monitor.check_watches()
        print(f"{len(alerts)} alert(s)")


def cmd_interview(a):
    from . import interview

    if a.op == "calibration":
        return _print_record()
    job = db.get_job(a.id)
    if a.op in ("questions", "sources", "paste", "site", "unsource", "readiness"):
        return _interview_sources(a, job)
    if a.op == "prep":
        print(f"wrote {interview.prep(job, a.council, a.provider)}")
    elif a.op == "mock":
        interview.mock(job, a.provider, a.focus)
    elif a.op == "log":
        f = {k: v for k, v in (("round", a.round), ("kind", a.kind), ("at", a.at), ("interviewers", a.interviewers),
                               ("notes", a.notes), ("outcome", a.outcome)) if v is not None}
        if a.questions_file:
            f["questions_asked"] = Path(a.questions_file).read_text(encoding="utf-8-sig")
        r = interview.get_round(interview.log_round(job["id"], **f))
        print(f"round {r['round']} of #{job['id']} {job['company']} saved ({r['kind']}, {r['at'] or 'no date'}, {r['outcome']}, "
              f"{len((r['questions_asked'] or '').splitlines())} question(s))")
    else:
        rs = interview.rounds(job["id"])
        print(f"#{job['id']} {job['company']} - {job['title']}: {len(rs) or 'no'} round(s)")
        for r in rs:
            print(f"  round {r['round']:<3} {r['kind']:<10} {r['at'] or 'no date':<17} {r['outcome']:<9} {r['interviewers'] or ''}")
            for q in (r["questions_asked"] or "").splitlines():
                print(f"      Q: {q}")
            if r["notes"]:
                print(f"      notes: {r['notes'][:300]}")


def _interview_sources(a, job):
    """interview questions / sources / paste / site / unsource / readiness."""
    from . import interview

    if a.op == "questions":
        s = interview.question_set(job, refresh=a.refresh and not a.offline, offline=a.offline, provider=a.provider)
        print(f"Practice questions for #{job['id']} {job['company']} - {job['title']}"
              + (" (stale: sources changed; --refresh)" if s["stale"] else ""))
        print(f"  {s['emphasis_text']}")
        print("  sources: " + ", ".join(f"{k} {n}" for k, n in s["by_source"].items() if n))
        if s["ai_error"]:
            print(f"  {s['ai_error']}")
        if s["dropped"]:
            print(f"  {len(s['dropped'])} AI question(s) dropped: " + "; ".join(sorted({d['why'] for d in s['dropped']})))
        for c in interview.QCOMP:
            rows = [e for e in s["questions"] if e["competency"] == c]
            if rows:
                print(f"\n{c}:")
                for e in rows:
                    print(f"  - {e['q']}\n      [{e['chip']}] {e['label']}")
    elif a.op == "sources":
        s = interview.sources(job)
        print(f"Question sources for {s['company']}: website {s['site']['url'] + ' (' + s['site']['label'] + ')' if s['site'] else 'none (lodestar interview site ID URL)'}")
        print(f"  pages ({s['counts']['pages']} read" + (f", last check {s['last_check']}" if s["last_check"] else "") + "):")
        for p in s["pages"]:
            print(f"    #{p['id']:<5} {p['status'] if p['status'] != 'robots' else 'skipped: robots.txt disallows':<10} {p['url']}  {p['label'] or ''}")
        print(f"  pastes ({s['counts']['pastes']}):")
        for p in s["pastes"]:
            print(f"    #{p['id']:<5} {p['created_at'][:10]}  {p['label']}" + (f"  <{p['url']}>" if p["url"] else ""))
    elif a.op == "paste":
        text = a.text if a.text is not None else sys.stdin.read() if a.file in (None, "-") else Path(a.file).read_text(encoding="utf-8-sig")
        print(interview.PASTE_NOTICE)
        print(f"saved paste #{interview.add_paste(job, a.label, text, a.url)} for {job['company']} "
              "(the practice set reads stale until rebuilt: lodestar interview questions ID --refresh)")
    elif a.op == "site":
        r = interview.set_site(job, a.url)
        print(f"{job['company']} website: {r['site'] or 'cleared'}")
    elif a.op == "unsource":
        interview.delete_source(job, a.sid)
        print(f"removed source #{a.sid}")
    else:
        from .readiness import readiness

        r = readiness(job)
        print(f"#{job['id']} {job['company']} - {job['title']}: readiness {r['score']}/100 (preparation)")
        print(r["chance"]["label"])
        if r["chance"]["funnel"]:
            print(r["chance"]["funnel"])
        print(f"  {r['stage']}")
        for k, v in r["parts"].items():
            print(f"  {k:<10} {v['s']:>3}/100  (weight {v['w']})  " + "; ".join(v["chips"]))
        print("  raise it:" if r["raise"] else "  nothing obvious left to raise it")
        for x in r["raise"]:
            print(f"    +{x['gain']}  {x['text']}")


def _print_record():
    from .readiness import calibration

    c = calibration()
    print(f"Your record (readiness vs results): {c['state']}")
    for b, row in c["table"].items():
        print(f"  {b:<7} {row['lo']:>3}-{row['hi']:<3} passed {row['passed']} of {row['total']}")
    print(f"  {c['caveat']}")
    if c["note"]:
        print(f"  {c['note']}")


def cmd_questions(a):
    from . import interview

    job = db.get_job(a.id) if a.id else None
    rows = interview.question_bank(job)
    if job:
        print(f"Questions for #{job['id']} {job['company']} - {job['title']}: logged at this company, then similar titles, "
              "then the bundled behavioural set")
    last = None
    for x in rows:
        if x["source"] != last:
            print(f"\n{x['source']}:")
            last = x["source"]
        print(f"  - {x['q']}" + (f"  ({x['where']})" if x["where"] else ""))


def cmd_stories(a):
    from . import interview

    if a.op == "list":
        rows = interview.stories()
        print(f"{len(rows) or 'no'} stor{'y' if len(rows) == 1 else 'ies'}" + ("" if rows else
              " yet: lodestar stories add --title ... --situation ... --action ... --result ..."))
        for s in rows:
            print(f"#{s['id']:<4} {s['title'][:60]:<60} {', '.join(s['competencies']) or 'untagged'}"
                  + (f"  (missing: {', '.join(s['missing'])})" if s["missing"] else ""))
    elif a.op == "show":
        s = next((x for x in interview.stories() if x["id"] == a.id), None)
        if not s:
            raise SystemExit(f"no story #{a.id}")
        print(f"#{s['id']} {s['title']}  [{', '.join(s['competencies']) or 'untagged'}]\n{interview.render_story(s)}")
    elif a.op == "rm":
        if not any(x["id"] == a.id for x in interview.stories()):
            raise SystemExit(f"no story #{a.id}")
        db.delete_answer(a.id)
        print(f"removed story #{a.id}")
    elif a.from_idea:
        print(f"saved story #{interview.story_from_idea(a.from_idea)} from idea #{a.from_idea}: fill in the rest in the "
              "Answers tab > Stories")
    else:
        sid = interview.save_story(a.title, a.situation, a.task, a.action, a.result, a.metrics, a.tags or "")
        print(f"saved story #{sid}")


def cmd_run(a):
    """The automation loop (see loop.py): email -> watches -> follow-ups -> reminders -> sync/digest/backup."""
    from . import loop, updater

    from . import studio

    studio.AUTO = True  # the master resume follows profile edits (never set by web.start_server)
    updater.startup()  # an interrupted update is rolled back first; then later updates know this process runs
    loop.run(a)


def cmd_alerts(a):
    print(ALERTS.read_text(encoding="utf-8")[-4000:] if ALERTS.is_file() else "(no alerts yet)")


def cmd_keys(a):
    """Link, check and remove AI keys. The key is read without echo and never printed."""
    from . import connections

    if a.op == "link":
        name = connections.resolve(a.name)
        key = None
        if connections.REGISTRY[name]["key"]:
            e = connections.REGISTRY[name]
            print(f"Get a key: {e['get']}" + (f"  ({e['hint']})" if e["hint"] else ""))
            key = getpass.getpass(f"{e['label']} key (not shown): ")
        ident = input(f"{e['id_label']}: ") if connections.REGISTRY[name].get("id") else None
        r = connections.link(name, key, ident)
        print(f"{r['label']}: {r['status']} - {r['detail']}")
        for k in ("prefix_warning", "shadowed"):
            if r.get(k):
                print(f"  note: {r[k]}")
    elif a.op == "check":
        names = [connections.resolve(a.name)] if a.name else None
        if names:
            connections.check(names[0])
        else:
            connections.check_all()
        _keys_table(connections.status(), names)
    elif a.op == "rm":
        connections.unlink(a.name)
        print(f"removed {connections.resolve(a.name)}")
    else:
        _keys_table(connections.status())


def _keys_table(st: dict, only: list[str] | None = None) -> None:
    from .connections import local

    for n, k in st["keys"].items():
        if only and n not in only:
            continue
        linked = {"env": "env", "vault": "vault"}.get(k["source"], "yes") if k["linked"] else "no"
        when = local(k["checked_at"]) if k["checked_at"] else "-"
        print(f"{n:<11} linked={linked:<5} {k['status'] if k['linked'] else '-':<11} {when:<16} {k['model'] or '-'}")
        if k["linked"] and k["detail"]:
            print(f"{'':<11} {k['detail']}")
        if not k["linked"]:
            print(f"{'':<11} get a key: {k['get']}")
    m = st.get("mail") or {}
    if m.get("status") and m["status"] != "unchecked" and not only:
        print(f"{'email':<11} {m['status']:<11} {local(m.get('checked_at', ''))}  {m.get('detail', '')}")


def cmd_ui(a):
    from . import connections, updater
    from . import pipeline, studio

    pipeline.AUTO = studio.AUTO = True  # answering a question resumes its step in a thread (never set by web.start_server)
    from .web import serve

    updater.startup()
    connections.start_checks()  # background, once: the server below comes up first
    serve(a.port, open_browser=not a.no_open)


def cmd_app(a):
    """The personal workbot: monitor loop in a background thread + web UI in the foreground, one process."""
    import threading
    from . import pipeline, studio

    pipeline.AUTO = studio.AUTO = True  # question answers resume steps; profile edits rebuild the master resume

    from .web import serve

    from . import connections, updater

    updater.startup()
    if not a.no_loop:
        a.once = False
        threading.Thread(target=cmd_run, args=(a,), daemon=True).start()
        print(f"monitor loop running every {a.every} min")
    connections.start_checks()  # background, once: keys and mailbox re-verified after the server is up
    serve(a.port, open_browser=not a.no_open)


def cmd_doctor(a):
    from .doctor import report

    raise SystemExit(0 if report(a.live) < 2 else 1)


def _print_update(p: dict) -> None:
    print(p["result"])
    if p.get("origin"):
        print(f"origin: {p['origin']}")
    for c in p.get("commits") or []:
        print(f"  {c}")
    if p.get("changelog"):
        print("\n" + p["changelog"])
    if p.get("blocked"):
        print(f"\nnot applicable now: {p['blocked']}")


def cmd_update(a):
    """Self-update (updater.py). apply shows the commit range and changelog first and asks unless --yes."""
    from . import updater

    if a.op == "check":
        _print_update(updater.check())
    elif a.op == "apply":
        p = updater.check()
        _print_update(p)
        if not p["available"] or p["kind"] != "git" or p["blocked"]:
            return
        if not a.yes:
            try:
                if input("\nApply this update? [y/N] ").strip().lower() not in ("y", "yes"):
                    return print("not applied")
            except EOFError:
                return print("not applied (no answer; use --yes)")
        print("backing up, updating and running the tests (a minute or two)...")
        r = updater.apply(plan=p)
        print(r["result"])
        if r.get("backup"):
            print(f"backup: {r['backup']}")
        if not r["ok"]:
            raise SystemExit(1)
    elif a.op == "log":
        for e in updater.entries(a.limit) or [{"at": "", "kind": "", "from": "", "to": "", "result": "(no checks yet)"}]:
            span = f"{e['from'][:7]}..{e['to'][:7]}" if e["from"] or e["to"] else ""
            print(f"{e['at']:<19} {e['kind']:<6} {span:<16} {e['result']}")
    else:
        for status, what, detail in updater.doctor_rows():
            print(f"{what:<14} {detail}")


def cmd_desktop(a):
    """The desktop app: server + monitor loop in this process, the UI in a native window. What the shortcut runs."""
    import threading
    from . import pipeline, studio

    pipeline.AUTO = studio.AUTO = True  # question answers resume steps; profile edits rebuild the master resume

    from . import desktop, web
    from .web import start_server

    from . import connections, updater

    updater.startup()
    web.RESTART = desktop.relaunch  # Setup > Updates offers Restart after an update
    port = a.port or desktop.free_port()
    srv = start_server(port)
    connections.start_checks()  # background, once; never blocks or crashes the window
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

    if a.options or a.pick:  # options are emails to the job's contact
        return _draft("outreach", {"job": a.id, "person": a.person or ""}, a)
    r = extras.outreach(db.get_job(a.id), a.person or "", a.channel, a.provider)
    print(r["text"]) if "text" in r else _print_mail(r)


def cmd_digest(a):
    from . import extras

    print(extras.digest(a.days, a.send, a.provider))
    if a.send:
        print(f"\n(emailed to {extras.digest_to()})")


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


def cmd_restore(a):
    """Put the data folder back to a backup zip (extras.restore): shows what the zip holds and asks unless --yes."""
    from . import extras

    plan = extras.restore_check(a.zip)  # refuses a bad zip before asking anything
    skipped = f"; never restored: {', '.join(plan['skipped'][:5])}" if plan["skipped"] else ""
    print(f"{Path(a.zip).name}: {len(plan['files'])} file(s), {plan['total'] / 1e6:.1f} MB unpacked{skipped}")
    print("Your data folder will be replaced by this backup; a safety backup of it is taken first.")
    if not a.yes:
        try:
            if input("Restore? [y/N] ").strip().lower() not in ("y", "yes"):
                return print("not restored")
        except EOFError:
            return print("not restored (no answer; use --yes)")
    r = extras.restore(a.zip)
    c = r["counts"]
    print(f"restored {r['restored']} file(s) from {r['from']} ({c['jobs']} jobs, {c['contacts']} contacts, {c['answers']} answers); "
          f"removed {r['removed']} file(s) made since")
    print(f"safety backup of what was there: {r['safety_backup']}")
    print(r["note"])


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

    edits = {k: v for k, v in (("subject", a.subject), ("body", Path(a.body).read_text(encoding="utf-8-sig") if a.body else None), ("to", a.to)) if v}
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
            print(f"#{r['id']:<3} Q: {r['question'][:90]}{'  [private]' if r['private'] else ''}\n     A: {r['answer'][:300].replace(chr(10), ' ')}\n")
    elif a.op == "add":
        db.save_answer(a.question, a.answer, a.tags or "", a.private, source="typed in the CLI")
        print("saved" + (" (private: never sent to an employer)" if a.private else ""))
    elif a.op == "rm":
        db.delete_answer(a.id)
        print(f"#{a.id} removed")
    elif a.op == "ask":
        r = apply.answer(db.get_job(a.id), a.question, a.provider)
        print(r["answer"])
        print(f"\n[reused: {r['reused'] or 'none'}] [save -> {r['proposal'].get('status')}]")


def cmd_pipeline(a):
    """Step-by-step automation per job (pipeline.py): states, runs, the questions queue, Autopilot, the run log."""
    from . import pipeline

    if a.op == "status" and a.id is None:
        summ = pipeline.summary()
        for j in db.list_jobs():
            if j["status"] in pipeline.CLOSED:
                continue
            s = (pipeline._summary_of(pipeline.status(j["id"])) if j["id"] not in summ else summ[j["id"]])
            bits = [f"next: {s['next']}" if s.get("next") else "nothing ready", f"? {s['you']}" if s.get("you") else "",
                    f"stale {s['stale']}" if s.get("stale") else "", f"errors {s['errors']}" if s.get("errors") else "",
                    "fit: skip (Autopilot leaves it alone)" if s.get("fit_skip") else ""]
            print(f"{_job_line(j)}  {'  '.join(b for b in bits if b)}")
    elif a.op == "status":
        for e in pipeline.status(a.id):
            out = e["output"].get("file") or ""
            print(f"{e['name']:<9} {e['state']:<8}{' (' + e['on'] + ')' if e['on'] else '':<11} rev {e['rev'] or 0:<2} "
                  f"{(e['origin'] or '-'):<9} {out:<18} {e['why'][:90]}")
    elif a.op == "run":
        if a.stage:
            rs = [pipeline.run(a.id, a.stage, provider=a.provider, rerun=a.rerun)]
        else:
            to = a.to or pipeline.next_stage(a.id)
            if not to:
                raise SystemExit(f"#{a.id}: nothing is ready to run (lodestar pipeline status {a.id})")
            rs = pipeline.run_to(a.id, to, provider=a.provider, rerun=a.rerun) if a.to else [pipeline.run(a.id, to, provider=a.provider)]
        for r in rs:
            print(f"#{r['job_id']} {r['stage']}: {r['outcome']} ({r['ai']} AI call{'s' if r['ai'] != 1 else ''}) {r['detail'][:160]}")
        if not rs:
            print("nothing ran: the first step on the way is waiting, blocked, manual or stale (lodestar pipeline status "
                  f"{a.id}; --rerun includes stale steps)")
    elif a.op == "skip":
        pipeline.skip(a.id, a.stage, not a.undo)
        print(f"#{a.id} {a.stage}: {'unskipped' if a.undo else 'skipped'}")
    elif a.op == "questions":
        qs = pipeline.questions(all=a.all, job=a.job)
        for q in qs:
            jobs = ", ".join(f"#{j['job_id']} {j['company']} ({j['stage']})" for j in q["jobs"]) or f"#{q['job_id']}"
            print(f"Q{q['id']:<4} [{q['status']}/{q['kind']}{'' if q['blocking'] else ', optional'}] {q['text']}\n"
                  f"       for {jobs}" + (f"\n       answer: {q['answer'][:200]}" if q["answer"] else "")
                  + "".join(f"\n       near match #{x['id']}: {x['question'][:80]} -> {x['answer'][:80]}" for x in q["suggestions"]))
        if not qs:
            print("no questions waiting for you")
    elif a.op == "answer":
        r = pipeline.answer(a.qid, a.text, scope="job" if a.job_only else None, private=a.private or None)
        print(f"saved{' to the answer bank #' + str(r['answer_id']) if r['answer_id'] else ''}; "
              f"resumed: {', '.join(f'#{j} {s}' for j, s in r['resumed']) or 'nothing waiting'}")
    elif a.op == "dismiss":
        r = pipeline.dismiss(a.qid)
        print(f"left for you; resumed: {', '.join(f'#{j} {s}' for j, s in r['resumed']) or 'nothing waiting'}")
    elif a.op == "add-questions":
        lines = (sys.stdin.read() if a.file == "-" else Path(a.file).read_text(encoding="utf-8-sig")).splitlines()
        print(f"#{a.id}: {pipeline.add_form_questions(a.id, lines, 'cli')} new form question(s)")
    elif a.op == "autopilot":
        if a.mode in ("on", "off"):
            settings.set_pref("autopilot", a.mode)
        p = settings.load()["prefs"]
        print(f"Autopilot: {'on' if p['autopilot'] else 'off'}; budgets {p['autopilot_ai_per_cycle']} AI calls per cycle, "
              f"{p['autopilot_ai_per_day']} per day, {p['autopilot_jobs_per_cycle']} jobs per cycle; "
              f"{pipeline.spent_today()} AI calls in the last 24 h")
        for n, st in pipeline.REGISTRY.items():
            if st.tool:
                t = settings.load()["tools"][st.tool]
                print(f"  {n:<9} tool {st.tool:<15} {'auto' if t['enabled'] and t['auto'] else 'asks in the Inbox' if t['enabled'] else 'off'}")
        if pipeline.LAST["at"]:
            print(f"last cycle {pipeline.LAST['at']}: ran {pipeline.LAST['ran']}, proposed {pipeline.LAST['proposed']} "
                  f"{pipeline.LAST['note']}")
    elif a.op == "log":
        for r in pipeline.log_runs(a.id, a.limit):
            print(f"{r['ts']}  #{r['job_id']:<4} {r['stage']:<9} {r['origin']:<10} {r['outcome']:<8} ai={r['ai']} {r['detail'][:100]}")


def _print_mail(r: dict) -> None:
    print(f"Subject: {r['draft'].get('subject', '')}\n\n{r['draft'].get('body', '')}\n\n-> {r['proposal']}")


DRAFTS_LAST = HOME / "draft_options.json"  # the options --options printed, so --pick N reuses them without an AI call


def _draft(kind: str, ctx: dict, a) -> None:
    """--options: print up to 3 numbered options (one AI call) and keep them; --pick N: use option N of the kept ones
    (proposed for review in the Inbox, or written into the pending item). Both: generate, then pick."""
    from . import drafts

    key = {"kind": kind, "ctx": ctx}
    if getattr(a, "options", False):
        opts = drafts.options(kind, ctx, provider=a.provider)
        DRAFTS_LAST.write_text(json.dumps(key | {"options": opts}), encoding="utf-8")
        for i, o in enumerate(opts, 1):
            print(f"[{i}] {o['label']} ({o['tone']})" + (f"  RECOMMENDED: {o['why']}" if o["recommended"] else ""))
            print((f"Subject: {o['subject']}\n" if o.get("subject") else "") + o["body"] + "\n")
        if not a.pick:
            print("pick one: the same command with --pick N (nothing is proposed until you do)")
    if a.pick:
        saved = json.loads(DRAFTS_LAST.read_text(encoding="utf-8")) if DRAFTS_LAST.is_file() else {}
        if {k: saved.get(k) for k in key} != key:
            raise SystemExit("no kept options for this draft: run the same command with --options first")
        if not 1 <= a.pick <= len(saved["options"]):
            raise SystemExit(f"--pick takes 1 to {len(saved['options'])}")
        r = drafts.use(kind, ctx, saved["options"][a.pick - 1])
        if "draft" in r:
            _print_mail(r)
        elif "payload" in r:
            print(f"inbox #{r['id']} updated; still waiting for your approval (lodestar inbox -v)")
        else:
            print(f"wrote {r['path']}" if "path" in r else f"{r['answer']}\n\n[save -> {r['proposal'].get('status')}]")


def cmd_draft(a):
    from . import approvals, drafts

    if a.op == "options":
        ctx = {"job": a.id, **{k: v for k, v in (("mail_id", a.mail), ("pending_id", a.pending), ("contact_id", a.contact),
                                                 ("interviewer", a.interviewer), ("notes", a.notes), ("person", a.person),
                                                 ("cite", a.cite), ("ask", a.ask), ("question", a.question)) if v}}
        a.options = a.options or not a.pick  # bare `draft options` prints them
        return _draft(a.kind, ctx, a)
    if a.pending:  # rewrite: an Inbox email is changed in place (subject and body only) and stays pending
        p = json.loads(db.get_pending(a.pending)["payload"])
        r = drafts.rewrite(p.get("body", ""), a.how, "email", p.get("subject", ""), a.provider)
        approvals.edit(a.pending, r.get("subject"), r["body"])
        print(f"Subject: {r.get('subject', '')}\n\n{r['body']}\n\n-> inbox #{a.pending} updated; still waiting for your approval")
    elif a.file:
        print(drafts.rewrite(Path(a.file).read_text(encoding="utf-8-sig"), a.how, "email", None, a.provider)["body"])
    else:
        raise SystemExit("rewrite what: --pending ID (an Inbox email) or --file FILE")


def cmd_suggest(a):
    from .drafts import snooze, suggest_emails

    if a.dismiss:
        snooze(int(a.dismiss[0]), a.dismiss[1])
        return print(f"#{a.dismiss[0]} {a.dismiss[1]}: dismissed for 3 days")
    rows = suggest_emails()
    print(f"Suggested emails: {len(rows) or 'none'}  (no AI used)")
    for s in rows:
        extra = f" --mail {s['mail_id']}" if s.get("mail_id") else f" --contact {s['contact_id']}" if s.get("contact_id") else ""
        print(f"  [{s['priority']}] due {s['due']}  #{s['job_id']:<4} {s['company'][:24]:<24} {s['kind']:<9} {s['reason']}"
              f"  -> {s['to'] or '(no address yet)'}\n      lodestar draft options {s['kind']} {s['job_id']}{extra}")


def _rec_line(r: dict) -> str:
    head = f"[{r['id']}] {r['label'] or r['field']}  ({r['impact']} impact, {r['risk']} risk)" + ("" if r["appliable"] else "  advice")
    flags = f"\n      blocked: {'; '.join(r['flags'])}" if r["flags"] else ""
    cur = f"\n      now:  {r['current'][:300]}" if r["current"] else ""
    return f"  {head}{cur}\n      new:  {r['proposed'][:600]}\n      why:  {r['reason']}{flags}"


def cmd_advise(a):
    from . import advisor

    if a.history:
        rows = advisor.history(a.limit)
        print(f"AI change batches: {len(rows) or 'none'}")
        for b in rows:
            print(f"  batch {b['batch']:<4} {b['ts']}  {b['mode']:<5} {len(b['changes'])} change(s)" + ("  (undone)" if b["undone"] else ""))
            for ch in b["changes"]:
                print(f"      {ch['scope']:<9} {ch['label'] or ch['field']}" + ("  undone" if ch["undone_at"] else ""))
        return
    if a.undo is not None:
        r = advisor.undo(a.undo)
        print(f"batch {r['batch']}: {r['undone']} change(s) put back")
        for s in r["skipped"]:
            print(f"  kept: {s['field']}: {s['why']}")
        return _advised_profile(r["batch"])
    if not a.scope and not a.apply:
        raise SystemExit(f"name a scope: {', '.join(advisor.SCOPES)} (or --apply IDS / --history / --undo BATCH)")
    if a.apply:
        r = advisor.apply(a.apply)
    elif a.auto:
        r = advisor.auto(a.scope, a.target, a.provider)
    elif a.list:
        rows = advisor.pending(a.scope, a.target)
        print(f"open recommendations: {len(rows) or 'none'}")
        return print("\n".join(map(_rec_line, rows))) if rows else None
    else:
        rows = advisor.recommend(a.scope, a.target, a.provider)
        print(f"{len(rows) or 'no'} recommendation(s) (one AI call; nothing changed yet). Apply: lodestar advise {a.scope}"
              f"{' ' + str(a.target) if a.target is not None else ''} --apply ID,ID")
        return print("\n".join(map(_rec_line, rows))) if rows else None
    print(f"applied {len(r['applied'])}" + (f" as batch {r['batch']} (undo: lodestar advise --undo {r['batch']})" if r["batch"] else ""))
    for s in r["skipped"]:
        print(f"  skipped #{s['id']}: {s['why']}")
    _advised_profile(r["batch"])


def cmd_ai_help(a):
    from . import advisor

    if not a.name:
        print("AI helpers (one AI call each; nothing is changed: an appliable one gives suggestions for advise --apply):")
        for k, h in advisor.helpers().items():
            print(f"  {k:<16} {h['where']:<9} {h['label']}" + ("  (suggestions)" if h["appliable"] else ""))
        return print("settings to explain: " + ", ".join(k for k, _ in advisor.topics()))
    r = advisor.assist(a.name, a.target, a.provider)
    if "recommendations" in r:
        print(f"{len(r['recommendations']) or 'no'} suggestion(s); apply: lodestar advise {r['scope']} {r['target']} --apply ID,ID")
        return print("\n".join(map(_rec_line, r["recommendations"]))) if r["recommendations"] else None
    print(f"{r['title']}\n\n{r['text']}")


def _advised_profile(batch) -> None:
    """The master resume follows a batch that changed profile.md or the bank (rebuilt once, offline)."""
    if batch and db.con().execute("SELECT 1 FROM ai_changes WHERE batch=? AND scope IN ('profile', 'bank')", (batch,)).fetchone():
        _sync_master()


def cmd_followup(a):
    from . import apply

    if a.options or a.pick:
        return _draft("followup", {"job": a.id}, a)
    _print_mail(apply.followup(db.get_job(a.id), a.provider, a.template))


def cmd_thanks(a):
    from . import apply

    if a.options or a.pick:
        return _draft("thanks", {"job": a.id, "interviewer": a.interviewer or "", "notes": a.notes or ""}, a)
    _print_mail(apply.thanks(db.get_job(a.id), a.interviewer or "", a.notes or "", a.provider, a.template))


def cmd_withdraw(a):
    from . import apply

    if a.options or a.pick:
        return _draft("withdraw", {"job": a.id}, a)
    _print_mail(apply.withdraw(db.get_job(a.id), a.provider, a.template))


def cmd_today(a):
    from .loop import agenda

    ag = agenda()
    for label, key in (("Next actions due", "actions"), ("Deadlines within 3 days", "deadlines"),
                       ("Interviews within 48 h", "interviews"), ("Follow-ups due", "followups"),
                       ("Postings closed (last 7 days)", "closed")):
        print(f"{label}: {len(ag[key]) or 'none'}")
        for i in ag[key]:
            extra = f"  {'OVERDUE ' if i.get('overdue') else ''}{i['what']}" if "what" in i else ""
            print(f"  #{i['id']:<4} {i['when']:<20} {i['company'][:24]} - {i['title'][:38]}{extra}")
    print(f"Contacts to get in touch with: {len(ag['contacts']) or 'none'}")
    for c in ag["contacts"]:
        print(f"  contact #{c['id']:<4} {c['when']:<12} {c['name'][:30]}" + (f" ({c['company'][:30]})" if c["company"] else ""))
    print(f"Suggested emails: {len(ag['emails']) or 'none'}" + ("  (lodestar suggest)" if ag["emails"] else ""))
    for s in ag["emails"]:
        print(f"  #{s['job_id']:<4} due {s['due']:<11} {s['kind']:<9} {s['company'][:24]} - {s['reason'][:60]}")
    print(f"Chance boosters: {len(ag['boosters']) or 'none'}" + ("  (lodestar boosters)" if ag["boosters"] else ""))
    for b in ag["boosters"]:
        j = b.get("job")
        print(f"  [{b['effect']:<6}] {b['text'][:70]}" + (f"  (#{j['id']} {j['company'][:24]})" if j else ""))
    print(f"Inbox: {ag['pending']} waiting" + ("  (lodestar inbox)" if ag["pending"] else ""))


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
        print(ideas.render(ideas.merged(r)))
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
        try:
            comp.set_range(a.title, a.city or "*", a.low, a.high)
        except ValueError as e:
            raise SystemExit(str(e)) from None
        print(f"recorded {a.title} / {a.city or '*'}: {a.low}-{a.high}")
    elif a.op == "lookup":
        print(comp.lookup(a.title, a.city or "") or "no match")
    elif a.op == "market":
        _market(a)
    else:
        for t, cities in comp.load().items():
            for c, (lo, hi) in cities.items():
                print(f"{t:<30} {c:<16} {lo:>9} - {hi:<9}")
        if not comp.load():
            print("empty: lodestar comp set \"software engineer\" austin 130000 170000")


def _market(a):
    """lodestar comp market ID [--soc X|none|auto] [--ai]: the job's public BLS figures; fetches what is missing."""
    from . import paydata, settings

    if not settings.pref("market_pay"):
        raise SystemExit("market pay is off (Lodestar never contacts api.bls.gov): lodestar tools set market_pay on")
    job = db.get_job(a.id)
    if a.soc:
        paydata.set_soc(a.id, "" if a.soc == "auto" else a.soc)
    if a.ai and not paydata.match_ai(job, a.provider):
        raise SystemExit("AI could not match an occupation: pick one with --soc NN-NNNN")
    job, tried = db.get_job(a.id), set()
    while (nxt := paydata.for_job(job).get("next")) and tuple(nxt) not in tried and len(tried) < 3:
        tried.add(tuple(nxt))
        if err := paydata.fetch([nxt]).get("error"):
            print(err)
            break
    r = paydata.for_job(job)
    s, area = r.get("soc"), r.get("area")
    print(f"#{job['id']} {job['company']} - {job['title']}")
    print(f"occupation: {s['name']} ({s['soc']}), {s['by']}" if s else
          "occupation: none matched (--soc 15-1252, or --ai to let your AI pick from the list)")
    if r["state"] == "no_area":
        print(f"area: '{r['location']}' is not a recognised U.S. metro or state (BLS covers U.S. jobs only; add the "
              "state, e.g. 'Boise, ID')")
    elif area:
        print(f"area: {area['name']} ({r.get('area_note') or area['why']})")
    if p := r.get("pay"):
        print("BLS: " + " | ".join(f"{paydata.LABEL[k]} {paydata._amount(p, k)}" for k in
                                   ("p10", "p25", "p50", "p75", "p90", "mean") if p[k] is not None))
        if r.get("posting_band"):
            print("this posting: " + ", ".join(f"{k} at {v}" for k, v in r["posting_band"].items()))
        print(r["label"])
    elif r["state"] in ("missing", "unpublished"):
        print("BLS publishes no figure for this occupation here" if r["state"] == "unpublished" else "no figure cached yet")


def cmd_variants(a):
    rows = db.variant_stats()
    if not rows:
        print("no tailored resumes sent yet (variants appear once tailored applications leave 'saved')")
    for v in rows:
        print(f"{v['variant']}  sent {v['applied']:<3} positive {v['positive']:<3} rejected {v['rejected']:<3} "
              f"response {v['response_rate']:.0%}  interview {v['interview_rate']:.0%}")


def cmd_insights(a):
    from . import extras

    d = extras.analytics(a.weeks)
    if a.json:
        return _p(d)
    keys = ("applications", "interviews", "offers", "contacts", "mock_sessions")
    print(f"{'week':<9} {'from':<11}" + "".join(f"{k.replace('_', ' '):>14}" for k in keys))
    for w in d["weeks"]:
        print(f"{w['week']:<9} {w['start']:<11}" + "".join(f"{w[k]:>14}" for k in keys))

    def rates(title, groups):
        print(f"\n{title} (applications that left 'saved'; under {d['min_n']}: not enough data yet)")
        for g in groups:
            print(f"  {g['group']:<22} n={g['n']:<4} " + (f"response {g['response_rate']:.0%}  interview {g['interview_rate']:.0%}"
                                                       if g["enough"] else "not enough data yet"))
    rates("Response rate by source", d["by_source"])
    rates("Response rate by fit score", d["by_band"])
    st = d["funnel"]["stages"]
    print("\nFunnel: " + "  ".join(f"{s} {v['reached']}" + (f" -> {v['conversion']:.0%}" if v["conversion"] is not None else "")
                                   + (f" ({v['median_days_to_next']}d)" if v["median_days_to_next"] is not None else "")
                                   for s, v in st.items()))
    for v in d["variants"]:
        print(f"resume variant {v['variant']}: sent {v['applied']}, " + (f"interview {v['interview_rate']:.0%}" if v["applied"] >= d["min_n"]
                                                                          else "not enough data yet"))
    print("\nWeekly goals: " + ("  ".join(f"{g['label']} {g['done']}/{g['target']}" for g in d["goals"]) or
                                "none set (lodestar tools set weekly_goals contacts=5; tailored_applications=N, mock_sessions=N, applications=N)"))


def _offer_table(d: dict) -> str:
    rows = d["offers"]
    if not rows:
        return "no live offers (jobs at status offer or accepted). Record one: lodestar offers set ID base=150000 bonus_pct=10"
    w = 18
    out = [f"{'':<18}" + "".join(f"{('#' + str(r['job_id']) + ' ' + r['company'])[:w - 1]:<{w}}" for r in rows)]
    labels = {"base": "base", "bonus": "bonus (target)", "sign_on": "sign-on", "match": "retirement match",
              "equity_year1": "equity year 1", "year1_cash": "year-1 cash", "year1_total": "year-1 total",
              "four_year_total": "4-year total"}
    for k, label in labels.items():
        out.append(f"{label:<18}" + "".join(f"{(format(r['total'][k], ',') + (' *' if r['job_id'] in d['best'].get(k, []) else '')):<{w}}"
                                            for r in rows))
    mkt = [f"{r['market']['low']:,}-{r['market']['high']:,}" if r["market"] else "-" for r in rows]
    out.append(f"{'market range':<18}" + "".join(f"{m:<{w}}" for m in mkt))
    bls = [f"{p['p50']:,}/{p['p75']:,}" if (p := (r.get("paydata") or {}).get("pay")) and p["p50"] and p["p75"] else "-"
           for r in rows]
    if any(b != "-" for b in bls):
        out.append(f"{'BLS median/75th':<18}" + "".join(f"{b:<{w}}" for b in bls))
        out.append(f"{'base vs BLS':<18}" + "".join(f"{(r['paydata'].get('base_band') or '-'):<{w}}" for r in rows))
    if d["floor"]:
        out.append(f"{'vs your floor':<18}" + "".join(f"{(format(r['vs_floor'], '+,') if r['vs_floor'] is not None else '-'):<{w}}"
                                                      for r in rows))
    for k in ("remote", "start_date", "deadline"):
        out.append(f"{k.replace('_', ' '):<18}" + "".join(f"{str(r['offer'].get(k) or '-'):<{w}}" for r in rows))
    est = sorted({e for r in rows for e in r["total"]["estimates"]})
    return "\n".join(out + ["* best in the row", *(["estimates: " + "; ".join(est)] if est else []),
                            *(["the floor row is private: it is never put in anything sent to an employer"] if d["floor"] else [])])


def cmd_offers(a):
    from . import apply, comp

    if a.op == "set":
        changed = db.set_offer(a.id, **_kv(a.pairs, db.OFFER_FIELDS))
        print(f"#{a.id} offer: " + ", ".join(f"{k}={'' if v is None else v}" for k, v in changed.items()))
        print(f"(status: {db.get_job(a.id)['status']})")
    elif a.op == "counter":
        if a.options or a.pick:
            return _draft("counter", {"job": a.id, "cite": a.cite or [], "ask": a.ask or ""}, a)
        _print_mail(apply.counter(db.get_job(a.id), a.cite or [], a.ask or "", a.provider, a.template))
    else:
        print(_offer_table(comp.compare()))


def cmd_activity(a):
    from datetime import date, timedelta

    from . import extras

    if a.week and (getattr(a, "from") or a.to):
        raise SystemExit("use --week, or --from / --to, not both")
    if a.to and not getattr(a, "from"):
        raise SystemExit("--to needs --from")
    if getattr(a, "from"):
        start, end = getattr(a, "from"), a.to or date.today().isoformat()
    else:
        start = extras.monday(extras._day(a.week) if a.week else date.today())
        end = start + timedelta(days=6)
    if a.csv or a.html:
        print(f"wrote {extras.activity_export(start, end, 'csv' if a.csv else 'html')}")
        return
    rep = extras.activity_report(start, end)
    print(f"Activity {rep['from']} to {rep['to']}. {rep['note']}")
    for wk in rep["weeks"]:
        need = f" / minimum {rep['minimum']} ({'met' if wk['met'] else 'not met'})" if rep["minimum"] else ""
        print(f"\nweek of {wk['week']}: {wk['count']}{need}")
        for r in rep["rows"]:
            if extras.monday(extras._day(r["date"])).isoformat() == wk["week"]:
                print(f"  {r['date']}  {r['activity']:<12} {r['employer'][:24]:<24} {r['position'][:28]:<28} {r['method']:<9} "
                      f"{r['contact'][:30]:<30} {r['result']}")


# ---------------------------------------------------------------- parser
def filter_args(x) -> None:
    """Search filters (web_monitor.refine); unknown salary / location / date pass and are marked."""
    x.add_argument("--location", help="substring of the listing location, or 'remote'")
    x.add_argument("--min-salary", help="top of the stated range at least this (120000 or 120k; currency not converted)")
    x.add_argument("--posted-within", type=int, metavar="DAYS")
    x.add_argument("--seniority", choices=["intern", "junior", "mid", "senior", "staff", "lead", "manager"], help="read off the title")


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

    s = sub.add_parser("keys", help="link AI keys (verified at once, re-checked at every app start), check, remove")
    v = s.add_subparsers(dest="op")
    x = v.add_parser("list")
    x = v.add_parser("link", help="NAME: anthropic, openai, gemini, groq, openrouter, mistral or ollama (or ANTHROPIC_API_KEY ...)")
    x.add_argument("name")
    x = v.add_parser("check"); x.add_argument("name", nargs="?")
    x = v.add_parser("rm"); x.add_argument("name")
    s.set_defaults(f=cmd_keys, op="list")

    s = sub.add_parser("vault", help="OS-keyring credential store (API keys, site logins, email)")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("set"); x.add_argument("name"); x.add_argument("value", nargs="?"); x.add_argument("--user")
    x = v.add_parser("get"); x.add_argument("name"); x.add_argument("--show", action="store_true")
    x = v.add_parser("rm"); x.add_argument("name")
    v.add_parser("list")
    s.set_defaults(f=cmd_vault)

    s = sub.add_parser("jobs", help="application tracker + job search")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add", help="track a job: --url, --jd (URL, file or text; pay and remote are read from it), --notes"); x.add_argument("company"); x.add_argument("title"); x.add_argument("--url"); x.add_argument("--jd", help="url, file, or text"); x.add_argument("--notes")
    x = v.add_parser("list", help="tracked jobs with pay, stars, workplace, deadline and tags; filters and sort"); x.add_argument("--status", choices=db.STATUSES)
    x.add_argument("--sort", choices=list(db.SORTS), help="default: updated (most recent first)")
    x.add_argument("--remote", choices=db.REMOTE); x.add_argument("--min-salary", type=int, help="top of the stated range")
    x.add_argument("--tag")
    x = v.add_parser("set", help="tracker fields: " + ", ".join(db.FIELDS) + " (key=value; empty value clears)")
    x.add_argument("id", type=int); x.add_argument("pairs", nargs="+", metavar="key=value")
    x = v.add_parser("show", help="every field plus the event timeline"); x.add_argument("id", type=int)
    x = v.add_parser("status", help="move a job: applied stamps applied_at; accepted offers to withdraw the others"); x.add_argument("id", type=int); x.add_argument("status", choices=db.STATUSES); x.add_argument("--note")
    x = v.add_parser("note", help="append a note (also logged on the timeline)"); x.add_argument("id", type=int); x.add_argument("text")
    x = v.add_parser("jd", help="replace the job description"); x.add_argument("id", type=int); x.add_argument("source", help="url, file, or text")
    x = v.add_parser("rm", help="delete a job and its timeline"); x.add_argument("id", type=int)
    x = v.add_parser("contact", help="recruiter / hiring manager email for replies and follow-ups"); x.add_argument("id", type=int); x.add_argument("email"); x.add_argument("--name")
    x = v.add_parser("checklist", help="what is done and what is next for this application"); x.add_argument("id", type=int)
    v.add_parser("stats", help="counts, response rate, interview rate")
    v.add_parser("funnel", help="stage conversion, median days per stage, rejections by stage, outcomes by source")
    x = v.add_parser("packet", help="zip everything about one application (documents, JD, notes)"); x.add_argument("id", type=int)
    x = v.add_parser("followups", help="applications quiet for N+ days"); x.add_argument("--days", type=int, default=None, help="default: pref followup_days")
    x = v.add_parser("all", help="All jobs: every listing any source found (searches, watches, company boards, captures)")
    x.add_argument("--new", action="store_true", help="only listings first seen since the last 'Mark all seen'")
    x.add_argument("--min-fit", type=int, help="fit score at least this (0-100)")
    x.add_argument("--source", help="only listings one source found, e.g. remotive, adzuna, greenhouse")
    x.add_argument("--show", choices=("open", "tracked", "dismissed", "all"), default="open")
    x.add_argument("--sort", choices=("fit", "new", "salary", "company"), default="fit")
    x.add_argument("--offset", type=int, default=0)
    x = v.add_parser("track-listing", help="add an All jobs listing (id L<n> from jobs all) to the tracker")
    x.add_argument("id", type=int)
    x = v.add_parser("search", help="job APIs: Remotive, Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, The Muse, "
                                    "Himalayas, We Work Remotely; Adzuna and USAJOBS once their keys are set")
    x.add_argument("query"); x.add_argument("--keywords", help="comma list, must appear in title/desc")
    x.add_argument("--rank", action="store_true", help="AI fit score vs your profile"); x.add_argument("--limit", type=int, default=25)
    x.add_argument("--save", type=int, nargs="*", help="result indexes to add to tracker")
    x.add_argument("--auto", action="store_true", help="AI-judge results and propose/track strong fits (tool: auto_track)")
    filter_args(x)
    s.set_defaults(f=cmd_jobs)

    s = sub.add_parser("resume", help="tailor, gap-check, cover letter, review, lint, file audit, export")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("gap"); x.add_argument("id", type=int)  # one structured JSON score: no council pooling
    for name in ("tailor", "cover"):
        x = v.add_parser(name); x.add_argument("id", type=int); x.add_argument("--council", action="store_true", help="pool all providers")
        if name == "tailor":
            x.add_argument("--docx", action="store_true")
            x.add_argument("--base", metavar="ID", help="start from this saved resume (ids: lodestar profile show) instead of the master")
            x.add_argument("--bullets", action="store_true", help="per-bullet proposals with no-invention flags, saved to bullets.json")
            x.add_argument("--accept", metavar="WHICH", help="build resume.md from bullets.json: all, unflagged, or numbers like 1,3,5")
        if name == "cover":
            x.add_argument("--tone", default="confident, warm, specific")
            x.add_argument("--words", type=int, default=300)
            x.add_argument("--docx", action="store_true")
    x = v.add_parser("import", help="bring in an existing resume (.docx/.pdf/.md/.txt); --merge folds it into the profile")
    x.add_argument("file"); x.add_argument("--merge", action="store_true"); x.add_argument("--save", action="store_true")
    x = v.add_parser("adjust", help="AI-revise the master profile or a job document with an instruction")
    x.add_argument("instruction"); x.add_argument("--job", type=int); x.add_argument("--doc", help="resume.md (default) or cover_letter.md"); x.add_argument("--save", action="store_true")
    x = v.add_parser("review"); x.add_argument("file", nargs="?", help="defaults to master profile")
    x = v.add_parser("lint", help="deterministic checks: weak openers, missing numbers, pronouns, cliches, sections, gaps")
    x.add_argument("file", nargs="?", help=".md/.txt/.docx/.pdf; defaults to the master profile"); x.add_argument("--job", type=int, help="the job's tailored resume")
    x = v.add_parser("audit", help="file checks a parser trips on (header contact, tables, text boxes, columns, scans) + the text it sees")
    x.add_argument("file", help=".docx or .pdf")
    x = v.add_parser("export", help="markdown -> .docx, or a PDF with --pdf (Word, else LibreOffice, else a browser print page)")
    x.add_argument("file", help="a job id (its tailored resume.md) or a markdown file")
    x.add_argument("--pdf", action="store_true"); x.add_argument("--style", choices=settings.CHOICES["resume_style"], help="default: pref resume_style")
    v.add_parser("profile", help="print master profile path")
    x = v.add_parser("master", help="the master resume built from your profile (resumes/master.pdf/.docx/.md/.txt)")
    x.add_argument("--rebuild", action="store_true", help="rebuild it now")
    x = v.add_parser("build", help="the resume studio: a version from a request + requirements (AI plan citing your facts, "
                                   "or offline with --no-ai), as PDF / DOCX / MD / TXT / HTML in studio/<id>/")
    x.add_argument("--request", help="what you want, in words: 'one page, lead with leadership, navy accent'")
    x.add_argument("--job", type=int, help="target this tracked job (its JD)"); x.add_argument("--jd", help="or a JD: file, URL or text")
    x.add_argument("--from", metavar="VID", help="refine this version with --request")
    x.add_argument("--pages", type=int, choices=(0, 1, 2), help="page limit (0: none)")
    x.add_argument("--style", choices=settings.CHOICES["resume_style"], help="template")
    x.add_argument("--font"); x.add_argument("--size", type=float, help="body pt (9.5-12)")
    x.add_argument("--accent", help="#rrggbb or navy, blue, teal, green, burgundy, gray, black")
    x.add_argument("--margins", type=float, help="inches (0.4-1.25)"); x.add_argument("--spacing", type=float, help="line spacing (1.0-1.5)")
    x.add_argument("--paper", choices=("letter", "a4")); x.add_argument("--date-format", dest="date_format", help="Mar 2021 | March 2021 | 03/2021 | 2021-03 | 2021")
    x.add_argument("--contact", choices=("one_line", "two_lines", "centered")); x.add_argument("--density", choices=("compact", "normal", "airy"))
    x.add_argument("--sections", help="comma list in order, e.g. summary,experience,skills,education")
    x.add_argument("--bullets", type=int, help="bullets per role (0: all)"); x.add_argument("--drop", help="fact ids to leave out, e.g. e3,p2 (resume catalogue)")
    x.add_argument("--since", type=int, metavar="YEAR", help="leave out entries that ended before this year")
    x.add_argument("--on-file", dest="on_file", action="store_true", help="also use facts from your other resumes")
    x.add_argument("--format", help="comma list of pdf, docx, md, txt, html (default pdf,docx)")
    x.add_argument("--no-ai", dest="no_ai", action="store_true", help="offline: your profile as written, no request")
    x.add_argument("--use-for-job", dest="use_for_job", action="store_true", help="make it the job's resume.md / .docx / .pdf")
    v.add_parser("versions", help="studio versions, newest first")
    x = v.add_parser("open", help="open a studio version's file"); x.add_argument("vid"); x.add_argument("--format", choices=("pdf", "docx", "md", "txt", "html"))
    v.add_parser("catalogue", help="your facts with the ids the studio and --drop use")
    s.set_defaults(f=cmd_resume)

    s = sub.add_parser("match", help="JD coverage: which of the posting's keywords your resume mentions (no AI; not an ATS verdict)")
    s.add_argument("id", type=int); s.add_argument("--file", help="score this resume file instead (.md/.txt/.docx/.pdf; not saved)")
    s.add_argument("--skip", action="append", metavar="TERM", help="mark a keyword 'not mine' for this job (again to undo)")
    s.set_defaults(f=cmd_match)

    s = sub.add_parser("fit", help="fit score: one job's breakdown (parts, weights, chips), or `fit refresh` for every stale one (no AI)")
    s.add_argument("target", help="a job id, or 'refresh'"); s.add_argument("--limit", type=int, default=300, help="refresh: at most this many")
    s.set_defaults(f=cmd_fit)

    s = sub.add_parser("apply-agent", help="the apply agent: fills an application in its own browser window (stop: you press "
                                           "Submit; review: the Inbox first; auto: within every gate)")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("run", help="apply to these jobs now, one at a time (Ctrl+C stops; the window closes with it)")
    x.add_argument("ids", type=int, nargs="+"); x.add_argument("--mode", choices=("stop", "review", "auto"))
    x.add_argument("--eeo", action="store_true", help="type your saved EEO answers"); x.add_argument("--headless", action="store_true")
    v.add_parser("status", help="live and recent runs, and what they need from you")
    v.add_parser("stop", help="stop the agent (any process); its tabs stay open while Lodestar runs")
    x = v.add_parser("continue", help="continue a run after you signed in, typed a code or allowed a host"); x.add_argument("run", type=int)
    x = v.add_parser("login", help="a plain browser window on the agent's profile: sign in to a site once, by hand")
    x.add_argument("url", nargs="?")
    v.add_parser("forget", help="delete the agent's browser profile (every site sign-in it holds)")
    x = v.add_parser("runs", help="a job's runs: outcome, who submitted, confirmation, evidence folder"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_apply_agent)

    s = sub.add_parser("accounts", help="site accounts the apply agent signs in with (one per site; passwords only in the "
                                        "OS keyring): list, add, password, remove")
    v = s.add_subparsers(dest="op")
    x = v.add_parser("list", help="every site account with its status, dates and jobs"); x.add_argument("--q", default="")
    x = v.add_parser("add", help="save a login you already have (no --password: asked, empty = Lodestar makes one)")
    x.add_argument("url"); x.add_argument("username"); x.add_argument("--password")
    x = v.add_parser("password", help="change the stored password (--generate prints a new one for the site's form)")
    x.add_argument("id", type=int); x.add_argument("--password"); x.add_argument("--generate", action="store_true")
    x = v.add_parser("remove", help="forget the account (its password leaves the OS keyring)"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_accounts)

    s = sub.add_parser("intel", help="job intelligence: company facts and news, hiring signals, role and pay context, "
                                     "each with its source and date")
    s.add_argument("id", type=int)
    s.add_argument("--gather", action="store_true", help="read the company's site, its news feed and Wikipedia (cached 7 days)")
    s.add_argument("--refresh", action="store_true", help="gather again even when the cache is fresh")
    s.add_argument("--summary", action="store_true", help="one AI summary citing the sources [S#]")
    s.set_defaults(f=cmd_intel)

    s = sub.add_parser("boosters", help="chance boosters: ranked actions with their expected effect (never a probability)")
    s.add_argument("id", type=int, nargs="?", help="a job id; omit for the best across your search")
    s.add_argument("--ai", action="store_true", help="one AI call: up to 3 job-specific additions, each with its basis")
    s.set_defaults(f=cmd_boosters)

    s = sub.add_parser("profile", help="profile bank: saved resumes, skills, languages, LinkedIn import")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("show", help="what the bank holds: contact, skills, languages, roles, saved resumes")
    for name, what in (("import", "a resume (.docx/.pdf/.md/.txt): saves the original, reads its facts into a review"),
                       ("linkedin", "LinkedIn 'Download your data' .zip, or the profile 'Save to PDF' file")):
        x = v.add_parser(name, help=what); x.add_argument("file")
        x.add_argument("--no-ai", action="store_true", help="offline extraction only (never sent to an AI provider)")
        _review_args(x)
    x = v.add_parser("review", help="imports waiting for review: list, show one, apply (--accept) or --discard")
    x.add_argument("pid", nargs="?"); _review_args(x)
    x.add_argument("--discard", action="store_true", help="drop it: the bank and profile.md stay as they are")
    v.add_parser("reread", help="re-read profile.md into a review (fixes older bank entries, picks up typed roles)")
    x = v.add_parser("link", help="store your LinkedIn profile URL"); x.add_argument("url")
    for name in ("add", "remove"):
        x = v.add_parser(name, help=f"{name} a skill / language / certification by hand")
        x.add_argument("kind", choices=["skills", "languages", "certifications"]); x.add_argument("name")
        if name == "add":
            x.add_argument("--detail", help="category (skills), proficiency (languages) or issuer (certifications)")
    v.add_parser("rebuild", help="regenerate profile.md from the bank (snapshots the old one)")
    s.set_defaults(f=cmd_profile)

    s = sub.add_parser("email", help="connect your mailbox; IMAP monitor: classify replies, update tracker")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("connect", help="store address, servers and app password (prompted, never echoed), then test")
    from .mailconn import PRESETS

    x.add_argument("--preset", choices=list(PRESETS),
                   help="default: guessed from the address, else custom")
    x.add_argument("--user", help="your email address")
    for k in ("imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_user"):
        x.add_argument("--" + k.replace("_", "-"), dest=k)
    x.add_argument("--imap-mode", dest="imap_mode", choices=["ssl", "starttls"], help="starttls for Proton Mail Bridge's default")
    x.add_argument("--smtp-mode", dest="smtp_mode", choices=["ssl", "starttls"])
    x.add_argument("--cafile", help="trust only this certificate file (Proton Mail Bridge's exported certificate)")
    x = v.add_parser("client", help="store your own OAuth client for sign-in (docs/CONNECT.md)")
    x.add_argument("provider", choices=["google", "microsoft"])
    x = v.add_parser("signin", help="sign in with Google or Microsoft in your browser (any 2-step method), then test")
    x.add_argument("provider", choices=["google", "microsoft"])
    x.add_argument("--work", action="store_true", help="Microsoft 365 work or school account")
    x.add_argument("--hint", help="your email address, to preselect the account")
    x.add_argument("--no-browser", dest="no_browser", action="store_true", help="print the sign-in page instead of opening it")
    v.add_parser("test", help="log in to IMAP and SMTP (sends nothing)")
    v.add_parser("test-send", help="send a short test email to your own address")
    v.add_parser("status", help="connected address and servers (never the password)")
    v.add_parser("disconnect", help="remove the stored app password, or sign out (Google: revokes the sign-in)")
    x = v.add_parser("check", help="scan the mailbox for hiring mail: classify, file under jobs, propose replies"); x.add_argument("--days", type=int, default=3); x.add_argument("--dry", action="store_true", help="report only, change nothing")
    x = v.add_parser("parse-alert", help="show what Lodestar reads from a saved job-alert email (.eml); changes nothing")
    x.add_argument("file"); x.add_argument("--trust", action="store_true", help="skip the DKIM/DMARC check (a saved file)")
    x = v.add_parser("reply", help="draft an email to the job's contact (waits in the Inbox)"); x.add_argument("id", type=int); x.add_argument("--intent", required=True, help="e.g. 'accept interview, propose Tue/Wed afternoons'")
    s.set_defaults(f=cmd_email)

    s = sub.add_parser("mail", help="mail Lodestar recorded: relevant scanned mail and everything it sent, by job")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("list", help="newest first: all, one job's (both ways), or incoming mail no job claims")
    g = x.add_mutually_exclusive_group(); g.add_argument("--job", type=int); g.add_argument("--unmatched", action="store_true")
    x = v.add_parser("link", help="file a message under a job (never sets the contact or trusts the sender)")
    x.add_argument("id", type=int); x.add_argument("job", type=int)
    x = v.add_parser("unlink", help="undo a link you made"); x.add_argument("id", type=int)
    x = v.add_parser("dismiss", help="drop an unmatched message from the list"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_mail)

    s = sub.add_parser("watch", help="career-page change alerts + saved job searches")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add", help="watch a careers page (http/https) for changes; --keywords filters the alert lines"); x.add_argument("url"); x.add_argument("--keywords")
    x = v.add_parser("search-add", help="save a job search: new listings alert each monitor cycle (filters kept on re-add)"); x.add_argument("query"); x.add_argument("--keywords")
    filter_args(x)
    v.add_parser("list", help="watches with keywords, filters, last good run and last error")
    x = v.add_parser("rm", help="remove a watch"); x.add_argument("id", type=int)
    v.add_parser("run", help="run every watch and watched company once now")
    s.set_defaults(f=cmd_watch)

    s = sub.add_parser("companies", help="watch companies' public job boards (Greenhouse, Lever, Ashby); new postings alert like saved searches")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add", help="careers or posting URL (boards.greenhouse.io/acme, jobs.lever.co/acme, jobs.ashbyhq.com/acme) "
                                 "or vendor:slug. Workday, Taleo and iCIMS have no public feed")
    x.add_argument("source"); x.add_argument("--name", help="display name (default: from the slug)"); x.add_argument("--keywords", help="comma list; only matching postings alert")
    v.add_parser("list")
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    s.set_defaults(f=cmd_companies)
    s = sub.add_parser("audit", help="the append-only audit trail: every policy decision (allow / needs you / block, with reasons) and every action run")
    s.add_argument("--limit", type=int, default=50); s.set_defaults(f=cmd_audit)
    s = sub.add_parser("careers", help="career discovery: occupations your profile fits (O*NET), career tracks you choose, track search with board coverage")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("suggest", help="occupations by career class: why it fits, what is missing, what does not transfer, how to close the gap")
    x.add_argument("--tiers", default="0,1,2,3,4,5", help="expansion tiers to show (0 your targets, 1 your occupations ... 5 longer-term)")
    x.add_argument("--limit", type=int, default=12); x.add_argument("--show-excluded", dest="show_excluded", action="store_true", help="show excluded ones as Currently ineligible")
    x = v.add_parser("occupation", help="one O*NET occupation: titles, tasks, technology, related, licensing"); x.add_argument("code")
    x = v.add_parser("explore", help="tier 6, Explore further: one AI call suggests occupations from what interests you, matched to O*NET")
    x.add_argument("interests", help='e.g. "working with people, puzzles, outdoors"'); x.add_argument("--provider")
    v.add_parser("tracks", help="your career tracks")
    x = v.add_parser("track-add", help="save a career track (a field to search; any field, even one your resume does not show)")
    x.add_argument("label"); x.add_argument("--intent", required=True, choices=["resume_led", "desired_field", "combined", "exploration", "pivot"])
    x.add_argument("--titles", help="comma list of job titles"); x.add_argument("--codes", help="comma list of O*NET codes")
    x.add_argument("--tiers", help="comma list 0-6 (default: desired_field 0, resume_led 1, others 0,1)")
    x.add_argument("--exclude", help="comma list of words to leave out"); x.add_argument("--location")
    x.add_argument("--training", default="none", choices=["none", "short_course", "certification", "apprenticeship", "degree", "open"])
    x.add_argument("--priority", default="medium", choices=["high", "medium", "exploratory"])
    x = v.add_parser("track-set", help="track fields: label, intent, titles, codes, tiers, exclusions, location, training, priority, enabled (key=value)")
    x.add_argument("id", type=int); x.add_argument("pairs", nargs="+", metavar="key=value")
    x = v.add_parser("track-rm", help="remove a track"); x.add_argument("id", type=int)
    x = v.add_parser("search", help="search the job boards for a track's titles; shows which boards were asked"); x.add_argument("id", type=int); x.add_argument("--location")
    s.set_defaults(f=cmd_careers)
    s = sub.add_parser("contacts", help="contacts CRM: people, the jobs they are linked to, last / next touch, LinkedIn import")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("add", help="add a person by hand"); x.add_argument("name")
    for f in ("email", "phone", "linkedin", "company", "position", "how-met", "notes"):
        x.add_argument(f"--{f}")
    x.add_argument("--next-touch", metavar="YYYY-MM-DD", help="when to get in touch next (opt-in cadence)")
    x = v.add_parser("list", help="name A-Z with company, position, last / next touch and linked jobs")
    x.add_argument("q", nargs="?", help="filter: name, company, position or email")
    x.add_argument("--due", action="store_true", help="only contacts whose next touch has come")
    x = v.add_parser("show", help="fields, linked jobs, recent timeline entries mentioning their email"); x.add_argument("id", type=int)
    x = v.add_parser("edit", help="fields: name, email, phone, linkedin_url, company, position, how_met, notes, last_touch, "
                                  "next_touch (key=value; empty value clears)")
    x.add_argument("id", type=int); x.add_argument("pairs", nargs="+", metavar="key=value")
    x = v.add_parser("rm", help="remove a contact (linked jobs stay)"); x.add_argument("id", type=int)
    x = v.add_parser("import", help="your LinkedIn 'Download your data' zip or its Connections.csv (de-duplicated; no follow-up dates set)")
    x.add_argument("file")
    v.add_parser("due", help="contacts whose next touch has come (also on the Today list; nothing is drafted for them)")
    x = v.add_parser("link", help="link a contact to a job with a role (again to change the role)")
    x.add_argument("id", type=int); x.add_argument("job", type=int)
    x.add_argument("--role", choices=["recruiter", "hiring_manager", "referrer", "interviewer", "other"], default="other")
    x.add_argument("--remove", action="store_true", help="unlink instead")
    s.set_defaults(f=cmd_contacts)
    s = sub.add_parser("sponsors", help="optional H-1B sponsor hints from the USCIS H-1B Employer Data Hub export you download")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("import", help="load the hub's CSV export (a fiscal year imported again replaces that year)"); x.add_argument("file")
    x = v.add_parser("lookup", help="check one employer name against your imported data"); x.add_argument("company")
    v.add_parser("clear", help="remove all imported sponsor data")
    s.set_defaults(f=cmd_sponsors)

    from .interview import COMPETENCIES, KINDS, OUTCOMES, QCOMP

    s = sub.add_parser("interview", help="prep pack, live mock interview with a score card per answer, interview rounds")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("prep", help="interview prep pack for one job (needs AI)"); x.add_argument("id", type=int); x.add_argument("--council", action="store_true")
    x = v.add_parser("mock", help="one question at a time; each answer gets a score card (STAR rubric needs AI)"); x.add_argument("id", type=int)
    x.add_argument("--focus", choices=QCOMP, help="practise one competency")
    x = v.add_parser("log", help="log an interview round (again with --round N to update that round)"); x.add_argument("id", type=int)
    x.add_argument("--round", type=int, help="round number (default: the next one)")
    x.add_argument("--kind", choices=KINDS); x.add_argument("--at", help='"YYYY-MM-DD HH:MM" (or just the date)')
    x.add_argument("--interviewers"); x.add_argument("--notes"); x.add_argument("--outcome", choices=OUTCOMES)
    x.add_argument("--questions-file", help="text file, one question you were asked per line")
    x = v.add_parser("rounds", help="a job's rounds with the questions asked"); x.add_argument("id", type=int)
    x = v.add_parser("questions", help="the sourced practice set, grouped by competency, each with where it came from")
    x.add_argument("id", type=int); x.add_argument("--refresh", action="store_true", help="re-read the company's pages + one AI build")
    x.add_argument("--offline", action="store_true", help="never call the AI")
    x = v.add_parser("sources", help="the company's question sources: website, pages read (status), your pastes"); x.add_argument("id", type=int)
    x = v.add_parser("paste", help="store interview reports you read yourself (never fetched); --file F, --text T or stdin")
    x.add_argument("id", type=int); x.add_argument("--label", required=True, help='where from, e.g. "Glassdoor reviews, read 2026-11-05"')
    x.add_argument("--url", help="link to where you read it (a citation: stored, never opened)")
    x.add_argument("--file", help="text file, or - for stdin"); x.add_argument("--text")
    x = v.add_parser("site", help="the company website (its public hiring / values pages are read; robots.txt respected)")
    x.add_argument("id", type=int); x.add_argument("url", help="https://... (empty string clears it)")
    x = v.add_parser("unsource", help="delete one paste or page of that job's company"); x.add_argument("id", type=int); x.add_argument("sid", type=int)
    x = v.add_parser("readiness", help="readiness 0-100 (preparation), the chance estimate band, the top 3 ways to raise it")
    x.add_argument("id", type=int)
    v.add_parser("calibration", help="your record: readiness vs round results, as plain counts")
    s.set_defaults(f=cmd_interview)
    s = sub.add_parser("questions", help="your question bank: logged at this company, then similar titles, then ~30 behavioural")
    s.add_argument("id", type=int, nargs="?", help="job id (without: every question you logged)")
    s.set_defaults(f=cmd_questions)
    s = sub.add_parser("stories", help="STAR story bank tagged by competency (prep and mock interviews use it)")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    x = v.add_parser("show"); x.add_argument("id", type=int)
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    x = v.add_parser("add", help="situation / task / action / result / metrics; or --from-idea ID (an ideas 'stories' idea)")
    x.add_argument("--title"); x.add_argument("--from-idea", type=int)
    for f in ("situation", "task", "action", "result", "metrics"):
        x.add_argument(f"--{f}", default="")
    x.add_argument("--tags", help=f"competencies, comma: {', '.join(COMPETENCIES)}")
    s.set_defaults(f=cmd_stories)

    def option_args(p):
        p.add_argument("--options", action="store_true", help="print up to 3 numbered options (one AI call; offline: the template)")
        p.add_argument("--pick", type=int, metavar="N", help="use option N of the last --options (proposed for review in the Inbox)")

    def loop_args(p):
        p.add_argument("--every", type=int, default=30, help="minutes")
        p.add_argument("--days", type=int, default=2, help="email lookback")
        p.add_argument("--followup", type=int, default=None, help="nudge after N quiet days (default: pref followup_days)")
        p.add_argument("--no-email", dest="email", action="store_false")
        p.add_argument("--no-update", dest="update", action="store_false", help="skip the update check (pref update_mode)")

    s = sub.add_parser("run", help="automation loop: email + watches + follow-up nudges")
    loop_args(s)
    s.add_argument("--once", action="store_true")
    s.set_defaults(f=cmd_run)

    s = sub.add_parser("doctor", help="check the install: Python, modules, WebView2, keyring, data folder, profile, providers, mail")
    s.add_argument("--live", action="store_true", help="also make one real call per configured provider")
    s.set_defaults(f=cmd_doctor)

    s = sub.add_parser("update", help="updates of this install: check, apply (backup, fast-forward, tests, rollback), status, log")
    v = s.add_subparsers(dest="op")
    v.add_parser("check", help="fetch the origin; show the commits and changelog an update would bring")
    x = v.add_parser("apply", help="show the update, then back up, fast-forward, test and roll back on failure")
    x.add_argument("--yes", action="store_true", help="apply without asking")
    v.add_parser("status", help="install kind, update preferences, last check and update")
    x = v.add_parser("log", help="every check and update: time, from, to, result"); x.add_argument("--limit", type=int, default=20)
    s.set_defaults(f=cmd_update)

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
    option_args(s)
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
    s = sub.add_parser("restore", help="put your data folder back to a backup zip (a safety backup first; keyring secrets stay)")
    s.add_argument("zip"); s.add_argument("--yes", action="store_true", help="restore without asking")
    s.set_defaults(f=cmd_restore)
    s = sub.add_parser("schedule", help="install/remove a background task that runs `lodestar run --once`")
    s.add_argument("op", choices=["install", "remove"]); s.add_argument("--every", type=int, default=30)
    s.set_defaults(f=cmd_schedule)
    sub.add_parser("variants", help="which tailored-resume variant gets responses").set_defaults(f=cmd_variants)
    s = sub.add_parser("insights", help="weekly activity, response rate by source and match score, funnel, variants, weekly goals")
    s.add_argument("--weeks", type=int, default=12); s.add_argument("--json", action="store_true"); s.set_defaults(f=cmd_insights)
    s = sub.add_parser("offers", help="live offers side by side (default: compare); set structured fields; draft a counter-offer")
    v = s.add_subparsers(dest="op")
    v.add_parser("compare", help="year-1 / 4-year totals, best per row, market range, gap to your private salary floor")
    x = v.add_parser("set", help="fields: " + ", ".join(db.OFFER_FIELDS) + " (key=value; 150k ok; empty clears)")
    x.add_argument("id", type=int); x.add_argument("pairs", nargs="+")
    x = v.add_parser("counter", help="draft a counter-offer citing competing figures; always waits in the Inbox")
    x.add_argument("id", type=int)
    x.add_argument("--cite", nargs="+", metavar="JOB:FIELD", help="competing figures, e.g. 7:base 7:sign_on (fields: base, "
                                                                   "bonus_pct, sign_on, equity_value_estimate, year1_total)")
    x.add_argument("--ask", help="what you ask for, e.g. 'a base of 170,000'")
    x.add_argument("--template", action="store_true", help="plain offline template instead of AI")
    option_args(x)
    s.set_defaults(f=cmd_offers, op=None)
    s = sub.add_parser("activity", help="your job-search activity log by week (helper report for unemployment claims)")
    s.add_argument("--week", metavar="YYYY-MM-DD", help="the week (Monday-Sunday) containing this date; default this week")
    s.add_argument("--from", metavar="YYYY-MM-DD"); s.add_argument("--to", metavar="YYYY-MM-DD")
    s.add_argument("--csv", action="store_true", help="write a CSV to ~/.lodestar/exports")
    s.add_argument("--html", action="store_true", help="write Markdown + a printable HTML page (print to PDF) to ~/.lodestar/exports")
    s.set_defaults(f=cmd_activity)
    s = sub.add_parser("comp", help="your market-rate table, used by gap checks and offer evaluation")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    x = v.add_parser("set"); x.add_argument("title"); x.add_argument("city", nargs="?"); x.add_argument("low", help="150000 or 150k"); x.add_argument("high")
    x = v.add_parser("lookup"); x.add_argument("title"); x.add_argument("city", nargs="?")
    x = v.add_parser("market", help="public BLS pay for a tracked job (needs: lodestar tools set market_pay on)")
    x.add_argument("id", type=int); x.add_argument("--soc", help="occupation: NN-NNNN, none (hide), auto (your pick removed)")
    x.add_argument("--ai", action="store_true", help="let your AI pick the occupation from the bundled list")
    s.set_defaults(f=cmd_comp)

    s = sub.add_parser("tools", help="turn automated AI tools on/off, manual (inbox) or auto; set preferences")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    for op in ("enable", "disable", "auto", "manual"):
        x = v.add_parser(op); x.add_argument("name")
    x = v.add_parser("set", help="preference: name, availability, auto_track_min_score, followup_days, reply_to_confirmations, "
                                     "weekly_target (applications/week, used by idea crafting), provider, council_providers, "
                                     "council_judge, signature, desktop_notifications, resume_style, excluded_companies and "
                                     "excluded_title_words (private search dealbreakers, comma lists), models (provider=model; also "
                                     "written by self-healing model selection), weekly_goals (goal=number: contacts, "
                                     "tailored_applications, mock_sessions, applications; 0 clears), activity_weekly_min "
                                     "(activities a week your unemployment claim asks for)")
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
    s = sub.add_parser("pipeline", help="step-by-step automation per job: states, run the next step or to a step, "
                                        "questions for you, Autopilot, run log")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("status", help="no JOB: one line per live job; JOB: the step table"); x.add_argument("id", type=int, nargs="?")
    x = v.add_parser("run", help="run the next step, --to STEP (stops at anything waiting, manual or stale) or --stage STEP")
    x.add_argument("id", type=int); x.add_argument("--to"); x.add_argument("--stage")
    x.add_argument("--rerun", action="store_true", help="also re-run stale (or done, with --stage) steps")
    x = v.add_parser("skip", help="skip a step for this job (e.g. letter), --undo to bring it back")
    x.add_argument("id", type=int); x.add_argument("stage"); x.add_argument("--undo", action="store_true")
    x = v.add_parser("questions", help="questions waiting for you (--all: answered and dismissed too)")
    x.add_argument("--all", action="store_true"); x.add_argument("--job", type=int)
    x = v.add_parser("answer", help="answer a question (reused for every job unless --job-only or --private)")
    x.add_argument("qid", type=int); x.add_argument("text"); x.add_argument("--job-only", action="store_true")
    x.add_argument("--private", action="store_true", help="this job only, never saved to the bank")
    x = v.add_parser("dismiss", help="I'll fill it in myself"); x.add_argument("qid", type=int)
    x = v.add_parser("add-questions", help="a job's application-form questions, one per line (FILE or - for stdin)")
    x.add_argument("id", type=int); x.add_argument("file")
    x = v.add_parser("autopilot", help="on / off / status: switches, budgets, AI calls in the last 24 h")
    x.add_argument("mode", choices=("on", "off", "status"), nargs="?", default="status")
    x = v.add_parser("log", help="the run log (newest first)"); x.add_argument("id", type=int, nargs="?")
    x.add_argument("--limit", type=int, default=50)
    s.set_defaults(f=cmd_pipeline)

    s = sub.add_parser("answers", help="answer bank for application-form questions")
    v = s.add_subparsers(dest="op", required=True)
    v.add_parser("list")
    x = v.add_parser("add"); x.add_argument("question"); x.add_argument("answer"); x.add_argument("--tags")
    x.add_argument("--private", action="store_true", help="for you only: never used in an employer-facing prompt or form")
    x = v.add_parser("rm"); x.add_argument("id", type=int)
    x = v.add_parser("ask", help="draft an answer for a job's form question"); x.add_argument("id", type=int); x.add_argument("question")
    s.set_defaults(f=cmd_answers)
    tpl = "plain offline template instead of AI (also the fallback when no provider is configured)"
    s = sub.add_parser("followup", help="draft a follow-up email (sent via inbox if a contact is known)")
    s.add_argument("id", type=int); s.add_argument("--template", action="store_true", help=tpl); option_args(s); s.set_defaults(f=cmd_followup)
    s = sub.add_parser("thanks", help="draft a post-interview thank-you note")
    s.add_argument("id", type=int); s.add_argument("--interviewer"); s.add_argument("--notes", help="something specific from the conversation")
    s.add_argument("--template", action="store_true", help=tpl); option_args(s)
    s.set_defaults(f=cmd_thanks)
    s = sub.add_parser("withdraw", help="draft a withdrawal email; sending it from the inbox marks the job withdrawn")
    s.add_argument("id", type=int); s.add_argument("--template", action="store_true", help=tpl); option_args(s); s.set_defaults(f=cmd_withdraw)
    from .drafts import KINDS

    s = sub.add_parser("draft", help="draft options (up to 3 from one AI call, one recommended) and rewrites")
    v = s.add_subparsers(dest="op", required=True)
    x = v.add_parser("options", help="numbered options for one draft; --pick N proposes it for review (pending: edits that Inbox item)")
    x.add_argument("kind", choices=KINDS); x.add_argument("id", type=int, nargs="?", help="job id (not needed with --mail / --pending)")
    x.add_argument("--mail", type=int, help="reply: the mail id (lodestar mail list)"); x.add_argument("--pending", type=int, help="pending: the Inbox item")
    x.add_argument("--contact", type=int, help="referral: the contact id"); x.add_argument("--interviewer"); x.add_argument("--notes")
    x.add_argument("--person", help="outreach: 'Name, title'"); x.add_argument("--cite", nargs="+", metavar="JOB:FIELD", help="counter")
    x.add_argument("--ask", help="counter: what you ask for"); x.add_argument("--question", help="answer: the form question")
    option_args(x)
    x = v.add_parser("rewrite", help="rewrite an Inbox email in place (stays pending) or a text file: shorter, warmer, formal, direct or your words")
    x.add_argument("--pending", type=int, metavar="ID"); x.add_argument("--file"); x.add_argument("--how", required=True)
    s.set_defaults(f=cmd_draft)
    s = sub.add_parser("suggest", help="suggested emails for today: thank-yous, follow-ups, replies, offer check-ins, referral asks (no AI)")
    s.add_argument("--dismiss", nargs=2, metavar=("JOB", "KIND"), help="hide one for 3 days")
    s.set_defaults(f=cmd_suggest)
    s = sub.add_parser("advise", help="AI recommendations for your content in a tab (one AI call); --apply IDS, --auto (Full AI: "
                       "never sends, moves or adds anything), --undo BATCH, --history")
    s.add_argument("scope", nargs="?", help="profile, bank, job, docs, answers, stories, contacts, searches, today, insights, inbox")
    s.add_argument("target", nargs="?", type=int, help="job id (job, docs), or a story / contact / Inbox id")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--apply", metavar="IDS", help="apply these recommendations (comma-separated ids)")
    g.add_argument("--auto", action="store_true", help="Full AI: recommend and apply what passes the guards (one undoable batch)")
    g.add_argument("--undo", type=int, metavar="BATCH", help="put one batch of AI changes back")
    g.add_argument("--history", action="store_true", help="recent AI change batches")
    g.add_argument("--list", action="store_true", help="open recommendations, no AI call")
    s.add_argument("--limit", type=int, default=20); s.add_argument("-p", "--provider")
    s.set_defaults(f=cmd_advise)
    s = sub.add_parser("ai-help", help="one AI helper from a tab's AI help menu (one AI call; nothing changed); no name lists them")
    s.add_argument("name", nargs="?", help="e.g. red_flags, plan_day, explain_setting (no name: the list)")
    s.add_argument("target", nargs="?", help="a job / contact / story id, or the setting to explain (e.g. autopilot, pref:followup_days)")
    s.add_argument("-p", "--provider")
    s.set_defaults(f=cmd_ai_help)
    sub.add_parser("today", help="today's agenda: next actions, deadlines, interviews, follow-ups, inbox").set_defaults(f=cmd_today)
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


def _review_args(x) -> None:
    x.add_argument("--accept", help="new (new + changed, unflagged), all, none, or item ids like i1,i3: apply now")
    x.add_argument("--take", help="for conflicts: i4=incoming,i7=both (default mine)")
    x.add_argument("--no-master", action="store_true", help="bank only: leave profile.md as it is")


def main(argv=None):
    from . import log

    for stream in (sys.stdout, sys.stderr):  # a piped cp1252 console must not crash on 'ﬂ' or an accent in a resume
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

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
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, PermissionError) as e:
        if not e.filename:
            raise
        # one check for every file argument (profile import, resume lint/audit, contacts import, --file ...): a clear
        # line instead of a traceback
        log.get("cli").warning("cannot open %s: %s", e.filename, e.strerror)
        raise SystemExit(f"cannot open {e.filename}: {e.strerror or e}") from None
    except Exception:
        log.get("cli").exception("unhandled error")
        raise


if __name__ == "__main__":
    main()
