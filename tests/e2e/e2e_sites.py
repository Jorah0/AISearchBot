"""The five job sites you browse yourself (pass 36): search links on the Jobs tab built from your role, place and
level (each opens the site's own search in a new tab; Lodestar fetches nothing), per-site caps under Accounts, and a
site at its cap flagged on Accounts, Today and the job drawer."""
import unittest
from urllib.parse import parse_qs, urlsplit

from harness import E2ETestCase, db


class Sites(E2ETestCase):
    ai_json = {"queries": [{"query": "Analytics Engineer", "why": "dbt and SQL in your profile"},
                           {"query": "<img src=x onerror=alert(1)>ETL Developer", "why": "older title for the same work"}],
               "boolean": '("data engineer" OR "analytics engineer") AND python'}

    @classmethod
    def seed(cls):
        super().seed()
        jid = db.add_job("Pace Labs", "Data Engineer", "https://www.linkedin.com/jobs/view/777", "Python, SQL.", "seed")
        db.set_status(jid, "applied")
        cls.ids["linkedin_job"] = jid

    def test_jobs_tab_links_search_each_site_with_your_role_place_and_level(self):
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        self.page.fill("#sLoc", "Austin, TX")
        self.page.select_option("#sLevel", "senior")
        links = self.page.locator("#siteSearch > a")  # the paced five (the other sites sit in .more)
        self.assertEqual(links.evaluate_all("as => as.map(a => a.dataset.site)"),
                         ["LinkedIn", "Indeed", "Glassdoor", "ZipRecruiter", "SimplyHired"])
        href = {s: links.nth(i).get_attribute("href") for i, s in enumerate(["LinkedIn", "Indeed", "Glassdoor", "ZipRecruiter", "SimplyHired"])}
        q = lambda s: parse_qs(urlsplit(href[s]).query)  # noqa: E731
        self.assertEqual(urlsplit(href["LinkedIn"]).netloc, "www.linkedin.com")
        self.assertEqual((q("LinkedIn")["keywords"], q("LinkedIn")["location"], q("LinkedIn")["f_E"]), (["data engineer"], ["Austin, TX"], ["4"]))
        self.assertEqual((q("Indeed")["q"], q("Indeed")["explvl"]), (["data engineer"], ["SENIOR_LEVEL"]))
        self.assertEqual(q("Glassdoor")["sc.keyword"], ["senior data engineer"])
        self.assertEqual(q("SimplyHired")["l"], ["Austin, TX"])
        for i in range(5):
            self.assertEqual((links.nth(i).get_attribute("target"), links.nth(i).get_attribute("rel")), ("_blank", "noopener"))
        self.page.fill("#sLoc", "remote")
        self.assertEqual(parse_qs(urlsplit(self.page.locator("#siteSearch a[data-site=LinkedIn]").get_attribute("href")).query)["f_WT"], ["2"])

    def test_several_places_get_their_own_row_of_site_links(self):
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        self.page.fill("#sLoc", "Austin, TX or Denver, CO or remote")
        rows = self.page.locator("#siteSearch .siteplace")
        self.assertEqual(rows.evaluate_all("rs => rs.map(r => r.dataset.place)"), ["Austin, TX", "Denver, CO", "remote"])
        loc = lambda p, s: parse_qs(urlsplit(self.page.locator(f'#siteSearch .siteplace[data-place="{p}"] a[data-site="{s}"]').get_attribute("href")).query)  # noqa: E731
        self.assertEqual(loc("Denver, CO", "LinkedIn")["location"], ["Denver, CO"])  # never the whole 'A or B' string
        self.assertEqual(loc("Denver, CO", "Dice")["location"], ["Denver, CO"])  # the More sites too
        self.assertEqual(loc("remote", "LinkedIn")["f_WT"], ["2"])
        self.assertEqual(self.page.locator("#siteSearch .siteplace a[data-site=Indeed]").count(), 3)

    def test_more_sites_lodestar_cannot_search_itself(self):  # each URL format checked live on 2026-11-18
        self.go("search")
        self.page.fill("#sQ", "data analyst")
        self.page.fill("#sLoc", "Austin, TX")
        self.page.select_option("#sLevel", "senior")
        more = self.page.locator("#siteSearch .more a")
        self.assertEqual(more.evaluate_all("as => as.map(a => a.dataset.site)"),
                         ["Google Jobs", "Monster", "Dice", "Built In", "Idealist", "USAJOBS"])
        href = {a: more.nth(i).get_attribute("href") for i, a in enumerate(["Google Jobs", "Monster", "Dice", "Built In", "Idealist", "USAJOBS"])}
        q = lambda s: parse_qs(urlsplit(href[s]).query)  # noqa: E731
        self.assertEqual((urlsplit(href["Google Jobs"]).netloc, q("Google Jobs")["q"], q("Google Jobs")["ibp"]),
                         ("www.google.com", ["senior data analyst jobs near Austin, TX"], ["htl;jobs"]))
        self.assertEqual((q("Monster")["q"], q("Monster")["where"]), (["senior data analyst"], ["Austin, TX"]))
        self.assertEqual((q("Dice")["q"], q("Dice")["location"]), (["senior data analyst"], ["Austin, TX"]))
        self.assertEqual(q("Built In")["search"], ["senior data analyst"])
        self.assertEqual(q("Idealist")["q"], ["senior data analyst"])
        self.assertEqual((q("USAJOBS")["k"], q("USAJOBS")["l"]), (["senior data analyst"], ["Austin, TX"]))
        for i in range(more.count()):
            self.assertEqual((more.nth(i).get_attribute("target"), more.nth(i).get_attribute("rel")), ("_blank", "noopener"))
        self.assertEqual(self.page.locator("#siteSearch > a").count(), 5)  # the paced five stay first, caps unchanged
        self.go("accounts")  # the More sites you apply on are capped too (Google Jobs only links onward)
        rows = self.page.locator("#siteList .connrow")
        self.assertEqual(rows.evaluate_all("rs => rs.map(r => r.dataset.site)")[5:], ["Dice", "Monster", "Built In", "Idealist", "USAJOBS"])
        dice = self.page.locator("#siteList .connrow[data-site=Dice]")
        dice.locator("input[aria-label='Dice daily cap']").fill("2")
        dice.locator("input[aria-label='Dice weekly cap']").fill("6")
        self.run_click(dice.get_by_role("button", name="Save caps"))
        self.expect_toast("Dice caps saved", "ok")
        self.assertIn("of 2 today", self.page.locator("#siteList .connrow[data-site=Dice]").text_content())

    def test_caps_flag_a_full_site_on_accounts_today_and_the_drawer(self):
        self.go("accounts")
        row = self.page.locator("#siteList .connrow[data-site=LinkedIn]")
        self.assertIn("1 of 10 today", row.text_content())
        self.assertIn("Open", row.text_content())
        row.locator("input[aria-label='LinkedIn daily cap']").fill("1")
        row.locator("input[aria-label='LinkedIn weekly cap']").fill("3")
        self.run_click(row.get_by_role("button", name="Save caps"))
        self.expect_toast("LinkedIn caps saved", "ok")
        row = self.page.locator("#siteList .connrow[data-site=LinkedIn]")
        self.assertIn("At cap: paused", row.text_content())
        self.assertIn("1 of 1 today", row.text_content())
        self.assertIn("LinkedIn", self.page.locator("#homePace").text_content())  # Today says so
        d = self.open_job(self.ids["linkedin_job"])
        self.assertIn("LinkedIn is at your cap", d.locator("#jPace").text_content())
        self.go("accounts")
        bad = self.page.locator("#siteList .connrow[data-site=Indeed]")
        bad.locator("input[aria-label='Indeed daily cap']").fill("9")
        bad.locator("input[aria-label='Indeed weekly cap']").fill("2")
        self.allow_console()
        self.run_click(bad.get_by_role("button", name="Save caps"))
        self.expect_toast("a week at least the day's cap", "err")
        self.set_viewport(420)
        self.assertEqual(self.overflow(), [])

    def test_ai_suggests_searches_to_run_yourself_on_each_site(self):  # pass 37
        self.go("search")
        self.page.fill("#sQ", "data engineer")
        self.page.fill("#sLoc", "Austin, TX")
        self.run_click("#siteIdeasBtn")
        rows = self.page.locator("#siteIdeas .idea")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.nth(1).locator("b").text_content(), "ETL Developer")  # markup removed on the server
        self.assertEqual(self.page.locator("#siteIdeas img").count(), 0)
        li = rows.first.locator("a[data-site=LinkedIn]").get_attribute("href")
        self.assertEqual(parse_qs(urlsplit(li).query)["keywords"], ["Analytics Engineer"])
        self.assertEqual(parse_qs(urlsplit(li).query)["location"], ["Austin, TX"])
        self.assertEqual(rows.first.locator("a").count(), 5)
        boolean = self.page.locator("#siteIdeas .idea-bool")
        self.assertEqual(boolean.locator("a").evaluate_all("as => as.map(a => a.dataset.site)"), ["LinkedIn", "Indeed"])
        rows.first.get_by_role("button", name="Use").click()
        self.assertEqual(self.page.input_value("#sQ"), "Analytics Engineer")
        self.assertIn("Analytics+Engineer", self.page.locator("#siteSearch a[data-site=Indeed]").get_attribute("href"))


if __name__ == "__main__":
    unittest.main()
