"""Reading resume files (blueprint 8.1, pass 31 move out of extras.py): .docx / .pdf / .odt / .rtf / .html /
.md / .txt to plain text. A PDF without a text layer is refused (no OCR, nothing guessed). Pure functions: no
network, no database. extras re-exports these names for older callers."""
import re
from pathlib import Path


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
        text = pdf_text(data)
        if len(text) < 40:  # blueprint 8.1: a scan is said, never guessed at (no OCR)
            raise SystemExit("this PDF has no text layer (a scan or a picture of a page): export it as text from the "
                             "program that made it, or paste the text in Profile")
        return text
    if ext in (".md", ".txt", ".markdown", ""):
        return data.decode("utf-8-sig", errors="replace").strip()  # -sig: a BOM from Notepad is not text
    if ext in (".html", ".htm"):
        return _html_text(data.decode("utf-8-sig", errors="replace"))
    if ext == ".odt":
        return _odt_text(data)
    if ext == ".rtf":
        return _rtf_text(data.decode("latin-1"))
    raise SystemExit(f"unsupported resume format '{ext}' (use .docx, .pdf, .odt, .rtf, .html, .md or .txt)")


def pdf_text(data: bytes) -> str:
    """A PDF's text layer as is (empty for a scan). SystemExit without pypdf; a broken PDF raises pypdf's error."""
    import io

    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit("PDF import needs pypdf: pip install pypdf  (or pip install -e .[pdf])") from None
    pages = PdfReader(io.BytesIO(data)).pages
    text = "\n".join((pg.extract_text() or "") for pg in pages).strip()
    if _word_per_line(text):  # some PDF writers place each word alone: plain mode then gives one word per line
        lay = "\n".join((pg.extract_text(extraction_mode="layout") or "") for pg in pages)
        text = "\n".join(" ".join(x.split()) for x in lay.splitlines() if x.strip())
    return text


def _word_per_line(text: str) -> bool:
    lines = [x for x in text.splitlines() if x.strip()]
    return len(lines) >= 12 and sum(len(x.split()) == 1 for x in lines) > 0.8 * len(lines)


def _html_text(html: str) -> str:
    """Visible text of an HTML resume, one line per block element; scripts and styles dropped."""
    from html.parser import HTMLParser

    class P(HTMLParser):
        BLOCK = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.skip = [""], 0

        def handle_starttag(self, tag, attrs):
            self.skip += tag in ("script", "style")
            if tag in self.BLOCK:
                self.out.append("")

        def handle_endtag(self, tag):
            self.skip -= tag in ("script", "style") and self.skip > 0
            if tag in self.BLOCK:
                self.out.append("")

        def handle_data(self, d):
            if not self.skip:
                self.out[-1] += d

    p = P()
    p.feed(html)
    return "\n".join(" ".join(x.split()) for x in p.out if x.strip())


def _odt_text(data: bytes) -> str:
    """An OpenDocument text (.odt): its headings and paragraphs from content.xml, one line each."""
    import io
    import zipfile
    from xml.etree import ElementTree

    try:  # stdlib expat: no external entities fetched, entity expansion capped; and it is your own file
        root = ElementTree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("content.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise SystemExit("this .odt file could not be read (not an OpenDocument text)") from None
    ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    lines = ["".join(el.itertext()) for el in root.iter() if el.tag in (ns + "h", ns + "p")]
    return "\n".join(" ".join(x.split()) for x in lines if x.strip())


def _rtf_text(rtf: str) -> str:
    """Plain text of an RTF resume: \\par -> new line, \\'xx -> the cp1252 character, groups like the font table
    dropped. ponytail: no tables or embedded objects; Word's 'Save as .docx' reads better."""
    out, depth, skip_at, i = [], 0, None, 0
    while i < len(rtf):
        c = rtf[i]
        if c == "{":
            depth += 1
            if skip_at is None and re.match(r"\{\\(?:\*|fonttbl|colortbl|stylesheet|info|pict)", rtf[i:]):
                skip_at = depth
            i += 1
        elif c == "}":
            if skip_at == depth:
                skip_at = None
            depth -= 1
            i += 1
        elif c == "\\":
            if rtf[i + 1:i + 2] == "'":
                if skip_at is None:
                    out.append(bytes([int(rtf[i + 2:i + 4], 16)]).decode("cp1252", errors="replace"))
                i += 4
                continue
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?|\\(.)", rtf[i:])
            word, sym = (m[1], m[3]) if m else (None, None)
            if skip_at is None and word in ("par", "line"):
                out.append("\n")
            elif skip_at is None and sym and sym in "\\{}":
                out.append(sym)
            i += len(m[0]) if m else 1
        else:
            if skip_at is None and c not in "\r\n":
                out.append(c)
            i += 1
    return "\n".join(" ".join(ln.split()) for ln in "".join(out).splitlines()).strip()
