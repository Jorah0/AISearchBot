"""Blueprint v1.1 acceptance journey (pass 30, sections 20.2 / 20.3), end to end in the page with a non-software resume:
career suggestions across distinct fields with their source, a target unrelated to the resume accepted and searched,
coverage shown, a live posting tracked, its career class and hard requirements (unknown, never met) in the drawer, and
a stage move kept in its history. The fixture ontology stands in for O*NET; the job board is faked."""
import sys
import unittest
from pathlib import Path

from harness import FETCH, E2ETestCase

from lodestar import careers, occupations, profile  # noqa: E402  (after harness: it sets the temp home first)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from careers_fixture import BANK, write_fixture  # noqa: E402

RN = {"title": "Registered Nurse", "company_name": "Harbor Clinic", "url": "https://jobs.example.com/harbor-clinic/rn",
      "candidate_required_location": "USA",
      "description": "Requirements:\n- Must hold a valid Registered Nurse license in the state\n- Patient care and charting "
                     "in an electronic health record. We are a community clinic serving families across the harbor district "
                     "with primary care, vaccinations and chronic-care programmes, and we value calm, careful teamwork."}


class Acceptance(E2ETestCase):
    @classmethod
    def seed(cls):
        super().seed()
        saved = occupations.DATA
        occupations.DATA = write_fixture(Path(profile.BANK).parent / "onet-fixture.json.gz")
        cls.addClassCleanup(lambda: setattr(occupations, "DATA", saved))
        cls.addClassCleanup(lambda saved=dict(FETCH): (FETCH.clear(), FETCH.update(saved)))
        FETCH["remotive.com"] = {"jobs": [RN]}
        profile.save(dict(BANK))

    def test_resume_to_tracks_to_a_live_job_to_its_gates_and_stage(self):
        self.go("careers")
        cards = self.page.locator("#careerSug .career-card")
        codes = {t.split(" · ")[0].strip()[:2] for t in cards.locator(".muted.grow").all_text_contents()}
        self.assertGreaterEqual(len(codes), 2, codes)  # distinct major occupation groups from one retail resume
        self.assertEqual(cards.count(), cards.filter(has_text="O*NET test fixture").count())  # every one names its source
        # a field the resume shows nothing for is accepted, labelled honestly, and searched
        self.page.fill("#trackLabel", "Nursing")
        self.page.fill("#trackTitles", "Registered nurse")
        self.page.select_option("#trackIntent", "pivot")
        self.page.click("#trackAdd")
        self.idle()
        rn = self.page.locator("#careerSug .career-card", has_text="Registered Nurses")
        self.assertIn("Requested target", rn.inner_text())
        self.assertIn("Bridge required", rn.inner_text())  # licensed and no credential: never qualified
        self.assertIn("Licensing:", rn.inner_text())
        self.run_click(self.page.locator(".track-row", has_text="Nursing").get_by_role("button", name="Search live openings"))
        self.assertIn("never searches every job board", self.page.locator("#careerRes .coverage").inner_text())
        res = self.page.locator("#careerRes .career-results li", has_text="Harbor Clinic")
        res.get_by_role("button", name="Track").click()
        self.idle()
        fitg = self.page.locator("#drawer #jFit")  # tracking opens the job
        self.assertEqual(fitg.locator(".chip.fit-class").text_content(), "Insufficient evidence")
        self.assertIn("Registered Nurse license: unknown (never counted as met)", fitg.locator(".gates").text_content())
        self.page.locator("#jStageSel").select_option("recruiter_screen")
        self.page.get_by_role("button", name="set stage").click()
        self.idle()
        job = next(j for j in self.state()["jobs"] if j["company"] == "Harbor Clinic")
        self.assertEqual((job["status"], job["stage"]), ("screening", "recruiter_screen"))
        self.assertTrue(careers.tracks())


if __name__ == "__main__":
    unittest.main()
