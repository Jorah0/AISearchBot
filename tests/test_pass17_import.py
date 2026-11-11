"""Pass 17, builder 1: full trait import into the profile bank. Schema v2 (every resume section, evidence quotes, a v1
bank loads unchanged), offline parsing of common layouts with line coverage, AI parsing checked against the file
(verify), personal data dropped before any parser or AI sees it, the import review (stage / diff / apply / discard /
re-read), facts written into profile.md, and the POST /api/profile stale-base guard."""
import base64
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, cli, profile, studio  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Master Resume
## Contact
Dana Smith | Austin, TX | dana@example.com | +1 512 555 0101

## Summary
Data engineer who ships.

## Work History
### Senior Engineer - Acme Corp (2021-03 - Present)
- Cut deploy time 40%

## Education
BSc Computer Science, UT Austin, 2018

## Preferences
Salary floor: $150,000 | Deal-breakers: on-call
"""
PLAIN = """DANA SMITH
Senior Data Engineer
Austin, TX | dana@example.com | (512) 555-0101 | https://dana.dev

EXPERIENCE
Senior Data Engineer | Acme Corp | Austin, TX | Mar 2021 - Present
• Cut deploy time 40%
Globex Inc
Engineer
2018 - 2021
- Built the billing pipeline
Data Analyst at Initech, 2016 -
- Wrote SQL reports

EDUCATION
BS Computer Science, University of Texas at Austin, 2016

CERTIFICATIONS
AWS Certified Data Engineer - Amazon Web Services (2023) ID: ABC123

AWARDS
Hackathon winner - PyData (2019)

PUBLICATIONS
Streaming at scale - VLDB (2020) | https://doi.example/1

VOLUNTEER WORK
Mentor, Code2040 (2019 - Present)
- Mentored six students

PATENTS
Method for deduplicating events - US 11111111 (2021)

SPEAKING
Kafka in practice - PyCon (2019)

LINKS
Blog: https://blog.dana.dev

INTERESTS
Climbing, Chess

SECURITY CLEARANCE
Secret (active)
"""


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


class Base(unittest.TestCase):
    """A known profile.md, an empty bank, no pending imports; all put back afterwards."""

    def setUp(self):
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        shutil.rmtree(profile.IMPORTS, ignore_errors=True)
        self.auto = studio.AUTO
        studio.AUTO = False

    def tearDown(self):
        studio.AUTO = self.auto
        shutil.rmtree(profile.IMPORTS, ignore_errors=True)
        for p in (PROFILE, profile.BANK):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def seed_bank(self):
        bank = profile.load()
        profile.merge(bank, profile.extract_heuristic(MASTER), "profile.md")
        profile.save(bank)
        return bank

    def snaps(self):
        return sorted(profile.HISTORY.glob("profile-*.md"))


class Parse(Base):
    def test_plain_text_role_blocks_pipe_dash_two_line_and_at(self):
        f = profile.extract_heuristic(PLAIN)
        roles = [(e["title"], e["company"], e["location"], e["start"], e["end"], e["bullets"]) for e in f["experience"]]
        self.assertEqual(roles[0], ("Senior Data Engineer", "Acme Corp", "Austin, TX", "Mar 2021", "Present",
                                    ["Cut deploy time 40%"]))
        self.assertEqual(roles[1], ("Engineer", "Globex Inc", "", "2018", "2021", ["Built the billing pipeline"]))
        self.assertEqual(roles[2][:2], ("Data Analyst", "Initech"))
        self.assertEqual((f["contact"]["name"], f["contact"]["headline"], f["contact"]["website"]),
                         ("DANA SMITH", "Senior Data Engineer", "https://dana.dev"))
        f = profile.extract_heuristic("## Experience\nSenior Engineer, Acme Corp (2020 - 2022)\n- Shipped it\n")
        self.assertEqual((f["experience"][0]["title"], f["experience"][0]["company"]), ("Senior Engineer", "Acme Corp"))

    def test_dangling_end_stays_empty_and_low_confidence(self):
        e = profile.extract_heuristic(PLAIN)["experience"][2]
        self.assertEqual((e["start"], e["end"], e.get("confidence")), ("2016", "", "low"))  # never an invented 'Present'
        e = profile.extract_heuristic("## Experience\nAnalyst | Initech | 2016 - present\n- x\n")["experience"][0]
        self.assertEqual(e["end"], "Present")

    def test_education_certification_and_list_kinds(self):
        f = profile.extract_heuristic(PLAIN)
        self.assertEqual(f["education"][0], {"school": "University of Texas at Austin", "degree": "BS",
                                             "field": "Computer Science", "end": "2016"})
        self.assertEqual(f["certifications"][0], {"name": "AWS Certified Data Engineer", "issuer": "Amazon Web Services",
                                                  "date": "2023", "credential_id": "ABC123"})
        self.assertEqual(f["awards"][0], {"name": "Hackathon winner", "issuer": "PyData", "date": "2019"})
        self.assertEqual(f["publications"][0], {"title": "Streaming at scale", "venue": "VLDB", "date": "2020",
                                                "url": "https://doi.example/1"})
        self.assertEqual((f["volunteering"][0]["role"], f["volunteering"][0]["organization"], f["volunteering"][0]["end"]),
                         ("Mentor", "Code2040", "Present"))
        self.assertEqual(f["patents"][0]["number"], "US 11111111")
        self.assertEqual(f["speaking"][0], {"title": "Kafka in practice", "event": "PyCon", "date": "2019"})
        self.assertEqual(f["links"], [{"label": "Blog", "url": "https://blog.dana.dev"}])
        self.assertEqual([i["name"] for i in f["interests"]], ["Climbing", "Chess"])
        self.assertEqual(profile.extract_heuristic("## Certifications\n- CKA (2021)\n")["certifications"], [{"name": "CKA (2021)"}])

    def test_unknown_heading_is_other_and_unread_lines_are_reported(self):
        f = profile.extract_heuristic(PLAIN, coverage=True)
        self.assertEqual(f["other"][0]["heading"], "SECURITY CLEARANCE")
        self.assertEqual(f["other"][0]["bullets"], ["Secret (active)"])
        self.assertEqual(f["unread"], [])
        self.assertEqual(f["experience"][0]["quote"], "Senior Data Engineer | Acme Corp | Austin, TX | Mar 2021 - Present")
        f = profile.extract_heuristic("# Dana\ndana@example.com\n## Experience\n### Engineer - Acme (2020 - 2021)\n"
                                      "A line that is no bullet\n- Built X\n", coverage=True)
        self.assertEqual([u["text"] for u in f["unread"]], ["A line that is no bullet"])

    def test_round_trip_keeps_every_fact(self):
        bank = profile.empty()
        profile.merge(bank, {
            "contact": {"name": "Dana Smith", "headline": "Senior Data Engineer", "email": "dana@example.com",
                        "phone": "+1 512 555 0101", "location": "Austin, TX", "linkedin": "https://www.linkedin.com/in/dana",
                        "github": "https://github.com/dana", "website": "https://dana.dev"},
            "summary": "I build data platforms that teams trust.",
            "skills": [{"name": "Python", "category": "Languages"}, {"name": "Spark", "category": "Data"}],
            "languages": [{"name": "Spanish", "proficiency": "Native"}],
            "experience": [{"title": "Senior Data Engineer", "company": "Acme Corp", "location": "Austin, TX", "start": "2021-03",
                            "end": "Present", "bullets": ["Cut deploy time 40%"], "technologies": ["Python", "Spark"]}],
            "education": [{"school": "University of Texas at Austin", "degree": "BS", "field": "Computer Science",
                           "start": "2012", "end": "2016", "honors": "Magna cum laude", "location": "Austin, TX"}],
            "certifications": [{"name": "AWS Certified Solutions Architect - Associate", "issuer": "Amazon Web Services",
                                "date": "2023", "credential_id": "ABC123", "expires": "2026", "url": "https://aws.example/c"},
                               {"name": "CKA"}],
            "projects": [{"name": "pgsnap", "description": "schema snapshots", "url": "https://github.com/dana/pgsnap",
                          "bullets": ["300 stars"], "technologies": ["Python"], "start": "2020", "end": "2021"}],
            "awards": [{"name": "Employee of the Year", "issuer": "Acme Corp", "date": "2022", "description": "for the move"}],
            "publications": [{"title": "Streaming at scale", "venue": "VLDB", "date": "2020", "url": "https://doi.example/1",
                              "authors": "D. Smith, J. Doe"}],
            "volunteering": [{"role": "Mentor", "organization": "Code2040", "location": "Remote", "start": "2019",
                              "end": "Present", "bullets": ["Mentored 6 students"]}],
            "patents": [{"title": "Method for deduplicating events", "number": "US 11,111,111", "date": "2021",
                         "url": "https://patents.example/1"}],
            "speaking": [{"title": "Kafka in practice", "event": "PyCon", "date": "2019", "url": "https://pycon.example/t"}],
            "links": [{"label": "Blog", "url": "https://blog.dana.dev"}],
            "interests": [{"name": "Climbing"}],
            "other": [{"heading": "Security Clearance", "bullets": ["Secret (active)"]}]}, "t")
        facts = profile.extract_heuristic(profile.render_markdown(bank, ""), coverage=True)
        self.assertEqual(facts["unread"], [])
        again = profile.empty()
        profile.merge(again, facts, "t")
        for kind in ("contact", "summary", *profile.FIELDS):
            want, got = bank[kind], again[kind]
            if isinstance(want, list):
                want, got = [profile._bare(x) for x in want], [profile._bare(x) for x in got]
            self.assertEqual(got, want, kind)


class Personal(Base):
    def test_personal_data_is_dropped_before_the_ai_sees_it(self):
        text = ("Dana Smith\nDate of Birth: 1990-01-01\nMarital status: married\nNationality: French\n"
                "dana@example.com | +1 512 555 0101\n\nSkills\nPython, SQL\n\nReferences\nJohn Ref, john@ref.example\n")
        prompts = []

        def fake(prompt, system=None, provider=None, **kw):
            prompts.append(prompt)
            return {"contact": {"name": "Dana Smith"}, "skills": [{"name": "Python"}]}
        with patched(ai, ask_json=fake):
            p = profile.stage_import(text.encode(), "dana.txt", use_ai=True)
        for secret in ("1990-01-01", "married", "French", "John Ref"):
            self.assertNotIn(secret, prompts[0])
        self.assertEqual([d["label"] for d in p["dropped"]], ["date of birth", "marital status", "nationality",
                                                              "references (other people's contact details)"])
        self.assertNotIn("1990", json.dumps(p["dropped"]))  # labels and line numbers, never the values
        self.assertNotIn("1990-01-01", json.dumps(p["items"]))
        buf = io.BytesIO()
        import docx
        d = docx.Document()
        d.add_paragraph("Dana Smith")
        d.add_paragraph("Date of birth: 1990-01-01")
        d.add_paragraph("Skills: Python")
        d.save(buf)
        z = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as src, zipfile.ZipFile(z, "w") as out:
            for n in src.namelist():
                out.writestr(n, src.read(n))
            out.writestr("word/media/image1.png", b"\x89PNG fake")
        p = profile.stage_import(z.getvalue(), "dana.docx", use_ai=False)
        self.assertIn({"label": "photo or image"}, p["dropped"])
        txt = profile.RESUMES / p["resume"]["file"].replace(".docx", ".txt")
        self.assertNotIn("1990-01-01", txt.read_text(encoding="utf-8"))  # the .txt beside the original is redacted

    def test_label_only_line_drops_the_value_under_it_and_pay_and_preferences_never_stage(self):
        clean, dropped = profile.redact_personal("Dana\nDate of Birth\n01.01.1990\nPython developer\n"
                                                 "Salary expectations: $120k\n## Preferences\nSalary floor: 150k\n")
        self.assertNotIn("1990", clean)
        self.assertNotIn("120k", clean)
        self.assertNotIn("150k", clean)
        self.assertIn("Python developer", clean)
        self.assertIn("pay", [d["label"] for d in dropped])
        p = profile.stage_import(b"Dana\nSalary expectations: $120k\n## Skills\nPython\n## Preferences\nSalary floor: 150k\n",
                                 "pay.md", use_ai=False)
        self.assertNotIn("120k", json.dumps(p["items"]))
        self.assertNotIn("150k", json.dumps(p["items"]))
        self.assertIsNone(profile.personal_label("- Pay-per-click campaigns for 12 clients"))  # not a pay line

    def test_saved_text_of_an_old_txt_original_is_redacted(self):
        bank = profile.load()
        profile.RESUMES.mkdir(parents=True, exist_ok=True)
        (profile.RESUMES / "old-dob.txt").write_text("Dana\nDOB: 1990-01-01\nSkills: Python\n", encoding="utf-8")
        bank["resumes"].append({"id": "0ld0ld00", "name": "old.txt", "source": "resume", "added": "2026-01-01", "sha": "x",
                                "chars": 10, "file": "old-dob.txt"})
        profile.save(bank)
        text = profile.saved_text("0ld0ld00")
        self.assertNotIn("1990", text)
        self.assertIn("Skills: Python", text)
        (profile.RESUMES / "old-dob.txt").unlink()


class Verify(Base):
    def reply(self, **kw):
        return {"contact": {"name": "Dana Smith", "email": "dana@example.com"}, "summary": "", "skills": [],
                "experience": [], **kw}

    def test_ai_company_not_in_file_is_flagged_and_unchecked(self):
        text = "Dana Smith\ndana@example.com\n## Experience\nEngineer at Acme Corp (2020 - 2022)\n- Built pipelines\n"
        reply = self.reply(experience=[{"title": "Engineer", "company": "Globex Inc", "start": "2020", "end": "2022",
                                        "bullets": ["Built pipelines"], "quote": "Engineer at Acme Corp (2020 - 2022)"}])
        with patched(ai, ask_json=lambda *a, **k: reply):
            p = profile.stage_import(text.encode(), "v.txt", use_ai=True)
        it = next(i for i in p["items"] if i["kind"] == "experience")
        self.assertIn('not in file: company "Globex Inc"', it["flags"])
        self.assertFalse(it["default"])

    def test_reworded_bullet_offers_the_verbatim_line_and_dates_match_by_month(self):
        text = "## Experience\nEngineer - Acme (March 2021 - Present)\n- Reduced workflow latency by 40% for 12 teams\n"
        facts = {"contact": {}, "experience": [{"title": "Engineer", "company": "Acme", "start": "2021-03", "end": "Present",
                                                "bullets": ["Reduced the workflow latency by 40% for 12 teams"],
                                                "quote": "Engineer - Acme (March 2021 - Present)"}]}
        e = profile.verify(facts, text)["experience"][0]
        self.assertEqual(e["flags"], ["bullet 1 reworded"])  # the dates pass: March 2021 = 2021-03
        self.assertEqual(e["suggest"]["0"], "Reduced workflow latency by 40% for 12 teams")
        e = profile.verify({"contact": {}, "experience": [{"title": "Engineer", "company": "Acme", "end": "Present",
                                                          "quote": "Engineer - Acme (2019 - 2020)"}]},
                           "Engineer - Acme (2019 - 2020)")["experience"][0]
        self.assertIn('not in file: end "Present"', e["flags"])
        e = profile.verify({"contact": {}, "skills": [], "experience": [{"title": "Workflow lead", "company": "Acme"}]},
                           "Workﬂow lead at Acme")["experience"][0]
        self.assertEqual(e["flags"], [])  # NFKC: the PDF's 'ﬂ' ligature reads as 'fl'

    def test_a_quote_starting_with_a_dash_bullet_is_found(self):
        text = "## Awards\n- Data Hero - Tidewater Logistics (2023)\n"
        for quote in ("- Data Hero - Tidewater Logistics (2023)", "Data Hero - Tidewater Logistics (2023)"):
            f = profile.verify({"contact": {}, "awards": [{"name": "Data Hero", "issuer": "Tidewater Logistics",
                                                           "date": "2023", "quote": quote}]}, text)
            self.assertEqual(f["awards"][0]["flags"], [], quote)
        self.assertEqual(profile._vnorm("- Built X\n— Shipped Y"), "built x shipped y")

    def test_ai_contact_values_are_checked_and_regex_wins(self):
        text = "Dana Smith\ndana@example.com | +1 512 555 0101\n## Skills\nPython\n"
        reply = self.reply(contact={"name": "Dana Smith", "email": "attacker@evil.example", "phone": "+1 999 999 9999",
                                    "website": "https://evil.example"})
        with patched(ai, ask_json=lambda *a, **k: reply):
            facts, used = profile.extract(text, use_ai=True)
        self.assertTrue(used)
        self.assertEqual(facts["contact"]["email"], "dana@example.com")  # the regex value wins
        self.assertEqual(facts["contact"]["phone"], "+1 512 555 0101")
        self.assertIn("website", facts["_flags"]["contact"])
        items = profile.diff(profile.load(), facts)
        site = next(i for i in items if i.get("field") == "website")
        self.assertFalse(site["default"])


class Review(Base):
    def test_diff_new_changed_conflict_duplicate_and_fuzzy(self):
        bank = self.seed_bank()
        facts = {"contact": {"name": "Dana Smith", "phone": "+1 512 555 0199"},
                 "skills": [{"name": "Rust"}],
                 "experience": [{"title": "Senior Engineer", "company": "Acme Corp", "start": "2021-03", "end": "Present",
                                 "bullets": ["Cut deploy time 40%", "Led 4 engineers"]},
                                {"title": "Staff Engineer", "company": "Acme Corporation", "start": "2022", "end": "2023"},
                                {"title": "Engineer", "company": "Globex", "start": "2018", "end": "2020"}]}
        items = {(i["kind"], i.get("field") or str(i["incoming"].get("company", i["incoming"].get("name")))): i
                 for i in profile.diff(bank, facts, MASTER)}
        self.assertEqual(items[("contact", "name")]["status"], "duplicate")
        self.assertEqual(items[("contact", "phone")]["status"], "conflict")  # a different number: yours is kept by default
        self.assertEqual(items[("skills", "Rust")]["status"], "new")
        self.assertEqual(items[("experience", "Acme Corp")]["status"], "changed")
        self.assertEqual(items[("experience", "Acme Corp")]["adds"], {"bullets": ["Led 4 engineers"]})
        fuzzy = items[("experience", "Acme Corporation")]
        self.assertEqual((fuzzy["status"], fuzzy["fuzzy"], fuzzy["default"]), ("conflict", True, False))
        self.assertEqual(items[("experience", "Globex")]["status"], "new")
        self.assertTrue(items[("experience", "Globex")]["default"])

    def test_accept_new_merges_and_inserts_into_master_before_preferences(self):
        self.seed_bank()
        snaps = len(self.snaps())
        p = profile.stage_import(b"Dana Smith\ndana@example.com\n## Experience\n### Engineer - Globex (2018 - 2020)\n"
                                 b"- Built billing\n## Skills\nPython, Rust\n## Awards\n- Hackathon winner - PyData (2019)\n",
                                 "more.md", use_ai=False)
        self.assertEqual(profile.load()["skills"], [])  # staging changes nothing
        r = profile.apply_import(p["id"], "new")
        self.assertEqual(r["added"], {"skills": 2, "experience": 1, "awards": 1})
        self.assertTrue(r["master_changed"])
        text = PROFILE.read_text(encoding="utf-8")
        self.assertEqual(len(self.snaps()), snaps + 1)  # one write_master: one snapshot
        self.assertNotIn("## Experience", text)  # the role went under '## Work History'
        self.assertLess(text.index("### Engineer - Globex (2018 - 2020)"), text.index("## Education"))
        self.assertLess(text.index("## Awards"), text.index("## Preferences"))
        self.assertIn("- Hackathon winner - PyData (2019)", text)
        self.assertFalse((profile.IMPORTS / f"{p['id']}.json").exists())
        bank = profile.load()
        globex = next(e for e in bank["experience"] if e["company"] == "Globex")
        self.assertEqual(globex["evidence"], {p["source"]: "### Engineer - Globex (2018 - 2020)"})
        self.assertTrue(any(r["name"] == "more.md" for r in bank["resumes"]))

    def test_conflict_incoming_replaces_the_master_block(self):
        PROFILE.write_text(MASTER.replace("## Work History", "## Experience"), encoding="utf-8")
        self.seed_bank()
        p = profile.stage_import(b"## Experience\n### Senior Engineer - Acme Corp (2021-03 - 2024-06)\n- Cut deploy time 40%\n",
                                 "acme.md", use_ai=False)
        it = next(i for i in p["items"] if i["kind"] == "experience")
        self.assertEqual((it["status"], it["fields"]), ("conflict", {"end": ["Present", "2024-06"]}))
        profile.apply_import(p["id"], [it["id"]], {it["id"]: "incoming"})
        text = PROFILE.read_text(encoding="utf-8")
        self.assertIn("### Senior Engineer - Acme Corp (2021-03 - 2024-06)", text)
        self.assertNotIn("2021-03 - Present", text)
        self.assertEqual(profile.load()["experience"][0]["end"], "2024-06")

    def test_bank_only_apply_and_discard_leave_profile_md_alone(self):
        before = PROFILE.read_bytes()
        p = profile.stage_import(b"## Skills\nPython, Rust\n", "skills.md", use_ai=False)
        profile.apply_import(p["id"], "all", to_master=False)
        self.assertEqual(PROFILE.read_bytes(), before)
        self.assertEqual({s["name"] for s in profile.load()["skills"]}, {"Python", "Rust"})
        bank = profile.BANK.read_bytes()
        p = profile.stage_import(b"## Skills\nGo\n", "go-only.md", use_ai=False)
        stored = profile.RESUMES / p["resume"]["file"]
        self.assertTrue(stored.is_file())
        profile.discard_import(p["id"])
        self.assertEqual((PROFILE.read_bytes(), profile.BANK.read_bytes()), (before, bank))
        self.assertFalse(stored.exists())  # a new original nothing uses is removed again
        self.assertEqual(profile.pending_imports(), [])
        with self.assertRaises(ValueError):
            profile.apply_import("../x", "new")

    def test_reread_master_never_stages_preferences(self):
        bank = profile.load()
        bank["education"] = [{"school": "BSc Computer Science, UT Austin, 2018", "sources": ["v1"]}]  # a v1 one-liner
        profile.save(bank)
        p = profile.reread_master()
        self.assertNotIn("150,000", json.dumps(p["items"]))
        self.assertNotIn("on-call", json.dumps(p["items"]))
        edu = next(i for i in p["items"] if i["kind"] == "education")
        self.assertEqual((edu["incoming"]["school"], edu["incoming"]["degree"]), ("UT Austin", "BSc"))
        self.assertEqual(edu["status"], "new")  # shown next to the old one-liner for you to resolve
        self.assertFalse(p["resume"])

    def test_apply_never_writes_what_profile_md_already_shows(self):
        PROFILE.write_text(MASTER.replace("+1 512 555 0101", "+1 512 555 0101 | linkedin.com/in/dana-smith"), encoding="utf-8")
        # the first import after pass 17: profile.md shows the role (another layout), the bank has no roles yet
        p = profile.stage_import(b"Dana Smith\ndana@example.com | https://www.linkedin.com/in/dana-smith\n## Experience\n"
                                 b"Senior Engineer | Acme Corp | Mar 2021 - Present\n- Cut deploy time 40%\n## Skills\nPython\n",
                                 "acme.md", use_ai=False)
        role = next(i for i in p["items"] if i["kind"] == "experience")
        self.assertEqual((role["status"], role["in_master"]), ("new", True))
        r = profile.apply_import(p["id"], "new")
        text = PROFILE.read_text(encoding="utf-8")
        self.assertEqual(r["added"]["experience"], 1)  # the bank has it now
        self.assertEqual((text.count("Acme Corp"), text.count("Cut deploy time 40%")), (1, 1))
        self.assertEqual(text.count("linkedin.com/in/dana-smith"), 1)  # the normalised URL is the same value
        self.assertIn("Python", text)  # what profile.md did not show still goes in
        # Re-read my master profile, then Accept all new: the bank fills, profile.md is not written back into
        before = PROFILE.read_text(encoding="utf-8")
        r = profile.apply_import(profile.reread_master()["id"], "new")
        self.assertEqual((PROFILE.read_text(encoding="utf-8"), r["master_changed"]), (before, False))
        self.assertTrue(r["added"])

    def test_a_finer_date_is_an_add_and_keep_mine_still_takes_new_bullets(self):
        bank = profile.load()
        profile.merge(bank, {"experience": [{"title": "Senior Engineer", "company": "Acme Corp", "start": "2021",
                                             "end": "Present", "bullets": ["Cut deploy time 40%"]}]}, "old.pdf")
        profile.save(bank)
        p = profile.stage_import(b"## Experience\n### Senior Engineer - Acme Corp (Mar 2021 - Present)\n- Cut deploy time 40%\n"
                                 b"- Mentored 2 junior engineers on dbt testing\n", "acme.md", use_ai=False)
        it = next(i for i in p["items"] if i["kind"] == "experience")
        self.assertEqual((it["status"], it["fields"], it["default"]), ("changed", {}, True))  # one date, more precise
        self.assertEqual(it["adds"], {"start": "Mar 2021", "bullets": ["Mentored 2 junior engineers on dbt testing"]})
        self.assertEqual(profile.apply_import(p["id"], "new", to_master=False)["updated"], 1)
        acme = profile.load()["experience"][0]
        self.assertEqual((acme["start"], acme["bullets"][-1]), ("Mar 2021", "Mentored 2 junior engineers on dbt testing"))
        self.assertIsNone(profile._finer_date("2021-03", "2022"))
        self.assertEqual(profile._finer_date("2021-03", "Mar 2021"), "2021-03")  # the same month: yours stays
        # a real conflict kept as yours still takes the bullets it adds when you tick it
        p = profile.stage_import(b"## Experience\n### Senior Engineer - Acme Corp (Mar 2021 - 2024)\n- Cut costs 12%\n",
                                 "acme2.md", use_ai=False)
        it = next(i for i in p["items"] if i["kind"] == "experience")
        self.assertEqual((it["status"], it["fields"]), ("conflict", {"end": ["Present", "2024"]}))
        profile.apply_import(p["id"], [it["id"]], {it["id"]: "mine"}, to_master=False)
        acme = profile.load()["experience"][0]
        self.assertEqual((acme["end"], acme["bullets"][-1]), ("Present", "Cut costs 12%"))

    def test_import_file_without_review_still_merges(self):
        PROFILE.write_text(MASTER, encoding="utf-8")
        r = profile.import_file(b"# X\n## Skills\n- Kubernetes, Rust\n", "extra.md", use_ai=False)
        self.assertEqual(r["added"]["skills"], 2)
        self.assertFalse(r["seeded_master"])

    def test_v1_bank_migrates_and_keeps_every_value(self):
        v1 = {"contact": {"name": "Dana", "email": "d@x.example"}, "summary": "s",
              "skills": [{"name": "Python", "category": "", "sources": ["a"]}],
              "experience": [{"title": "Eng", "company": "Acme", "location": "", "start": "2020", "end": "", "bullets": ["b"],
                              "sources": ["a"]}],
              "education": [{"school": "BSc CS, UT Austin, 2018", "degree": "", "field": "", "start": "", "end": "", "sources": ["a"]}],
              "certifications": [], "projects": [], "languages": [], "resumes": [{"id": "abcd1234", "file": "x.txt"}],
              "updated": "2026-01-01T00:00:00"}
        profile.BANK.write_text(json.dumps(v1), encoding="utf-8")
        bank = profile.load()
        self.assertEqual(bank["awards"], [])
        profile.save(bank)
        saved = json.loads(profile.BANK.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], 2)
        for k in ("contact", "summary", "skills", "experience", "education", "resumes"):
            self.assertEqual(saved[k] if k != "contact" else {c: saved[k][c] for c in v1[k]}, v1[k], k)

    def test_linkedin_extra_files_are_read_by_header_and_others_noted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Profile.csv", "First Name,Last Name,Headline\nDana,Smith,Engineer\n")
            z.writestr("Honors.csv", "Title,Description,Issued On\nHackathon winner,Best data hack,Mar 2019\n")
            z.writestr("Publications.csv", "Name,Published On,Description,Publisher,Url\nStreaming,Jan 2020,x,VLDB,https://d.example\n")
            z.writestr("Volunteering.csv", "Company Name,Role,Cause,Started On,Finished On,Description\nCode2040,Mentor,Education,Jan 2019,,Mentored\n")
            z.writestr("Courses.csv", "Name,Number\nDeep Learning,CS230\n")
            z.writestr("Patents.csv", "Weird,Header\n1,2\n")  # unknown columns: skipped, never guessed
            z.writestr("messages.csv", "FROM,TO\na,b\n")
        f = profile.linkedin_facts(buf.getvalue())
        self.assertEqual((f["awards"][0]["name"], f["awards"][0]["date"]), ("Hackathon winner", "2019-03"))
        self.assertEqual((f["publications"][0]["venue"], f["publications"][0]["url"]), ("VLDB", "https://d.example"))
        self.assertEqual((f["volunteering"][0]["organization"], f["volunteering"][0]["role"]), ("Code2040", "Mentor"))
        self.assertEqual(f["other"], [{"heading": "Courses", "bullets": ["Deep Learning"]}])
        self.assertEqual(f["patents"], [])
        self.assertIn("not read: 1 other file(s)", f["_notes"][0])


class Catalogue(Base):
    def test_structured_maps_every_master_line_to_a_fact(self):
        PROFILE.write_text(MASTER.replace("- Cut deploy time 40%", "- Cut deploy time 40%\nA stray line")
                           .replace("## Preferences", "## Notes\nCall Bob\n\n## Preferences"), encoding="utf-8")
        bank = profile.load()
        profile.merge(bank, {"skills": [{"name": "Rust"}],
                             "experience": [{"title": "Senior Engineer", "company": "Acme Corp", "technologies": ["Python"]}]}, "x")
        profile.save(bank)
        d = profile.structured()
        acme = d["experience"][0]
        self.assertEqual((acme["id"], acme["technologies"], acme.get("on_file")), ("e1", ["Python"], None))  # bank fills blanks
        self.assertEqual((d["skills"][0]["name"], d["skills"][0]["on_file"], d["skills"][0]["id"]), ("Rust", True, "k1"))
        others = {o["heading"]: o["bullets"] for o in d["other"]}
        self.assertEqual(others["Notes"], ["Call Bob"])
        self.assertEqual(others["Work History"], ["A stray line"])  # no master line is left without a fact
        self.assertNotIn("150,000", json.dumps(d))
        PROFILE.write_text(MASTER.replace("## Summary", "## Summary\nMy salary floor is $150,000"), encoding="utf-8")
        with self.assertRaises(SystemExit):
            profile.structured()  # employer=True: a floor outside Preferences is refused
        PROFILE.write_text("# Me\nme@example.com\n## Experience\nI did many things at many places.\n", encoding="utf-8")
        self.assertIn("Experience could not be read as roles", profile.structured()["warnings"][0])


class Web(Base):
    def call(self, method, path, body=None, token=True):
        import http.client

        from lodestar import web

        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"} | (
            {"X-Lodestar-Token": web.TOKEN} if token else {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def setUp(self):
        super().setUp()
        from lodestar import desktop, web

        self.port = desktop.free_port(8960)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def task(self, action, body):
        st, v = self.call("POST", f"/api/run/{action}", body)
        for _ in range(100):
            st, t = self.call("GET", f"/api/tasks/{v['task']}")
            if t["status"] != "running":
                return t
            time.sleep(0.05)
        return t

    def test_profile_post_with_stale_base_is_409_and_without_base_saves(self):
        st, v = self.call("GET", "/api/profile")
        self.assertEqual((st, v["text"]), (200, MASTER))
        base = v["base"]
        PROFILE.write_text(MASTER + "\n## Awards\n- Imported line\n", encoding="utf-8")  # an import wrote meanwhile
        st, v = self.call("POST", "/api/profile", {"text": MASTER + "\nmy edit\n", "base": base})
        self.assertEqual(st, 409)
        self.assertIn("reload, then redo your edit", v["error"])
        self.assertIn("Imported line", PROFILE.read_text(encoding="utf-8"))  # unchanged
        st, v = self.call("POST", "/api/profile", {"text": MASTER + "\nscript edit\n"})  # no base: saved as before
        self.assertEqual(st, 200)
        self.assertIn("script edit", PROFILE.read_text(encoding="utf-8"))
        st, v2 = self.call("POST", "/api/profile", {"text": MASTER, "base": v["base"]})
        self.assertEqual(st, 200)

    def test_import_review_routes_and_token(self):
        data = base64.b64encode(b"Dana Smith\ndana@example.com\n## Skills\nPython, Rust\n").decode()
        t = self.task("profile_import", {"name": "r.md", "data": data, "ai": False, "review": True})
        self.assertEqual(t["status"], "done", t)
        pid = t["result"]["pending"]["id"]
        self.assertEqual(profile.load()["skills"], [])
        st, v = self.call("GET", "/api/profile/imports")
        self.assertEqual([p["id"] for p in v["imports"]], [pid])
        self.assertEqual(self.call("POST", "/api/profile/imports/zzzz/apply", {})[0], 400)
        self.assertEqual(self.call("POST", f"/api/profile/imports/{pid}/apply", {}, token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/profile/imports", token=False)[0], 403)
        st, v = self.call("POST", f"/api/profile/imports/{pid}/apply", {"accept": "new", "to_master": False})
        self.assertEqual(st, 200, v)
        self.assertEqual(v["added"], {"contact": 2, "skills": 2})  # name and email were not in the bank yet
        self.assertIn("Rust", [s["name"] for s in v["bank"]["skills"]])
        t = self.task("profile_reread", {})
        self.assertEqual(t["status"], "done", t)
        st, v = self.call("POST", f"/api/profile/imports/{t['result']['pending']['id']}/discard", {})
        self.assertEqual((st, v), (200, {"ok": True}))
        bank = profile.load()
        bank["experience"] = [{"title": "Eng", "company": "Acme", "sources": ["x"]},
                              {"title": "Lead", "company": "Acme", "sources": ["x"]}]
        profile.save(bank)
        st, v = self.call("POST", "/api/profile/bank", {"op": "remove_at", "kind": "experience", "index": 1, "label": "Eng - Acme"})
        self.assertEqual(st, 400)  # the label no longer matches that position: nothing removed
        st, v = self.call("POST", "/api/profile/bank", {"op": "remove_at", "kind": "experience", "index": 1, "label": "Lead - Acme"})
        self.assertEqual((st, [e["title"] for e in v["bank"]["experience"]]), (200, ["Eng"]))


class Cli(Base):
    def test_cli_import_stages_then_review_accepts(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "cv.md")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("Dana Smith\ndana@example.com\n## Skills\nPython, Rust\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["profile", "import", f, "--no-ai"])
            self.assertIn("nothing saved to the bank yet", out.getvalue())
            self.assertEqual(profile.load()["skills"], [])
            pid = profile.pending_imports()[0]["id"]
            synced = []
            with contextlib.redirect_stdout(io.StringIO()) as out, patched(studio, sync_master=lambda: synced.append(1) or {}):
                cli.main(["profile", "review", pid, "--accept", "new", "--no-master"])
            self.assertIn(f"applied {pid}: added 2 contact, 2 skills", out.getvalue())
            self.assertEqual(synced, [1])  # a command that changed the profile rebuilds the master resume once
            self.assertEqual({s["name"] for s in profile.load()["skills"]}, {"Python", "Rust"})

    def test_cli_prints_ligature_under_cp1252(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        bank = profile.load()
        bank["contact"]["name"] = "Workﬂow Smith"
        profile.save(bank)
        with patched(sys, stdout=stream):
            cli.main(["profile", "show"])
            stream.flush()
        self.assertIn(b"Work?ow Smith", raw.getvalue())


if __name__ == "__main__":
    unittest.main()
