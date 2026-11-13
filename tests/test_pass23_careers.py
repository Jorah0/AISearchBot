"""Pass 23: career discovery foundation. The bundled O*NET ontology (occupations.py, scripts/build_onet.py), expansion
tiers and career classes (careers.suggest), career tracks, and searching a track with visible source coverage. The
fixture ontology (careers_fixture.py) stands in for O*NET; no network. Every patched attribute is put back."""
import contextlib
import csv
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "scripts"))
import build_onet  # noqa: E402
from careers_fixture import BANK, write_fixture  # noqa: E402

from lodestar import careers, db, listings, occupations, profile, settings  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402

REAL_DATA = occupations.DATA


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="careers-")
        self._data = occupations.DATA
        occupations.DATA = write_fixture(Path(self.tmp) / "onet.json.gz")

    def tearDown(self):
        occupations.DATA = self._data


def _tsv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


class Ontology(FixtureCase):
    def test_build_script_reads_onet_text_zip(self):  # the O*NET 31.0 file and column names
        S, R = "O*NET-SOC Code", "41-1011.00"
        files = {
            "Occupation Data.txt": [{S: R, "Title": "First-Line Supervisors of Retail Sales Workers", "Description": "Directly supervise " * 40},
                                    {S: "41-2031.00", "Title": "Retail Salespersons", "Description": "Sell merchandise."}],
            "Job Zones.txt": [{S: R, "Job Zone": "3", "Date": "", "Domain Source": ""},
                              {S: "41-2031.00", "Job Zone": "2", "Date": "", "Domain Source": ""}],
            "Job Titles.txt": [{S: R, "Job Title": "Store Manager", "Short Title": "", "Source(s)": ""},
                               {S: R, "Job Title": "store manager", "Short Title": "", "Source(s)": ""},
                               {S: "41-2031.00", "Job Title": "Sales Associate", "Short Title": "", "Source(s)": ""}],
            "Related Occupations.txt": [{S: R, "Related O*NET-SOC Code": "11-2022.00", "Relatedness Tier": "Primary-Short", "Index": "2"},
                                        {S: R, "Related O*NET-SOC Code": "41-2031.00", "Relatedness Tier": "Primary-Short", "Index": "1"}],
            "Task Statements.txt": [{S: R, "Task ID": "1", "Task": "Direct and supervise employees.", "Task Type": "Core", "Incumbents Responding": "", "Date": "", "Domain Source": ""},
                                    {S: R, "Task ID": "2", "Task": "Order merchandise.", "Task Type": "Supplemental", "Incumbents Responding": "", "Date": "", "Domain Source": ""}],
            "Software Skills.txt": [{S: R, "Workplace Example": "Inventory software", "Element ID": "1", "Element Name": "", "Hot Technology": "N", "In Demand": "N"},
                                    {S: R, "Workplace Example": "Microsoft Excel", "Element ID": "2", "Element Name": "", "Hot Technology": "Y", "In Demand": "Y"}],
        }
        zp, out = Path(self.tmp) / "db_31_0_text.zip", Path(self.tmp) / "out.json.gz"
        with zipfile.ZipFile(zp, "w") as z:
            for name, rows in files.items():
                z.writestr(f"db_31_0_text/{name}", _tsv(rows))
        meta = build_onet.build(zp, out, version="31.0")
        data = json.loads(gzip.decompress(out.read_bytes()))
        o = data["occ"][R]
        self.assertEqual(o["zone"], 3)
        self.assertEqual(o["titles"], ["Store Manager"])  # de-duplicated case-insensitively
        self.assertEqual(o["related"], ["41-2031.00", "11-2022.00"])  # by Related Index ascending
        self.assertEqual(o["tasks"], ["Direct and supervise employees."])  # Core only
        self.assertEqual(o["tech"][0], "Microsoft Excel")  # Hot Technology first
        self.assertLessEqual(len(o["desc"]), 300)
        self.assertEqual((meta["version"], meta["license"]), ("31.0", "CC BY 4.0"))
        self.assertEqual(data["meta"], meta)

    def test_match_title_exact_and_fuzzy(self):
        self.assertEqual(occupations.match_title("store manager")[0], ("41-1011.00", 1.0))
        code, score = occupations.match_title("Sr. Store Manager")[0]
        self.assertEqual(code, "41-1011.00")
        self.assertGreaterEqual(score, 0.5)
        self.assertEqual(occupations.match_title("Ninja Rockstar"), [])
        self.assertEqual(occupations.related("11-9081.00"), ["43-4081.00", "11-9051.00"])
        self.assertIsNone(occupations.get("99-9999.00"))

    def test_missing_data_is_a_clear_error(self):
        occupations.DATA = Path(self.tmp) / "nope.json.gz"
        with self.assertRaises(SystemExit) as cm:
            occupations.load()
        self.assertIn("occupation data", str(cm.exception))
        bad = Path(self.tmp) / "bad.json.gz"
        bad.write_bytes(b"not gzip")
        occupations.DATA = bad
        with self.assertRaises(SystemExit):
            occupations.load()

    def test_bundled_data_loads(self):  # the real file, not the fixture
        occupations.DATA = REAL_DATA
        self.assertGreaterEqual(len(occupations.load()["occ"]), 1000)
        self.assertEqual(occupations.meta()["version"], "31.0")
        self.assertTrue(occupations.get("41-1011.00")["title"].startswith("First-Line Supervisors"))
        self.assertIn("CC BY 4.0", occupations.meta()["credit"])


class Discovery(FixtureCase):
    def suggest(self, **kw):
        return careers.suggest(bank=kw.pop("bank", BANK), **kw)

    def test_resume_led_tiers_and_classes(self):
        got = {s["code"]: (s["tier"], s["cls"]) for s in self.suggest()["suggestions"]}
        self.assertEqual(got, {
            "41-1011.00": (1, "qualified_now"),  # the user's own title
            "41-2031.00": (2, "qualified_now"),  # same major group, lower zone
            "11-9051.00": (3, "competitive_with_framing"),
            "43-4051.00": (3, "competitive_with_framing"),
            "11-2022.00": (3, "bridge_required"),  # zone 4 = candidate zone 3 + 1
            "13-1081.00": (3, "bridge_required"),
            "11-1011.00": (5, "longer_term"),  # zone 5 >= 3 + 2
        })
        self.assertEqual(self.suggest()["zone"], 3)

    def test_every_suggestion_names_its_source_and_four_explanations(self):
        out = self.suggest()["suggestions"]
        for s in out:
            self.assertEqual(s["source"], "O*NET test fixture")
            self.assertEqual((s["tier_label"], s["cls_label"]), (careers.TIERS[s["tier"]], careers.CLASSES[s["cls"]]))
            for k in ("why", "missing", "not_transfer", "close_gap"):
                self.assertIsInstance(s[k], list)
            self.assertTrue(s["why"])
        logi = next(s for s in out if s["code"] == "13-1081.00")
        self.assertIn("SAP software", logi["missing"])
        self.assertEqual(logi["close_gap"], [occupations.ZONE_PREP[4]])
        own = next(s for s in out if s["code"] == "41-1011.00")
        self.assertIn("Store Manager", own["why"][0])
        self.assertNotIn("Microsoft Excel", own["missing"])  # a skill you list is not missing
        self.assertIn("Formulate pricing policies for merchandise.", own["not_transfer"])  # no shared word with your text

    def test_tiers_are_never_broadened(self):
        self.assertEqual([s["code"] for s in self.suggest(tiers=(1,))["suggestions"]], ["41-1011.00"])

    def test_exclusions_drop_or_show_as_ineligible(self):
        old = settings.pref("excluded_title_words")
        try:
            settings.set_pref("excluded_title_words", "salespersons, sales managers")
            codes = {s["code"] for s in self.suggest()["suggestions"]}
            self.assertFalse({"41-2031.00", "11-2022.00"} & codes)
            self.assertIn("41-1011.00", codes)
            shown = {s["code"]: s["cls"] for s in self.suggest(show_excluded=True)["suggestions"]}
            self.assertEqual(shown["11-2022.00"], "ineligible")
        finally:
            settings.set_pref("excluded_title_words", old or "")

    def test_unmatched_title_is_insufficient_evidence(self):
        bank = {**BANK, "experience": [{"title": "Ninja Rockstar", "company": "X"}], "education": []}
        out = self.suggest(bank=bank)
        self.assertEqual(out["suggestions"], [])
        self.assertIn("Insufficient evidence", out["note"])

    def test_empty_profile_is_insufficient_evidence(self):
        out = self.suggest(bank=profile.empty())
        self.assertEqual((out["suggestions"], out["zone"]), ([], None))
        self.assertIn("Insufficient evidence", out["note"])

    def test_desired_field_target_and_its_bridges(self):
        got = {s["code"]: s for s in self.suggest(targets=["11-9081.00"], tiers=(0, 1, 2, 3, 4, 5))["suggestions"]}
        self.assertEqual((got["11-9081.00"]["tier"], got["11-9081.00"]["cls"]), (0, "bridge_required"))
        self.assertEqual((got["43-4081.00"]["tier"], got["43-4081.00"]["cls"]), (4, "bridge_required"))
        self.assertEqual(got["11-9051.00"]["tier"], 3)  # the lowest tier wins ...
        self.assertTrue(any("Lodging Managers" in w for w in got["11-9051.00"]["why"]))  # ... and names the route

    def test_regulated_target_is_flagged_and_never_qualified(self):
        s = self.suggest(targets=["29-1141.00"], tiers=(0,))["suggestions"][0]
        self.assertIn("license", s["regulated"].lower())
        self.assertEqual(s["cls"], "bridge_required")  # no RN credential in the evidence
        self.assertIn(s["regulated"], s["close_gap"])
        rn = {**BANK, "certifications": [{"name": "Registered Nurse (RN) license"}]}
        self.assertEqual(self.suggest(bank=rn, targets=["29-1141.00"], tiers=(0,))["suggestions"][0]["cls"],
                         "competitive_with_framing")

    def test_classify_table(self):
        C = careers.classify
        self.assertEqual(C(1, 3, 3), "qualified_now")
        self.assertEqual(C(2, 2, 3), "qualified_now")  # closely related and needs less preparation
        self.assertEqual(C(2, 3, 3), "competitive_with_framing")  # related, same preparation: not proven
        self.assertEqual(C(3, 3, 3), "competitive_with_framing")
        self.assertEqual(C(0, 3, 3), "competitive_with_framing")
        self.assertEqual(C(3, 4, 3), "bridge_required")
        self.assertEqual(C(4, 2, 3), "bridge_required")
        self.assertEqual(C(3, 5, 3), "longer_term")
        self.assertEqual(C(1, 3, None), "insufficient_evidence")
        self.assertEqual(C(1, None, 3), "insufficient_evidence")
        self.assertEqual(C(1, 3, 3, excluded=True), "ineligible")
        self.assertEqual(C(1, 3, 3, regulated_unmet=True), "bridge_required")

    def test_candidate_zone_is_conservative_per_title(self):
        Z = careers.candidate_zone
        self.assertEqual(Z({"Store Manager": ["41-1011.00", "11-2022.00"]}, []), 3)  # one title, two zones: the lower
        self.assertEqual(Z({"Store Manager": ["41-1011.00"], "Sales Manager": ["11-2022.00"]}, []), 4)  # across titles: max
        self.assertEqual(Z({"Store Manager": ["41-1011.00"]}, ["Bachelor of Science"]), 4)  # a degree can raise it
        self.assertEqual(Z({}, ["Associate of Arts"]), 3)
        self.assertIsNone(Z({}, []))

    def test_regulated_prefixes(self):
        self.assertIn("license", careers.regulated("29-1141.00").lower())
        self.assertIn("CDL", careers.regulated("53-3032.00"))
        self.assertIsNone(careers.regulated("41-1011.00"))


class TrackCase(FixtureCase):
    def tearDown(self):
        db.con().execute("DELETE FROM career_tracks")
        db.con().execute("DELETE FROM postings WHERE url LIKE 'https://%.test/%'")
        db.con().commit()
        super().tearDown()


class Tracks(TrackCase):
    def test_desired_field_unrelated_to_resume_is_accepted(self):
        tid = careers.add_track("Hospitality", "desired_field", titles=["Hotel manager"])
        t = careers.get_track(tid)
        self.assertEqual((t["label"], t["intent"], t["tiers"], t["codes"]), ("Hospitality", "desired_field", [0], ["11-9081.00"]))
        self.assertEqual([x["id"] for x in careers.tracks()], [tid])

    def test_validation(self):
        for kw in ({"intent": "nope", "titles": ["x"]}, {"intent": "pivot"}, {"intent": "pivot", "titles": ["x"], "tiers": [7]},
                   {"intent": "pivot", "titles": ["x"], "training": "phd"}, {"intent": "pivot", "titles": ["x"], "priority": "max"}):
            with self.assertRaises(SystemExit):
                careers.add_track("T", **kw)
        with self.assertRaises(SystemExit):
            careers.add_track(" ", "pivot", titles=["x"])
        with self.assertRaises(SystemExit):
            careers.get_track(99999)

    def test_search_titles_respects_tiers(self):
        t = careers.get_track(careers.add_track("H", "desired_field", titles=["Hotel manager"]))
        self.assertEqual(careers.search_titles(t), ["Hotel manager"])
        t = careers.update_track(t["id"], tiers=[0, 1])
        self.assertEqual(careers.search_titles(t), ["Hotel manager", "Lodging Managers", "Hospitality Manager"])

    def test_titles_are_deduped_and_capped(self):
        t = careers.get_track(careers.add_track("M", "desired_field",
                                                titles=["Chef", "chef ", "Cook", "Baker", "Barista", "Server", "Host", "Busser"]))
        self.assertEqual(careers.search_titles(t), ["Chef", "Cook", "Baker", "Barista", "Server", "Host"])

    def test_remove_track_clears_posting_tags(self):
        tid = careers.add_track("H", "desired_field", titles=["Hotel manager"])
        db.con().execute("INSERT INTO postings(key, url, track_id) VALUES ('k1.test', 'https://x.test/1', ?)", (tid,))
        db.con().commit()
        careers.remove_track(tid)
        self.assertIsNone(db.con().execute("SELECT track_id FROM postings WHERE key='k1.test'").fetchone()[0])
        self.assertEqual(careers.tracks(), [])

    def test_suggestions_include_your_tracks_targets(self):
        careers.add_track("Hospitality", "desired_field", titles=["Hotel manager"])
        off = careers.add_track("Nursing", "pivot", titles=["Registered nurse"])
        careers.update_track(off, enabled=False)  # a disabled track is not a target
        got = {s["code"]: s["tier"] for s in careers.suggest(bank=BANK, tiers=(0, 4))["suggestions"]}
        self.assertEqual(got, {"11-9081.00": 0, "43-4081.00": 4})


class TrackSearch(TrackCase):
    def setUp(self):
        super().setUp()
        self._wm = (wm.SOURCES, wm.search, wm.sources_ready)
        wm.SOURCES = {"remotive": None, "adzuna": None}  # pinned: an earlier module may leave it patched
        self.seen = []

    def tearDown(self):
        wm.SOURCES, wm.search, wm.sources_ready = self._wm
        super().tearDown()

    def fake(self, ready=("remotive",), fail=True, results=True):
        wm.sources_ready = lambda: list(ready)

        def search(query, errors=None, ran=None, **f):
            self.seen.append((query, f.get("location")))
            if not ready:
                return []
            ran.append("remotive")
            if fail:
                errors.append("adzuna: HTTP 500")
            if not results:
                return []
            rows = [wm._listing("Hotel Manager", "Inn Co", "https://inn.test/1", source="remotive")]
            listings.store(rows, source="remotive")
            return rows
        wm.search = search

    def test_search_track_chunks_queries_tags_postings_and_reports_coverage(self):
        self.fake()
        tid = careers.add_track("H", "desired_field", titles=["Hotel manager"], tiers=[0, 1], location="Austin, TX")
        out = careers.search_track(tid)
        self.assertEqual(self.seen, [("Hotel manager, Lodging Managers, Hospitality Manager", "Austin, TX")])
        self.assertEqual(out["titles"], ["Hotel manager", "Lodging Managers", "Hospitality Manager"])
        cov = out["coverage"]
        self.assertEqual((cov["asked"], cov["failed"], cov["not_ready"], cov["total"]), (["remotive"], ["adzuna: HTTP 500"], ["adzuna"], 2))
        self.assertTrue(cov["checked"])
        self.assertIn("never searches every job board", cov["note"])
        self.assertEqual([r["url"] for r in out["results"]], ["https://inn.test/1"])
        self.assertEqual(db.con().execute("SELECT track_id FROM postings WHERE url='https://inn.test/1'").fetchone()[0], tid)

    def test_more_titles_than_one_round_are_searched_in_rounds_and_merged(self):
        self.fake(fail=False)
        out = careers.search_track(careers.add_track("M", "desired_field", titles=["Chef", "Cook", "Baker", "Barista"]))
        self.assertEqual([q for q, _ in self.seen], ["Chef, Cook, Baker", "Barista"])
        self.assertEqual(len(out["results"]), 1)  # the same posting from both rounds, once
        self.assertEqual(out["coverage"]["asked"], ["remotive"])

    def test_search_with_no_board_ready_says_nothing_checked(self):
        self.fake(ready=())
        out = careers.search_track(careers.add_track("H", "desired_field", titles=["Hotel manager"]))
        self.assertEqual((out["results"], out["coverage"]["asked"], out["coverage"]["checked"]), ([], [], False))
        self.assertEqual(out["coverage"]["not_ready"], ["remotive", "adzuna"])

    def test_desired_field_searches_with_no_profile(self):
        self.fake(results=False)
        old = profile.BANK
        try:
            profile.BANK = Path(self.tmp) / "empty-profile.json"  # no bank at all
            tid = careers.add_track("Nursing", "desired_field", titles=["Registered nurse"])
            out = careers.search_track(tid)
            self.assertEqual(careers.suggest()["suggestions"][0]["tier"], 0)  # the target is still suggested
        finally:
            profile.BANK = old
        self.assertEqual(self.seen, [("Registered nurse", None)])
        self.assertTrue(out["coverage"]["checked"])


if __name__ == "__main__":
    unittest.main()
