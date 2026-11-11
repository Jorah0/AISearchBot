"""Pass 17 document viewer (viewer.py + render.py's block adapters): any generated markdown document as render blocks
(contact line, sections, role lines with dates in the style's format), letters read into contact / date / address /
body / sign-off with the letter options, the bullet and paragraph-spacing styles in HTML and .docx, per-document
formatting kept in viewer.json, section order and hiding, studio versions in their own look, compare options and
differences, the floor guard (employer kinds refused, private notes not), the fact guard on edited resume lines (needs
confirm), counter drafts with their cited figures, refused refs, PDFs cached by page hash, the /api/view routes and the
token, and one real headless-Edge print that skips without Edge / Chrome."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import db, profile, render, resume, settings, studio, viewer  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Master Resume
## Contact
Dana Smith | Austin, TX | dana@example.com | +1 512 555 0101 | linkedin.com/in/dana

## Summary
Data engineer who ships reliable pipelines.

## Skills
- Languages: Python, SQL

## Experience
### Senior Engineer - Acme Corp (2021-03 - Present)
- Cut deploy time 40% by rebuilding CI
- Led 4 engineers through a database migration

### Engineer - Globex (2016-01 - 2021-02)
- Built Kafka pipelines for billing events

## Education
### BSc, Computer Science - UT Austin (2015)

## Preferences
Salary floor: $150,000 | Deal-breakers: on-call
"""
RESUME = """# Dana Smith
Dana Smith | Austin, TX | dana@example.com | linkedin.com/in/dana

## Summary
Data engineer who ships reliable pipelines.

## Experience
### Senior Engineer - Acme Corp (2021-03 - Present)
- Cut deploy time 40% by rebuilding CI
- Led 4 engineers through a database migration

### Engineer, Globex (2016-2021)
- Built Kafka pipelines for billing events

## Skills
Python, SQL, Kafka
"""
LETTER = """Dana Smith | Austin, TX | dana@example.com
November 10, 2026

Hiring Manager
Initrode

Dear Hiring Manager,

I rebuild pipelines that teams trust.

I would like to talk.

Sincerely,
Dana Smith

P.S. My portfolio is linked above."""


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class Base(unittest.TestCase):
    """A known profile.md and job documents; no viewer.json, studio versions or resume_look; no PDF engine unless a
    test brings one. Everything is put back afterwards."""

    def setUp(self):
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        settings.PATH.unlink(missing_ok=True)
        viewer.STORE.unlink(missing_ok=True)
        shutil.rmtree(viewer.CACHE, ignore_errors=True)
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patched(studio, AUTO=False))
        self.stack.enter_context(patched(resume, _browser=lambda: None, _word=lambda: False, _soffice=lambda: None))
        self._con = getattr(db._local, "con", None)  # a connection of our own to this home's database (another test
        db._local.con = None  # may have left this thread on a different one); the web server's threads open theirs
        self.jid = db.add_job("Initrode", "Data Engineer", None, "Python, SQL and Kafka pipelines", "viewer test")
        self.job = db.get_job(self.jid)
        self.dir = resume.app_dir(self.job)
        for name, text in (("resume.md", RESUME), ("cover_letter.md", LETTER),
                           ("offer.md", "Base 160k\n\n## Evaluation\n- Above my salary floor of $150,000"),
                           ("interview_prep.md", "# Prep\n\n## Questions\n- Why Initrode?")):
            (self.dir / name).write_text(text, encoding="utf-8")
        self.ref = {"type": "job", "id": self.jid, "name": "resume.md"}

    def tearDown(self):
        self.stack.close()
        db.delete_job(self.jid)
        db.release()
        db._local.con = self._con
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        shutil.rmtree(viewer.CACHE, ignore_errors=True)
        viewer.STORE.unlink(missing_ok=True)
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)


class Blocks(Base):
    def test_markdown_blocks_contact_sections_and_dates_in_the_style(self):
        st = render.full_style({"date_format": "2021", "contact_layout": "two_lines"})
        bl = render.md_blocks(RESUME + "\n- Spoke at PyCon\n", st)
        self.assertEqual(bl[0], ("name", "Dana Smith"))
        self.assertEqual(bl[1], ("contact", ["Austin, TX", "dana@example.com", "linkedin.com/in/dana"]))  # name not repeated
        self.assertIn(("entry", "Senior Engineer - Acme Corp", "2021 - Present"), bl)
        self.assertIn(("entry", "Engineer, Globex", "2016 - 2021"), bl)
        self.assertEqual([b[1] for b in bl if b[0] == "h2"], ["Summary", "Experience", "Skills"])
        self.assertEqual([b[2] for b in bl if b[0] == "h2"], ["summary", "experience", "skills"])
        self.assertEqual(render.fmt_span("2021-03 - Present", "Mar 2021"), "Mar 2021 - Present")
        self.assertEqual(render.fmt_span("2018-present", "March 2021"), "2018 - Present")
        self.assertEqual(render.name_part("Łukasz Żak-Ńowak"), "Lukasz-Zak-Nowak")  # file names and headers stay ASCII
        self.assertEqual(render.filename({"contact": {"name": "Zoë Ünal"}}, "pdf"), "Zoe-Unal-Resume.pdf")
        many = render.md_blocks("# A\nA | Austin, TX | a@b.co | 555 0101 | linkedin.com/in/a\n", st)
        self.assertEqual([b[0] for b in many], ["name", "contact", "contact"])  # two_lines
        notes = render.md_blocks("# Prep\nWhy | this line is not contact\n## Questions\n- Why us?", st, "notes")
        self.assertEqual([b[0] for b in notes], ["name", "p", "h2", "li"])

    def test_letter_parts_and_options(self):
        p = render.letter_parts(LETTER)
        self.assertEqual((p["name"], p["contact"], p["date"]), ("Dana Smith", ["Austin, TX", "dana@example.com"], "November 10, 2026"))
        self.assertEqual(p["recipient"], ["Hiring Manager", "Initrode"])
        self.assertEqual(p["body"], ["Dear Hiring Manager,", "I rebuild pipelines that teams trust.", "I would like to talk."])
        self.assertEqual((p["closing"], p["after"]), (["Sincerely,", "Dana Smith"], ["P.S. My portfolio is linked above."]))
        st = render.full_style({})
        bl = render.letter_blocks(LETTER, st, {"date": False, "recipient": "Ms. Lee\nInitrode\nDallas, TX", "signature": "Best,\nDana"})
        self.assertNotIn(("p", "November 10, 2026"), bl)
        self.assertIn(("lines", ["Ms. Lee", "Initrode", "Dallas, TX"]), bl)
        self.assertIn(("lines", ["Best,", "Dana"]), bl)
        self.assertEqual(bl[-1], ("p", "P.S. My portfolio is linked above."))  # a P.S. survives a new signature
        txt = render.page_txt(render.letter_blocks(LETTER, st), True)
        self.assertIn("Initrode\n\nDear Hiring Manager,\n\nI rebuild", txt)
        html = render.page_html(bl, st, "Dana Smith", True)
        self.assertIn('<body class="letter">', html)
        self.assertIn('<p class="lines">Ms. Lee<br>Initrode<br>Dallas, TX</p>', html)
        self.assertEqual(render.letter_parts("Just one paragraph.")["body"], ["Just one paragraph."])

    def test_bullet_and_paragraph_spacing_in_html_and_docx(self):
        from docx import Document

        base = render.css(render.full_style({}))
        self.assertNotIn("list-style-type", base)  # the default leaves the studio's golden page as it was
        st = render.full_style({"bullet": "dash", "para_spacing": 6})
        self.assertIn('ul{list-style-type:"- "}', render.css(st))
        self.assertIn("li{margin:0 0 6.0pt", render.css(st))
        self.assertIn("padding-left:0", render.css(render.full_style({"bullet": "none"})))
        self.assertEqual(render.full_style({"bullet": "square"}, {"template": "modern"})["bullet"], "disc")  # template resets
        buf = io.BytesIO()
        render.page_docx(render.md_blocks(RESUME, st) + [("lines", ["Best,", "Dana"])], st, buf)
        d = Document(io.BytesIO(buf.getvalue()))
        texts = [p.text for p in d.paragraphs]
        self.assertIn("- Cut deploy time 40% by rebuilding CI", texts)
        self.assertIn("Best,\nDana", texts)
        self.assertEqual(d.styles["Normal"].paragraph_format.space_after.pt, 6)
        self.assertEqual(len(d.tables), 0)
        with self.assertRaises(SystemExit):
            render.clean_style({"bullet": "star"}, strict=True)


class View(Base):
    def test_view_saves_per_document_formatting_orders_and_hides_sections(self):
        v = viewer.view(self.ref)
        self.assertEqual((v["kind"], v["employer"], v["save"]), ("resume", True, True))
        self.assertEqual(v["sections"], ["Summary", "Experience", "Skills"])
        self.assertEqual([d["name"] for d in v["docs"]], ["resume.md", "cover_letter.md", "interview_prep.md", "offer.md"])
        self.assertNotIn("<script", v["html"])
        opts = {"look": {"font": "Georgia", "accent": "teal", "paper": "a4"}, "order": ["Skills"], "hide": ["Summary"]}
        v = viewer.view(self.ref, opts, save=True)
        self.assertEqual([b for b in v["txt"].splitlines() if b.isupper()], ["SKILLS", "EXPERIENCE"])
        self.assertEqual(v["sections"], ["Summary", "Experience", "Skills"])  # the panel still lists the hidden one
        self.assertIn('font-family:"Georgia"', v["html"])
        self.assertEqual(json.loads(viewer.STORE.read_text(encoding="utf-8"))[f"job:{self.jid}:resume.md"]["look"]["paper"], "a4")
        again = viewer.view(self.ref)  # reopened: the kept formatting
        self.assertEqual((again["look"]["font"], again["opts"]["hide"]), ("Georgia", ["Summary"]))
        self.assertEqual(viewer.view(self.ref, {}, save=True)["look"]["font"], "Calibri")  # empty: back to the saved look
        self.assertNotIn(f"job:{self.jid}:resume.md", json.loads(viewer.STORE.read_text(encoding="utf-8")))
        settings.set_pref("resume_look", {"font": "Verdana"})
        self.assertEqual(viewer.view(self.ref)["look"]["font"], "Verdana")  # every document starts from your saved look
        with self.assertRaises(SystemExit):
            viewer.view(self.ref, {"look": {"font": "Comic Sans"}})

    def test_studio_version_opens_in_its_own_look_and_compares(self):
        a = studio.build(req={"template": "modern", "bullets_per_role": 1}, use_ai=False)
        b = studio.build(req={"accent": "burgundy"}, use_ai=False)
        self.assertIn("doc", a)
        v = viewer.view({"type": "studio", "vid": a["vid"]}, compare={"type": "studio", "vid": b["vid"]})
        self.assertEqual((v["look"]["template"], v["look"]["font"]), ("modern", "Arial"))
        self.assertEqual(v["html"], render.page_html(render.blocks(a["doc"], v["look"]), v["look"], "Dana Smith"))  # one renderer path
        self.assertIn({"label": "Studio " + b["created"][:16].replace("T", " ") + " general", "ref": {"type": "studio", "vid": b["vid"]}},
                      v["compare"])
        self.assertNotIn(a["vid"], [c["ref"].get("vid") for c in v["compare"]])
        self.assertEqual(v["other"]["look"]["accent"], "#7A1F2B")
        self.assertTrue(any("bullet" in x for x in v["diff"]), v["diff"])
        # edited text renders from the markdown (the same block renderer)
        e = viewer.view({"type": "studio", "vid": a["vid"]}, text=v["md"].replace("Data engineer who ships", "Engineer who ships"))
        self.assertIn("Engineer who ships", e["txt"])

    def test_history_versions_compare_and_refused_refs(self):
        resume.save_doc(self.job, "resume.md", RESUME.replace("40%", "35%"))
        v = viewer.view(self.ref)
        hist = [c["ref"] for c in v["compare"] if c["ref"].get("hist")]
        self.assertEqual(len(hist), 1)
        old = viewer.view(hist[0])
        self.assertIn("40%", old["txt"])
        self.assertFalse(old["save"])
        self.assertIn("+1 bullet in Acme Corp", viewer.view(self.ref, compare=hist[0])["diff"])
        for bad in ({"type": "job", "id": self.jid, "name": "../profile.md"}, {"type": "job", "id": self.jid, "name": "gap.json"},
                    {"type": "job", "id": self.jid, "name": "resume.md", "hist": "../../profile.md"},
                    {"type": "job", "id": self.jid, "name": "resume.md", "hist": "cover_letter-20260101-000000.md"},
                    {"type": "studio", "vid": "../x"}, {"type": "nope"}, None):
            with self.assertRaises(SystemExit, msg=bad):
                viewer.view(bad)
        with self.assertRaises(SystemExit):
            viewer.save_text({"type": "master"}, "x")
        with self.assertRaises(SystemExit):
            viewer.export(self.ref, "exe")

    def test_master_resume_and_letter_kinds(self):
        studio.sync_master(force=True)
        m = viewer.view({"type": "master"})
        self.assertEqual((m["title"], m["kind"]), ("Master resume", "resume"))
        self.assertNotIn("Salary floor", m["txt"])
        c = viewer.view({"type": "job", "id": self.jid, "name": "cover_letter.md"}, {"letter": {"date": False}})
        self.assertEqual(c["kind"], "letter")
        self.assertNotIn("November 10, 2026", c["txt"])
        self.assertEqual(viewer.clean_opts({"letter": {"date": True, "recipient": "", "signature": ""}}), {})
        name, data, _ = viewer.export({"type": "job", "id": self.jid, "name": "cover_letter.md"}, "txt")
        self.assertEqual(name, "Dana-Smith-Cover-Letter.txt")
        name, _, _ = viewer.export({"type": "job", "id": self.jid, "name": "interview_prep.md"}, "md")
        self.assertEqual(name, "Initrode-Interview-Prep.md")


class Guards(Base):
    def test_floor_guard_refuses_employer_documents_but_not_private_notes(self):
        leak = RESUME + "\n## Notes\nMy salary floor is $150,000\n"
        v = viewer.view(self.ref, text=leak)
        self.assertIn("salary floor", v["guards"]["blocked"])
        for fmt in viewer.FORMATS:
            with self.assertRaises(SystemExit, msg=fmt):
                viewer.export(self.ref, fmt, text=leak, confirm=True)
        with self.assertRaises(SystemExit):
            viewer.save_text(self.ref, leak)
        self.assertEqual((self.dir / "resume.md").read_text(encoding="utf-8"), RESUME)  # nothing saved
        # the floor hidden from the rendered page (after a P.S. a new signature replaces) is still caught in the text
        letter = {"type": "job", "id": self.jid, "name": "cover_letter.md"}
        with self.assertRaises(SystemExit):
            viewer.export(letter, "pdf", {"letter": {"signature": "Best,\nDana"}}, text=LETTER + "\n\nMy salary floor is $150,000")
        offer = viewer.view({"type": "job", "id": self.jid, "name": "offer.md"})  # your own notes: no guard
        self.assertEqual((offer["employer"], offer["guards"]["blocked"]), (False, ""))
        self.assertIn("150,000", viewer.export({"type": "job", "id": self.jid, "name": "offer.md"}, "txt")[1].decode())

    def test_fact_guard_on_edited_lines_needs_confirm_and_personal_data_is_named(self):
        edited = RESUME.replace("Cut deploy time 40%", "Cut deploy time 55%") + "- Date of birth: 1990-01-01\n"
        v = viewer.view(self.ref, text=edited)
        self.assertTrue(any("new number 55" in x for x in v["guards"]["facts"]), v["guards"])
        self.assertTrue(any("date of birth" in x for x in v["guards"]["personal"]), v["guards"])
        with self.assertRaises(viewer.Unconfirmed):
            viewer.export(self.ref, "txt", text=edited)
        name, data, _ = viewer.export(self.ref, "txt", text=edited, confirm=True)
        self.assertIn("55%", data.decode())
        self.assertEqual(viewer.view(self.ref, text=RESUME)["guards"]["facts"], [])  # unchanged text: nothing to check
        r = viewer.save_text(self.ref, edited, confirm=True)
        self.assertTrue(r["facts"])
        self.assertIn("55%", (self.dir / "resume.md").read_text(encoding="utf-8"))
        self.assertTrue(list((self.dir / "history").glob("resume-*.md")))

    def test_save_asks_like_an_export_and_every_changed_line_is_checked(self):
        # the saved text is what every later export, mail and the packet read: an unsupported line needs confirm first
        bad = "- Led the Kubernetes migration at Google as VP of Engineering"
        edited = RESUME.replace("### Engineer, Globex (2016-2021)", "### Director of Engineering - Google (2012 - Present)")
        with self.assertRaises(viewer.Unconfirmed):
            viewer.save_text(self.ref, edited)
        self.assertEqual((self.dir / "resume.md").read_text(encoding="utf-8"), RESUME)  # nothing saved
        self.assertFalse((self.dir / "history").exists())
        r = viewer.save_text(self.ref, edited, confirm=True)  # your confirm: saved, and the lines are named back
        self.assertTrue(any("google" in x.lower() for x in r["facts"]), r)
        self.assertIn("Google", (self.dir / "resume.md").read_text(encoding="utf-8"))
        (self.dir / "resume.md").write_text(RESUME, encoding="utf-8")
        # a filler of 30 harmless lines (the same one) never uses up the check: the invented line after it is caught
        padded = RESUME + "\n" + "- tidied the pipeline docs\n" * 30 + bad + "\n"
        g = viewer.view(self.ref, text=padded)["guards"]["facts"]
        self.assertTrue(any("Kubernetes" in x for x in g), g)
        with self.assertRaises(viewer.Unconfirmed):
            viewer.export(self.ref, "txt", text=padded)
        # past the cap, the rest is not passed silently: one entry asks for confirm
        with patched(viewer, CHECK_MAX=2):
            g = viewer.view(self.ref, text=RESUME + "- Wrote docs\n- Wrote more docs\n- Wrote better docs\n")["guards"]["facts"]
            self.assertIn("1 more changed line(s) were not checked (over 2): confirm only if every one comes from your profile", g)
            with self.assertRaises(viewer.Unconfirmed):
                viewer.save_text(self.ref, RESUME + "- Wrote docs\n- Wrote more docs\n- Wrote better docs\n")

    def test_counter_draft_may_name_only_its_cited_figures(self):
        other = db.add_job("Hooli", "Data Engineer", None, "x", "viewer test")
        try:
            db.set_status(other, "offer")
            db.set_offer(other, base="170k")
            db.set_status(self.jid, "offer")
            ref = {"type": "text", "kind": "counter", "job": self.jid, "cite": [f"{other}:base"],
                   "text": "Hi,\n\nAnother offer has a base of $170,000. Could you match it?\n\nBest,\nDana"}
            v = viewer.view(ref)
            self.assertEqual((v["kind"], v["guards"]["blocked"]), ("counter", ""))
            self.assertEqual(viewer.export(ref, "md")[0], "Counter-Offer.md")
            with self.assertRaises(SystemExit):
                viewer.export(ref | {"text": ref["text"] + "\nMy floor is $150,000."}, "txt")
        finally:
            db.delete_job(other)


class Pdf(Base):
    def test_pdf_is_cached_by_page_and_no_engine_says_so(self):
        calls = []

        def fake(html, pdf, browser=None):
            calls.append(Path(html).read_text(encoding="utf-8"))
            Path(pdf).write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Page\n" + b"x" * 2000)
            return {"path": str(pdf), "method": "edge", "tried": []}

        with patched(resume, pdf_from_html=fake):
            name, data, info = viewer.export(self.ref, "pdf", {"look": {"font": "Georgia"}})
            self.assertEqual((name, info["pages"]), ("Dana-Smith-Resume.pdf", 2))
            self.assertTrue(data.startswith(b"%PDF"))
            viewer.export(self.ref, "pdf", {"look": {"font": "Georgia"}})
            self.assertEqual(len(calls), 1)  # the same page: no second print
            self.assertIn('font-family:"Georgia"', calls[0])
            self.assertEqual(viewer.view(self.ref, {"look": {"font": "Georgia"}})["pages"], 2)
            viewer.export(self.ref, "pdf", {"look": {"font": "Arial"}})
            self.assertEqual(len(calls), 2)
            self.assertEqual(list(viewer.CACHE.glob("*.html")), [])  # the printed page is not kept
        with self.assertRaises(SystemExit) as e:
            viewer.export(self.ref, "pdf", {"look": {"font": "Verdana"}})
        self.assertIn("no PDF engine", str(e.exception))


class RealEdge(unittest.TestCase):
    @unittest.skipUnless(resume._browser(), "no Edge / Chrome / Chromium")
    def test_real_edge_prints_the_viewer_page_on_a4(self):
        with tempfile.TemporaryDirectory() as tmp, patched(viewer, CACHE=Path(tmp) / "cache"):
            html = render.page_html(render.md_blocks(RESUME, render.full_style({"paper": "a4"})), render.full_style({"paper": "a4"}))
            data = viewer.pdf(html)
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertEqual(resume.page_count(next((Path(tmp) / "cache").glob("*.pdf"))), 1)
            import re

            self.assertIn(int(re.search(rb"/MediaBox\s*\[\s*0\s+0\s+(\d+)", data)[1]), (594, 595))  # A4 width in points


class Desktop(unittest.TestCase):
    def test_the_desktop_window_lets_downloads_save(self):
        import types

        from lodestar import desktop

        made = []
        fake = types.SimpleNamespace(settings={"ALLOW_DOWNLOADS": False}, windows=[],
                                     create_window=lambda *a, **k: made.append(a), start=lambda **k: made.append("start"))
        old = sys.modules.get("webview")
        sys.modules["webview"] = fake
        try:
            desktop.open_window(9999)
        finally:
            sys.modules.pop("webview")
            if old is not None:
                sys.modules["webview"] = old
        self.assertTrue(fake.settings["ALLOW_DOWNLOADS"])  # the viewer's Download buttons (a blob link) save a file
        self.assertEqual(made[-1], "start")


class Web(Base):
    def call(self, path, body=None, token=True):
        import http.client

        from lodestar import web

        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"} | ({"X-Lodestar-Token": web.TOKEN} if token else {})
        c.request("POST", path, json.dumps(body or {}), h)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()

    def setUp(self):
        super().setUp()
        from lodestar import desktop, web

        self.port = desktop.free_port(9030)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def test_view_file_open_save_routes_and_the_token(self):
        from lodestar import web

        st, _, body = self.call("/api/view", {"ref": self.ref, "opts": {"look": {"accent": "navy"}}, "save": True})
        v = json.loads(body)
        self.assertEqual(st, 200, v)
        self.assertEqual((v["look"]["accent"], v["choices"]["pages"]), ("#1F3A5F", [0, 1, 2]))
        st, h, data = self.call("/api/view/file", {"ref": self.ref, "fmt": "docx"})
        self.assertEqual((st, h["Content-Disposition"]), (200, 'attachment; filename="Dana-Smith-Resume.docx"'))
        self.assertTrue(data.startswith(b"PK"))
        st, h, data = self.call("/api/view/file", {"ref": self.ref, "fmt": "txt", "text": RESUME.replace("40%", "45%")})
        self.assertEqual((st, json.loads(data)["confirm"]), (409, True))
        st, _, data = self.call("/api/view/file", {"ref": self.ref, "fmt": "txt", "text": RESUME + "\nSalary floor: $150,000"})
        self.assertEqual(st, 400)
        self.assertIn("salary floor", json.loads(data)["error"])
        opened = []
        with patched(web, _open_path=lambda p: opened.append(p)):
            st, _, data = self.call("/api/view/open", {"ref": self.ref, "fmt": "html"})
        self.assertEqual(st, 200)
        self.assertTrue(str(opened[0]).endswith(os.path.join("exports", "Dana-Smith-Resume.html")))
        self.assertIn("#1F3A5F", Path(opened[0]).read_text(encoding="utf-8"))  # the document's own look
        st, _, data = self.call("/api/view/save", {"ref": self.ref, "text": RESUME.replace("40%", "45%")})
        self.assertEqual((st, json.loads(data)["confirm"]), (409, True))  # the fact guard asks before a save too
        self.assertIn("40%", (self.dir / "resume.md").read_text(encoding="utf-8"))
        st, _, data = self.call("/api/view/save", {"ref": self.ref, "text": RESUME.replace("ships", "builds")})
        self.assertEqual((st, json.loads(data)["ok"]), (200, True))
        self.assertIn("builds reliable", (self.dir / "resume.md").read_text(encoding="utf-8"))
        for path in ("/api/view", "/api/view/file", "/api/view/open", "/api/view/save"):
            self.assertEqual(self.call(path, {"ref": self.ref, "fmt": "txt"}, token=False)[0], 403, path)


if __name__ == "__main__":
    unittest.main()
