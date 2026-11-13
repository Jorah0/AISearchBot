"""Fit score: one deterministic 0-100 compatibility score for a tracked job or a listing, with a chip per reason.

Five measured parts (skills, role, experience, location, pay) plus soft modifiers (watched company, people you know,
staleness) and, when judged, an AI part. Hard requirements (work authorization, clearance, licenses, your exclusions)
are gates (gates()), never points. A part that cannot be measured drops out
and the score shrinks toward 50 by the unmeasured share, so a title-only listing never outranks a fully read posting.
Weights and patterns live in data/fit.json; the pref fit_weights overrides them.

Private: fit data is the user's own judgement. It never holds a salary floor figure, never goes into employer text
(resume, letters, answers, mail, drafts) and never reaches an AI provider (rank() sees listings and the profile, not
fit chips). No AI call happens here: the AI part is stored by rank() callers (auto_track, the 'AI fit' button).
"""
import hashlib
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from . import db, settings

DATA = Path(__file__).parent / "data" / "fit.json"
PARTS = ("skills", "role", "experience", "location", "pay")
REV_PREFS = ("fit_weights", "work_authorization", "target_seniority", "years_experience", "excluded_companies",
             "excluded_title_words")
RUNGS = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "staff": 4, "lead": 4}  # manager is its own track
_MGR = re.compile(r"\b(manager|head|director|vp|chief)\b", re.I)
AI_DAILY = 60  # listings rank() may judge a day (auto_track and the AI fit button share meta quota:ai_rank:<day>)
_YM = re.compile(r"((?:19|20)\d\d)(?:[-/.](\d{1,2}))?")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))  # utf-8: the patterns hold '–' and '’'


@lru_cache(maxsize=1)
def _rx() -> dict:
    c = config()
    return {"years": re.compile(c["years"], re.I),
            **{k: re.compile("|".join(f"(?:{p})" for p in c[k]), re.I) for k in ("no_sponsor", "sponsor_yes", "clearance")}}


def weights(prefs: dict | None = None) -> dict:
    """data/fit.json weights with the user's fit_weights on top (validated when saved; re-checked here)."""
    w = dict(config()["weights"])
    for k, v in ((prefs or settings.load()["prefs"]).get("fit_weights") or {}).items():
        if k in w and str(v).strip().isdigit() and 0 <= int(v) <= 100:
            w[k] = int(v)
    return w


def _h(s) -> str:
    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:12]


def rev() -> str:
    """What every stored fit was scored against: the profile (pass 17's profile_rev, which leaves Preferences out), the
    Preferences text, the fit prefs and dealbreakers, fit.json's version and the watched companies. A stored fit whose
    rev differs is stale (dimmed on the board; the loop and the page refresh it)."""
    from . import profile

    try:
        prof, prefs_text = profile.profile_rev(), profile.preferences_text()
    except (Exception, SystemExit):  # no profile yet: one stable value, so nothing flips back and forth
        prof, prefs_text = "?", ""
    prefs = settings.load()["prefs"]
    names = sorted(str(c["name"] or c["slug"]) for c in db.companies())
    return _h(json.dumps([prof, _h(prefs_text), {k: prefs.get(k) for k in REV_PREFS}, config()["version"], names],
                         sort_keys=True, default=str))


# ----------------------------------------------------------------------------- context (once per batch)
def _split(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]|\bor\b", v or "") if x.strip() and x.strip().lower() not in ("none", "n/a", "-")]


def _ym(s, today: date) -> tuple[int, int] | None:
    t = str(s or "").strip().lower()
    if re.match(r"(present|current|now|today|to date)", t):
        return today.year, today.month
    if not (m := _YM.search(t)):
        return None
    mon = int(m[2]) if m[2] and 1 <= int(m[2]) <= 12 else next((n for k, n in _MONTHS.items() if k in t), 1)
    return int(m[1]), mon


def years_from(experience: list[dict], today: date | None = None) -> float | None:
    """Years worked: the union of the roles' start-end intervals (overlaps counted once; 'Present' = today)."""
    today = today or date.today()
    spans = []
    for role in experience or []:
        a, b = _ym(role.get("start"), today), _ym(role.get("end"), today)
        if a and b and b >= a:
            spans.append((a[0] * 12 + a[1], b[0] * 12 + b[1] + 1))  # months, the end month included
    if not spans:
        return None
    total, reach = 0, 0
    for lo, hi in sorted(spans):
        lo = max(lo, reach)
        if hi > lo:
            total, reach = total + hi - lo, hi
    return round(total / 12, 1)


def _level_of_years(y: float | None) -> str:
    return "" if y is None else "junior" if y < 2 else "mid" if y < 5 else "senior" if y < 9 else "staff"


def context() -> dict:
    """Everything score() reads besides the item, read once per batch: the profile as an employer sees it (no
    Preferences), the Preferences fields, the private floor, years, level, past titles, prefs and indexes."""
    from . import profile
    from .contacts import warm_index
    from .web_monitor import norm_company, norm_title

    prefs = settings.load()["prefs"]
    try:
        resume = profile.drop_preferences(profile.candidate_text())
    except (Exception, SystemExit):  # the template (or no profile): skills and clearance are unknown
        resume = None
    try:
        pt = profile.preferences_text()
        floor = profile.salary_floor()
    except (Exception, SystemExit):
        pt, floor = "", None
    line = next((ln for ln in pt.split("|") + pt.splitlines() if re.search(r"(?i)salary floor", ln)), "")
    cur = next((c for c, rx in (("EUR", r"€|\beur\b"), ("GBP", r"£|\bgbp\b"), ("CAD", r"\bcad\b"), ("AUD", r"\baud\b"),
                                ("CHF", r"\bchf\b"), ("INR", r"\binr\b|₹")) if re.search(rx, line, re.I)), "USD")
    exp: list[dict] = []
    try:
        exp = [e for e in profile.load().get("experience") or [] if isinstance(e, dict)]
        if not exp and resume:
            exp = profile.extract_heuristic(resume).get("experience") or []
    except (Exception, SystemExit):
        pass
    have = int(prefs.get("years_experience") or 0) or years_from(exp)
    locs = [x.lower() for x in _split(profile.pref_field("Locations / remote", pt) or profile.pref_field("Locations", pt))]
    bad = [w for w in _split(profile.pref_field("Deal-breakers", pt)) + _split(profile.pref_field("Industries to avoid", pt))
           if len(w) >= 3]
    targets = _split(profile.pref_field("Target roles", pt))
    watched = {norm_company(c["name"] or c["slug"]) for c in db.companies()}
    watched |= {norm_company(x) for x in _split(profile.pref_field("Target companies", pt))}
    return {"resume": resume, "targets": targets, "titles": [str(e.get("title") or "") for e in exp if e.get("title")],
            "locations": locs, "remote_ok": any(re.search(r"\b(remote|anywhere)\b", x) for x in locs),
            "cities": {x.split()[0] for x in (" ".join(re.findall(r"[a-z0-9]+", x)) for x in locs)
                       if x and x.split()[0] not in ("remote", "anywhere", "hybrid", "onsite", "on")},
            "dealbreakers": bad, "floor": floor, "floor_cur": cur, "years": have,
            "level": prefs.get("target_seniority") or _level_of_years(have),
            "manager_ok": any(_MGR.search(t) for t in targets), "auth": prefs.get("work_authorization") or "",
            "weights": weights(prefs), "watched": watched - {""},
            "bad_co": {norm_company(c) for c in _split(prefs.get("excluded_companies") or "")} - {""},
            "bad_words": [norm_title(w) for w in _split(prefs.get("excluded_title_words") or "")],
            "warm": warm_index(), "rev": rev()}


# ----------------------------------------------------------------------------- parts
def _sign(s) -> str:
    return "+" if s >= 70 else "-" if s < 40 else "·"


def _skills(x, ctx) -> tuple:
    from . import ats

    jd = x["desc"]
    if ctx["resume"] is None:
        return None, "your profile is still the template", {}
    if len(jd.split()) < 40:
        return None, "the posting text is missing or very short (open it and capture it, or wait for a feed copy)", {}
    m = ats.match(ctx["resume"], jd, x["title"], x.get("skip") or (), x["company"])
    req_text, nice_text = ats.split_nice(jd, config()["nice_headings"])
    req: list[dict] = []
    nice: list[dict] = []
    other: list[dict] = []
    mw = tw = 0.0
    for k in m["keywords"]:
        if k["skipped"]:
            continue
        is_nice = k["kind"] != "other" and ats.mentions(k["term"], nice_text) and not ats.mentions(k["term"], req_text)
        w = 0.5 if is_nice or k["kind"] in ("soft", "other") else 1.0
        (nice if is_nice else req if k["kind"] == "hard" else other).append(k)
        tw += w
        mw += w * k["matched"]
    if not tw:
        return None, "the posting names no skills Lodestar can compare", {}
    s = round(100 * mw / tw)
    got = sum(k["matched"] for k in req)
    missing = [k["term"] for k in req if not k["matched"]]
    chips = []
    if req:
        chips.append((_sign(s), f"{got} of {len(req)} required skills"))
    if missing:
        chips.append(("-", "missing " + ", ".join(missing[:2])))
    if nice:
        chips.append(("·", f"{sum(k['matched'] for k in nice)} of {len(nice)} nice-to-haves"))
    if not chips:
        chips.append((_sign(s), f"{sum(k['matched'] for k in other)} of {len(other)} posting keywords"))
    return s, chips, {"required": [got, len(req)], "nice": [sum(k["matched"] for k in nice), len(nice)],
                      "missing": missing[:5], "matched": [k["term"] for k in req + nice if k["matched"]][:5]}


def _role(x, ctx) -> tuple:
    from . import ats
    from .web_monitor import seniority_of

    core = ats.core_title(x["title"])
    title, hit = None, ""
    for t in ctx["targets"] + ctx["titles"]:
        c = ats.core_title(t)
        if not c or not core:
            continue
        a, b = set(c.split()), set(core.split())
        v = 100 if c == core else round(100 * len(a & b) / len(a | b))
        if title is None or v > title:
            title, hit = v, t
    level, lchip = None, None
    job_lvl, mine = seniority_of(x["title"]), ctx["level"]
    if mine:
        if (job_lvl == "manager") != (mine == "manager"):
            level = 100 if job_lvl == "manager" and ctx["manager_ok"] else 40
        else:
            d = 0 if mine == "manager" else abs(RUNGS[job_lvl] - RUNGS[mine])
            level = 100 if d == 0 else 70 if d == 1 else 30
        if level < 100:
            lchip = ("-" if level < 70 else "·", f"{job_lvl} level, you are {mine}")
    if title is None and level is None:
        return None, "add Target roles to Preferences (or roles to your profile) to score this", {}
    s = round(0.6 * title + 0.4 * level) if title is not None and level is not None else title if level is None else level
    chips = []
    if title is not None:
        what = "target" if hit in ctx["targets"] else "your past title"
        chips.append((_sign(title), f"matches {what} \"{hit}\"" if title == 100 else
                      f"close to {what} \"{hit}\"" if title >= 50 else "title unlike your targets"))
    if lchip:
        chips.append(lchip)
    return s, chips, {"title": title, "level": level}


def required_years(text: str) -> int | None:
    """The largest lower bound of 'N+ years of experience' style requirements; over 15 is ignored ('our 25 years of
    experience' describes the company). ponytail: '5+ years of Python' counts like general years; upgrade: tie the
    number to the skill."""
    ns = [int(m[1]) for m in _rx()["years"].finditer(text or "") if 0 < int(m[1]) <= 15]
    return max(ns) if ns else None


def _experience(x, ctx, req_text) -> tuple:
    from .web_monitor import seniority_of

    req, have = required_years(req_text), ctx["years"]
    if req is None:
        return None, "no years of experience stated", {}
    if have is None:
        return None, "set years_experience in Preferences, or add dated roles to your profile", {"req": req}
    have_n = int(have)
    if have >= req + 8 and seniority_of(x["title"]) in ("junior", "intern"):
        s = 70
    else:
        s = 100 if have >= req else max(0, round(100 - 25 * (req - have)))
    text = (f"requires {req} yrs, you have {have_n}" if have < req else f"{req}+ yrs asked, you have {have_n}")
    return s, [(_sign(s), text)], {"req": req, "have": have_n}


def _location(x, ctx) -> tuple:
    from .web_monitor import norm_location

    if not ctx["locations"]:
        return None, "set Locations in Preferences to score this", {}
    kind = ("remote" if str(x.get("source") or "").split(":")[-1] in db.REMOTE_BOARDS
            else x.get("remote") or db.remote_kind(f"{x['location']}\n{x['desc'][:1500]}"))
    words = norm_location(x["location"]).split()
    in_city = bool(words) and words[0] in ctx["cities"]
    if kind == "remote":
        return (100, [("+", "remote")], {}) if ctx["remote_ok"] else (
            70, [("+", "remote (not in your Locations)")], {})
    if not words:
        return None, "the posting does not say where", {}
    where = " ".join(words[:3])
    if in_city:
        return 100, [("+", f"{kind or 'based'} in {where}")], {}
    if kind == "hybrid":
        return 30, [("-", f"hybrid in {where}")], {}
    return 15, [("-", f"onsite in {where}")], {}


def _pay(x, ctx) -> tuple:
    """Against the private floor; only the part score is kept (never a figure)."""
    from .resume import parse_salary
    from .web_monitor import jd_with_salary

    if not ctx["floor"]:
        return None, "set a Salary floor in Preferences to score pay", {}
    if x.get("salary_min") is not None or x.get("salary_max") is not None:
        lo, hi = x.get("salary_min"), x.get("salary_max")
        pay = {"salary_min": lo if lo is not None else hi, "salary_max": hi if hi is not None else lo,
               "currency": x.get("currency")}
    else:
        pay = parse_salary(jd_with_salary({"salary": x.get("salary"), "source": x.get("source"), "desc": x["desc"]}))
    if not pay:
        return None, "pay not stated", {}
    if pay.get("currency") and pay["currency"] != ctx["floor_cur"]:
        return None, f"pay in {pay['currency']}, not compared", {}
    if pay["salary_max"] < ctx["floor"]:
        return 0, [("-", "top of range below your floor")], {}
    if pay["salary_min"] >= ctx["floor"]:
        return 100, [("+", "range clears your floor")], {}
    return 70, [("·", "range straddles your floor")], {}


# ----------------------------------------------------------------------------- score
def _item(x) -> dict:
    """A listing dict (title, company, location, salary, desc, source, date, urls) or a job row, as one shape."""
    d = dict(x)
    is_job = "jd" in d and "status" in d
    ai_fit = d.get("ai_fit")
    if isinstance(ai_fit, str):
        try:
            ai_fit = json.loads(ai_fit)
        except ValueError:
            ai_fit = None
    skip = d.get("skip")
    if is_job:
        skip = db.ats_skip(d)
    return d | {"title": str(d.get("title") or ""), "company": str(d.get("company") or ""),
                "location": str(d.get("location") or ""), "desc": str((d.get("jd") if is_job else d.get("desc")) or d.get("jd") or ""),
                "skip": skip or (), "ai_fit": ai_fit if isinstance(ai_fit, dict) else None, "is_job": is_job}


_CRED = re.compile(r"(?i)\b(license|licence|certification|certificate|registration)\b")
_CUE = re.compile(r"(?i)\b(must|required|requires|require|valid|active|current|hold|possess)\b")
_LEAD = {"a", "an", "the", "valid", "active", "current", "must", "hold", "have", "possess", "required", "requires",
         "require", "and", "or", "with", "be", "to", "of", "your", "in", "good", "standing"}


def _credentials(req_text: str) -> list[str]:
    """Licenses / certifications the requirements (never the nice-to-haves) demand: 'Must hold a valid Class A CDL
    license' -> 'Class A CDL license'. ponytail: up to four words before the keyword, at most three per posting."""
    out: dict[str, str] = {}
    for line in re.split(r"[\n.;]", req_text):
        m = _CRED.search(line)
        if not m or not _CUE.search(line):
            continue
        words = re.findall(r"[\w+/'-]+", line[:m.start()])[-4:]
        while words and words[0].casefold() in _LEAD:
            words.pop(0)
        if words:
            name = " ".join(words + [m[1]])
            out.setdefault(name.casefold(), name)
    return list(out.values())[:3]


def gates(x, ctx, req_text: str | None = None) -> list[dict]:
    """Hard requirements, each {requirement, state, evidence} with state met / not_met / unknown (blueprint 7.2):
    work authorization / sponsorship, security clearance, licenses the requirements name, and your own exclusions.
    Kept out of the fit score; unknown is never met. Evidence strings never hold a salary figure."""
    from . import ats
    from .web_monitor import norm_company, norm_title

    rx, out, desc = _rx(), [], x["desc"]
    req_text = ats.split_nice(desc, config()["nice_headings"])[0] if req_text is None else req_text
    have = (ctx["resume"] or "").casefold()

    def add(req, state, evidence):
        out.append({"requirement": req, "state": state, "evidence": evidence})

    co, title = norm_company(x["company"]), norm_title(x["title"])
    if co and co in ctx["bad_co"]:
        add("Excluded company", "not_met", "excluded company")
    if any(w and re.search(rf"(?<!\S){re.escape(w)}(?!\S)", title) for w in ctx["bad_words"]):
        add("Excluded title word", "not_met", "excluded title word")
    text = f"{x['title']}\n{x['company']}\n{desc}"
    if w := next((w for w in ctx["dealbreakers"] if re.search(rf"(?i)(?<!\w){re.escape(w)}(?!\w)", text)), None):
        add("Deal-breaker", "not_met", f'mentions "{w}" (deal-breaker)')
    no, yes, auth = rx["no_sponsor"].search(desc), rx["sponsor_yes"].search(desc), ctx["auth"]
    req = "Work authorization / visa sponsorship"
    if auth == "needs_sponsorship":
        add(req, *(("not_met", "says no visa sponsorship") if no else ("met", "offers sponsorship") if yes
                   else ("unknown", "the posting does not say whether it sponsors visas")))
    elif auth == "authorized" and (no or yes):
        add(req, "met", "you are authorized to work")
    elif no:
        add(req, "unknown", "says no visa sponsorship; set Work authorization in Preferences")
    if rx["clearance"].search(desc):
        add("Security clearance", *(("met", "your profile mentions a clearance") if "clearance" in have
                                    else ("unknown", "requires a security clearance; your profile does not say")))
    for name in _credentials(req_text):
        words = [w for w in re.findall(r"[\w+/'-]+", name.casefold()) if len(w) >= 2 and w not in _LEAD
                 and not _CRED.fullmatch(w)]
        found = bool(words) and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", have) for w in words)
        add(name, *(("met", "on your profile") if found else ("unknown", "required; your profile does not show it")))
    return out


def _mods(x, ctx) -> list[dict]:
    """Soft effects on the score (preferences, signals). Hard requirements are gates(), never a score cut."""
    from .contacts import warm
    from .web_monitor import GHOST_SHOW, ghost_signals, norm_company, sponsor_hint

    m, rx, out = config()["modifiers"], _rx(), []
    co = norm_company(x["company"])
    # work authorization is a gate (gates()), never points: a sponsorship hint is shown, it moves nothing (pass 31)
    if ctx["auth"] == "needs_sponsorship" and not rx["no_sponsor"].search(x["desc"]) and not rx["sponsor_yes"].search(x["desc"]):
        if x["company"] and sponsor_hint(x["company"]):
            out.append({"d": 0, "why": "sponsor_hint", "chip": ("+", "possible H-1B sponsor")})
    if co and co in ctx["watched"]:
        out.append({"d": m["watched"], "why": "watched", "chip": ("+", "a company you watch")})
    if x["company"] and (people := warm(x["company"], ctx["warm"])):
        n = len(people)
        out.append({"d": m["warm"], "why": "warm", "chip": ("+", f"{n} {'person' if n == 1 else 'people'} you know there")})
    g = x.get("ghost") if isinstance(x.get("ghost"), dict) else ghost_signals(x if not x["is_job"] else
                                                                              {k: v for k, v in x.items() if k != "desc"})
    if g["score"] >= GHOST_SHOW:
        d = max(m["ghost_max"], m["ghost_per_10"] * g["score"] // 10)
        out.append({"d": d, "why": "ghost", "chip": ("-", "possibly stale (" + "; ".join(g["reasons"][:1]) + ")")})
    return out


def score(x, ctx: dict | None = None) -> dict:
    """The fit of one job row or listing dict: {score, known, blocked, partial, rev, at, parts, mods, chips, note}.
    Deterministic: the same item and context give the same JSON. Never holds a floor figure."""
    from . import ats

    ctx = ctx or context()
    c, x = config(), _item(x)
    w = ctx["weights"]
    req_text = ats.split_nice(x["desc"], c["nice_headings"])[0]
    parts, chips, unknown = {}, [], []
    for name, res in (("skills", _skills(x, ctx)), ("role", _role(x, ctx)), ("experience", _experience(x, ctx, req_text)),
                      ("location", _location(x, ctx)), ("pay", _pay(x, ctx))):
        s, ch, extra = res
        parts[name] = {"s": s, "w": w[name], **extra}
        if s is None:
            unknown.append(name)
            chips.append({"sign": "·", "text": ch, "part": name, "rank": 0, "info": True})
        else:
            chips += [{"sign": sg, "text": t, "part": name, "rank": abs(s - 50) * w[name]} for sg, t in ch]
    ai = x["ai_fit"] if x["ai_fit"] and isinstance(x["ai_fit"].get("score"), (int, float)) else None
    if ai:
        parts["ai"] = {"s": int(max(0, min(100, ai["score"]))), "w": w["ai"]}
        chips.append({"sign": _sign(parts["ai"]["s"]), "text": f"AI {parts['ai']['s']}: {str(ai.get('why') or '')[:80]}".rstrip(": "),
                      "part": "ai", "rank": abs(parts["ai"]["s"] - 50) * w["ai"]})
    core_w = sum(w[p] for p in PARTS if w[p] > 0)
    known_w = sum(w[p] for p in PARTS if w[p] > 0 and parts[p]["s"] is not None)
    k = known_w / core_w if core_w else 0.0
    live = [(parts[p]["s"], w[p]) for p in (*PARTS, "ai") if p in parts and parts[p]["s"] is not None and w[p] > 0]
    base = sum(s * wt for s, wt in live) / sum(wt for _, wt in live) if live else c["shrink_to"]
    value = base * k + c["shrink_to"] * (1 - k)
    mods, gs = _mods(x, ctx), gates(x, ctx, req_text)
    blocked = any(g["state"] == "not_met" for g in gs)
    value += sum(o["d"] for o in mods)
    value = max(0, min(100, round(value)))
    chips += [{"sign": o["chip"][0], "text": o["chip"][1], "part": "mod", "rank": abs(o["d"]) * 50} for o in mods]
    chips += [{"sign": "-", "text": g["evidence"], "part": "gate", "rank": 10**6} for g in gs if g["state"] == "not_met"]
    chips.sort(key=lambda ch: -ch["rank"])
    n_known = sum(parts[p]["s"] is not None for p in PARTS)
    note = f"measured {n_known} of {len(PARTS)} parts" + (
        "; " + "; ".join(next(ch["text"] for ch in chips if ch["part"] == p and ch.get("info")) for p in unknown[:2])
        if unknown else "")
    return {"score": value, "known": round(k, 2), "confidence": round(k, 2), "blocked": blocked,
            "partial": k < c["partial_below"], "gates": gs, "gates_unknown": any(g["state"] == "unknown" for g in gs),
            "rev": ctx["rev"], "at": date.today().isoformat(), "parts": parts,
            "mods": [{"d": o["d"], "why": o["why"]} for o in mods],
            "chips": [{kk: ch[kk] for kk in ("sign", "text", "part", "info") if kk in ch} for ch in chips], "note": note}


def top(fit: dict, n: int = 3) -> list[dict]:
    """The chips a card shows: blocks first, then the largest effects (score() already sorted them)."""
    return [ch for ch in (fit or {}).get("chips") or [] if not ch.get("info")][:n]


CLASS_BANDS = ((75, "qualified_now"), (55, "competitive_with_framing"), (35, "bridge_required"))


def job_class(fit: dict | None) -> str | None:
    """A job's career class (blueprint 4.4 / 7.3; careers.CLASSES): a gate not met -> Currently ineligible; an unknown
    gate or a partial fit -> Insufficient evidence; else by score band. ponytail: fixed bands; a reading of the fit,
    never a hiring probability."""
    if not fit:
        return None
    states = {g["state"] for g in fit.get("gates") or []}
    if "not_met" in states:
        return "ineligible"
    if "unknown" in states or fit.get("partial"):
        return "insufficient_evidence"
    return next((k for floor, k in CLASS_BANDS if fit["score"] >= floor), "longer_term")


def light(fit: dict | None, cur_rev: str | None = None) -> dict:
    """What the board and lists carry per item (about 200 bytes): score, confidence, partial, stale, blocked, class,
    top chips."""
    from .careers import CLASSES

    if not fit:
        return {"fit_score": None}
    cls = job_class(fit)
    return {"fit_score": fit["score"], "fit_known": fit["known"], "fit_confidence": fit.get("confidence", fit["known"]),
            "fit_partial": fit.get("partial", False), "fit_blocked": fit.get("blocked", False),
            "fit_stale": bool(cur_rev and fit.get("rev") != cur_rev), "fit_class": cls, "fit_class_label": CLASSES.get(cls),
            "fit_chips": [f"{c['sign']} {c['text']}" for c in top(fit)]}


def stored(row) -> dict | None:
    try:
        f = json.loads(row["fit"]) if row["fit"] else None
    except (ValueError, TypeError, IndexError, KeyError):
        return None
    return f if isinstance(f, dict) else None


def for_job(job, ctx: dict | None = None) -> dict:
    """Score a tracked job (its JD, ats_skip 'not mine' terms, location / remote / pay columns, AI part) and store it."""
    job = db.get_job(job["id"]) if not hasattr(job, "keys") or "fit" not in job.keys() else job
    f = score(job, ctx)
    db.set_fit("jobs", job["id"], f)
    return f


def for_listing(row_or_dict, ctx: dict | None = None) -> dict:
    """Score a listing; stored on its postings row when it has one (`id` = rowid)."""
    d = dict(row_or_dict)
    if isinstance(d.get("jd"), str) and not d.get("desc"):
        d["desc"] = d["jd"]
    d.pop("jd", None)
    d.pop("status", None)  # a listing, never read as a job row
    for k in ("urls", "sources"):  # a postings row keeps these as JSON text
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                d[k] = []
    d.setdefault("date", d.get("posted_at") or "")
    if not d.get("source") and d.get("sources"):
        d["source"] = d["sources"][0]
    f = score(d, ctx)
    if d.get("id"):
        db.set_fit("postings", int(d["id"]), f)
    return f


def set_ai(table: str, row_id: int, ai_score, why: str) -> dict:
    """Store an AI judgement {score, why, at} as the item's AI part (it moves the fit by at most the AI weight)."""
    s = int(max(0, min(100, float(ai_score))))
    db.con().execute(f"UPDATE {table} SET ai_fit=? WHERE {'id' if table == 'jobs' else 'rowid'}=?",
                     (json.dumps({"score": s, "why": str(why or "")[:300], "at": date.today().isoformat()}), row_id))
    db.con().commit()
    return {"score": s, "why": str(why or "")[:300]}


def _ai_one(what: str, row, provider: str | None) -> dict:
    """One rank() call on one item (the listing fenced as data, no floor) under the daily quota:ai_rank budget."""
    from . import ai
    from .web_monitor import rank

    if not (row["jd"] or "").strip():
        raise SystemExit(f"{what} has no job description: add one first")
    if not (provider or ai.available()):
        raise SystemExit("the AI fit needs an AI provider: Setup > Link an AI key")
    if not db.quota("ai_rank", AI_DAILY):
        raise SystemExit(f"today's AI fit budget is used up ({AI_DAILY} listings a day); the rules-based fit still stands")
    one = [{"title": row["title"], "company": row["company"] or "", "location": row["location"] or "", "desc": row["jd"]}]
    try:
        rank(one, provider)
    finally:
        if "score" not in one[0]:
            db.quota_refund("ai_rank")
    if "score" not in one[0]:
        raise SystemExit("the AI gave no usable score; try again")
    return one[0]


def ai_judge(job_id: int, provider: str | None = None) -> dict:
    """The drawer's 'AI fit' click: one rank() call on this job, stored as its AI part, then the job is re-scored."""
    r = _ai_one(f"job #{job_id}", db.get_job(job_id), provider)
    set_ai("jobs", job_id, r["score"], r.get("why", ""))
    return for_job(db.get_job(job_id))


def ai_listing(pid: int, provider: str | None = None) -> dict:
    """All jobs > 'AI fit' on one listing (a user click): the same one rank() call, stored on the postings row."""
    row = db.con().execute("SELECT rowid AS id, * FROM postings WHERE rowid=?", (int(pid),)).fetchone()
    if not row or not row["title"]:
        raise SystemExit(f"no listing #{pid}")
    r = _ai_one(f"listing #{pid}", row, provider)
    set_ai("postings", int(pid), r["score"], r.get("why", ""))
    return for_listing(db.con().execute("SELECT rowid AS id, * FROM postings WHERE rowid=?", (int(pid),)).fetchone())



def refresh(limit: int = 300) -> dict:
    """Re-score stale fits: jobs first (never scored, or scored at another rev), then stored listings newest first.
    {jobs, listings, left}. Background-safe: one item that fails never stops the rest."""
    ctx = context()
    cur = ctx["rev"]
    jobs = db.con().execute("SELECT * FROM jobs WHERE fit_rev IS NULL OR fit_rev != ? ORDER BY id DESC", (cur,)).fetchall()
    posts = db.con().execute("SELECT rowid AS id, * FROM postings WHERE title IS NOT NULL AND (fit_rev IS NULL OR fit_rev != ?) "
                             "ORDER BY first_seen DESC", (cur,)).fetchall()
    done = {"jobs": 0, "listings": 0}
    for kind, rows in (("jobs", jobs), ("listings", posts)):
        for r in rows:
            if done["jobs"] + done["listings"] >= limit:
                break
            try:
                (for_job if kind == "jobs" else for_listing)(r, ctx)
                done[kind] += 1
            except (Exception, SystemExit) as e:  # one bad row costs only itself
                db.release(close=False)
                from . import log

                log.get("fit").warning("fit %s %s failed: %s", kind, r["id"], e)
    return done | {"left": len(jobs) + len(posts) - done["jobs"] - done["listings"]}


def stale_count(cur: str | None = None) -> int:
    cur = cur or rev()
    return db.con().execute("SELECT COUNT(*) n FROM jobs WHERE fit_rev IS NULL OR fit_rev != ?", (cur,)).fetchone()["n"]


def top_fits(days: int = 3, min_fit: int = 70, n: int = 3) -> list[dict]:
    """Today's 'Top new fits': untracked, undismissed listings first seen in the last `days` days at fit >= min_fit."""
    since = datetime.now().timestamp() - days * 86400
    rows = db.con().execute(
        "SELECT rowid AS id, title, company, url, sources, fit_score FROM postings WHERE job_id IS NULL AND "
        "COALESCE(dismissed, 0) = 0 AND (closed_at IS NULL OR closed_at >= date('now', 'localtime')) AND title IS NOT NULL AND fit_score >= ? AND "
        "first_seen >= datetime(?, 'unixepoch') ORDER BY fit_score DESC, first_seen DESC LIMIT ?",
        (min_fit, int(since), n)).fetchall()
    out = []
    for r in rows:
        try:
            src = json.loads(r["sources"] or "[]")
        except ValueError:
            src = []
        out.append({"id": r["id"], "title": r["title"], "company": r["company"] or "", "url": r["url"] or "",
                    "fit": r["fit_score"], "sources": [str(s) for s in src][:3] if isinstance(src, list) else []})
    return out


def breakdown_text(job) -> str:
    """`lodestar fit ID`: the score, every part with its weight, the modifiers and the chips."""
    f = stored(job)
    if not f:
        return f"#{job['id']} {job['company']} - {job['title']}: no fit yet (lodestar fit refresh)"
    lines = [f"#{job['id']} {job['company']} - {job['title']}: fit {f['score']}"
             + (" · partial" if f.get("partial") else "") + (" · BLOCKED" if f.get("blocked") else "")
             + (" (stale: lodestar fit refresh)" if f.get("rev") != rev() else ""), f"  {f.get('note', '')}"]
    for p, v in f["parts"].items():
        lines.append(f"  {p:<11} {'-' if v['s'] is None else v['s']:>4}  (weight {v['w']})")
    lines += [f"  {c['sign']} {c['text']}" for c in f["chips"]]
    return "\n".join(lines)
