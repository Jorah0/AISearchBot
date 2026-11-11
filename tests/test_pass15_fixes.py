"""Pass 15 review fixes: bullet tailoring from .docx/.pdf bases, role-safe reordering, invented-skill and Preferences
guards, coverage kept apart from the gap check, salary ranges, hybrid cloud, quiet field writes, export of a missing file."""
import io
import json
import os
import sys
import tempfile
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, db, profile, resume  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402
from test_pass15_bullets import MASTER, Base  # noqa: E402

BOLD_ROLES = """# Master Resume
Jane Doe | Austin, TX | jane@example.com | +1 512 555 0100

## Experience
**Engineer**, Acme
- A1 at Acme
- A2 at Acme
**Analyst**, Beta
- B1 at Beta
"""


class BulletFixes(Base):
    def reply(self, **r):
        ai.ask_json = lambda p, *a, **k: self.prompts.append(p) or json.loads(json.dumps(r))

    def test_docx_base_keeps_headings_and_bullets(self):  # F1
        from docx import Document
        d = Document(); d.add_paragraph("Jane Doe"); d.add_paragraph("jane@example.com | +1 512 555 0100")
        d.add_heading("Experience", 1); d.add_heading("Engineer - Acme", 2)
        d.add_paragraph("Cut deploy time 40%", style="List Bullet"); d.add_paragraph("Built CI in Python", style="List Bullet")
        d.add_heading("Analyst - Beta", 2); d.add_paragraph("Wrote SQL reports", style="List Bullet")
        buf = io.BytesIO(); d.save(buf)
        rid = profile.import_file(buf.getvalue(), "cv.docx", use_ai=False)["resume"]["id"]
        self.reply(bullets=[], order=[])
        rows = resume.tailor_bullets(self.job(), base=rid)["proposals"]
        self.assertEqual([(r["role"], r["original"]) for r in rows],
                         [("Engineer - Acme", "Cut deploy time 40%"), ("Engineer - Acme", "Built CI in Python"), ("Analyst - Beta", "Wrote SQL reports")])
        pdf_like = "Jane Doe\nEXPERIENCE\nEngineer - Acme\n• Cut deploy time 40%\nSkills\n• Python"  # bare headings, PDF glyphs
        self.assertEqual([b["original"] for b in resume._bullets(pdf_like)], ["Cut deploy time 40%"])

    def test_bold_line_roles_never_trade_bullets(self):  # F2
        PROFILE.write_text(BOLD_ROLES, encoding="utf-8")
        self.reply(bullets=[], order=[3, 1, 2])
        j = self.job()
        rows = resume.tailor_bullets(j)["proposals"]
        self.assertEqual(len({r["group"] for r in rows}), 2)
        resume.apply_bullets(db.get_job(j["id"]), "all")
        md = (resume.app_dir(j) / "resume.md").read_text(encoding="utf-8")
        self.assertIn("**Engineer**, Acme\n- A1 at Acme\n- A2 at Acme\n**Analyst**, Beta\n- B1 at Beta", md)

    def test_an_invented_skill_outside_the_posting_is_flagged(self):  # SEC-1
        self.reply(bullets=[{"id": 1, "proposed": "Built data pipelines in Python and SQL on AWS with Terraform that cut compute costs 30%",
                             "added_terms": []}], order=[])
        r = resume.tailor_bullets(self.job())["proposals"]
        row = next(x for x in r if x["id"] == 1)
        self.assertEqual((row["unsupported"], row["flags"], row["accepted"]), (["terraform"], ["unsupported"], False))
        self.assertTrue(row["marks"])

    def test_preferences_at_any_level_never_reach_the_employer(self):  # SEC-2
        for head in ("# Preferences", "### Preferences", "## PREFERENCES"):
            PROFILE.write_text(MASTER.replace("## Preferences", head) + "## Education\n- BSc\n", encoding="utf-8")
            text = resume.candidate_text(private=False)
            self.assertNotIn("187k", text, head); self.assertIn("BSc", text, head)
            self.assertIn("187k", profile.preferences_text(), head)
        with self.assertRaises(SystemExit):
            resume._employer_copy("# Jane\nSalary floor: 150k\n")

    def test_export_of_a_missing_resume_is_a_message(self):  # F7
        with self.assertRaises(SystemExit):
            resume.export_docx(resume.app_dir(self.job()) / "resume.md")


class CoverageFixes(Base):
    def test_coverage_is_not_a_gap_check(self):  # F3
        j = self.job()
        resume.coverage(j)
        d = resume.app_dir(j)
        self.assertTrue((d / "coverage.json").is_file()); self.assertFalse((d / "gap.json").is_file())
        self.assertFalse(next(c for c in apply.checklist(db.get_job(j["id"])) if c["item"] == "Fit checked")["done"])
        (d / "gap.json").write_text(json.dumps({"verdict": "stretch", "missing_keywords": ["old"], "weak_areas": ["x"]}), encoding="utf-8")
        cov = resume.coverage(db.get_job(j["id"]))
        g = json.loads((d / "gap.json").read_text(encoding="utf-8"))
        self.assertEqual((g["verdict"], g["weak_areas"], g["match_score"]), ("stretch", ["x"], cov["score"]))
        self.assertNotIn("old", g["missing_keywords"]); self.assertIn("snowflake", g["missing_keywords"])
        self.assertTrue(next(c for c in apply.checklist(db.get_job(j["id"])) if c["item"] == "Fit checked")["done"])

    def test_field_writes_are_not_activity(self):  # F6 / ui-4
        j = self.job()
        db._local.con.execute("UPDATE jobs SET updated_at='2020-01-01 00:00:00' WHERE id=?", (j["id"],))
        db.set_fields(j["id"], tags="chase")
        db.toggle_ats_skip(j["id"], "dbt")
        resume.coverage(db.get_job(j["id"]))
        self.assertEqual(db.get_job(j["id"])["updated_at"], "2020-01-01 00:00:00")
        db.set_status(j["id"], "applied")
        self.assertNotEqual(db.get_job(j["id"])["updated_at"], "2020-01-01 00:00:00")


class ParseFixes(unittest.TestCase):
    def test_k_covers_both_ends_of_a_range(self):  # F4
        self.assertEqual(resume.parse_salary("Pay: $120-150k DOE"), {"salary_min": 120000, "salary_max": 150000, "currency": "USD"})
        self.assertEqual(resume.parse_salary("$80-100k")["salary_min"], 80000)
        self.assertEqual(resume.parse_salary("$50 - $70 an hour"), {})

    def test_hybrid_cloud_is_not_a_workplace(self):  # F5
        self.assertEqual(db.remote_kind("Fully remote role. Experience with hybrid cloud (AWS + on-prem) required."), "remote")
        self.assertEqual(db.remote_kind("Hybrid role in Berlin, 3 days in office"), "hybrid")
        self.assertEqual(db.remote_kind("We offer a hybrid work schedule"), "hybrid")


if __name__ == "__main__":
    unittest.main()
