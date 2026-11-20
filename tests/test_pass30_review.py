"""Pass 30, final review fixes: O*NET titles with commas never split into broader searches, all-failing boards are
'nothing checked', a blocked or unknown hard requirement never auto-submits, corrupt occupation data is a clear
message, disputed facts never reach AI prompts for employer text, unsafe result links are not links, and exclusions
match whole words. No network; every patched attribute is put back."""
import gzip
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from careers_fixture import BANK, write_fixture  # noqa: E402
from test_pass21_fit import Base  # noqa: E402

from lodestar import apply_agent, careers, db, fit, occupations, profile, settings  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402

PKG = Path(__file__).resolve().parents[1] / "lodestar"


class Fixture(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="review-")
        self._data = occupations.DATA
        occupations.DATA = write_fixture(Path(self.tmp) / "onet.json.gz")

    def tearDown(self):
        occupations.DATA = self._data
        super().tearDown()


class Fixes(Fixture):
    def test_onet_titles_with_commas_are_never_split_into_searches(self):
        t = careers.get_track(careers.add_track("Desk", "resume_led", codes=["43-4081.00"], tiers=[1]))
        titles = careers.search_titles(t)
        self.assertNotIn("Hotel, Motel, and Resort Desk Clerks", titles)
        self.assertEqual(titles, ["Front Desk Agent"])
        self.assertFalse(any(re.search(r",|;|\|| or ", x) for x in titles))
        self.assertIsNone(careers._SPLITS.search("Medical Office Coordinator"))  # 'or' inside a word is not a split
        self.assertIsNotNone(careers._SPLITS.search("Bartender or Barista"))  # a separate 'or' is
        t = careers.get_track(careers.add_track("Mixed", "desired_field", titles=["Chef, Cook"]))  # one item, two titles
        self.assertEqual(careers.search_titles(t), ["Chef", "Cook"])

    def test_every_board_failing_is_nothing_checked(self):
        old = (wm.SOURCES, wm.sources_ready)
        try:
            wm.SOURCES, wm.sources_ready = {"remotive": None, "hn": None}, lambda: ["remotive", "hn"]
            cov = careers.coverage(["remotive", "hn"], ["remotive: HTTP 500", "hn: timed out"])
            self.assertFalse(cov["checked"])
            self.assertTrue(careers.coverage(["remotive", "hn"], ["hn: timed out"])["checked"])
        finally:
            wm.SOURCES, wm.sources_ready = old

    def test_corrupt_or_misshapen_occupation_data_is_a_clear_message(self):
        good = occupations.DATA.read_bytes()
        bad = Path(self.tmp) / "bad.json.gz"
        bad.write_bytes(good[:10] + b"\x00" * 40 + good[50:])  # a valid gzip header, a broken body
        occupations.DATA = bad
        with self.assertRaises(SystemExit):
            occupations.load()
        shape = Path(self.tmp) / "shape.json.gz"
        shape.write_bytes(gzip.compress(json.dumps({"meta": {}, "occ": []}).encode()))
        occupations.DATA = shape
        with self.assertRaises(SystemExit):
            occupations.load()

    def test_exclusions_match_whole_words(self):
        old = settings.pref("excluded_title_words")
        try:
            settings.set_pref("excluded_title_words", "manage")
            codes = {s["code"] for s in careers.suggest(bank=BANK)["suggestions"]}
            self.assertIn("11-2022.00", codes)  # Sales Managers: 'manage' is only inside a word
            settings.set_pref("excluded_title_words", "managers")
            self.assertNotIn("11-2022.00", {s["code"] for s in careers.suggest(bank=BANK)["suggestions"]})
        finally:
            settings.set_pref("excluded_title_words", old or "")


class AutoSubmit(Base):
    def test_a_blocked_or_unknown_hard_requirement_never_auto_submits(self):
        settings.set_pref("excluded_companies", "Blockco")
        jid = db.add_job("Blockco", "Data Engineer", None, "jd", "via test")
        fit.for_job(db.get_job(jid))
        why = apply_agent.auto_blockers(db.get_job(jid), "greenhouse")
        self.assertTrue(any("hard requirement" in w for w in why), why)
        settings.set_pref("excluded_companies", "")
        settings.set_pref("work_authorization", "needs_sponsorship")  # a posting silent on it: unknown, never met
        fit.for_job(db.get_job(jid))
        why = apply_agent.auto_blockers(db.get_job(jid), "greenhouse")
        self.assertTrue(any("unknown" in w for w in why), why)


class DisputedPrompts(Base):
    def test_disputed_facts_never_reach_prompt_text(self):
        from lodestar.config import PROFILE

        PROFILE.write_text("# Jane Doe\nJane Doe | Austin, TX | jane@example.com\n## Experience\n"
                           "### Store Manager - Acme Retail (2019-01 - 2025-06)\n- Led 14 staff\n"
                           "### Night Auditor - Saltmarsh Inn (2016-01 - 2018-12)\n- Balanced accounts\n", encoding="utf-8")
        self.assertIn("Saltmarsh Inn", profile.candidate_text(private=False))
        profile.set_disputed("experience", ["Saltmarsh Inn", "Night Auditor"])
        text = profile.candidate_text(private=False)
        self.assertNotIn("Saltmarsh Inn", text)
        self.assertNotIn("Balanced accounts", text)
        self.assertIn("Acme Retail", text)


class PageLinks(unittest.TestCase):
    def test_career_result_links_pass_safe_url(self):
        js = (PKG / "static" / "app.js").read_text(encoding="utf-8")
        body = js.split("function renderCareerRes(r) {", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("safeUrl(x.url)", body)


if __name__ == "__main__":
    unittest.main()
