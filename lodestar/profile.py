"""Profile bank: structured facts (contact, skills, languages, experience, education, certifications, projects)
gathered from every resume you import and from your LinkedIn data export, plus the original resume files.

    ~/.lodestar/profile.json      the bank; every entry lists the sources it came from
    ~/.lodestar/resumes/          originals (deduplicated by content hash) + extracted text
    ~/.lodestar/profile-history/  a snapshot of profile.md before every overwrite

profile.md stays the editable master that prompts read. The bank seeds it while it is still the template, rebuilds it
on request, and tops up prompts with facts the master leaves out (candidate_text). Nothing here invents data.

LinkedIn: its API gives third-party apps only name/email/photo and scraping profiles breaks its terms, so "linking"
means storing your profile URL plus importing what LinkedIn hands you: the "Download your data" zip (CSV files) or
the profile "Save to PDF" file. From the zip only the parsed profile facts are kept, never the archive itself
(it can also hold messages and connections).
"""
import csv
import hashlib
import io
import json
import os
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from .config import HOME, PROFILE
from .util import slug

BANK = HOME / "profile.json"
RESUMES = HOME / "resumes"
HISTORY = HOME / "profile-history"
LINKEDIN_EXPORT_URL = "https://www.linkedin.com/mypreferences/d/download-my-data"
_LOCK = threading.Lock()  # bank read-modify-write: the web server threads and the monitor loop share this file

CONTACT = ("name", "headline", "email", "phone", "location", "linkedin", "github", "website")
FIELDS = {  # list kinds -> allowed fields; the first field(s) of KEYS identify an entry
    "skills": ("name", "category"),
    "languages": ("name", "proficiency"),
    "experience": ("title", "company", "location", "start", "end", "bullets"),
    "education": ("school", "degree", "field", "start", "end"),
    "certifications": ("name", "issuer", "date", "url"),
    "projects": ("name", "description", "url"),
}
KEYS = {"skills": ("name",), "languages": ("name",), "experience": ("company", "title"), "education": ("school", "degree"),
        "certifications": ("name",), "projects": ("name",)}
PLACEHOLDERS = {"full name", "city, st", "email@example.com", "+1 555 000 0000", "linkedin.com/in/you", "github.com/you",
                "job title", "previous title", "company", "project name", "degree, school, year", "bullet",
                "achievement bullet with a number (e.g. cut deploy time 40%)", "another bullet"}
TEMPLATE_MARKERS = ("Full Name", "Two or three sentences", "Achievement bullet with a number")


def empty() -> dict:
    return {"contact": {k: "" for k in CONTACT}, "summary": "", **{k: [] for k in FIELDS}, "resumes": [], "updated": ""}


def load() -> dict:
    bank = empty()
    if BANK.is_file():
        try:
            data = json.loads(BANK.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # set the bad file aside so the next save cannot destroy it
            aside = BANK.with_name(f"profile.json.corrupt-{datetime.now():%Y%m%d-%H%M%S}")
            try:
                os.replace(BANK, aside)
            except OSError:
                pass
            from . import log

            log.get("profile").error("profile.json unreadable (%s); moved to %s, starting an empty bank", e, aside.name)
            data = {}
        for k, v in data.items():
            if k == "contact" and isinstance(v, dict):
                bank["contact"].update({c: str(v.get(c) or "") for c in CONTACT})
            elif k in bank:
                bank[k] = v
    return bank


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save(bank: dict) -> None:
    bank["updated"] = datetime.now().isoformat(timespec="seconds")
    _atomic_write(BANK, json.dumps(bank, indent=2, ensure_ascii=False))


# ----------------------------------------------------------------------------- master profile.md
def is_template(text: str) -> bool:
    """True while profile.md has no real content: missing, empty, or only the starter template's lines (headings
    aside). A filled-in profile with one leftover placeholder line is NOT the template."""
    from .resume import PROFILE_TEMPLATE

    if not text.strip():
        return True
    stock = {ln.strip() for ln in PROFILE_TEMPLATE.splitlines() if ln.strip()}
    if not any(m in text for m in TEMPLATE_MARKERS) and not any(ln.strip() in stock and not ln.strip().startswith("#")
                                                                and len(ln.strip()) > 30 for ln in text.splitlines()):
        return False  # no starter text at all: short, but the user's own words
    real = [ln.strip() for ln in text.splitlines()
            if ln.strip() and ln.strip() not in stock and not ln.strip().startswith("#")
            and not any(m in ln for m in TEMPLATE_MARKERS)]
    return sum(len(x) for x in real) < 80


def master_text() -> str:
    return PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else ""


def snapshot_master(keep: int = 30) -> Path | None:
    """Copy profile.md into profile-history/ (skipped when identical to the newest snapshot); keeps the last N."""
    if not PROFILE.is_file():
        return None
    text = master_text()
    HISTORY.mkdir(parents=True, exist_ok=True)
    snaps = sorted(HISTORY.glob("profile-*.md"))
    if snaps and snaps[-1].read_text(encoding="utf-8") == text:
        return snaps[-1]
    out = HISTORY / f"profile-{datetime.now():%Y%m%d-%H%M%S-%f}.md"
    out.write_text(text, encoding="utf-8")
    for old in sorted(HISTORY.glob("profile-*.md"))[:-keep]:
        old.unlink()
    return out


def write_master(text: str) -> Path:
    """Every overwrite of profile.md goes through here: snapshot the old one, then replace atomically."""
    snapshot_master()
    _atomic_write(PROFILE, text)
    return PROFILE


# ----------------------------------------------------------------------------- merging
def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _key(item: dict, kind: str) -> tuple:
    return tuple(_norm(item.get(f)).casefold() for f in KEYS[kind])


def _placeholder(v: str) -> bool:
    return _norm(v).casefold().strip("-* ") in PLACEHOLDERS


def _clean_item(kind: str, item) -> dict | None:
    if isinstance(item, str):
        item = {FIELDS[kind][0]: item}
    if not isinstance(item, dict):
        return None
    out: dict = {}
    for f in FIELDS[kind]:
        v = item.get(f)
        if f == "bullets":
            vals = v if isinstance(v, list) else re.split(r"\n|•", str(v or ""))
            out[f] = [b for b in (_norm(str(x)).lstrip("-*• ").strip() for x in vals) if b and not _placeholder(b)]
        else:
            out[f] = "" if _placeholder(_norm(v)) else _norm(v)[:500]
    if not any(out.get(f) for f in KEYS[kind]):
        return None
    if kind in ("skills", "languages") and not 1 <= len(out["name"]) <= 60:
        return None
    return out


def merge(bank: dict, facts: dict, source: str) -> dict:
    """Fold extracted facts into the bank without deleting or overwriting anything. Returns {kind: entries added}."""
    added = {k: 0 for k in FIELDS} | {"contact": 0}
    for k, v in (facts.get("contact") or {}).items():
        v = _norm(v)
        if _placeholder(v):  # before normalising: the template's linkedin.com/in/you must stay a placeholder
            continue
        if k == "linkedin" and v:
            v = _linkedin_url(v) or v
        if k in CONTACT and v and not bank["contact"].get(k):
            bank["contact"][k] = v
            added["contact"] += 1
    if not bank.get("summary") and _norm(facts.get("summary")):
        bank["summary"] = str(facts["summary"]).strip()[:3000]
    for kind in FIELDS:
        index = {_key(x, kind): x for x in bank[kind]}
        for raw in facts.get(kind) or []:
            item = _clean_item(kind, raw)
            if not item:
                continue
            k = _key(item, kind)
            have = index.get(k)
            if have is None and kind == "experience" and not k[1]:  # a title-less entry adds to a role at that company
                have = next((x for kk, x in index.items() if kk[0] == k[0]), None)
            if have is None:
                item["sources"] = [source]
                bank[kind].append(item)
                index[k] = item
                added[kind] += 1
                continue
            for f, v in item.items():
                if f == "bullets":
                    have.setdefault("bullets", [])
                    have["bullets"] += [b for b in v if b.casefold() not in {x.casefold() for x in have["bullets"]}]
                elif v and not have.get(f):
                    have[f] = v
            if source not in have.setdefault("sources", []):
                have["sources"].append(source)
    return added


# ----------------------------------------------------------------------------- extraction
SECTIONS = {
    "summary": ("summary", "about", "profile", "professional summary", "objective"),
    "skills": ("skills", "top skills", "technical skills", "core competencies", "competencies", "technologies", "tools"),
    "languages": ("languages", "spoken languages", "language skills"),
    "experience": ("experience", "work experience", "professional experience", "employment", "employment history", "work history"),
    "education": ("education",),
    "certifications": ("certifications", "certificates", "licenses & certifications", "licenses and certifications", "licenses"),
    "projects": ("projects", "selected projects", "personal projects"),
    "contact": ("contact", "contact information"),
}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
DATES_RE = re.compile(r"\s+(?:-|–|—|to)\s+")
YEARS_RE = re.compile(r"(?:19|20)\d\d\s*[-–—]\s*(?:(?:19|20)\d\d|present)", re.I)
LANGUAGE_NAMES = {  # spoken languages; a bare line in a Languages section must be one of these to count
    "afrikaans", "albanian", "amharic", "arabic", "armenian", "bengali", "bosnian", "bulgarian", "burmese", "cantonese",
    "catalan", "chinese", "croatian", "czech", "danish", "dutch", "english", "estonian", "farsi", "filipino", "finnish",
    "french", "georgian", "german", "greek", "gujarati", "hausa", "hebrew", "hindi", "hungarian", "icelandic", "igbo",
    "indonesian", "irish", "italian", "japanese", "kannada", "kazakh", "khmer", "korean", "kurdish", "lao", "latvian",
    "lithuanian", "macedonian", "malay", "malayalam", "maltese", "mandarin", "marathi", "mongolian", "nepali",
    "norwegian", "pashto", "persian", "polish", "portuguese", "punjabi", "romanian", "russian", "serbian", "sinhala",
    "slovak", "slovenian", "somali", "spanish", "swahili", "swedish", "tagalog", "tamil", "telugu", "thai", "turkish",
    "ukrainian", "urdu", "uzbek", "vietnamese", "welsh", "yoruba", "zulu", "asl", "american sign language",
    "sign language", "brazilian portuguese", "haitian creole", "creole", "latin", "esperanto", "basque", "galician",
}
OTHER_HEADINGS = {"interests", "hobbies", "awards", "honors", "honors & awards", "honors-awards", "publications",
                  "volunteer", "volunteering", "volunteer experience", "references", "activities", "achievements",
                  "courses", "memberships", "affiliations", "additional information", "personal", "patents",
                  "recommendations", "organizations"}


def _phone(text: str) -> str:
    """A real phone number in `text` (10-15 digits once separators go), never a year range like 2019 - 2021."""
    for m in PHONE_RE.finditer(text):
        s = m.group(0).strip()
        if 10 <= len(re.sub(r"\D", "", s)) <= 15 and not YEARS_RE.search(s):
            return s
    return ""


def _namelike(line: str) -> bool:
    low = line.lower()
    return (bool(line) and len(line) < 60 and not re.search(r"[@\d|:]", line) and _section_of(line) not in SECTIONS
            and "resume" not in low and "curriculum" not in low)


def _section_of(line: str) -> str | None:
    s = line.strip()
    m = re.match(r"^#{1,2}\s+(.+)$", s)
    if not m and (len(s) > 40 or s.endswith(".")):
        return None
    name = re.sub(r"\(.*?\)", "", m.group(1) if m else s).strip(" :").casefold()
    for sec, aliases in SECTIONS.items():
        if name in aliases:
            return sec
    caps_heading = len(s) >= 10 and re.fullmatch(r"[A-Z][A-Z&/-]*(?: [A-Z&/-]+)+", s)  # "VOLUNTEER WORK", not "HTML5"
    if m or name in OTHER_HEADINGS or caps_heading:
        return "other"  # a heading we do not read: its content must not spill into the section above
    return None


def _split_list(line: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;|•·](?![^(]*\))", line) if p.strip()]


def extract_heuristic(text: str) -> dict:
    """Offline parse of a markdown or plain-text resume. Reliable for contact details, skills and languages; experience
    only in the master-profile format (### Title - Company (start - end)). The AI extractor does the rest."""
    facts: dict = {"contact": {}, "summary": "", **{k: [] for k in FIELDS}}
    c = facts["contact"]
    if m := EMAIL_RE.search(text):
        c["email"] = m.group(0)
    if m := LINKEDIN_RE.search(text):
        c["linkedin"] = m.group(0)
    if m := GITHUB_RE.search(text):
        c["github"] = m.group(0)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    header = "\n".join(lines[:15])  # contact details live at the top; dates further down are not phone numbers
    first = lines[0].lstrip("# ").strip() if lines else ""
    pipe = next((ln for ln in lines[:15] if "@" in ln and "|" in ln), None)
    if pipe:  # "Name | City | email | phone | links", or under a name line "City | email | phone"
        words = [w.strip().lstrip("# ") for w in pipe.split("|")]
        plain = [w for w in words if w and not re.search(r"[@/]", w) and not _phone(w) and "linkedin" not in w.lower()]
        if pipe != lines[0] and _namelike(first):
            c["name"], rest = first, plain
        else:
            c["name"], rest = (plain[0] if plain and not re.search(r"\d", plain[0]) else ""), plain[1:]
        c["location"] = rest[0] if rest else ""
    elif _namelike(first):
        c["name"] = first
    c["phone"] = _phone(header)

    sec, summary = None, []
    cur: dict | None = None  # the experience / project entry being filled
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        found = _section_of(line)
        if found:
            sec, cur = found, None
            continue
        item = line.lstrip("-*•· ").strip()
        if sec == "summary":
            summary.append(item)
        elif sec == "skills":
            cat = ""
            if ":" in item and len(item.split(":", 1)[0]) < 30:
                cat, item = (x.strip() for x in item.split(":", 1))
            facts["skills"] += [{"name": s, "category": cat} for s in _split_list(item) if len(s) <= 40]
        elif sec == "languages":
            for piece in _split_list(item):
                m = re.match(r"([^()\-–:]+?)\s*(?:\((.+)\)|[-–:]\s*(.+))?$", piece)
                if m:
                    name, prof = m.group(1).strip(), (m.group(2) or m.group(3) or "").strip()
                    if name.casefold() in LANGUAGE_NAMES or (prof and len(name.split()) <= 2 and not re.search(r"\d", name)):
                        facts["languages"].append({"name": name, "proficiency": prof})
        elif sec == "experience":
            m = re.match(r"^#{3,}\s*(.+?)\s+(?:-|–|—|at|@)\s+(.+?)(?:\s*\((.+?)\))?\s*$", line)
            if m:
                start, end = (DATES_RE.split(m.group(3), 1) + [""])[:2] if m.group(3) else ("", "")
                cur = {"title": m.group(1), "company": m.group(2), "start": start, "end": end, "bullets": []}
                facts["experience"].append(cur)
            elif cur is not None and raw.lstrip().startswith(("-", "*", "•")):
                cur["bullets"].append(item)
        elif sec == "education" and not line.startswith("#"):
            facts["education"].append({"school": item})
        elif sec == "certifications":
            facts["certifications"].append({"name": item})
        elif sec == "projects":
            if line.startswith("#"):
                title, _, rest = line.lstrip("# ").partition(" - ")
                cur = {"name": title.strip(), "description": rest.strip()}
                facts["projects"].append(cur)
            elif cur is not None:
                cur["description"] = (cur["description"] + " " + item).strip()
    facts["summary"] = " ".join(s for s in summary if not s.startswith("Two or three sentences"))
    return facts


EXTRACT_PROMPT = """Extract the candidate's facts from this resume / profile text into JSON with exactly these keys:
{"contact": {"name": "", "headline": "", "email": "", "phone": "", "location": "", "linkedin": "", "github": "", "website": ""},
 "summary": "",
 "skills": [{"name": "", "category": ""}],
 "languages": [{"name": "", "proficiency": ""}],
 "experience": [{"title": "", "company": "", "location": "", "start": "", "end": "", "bullets": [""]}],
 "education": [{"school": "", "degree": "", "field": "", "start": "", "end": ""}],
 "certifications": [{"name": "", "issuer": "", "date": "", "url": ""}],
 "projects": [{"name": "", "description": "", "url": ""}]}
Rules: only facts stated in the text, copied faithfully (keep every bullet and number); empty string or [] when absent.
"languages" means spoken/human languages; programming languages go in skills with category "Programming languages".
Dates as written (YYYY-MM or YYYY when possible; "Present" for current roles).

TEXT:
"""


def extract(text: str, provider: str | None = None, use_ai: bool | None = None) -> tuple[dict, bool]:
    """(facts, used_ai). AI extraction when a provider is configured (or use_ai=True); falls back to the offline parser.
    Contact fields the regexes find reliably fill any blanks the AI left."""
    heur = extract_heuristic(text)
    if use_ai is None:
        from . import ai

        use_ai = bool(ai.available())
    if not use_ai:
        return heur, False
    from . import ai
    from .resume import SYSTEM

    try:
        facts = ai.ask_json(EXTRACT_PROMPT + text[:20000], SYSTEM, provider)
        if not isinstance(facts, dict):
            raise ValueError("extractor did not return an object")
    except (Exception, SystemExit) as e:  # no key / provider down (ai raises SystemExit), bad reply: parse offline
        from . import log

        log.get("profile").warning("AI extraction failed, using the offline parser: %s", e)
        return heur, False
    contact: dict = facts["contact"] if isinstance(facts.get("contact"), dict) else {}
    facts["contact"] = {k: contact.get(k) or heur["contact"].get(k, "") for k in CONTACT}
    for kind in FIELDS:  # a string where a list belongs would otherwise become one skill per character
        if not isinstance(facts.get(kind), list):
            facts[kind] = []
    for kind in ("skills", "languages"):  # the offline read only fills a list the AI left empty
        if not facts[kind]:
            facts[kind] = heur[kind]
    return facts, True


# ----------------------------------------------------------------------------- LinkedIn
def _li_rows(z: zipfile.ZipFile, files: dict, name: str, first_col: str) -> list[dict]:
    """Rows of one export CSV. Some files open with a 'Notes:' preamble, so parsing starts at the header line."""
    if name not in files:
        return []
    text = z.read(files[name]).decode("utf-8-sig", errors="replace")
    m = re.search(rf'(?m)^"?{re.escape(first_col)}', text)
    if not m:
        return []
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text[m.start():], newline=""))]


def linkedin_facts(data: bytes) -> dict:
    """Facts from LinkedIn's "Download your data" zip (basic or full archive). Other CSVs in the archive are ignored."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SystemExit("not a zip file: use LinkedIn's 'Download your data' archive, or its profile 'Save to PDF'") from None
    files = {Path(n).name.lower(): n for n in z.namelist() if n.lower().endswith(".csv")}
    known = {"profile.csv", "positions.csv", "skills.csv", "languages.csv", "education.csv", "certifications.csv"}
    if not files.keys() & known:
        raise SystemExit("this zip has no LinkedIn profile files (Profile.csv, Positions.csv, Skills.csv, ...). Request "
                         f"'Download your data' at {LINKEDIN_EXPORT_URL}")
    facts: dict = {"contact": {}, "summary": "", **{k: [] for k in FIELDS}}
    c = facts["contact"]
    for p in _li_rows(z, files, "profile.csv", "First Name")[:1]:
        c["name"] = f"{p.get('First Name', '')} {p.get('Last Name', '')}".strip()
        c["headline"], c["location"] = p.get("Headline", ""), p.get("Geo Location", "")
        facts["summary"] = p.get("Summary", "")
        for url in re.findall(r"https?://[^\s,\]\[]+", p.get("Websites", "")):
            key = "github" if "github.com" in url else "linkedin" if "linkedin.com/in/" in url else "website"
            c.setdefault(key, url)
    emails = _li_rows(z, files, "email addresses.csv", "Email Address")
    if emails:
        c["email"] = next((e["Email Address"] for e in emails if e.get("Primary", "").lower() == "yes"), emails[0]["Email Address"])
    phones = _li_rows(z, files, "phonenumbers.csv", "Extension") or _li_rows(z, files, "phonenumbers.csv", "Number")
    if phones:
        c["phone"] = phones[0].get("Number", "")
    for r in _li_rows(z, files, "positions.csv", "Company Name"):
        facts["experience"].append({"title": r.get("Title"), "company": r.get("Company Name"), "location": r.get("Location"),
                                    "start": r.get("Started On"), "end": r.get("Finished On") or "Present",
                                    "bullets": re.split(r"\n|•", r.get("Description", ""))})
    for r in _li_rows(z, files, "education.csv", "School Name"):
        facts["education"].append({"school": r.get("School Name"), "degree": r.get("Degree Name"), "start": r.get("Start Date"),
                                   "end": r.get("End Date")})
    facts["skills"] = [{"name": r.get("Name")} for r in _li_rows(z, files, "skills.csv", "Name")]
    facts["languages"] = [{"name": r.get("Name"), "proficiency": r.get("Proficiency")} for r in _li_rows(z, files, "languages.csv", "Name")]
    for r in _li_rows(z, files, "certifications.csv", "Name"):
        facts["certifications"].append({"name": r.get("Name"), "issuer": r.get("Authority"), "date": r.get("Started On"), "url": r.get("Url")})
    for r in _li_rows(z, files, "projects.csv", "Title"):
        facts["projects"].append({"name": r.get("Title"), "description": r.get("Description"), "url": r.get("Url")})
    return facts


def _linkedin_url(text: str) -> str:
    """'linkedin.com/in/jane/?trk=x' -> 'https://www.linkedin.com/in/jane'; '' when there is no profile URL in it."""
    m = re.search(r"linkedin\.com/in/([\w\-%]+)", text or "", re.I)
    return f"https://www.linkedin.com/in/{m.group(1)}" if m else ""


def link_linkedin(url: str) -> str:
    """Store your public LinkedIn profile URL (used in rendered resumes and by the autofill bookmarklet)."""
    clean = _linkedin_url(url)
    if not clean:
        raise ValueError("expected a profile URL like https://www.linkedin.com/in/your-name")
    with _LOCK:
        bank = load()
        bank["contact"]["linkedin"] = clean
        save(bank)
    return clean


# ----------------------------------------------------------------------------- importing files
def import_file(data: bytes, filename: str, source: str = "resume", provider: str | None = None,
                use_ai: bool | None = None) -> dict:
    """Save an original (resume .docx/.pdf/.md/.txt, LinkedIn .zip or profile PDF), extract its facts, merge them into
    the bank, and seed profile.md if it is still the template. Re-importing the same file adds no duplicate copy."""
    from .extras import import_document

    name = Path(filename).name or "resume.txt"
    is_zip = name.lower().endswith(".zip")
    if is_zip:
        facts, used_ai, text = linkedin_facts(data), False, ""
        source = "linkedin"
    else:
        text = import_document(data, name)  # raises SystemExit with a clear message on an unsupported format
        if not text.strip():
            raise SystemExit(f"no text found in {name} (a scanned PDF needs OCR first)")
        facts, used_ai = extract(text, provider, use_ai)
    sha = hashlib.sha256(data).hexdigest()
    with _LOCK:
        bank = load()
        entry: dict | None = next((r for r in bank["resumes"] if r.get("sha") == sha), None)
        new_file = entry is None
        if new_file:
            RESUMES.mkdir(parents=True, exist_ok=True)
            stem = f"{datetime.now():%Y%m%d}-{sha[:8]}-{slug(Path(name).stem)}"
            if is_zip:  # keep only the parsed facts, not the archive
                stored = stem + ".linkedin.json"
                (RESUMES / stored).write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                stored = stem + (Path(name).suffix.lower() or ".txt")
                (RESUMES / stored).write_bytes(data)
                if not stored.endswith((".txt", ".md")):
                    (RESUMES / (stem + ".txt")).write_text(text, encoding="utf-8")
            entry = {"id": sha[:8], "name": name, "source": source, "added": datetime.now().isoformat(timespec="seconds"),
                     "sha": sha, "chars": len(text), "file": stored}
            bank["resumes"].append(entry)
        elif not is_zip and Path(str(entry.get("file", ""))).name == entry.get("file") and not entry["file"].endswith((".txt", ".md")):
            (RESUMES / Path(entry["file"]).with_suffix(".txt").name).write_text(text, encoding="utf-8")  # re-import: fresh extraction
        assert entry is not None
        added = merge(bank, facts, f"{source}:{entry['id']}")
        save(bank)
        seeded = False
        if is_template(master_text()):
            write_master(render_markdown(bank))
            seeded = True
    return {"resume": entry, "new_file": new_file, "added": added, "used_ai": used_ai, "seeded_master": seeded,
            "text": text or render_markdown({**empty(), **facts, "resumes": []})}


# ----------------------------------------------------------------------------- manual edits
def add(kind: str, name: str, detail: str = "") -> dict:
    """Add one skill / language / certification by hand ('detail' = category, proficiency or issuer)."""
    second = {"skills": "category", "languages": "proficiency", "certifications": "issuer"}
    if kind not in second:
        raise ValueError(f"can add skills, languages or certifications, not {kind}")
    with _LOCK:
        bank = load()
        n = merge(bank, {kind: [{"name": name, second[kind]: detail}]}, "manual")[kind]
        save(bank)
    return {"added": n, "bank": bank}


def remove(kind: str, name: str) -> dict:
    if kind not in FIELDS:
        raise ValueError(f"unknown kind {kind}")
    with _LOCK:
        bank = load()
        before = len(bank[kind])
        bank[kind] = [x for x in bank[kind] if _norm(x.get(KEYS[kind][0])).casefold() != _norm(name).casefold()]
        save(bank)
    return {"removed": before - len(bank[kind]), "bank": bank}


def set_contact(field: str, value: str) -> dict:
    if field not in CONTACT:
        raise ValueError(f"unknown contact field {field}")
    if field == "linkedin" and value:
        link_linkedin(value)
        return load()
    with _LOCK:
        bank = load()
        bank["contact"][field] = _norm(value)
        save(bank)
    return bank


# ----------------------------------------------------------------------------- rendering + prompts
PREFS_HEAD_RE = re.compile(r"(?mi)^(#{1,6})[ \t]*preferences\b")  # any level, any case: lint treats them all as private


def _prefs_span(text: str) -> tuple[int, int] | None:
    """The first Preferences section: its heading up to the next section (# or ##) or a heading of its own level."""
    if not (m := PREFS_HEAD_RE.search(text)):
        return None
    end = re.compile(rf"(?m)^#{{1,{max(len(m[1]), 2)}}}[ \t]").search(text, m.end())
    return m.start(), end.start() if end else len(text)


def drop_preferences(text: str) -> str:
    """Text without any Preferences section (salary floor, deal-breakers): for anything an employer reads."""
    while s := _prefs_span(text):
        text = text[:s[0]] + text[s[1]:]
    return text


def _preferences(master: str) -> str:
    s = _prefs_span(master)
    return master[s[0]:s[1]].strip() if s else "## Preferences (used for job search ranking)\nTarget roles: | Locations / remote: | Salary floor: | Deal-breakers: | Industries to avoid:"


def render_markdown(bank: dict, master: str | None = None) -> str:
    """The bank as a master profile in the template's section layout. Preferences are kept from the current master."""
    c = bank.get("contact") or {}
    out = ["# Master Resume", "", "## Contact",
           " | ".join(v for v in (c.get(k) for k in ("name", "location", "email", "phone", "linkedin", "github", "website")) if v)]
    if c.get("headline") or bank.get("summary"):
        out += ["", "## Summary"] + [x for x in (c.get("headline"), bank.get("summary")) if x]
    if bank.get("skills"):
        groups: dict[str, list[str]] = {}
        for s in bank["skills"]:
            groups.setdefault(s.get("category") or "", []).append(s["name"])
        out += ["", "## Skills"] + [f"- {cat + ': ' if cat else ''}{', '.join(names)}" for cat, names in groups.items()]
    if bank.get("languages"):
        out += ["", "## Languages"] + [f"- {x['name']}{' (' + x['proficiency'] + ')' if x.get('proficiency') else ''}" for x in bank["languages"]]
    if bank.get("experience"):
        out += ["", "## Experience"]
        for e in bank["experience"]:
            dates = " - ".join(x for x in (e.get("start"), e.get("end")) if x)
            out += ["", f"### {e.get('title') or 'Role'} - {e.get('company') or ''}{f' ({dates})' if dates else ''}".rstrip(" -")]
            out += [f"- {b}" for b in e.get("bullets") or []]
    if bank.get("projects"):
        out += ["", "## Projects"]
        for p in bank["projects"]:
            out += ["", f"### {p['name']}{' - ' + p['url'] if p.get('url') else ''}"] + ([f"- {p['description']}"] if p.get("description") else [])
    if bank.get("education"):
        out += ["", "## Education"]
        for e in bank["education"]:
            dates = " - ".join(x for x in (e.get("start"), e.get("end")) if x)
            out.append(", ".join(x for x in (e.get("degree"), e.get("field"), e.get("school")) if x) + (f" ({dates})" if dates else ""))
    if bank.get("certifications"):
        out += ["", "## Certifications"] + [f"- {x['name']}{' - ' + x['issuer'] if x.get('issuer') else ''}{' (' + x['date'] + ')' if x.get('date') else ''}" for x in bank["certifications"]]
    out += ["", _preferences(master if master is not None else master_text()), ""]
    return "\n".join(out)


def rebuild_master() -> Path:
    """Regenerate profile.md from the bank (the old file is snapshotted to profile-history/ first)."""
    with _LOCK:
        return write_master(render_markdown(load()))


def _mentioned(name: str, text: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I))


def extras_text(master: str, bank: dict | None = None) -> str:
    """Bank facts the master profile does not mention, as a short section prompts can draw on."""
    bank = bank or load()
    skills = [s["name"] for s in bank["skills"] if not _mentioned(s["name"], master)]
    langs = [f"{x['name']}{' (' + x['proficiency'] + ')' if x.get('proficiency') else ''}" for x in bank["languages"] if not _mentioned(x["name"], master)]
    certs = [x["name"] for x in bank["certifications"] if not _mentioned(x["name"], master)]
    roles = [f"{e.get('title')} at {e.get('company')} ({e.get('start') or '?'} - {e.get('end') or '?'})" for e in bank["experience"]
             if e.get("company") and not _mentioned(e["company"], master)]
    lines = [f"- {label}: {'; '.join(v[:60])}" for label, v in (("Skills", skills), ("Languages", langs),
                                                                  ("Certifications", certs), ("Other roles", roles)) if v]
    return ("## On file (from imported resumes / LinkedIn; not yet in the master above)\n" + "\n".join(lines)) if lines else ""


PRIORITY = ("contact", "summary", "skills", "languages", "preferences", "on file", "certifications", "education",
            "experience", "projects")


def brief(text: str, limit: int) -> str:
    """Fit a markdown profile into `limit` characters by whole sections in priority order (contact, summary, skills,
    languages, preferences first; experience trimmed last), instead of cutting off whatever comes at the end."""
    if len(text) <= limit:
        return text
    secs = re.split(r"(?m)^(?=## )", text)

    def rank(i: int) -> int:
        if i == 0:
            return -1  # title / preamble
        head = secs[i].split("\n", 1)[0].casefold()
        return next((n for n, k in enumerate(PRIORITY) if k in head), len(PRIORITY))

    keep: dict[int, str] = {}
    used = 0
    for i in sorted(range(len(secs)), key=rank):
        room = limit - used
        if room < 80:
            break
        s = secs[i]
        keep[i] = s if len(s) <= room else s[:room].rsplit("\n", 1)[0] + "\n…\n"
        used += len(keep[i])
    return "".join(keep[i] for i in sorted(keep)).strip()


def candidate_text(limit: int | None = None, strict: bool = True, private: bool = True) -> str:
    """What prompts should read: the master profile plus bank facts it leaves out, fitted to `limit` by section.
    strict=False (coach, ideas) tolerates an unfilled profile: those helpers are how a new user builds one.
    private=False drops the Preferences section (salary floor, deal-breakers) for text an employer will read."""
    from .resume import profile_text

    master = profile_text()
    if is_template(master):  # never rank listings or draft letters for "Full Name" with placeholder skills
        bank = load()
        if not any(bank[k] for k in FIELDS) and not bank["contact"]["name"]:
            if not strict:
                return "(The candidate has not filled in a profile yet. Help them build one; never invent facts.)"
            raise SystemExit(f"your master profile is still the template: fill in {PROFILE} or import a resume "
                             "(lodestar profile import <file>, or the Profile tab)")
        master = render_markdown(bank, master)
    extra = extras_text(master)
    text = master.rstrip() + ("\n\n" + extra if extra else "")
    if not private:
        text = drop_preferences(text)
    return brief(text, limit) if limit else text


def saved_resumes() -> list[dict]:
    """Saved resumes that can be a tailoring base: [{id, name, added}]. LinkedIn zips keep only facts, so they are out."""
    return [{"id": r["id"], "name": r.get("name", ""), "added": r.get("added", "")} for r in load()["resumes"]
            if r.get("id") and not str(r.get("file", "")).endswith(".linkedin.json")]


def saved_text(rid: str) -> str:
    """The plain text of saved resume `rid` (the extracted .txt kept beside a .docx / .pdf original)."""
    r = next((r for r in load()["resumes"] if r.get("id") == rid and not str(r.get("file", "")).endswith(".linkedin.json")), None)
    f = str(r.get("file", "")) if r else ""
    if not f or Path(f).name != f:  # a bare file name inside resumes/, nothing else
        raise SystemExit(f"no saved resume '{rid}': `lodestar profile show` lists their ids")
    p = RESUMES / f
    p = p if p.suffix in (".txt", ".md") else p.with_suffix(".txt")
    if not p.is_file():
        raise SystemExit(f"the text of saved resume '{rid}' is missing ({p.name}); import the file again")
    return p.read_text(encoding="utf-8")


def preferences_text() -> str:
    """Just the Preferences section of the master profile (for private judgements: gap check, offer, ranking)."""
    return _preferences(master_text())


def summary_text() -> str:
    bank = load()
    c = bank["contact"]
    lines = [f"bank: {BANK}", f"contact: {' | '.join(v for v in c.values() if v) or '(empty)'}",
             f"skills ({len(bank['skills'])}): {', '.join(s['name'] for s in bank['skills']) or '-'}",
             f"languages ({len(bank['languages'])}): " + (", ".join(f"{x['name']} {('(' + x['proficiency'] + ')') if x.get('proficiency') else ''}".strip() for x in bank["languages"]) or "-"),
             f"experience: {len(bank['experience'])} | education: {len(bank['education'])} | certifications: "
             f"{len(bank['certifications'])} | projects: {len(bank['projects'])}",
             f"saved resumes ({len(bank['resumes'])}):"]
    lines += [f"  {r['id']}  {r['added'][:10]}  {r['source']:<9} {r['name']}  -> resumes/{r['file']}" for r in bank["resumes"]] or ["  (none)"]
    return "\n".join(lines)
