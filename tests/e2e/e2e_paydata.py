"""Market pay (BLS OEWS, paydata.py) in the browser: off by default with nothing sent, one click turns it on and fetches
the open job once (the percentile strip, the posting's band, the honesty label, the board chip), a cached figure is never
fetched again; a metro BLS does not publish falls back to the state, your occupation pick wins and 'none' hides it; a
BLS error is shown as text once per page load (Fetch retries); the offers table's BLS row and the counter-offer citing
the public figure (never the floor); 420px. BLS is a fake util.fetch (series IDs in, canned figures out)."""
import json
import unittest

from harness import FLOOR, E2ETestCase, db
from lodestar import paydata, settings, util

PDX = {"mean": 155000, "p10": 95000, "p25": 120000, "p50": 150000, "p75": 185000, "p90": 220000}
SEA = {"mean": 174920, "p10": 99190, "p25": 132800, "p50": 167280, "p75": 211860, "p90": 257960}
BOS = {"mean": 180000, "p10": 110000, "p25": 140000, "p50": 175000, "p75": 200000, "p90": 240000}
DT = {v: k for k, v in paydata.DATATYPES.items()}
TABLE = {paydata.series_id(soc, area, DT[k]): v for soc, area, figs in (
    ("15-1252", "M0038900", PDX), ("15-1252", "M0042660", SEA), ("15-1252", "M0014460", BOS),
    ("15-1299", "S5300000", {"p50": 140000, "p75": 170000})) for k, v in figs.items()}  # 15-1299 Seattle: unpublished
EVIL = "<img src=x onerror=alert(1)> Invalid series"


class Paydata(E2ETestCase):
    FAIL: dict = {}  # area code -> a canned BLS answer that is not a success

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bls, other = [], util.fetch  # the harness fake answers everything that is not BLS

        def fetch(url, timeout=25, headers=None, max_bytes=None, follow=True, data=None):
            if "api.bls.gov" not in url:
                return other(url, timeout, headers, max_bytes, follow)
            ids = json.loads(data)["seriesid"]
            cls.bls.append(ids)
            bad = next((v for a, v in cls.FAIL.items() if any(a in s for s in ids)), None)
            if bad:
                return json.dumps(bad)
            series = [{"seriesID": s, "data": [{"year": "2025", "period": "A01", "periodName": "Annual", "latest": "true",
                                                "value": str(TABLE[s]), "footnotes": [{}]}]} for s in ids if s in TABLE]
            return json.dumps({"status": "REQUEST_SUCCEEDED", "message": [f"Series does not exist for Series {s}" for s in ids
                                                                          if s not in TABLE], "Results": {"series": series}})
        cls._patch(util, "fetch", fetch)

    def on(self):
        settings.set_pref("market_pay", "on")
        self.reload_state()

    def test_drawer_is_off_until_one_click_then_fetches_once_and_the_board_shows_the_chip(self):
        settings.set_pref("market_pay", "off")
        self.reload_state()
        jid, n = self.ids["saved"], len(self.bls)
        d = self.open_job(jid)
        self.assertIn("Turn on market pay", d.locator("#jPay").text_content())
        self.assertIn("sends only occupation and area codes to api.bls.gov", d.locator("#jPay").text_content())
        self.assertEqual((len(self.bls), self.page.locator(".chip.pay").count()), (n, 0))  # off: nothing sent, no chip
        self.run_click("#jPayOn")
        self.page.locator("#jPay .pstrip").wait_for()
        self.idle()
        self.assertTrue(settings.pref("market_pay"))
        self.assertEqual(len(self.bls), n + 1)  # one batched query for the job you opened
        self.assertEqual(len(self.bls[-1]), 6)
        self.assertEqual(self.page.locator("#jPay .pstrip i").count(), 5)
        self.assertEqual(self.page.locator("#jPay .pstrip .post").count(), 1)
        text = self.page.text_content("#jPay")
        for part in ("Software Developers (15-1252), matched by keyword 'data engineer'",
                     "Portland-Vancouver-Hillsboro, OR-WA (metro)", "10th 95,000 | 25th 120,000 | median 150,000",
                     "This posting's top end sits between the median and the 75th percentile.", "BLS OEWS May 2025",
                     "It is not this company's pay band", "BLS.gov cannot vouch for the data"):
            self.assertIn(part, text)
        chip = self.page.locator(f'.card[data-id="{jid}"] .chip.pay')
        self.assertEqual(chip.text_content(), "market median $150k (BLS May 2025, Portland)")
        self.assertIn("BLS.gov cannot vouch", chip.get_attribute("title"))
        self.open_job(jid)  # cached: opening it again asks BLS nothing
        self.idle()
        self.assertEqual(len(self.bls), n + 1)
        self.assertEqual(self.page.locator("#jPayGet").count(), 0)

    def test_metro_without_a_figure_falls_back_to_the_state_and_your_occupation_wins(self):
        self.on()
        jid, n = self.ids["screening"], len(self.bls)
        self.open_job(jid)
        self.page.wait_for_function("() => document.querySelector('#jPay') && document.querySelector('#jPay').textContent.includes('Washington')")
        self.idle()
        text = self.page.text_content("#jPay")
        self.assertIn("Computer Occupations, All Other (15-1299), matched by keyword 'platform engineer' (closest BLS group)", text)
        self.assertIn("Washington (state: BLS publishes no figure for this occupation in Seattle-Tacoma-Bellevue, WA)", text)
        self.assertEqual(len(self.bls), n + 2)  # the metro (nothing published), then the state
        self.page.select_option("#jSoc", "15-1252")
        self.page.wait_for_function("() => document.querySelector('#jPay').textContent.includes('set by you')")
        self.page.locator("#jPay .pstrip").wait_for()
        self.idle()
        text = self.page.text_content("#jPay")
        self.assertIn("Software Developers (15-1252), set by you", text)
        self.assertIn("Seattle-Tacoma-Bellevue, WA (metro)", text)
        self.assertEqual(db.get_job(jid)["soc_by"], "user")
        self.page.select_option("#jSoc", "none")
        self.page.wait_for_function("() => document.querySelector('#jPay').textContent.includes('Hidden for this job')")
        self.idle()
        self.assertEqual(self.page.locator(f'.card[data-id="{jid}"] .chip.pay').count(), 0)
        self.page.select_option("#jSoc", "")  # back to automatic
        self.page.wait_for_function("() => document.querySelector('#jPay').textContent.includes('platform engineer')")
        self.idle()

    def test_offline_or_refused_answers_show_as_text_once_per_page_load(self):
        self.on()
        Paydata.FAIL = {"M0012420": {"status": "REQUEST_NOT_PROCESSED", "message": [EVIL]}}
        try:
            jid, n = self.ids["rejected"], len(self.bls)
            self.open_job(jid)
            self.page.wait_for_function("() => (document.querySelector('#jPayErr') || {}).textContent")
            self.idle()
            err = self.page.locator("#jPayErr")
            self.assertEqual(err.text_content(), f"BLS: {EVIL}")
            self.assertEqual(err.locator("img").count(), 0)  # text, never markup
            self.assertEqual(len(self.bls), n + 1)
            self.open_job(jid)  # one automatic try per job per page load
            self.idle()
            self.assertEqual(len(self.bls), n + 1)
            self.run_click("#jPayGet")  # Fetch BLS figures: you asked, so it tries again
            self.assertEqual(len(self.bls), n + 2)
            self.assertIn("Invalid series", self.page.text_content("#jPayErr"))
        finally:
            Paydata.FAIL = {}

    def test_offers_compare_row_and_the_counter_offer_cites_the_public_figure(self):
        self.allow_console()
        self.on()
        jid = self.ids["offer"]  # Juniper, Boston, base 182,000
        paydata.fetch([paydata.for_job(db.get_job(jid))["next"]])  # what opening its drawer does
        self.go("insights")
        row = self.page.locator("#offerTable tr", has_text="BLS market (median / 75th)")
        self.assertIn("175,000 / 200,000", row.text_content())
        self.assertIn("base at median-75th", row.text_content())
        self.page.click("#offerPanel summary:text('Draft a counter-offer')")
        self.page.select_option("#ctrJob", str(jid))
        labels = [x.strip() for x in self.page.locator("#ctrCite label").all_text_contents()]
        self.assertIn("public BLS 75th percentile for this job: 200,000 (May 2025, Boston)", labels)
        self.assertFalse(any("BLS median" in x for x in labels))  # their base is above it: it would argue for less
        before = {p["id"] for p in self.state()["pending"]}
        self.page.locator("#ctrCite label", has_text="public BLS 75th").locator("input").check()
        self.page.check("#ctrTpl")
        self.run_click(self.page.get_by_role("button", name="Draft counter-offer"))
        new = [p for p in self.state()["pending"] if p["id"] not in before]
        self.assertEqual(len(new), 1)  # waits in the Inbox, always reviewed
        body = new[0]["payload"]["body"]
        self.assertIn("Public data point the same way: U.S. Bureau of Labor Statistics data (May 2025) put the 75th "
                      "percentile annual wage for Software Developers in the Boston-Cambridge-Newton area at $200,000.", body)
        for private in (FLOOR, FLOOR.replace("$", "").replace(",", "")):
            self.assertNotIn(private, body)

    def test_narrow_window_420(self):
        self.on()
        self.set_viewport(420)
        self.open_job(self.ids["accepted"])  # Portland, data engineer: cached by now, or fetched once here
        self.page.locator("#jPay .pstrip").wait_for()
        self.idle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
