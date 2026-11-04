"""The automation cycle: email -> watches -> follow-up cadence -> interview reminders -> sync/digest/backup.
`lodestar run`, `app` and `desktop` all drive this. Every automatic action still goes through approvals."""
import time

from . import ai, approvals, db, settings
from .util import notify

STATUS = {"running": False, "every": None, "last_cycle": None, "cycles": 0}  # read by the UI top bar


def followup_step(job) -> str:
    """Cadence for a quiet application: nudge at each followup_days interval, close as ghosted after the third."""
    nudges = sum(1 for e in db.events(job["id"]) if e["kind"] in ("followup", "followup_nudge"))
    return "close" if nudges >= 3 else "nudge"


def cycle(a) -> None:
    STATUS["last_cycle"], STATUS["cycles"] = time.strftime("%H:%M"), STATUS["cycles"] + 1
    print(f"\n--- lodestar cycle {STATUS['last_cycle']} ---")
    if getattr(a, "email", True):
        try:
            from . import email_monitor

            email_monitor.check(a.days, provider=a.provider)
        except SystemExit as e:
            print(f"email skipped: {e}")
        except Exception as e:
            print(f"email error: {e}")
    try:
        from . import web_monitor

        web_monitor.check_watches()
    except Exception as e:
        print(f"watch error: {e}")

    for j in db.needs_followup(a.followup):
        if followup_step(j) == "close":
            if settings.enabled("followup"):
                r = approvals.propose("followup", "set_status",
                                      {"job_id": j["id"], "status": "withdrawn", "note": "no response after three follow-ups (ghosted)"},
                                      f"close #{j['id']} {j['company']} - {j['title']} as ghosted", j["id"])
                print(f"  ghosted close-out -> {r.get('status')}")
            db.add_event(j["id"], "followup_nudge", "cadence exhausted")
            continue
        notify(f"FOLLOW UP: #{j['id']} {j['company']} - {j['title']} has been quiet {a.followup}+ days")
        db.add_event(j["id"], "followup_nudge", "")
        if settings.enabled("followup") and j["contact_email"] and ai.available():
            try:  # draft goes to the inbox (or out, if the followup tool is auto)
                from .apply import followup

                print(f"  follow-up draft -> {followup(j, a.provider)['proposal'].get('status')}")
            except Exception as e:
                print(f"  follow-up draft failed: {e}")

    from .extras import upcoming_interviews

    for it in upcoming_interviews(2):
        key = f"remind:{it['path']}"
        if not db.seen(key):
            notify(f"INTERVIEW {it['when']:%a %Y-%m-%d %H:%M}: #{it['job_id']} {it['company']} - {it['title']}. "
                   f"Prep: lodestar interview prep {it['job_id']}")
            db.mark_seen(key)

    if settings.auto("obsidian_sync"):
        try:
            from .extras import export_obsidian

            export_obsidian()
        except Exception as e:
            print(f"obsidian sync error: {e}")
    week = time.strftime("digest:%Y-%W")
    if settings.auto("digest") and time.localtime().tm_wday == 4 and not db.seen(week):
        from .extras import digest

        digest(7, send=True, provider=a.provider)
        db.mark_seen(week)
    day = time.strftime("backup:%Y-%m-%d")
    if settings.auto("backup") and not db.seen(day):
        from .extras import backup

        print(f"backup: {backup()}")
        db.mark_seen(day)
    pending = db.list_pending("pending")
    if pending:
        print(f"{len(pending)} action(s) waiting in `lodestar inbox`")


def run(a) -> None:
    STATUS["running"], STATUS["every"] = True, a.every
    while True:
        cycle(a)
        if getattr(a, "once", False):
            break
        time.sleep(a.every * 60)
