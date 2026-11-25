"""Job search fixes from a live run of every keyless board (2026-11-13): Arbeitnow and Himalayas answers are filtered
by the query here (Arbeitnow ignores its search parameter; Himalayas matches loosely), RemoteOK's double-encoded text
('â\\x80\\x94') is repaired, and an HN header whose second field is a link never makes the link the job title.
No network; every patched attribute is put back."""
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

from lodestar import web_monitor as wm  # noqa: E402


def job(title, desc="", **k):
    return {"title": title, "company_name": "Acme", "url": f"https://x/{title}", "description": desc, "tags": []} | k


class LiveFixes(unittest.TestCase):
    def test_arbeitnow_and_himalayas_answers_are_filtered_by_the_query(self):
        arb = {"data": [job("Senior Finance Manager"), job("Software Engineer (m/w/d)"),
                        job("Backend Developer", "You are a software engineer at heart.")]}
        with patched(wm, fetch_json=lambda url, **k: arb):
            self.assertEqual([j["title"] for j in wm._arbeitnow("software engineer")],
                             ["Software Engineer (m/w/d)", "Backend Developer"])
        him = {"jobs": [{"title": "Marketing Manager", "companyName": "B", "applicationLink": "https://h/1"},
                        {"title": "Store Manager", "companyName": "C", "applicationLink": "https://h/2"}]}
        with patched(wm, fetch_json=lambda url, **k: him):
            self.assertEqual([j["title"] for j in wm._himalayas("store manager")], ["Store Manager"])

    def test_double_encoded_text_is_repaired(self):
        got = wm._listing("Senior Engineer â\u0080\u0094 Kubernetes", "CafÃ© Co", "https://x")
        self.assertEqual((got["title"], got["company"]), ("Senior Engineer — Kubernetes", "Café Co"))
        for fine in ("Café Co", "MÜNCHEN - Kundenservice", "Señor Dev — Remote", "Ångström Labs"):
            self.assertEqual(wm._listing(fine, "", "")["title"], fine)

    def test_hn_header_link_is_never_the_title(self):
        story = {"hits": [{"objectID": "50"}]}
        post = {"hits": [{"objectID": "7", "parent_id": "50", "author": "x", "created_at": "2026-11-02",
                          "comment_text": "<p>SentiLink | https://www.sentilink.com/ | Senior Python Engineer | Remote</p>"}]}
        with patched(wm, fetch_json=lambda url, **k: story if "author_whoishiring" in url else post if "page=0" in url
                     else {"hits": []}):
            h, = wm._hn("python")
        self.assertEqual((h["company"], h["title"], h["location"]), ("SentiLink", "Senior Python Engineer", "Remote"))


if __name__ == "__main__":
    unittest.main()
