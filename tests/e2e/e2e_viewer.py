"""Document viewer, pass 17: one viewer for every generated document. Paged Letter / A4 sheets with page numbers, zoom,
the page count and the over-the-limit marker; the PDF tab showing the file headless Edge printed (fetched with the
token into a blob); the Word-layout preview; the exact TXT / MD; downloads of every format; print and Open in new
window; compare two versions side by side; every formatting control (each changes the preview, and the export carries
it); sections dragged, moved and hidden; letter options; section edits with the fact and floor guards; and the entry
points (drawer documents and packet, interview prep, research, the master card, Insights offer notes and the counter
draft, a studio version). PDFs come from the installed Edge when there is one (the PDF assertions skip without it)."""
import io
import json
import re
import shutil
import unittest
import zipfile

from harness import FLOOR, E2ETestCase, db, resume

from lodestar import settings, studio, viewer

REAL_BROWSER = resume._browser  # the harness pins the print-page fallback per class; this suite prints real PDFs
EDGE = REAL_BROWSER()
LONG = "# Research: Northwind Analytics\n\n" + "\n\n".join(
    f"## Topic {n}\n" + "\n".join(f"- Finding {n}.{k}: Northwind ships data products to {k + 3} regional teams" for k in range(8))
    for n in range(1, 9))


class Viewer(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        cls._patch(resume, "_browser", REAL_BROWSER)
        saved, offer = db.get_job(cls.ids["saved"]), db.get_job(cls.ids["offer"])
        d = resume.app_dir(saved)
        resume.write_doc(d / "resume.md", resume._employer_copy(resume._source()))
        resume.write_doc(d / "cover_letter.md", resume.letter(saved, "I rebuild pipelines that teams trust.\n\nI would like to talk."))
        resume.write_doc(d / "interview_prep.md", "# Interview prep: Northwind\n\n## Likely questions\n- Tell me about a pipeline you rebuilt")
        resume.write_doc(d / "research.md", LONG)
        resume.write_doc(resume.app_dir(offer) / "offer.md", f"Base 182k | bonus 10%\n\n## Evaluation\n- Above my floor of {FLOOR}")

    def setUp(self):
        super().setUp()
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        viewer.STORE.unlink(missing_ok=True)
        settings.set_pref("resume_look", {})

    # --- helpers
    def open_doc(self, name, jid=None):
        self.open_job(jid or self.ids["saved"])
        self.page.evaluate("n => docTab(n)", name)
        self.page.locator("#drawer").get_by_role("button", name="View / format").click()
        return self.ready()

    def ready(self):
        """Wait until the viewer shows the latest render, laid out into sheets."""
        self.page.wait_for_selector("#viewer:not([hidden])")
        self.page.wait_for_function("() => VW && VW.t === null && VW.ready")
        self.idle()
        self.page.wait_for_function("() => VW && VW.t === null && VW.ready")
        return self.page.frame_locator("#vwFrame")

    def frame(self, js, second=False):
        return self.page.evaluate(f"() => {{ const d = document.querySelector('#vwFrame{'2' if second else ''}').contentDocument; return {js}; }}")

    def download(self, fmt, answer=None):
        if answer is not None:
            self.answer(answer)
        with self.page.expect_download() as info:
            self.page.locator("#vwDl").get_by_role("button", name=f"Download {fmt.upper()}").click()
        dl = info.value
        self.idle()
        with open(dl.path(), "rb") as f:
            return dl.suggested_filename, f.read()

    def look(self, sel, value):
        self.page.select_option(sel, value)
        return self.ready()

    def number(self, sel, value):
        self.page.fill(sel, str(value))
        return self.ready()

    # --- tests
    def test_paged_preview_zoom_tabs_downloads_and_the_real_pdf(self):
        frame = self.open_doc("resume.md")
        self.assertIn("resume.md", self.page.text_content("#vwTitle"))
        self.assertEqual(self.frame("d.querySelectorAll('.sheet').length"), 1)
        self.assertEqual(self.frame("d.querySelector('.pgno').textContent"), "Page 1 of 1")
        self.assertEqual(self.page.text_content("#vwPages").strip(), "1 page")
        self.assertEqual(frame.locator("h1").text_content(), "Pat Rivera")
        self.assertEqual(frame.locator("script").count(), 0)
        self.assertAlmostEqual(float(self.frame("getComputedStyle(d.querySelector('.sheet')).width")[:-2]), 816, places=0)  # Letter
        self.page.select_option("#vwZoom", "1")
        self.assertEqual(float(self.frame("d.body.style.zoom")), 1)
        self.page.select_option("#vwZoom", "page")
        page_z = float(self.frame("d.body.style.zoom"))
        self.page.select_option("#vwZoom", "width")
        self.assertLess(page_z, float(self.frame("d.body.style.zoom")))
        self.page.click("#vwTabs button[data-t=txt]")
        txt = self.page.text_content("#vwText")
        self.assertIn("EXPERIENCE", txt)
        self.assertNotIn("Salary floor", txt)
        name, data = self.download("txt")
        self.assertEqual((name, data.decode()), ("Pat-Rivera-Resume.txt", txt))
        self.page.click("#vwTabs button[data-t=md]")
        md = self.page.text_content("#vwText")
        self.assertEqual(md, (resume.app_dir(db.get_job(self.ids["saved"])) / "resume.md").read_text(encoding="utf-8"))
        self.assertEqual(self.download("md")[1].decode(), md)
        self.page.click("#vwTabs button[data-t=docx]")
        self.assertIn("Word layout preview; Word may differ slightly", self.page.text_content("#vwLabel"))
        self.assertTrue(self.page.locator("#vwFrame").is_visible())
        name, data = self.download("docx")
        self.assertEqual(name, "Pat-Rivera-Resume.docx")
        self.assertIn("word/document.xml", zipfile.ZipFile(io.BytesIO(data)).namelist())
        name, data = self.download("html")
        self.assertIn('<h1>Pat Rivera</h1>', data.decode())
        if not EDGE:
            return
        self.page.click("#vwTabs button[data-t=pdf]")
        self.page.wait_for_function("() => VW.pdf && document.querySelector('#vwPdf').src.startsWith('blob:')", timeout=30_000)
        self.idle()
        self.assertIn("The PDF as printed by edge", self.page.text_content("#vwLabel"))
        self.assertIn("PDF: 1 page", self.page.text_content("#vwPages"))
        name, data = self.download("pdf")
        self.assertEqual(name, "Pat-Rivera-Resume.pdf")
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page(?!s)", data)), 1)

    def test_every_formatting_control_changes_the_preview_and_the_export(self):
        frame = self.open_doc("resume.md")
        body = lambda prop: self.frame(f"getComputedStyle(d.body).{prop}")  # noqa: E731
        self.look("#vw_font", "Georgia")
        self.assertIn("Georgia", body("fontFamily"))
        self.number("#vw_size", 11.5)
        self.assertAlmostEqual(float(body("fontSize")[:-2]), 11.5 * 96 / 72, places=1)
        self.number("#vw_heading_size", 1.5)
        self.assertIn("font-size:1.5em", self.frame("d.querySelector('style').textContent"))
        self.look("#vw_accent", "teal")
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('h2')).color"), "rgb(15, 110, 110)")
        self.page.locator("#vw_accentC").evaluate("e => { e.value = '#7a1f2b'; e.dispatchEvent(new Event('input')); }")
        self.ready()
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('h2')).color"), "rgb(122, 31, 43)")
        self.number("#vw_margins", 1)
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('.sheet')).paddingTop"), "96px")
        self.number("#vw_line_spacing", 1.4)
        self.assertIn("line-height:1.4", self.frame("d.querySelector('style').textContent"))
        self.number("#vw_para_spacing", 6)
        self.assertIn("li{margin:0 0 6.0pt", self.frame("d.querySelector('style').textContent"))
        self.look("#vw_paper", "a4")
        self.assertAlmostEqual(float(self.frame("getComputedStyle(d.querySelector('.sheet')).width")[:-2]), 8.27 * 96, places=0)
        self.look("#vw_density", "airy")
        self.look("#vw_date_format", "2021")
        self.assertIn("2018 - 2021", frame.locator("h3").nth(1).text_content())
        self.look("#vw_bullet", "square")
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('ul')).listStyleType"), "square")
        self.look("#vw_contact_layout", "centered")
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('.contact')).textAlign"), "center")
        self.look("#vw_heading_case", "title")
        self.assertEqual(self.frame("getComputedStyle(d.querySelector('h2')).textTransform"), "none")
        # the export carries the same look: the HTML has it, the DOCX has the font, size, paper and accent
        html = self.download("html")[1].decode()
        for rule in ('font-family:"Georgia"', "font-size:11.5pt", "size:a4;margin:1.0in", "line-height:1.4", "list-style-type:square",
                     "color:#7A1F2B", "text-transform:none"):
            self.assertIn(rule, html)
        from docx import Document

        d = Document(io.BytesIO(self.download("docx")[1]))
        self.assertEqual((d.styles["Normal"].font.name, d.styles["Normal"].font.size.pt), ("Georgia", 11.5))
        self.assertEqual(str(d.styles["Heading 2"].font.color.rgb), "7A1F2B")
        self.assertAlmostEqual(d.sections[0].page_width.inches, 8.27, places=2)
        self.assertTrue(any(p.text.startswith("▪ ") for p in d.paragraphs))
        # kept for this document: reopening shows the same look
        saved = json.loads(viewer.STORE.read_text(encoding="utf-8"))[f"job:{self.ids['saved']}:resume.md"]["look"]
        self.assertEqual((saved["font"], saved["paper"], saved["bullet"]), ("Georgia", "a4", "square"))
        self.page.click("#vwClose")
        self.open_doc("resume.md")
        self.assertEqual(self.page.input_value("#vw_font"), "Georgia")
        # the page limit, then a template change (resets the look), Save as my default look, Reset to template
        self.look("#vw_pages", "1")
        self.assertEqual(self.page.locator("#vwOver").count(), 0)
        self.look("#vw_template", "modern")
        self.assertEqual(self.page.input_value("#vw_font"), "Arial")
        self.page.get_by_role("button", name="Save as my default look").click()
        self.ready()
        self.expect_toast("saved as your default look", "ok")
        self.assertEqual(settings.pref("resume_look")["font"], "Arial")
        self.assertNotIn("pages", settings.pref("resume_look"))
        self.look("#vw_font", "Verdana")
        self.page.get_by_role("button", name="Reset to template").click()
        self.ready()
        self.assertEqual(self.page.input_value("#vw_font"), "Arial")
        self.assertIn("Arial", body("fontFamily"))

    def test_sections_drag_move_hide_and_edits_with_the_guards(self):
        frame = self.open_doc("resume.md")
        heads = lambda: [h.lower() for h in frame.locator("h2").all_text_contents()]  # noqa: E731
        self.assertEqual(heads(), ["summary", "skills", "experience", "education"])
        self.page.locator("#vwRows .row", has_text="Skills").locator("input").uncheck()
        self.ready()
        self.assertNotIn("skills", heads())
        self.page.get_by_role("button", name="move Education up").click()
        self.ready()
        self.assertEqual(heads(), ["summary", "education", "experience"])
        self.page.locator("#vwRows .row", has_text="Experience").drag_to(self.page.locator("#vwRows .row").first)
        self.ready()
        self.assertEqual(heads()[0], "experience")
        # a click on a heading in the page opens that section's editor
        # Edge logs 'Blocked script execution' for pointer input over a frame sandboxed without scripts: nothing runs in it
        self.allow_console(r"Blocked script execution in 'about:srcdoc'")
        frame.locator("h2", has_text="Experience").click()
        self.assertTrue(self.page.locator("#vwEdit").is_visible())
        self.assertEqual(self.page.evaluate("document.activeElement.closest('.vwsec').dataset.title"), "Experience")
        box = self.page.locator("#vwEdit .vwsec[data-title=Experience] textarea")
        box.fill(box.input_value().replace("Cut warehouse spend 40%", "Cut warehouse spend 45%"))
        self.ready()
        self.assertIn("Cut warehouse spend 45%", frame.locator("body").text_content())
        self.assertIn("not in your profile", self.page.text_content("#vwGuards"))
        self.assertIn("new number 45", self.page.text_content("#vwGuards"))
        self.allow_console(r"status of 409")
        name, data = self.download("txt", answer=True)  # the fact guard asks first
        self.assertIn("Export anyway?", self.dialogs[-1])
        self.assertIn("45%", data.decode())
        self.page.get_by_role("button", name="Discard edits").click()
        self.ready()
        self.assertIn("Cut warehouse spend 40%", frame.locator("body").text_content())
        # Save document keeps an edit in resume.md (the old one goes to history/)
        self.page.click("#vwEditTab")
        box = self.page.locator("#vwEdit .vwsec[data-title=Summary] textarea")
        box.fill("## Summary\nData engineer building batch and streaming pipelines.")
        self.ready()
        self.page.get_by_role("button", name="Save document").click()
        self.idle()
        self.expect_toast("saved resume.md", "ok")
        d = resume.app_dir(db.get_job(self.ids["saved"]))
        self.assertIn("Data engineer building batch and streaming pipelines.", (d / "resume.md").read_text(encoding="utf-8"))
        self.assertTrue(list((d / "history").glob("resume-*.md")))

    def test_letter_options_and_the_floor_guard(self):
        frame = self.open_doc("cover_letter.md")
        text = lambda: frame.locator("body").text_content()  # noqa: E731
        self.assertTrue(self.page.locator("#vwLDate").is_checked())
        self.assertRegex(text(), r"[A-Z][a-z]+ \d{1,2}, \d{4}")
        self.page.locator("#vwLDate").uncheck()
        self.ready()
        self.assertNotRegex(text(), r"[A-Z][a-z]+ \d{1,2}, \d{4}")
        self.page.fill("#vwLRec", "Maya Chen\nNorthwind Analytics\nPortland, OR")
        self.ready()
        self.assertEqual(frame.locator("p.lines").first.inner_text(), "Maya Chen\nNorthwind Analytics\nPortland, OR")
        self.page.fill("#vwLSig", "With thanks,\nPat")
        self.ready()
        self.assertEqual(frame.locator("p.lines").last.inner_text(), "With thanks,\nPat")
        self.page.click("#vwTabs button[data-t=txt]")
        self.assertIn("With thanks,\nPat", self.page.text_content("#vwText"))
        self.assertEqual(self.download("txt")[0], "Pat-Rivera-Cover-Letter.txt")
        # a floor in the text: shown as a refusal, and no export happens
        self.page.click("#vwEditTab")
        box = self.page.locator("#vwEdit textarea").first
        box.fill(box.input_value() + f"\n\nMy salary floor is {FLOOR}.")
        self.ready()
        self.assertIn("names your salary floor", self.page.text_content("#vwGuards"))
        self.allow_console(r"status of 400")
        self.page.locator("#vwDl").get_by_role("button", name="Download PDF").click()
        self.idle()
        self.expect_toast("names your salary floor", "err")

    def test_over_limit_marker_compare_print_and_new_window(self):
        frame = self.open_doc("research.md")
        n = self.frame("d.querySelectorAll('.sheet').length")
        self.assertGreaterEqual(n, 2)
        self.assertEqual(self.frame("d.querySelectorAll('.pgno')[1].textContent"), f"Page 2 of {n}")
        self.look("#vw_pages", "1")
        self.assertIn("over the 1-page limit", self.page.text_content("#vwPages"))
        self.assertEqual(self.frame("d.querySelectorAll('.sheet.over').length"), n - 1)
        self.assertIn("over the 1-page limit", self.frame("d.querySelectorAll('.pgno')[1].textContent"))
        self.assertEqual(self.frame("d.querySelectorAll('.sheet')[0].classList.contains('over')"), False)
        self.assertEqual(frame.locator("h2").first.text_content(), "Topic 1")
        # print: the sheets themselves (stubbed: no print dialog in a test)
        self.page.evaluate("() => { window.__printed = 0; document.querySelector('#vwFrame').contentWindow.print = () => window.__printed++; }")
        self.page.get_by_role("button", name="Print").click()
        self.assertEqual(self.page.evaluate("window.__printed"), 1)
        self.page.get_by_role("button", name="Open in new window").click()
        self.idle()
        self.assertTrue(self.opened[-1][1].endswith("Northwind-Analytics-Research.html"), self.opened[-1])
        self.page.click("#vwClose")
        # compare two studio versions side by side
        self.page.evaluate("closeDrawer()")
        a = studio.build(req={"bullets_per_role": 1}, use_ai=False)
        b = studio.build(req={"template": "modern"}, use_ai=False)
        self.go("studio")
        self.page.evaluate("v => openViewer({type: 'studio', vid: v})", b["vid"])
        self.ready()
        self.assertEqual(self.page.input_value("#vw_template"), "modern")  # a version opens in its own look
        label = self.page.locator("#vwCmp option", has_text="Studio").filter(has_not_text=b["vid"]).first.text_content()
        self.page.select_option("#vwCmp", label=label)
        self.ready()
        self.page.wait_for_function("() => !document.querySelector('#vwFrame2').hidden && document.querySelector('#vwFrame2').contentDocument.querySelector('.sheet')")
        self.assertIn("bullet", self.page.text_content("#vwDiff"))
        self.assertGreater(self.frame("d.querySelectorAll('li').length"), self.frame("d.querySelectorAll('li').length", second=True))
        self.assertTrue(a["vid"])

    def test_entry_points_master_offers_counter_studio_prep_research_and_packet(self):
        studio.sync_master(force=True)
        self.go("profile")
        self.page.click("#mView")
        self.ready()
        self.assertEqual(self.page.text_content("#vwTitle"), "Master resume")
        self.press("Escape")
        self.page.wait_for_selector("#viewer", state="hidden")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "mView")  # focus goes back
        self.go("insights")
        self.page.click("#offerPanel summary:has-text('Draft a counter-offer')")
        self.page.select_option("#ctrJob", str(self.ids["offer"]))
        self.page.get_by_role("button", name="View offer notes").click()
        self.ready()
        self.assertIn("offer.md", self.page.text_content("#vwTitle"))
        self.assertIn(FLOOR, self.page.frame_locator("#vwFrame").locator("body").text_content())  # private notes: yours
        self.assertEqual(self.page.text_content("#vwGuards"), "")
        self.page.click("#vwClose")
        self.page.locator("#ctrAsk").fill("a base of 195,000")
        self.page.locator("#ctrTpl").check()
        self.run_click(self.page.get_by_role("button", name="Draft counter-offer"))
        self.page.click("#ctrView")
        self.ready()
        self.assertEqual(self.page.text_content("#vwTitle"), "Counter-offer draft")
        self.assertIn("195,000", self.page.frame_locator("#vwFrame").locator("body").text_content())
        self.page.click("#vwClose")
        v = studio.build(use_ai=False)
        self.go("studio")
        self.page.evaluate("v => openVersion(STU.versions.findIndex(x => x.vid === v))", v["vid"])
        self.idle()
        self.page.locator("#sResult").get_by_role("button", name="View / format").click()
        self.ready()
        self.assertIn(v["vid"], self.page.text_content("#vwTitle"))
        self.page.click("#vwClose")
        drawer = self.open_job(self.ids["saved"])
        drawer.get_by_role("button", name="View the interview prep").click()
        self.ready()
        self.assertIn("interview_prep.md", self.page.text_content("#vwTitle"))
        self.page.click("#vwClose")
        drawer.get_by_role("button", name="View the research pack").click()
        self.ready()
        self.assertIn("research.md", self.page.text_content("#vwTitle"))
        self.page.click("#vwClose")
        drawer.get_by_role("button", name="View documents").click()
        self.ready()
        self.assertEqual(self.page.locator("#vwDoc option").all_text_contents(),
                         ["resume.md", "cover_letter.md", "interview_prep.md", "research.md"])
        self.page.select_option("#vwDoc", "cover_letter.md")
        self.ready()
        self.assertIn("cover_letter.md", self.page.text_content("#vwTitle"))
        self.assertTrue(self.page.locator("#vwLDate").is_visible())

    def test_narrow_window_420(self):
        self.set_viewport(420)
        self.open_doc("resume.md")
        self.assertEqual(self.overflow(), [])
        wide = self.page.evaluate("""() => [...document.querySelectorAll('#viewer *')].filter(e => {
            const r = e.getBoundingClientRect(); return r.width && r.right > innerWidth + 1; }).map(e => e.tagName + '#' + e.id).slice(0, 5)""")
        self.assertEqual(wide, [])
        side, main = self.page.locator(".vwside").bounding_box(), self.page.locator(".vwmain").bounding_box()
        self.assertGreaterEqual(side["y"], main["y"] + main["height"] - 1)  # the panel sits under the page
        self.look("#vw_font", "Georgia")
        self.assertIn("Georgia", self.frame("getComputedStyle(d.body).fontFamily"))


if __name__ == "__main__":
    unittest.main()
