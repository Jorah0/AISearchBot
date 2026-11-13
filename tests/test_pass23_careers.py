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

from lodestar import occupations  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
