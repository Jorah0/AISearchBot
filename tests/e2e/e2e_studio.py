"""Studio tab, pass 17: a request + requirements build (the AI plan's invented number reverted and shown, its notes as
text), the sandboxed srcdoc preview inside the framed-denied page, refine, Build without AI with the formatting panel
(font, accent, section order and show/hide, leave out an entry, formats), Use for this job, Make this my default look,
Open, Delete, and Build in Studio from the drawer."""
import shutil
import unittest

from harness import E2ETestCase, db, resume

from lodestar import settings, studio

PLAN = {"summary": {"text": "Data engineer with 7 years building batch and streaming pipelines. Led a team of 30.", "refs": ["s0"]},
        "sections": [{"kind": "summary"},
                     {"kind": "experience", "items": [{"ref": "e1", "bullets": [
                         {"refs": ["e1.b2"], "text": "Cut warehouse spend 45% by moving cold tables to Iceberg on S3"},
                         {"refs": ["e1.b1"]}]}]},
                     {"kind": "skills", "groups": [{"label": "Data", "refs": ["k1", "k3"]}]}],
        "style": {"accent": "navy"}, "notes": "<b>Kept</b> it to one page."}


class Studio(E2ETestCase):
    ai_json = PLAN

    def setUp(self):
        super().setUp()
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        settings.set_pref("resume_look", {})
        self.go("studio")
        self.idle()

    def frame_text(self):
        return self.page.frame_locator("#sFrame").locator("body").text_content()

    def test_build_with_a_request_preview_checks_and_refine(self):
        self.page.fill("#sReq", "one page, navy accent, lead with cost savings")
        self.page.select_option("#sJob", str(self.ids["saved"]))
        self.run_click("#sBuild")
        self.expect_toast("version built", "ok")
        frame = self.page.frame_locator("#sFrame")
        self.assertEqual(frame.locator("h1").text_content(), "Pat Rivera")  # srcdoc renders inside the frame-denied page
        self.assertIn("Cut warehouse spend 40% by moving cold tables to Iceberg on S3", self.frame_text())
        self.assertNotIn("45%", self.frame_text())
        self.assertNotIn("team of 30", self.frame_text())
        self.assertEqual(frame.locator("script").count(), 0)
        warn = self.page.text_content("#sWarn")
        self.assertIn("e1.b2: reverted (new number 45)", warn)
        self.assertIn('summary: left out "Led a team of 30."', warn)
        self.assertIn("note: <b>Kept</b> it to one page.", warn)  # the AI's notes are text, never markup
        self.assertEqual(self.page.locator("#sWarn b").count(), 0)
        self.assertIn("<<<REQUEST\none page, navy accent, lead with cost savings\nREQUEST>>>", self.ai_calls[-1]["messages"][0]["content"])
        self.assertNotIn("pat.rivera@example.com", self.ai_calls[-1]["messages"][0]["content"])
        self.assertEqual(self.page.locator("#sHist .row").count(), 1)
        self.page.fill("#sRefine", "shorter")
        self.run_click(self.page.get_by_role("button", name="Refine"))
        self.expect_toast("refined version built", "ok")
        self.assertIn("PREVIOUS PLAN", self.ai_calls[-1]["messages"][0]["content"])
        self.assertEqual(self.page.locator("#sHist .row").count(), 2)
        self.assertIn("refined from", self.page.text_content("#sResult"))

    def test_formatting_offline_use_for_job_default_look_open_and_delete(self):
        self.page.click("#sMore > summary")
        self.page.select_option("#sL_font", "Georgia")
        self.page.select_option("#sL_accent", "teal")
        self.page.locator("#sSections .row", has_text="skills").locator("input").uncheck()
        self.page.get_by_role("button", name="move education up").click()
        self.page.get_by_role("button", name="move education up").click()
        self.assertEqual(self.page.locator("#sSections .row").nth(1).locator("input").get_attribute("value"), "education")
        self.page.locator("#sFormats input[value=txt]").check()
        self.page.click("#sMore details > summary")
        self.page.locator("#sDrop label", has_text="Mapleleaf Clinics").locator("input").check()
        self.run_click(self.page.get_by_role("button", name="Build without AI"))
        n = len(self.ai_calls)
        v = self.api("/api/studio/" + studio.versions()[0]["vid"])
        self.assertEqual((v["style"]["font"], v["style"]["accent"], v["used_ai"]), ("Georgia", "#0F6E6E", False))
        self.assertEqual(sorted(v["files"]), ["docx", "html", "md", "txt"])
        md = v["md"]
        self.assertLess(md.index("## Education"), md.index("## Experience"))
        for gone in ("## Skills", "Mapleleaf", "165,000", "Deal-breakers"):
            self.assertNotIn(gone, md)
        self.assertIn('font-family:"Georgia", Georgia, serif', v["html"])
        self.assertEqual(len(self.ai_calls), n)  # offline: no AI call
        self.page.select_option("#sUseJob", str(self.ids["saved"]))
        self.page.get_by_role("button", name="Use for this job").click()
        self.idle()
        self.expect_toast(f"job #{self.ids['saved']} now uses this version", "ok")
        job = db.get_job(self.ids["saved"])
        self.assertEqual((resume.app_dir(job) / "resume.md").read_text(encoding="utf-8"), md)
        self.assertTrue((resume.app_dir(job) / "resume.docx").is_file())
        self.page.get_by_role("button", name="Make this my default look").click()
        self.idle()
        self.expect_toast("saved as your default look", "ok")
        self.assertEqual(settings.pref("resume_look")["font"], "Georgia")
        self.page.get_by_role("button", name="Open DOCX").click()
        self.idle()
        self.assertTrue(self.opened[-1][1].endswith(v["files"]["docx"]))
        self.answer(True)
        self.page.locator("#sHist .row").first.get_by_role("button", name="Delete").click()
        self.idle()
        self.expect_toast("version deleted", "ok")
        self.assertEqual(studio.versions(), [])
        self.assertFalse(self.page.locator("#sResult").is_visible())

    def test_build_in_studio_from_the_drawer(self):
        self.go("board")
        drawer = self.open_job(self.ids["saved"])
        drawer.get_by_role("button", name="Build in Studio").click()
        self.idle()
        self.assertTrue(self.page.locator("section#studio").is_visible())
        self.assertEqual(self.page.input_value("#sJob"), str(self.ids["saved"]))
        self.assertFalse(self.page.locator("#sJd").is_visible())


if __name__ == "__main__":
    unittest.main()
