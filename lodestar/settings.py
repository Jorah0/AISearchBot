"""User-controllable tool switches and preferences, stored in ~/.lodestar/settings.json.

Every automated AI flow is a *tool* with two switches:
    enabled = False             never runs
    enabled = True, auto=False  proposes an action into the approvals inbox and waits for you
    enabled = True, auto=True   executes immediately and logs an event
Commands you type yourself are confirmed by typing them; only automatic flows go through the inbox.
"""
import copy
import json
import os
import time
import threading

from .ai import PROVIDERS
from .config import HOME, full_ai_check

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
    # pipeline steps (pipeline.py): enabled = Autopilot may use the step; auto = it runs without asking, otherwise
    # Autopilot asks once per job in the Inbox. Clicks and the CLI run steps whatever these say.
    "fit_check": ("Pipeline: judge fit for newly tracked jobs (JD coverage + AI verdict)", True, False),
    "research": ("Pipeline: build the company research pack from public pages", True, False),
    "tailor": ("Pipeline: build the job's resume in the resume studio (your facts only, checked rewrites, one page) and use it", True, False),
    "cover_letter": ("Pipeline: write the cover letter from the tailored resume, research and fit check", True, False),
    "form_answers": ("Pipeline: draft answers to a job's form questions; asks you what it cannot know "
                     "(never eligibility or EEO)", True, False),
    "interview_prep": ("Pipeline: write the interview prep pack once an interview is booked", True, False),
    "thank_you": ("Pipeline: draft a thank-you after an interview round; the email always waits in the Inbox", True, True),
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
    "resume_look": {},  # the studio's default look (render.clean_style keys); "Make this my default look" writes it
    "resume_request": "",  # what the pipeline's Tailor step asks the studio for (empty: a strong resume for the job)
    # private dealbreakers (comma lists): search results and watch hits drop these before ranking; never sent anywhere
    "excluded_companies": "",
    "excluded_title_words": "",
    "weekly_goals": {},  # goal=number per week (GOALS); none by default, and no default application count
    "activity_weekly_min": 0,  # activity log: activities a week your unemployment claim asks for (0 = none set)
    # self-update (updater.py): the monitor loop checks every update_every_hours; notify = an alert, auto = apply
    "update_mode": "notify",
    "update_every_hours": 24,
    "update_channel": "commits",  # commits: the origin branch's tip; releases: its newest v* tag
    "update_origin": "",  # empty: the install's git origin remote (https:// or a local folder only)
    "update_manifest_url": "",  # the standalone (-Exe) build: an https JSON {version, url, notes}; notify only
    # Autopilot (pipeline.advance): off = the loop only refreshes step states; budgets count AI calls
    "autopilot": False,
    "autopilot_ai_per_cycle": 6,
    "autopilot_ai_per_day": 30,
    "autopilot_jobs_per_cycle": 3,
    "reported_questions": False,  # practice questions the AI says a company is reported to ask (unverified)
    # capture/autofill bookmarklets: their ?t= token is readable by the page they run on. auto = on until a browser
    # extension is paired (extension.bookmarklets_on), then off
    "bookmarklets": "auto",
    # public BLS pay figures per job (paydata.py): off = Lodestar never contacts api.bls.gov; on = the drawer fetches
    # the job you open and the monitor loop fills the rest (at most one BLS query a cycle)
    "market_pay": False,
}
PREF_HELP = {  # Tools > Preferences: a plain label and one line of help per key
    "name": ("Your name", "signs drafted emails when no signature is set"),
    "availability": ("Interview availability", "replies accept or offer interview slots inside this"),
    "auto_track_min_score": ("Auto-track threshold (0-100)", "listings the AI scores at least this high are proposed for the Board"),
    "followup_days": ("Follow-up after (days)", "a quiet application gets a follow-up draft after this many days (1-90)"),
    "reply_to_confirmations": ("Reply to confirmations", "also draft replies to 'we received your application' mail"),
    "weekly_target": ("Weekly application target", "applications a week; idea crafting plans around it (0-200)"),
    "provider": ("Default AI provider", "empty: the first configured one"),
    "council_providers": ("Council providers", "comma list of the only providers the council and ideas may use; empty: all configured"),
    "council_judge": ("Council judge", "a second provider checks and improves the council's combined answer"),
    "models": ("Pinned models", "provider=model to pin a model id (Setup > List models)"),
    "signature": ("Email signature", "how drafted emails sign off; empty: your name"),
    "desktop_notifications": ("Desktop notifications", "daily agenda, interview in 2 hours, deadline tomorrow"),
    "resume_style": ("Resume style", "the look of .docx and PDF resumes"),
    "resume_look": ("Studio look", "key=value, e.g. font=Georgia, accent=navy, paper=a4 (Studio > Make this my default look)"),
    "resume_request": ("Tailor request", "what the pipeline's Tailor step asks the resume studio for, e.g. one page, lead with leadership"),
    "excluded_companies": ("Excluded companies (private)", "comma list dropped from search results and watches"),
    "excluded_title_words": ("Excluded title words (private)", "comma list: listings whose title has one are dropped"),
    "weekly_goals": ("Weekly goals", "goal=number, e.g. contacts=5 (also on the Insights tab)"),
    "activity_weekly_min": ("Activity log weekly minimum", "activities a week your unemployment claim asks for (0 = none)"),
    "update_mode": ("Updates", "off; notify: tell me when an update is out; auto: apply it (tested, rolled back on failure)"),
    "update_every_hours": ("Check for updates every (hours)", "how often the monitor loop looks for an update (1-720)"),
    "update_channel": ("Update channel", "commits: every change on the origin branch; releases: tagged versions only"),
    "update_origin": ("Update origin", "https:// git URL or local folder to update from; empty: the install's origin"),
    "update_manifest_url": ("Update manifest (standalone build)", "https URL of the version file the .exe checks"),
    "autopilot": ("Autopilot", "the monitor loop runs pipeline steps within the AI budgets; steps not on auto ask once per job in the Inbox"),
    "autopilot_ai_per_cycle": ("Autopilot AI calls per cycle", "at most this many AI calls in one monitor cycle (0-500)"),
    "autopilot_ai_per_day": ("Autopilot AI calls per day", "at most this many AI calls in any 24 hours, approved runs included (0-500)"),
    "autopilot_jobs_per_cycle": ("Autopilot jobs per cycle", "at most this many jobs advanced in one monitor cycle (0-50)"),
    "reported_questions": ("Reported interview questions", "also practise questions the AI says a company is reported to "
                           "ask (labelled 'reported, unverified'; off: only your logs, your pastes, the company's pages, the JD)"),
    "bookmarklets": ("Bookmarklets", "auto: on until a browser extension is paired, then off; on / off: always "
                     "(the page a bookmarklet runs on can read its token)"),
    "market_pay": ("Market pay (BLS)", "public BLS wage percentiles for each job's occupation and area; sends only "
                   "occupation and area codes to api.bls.gov (25 queries a day, 500 with a free BLS_API_KEY)"),
}
CHOICES = {"resume_style": ("classic", "modern", "compact"),  # prefs limited to a fixed set of values
           "provider": ("", *PROVIDERS),  # "" = the first configured one
           "update_mode": ("off", "notify", "auto"), "update_channel": ("commits", "releases"),
           "bookmarklets": ("auto", "on", "off")}
RANGES = {"followup_days": (1, 90), "auto_track_min_score": (0, 100), "weekly_target": (0, 200),
          "activity_weekly_min": (0, 100), "update_every_hours": (1, 720),
          "autopilot_ai_per_cycle": (0, 500), "autopilot_ai_per_day": (0, 500), "autopilot_jobs_per_cycle": (0, 50)}  # whole-number prefs: a negative followup_days would nudge every job each cycle
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
    # a copy: set_model() fills prefs["models"] in place, and that must never be the shared default dict
    return {"tools": tools, "prefs": copy.deepcopy(PREFS) | data.get("prefs", {})}


def save(data: dict) -> None:
    full_ai_check("changes settings (automation, privacy, providers)")
    tmp = PATH.with_name(PATH.name + ".tmp")  # write-then-rename: a crash mid-write never leaves a torn file
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for i in range(40):  # Windows refuses the rename while another thread reads settings.json at this instant
        try:
            return os.replace(tmp, PATH)
        except PermissionError:
            if i == 39:
                raise
            time.sleep(0.025)


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
        if key == "provider":  # 'Anthropic ' works; a typo is refused here (CHOICES), never a KeyError at the next AI call
            value = str(value or "").strip().lower()
        if key in ("update_origin", "update_manifest_url"):
            value = str(value or "").strip()
            if key == "update_origin" and value:
                from .updater import allowed_origin

                value = allowed_origin(value)  # https:// or a local folder; ssh / http / git:// are refused here
            elif value and not value.lower().startswith("https://"):
                raise SystemExit(f"{key} must be an https:// URL")
        if key in CHOICES and value not in CHOICES[key]:
            raise SystemExit(f"{key} is one of: {', '.join(c or '(empty: automatic)' for c in CHOICES[key])}")
        data = load()
        cur = PREFS[key]
        if isinstance(cur, dict):
            if not isinstance(value, dict):  # one entry at a time: "provider=model" (empty model = back to the default)
                k, sep, v = str(value).partition("=")
                if not sep or not k.strip():
                    raise SystemExit(f"{key} takes " + ("goal=number, e.g. contacts=5" if key == "weekly_goals"
                                                        else "provider=model, e.g. openai=gpt-5"))
                value = {**data["prefs"].get(key, {}), k.strip(): v.strip()}
            if key == "resume_look":  # validated like a studio request: an unknown font or a bad colour is refused
                from .render import clean_style

                value = clean_style(value, strict=True)
            data["prefs"][key] = _goals(value) if key == "weekly_goals" else dict(value)
            save(data)
            return
        if isinstance(cur, bool):
            v = str(value).strip().lower()
            if v not in ("1", "true", "yes", "on", "0", "false", "no", "off", ""):
                raise SystemExit(f"{key} is on or off (true / false): {str(value)[:40]}")
            value = v in ("1", "true", "yes", "on")
        elif isinstance(cur, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise SystemExit(f"{key} must be a whole number") from None
            lo, hi = RANGES.get(key, (value, value))
            if not lo <= value <= hi:
                raise SystemExit(f"{key} must be between {lo} and {hi}")
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
