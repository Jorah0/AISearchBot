"""The automation cycle: email (+ job-alert mail) -> watches + companies -> daily listing check -> market pay (BLS, when on) -> follow-up cadence -> interview
reminders -> sync/digest/backup -> update check (updater.tick, on its own interval).
`lodestar run`, `app` and `desktop` all drive this. Every automatic action still goes through approvals."""
import threading
import time
from datetime import date, datetime, timedelta

from . import approvals, db, log, settings, updater  # updater.BOOT: an update applied after start asks for a restart
from .config import setting
from .util import desktop_notify, notify

HOLD = threading.Lock()  # held by run() for each cycle and by extras.restore for the whole restore
STATUS = {"running": False, "every": None, "last_cycle": None, "cycles": 0, "last_error": None}  # read by the UI top bar
CLOSED = ("accepted", "rejected", "withdrawn")


def agenda(now: datetime | None = None) -> dict:
    """Today's list (Board panel, `lodestar today`, the daily toast): next actions due today or overdue, deadlines in
    the next 3 days, follow-ups due (followup_days), interviews in the next 48 hours, contacts whose next touch has
    come (surfaced only, never drafted), suggested emails (drafts.suggest_emails: nothing drafted until you ask), and
    the Inbox size."""
    from .contacts import due
    from .extras import upcoming_interviews

    now = now or datetime.now()
    today, soon = f"{now:%Y-%m-%d}", f"{now + timedelta(days=3):%Y-%m-%d}"
    live = [j for j in db.list_jobs() if j["status"] not in CLOSED]

    def item(j, **kw) -> dict:
        return {"id": j["id"], "company": j["company"], "title": j["title"], **kw}

    actions = [item(j, when=j["next_action_at"], what=j["next_action"] or "next action", overdue=j["next_action_at"] < today)
               for j in live if j["next_action_at"] and j["next_action_at"] <= today]
    deadlines = [item(j, when=j["deadline"], days=(date.fromisoformat(j["deadline"]) - now.date()).days)
                 for j in live if j["deadline"] and today <= j["deadline"] <= soon]
    return {
        "actions": sorted(actions, key=lambda i: i["when"]),
        "deadlines": sorted(deadlines, key=lambda i: i["when"]),
        # a job whose cadence is exhausted (ghosted close-out already offered) stops reappearing here
        "followups": [item(j, when=j["updated_at"][:10]) for j in db.needs_followup() if followup_step(j) != "done"],
        "interviews": [{"id": i["job_id"], "company": i["company"], "title": i["title"], "when": f"{i['when']:%a %Y-%m-%d %H:%M}",
                        **_ready(i["job_id"])} for i in upcoming_interviews(2)],
        "contacts": [{"id": c["id"], "name": c["name"], "company": c["company"] or "", "when": c["next_touch"]} for c in due(today)],
        "emails": _suggested(now),
        "top_fits": _top_fits(),
        "closed": _closed_postings(live, now),
        "boosters": _boosters(),
        "pending": len(db.list_pending("pending")),
    }


def _boosters() -> list[dict]:
    """Today's Chance boosters: the 3 best across the search (rules only); [] on any fault."""
    from . import boosters

    try:
        return boosters.across(3)
    except (Exception, SystemExit) as e:
        log.get("loop").warning("boosters failed: %s", e)
        return []


def _ready(job_id: int) -> dict:
    """{readiness: {score, band, tip}} for a Today interview item (tip: the top 'raise it' action); {} on any fault."""
    from . import readiness

    try:
        r = readiness.readiness(db.get_job(job_id))
    except (Exception, SystemExit) as e:
        log.get("loop").warning("readiness #%s failed: %s", job_id, e)
        return {}
    top = r["raise"][0] if r["raise"] else None
    return {"readiness": {"score": r["score"], "band": r["band"],
                          "tip": f"{top['text']}, +{top['gain']}" if top else None, "action": top and top["action"]}}


def _closed_postings(live, now: datetime) -> list[dict]:
    """Applied (or later) live jobs whose posting the listing monitor saw removed in the last 7 days (a saved job gets
    a withdraw proposal in the Inbox instead): 'posting closed: #12 Acme'."""
    from .web_monitor import removed_event

    since, out = f"{now - timedelta(days=7):%Y-%m-%d}", []
    for j in live:
        e = j["status"] != "saved" and removed_event(j["id"])
        if e and str(e["ts"])[:10] >= since:
            out.append({"id": j["id"], "company": j["company"], "title": j["title"], "when": str(e["ts"])[:10]})
    return out


def _top_fits() -> list[dict]:
    """Untracked listings first seen in the last 3 days with fit >= 70 (fit.top_fits); [] on any fault."""
    from . import fit

    try:
        return fit.top_fits()
    except (Exception, SystemExit) as e:
        log.get("loop").warning("top fits failed: %s", e)
        return []


def _suggested(now: datetime) -> list[dict]:
    """Suggested emails for the agenda; a fault there costs only this list, never the Today panel or the page."""
    from .drafts import suggest_emails

    try:
        return suggest_emails(now)
    except (Exception, SystemExit) as e:
        log.get("loop").warning("suggested emails failed: %s", e)
        return []


def followup_step(job) -> str:
    """Cadence for a quiet application: nudge at each followup_days interval, close as ghosted after the third
    follow-up. With a contact email only SENT follow-ups count (the 'followup' event written on send), so drafts left
    in the Inbox never add up to 'ghosted'; without one, the nudges you were shown are the follow-ups."""
    events = db.events(job["id"])
    if any(e["kind"] == "followup_nudge" and e["detail"] == "cadence exhausted" for e in events):
        return "done"  # the close-out was proposed once already; never re-propose it
    kind = "followup" if job["contact_email"] else "followup_nudge"
    done = sum(1 for e in events if e["kind"] == kind and e["detail"] != "drafted")  # old databases logged drafts too
    return "close" if done >= 3 else "nudge"


def _step(name: str, fn) -> None:
    """One cycle step. Helpers report user-facing problems as SystemExit (no key, model rejected, profile missing),
    which `except Exception` does not catch; either kind must cost only this step, never the loop thread."""
    try:
        fn()
    except (Exception, SystemExit) as e:
        db.release(close=False)  # a write that failed half-way must not keep the database locked for the UI
        STATUS["last_error"] = f"{time.strftime('%H:%M')} {name}: {e}"
        print(f"{name} skipped: {e}")
        log.get("loop").warning("%s failed: %s", name, e)


def _followups(a) -> None:
    days = getattr(a, "followup", None) or int(settings.pref("followup_days") or 7)  # --followup overrides the pref
    for j in db.needs_followup(days):
        step = followup_step(j)
        if step == "done":
            continue
        if step == "close":
            if settings.enabled("followup"):
                r = approvals.propose("followup", "set_status",
                                      {"job_id": j["id"], "status": "withdrawn", "note": "no response after three follow-ups (ghosted)"},
                                      f"close #{j['id']} {j['company']} - {j['title']} as ghosted", j["id"])
                print(f"  ghosted close-out -> {r.get('status')}")
            db.add_event(j["id"], "followup_nudge", "cadence exhausted")
            continue
        notify(f"FOLLOW UP: #{j['id']} {j['company']} - {j['title']} has been quiet {days}+ days")
        db.add_event(j["id"], "followup_nudge", "")
        # no AI provider: the plain template (apply.TEMPLATES)
        if settings.enabled("followup") and j["contact_email"] and not db.followup_waiting(j["id"]):
            from .apply import followup

            _step(f"follow-up draft #{j['id']}", lambda j=j: print(f"  follow-up draft -> {followup(j, a.provider)['proposal'].get('status')}"))


def _reminders() -> None:
    from .extras import upcoming_interviews

    for it in upcoming_interviews(2):
        key = f"remind:{it['path']}"
        if not db.seen(key):
            notify(f"INTERVIEW {it['when']:%a %Y-%m-%d %H:%M}: #{it['job_id']} {it['company']} - {it['title']}. "
                   f"Prep: open job #{it['job_id']} on the Board > Interview prep (CLI: lodestar interview prep {it['job_id']})")
            db.mark_seen(key)


def _toast_once(key: str, title: str, body: str) -> None:
    if not db.seen(key):
        desktop_notify(title, body)
        db.mark_seen(key)  # even when the OS said no: never retry a toast every cycle


def _desktop(now: datetime | None = None) -> None:
    """Opt-in OS notifications (pref desktop_notifications), each fired once via the seen table: one agenda per day,
    an interview within 2 hours, a deadline tomorrow."""
    if not settings.pref("desktop_notifications"):
        return
    from .extras import upcoming_interviews

    now = now or datetime.now()
    ag = agenda(now)
    counts = [(len(ag["actions"]), "next action(s) due"), (len(ag["deadlines"]), "deadline(s) within 3 days"),
              (len(ag["followups"]), "follow-up(s) due"), (len(ag["interviews"]), "interview(s) within 48 h"),
              (len(ag["contacts"]), "contact(s) to get in touch with"), (len(ag["emails"]), "suggested email(s)"),
              (ag["pending"], "waiting in the Inbox")]
    line = " · ".join(f"{n} {what}" for n, what in counts if n)
    if line:
        _toast_once(f"toast:agenda:{now:%Y-%m-%d}", "Lodestar: today", line)
    for it in upcoming_interviews(1):
        if it["when"] <= now + timedelta(hours=2):
            _toast_once(f"toast:interview:{it['path']}", f"Interview at {it['when']:%H:%M}",
                        f"#{it['job_id']} {it['company']} - {it['title']}")
    tomorrow = f"{now + timedelta(days=1):%Y-%m-%d}"
    for d in ag["deadlines"]:
        if d["when"] == tomorrow:
            _toast_once(f"toast:deadline:{d['id']}:{tomorrow}", "Deadline tomorrow", f"#{d['id']} {d['company']} - {d['title']}")


def _digest(a, now: datetime | None = None) -> None:
    """Once per Friday-to-Thursday week, on the first cycle from Friday on: a Friday the app was closed still gets
    its digest on the next cycle. Emailed when LODESTAR_NOTIFY_EMAIL is set, else a one-line alert says it is ready."""
    week = f"digest:{(now or datetime.now()) - timedelta(days=4):%G-%V}"  # the key turns over on Friday
    if settings.auto("digest") and not db.seen(week):
        from .extras import digest

        db.mark_seen(week)  # ponytail: one try a week; a failed send is reported once, the digest stays on Monitor
        if setting("LODESTAR_NOTIFY_EMAIL"):
            digest(7, send=True, provider=a.provider)
        else:
            notify("DIGEST ready: Monitor > Weekly digest (or lodestar digest); set LODESTAR_NOTIFY_EMAIL to get it by email")


def _prune() -> None:
    day = time.strftime("prune:postings:%Y-%m-%d")
    if not db.seen(day):
        from . import listings

        print(f"all jobs: {listings.prune()} old listing(s) pruned")
        db.mark_seen(day)


def _backup() -> None:
    day = time.strftime("backup:%Y-%m-%d")
    if settings.auto("backup") and not db.seen(day):
        from .extras import backup

        print(f"backup: {backup()}")
        db.mark_seen(day)


RECHECK_EVERY = 6 * 3600


def _recheck() -> None:
    """Every linked key and the mailbox re-verified every 6 hours (no tokens), so a link that stopped working shows on
    the Accounts tab (and as a notice) without waiting for the next app start."""
    from . import connections
    from .web_monitor import _due, _ran

    if not connections._STARTED:  # only the long-running commands (app, ui, desktop, run): never tests or --once
        return
    if _due("conn:check", RECHECK_EVERY):
        _ran("conn:check")
        connections.check_all()


def cycle(a) -> None:
    STATUS["last_cycle"], STATUS["cycles"] = time.strftime("%H:%M"), STATUS["cycles"] + 1
    print(f"\n--- lodestar cycle {STATUS['last_cycle']} ---")
    STATUS["last_error"] = None  # the top bar shows this cycle's problem, not one fixed since
    from .util import mail_login

    if getattr(a, "email", True) and not mail_login(setting)[1]:
        print("email: skipped (no mailbox connected: Setup > Connect email)")  # optional, so not a 'problem'
    elif getattr(a, "email", True):
        from . import email_monitor

        _step("email", lambda: email_monitor.check(a.days, provider=a.provider))
    from . import fit, web_monitor

    _step("connection check", _recheck)
    _step("watches", web_monitor.check_watches)
    _step("listing check", web_monitor.check_listings)  # daily: tracked jobs' postings removed / changed
    _step("fit", fit.refresh)  # stale fit scores (profile, preferences, weights changed), no AI
    _step("all jobs prune", _prune)  # daily: untracked listings unseen for 45 days, or past their closing date
    if settings.pref("market_pay"):  # public BLS pay: cache first, at most one query a cycle, never the AI
        from . import paydata

        _step("market pay", lambda: paydata.fill(1))
    _step("follow-ups", lambda: _followups(a))
    _step("interview reminders", _reminders)
    from . import readiness

    _step("readiness", readiness.snapshot_due)  # one snapshot per round, from 2 h before to 24 h after it
    from . import pipeline

    _step("pipeline", lambda: pipeline.advance(a.provider))  # step states always; Autopilot runs only when switched on
    _step("desktop notifications", _desktop)
    if settings.auto("obsidian_sync"):
        from .extras import export_obsidian

        _step("obsidian sync", export_obsidian)
    _step("digest", lambda: _digest(a))
    _step("backup", _backup)
    from . import studio

    if studio.AUTO:  # the long-running commands: picks up profile edits made outside the app (offline, no AI)
        _step("master resume", studio.sync_master)
    if getattr(a, "update", False):  # lodestar run / app / desktop (--no-update skips it); every update_every_hours
        _step("update check", updater.tick)
    pending = db.list_pending("pending")
    if pending:
        print(f"{len(pending)} action(s) waiting in `lodestar inbox`")


def run(a) -> None:
    STATUS["running"], STATUS["every"] = True, a.every
    try:
        while True:
            try:
                with HOLD:
                    cycle(a)
            except (Exception, SystemExit) as e:  # anything the steps did not contain; the next cycle still runs
                STATUS["last_error"] = f"{time.strftime('%H:%M')} cycle: {e}"
                log.get("loop").exception("cycle failed")
            if getattr(a, "once", False):
                break
            time.sleep(a.every * 60)
    finally:
        STATUS["running"] = False  # the top bar must never claim a loop that is gone
