"""Fit score (pass 21): the board's fit badge and its top chips, the table's Fit and Coverage columns and the Best fit
sort, the drawer's Fit breakdown (every part, its weight and chips, modifiers, Why not higher?, the AI fit button),
Today's Top new fits with Track, the Insights band label and the Fit weights preference with Reset."""
import json
import re
import unittest

from harness import PROFILE_MD, E2ETestCase, db, profile

from lodestar import fit, settings  # noqa: E402  (after harness: it sets the temp home first)

XSS = "<img src=x onerror=window.__xss=1>"
JD = ("Senior Data Engineer, remote. 5+ years of experience. Python, SQL, Spark, Airflow, dbt and Kafka on AWS. "
      "We build reliable batch and streaming pipelines for logistics teams and care about tests and clear docs. "
      f"Salary $170,000 - $200,000 per year. Not for people who dislike {XSS} reviews.")


class Fit(E2ETestCase):
    ai_json = [{"i": 0, "score": 88, "why": "strong data platform overlap"}]  # rank(): index -> score

    @classmethod
    def seed(cls):
        super().seed()
        profile.write_master(PROFILE_MD.replace(
            "Deal-breakers: on-call every week",
            f"Target roles: Senior Data Engineer | Locations / remote: Remote, Portland | Deal-breakers: on-call every week, {XSS}"))
        cls.ids["fit"] = db.add_job("Ternwell", "Senior Data Engineer", "https://jobs.example.com/ternwell/sde", JD, "e2e")
        db.note_posting("larkspur|senior data engineer|remote", "https://jobs.example.com/larkspur/sde")
        db.con().execute("UPDATE postings SET title='Senior Data Engineer', company='Larkspur Freight', location='Remote', "
                         "jd=?, sources='[\"remotive\"]' WHERE key='larkspur|senior data engineer|remote'", (JD.replace(XSS, "noisy"),))
        db.con().commit()
        fit.refresh()  # the jobs and the listing, as the loop's fit step does
        db.release()

    def test_board_badge_table_columns_and_best_fit_sort(self):
        badge = self.page.locator(f'.card[data-id="{self.ids["fit"]}"] .chip.fit')
        self.assertRegex(badge.text_content(), r"^fit \d+")
        self.assertIn("fit-", badge.get_attribute("class"))
        self.assertTrue(badge.get_attribute("title"))  # the top chips
        self.page.click("#fView")
        heads = self.page.locator("#jobTable thead").text_content()
        self.assertIn("Fit", heads); self.assertIn("Coverage", heads)
        self.page.select_option("#fSort", "fit")
        jobs = {j["id"]: j for j in self.state()["jobs"]}
        ids = self.page.evaluate("() => [...document.querySelectorAll('#jobTable tbody tr')].map(r => Number(r.cells[1].textContent))")
        vals = [jobs[i]["fit_score"] for i in ids]
        known = [v for v in vals if v is not None]
        self.assertEqual(known, sorted(known, reverse=True))
        self.assertTrue(all(v is None for v in vals[len(known):]))
        self.assertNotIn("fit", jobs[self.ids["fit"]])  # the board carries the light fit only
        self.assertLessEqual(len(jobs[self.ids["fit"]]["fit_chips"]), 3)

    def test_drawer_breakdown_why_not_higher_ai_fit_and_escaped_chips(self):
        d = self.open_job(self.ids["fit"])
        group = d.locator("#jFit")
        self.assertRegex(group.locator("b.cov-score").text_content(), r"^fit \d+$")
        text = group.text_content()
        for part in ("Skills (weight 35)", "Role (weight 20)", "Experience (weight 15)", "Location (weight 15)", "Pay (weight 15)"):
            self.assertIn(part, text)
        self.assertIn(f'mentions "{XSS}" (deal-breaker)', text)  # shown as text, never markup
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertIn("range clears your floor", text)
        self.assertNotIn("165", text)  # the floor figure never shows
        group.get_by_role("button", name="Why not higher?").click()
        self.assertIn("costs about", d.locator("#jFitWhy").text_content())
        self.run_click(group.get_by_role("button", name="AI fit"))
        self.page.wait_for_function("() => /AI \\(weight 25\\)/.test(document.querySelector('#jFit').textContent)")
        self.assertIn("AI 88: strong data platform overlap", d.locator("#jFit").text_content())
        prompt = self.ai_calls[-1]["messages"][0]["content"]
        self.assertIn("untrusted text copied from job sites", prompt)
        self.assertNotIn("165,000", prompt); self.assertNotIn('"chips"', prompt)
        self.assertEqual(json.loads(db.get_job(self.ids["fit"])["ai_fit"])["score"], 88)

    def test_career_class_on_the_card_and_hard_requirements_in_the_drawer(self):  # pass 24
        card = self.page.locator(f'.card[data-id="{self.ids["fit"]}"]')
        self.assertEqual(card.locator(".chip.fit-class").text_content(), "Currently ineligible")  # its deal-breaker
        group = self.open_job(self.ids["fit"]).locator("#jFit")
        self.assertEqual(group.locator(".chip.fit-class").text_content(), "Currently ineligible")
        gates = group.locator(".gates").text_content()
        self.assertIn("Hard requirements (kept out of the score)", gates)
        self.assertIn("Deal-breaker: not met", gates)
        self.assertRegex(group.text_content(), r"confidence \d+%")
        self.assertIsNone(self.page.evaluate("window.__xss"))

    def test_today_top_new_fit_tracks_the_listing(self):
        today = self.page.locator("#today")
        self.assertIn("Top new fits", today.text_content())
        row = today.locator(".row", has_text="Larkspur Freight")
        self.assertRegex(row.text_content(), r"fit \d+")
        self.assertIn("(Remotive)", row.text_content())  # the source by its name, never the raw id
        row.get_by_role("button", name="Track").click()
        self.expect_toast("tracked as #", "ok")
        self.page.wait_for_function("() => cur && cur.job.company === 'Larkspur Freight'")
        jid = self.page.evaluate("cur.job.id")
        self.assertEqual(db.get_job(jid)["url"], "https://jobs.example.com/larkspur/sde")
        self.idle()
        tracked = self.page.locator("#today .row", has_text="Larkspur Freight").filter(has=self.page.get_by_role("button", name="Track"))
        self.assertEqual(tracked.count(), 0)  # no longer a Top new fit (its chance boosters may name it now)

    def test_insights_label_and_fit_weights_preference(self):
        self.go("insights")
        self.assertIn("Response rate by fit score", self.page.text_content("#insights"))
        self.go("tools")
        i = self.page.evaluate("k => PK.indexOf(k)", "fit_weights")
        row = self.page.locator(f"#prefs .row:has(#pl{i})")
        self.assertIn("defaults (skills=35", row.text_content())
        row.locator("input").fill("skills=40")
        row.locator("input").dispatch_event("change")
        self.page.wait_for_function("() => S.prefs.fit_weights && S.prefs.fit_weights.skills === 40")
        self.assertEqual(settings.load()["prefs"]["fit_weights"], {"skills": 40})
        self.idle()  # the row re-renders after the first save
        row.locator("input").fill("pay=0")  # regression: a switched-off part read '(default)'
        row.locator("input").dispatch_event("change")
        self.page.wait_for_function("() => S.prefs.fit_weights && S.prefs.fit_weights.pay === 0")
        self.page.wait_for_function("i => document.querySelector(`#prefs .row:has(#pl${i})`).textContent.includes('pay=0 (off)')", arg=i)
        self.page.locator(f"#prefs .row:has(#pl{i})").get_by_role("button", name="Reset weights").click()
        self.page.wait_for_function("() => S.prefs.fit_weights && Object.keys(S.prefs.fit_weights).length === 0")
        self.assertEqual(settings.load()["prefs"]["fit_weights"], {})
        self.allow_console()  # the refused value below is a 400
        bad = self.page.locator(f"#prefs .row:has(#pl{i}) input")
        bad.fill("skills=500")
        bad.dispatch_event("change")
        self.expect_toast("between 0 and 100", "err")
        self.assertTrue(re.search(r"weight", self.page.text_content("#prefs")))


if __name__ == "__main__":
    unittest.main()
