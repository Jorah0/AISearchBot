"""The automation cycle: email -> watches + companies -> weekly posting check -> follow-up cadence -> interview
reminders -> sync/digest/backup.
`lodestar run`, `app` and `desktop` all drive this. Every automatic action still goes through approvals."""
import time
from datetime import date, datetime, timedelta

from . import approvals, db, log, settings
from .util import desktop_notify, notify

STATUS = {"running": False, "every": None, "last_cycle": None, "cycles": 0, "last_error": None}  # read by the UI top bar
CLOSED = ("accepted", "rejected", "withdrawn")


def agenda(now: datetime | None = None) -> dict:
    """Today's list (Board panel, `lodestar today`, the daily toast): next actions due today or overdue, deadlines in
    the next 3 days, follow-ups due (followup_days), interviews in the next 48 hours, contacts whose next touch has
    come (surfaced only, never drafted), and the Inbox size."""
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
        "followups": [item(j, when=j["updated_at"][:10]) for j in db.needs_followup()],
        "interviews": [{"id": i["job_id"], "company": i["company"], "title": i["title"], "when": f"{i['when']:%a %Y-%m-%d %H:%M}"}
                       for i in upcoming_interviews(2)],
        "contacts": [{"id": c["id"], "name": c["name"], "company": c["company"] or "", "when": c["next_touch"]} for c in due(today)],
        "pending": len(db.list_pending("pending")),
    }


def followup_step(job) -> str:
    """Cadence for a quiet application: nudge at each followup_days interval, close as ghosted after the third.
    Only the loop's own nudges count (a drafted follow-up email is not a second nudge)."""
    events = db.events(job["id"])
    if any(e["kind"] == "followup_nudge" and e["detail"] == "cadence exhausted" for e in events):
        return "done"  # the close-out was proposed once already; never re-propose it
    nudges = sum(1 for e in events if e["kind"] == "followup_nudge")
    return "close" if nudges >= 3 else "nudge"


def _step(name: str, fn) -> None:
    """One cycle step. Helpers report user-facing problems as SystemExit (no key, model rejected, profile missing),
    which `except Exception` does not catch; either kind must cost only this step, never the loop thread."""
    try:
        fn()
    except (Exception, SystemExit) as e:
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
        if settings.enabled("followup") and j["contact_email"]:  # no AI provider: the plain template (apply.TEMPLATES)
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
              (len(ag["contacts"]), "contact(s) to get in touch with"),
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


def _digest(a) -> None:
    week = time.strftime("digest:%Y-%W")
    if settings.auto("digest") and time.localtime().tm_wday == 4 and not db.seen(week):
        from .extras import digest

        digest(7, send=True, provider=a.provider)
        db.mark_seen(week)


def _backup() -> None:
    day = time.strftime("backup:%Y-%m-%d")
    if settings.auto("backup") and not db.seen(day):
        from .extras import backup

        print(f"backup: {backup()}")
        db.mark_seen(day)


def cycle(a) -> None:
    STATUS["last_cycle"], STATUS["cycles"] = time.strftime("%H:%M"), STATUS["cycles"] + 1
    print(f"\n--- lodestar cycle {STATUS['last_cycle']} ---")
    if getattr(a, "email", True):
        from . import email_monitor

        _step("email", lambda: email_monitor.check(a.days, provider=a.provider))
    from . import web_monitor

    _step("watches", web_monitor.check_watches)
    _step("posting check", web_monitor.recheck_postings)  # weekly: saved feed jobs whose posting vanished -> Inbox
    _step("follow-ups", lambda: _followups(a))
    _step("interview reminders", _reminders)
    _step("desktop notifications", _desktop)
    if settings.auto("obsidian_sync"):
        from .extras import export_obsidian

        _step("obsidian sync", export_obsidian)
    _step("digest", lambda: _digest(a))
    _step("backup", _backup)
    pending = db.list_pending("pending")
    if pending:
        print(f"{len(pending)} action(s) waiting in `lodestar inbox`")


def run(a) -> None:
    STATUS["running"], STATUS["every"] = True, a.every
    try:
        while True:
            try:
                cycle(a)
            except Exception as e:  # anything the steps did not contain; the next cycle still runs
                STATUS["last_error"] = f"{time.strftime('%H:%M')} cycle: {e}"
                log.get("loop").exception("cycle failed")
            if getattr(a, "once", False):
                break
            time.sleep(a.every * 60)
    finally:
        STATUS["running"] = False  # the top bar must never claim a loop that is gone
