"""Job intelligence and chance boosters (pass 21): the drawer's Chance boosters (ranked by expected effect, never a
number; buttons into the feature; More from AI with a stated basis) and Job intelligence (Gather public facts from the
company's own site, its news feed and Wikipedia with sources and dates, escaped; never a job board; the AI summary keeps
cited lines only), Today's and Insights' boosters across the search."""
import json
import re
import unittest

import harness
from harness import E2ETestCase, db

from lodestar import contacts, fit  # noqa: E402  (after harness: it sets the temp home first)

XSS = "<img src=x onerror=window.__xss=1>"
JD = ("Senior Data Engineer at Quillon Freight. You take ownership of rail data pipelines and show ownership of quality; "
      "teamwork with planners matters. Requirements: 5+ years of experience. Python, SQL, Spark, Kubernetes and "
      "Terraform. We value clear writing and steady delivery across a friendly distributed team. " * 2)
HOME = ('<html><head><title>Quillon Freight</title><meta name="description" content="Quillon moves freight by rail.">'
        '<link rel="alternate" type="application/rss+xml" href="/press/feed.xml"></head><body/></html>')
FEED = (f"<rss><channel><item><title>Quillon opens a Denver hub {XSS.replace('<', '&lt;')}</title><link>/press/denver</link>"
        "<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>")
WIKI = {"type": "standard", "title": "Quillon Freight", "extract": "Quillon Freight is a fictional rail carrier.",
        "timestamp": "2026-10-20T08:00:00Z", "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Quillon_Freight"}}}
PAGES = {"quillon.example/robots.txt": "User-agent: *\nAllow: /\n", "quillon.example/press/feed.xml": FEED,
         "quillon.example": HOME, "wikipedia.org": WIKI}


class Intel(E2ETestCase):
    ai_text = "- Quillon opened a Denver hub [S2]\n- An uncited claim about culture\n- Roles keep appearing [S4][S99]"
    ai_json = {"boosters": [{"text": f"Mention rail logistics {XSS}", "why": "their news is about a new hub",
                             "basis": "S2: Denver hub", "effect": "high", "do": "tailor"},
                            {"text": "A 70% better chance", "why": "x", "basis": "JD", "effect": "high", "do": "tailor"}]}

    @classmethod
    def seed(cls):
        super().seed()
        for k, v in PAGES.items():
            harness.FETCH[k] = v
            cls.addClassCleanup(harness.FETCH.pop, k, None)
        jid = db.add_job("Quillon Freight", "Senior Data Engineer", "https://quillon.example/careers/sde", JD, "e2e")
        cls.ids["q"] = jid
        cls.ids["robin"] = contacts.add(name="Robin Vale", company="Quillon Freight", position="Data Lead")
        c = db.con()
        for i, t in enumerate(("Senior Data Engineer", "Rail Planner", "Data Engineer")):
            c.execute("INSERT INTO postings(key, url, title, company, first_seen, last_seen) VALUES(?, ?, ?, 'Quillon Freight', "
                      "datetime('now', ?), datetime('now'))", (f"quillon freight|{t.lower()}|{i}", f"https://q.example/{i}", t,
                                                               f"-{10 * (i + 1)} days"))
        c.commit()
        fit.refresh()

    def test_drawer_boosters_rank_buttons_and_ai_additions_with_a_basis(self):
        d = self.open_job(self.ids["q"])
        g = d.locator("#jBoost")
        rows = g.locator(".row.boost")
        self.assertGreaterEqual(rows.count(), 3)
        effects = [rows.nth(i).locator(".pill").first.text_content() for i in range(rows.count())]
        order = ["high effect", "medium effect", "low effect"]
        self.assertEqual(effects, sorted(effects, key=order.index))
        text = g.text_content()
        self.assertIn("Apply while the posting is fresh", text)
        self.assertIn("Ask Robin Vale, Data Lead at Quillon Freight for a referral", text)
        self.assertIn("Close a named gap", text)
        self.assertNotIn("%", text)
        g.locator(".row.boost", has_text="Robin Vale").get_by_role("button", name="Open People").click()
        self.page.wait_for_function("() => { const r = document.querySelector('#jPeople').getBoundingClientRect(); return r.top < 300 && r.bottom > 0; }")
        g.locator(".row.boost", has_text="Tailor your resume").get_by_role("button", name="Open tailoring").click()
        self.page.wait_for_function("() => { const r = document.querySelector('#jDocs').getBoundingClientRect(); return r.top < 300 && r.bottom > 0; }")
        self.run_click(d.locator("#jBoost").get_by_role("button", name="More from AI"))
        ai_row = d.locator("#jBoost .row.boost[data-basis='ai']")
        self.assertEqual(ai_row.count(), 1)  # the '70% better chance' item was dropped
        self.assertIn(f"Mention rail logistics {XSS}", ai_row.text_content())  # shown as text, never markup
        self.assertIn("basis: S2: Denver hub", ai_row.text_content())
        self.assertIsNone(self.page.evaluate("window.__xss"))
        prompt = self.ai_calls[-1]["messages"][0]["content"]
        self.assertIn("BLOCK JD", prompt); self.assertNotIn("165,000", prompt)

    def test_intel_gather_sources_dates_escaped_and_cited_ai_summary(self):
        d = self.open_job(self.ids["q"])
        g = d.locator("#jIntel")
        self.assertIn("web facts not gathered yet", g.text_content())
        self.assertIn("3 roles from Quillon Freight seen since", g.text_content())  # hiring signals need no network
        self.assertIn("Stresses ownership", g.text_content())
        before = len(self.urls)
        self.run_click(g.get_by_role("button", name="Gather public facts"))
        g = d.locator("#jIntel")
        self.assertIn("web facts gathered", g.text_content())
        asked = self.urls[before:]
        self.assertEqual(asked[0], "https://quillon.example/robots.txt")  # robots.txt before the homepage
        self.assertIn("https://quillon.example/", asked)
        self.assertFalse(any(h in u for u in asked for h in ("linkedin", "indeed", "glassdoor", "ziprecruiter")))
        news = g.locator(".intel-row[data-kind='news']")
        self.assertIn(f"Quillon opens a Denver hub {XSS}", news.text_content())
        self.assertIn("company news feed, 2026-11-02", news.text_content())
        self.assertEqual(news.locator("a").get_attribute("href"), "https://quillon.example/press/denver")
        self.assertIn("Wikipedia, 2026-10-20", g.locator(".intel-row[data-kind='company']", has_text="Wikipedia").text_content())
        self.assertIn("company website", g.text_content())
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.run_click(g.get_by_role("button", name="AI summary"))
        self.page.wait_for_selector("#jIntel .intel-sum pre")
        s = d.locator("#jIntel .intel-sum pre").text_content()
        self.assertEqual(s, "- Quillon opened a Denver hub [S2]\n- Roles keep appearing [S4]")
        prompt = self.ai_calls[-1]["messages"][0]["content"]
        self.assertIn("BLOCK S1", prompt); self.assertIn("untrusted data", prompt); self.assertNotIn("165,000", prompt)

    def test_today_and_insights_list_boosters_across_the_search(self):
        today = self.page.locator("#today")
        self.assertIn("Chance boosters", today.text_content())
        rows = today.locator(".row.boost")
        self.assertTrue(0 < rows.count() <= 3)
        first = today.locator(".row.boost", has=self.page.get_by_role("button", name="Open the pipeline")).first
        jid = int(re.search(r"#(\d+) ", first.text_content()).group(1))
        first.get_by_role("button", name="Open the pipeline").click()
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=jid)
        self.go("insights")
        ins = self.page.locator("#insBoost .row.boost")
        self.assertGreater(ins.count(), 0)
        self.assertIn("Chance boosters across your search", self.page.text_content("#insights"))
        self.assertNotIn("%", self.page.text_content("#insBoost"))
        r = self.api("/api/boosters")
        self.assertEqual(len(r["boosters"]), ins.count())
        self.assertTrue(all(b["effect"] in ("high", "medium", "low") for b in r["boosters"]))
        self.assertEqual(json.dumps(r).count("probabilit"), 0)


if __name__ == "__main__":
    unittest.main()
