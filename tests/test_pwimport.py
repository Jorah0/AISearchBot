"""Importing logins from a password manager (pass 48): CSV exports of Chrome / Edge, Firefox, Bitwarden, 1Password,
LastPass and the like; only job-application sites (an application system, or the site of a job you track) are kept,
never LinkedIn / Indeed / Glassdoor / ZipRecruiter / SimplyHired; a review first (sites and usernames, never a
password), held in memory only and for minutes; on Import every password goes to the OS keyring through accounts.add
and nowhere else (no file, no answer, no AI). The keyring is faked; every patch is put back."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

import keyring  # noqa: E402

from lodestar import accounts, config, db, pwimport  # noqa: E402

CHROME = ("name,url,username,password,note\n"
          "greenhouse,https://boards.greenhouse.io/users/sign_in,pat@example.com,Gh-Secret-111,\n"
          "workday,https://acme.wd5.myworkdayjobs.com/en-US/careers/login,pat@example.com,Wd-Secret-222,\n"
          "linkedin,https://www.linkedin.com/login,pat@example.com,Li-Secret-333,\n"
          "bank,https://bank.example/login,pat,Bank-Secret-444,\n"
          "careers,https://careers.trackedco.example/login,pat@example.com,Co-Secret-555,\n"
          "nouser,https://jobs.lever.co/acme,,Lv-Secret-666,\n")
BITWARDEN = ("folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp\n"
             ",,login,Ashby,,,0,https://jobs.ashbyhq.com/acme,pat@example.com,Ab-Secret-777,\n")
ONEPASSWORD = "Title,Url,Username,Password,OTPAuth,Favorite,Archived,Tags,Notes\nLever,https://jobs.lever.co/acme,pat,Lv-Secret-888,,,,,\n"
SECRETS = ("Gh-Secret-111", "Wd-Secret-222", "Li-Secret-333", "Bank-Secret-444", "Co-Secret-555", "Lv-Secret-666",
           "Ab-Secret-777", "Lv-Secret-888")


class Base(unittest.TestCase):
    def setUp(self):
        self.store = {}
        for k, f in (("get_password", lambda s, n: self.store.get((s, n))),
                     ("set_password", lambda s, n, v: self.store.__setitem__((s, n), v)),
                     ("delete_password", lambda s, n: self.store.pop((s, n), None))):
            old = getattr(keyring, k)
            setattr(keyring, k, f)
            self.addCleanup(setattr, keyring, k, old)
        db.con().execute("DELETE FROM site_accounts")
        db.con().commit()
        self.addCleanup(lambda: (db.con().execute("DELETE FROM site_accounts"), db.con().commit()))
        jid = db.add_job("Trackedco", "Data Engineer", "https://careers.trackedco.example/jobs/9", "x", None)
        self.addCleanup(db.delete_job, jid)


class Import(Base):
    def test_known_exports_parse(self):
        self.assertEqual(pwimport.parse(BITWARDEN), [("https://jobs.ashbyhq.com/acme", "pat@example.com", "Ab-Secret-777")])
        self.assertEqual(pwimport.parse(ONEPASSWORD)[0][1:], ("pat", "Lv-Secret-888"))
        self.assertEqual(len(pwimport.parse("﻿" + CHROME)), 6)  # a BOM from Excel is fine
        with self.assertRaisesRegex(SystemExit, "URL column and a password column"):
            pwimport.parse("a,b\n1,2\n")

    def test_the_review_keeps_job_sites_only_and_never_shows_a_password(self):
        r = pwimport.stage(CHROME)
        self.assertEqual(sorted(s["site"] for s in r["sites"]),
                         ["acme.wd5.myworkdayjobs.com", "boards.greenhouse.io", "careers.trackedco.example"])
        self.assertEqual(r["skipped"], {"a big job board Lodestar never signs in to": 1, "not a job-application site": 1,
                                        "no username": 1})
        text = json.dumps(r)
        self.assertFalse([s for s in SECRETS if s in text])
        self.assertEqual(self.store, {})  # nothing saved until you press Import
        pwimport.discard(r["id"])
        with self.assertRaisesRegex(SystemExit, "expired or was used"):
            pwimport.apply(r["id"])

    def test_import_saves_each_password_only_in_the_keyring(self):
        r = pwimport.stage(CHROME)
        out = pwimport.apply(r["id"], ["boards.greenhouse.io", "careers.trackedco.example"])
        self.assertEqual(sorted(out["saved"]), ["boards.greenhouse.io", "careers.trackedco.example"])
        self.assertFalse([s for s in SECRETS if s in json.dumps(out)])
        self.assertEqual(sorted(v for v in self.store.values()), ["Co-Secret-555", "Gh-Secret-111"])
        row = accounts.for_site("boards.greenhouse.io")
        self.assertEqual((row["username"], row["created_by"]), ("pat@example.com", "import"))
        rows = json.dumps([dict(x) for x in db.con().execute("SELECT * FROM site_accounts").fetchall()])
        self.assertNotIn("Gh-Secret-111", rows)  # never in the database
        with self.assertRaisesRegex(SystemExit, "expired or was used"):
            pwimport.apply(r["id"])  # one use
        again = pwimport.stage(CHROME)  # a site already saved is never overwritten
        self.assertEqual(again["skipped"].get("already saved in Lodestar"), 2)

    def test_a_review_expires_and_full_ai_cannot_import(self):
        r = pwimport.stage(CHROME)
        later = pwimport._now() + pwimport.TTL + 1
        with patched(pwimport, _now=lambda: later):
            pwimport.stage(BITWARDEN)  # any new review sweeps expired ones
        with self.assertRaisesRegex(SystemExit, "expired or was used"):
            pwimport.apply(r["id"])
        r = pwimport.stage(CHROME)
        config.FULL_AI.on = True  # Full AI (the advisor writing on its own) never writes the vault
        try:
            out = pwimport.apply(r["id"])
        finally:
            config.FULL_AI.on = False
        self.assertEqual(out["saved"], [])
        self.assertEqual(self.store, {})

    def test_the_command_reviews_then_imports_with_yes_and_deletes_the_file(self):
        import argparse
        import contextlib
        import io

        from lodestar import cli

        f = Path(tempfile.mkdtemp()) / "export.csv"
        f.write_text(CHROME, encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.cmd_accounts(argparse.Namespace(op="import", file=str(f), yes=False, delete=False))
        self.assertIn("boards.greenhouse.io", out.getvalue())
        self.assertIn("nothing saved", out.getvalue())
        self.assertEqual(self.store, {})
        with contextlib.redirect_stdout(out):
            cli.cmd_accounts(argparse.Namespace(op="import", file=str(f), yes=True, delete=True))
        self.assertEqual(len(self.store), 3)
        self.assertFalse(f.exists())
        self.assertFalse([s for s in SECRETS if s in out.getvalue()])  # never printed

    def test_too_big_a_file_is_refused(self):
        with self.assertRaisesRegex(SystemExit, "too large"):
            pwimport.parse("url,password\n" + "https://x.example/,p\n" * 200_000)


if __name__ == "__main__":
    unittest.main()
