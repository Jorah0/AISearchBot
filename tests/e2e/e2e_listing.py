"""One listing monitored both ways (pass 21): the drawer's Listing activity (posting checks, an alert sighting, ATS mail
filed with its link reason and never trusted, all escaped), its posting line and Use live description; Today's
'posting closed' item; Setup > Job alerts (each site's last alert read, the job_alerts switch)."""
import json
import unittest

from harness import E2ETestCase, db

from lodestar import config, settings  # noqa: E402  (after harness: it sets the temp home first)
from lodestar.resume import app_dir  # noqa: E402

XSS = "<img src=x onerror=window.__xss=1>"
LIVE = "Build pipelines in Python and SQL.\nOwn the lakehouse.\nMentor two engineers."


class Listing(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        jid = db.add_job("Larchmont Data", "Data Engineer", "https://careers.larchmont.example/jobs/de", "the JD I tailored to")
        db.set_status(jid, "applied")
        cls.ids["listing"] = jid
        config.SNAPSHOTS.mkdir(exist_ok=True)  # read at run time: the harness moved the home after import
        (config.SNAPSHOTS / f"job-{jid}.json").write_text(json.dumps({"title": "Data Engineer", "location": "Chicago, IL",
                                                               "salary": "", "desc": LIVE, "desc_sha": "x"}), encoding="utf-8")
        (app_dir(db.get_job(jid)) / "posting_changes.md").write_text(
            "\n## 2026-11-10 posting changed\n\ndescription +1/-1 lines\n\n```diff\n-Own the warehouse.\n+Own the lakehouse.\n```\n",
            encoding="utf-8")
        db.add_event(jid, "posting_changed", f"title 'Data Engineer' -> 'Data Engineer {XSS}'")
        db.add_event(jid, "listing_seen", "in LinkedIn alert 2026-11-10: Data Engineer")
        db.add_event(jid, "posting_removed", "posting page: HTTP 404 (checked 2026-11-11)")
        db.add_mail(message_id="<e2e-ats@greenhouse-mail.io>", job_id=jid, direction="in",
                    from_addr="no-reply@us.greenhouse-mail.io", subject=f"Thanks for applying {XSS}",
                    category="application_received", trusted=False, linked_by="auto", link_reason="ATS posting link 4012399")
        db.meta_set("alerts:linkedin:last", 1793000000)
        db.meta_set("alerts:linkedin:n", 14)

    def test_drawer_listing_activity_escaped_and_use_live_description(self):
        d = self.open_job(self.ids["listing"])
        group = d.locator("#jActivity")
        text = group.text_content()
        self.assertIn(f"Data Engineer {XSS}", text)  # page text shown as text, never markup
        self.assertIn(f"Thanks for applying {XSS}", text)
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertIn("posting removed today", group.locator("#jPosting").text_content())
        self.assertIn("seen in an alert today", group.locator("#jPosting").text_content())
        self.assertIn("1 email", group.locator("#jPosting").text_content())
        mail = group.locator('.actrow[data-src="mail"]')
        self.assertIn("unverified", mail.text_content())
        self.assertIn("ATS posting link 4012399", mail.text_content())
        self.assertEqual(group.locator('.actrow[data-src="alert"]').count(), 1)
        self.assertEqual(group.locator('.actrow[data-src="web"]').count(), 2)
        self.answer(True)
        self.run_click(group.get_by_role("button", name="Use live description"))
        self.expect_toast("description replaced by the live posting", "ok")
        self.assertEqual(db.get_job(self.ids["listing"])["jd"], LIVE)

    def test_today_posting_closed_and_setup_job_alerts_panel(self):
        today = self.page.locator("#today")
        btn = today.get_by_role("button", name="posting closed · #%d Larchmont Data - Data Engineer" % self.ids["listing"])
        self.assertEqual(btn.count(), 1)
        self.go("setup")
        card = self.page.locator("#alertCard")
        self.assertIn("never opens an alert's links", card.text_content())
        li = card.locator("#alertList div", has_text="LinkedIn")
        self.assertIn("14 jobs in it", li.text_content())
        self.assertIn("no alert read yet", card.locator("#alertList div", has_text="Glassdoor").text_content())
        box = self.page.locator("#alertsOn")
        self.assertTrue(box.is_checked())
        self.addCleanup(settings.set_tool, "job_alerts", True, True)
        box.uncheck()
        self.expect_toast("job alerts off", "ok")
        self.page.wait_for_function("() => !S.tools.find(t => t.tool === 'job_alerts').enabled")
        self.assertFalse(settings.enabled("job_alerts"))
        self.page.locator("#alertsOn").check()
        self.expect_toast("job alerts on", "ok")
        self.page.wait_for_function("() => S.tools.find(t => t.tool === 'job_alerts').enabled")


if __name__ == "__main__":
    unittest.main()
