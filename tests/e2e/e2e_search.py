"""Search: free job APIs with filters, unknown chips, board errors, AI rank, Auto-track, Save as watch, track a listing."""
import unittest

from harness import FETCH, E2ETestCase, contacts, day, db, web_monitor

from lodestar import settings  # noqa: E402  (after harness: it sets the temp home first)

SALTMARSH = {"title": "Data Engineer", "company_name": "Saltmarsh Data", "url": "https://jobs.example.com/saltmarsh/de",
             "candidate_required_location": "USA", "salary": "$140k - $170k", "description": "Python, SQL, Airflow, dbt"}
KESTREL = {"title": "Senior Data Engineer", "company_name": "Kestrel Maps", "url": "https://jobs.example.com/kestrel/sde",
           "location": "", "description": "Python Spark Airflow. Build map data pipelines."}  # no pay, place or date
OLD_HARBOR = {"jobTitle": "Data Engineer", "companyName": "Old Harbor", "url": "https://jobs.example.com/oldharbor/de",
              "jobGeo": "Remote", "jobExcerpt": "data engineer", "jobDescription": "Data engineer. SQL."}  # old and reposted


class Search(E2ETestCase):
    # AI rank (and Auto-track, which ranks) asks for a JSON list: index -> score
    ai_json = [{"i": 0, "score": 62, "why": "SQL and Airflow, fewer Spark signals"},
               {"i": 1, "score": 91, "why": "Spark and Airflow at senior level"},
               {"i": 2, "score": 95, "why": "SQL match"}]

    @classmethod
    def seed(cls):
        super().seed()
        cls.addClassCleanup(lambda saved=dict(FETCH): (FETCH.clear(), FETCH.update(saved)))
        FETCH["remotive.com"] = {"jobs": [SALTMARSH | {"publication_date": day(-4)}]}
        FETCH["arbeitnow.com"] = {"data": [KESTREL]}
        FETCH["hn.algolia.com"] = {"hits": "not a list"}  # a board that answers garbage: reported, never fatal
        FETCH["jobicy.com"] = {"jobs": [OLD_HARBOR | {"pubDate": day(-200)}]}
        # Old Harbor's role was first seen 40 days ago under another link: posted long ago + reposted = possibly stale
        db.note_posting(web_monitor.posting_key({"company": "Old Harbor", "title": "Data Engineer", "location": "Remote"}),
                        "https://jobs.example.com/oldharbor/first")
        db.con().execute("UPDATE postings SET first_seen=datetime('now','-40 days') WHERE url=?", ("https://jobs.example.com/oldharbor/first",))
        db.con().commit()
        contacts.add(name="Lee Park", email="lee.park@saltmarsh.example", company="Saltmarsh Data", position="Analyst")

    def search(self, q="data engineer", **fields):
        self.page.fill("#sQ", q)
        for sel, v in {"#sK": "", "#sLoc": "", "#sSal": "", "#sDays": ""}.items():
            self.page.fill(sel, fields.get(sel, v))
        self.page.select_option("#sLevel", fields.get("#sLevel", ""))
        self.run_click(self.page.get_by_role("button", name="Search boards now"))

    def listing(self, company):
        return self.page.locator("#sRes .list > div", has_text=company)

    def test_search_with_filters_unknown_chips_and_board_errors(self):
        self.go("search")
        self.search()
        # pass 21: Remotive limits calls per user, so one unfiltered fetch serves every query (filtered locally)
        self.assertIn("https://remotive.com/api/remote-jobs?limit=100", self.urls)
        self.assertEqual(self.page.locator("#sRes .list > div").count(), 3)
        self.assertIn("could not read hn", self.page.text_content("#sRes .warnbox"))
        salt, kes, old = self.listing("Saltmarsh Data"), self.listing("Kestrel Maps"), self.listing("Old Harbor")
        self.assertIn("$140k - $170k", salt.text_content())
        self.assertEqual(salt.locator("a", has_text="open").get_attribute("href"), SALTMARSH["url"])
        self.assertIn("senior", kes.locator(".chips").text_content())
        self.assertRegex(salt.locator(".chips .chip.fit").text_content(), r"^fit \d+")  # pass 21: the fit badge
        self.assertNotIn("matched:", salt.text_content())  # pass 21: no JD-coverage line; the fit badge carries the reasons
        warm = salt.locator(".chip.warm")
        self.assertEqual(warm.text_content(), "you know 1 person here")
        self.assertIn("Lee Park (Analyst)", warm.get_attribute("title"))
        stale = old.locator(".chip.stale")
        self.assertEqual(stale.text_content(), "possibly stale")
        self.assertIn("posted 200 days ago", stale.get_attribute("title"))
        self.assertIn("reposted", old.text_content())
        self.assertEqual(salt.locator(".chip.stale").count(), 0)
        # min salary and posted-within: a listing that does not say is kept and marked, not dropped
        self.search(**{"#sSal": "150000", "#sDays": "30"})  # Old Harbor: 200 days old
        self.assertEqual(self.page.locator("#sRes .list > div").count(), 2)
        self.assertEqual(self.listing("Old Harbor").count(), 0)
        chips = self.listing("Kestrel Maps").locator(".chips").text_content()
        self.assertIn("salary unknown", chips)
        self.assertIn("date unknown", chips)
        self.assertNotIn("unknown", self.listing("Saltmarsh Data").locator(".chips").text_content())
        self.search(**{"#sSal": "175000"})  # Saltmarsh tops out at 170k
        self.assertEqual(self.listing("Saltmarsh Data").count(), 0)
        self.assertEqual(self.listing("Kestrel Maps").count(), 1)
        self.search(**{"#sDays": "2"})  # Saltmarsh was posted 4 days ago
        self.assertEqual(self.listing("Saltmarsh Data").count(), 0)
        self.search(**{"#sLevel": "senior"})
        self.assertEqual((self.listing("Saltmarsh Data").count(), self.listing("Kestrel Maps").count()), (0, 1))
        self.search(**{"#sLoc": "Berlin"})  # Kestrel names no place: kept, marked
        self.assertEqual(self.listing("Saltmarsh Data").count(), 0)
        self.assertIn("location unknown", self.listing("Kestrel Maps").locator(".chips").text_content())
        self.search(**{"#sK": "spark"})  # must-have keyword
        self.assertEqual((self.listing("Saltmarsh Data").count(), self.listing("Kestrel Maps").count()), (0, 1))
        self.search(**{"#sK": "cobol"})
        self.assertIn("nothing found", self.page.text_content("#sRes .empty"))

    def test_no_board_reachable_says_nothing_was_checked(self):
        saved = dict(FETCH)
        try:
            for k in list(FETCH):
                FETCH[k] = "broken"  # every board answers garbage
            self.go("search")
            self.search()
            self.assertIn("No job board could be reached", self.page.text_content("#sRes .empty"))
            self.assertGreaterEqual(self.page.text_content("#sRes .warnbox").count("could not read"), 6)
        finally:
            FETCH.clear()
            FETCH.update(saved)

    def test_track_a_listing_once(self):
        self.go("search")
        self.search()
        before = len(self.state()["jobs"])
        self.run_click(self.listing("Saltmarsh Data").get_by_role("button", name="track"))
        jid = int(self.expect_toast("tracked as #", "ok").split("#")[1])
        j = db.get_job(jid)
        self.assertEqual((j["company"], j["title"], j["url"], j["location"], j["status"]),
                         ("Saltmarsh Data", "Data Engineer", SALTMARSH["url"], "USA", "saved"))
        self.assertEqual((j["salary_min"], j["salary_max"]), (140000, 170000))
        self.assertEqual(j["posted_at"], day(-4))
        self.assertEqual(len(self.state()["jobs"]), before + 1)
        self.run_click(self.listing("Saltmarsh Data").get_by_role("button", name="track"))
        self.expect_toast(f"already on your Board as #{jid}", "ok")
        self.assertEqual(len(self.state()["jobs"]), before + 1)
        self.search()  # a new search marks it as tracked
        self.assertIn(f"tracked as #{jid}", self.listing("Saltmarsh Data").locator(".chips").text_content())
        self.go("board")
        self.assertEqual(self.page.locator(f'.card[data-id="{jid}"]').count(), 1)

    def test_ai_rank_orders_best_first(self):
        self.go("search")
        self.page.check("#sRank")
        self.search()
        scores = [int(s) for s in self.page.eval_on_selector_all("#sRes .score", "s => s.map(x => x.textContent)")]
        self.assertEqual(scores, [95, 91, 62])
        first = self.page.locator("#sRes .list > div").nth(1)
        self.assertIn("Kestrel Maps", first.text_content())
        self.assertIn("Spark and Airflow at senior level", first.text_content())
        self.assertIn("Saltmarsh Data", self.ai_calls[-1]["messages"][0]["content"])

    def test_auto_track_proposes_strong_fits(self):
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        settings.set_pref("auto_track_min_score", 0)  # pass 21: the blended fit is compared, so any judged listing passes
        self.addCleanup(settings.set_pref, "auto_track_min_score", 75)
        # pass 21: only a listing with a real description (40+ words) reaches the AI; the others are judged by rules
        long = KESTREL["description"] + " We map coastlines and shipping lanes from open data, with tested pipelines." * 4
        self.addCleanup(FETCH.__setitem__, "arbeitnow.com", {"data": [KESTREL]})
        FETCH["arbeitnow.com"] = {"data": [KESTREL | {"description": long}]}
        before = {p["id"] for p in self.state()["pending"]}
        self.run_click(self.page.get_by_role("button", name="Auto-track strong fits"))
        self.expect_toast("strong fit(s) proposed", "err")  # one board (hn) could not be read: said in the toast
        new = {p["payload"]["company"]: p for p in self.state()["pending"] if p["id"] not in before}
        self.assertIn("Kestrel Maps", new)
        self.assertNotIn("Old Harbor", new)  # Old Harbor (AI would say 95) looks stale: never judged
        self.assertEqual({(p["tool"], p["kind"]) for p in new.values()}, {("auto_track", "add_job")})
        self.assertRegex(new["Kestrel Maps"]["summary"], r"fit \d+ \(AI\)")
        self.assertIn("could not read: hn", self.page.text_content("#toast"))

    def test_save_as_watch_blank_new_and_update(self):
        self.go("search")
        self.page.click("text=Save as watch")
        self.expect_toast("type a query first", "err")
        self.page.fill("#sQ", "analytics engineer")
        self.page.fill("#sK", "dbt")
        self.page.fill("#sLoc", "remote")
        self.page.fill("#sSal", "130000")
        self.page.fill("#sDays", "7")
        self.page.select_option("#sLevel", "senior")
        self.run_click("text=Save as watch")
        self.expect_toast('saved: new listings for "analytics engineer" will alert', "ok")
        w = next(w for w in self.state()["watches"] if w["url"] == "search:analytics engineer")
        self.assertEqual(w["keywords"], "dbt")
        self.assertEqual(w["filters"], {"location": "remote", "min_salary": 130000, "posted_within": 7, "seniority": "senior"})
        n = len(self.state()["watches"])
        for s in ("#sK", "#sLoc", "#sSal", "#sDays"):
            self.page.fill(s, "")
        self.page.select_option("#sLevel", "")
        self.run_click("text=Save as watch")  # blank fields keep what the saved search had
        self.expect_toast('updated the existing saved search "analytics engineer"', "ok")
        self.assertEqual(len(self.state()["watches"]), n)
        w = next(w for w in self.state()["watches"] if w["url"] == "search:analytics engineer")
        self.assertEqual((w["keywords"], w["filters"]["min_salary"]), ("dbt", 130000))
        self.go("monitor")
        self.assertIn("search:analytics engineer", self.page.text_content("#wList"))

    def test_search_from_the_keyboard_and_at_420px(self):
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        self.tab_to("#search .row button.b:not(.ghost)")  # Search boards now
        self.press("Enter")
        self.idle()
        self.assertEqual(self.page.locator("#sRes .list > div").count(), 3)
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
