"""Setup > Data > Restore from backup: Backup now fills the list, a cancelled confirm changes nothing, Restore puts the
tracker back and says what was restored (counts, the safety backup, keyring secrets left alone), a bad zip is refused in
place before anything changes, and the controls work from the keyboard."""
import unittest
import zipfile

from harness import E2ETestCase, db


class Restore(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("setup")

    def backup_now(self):
        self.run_click(self.page.locator("#setup").get_by_role("button", name="Backup now"))
        self.page.wait_for_function("() => document.querySelector('#rsPick').value.endsWith('.zip')")
        return self.page.input_value("#rsPick")

    def test_backup_then_restore_puts_the_tracker_back_and_says_what_it_did(self):
        jobs = len(self.state()["jobs"])
        name = self.backup_now()
        self.assertTrue(name.startswith("lodestar-backup-"))
        extra = self.api("/api/jobs", {"company": "Late Addition Inc", "title": "Data Engineer", "jd": "added after the backup"})
        self.assertNotIn("error", extra)
        self.reload_state()
        self.assertEqual(len(self.state()["jobs"]), jobs + 1)
        self.answer(False)  # cancelled: nothing happens
        self.page.click("#rsGo")
        self.assertIn(f"Restore {name}?", self.dialogs[-1])
        self.assertIn("Keyring secrets", self.dialogs[-1])
        self.assertEqual(self.page.text_content("#rsOut"), "")
        self.answer(True)
        self.run_click("#rsGo")
        done = self.page.locator("#rsDone")
        done.wait_for()
        text = done.text_content()
        self.assertIn(f"from {name}", text)
        self.assertIn(f"{jobs} jobs", text)
        self.assertIn("Safety backup of what was there", text)
        self.assertIn("before-restore-", text)
        self.assertIn("keyring", text)
        self.expect_toast("backup restored", "ok")
        self.assertEqual(len(self.state()["jobs"]), jobs)
        self.assertNotIn("Late Addition Inc", [j["company"] for j in self.state()["jobs"]])
        self.assertTrue(any(o.startswith("before-restore-") for o in
                            self.page.eval_on_selector_all("#rsPick option", "os => os.map(o => o.value)")))

    def test_a_bad_zip_is_refused_in_place_and_nothing_changes(self):
        self.allow_console()
        self.backup_now()
        bad = self.home / "backups" / "not-lodestar.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("../escape.md", "x")
            z.writestr("lodestar.db", "x")
        self.addCleanup(bad.unlink, missing_ok=True)
        jobs = len(self.state()["jobs"])
        self.page.locator("#setup").get_by_role("button", name="Refresh").click()
        self.idle()
        self.page.select_option("#rsPick", "not-lodestar.zip")
        self.answer(True)
        self.run_click("#rsGo")
        err = self.page.locator("#rsErr")
        err.wait_for()
        self.assertIn("unsafe path", err.text_content())
        self.assertIn("nothing was changed", err.text_content())
        self.assertFalse((self.home.parent / "escape.md").exists())
        self.assertEqual(len(self.state()["jobs"]), jobs)
        self.assertFalse(any(p.name.startswith("before-restore-") for p in (self.home / "backups").glob("*.zip")))
        db.release()

    def test_keyboard_reaches_the_picker_and_restore(self):
        self.backup_now()
        self.page.focus("#rsPick")
        self.press("Tab")
        self.assertIn("Refresh", self.focused())
        self.press("Tab")
        self.assertEqual(self.focused().split(" ")[0], "button#rsGo.b.danger")
        self.answer(False)
        self.press("Enter")
        self.assertIn("Restore ", self.dialogs[-1])


if __name__ == "__main__":
    unittest.main()
