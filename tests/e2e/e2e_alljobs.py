"""All jobs (pass 21, Jobs tab): every stored listing with fit badges, source chips (Adzuna's credit link at its size),
filters, New since last visit / Mark all seen, Track, Dismiss, AI fit, the expanded row, search results marked "from
this search", and Accounts > Job sources (linking an Adzuna key, verified by one small search). Text stays escaped."""
import json
import unittest

from harness import E2ETestCase, db

from lodestar import listings  # noqa: E402  (after harness: it sets the temp home first)

XSS = "<img src=x onerror=window.__xss=1>"
DESC = ("Build reliable data pipelines in Python and SQL on AWS with Spark and Airflow. We care about tests, code review "
        "and clear docs, and we pair often. ") * 3


def listing(title, company, url, source, location="Remote", salary=""):
    return {"title": title, "company": company, "url": url, "location": location, "salary": salary, "date": "",
            "desc": DESC, "source": source}


class AllJobs(E2ETestCase):
    ai_json = [{"i": 0, "score": 77, "why": "pipelines and Spark match"}]  # rank(): index -> score

    @classmethod
    def seed(cls):
        super().seed()
        listings.store([listing("Analytics Engineer", "Thistledown Co", "https://jobs.example.com/thistledown/ae", "remotive",
                                salary="$150,000 - $170,000")])
        listings.store([listing("Data Engineer", "Quillfeather Labs", "https://www.adzuna.com/land/ad/101", "adzuna",
                                location="Austin, TX")])
        listings.store([listing(f"Platform Engineer {XSS}", "Marrowgate", "https://jobs.example.com/marrowgate/pe", "hn",
                                location="Berlin (hybrid)")])
        listings.store([listing("Analytics Lead", "Bramblecrest", "https://www.linkedin.com/jobs/view/4012345690/", "linkedin_alert",
                                location="Remote")], source="linkedin_alert")
        db.con().execute("UPDATE postings SET first_seen=datetime('now', '-2 days') WHERE company='Thistledown Co'")
        db.con().execute("INSERT INTO meta(key, value) VALUES('alljobs_visit', CAST(strftime('%s','now') AS INTEGER) - 86400)")
        db.con().commit()

    def rows(self):
        return self.page.locator("#ajList .ajrow")

    def row(self, company):
        return self.page.locator("#ajList .ajrow", has_text=company)

    def open_jobs(self):
        self.go("search")
        self.page.wait_for_selector("#ajList .ajrow")

    def test_list_filters_new_track_dismiss_and_escaping(self):
        self.open_jobs()
        self.assertEqual(self.page.locator("h2", has_text="Jobs").count(), 1)
        self.assertIn("Jobs", self.page.text_content('nav button[data-tab="search"]'))
        self.assertGreaterEqual(self.rows().count(), 3)
        mg = self.row("Marrowgate")
        self.assertIn(f"Platform Engineer {XSS}", mg.text_content())  # shown as text, never markup
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertRegex(mg.locator(".chip.fit").text_content(), r"^fit \d+")
        self.assertEqual(self.row("Thistledown Co").locator(".pill", has_text="new").count(), 0)  # seen before the visit
        self.assertEqual(self.row("Quillfeather Labs").locator(".pill", has_text="new").count(), 1)
        chips = self.page.text_content("#ajSources")  # an alert source reads as its site's name, never a raw id
        self.assertIn("LinkedIn alert", chips); self.assertNotIn("linkedin_alert", chips)
        self.assertIn("LinkedIn alert", self.row("Bramblecrest").text_content())
        # a source chip filters; its count stays
        self.page.locator("#ajSources .chip.board", has_text="HN Who is hiring").click()
        self.idle()
        self.assertEqual([self.rows().nth(i).get_attribute("data-id") for i in range(self.rows().count())],
                         [self.row("Marrowgate").get_attribute("data-id")])
        self.page.locator("#ajSources .chip.board", has_text="HN Who is hiring").click()
        self.idle()
        self.page.select_option("#ajRemote", "hybrid")
        self.idle()
        self.assertEqual(self.rows().count(), 1)
        self.page.select_option("#ajRemote", "")
        self.page.fill("#ajSal", "160000")
        self.page.dispatch_event("#ajSal", "change")
        self.idle()
        self.assertEqual((self.rows().count(), self.row("Thistledown Co").count()), (1, 1))
        self.page.fill("#ajSal", "")
        self.page.dispatch_event("#ajSal", "change")
        self.idle()
        self.page.check("#ajNew")
        self.idle()
        self.assertEqual(self.row("Thistledown Co").count(), 0)
        self.page.uncheck("#ajNew")
        self.idle()
        # Track: a user click adds the job directly and links the row
        self.row("Thistledown Co").get_by_role("button", name="Track").click()
        jid = int(self.expect_toast("tracked as #", "ok").split("#")[1])
        self.idle()
        self.assertEqual(db.get_job(jid)["company"], "Thistledown Co")
        self.assertEqual(self.row("Thistledown Co").count(), 0)  # no longer an untracked listing
        self.page.select_option("#ajShow", "tracked")
        self.idle()
        self.assertEqual(self.row("Thistledown Co").get_by_role("button", name=f"tracked as #{jid}").count(), 1)
        self.page.select_option("#ajShow", "open")
        self.idle()
        self.row("Marrowgate").get_by_role("button", name="Dismiss").click()
        self.expect_toast("dismissed", "ok")
        self.idle()
        self.assertEqual(self.row("Marrowgate").count(), 0)
        self.page.select_option("#ajShow", "dismissed")
        self.idle()
        self.row("Marrowgate").get_by_role("button", name="Undismiss").click()
        self.idle()
        self.page.select_option("#ajShow", "open")
        self.idle()
        self.assertEqual(self.row("Marrowgate").count(), 1)
        self.page.get_by_role("button", name="Mark all seen").click()
        self.expect_toast("all marked seen", "ok")
        self.idle()
        self.assertEqual(self.page.locator("#ajList .ajrow.new").count(), 0)

    def test_expand_adzuna_credit_and_ai_fit(self):
        self.open_jobs()
        q = self.row("Quillfeather Labs")
        credit = q.locator("a.chip.attr-adzuna")
        self.assertEqual((credit.text_content(), credit.get_attribute("href")), ("Adzuna", "https://www.adzuna.com/"))
        box = credit.bounding_box()
        self.assertGreaterEqual(box["width"], 116); self.assertGreaterEqual(box["height"], 23)  # Adzuna's attribution size
        q.locator("a.ajt").click()
        self.idle()
        detail = self.row("Quillfeather Labs").locator(".ajdetail")
        self.assertIn("weight 35", detail.text_content())
        self.assertIn("Build reliable data pipelines", detail.text_content())
        self.run_click(self.row("Quillfeather Labs").get_by_role("button", name="AI fit"))
        self.expect_toast("AI fit: fit", "ok")
        pid = int(self.row("Quillfeather Labs").get_attribute("data-id"))
        self.assertEqual(listings.get(pid)["fit"]["parts"]["ai"]["s"], 77)  # stored on the row, blended into its fit
        self.assertIn("untrusted text copied from job sites", self.ai_calls[-1]["messages"][0]["content"])

    def test_search_results_are_stored_and_marked_from_this_search(self):
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        self.run_click(self.page.get_by_role("button", name="Search boards now"))
        self.page.wait_for_selector("#ajList .ajrow.hi")
        hi = self.page.locator("#ajList .ajrow.hi")
        self.assertIn("Saltmarsh Data", hi.first.text_content())
        self.assertIn("from this search", hi.first.text_content())

    def test_setup_job_sources_link_an_adzuna_key(self):
        self.go("accounts")
        src = self.page.locator("#srcList")
        self.assertIn("Remotive", src.text_content())
        ad = src.locator(".srckey", has_text="Adzuna")
        self.assertIn("needs keys", ad.text_content())
        self.assertIn("ADZUNA_APP_ID", ad.text_content())
        self.assertEqual(self.page.locator("#kProv option", has_text="Adzuna").count(), 0)  # not on the AI card
        i = self.page.evaluate("BOARDS.indexOf('adzuna')")
        self.page.fill(f"#srcId{i}", "e2e-app-id-123")
        self.page.fill(f"#srcKey{i}", "e2e-adzuna-key-456")
        self.run_click(ad.get_by_role("button", name="Link"))
        self.expect_toast("Adzuna (job search): Verified", "ok")
        self.page.wait_for_function("() => S.sources.adzuna.ready")
        self.assertNotIn("e2e-adzuna-key-456", json.dumps(self.state()))
        self.assertTrue(any("api.adzuna.com" in u and "app_id=e2e-app-id-123" in u for u in self.urls))
        self.answer(True)
        self.page.locator("#srcList .srckey", has_text="Adzuna").get_by_role("button", name="Remove").click()
        self.expect_toast("removed", "ok")
        self.page.wait_for_function("() => !S.sources.adzuna.ready")

    def test_all_jobs_at_420px(self):
        self.open_jobs()
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
