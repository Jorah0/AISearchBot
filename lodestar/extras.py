"""Small high-payoff extras: outreach drafts, interview .ics files, weekly digest, Obsidian tracker mirror,
resume-variant hashing, and a scheduled-task installer. One module on purpose; split when any grows real logic.
"""
import hashlib
import os
import platform
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ai, db
from .config import ALERTS, APPS_DIR
from .util import notify, slug


def _job_dir(j) -> Path:
    return APPS_DIR / f"{j['id']}-{slug(j['company'])}-{slug(j['title'])}"


# ----------------------------------------------------------------------------- outreach
def outreach(job, person: str = "", channel: str = "linkedin", provider: str | None = None) -> str:
    from .resume import profile_text

    limit = "under 300 characters, no greeting fluff" if channel == "linkedin" else "under 120 words, include a subject line"
    return ai.ask(
        f"""Write a {channel} message from the candidate to {person or 'a hiring manager or recruiter'} at {job['company']}
about the {job['title']} role. Goal: a reply or a referral, not a pitch. {limit}. Mention one specific, relevant
achievement and one specific reason this company. Plain text.

JOB DESCRIPTION:
{(job['jd'] or '')[:3000]}

CANDIDATE:
{profile_text()[:5000]}""",
        provider=provider,
    )


# ----------------------------------------------------------------------------- calendar
def parse_when(s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %I:%M %p", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    raise SystemExit(f"could not parse date '{s}' (use YYYY-MM-DD HH:MM)")


def ics(job, when: datetime, minutes: int = 60, title: str | None = None, reminder_days: int = 2) -> Path:
    """Write an .ics with the interview and a prep reminder N days before. Double-click imports into any calendar."""
    def ev(start, mins, summary, desc):
        end = start + timedelta(minutes=mins)
        return "\n".join([
            "BEGIN:VEVENT", f"UID:{uuid.uuid4()}@lodestar", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
            f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}", f"SUMMARY:{summary}",
            f"DESCRIPTION:{desc}", "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", f"DESCRIPTION:{summary}",
            "END:VALARM", "END:VEVENT"])

    summary = title or f"Interview: {job['company']} - {job['title']}"
    prep = (when - timedelta(days=reminder_days)).replace(hour=9, minute=0, second=0)
    body = "\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//lodestar//EN",
        ev(when, minutes, summary, f"lodestar job #{job['id']} {job['url'] or ''}".strip()),
        ev(prep, 30, f"Prep: {job['company']} interview", f"run: lodestar interview prep {job['id']}"),
        "END:VCALENDAR", ""])
    d = _job_dir(job)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"interview-{when:%Y%m%d-%H%M}.ics"
    out.write_text(body, encoding="utf-8")
    db.add_event(job["id"], "calendar", str(out))
    return out


# ----------------------------------------------------------------------------- digest
def digest(days: int = 7, send: bool = False, provider: str | None = None) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [j for j in db.list_jobs() if j["updated_at"] >= cutoff]
    follow = db.needs_followup(7)
    alerts = [ln for ln in (ALERTS.read_text(encoding="utf-8").splitlines() if ALERTS.is_file() else [])
              if ln[1:11] >= cutoff]
    st = db.stats()
    lines = [f"# lodestar digest - last {days} days ({datetime.now():%Y-%m-%d})", "",
             f"Pipeline: {st['counts']} | applied {st['applied_total']} | response {st['response_rate']:.0%} | interview {st['interview_rate']:.0%}",
             "", f"## Moved this week ({len(recent)})",
             *[f"- #{j['id']} {j['company']} - {j['title']}: {j['status']}" for j in recent[:20]],
             "", f"## Needs follow-up ({len(follow)})",
             *[f"- #{j['id']} {j['company']} - {j['title']} (quiet since {j['updated_at'][:10]})" for j in follow[:20]],
             "", f"## Alerts ({len(alerts)})", *[f"- {a}" for a in alerts[-25:]]]
    text = "\n".join(lines)
    if ai.available():
        try:
            text += "\n\n## Coach's plan for next week\n" + ai.ask(
                "Given this job-search digest, write 5 concrete actions for next week, most impactful first, one line each.\n\n"
                + text, provider=provider)
        except Exception as e:  # the digest is still useful without the AI paragraph
            text += f"\n\n(coach unavailable: {e})"
    if send:
        notify(text)
    return text


# ----------------------------------------------------------------------------- obsidian mirror of the tracker
def vault_root() -> Path:
    return Path(os.environ.get("OBSIDIAN_VAULT") or (Path.home() / "Documents" / "Obsidian Vault"))


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
            "---", f'company: "{j["company"]}"', f'title: "{j["title"]}"', f"status: {j['status']}",
            f"url: {j['url'] or ''}", f"applied: {j['applied_at'] or ''}", f"updated: {j['updated_at'][:10]}",
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

    cmd = f'"{sys.executable}" -m lodestar run --once'  # the interpreter running this command, wherever it lives
    if platform.system() != "Windows":
        return f"add to crontab -e:\n*/{every} * * * * {cmd} >> ~/.lodestar/cron.log 2>&1"
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

    from .resume import profile_text
    from .util import fetch, strip_html

    sources = []
    if job["url"]:
        host = urlparse(job["url"]).netloc
        for u in (job["url"], f"https://{host}", f"https://{host}/about"):
            try:
                sources.append((u, strip_html(fetch(u))[:5000]))
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
{profile_text()[:1500]}""",
        provider=provider,
    )
    out = _job_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    (out / "research.md").write_text(text, encoding="utf-8")
    db.add_event(job["id"], "research", f"{len(sources)} source(s)")
    return out / "research.md"


def autofill_data() -> dict:
    """Fields the autofill bookmarklet may type into application forms. Parsed from the profile contact line."""
    from .resume import profile_text

    text = profile_text()
    contact = next((ln for ln in text.splitlines() if "@" in ln and "|" in ln), "")
    parts = [p.strip() for p in contact.split("|")]
    email = next((p for p in parts if "@" in p), "")
    phone = next((p for p in parts if re.search(r"\+?\d[\d\s().-]{7,}", p)), "")
    linkedin = next((p for p in parts if "linkedin" in p.lower()), "")
    github = next((p for p in parts if "github" in p.lower()), "")
    website = next((p for p in parts if p.lower().startswith(("http", "www")) and "linkedin" not in p and "github" not in p), "")
    name = parts[0] if parts and "@" not in parts[0] and not phone == parts[0] else ""
    first, _, last = name.partition(" ")
    answers = {a["question"]: a["answer"] for a in db.list_answers()}
    return {"name": name, "first_name": first, "last_name": last, "email": email, "phone": phone, "linkedin": linkedin,
            "github": github, "website": website, "location": parts[1] if len(parts) > 1 and "@" not in parts[1] else "",
            "answers": answers}


# ----------------------------------------------------------------------------- backup + export
def backup(out_dir: Path | None = None, keep: int = 7) -> Path:
    """Zip profile, tracker, settings, answers, ideas and generated documents (not snapshots/caches). Keeps the last N."""
    import zipfile

    from .config import HOME

    out_dir = out_dir or HOME / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"lodestar-backup-{datetime.now():%Y%m%d-%H%M}.zip"
    skip = {"backups", "snapshots", "cache", "__pycache__", "lodestar.log"}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in HOME.rglob("*"):
            rel = p.relative_to(HOME)
            if p.is_file() and not (set(rel.parts) & skip) and not p.name.startswith("lodestar.log"):
                z.write(p, str(rel))
    for old in sorted(out_dir.glob("lodestar-backup-*.zip"))[:-keep]:
        old.unlink()
    return target


def export_data(fmt: str = "json", out_dir: Path | None = None) -> Path:
    """Dump jobs, events, answers, ideas, pending as JSON (one file) or CSV (one file per table)."""
    import csv
    import json as _json

    from .config import HOME

    tables = {"jobs": db.list_jobs(), "events": db.con().execute("SELECT * FROM events ORDER BY id").fetchall(),
              "answers": db.list_answers(), "ideas": db.list_ideas(), "pending": db.list_pending(None, 10000)}
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
                w.writerows([list(r) for r in rows])
    return out_dir
