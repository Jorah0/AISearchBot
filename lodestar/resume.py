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


def write_doc(path: Path, text: str) -> Path:
    """Write a generated per-job document. A previous version that differs (possibly hand-edited) moves to history/."""
    from datetime import datetime

    if path.is_file() and path.read_text(encoding="utf-8") != text:
        (path.parent / "history").mkdir(exist_ok=True)
        path.replace(path.parent / "history" / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    path.write_text(text, encoding="utf-8")
    return path


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
    return p.read_text(encoding="utf-8") if p.is_file() else candidate_text(private=False)


def tailor(job, use_council: bool = False, provider: str | None = None) -> Path:
    prompt = f"""Tailor the candidate's master resume for this job. Output a complete resume in Markdown (one page where possible).
Mirror the job's vocabulary wherever the candidate genuinely has that experience, lead with the most relevant items,
cut irrelevant ones, and keep contact details exactly as given.

JOB: {job['title']} at {job['company']}
JOB DESCRIPTION:
{_jd(job)}

MASTER RESUME (an "On file" section, if present, lists further true facts from the candidate's other resumes):
{candidate_text(private=False)}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)
    out = write_doc(app_dir(job) / "resume.md", text)
    from .extras import resume_hash

    h = resume_hash(text)
    db.update_job(job["id"], resume_hash=h)
    db.add_event(job["id"], "resume", f"{out} variant={h}")
    return out


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
    from datetime import datetime

    d = app_dir(job)
    research = (d / "research.md").read_text(encoding="utf-8")[:2500] if (d / "research.md").is_file() else ""
    gapj = json.loads((d / "gap.json").read_text(encoding="utf-8")) if (d / "gap.json").is_file() else {}
    addressee = job["contact_name"] or "Hiring Manager"
    prompt = f"""Write the BODY of a cover letter (no header, no greeting line, no sign-off; those are added by the program)
for {job['title']} at {job['company']}, addressed to {addressee}. {words} words maximum, 3-4 paragraphs, tone: {tone}.
Paragraph 1: a specific hook about this company or role (use the research notes if given), and the one-line reason the
candidate fits. Paragraphs 2-3: two or three concrete achievements that map to the posting's stated needs, with numbers
from the resume only. Final paragraph: what the candidate wants next and a clear, low-friction ask.
Never invent facts. No cliches ("I am writing to apply", "team player", "passionate", "fast-paced"). Plain text.

JOB DESCRIPTION:
{_jd(job)}

GAP CHECK (address the weak spots gracefully, do not list them): {json.dumps({k: gapj.get(k) for k in ('missing_keywords', 'weak_areas')})}

RESEARCH NOTES:
{research or '(none)'}

CANDIDATE (tailored resume if available, else master profile):
{_current_resume(job)}"""
    body = (ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider)).strip()
    letter = "\n".join([contact_line(), datetime.now().strftime("%B %d, %Y"), "", addressee, job["company"], "",
                        f"Dear {addressee},", "", body, "", "Sincerely,", candidate_name()])
    out = write_doc(d / "cover_letter.md", letter)
    db.add_event(job["id"], "cover_letter", str(out))
    return out


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
        current = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else PROFILE_TEMPLATE
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


def salary_mentions(text: str) -> list[str]:
    """Pay figures stated in a posting, e.g. '$140,000 - $170,000' or '€80k'. Real data beats an AI guess."""
    seen: list[str] = []
    for m in SALARY_RE.findall(text or ""):
        m = " ".join(m.split())
        if m not in seen and any(ch.isdigit() for ch in m):
            seen.append(m)
    return seen[:4]


def gap(job, provider: str | None = None) -> dict:
    from . import comp
    from .profile import preferences_text

    sal = salary_mentions(_jd(job))
    market = comp.lookup(job["title"], _jd(job))
    prompt = f"""Compare the candidate against the job description the way an ATS and then a hiring manager would.
Pay stated in the posting: {', '.join(sal) or 'none stated'}. Your recorded market range for this title: {f"{market['low']}-{market['high']} ({market['city']})" if market else 'none recorded'}.
Weigh both against the candidate's salary floor in Preferences.
Return JSON: {{"match_score": 0-100, "missing_keywords": [...], "present_keywords": [...], "weak_areas": [...],
"suggestions": ["concrete resume edits"], "red_flags": [...], "verdict": "apply|stretch|skip", "why": "one line"}}

JOB DESCRIPTION:
{_jd(job)}

CANDIDATE RESUME:
{_current_resume(job)}

CANDIDATE PREFERENCES (private, never quoted to the employer):
{preferences_text()}"""
    data = ai.ask_json(prompt, SYSTEM, provider)
    data["salary_in_posting"] = sal
    data["market_range"] = market
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
