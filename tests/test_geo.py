"""The Board's map (pass 53): offline place lookup (cities, ZIP codes, state names), miles, remote and unplaced jobs
kept apart, home from the search profile place. No network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import db, geo, web_monitor  # noqa: E402


class Geo(unittest.TestCase):
    def test_locate_cities_zips_and_state_names(self):
        self.assertEqual(geo.locate("Austin, TX")[2], "Austin, TX")
        self.assertEqual(geo.locate("Portland, OR (hybrid)")[2], "Portland, OR")
        self.assertEqual(geo.locate("New York, New York")[2], "New York, NY")
        self.assertEqual(geo.locate("St. Louis, MO")[2], "St. Louis, MO")
        self.assertEqual(geo.locate("Austin, TX 78701")[2], "78701")
        for none in ("Remote (US)", "Paris, France", "", None, "Springfield"):
            self.assertIsNone(geo.locate(none), none)

    def test_miles(self):
        self.assertAlmostEqual(geo.miles(geo.locate("Austin, TX"), geo.locate("Dallas, TX")), 182, delta=8)
        self.assertEqual(geo.miles((1, 1), (1, 1)), 0)

    def test_board_map_sorts_by_miles_and_keeps_remote_apart(self):
        made = [db.add_job("Fennel Co", "A", "https://f.example/1", "", "test", location="Dallas, TX"),
                db.add_job("Juniper Co", "B", "https://j.example/1", "", "test", location="Round Rock, TX"),
                db.add_job("Nutmeg Co", "C", "https://n.example/1", "", "test", location="Remote (US)"),
                db.add_job("Sorrel Co", "D", "https://s.example/1", "", "test", location="Berlin, Germany")]
        self.addCleanup(lambda: [db.delete_job(j) for j in made])
        with patched(web_monitor, defaults=lambda: {"location": "Austin, TX"}):
            m = geo.board_map()
        mine = [r["company"] for r in m["jobs"] if r["id"] in made]
        self.assertEqual(mine, ["Juniper Co", "Fennel Co"])
        self.assertEqual(m["home"]["label"], "Austin, TX")
        self.assertIn("Nutmeg Co", [r["company"] for r in m["remote"]])
        self.assertIn("Sorrel Co", [r["company"] for r in m["unplaced"]])
        self.assertIn("Census", m["source"])


if __name__ == "__main__":
    unittest.main()
