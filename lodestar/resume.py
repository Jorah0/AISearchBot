"""Resume / cover-letter tooling. Your master profile lives at ~/.lodestar/profile.md (you edit it once;
lodestar tailors per job). Every job gets a folder under ~/.lodestar/applications/<id>-<company>-<title>/.
"""
import json
import re
from pathlib import Path

from . import ai, db
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
    return PROFILE.read_text(encoding="utf-8")


def app_dir(job) -> Path:
    d = APPS_DIR / f"{job['id']}-{slug(job['company'])}-{slug(job['title'])}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _jd(job) -> str:
    if not job["jd"]:
        raise SystemExit(f"job #{job['id']} has no job description. Add one: lodestar jobs jd {job['id']} <url|file>")
    return job["jd"]


def _current_resume(job) -> str:
    p = app_dir(job) / "resume.md"
    return p.read_text(encoding="utf-8") if p.is_file() else profile_text()


def tailor(job, use_council: bool = False, provider: str | None = None) -> Path:
    prompt = f"""Tailor the candidate's master resume for this job. Output a complete resume in Markdown (one page where possible).
Mirror the job's vocabulary wherever the candidate genuinely has that experience, lead with the most relevant items,
cut irrelevant ones, and keep contact details exactly as given.

JOB: {job['title']} at {job['company']}
JOB DESCRIPTION:
{_jd(job)}

MASTER RESUME:
{profile_text()}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)
    out = app_dir(job) / "resume.md"
    out.write_text(text, encoding="utf-8")
    from .extras import resume_hash

    h = resume_hash(text)
    db.update_job(job["id"], resume_hash=h)
    db.add_event(job["id"], "resume", f"{out} variant={h}")
    return out


def cover_letter(job, use_council: bool = False, provider: str | None = None, tone: str = "confident, warm, specific") -> Path:
    prompt = f"""Write a cover letter (max 300 words, 3-4 short paragraphs, tone: {tone}) for {job['title']} at {job['company']}.
Open with a specific hook about the company or role, connect 2-3 concrete achievements to their stated needs,
close with a clear ask. No cliches ("I am writing to apply", "team player", "passionate"). Plain text, ready to paste.

JOB DESCRIPTION:
{_jd(job)}

CANDIDATE:
{_current_resume(job)}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)
    out = app_dir(job) / "cover_letter.md"
    out.write_text(text, encoding="utf-8")
    db.add_event(job["id"], "cover_letter", str(out))
    return out


def gap(job, provider: str | None = None) -> dict:
    prompt = f"""Compare the candidate against the job description the way an ATS and then a hiring manager would.
Return JSON: {{"match_score": 0-100, "missing_keywords": [...], "present_keywords": [...], "weak_areas": [...],
"suggestions": ["concrete resume edits"], "red_flags": [...], "verdict": "apply|stretch|skip", "why": "one line"}}

JOB DESCRIPTION:
{_jd(job)}

CANDIDATE RESUME:
{_current_resume(job)}"""
    data = ai.ask_json(prompt, SYSTEM, provider)
    (app_dir(job) / "gap.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    db.add_event(job["id"], "gap", f"score={data.get('match_score')} verdict={data.get('verdict')}")
    return data


def review(text: str, provider: str | None = None) -> str:
    return ai.ask(
        "Critique this resume ruthlessly as a recruiter who sees 300 a day. Give: overall score /10, the top 5 fixes "
        "in priority order, ATS/formatting problems, and rewrite the 3 weakest bullets.\n\n" + text,
        SYSTEM,
        provider,
    )


def _plain(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s).replace("`", "")


def export_docx(md_path: str | Path) -> Path:
    """Markdown -> .docx (headings, bullets, paragraphs). Good enough for ATS uploads."""
    from docx import Document
    from docx.shared import Pt

    template = PROFILE.with_name("template.docx")  # drop your own styled .docx next to profile.md to use its styles
    doc = Document(str(template)) if template.is_file() else Document()
    if not template.is_file():
        normal = doc.styles["Normal"]
        normal.font.name, normal.font.size = "Calibri", Pt(10.5)
    for line in Path(md_path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("```"):
            continue
        if s.startswith("#"):
            level = min(len(s) - len(s.lstrip("#")), 3)
            doc.add_heading(_plain(s.lstrip("#").strip()), level=level)
        elif s.startswith(("- ", "* ")):
            doc.add_paragraph(_plain(s[2:]), style="List Bullet")
        else:
            doc.add_paragraph(_plain(s))
    out = Path(md_path).with_suffix(".docx")
    doc.save(out)
    return out
