"""User-controllable tool switches and preferences, stored in ~/.lodestar/settings.json.

Every automated AI flow is a *tool* with two switches:
    enabled = False             never runs
    enabled = True, auto=False  proposes an action into the approvals inbox and waits for you
    enabled = True, auto=True   executes immediately and logs an event
Commands you type yourself are confirmed by typing them; only automatic flows go through the inbox.
"""
import json
import os
import threading

from .config import HOME

PATH = HOME / "settings.json"
_LOCK = threading.RLock()  # web threads and the monitor loop both write settings: no lost updates

# name: (what it does, enabled by default, auto by default)
TOOLS = {
    "email_classify": ("Classify inbox mail and move matching jobs forward in the tracker", True, True),
    "email_reply": ("Draft replies to application confirmations, assessments, interview invites and offers", True, False),
    "interview_scheduling": ("Accept a proposed interview slot or propose times from your availability", True, False),
    "followup": ("Draft follow-up emails for applications that went quiet", True, False),
    "auto_track": ("Judge new listings from watches and searches; add strong fits to the tracker", True, False),
    "answers": ("Save newly generated application-form answers to the answer bank", True, False),
    "calendar": ("Write .ics calendar files for interviews found in mail", True, True),
    "obsidian_sync": ("Mirror the tracker into Obsidian after each monitor cycle", False, True),
    "digest": ("Email the weekly digest at the end of the week", False, True),
    "backup": ("Nightly zip of your data folder into ~/.lodestar/backups (keeps 7)", True, True),
    "posting_check": ("Weekly: re-check saved jobs from Greenhouse / Lever / Ashby feeds and propose withdrawing ones "
                      "whose posting was removed (always waits in the Inbox)", True, False),
}
PREFS = {
    "name": "",
    "availability": "weekdays 10:00-16:00 local time",
    "auto_track_min_score": 75,
    "followup_days": 7,
    "reply_to_confirmations": False,
    "weekly_target": 10,
    "provider": "",
    "council_providers": "",
    "council_judge": False,
    "models": {},
    "signature": "",
    "desktop_notifications": False,  # OS toasts from the monitor loop: daily agenda, interview in 2 h, deadline tomorrow
    "resume_style": "classic",  # .docx / PDF look (resume.STYLES); a template.docx beside profile.md overrides it
    # private dealbreakers (comma lists): search results and watch hits drop these before ranking; never sent anywhere
    "excluded_companies": "",
    "excluded_title_words": "",
    "weekly_goals": {},  # goal=number per week (GOALS); none by default, and no default application count
    "activity_weekly_min": 0,  # activity log: activities a week your unemployment claim asks for (0 = none set)
}
CHOICES = {"resume_style": ("classic", "modern", "compact")}  # prefs limited to a fixed set of values
GOALS = ("contacts", "tailored_applications", "mock_sessions", "applications")  # quality first, raw volume last


def _goals(value: dict) -> dict:
    """weekly_goals, validated: known goals only, whole numbers 0-1000; 0 or empty removes a goal."""
    out = {}
    for k, v in value.items():
        if k not in GOALS:
            raise SystemExit(f"unknown weekly goal '{k}'. Goals: {', '.join(GOALS)}")
        try:
            n = int(str(v).strip() or 0)
        except ValueError:
            raise SystemExit(f"weekly goal {k} must be a whole number: {str(v)[:40]}") from None
        if not 0 <= n <= 1000:
            raise SystemExit(f"weekly goal {k} must be between 0 and 1000")
        if n:
            out[k] = n
    return out


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8")) if PATH.is_file() else {}
    except ValueError:  # a corrupt file must not break every setting check; defaults apply until the next save
        data = {}
    tools = {n: {"enabled": e, "auto": a} | data.get("tools", {}).get(n, {}) for n, (_, e, a) in TOOLS.items()}
    return {"tools": tools, "prefs": PREFS | data.get("prefs", {})}


def save(data: dict) -> None:
    tmp = PATH.with_name(PATH.name + ".tmp")  # write-then-rename: a crash mid-write never leaves a torn file
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def enabled(tool: str) -> bool:
    return bool(load()["tools"][tool]["enabled"])


def auto(tool: str) -> bool:
    t = load()["tools"][tool]
    return bool(t["enabled"] and t["auto"])


def pref(key: str):
    return load()["prefs"].get(key, PREFS.get(key))


def set_tool(tool: str, enabled: bool | None = None, auto: bool | None = None) -> dict:
    with _LOCK:
        if tool not in TOOLS:
            raise SystemExit(f"unknown tool '{tool}'. Tools: {', '.join(TOOLS)}")
        data = load()
        if enabled is not None:
            data["tools"][tool]["enabled"] = enabled
        if auto is not None:
            data["tools"][tool]["auto"] = auto
        save(data)
        return data["tools"][tool]


def set_pref(key: str, value) -> None:
    with _LOCK:
        if key not in PREFS:
            raise SystemExit(f"unknown preference '{key}'. Keys: {', '.join(PREFS)}")
        if key in CHOICES and value not in CHOICES[key]:
            raise SystemExit(f"{key} is one of: {', '.join(CHOICES[key])}")
        data = load()
        cur = PREFS[key]
        if isinstance(cur, dict):
            if not isinstance(value, dict):  # one entry at a time: "provider=model" (empty model = back to the default)
                k, sep, v = str(value).partition("=")
                if not sep or not k.strip():
                    raise SystemExit(f"{key} takes " + ("goal=number, e.g. contacts=5" if key == "weekly_goals"
                                                        else "provider=model, e.g. openai=gpt-5"))
                value = {**data["prefs"].get(key, {}), k.strip(): v.strip()}
            data["prefs"][key] = _goals(value) if key == "weekly_goals" else dict(value)
            save(data)
            return
        if isinstance(cur, bool):
            value = str(value).lower() in ("1", "true", "yes", "on")
        elif isinstance(cur, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise SystemExit(f"{key} must be a whole number") from None
            if key == "activity_weekly_min" and not 0 <= value <= 100:
                raise SystemExit("activity_weekly_min must be between 0 and 100")
        data["prefs"][key] = value
        save(data)


def set_model(provider: str, model: str) -> None:
    """Remember a model id that was verified to work for a provider (prefs.models)."""
    with _LOCK:
        data = load()
        data["prefs"].setdefault("models", {})[provider] = model
        save(data)


def table() -> list[dict]:
    d = load()
    return [{"tool": n, "description": TOOLS[n][0], **d["tools"][n]} for n in TOOLS]
