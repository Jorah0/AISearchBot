"""Deterministic resume renderers (the studio and its versions): one resolved document + one style -> an HTML page (the
preview, and what headless Edge prints to PDF), a .docx (python-docx), the master-profile markdown (re-importable), and
ATS plain text. All four read the same blocks(), so they say the same thing in the same order.

A resolved doc (studio.resolve): {"contact": {name, location, email, phone, linkedin, github, website}, "headline",
"summary", "sections": [{"kind", "title", "items": [catalogue entries with final bullets]} | {"kind": "skills",
"title", "groups": [{"label", "names"}]}]}. Every text in it is the candidate's own or passed the studio's guards; nothing
here writes or rewrites content."""
import re
from html import escape
from pathlib import Path

from . import lint, profile

FONTS = {"Calibri": "sans", "Arial": "sans", "Helvetica": "sans", "Verdana": "sans", "Tahoma": "sans", "Georgia": "serif",
         "Cambria": "serif", "Garamond": "serif", "Times New Roman": "serif", "Book Antiqua": "serif"}  # ATS-safe, installed
ACCENTS = {"navy": "#1F3A5F", "blue": "#1F4E79", "teal": "#0F6E6E", "green": "#2E6B3A", "burgundy": "#7A1F2B",
           "gray": "#4A4A4A", "grey": "#4A4A4A", "black": "#000000"}
DATE_FORMATS = ("Mar 2021", "March 2021", "03/2021", "2021-03", "2021")
KINDS = ("summary", "experience", "skills", "education", "certifications", "projects", "awards", "publications",
         "volunteering", "patents", "speaking", "languages", "links", "interests", "other")
FORMATS = ("pdf", "docx", "md", "txt", "html")
BLOCK_KINDS = ("experience", "education", "projects", "volunteering")  # a role line with dates, then bullets
CHOICES = {"paper": ("letter", "a4"), "date_format": DATE_FORMATS, "contact_layout": ("one_line", "two_lines", "centered"),
           "heading_case": ("upper", "title"), "density": ("compact", "normal", "airy"),
           "bullet": ("disc", "circle", "square", "dash", "none")}
RANGES = {"size": (9.5, 12.0), "heading_size": (1.0, 1.6), "margins": (0.4, 1.25), "line_spacing": (1.0, 1.5),
          "para_spacing": (0.0, 14.0)}  # para_spacing: points after a paragraph / bullet (unset: from density)
INTS = {"pages": (0, 2), "bullets_per_role": (0, 10)}
VISUAL = ("font", "size", "heading_size", "accent", "margins", "density", "bullet", "para_spacing")  # a template resets these
BULLETS = {"circle": "circle", "square": "square", "dash": '"- "', "none": "none"}  # CSS list-style-type (disc: the default)
GLYPHS = {"circle": "◦ ", "square": "▪ ", "dash": "- ", "none": ""}  # the .docx: a prefix instead of Word's List Bullet
DEFAULTS = {"template": "classic", "heading_size": 1.25, "line_spacing": 1.15, "paper": "letter", "date_format": "Mar 2021",
            "contact_layout": "one_line", "heading_case": "upper", "density": "normal", "bullet": "disc", "pages": 0,
            "sections": list(KINDS), "bullets_per_role": 0, "formats": ["pdf", "docx"]}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")


def preset(name: str) -> dict:
    """The look of a resume.STYLES preset in style-spec keys (the one mapping from STYLES' color tuple / margin)."""
    from .resume import STYLES

    s = STYLES.get(name) or STYLES["classic"]
    hs = s["heading_sizes"][1] / s["size"] if s.get("heading_sizes") else DEFAULTS["heading_size"]
    return {"font": s["font"], "size": s["size"], "accent": "#%02X%02X%02X" % s.get("color", (0, 0, 0)),
            "margins": s.get("margin", 0.75), "density": "compact" if s.get("tight") else "normal",
            "heading_size": round(hs, 2)}


def as_preset(look: dict) -> dict:
    """A studio look in resume.STYLES form, for the markdown exports (the drawer's Export, the master resume)."""
    st = full_style(look)
    acc = tuple(int(st["accent"][i:i + 2], 16) for i in (1, 3, 5))
    hs = st["heading_size"]
    return {"font": st["font"], "heading_font": st["font"], "size": st["size"], "margin": st["margins"],
            "paper": st["paper"], "tight": st["density"] == "compact",
            "heading_sizes": (round(st["size"] * hs * 1.6), round(st["size"] * hs, 1), st["size"])} | (
        {"color": acc} if any(acc) else {})


def _list(v) -> list[str]:
    return [x.strip().lower() for x in (v.split(",") if isinstance(v, str) else v if isinstance(v, list) else []) if str(x).strip()]


def clean_style(d, notes: list | None = None, strict: bool = False) -> dict:
    """The valid part of a style dict (an AI plan's, the requirements form, CLI flags, the resume_look pref). A refused
    value is dropped with a note ("font 'Comic Sans' is not ATS-safe"); strict (your own input) raises it instead."""
    from .resume import STYLES

    out: dict = {}

    def bad(msg: str) -> None:
        if strict:
            raise SystemExit(msg)
        if notes is not None:
            notes.append(msg)

    for k, v in (d.items() if isinstance(d, dict) else ()):
        if v is None or v == "":
            continue
        if k == "template":
            (out.__setitem__(k, str(v).lower()) if str(v).lower() in STYLES else bad(f"template '{str(v)[:30]}' is not one of {', '.join(STYLES)}"))
        elif k == "font":
            hit = next((f for f in FONTS if f.lower() == str(v).strip().lower()), None)
            out[k] = hit if hit else bad(f"font '{str(v)[:30]}' is not ATS-safe: use one of {', '.join(FONTS)}")
        elif k in RANGES:
            lo, hi = RANGES[k]
            try:
                f = float(v)
            except (TypeError, ValueError):
                f = None
            out[k] = f if f is not None and lo <= f <= hi else bad(f"{k} {str(v)[:20]} is outside {lo:g}-{hi:g}")
        elif k in INTS:
            lo, hi = INTS[k]
            try:
                n = int(v)
            except (TypeError, ValueError):
                n = None
            out[k] = n if n is not None and lo <= n <= hi else bad(f"{k} {str(v)[:20]} is outside {lo}-{hi}")
        elif k == "accent":
            s = str(v).strip().lower()
            s = ACCENTS.get(s, s if s.startswith("#") else "#" + s)
            out[k] = s.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", s) else bad(f"accent '{str(v)[:20]}' is not #rrggbb or one of {', '.join(ACCENTS)}")
        elif k in CHOICES:
            s = str(v).strip()
            hit = next((c for c in CHOICES[k] if c.lower() == s.lower()), None)
            out[k] = hit if hit else bad(f"{k} '{s[:20]}' is one of: {', '.join(CHOICES[k])}")
        elif k == "sections":
            got = [x for x in _list(v) if x in KINDS]
            if len(got) < len(_list(v)):
                bad(f"unknown section(s) {', '.join(x for x in _list(v) if x not in KINDS)[:80]}: sections are {', '.join(KINDS)}")
            out[k] = list(dict.fromkeys(got)) if got else bad("sections needs at least one section")
        elif k == "formats":
            got = [x for x in _list(v) if x in FORMATS]
            if len(got) < len(_list(v)):
                bad(f"formats are {', '.join(FORMATS)}")
            out[k] = list(dict.fromkeys(got)) if got else bad("formats needs at least one of " + ", ".join(FORMATS))
        else:
            bad(f"unknown style setting '{str(k)[:30]}'")
    return {k: v for k, v in out.items() if v is not None}


def full_style(*layers) -> dict:
    """Every style key: the defaults, the template's preset, then each (cleaned) layer in turn. A layer that picks a
    template resets the earlier layers' look (font, size, accent, ...), so 'modern' means modern."""
    from . import settings

    merged: dict = {}
    for layer in map(clean_style, layers):
        if layer.get("template"):
            merged = {k: v for k, v in merged.items() if k not in VISUAL}
        merged |= layer
    t = merged.get("template") or settings.pref("resume_style") or "classic"
    return DEFAULTS | {"template": t} | preset(t) | {k: v for k, v in merged.items() if k != "template"}


# ----------------------------------------------------------------------------- text of each entry
def fmt_date(s, date_format: str = "Mar 2021") -> str:
    """A date as the style asks; a bare year stays a year (no invented month), Present stays, the unparseable as written."""
    s = str(s or "").strip()
    if not s or re.fullmatch(r"\d{4}", s):
        return s
    if profile.CURRENT_RE.fullmatch(s):
        return "Present"
    m = lint._month(s, False)
    if m is None or (s[:1].isalpha() and s[:3].lower() not in lint.MONTHS):  # 'Summer 2019' is not January
        return s
    y, mo = (m - 1) // 12, (m - 1) % 12 + 1
    return {"Mar 2021": f"{MONTHS[mo - 1][:3]} {y}", "March 2021": f"{MONTHS[mo - 1]} {y}", "03/2021": f"{mo:02d}/{y}",
            "2021-03": f"{y}-{mo:02d}", "2021": str(y)}[date_format]


def span(e: dict, date_format: str) -> str:
    return " - ".join(x for x in (fmt_date(e.get("start"), date_format), fmt_date(e.get("end"), date_format)) if x)


def _join(*parts, sep=" - ") -> str:
    return sep.join(p for p in parts if p)


def entry_line(kind: str, e: dict, df: str) -> tuple[str, str, list[str]]:
    """(main text, dates, detail lines) of a block entry."""
    tech = [f"Technologies: {', '.join(e['technologies'])}"] if e.get("technologies") else []
    if kind == "experience":
        return _join(e.get("title"), _join(e.get("company"), e.get("location"), sep=", ")), span(e, df), tech
    if kind == "volunteering":
        return _join(e.get("role"), _join(e.get("organization"), e.get("location"), sep=", ")), span(e, df), []
    if kind == "education":
        main = _join(_join(e.get("degree"), e.get("field"), sep=", "), _join(e.get("school"), e.get("location"), sep=", "))
        return main, span(e, df), [f"Honors: {e['honors']}"] if e.get("honors") else []
    url = e.get("url") or ""
    return _join(e.get("name"), e.get("description")), span(e, df), ([url] if url and url not in (e.get("description") or "") else []) + tech


def item_line(kind: str, e: dict, df: str) -> str:
    """One line of a list kind (certifications, awards, publications, patents, speaking, links)."""
    date = f" ({fmt_date(e['date'], df)})" if e.get("date") else ""
    if kind == "links":
        return _join(e.get("label"), e.get("url"), sep=": ")
    first, second = profile.FIELDS[kind][0], profile.SECOND.get(kind)
    line = _join(e.get(first), e.get(second) if second else "") + date
    extra = {"certifications": [f"ID: {e['credential_id']}" if e.get("credential_id") else ""],
             "awards": [e.get("description") or ""], "publications": [e.get("authors") or ""]}.get(kind, [])
    return " | ".join(x for x in [line, *extra, e.get("url") or ""] if x)


def contact_parts(c: dict) -> list[str]:
    return [c[k] for k in ("location", "phone", "email", "linkedin", "github", "website") if c.get(k)]


def blocks(doc: dict, st: dict) -> list[tuple]:
    """The page as (kind, ...) blocks: name, contact (parts per line), headline, h2 (title, kind, index), entry (main,
    dates), detail, li, p. Every renderer but the markdown one reads these."""
    c, df = doc.get("contact") or {}, st["date_format"]
    out: list[tuple] = [("name", c.get("name") or "Resume")]
    parts = contact_parts(c)
    if st["contact_layout"] == "two_lines":
        top = [c[k] for k in ("location", "phone", "email") if c.get(k)]
        lines = [x for x in (top, [p for p in parts if p not in top]) if x]
    else:
        lines = [parts] if parts else []
    out += [("contact", ln) for ln in lines]
    if doc.get("headline"):
        out.append(("headline", doc["headline"]))
    for i, s in enumerate(doc.get("sections") or []):
        kind = s["kind"]
        out.append(("h2", s["title"], kind, i))
        if kind == "summary":
            out.append(("p", doc.get("summary") or ""))
        elif kind == "skills":
            groups = s.get("groups") or []
            out += [("p", _join(g["label"] if len(groups) > 1 or g["label"] != s["title"] else "", ", ".join(g["names"]), sep=": "))
                    for g in groups if g.get("names")]
        elif kind in ("languages", "interests"):
            names = [_join(e["name"], f"({e['proficiency']})" if e.get("proficiency") else "", sep=" ") for e in s["items"]]
            out.append(("p", ", ".join(names)))
        elif kind == "other":
            out += [("li", b) for e in s["items"] for b in e.get("bullets") or []]
        elif kind in BLOCK_KINDS:
            for e in s["items"]:
                main, dates, details = entry_line(kind, e, df)
                out += [("entry", main, dates)] + [("detail", d) for d in details] + [("li", b) for b in e.get("bullets") or []]
        else:
            out += [("li", item_line(kind, e, df)) for e in s["items"]]
    return out


DATES_RE = re.compile(r"^(.*?)\s*\(([^()]*\b(?:19|20)\d\d[^()]*)\)\s*$")  # '### Title - Company (2021-03 - Present)'


def fmt_span(s: str, date_format: str) -> str:
    """'2021-03 - Present', '2018-2021', 'Mar 2021 – now' -> both ends in the style's date format."""
    parts = re.split(r"\s*(?:–|—|\bto\b)\s*|\s+-\s+|(?<=\d)-(?=[A-Za-z])|(?<=\d{4})-(?=\d{4}\b)", s.strip())
    return " - ".join(fmt_date(p, date_format) for p in parts if p.strip()) if 0 < len(parts) <= 2 else s.strip()


def _contact_blocks(parts: list[str], st: dict) -> list[tuple]:
    if st["contact_layout"] == "two_lines" and len(parts) > 3:
        return [("contact", parts[:3]), ("contact", parts[3:])]
    return [("contact", parts)] if parts else []


def md_blocks(md: str, st: dict, kind: str = "resume") -> list[tuple]:
    """Any generated markdown document (a tailored resume.md, the master resume, form answers, prep notes) as the same
    blocks blocks() makes: the first '# ' line is the name / title, a resume's contact line right under it, '## ' a
    section, '### Title (dates)' a role line with its dates in the style's format, '- ' a bullet, the rest paragraphs."""
    from .resume import _blocks

    out: list[tuple] = []
    sec = 0
    for k, lvl, text in _blocks(md):
        if k == "h" and lvl == 1 and not out:
            out.append(("name", text))
        elif k == "p" and kind == "resume" and len(out) == 1 and out[0][0] == "name" and ("|" in text or "@" in text):
            out += _contact_blocks([x.strip() for x in text.split("|") if x.strip() and x.strip() != out[0][1]], st)
        elif k == "h" and lvl <= 2:
            out.append(("h2", text, profile._section_of("## " + text) or "other", sec))
            sec += 1
        elif k == "h":
            m = DATES_RE.match(text)
            out.append(("entry", m[1].strip(), fmt_span(m[2], st["date_format"])) if m else ("entry", text, ""))
        else:
            out.append((k, text))
    return out


CLOSING_RE = re.compile(r"(?i)^(?:sincerely|best regards|kind regards|warm regards|regards|best|thank you|thanks|respectfully"
                        r"|yours (?:truly|sincerely|faithfully)|with appreciation)\b[,.!]?\s*$")
SALUTE_RE = re.compile(r"(?i)^(?:dear|hello|hi|to whom)\b")
DATE_LINE_RE = re.compile(r"^(?:[A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]+ \d{4}|\d{4}-\d{2}-\d{2})$")


def letter_parts(text: str) -> dict:
    """A letter (resume.letter's layout, or any plain one) read into {name, contact, date, recipient, body, closing}:
    the contact line, the date line, the address block before 'Dear ...', the paragraphs, and the sign-off from
    'Sincerely,' to the end. A part the letter does not have is empty."""
    paras: list[list[str]] = [[]]
    for ln in text.replace("\r", "").splitlines():
        s = ln.strip().lstrip("#").strip() if ln.strip().startswith("#") else ln.strip()
        if s:
            paras[-1].append(s)
        elif paras[-1]:
            paras.append([])
    paras = [p for p in paras if p]
    out = {"name": "", "contact": [], "date": "", "recipient": [], "body": [], "closing": [], "after": []}
    if paras and ("|" in paras[0][0] or "@" in paras[0][0]):
        parts = [x.strip() for x in paras[0][0].split("|") if x.strip()]
        if parts and not re.search(r"[@\d]", parts[0]):
            out["name"] = parts.pop(0)
        out["contact"] = parts
        rest = paras[0][1:]
        paras = ([rest] if rest else []) + paras[1:]
    if paras and DATE_LINE_RE.match(paras[0][0]):
        out["date"] = paras[0][0]
        paras = ([paras[0][1:]] if paras[0][1:] else []) + paras[1:]
    if len(paras) > 1 and not SALUTE_RE.match(paras[0][0]) and any(SALUTE_RE.match(p[0]) for p in paras[1:3]):
        out["recipient"] = paras.pop(0)
    for i, p in enumerate(paras):
        if CLOSING_RE.match(p[0]) or (len(p) > 1 and CLOSING_RE.match(p[-2])):
            cut = 0 if CLOSING_RE.match(p[0]) else len(p) - 2
            out["closing"], out["after"] = p[cut:], [" ".join(q) for q in paras[i + 1:]]  # after: a P.S. stays
            paras = paras[:i] + ([p[:cut]] if cut else [])
            break
    out["body"] = [" ".join(p) for p in paras]
    return out


def letter_blocks(text: str, st: dict, opt: dict | None = None) -> list[tuple]:
    """A letter's blocks with the viewer's letter options: date (False leaves the date line out), recipient (lines
    replacing the address block), signature (lines replacing the sign-off). Empty options keep the letter's own."""
    opt, p = opt or {}, letter_parts(text)
    lines = lambda v: [x.strip() for x in str(v).splitlines() if x.strip()]  # noqa: E731
    out: list[tuple] = [("name", p["name"])] if p["name"] else []
    out += _contact_blocks(p["contact"], st)
    if p["date"] and opt.get("date", True) is not False:
        out.append(("p", p["date"]))
    if rec := lines(opt.get("recipient") or "") or p["recipient"]:
        out.append(("lines", rec))
    out += [("p", b) for b in p["body"]]
    if sig := lines(opt.get("signature") or "") or p["closing"]:
        out.append(("lines", sig))
    return out + [("p", b) for b in p.get("after") or []]


# ----------------------------------------------------------------------------- renderers
def _link(text: str) -> str:
    """An <a> only for http(s) and email values (web.http_only's rule); anything else is plain text."""
    t = escape(text)
    if re.fullmatch(r"https?://\S+", text, re.I):
        return f'<a href="{t}">{t}</a>'
    if lint.EMAIL.fullmatch(text):
        return f'<a href="mailto:{t}">{t}</a>'
    return t


def css(st: dict, letter: bool = False) -> str:
    """The stylesheet: @page size and margins, ligatures off (Chromium would write 'ﬂ' into the PDF's text layer), flex
    role lines with the dates after a real space (no floats: extraction order stays title, then dates)."""
    fam = f'"{st["font"]}", ' + ("Georgia, serif" if FONTS.get(st["font"]) == "serif" else "Arial, sans-serif")
    li, h2, h3 = {"compact": (1, 6, 3), "normal": (2, 10, 5), "airy": (4, 14, 8)}[st["density"]]
    li = st["para_spacing"] if st.get("para_spacing") is not None else li
    bullet = st.get("bullet") or "disc"
    lst = f"ul{{list-style-type:{BULLETS[bullet]}{';padding-left:0' if bullet == 'none' else ''}}}" if bullet != "disc" else ""
    acc, hs, m = st["accent"], st["heading_size"], st["margins"]
    align = "center" if st["contact_layout"] == "centered" else "left"
    width = 8.27 if st["paper"] == "a4" else 8.5
    return (f"@page{{size:{st['paper']};margin:{m}in}}html{{background:#fff}}"
            f"body{{margin:0;color:#000;font-family:{fam};font-size:{st['size']}pt;line-height:{st['line_spacing']};"
            "font-variant-ligatures:none}"
            f"h1{{font-size:{hs * 1.6:.2f}em;color:{acc};margin:0 0 2pt;text-align:{align}}}"
            f".contact,.headline{{margin:0 0 2pt;text-align:{align}}}.headline{{font-weight:bold}}"
            f"h2{{font-size:{hs}em;color:{acc};text-transform:{'uppercase' if st['heading_case'] == 'upper' else 'none'};"
            f"border-bottom:1px solid {acc};margin:{h2}pt 0 3pt;padding-bottom:1pt;break-after:avoid}}"
            f"h3{{display:flex;justify-content:space-between;gap:12pt;font-size:1em;margin:{h3}pt 0 1pt;break-after:avoid}}"
            f".dates{{white-space:nowrap;font-weight:normal}}p{{margin:0 0 {li}pt}}.detail{{font-style:italic}}"
            f"ul{{margin:0;padding-left:16pt}}li{{margin:0 0 {li}pt;break-inside:avoid}}a{{color:inherit;text-decoration:none}}"
            + lst + (f".lines{{margin:0 0 {max(li, 8)}pt}}.letter p{{margin:0 0 {max(li, 8)}pt}}" if letter else "")
            + f"@media screen{{body{{max-width:{width}in;margin:0 auto;padding:{m}in;box-sizing:border-box}}}}")


def to_html(doc: dict, st: dict) -> str:
    """The page: semantic h1 / h2 / h3 / ul, every text escaped, no script. data-section on each h2 (the viewer jumps
    from a section to its editor)."""
    return page_html(blocks(doc, st), st, (doc.get("contact") or {}).get("name") or "Resume")


def page_html(bl: list[tuple], st: dict, title: str = "Resume", letter: bool = False) -> str:
    """Blocks (blocks(), md_blocks(), letter_blocks()) -> the HTML page every preview and every PDF comes from."""
    body, in_list = [], False
    for b in bl:
        if in_list != (b[0] == "li"):
            body.append("<ul>" if b[0] == "li" else "</ul>")
            in_list = b[0] == "li"
        if b[0] == "name":
            body.append(f"<h1>{escape(b[1])}</h1>")
        elif b[0] == "contact":
            body.append('<p class="contact">' + " | ".join(_link(x) for x in b[1]) + "</p>")
        elif b[0] == "headline":
            body.append(f'<p class="headline">{escape(b[1])}</p>')
        elif b[0] == "h2":
            body.append(f'<h2 data-section="{b[3]}">{escape(b[1])}</h2>')
        elif b[0] == "entry":
            body.append(f"<h3><span>{escape(b[1])}</span>" + (f' <span class="dates">{escape(b[2])}</span>' if b[2] else "") + "</h3>")
        elif b[0] == "detail":
            body.append(f'<p class="detail">{_link(b[1])}</p>')
        elif b[0] == "lines":  # an address block or a sign-off: one paragraph, a line each
            body.append('<p class="lines">' + "<br>".join(escape(x) for x in b[1]) + "</p>")
        elif b[0] in ("li", "p"):
            body.append(f"<{b[0]}>{escape(b[1])}</{b[0]}>")
    body += ["</ul>"] if in_list else []
    cls = ' class="letter"' if letter else ""
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
            f"<style>{css(st, letter)}</style></head><body{cls}>\n" + "\n".join(body) + "\n</body></html>\n")


def to_txt(doc: dict, st: dict) -> str:
    """ATS plain text: UPPERCASE headings, '- ' bullets, ASCII hyphens, no markdown."""
    return page_txt(blocks(doc, st))


def page_txt(bl: list[tuple], letter: bool = False) -> str:
    """Blocks -> plain text; a letter keeps a blank line between its paragraphs."""
    out: list[str] = []
    for b in bl:
        if letter and b[0] in ("p", "lines") and out:
            out.append("")
        if b[0] == "contact":
            out.append(" | ".join(b[1]))
        elif b[0] == "lines":
            out += ([] if letter else [""]) + list(b[1])
        elif b[0] == "h2":
            out += ["", b[1].upper()]
        elif b[0] == "entry":
            out += ["", _join(b[1], b[2], sep=" | ")]
        elif b[0] == "li":
            out.append(f"- {b[1]}")
        else:
            out.append(b[1])
    text = "\n".join(out).strip() + "\n"
    return text.translate({0x2013: "-", 0x2014: "-", 0x2022: "-", 0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"'})


def to_md(doc: dict, st: dict) -> str:
    """The master-profile line format (profile.extract_heuristic reads it back), in the document's section order."""
    c = doc.get("contact") or {}
    out = [f"# {c.get('name') or 'Resume'}", " | ".join(x for x in [c.get("name"), *contact_parts(c)] if x)]
    if doc.get("headline") and not any(s["kind"] == "summary" for s in doc.get("sections") or []):
        out += ["", "## Summary", doc["headline"]]
    for s in doc.get("sections") or []:
        out += ["", f"## {s['title']}"]
        if s["kind"] == "summary":
            out += [x for x in (doc.get("headline"), doc.get("summary")) if x]
        elif s["kind"] == "skills":
            groups = s.get("groups") or []
            out += [f"- {g['label'] + ': ' if len(groups) > 1 or g['label'] != s['title'] else ''}{', '.join(g['names'])}"
                    for g in groups if g.get("names")]
        else:
            out += [ln for e in s["items"] for ln in profile._render_item(s["kind"], e)]
    return "\n".join(out).strip() + "\n"


def _border(style, color: str) -> None:
    """A bottom rule under a paragraph style (Word's w:pBdr), the h2 line of the HTML page."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ppr = style.element.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", color.lstrip("#"))):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    ppr.append(bdr)


def _docx_styles(d, st: dict) -> None:
    from docx.shared import Pt, RGBColor

    from .resume import _font

    acc = RGBColor.from_string(st["accent"].lstrip("#").upper())
    after = {"compact": 1, "normal": 2, "airy": 4}[st["density"]]
    normal = d.styles["Normal"]
    _font(normal, st["font"])
    normal.font.size = Pt(st["size"])
    normal.paragraph_format.line_spacing = st["line_spacing"]
    normal.paragraph_format.space_after = Pt(st["para_spacing"] if st.get("para_spacing") is not None else after)
    for lvl, size, color in ((1, st["size"] * st["heading_size"] * 1.6, acc), (2, st["size"] * st["heading_size"], acc),
                             (3, st["size"], RGBColor(0, 0, 0))):
        h = d.styles[f"Heading {lvl}"]
        _font(h, st["font"])
        h.font.size, h.font.color.rgb, h.font.bold, h.font.italic = Pt(round(size * 2) / 2), color, True, False
        h.paragraph_format.space_before = Pt({1: 0, 2: after * 4 + 2, 3: after * 2 + 1}[lvl])
        h.paragraph_format.space_after = Pt(after)
    d.styles["Heading 2"].font.all_caps = st["heading_case"] == "upper"
    _border(d.styles["Heading 2"], st["accent"])


def to_docx(doc: dict, st: dict, path) -> Path:
    """python-docx from the same blocks: contact in the body (never a header), dates on a right tab stop (no table),
    bullets as List Bullet. A template.docx beside profile.md keeps its own styling, as for every .docx export."""
    return page_docx(blocks(doc, st), st, path)


def page_docx(bl: list[tuple], st: dict, path) -> Path:
    """Blocks -> .docx (path: a file path or a writable binary stream). A bullet style other than disc is a prefix
    glyph on an indented paragraph (Word's List Bullet draws only its own bullet)."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.shared import Inches

    template = profile.PROFILE.with_name("template.docx")
    d = Document(str(template)) if template.is_file() else Document()
    if not template.is_file():
        _docx_styles(d, st)
    sec = d.sections[0]
    sec.page_width, sec.page_height = (Inches(8.27), Inches(11.69)) if st["paper"] == "a4" else (Inches(8.5), Inches(11))
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(st["margins"])
    width = sec.page_width - sec.left_margin - sec.right_margin
    center = st["contact_layout"] == "centered"
    glyph = GLYPHS.get(st.get("bullet") or "disc")
    for b in bl:
        if b[0] == "name":
            p = d.add_heading(b[1], 1)
        elif b[0] == "contact":
            p = d.add_paragraph(" | ".join(b[1]))
        elif b[0] == "headline":
            p = d.add_paragraph()
            p.add_run(b[1]).bold = True
        elif b[0] == "h2":
            d.add_heading(b[1], 2)
            continue
        elif b[0] == "entry":
            p = d.add_paragraph(style="Heading 3")
            p.add_run(b[1])
            if b[2]:
                p.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
                p.add_run("\t" + b[2]).bold = False
            continue
        elif b[0] == "detail":
            d.add_paragraph().add_run(b[1]).italic = True
            continue
        elif b[0] == "lines":
            p = d.add_paragraph()
            for n, x in enumerate(b[1]):
                run = p.add_run(x)
                if n < len(b[1]) - 1:
                    run.add_break()
            continue
        elif b[0] == "li" and glyph is not None:
            p = d.add_paragraph(glyph + b[1])
            p.paragraph_format.left_indent, p.paragraph_format.first_line_indent = Inches(0.25), Inches(-0.15 if glyph else 0)
            continue
        else:
            d.add_paragraph(b[1], style="List Bullet" if b[0] == "li" else None)
            continue
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    d.save(path if hasattr(path, "write") else str(path))
    return path if hasattr(path, "write") else Path(path)


def name_part(s: str) -> str:
    """A name for a file name: ASCII letters and digits joined by '-' ('Łukasz Żak' -> 'Lukasz-Zak'), so it also fits
    an HTTP Content-Disposition header (latin-1) and every file system."""
    import unicodedata

    s = unicodedata.normalize("NFKD", str(s or "").replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40]


def filename(doc: dict, ext: str) -> str:
    """Dana-Smith-Resume.pdf (lint._odd_name passes it); Resume.pdf without a usable name."""
    name = name_part((doc.get("contact") or {}).get("name") or "")
    return f"{name}-Resume.{ext}" if name else f"Resume.{ext}"


def pages(pdf) -> int | None:
    """Page count by the lint.audit regex (no pypdf needed)."""
    from .resume import page_count

    return page_count(Path(pdf))
