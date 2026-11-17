"""AI help for the job sites you browse yourself (pass 37): one AI call turns your profile (never the salary floor) and
your saved searches into up to 6 searches to run yourself on LinkedIn, Indeed, Glassdoor, ZipRecruiter and SimplyHired,
plus one boolean string for the LinkedIn / Indeed keyword box. Every value is cleaned (no markup, no links, no
duplicates, bounded); the AI never sees those sites and Lodestar never fetches them. No network; patches put back."""
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

from lodestar import ai, pacing, resume  # noqa: E402

REPLY = {"queries": [
    {"query": "Data Engineer", "why": "your current title"},
    {"query": "data engineer", "why": "duplicate"},
    {"query": "<b>Analytics Engineer</b>", "why": "dbt and SQL <script>x</script>"},
    {"query": "https://www.linkedin.com/jobs/view/1", "why": "a link is never a search"},
    {"query": "", "why": "empty"},
    {"query": "ETL Developer", "why": "older title for the same work"},
    {"query": "Platform Data Engineer " + "x" * 200, "why": "long"},
    {"query": "BI Engineer", "why": "1"}, {"query": "Data Integration Engineer", "why": "2"},
    {"query": "Pipeline Engineer", "why": "3"}, {"query": "Seventh Engineer", "why": "over the cap"}],
    "boolean": '("data engineer" OR "analytics engineer") AND (python OR sql) NOT intern <img src=x>'}


class SiteQueries(unittest.TestCase):
    def test_queries_are_cleaned_bounded_and_deduplicated(self):
        asked = {}

        def fake_text(limit, **kw):
            asked.update(kw)
            return "Riley, data engineer, Python, SQL"
        with patched(ai, ask_json=lambda prompt, **k: asked.update(prompt=prompt) or REPLY, available=lambda: ["anthropic"]), \
                patched(resume, candidate_text=fake_text):
            r = pacing.site_queries(level="senior", location="Austin, TX")
        qs = [q["query"] for q in r["queries"]]
        self.assertEqual(qs[:3], ["Data Engineer", "Analytics Engineer", "ETL Developer"])
        self.assertLessEqual(len(qs), 6)
        self.assertNotIn("Seventh Engineer", qs)
        self.assertTrue(all(len(q) <= 80 and "<" not in q and "http" not in q.lower() for q in qs))
        self.assertTrue(all("<" not in q["why"] for q in r["queries"]))
        self.assertEqual(r["boolean"], '("data engineer" OR "analytics engineer") AND (python OR sql) NOT intern')
        self.assertEqual((r["level"], r["location"]), ("senior", "Austin, TX"))
        self.assertIs(asked["private"], False)  # never the salary floor
        self.assertIn("senior", asked["prompt"])
        self.assertNotIn("linkedin.com/jobs", asked["prompt"])  # nothing from the sites themselves

    def test_without_an_ai_provider_it_says_so(self):
        with patched(ai, available=lambda: []):
            with self.assertRaises(SystemExit) as e:
                pacing.site_queries()
        self.assertIn("AI provider", str(e.exception))


if __name__ == "__main__":
    unittest.main()
