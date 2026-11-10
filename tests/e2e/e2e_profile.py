"""Profile: the master editor (Save with a snapshot, Check, AI review, Adjust; empty and blank input; the unsaved-edits
guard), the profile bank (LinkedIn link and data-request link, skills / languages / certifications add, duplicate,
remove, counts), imports (no file, offline-only, AI extraction, LinkedIn zip, .docx; the import review with Replace and
Merge; saved resumes; file audit), Rebuild master from the bank (cancel, unsaved warning, snapshot to restore from),
keyboard and 420px."""
import io
import unittest
import zipfile

import docx
from harness import PROFILE_MD, E2ETestCase, profile

AI_FACTS = {"contact": {"name": "Pat Rivera", "email": "pat.rivera@example.com"}, "summary": "Data engineer.",
            "skills": [{"name": "Kubernetes", "category": "platform"}, {"name": "Flink", "category": "streaming"}],
            "languages": [{"name": "Portuguese", "proficiency": "B1"}], "experience": [], "education": [],
            "certifications": [{"name": "dbt Analytics Engineering", "issuer": "dbt Labs"}], "projects": []}
RESUME_MD = """# Pat Rivera
pat.rivera@example.com | Portland, OR

## Skills
Python, SQL, Snowflake, Looker

## Languages
Spanish (B2)
"""


def _zip(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)
    return b.getvalue()


def _docx(*paras) -> bytes:
    d = docx.Document()
    for p in paras:
        d.add_paragraph(p)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


class Profile(E2ETestCase):
    ai_json = AI_FACTS

    def setUp(self):
        super().setUp()
        self.go("profile")
        self.page.wait_for_function("() => $('#pText').value.length > 0 && BANK")

    def snaps(self):
        return sorted(profile.HISTORY.glob("profile-*.md"))

    def bank(self):
        return profile.load()

    def names(self, kind):
        return [x["name"] for x in self.bank()[kind]]

    def upload(self, sel, name, data, mime="application/octet-stream"):
        self.page.set_input_files(sel, files=[{"name": name, "mimeType": mime, "buffer": data}])

    # --- master editor
    def test_save_check_review_adjust_and_blank_input(self):
        self.allow_console()
        self.assertEqual(self.page.input_value("#pText"), profile.master_text())
        self.assertTrue(self.page.text_content("#pPath").endswith("profile.md"))
        # Check: offline lint with line numbers; an empty editor is refused, not silently replaced by the file
        self.run_click(self.page.get_by_role("button", name="Check", exact=True))
        self.assertIn("Resume check", self.page.text_content("#pCheck"))
        self.assertRegex(self.page.text_content("#pCheck"), r"score \d+/100")
        text = self.page.input_value("#pText")
        self.page.fill("#pText", "")
        self.run_click(self.page.get_by_role("button", name="Check", exact=True))
        self.expect_toast("error: nothing to check: the text is empty", "err")
        self.run_click(self.page.get_by_role("button", name="AI review"))
        self.expect_toast("error: nothing to review: the text is empty", "err")
        self.page.fill("#pText", text)
        self.run_click(self.page.get_by_role("button", name="AI review"))
        self.assertEqual(self.page.text_content("#pOut"), self.ai_text)
        self.assertIn("Rebuilt the nightly freight ETL", str(self.ai_calls[-1]["messages"]))
        # Adjust: blank refused; the result replaces the editor and nothing is saved
        self.page.get_by_role("button", name="Adjust").click()
        self.expect_toast("type an instruction first", "err")
        on_disk = profile.master_text()
        self.page.fill("#pAdj", "tighten the summary")
        self.run_click(self.page.get_by_role("button", name="Adjust"))
        self.expect_toast("adjusted; review, then Save", "ok")
        self.assertEqual(self.page.input_value("#pText"), self.ai_text)
        self.assertEqual(profile.master_text(), on_disk)
        self.assertTrue(self.page.evaluate("""() => { const e = new Event('beforeunload', {cancelable: true});
            window.dispatchEvent(e); return e.defaultPrevented; }"""))  # leaving now asks first
        # Save: the old file is snapshotted first
        snaps = len(self.snaps())
        edited = text.replace("Data engineer with 7 years", "Data engineer with 8 years")
        self.page.fill("#pText", edited)
        self.run_click(self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True))
        self.expect_toast("profile saved (previous version kept in profile-history/)", "ok")
        self.assertEqual(profile.master_text(), edited)
        self.assertEqual(len(self.snaps()), snaps + 1)
        self.assertEqual(self.snaps()[-1].read_text(encoding="utf-8"), on_disk)
        self.assertFalse(self.page.evaluate("""() => { const e = new Event('beforeunload', {cancelable: true});
            window.dispatchEvent(e); return e.defaultPrevented; }"""))
        self.page.fill("#pText", PROFILE_MD)  # back to the seed for the other tests
        self.run_click(self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True))

    # --- bank: manual edits
    def test_bank_linkedin_link_and_manual_facts(self):
        self.allow_console()
        self.assertEqual(self.page.get_attribute("#liExport", "href"), profile.LINKEDIN_EXPORT_URL)
        link = self.page.locator("#bankPanel .row", has=self.page.locator("#liUrl")).get_by_role("button", name="Link")
        link.click()
        self.expect_toast("paste your LinkedIn profile URL first", "err")
        self.page.fill("#liUrl", "my profile")
        link.click()
        self.idle()
        self.expect_toast("error: expected a profile URL like https://www.linkedin.com/in/your-name", "err")
        self.page.fill("#liUrl", "linkedin.com/in/pat-rivera-example")
        link.click()
        self.idle()
        self.expect_toast("LinkedIn linked", "ok")
        self.assertEqual(self.bank()["contact"]["linkedin"], "https://www.linkedin.com/in/pat-rivera-example")
        self.assertEqual(self.page.input_value("#liUrl"), "https://www.linkedin.com/in/pat-rivera-example")
        for kind, box, detail, name, det, chips, label in (
                ("skills", "#bSkill", "#bSkillCat", "Rust", "language", "#bSkills", "Rust · language"),
                ("languages", "#bLang", "#bLangLvl", "Spanish", "B2", "#bLangs", "Spanish · B2"),
                ("certifications", "#bCert", "#bCertIss", "AWS Certified Data Engineer", "Amazon", "#bCerts",
                 "AWS Certified Data Engineer · Amazon")):
            add = self.page.locator("#bankPanel .row", has=self.page.locator(box)).get_by_role("button", name="Add")
            add.click()
            self.expect_toast("type a name first", "err")
            self.page.fill(box, name)
            self.page.fill(detail, det)
            add.click()
            self.idle()
            self.expect_toast(f"{kind[:-1]} added", "ok")
            self.assertIn(name, self.names(kind))
            self.assertEqual([self.page.input_value(box), self.page.input_value(detail)], ["", ""])
            chip = self.page.locator(f"{chips} .pill", has_text=label)
            self.assertEqual(chip.count(), 1)
            self.page.fill(box, name.lower())  # the same entry again
            add.click()
            self.idle()
            self.expect_toast("already in the bank (or not a valid entry)", "err")
            self.assertEqual(self.names(kind).count(name), 1)
            self.assertIn(f"{len(self.bank()['certifications'])} certifications", self.page.text_content("#bCounts"))
            chip.get_by_role("button", name="remove").click()
            self.idle()
            self.expect_toast(f"removed {name}", "ok")
            self.assertNotIn(name, self.names(kind))
            self.assertEqual(chip.count(), 0)

    # --- imports
    def test_import_resume_offline_review_replace_and_merge(self):
        self.allow_console()
        self.page.locator("#profile .panel", has_text="Import an existing resume").get_by_role("button", name="Import").click()
        self.expect_toast("choose a file first", "err")
        self.page.check("#pNoAi")
        self.upload("#pFile", "old-resume.md", RESUME_MD.encode(), "text/markdown")
        calls = len(self.ai_calls)
        self.run_click(self.page.locator("#profile .panel", has_text="Import an existing resume").get_by_role("button", name="Import"))
        msg = self.expect_toast("saved old-resume.md:", "ok")
        self.assertIn("(offline extraction)", msg)
        self.assertEqual(len(self.ai_calls), calls)  # offline only: the file never went to an AI provider
        self.assertIn("Snowflake", self.names("skills"))
        self.assertIn("Spanish", self.names("languages"))
        self.assertIn("Snowflake", self.page.text_content("#bSkills"))
        self.assertTrue(self.page.is_visible("#pImport"))
        self.assertIn("Snowflake", self.page.input_value("#pImport"))
        self.page.click("#bankPanel summary:text('Saved resumes')")
        self.assertIn("old-resume.md", self.page.text_content("#bResumes"))
        self.assertEqual(sum(r["name"] == "old-resume.md" for r in self.bank()["resumes"]), 1)
        on_disk = profile.master_text()
        self.page.get_by_role("button", name="Replace profile with this text").click()
        self.expect_toast("replaced the editor; review, then Save", "ok")
        self.assertEqual(self.page.input_value("#pText"), self.page.input_value("#pImport"))
        self.assertEqual(profile.master_text(), on_disk)  # nothing saved
        self.run_click(self.page.get_by_role("button", name="Merge into my profile (AI)"))
        self.expect_toast("merged into the editor; review, then Save", "ok")
        self.assertIn(self.ai_text, self.page.input_value("#pText"))
        self.assertIn("Snowflake", str(self.ai_calls[-1]["messages"]))
        self.assertEqual(profile.master_text(), on_disk)
        self.run_click(self.page.locator("#profile .panel", has_text="Import an existing resume").get_by_role("button", name="Import"))
        self.expect_toast("already saved old-resume.md", "ok")  # the same file again: no second copy
        self.assertEqual(sum(r["name"] == "old-resume.md" for r in self.bank()["resumes"]), 1)
        self.page.evaluate("loadProfile()")

    def test_import_with_ai_linkedin_zip_docx_and_audit(self):
        self.allow_console()
        self.page.uncheck("#pNoAi")
        imp = self.page.locator("#profile .panel", has_text="Import an existing resume").get_by_role("button", name="Import")
        self.upload("#pFile", "ai-resume.txt", b"Pat Rivera\nSkills: Python, Kubernetes, Flink\n", "text/plain")
        self.run_click(imp)
        self.assertIn("(AI extraction)", self.expect_toast("saved ai-resume.txt:", "ok"))
        self.assertTrue({"Kubernetes", "Flink"} <= set(self.names("skills")))
        self.assertIn("dbt Analytics Engineering", self.names("certifications"))
        self.assertIn("Kubernetes · platform", self.page.text_content("#bSkills"))
        # LinkedIn: a bad file, then the export zip (profile facts only; never an AI call)
        li = self.page.get_by_role("button", name="Import LinkedIn")
        li.click()
        self.expect_toast("choose a file first", "err")
        self.upload("#liFile", "export.zip", _zip({"Notes.csv": "x\n1\n"}), "application/zip")
        self.run_click(li)
        self.expect_toast("error: this zip has no LinkedIn profile files", "err")
        calls = len(self.ai_calls)
        self.upload("#liFile", "Basic_LinkedInDataExport.zip", _zip({
            "Profile.csv": "First Name,Last Name,Headline,Geo Location,Summary\nPat,Rivera,Data Engineer,\"Portland, OR\",Pipelines\n",
            "Skills.csv": "Name\nApache Iceberg\nTerraform\n",
            "Languages.csv": "Name,Proficiency\nFrench,Elementary proficiency\n"}), "application/zip")
        self.run_click(li)
        self.expect_toast("saved Basic_LinkedInDataExport.zip:", "ok")
        self.assertEqual(len(self.ai_calls), calls)
        self.assertIn("Apache Iceberg", self.names("skills"))
        self.assertIn("French", self.names("languages"))
        self.assertTrue(self.page.is_hidden("#pImport") or "Apache Iceberg" not in self.page.input_value("#pImport"))
        # the file audit reads the newest saved .docx / .pdf
        audit = self.page.get_by_role("button", name="Audit latest saved resume file")
        if not any(r["file"].endswith((".docx", ".pdf")) for r in self.bank()["resumes"]):
            self.run_click(audit)
            self.expect_toast("error: no .docx or .pdf resume saved in the profile bank yet", "err")
        self.page.check("#pNoAi")
        self.upload("#pFile", "resume.docx", _docx("Pat Rivera", "Skills", "Python, SQL, Airflow"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.run_click(imp)
        self.expect_toast("saved resume.docx:", "ok")
        self.run_click(audit)
        self.assertIn("File audit: resume.docx", self.page.text_content("#bAudit"))
        self.page.click("#bAudit summary:text('What a parser sees')")
        self.assertIn("Python, SQL, Airflow", self.page.text_content("#bAudit pre"))
        self.page.evaluate("loadProfile()")

    # --- rebuild, and the snapshot to restore from
    def test_rebuild_master_cancel_unsaved_warning_and_snapshot(self):
        before = profile.master_text()
        btn = self.page.get_by_role("button", name="Rebuild master profile from bank")
        self.answer(False)
        btn.click()
        self.assertIn("snapshotted to profile-history/ first", self.dialogs[-1])
        self.assertNotIn("UNSAVED", self.dialogs[-1])
        self.idle()
        self.assertEqual(profile.master_text(), before)
        self.page.fill("#pText", before + "\nAn unsaved line.\n")
        self.answer(False)
        btn.click()
        self.assertIn("The editor has UNSAVED changes", self.dialogs[-1])
        self.idle()
        snaps = len(self.snaps())
        self.answer(True)
        self.run_click(btn)
        self.expect_toast("master rebuilt from the bank", "ok")
        rebuilt = profile.master_text()
        self.assertNotEqual(rebuilt, before)
        self.assertEqual(self.page.input_value("#pText"), rebuilt)
        self.assertIn("Pat Rivera", rebuilt)
        self.assertIn("Salary floor", rebuilt)  # the private Preferences section is carried over
        self.assertEqual(len(self.snaps()), snaps + 1)
        snap = self.snaps()[-1]
        self.assertEqual(snap.read_text(encoding="utf-8"), before)  # restore = save this snapshot back
        self.page.fill("#pText", snap.read_text(encoding="utf-8"))
        self.run_click(self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True))
        self.assertEqual(profile.master_text(), before)

    def test_keyboard_and_420px(self):
        self.page.focus("#bSkill")
        self.page.keyboard.type("Great Expectations")
        self.press("Tab", "Tab", "Enter")  # category, then Add
        self.idle()
        self.assertIn("Great Expectations", self.names("skills"))
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
