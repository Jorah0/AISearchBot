"""Careers tab (pass 23, blueprint 18.2): suggestions in career-class bands with their four explanations and the O*NET
credit, a desired-field track added from the page, its live search with the board coverage, and tracking a result.
The fixture ontology (tests/careers_fixture.py) stands in for O*NET."""
import sys
import unittest
from pathlib import Path

from harness import FETCH, E2ETestCase

from lodestar import careers, occupations, profile  # noqa: E402  (after harness: it sets the temp home first)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careers_fixture import BANK, write_fixture  # noqa: E402

INN = {"title": "Hotel Manager", "company_name": "Saltmarsh Inn", "url": "https://jobs.example.com/saltmarsh-inn/hm",
       "candidate_required_location": "USA", "description": "Run a 90-room hotel: front office, budgets, guest care."}


class Careers(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        saved = occupations.DATA
        occupations.DATA = write_fixture(Path(profile.BANK).parent / "onet-fixture.json.gz")
        cls.addClassCleanup(lambda: setattr(occupations, "DATA", saved))
        cls.addClassCleanup(lambda saved=dict(FETCH): (FETCH.clear(), FETCH.update(saved)))
        FETCH["remotive.com"] = {"jobs": [INN]}
        profile.save(dict(BANK))

    def tearDown(self):
        for t in careers.tracks():
            careers.remove_track(t["id"])
        super().tearDown()

    def test_bands_show_classes_explanations_and_credit(self):
        self.go("careers")
        for band in ("Qualified now", "Competitive with framing", "Bridge required", "Longer-term development"):
            self.assertTrue(self.page.locator("#careers h3", has_text=band).count(), band)
        card = self.page.locator("#careers .career-card", has_text="Logisticians")
        text = card.inner_text()
        for part in ("Transferable fit", "Why it fits", "What is missing", "SAP software", "To close the gap", "O*NET test fixture"):
            self.assertIn(part, text)
        self.assertIn("test fixture credit", self.page.locator("#careers .credit").inner_text())

    def test_desired_field_track_searches_with_coverage_and_tracks_a_result(self):
        self.go("careers")
        self.page.fill("#trackLabel", "Hospitality")
        self.page.fill("#trackTitles", "Hotel manager")
        self.page.select_option("#trackIntent", "desired_field")
        self.page.click("#trackAdd")
        self.idle()
        row = self.page.locator("#careers .track-row", has_text="Hospitality")
        self.assertIn("Requested target", row.inner_text())
        # the track's field is now a suggestion too, in its own band
        self.assertTrue(self.page.locator("#careers .career-card", has_text="Lodging Managers").count())
        self.run_click(row.get_by_role("button", name="Search live openings"))
        self.assertIn("never searches every job board", self.page.locator("#careers .coverage").inner_text())
        self.assertIn("remotive", self.page.locator("#careers .coverage").inner_text())
        res = self.page.locator("#careers .career-results li", has_text="Saltmarsh Inn")
        self.assertEqual(res.count(), 1)
        res.get_by_role("button", name="Track").click()
        self.idle()
        self.assertTrue(any(j["company"] == "Saltmarsh Inn" for j in self.api("/api/state")["jobs"]))

    def test_bad_track_is_refused_in_place(self):
        self.allow_console()  # the API's 400 for the refused track
        self.go("careers")
        self.page.fill("#trackLabel", "Nothing")
        self.page.fill("#trackTitles", "")
        self.page.click("#trackAdd")
        self.idle()
        self.assertIn("a track needs a title or an occupation", self.page.locator("#trackErr").inner_text())
        self.assertEqual(careers.tracks(), [])


if __name__ == "__main__":
    unittest.main()
