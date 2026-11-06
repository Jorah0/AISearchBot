"""Interview prep pack and interactive mock interview."""
import json
from datetime import datetime
from pathlib import Path

from . import ai, db
from .resume import app_dir, candidate_text, write_doc

SYSTEM = "You are a veteran hiring manager and interview coach. Be concrete, honest, and grounded in the candidate's real history."


def _resume(job, strict: bool = True) -> str:
    p = app_dir(job) / "resume.md"
    return p.read_text(encoding="utf-8") if p.is_file() else candidate_text(strict=strict)


def _notes(job) -> str:
    """Research pack and gap check from the job's folder, when they exist. Prep and mock are read by the candidate only."""
    d, out = app_dir(job), ""
    if (d / "research.md").is_file():
        out += "\n\nCOMPANY RESEARCH:\n" + (d / "research.md").read_text(encoding="utf-8")[:2500]
    if (d / "gap.json").is_file():
        g = json.loads((d / "gap.json").read_text(encoding="utf-8"))
        out += "\n\nGAP CHECK: " + json.dumps({k: g.get(k) for k in ("missing_keywords", "weak_areas")})
    return out


def _pay(job) -> str:
    """Real pay figures only: what the posting states, your recorded market range, your Preferences (private)."""
    from . import comp
    from .profile import preferences_text
    from .resume import salary_mentions

    jd = job["jd"] or ""
    m = comp.lookup(job["title"], jd)
    market = f"{m['low']}-{m['high']} ({m['city']})" if m else "none recorded"
    return (f"PAY FIGURES: stated in the posting: {', '.join(salary_mentions(jd)) or 'none stated'}; "
            f"recorded market range: {market}.\n"
            f"CANDIDATE PREFERENCES (private, includes the salary floor):\n{preferences_text() or '(none stated)'}")


def prep(job, use_council: bool = False, provider: str | None = None) -> Path:
    prompt = f"""Prepare the candidate for an interview: {job['title']} at {job['company']}.
Produce Markdown with these sections:
1. 10 likely role-specific technical/skill questions, each with a strong model answer built from the candidate's real experience.
2. 6 behavioral questions with STAR answers drawn from the candidate's actual history.
3. The 3 toughest questions given gaps between the resume and the job description (use the gap check if given), with honest strategies.
4. 5 sharp questions to ask the interviewer that signal seniority, grounded in the company research when given.
5. A 60-second "tell me about yourself" pitch.
6. Salary negotiation notes: quote the PAY FIGURES and the salary floor below. Never invent market data; if a number is unknown, say what to look up.

JOB DESCRIPTION:
{job['jd'] or '(none on file - infer from title)'}

CANDIDATE:
{_resume(job)}

{_pay(job)}{_notes(job)}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider, max_tokens=8000)
    out = write_doc(app_dir(job) / "interview_prep.md", text)
    db.add_event(job["id"], "interview_prep", str(out))
    return out


def mock_system(job) -> str:
    return (
        SYSTEM + f" Conduct a realistic mock interview for {job['title']} at {job['company']}. Ask ONE question at a time, "
        "wait for the answer, give two lines of feedback, then ask the next. Mix technical and behavioral. When the "
        "candidate says 'done', give a scored (1-10) debrief with specific improvements.\n\n"
        f"JOB DESCRIPTION:\n{job['jd'] or '(infer from title)'}\n\nCANDIDATE:\n{_resume(job, strict=False)}{_notes(job)}"
    )


def save_mock(job, history: list[dict]) -> Path:
    """Transcript plus the scored debrief -> mock_interview.md (the previous one moves to history/), and a timeline event."""
    who = {"assistant": "Interviewer", "user": "You"}
    lines = [f"# Mock interview: {job['title']} at {job['company']}", f"_{datetime.now():%Y-%m-%d %H:%M}_", ""]
    lines += [f"**{who.get(m['role'], m['role'])}:** {m['content']}\n" for m in history]
    out = write_doc(app_dir(job) / "mock_interview.md", "\n".join(lines))
    db.add_event(job["id"], "mock_interview", f"{len(history) // 2} turns, saved {out.name}")
    return out


def mock(job, provider: str | None = None) -> None:
    system = mock_system(job)
    history = [{"role": "user", "content": "Please start the interview."}]
    print("(type 'done' to finish)\n")
    while True:
        reply = ai.chat(history, system, provider)
        history.append({"role": "assistant", "content": reply})
        print(f"\nINTERVIEWER: {reply}\n")
        if history[-2]["content"].strip().lower() == "done":
            break
        try:
            answer = input("YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        history.append({"role": "user", "content": answer or "(no answer)"})
    save_mock(job, history)
