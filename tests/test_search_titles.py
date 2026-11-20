"""Search terms from resume titles (pass 42; found by a real search that returned 0 listings): without Target roles the
Jobs tab searched 'Software Engineer (Frontend / Full-Stack)' word for word and no board matched it. Resume titles now
become board searches: the bracketed specialty and level words go (the seniority filter carries the level), each title
once. Target roles you typed stay exactly as written. No network; every patched attribute is put back."""
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

from lodestar import ai, ats, fit, profile, web_monitor  # noqa: E402

RESUME = ["Software Engineer (Frontend / Full-Stack)", "Student Software Engineer (AI / Systems)", "Web Development Intern"]


class Titles(unittest.TestCase):
    def test_brackets_and_level_words_go_and_each_title_once(self):
        self.assertEqual(web_monitor.search_titles(RESUME), ["Software Engineer", "Web Development"])
        self.assertEqual(web_monitor.search_titles(["Sr. Data Engineer [Payments]", "Junior QA Analyst - Contract",
                                                     "Lead Nurse", "(Intern)"]),
                         ["Data Engineer", "QA Analyst", "Lead Nurse"])  # lead changes the role: it stays

    def test_the_jobs_tab_query_from_the_resume_is_searchable(self):
        doc = {"experience": [{"title": t} for t in RESUME], "contact": {"location": "Remote (US)"}}
        with patched(profile, preferences_text=lambda: "", structured=lambda employer=False: doc):
            d = web_monitor.defaults()
        self.assertEqual(d["query"], "Software Engineer, Web Development")
        self.assertEqual(d["roles_from"], "your resume")

    def test_target_roles_you_typed_stay_as_written(self):
        prefs = "Target roles: Software Engineer (Frontend) | Locations / remote: Remote"
        with patched(profile, preferences_text=lambda: prefs):
            self.assertEqual(web_monitor.defaults()["query"], "Software Engineer (Frontend)")


class LocalModel(unittest.TestCase):  # the same real run: the Ollama preset had pinned codellama for every prompt
    def test_the_picker_skips_code_and_embedding_models(self):
        tags = ["phi3:latest", "qwen2.5-coder:32b", "nomic-embed-text:latest", "codellama:latest", "llama3.2:latest"]
        self.assertEqual(ai.pick_from("ollama", tags), "llama3.2:latest")
        self.assertEqual(ai.pick_from("ollama", ["codellama:latest", "qwen3-coder:30b"]), "codellama:latest")  # only those


class HnSeekers(unittest.TestCase):  # the same real run: job seekers' own posts in the hiring thread came back as jobs
    def test_seeker_posts_in_the_hiring_thread_are_not_listings(self):
        def post(i, html):
            return {"objectID": str(i), "parent_id": "50", "author": f"u{i}", "created_at": "2026-11-03T10:00:00Z",
                    "comment_text": html}
        pages = {"author_whoishiring": {"hits": [{"objectID": "50"}]}, "story_50": {"hits": [
            post(1, "<p>Acme | Software Engineer | Remote (US)</p><p>We build widgets in Python.</p>"),
            post(2, "<p>Location: Bangalore, India</p><p>Remote: Yes</p><p>Willing to relocate: Yes</p>"
                    "<p>Technologies: Python, React</p><p>R&eacute;sum&eacute;/CV: https://x.example/cv</p><p>Email: a@x</p>"),
            post(3, "<p>I'm Sam Doe, a Software Engineer focused on Python and React. I'm actively looking for "
                    "full-time roles.</p>"),
            post(4, "<p>I'm the CTO at Globex and we're hiring a Python engineer | Remote</p>"),
            post(5, "<p>Location: Lisbon</p><p>Initrode | Python Backend | Lisbon / Remote</p>")]}}
        with patched(web_monitor, fetch_json=lambda url, **k: next(v for key, v in pages.items() if key in url)):
            got = [j["url"].rsplit("=", 1)[1] for j in web_monitor._hn("python")]
        self.assertEqual(got, ["1", "4", "5"])


class SkillsChip(unittest.TestCase):  # the same real run: '1 of 1 required skills' carried a minus sign
    def test_the_required_chip_signs_the_required_skills_it_names(self):
        kws = [{"term": "python", "kind": "hard", "matched": True, "skipped": False}] + [
            {"term": f"soft{i}", "kind": "soft", "matched": False, "skipped": False} for i in range(6)]
        x = {"title": "Software Engineer", "company": "Acme", "desc": "word " * 60}
        with patched(ats, match=lambda *a, **k: {"keywords": kws}, split_nice=lambda jd, h: (jd, "")):
            s, chips, _ = fit._skills(x, {"resume": "Python"})
        self.assertLess(s, 40)  # the overall keyword score is low (soft words missing) ...
        self.assertEqual(chips[0], ("+", "1 of 1 required skills"))  # ... but every required skill is there


class RemoteRegion(unittest.TestCase):  # live run: 'Remote (US)' (the profile's place) dropped every remote listing
    def listing(self, loc, source="remotive"):
        return {"title": "Software Engineer", "company": "Acme", "location": loc, "desc": "Build things.", "source": source,
                "url": f"https://x.example/{loc}", "date": "", "salary": ""}

    def test_the_ways_people_write_remote_in_a_region(self):
        for s in ("Remote (US)", "Remote - USA", "Remote, United States", "US Remote", "USA (Remote)", "Remote in the US"):
            self.assertEqual(web_monitor._loc_alts(s), ["remote:" + s.replace("Remote", "").replace("remote", "")
                                                        .strip(" -,()").removeprefix("in the ").strip()], s)
        self.assertEqual(web_monitor._loc_alts("remote"), ["remote"])
        self.assertEqual(web_monitor._loc_alts("Austin, TX or Remote (US)"), ["Austin, TX", "remote:US"])
        self.assertEqual(web_monitor._where("Remote (US) or Austin, TX"), "Austin, TX")  # a local board searches a place

    def test_remote_us_keeps_us_and_worldwide_remote_jobs_and_drops_other_regions(self):
        keep = ["USA Only", "United States", "LATAM, Europe, USA, Canada, AP", "USA, Canada, USA timezones", "Worldwide",
                "Anywhere in the World", "Remote", "North America", ""]
        drop = ["Latin America Only", "Pakistan", "Germany", "Europe"]
        got = web_monitor.refine([self.listing(x) for x in keep + drop], "", location="Remote (US)")
        self.assertEqual(sorted(j["location"] for j in got), sorted(keep))

    def test_an_onsite_job_in_the_region_is_not_remote(self):
        onsite = self.listing("Dahlgren, Virginia", source="usajobs")
        self.assertEqual(web_monitor.refine([onsite], "", location="Remote (US)"), [])


if __name__ == "__main__":
    unittest.main()
