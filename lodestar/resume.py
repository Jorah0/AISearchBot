"""Resume / cover-letter tooling. Your master profile lives at ~/.lodestar/profile.md (you edit it once;
lodestar tailors per job). Every job gets a folder under ~/.lodestar/applications/<id>-<company>-<title>/.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

from . import ai, db, log
from .config import APPS_DIR, PROFILE
from .util import slug

SYSTEM = (
    "You are a senior resume writer and ATS specialist. Hard rules: never invent employers, titles, dates, "
    "degrees, metrics or skills the candidate did not provide; you may rephrase, reorder, cut, and quantify only "
    "with numbers present in the source. Write tight achievement-first bullets: action verb, what, measurable result."
)

PROFILE_TEMPLATE = """# Master Resume  (edit me - keep EVERYTHING here; lodestar trims per job)

## Contact
Full Name | City, ST | email@example.com | +1 555 000 0000 | linkedin.com/in/you | github.com/you

## Summary
Two or three sentences: who you are, strongest skills, what you want next.

## Skills
- Languages:
- Frameworks / Tools:
- Domains:

## Experience
### Job Title - Company (2022-01 - Present)
- Achievement bullet with a number (e.g. cut deploy time 40%)
- Another bullet

### Previous Title - Company (2019-06 - 2021-12)
- Bullet

## Projects
### Project name - one line, link
- What it does, what you used, result

## Education
Degree, School, Year

## Certifications

## Preferences (used for job search ranking)
Target roles: | Locations / remote: | Salary floor: | Deal-breakers: | Industries to avoid:
"""


def profile_text() -> str:
    if not PROFILE.is_file():
        PROFILE.write_text(PROFILE_TEMPLATE, encoding="utf-8")
        raise SystemExit(f"Created {PROFILE}. Fill in your full history there, then rerun.")
    return PROFILE.read_text(encoding="utf-8-sig")


def app_dir(job) -> Path:
    d = APPS_DIR / f"{job['id']}-{slug(job['company'])}-{slug(job['title'])}"
    d.mkdir(parents=True, exist_ok=True)
    return d


SUBMITTED = ("resume.md", "resume.docx", "resume.pdf", "cover_letter.md", "cover_letter.docx", "cover_letter.pdf",
             "form_answers.md")


def snapshot_submitted(job) -> Path | None:
    """Copy the employer-facing documents of an application into its submitted/ folder with a sha256 manifest, once:
    what was sent stays as it was when you edit the working copies later (blueprint 8.6). None when already taken."""
    import hashlib
    from datetime import datetime

    d = app_dir(job)
    sub = d / "submitted"
    if (sub / "manifest.json").is_file():
        return None
    sub.mkdir(exist_ok=True)
    files = {}
    for name in SUBMITTED:
        if (d / name).is_file():
            shutil.copy2(d / name, sub / name)
            files[name] = hashlib.sha256((sub / name).read_bytes()).hexdigest()
    (sub / "manifest.json").write_text(json.dumps({"job_id": job["id"], "at": datetime.now().isoformat(timespec="seconds"),
                                                   "files": files}, indent=1), encoding="utf-8")
    return sub


def write_doc(path: Path, text: str) -> Path:
    """Write a generated per-job document. A previous version that differs (possibly hand-edited) moves to history/."""
    from datetime import datetime

    if path.is_file() and path.read_text(encoding="utf-8") != text:
        (path.parent / "history").mkdir(exist_ok=True)
        path.replace(path.parent / "history" / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    path.write_text(text, encoding="utf-8")
    return path


def _drop_pdf(md: Path) -> bool:
    """Before a per-job .md is rewritten: remove the .pdf beside it (what mail attaches first), so no PDF of the old text
    outlives it. A PDF open in another program stops the save here, before anything changed. -> there was one."""
    pdf = md.with_suffix(".pdf")
    if not pdf.is_file():
        return False
    try:
        pdf.unlink()
    except OSError:
        raise SystemExit(f"{pdf.name} is open in another program: close it, then save again") from None
    return True


def _keep_exports(md: Path, had_pdf: bool) -> None:
    """After a per-job .md changed: the .docx / .pdf beside it are what get uploaded and attached, so they follow it.
    A PDF that was there is printed again (export_pdf, which re-exports the .docx too); when no PDF can be made it stays
    removed (the .docx and the text are current) rather than an old one being sent."""
    if had_pdf:
        try:
            r = export_pdf(md, open_html=False)
            if r["method"] == "html":  # no engine: no PDF; the print page is not a document to attach
                Path(r["path"]).unlink(missing_ok=True)
            return
        except (Exception, SystemExit) as e:
            log.get("resume").warning("could not print %s again (%s): it stays removed", md.with_suffix(".pdf").name, e)
    if md.with_suffix(".docx").is_file():
        export_docx(md)


def save_doc(job, name: str, text: str) -> Path:
    """An edited per-job document (editor Save, `resume adjust --job --save`): the previous version moves to history/,
    resume.md gets its variant hash and a re-score, and an existing .docx / .pdf beside it is exported again."""
    had_pdf = _drop_pdf(app_dir(job) / name)
    out = write_doc(app_dir(job) / name, text)
    if name == "resume.md":
        from .extras import resume_hash

        db.update_job(job["id"], resume_hash=resume_hash(text))
        rescore(job["id"])  # the match % follows the resume you just saved
    _keep_exports(out, had_pdf)
    db.add_event(job["id"], "edited", name)
    return out


def _jd(job) -> str:
    if not job["jd"]:
        raise SystemExit(f"job #{job['id']} has no job description. Add one: lodestar jobs jd {job['id']} <url|file>")
    return job["jd"]


def candidate_text(limit: int | None = None, strict: bool = True, private: bool = True) -> str:
    """Master profile + profile-bank facts it leaves out, fitted to `limit` by whole sections. Prompts read this.
    private=False for anything an employer reads (resume, letters, mail, form answers): no salary floor."""
    from .profile import candidate_text as _ct

    return _ct(limit, strict, private)


def _current_resume(job) -> str:
    p = app_dir(job) / "resume.md"
    return p.read_text(encoding="utf-8-sig") if p.is_file() else candidate_text(private=False)


def coverage(job, text: str | None = None, save: bool = True) -> dict:
    """Deterministic JD coverage (ats.match) of `text`, by default the job's current resume (tailored, else the master
    without Preferences). save: keep it in coverage.json and as the job's match_score, and refresh the keyword lists of
    an existing gap.json (its AI verdict stays as judged). No AI involved."""
    from . import ats

    cov = ats.match(_current_resume(job) if text is None else text, _jd(job), job["title"], db.ats_skip(job), job["company"])
    if save:
        d = app_dir(job)
        (d / "coverage.json").write_text(json.dumps(cov, indent=2), encoding="utf-8")
        db.set_fields(job["id"], match_score=cov["score"])
        try:
            gapj = json.loads((d / "gap.json").read_text(encoding="utf-8")) if (d / "gap.json").is_file() else None
        except ValueError:
            gapj = None
        if isinstance(gapj, dict):  # a gap check ran: its keyword lists follow the resume, not the resume it judged
            (d / "gap.json").write_text(json.dumps(gapj | _gap_keywords(cov), indent=2), encoding="utf-8")
    return cov


def rescore(job_id: int) -> None:
    """The JD or resume.md changed by hand: a stored JD coverage (card match %, match sort, coverage.json, Insights'
    match bands) is recomputed, never left judging the old text. Nothing stored yet: nothing is made here. When it can
    no longer be computed (JD cleared, template profile) the old score is dropped rather than kept."""
    job = db.get_job(job_id)
    stored = APPS_DIR / app_dir(job).name / "coverage.json"
    if job["match_score"] is None and not stored.is_file():
        return
    try:
        coverage(job)
    except SystemExit:
        db.update_job(job_id, touch=False, match_score=None)
        stored.unlink(missing_ok=True)


def set_jd(job_id: int, jd: str, **fields) -> None:
    """Replace a job's description (fields: e.g. the posting url) and re-score its coverage: the one JD save path."""
    db.update_job(job_id, jd=jd, **fields)
    rescore(job_id)
    refit(job_id)


def refit(job_id: int) -> None:
    """The fit score follows a changed JD or tracker field; a fit failure never blocks the save."""
    try:
        from . import fit

        fit.for_job(db.get_job(job_id))
    except (Exception, SystemExit) as e:
        log.get("fit").warning("fit #%s not re-scored: %s", job_id, e)


def _gap_keywords(cov: dict) -> dict:
    return {"match_score": cov["score"], "coverage": cov,
            "missing_keywords": [k["term"] for k in cov["keywords"] if not k["matched"] and not k["skipped"]],
            "present_keywords": [k["term"] for k in cov["keywords"] if k["matched"]]}


def toggle_skip(job, term) -> dict:
    """Mark a JD keyword "not mine" (or unmark it) and return the recomputed coverage. Aliases resolve ('k8s')."""
    from . import ats

    db.toggle_ats_skip(job["id"], ats.canonical(term))
    return coverage(db.get_job(job["id"]))


def _source(base: str | None = None) -> str:
    """What tailoring starts from, employer-safe (no Preferences): the master profile, or saved resume `base` from the
    profile bank plus the bank facts it leaves out."""
    if not base:
        return candidate_text(private=False)
    from . import profile

    text = profile.saved_text(base).rstrip()
    extra = profile.extras_text(text)
    return profile.employer_safe(text + ("\n\n" + extra if extra else ""))


def _save_resume(job, text: str, before: int, note: str = "", revs: dict | None = None) -> tuple[Path, int]:
    """Write a new resume.md (the old one moves to history/, a .docx / .pdf beside it follows), record its variant,
    re-score coverage and log the delta. revs: the profile's section_revs the text was built from (a studio version
    built earlier); default: the profile as it is now."""
    from .extras import resume_hash

    from .profile import used_revs

    had_pdf = _drop_pdf(app_dir(job) / "resume.md")
    out = write_doc(app_dir(job) / "resume.md", text)
    _keep_exports(out, had_pdf)
    h = resume_hash(text)
    # the profile sections this resume draws on, as they were when it was written: the drawer's 'profile changed'
    # badge and the pipeline's stale Tailor step compare them with the profile now
    db.update_job(job["id"], resume_hash=h, profile_rev=json.dumps(used_revs(text, revs), sort_keys=True))
    db.add_event(job["id"], "resume", f"{out} variant={h}" + (f" ({note})" if note else ""))
    if not job["jd"]:  # a resume for a job with no description yet (studio): no coverage to re-score
        return out, before
    after = coverage(job, text)["score"]
    db.add_event(job["id"], "coverage", f"coverage {before} -> {after}")
    return out, after


def tailor(job, use_council: bool = False, provider: str | None = None, base: str | None = None) -> Path:
    """Whole-document AI tailoring. base: a saved resume id from the profile bank to start from instead of the master."""
    prompt = f"""Tailor the candidate's {'resume' if base else 'master resume'} for this job. Output a complete resume in Markdown (one page where possible).
Mirror the job's vocabulary wherever the candidate genuinely has that experience, lead with the most relevant items,
cut irrelevant ones, and keep contact details exactly as given.

JOB: {job['title']} at {job['company']}
JOB DESCRIPTION:
{_jd(job)}

{'BASE RESUME' if base else 'MASTER RESUME'} (an "On file" section, if present, lists further true facts from the candidate's other resumes):
{_source(base)}"""
    before = coverage(job, save=False)["score"]
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)
    return _save_resume(job, text, before)[0]


# ----------------------------------------------------------------------------- bullet-level tailoring
ROLE_SECTIONS = ("experience", "employment", "work history", "career history", "project", "volunteer")
BULLET_RE = re.compile(r"^(\s*[-*•·▪◦‣●–]\s+)(\S.*)$")  # PDF text keeps its bullet glyphs
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
ONFILE_RE = re.compile(r"(?ms)^## On file.*?(?=^## |\Z)")


def _heading(line: str) -> tuple[str, int] | None:
    """(text, level): a markdown '#' heading, a short capitals / ':' line (lint), or a bare standard section name such as
    'Experience' (the plain text of an imported .docx or .pdf)."""
    from . import lint

    if BULLET_RE.match(line):
        return None
    if h := lint._heading(line):
        return h
    s = lint._plain(line).rstrip(":").strip()
    return (s, 2) if lint.STANDARD_HEADINGS.match(s.lower()) else None


def _bullets(text: str) -> list[dict]:
    """Achievement bullets under Experience / Projects-like headings: [{id, section, role, group, line, original}].
    group: bullets that may be reordered among themselves. A role heading, or any other line between bullets
    ('**Analyst**, Beta'), starts a new group, so a bullet never moves to another employer."""
    from . import lint

    out: list[dict] = []
    section = role = ""
    level, group, after_bullet = 0, 0, False
    for n, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        in_roles = any(k in section.lower() for k in ROLE_SECTIONS)
        if h := _heading(line):
            t, lv = h
            low = t.lower()
            # a section: a standard name, anything outside Experience-like sections, or a markdown heading no deeper
            # than the section's own ('# Experience' then '## Engineer - Acme' is a role, as a .docx's Heading 2 is)
            if lint.STANDARD_HEADINGS.match(low) or low.startswith("on file") or not in_roles or (line.lstrip().startswith("#") and lv <= level):
                section, role, level = t, "", lv
            else:
                role = t
            group, after_bullet = group + 1, False
        elif b := BULLET_RE.match(line):
            if in_roles:
                out.append({"id": len(out) + 1, "section": section, "role": role or section, "group": group, "line": n,
                            "original": b[2].strip()})
                after_bullet = True
        elif after_bullet or not role:  # a plain role line ('**Analyst**, Beta'), or the first line under a section
            group += after_bullet
            after_bullet, role = False, lint._plain(line)[:120]
    return out


def _numbers(s: str) -> set[str]:
    return {n.replace(",", "") for n in NUM_RE.findall(s or "")}


TITLE_WORDS = re.compile(r"(?i)\b(?:director|vp|vice president|head of|chief|manager|lead|principal|senior|staff|founder|"
                         r"cto|ceo|cfo|coo)\b")
TOKEN_RE = re.compile(r"[A-Za-z0-9][\w.+#/&-]*[\w+#]|[A-Za-z]")
PERSONAL_TEXT = re.compile(r"(?i)\b(?:citizen(?:ship)?|green card|visa status|nationality|married|divorced|date of birth|"
                           r"born in|years old|religio\w*|ethnicity|disabilit\w*|gender|pregnan\w*|ssn|passport)\b")


def _new_terms(text: str, base: str) -> list[str]:
    """Names in `text` that `base` never mentions: a token capitalised mid-sentence, or one that looks technical (an
    inner capital, a digit, '.', '+' or '#'). The lexicon-free half of the guard: 'Dagster' is in no skills list."""
    from .profile import _mentioned

    out = []
    for sent in re.split(r"(?<=[.!?;:])\s+", text):
        for i, t in enumerate(TOKEN_RE.findall(sent)):
            t = t.rstrip(".")
            if not t or re.fullmatch(r"[\d.,%$€£+xX-]*\d[\d.,%$€£+kKmMbBxX-]*", t):
                continue  # a number: the new-number check judges those
            if (re.search(r"[A-Z]", t[1:]) or re.search(r"\d|[.+#]", t) or (i and t[0].isupper())) and not _mentioned(t, base):
                out.append(t)
    return list(dict.fromkeys(out))


def check_rewrite(originals, proposed: str, facts: str, scope: str | None = None, jd_missing=(), declared=(),
                  title: str = "", allow_numbers=()) -> dict:
    """The no-invention guard every AI rewrite of your own text passes (bullet tailoring, the studio's bullets, headline,
    summary and skill-group labels). originals: the text(s) it rewrites, the only source of its numbers. facts: the
    whole profile; scope: what this text may draw on instead (the studio: the cited bullets + the entry's title and
    technologies, so a tool used at another employer cannot move here). Flags, any of which reverts the rewrite:
    unsupported (an added skill / cert / degree or missing JD keyword not in scope), new number (incl. years and
    dates), new title (a seniority word), new degree, new term (a name or tool the scope never mentions; no JD
    exemption), new link (URL, email, phone), personal (personal data or a pay figure)."""
    from . import ats
    from .lint import EMAIL
    from .profile import URL_RE, _mentioned, _phone

    orig = "\n".join([originals] if isinstance(originals, str) else originals)
    base = facts if scope is None else scope
    found = [t for t in jd_missing if ats.mentions(t, proposed)]
    found += sorted(ats.claims_in(proposed) - ats.claims_in(orig)) if proposed != orig else []
    added = list(dict.fromkeys(ats.canonical(t) for t in [*declared, *found]
                               if isinstance(t, str) and t.strip() and ats.mentions(t, proposed) and not ats.mentions(t, orig)))
    unsupported = [t for t in added if not ats.mentions(t, base)]
    numbers = _numbers(proposed) - _numbers(orig)
    # a computed number (the studio's 'N years') counts only as 'N years' / 'N+ years': the same figure stated anywhere
    # else in the text ('managed 7 engineers') is a new number like any other
    allow = {str(n) for n in allow_numbers
             if str(n) not in _numbers(re.sub(rf"(?<![\d.,]){re.escape(str(n))}\+?\s*-?\s*years?\b", " ", proposed, flags=re.I))}
    new_numbers = sorted(numbers - allow)
    titles = sorted({m.lower() for m in TITLE_WORDS.findall(proposed)} - {m.lower() for m in TITLE_WORDS.findall(orig + " " + title)})
    degrees = {x[0] for x in ats.lexicon()["terms"] if x[1] == "education"}
    new_degree = [t for t in unsupported if t in degrees]
    terms = [t for t in _new_terms(proposed, base + "\n" + orig + "\n" + title) if not any(ats.mentions(u, t) for u in added)]
    links = [x for x in [*URL_RE.findall(proposed), *EMAIL.findall(proposed), _phone(proposed)] if x and x not in orig]
    personal = [m for m in PERSONAL_TEXT.findall(proposed) if not _mentioned(m, orig)]
    personal += [m for m in salary_mentions(proposed) if m not in orig]
    flags = (["unsupported"] if unsupported else []) + (["new number"] if new_numbers else []) \
        + (["new title"] if titles else []) + (["new degree"] if new_degree else []) + (["new term"] if terms else []) \
        + (["new link"] if links else []) + (["personal"] if personal else [])
    why = "; ".join(x for x in (f"unsupported {', '.join(unsupported)}" if unsupported else "",
                                f"new number {', '.join(new_numbers)}" if new_numbers else "",
                                f"new title {', '.join(titles)}" if titles else "", f"new term {', '.join(terms)}" if terms else "",
                                "new link" if links else "", "personal data or pay" if personal else "") if x)
    return {"flags": flags, "added": added, "unsupported": unsupported, "new_numbers": new_numbers, "titles": titles,
            "terms": terms, "why": why, "computed": sorted(numbers & allow),
            "marks": sorted({s for t in added for s in ats.spans(t, proposed)})}


def _employer_copy(text: str) -> str:
    """A finished resume from tailoring source text: no "On file" prompt section, and the master's '# Master Resume'
    title becomes the candidate's name (from the contact line). It is copied out verbatim, so Preferences are stripped
    again here, and a salary floor still present stops the build."""
    from .profile import employer_safe

    text = employer_safe(ONFILE_RE.sub("", text))
    contact = next((ln for ln in text.splitlines() if "@" in ln and "|" in ln), "")
    name = contact.split("|")[0].strip().lstrip("# ") if contact else ""
    return re.sub(r"\A\s*# Master Resume[^\n]*", f"# {name}" if name and "@" not in name else "", text).strip() + "\n"


def tailor_bullets(job, base: str | None = None, provider: str | None = None) -> dict:
    """One AI call proposes per-bullet rewrites that carry the posting's missing keywords where the facts allow, and a
    relevance order per role. Deterministic guards then flag any added keyword found nowhere in your profile or bank
    ("unsupported") and any number the original bullet does not have ("new number"); flagged rows start rejected.
    Saved to bullets.json; resume.md is untouched until apply_bullets()."""
    from datetime import datetime

    from . import ats, profile

    src = _source(base)
    items = _bullets(src)
    if not items:
        raise SystemExit("no bullets found under an Experience or Projects heading (lines starting with '- ' or '•'). "
                         "A .docx imported before this version kept no bullet marks: import it again.")
    cov = ats.match(src, _jd(job), job["title"], db.ats_skip(job), job["company"])
    missing = [k for k in cov["keywords"] if not k["matched"] and not k["skipped"]]
    listing = "\n".join(f"{b['id']}. [{b['role']}] {b['original']}" for b in items)
    reply = ai.ask_json(f"""Propose bullet-level edits that tailor this resume to the job.
Rules: rewrite a bullet ONLY where it can truthfully carry the posting's language: same facts, same numbers, no new
tools, skills, employers or metrics. If a bullet cannot truthfully use a missing keyword, return it unchanged. Then rank
every bullet by relevance to this job (most relevant first; the program keeps each bullet under its own role). You may
set "drop": true on a bullet that is clearly irrelevant to this job.
Return JSON: {{"bullets": [{{"id": 1, "proposed": "the full bullet text", "added_terms": ["posting keywords this rewrite adds"],
"reason": "one line", "drop": false}}], "order": [ids, most relevant first]}}

MISSING KEYWORDS (most mentioned in the posting first): {', '.join(k['term'] for k in missing[:40]) or 'none'}

JOB: {job['title']} at {job['company']}
JOB DESCRIPTION:
{_jd(job)}

BULLETS (id. [role] text):
{listing}

THE WHOLE RESUME (for facts only):
{src}""", SYSTEM, provider)
    got: dict[int, dict] = {}
    for r in (reply.get("bullets") if isinstance(reply, dict) else None) or []:
        try:
            got[int(r["id"])] = r
        except (TypeError, KeyError, ValueError):
            continue
    rank: dict[int, int] = {}
    for i, x in enumerate((reply.get("order") if isinstance(reply, dict) else None) or []):
        try:
            rank.setdefault(int(x), i)
        except (TypeError, ValueError):
            continue
    bank = {k: v for k, v in profile.load().items() if k != "resumes"}  # file names are not facts
    facts = "\n".join((src, candidate_text(strict=False, private=False), json.dumps(bank, ensure_ascii=False)))
    rows = []
    for b in items:
        r, orig = got.get(b["id"], {}), b["original"]
        drop = r.get("drop") is True
        proposed = "" if drop else " ".join(str(r.get("proposed") or "").split()).lstrip("-*• ") or orig
        declared = [t for t in r.get("added_terms") or [] if isinstance(t, str)] if isinstance(r.get("added_terms"), list) else []
        # undeclared additions count too: posting keywords, and any skill, cert or degree the original did not name
        g = check_rewrite(orig, proposed, facts, jd_missing=[k["term"] for k in missing], declared=declared, title=b["role"]) \
            if proposed != orig else {"flags": [], "added": [], "unsupported": [], "new_numbers": [], "marks": []}
        flags = g["flags"]
        rows.append(b | {"proposed": proposed, "drop": drop, "changed": proposed != orig, "added_terms": g["added"],
                         "marks": g["marks"], "reason": str(r.get("reason") or "")[:300], "flags": flags,
                         "unsupported": g["unsupported"], "new_numbers": g["new_numbers"],
                         "accepted": proposed != orig and not flags and not drop})  # a drop starts unchecked: you choose
    rows.sort(key=lambda x: (x["group"], rank.get(x["id"], 10**6 + x["id"])))
    data = {"job": job["id"], "base": base or "", "created": datetime.now().isoformat(timespec="seconds"),
            "coverage": cov["score"], "source": src, "proposals": rows}
    (app_dir(job) / "bullets.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    n = sum(x["changed"] for x in rows)
    db.add_event(job["id"], "bullets", f"{n} of {len(rows)} bullets rewritten, {sum(bool(x['flags']) for x in rows)} flagged")
    return data


def _accepted(rows: list[dict], accept) -> set[int]:
    """accept: 'all', 'unflagged', or ids (a list, or a string like '1,3,5')."""
    if accept == "all":
        return {r["id"] for r in rows}
    if accept == "unflagged":
        return {r["id"] for r in rows if not r["flags"]}
    ids = set()
    for x in (accept.split(",") if isinstance(accept, str) else accept or []):
        try:
            ids.add(int(str(x).strip()))
        except ValueError:
            raise SystemExit(f"accept takes all, unflagged or bullet numbers like 1,3,5 (got {str(x)[:20]!r})") from None
    if unknown := ids - {r["id"] for r in rows}:
        raise SystemExit(f"no bullet number {', '.join(map(str, sorted(unknown)))} in bullets.json")
    return ids


def apply_bullets(job, accept="unflagged", docx: bool = False) -> dict:
    """Build resume.md from bullets.json: accepted rows take the proposed text (an accepted drop removes the bullet),
    the rest keep the original; bullets follow the suggested order within each role. Saved like a tailored resume
    (previous version kept in history/), then coverage is re-scored and the change logged. docx: also write the .docx
    (it is regenerated anyway when one exists)."""
    p = app_dir(job) / "bullets.json"
    if not p.is_file():
        raise SystemExit(f"no bullet proposals for job #{job['id']} yet: lodestar resume tailor {job['id']} --bullets")
    data = json.loads(p.read_text(encoding="utf-8"))
    rows, lines = data["proposals"], data["source"].splitlines()
    group = {b["line"]: b["group"] for b in _bullets(data["source"])}  # recomputed: the source text is the truth
    if {r["line"] for r in rows} - group.keys():
        raise SystemExit("bullets.json does not match its source text: run the bullet tailoring again")
    ids = _accepted(rows, accept)
    groups: dict[int, list[dict]] = {}
    for r in rows:  # rows are saved in the suggested order; each group (one role) keeps its own line slots
        groups.setdefault(group[r["line"]], []).append(r)
    gone = set()
    for g in groups.values():
        texts = [t for t in (r["proposed"] if r["id"] in ids else r["original"] for r in g) if t]
        for i, n in enumerate(sorted(r["line"] for r in g)):
            if i < len(texts):
                m = BULLET_RE.match(lines[n])
                lines[n] = (m[1] if m else "- ") + texts[i]
            else:
                gone.add(n)
    text = _employer_copy("\n".join(ln for i, ln in enumerate(lines) if i not in gone))
    took = sorted(r["id"] for r in rows if r["id"] in ids and r["changed"])
    before = coverage(job, save=False)["score"]
    out, after = _save_resume(job, text, before, f"bullets: {len(took)} of {sum(r['changed'] for r in rows)} rewrites accepted")
    for r in rows:
        r["accepted"] = r["id"] in ids
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if docx or out.with_suffix(".docx").is_file():
        export_docx(out)
    return {"path": str(out), "accepted": took, "coverage": {"before": before, "after": after}}


def contact_line() -> str:
    """The profile's contact line (name | city | email | phone | links), normalised."""
    for ln in profile_text().splitlines():
        if "@" in ln and "|" in ln:
            return " | ".join(p.strip() for p in ln.split("|") if p.strip())
    return ""


def candidate_name() -> str:
    c = contact_line()
    return c.split("|")[0].strip() if c else ""


def cover_letter(job, use_council: bool = False, provider: str | None = None, tone: str = "confident, warm, specific",
                 words: int = 300) -> Path:
    """A complete, send-ready letter: contact block, date, addressee, greeting, 3-4 paragraphs, sign-off.
    Uses the tailored resume, the gap check and the research pack when they exist."""
    from .drafts import leaks, screen

    d = app_dir(job)
    from .extras import research_for_prompts

    research = research_for_prompts(job)  # never a line the research marked (unverified)
    gapj = json.loads((d / "gap.json").read_text(encoding="utf-8")) if (d / "gap.json").is_file() else {}
    # the gap check is a private judgement (it weighs pay against the floor): only its items that name no floor go in
    gapj = {k: [x for x in v if not leaks(str(x))] if isinstance(v := gapj.get(k), list) else (None if leaks(str(v or "")) else v)
            for k in ("missing_keywords", "weak_areas")}
    addressee = job["contact_name"] or "Hiring Manager"
    prompt = f"""Write the BODY of a cover letter (no header, no greeting line, no sign-off; those are added by the program)
for {job['title']} at {job['company']}, addressed to {addressee}. {words} words maximum, 3-4 paragraphs, tone: {tone}.
Paragraph 1: a specific hook about this company or role (use the research notes if given), and the one-line reason the
candidate fits. Paragraphs 2-3: two or three concrete achievements that map to the posting's stated needs, with numbers
from the resume only. Final paragraph: what the candidate wants next and a clear, low-friction ask.
Never invent facts. No cliches ("I am writing to apply", "team player", "passionate", "fast-paced"). Plain text.

JOB DESCRIPTION:
{_jd(job)}

GAP CHECK (address the weak spots gracefully, do not list them): {json.dumps(gapj)}

RESEARCH NOTES:
{research or '(none)'}

CANDIDATE (tailored resume if available, else master profile):
{_current_resume(job)}"""
    body = (ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)).strip()
    out = write_doc(d / "cover_letter.md", screen({"body": letter(job, body)})["body"])
    db.add_event(job["id"], "cover_letter", str(out))
    return out


def letter(job, body: str) -> str:
    """A letter body wrapped in the contact block, date, addressee, greeting and sign-off (cover_letter, drafts)."""
    from datetime import datetime

    addressee = job["contact_name"] or "Hiring Manager"
    return "\n".join([contact_line(), datetime.now().strftime("%B %d, %Y"), "", addressee, job["company"], "",
                      f"Dear {addressee},", "", body.strip(), "", "Sincerely,", candidate_name()])


def adjust_text(text: str, instruction: str, kind: str = "document", provider: str | None = None) -> str:
    """Rewrite a resume / profile / letter per an instruction, keeping every fact. Nothing is saved here."""
    return ai.ask(
        f"""Revise this {kind} according to the instruction. Keep every factual claim (employers, dates, numbers, skills);
you may cut, reorder, reword, and change emphasis, length and tone. Return the complete revised {kind} only, same format.

INSTRUCTION: {instruction}

{kind.upper()}:
{text}""",
        SYSTEM,
        provider,
    )


def merge_into_profile(uploaded: str, provider: str | None = None, current: str | None = None) -> str:
    """Fold an uploaded resume into the master profile structure without losing anything from either.
    `current` is the editor text (unsaved edits included); defaults to the file on disk."""
    if not current:
        current = PROFILE.read_text(encoding="utf-8-sig") if PROFILE.is_file() else PROFILE_TEMPLATE
    return ai.ask(
        f"""Merge the UPLOADED RESUME into the MASTER PROFILE below and return the complete merged profile in Markdown using
exactly the master profile's section structure (Contact, Summary, Skills, Experience, Projects, Education,
Certifications, Preferences). Keep every fact from both; where both describe the same job, keep the richer bullets.
Keep the template's placeholder lines only where no real content exists. Never invent facts.

MASTER PROFILE:
{current}

UPLOADED RESUME:
{uploaded[:20000]}""",
        SYSTEM,
        provider,
        max_tokens=8000,  # the reply is the whole profile; ai.chat raises rather than return a cut-off one
    )


SALARY_RE = re.compile(r"[$€£]\s?\d{2,3}(?:,\d{3})?\s?[kK]?(?:\s?(?:-|–|to)\s?[$€£]?\s?\d{2,3}(?:,\d{3})?\s?[kK]?)?")


# the line saved listings carry (web_monitor.jd_with_salary): job APIs often give bare numbers, e.g. '120000-160000'
SALARY_LINE_RE = re.compile(r"^Salary \(from [^)\n]*\):[ \t]*(\S[^\n]*)", re.M)


def salary_mentions(text: str) -> list[str]:
    """Pay figures stated in a posting, e.g. '$140,000 - $170,000' or '€80k'. Real data beats an AI guess."""
    seen: list[str] = []
    for m in SALARY_LINE_RE.findall(text or "") + SALARY_RE.findall(text or ""):
        m = " ".join(m.split())
        if m not in seen and any(ch.isdigit() for ch in m):
            seen.append(m)
    return seen[:4]


_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}
_PERIOD = re.compile(r"(?:\bper[\s-]*|/\s*|\ban?\s+)(?:month|mo|week|wk|day|hour|hr)\b|\b(?:monthly|weekly|daily|hourly)\b", re.I)
_YEARLY = re.compile(r"\b(?:year|yr|annual|annually|annum|p\.?a)\b", re.I)


def parse_salary(text: str) -> dict:
    """The first stated annual pay figure as {salary_min, salary_max, currency}; {} when there is none. Figures under
    1,000 (hourly rates, '50-70') and figures stated per month / week / day / hour ('EUR 5000-7000 (per-month-salary)',
    '€5K – €7K per month') are not annual pay and are skipped rather than guessed at."""
    for m in salary_mentions(text):
        i = (text or "").find(m)
        w = m + (text[i + len(m): i + len(m) + 25] if i >= 0 else "")  # the figure and what follows it
        p, y = _PERIOD.search(w), _YEARLY.search(w)
        if p and not (y and y.start() < p.start()):
            continue
        pairs = [(float(n.replace(",", "")), k) for n, k in re.findall(r"(\d[\d,]*(?:\.\d+)?)\s?([kK])?", m)]
        k_any = any(k for _, k in pairs)  # '$120-150k': the k covers both ends of the range
        nums = [int(n * (1000 if k or (k_any and n < 1000) else 1)) for n, k in pairs]
        nums = [n for n in nums if 1000 <= n <= 10_000_000][:2]
        if nums:  # a code just around the figure: 'CAD $90k', '90-110k EUR'
            ctx = text[max(0, i - 5): i + len(m) + 5] if i >= 0 else m
            code = re.search(r"\b(USD|EUR|GBP|CAD|AUD|CHF|INR|SEK|NOK|DKK|PLN)\b", ctx)
            cur = code.group(1) if code else next((c for s, c in _CURRENCY.items() if s in m), None)  # 'CAD $90k' is CAD
            return {"salary_min": min(nums), "salary_max": max(nums), "currency": cur}
    return {}


def gap(job, provider: str | None = None) -> dict:
    """Keyword coverage first (deterministic, saved even if the AI part fails or no provider is set), then the AI's
    verdict, weak areas and suggestions, which see the missing-keyword table."""
    from . import comp, paydata
    from .profile import preferences_text

    cov = coverage(job)
    sal = salary_mentions(_jd(job))
    market = comp.lookup(job["title"], _jd(job))
    missing = [k for k in cov["keywords"] if not k["matched"] and not k["skipped"]]
    data = {**_gap_keywords(cov), "salary_in_posting": sal, "market_range": market}
    if provider or ai.available():  # an AI failure raises (SystemExit for "no key" / "model rejected"); coverage is kept
        table = "\n".join(f"- {k['term']} ({k['kind']}, {k['jd_count']}x in the posting)" for k in missing[:40]) or "- none"
        prompt = f"""Judge the candidate against the job description the way a hiring manager would.
Keyword coverage was already computed deterministically: {cov['score']}/100 of the posting's keywords appear in the resume.
Missing keywords (the candidate may genuinely lack some; never suggest claiming a skill the resume does not support):
{table}
Pay stated in the posting: {', '.join(sal) or 'none stated'}. Your recorded market range for this title: {f"{market['low']}-{market['high']} ({market['city']})" if market else 'none recorded'}.
{paydata.line(job)}
Weigh both against the candidate's salary floor in Preferences.
Return JSON: {{"weak_areas": [...], "suggestions": ["concrete resume edits"], "red_flags": [...],
"verdict": "apply|stretch|skip", "why": "one line"}}

JOB DESCRIPTION:
{_jd(job)}

CANDIDATE RESUME:
{_current_resume(job)}

CANDIDATE PREFERENCES (private, never quoted to the employer):
{preferences_text()}"""
        judged = ai.ask_json(prompt, SYSTEM, provider)
        if isinstance(judged, dict):
            data |= {k: judged[k] for k in ("weak_areas", "suggestions", "red_flags", "verdict", "why") if k in judged}
    else:
        data["note"] = "no AI provider configured: keyword coverage only. Add a key for the verdict and suggestions."
    (app_dir(job) / "gap.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    db.add_event(job["id"], "gap", f"coverage={cov['score']} verdict={data.get('verdict', '-')}")
    return data


def review(text: str, provider: str | None = None) -> str:
    """AI critique, given the deterministic lint results so it builds on them instead of rediscovering them."""
    from .lint import lint

    found = lint(text)["issues"]
    checks = "\n".join(f"- line {i['line'] or '-'} [{i['severity']}] {i['text']}" for i in found[:30]) or "- none"
    return ai.ask(
        "Critique this resume ruthlessly as a recruiter who sees 300 a day. Give: overall score /10, the top 5 fixes "
        "in priority order, ATS/formatting problems, and rewrite the 3 weakest bullets.\n\n"
        "AUTOMATED CHECKS ALREADY RUN (line numbers refer to the resume below; build on them rather than repeating them):\n"
        f"{checks}\n\nRESUME:\n{text}",
        SYSTEM,
        provider,
    )


def _plain(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s).replace("`", "")


# Single column, body text only (no tables, text boxes, headers or footers), body >= 10 pt: each passes lint.audit.
STYLES = {
    "classic": {"font": "Calibri", "size": 10.5},
    "modern": {"font": "Arial", "size": 10.5, "heading_font": "Arial", "color": (0x1F, 0x4E, 0x79), "margin": 0.8},
    "compact": {"font": "Calibri", "size": 10, "margin": 0.6, "tight": True, "heading_sizes": (15, 12, 10.5)},
}


def _style(name: str | dict | None) -> dict:
    """A preset by name; no name: your saved studio look (pref resume_look) when there is one, else the resume_style
    preset. A style dict is used as given."""
    from . import settings

    if isinstance(name, dict):
        return name
    if not name and (look := settings.pref("resume_look")):
        from .render import as_preset

        return as_preset(look)
    return STYLES.get(name or settings.pref("resume_style"), STYLES["classic"])


def _blocks(md: str):
    """Markdown lines as (kind, heading level, text): kind is h, li or p. The .docx and the HTML read the same blocks."""
    for line in md.lstrip("﻿").splitlines():  # a BOM some editors write must not hide the name heading
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        if s.startswith("#"):
            yield "h", min(len(s) - len(s.lstrip("#")), 3), _plain(s.lstrip("#").strip())
        elif s.startswith(("- ", "* ")):
            yield "li", 0, _plain(s[2:])
        else:
            yield "p", 0, _plain(s)


def _font(style, name: str) -> None:
    """Set a style's font and drop the theme-font attributes that would otherwise win over it in Word."""
    from docx.oxml.ns import qn

    style.font.name = name
    rf = style.element.rPr.rFonts
    for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rf.attrib.pop(qn(a), None)


def _apply_style(doc, s: dict) -> None:
    from docx.shared import Inches, Pt, RGBColor

    normal = doc.styles["Normal"]
    _font(normal, s["font"])
    normal.font.size = Pt(s["size"])
    if s.get("tight"):
        normal.paragraph_format.space_after = Pt(1)
    for i in (1, 2, 3):
        h = doc.styles[f"Heading {i}"]
        if s.get("heading_font"):
            _font(h, s["heading_font"])
        if s.get("color"):
            h.font.color.rgb = RGBColor(*s["color"])
        if s.get("heading_sizes"):
            h.font.size = Pt(s["heading_sizes"][i - 1])
        if s.get("tight"):
            h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(6), Pt(1)
    if s.get("margin"):
        for sec in doc.sections:
            sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(s["margin"])


def export_docx(md_path: str | Path, style: str | dict | None = None) -> Path:
    """Markdown -> .docx (headings, bullets, paragraphs) in the chosen style (default: the resume_style preference)."""
    from docx import Document

    if not Path(md_path).is_file():
        raise SystemExit(f"no {Path(md_path).name} yet: tailor a resume first")
    template = PROFILE.with_name("template.docx")  # drop your own styled .docx next to profile.md to use its styles
    doc = Document(str(template)) if template.is_file() else Document()
    if not template.is_file():
        _apply_style(doc, _style(style))
    for kind, level, text in _blocks(Path(md_path).read_text(encoding="utf-8-sig")):
        if kind == "h":
            doc.add_heading(text, level=level)
        else:
            doc.add_paragraph(text, style="List Bullet" if kind == "li" else None)
    out = Path(md_path).with_suffix(".docx")
    doc.save(out)
    return out


def export_html(md_path: str | Path, style: str | dict | None = None, printable: bool = True) -> Path:
    """Markdown -> a plain single-column HTML page with print CSS. printable: a Print button and an auto print() for the
    last-resort fallback (opened in your browser); the headless PDF engine gets the page without any script. Ligatures
    are off (Chromium otherwise writes 'ﬂ' into the PDF's text layer, which parsers mis-read)."""
    from html import escape

    s, body, in_list = _style(style), [], False
    title = "Resume"
    for kind, level, text in _blocks(Path(md_path).read_text(encoding="utf-8-sig")):
        if in_list != (kind == "li"):
            body.append("<ul>" if kind == "li" else "</ul>")
            in_list = kind == "li"
        if kind == "h" and level == 1 and title == "Resume":
            title = text
        body.append(f"<h{level}>{escape(text)}</h{level}>" if kind == "h" else f"<{kind}>{escape(text)}</{kind}>")
    body += ["</ul>"] if in_list else []
    color = "#%02x%02x%02x" % s.get("color", (0, 0, 0))
    css = (f"body{{font-family:{s['font']},Arial,sans-serif;font-size:{s['size']}pt;line-height:1.3;max-width:7.5in;margin:24px auto;color:#000}}"
           f"h1,h2,h3{{color:{color};margin:{'6px 0 1px' if s.get('tight') else '12px 0 4px'}}}h1{{font-size:1.8em}}h2{{font-size:1.25em;"
           f"border-bottom:1px solid #999}}h3{{font-size:1.05em}}p,li{{margin:{'1px' if s.get('tight') else '3px'} 0}}ul{{padding-left:18px}}"
           f"body{{font-variant-ligatures:none}}@page{{size:{s.get('paper', 'letter')};margin:{s.get('margin', 0.75)}in}}"
           "@media print{.noprint{display:none}body{margin:0;max-width:none}}")
    button = ("<p class=\"noprint\"><button onclick=\"print()\">Print / Save as PDF</button> Choose 'Save as PDF' as the "
              "printer.</p>\n") if printable else ""
    script = "\n<script>addEventListener('load',()=>setTimeout(print,400))</script>" if printable else ""
    page = (f"<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{escape(title)}</title><style>{css}</style></head>"
            f"<body>{button}" + "\n".join(body) + f"{script}</body></html>\n")
    out = Path(md_path).with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    return out


# Word over COM; the paths arrive in environment variables, never spliced into the script. 17 = wdFormatPDF.
_WORD_PS = r"""$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try { $d = $w.Documents.Open($env:LS_IN, $false, $true); $d.SaveAs2($env:LS_OUT, 17); $d.Close($false) } finally { $w.Quit() }"""


def _word() -> bool:
    """Microsoft Word is registered for COM automation (Windows only)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"))
        return True
    except OSError:
        return False


def _soffice() -> str | None:
    """LibreOffice on PATH, or in its default Windows install folder."""
    win = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    return shutil.which("soffice") or shutil.which("libreoffice") or (str(win) if sys.platform.startswith("win") and win.is_file() else None)


BROWSERS = {  # headless Chromium engines, first found wins (LODESTAR_BROWSER overrides)
    "win": [(r"Microsoft\Edge\Application\msedge.exe", "edge"), (r"Google\Chrome\Application\chrome.exe", "chrome"),
            (r"Chromium\Application\chrome.exe", "chromium")],
    "darwin": [("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "edge"),
               ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
               ("/Applications/Chromium.app/Contents/MacOS/Chromium", "chromium")],
}


def _browser() -> str | None:
    """A headless-capable Chromium (Edge, Chrome, Chromium): LODESTAR_BROWSER, then the usual install folders
    (Program Files, Program Files (x86), per-user LOCALAPPDATA on Windows; /Applications on macOS), then PATH."""
    from .config import setting

    if (own := str(setting("LODESTAR_BROWSER") or "").strip()) and Path(own).is_file():
        return own
    if sys.platform.startswith("win"):
        roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
        for rel, _ in BROWSERS["win"]:
            for root in filter(None, roots):
                if (p := Path(root) / rel).is_file():
                    return str(p)
    for path, _ in BROWSERS.get(sys.platform, []):
        if Path(path).is_file():
            return path
    for name in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return None


def engine_name(path: str | None = None) -> str:
    """edge / chrome / chromium for a browser path; word / libreoffice / '' when only those (or nothing) exist."""
    if path := path or _browser():
        low = Path(path).name.lower()
        return "edge" if "edge" in low else "chromium" if "chromium" in low else "chrome"
    return "word" if _word() else "libreoffice" if _soffice() else ""


class NoEngine(RuntimeError):
    """No headless browser, or it wrote no PDF; str() says what was tried."""


def pdf_from_html(html: Path, pdf: Path, browser: str | None = None) -> dict:
    """Print a page to PDF with headless Edge / Chrome / Chromium. The browser prints into a fresh temp folder (with its
    own throwaway profile), and the result is moved onto `pdf` only when it is a real PDF: the exit code is never
    trusted (Edge exits 0 when it cannot write a locked target). A locked target raises SystemExit 'close it'.
    -> {path, method, tried}; raises NoEngine when there is no browser or it wrote nothing."""
    import tempfile

    exe = browser or _browser()
    if not exe:
        raise NoEngine("no Edge, Chrome or Chromium found")
    tmp = tempfile.mkdtemp(prefix="lodestar-pdf-")
    try:
        return _print_pdf(exe, Path(tmp), Path(html), pdf)
    finally:  # the browser's helper processes hold the profile for a moment after it exits: retry, never leave it
        import time

        for _ in range(50):
            shutil.rmtree(tmp, ignore_errors=True)
            if not os.path.exists(tmp):
                break
            time.sleep(0.1)


def _print_pdf(exe: str, tmp: Path, html: Path, pdf: Path) -> dict:
    from .updater import _proc

    method = engine_name(exe)
    out = tmp / "out.pdf"
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", f"--user-data-dir={tmp / 'profile'}", f"--print-to-pdf={out}", html.resolve().as_uri()]
    try:  # ponytail: 60 s like Word's limit; a timed-out browser is killed with its whole process tree
        code, _, err = _proc(cmd, tmp, 60)
    except (OSError, SystemExit) as e:
        raise NoEngine(f"{method}: {e}") from None
    data = out.read_bytes() if out.is_file() else b""
    if not data.startswith(b"%PDF") or len(data) < 1024:
        raise NoEngine(f"{method}: no PDF written (exit {code}) {err.strip()[:160]}".strip())
    part = pdf.with_name(pdf.name + ".tmp")
    part.write_bytes(data)
    try:
        os.replace(part, pdf)
    except PermissionError:
        part.unlink(missing_ok=True)
        raise SystemExit(f"{pdf.name} is open in another program: close it, then export again") from None
    return {"path": str(pdf), "method": method, "tried": [f"{method}: exit {code}"]}


def page_count(pdf: Path) -> int | None:
    """Pages of a PDF by the same regex lint.audit uses (no pypdf needed); None without a file."""
    try:
        return max(1, len(re.findall(rb"/Type\s*/Page(?!s)", Path(pdf).read_bytes())))
    except OSError:
        return None


def office_pdf(docx: Path, pdf: Path, tried: list) -> dict | None:
    """A .docx -> PDF with Microsoft Word (COM) or LibreOffice when either is installed; failures go into `tried`."""
    import subprocess

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if _word():
        env = {**os.environ, "LS_IN": str(docx.resolve()), "LS_OUT": str(pdf.resolve())}
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WORD_PS],
                               env=env, capture_output=True, text=True, timeout=120, creationflags=flags)
            if pdf.is_file():
                return {"path": str(pdf), "method": "word", "note": "converted with Microsoft Word", "tried": tried}
            tried.append(f"Microsoft Word: {(r.stderr or r.stdout or 'no PDF written').strip()[:200]}")
        except (OSError, subprocess.SubprocessError) as e:  # ponytail: a timed-out Word may linger; Task Manager ends it
            tried.append(f"Microsoft Word: {e}")
    if so := _soffice():
        try:
            r = subprocess.run([so, "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent.resolve()), str(docx.resolve())],
                               capture_output=True, text=True, timeout=120, creationflags=flags)
            if pdf.is_file():
                return {"path": str(pdf), "method": "libreoffice", "note": "converted with LibreOffice", "tried": tried}
            tried.append(f"LibreOffice: {(r.stderr or r.stdout or 'no PDF written').strip()[:200]}")
        except (OSError, subprocess.SubprocessError) as e:
            tried.append(f"LibreOffice: {e}")
    return None


def export_pdf(md_path: str | Path, style: str | dict | None = None, open_html: bool = True) -> dict:
    """Markdown -> PDF with what this computer has: headless Edge / Chrome / Chromium on the HTML page (every Windows 11
    has Edge), else Microsoft Word (COM) or LibreOffice on the .docx, else an HTML print page opened in the system
    browser (print it to PDF there). Returns {path, method, note, tried}."""
    md = Path(md_path)
    if not md.is_file():
        raise SystemExit(f"no {md.name} yet: tailor a resume first")
    docx, pdf, tried = export_docx(md, style), md.with_suffix(".pdf"), list[str]()
    try:
        pdf.unlink(missing_ok=True)  # a stale file must not pass for a fresh conversion
    except OSError:
        raise SystemExit(f"{pdf.name} is open in another program: close it and export again") from None
    if _browser():
        page = export_html(md, style, printable=False)  # no print script: the browser prints it itself
        try:
            r = pdf_from_html(page, pdf)
            page.unlink(missing_ok=True)
            return r | {"note": f"printed with {'Microsoft Edge' if r['method'] == 'edge' else r['method'].title()} "
                                "(headless)", "tried": tried}
        except NoEngine as e:
            tried.append(str(e))
    if r := office_pdf(docx, pdf, tried):
        return r
    html = export_html(md, style)
    if open_html:
        import webbrowser

        webbrowser.open(html.as_uri())  # the system browser, also from the desktop window: its print dialog saves PDFs
    return {"path": str(html), "method": "html", "tried": tried,
            "note": "no PDF engine found (Edge, Chrome, Word or LibreOffice): opened a print page in your browser; choose "
                    "'Save as PDF' as the printer"}
