"""No duplicate watches: a saved search differing only in case, spacing or comma spacing, a careers page URL differing
only in scheme, www., case of the host, a default port, a trailing slash or a #fragment, and a company board slug
differing only in case all update the watch already there (same id, original spelling kept) instead of adding one.
No network; every watch added here is removed."""
import os
import sys
import tempfile
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import db  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class NoDuplicates(unittest.TestCase):
    def tearDown(self):
        for w in db.watches():
            if "dedupe" in w["url"].lower():
                db.con().execute("DELETE FROM watches WHERE id=?", (w["id"],))
        for c in db.companies():
            if c["slug"].lower() == "dedupeco":
                db.con().execute("DELETE FROM companies WHERE id=?", (c["id"],))
        db.con().commit()

    def ids(self, part):
        return [(w["id"], w["url"]) for w in db.watches() if part in w["url"].lower()]

    def test_saved_searches_differing_in_case_or_spacing_are_one(self):
        self.assertFalse(db.add_watch("search:Dedupe Engineer, Data Analyst", "python"))
        for again in ("search:dedupe engineer,data analyst", "search:  DEDUPE   Engineer ,  Data Analyst ",
                      "search:Dedupe Engineer, Data Analyst"):
            self.assertTrue(db.add_watch(again, "sql"), again)
        (wid, url), = self.ids("dedupe")
        self.assertEqual(url, "search:Dedupe Engineer, Data Analyst")  # the first spelling stays
        self.assertEqual(db.con().execute("SELECT keywords FROM watches WHERE id=?", (wid,)).fetchone()[0], "sql")
        self.assertFalse(db.add_watch("search:Dedupe Engineer", ""))  # a different search is still its own watch

    def test_page_urls_that_name_the_same_page_are_one(self):
        self.assertFalse(db.add_watch("https://dedupe.example/careers", ""))
        for again in ("http://dedupe.example/careers", "https://www.dedupe.example/careers/", "https://DEDUPE.example/careers#open",
                      "https://dedupe.example:443/careers", " https://dedupe.example/careers "):
            self.assertTrue(db.add_watch(again, ""), again)
        self.assertEqual(len(self.ids("dedupe")), 1)
        self.assertFalse(db.add_watch("https://dedupe.example/careers?team=data", ""))  # another page
        self.assertFalse(db.add_watch("https://dedupe.example/Careers", ""))  # paths can be case-sensitive

    def test_company_board_slug_case_is_one_board(self):
        a = wm.add_company("greenhouse:dedupeco", "Dedupe Co")
        b = wm.add_company("greenhouse:DedupeCo")
        self.assertEqual((b["id"], b["slug"], b["name"]), (a["id"], "dedupeco", "Dedupe Co"))
        self.assertEqual(sum(c["slug"].lower() == "dedupeco" for c in db.companies()), 1)


if __name__ == "__main__":
    unittest.main()
