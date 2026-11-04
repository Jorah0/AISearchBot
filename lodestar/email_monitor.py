"""IMAP inbox monitor: finds hiring-related mail, classifies it with AI, updates the tracker, alerts you.

Gmail: enable IMAP and create an App Password (Google Account -> Security -> App passwords), then
    lodestar vault set IMAP_USER   (your address)
    lodestar vault set IMAP_PASS   (the app password)
Other providers: also set IMAP_HOST (default imap.gmail.com).
"""
import email
import imaplib
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr

from . import ai, approvals, db, settings
from .config import setting
from .util import notify, strip_html

NOREPLY = re.compile(r"no-?reply|donotreply|do-?not-?reply|notifications?@|mailer-daemon|jobs-noreply", re.I)

HINTS = (
    "interview", "application", "applied", "position", "role", "recruit", "candidate", "offer", "opportunity",
    "hiring", "talent", "unfortunately", "next steps", "assessment", "screening", "phone screen", "thank you for applying",
    "move forward", "not selected", "other candidates",
)
CATEGORIES = ("interview", "rejection", "offer", "recruiter_outreach", "application_received", "assessment", "other")
STATUS_FOR = {"interview": "interview", "rejection": "rejected", "offer": "offer", "assessment": "screening", "application_received": "applied"}


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[1].lower() if "@" in addr else ""


def _aligned(d: str, dom: str) -> bool:
    return bool(d) and (d == dom or dom.endswith("." + d))


def mail_authenticated(auth_headers: list[str], sender_email: str) -> bool:
    """True only when the receiving MTA's own (top-most) Authentication-Results header carries a passing DMARC or DKIM
    result whose domain aligns with the From address. Headers further down can be forged by the sender."""
    if not auth_headers or "@" not in sender_email:
        return False
    top = " ".join(str(auth_headers[0]).split()).lower()
    dom = _domain(sender_email)
    m = re.search(r"dmarc=pass[^;]*header[.]from=([a-z0-9.-]+)", top)
    if m and _aligned(m.group(1), dom):
        return True
    m = re.search(r"dkim=pass[^;]*header[.]d=([a-z0-9.-]+)", top)
    return bool(m and _aligned(m.group(1), dom))


def _hdr(msg, name: str) -> str:
    try:
        return str(make_header(decode_header(msg.get(name, "") or "")))
    except Exception:
        return msg.get(name, "") or ""


def _body(msg) -> str:
    html = ""
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        if p.get_content_disposition() == "attachment":
            continue
        ct = p.get_content_type()
        payload = p.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(p.get_content_charset() or "utf-8", "replace")
        if ct == "text/plain":
            return text
        if ct == "text/html" and not html:
            html = text
    return strip_html(html)


def looks_relevant(subject: str, sender: str, body: str) -> bool:
    blob = f"{subject} {body[:2000]}".lower()
    return any(h in blob for h in HINTS) or db.find_job_by_company(sender) is not None


def classify(subject: str, sender: str, body: str, provider: str | None = None) -> dict:
    tracked = ", ".join(f"{j['company']} ({j['title']})" for j in db.list_jobs()[:40])
    return ai.ask_json(
        f"""Classify this email for a job seeker. Categories: {', '.join(CATEGORIES)}.
Use "other" for newsletters, job-board digests, marketing, and anything not about a specific application or recruiter contact.
Known tracked applications: {tracked or 'none'}
Return JSON: {{"category": "...", "company": "...", "title": "...", "summary": "one line",
"action": "what the candidate should do next, or none", "deadline": "YYYY-MM-DD or null"}}

FROM: {sender}
SUBJECT: {subject}
BODY:
{body[:4000]}""",
        provider=provider,
    )


def check(days: int = 3, limit: int = 100, dry: bool = False, provider: str | None = None) -> list[dict]:
    if not settings.enabled("email_classify"):
        raise SystemExit("tool email_classify is off (lodestar tools enable email_classify)")
    host, user, pw = setting("IMAP_HOST", "imap.gmail.com"), setting("IMAP_USER"), setting("IMAP_PASS")
    if not (user and pw):
        raise SystemExit("Set IMAP_USER and IMAP_PASS (Gmail: App Password). e.g.  lodestar vault set IMAP_PASS")
    box = imaplib.IMAP4_SSL(host)
    box.login(user, pw)
    box.select("INBOX", readonly=True)
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, data = box.uid("search", None, f"(SINCE {since})")  # type: ignore[arg-type]
    uids = data[0].split()[-limit:]
    found = []
    try:
        for uid in reversed(uids):
            key = f"email:{user}:{uid.decode()}"
            if db.seen(key):
                continue
            ok = True
            try:  # one bad message (odd MIME, malformed model reply, vanished job) must not stop the scan
                _, raw = box.uid("fetch", uid, "(RFC822)")
                msg = email.message_from_bytes(raw[0][1])
                subject, sender, body = _hdr(msg, "Subject"), _hdr(msg, "From"), _body(msg)
                if looks_relevant(subject, sender, body):
                    try:
                        info = classify(subject, sender, body, provider)
                        if not isinstance(info, dict) or not isinstance(info.get("category"), str):
                            raise ValueError(f"unexpected classifier reply: {str(info)[:120]}")
                    except Exception as e:  # provider outage: leave the message unseen so the next run retries it
                        ok = False
                        info = {"category": "other", "summary": f"classify failed: {e}", "company": "", "title": ""}
                        print(f"  classify failed for '{subject[:50]}': {e} (will retry)")
                    name, addr = parseaddr(sender)
                    info |= {"subject": subject, "from": sender, "date": _hdr(msg, "Date"),
                             "message_id": _hdr(msg, "Message-ID"), "sender_email": addr, "sender_name": name,
                             "body": body[:3500],
                             "dkim_pass": mail_authenticated(msg.get_all("Authentication-Results") or [], addr)}
                    if info.get("category") != "other":
                        _apply(info, dry)
                        found.append(info)
            except Exception as e:
                ok = False
                print(f"  message {uid.decode()} skipped: {e} (will retry)")
            if not dry and ok:
                db.mark_seen(key)
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return found


def _apply(info: dict, dry: bool) -> None:
    job = db.find_job_by_company(info.get("company") or "")
    if not job and info.get("sender_email"):  # fall back to the sender's domain, never the free-text From line
        job = db.find_job_by_company(info["sender_email"].split("@")[-1].split(".")[0])
    action = info.get("action")
    line = f"EMAIL {info['category'].upper()}: {info.get('company') or info['from']} - {info.get('summary')}"
    if action and str(action).lower() != "none":
        line += f" | ACTION: {action}"
    notify(line)
    if dry:
        return
    new = STATUS_FOR.get(info["category"])
    sender_email = info.get("sender_email") or ""
    human = bool(sender_email) and not NOREPLY.search(sender_email)
    known = (job["contact_email"] if job else "") or ""
    # trusted = passes DMARC/DKIM alignment AND (no stored contact yet, or same domain as the stored contact)
    info["trusted"] = bool(info.get("dkim_pass")) and (not known or _domain(known) == _domain(sender_email))
    if job:
        if human and not job["contact_email"]:
            db.update_job(job["id"], contact_email=sender_email, contact_name=info.get("sender_name") or "")
            job = db.get_job(job["id"])
        if new and db.STATUSES.index(new) > db.STATUSES.index(job["status"]):
            approvals.propose("email_classify", "set_status",
                              {"job_id": job["id"], "status": new, "note": f"(email: {info['subject'][:60]})"},
                              f"move #{job['id']} {job['company']} to {new} ({info['category']} email)", job["id"],
                              force_pending=not info.get("trusted", False))  # unauthenticated mail never moves a job unreviewed
        else:
            db.add_event(job["id"], "email", f"{info['category']}: {info['subject'][:80]}")
        if info["category"] == "interview" and info.get("deadline") and settings.enabled("calendar"):
            try:  # calendar file + prep reminder; a bad date must not break the scan
                from .extras import ics, parse_when

                notify(f"CALENDAR: wrote {ics(job, parse_when(str(info['deadline'])))}")
            except Exception as e:
                db.add_event(job["id"], "calendar", f"could not parse date {info['deadline']!r}: {e}")
    elif info["category"] in ("recruiter_outreach", "interview", "offer") and info.get("company"):
        r = approvals.propose("email_classify", "add_job",
                              {"company": info["company"], "title": info.get("title") or "Unknown role",
                               "notes": f"from email: {info['subject']}", "contact_email": sender_email if human else "",
                               "contact_name": info.get("sender_name") or ""},
                              f"track {info['company']} - {info.get('title') or 'Unknown role'} ({info['category']} email)")
        if r.get("status") == "done":
            job = db.find_job_by_company(info["company"])
    if human and job:
        _maybe_reply(info, job)


REPLY_GUIDE = {
    "application_received": "Thank them briefly for confirming receipt, one line of enthusiasm, no questions. Three sentences max.",
    "assessment": "Confirm you will complete the assessment, ask for the deadline if it is not stated, and ask one practical question only if genuinely needed.",
    "offer": "Thank them warmly and express enthusiasm. Ask for the full written offer (base, bonus, equity, benefits, start date) and a reasonable decision timeline. Do NOT accept, decline, negotiate, or state any number.",
    "recruiter_outreach": "Express interest, ask for the role details, compensation range and process, and offer availability for a short call.",
}


def _maybe_reply(info: dict, job) -> None:
    """Draft a reply for confirmations / assessments / interview invites / offers; propose sending it."""
    cat = info["category"]
    if cat == "application_received" and not settings.pref("reply_to_confirmations"):
        return
    if cat not in (*REPLY_GUIDE, "interview"):
        return
    tool = "interview_scheduling" if cat == "interview" else "email_reply"
    if not settings.enabled(tool):
        return
    from .apply import _sig, next_slots, parse_times
    from .extras import upcoming_interviews
    from .resume import profile_text

    busy = ", ".join(f"{it['when']:%Y-%m-%d %H:%M} ({it['company']})" for it in upcoming_interviews(45)) or "none"

    guide = REPLY_GUIDE.get(cat) or (
        f"Candidate availability: {settings.pref('availability')}. If the email proposes specific times, accept the first "
        f"one inside that availability and put it in chosen_time (YYYY-MM-DD HH:MM, 24h). If none fit or none are "
        f"proposed, propose exactly three slots chosen from: {', '.join(next_slots(6))}. Confirm the format "
        f"(video/phone/onsite) and who the candidate will meet if that is unstated.")
    try:
        draft = ai.ask_json(
            f"""Draft a reply from the candidate to this email. {guide}
Tone: professional, warm, concise (under 130 words). Subject: 'Re: <original subject>'.{_sig()}
Already-booked interviews (never accept or propose a time within 90 minutes of these): {busy}
Return JSON only: {{"subject": "...", "body": "...", "chosen_time": "YYYY-MM-DD HH:MM or null"}}
Times mentioned in the email (pre-extracted): {parse_times(info.get('body', ''))}

ORIGINAL EMAIL
From: {info['from']}
Subject: {info['subject']}
{info.get('body', '')[:3000]}

CANDIDATE (for name and signature only):
{profile_text()[:800]}""")
    except (Exception, SystemExit) as e:  # missing profile / provider / bad JSON: log on the job, keep scanning
        db.add_event(job["id"], "reply", f"draft failed: {e}")
        notify(f"REPLY SKIPPED for {job['company']}: {e}")
        return
    ct = draft.get("chosen_time")
    ct = None if not ct or str(ct).strip().lower() in ("null", "none", "") else str(ct)
    payload = {"to": info["sender_email"], "subject": draft.get("subject") or f"Re: {info['subject']}",
               "body": draft.get("body", ""), "in_reply_to": info.get("message_id") or None, "job_id": job["id"],
               "chosen_time": ct}
    if cat == "offer":
        payload["new_status"] = "offer"
    who = info.get("sender_name") or info["sender_email"]
    r = approvals.propose(tool, "send_email", payload,
                          f"reply ({cat}) to {who} at {job['company']}" + (f", accepting {ct}" if ct else ""), job["id"],
                          force_pending=not info.get("trusted", False))  # a reply to unauthenticated mail always waits for you
    notify(f"REPLY {r.get('status', '?').upper()}: {payload['subject']}" + (f"  (inbox #{r['id']})" if r.get("status") == "pending" else ""))


def draft_reply(job, intent: str, provider: str | None = None) -> str:
    from .resume import profile_text

    return ai.ask(
        f"""Draft a short professional email (under 150 words) from the candidate to {job['company']} regarding the
{job['title']} application. Intent: {intent}. Match a friendly, direct tone; include a subject line.
Candidate background (for name/signature only):
{profile_text()[:1500]}""",
        provider=provider,
    )
