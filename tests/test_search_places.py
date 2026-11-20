"""Search by place (pass 44): a postal code, city, state or remote; a radius in miles for the boards that search near a
place (USAJOBS Radius in miles, Adzuna distance in km), part of their cache key and kept by saved searches. A listing
from a board that searched near the place passes the place filter (Round Rock for Austin, anything for a ZIP); the
other boards are matched on their listing text. No network; every patched attribute is put back."""
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

from lodestar import db, web, web_monitor as wm  # noqa: E402


def listing(loc, source):
    return {"title": "Registered Nurse", "company": "Acme Health", "location": loc, "desc": "Care for patients.",
            "source": source, "url": f"https://x.example/{source}/{loc}", "date": "", "salary": ""}


class Places(unittest.TestCase):
    def test_radius_is_a_validated_filter_saved_searches_keep(self):
        self.assertEqual(wm.clean_filters(location="78701", radius="25"), {"location": "78701", "radius": 25})
        for bad in ("0", "500", "ten"):
            with self.assertRaises(SystemExit):
                wm.clean_filters(radius=bad)
        self.assertIn("radius", web.FILTER_KEYS)

    def test_a_postal_code_keeps_what_the_local_boards_found_near_it(self):
        rows = [listing("Austin, Texas", "usajobs"), listing("Austin, TX", "remotive"), listing("Austin, TX 78701", "hn"),
                listing("Denver, CO", "hn")]
        got = wm.refine(rows, "", location="78701")
        self.assertEqual([(j["source"], j["location"]) for j in got], [("usajobs", "Austin, Texas"), ("hn", "Austin, TX 78701")])

    def test_a_city_keeps_the_local_boards_nearby_towns_and_text_matches_elsewhere(self):
        rows = [listing("Round Rock, Texas", "usajobs"), listing("Round Rock, TX", "hn"), listing("Austin, TX", "hn"),
                listing("Dallas, TX", "hn")]
        got = wm.refine(rows, "", location="Austin, TX")
        self.assertEqual([(j["source"], j["location"]) for j in got], [("usajobs", "Round Rock, Texas"), ("hn", "Austin, TX")])
        self.assertEqual(len(wm.refine(rows, "", location="TX")), 4)  # a state: every listing in it

    def test_the_radius_reaches_the_local_boards_and_their_cache(self):
        urls = []
        # an earlier module may leave SOURCES patched (CLAUDE.md > Sources): pin the two local boards
        pin = patched(wm, SOURCES={"usajobs": wm._usajobs, "adzuna": wm._adzuna})
        pin.__enter__()
        self.addCleanup(pin.__exit__, None, None, None)
        with patched(wm, fetch_json=lambda url, **k: urls.append(url) or {"SearchResult": {"SearchResultItems": []}}):
            wm._ANSWERS.clear()
            wm._ask("usajobs", "nurse", False, "78701", 10)
            wm._ask("usajobs", "nurse", False, "78701", 50)
            wm._ask("usajobs", "nurse", False, "78701", 50)  # same radius: a fresh manual search asks again too
        self.assertIn("LocationName=78701&Radius=10", urls[0])
        self.assertIn("Radius=50", urls[1])
        self.assertEqual(wm._RUN.where, "")
        self.assertIsNone(getattr(wm._RUN, "radius", None))
        with patched(wm, fetch_json=lambda url, **k: urls.append(url) or {"results": []}), \
                patched(db, quota=lambda *a, **k: True):
            wm._ask("adzuna", "nurse", False, "Austin, TX", 50)
        self.assertIn("&distance=80", urls[-1])  # 50 miles in km
        seen = []
        with patched(wm, _ask=lambda name, q, scheduled, where="", radius=None: seen.append((name, where, radius)) or [],
                     sources_ready=lambda: ["usajobs", "hn"]):
            wm.search("nurse", location="78701", radius=10, sources=["usajobs", "hn"])
        self.assertIn(("usajobs", "78701", 10), seen)
        self.assertIn(("hn", "78701", 10), seen)  # _ask itself keeps place and radius only for the local boards


if __name__ == "__main__":
    unittest.main()
