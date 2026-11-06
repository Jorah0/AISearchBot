"""Application-stage tools: answer bank for form questions, per-job checklist, follow-ups, thank-you notes,
offer evaluation, and listing judgement for auto-track. Anything that acts on its own goes through approvals.
"""
import json
import re
from datetime import datetime, timedelta

from . import ai, approvals, db, settings
from .resume import app_dir, candidate_text

JSON_MAIL = 'Return JSON only: {"subject": "...", "body": "..."}'


def _sig() -> str:
    s = settings.pref("signature") or settings.pref("name") or ""
    return f"\nSign off as: {s}" if s else ""


# ----------------------------------------------------------------------------- answer bank
def answer(job, question: str, provider: str | None = None) -> dict:
    """Draft a form answer from the profile + prior answers; propose saving it (tool: answers)."""
    prior = db.find_answers(question, limit=6)
    seen_q = {a["question"] for a in prior}
    prior = prior + [a for a in db.list_answers() if a["question"] not in seen_q][:10]  # the model picks what fits
    bank = "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in prior) or "(none)"
    text = ai.ask(
        f"""Answer this job-application form question for the candidate: first person, concise, honest, ready to paste.
Reuse the candidate's prior answers below when they fit (adapt wording, never contradict them). Never invent facts.
If the question asks for a number (salary, years, notice period) and the profile has no answer, say so in one line
instead of guessing.

QUESTION: {question}
JOB: {job['title']} at {job['company']}
JOB DESCRIPTION: {(job['jd'] or '')[:2500]}

PRIOR ANSWERS:
{bank}

CANDIDATE:
{candidate_text(5000, private=False)}""",
        provider=provider,
    )
    prop = approvals.propose("answers", "save_answer", {"question": question, "answer": text, "tags": job["company"]},
                             f"save answer: {question[:70]}", job["id"])
    return {"answer": text, "proposal": prop, "reused": [a["question"] for a in prior]}


# ----------------------------------------------------------------------------- checklist
def checklist(job) -> list[dict]:
    d = app_dir(job)
    # 'followup'/'thanks' events are written when the mail is sent; older databases logged them as "drafted"
    kinds = {e["kind"] for e in db.events(job["id"]) if e["detail"] != "drafted"}
    gap = json.loads((d / "gap.json").read_text(encoding="utf-8")) if (d / "gap.json").is_file() else {}
    past_apply = job["status"] in ("screening", "interview", "offer", "accepted")
    items = [
        ("Job description on file", bool(job["jd"]), f"lodestar jobs jd {job['id']} <url>"),
        ("Fit checked", "missing_keywords" in gap, f"lodestar resume gap {job['id']}"),
        (f"Verdict worth applying ({gap.get('verdict', '?')}, score {gap.get('match_score', '?')})",
         gap.get("verdict") in ("apply", "stretch"), "reconsider or move on"),
        ("Resume tailored", (d / "resume.md").is_file(), f"lodestar resume tailor {job['id']} --docx"),
        ("Cover letter", (d / "cover_letter.md").is_file(), f"lodestar resume cover {job['id']}"),
        ("Contact known", bool(job["contact_email"]), f"lodestar jobs contact {job['id']} <email>"),
        ("Applied", job["status"] != "saved", f"lodestar jobs status {job['id']} applied"),
        ("Followed up or in motion", "followup" in kinds or past_apply, f"lodestar followup {job['id']}"),
        ("Interview prep", (d / "interview_prep.md").is_file() or job["status"] not in ("interview", "offer"),
         f"lodestar interview prep {job['id']}"),
        ("Thank-you sent", "thanks" in kinds or job["status"] != "interview", f"lodestar thanks {job['id']}"),
    ]
    return [{"item": i, "done": bool(ok), "next": nxt} for i, ok, nxt in items]


# ----------------------------------------------------------------------------- follow-up / thanks / withdraw
TEMPLATES = {  # offline drafts: plain, honest, only what the tracker knows; never the profile (so never the salary floor)
    "followup": ("Following up on my {title} application",
                 "I am writing to follow up on my application for the {title} position at {company}. I am still very "
                 "interested in the role and would be grateful for any update on the next steps."),
    "thanks": ("Thank you for the {title} interview",
               "Thank you for taking the time to speak with me about the {title} position at {company}.{notes} I enjoyed "
               "the conversation and remain very interested in the role."),
    "withdraw": ("Withdrawing my application for {title}",
                 "Thank you for considering me for the {title} position at {company}. I have decided to withdraw my "
                 "application. I appreciate the time you spent on it and wish you the best with the search."),
}


def template_mail(kind: str, job, to: str = "", notes: str = "") -> dict:
    """{subject, body} from TEMPLATES, filled from the job and your name (signature / name pref, else the profile bank)."""
    from .profile import load

    subject, body = TEMPLATES[kind]
    name = settings.pref("signature") or settings.pref("name") or load()["contact"].get("name") or ""
    who = (to or job["contact_name"] or "").strip()
    fill = {"title": job["title"], "company": job["company"],
            "notes": f" I especially valued our conversation about {notes.strip().rstrip('.')}." if notes.strip() else ""}
    return {"subject": subject.format(**fill),
            "body": f"Hello{' ' + who if who else ''},\n\n{body.format(**fill)}\n\nBest regards,\n{name}".rstrip()}


def _offline(template: bool) -> bool:
    return template or not ai.available()  # no provider configured: the template, still proposed through the Inbox


def followup(job, provider: str | None = None, template: bool = False) -> dict:
    last = next((e for e in reversed(db.events(job["id"])) if e["kind"] == "status"), None)
    mail = template_mail("followup", job) if _offline(template) else ai.ask_json(
        f"""Write a brief, warm follow-up email (under 110 words) from the candidate about the {job['title']} application
at {job['company']} (status: {job['status']}, last update: {last['ts'][:10] if last else 'unknown'}). Reaffirm interest
with one concrete reason, ask for a status update or next step, no pressure, no cliches.{_sig()}
{JSON_MAIL}

CANDIDATE SUMMARY:
{candidate_text(1500, private=False)}""",
        provider=provider,
    )
    db.add_event(job["id"], "followup_draft", mail.get("subject", ""))
    return mail_proposal(job, mail, "followup", f"follow-up to {job['contact_name'] or job['contact_email']} at {job['company']}",
                         purpose="followup")


def thanks(job, interviewer: str = "", notes: str = "", provider: str | None = None, template: bool = False) -> dict:
    mail = template_mail("thanks", job, interviewer, notes) if _offline(template) else ai.ask_json(
        f"""Write a thank-you email (under 120 words) from the candidate to {interviewer or 'the interviewer'} after an
interview for {job['title']} at {job['company']}. Reference something specific from the conversation if given:
"{notes}". Reaffirm fit in one sentence, no flattery.{_sig()}
{JSON_MAIL}

CANDIDATE SUMMARY:
{candidate_text(1500, private=False)}""",
        provider=provider,
    )
    db.add_event(job["id"], "thanks_draft", mail.get("subject", ""))
    return mail_proposal(job, mail, "email_reply", f"thank-you note to {job['company']}", purpose="thanks")


def withdraw(job, provider: str | None = None, template: bool = False) -> dict:
    """Draft a withdrawal email; once sent from the Inbox the job moves to withdrawn. Always waits for review."""
    mail = template_mail("withdraw", job) if _offline(template) else ai.ask_json(
        f"""Write a short, gracious email (under 90 words) from the candidate withdrawing their application for
{job['title']} at {job['company']}. Thank them for their time, keep any reason brief and general, invent nothing, leave
the door open, no cliches.{_sig()}
{JSON_MAIL}

CANDIDATE SUMMARY (for the name only):
{candidate_text(800, private=False)}""",
        provider=provider,
    )
    db.add_event(job["id"], "withdraw_draft", mail.get("subject", ""))
    return mail_proposal(job, mail, "email_reply", f"withdrawal to {job['company']}", review=True, new_status="withdrawn")


def mail_proposal(job, mail: dict, tool: str, summary: str, purpose: str = "", review: bool = False,
                  new_status: str = "") -> dict:
    """Propose sending a drafted {subject, body} to the job's contact. purpose ('followup' / 'thanks') is logged as
    an event on the job only once the mail is actually sent, so the checklist reflects sends, not drafts.
    review=True: a draft the user asked for always waits in the Inbox, even when the tool is on auto.
    new_status: where the job moves once the mail is sent (forward only, see approvals._send)."""
    if not job["contact_email"]:
        return {"draft": mail, "proposal": {"status": "draft_only", "reason": "no contact email on this job"}}
    payload = {"to": job["contact_email"], "subject": mail.get("subject", ""), "body": mail.get("body", ""), "job_id": job["id"]}
    if purpose:
        payload["purpose"] = purpose
    if new_status:
        payload["new_status"] = new_status
    summary = f"{summary} -> {payload['to']}"  # the label always names the real recipient
    return {"draft": mail, "proposal": approvals.propose(tool, "send_email", payload, summary, job["id"], force_pending=review)}


# ----------------------------------------------------------------------------- offers
def offer(job, salary: str = "", bonus: str = "", equity: str = "", benefits: str = "", deadline: str = "",
          notes: str = "", provider: str | None = None):
    terms = (f"**Terms:** base: {salary or '?'} | bonus: {bonus or '?'} | equity: {equity or '?'} | "
             f"benefits: {benefits or '?'} | deadline: {deadline or '?'}")
    others = []
    for j in db.list_jobs("offer"):
        if j["id"] != job["id"]:  # each evaluated offer.md opens with its terms line, so offers can be weighed
            f = app_dir(j) / "offer.md"
            others.append(f"#{j['id']} {j['company']} - {j['title']}"
                          + (": " + f.read_text(encoding="utf-8")[:600] if f.is_file() else ""))
    text = ai.ask(
        f"""Evaluate this job offer for the candidate and produce Markdown with sections:
1. Fit against the candidate's stated preferences and salary floor (quote them).
2. What is strong, what is weak, what is missing (base, bonus, equity, benefits, remote, growth, risk).
3. Negotiation plan: realistic asks in priority order with the exact wording to use, and what to trade.
4. Questions to ask before deciding.
5. Recommendation: accept / negotiate / decline, with the reasoning.
Never invent market data; if a number is unknown say what to look up.

OFFER: {job['title']} at {job['company']}
{terms}
notes: {notes}
OTHER LIVE OFFERS:
{chr(10).join(others) or 'none'}
RECORDED MARKET RANGE: {__import__('lodestar.comp', fromlist=['lookup']).lookup(job['title'], job['jd'] or '') or 'none recorded'}

CANDIDATE PROFILE (see Preferences):
{candidate_text(6000)}""",
        provider=provider,
    )
    from .resume import write_doc

    out = write_doc(app_dir(job) / "offer.md", f"{terms}\n\n{text}")
    db.add_event(job["id"], "offer_eval", str(out))
    if job["status"] != "offer":
        db.set_status(job["id"], "offer", "offer received")
    return out


# ----------------------------------------------------------------------------- listing judgement
def auto_track(listings: list[dict], provider: str | None = None) -> list[dict]:
    """Score new listings against the profile; propose tracking those above the threshold (tool: auto_track)."""
    from .web_monitor import jd_with_salary, listing_fields, rank

    if not listings or not settings.enabled("auto_track"):
        return []
    ranked = rank(list(listings), provider)
    floor = int(settings.pref("auto_track_min_score"))
    out = []
    for j in ranked:
        if j.get("score", 0) >= floor:
            prop = approvals.propose("auto_track", "add_job",
                                     {"company": j["company"], "title": j["title"], "url": j["url"], "jd": jd_with_salary(j),
                                      "notes": f"auto-track fit {j['score']}: {j.get('why', '')} (via {j['source']})",
                                      **listing_fields(j)},
                                     f"track {j['title']} @ {j['company']} (fit {j['score']})")
            out.append({**j, "proposal": prop})
    return out


def parse_times(text: str) -> list[str]:
    """Cheap pre-pass: pull 'YYYY-MM-DD HH:MM'-like and 'Nov 12 at 2pm'-like mentions so the model sees them listed."""
    pats = [r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}",
            r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:[^\n]{0,20}?\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))?",
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:[^\n]{0,20}?\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))?"]
    found = []
    for p in pats:
        found += [m.group(0).strip() for m in re.finditer(p, text)]
    return list(dict.fromkeys(found))[:10]


def next_slots(n: int = 3) -> list[str]:
    """Fallback proposals when the model needs concrete times: next weekdays at 10:00, 14:00 local."""
    out, d = [], datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out += [f"{d:%Y-%m-%d} 10:00", f"{d:%Y-%m-%d} 14:00"]
        d += timedelta(days=1)
    return out[:n]
