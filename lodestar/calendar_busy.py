"""Calendar busy times (pass 28, blueprint 12.2): Google Calendar FreeBusy through your existing Google sign-in, only
with the calendar_freebusy preference on (then the sign-in also asks for calendar.freebusy: free/busy blocks only, no
event titles, nothing written). Interview replies and proposed slots avoid these blocks. Any failure returns no blocks
and says why in LAST; it never stops a mail scan. ponytail: Google only; Microsoft Graph getSchedule when asked for."""
import json
from datetime import datetime, timedelta

from . import log, oauth, settings, util, vault

URL = "https://www.googleapis.com/calendar/v3/freeBusy"
LAST: dict = {"error": "", "at": ""}


def _provider() -> str:
    return vault.get("OAUTH_PROVIDER") or ""


def _local(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)


def busy(days: int = 14) -> list[tuple[datetime, datetime]]:
    """Your busy blocks from now to `days` ahead as local naive (start, end), or [] (off, not Google, no permission)."""
    LAST.update(error="", at=datetime.now().isoformat(timespec="seconds"))
    if not settings.pref("calendar_freebusy"):
        return []
    if _provider() != "google":
        LAST["error"] = "calendar busy times need a Google sign-in (Setup > Email > Sign in with Google)"
        return []
    now = datetime.now().astimezone()
    body = {"timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(), "items": [{"id": "primary"}]}
    try:
        token = oauth.access_token()
        ans = json.loads(util.fetch(URL, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                    data=json.dumps(body).encode()))
        cal = (ans.get("calendars") or {}).get("primary") or {}
        if cal.get("errors"):
            raise ValueError(str(cal["errors"])[:120])
        return [(_local(b["start"]), _local(b["end"])) for b in cal.get("busy") or []]
    except (Exception, SystemExit) as e:  # never fatal: the reply is drafted without calendar blocks, and you are told
        code = getattr(e, "code", None)
        LAST["error"] = ("Google refused calendar access: sign in again with Google (Setup > Email) to allow busy times"
                         if code in (401, 403) else f"calendar busy times unavailable: {str(e)[:160]}")
        log.get("calendar").info(LAST["error"])
        return []


def overlaps(t: datetime, blocks, minutes: int = 60) -> bool:
    """A meeting of `minutes` starting at t touches a busy block."""
    end = t + timedelta(minutes=minutes)
    return any(s < end and t < e for s, e in blocks)
