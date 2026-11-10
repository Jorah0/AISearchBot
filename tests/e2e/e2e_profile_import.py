"""Profile, pass 17: the import review (conflict keep mine / use incoming, flagged rows, the 'Not stored' note, lines not
read, Re-read my master profile, bank chips of the new kinds), the stale-editor guard on Save, the master resume card
(Update now, Open, Show folder, the 'profile changed' state) and the drawer's 'profile changed' badge."""
import unittest

from harness import PROFILE_MD, E2ETestCase, db, profile, resume

RESUME = b"""Pat Rivera
Date of Birth: 1990-04-02
pat.rivera@example.com | Portland, OR

## Experience
### Senior Data Engineer - Tidewater Logistics (2021 - 2024)
- Rebuilt the nightly freight ETL on Spark and Airflow, cutting runtime from 6 hours to 50 minutes
A sentence the parser keeps for you to see

## Awards
- Data Hero - Tidewater Logistics (2023)
"""


class ProfileImport(E2ETestCase):
    def setUp(self):
        super().setUp()
        profile.write_master(PROFILE_MD)
        profile.BANK.unlink(missing_ok=True)
        for p in profile.pending_imports():
            profile.discard_import(p["id"])
        self.go("profile")
        self.page.evaluate("loadProfile(); loadBank(); loadReviews(); loadMaster()")
        self.idle()

    def upload_and_import(self, name, data):
        self.page.check("#pNoAi")
        self.page.set_input_files("#pFile", files=[{"name": name, "mimeType": "text/plain", "buffer": data}])
        self.run_click(self.page.locator("#profile .panel", has_text="Import an existing resume").get_by_role("button", name="Import"))
        return self.page.locator("#pReview .review", has_text=name)

    def test_review_conflict_use_incoming_not_stored_and_unread(self):
        self.run_click(self.page.get_by_role("button", name="Re-read my master profile"))
        self.expect_toast("profile.md read into a review below", "ok")
        self.run_click(self.page.locator("#pReview .review", has_text="profile.md").get_by_role("button", name="Accept all new"))
        self.assertEqual(self.page.locator("#pReview .review").count(), 0)
        self.assertEqual(profile.load()["experience"][0]["end"], "Present")
        review = self.upload_and_import("pat-2024.txt", RESUME)
        self.assertIn("Not stored: date of birth (line 2)", review.locator(".warnbox").text_content())
        self.assertNotIn("1990", review.text_content())
        review.locator("summary", has_text="were not read").click()
        self.assertIn("A sentence the parser keeps for you to see", review.locator("pre").text_content())
        row = review.locator("tr", has_text="Tidewater Logistics (2021 - 2024)")
        self.assertIn("conflict", row.text_content())
        self.assertIn("end: yours Present · incoming 2024", row.text_content())
        self.assertEqual(row.locator("select").input_value(), "mine")
        row.locator("select").select_option("incoming")
        award = review.locator("tr", has_text="Data Hero")
        self.assertTrue(award.locator("input[type=checkbox]").is_checked())
        snaps = len(list(profile.HISTORY.glob("profile-*.md")))
        self.run_click(review.get_by_role("button", name="Apply selected"))
        self.assertIn("applied: 1 awards; 1 updated; profile.md updated", self.expect_toast("applied:", "ok"))
        self.assertEqual(profile.load()["experience"][0]["end"], "2024")
        text = profile.master_text()
        self.assertIn("### Senior Data Engineer - Tidewater Logistics (2021 - 2024)", text)
        self.assertLess(text.index("## Awards"), text.index("## Preferences"))
        self.assertEqual(len(list(profile.HISTORY.glob("profile-*.md"))), snaps + 1)
        self.assertEqual(self.page.input_value("#pText"), text)  # no unsaved edits: the editor reloaded
        chip = self.page.locator("#bMore .pill", has_text="Data Hero - Tidewater Logistics")
        self.assertEqual(chip.count(), 1)
        chip.get_by_role("button", name="remove").click()
        self.idle()
        self.expect_toast("removed Data Hero - Tidewater Logistics", "ok")
        self.assertEqual(profile.load()["awards"], [])

    def test_stale_editor_save_is_refused_after_an_import(self):
        self.allow_console()  # the 409 is logged by the browser
        self.page.fill("#pText", PROFILE_MD + "\nMy unsaved line\n")
        profile.write_master(PROFILE_MD + "\n## Awards\n- Imported meanwhile\n")  # an import applied from elsewhere
        self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.expect_toast("save failed: profile.md changed since you opened it", "err")
        self.assertIn("Imported meanwhile", profile.master_text())
        self.assertNotIn("My unsaved line", profile.master_text())
        self.page.evaluate("loadProfile()")
        self.idle()
        self.page.fill("#pText", profile.master_text() + "\nMy line, redone\n")
        self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.expect_toast("profile saved", "ok")
        self.assertIn("My line, redone", profile.master_text())

    def test_master_card_update_now_open_and_stale(self):
        self.assertIn("Not built yet", self.page.text_content("#mStatus"))
        card = self.page.locator("#masterCard")
        self.run_click(card.get_by_role("button", name="Update now"))
        self.expect_toast("master resume updated", "ok")
        self.assertIn("Updated from your profile at", self.page.text_content("#mStatus"))
        self.assertIn("first build", self.page.text_content("#mDiff"))
        self.assertTrue((profile.RESUMES / "master.docx").is_file())
        self.assertNotIn("Salary floor", (profile.RESUMES / "master.md").read_text(encoding="utf-8"))
        opened = len(self.opened)
        self.page.click("#mPdf")  # no PDF engine in the browser tests: the print page opens instead
        self.idle()
        self.assertTrue(self.opened[opened][1].endswith("master.html"))
        card.get_by_role("button", name="Open DOCX").click()
        self.idle()
        self.assertTrue(self.opened[-1][1].endswith("master.docx"))
        card.get_by_role("button", name="Show folder").click()
        self.idle()
        self.assertTrue(self.opened[-1][1].endswith("resumes"))
        self.page.fill("#pText", PROFILE_MD.replace("health and logistics teams", "health, freight and logistics teams"))
        self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.assertIn("profile changed", self.page.text_content("#mStatus"))
        self.run_click(card.get_by_role("button", name="Update now"))
        self.assertIn("summary edited", self.page.text_content("#mDiff"))
        self.assertNotIn("profile changed", self.page.text_content("#mStatus"))
        self.page.fill("#pText", PROFILE_MD.replace("## Preferences", "## Notes\nAsk Sam\n\n## Preferences"))
        self.page.locator("#profile > .row").get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.run_click(card.get_by_role("button", name="Update now"))
        self.assertIn("'## Notes' is in your master resume", self.page.text_content("#mWarn"))
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])

    def test_drawer_badge_when_a_used_section_changed(self):
        jid = self.ids["saved"]
        resume._save_resume(db.get_job(jid), "# Pat Rivera\nPat Rivera | pat.rivera@example.com\n## Experience\n"
                                             "### Senior Data Engineer - Tidewater Logistics\n- Rebuilt the nightly freight ETL\n", 0)
        try:
            self.reload_state()
            self.open_job(jid)
            self.assertEqual(self.page.locator("#jProfileChanged").count(), 0)
            profile.write_master(PROFILE_MD.replace("## Skills\nPython,", "## Skills\nRust, Python,"))  # not on this resume
            self.reload_state()
            self.open_job(jid)
            self.assertEqual(self.page.locator("#jProfileChanged").count(), 0)
            profile.write_master(PROFILE_MD.replace("(2021-present)", "(2021-2024)"))
            self.reload_state()
            self.open_job(jid)
            badge = self.page.locator("#jProfileChanged")
            self.assertIn("Profile changed since this resume was made (Experience)", badge.text_content())
        finally:
            db.update_job(jid, touch=False, profile_rev=None)
            (resume.app_dir(db.get_job(jid)) / "resume.md").unlink(missing_ok=True)
            profile.write_master(PROFILE_MD)


if __name__ == "__main__":
    unittest.main()
