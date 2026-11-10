"""Monitor: watches (page and search; add, bad input, remove), companies (add, bad link, remove), Run watches, Check
email, Email dry-run, Weekly digest, Email digest, Export tracker to Obsidian, and the tab at 420px."""
import unittest

from harness import FETCH, E2ETestCase, FakeMail, db


class Monitor(E2ETestCase):
    ai_json = [{"i": 0, "score": 30, "why": "too junior"}]  # the AI judgement of new postings: not a strong fit

    def setUp(self):
        super().setUp()
        self.go("monitor")

    @property
    def add_company(self):
        return self.page.locator("#monitor .panel", has=self.page.locator("h3", has_text="Companies")).get_by_role("button", name="Add", exact=True)

    def watch_urls(self):
        return [w["url"] for w in self.state()["watches"]]

    def test_add_page_and_search_watches_bad_input_and_remove(self):
        self.allow_console()
        self.page.click("#monitor >> text=Add >> nth=0")  # nothing typed
        self.expect_toast("a URL or a search query is required", "err")
        self.page.fill("#wUrl", "careers at acme")  # not a link, and not ticked as a search
        self.run_click("#monitor >> text=Add >> nth=0")
        self.expect_toast("a page watch needs an http(s) URL", "err")
        self.assertNotIn("careers at acme", self.watch_urls())
        self.page.fill("#wUrl", "https://careers.example.org/jobs")
        self.page.fill("#wKw", "data, python")
        self.run_click("#monitor >> text=Add >> nth=0")
        w = next(w for w in self.state()["watches"] if w["url"] == "https://careers.example.org/jobs")
        self.assertEqual(w["keywords"], "data, python")
        self.assertFalse(w["filters"])  # a page watch has no search filters
        self.assertEqual(self.page.input_value("#wUrl"), "")
        row = self.page.locator("#wList .list > div", has_text="https://careers.example.org/jobs")
        self.assertIn("kw=data, python", row.text_content())
        self.assertIn("last never", row.text_content())
        self.page.fill("#wUrl", "platform engineer")
        self.page.check("#wSearch")
        self.run_click("#monitor >> text=Add >> nth=0")
        self.assertIn("search:platform engineer", self.watch_urls())
        self.run_click(row.get_by_role("button", name="remove"))
        self.assertNotIn("https://careers.example.org/jobs", self.watch_urls())
        self.assertEqual(self.page.locator("#wList .list > div", has_text="https://careers.example.org/jobs").count(), 0)
        # the seeded saved search shows its filters
        seeded = self.page.locator("#wList .list > div", has_text="search:data engineer").text_content()
        for f in ("kw=python spark", "location=Remote", "min_salary=140000", "posted_within=14", "seniority=senior"):
            self.assertIn(f, seeded)

    def test_companies_add_bad_link_and_remove(self):
        self.allow_console()
        self.page.fill("#cSrc", "https://example.com/careers")
        self.run_click(self.add_company)
        self.expect_toast("not a Greenhouse, Lever or Ashby board", "err")
        self.page.fill("#cSrc", "https://boards.greenhouse.io/kestrelmaps")
        self.page.fill("#cName", "Kestrel Maps")
        self.page.fill("#cKw", "data, platform")
        self.run_click(self.add_company)
        self.expect_toast("watching Kestrel Maps (greenhouse:kestrelmaps)", "ok")
        c = next(c for c in self.state()["companies"] if c["slug"] == "kestrelmaps")
        self.assertEqual((c["vendor"], c["name"], c["keywords"]), ("greenhouse", "Kestrel Maps", "data, platform"))
        self.assertEqual([self.page.input_value(s) for s in ("#cSrc", "#cName", "#cKw")], ["", "", ""])
        row = self.page.locator("#coList .list > div", has_text="Kestrel Maps")
        self.assertIn("greenhouse:kestrelmaps", row.text_content())
        self.page.fill("#cSrc", "lever:quarrygames")
        self.run_click(self.add_company)
        self.assertIn(("lever", "quarrygames"), [(c["vendor"], c["slug"]) for c in self.state()["companies"]])
        self.run_click(row.get_by_role("button", name="remove"))
        self.assertNotIn("kestrelmaps", [c["slug"] for c in self.state()["companies"]])
        self.assertEqual(row.count(), 0)

    def test_run_watches_reads_saved_searches_and_company_boards(self):
        run = self.page.locator(".top").get_by_role("button", name="Run watches")
        self.run_click(run)  # the first read of a board records what is open now; only later postings alert
        self.expect_toast("alert(s)", "ok")
        self.assertTrue(any("boards-api.greenhouse.io" in u and "northwind" in u for u in self.urls))
        self.assertTrue(any("remotive.com" in u for u in self.urls))
        st = self.state()
        self.assertTrue(next(c for c in st["companies"] if c["slug"] == "northwind")["last_seen"])
        self.assertTrue(next(w for w in st["watches"] if w["url"] == "search:data engineer")["last_seen"])
        self.assertNotIn("last never", self.page.locator("#coList .list > div", has_text="Northwind Analytics").text_content())
        feed = FETCH["boards-api.greenhouse.io"]
        try:  # a new posting on the followed board
            FETCH["boards-api.greenhouse.io"] = {"jobs": feed["jobs"] + [dict(feed["jobs"][0], id=4102, title="Staff Data Engineer",
                                                                                  absolute_url="https://boards.greenhouse.io/northwind/jobs/4102")]}
            pending = len(self.state()["pending"])
            self.run_click(run)
            n = int(self.expect_toast("alert(s)", "ok").split()[0])
            self.assertGreaterEqual(n, 1)
            self.assertIn("Staff Data Engineer", self.page.text_content("#alerts"))
            self.assertEqual(len(self.state()["pending"]), pending)  # judged a weak fit (score 30): nothing proposed
        finally:
            FETCH["boards-api.greenhouse.io"] = feed

    def test_check_email_opens_the_mailbox(self):
        FakeMail.CALLS.clear()
        self.run_click(self.page.locator(".top").get_by_role("button", name="Check email"))
        self.expect_toast("0 relevant email(s)", "ok")
        self.assertIn("login", FakeMail.CALLS)
        self.assertIn("select", FakeMail.CALLS)

    def test_email_dry_run_and_digests(self):
        mail = db.con().execute("SELECT COUNT(*) FROM mail").fetchone()[0]
        FakeMail.CALLS.clear()
        self.run_click(self.page.get_by_role("button", name="Email dry-run (7 days)"))
        self.assertEqual(self.page.text_content("#aOut").strip(), "[]")
        self.assertIn("login", FakeMail.CALLS)
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM mail").fetchone()[0], mail)  # a dry run files nothing
        sent = len(FakeMail.SENT)
        self.run_click(self.page.get_by_role("button", name="Weekly digest"))
        digest = self.page.text_content("#aOut")
        self.assertTrue(digest.strip())
        self.assertEqual(len(FakeMail.SENT), sent)  # shown only
        self.run_click(self.page.get_by_role("button", name="Email digest"))
        self.expect_toast("digest emailed to pat.rivera@example.com", "ok")
        self.assertEqual(len(FakeMail.SENT), sent + 1)
        self.assertEqual(FakeMail.SENT[-1]["To"], "pat.rivera@example.com")
        self.assertTrue(self.page.text_content("#aOut").strip())

    def test_export_to_obsidian_asks_first_then_writes_notes(self):
        target = self.home / "obsidian-vault" / "jobs"
        self.page.get_by_role("button", name="Export tracker to Obsidian").click()
        self.assertIn(str(target), self.dialogs[-1])  # names where it writes
        self.idle()
        self.assertFalse(target.exists())
        self.answer(True)
        self.run_click(self.page.get_by_role("button", name="Export tracker to Obsidian"))
        self.expect_toast("vault notes written to", "ok")
        notes = {p.name for p in target.glob("*.md")}
        jobs = self.state()["jobs"]
        self.assertEqual(len([n for n in notes if not n.startswith("_")]), len(jobs))
        self.assertIn("_index.md", notes)
        orchid = next(target.glob(f"{self.ids['interview']}-*.md")).read_text(encoding="utf-8")
        self.assertIn('company: "Orchid Health"', orchid)

    def test_keyboard_add_and_420px(self):
        self.page.focus("#wUrl")
        self.page.keyboard.type("https://jobs.example.net/careers")
        self.tab_to("#monitor .panel:first-child button.b:not(.ghost)")  # Watches > Add, by Tab alone
        self.press("Enter")
        self.idle()
        self.assertIn("https://jobs.example.net/careers", self.watch_urls())
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
