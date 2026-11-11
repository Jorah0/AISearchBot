"""The document viewer (pass 17): every generated document - the master resume, studio versions, a job's tailored
resume, cover letter, form answers, offer notes, interview prep, research and mock-interview notes (its application
packet), and an unsaved counter-offer draft - shown and exported through one renderer path:

    markdown (or a studio version's resolved doc) + a look -> render.py blocks -> the HTML page (the paged preview, and
    what headless Edge prints to PDF) / python-docx / plain text / markdown

A document is named by a ref the UI sends back as it got it:
    {type: master} | {type: studio, vid} | {type: job, id, name, hist?} | {type: text, kind: letter|counter|notes, text,
    title?, job?, cite?}
Formatting per document (look keys, section order / hidden sections, letter options) is kept in viewer.json under the
ref's key; the saved look every document starts from is pref resume_look. Edited text is never written back except a
job document's Save (resume.save_doc, history kept); it only changes what is previewed and exported, and every export
re-runs the floor guard (employer-facing kinds: refused) and, for resumes, the fact guard on the lines you changed.
"""
import difflib
import hashlib
import io
import json
import re

from . import profile, render
from .config import HOME

STORE = HOME / "viewer.json"
CACHE = HOME / "cache" / "view"  # PDFs by the hash of the exact page Edge printed (re-render only on a change)
JOB_DOCS = {"resume.md": "resume", "cover_letter.md": "letter", "form_answers.md": "answers", "interview_prep.md": "notes",
            "research.md": "notes", "offer.md": "notes", "mock_interview.md": "notes"}
EMPLOYER = {"resume", "letter", "answers", "counter"}  # an employer reads these: a salary floor in them stops the export
FORMATS = ("pdf", "docx", "txt", "md", "html")
HIST_RE = re.compile(r"^[\w.-]{1,120}$")
CHECK_MAX = 400  # distinct changed resume lines the fact guard checks; more than that needs confirm as a whole


class Unconfirmed(SystemExit):
    """The fact guard found lines your profile does not support; export again with confirm to go ahead."""


def _load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def source(ref) -> dict:
    """{key, title, kind, md, doc, job, save, allow, base} of a document ref; anything unknown is refused, and no path
    ever comes from the caller (job documents by name from JOB_DOCS, history files by a checked name)."""
    ref = ref if isinstance(ref, dict) else {}
    t = str(ref.get("type") or "")
    if t == "master":
        f = profile.RESUMES / "master.md"
        if not f.is_file():
            raise SystemExit("no master resume yet: Profile > Master resume > Update now builds it")
        return {"key": "master", "title": "Master resume", "kind": "resume", "md": f.read_text(encoding="utf-8-sig"),
                "base": "Resume"}
    if t == "studio":
        from . import studio

        v = studio.version(ref.get("vid"))
        md = studio.file_path(v["vid"], v["files"]["md"]).read_text(encoding="utf-8-sig")
        look = {k: x for k, x in (v.get("style") or {}).items() if k in (*studio.LOOK_KEYS, "bullet", "para_spacing", "pages")}
        return {"key": f"studio:{v['vid']}", "title": f"Studio version {v['vid']}", "kind": "resume", "md": md,
                "doc": v.get("doc"), "base": "Resume", "vid": v["vid"], "look": look}  # it opens in its own look
    if t == "job":
        from . import db
        from .resume import app_dir

        job, name = db.get_job(int(ref.get("id") or 0)), str(ref.get("name") or "")
        if name not in JOB_DOCS:
            raise SystemExit(f"not a document the viewer shows: {name[:40]}")
        hist = str(ref.get("hist") or "")
        path = app_dir(job) / name
        if hist:
            path = app_dir(job) / "history" / hist
            if not HIST_RE.match(hist) or not hist.startswith(name.rsplit(".", 1)[0] + "-") or not hist.endswith(".md"):
                raise SystemExit(f"not an earlier version of {name}: {hist[:40]}")
        if not path.is_file():
            raise SystemExit(f"no {name} for job #{job['id']} yet")
        base = name.rsplit(".", 1)[0].replace("_", " ").title().replace(" ", "-")
        return {"key": f"job:{job['id']}:{name}" + (f":{hist}" if hist else ""), "kind": JOB_DOCS[name],
                "title": f"{name}{' (earlier: ' + hist + ')' if hist else ''} · {job['company']}", "job": job, "name": name,
                "md": path.read_text(encoding="utf-8-sig", errors="replace"), "save": not hist, "hist": hist,
                "base": "Resume" if name == "resume.md" else "Cover-Letter" if name == "cover_letter.md" else base}
    if t == "text":  # a draft shown in place (the counter-offer draft): rendered and exported, never stored
        kind = ref.get("kind") if ref.get("kind") in ("letter", "counter", "notes") else "notes"
        allow = ()
        if kind == "counter":
            from .apply import counter_figures

            allow = counter_figures(int(ref.get("job") or 0), ref.get("cite") or [])  # the only figures it may name
        return {"key": f"text:{kind}", "title": str(ref.get("title") or "Draft")[:80], "kind": kind,
                "md": str(ref.get("text") or "")[:60000], "allow": allow,
                "base": "Counter-Offer" if kind == "counter" else "Letter" if kind == "letter" else "Notes"}
    raise SystemExit("unknown document: type is master, studio, job or text")


def clean_opts(o) -> dict:
    """The per-document settings that are valid: look (render.clean_style; a bad value is refused), order and hide
    (section titles), letter {date, recipient, signature}."""
    o = o if isinstance(o, dict) else {}
    titles = lambda v: [str(x).strip()[:80] for x in v if str(x).strip()][:40] if isinstance(v, list) else []  # noqa: E731
    let = o.get("letter") if isinstance(o.get("letter"), dict) else {}
    letter = {k: v for k, v in {"date": let.get("date") is not False, "recipient": str(let.get("recipient") or "")[:400],
                                "signature": str(let.get("signature") or "")[:300]}.items() if v not in (True, "")}
    return {k: v for k, v in {"look": render.clean_style(o.get("look") or {}, strict=True), "order": titles(o.get("order")),
                              "hide": titles(o.get("hide")), "letter": letter}.items() if v}


def save_opts(ref, opts) -> dict:
    """Keep this document's formatting (empty: back to the saved look). The newest 300 documents are kept."""
    src, o = source(ref), clean_opts(opts)
    data = _load()
    data.pop(src["key"], None)
    if o:
        data[src["key"]] = o
    STORE.parent.mkdir(parents=True, exist_ok=True)
    profile._atomic_write(STORE, json.dumps(dict(list(data.items())[-300:]), indent=1, ensure_ascii=False))
    return o


def _style(src: dict, o: dict) -> dict:
    """The look in effect: your saved look, the document's own (a studio version's), then this document's changes."""
    from . import settings

    return render.full_style(settings.pref("resume_look") or {}, src.get("look") or {}, o.get("look") or {})


def _arrange(bl: list[tuple], o: dict) -> list[tuple]:
    """Sections reordered (o.order, by title; the rest keep their place after) and hidden (o.hide), renumbered."""
    if not o.get("order") and not o.get("hide"):
        return bl
    head, groups = [], []
    for b in bl:
        (groups.append([b]) if b[0] == "h2" else (groups[-1] if groups else head).append(b))
    order, hide = [x.lower() for x in o.get("order") or []], {x.lower() for x in o.get("hide") or []}
    key = lambda g: g[0][1].strip().lower()  # noqa: E731
    groups = sorted((g for g in groups if key(g) not in hide), key=lambda g: order.index(key(g)) if key(g) in order else len(order))
    out = list(head)
    for i, g in enumerate(groups):
        out += [("h2", g[0][1], g[0][2], i), *g[1:]]
    return out


def _blocks(src: dict, st: dict, o: dict, text: str | None) -> list[tuple]:
    if text is None and src.get("doc"):
        bl = render.blocks(src["doc"], st)  # a studio version, unedited: its own structure
    elif src["kind"] in ("letter", "counter"):
        bl = render.letter_blocks(src["md"] if text is None else text, st, o.get("letter"))
    else:
        bl = render.md_blocks(src["md"] if text is None else text, st, "resume" if src["kind"] == "resume" else "notes")
    return _arrange(bl, o)


def _sections(src: dict, st: dict, text: str | None) -> list[str]:
    return [b[1] for b in _blocks(src, st, {}, text) if b[0] == "h2"]


def _title(bl: list[tuple], src: dict) -> str:
    return next((b[1] for b in bl if b[0] == "name"), "") or src["title"]


def _facts() -> str:
    from .studio import catalogue_text

    try:
        return catalogue_text(profile.structured(), cap=0, contact=True)
    except (Exception, SystemExit):  # a template or unreadable profile: the master text is all there is
        return profile.master_text() if profile.PROFILE.is_file() else ""


def guards(src: dict, text: str | None, txt: str) -> dict:
    """{blocked, facts, personal}: blocked = the floor guard's refusal (employer kinds); facts = changed resume lines
    your profile does not support (resume.check_rewrite against the closest original line); personal = lines stating
    personal data (a resume)."""
    from .drafts import leaks

    out: dict = {"blocked": "", "facts": [], "personal": []}
    raw = src["md"] if text is None else text  # the rendered page and the text it came from (the MD export is the text)
    if src["kind"] in EMPLOYER and leaks(f"{txt}\n{raw}", src.get("allow") or ()):
        out["blocked"] = ("this document names your salary floor (or your private Preferences): edit it out before it "
                          "is exported or sent")
    if src["kind"] != "resume":
        return out
    out["personal"] = [f"line {n} states {hit[0]}: personal details do not belong on a resume"
                       for n, ln in enumerate(txt.splitlines(), 1) if (hit := profile.personal_label(ln))]
    if text is not None and text != src["md"]:
        from .resume import _plain, check_rewrite

        old = [_plain(x.strip().lstrip("-*# ").strip()) for x in src["md"].splitlines() if x.strip()]
        new = [_plain(x.strip().lstrip("-*# ").strip()) for x in text.splitlines() if x.strip()]
        facts, seen = _facts(), set(old)
        fresh = list(dict.fromkeys(x for x in new if x not in seen))  # every distinct changed line is checked
        for ln in fresh[:CHECK_MAX]:
            near = difflib.get_close_matches(ln, old, 1, 0.3)
            g = check_rewrite(near or [""], ln, facts)
            if g["flags"]:
                out["facts"].append(f'"{ln[:70]}": {g["why"]}')
        if len(fresh) > CHECK_MAX:  # never pass unchecked lines silently: they need your confirm like a flagged one
            out["facts"].append(f"{len(fresh) - CHECK_MAX} more changed line(s) were not checked (over {CHECK_MAX}): "
                                "confirm only if every one comes from your profile")
    return out


def view(ref, opts=None, text: str | None = None, save: bool = False, compare=None) -> dict:
    """The viewer's payload: the page, its text and markdown, the look in effect, the sections, the guards, the files
    it can export, what it can be compared with (and, with compare, that document's page and the differences)."""
    from .resume import engine_name, page_count

    src = source(ref)
    o = save_opts(ref, opts) if save else clean_opts(opts) if opts is not None else clean_opts(_load().get(src["key"]))
    st = _style(src, o)
    text = None if text is None else str(text)[:200000]
    bl = _blocks(src, st, o, text)
    html = render.page_html(bl, st, _title(bl, src), src["kind"] in ("letter", "counter"))
    txt = render.page_txt(bl, src["kind"] in ("letter", "counter"))
    cached = CACHE / f"{hashlib.sha256(html.encode()).hexdigest()[:20]}.pdf"  # printed before in this exact look
    out = {"key": src["key"], "title": src["title"], "kind": src["kind"], "employer": src["kind"] in EMPLOYER,
           "html": html, "txt": txt, "md": src["md"] if text is None else text, "look": st, "opts": o,
           "sections": _sections(src, st, text), "limit": st["pages"], "pages": page_count(cached) if cached.is_file() else None,
           "guards": guards(src, text, txt), "save": bool(src.get("save")), "engine": engine_name(),
           "compare": compare_options(src), "formats": list(FORMATS),
           "docs": job_documents(src["job"]["id"]) if src.get("job") else [], "choices": choices()}
    if compare:
        other = view(compare)
        out["other"] = {"title": other["title"], "html": other["html"], "look": other["look"]}
        out["diff"] = differences(other["md"], out["md"], src["kind"] == "resume")
    return out


def choices() -> dict:
    """The formatting panel's options (the same lists render.clean_style accepts)."""
    from .resume import STYLES

    return {"template": list(STYLES), "font": list(render.FONTS), "accent": render.ACCENTS,
            **{k: list(v) for k, v in render.CHOICES.items()}, "pages": [0, 1, 2], "ranges": render.RANGES}


def differences(a: str, b: str, resume: bool) -> list[str]:
    """What changed from a to b, in words: the master card's change summary for resumes, line counts for the rest."""
    if resume:
        from .studio import doc_diff

        try:
            return doc_diff(a, b)
        except (Exception, SystemExit):  # an odd layout: fall back to counting lines
            pass
    sa, sb = [x.strip() for x in a.splitlines() if x.strip()], [x.strip() for x in b.splitlines() if x.strip()]
    plus, minus = len([x for x in sb if x not in sa]), len([x for x in sa if x not in sb])
    return [f"+{plus} line(s), -{minus} line(s)"] if plus or minus else ["no difference in wording"]


def compare_options(src: dict) -> list[dict]:
    """Documents worth comparing with this one: for a resume, the master and the newest studio versions; for a job
    document, its earlier versions in history/."""
    out: list[dict] = []
    if src["kind"] == "resume":
        from . import studio

        if src["key"] != "master" and (profile.RESUMES / "master.md").is_file():
            out.append({"label": "Master resume", "ref": {"type": "master"}})
        out += [{"label": f"Studio {v['created'][:16].replace('T', ' ')} {(v.get('request') or 'general')[:40]}",
                 "ref": {"type": "studio", "vid": v["vid"]}} for v in studio.versions(15) if f"studio:{v['vid']}" != src["key"]]
    if src.get("job") and src.get("name"):
        from .resume import app_dir

        stem = src["name"].rsplit(".", 1)[0]
        hist = sorted((app_dir(src["job"]) / "history").glob(f"{stem}-*.md"), reverse=True)[:10]
        out += [{"label": f"earlier {h.stem[len(stem) + 1:]}", "ref": {"type": "job", "id": src["job"]["id"], "name": src["name"],
                                                                      "hist": h.name}}
                for h in hist if h.name != src.get("hist")]
    return out


def job_documents(job_id: int) -> list[dict]:
    """A job's viewable documents (its application packet's contents), in a fixed order."""
    from . import db
    from .resume import app_dir

    d = app_dir(db.get_job(int(job_id)))
    return [{"name": n, "kind": k} for n, k in JOB_DOCS.items() if (d / n).is_file()]


def filename(src: dict, bl: list[tuple], ext: str) -> str:
    """Dana-Smith-Resume.pdf / Dana-Smith-Cover-Letter.docx for what an employer reads; Initrode-Interview-Prep.pdf for
    your own notes. ASCII only (render.name_part)."""
    if src["kind"] in EMPLOYER:
        name = render.name_part(next((b[1] for b in bl if b[0] == "name"), ""))
    else:
        name = render.name_part(src["job"]["company"]) if src.get("job") else ""
    return "-".join(x for x in (name, src["base"]) if x) + f".{ext}"


def export(ref, fmt: str, opts=None, text: str | None = None, confirm: bool = False) -> tuple[str, bytes, dict]:
    """One format of a document in its look -> (file name, bytes, {pages}). The floor guard refuses an employer-facing
    document that names the floor; edited resume lines the profile does not support need confirm (Unconfirmed)."""
    if fmt not in FORMATS:
        raise SystemExit(f"format is one of {', '.join(FORMATS)}")
    src = source(ref)
    o = clean_opts(opts) if opts is not None else clean_opts(_load().get(src["key"]))
    st = _style(src, o)
    text = None if text is None else str(text)[:200000]
    bl = _blocks(src, st, o, text)
    txt = render.page_txt(bl, src["kind"] in ("letter", "counter"))
    g = guards(src, text, txt)
    if g["blocked"]:
        raise SystemExit(g["blocked"])
    if g["facts"] and not confirm:
        raise Unconfirmed("these lines say what your profile does not: " + "; ".join(g["facts"][:6]))
    name, letter = filename(src, bl, fmt), src["kind"] in ("letter", "counter")
    html = render.page_html(bl, st, _title(bl, src), letter)
    if fmt == "html":
        return name, html.encode(), {}
    if fmt == "txt":
        return name, txt.encode(), {}
    if fmt == "md":
        return name, (src["md"] if text is None else text).encode(), {}
    if fmt == "docx":
        buf = io.BytesIO()
        render.page_docx(bl, st, buf)
        return name, buf.getvalue(), {}
    data = pdf(html)
    from .resume import page_count

    f = CACHE / f"{hashlib.sha256(html.encode()).hexdigest()[:20]}.pdf"
    return name, data, {"pages": page_count(f)}


def pdf(html: str) -> bytes:
    """The page printed by headless Edge / Chrome (resume.pdf_from_html), cached by the page's hash: an unchanged look
    and text never runs the browser twice. The newest 40 PDFs are kept."""
    from .resume import NoEngine, pdf_from_html

    CACHE.mkdir(parents=True, exist_ok=True)
    stem = hashlib.sha256(html.encode()).hexdigest()[:20]
    f = CACHE / f"{stem}.pdf"
    if not f.is_file():
        page = CACHE / f"{stem}.html"
        page.write_text(html, encoding="utf-8")
        try:
            pdf_from_html(page, f)
        except NoEngine as e:
            raise SystemExit(f"no PDF engine (Edge, Chrome or Chromium) on this computer ({e}): download the DOCX or the "
                             "HTML page and print it to PDF") from None
        finally:
            page.unlink(missing_ok=True)
        for old in sorted(CACHE.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[40:]:
            old.unlink(missing_ok=True)
    return f.read_bytes()


def open_file(ref, fmt: str, opts=None, text: str | None = None, confirm: bool = False) -> str:
    """Write one format into ~/.lodestar/exports/ and return its path (the web layer opens it: Open in new window)."""
    name, data, _ = export(ref, fmt, opts, text, confirm)
    out = HOME / "exports" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write_bytes(data)
    except PermissionError:
        raise SystemExit(f"{name} is open in another program: close it, then try again") from None
    return str(out)


def save_text(ref, text: str, confirm: bool = False) -> dict:
    """Save an edited job document (resume.save_doc: the old version goes to history/). The floor guard runs first,
    then the fact guard like an export: the saved text becomes the document every later export, mail and packet reads,
    so lines your profile does not support need confirm (Unconfirmed) here. The master resume, studio versions and
    drafts are not saved from here (edit the profile, build again, or export)."""
    from .resume import save_doc

    src = source(ref)
    if not src.get("save"):
        raise SystemExit("only a job's own documents are saved from the viewer: export this one instead")
    st = _style(src, clean_opts(_load().get(src["key"])))
    g = guards(src, str(text), render.page_txt(_blocks(src, st, {}, str(text))))
    if g["blocked"]:
        raise SystemExit(g["blocked"])
    if g["facts"] and not confirm:
        raise Unconfirmed("these lines say what your profile does not: " + "; ".join(g["facts"][:6]))
    save_doc(src["job"], src["name"], str(text))
    return {"ok": True, "facts": g["facts"], "personal": g["personal"]}
