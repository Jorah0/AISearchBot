"""Deterministic resume checks. lint(): line-level writing checks on resume text. audit(): what a resume FILE (.docx /
.pdf) does that parsers often trip on, plus the plain text a parser would see. No AI; the issue list matters more than
the score."""
import io
import re
import zipfile
from datetime import date
from pathlib import Path

SEVERITIES = ("high", "medium", "low", "info")
_PENALTY = {"high": 15, "medium": 6, "low": 2, "info": 0}
WEAK = ("responsible for", "helped", "helped with", "worked on", "worked with", "assisted with", "assisted in", "assisted",
        "duties included", "tasked with", "in charge of", "involved in", "participated in", "contributed to",
        "was responsible", "handled", "tried to", "familiar with", "exposure to", "various")
CLICHES = ("team player", "hard worker", "hardworking", "hard-working", "detail-oriented", "detail oriented", "results-driven",
           "results driven", "results-oriented", "go-getter", "synergy", "think outside the box", "self-starter",
           "self starter", "passionate", "proven track record", "excellent communication skills",
           "fast-paced environment", "motivated", "guru", "ninja", "rockstar", "rock star", "best of breed", "go-to person",
           "value add", "seasoned professional", "strategic thinker", "people person", "thought leader", "wear many hats",
           "outside the box", "track record of success", "highly skilled", "extensive experience")
SECTIONS = {
    "experience": r"(work |professional |relevant |career )?(experience|employment( history)?|work history|career history)",
    "education": r"education( and training)?|academic( background)?",
    "skills": r"(technical |core |key )?(skills|competencies|expertise)( and tools)?",
}
ACHIEVEMENT_SECTIONS = ("project", "volunteer", "leadership", "achievement", "accomplishment")
STANDARD_HEADINGS = re.compile(
    r"(contact|contact (info|information|details)|summary|professional summary|career summary|profile|professional profile|"
    r"objective|about( me)?|highlights|summary of qualifications|qualifications|skills|technical skills|core competencies|"
    r"competencies|key skills|skills and tools|expertise|experience|work experience|professional experience|relevant experience|"
    r"employment|employment history|work history|career history|education|education and training|academic background|"
    r"certifications?|certificates|licenses( and certifications)?|certifications and licenses|projects|selected projects|"
    r"publications|awards|honors|honors and awards|volunteer( experience| work)?|volunteering|languages|interests|references|"
    r"training|courses|coursework|achievements|accomplishments|leadership|activities|affiliations|memberships|"
    r"professional development|research|patents|portfolio|additional information|military service|preferences.*)$")
EMAIL = re.compile(r"[^@\s<>()|,;]+@[^@\s<>()|,;]+\.[a-z]{2,}", re.I)
PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")
NUMBER = re.compile(r"\d|%|\$|€|£|\b(one|two|three|four|five|six|seven|eight|nine|ten|twelve|dozen|hundred|thousand|million|"
                    r"billion|double[ds]?|tripled?|half|halved)\b", re.I)
PRONOUN = re.compile(r"\bI\b|\b(?i:me|my|myself|mine|we|our|ours)\b")
PASSIVE = re.compile(r"\b(was|were)\s+(\w{3,}ed|built|made|given|taken|led|written|chosen|done|sent|held|seen|known|shown|"
                     r"driven|grown|run|brought|bought|kept|taught|won)\b", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}
_D = r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4}-\d{2}|\d{4})"
RANGE = re.compile(rf"({_D})\s*(?:-|–|—|to|until)\s*({_D}|present|current|now|today)", re.I)
BULLET = re.compile(r"^\s*(?:[-*•·▪◦‣–]|\d{1,2}[.)])\s+")


def _plain(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|__(.+?)__|`", lambda m: m.group(1) or m.group(2) or "", s).strip()


def _heading(line: str) -> tuple[str, int] | None:
    """(text, level) of a heading line: markdown '#' (level = number of #), or a short line in capitals / ending in ':'
    (plain-text resumes, level 2). Level 3+ is an entry inside a section, e.g. '### Engineer - Acme (2020 - 2023)'."""
    s = _plain(line)
    if s.startswith("#"):
        return s.lstrip("#").strip(), len(s) - len(s.lstrip("#"))
    words = s.rstrip(":").split()
    if 0 < len(words) <= 4 and not BULLET.match(line) and (s.endswith(":") or (s.isupper() and len(s) > 3)):
        return s.rstrip(":").strip(), 2
    return None


def _month(s: str, end: bool) -> int | None:
    """A date as a month count (year*12 + month); a bare year is January as a start and December as an end."""
    s = s.lower().strip()
    if s in ("present", "current", "now", "today"):
        return date.today().year * 12 + date.today().month
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        return int(m[1]) * 12 + int(m[2])
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return int(m[2]) * 12 + int(m[1])
    if m := re.fullmatch(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", s):
        return int(m[2]) * 12 + MONTHS.get(m[1], 1)
    if re.fullmatch(r"\d{4}", s):
        return int(s) * 12 + (12 if end else 1)
    return None


def lint(text: str) -> dict:
    """Line-level checks. Issues: {line (1-based; 0 = whole document), severity, rule, text, hint}. The Preferences section
    (private, never sent) is skipped."""
    issues: list[dict] = []

    def add(line, severity, rule, msg, hint):
        issues.append({"line": line, "severity": severity, "rule": rule, "text": msg, "hint": hint})

    lines = (text or "").splitlines()
    section, found, ranges = "", set(), []
    starts: dict[str, list[int]] = {}
    for n, raw in enumerate(lines, 1):
        h = _heading(raw)
        if h is not None:
            low = h[0].lower()
            if h[1] <= 2:
                section = next((k for k, rx in SECTIONS.items() if re.search(rf"\b(?:{rx})\b", low)),
                               "preferences" if low.startswith("preferences") else low)
                found.add(section)
            elif section in ("experience", ""):
                ranges += [(n, a, b) for a, b in RANGE.findall(low)]
            continue
        if section == "preferences" or not raw.strip():
            continue
        s = _plain(raw)
        if section in ("experience", ""):
            ranges += [(n, a, b) for a, b in RANGE.findall(s)]
        low = s.lower()
        contact = bool(EMAIL.search(s) or ("|" in s and n <= 5))
        if not contact and (m := PRONOUN.search(s)):
            add(n, "medium", "pronoun", f"first-person pronoun: \"{m.group()}\"",
                "Resumes drop I / my / we: start the line with the action instead.")
        for c in CLICHES:
            if re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", low):
                add(n, "low", "cliche", f"cliché: \"{c}\"", "Show it with a concrete example or result instead of the label.")
        achievements = section in ("experience", "") or any(w in section for w in ACHIEVEMENT_SECTIONS)
        if not BULLET.match(raw) or not achievements:  # skills / education lists are not achievement bullets
            continue
        body = BULLET.sub("", s).strip()
        words = body.split()
        weak = next((w for w in sorted(WEAK, key=len, reverse=True) if re.match(rf"{w}\b", body.lower())), None)
        if weak:
            add(n, "medium", "weak_opener", f"weak opener: \"{weak}\"", "Lead with a strong verb: Led, Built, Cut, Grew, Launched, Reduced.")
        if not NUMBER.search(body):
            add(n, "low", "no_metric", "no number in this bullet", "Add a number where you can: how many, how much, how fast, what changed.")
        if m := PASSIVE.search(body):
            add(n, "low", "passive", f"passive voice (hint): \"{m.group()}\"",
                "Hint only: say who did it, e.g. 'I was promoted' -> 'Promoted to ...'.")
        if len(words) > 35:
            add(n, "low", "long", f"long bullet ({len(words)} words)", "Keep bullets to one or two lines: split it or cut the context.")
        elif len(words) < 4:
            add(n, "low", "short", f"very short bullet ({len(words)} words)", "Say what you did and what came of it.")
        if words:
            starts.setdefault(re.sub(r"\W", "", words[0].lower()), []).append(n)
    for verb, at in starts.items():
        if verb and len(at) > 2:
            add(at[0], "low", "repeated_verb", f"\"{verb}\" starts {len(at)} bullets (lines {', '.join(map(str, at))})",
                "Vary the verbs so each bullet reads as its own achievement.")
    whole = "\n".join(lines)
    if not EMAIL.search(whole):
        add(0, "high", "no_email", "no email address found", "Put your email in the contact line at the top.")
    if not PHONE.search(whole):
        add(0, "high", "no_phone", "no phone number found", "Put a phone number in the contact line at the top.")
    for sec in SECTIONS:
        if sec not in found:
            add(0, "medium", "missing_section", f"no {sec.title()} section heading",
                f"Add a heading named plainly, e.g. '{sec.title()}': parsers and recruiters look for it.")
    spans = sorted((a, b, n) for n, x, y in ranges if (a := _month(x, False)) and (b := _month(y, True)) and a <= b)
    last_end = None
    for a, b, n in spans:
        if last_end is not None and a - last_end > 6:
            add(n, "info", "gap", f"about {a - last_end} months between roles (before line {n})",
                "Information only: a short line about that time (study, caregiving, freelance) can answer the question.")
        if last_end is None or b > last_end:
            last_end = b
    issues.sort(key=lambda i: (SEVERITIES.index(i["severity"]), i["line"]))
    counts = {s: sum(i["severity"] == s for i in issues) for s in SEVERITIES}
    return {"score": max(0, 100 - sum(_PENALTY[i["severity"]] for i in issues)), "counts": counts, "issues": issues}


# ----------------------------------------------------------------------------- file audit
def _xml_text(xml: str) -> str:
    return " ".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml))


def _docx_checks(data: bytes, add) -> None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError):
        raise SystemExit("not a readable .docx file (re-save it from Word or Google Docs as .docx)") from None
    names = z.namelist()
    edges = " ".join(_xml_text(z.read(n).decode("utf-8", "replace")) for n in names if re.fullmatch(r"word/(header|footer)\d*\.xml", n))
    if EMAIL.search(edges) or PHONE.search(edges):
        add("high", "contact_in_header", "contact details sit in the page header or footer",
            "Many parsers skip headers and footers: put your name, email and phone in the body at the top.")
    if (n := doc.count("<w:tbl>") + doc.count("<w:tbl ")):
        add("medium", "tables", f"{n} table(s)", "Parsers can read table cells out of order: use plain lines and bullets.")
    if "<w:txbxContent" in doc or "<v:textbox" in doc or "<wps:txbx" in doc:
        add("high", "text_boxes", "text boxes or shapes hold text", "Text inside boxes and shapes is often skipped entirely: move it into the body.")
    if "<w:drawing" in doc or any(n.startswith("word/media/") for n in names):
        add("low", "images", "images (photo, icons, logo or charts)", "Images carry no readable text: keep anything important as text, and leave out a photo unless it is the local norm.")
    if (cols := [int(c) for c in re.findall(r'<w:cols\b[^>]*\bw:num="(\d+)"', doc) if int(c) > 1]):
        add("medium", "columns", f"{max(cols)}-column layout", "Columns can interleave lines when parsed: a single column reads cleanly.")
    styles = z.read("word/styles.xml").decode("utf-8", "replace") if "word/styles.xml" in names else ""
    normal = re.search(r'<w:style\b[^>]*w:styleId="Normal".*?</w:style>', styles, re.S)
    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", styles, re.S)
    scope = doc + (normal.group() if normal else "") + (defaults.group() if defaults else "")  # unused styles don't count
    sizes = [int(v) for v in re.findall(r'<w:sz w:val="(\d+)"', scope)]
    if sizes and min(sizes) < 20:  # half-points: 20 = 10 pt
        add("low", "small_font", f"text below 10 pt (smallest {min(sizes) / 2:g} pt)", "Use 10-12 pt for body text so it survives scanning and reading.")
    headings = re.findall(r'<w:pStyle w:val="(?:Heading[12]|Title)"/>.*?</w:p>', doc, re.S)
    for i, h in enumerate(headings):
        t = " ".join(_xml_text(h).split())
        if i and t and len(t.split()) <= 4 and not re.search(r"\d|\||@", t) and not STANDARD_HEADINGS.match(t.lower().rstrip(":")):
            add("low", "heading", f"non-standard section heading: \"{t}\"", "Parsers look for familiar names: Summary, Experience, Education, Skills, Projects, Certifications.")


def _odd_name(name: str) -> str | None:
    stem = Path(name).stem
    if len(name) > 60:
        return "a very long name"
    if re.search(r"\(\d+\)|\bcopy\b|final|untitled|document\d*$|draft|v\d+$|\d{6,}", stem, re.I):
        return "a draft-like or generic name"
    if re.search(r"[^\w .()-]", stem) or not re.search(r"[a-z]", stem, re.I):
        return "unusual characters"
    return None


def audit(data: bytes, filename: str) -> dict:
    """Checks on the resume file itself. Returns {file, size, issues: [{severity, rule, text, hint}], text, note}; text is
    the plain extraction the profile importer uses, i.e. roughly what a parser sees."""
    from .extras import import_document

    ext = Path(filename).suffix.lower()
    if ext not in (".docx", ".pdf"):
        raise SystemExit("audit checks .docx and .pdf files (plain .md / .txt has no layout to trip a parser)")
    issues: list[dict] = []

    def add(severity, rule, msg, hint):
        issues.append({"severity": severity, "rule": rule, "text": msg, "hint": hint})

    text, note = "", "General guidance: parsers differ, and a clean single-column .docx or text PDF is read most reliably."
    if ext == ".docx":
        _docx_checks(data, add)
        text = import_document(data, filename)
    else:
        if not data.startswith(b"%PDF"):
            raise SystemExit("not a PDF file")
        if (imgs := len(re.findall(rb"/Subtype\s*/Image", data))):
            add("low", "images", f"{imgs} image(s)", "Images carry no readable text: keep anything important as text.")
        try:
            text = import_document(data, filename)
        except SystemExit as e:  # pypdf is optional: the size, name and image checks still run without it
            note += f" Text checks skipped: {e}"
        except Exception as e:  # a PDF pypdf cannot open will trip parsers too
            add("high", "unreadable", f"the PDF could not be read ({str(e)[:80]})", "Re-export it from your editor as a standard PDF, or send the .docx.")
        else:
            pages = max(1, len(re.findall(rb"/Type\s*/Page(?!s)", data)))
            if len(text.strip()) < 150 * pages:
                add("high", "no_text_layer", f"almost no selectable text ({len(text.strip())} characters)",
                    "This looks scanned or exported as an image: parsers see nothing. Export a text PDF from your editor, or send the .docx.")
    if text and not EMAIL.search(text):
        add("high", "no_email_in_body", "no email address in the text a parser reads", "Put your email in the body near the top.")
    if len(data) > 2_000_000:
        add("medium", "size", f"file is {len(data) / 1e6:.1f} MB", "Keep it under 2 MB: some portals reject or time out on large files.")
    if (why := _odd_name(filename)):
        add("low", "filename", f"file name has {why}: \"{Path(filename).name}\"", "Name it like 'FirstName-LastName-Resume" + ext + "'.")
    issues.sort(key=lambda i: SEVERITIES.index(i["severity"]))
    return {"file": Path(filename).name, "size": len(data), "issues": issues, "text": text[:8000], "note": note}
