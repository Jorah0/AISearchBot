"""Mail attachments. Outgoing: only an employer-safe set from the job's folder (the generated resume / cover letter and
files you put in its attach/ folder), validated on propose, before the Inbox claim and again at send. Incoming: kept
types only, size and count capped, saved under the job folder with Mark-of-the-Web, never opened, previewed or run.

Never attachable: .md/.txt/.json/.ics (interview_prep.md, offer.md, research.md, mock_interview.md, gap.json and the
.ics files carry private notes and the salary floor), mail/ (received files), history/ (old versions)."""
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .config import HOME

OUT_FIXED = ("resume.pdf", "resume.docx", "cover_letter.pdf", "cover_letter.docx")  # top level of the job folder
OUT_DIR = "attach"  # user-placed extras, one level deep
OUT_TYPES = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
IN_TYPES = {".pdf", ".docx", ".odt", ".txt", ".png", ".jpg", ".jpeg", ".gif", ".ics", ".csv", ".xlsx"}  # no .doc/.rtf: macros
TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".txt": "text/plain", ".csv": "text/csv", ".ics": "text/calendar",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         ".odt": "application/vnd.oasis.opendocument.text"}  # fixed, not mimetypes: the Windows registry varies
EXT_FOR = {v: k for k, v in TYPES.items()} | {"image/jpeg": ".jpg"}
MAX_FILE = 10_000_000  # per file, in and out
MAX_OUT_TOTAL = 10_000_000  # ponytail: raw bytes; base64 adds ~37% -> ~13.7 MB, under Outlook.com's 20 MB message cap
MAX_IN_TOTAL = 25_000_000  # per incoming message
MAX_COUNT = 10
MAX_DOCX_XML = 20_000_000  # a .docx whose text part unpacks larger than this is refused (zip bomb)
RESERVED = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.I)
ONLY = ("only resume.pdf / .docx, cover_letter.pdf / .docx, or a pdf, docx, png or jpg you put in this job's attach/ "
        "folder can be attached")


def safe_name(name, fallback: str = "attachment") -> str:
    """Basename only; no control characters or \\ / : * ? " < > |; spaces collapsed; no leading or trailing dots; the
    extension kept; at most 100 characters; Windows reserved names (CON, NUL, COM1...) get a leading underscore."""
    n = re.split(r"[\\/]", str(name or ""))[-1]
    n = re.sub(r'[\x00-\x1f\x7f:*?"<>|]', "", n)
    n = " ".join(n.split()).strip(". ") or fallback
    stem, suf = os.path.splitext(n)
    suf = suf[:12]
    n = stem[:100 - len(suf)] + suf
    return "_" + n if RESERVED.fullmatch(n) else n


def _dir(job) -> Path:
    from .resume import app_dir

    return app_dir(job)


def _ctype(name: str) -> str:
    return TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def attachable(job) -> list[dict]:
    """Files a mail for this job may carry: the OUT_FIXED names that exist, plus files directly in attach/ with a
    suffix in OUT_TYPES. Nothing else. [{"name": relative posix path, "size", "mtime", "type", "blocked"?}], newest
    first. blocked: why resolve() would refuse it (the salary-floor guard), so the Inbox greys it out instead of offering
    a file that Approve always refuses."""
    d = _dir(job)
    extra = d / OUT_DIR
    files = [d / n for n in OUT_FIXED] + (sorted(extra.iterdir()) if extra.is_dir() else [])
    out = []
    for f in files:
        if f.is_file() and not f.is_symlink() and f.suffix.lower() in OUT_TYPES:
            st = f.stat()
            row = {"name": f.relative_to(d).as_posix(), "size": st.st_size, "mtime": st.st_mtime, "type": _ctype(f.name)}
            try:
                _screen(f, d)
            except SystemExit as e:
                row["blocked"] = str(e)
            out.append(row)
    return sorted(out, key=lambda x: -x["mtime"])


def _allowed(name: str) -> bool:
    if name in OUT_FIXED:
        return True
    parts = PurePosixPath(name).parts
    return (bool(re.fullmatch(rf"{OUT_DIR}/[^/\\:\x00]+", name)) and len(parts) == 2
            and parts[1] not in (".", "..") and Path(name).suffix.lower() in OUT_TYPES)


def _docx_text(p: Path) -> str:
    import zipfile

    from .extras import import_document

    try:
        with zipfile.ZipFile(p) as z:
            if z.getinfo("word/document.xml").file_size > MAX_DOCX_XML:
                raise SystemExit(f"{p.name}: its text is too large to check (over 20 MB unpacked); attach a PDF instead")
    except (zipfile.BadZipFile, KeyError):
        raise SystemExit(f"{p.name} is not a valid .docx") from None
    return import_document(p.read_bytes(), p.name)


def _screen(p: Path, d: Path) -> None:
    """The salary-floor guard over what an attachment says: the resume / cover-letter text it was made from, and the
    text of any .docx. attach/ PDFs and images are your own files and are not read."""
    from .drafts import leaks

    texts = []
    if p.parent == d and p.stem in ("resume", "cover_letter") and (d / f"{p.stem}.md").is_file():
        texts.append((d / f"{p.stem}.md").read_text(encoding="utf-8", errors="replace"))
    if p.suffix.lower() == ".docx":
        texts.append(_docx_text(p))
    if any(leaks(t) for t in texts):
        raise SystemExit(f"{p.name} names your salary floor (or your private Preferences), so it cannot be attached: "
                         "edit it out of the document and try again")


def resolve(job, names) -> list[Path]:
    """The attachment list of a send_email payload, validated; SystemExit otherwise (approvals._precheck refuses it
    before the claim, so the item stays pending). Each name is one of OUT_FIXED or exactly 'attach/<name>'; it must
    resolve to a regular file inside the job folder and HOME with no link on the way (symlinks and junctions are
    refused), of an allowed type, within the size caps, and pass the salary-floor guard."""
    if names in (None, "", []):
        return []
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise SystemExit("attachments must be a list of file names from this job's folder")
    names = list(dict.fromkeys(names))  # duplicates dropped
    if len(names) > MAX_COUNT:
        raise SystemExit(f"at most {MAX_COUNT} attachments per mail")
    if job is None:
        raise SystemExit("attachments need a job: they come from that job's folder")
    d, home = _dir(job).resolve(), HOME.resolve()
    out, total = [], 0
    for n in names:
        if not _allowed(n):
            raise SystemExit(f"{n[:80]!r} cannot be attached: {ONLY}")
        p = d / n
        try:
            real = p.resolve(strict=True)
        except OSError:
            raise SystemExit(f"{n}: not found in this job's folder (moved or deleted?)") from None
        if (os.path.normcase(real) != os.path.normcase(p) or not real.is_relative_to(d) or not real.is_relative_to(home)
                or not real.is_file()):
            raise SystemExit(f"{n[:80]!r} cannot be attached: it is a link or not a plain file in this job's folder")
        size = real.stat().st_size
        if size > MAX_FILE:
            raise SystemExit(f"{n}: over {MAX_FILE // 1_000_000} MB, too large to attach")
        total += size
        if total > MAX_OUT_TOTAL:
            raise SystemExit(f"attachments over {MAX_OUT_TOTAL // 1_000_000} MB together: remove one")
        _screen(real, d)
        out.append(real)
    return out


def suggest(job) -> list[str]:
    """The tailored resume to pre-tick on a draft you asked for (pdf before docx); [] when none passes resolve."""
    for n in ("resume.pdf", "resume.docx"):
        if (_dir(job) / n).is_file():
            try:
                resolve(job, [n])
                return [n]
            except SystemExit:
                return []
    return []


def attach(msg, paths: list[Path]) -> list[dict]:
    """Add each file to an EmailMessage (after set_content); [{"name", "size", "type"}] for the mail record."""
    info = []
    for p in paths:
        data, name, ctype = Path(p).read_bytes(), safe_name(Path(p).name), _ctype(Path(p).name)
        main, sub = ctype.split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
        info.append({"name": name, "size": len(data), "type": ctype})
    return info


# ----------------------------------------------------------------------------- incoming
def _leaves(m):
    """Leaf parts, without descending into forwarded mail (message/rfc822 is yielded whole, then skipped)."""
    if m.get_content_type() == "message/rfc822" or not m.is_multipart():
        yield m
        return
    for p in m.get_payload() or []:
        yield from _leaves(p)


def extract(msg) -> tuple[list[dict], list[dict]]:
    """Incoming parts worth keeping: ([{"name", "type", "data"}], [{"name", "skipped": why}]). An attachment (or an
    inline part with a filename that is not an image), of a type in IN_TYPES, at most MAX_FILE each, MAX_IN_TOTAL and
    MAX_COUNT per message. A text/calendar part is kept as .ics even without a filename. Forwarded mail is skipped."""
    items: list[dict] = []
    skipped: list[dict] = []
    total = 0
    for part in _leaves(msg):
        ctype, disp, fname = part.get_content_type(), part.get_content_disposition(), part.get_filename()
        if ctype == "message/rfc822":
            skipped.append({"name": safe_name(fname or "forwarded message"), "skipped": "forwarded mail not kept"})
            continue
        if not (ctype == "text/calendar" or disp == "attachment"
                or (disp == "inline" and fname and not ctype.startswith("image/"))):
            continue  # the body itself, or an inline logo
        name = safe_name(fname or ("invite" if ctype == "text/calendar" else "attachment"))
        suf = Path(name).suffix.lower()
        if not suf and (suf := EXT_FOR.get(ctype, "")):  # no extension: the declared type names one
            name += suf
        if suf not in IN_TYPES:
            skipped.append({"name": name, "skipped": "type not kept"})
            continue
        data = part.get_payload(decode=True) or b""
        if len(data) > MAX_FILE:
            skipped.append({"name": name, "skipped": f"over {MAX_FILE // 1_000_000} MB"})
        elif len(items) >= MAX_COUNT:
            skipped.append({"name": name, "skipped": f"more than {MAX_COUNT} attachments"})
        elif total + len(data) > MAX_IN_TOTAL:
            skipped.append({"name": name, "skipped": f"over {MAX_IN_TOTAL // 1_000_000} MB for this message"})
        else:
            total += len(data)
            items.append({"name": name, "type": TYPES[suf], "data": data})
    return items, skipped


MOTW = "[ZoneTransfer]\r\nZoneId=3\r\n"  # "from the internet": Office opens it in Protected View, SmartScreen applies


def save(items: list[dict], job, message_id: str, when: datetime) -> list[dict]:
    """Write extract() items under applications/<job>/mail/<YYYYMMDD>-<8 hex>/ (never overwriting: a clash gets ' (2)')
    with Mark-of-the-Web on Windows. Files are only written, never opened, run or previewed.
    [{"name", "size", "type", "path": relative to HOME}]"""
    if not items or job is None:
        return []
    d = _dir(job) / "mail" / f"{when:%Y%m%d}-{hashlib.sha1(str(message_id).encode()).hexdigest()[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for it in items:
        name = safe_name(it["name"])
        stem, suf = os.path.splitext(name)
        for i in range(1, 100):
            path = d / (name if i == 1 else f"{stem} ({i}){suf}")
            try:
                with open(path, "xb") as f:
                    f.write(it["data"])
                break
            except FileExistsError:
                continue
        else:
            continue  # ponytail: 99 same-named files in one message; the rest are left in the mailbox
        if sys.platform.startswith("win"):
            try:
                with open(f"{path}:Zone.Identifier", "w", encoding="ascii", newline="") as f:
                    f.write(MOTW)
            except OSError:
                pass  # not NTFS (FAT, a network share): the file is still never opened by Lodestar
        out.append({"name": path.name, "size": len(it["data"]), "type": it["type"],
                    "path": path.relative_to(HOME).as_posix()})
    return out


def _dt(line: str) -> datetime | None:
    head, _, value = line.partition(":")
    params = {k.upper(): v for k, _, v in (p.partition("=") for p in head.split(";")[1:])}
    m = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", value.strip())
    if not m or params.get("VALUE", "").upper() == "DATE":
        return None  # a date-only value is no interview time
    dt = datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S")
    if m[3]:
        return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    if tz := params.get("TZID", "").strip('"'):
        try:
            from zoneinfo import ZoneInfo

            return dt.replace(tzinfo=ZoneInfo(tz)).astimezone().replace(tzinfo=None)
        except Exception:  # "Eastern Standard Time" (Outlook) or no tzdata here: no time, never "taken as local"
            return None
    return dt  # floating time: local


def ics_start(items: list[dict]) -> datetime | None:
    """Local start time of the first VEVENT in the first kept .ics (RFC 5545 lines unfolded; first 200 lines)."""
    ics = next((it for it in items if it["name"].lower().endswith(".ics")), None)
    if not ics:
        return None
    lines: list[str] = []
    for ln in ics["data"][:200_000].decode("utf-8", "replace").splitlines():
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    event = False
    for ln in lines[:200]:
        u = ln.upper()
        if u.startswith("BEGIN:VEVENT"):
            event = True
        elif u.startswith("END:VEVENT"):
            return None
        elif event and (u.startswith("DTSTART:") or u.startswith("DTSTART;")):
            return _dt(ln)
    return None
