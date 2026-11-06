"""The automation cycle: email -> watches -> follow-up cadence -> interview reminders -> sync/digest/backup.
`lodestar run`, `app` and `desktop` all drive this. Every automatic action still goes through approvals."""
import time

from . import ai, approvals, db, log, settings
from .util import notify

STATUS = {"running": False, "every": None, "last_cycle": None, "cycles": 0, "last_error": None}  # read by the UI top bar


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
        if settings.enabled("followup") and j["contact_email"] and ai.available():
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
    _step("follow-ups", lambda: _followups(a))
    _step("interview reminders", _reminders)
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
