"""Insights: weekly charts and their tables (range picker), response rates by source and match band, the funnel, weekly
goals (save, bad value, clear), offers side by side (best per row, market range, the private floor row, job links),
Record or edit an offer (blank, bad value, a job not yet at offer moves there), the counter-offer draft (blank, cited
figures, plain template, Options and Use this; always into the Inbox), the activity log (Show, weekly minimum, Export
CSV, Printable page), keyboard and 420px."""
import csv
import re
import unittest

from harness import E2ETestCase, db, day
from lodestar import settings

AI = {"options": [
    {"label": "Confident", "tone": "confident", "subject": "Revisiting the base", "recommended": True, "why": "clear ask",
     "body": "Thank you for the offer. I have another offer with a base salary of 175,000. Could you revisit the base? Best, Pat"},
    {"label": "Warm", "tone": "warm", "subject": "Thank you, one question", "recommended": False, "why": "",
     "body": "Thank you again, I am excited about the role. Is there room on the base? Best, Pat"}],
    "subject": "Offer follow-up", "body": "Thank you for the offer. Best, Pat"}


class Insights(E2ETestCase):
    ai_json = AI

    def setUp(self):
        super().setUp()
        self.go("insights")
        self.idle()

    def analytics(self, weeks=12):
        return self.api(f"/api/analytics?weeks={weeks}")

    def no_goals(self):
        settings.set_pref("weekly_goals", {k: 0 for k in settings.GOALS})
        self.reload_state()
        self.reopen()

    def reopen(self):
        self.go("board")
        self.go("insights")
        self.idle()

    # --- charts and tables
    def test_weekly_charts_tables_rates_and_funnel(self):
        a = self.analytics(12)
        charts = self.page.locator("#insWeeks svg.bars[role=img]")
        self.assertEqual(charts.count(), 5)
        total = sum(w["applications"] for w in a["weeks"])
        self.assertEqual(charts.first.get_attribute("aria-label"), f"applications per week, 12 weeks, {total} in total")
        self.assertEqual(charts.first.locator("rect").count(), 12)
        self.assertEqual(charts.first.locator("rect title").last.text_content(),
                         f"week of {a['weeks'][-1]['start']}: {a['weeks'][-1]['applications']} applications")
        table = self.page.locator("#insWeeksTable table")
        self.assertFalse(table.is_visible())
        self.page.click("#insights summary:text('as a table')")
        self.assertTrue(table.is_visible())
        self.assertEqual(table.locator("tbody tr").count(), 12)
        self.assertEqual(table.locator("tbody tr").last.locator("td").nth(2).text_content(), str(a["weeks"][-1]["applications"]))
        self.page.select_option("#insRange", "4")
        self.idle()
        self.assertEqual(table.locator("tbody tr").count(), 4)
        self.assertEqual(charts.first.locator("rect").count(), 4)
        # response rate by source: a bar where there is enough data, the count where there is not
        for g in a["by_source"]:
            row = self.page.locator("#insSource .cov-row", has_text=g["group"])
            if g["enough"]:
                self.assertEqual(row.locator(".bar").get_attribute("aria-label"),
                                 f"{g['group']}: response {round(g['response_rate'] * 100)}% of {g['n']}")
            else:
                self.assertIn("not enough data yet", row.text_content())
        for g in a["by_band"]:
            self.assertIn(f"n={g['n']}", self.page.locator("#insBand .cov-row", has_text=g["group"]).first.text_content())
        rows = self.page.locator("#insFunnel tbody tr")
        self.assertEqual(rows.count(), len(a["funnel"]["stages"]))
        applied = a["funnel"]["stages"]["applied"]
        self.assertEqual(rows.first.locator("td").all_text_contents()[:3], ["applied", str(applied["reached"]), str(applied["advanced"])])
        self.assertIn("no tailored resume sent yet", self.page.text_content("#insFunnel"))

    # --- goals
    def test_skill_gaps_and_career_tracks_panel(self):  # pass 29, blueprint 13.1 / 13.3
        self.go("insights")
        panel = self.page.locator("#gapPanel")
        self.assertIn("Skill gaps", panel.locator("h3").text_content())
        self.assertRegex(panel.locator(".gap-note").text_content(), r"based on \d+ (open )?jobs?")
        self.assertIn("Career tracks", panel.text_content())

    def test_weekly_goals_save_bad_value_and_clear(self):
        self.allow_console()
        self.no_goals()
        self.assertIn("no goals set", self.page.text_content("#goalBars"))
        self.assertEqual(self.page.get_attribute("#g_contacts", "placeholder"), "not set")
        self.page.fill("#g_contacts", "3")
        self.page.fill("#g_applications", "2")
        self.run_click(self.page.get_by_role("button", name="Save goals"))
        self.expect_toast("weekly goals saved", "ok")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["weekly_goals"], {"contacts": 3, "applications": 2})
        bars = self.page.locator("#goalBars progress")
        self.assertEqual(bars.count(), 2)
        self.assertEqual(sorted(int(b.get_attribute("max")) for b in bars.all()), [2, 3])
        self.assertTrue(all(re.search(r"\d+ of [23] this week", t) for t in self.page.locator("#goalBars label").all_text_contents()))
        self.assertEqual(self.page.input_value("#g_contacts"), "3")  # the form shows what is set
        self.page.fill("#g_mock_sessions", "5000")
        self.page.get_by_role("button", name="Save goals").click()
        self.expect_toast("error: weekly goal mock_sessions must be between 0 and 1000", "err")
        self.assertEqual(settings.load()["prefs"]["weekly_goals"], {"contacts": 3, "applications": 2})
        self.page.fill("#g_mock_sessions", "")
        self.page.fill("#g_contacts", "0")
        self.run_click(self.page.get_by_role("button", name="Save goals"))
        self.idle()
        self.assertEqual(settings.load()["prefs"]["weekly_goals"], {"applications": 2})
        self.assertEqual(self.page.locator("#goalBars progress").count(), 1)
        self.page.fill("#g_applications", "0")
        self.run_click(self.page.get_by_role("button", name="Save goals"))
        self.idle()
        self.assertIn("no goals set", self.page.text_content("#goalBars"))

    # --- offers side by side
    def test_offers_side_by_side_best_market_and_private_floor(self):
        o = self.api("/api/offers")
        head = self.page.locator("#offerTable thead th").all_text_contents()[1:]
        self.assertEqual(len(head), len(o["offers"]))
        juniper = next(i for i, r in enumerate(o["offers"]) if r["job_id"] == self.ids["offer"])
        self.assertIn("Juniper Robotics", head[juniper])
        self.assertIn("ML Data Engineer · offer", head[juniper])
        base = self.page.locator("#offerTable tbody tr", has=self.page.locator("td:text-is('base')"))
        cell = base.locator("td").nth(juniper + 1)
        self.assertEqual(cell.get_attribute("class"), "best" if self.ids["offer"] in o["best"]["base"] else "")
        self.assertIn("182,000", cell.text_content())
        y1 = self.page.locator("#offerTable tbody tr", has=self.page.locator("td:text-is('year-1 total')"))
        self.assertIn(f"{o['offers'][juniper]['total']['year1_total']:,}", y1.locator("td").nth(juniper + 1).text_content())
        market = self.page.locator("#offerTable tbody tr", has=self.page.locator("td:text-is('market range')"))
        self.assertIn("140,000–190,000", market.locator("td").nth(juniper + 1).text_content())
        floor = self.page.locator("#offerTable tr.private")
        self.assertIn("(private)", floor.text_content())
        self.assertEqual(floor.locator("td").nth(juniper + 1).text_content(), f"+{o['offers'][juniper]['vs_floor']:,}")
        self.assertIn("hybrid", self.page.locator("#offerTable tbody tr", has=self.page.locator("td:text-is('remote')")).text_content())
        self.page.locator("#offerTable thead a", has_text="Juniper Robotics").click()
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=self.ids["offer"])
        self.assertTrue(self.page.is_visible("section#board.on"))

    def test_record_offer_blank_bad_and_move_to_offer(self):
        self.allow_console()
        self.page.click("#offerPanel summary:text('Record or edit an offer')")
        saved = self.ids["saved"]
        self.page.select_option("#ofJob", str(saved))
        self.assertEqual(self.page.input_value("#of_base"), "")
        self.page.get_by_role("button", name="Save offer").click()
        self.expect_toast("fill in at least one field", "err")
        self.page.fill("#of_base", "160000")
        self.page.fill("#of_bonus_pct", "500")
        self.page.get_by_role("button", name="Save offer").click()
        self.expect_toast("error: bonus_pct must be between 0 and 200", "err")
        self.assertIsNone(db.get_offer(saved))
        self.page.fill("#of_bonus_pct", "12.5")
        self.page.fill("#of_start_date", day(45))
        self.page.select_option("#of_remote", "remote")
        self.page.fill("#of_notes", "verbal offer, written to follow")
        self.run_click(self.page.get_by_role("button", name="Save offer"))
        self.expect_toast("offer saved", "ok")
        self.idle()
        o = db.get_offer(saved)
        self.assertEqual((o["base"], o["bonus_pct"], o["remote"], o["start_date"]), (160000, 12.5, "remote", day(45)))
        self.assertEqual(db.get_job(saved)["status"], "offer")  # a job not yet at offer moves there
        self.assertIn("Northwind Analytics", self.page.locator("#offerTable thead").text_content())
        self.assertEqual(self.page.input_value("#ofJob"), str(saved))
        self.assertEqual(self.page.input_value("#of_base"), "160000")  # the form shows the stored offer
        # an empty field clears it
        self.page.fill("#of_notes", "")
        self.run_click(self.page.get_by_role("button", name="Save offer"))
        self.idle()
        self.assertIsNone(db.get_offer(saved)["notes"])

    # --- counter-offer
    def test_counter_offer_template_options_and_inbox(self):
        self.allow_console()
        db.set_offer(self.ids["accepted"], base=175000, sign_on=10000)  # a competing offer with figures to cite
        self.reopen()
        self.page.click("#offerPanel summary:text('Draft a counter-offer')")
        self.page.select_option("#ctrJob", str(self.ids["offer"]))
        cites = self.page.locator("#ctrCite label")
        labels = cites.all_text_contents()
        self.assertIn(f"#{self.ids['accepted']} Harbor & Pine: base 175,000", [x.strip() for x in labels])
        self.assertFalse(any("Juniper" in x for x in labels))  # never the offer being countered
        self.page.get_by_role("button", name="Draft counter-offer").click()  # nothing ticked, no ask
        self.idle()
        self.expect_toast("error: tick at least one competing figure to cite, or say what you are asking for", "err")
        before = {p["id"] for p in self.state()["pending"]}
        cites.filter(has_text="base 175,000").locator("input").check()
        self.page.fill("#ctrAsk", "a base of 190,000")
        self.page.check("#ctrTpl")
        calls = len(self.ai_calls)
        self.run_click(self.page.get_by_role("button", name="Draft counter-offer"))
        self.assertEqual(len(self.ai_calls), calls)  # plain template: no AI
        new = [p for p in self.state()["pending"] if p["id"] not in before]
        self.assertEqual(len(new), 1)
        p = new[0]["payload"]
        self.assertEqual((new[0]["job_id"], p["to"]), (self.ids["offer"], "recruiting@juniperrobotics.example"))
        self.assertIn("175,000", p["body"])
        self.assertIn("190,000", p["body"])
        for private in ("Harbor", "165,000", "165000"):
            self.assertNotIn(private, p["subject"] + p["body"])
        out = self.page.text_content("#ctrOut")
        self.assertIn(f"Subject: {p['subject']}", out)
        self.assertIn(f"-> pending (inbox #{new[0]['id']})", out)
        # Options: one AI call, nothing proposed until you use one
        self.page.uncheck("#ctrTpl")
        before = {p["id"] for p in self.state()["pending"]}
        self.run_click(self.page.locator("#offerPanel").get_by_role("button", name="Options"))
        self.assertEqual(len(self.ai_calls), calls + 1)
        self.assertIn("a base salary of 175,000", str(self.ai_calls[-1]["messages"]))
        self.assertNotIn("165,000", str(self.ai_calls[-1]["messages"]))
        opts = self.page.locator("#ctrOpts .opt")
        self.assertEqual(opts.count(), 2)
        self.assertEqual({p["id"] for p in self.state()["pending"]}, before)
        self.run_click(opts.nth(0).get_by_role("button", name="Use this"))
        new = [p for p in self.state()["pending"] if p["id"] not in before]
        self.assertEqual([(x["payload"]["subject"], x["payload"]["to"]) for x in new],
                         [("Revisiting the base", "recruiting@juniperrobotics.example")])
        self.assertIn(f"inbox #{new[0]['id']}", self.page.text_content("#ctrOut"))
        self.assertEqual(self.page.locator("#ctrOpts .opt").count(), 0)

    # --- activity log
    def test_activity_log_show_minimum_csv_and_print(self):
        self.allow_console()
        self.assertTrue(self.page.input_value("#acFrom"))  # this week by default
        self.assertEqual(self.page.input_value("#acTo"), day(0))
        self.page.fill("#acFrom", day(-14))
        self.run_click(self.page.locator("#insights").get_by_role("button", name="Show", exact=True))
        weeks = self.page.locator("#acOut h4")
        self.assertGreaterEqual(weeks.count(), 3)
        self.assertIn("check your state's requirements", self.page.text_content("#acOut"))
        self.assertIn("Orchid Health", self.page.text_content("#acOut table"))
        self.assertEqual(self.page.locator("#acOut .pill").count(), 0)  # no minimum yet
        self.page.fill("#acMin", "500")
        self.press("Tab")
        self.expect_toast("error: activity_weekly_min must be between 0 and 100", "err")  # the name is shown, not ***
        self.page.fill("#acMin", "2")
        self.press("Tab")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["activity_weekly_min"], 2)
        self.run_click(self.page.locator("#insights").get_by_role("button", name="Show", exact=True))
        pills = self.page.locator("#acOut .pill").all_text_contents()
        self.assertEqual(len(pills), weeks.count())
        self.assertTrue(set(pills) <= {"met", "not met"})
        self.assertIn("minimum 2", weeks.first.text_content())
        self.run_click(self.page.get_by_role("button", name="Export CSV"))
        path = self.expect_toast("CSV written: ", "ok").split("CSV written: ", 1)[1].strip()
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][:3], ["date", "activity", "employer"])
        self.assertTrue(any("Orchid Health" in r for r in rows[1:]))
        opened = len(self.opened)
        self.run_click(self.page.get_by_role("button", name="Printable page"))
        self.expect_toast("printable page opened in your browser: ", "ok")
        kind, url = self.opened[opened]
        self.assertEqual(kind, "browser")
        self.assertTrue(url.startswith("file:") and url.endswith(".html"), url)
        self.page.fill("#acMin", "")
        self.press("Tab")
        self.idle()

    def test_keyboard_and_420px(self):
        self.addCleanup(settings.set_pref, "weekly_goals", {"contacts": 0})
        self.page.focus("#g_contacts")
        self.page.keyboard.type("4")
        self.tab_to("#goalForm button")
        self.press("Enter")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["weekly_goals"].get("contacts"), 4)
        self.page.click("#offerPanel summary:text('Record or edit an offer')")
        self.page.click("#offerPanel summary:text('Draft a counter-offer')")
        self.page.click("#insights summary:text('as a table')")
        self.run_click(self.page.locator("#insights").get_by_role("button", name="Show", exact=True))
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
