"""Search seniority and keywords (pass 34): a title's level reads numbered levels (I / II / III / IV, 1-4, not a support
'Tier'), working-student roles, C-level titles, 'Associate' and 'Early-career' starts and 'Supervisor'; the Jobs tab
starts from your target level (Preferences, else your years as a suggestion); must-have keywords match whole words.
No network; every patched attribute and preference is put back."""
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

from lodestar import settings  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402

LEVELS = {
    "Patient Advocate I": "junior", "Software Engineer 1": "junior", "Data Analyst II": "mid",
    "Software Development Engineer in Test II, NavNative": "mid", "Software Engineer III": "senior",
    "Software Engineer III (Backend)": "senior", "Engineer IV - Platform": "staff", "Senior Software Engineer II": "senior",
    "Tier III Service Desk Engineer": "mid", "Helpdesk Technician Tier 1": "mid",
    "I'm Rajneesh, a Full-Stack Engineer": "mid", "NYC + Toronto (most roles require 2+ days in office)": "mid",
    "Customer Support (Working Student) (m/f/d)": "intern", "Werkstudent:in Community Management (m/w/d)": "intern",
    "Social Media Manager (Working Student) // AI Music Video Platform": "intern", "Praktikant Marketing": "intern",
    "COO — founder-level role": "manager", "CTO": "manager", "Chief Financial Officer, Interim": "manager",
    "Associate AI Deployment Strategist": "junior", "Associate Product Manager": "junior",
    "Associate Director, Business Development (US-Based)": "manager",
    "Early-Career AI Engineers – Full-Stack": "junior", "Entry Level Analyst": "junior", "Supervisor, UK Payroll": "lead",
    # unchanged readings
    "Coding Consultant Outpatient - Sign On Bonus - $1,000/$1,500": "mid", "/^Full-?stack Engineer$/i": "mid",
    "Engineering Technician II": "mid", "Engineer I/II": "junior",
    "Senior Engineering Manager": "manager", "Staff Engineer": "staff", "Data Engineer": "mid", "Product Manager": "mid",
    "Sr. Data Engineer": "senior", "Team Lead, Support": "lead", "Software Engineering Intern": "intern",
}


def L(title, desc=""):
    return {"title": title, "company": "Acme", "url": f"https://x/{title}", "location": "", "salary": "", "date": "",
            "desc": desc, "source": "test"}


class Levels(unittest.TestCase):
    def test_titles_read_to_the_right_level(self):
        got = {t: wm.seniority_of(t) for t in LEVELS}
        self.assertEqual({t: g for t, g in got.items() if g != LEVELS[t]}, {})

    def test_the_seniority_filter_keeps_only_that_level(self):
        rows = [L("Software Engineer III"), L("Software Engineer II"), L("Senior Data Engineer")]
        self.assertEqual([j["title"] for j in wm.refine(rows, seniority="senior")], ["Software Engineer III", "Senior Data Engineer"])

    def test_keywords_match_whole_words(self):
        rows = [L("Digital Marketing Lead", "Laws and access."), L("Platform Engineer", "We use Git and AWS daily.")]
        self.assertEqual([j["title"] for j in wm.refine(rows, keywords="git, aws, css")], ["Platform Engineer"])
        self.assertEqual([j["title"] for j in wm.refine(rows, keywords="digital marketing")], ["Digital Marketing Lead"])

    def test_the_jobs_tab_starts_from_your_target_level(self):
        old = settings.pref("target_seniority")
        try:
            settings.set_pref("target_seniority", "senior")
            d = wm.defaults()
            self.assertEqual((d["seniority"], d["seniority_from"]), ("senior", "Preferences"))
            settings.set_pref("target_seniority", "")
            with patched(wm, _years=lambda: 3.5):
                d = wm.defaults()
            self.assertEqual((d["seniority"], d["seniority_from"]), ("mid", "your experience (3.5 years)"))
        finally:
            settings.set_pref("target_seniority", old or "")


class Coverage(unittest.TestCase):
    def test_a_ready_board_that_was_not_asked_is_named(self):
        from lodestar import careers

        with patched(wm, sources_ready=lambda: ["remotive", "jobicy", "wwr"],
                     SOURCES={n: (lambda q: []) for n in ("remotive", "jobicy", "wwr", "adzuna")}):  # pinned
            c = careers.coverage(["remotive", "jobicy"], ["jobicy: HTTP 500"])
        self.assertEqual(c["skipped"], ["wwr"])  # asked too recently by another search: said, never silent
        self.assertEqual(c["asked"], ["remotive", "jobicy"])


if __name__ == "__main__":
    unittest.main()
