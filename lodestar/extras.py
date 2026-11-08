"""Small high-payoff extras: outreach drafts, interview .ics files, weekly digest, Obsidian tracker mirror,
resume-variant hashing, and a scheduled-task installer. One module on purpose; split when any grows real logic.
"""
import hashlib
import json
import platform
import re
import subprocess
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import ai, db
from .config import ALERTS, APPS_DIR
from .util import slug


def _job_dir(j) -> Path:
    return APPS_DIR / f"{j['id']}-{slug(j['company'])}-{slug(j['title'])}"


# ----------------------------------------------------------------------------- outreach
def outreach(job, person: str = "", channel: str = "linkedin", provider: str | None = None, to: str | None = None,
             goal: str = "a reply or a referral, not a pitch") -> dict:
    """{text} for a LinkedIn note; for email {draft, proposal}, proposed through the Inbox to `to` (default: the job's
    contact; '' = draft only)."""
    from .apply import JSON_MAIL, mail_proposal
    from .resume import candidate_text

    email = channel == "email"
    limit = f"under 120 words. {JSON_MAIL}" if email else "under 300 characters, no greeting fluff. Plain text."
    prompt = f"""Write a {channel} message from the candidate to {person or 'a hiring manager or recruiter'} at {job['company']}
about the {job['title']} role. Goal: {goal}. Mention one specific, relevant
achievement and one specific reason this company. {limit}

JOB DESCRIPTION:
{(job['jd'] or '')[:3000]}

CANDIDATE:
{candidate_text(5000, private=False)}"""
    if not email:
        return {"text": ai.ask(prompt, provider=provider)}
    # always reviewed: the note may be written for `person` while the only stored address is another contact
    return mail_proposal(job, ai.ask_json(prompt, provider=provider), "email_reply",
                         f"outreach email{' written for ' + person if person else ''} at {job['company']}", review=True, to=to)


# ----------------------------------------------------------------------------- calendar
def parse_when(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    raise SystemExit(f"could not parse date '{s}' (use YYYY-MM-DD HH:MM)")


def ics_text(s) -> str:
    """An RFC 5545 TEXT value: backslash, ';' and ',' escaped, line breaks as an escaped n, other control characters
    dropped. Company and title come from feeds and mail, so a raw newline would let them add their own events, URLs or
    alarms to the calendar file."""
    s = str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    s = re.sub(r"\r\n?|\n", r"\\n", s)
    return re.sub(r"[\x00-\x1f\x7f]", "", s)


def ics(job, when: datetime, minutes: int = 60, title: str | None = None, reminder_days: int = 2) -> Path:
    """Write an .ics with the interview and a prep reminder N days before. Double-click imports into any calendar."""
    def ev(start, mins, summary, desc):
        end = start + timedelta(minutes=mins)
        return "\n".join([
            "BEGIN:VEVENT", f"UID:{uuid.uuid4()}@lodestar", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}", f"SUMMARY:{ics_text(summary)}",
            f"DESCRIPTION:{ics_text(desc)}", "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY",
            f"DESCRIPTION:{ics_text(summary)}",
            "END:VALARM", "END:VEVENT"])

    summary = title or f"Interview: {job['company']} - {job['title']}"
    prep = (when - timedelta(days=reminder_days)).replace(hour=9, minute=0, second=0)
    body = "\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//lodestar//EN",
        ev(when, minutes, summary, f"lodestar job #{job['id']} {job['url'] or ''}".strip()),
        ev(prep, 30, f"Prep: {job['company']} interview", f"Lodestar: open job #{job['id']} > Interview prep (CLI: lodestar interview prep {job['id']})"),
        "END:VCALENDAR", ""])
    d = _job_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"interview-{when:%Y%m%d-%H%M}.ics"
    out.write_text(body, encoding="utf-8")
    db.add_event(job["id"], "calendar", str(out))
    from .interview import booked

    booked(job["id"], f"{when:%Y-%m-%d %H:%M}", str(out))  # the job's interview round at that time (new or updated)
    return out


# ----------------------------------------------------------------------------- digest
def digest_to() -> str:
    """Where digest --send goes: LODESTAR_NOTIFY_EMAIL, else your connected mailbox's address; SystemExit when neither."""
    from .config import setting

    if to := setting("LODESTAR_NOTIFY_EMAIL") or setting("IMAP_USER"):
        return to
    raise SystemExit("emailing the digest needs your own address: connect your mailbox (Setup > Connect email), "
                     "or store LODESTAR_NOTIFY_EMAIL in Setup > Vault (lodestar vault set LODESTAR_NOTIFY_EMAIL)")


def digest(days: int = 7, send: bool = False, provider: str | None = None) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [j for j in db.list_jobs() if j["updated_at"] >= cutoff]
    follow = db.needs_followup()
    alerts = [ln for ln in (ALERTS.read_text(encoding="utf-8").splitlines() if ALERTS.is_file() else [])
              if ln[1:11] >= cutoff]
    st = db.stats()
    lines = [f"# lodestar digest - last {days} days ({datetime.now():%Y-%m-%d})", "",
             f"Pipeline: {', '.join(f'{k} {v}' for k, v in st['counts'].items()) or 'empty'} | applied {st['applied_total']} | response {st['response_rate']:.0%} | interview {st['interview_rate']:.0%}",
             "", f"## Moved this week ({len(recent)})",
             *[f"- #{j['id']} {j['company']} - {j['title']}: {j['status']}" for j in recent[:20]],
             "", f"## Needs follow-up ({len(follow)})",
             *[f"- #{j['id']} {j['company']} - {j['title']} (quiet since {j['updated_at'][:10]})" for j in follow[:20]]]
    if goals := goal_progress():  # only the goals you set (pref weekly_goals)
        lines += ["", "## Weekly goals (this week so far)", *[f"- {g['label']}: {g['done']} of {g['target']}" for g in goals]]
    lines += ["", f"## Alerts ({len(alerts)})", *[f"- {a}" for a in alerts[-25:]]]
    text = "\n".join(lines)
    if ai.available():
        try:
            text += "\n\n## Coach's plan for next week\n" + ai.ask(
                "Given this job-search digest, write 5 concrete actions for next week, most impactful first, one line each.\n\n"
                + text, provider=provider)
        except (Exception, SystemExit) as e:  # the digest is still useful without the AI paragraph (rejected model: SystemExit)
            text += f"\n\n(coach unavailable: {e})"
    if send:  # straight to your own address: the full text never lands in alerts.log (and the next digest's Alerts)
        from .util import send_email

        to = digest_to()
        try:
            send_email(to, f"[lodestar] digest - last {days} days", text)
        except Exception as e:  # no mailbox, SMTP refused: say so instead of a traceback
            raise SystemExit(f"the digest was not emailed: {e}") from None
    return text


# ----------------------------------------------------------------------------- obsidian mirror of the tracker
def vault_root() -> Path:
    from .config import setting  # env, then Setup > Vault (OBSIDIAN_VAULT)

    return Path(setting("OBSIDIAN_VAULT") or (Path.home() / "Documents" / "Obsidian Vault"))


def export_obsidian(folder: str = "jobs") -> Path:
    """One note per tracked job (properties + wikilinks) plus an index table, so the search lives in your vault."""
    out = vault_root() / folder
    out.mkdir(parents=True, exist_ok=True)
    jobs = db.list_jobs()
    for j in jobs:
        name = f"{j['id']}-{slug(j['company'])}-{slug(j['title'])}"
        d = _job_dir(j)
        docs = sorted(p.name for p in d.iterdir()) if d.exists() else []
        note = "\n".join([
            # JSON strings are valid YAML: a quote or colon in a company or title cannot break the properties
            "---", f"company: {json.dumps(j['company'] or '')}", f"title: {json.dumps(j['title'] or '')}", f"status: {j['status']}",
            f"url: {json.dumps(j['url'] or '')}", f"applied: {j['applied_at'] or ''}", f"updated: {j['updated_at'][:10]}",
            f"tags: [job, {j['status']}]", f"lodestar_id: {j['id']}", "---", "",
            f"# {j['company']} - {j['title']}", "",
            f"> [!info] Status: **{j['status']}** · [[{folder}/_index|all applications]]", "",
            "## Timeline", *[f"- {e['ts']} **{e['kind']}** {e['detail'] or ''}" for e in db.events(j["id"])], "",
            "## Documents", *([f"- `{x}`" for x in docs] or ["- (none yet)"]), "",
            "## Notes", j["notes"] or "", "",
            "## Job description", (j["jd"] or "")[:4000], ""])
        (out / f"{name}.md").write_text(note, encoding="utf-8")
    keep = {f"{j['id']}-{slug(j['company'])}-{slug(j['title'])}.md" for j in jobs}
    for stale in out.glob("*.md"):  # only notes we generated (they carry lodestar_id) and only when the job is gone
        if stale.name not in keep and stale.name != "_index.md" and "lodestar_id:" in stale.read_text(encoding="utf-8", errors="replace")[:600]:
            stale.unlink()
    rows = [f"| [[{folder}/{j['id']}-{slug(j['company'])}-{slug(j['title'])}|{j['company']}]] | {j['title']} | {j['status']} | {j['updated_at'][:10]} |"
            for j in jobs]
    (out / "_index.md").write_text("\n".join(["---", "tags: [job, index]", "---", "# Applications", "",
                                              "| Company | Title | Status | Updated |", "|---|---|---|---|", *rows, ""]),
                                   encoding="utf-8")
    return out


# ----------------------------------------------------------------------------- scheduler + variants
def schedule(action: str, every: int = 30) -> str:
    import sys

    from .config import HOME

    # the interpreter running this command, wherever it lives; the PyInstaller exe takes the subcommand directly
    cmd = f'"{sys.executable}" ' + ("run --once" if getattr(sys, "frozen", False) else "-m lodestar run --once")
    if platform.system() != "Windows":
        return f"add to crontab -e:\n*/{every} * * * * {cmd} >> \"{HOME / 'cron.log'}\" 2>&1"
    if action == "install":
        r = subprocess.run(["schtasks", "/Create", "/SC", "MINUTE", "/MO", str(every), "/TN", "lodestar", "/TR", cmd, "/F"],
                           capture_output=True, text=True)
        return (r.stdout or r.stderr).strip() + f"\n(task 'lodestar' runs `{cmd}` every {every} min)"
    r = subprocess.run(["schtasks", "/Delete", "/TN", "lodestar", "/F"], capture_output=True, text=True)
    return (r.stdout or r.stderr).strip()


def resume_hash(text: str) -> str:
    """Short content hash so stats can tell which resume variant actually gets responses."""
    return hashlib.sha256(re.sub(r"\s+", " ", text).encode()).hexdigest()[:8]


# ----------------------------------------------------------------------------- company research pack
def research(job, provider: str | None = None):
    """Pull what is publicly reachable (job page, company site, a web search page) and summarize for the interview."""
    from urllib.parse import quote, urlparse

    from .resume import candidate_text
    from .util import fetch, strip_html

    sources = []
    if job["url"]:
        host = urlparse(job["url"]).netloc
        for u in (job["url"], f"https://{host}", f"https://{host}/about"):
            try:
                sources.append((u, strip_html(fetch(u))[:5000]))
            except Exception:
                pass
    try:  # Wikipedia summary: keyless, stable, and a good antidote to the search page being blocked
        import json as _json

        wiki = _json.loads(fetch(f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(job['company'])}"))
        if wiki.get("extract"):
            sources.append((wiki.get("content_urls", {}).get("desktop", {}).get("page", "wikipedia"), wiki["extract"][:3000]))
    except Exception:
        pass
    q = quote(f"{job['company']} company news engineering culture")
    try:  # ponytail: html.duckduckgo.com needs no key; if it blocks us the pack is built from the other sources
        sources.append((f"https://html.duckduckgo.com/html/?q={q}", strip_html(fetch(f"https://html.duckduckgo.com/html/?q={q}"))[:6000]))
    except Exception:
        pass
    corpus = (chr(10) * 2).join(f"SOURCE {u}" + chr(10) + t for u, t in sources) or "(nothing fetched)"
    text = ai.ask(
        f"""Build an interview research pack for {job['company']} ({job['title']}) from the sources below plus what you
reliably know. Mark anything not supported by the sources as "(unverified)". Sections: 1) what the company does and
how it makes money, 2) products and recent news, 3) team, stack and engineering culture signals, 4) likely
challenges this role solves, 5) talking points that connect the candidate to them, 6) five questions to ask,
7) things to verify before accepting. Keep it under 700 words.

SOURCES:
{corpus[:16000]}

CANDIDATE SUMMARY:
{candidate_text(1500, private=False)}""",  # research.md feeds the cover-letter prompt: no salary floor or private prefs
        provider=provider,
    )
    out = _job_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    from .resume import write_doc

    # what was read is written down, not left to the model: with nothing fetched the whole pack is unverified recall
    if not sources:
        text = (f"> **No public source could be fetched** (job page, company site, Wikipedia, web search). Everything below "
                f"is the model's own recall of {job['company']}: treat all of it as unverified.\n\n{text}")
    text = text.rstrip() + "\n\n## Sources read\n" + ("\n".join(f"- {u}" for u, _ in sources) or "- none") + "\n"
    write_doc(out / "research.md", text)
    db.add_event(job["id"], "research", f"{len(sources)} source(s)")
    return out / "research.md"


def autofill_data() -> dict:
    """Fields the autofill bookmarklet may type into application forms. Parsed from the profile contact line."""
    from .resume import profile_text

    text = profile_text()
    contact = next((ln for ln in text.splitlines() if "@" in ln and "|" in ln), "")
    parts = [p.strip() for p in contact.split("|") if p.strip()]
    # each part classified by what it is, never by position: 'email | phone | City' must not type the phone as the city
    email = next((p for p in parts if "@" in p), "")
    phone = next((p for p in parts if "@" not in p and re.fullmatch(r"\+?[\d\s().-]{7,}", p) and sum(c.isdigit() for c in p) >= 7), "")
    linkedin = next((p for p in parts if "linkedin" in p.lower()), "")
    github = next((p for p in parts if "github" in p.lower()), "")
    website = next((p for p in parts if re.match(r"(https?://|www\.)|[\w-]+(\.[\w-]+)+(/\S*)?$", p, re.I) and "@" not in p
                    and p not in (linkedin, github)), "")
    rest = [p for p in parts if p not in (email, phone, linkedin, github, website)]  # names and places
    from .profile import load as load_bank

    bank = load_bank()["contact"]  # imported resumes / LinkedIn fill whatever the master's contact line leaves out
    head = next((ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("# ")), "")
    if re.search(r"(?i)resume|r[ée]sum[ée]|\bcv\b|curriculum|profile", head):  # '# Master Resume' names nobody
        head = ""
    if len(rest) >= 2:  # the template's order: Name | City | ...
        name, location = rest[0], rest[1]
    elif rest and (head or bank["name"]) and rest[0] != (head or bank["name"]):
        name, location = "", rest[0]  # the name is in the heading or the bank, so the one left is the place
    elif rest:  # ponytail: alone and unnamed elsewhere, two or more words without a comma or digit read as a name
        one = rest[0]
        name, location = (one, "") if len(one.split()) >= 2 and not re.search(r"[,\d]", one) else ("", one)
    else:
        name, location = "", ""
    name, email, phone = name or head or bank["name"], email or bank["email"], phone or bank["phone"]
    linkedin, github, website = linkedin or bank["linkedin"], github or bank["github"], website or bank["website"]
    first, _, last = name.partition(" ")
    answers = {a["question"]: a["answer"] for a in db.list_answers(employer=True)}  # typed into employer forms
    return {"name": name, "first_name": first, "last_name": last, "email": email, "phone": phone, "linkedin": linkedin,
            "github": github, "website": website, "location": location or bank["location"], "answers": answers}


# ----------------------------------------------------------------------------- backup + export
def backup(out_dir: Path | None = None, keep: int = 7) -> Path:
    """Zip profile, tracker, settings, answers, ideas and generated documents (not snapshots/caches). Keeps the last N."""
    import zipfile

    from .config import HOME

    if int(keep) < 1:
        raise SystemExit("keep must be at least 1 (the backup just made)")
    out_dir = out_dir or HOME / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"lodestar-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"  # seconds: two backups in the same minute both stay
    import sqlite3
    import tempfile

    skip = {"backups", "snapshots", "cache", "__pycache__", "lodestar.log"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z, tempfile.TemporaryDirectory() as tmp:
        for p in HOME.rglob("*"):
            rel = p.relative_to(HOME)
            if (not p.is_file() or set(rel.parts) & skip or p.name.startswith("lodestar.log") or p.suffix in (".lock", ".tmp")
                    or p.name == ".env"):  # .env may hold keys or IMAP_PASS in clear text; secrets stay out of zips
                continue
            if p.suffix == ".db":  # SQLite online backup: a consistent snapshot even while the loop is writing
                snap = Path(tmp) / p.name
                src, dst = sqlite3.connect(p), sqlite3.connect(snap)
                try:
                    src.backup(dst)
                finally:
                    src.close()
                    dst.close()
                z.write(snap, str(rel))
            elif not p.name.endswith(("-wal", "-shm", "-journal")):
                z.write(p, str(rel))
    for old in sorted(out_dir.glob("lodestar-backup-*.zip"))[:-keep]:  # keep >= 1 (checked above): [:-0] would keep all
        old.unlink()
    return target


def csv_cell(v):
    """A text value a spreadsheet would run as a formula ('=HYPERLINK(...)' in a scraped company name or an imported
    LinkedIn position) gets a leading apostrophe; numbers and empty values pass unchanged."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_data(fmt: str = "json", out_dir: Path | None = None) -> Path:
    """Dump jobs, events, answers, ideas, pending, contacts, interview rounds, mock sessions, offers, contact
    touches and linked mail as JSON (one file) or CSV (one file per table)."""
    import csv
    import json as _json

    from .config import HOME

    tables = {"jobs": db.list_jobs(), "events": db.con().execute("SELECT * FROM events ORDER BY id").fetchall(),
              "answers": db.list_answers(), "ideas": db.list_ideas(), "pending": db.list_pending(None, 10000),
              "contacts": db.con().execute("SELECT * FROM contacts ORDER BY id").fetchall(),
              "job_contacts": db.con().execute("SELECT * FROM job_contacts ORDER BY job_id").fetchall(),
              "interviews": db.con().execute("SELECT * FROM interviews ORDER BY id").fetchall(),
              "mock_sessions": db.con().execute("SELECT * FROM mock_sessions ORDER BY id").fetchall(),
              "offers": db.con().execute("SELECT * FROM offers ORDER BY job_id").fetchall(),
              "touches": db.con().execute("SELECT * FROM touches ORDER BY day").fetchall(),
              "mail": db.con().execute("SELECT * FROM mail ORDER BY id").fetchall()}  # subjects/snippets: csv_cell
    out_dir = out_dir or HOME / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M}"
    if fmt == "json":
        target = out_dir / f"lodestar-{stamp}.json"
        target.write_text(_json.dumps({k: [dict(r) for r in v] for k, v in tables.items()}, indent=2, default=str), encoding="utf-8")
        return target
    for name, rows in tables.items():
        with (out_dir / f"{name}-{stamp}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if rows:
                w.writerow(rows[0].keys())
                w.writerows([[csv_cell(v) for v in r] for r in rows])
    return out_dir


# ----------------------------------------------------------------------------- interview reminders + packet
def upcoming_interviews(days: int = 2) -> list[dict]:
    """Interview rounds with a time in the next N days (rounds come from .ics files, interview mail and your own log;
    calendar events from before rounds existed are imported once). 'path' keys the once-only reminders and toasts: the
    .ics while the round is still at the time in its file name, else round id + time, so a rescheduled round reminds again."""
    from .interview import sync_ics

    sync_ics()
    now = datetime.now()
    # a withdrawn or rejected job's rounds are off: no Today entry, reminder, toast, clash or busy slot
    rows = db.con().execute("SELECT i.id, i.job_id, i.at, i.ics, j.company, j.title FROM interviews i JOIN jobs j ON j.id=i.job_id "
                            "WHERE length(i.at)=16 AND i.at BETWEEN ? AND ? AND j.status NOT IN ('rejected','withdrawn') "
                            "ORDER BY i.at",
                            (f"{now:%Y-%m-%d %H:%M}", f"{now + timedelta(days=days):%Y-%m-%d %H:%M}")).fetchall()
    out = []
    for r in rows:
        when = datetime.strptime(r["at"], "%Y-%m-%d %H:%M")
        key = r["ics"] if r["ics"] and f"{when:%Y%m%d-%H%M}" in r["ics"] else f"round:{r['id']}:{r['at']}"
        out.append({"job_id": r["job_id"], "company": r["company"], "title": r["title"], "when": when, "path": key})
    return out


def packet(job) -> Path:
    """One zip with everything about an application: generated documents, the posting, notes, timeline."""
    import zipfile

    from .config import HOME

    out_dir = HOME / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"packet-{job['id']}-{slug(job['company'])}-{slug(job['title'])}.zip"
    d = _job_dir(job)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        if d.exists():
            for p in d.iterdir():
                if p.is_file():
                    z.write(p, p.name)
        z.writestr("job.txt", "\n".join([f"{job['company']} - {job['title']}", f"status: {job['status']}", f"url: {job['url'] or ''}",
                                         f"contact: {job['contact_name'] or ''} {job['contact_email'] or ''}", "", "NOTES", job["notes"] or "",
                                         "", "TIMELINE", *[f"{e['ts']} {e['kind']} {e['detail'] or ''}" for e in db.events(job["id"])],
                                         "", "JOB DESCRIPTION", job["jd"] or ""]))
    db.add_event(job["id"], "packet", str(target))
    return target


# ----------------------------------------------------------------------------- resume import
def _md_line(p) -> str:
    """A .docx paragraph as a Markdown line: Title / Heading N become '#' x N, list paragraphs '- ', so the structure
    (sections, roles, bullets) survives for bullet tailoring and the profile importer."""
    t, style = p.text.strip(), (p.style.name if p.style is not None else "") or ""
    if not t:
        return ""
    if style == "Title" or (style.startswith("Heading ") and style[8:].isdigit()):
        return "#" * min(int(style[8:]) if style != "Title" else 1, 6) + " " + t
    ppr = p._p.pPr
    if style.startswith("List") or (ppr is not None and ppr.numPr is not None):
        return "- " + t.lstrip("-*•·▪◦‣● ").strip()
    return p.text


def import_document(data: bytes, filename: str) -> str:
    """Bytes of a .docx / .pdf / .md / .txt resume -> plain text. PDF needs the `pdf` extra (pypdf)."""
    import io

    ext = Path(filename).suffix.lower()
    if ext == ".docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        lines = [_md_line(p) for p in doc.paragraphs]
        for t in doc.tables:
            for row in t.rows:
                lines.append(" | ".join(c.text.strip() for c in row.cells if c.text.strip()))
        return "\n".join(ln for ln in lines if ln is not None).strip()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise SystemExit("PDF import needs pypdf: pip install pypdf  (or pip install -e .[pdf])") from None
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages).strip()
    if ext in (".md", ".txt", ".markdown", ""):
        return data.decode("utf-8", errors="replace").strip()
    raise SystemExit(f"unsupported resume format '{ext}' (use .docx, .pdf, .md or .txt)")


def conflicts(when: datetime, window_minutes: int = 90, job_id: int | None = None) -> list[dict]:
    """Existing interviews within the window of a proposed time; job_id's own rounds don't count (accepting the slot
    its invite already booked is no clash with itself)."""
    return [it for it in upcoming_interviews(60) if it["job_id"] != job_id
            and abs((it["when"] - when).total_seconds()) <= window_minutes * 60]


# ----------------------------------------------------------------------------- activity log, insights, weekly goals
ACTIVITY_COLUMNS = ("date", "activity", "employer", "position", "method", "contact", "result")
ACTIVITY_NOTE = ("Helper report built from what Lodestar recorded; check your state's requirements. It is not a claim "
                 "of compliance.")
MIN_N = 5  # fewer applications than this in a group: "not enough data yet", no rate


def _day(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(db.valid_date("date", str(d or "").strip()))


def _local(ts: str) -> date:
    """A UTC 'YYYY-MM-DD HH:MM:SS' column value (datetime('now')) as your local calendar day."""
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc).astimezone().date()


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _first_status(status: str):
    """(local day, job row) of the first time each job entered `status`, from the status events on its timeline."""
    rows = db.con().execute("SELECT j.*, MIN(e.ts) entered FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.kind='status' "
                            "AND (e.detail=? OR e.detail LIKE ?) GROUP BY e.job_id", (status, status + " %")).fetchall()
    return [(_local(r["entered"]), r) for r in rows]


def activity_log(start, end) -> list[dict]:
    """What you did from start to end (dates, inclusive; never past today), oldest first, as rows of ACTIVITY_COLUMNS
    (+ job_id). Only your own actions count: jobs moved to applied (by you, or by the employer's confirmation mail; an
    auto-tracked save never is), mail actually sent from the Inbox (pending, rejected and failed items do not count,
    nor withdrawals), interview rounds up to today, and contact touches you recorded yourself."""
    start, end = _day(start), min(_day(end), date.today())
    if start > end:
        return []
    rows = []

    def add(d, activity, employer="", position="", method="", contact="", result="", job_id=None):
        if start <= d <= end:
            rows.append({"date": d.isoformat(), "activity": activity, "employer": employer or "", "position": position or "",
                         "method": method, "contact": contact or "", "result": result or "", "job_id": job_id})

    for d, j in _first_status("applied"):
        add(d, "applied", j["company"], j["title"], "email" if (j["source"] or "") == "email" else "online",
            " ".join(x for x in (j["contact_name"], j["contact_email"]) if x), j["status"], j["id"])
    for p in db.con().execute("SELECT p.decided_at, p.payload, j.id, j.company, j.title, j.status FROM pending p LEFT JOIN "
                              "jobs j ON j.id=p.job_id WHERE p.kind='send_email' AND p.status='done'").fetchall():
        try:
            pay = json.loads(p["payload"] or "{}")
        except ValueError:
            continue
        if pay.get("new_status") == "withdrawn" or not p["decided_at"]:  # withdrawing is not a search activity
            continue
        add(_local(p["decided_at"]), "followed_up" if pay.get("purpose") in ("followup", "thanks") else "contacted",
            p["company"], p["title"], "email", pay.get("to"), "sent", p["id"])
    # a closed (withdrawn / rejected) job's rounds after it closed never took place; earlier ones keep their history.
    # ponytail: round times are local, event times UTC; a round within hours of the close can land on either side
    for r in db.con().execute("SELECT i.at, i.kind, i.interviewers, i.outcome, j.id, j.company, j.title FROM interviews i "
                              "JOIN jobs j ON j.id=i.job_id WHERE COALESCE(i.at, '') != '' AND NOT (j.status IN "
                              "('rejected','withdrawn') AND i.at > COALESCE((SELECT MAX(e.ts) FROM events e WHERE "
                              "e.job_id=j.id AND e.kind='status'), j.updated_at))").fetchall():
        add(date.fromisoformat(r["at"][:10]), "interviewed", r["company"], r["title"],
            {"onsite": "in person", "phone": "phone"}.get(r["kind"], "online"), r["interviewers"], r["outcome"], r["id"])
    for t in db.con().execute("SELECT t.day, c.name, c.email, c.company, c.position FROM touches t JOIN contacts c ON "
                              "c.id=t.contact_id").fetchall():
        add(date.fromisoformat(t["day"]), "contacted", t["company"], "", "", " ".join(x for x in (t["name"], t["email"]) if x))
    order = ("applied", "interviewed", "followed_up", "contacted")
    return sorted(rows, key=lambda r: (r["date"], order.index(r["activity"]), r["employer"]))


def activity_report(start, end) -> dict:
    """activity_log grouped by week (Monday first) with each week's count against your activity_weekly_min pref."""
    from . import settings

    start, end = _day(start), _day(end)
    if start > end:
        raise SystemExit("the start date is after the end date")
    if (end - start).days > 1100:
        raise SystemExit("pick a range of at most three years")
    rows, minimum = activity_log(start, end), int(settings.pref("activity_weekly_min") or 0)
    weeks, d = {}, monday(start)
    while d <= end:
        weeks[d.isoformat()] = 0
        d += timedelta(days=7)
    for r in rows:
        weeks[monday(date.fromisoformat(r["date"])).isoformat()] += 1
    return {"from": start.isoformat(), "to": end.isoformat(), "rows": rows, "minimum": minimum or None, "note": ACTIVITY_NOTE,
            "weeks": [{"week": w, "count": n, "met": n >= minimum if minimum else None} for w, n in weeks.items()]}


def activity_export(start, end, fmt: str = "csv", out_dir: Path | None = None) -> Path:
    """The activity report as a CSV, or as Markdown plus a printable HTML page (resume.export_html: print to PDF)."""
    import csv

    from .config import HOME

    rep = activity_report(start, end)
    out_dir = out_dir or HOME / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"activity-{rep['from']}-to-{rep['to']}"
    if fmt == "csv":
        with stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(ACTIVITY_COLUMNS)
            w.writerows([[csv_cell(str(r[k])) for k in ACTIVITY_COLUMNS] for r in rep["rows"]])
        return stem.with_suffix(".csv")
    if fmt != "html":
        raise SystemExit("format is csv or html")
    from .resume import export_html

    lines = [f"# Job search activity {rep['from']} to {rep['to']}", "", rep["note"]]
    for wk in rep["weeks"]:
        mine = [r for r in rep["rows"] if monday(date.fromisoformat(r["date"])).isoformat() == wk["week"]]
        need = f" (your weekly minimum: {rep['minimum']}{', met' if wk['met'] else ', not met'})" if rep["minimum"] else ""
        lines += ["", f"## Week of {wk['week']}: {wk['count']} activit{'y' if wk['count'] == 1 else 'ies'}{need}"]
        lines += [f"- {r['date']} · {r['activity'].replace('_', ' ')} · {r['employer'] or '-'} · {r['position'] or '-'} · "
                  f"{r['method'] or '-'} · contact: {r['contact'] or '-'} · result: {r['result'] or '-'}" for r in mine]
    md = stem.with_suffix(".md")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return export_html(md)


def _who(contact: str) -> str:
    """One person, however an activity row names them: a touch says 'Jane Doe jane@x.com', a sent mail the bare
    address. The address when there is one, else the lowercased name."""
    m = re.search(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", contact or "")
    return (m.group(0) if m else " ".join((contact or "").split())).lower()


def goal_progress(today: date | None = None) -> list[dict]:
    """This week's progress (Monday to today) on each weekly goal you set (pref weekly_goals); [] when none is set."""
    from . import settings

    goals = settings.pref("weekly_goals") or {}
    if not any(goals.values()):
        return []
    today = today or date.today()
    week = activity_log(monday(today), today)
    applied = [r for r in week if r["activity"] == "applied"]
    done = {"applications": len(applied),
            "tailored_applications": sum(1 for r in applied if db.get_job(r["job_id"])["resume_hash"]),
            "contacts": len({_who(r["contact"]) for r in week if r["activity"] in ("contacted", "followed_up") and r["contact"]}),
            "mock_sessions": sum(1 for s in db.con().execute("SELECT ts FROM mock_sessions").fetchall()
                                 if monday(today) <= _local(s["ts"]) <= today)}
    return [{"goal": k, "label": k.replace("_", " "), "target": int(goals[k]), "done": done[k]} for k in settings.GOALS if goals.get(k)]


BANDS = ("<40", "40-59", "60-79", "80+")


def _band(score) -> str:
    return "unscored" if score is None else BANDS[0] if score < 40 else BANDS[1] if score < 60 else BANDS[2] if score < 80 else BANDS[3]


def _rates(key, order=()) -> list[dict]:
    """Response and interview rate per group over the jobs you applied to (db.applied_ids, as db.stats counts them);
    n < MIN_N: no rate."""
    groups: dict[str, list[int]] = {k: [0, 0, 0] for k in order}
    done = db.applied_ids()
    for j in db.list_jobs():
        if j["id"] in done:
            g = groups.setdefault(key(j), [0, 0, 0])
            pos = j["status"] in db.POSITIVE
            g[0], g[1], g[2] = g[0] + 1, g[1] + (pos or j["status"] == "rejected"), g[2] + pos
    out = [{"group": k, "n": n, "responded": r, "positive": p, "enough": n >= MIN_N,
            "response_rate": round(r / n, 2) if n >= MIN_N else None, "interview_rate": round(p / n, 2) if n >= MIN_N else None}
           for k, (n, r, p) in groups.items()]
    return out if order else sorted(out, key=lambda g: -g["n"])


def analytics(weeks: int = 12, today: date | None = None) -> dict:
    """Insights: per-week counts of your own activity (activity_log), offers and mock sessions; response rate by source
    and by match-score band (does tailoring pay off?); the existing funnel and resume-variant data; weekly goals."""
    today = today or date.today()
    weeks = max(1, min(int(weeks), 104))
    first = monday(today) - timedelta(weeks=weeks - 1)
    buckets = {first + timedelta(weeks=i): {"applications": 0, "interviews": 0, "offers": 0, "contacts": set(), "mock_sessions": 0}
               for i in range(weeks)}

    def bump(d: date, k: str, who=None):
        b = buckets.get(monday(d))
        if b is None or d > today:
            return
        if who is None:
            b[k] += 1
        else:
            b[k].add(who)  # contacts: distinct people a week

    for r in activity_log(first, today):
        d = date.fromisoformat(r["date"])
        if r["activity"] == "applied":
            bump(d, "applications")
        elif r["activity"] == "interviewed":
            bump(d, "interviews")
        elif r["contact"]:
            bump(d, "contacts", _who(r["contact"]))
    for d, _ in _first_status("offer"):
        bump(d, "offers")
    for s in db.con().execute("SELECT ts FROM mock_sessions").fetchall():
        bump(_local(s["ts"]), "mock_sessions")
    series = [{"week": f"{m.isocalendar()[0]}-W{m.isocalendar()[1]:02d}", "start": m.isoformat(),
               **{k: len(v) if isinstance(v, set) else v for k, v in b.items()}} for m, b in buckets.items()]
    funnel = db.funnel()
    for v in funnel["stages"].values():  # the same n<5 guard as the rates: '2 -> 0%' is noise, not a conversion
        if v["reached"] < MIN_N:
            v["conversion"] = None
    return {"weeks": series, "min_n": MIN_N,
            "by_source": _rates(lambda j: j["source"] or db.source_of(j["notes"])),
            "by_band": _rates(lambda j: _band(j["match_score"]), (*BANDS, "unscored")),
            "funnel": funnel, "variants": db.variant_stats(), "goals": goal_progress(today)}
