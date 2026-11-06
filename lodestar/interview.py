"""Interview prep pack and interactive mock interview."""
from pathlib import Path

from . import ai, db
from .resume import app_dir, candidate_text

SYSTEM = "You are a veteran hiring manager and interview coach. Be concrete, honest, and grounded in the candidate's real history."


def _resume(job, strict: bool = True) -> str:
    p = app_dir(job) / "resume.md"
    return p.read_text(encoding="utf-8") if p.is_file() else candidate_text(strict=strict)


def prep(job, use_council: bool = False, provider: str | None = None) -> Path:
    prompt = f"""Prepare the candidate for an interview: {job['title']} at {job['company']}.
Produce Markdown with these sections:
1. 10 likely role-specific technical/skill questions, each with a strong model answer built from the candidate's real experience.
2. 6 behavioral questions with STAR answers drawn from the candidate's actual history.
3. The 3 toughest questions given gaps between the resume and the job description, with honest strategies.
4. 5 sharp questions to ask the interviewer that signal seniority.
5. A 60-second "tell me about yourself" pitch.
6. Salary negotiation notes for this role level.

JOB DESCRIPTION:
{job['jd'] or '(none on file - infer from title)'}

CANDIDATE:
{_resume(job)}"""
    text = ai.council(prompt, SYSTEM)["synthesis"] if use_council else ai.ask(prompt, SYSTEM, provider, max_tokens=8000)
    from .resume import write_doc

    out = write_doc(app_dir(job) / "interview_prep.md", text)
    db.add_event(job["id"], "interview_prep", str(out))
    return out


def mock_system(job) -> str:
    return (
        SYSTEM + f" Conduct a realistic mock interview for {job['title']} at {job['company']}. Ask ONE question at a time, "
        "wait for the answer, give two lines of feedback, then ask the next. Mix technical and behavioral. When the "
        "candidate says 'done', give a scored (1-10) debrief with specific improvements.\n\n"
        f"JOB DESCRIPTION:\n{job['jd'] or '(infer from title)'}\n\nCANDIDATE:\n{_resume(job, strict=False)}"
    )


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
    db.add_event(job["id"], "mock_interview", f"{len(history) // 2} turns")
