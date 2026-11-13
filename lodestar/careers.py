"""Career discovery (blueprint v1.1 sections 4-5, pass 23): your profile bank is evidence about you, never a boundary.
Past titles map to O*NET occupations (occupations.py); related occupations become expansion tiers; each suggestion gets
a career class and says why it fits, what is missing, what does not transfer and how to close the gap. Deterministic:
no AI. Candidate-only: never in employer text or prompts, and the salary floor is never read here."""
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from . import occupations

TIERS = {0: "Requested target", 1: "Equivalent roles", 2: "Closely related", 3: "Transferable fit",
         4: "Bridge opportunity", 5: "Longer-term pathway", 6: "Explore further"}
CLASSES = {"qualified_now": "Qualified now", "competitive_with_framing": "Competitive with framing",
           "bridge_required": "Bridge required", "longer_term": "Longer-term development",
           "ineligible": "Currently ineligible", "insufficient_evidence": "Insufficient evidence"}
NOTE_NO_EVIDENCE = ("Insufficient evidence: no past title matched an O*NET occupation and no degree is on file. Add your "
                    "roles in Profile, or add a career track for the field you want.")
REGULATED = Path(__file__).parent / "data" / "regulated.json"


@lru_cache(maxsize=1)
def _regulated() -> dict:
    return {k: v for k, v in json.loads(REGULATED.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def regulated(code: str) -> str | None:
    """The licensing note for an occupation, by the longest matching SOC prefix (data/regulated.json)."""
    # ponytail: a seed list of common licensed occupations; extend it as data, never as code
    hit = max((p for p in _regulated() if code.startswith(p)), key=len, default=None)
    return _regulated()[hit] if hit else None


def _words(s: str, n: int) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", str(s).casefold()) if len(w) >= n}


def evidence(bank: dict | None = None) -> dict:
    """What the profile bank shows: titles, skills, certifications, degrees, its text, the occupations your titles
    are (score >= 0.8) and the zone that implies."""
    if bank is None:
        from . import profile

        bank = profile.load()
    from .profile import is_disputed

    rows = lambda k: [r for r in bank.get(k) or [] if isinstance(r, dict) and not is_disputed(k, r, bank)]  # noqa: E731
    titles = [str(r.get("title") or "").strip() for r in rows("experience")]
    titles += [str(r.get("role") or "").strip() for r in rows("volunteering")]
    titles = [t for t in titles if t]
    skills = [str(r.get("name") or "").strip() for r in rows("skills")]
    for k in ("experience", "projects"):
        for r in rows(k):
            tech = r.get("technologies") or []
            skills += [str(x).strip() for x in (tech if isinstance(tech, list) else str(tech).split(","))]
    skills = list(dict.fromkeys(s for s in skills if s))
    certs = [str(r.get("name") or "").strip() for r in rows("certifications") if r.get("name")]
    degrees = [str(r.get("degree") or "").strip() for r in rows("education") if r.get("degree")]
    bullets = [str(b) for k in ("experience", "projects", "volunteering") for r in rows(k) for b in r.get("bullets") or []]
    direct: dict[str, tuple[float, str]] = {}
    by_title: dict[str, list[str]] = {}
    for t in titles:
        for code, score in occupations.match_title(t):
            if score >= 0.8:
                by_title.setdefault(t, []).append(code)
                if score > direct.get(code, (0.0, ""))[0]:
                    direct[code] = (score, t)
    return {"titles": titles, "skills": skills, "certs": certs, "degrees": degrees,
            "text": " ".join(titles + skills + bullets), "direct": direct,
            "zone": candidate_zone(by_title, degrees)}


def _degree_zone(degrees: list[str]) -> int | None:
    d = " ".join(degrees).casefold()
    if re.search(r"doctor|ph\.?d|master|mba|m\.s|bachelor|b\.s|b\.a|\bbs\b|\bba\b", d):
        return 4
    if "associate" in d:
        return 3
    if re.search(r"high school|ged|diploma", d):
        return 2
    return None


def candidate_zone(by_title: dict[str, list[str]], degrees: list[str]) -> int | None:
    """The O*NET Job Zone your evidence supports. A title O*NET files under several occupations counts at the lowest
    of their zones (never the most flattering reading); across titles and your degree, the highest."""
    zones = []
    for codes in by_title.values():
        z = [x for x in ((occupations.get(c) or {}).get("zone") for c in codes) if x]
        if z:
            zones.append(min(z))
    if (dz := _degree_zone(degrees)) is not None:
        zones.append(dz)
    return max(zones) if zones else None


def classify(tier: int, zone: int | None, cand_zone: int | None, excluded: bool = False,
             regulated_unmet: bool = False) -> str:
    """The career class (blueprint 4.4) of one occupation for you."""
    if excluded:
        return "ineligible"
    if cand_zone is None or zone is None:
        return "insufficient_evidence"
    if tier == 4:
        return "bridge_required"
    if zone >= cand_zone + 2:
        return "longer_term"
    if zone == cand_zone + 1 or regulated_unmet:
        return "bridge_required"
    if tier == 1 or (tier == 2 and zone < cand_zone):  # your own occupation, or a close one needing less preparation
        return "qualified_now"
    return "competitive_with_framing"


def _excluded_words(extra=()) -> list[str]:
    from . import settings

    words = [w for w in re.split(r"[,;]", str(settings.pref("excluded_title_words") or ""))]
    try:
        from . import profile

        words += re.split(r"[,;]", profile.pref_field("Deal-breakers"))
    except (Exception, SystemExit):  # the template (or no profile): no deal-breakers
        pass
    return [w.strip().casefold() for w in list(words) + list(extra) if len(w.strip()) >= 3]


from .util import word_in as _word_in  # noqa: E402  one home (pass 31): whole word, like fit.gates


def _has(hay: str, needle: str) -> bool:
    a, b = hay.casefold(), needle.casefold()
    return bool(a and b) and (a in b or b in a)


def suggest(tiers=(0, 1, 2, 3, 4, 5), limit: int = 12, per_group: int = 2, bank: dict | None = None,
            targets: list[str] | None = None, exclude=(), show_excluded: bool = False) -> dict:
    """Career suggestions from your evidence (tiers 1-5) and the targets you chose (tier 0, plus their tier-4 bridges).
    Only the tiers asked for are returned: the search is never broadened silently. Returns {suggestions, zone, meta,
    note}; each suggestion names its source taxonomy and version."""
    ev, meta, occ = evidence(bank), occupations.meta(), occupations.load()["occ"]
    targets = _track_targets() if targets is None else list(targets)
    cz, direct = ev["zone"], ev["direct"]
    found: dict[str, dict] = {}

    def add(code: str, tier: int, why: str) -> None:
        if code not in occ:
            return
        hit = found.setdefault(code, {"tier": tier, "why": []})
        hit["tier"] = min(hit["tier"], tier)
        if why not in hit["why"]:
            hit["why"].append(why)

    for code, (_, t) in direct.items():
        add(code, 1, f"Your title '{t}' is an O*NET title for {occ[code]['title']}")
    for d in direct:
        for r in occupations.related(d):
            if r in direct:
                continue
            z = occ.get(r, {}).get("zone")
            tier = 5 if z and cz and z >= cz + 2 else 2 if r[:2] in {c[:2] for c in direct} else 3
            add(r, tier, f"Related to {occ[d]['title']} in O*NET")
    for t in targets:
        if t not in occ:
            continue
        o = occ[t]
        add(t, 0, "You chose this field")
        if cz and o.get("zone") and o["zone"] > cz:
            for r in occupations.related(t):
                rz = occ.get(r, {}).get("zone")
                if r != t and rz and rz <= cz:
                    add(r, 4, f"Also a route into {o['title']}")
    if not found or (cz is None and not targets):
        return {"suggestions": [], "zone": cz, "meta": meta, "note": NOTE_NO_EVIDENCE}
    bad, source = _excluded_words(exclude), _source(meta)
    out = [c for code, hit in found.items() if hit["tier"] in tiers
           and (c := _card(occ[code], hit["tier"], hit["why"], ev, bad, source, show_excluded))]
    out.sort(key=lambda s: (s["tier"], -s["overlap"], s["code"]))
    kept: list[dict] = []
    per: dict[str, int] = {}
    for s in out:
        g = s["code"][:4]
        if s["tier"] > 1 and per.get(g, 0) >= per_group:
            continue
        per[g] = per.get(g, 0) + (s["tier"] > 1)
        kept.append(s)
    return {"suggestions": kept[:limit], "zone": cz, "meta": meta, "note": "" if kept else NOTE_NO_EVIDENCE}


def _source(meta: dict) -> str:
    source = str(meta.get("source") or "")
    return f"O*NET {meta.get('version', '')}".strip() if not source or source.endswith(" Database") else source


def _card(o: dict, tier: int, why: list[str], ev: dict, bad: list[str], source: str, show_excluded: bool) -> dict | None:
    """One suggestion for occupation o: class, the four explanations, licensing note; None when excluded (unless
    show_excluded, then Currently ineligible)."""
    code, cz = o["code"], ev["zone"]
    names = [o["title"]] + list(o.get("titles") or [])
    excluded = any(_word_in(w, n) for w in bad for n in names)
    if excluded and not show_excluded:
        return None
    tech = o.get("tech") or []
    uses = [s for s in ev["skills"] if any(_has(s, x) for x in tech)]
    mine = _words(ev["text"], 5)
    note = regulated(code)
    unmet = bool(note) and not any(_words(c, 3) & _words(o["title"], 3) for c in ev["certs"])
    zone = o.get("zone")
    cls = classify(tier, zone, cz, excluded, unmet)
    return {"code": code, "title": o["title"], "tier": tier, "tier_label": TIERS[tier], "cls": cls,
            "cls_label": CLASSES[cls], "zone": zone, "overlap": round(len(uses) / max(1, min(len(tech), 10)), 2),
            "why": list(why) + ([f"Uses skills you list: {', '.join(uses[:4])}"] if uses else []),
            "missing": [x for x in tech if not any(_has(s, x) for s in ev["skills"])][:5],
            "not_transfer": [t for t in o.get("tasks") or [] if not (_words(t, 5) & mine)][:3],
            "close_gap": ([occupations.ZONE_PREP[zone]] if zone and cz and zone > cz else []) + ([note] if note else []),
            "regulated": note, "source": source}


UNMAPPED = "AI-suggested unmapped role: review"
TECH_GROUPS = ("15-", "17-")  # computer and mathematical; architecture and engineering


def work_focus(title: str) -> str:
    """What a research pack looks for in a team, by the job's occupation (blueprint 12.3: never software by default)."""
    try:
        hit = next((c for c, s in occupations.match_title(title or "", 1) if s >= 0.8), "")
    except SystemExit:  # no occupation data: the generic wording
        hit = ""
    return ("team, stack and engineering culture signals" if hit.startswith(TECH_GROUPS)
            else "team, ways of working and culture signals for this kind of role")


def explore(interests: str, provider: str | None = None, bank: dict | None = None, limit: int = 8) -> dict:
    """Tier 6, Explore further (blueprint 3.2 open exploration): one AI call proposes occupations from what interests
    you and your profile as an employer sees it (never the salary floor or Preferences). Each role is matched to O*NET
    by title (its card names the taxonomy and version); one O*NET does not know stays, labelled UNMAPPED."""
    from . import ai, profile

    interests = " ".join(str(interests or "").split())[:500]
    if not interests:
        raise SystemExit("say what interests you: work you enjoy, settings, people, values")
    try:
        prof = profile.drop_preferences(profile.candidate_text(3000, strict=False, private=False))
    except (Exception, SystemExit):  # the template or no profile: interests alone
        prof = ""
    r = ai.ask_json(
        "Suggest up to 8 distinct occupations, across different industries, that fit this person's interests and "
        "transferable experience, including non-obvious ones. Use standard occupation titles. Return JSON "
        '{"roles": [{"title": "...", "why": "one sentence tied to their interests or experience"}]}. '
        f"Never claim they are qualified; never mention pay.\n\nINTERESTS: {interests}\n\nPROFILE:\n{prof or '(none)'}",
        provider=provider)
    roles = r.get("roles") if isinstance(r, dict) else r if isinstance(r, list) else None
    if not isinstance(roles, list):
        raise SystemExit("the AI answer had no list of roles; try again")
    from .extras import clean_label

    ev, meta, occ = evidence(bank), occupations.meta(), occupations.load()["occ"]
    bad, source, out, seen = _excluded_words(), _source(meta), [], set()
    for x in roles[:12]:
        if not isinstance(x, dict) or not (title := clean_label(x.get("title") or "", 80)):
            continue
        why = [f"AI: {clean_label(x.get('why') or '', 200)}"] if x.get("why") else ["AI suggestion"]
        hit = next((c for c, s in occupations.match_title(title, 1) if s >= 0.8), None)
        if hit:
            if hit not in seen and (c := _card(occ[hit], 6, why, ev, bad, source, False)):
                seen.add(hit)
                out.append(c)
        elif title.casefold() not in seen and not any(_word_in(w, title) for w in bad):
            seen.add(title.casefold())
            out.append({"code": None, "title": title, "tier": 6, "tier_label": TIERS[6], "cls": "insufficient_evidence",
                        "cls_label": CLASSES["insufficient_evidence"], "zone": None, "overlap": 0.0, "why": why,
                        "missing": [], "not_transfer": [], "close_gap": [], "regulated": None, "source": UNMAPPED})
    return {"suggestions": out[:limit], "zone": ev["zone"], "meta": meta, "note": ""}


# --- career tracks (blueprint appendix A.1): a field you chose to search -----------------------------------------
INTENTS = ("resume_led", "desired_field", "combined", "exploration", "pivot")
TRAINING = ("none", "short_course", "certification", "apprenticeship", "degree", "open")
PRIORITY = ("high", "medium", "exploratory")
TITLE_CAP = 6  # ponytail: titles searched per track; each 3 is one round of board requests
_LISTS = ("titles", "codes", "tiers", "exclusions")


def _clean_list(v) -> list[str]:
    items = [x for item in ([v] if isinstance(v, str) else list(v or [])) for x in str(item).split(",")]
    out: dict[str, str] = {}
    for x in items:
        x = " ".join(str(x).split())
        if x and x.casefold() not in out:
            out[x.casefold()] = x
    return list(out.values())


def _check(t: dict) -> dict:
    if not str(t.get("label") or "").strip():
        raise SystemExit("a track needs a name")
    if t["intent"] not in INTENTS:
        raise SystemExit(f"intent must be one of {', '.join(INTENTS)}")
    if not t["titles"] and not t["codes"]:
        raise SystemExit("a track needs a title or an occupation")
    try:
        t["tiers"] = sorted({int(x) for x in t["tiers"]})
    except (TypeError, ValueError):
        raise SystemExit("tiers are 0-6") from None
    if not t["tiers"] or any(x not in TIERS for x in t["tiers"]):
        raise SystemExit("tiers are 0-6")
    if t["training"] not in TRAINING:
        raise SystemExit(f"training must be one of {', '.join(TRAINING)}")
    if t["priority"] not in PRIORITY:
        raise SystemExit(f"priority must be one of {', '.join(PRIORITY)}")
    bad = [c for c in t["codes"] if not occupations.get(c)]
    if bad:
        raise SystemExit(f"unknown O*NET occupation: {', '.join(bad)}")
    return t


def _row(r) -> dict:
    t = dict(r)
    for k in _LISTS:
        t[k] = json.loads(t[k] or "[]")
    t["enabled"] = bool(t["enabled"])
    return t


def add_track(label: str, intent: str, titles=(), codes=(), tiers=None, exclusions=(), location: str = "",
              training: str = "none", priority: str = "medium") -> int:
    """Save a career track. Default tiers: a desired field searches its own words only (0), resume-led your
    occupations' titles (1), the others both. Occupation codes are resolved from the titles (score >= 0.8) but used
    only when tier 1 is on."""
    from . import db
    from .config import full_ai_check

    full_ai_check("changes a career track")
    titles = _clean_list(titles)
    codes = _clean_list(codes) or list(dict.fromkeys(c for t in titles for c, s in occupations.match_title(t, 1) if s >= 0.8))
    tiers = [0] if tiers is None and intent == "desired_field" else [1] if tiers is None and intent == "resume_led" else (
        [0, 1] if tiers is None else tiers)
    t = _check({"label": str(label or "").strip(), "intent": intent, "titles": titles, "codes": codes, "tiers": tiers,
                "exclusions": _clean_list(exclusions), "location": str(location or "").strip(), "training": training,
                "priority": priority})
    cur = db.con().execute(
        "INSERT INTO career_tracks(label, intent, titles, codes, tiers, exclusions, location, training, priority) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (t["label"], t["intent"], *(json.dumps(t[k]) for k in _LISTS), t["location"], t["training"], t["priority"]))
    db.con().commit()
    return int(cur.lastrowid or 0)


def get_track(track_id: int) -> dict:
    from . import db

    r = db.con().execute("SELECT * FROM career_tracks WHERE id=?", (track_id,)).fetchone()
    if r is None:
        raise SystemExit(f"no career track #{track_id}")
    return _row(r)


def tracks(enabled_only: bool = False) -> list[dict]:
    from . import db

    q = "SELECT * FROM career_tracks" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
    return [_row(r) for r in db.con().execute(q)]


def update_track(track_id: int, **fields) -> dict:
    from . import db
    from .config import full_ai_check

    full_ai_check("changes a career track")
    t = get_track(track_id)
    unknown = set(fields) - {"label", "intent", "titles", "codes", "tiers", "exclusions", "location", "training",
                             "priority", "enabled"}
    if unknown:
        raise SystemExit(f"unknown track field: {', '.join(sorted(unknown))}")
    t.update({k: _clean_list(v) if k in ("titles", "codes", "exclusions") else v for k, v in fields.items()})
    t["enabled"] = bool(t["enabled"]) if not isinstance(t["enabled"], str) else t["enabled"].lower() in ("1", "true", "on", "yes")
    _check(t)
    db.con().execute("UPDATE career_tracks SET label=?, intent=?, titles=?, codes=?, tiers=?, exclusions=?, location=?, "
                     "training=?, priority=?, enabled=? WHERE id=?",
                     (t["label"], t["intent"], *(json.dumps(t[k]) for k in _LISTS), str(t["location"] or ""),
                      t["training"], t["priority"], int(t["enabled"]), track_id))
    db.con().commit()
    return get_track(track_id)


def remove_track(track_id: int) -> None:
    from . import db
    from .config import full_ai_check

    full_ai_check("changes a career track")
    get_track(track_id)
    with db.con():
        db.con().execute("UPDATE postings SET track_id=NULL WHERE track_id=?", (track_id,))
        db.con().execute("DELETE FROM career_tracks WHERE id=?", (track_id,))


def search_titles(track: dict) -> list[str]:
    """The titles a track searches: your own words (tier 0) and, only when tier 1 is on, each occupation's O*NET title
    and its first two job titles. De-duplicated, at most TITLE_CAP: never broadened beyond the tiers you chose."""
    out = list(track["titles"])
    if 1 in track["tiers"]:
        for c in track["codes"]:
            o = occupations.get(c) or {}
            # an O*NET title with a comma or 'or' ('Hotel, Motel, and Resort Desk Clerks') would be split into broader
            # searches by web_monitor.alternatives: only clean titles are searched (its job titles usually are)
            out += [t for t in [o.get("title") or ""] + list(o.get("titles") or [])[:3] if not _SPLITS.search(t)][:3]
    return _clean_list(out)[:TITLE_CAP]


_SPLITS = re.compile(r"[,;|]|\bor\b", re.I)


COVERAGE_NOTE = "Partial coverage: only the boards listed were searched. Lodestar never searches every job board or employer."


def coverage(ran: list[str], errors: list[str]) -> dict:
    """Which boards a search asked, which failed and which were not ready (no key), against all of them (blueprint
    6.5). checked=False means nothing was searched: never report that as 'no jobs'."""
    from . import web_monitor

    ready = set(web_monitor.sources_ready())
    asked = list(dict.fromkeys(ran))
    failed = {str(e).split(":", 1)[0].strip() for e in errors}  # 'remotive: HTTP 500' -> asked, but answered nothing
    return {"asked": asked, "failed": list(dict.fromkeys(errors)), "total": len(web_monitor.SOURCES),
            "not_ready": [s for s in web_monitor.SOURCES if s not in ready], "checked": bool(set(asked) - failed),
            "note": COVERAGE_NOTE}


def search_track(track_id: int, location: str | None = None) -> dict:
    """Search the job boards for one track's titles (three per round: web_monitor.search runs each on its own), merge
    by link, tag the stored postings with the track and report the coverage."""
    from . import db, web_monitor

    t = get_track(track_id)
    titles, ran, errs, results = search_titles(t), [], [], {}
    loc = location or t["location"] or None
    for i in range(0, len(titles), 3):
        found = web_monitor.search(", ".join(titles[i:i + 3]), errors=errs, ran=ran, **({"location": loc} if loc else {}))
        for r in found:
            results.setdefault(r.get("url"), r)
    results.pop(None, None)
    with db.con():
        for url in results:  # ponytail: tags by the first link, which listings.store keeps as `url`
            db.con().execute("UPDATE postings SET track_id=? WHERE url=?", (track_id, url))
    return {"track": t, "titles": titles, "results": list(results.values()), "coverage": coverage(ran, errs)}


def _track_targets() -> list[str]:
    """Tier-0 targets: the occupations of your enabled tracks other than resume-led ones."""
    try:
        return list(dict.fromkeys(c for t in tracks(enabled_only=True) if t["intent"] != "resume_led" for c in t["codes"]))
    except sqlite3.OperationalError:  # a database from before pass 23 opened read-only: no targets
        return []
