"""Importing logins from a password manager on the Accounts tab (pass 48): choose the CSV export, the review lists
job-application sites and usernames (never a password), untick one, Import: the kept passwords land only in the
(faked) keyring, the accounts list shows them, and no password ever reaches the page."""
import tempfile
import unittest
from pathlib import Path

from harness import E2ETestCase, db

CSV = ("name,url,username,password\n"
       "greenhouse,https://boards.greenhouse.io/users/sign_in,pat@example.com,Gh-Page-Secret-1\n"
       "lever,https://jobs.lever.co/login,pat@example.com,Lv-Page-Secret-2\n"
       "linkedin,https://www.linkedin.com/login,pat@example.com,Li-Page-Secret-3\n"
       "bank,https://bank.example/login,pat,Bank-Page-Secret-4\n")


class PwImport(E2ETestCase):
    def test_review_untick_import_and_no_password_on_the_page(self):
        db.con().execute("DELETE FROM site_accounts")
        db.con().commit()
        f = Path(tempfile.mkdtemp()) / "logins.csv"
        f.write_text(CSV, encoding="utf-8")
        self.go("accounts")
        self.page.click("#acctImport summary")
        self.page.set_input_files("#acctImpFile", str(f))
        review = self.page.locator("#acctImpReview")
        review.get_by_role("button", name="Import selected").wait_for()
        text = review.text_content()
        self.assertIn("4 login(s) in the file; 2 job-application site(s)", text)
        self.assertIn("1 a big job board Lodestar never signs in to", text)
        self.assertIn("1 not a job-application site", text)
        self.assertIn("boards.greenhouse.io", text)
        self.assertIn("jobs.lever.co", text)
        review.get_by_label("jobs.lever.co").uncheck()
        self.run_click(review.get_by_role("button", name="Import selected"))
        self.expect_toast("imported 1 login(s) into the encrypted store", "ok")
        self.assertEqual(sorted(v for (svc, name), v in self.keyring.items() if name.startswith("site:")), ["Gh-Page-Secret-1"])
        html = self.page.content()
        for secret in ("Gh-Page-Secret-1", "Lv-Page-Secret-2", "Li-Page-Secret-3", "Bank-Page-Secret-4"):
            self.assertNotIn(secret, html)
        self.page.wait_for_function("() => document.querySelector('#acctList').textContent.includes('boards.greenhouse.io')")


if __name__ == "__main__":
    unittest.main()
