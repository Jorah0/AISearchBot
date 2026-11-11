"""Pass 17, builder 2: the AI resume studio. The renderers (render.py: html, docx, md, txt from one block list; golden
strings), the style spec (clean_style / full_style / resume_look), the no-invention guards (resume.check_rewrite and
studio.resolve: structure copied by id, bullets checked against their own entry, the summary per sentence, computed
years), builds (offline, AI, page limit with one tighten call then trim, refine, the floor guard), versions and
use_for_job, the pipeline's Tailor step on the studio, the web routes, the CLI, and one real headless-Edge render that
skips when no Edge / Chrome is installed."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, cli, db, lint, pipeline, profile, render, resume, settings, studio  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Master Resume
## Contact
Dana Smith | Austin, TX | dana@example.com | +1 512 555 0101 | linkedin.com/in/dana

## Summary
Data engineer who ships reliable pipelines.

## Skills
- Languages: Python, SQL
- Platforms: Kafka, AWS

## Experience
### Senior Engineer - Acme Corp (2021-03 - Present)
Location: Austin, TX | Technologies: Python, SQL
- Cut deploy time 40% by rebuilding CI
- Led 4 engineers through a database migration
- Wrote the on-call runbook

### Engineer - Globex (2016-01 - 2021-02)
Technologies: Kafka
- Built Kafka pipelines for billing events
- Managed 10 engineers on the billing rewrite

### Analyst - Initech (2012-01 - 2015-12)
- Wrote SQL reports

## Education
### BSc, Computer Science - UT Austin (2015)

## Certifications
- AWS Certified Data Engineer - Amazon Web Services (2023)

## Preferences
Salary floor: $150,000 | Deal-breakers: on-call
"""
DOC = {"contact": {"name": "Dana Smith", "location": "Austin, TX", "email": "dana@example.com", "phone": "+1 512 555 0101",
                   "linkedin": "linkedin.com/in/dana", "website": "https://dana.dev"},
       "headline": "Data engineer", "summary": "Builds reliable pipelines.",
       "sections": [{"kind": "summary", "title": "Summary"},
                    {"kind": "experience", "title": "Experience", "items": [
                        {"id": "e1", "title": "Senior Engineer", "company": "Acme Corp", "location": "Austin, TX",
                         "start": "2021-03", "end": "Present", "bullets": ["Cut deploy time 40%", "Led 4 engineers"],
                         "technologies": ["Python"]}]},
                    {"kind": "skills", "title": "Skills", "groups": [{"label": "Data", "names": ["Python", "SQL"]},
                                                                     {"label": "Cloud", "names": ["AWS"]}]},
                    {"kind": "education", "title": "Education", "items": [
                        {"id": "d1", "school": "UT Austin", "degree": "BSc", "field": "Computer Science", "end": "2018"}]},
                    {"kind": "certifications", "title": "Certifications", "items": [
                        {"id": "c1", "name": "AWS Certified Data Engineer", "issuer": "Amazon Web Services", "date": "2023-05"}]}]}
GOLDEN_MD = ("# Dana Smith\nDana Smith | Austin, TX | +1 512 555 0101 | dana@example.com | linkedin.com/in/dana | https://dana.dev\n\n"
             "## Summary\nData engineer\nBuilds reliable pipelines.\n\n## Experience\n\n### Senior Engineer - Acme Corp (2021-03 - Present)\n"
             "Location: Austin, TX | Technologies: Python\n- Cut deploy time 40%\n- Led 4 engineers\n\n## Skills\n- Data: Python, SQL\n"
             "- Cloud: AWS\n\n## Education\n\n### BSc, Computer Science - UT Austin (2018)\n\n## Certifications\n"
             "- AWS Certified Data Engineer - Amazon Web Services (2023-05)\n")
GOLDEN_TXT = ("Dana Smith\nAustin, TX | +1 512 555 0101 | dana@example.com | linkedin.com/in/dana | https://dana.dev\nData engineer\n\n"
              "SUMMARY\nBuilds reliable pipelines.\n\nEXPERIENCE\n\nSenior Engineer - Acme Corp, Austin, TX | Mar 2021 - Present\n"
              "Technologies: Python\n- Cut deploy time 40%\n- Led 4 engineers\n\nSKILLS\nData: Python, SQL\nCloud: AWS\n\nEDUCATION\n\n"
              "BSc, Computer Science - UT Austin | 2018\n\nCERTIFICATIONS\n- AWS Certified Data Engineer - Amazon Web Services (May 2023)\n")
GOLDEN_BODY = ('<h1>Dana Smith</h1>\n<p class="contact">Austin, TX | +1 512 555 0101 | <a href="mailto:dana@example.com">'
               'dana@example.com</a> | linkedin.com/in/dana | <a href="https://dana.dev">https://dana.dev</a></p>\n'
               '<p class="headline">Data engineer</p>\n<h2 data-section="0">Summary</h2>\n<p>Builds reliable pipelines.</p>\n'
               '<h2 data-section="1">Experience</h2>\n<h3><span>Senior Engineer - Acme Corp, Austin, TX</span> <span class="dates">'
               'Mar 2021 - Present</span></h3>\n<p class="detail">Technologies: Python</p>\n<ul>\n<li>Cut deploy time 40%</li>\n'
               '<li>Led 4 engineers</li>\n</ul>\n<h2 data-section="2">Skills</h2>\n<p>Data: Python, SQL</p>\n<p>Cloud: AWS</p>\n'
               '<h2 data-section="3">Education</h2>\n<h3><span>BSc, Computer Science - UT Austin</span> <span class="dates">2018'
               '</span></h3>\n<h2 data-section="4">Certifications</h2>\n<ul>\n<li>AWS Certified Data Engineer - Amazon Web Services '
               '(May 2023)</li>\n</ul>\n</body></html>\n')


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


class FakeAI:
    """ask_json by prompt marker: the plan, the tighten reply; every prompt kept."""

    def __init__(self, plan=None, tighten=None):
        self.plan, self.tighten, self.prompts = plan or {}, tighten, []

    def ask_json(self, prompt, system=None, provider=None, **kw):
        self.prompts.append(prompt)
        if "prints on" in prompt:
            return self.tighten if self.tighten is not None else self.plan
        return self.plan


def fake_pages(seq):
    """studio._engine_pdf stand-in: writes a small PDF and reports the next page count of seq (the last one repeats)."""
    calls = []

    def run(html, pdf, tried):
        calls.append(Path(html).read_text(encoding="utf-8"))
        Path(pdf).write_bytes(b"%PDF-1.4\n/Type /Page\n" + b"x" * 2000)
        return seq[min(len(calls), len(seq)) - 1]
    return run, calls


class Base(unittest.TestCase):
    """A known profile.md, an empty bank, no studio versions or resume_look; all put back afterwards. No PDF engine
    unless a test brings one (real Edge only in Edge.test_real_edge_renders_a_one_page_studio_pdf)."""

    def setUp(self):
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        settings.PATH.unlink(missing_ok=True)
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patched(studio, AUTO=False))
        self.stack.enter_context(patched(resume, _browser=lambda: None, _word=lambda: False, _soffice=lambda: None))

    def tearDown(self):
        self.stack.close()
        shutil.rmtree(studio.STUDIO, ignore_errors=True)
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def ai(self, plan=None, tighten=None):
        fake = FakeAI(plan, tighten)
        self.stack.enter_context(patched(ai, ask_json=fake.ask_json, available=lambda: ["anthropic"]))
        return fake

    def files(self, v, ext):
        return (studio.STUDIO / v["vid"] / v["files"][ext]).read_text(encoding="utf-8")


class Render(Base):
    def test_golden_md_txt_and_html_from_one_doc(self):
        st = render.full_style({"template": "classic"})
        self.assertEqual(render.to_md(DOC, st), GOLDEN_MD)
        self.assertEqual(render.to_txt(DOC, st), GOLDEN_TXT)
        html = render.to_html(DOC, st)
        self.assertEqual(html.split("<body>\n", 1)[1], GOLDEN_BODY)
        for rule in ("@page{size:letter;margin:0.75in}", "font-variant-ligatures:none", "display:flex"):
            self.assertIn(rule, html)
        self.assertNotIn("float", html)
        back = profile.extract_heuristic(GOLDEN_MD)  # the markdown is the master format: it reads back
        self.assertEqual((back["experience"][0]["company"], back["experience"][0]["bullets"]), ("Acme Corp", ["Cut deploy time 40%", "Led 4 engineers"]))
        self.assertEqual(back["certifications"][0]["issuer"], "Amazon Web Services")

    def test_docx_styles_tab_stop_no_tables_and_audit_clean(self):
        from docx import Document

        for look in ({"template": "classic"}, {"template": "modern"}, {"template": "compact"},
                     {"template": "classic", "font": "Georgia", "accent": "teal", "paper": "a4", "size": 11}):
            st = render.full_style(look)
            with tempfile.TemporaryDirectory() as tmp:
                out = render.to_docx(DOC, st, Path(tmp) / "Dana-Smith-Resume.docx")
                data = out.read_bytes()
            d = Document(io.BytesIO(data))
            texts = [p.text for p in d.paragraphs]
            self.assertEqual(texts[:3], ["Dana Smith", "Austin, TX | +1 512 555 0101 | dana@example.com | linkedin.com/in/dana | https://dana.dev", "Data engineer"])
            self.assertIn("Senior Engineer - Acme Corp, Austin, TX\tMar 2021 - Present", texts)
            role = next(p for p in d.paragraphs if p.text.startswith("Senior Engineer"))
            self.assertEqual(len(role.paragraph_format.tab_stops), 1)
            self.assertEqual(d.styles["Normal"].font.name, st["font"])
            self.assertEqual(d.styles["Normal"].font.size.pt, st["size"])
            self.assertEqual(str(d.styles["Heading 2"].font.color.rgb), st["accent"].lstrip("#"))
            self.assertEqual(len(d.tables), 0)
            self.assertEqual([i["rule"] for i in lint.audit(data, "Dana-Smith-Resume.docx")["issues"]], [], look)
        self.assertAlmostEqual(d.sections[0].page_width.inches, 8.27, places=2)

    def test_links_only_for_http_and_email_and_no_script(self):
        doc = DOC | {"contact": DOC["contact"] | {"website": "javascript:alert(1)", "github": "<b>gh</b>"}}
        html = render.to_html(doc, render.full_style({}))
        self.assertNotIn("<script", html.lower())
        self.assertNotIn('href="javascript', html)
        self.assertIn("javascript:alert(1)", html)
        self.assertIn("&lt;b&gt;gh&lt;/b&gt;", html)

    def test_dates_and_file_name(self):
        f = render.fmt_date
        self.assertEqual([f("2021-03", x) for x in render.DATE_FORMATS], ["Mar 2021", "March 2021", "03/2021", "2021-03", "2021"])
        self.assertEqual((f("2019", "Mar 2021"), f("present", "Mar 2021"), f("Summer 2019", "Mar 2021")), ("2019", "Present", "Summer 2019"))
        self.assertEqual(render.filename(DOC, "pdf"), "Dana-Smith-Resume.pdf")
        self.assertIsNone(lint._odd_name("Dana-Smith-Resume.pdf"))
        self.assertEqual(render.filename({"contact": {}}, "docx"), "Resume.docx")


class Style(Base):
    def test_clean_style_refuses_logs_and_maps(self):
        notes = []
        got = render.clean_style({"font": "Comic Sans", "accent": "navy", "size": 30, "margins": "0.5", "paper": "A4",
                                  "sections": "experience,skills", "formats": "pdf,txt", "colour": "red"}, notes)
        self.assertEqual(got, {"accent": "#1F3A5F", "margins": 0.5, "paper": "a4", "sections": ["experience", "skills"],
                               "formats": ["pdf", "txt"]})
        self.assertEqual(len(notes), 3)
        self.assertIn("font 'Comic Sans' is not ATS-safe", notes[0])
        with self.assertRaises(SystemExit):
            render.clean_style({"accent": "rainbow"}, strict=True)
        st = render.full_style({"font": "Georgia", "accent": "teal"}, {"template": "modern"})
        self.assertEqual((st["font"], st["accent"]), ("Arial", "#1F4E79"))  # picking a template resets the earlier look
        self.assertEqual(render.full_style({"template": "compact"}, {"font": "Georgia"})["font"], "Georgia")

    def test_resume_look_pref_is_validated(self):
        settings.set_pref("resume_look", "font=georgia")
        settings.set_pref("resume_look", "accent=navy")
        self.assertEqual(settings.pref("resume_look"), {"font": "Georgia", "accent": "#1F3A5F"})
        with self.assertRaises(SystemExit):
            settings.set_pref("resume_look", "font=Comic Sans")
        with self.assertRaises(SystemExit):
            settings.set_pref("resume_look", {"margins": 3})
        self.assertEqual(settings.pref("resume_look"), {"font": "Georgia", "accent": "#1F3A5F"})

    def test_drawer_exports_use_the_saved_look_else_the_presets(self):
        self.assertEqual(resume._style(None), resume.STYLES["classic"])
        settings.set_pref("resume_look", {"font": "Georgia", "accent": "teal", "paper": "a4"})
        s = resume._style(None)
        self.assertEqual((s["font"], s["color"], s["paper"]), ("Georgia", (0x0F, 0x6E, 0x6E), "a4"))
        self.assertEqual(resume._style("modern"), resume.STYLES["modern"])  # a preset you pick still wins
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "resume.md"
            md.write_text("# Dana Smith\ndana@example.com\n## Experience\n- Cut deploy time 40%\n", encoding="utf-8")
            html = resume.export_html(md, None, printable=False).read_text(encoding="utf-8")
            from docx import Document

            d = Document(str(resume.export_docx(md)))
        self.assertIn("font-family:Georgia", html)
        self.assertIn("size:a4", html)
        self.assertEqual(d.styles["Normal"].font.name, "Georgia")


class Guards(Base):
    def test_check_rewrite_flags_every_kind_of_invention(self):
        orig, title = "Cut deploy time 40% by rebuilding CI", "Senior Engineer - Acme Corp"
        scope = orig + "\n" + title + "\nPython, SQL"
        g = lambda text, **kw: resume.check_rewrite(orig, text, MASTER, scope=scope, title=title, **kw)["flags"]  # noqa: E731
        self.assertEqual(g("Cut deploy time 40% by rebuilding the CI pipeline"), [])
        self.assertEqual(g("Cut deploy time 45% by rebuilding CI"), ["new number"])
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI on Kafka"), ["unsupported"])  # Kafka is Globex's
        self.assertIn("new title", g("As engineering manager, cut deploy time 40% by rebuilding CI"))
        self.assertIn("new degree", g("Cut deploy time 40% by rebuilding CI with an MBA"))
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI in Zorblax"), ["new term"])  # in no skills list
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI in Zorblax", jd_missing=["Zorblax"]), ["unsupported"])
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI in Dagster", jd_missing=["Dagster"]), ["unsupported"])
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI, see https://x.dev"), ["new term", "new link"])
        self.assertIn("personal", g("Cut deploy time 40% by rebuilding CI as a US citizen"))
        self.assertEqual(g("Cut deploy time 40% by rebuilding CI for $150k"), ["new number", "personal"])

    def plan(self, **extra):
        return {"sections": [{"kind": "experience", "items": [{"ref": "e1", "company": "Google", "title": "CTO", "bullets": [
                    {"refs": ["e1.b1"], "text": "Cut deploy time 35% by rebuilding CI"},
                    {"refs": ["e1.b2"], "text": "Led 4 engineers through a database migration to Kafka"},
                    {"refs": ["e1.b3"], "text": "Wrote the on-call runbook in Zorblax"},
                    {"refs": ["e2.b1"]},
                    {"refs": ["e1.b1"], "text": "Rebuilt CI and cut deploy time 40%"}]},
                    {"ref": "e9"}, {"ref": "e2", "bullets": [{"refs": ["e2.b2"]}]}]},
                {"kind": "skills", "title": "Preferences", "groups": [{"label": "Kubernetes", "refs": ["k1", "k2"]},
                                                                      {"label": "Platforms", "refs": ["k3", "k4"]}]},
                {"kind": "education", "items": ["d1"]}]} | extra

    def test_resolve_copies_structure_and_reverts_what_the_entry_does_not_say(self):
        doc = profile.structured()
        r, ev = studio.resolve(self.plan(), doc, jd_missing=["Zorblax"])
        e1 = r["sections"][1]["items"][0]  # 0 is the summary (s0 kept)
        self.assertEqual((e1["company"], e1["title"]), ("Acme Corp", "Senior Engineer"))
        self.assertEqual(e1["bullets"], ["Cut deploy time 40% by rebuilding CI", "Led 4 engineers through a database migration",
                                         "Wrote the on-call runbook", "Rebuilt CI and cut deploy time 40%"])
        text = "\n".join(ev)
        for frag in ("e1.b1: reverted (new number 35)", "e1.b2: reverted (unsupported kafka", "e1.b3: reverted (unsupported zorblax)",
                     "e1: a bullet citing e2.b1 was dropped (it belongs to another entry)", "experience: unknown id e9 dropped",
                     "group label 'Kubernetes' is not supported", "section title 'Preferences' is not a standard heading: used Skills"):
            self.assertIn(frag, text)
        skills = next(x for x in r["sections"] if x["kind"] == "skills")
        self.assertEqual((skills["title"], [g["label"] for g in skills["groups"]]), ("Skills", ["Skills", "Platforms"]))
        self.assertEqual(r["sections"][1]["items"][1]["bullets"], ["Managed 10 engineers on the billing rewrite"])

    def test_summary_is_checked_per_sentence_and_years_may_be_computed(self):
        doc = profile.structured()
        plan = {"headline": {"text": "Engineering director", "refs": ["e1"]},
                "summary": {"text": "Data engineer with 14 years of experience. US citizen open to relocation. "
                                    "Earns $150k today. Led 10+ years of platform work. Ships reliable pipelines.", "refs": ["s0"]},
                "sections": [{"kind": "summary"}, {"kind": "experience", "items": ["e1"]}]}
        r, ev = studio.resolve(plan, doc)
        self.assertEqual(r["summary"], "Data engineer with 14 years of experience. Ships reliable pipelines.")
        self.assertEqual(r["headline"], "")  # 'director' is a new title: back to the (empty) headline
        text = "\n".join(ev)
        self.assertIn("summary: 14 years is computed from your earliest role (2012)", text)
        self.assertIn('left out "Led 10+ years of platform work."', text)
        self.assertIn('left out "US citizen open to relocation."', text)

    def test_computed_years_cover_only_a_years_phrase(self):
        n = time.localtime().tm_year - 2012  # the earliest role starts in 2012
        plan = {"headline": {"text": f"Data engineer who managed {n} engineers", "refs": ["e1"]},
                "summary": {"text": f"Data engineer with {n}+ years of experience. Grew the platform to {n} regions.",
                            "refs": ["s0"]},
                "sections": [{"kind": "summary"}, {"kind": "experience", "items": ["e1"]}]}
        r, ev = studio.resolve(plan, profile.structured())
        self.assertEqual((r["headline"], r["summary"]), ("", f"Data engineer with {n}+ years of experience."))
        text = "\n".join(ev)
        self.assertIn(f'left out "Grew the platform to {n} regions."', text)
        self.assertNotIn(f"headline: {n} years is computed", text)  # an invented team size is not a computed fact
        g = resume.check_rewrite("", f"{n} years building pipelines for {n} teams", "", allow_numbers={n})
        self.assertEqual((g["new_numbers"], g["computed"]), ([str(n)], []))
        self.assertEqual(resume.check_rewrite("", f"{n}-year track record", "", allow_numbers={n})["computed"], [str(n)])

    def test_on_file_entries_are_listed_and_contact_values_never_reach_the_prompt(self):
        bank = profile.load()
        profile.merge(bank, {"experience": [{"title": "Intern", "company": "Hooli", "start": "2011", "end": "2011",
                                             "bullets": ["Fixed bugs"]}]}, "old.pdf")
        profile.save(bank)
        fake = self.ai({"sections": [{"kind": "experience", "items": ["e1", "e4"]}]})
        v = studio.build("lead with Acme")
        self.assertIn("used from your other resumes: Intern - Hooli (2011 - 2011)", "\n".join(v["events"]))
        p = fake.prompts[0]
        self.assertIn("e4 experience: Intern - Hooli (2011 - 2011) [on file]", p)
        for secret in ("dana@example.com", "555 0101", "linkedin.com/in/dana", "150,000"):
            self.assertNotIn(secret, p)
        self.assertIn("<<<REQUEST\nlead with Acme\nREQUEST>>>", p)


class Build(Base):
    def test_offline_build_honours_sections_bullets_drop_and_since(self):
        v = studio.build(req={"sections": "experience,education", "bullets_per_role": 1, "drop": ["e2"], "since": 2016,
                              "formats": ["docx", "txt"]}, use_ai=False)
        md = self.files(v, "md")
        self.assertIn("### Senior Engineer - Acme Corp (2021-03 - Present)\nLocation: Austin, TX | Technologies: Python, SQL\n"
                      "- Cut deploy time 40% by rebuilding CI\n\n## Education", md)
        for gone in ("Globex", "Initech", "## Skills", "## Summary", "Led 4 engineers", "Salary"):
            self.assertNotIn(gone, md)
        self.assertEqual(sorted(v["files"]), ["docx", "html", "md", "txt"])
        self.assertIsNone(v["pages"])
        self.assertIn("page count unknown", v["warnings"][0])
        self.assertFalse(v["used_ai"])

    def test_a_request_needs_an_ai_provider(self):
        with patched(ai, available=lambda: []):
            with self.assertRaises(SystemExit) as e:
                studio.build("one page please")
            self.assertIn("add an AI provider", str(e.exception))
            self.assertEqual(studio.build()["used_ai"], False)  # no request, no provider: offline

    def test_a_salary_floor_outside_preferences_stops_the_build_and_leaves_nothing(self):
        PROFILE.write_text(MASTER.replace("## Summary\n", "## Summary\nSalary floor: $150,000\n"), encoding="utf-8")
        with self.assertRaises(SystemExit):
            studio.build(use_ai=False)
        self.assertEqual(list(studio.STUDIO.glob("*")) if studio.STUDIO.is_dir() else [], [])
        PROFILE.write_text(MASTER, encoding="utf-8")
        v = studio.build(use_ai=False, req={"formats": "pdf,docx,md,txt"})
        for ext in ("md", "txt", "html"):
            self.assertNotIn("150,000", self.files(v, ext))
            self.assertNotIn("Deal-breakers", self.files(v, ext))

    def test_page_limit_tightens_once_with_ai_then_trims_then_warns(self):
        fake = self.ai({"sections": [{"kind": "experience", "items": ["e1", "e2", "e3"]}]},
                       tighten={"sections": [{"kind": "experience", "items": ["e1"]}]})
        run, calls = fake_pages([2, 1])
        with patched(studio, _engine_pdf=run):
            v = studio.build(req={"pages": 1})
        self.assertEqual((v["pages"], v["ai_calls"], len(calls), len(fake.prompts)), (1, 2, 2, 2))
        self.assertIn("2 pages, limit 1: the AI tightened the plan", v["events"])
        self.assertNotIn("Globex", self.files(v, "md"))
        run, calls = fake_pages([2, 2, 1])
        with patched(studio, _engine_pdf=run):
            v = studio.build(req={"pages": 1}, use_ai=False)
        self.assertEqual((v["pages"], len(calls)), (1, 3))
        self.assertEqual([e for e in v["events"] if e.startswith("page limit")],
                         ["page limit: cut the last bullet of Senior Engineer - Acme Corp, Austin, TX (2021-03 - Present)",
                          "page limit: cut the last bullet of Engineer - Globex (2016-01 - 2021-02)"])
        run, calls = fake_pages([2])
        with patched(studio, _engine_pdf=run):
            v = studio.build(req={"pages": 1}, use_ai=False)
        self.assertLessEqual(len(calls), studio.MAX_RENDERS)
        self.assertTrue(v["warnings"][0].startswith("still 2 pages after"))
        self.assertTrue((studio.STUDIO / v["vid"] / "plan.json").is_file())

    def test_refine_carries_the_parent_and_builds_fresh_after_a_profile_change(self):
        fake = self.ai({"sections": [{"kind": "experience", "items": ["e1"]}], "style": {"template": "modern"}})
        a = studio.build("modern", req={"bullets_per_role": 2})
        b = studio.build("shorter", parent=a["vid"])
        self.assertNotEqual(a["vid"], b["vid"])
        self.assertEqual((b["parent"], b["req"]), (a["vid"], {"bullets_per_role": 2}))
        self.assertIn("PREVIOUS PLAN", fake.prompts[-1])
        self.assertIn('"template": "modern"', fake.prompts[-1])
        PROFILE.write_text(MASTER.replace("ships reliable", "ships fast, reliable"), encoding="utf-8")
        c = studio.build("warmer", parent=b["vid"])
        self.assertNotIn("PREVIOUS PLAN", fake.prompts[-1])
        self.assertIn("modern\nshorter\nwarmer", fake.prompts[-1])
        self.assertIn("built fresh", c["notes"][0])
        self.assertEqual([x["vid"] for x in studio.versions()][:3], [c["vid"], b["vid"], a["vid"]])
        self.assertTrue(studio.versions()[1]["profile_changed"])
        same = [studio._new_dir("x")[0] for _ in range(3)]
        self.assertEqual(len(set(same)), 3)
        self.assertTrue(same[1].endswith("-2"))

    def test_use_for_job_writes_resume_md_through_save_resume_and_copies_files(self):
        con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        try:
            jid = db.add_job("Acme", "Data Engineer", jd="Python SQL CI pipelines")
            v = studio.build(use_ai=False, job_id=jid)
            job = db.get_job(jid)
            old = resume.app_dir(job) / "resume.pdf"
            old.write_bytes(b"%PDF-old")
            (resume.app_dir(job) / "resume.md").write_text("# old\n", encoding="utf-8")
            r = studio.use_for_job(v["vid"], jid)
            d = resume.app_dir(job)
            self.assertEqual((d / "resume.md").read_text(encoding="utf-8"), self.files(v, "md"))
            self.assertTrue(list((d / "history").glob("resume-*.md")))
            self.assertTrue((d / "resume.docx").is_file())
            self.assertFalse(old.exists())  # this version has no PDF: an older one must not stay beside the new text
            job = db.get_job(jid)
            self.assertIn("experience", json.loads(job["profile_rev"]))
            kinds = [e["kind"] for e in db.events(jid)]
            self.assertIn("coverage", kinds)
            self.assertIn(f"(studio {v['vid']})", next(e["detail"] for e in db.events(jid) if e["kind"] == "resume"))
            self.assertEqual(r["coverage"]["after"], job["match_score"])
        finally:
            shutil.rmtree(resume.APPS_DIR, ignore_errors=True)
            db._local.con.close()
            db._local.con = con


    def test_use_for_job_keeps_the_build_time_sections_and_a_locked_file_changes_nothing(self):
        import pathlib

        con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        run, _ = fake_pages([1])
        try:
            jid = db.add_job("Acme", "Data Engineer", jd="Python SQL CI pipelines")
            with patched(studio, _engine_pdf=run):
                v1, v2 = studio.build(use_ai=False, job_id=jid), studio.build(use_ai=False, job_id=jid, req={"drop": ["e3"]})
            for v, mark in ((v1, b"%PDF VERSION-ONE"), (v2, b"%PDF VERSION-TWO")):
                (studio.STUDIO / v["vid"] / v["files"]["pdf"]).write_bytes(mark)
            studio.use_for_job(v1["vid"], jid)
            d = resume.app_dir(db.get_job(jid))
            md, docx, h = (d / "resume.md").read_text(encoding="utf-8"), (d / "resume.docx").read_bytes(), db.get_job(jid)["resume_hash"]
            PROFILE.write_text(MASTER.replace("Cut deploy time 40%", "Cut deploy time 12%"), encoding="utf-8")  # after v2
            real = pathlib.Path.replace

            def locked(self, target):
                if self.name == "resume.pdf":  # open in a PDF reader
                    raise PermissionError(13, "in use")
                return real(self, target)

            pathlib.Path.replace = locked
            try:
                with self.assertRaises(SystemExit) as e:
                    studio.use_for_job(v2["vid"], jid)
            finally:
                pathlib.Path.replace = real
            self.assertIn("resume.pdf is open in another program", str(e.exception))
            self.assertEqual(((d / "resume.md").read_text(encoding="utf-8"), (d / "resume.docx").read_bytes(),
                              (d / "resume.pdf").read_bytes(), db.get_job(jid)["resume_hash"]), (md, docx, b"%PDF VERSION-ONE", h))
            self.assertEqual(list(d.glob("*.old")), [])
            studio.use_for_job(v2["vid"], jid)
            self.assertEqual((d / "resume.pdf").read_bytes(), b"%PDF VERSION-TWO")
            self.assertEqual(list(d.glob("*.old")), [])
            # v2 was built from the profile before the edit: the badge and the pipeline's Tailor step say so
            job = db.get_job(jid)
            self.assertEqual(profile.changed_sections(job["profile_rev"]), ["Experience"])
            self.assertIn("Experience", pipeline._profile_stale(job, {"_revs": profile.section_revs()}))
        finally:
            shutil.rmtree(resume.APPS_DIR, ignore_errors=True)
            db._local.con.close()
            db._local.con = con

    def test_an_edited_resume_md_never_leaves_an_old_pdf_beside_it(self):
        con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        try:
            jid = db.add_job("Acme", "Data Engineer", jd="Python SQL CI pipelines")
            job = db.get_job(jid)
            d = resume.app_dir(job)
            (d / "resume.md").write_text("# Dana\n## Experience\n- Cut deploy time 40%\n- Wrote the runbook\n", encoding="utf-8")
            (d / "resume.pdf").write_bytes(b"%PDF stale")
            resume.save_doc(job, "resume.md", "# Dana\n## Experience\n- Cut deploy time 40%\n")  # no PDF engine here
            self.assertFalse((d / "resume.pdf").exists())  # removed rather than attached saying the old thing
            self.assertFalse((d / "resume.html").exists())
            self.assertNotIn("runbook", "\n".join(p.text for p in __import__("docx").Document(str(d / "resume.docx")).paragraphs))

            def fake(html, pdf, browser=None):
                Path(pdf).write_bytes(b"%PDF " + Path(html).read_text(encoding="utf-8").encode()[-200:])
                return {"path": str(pdf), "method": "edge", "tried": []}

            (d / "resume.pdf").write_bytes(b"%PDF stale")
            with patched(resume, _browser=lambda: "msedge.exe", pdf_from_html=fake):
                resume._save_resume(job, "# Dana\n## Experience\n- Cut deploy time 41%\n", 0)  # tailor / bullets path
            self.assertNotEqual((d / "resume.pdf").read_bytes(), b"%PDF stale")  # printed again from the new text
            self.assertFalse((d / "resume.html").exists())
        finally:
            shutil.rmtree(resume.APPS_DIR, ignore_errors=True)
            db._local.con.close()
            db._local.con = con

    def test_tighten_needs_a_second_ai_call_in_the_budget(self):
        fake = self.ai({"sections": [{"kind": "experience", "items": ["e1", "e2", "e3"]}]},
                       tighten={"sections": [{"kind": "experience", "items": ["e1"]}]})
        run, calls = fake_pages([3, 3, 1])
        with patched(studio, _engine_pdf=run):
            v = studio.build(req={"pages": 1}, max_ai=1)  # a pipeline run with one call left
        self.assertEqual((v["ai_calls"], len(fake.prompts)), (1, 1))
        self.assertFalse(any("tightened" in e for e in v["events"]), v["events"])
        self.assertTrue(any(e.startswith("page limit: cut") for e in v["events"]), v["events"])


class Pipeline(Base):
    def test_tailor_step_runs_the_studio_and_is_stale_only_when_a_used_section_changed(self):
        con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.ai({"sections": [{"kind": "experience", "items": ["e1"]}, {"kind": "skills", "groups": [{"label": "Languages", "refs": ["k1"]}]}]})
        try:
            jid = db.add_job("Acme", "Data Engineer", jd="Python SQL")
            pipeline.skip(jid, "score")
            r = pipeline.run(jid, "tailor")
            self.assertEqual((r["outcome"], r["ai"]), ("done", 1))
            out = {e["name"]: e for e in pipeline.status(jid)}["tailor"]
            self.assertEqual(out["state"], "done")
            self.assertTrue(out["output"]["vid"])
            self.assertIn("Acme Corp", (pipeline._dir(db.get_job(jid)) / "resume.md").read_text(encoding="utf-8"))
            PROFILE.write_text(MASTER + "\n## Awards\n- Data Hero (2023)\n", encoding="utf-8")  # a section it did not use
            self.assertEqual({e["name"]: e for e in pipeline.status(jid)}["tailor"]["state"], "done")
            PROFILE.write_text(MASTER.replace("Wrote the on-call runbook", "Wrote the incident runbook"), encoding="utf-8")
            st = {e["name"]: e for e in pipeline.status(jid)}["tailor"]
            self.assertEqual(st["state"], "stale")
            self.assertIn("your profile changed since this was built (Experience)", st["why"])
        finally:
            shutil.rmtree(resume.APPS_DIR, ignore_errors=True)
            db._local.con.close()
            db._local.con = con

    def test_tailor_step_stays_within_the_runs_ai_budget(self):
        con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        fake = self.ai({"sections": [{"kind": "experience", "items": ["e1", "e2", "e3"]}]},
                       tighten={"sections": [{"kind": "experience", "items": ["e1"]}]})
        run, _ = fake_pages([3, 3, 1])
        try:
            jid = db.add_job("Acme", "Data Engineer", jd="Python SQL")
            pipeline.skip(jid, "score")
            with patched(studio, _engine_pdf=run):
                r = pipeline.run(jid, "tailor", budget=1)  # one call left today: the plan, then trim (no tighten call)
            self.assertEqual((r["outcome"], r["ai"], len(fake.prompts)), ("done", 1, 1))
        finally:
            shutil.rmtree(resume.APPS_DIR, ignore_errors=True)
            db._local.con.close()
            db._local.con = con


class Web(Base):
    def call(self, method, path, body=None, token=True, raw=False):
        import http.client

        from lodestar import web

        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"} | ({"X-Lodestar-Token": web.TOKEN} if token else {})
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        data = r.read()
        return r.status, (data if raw else json.loads(data))

    def setUp(self):
        super().setUp()
        from lodestar import desktop, web

        self.port = desktop.free_port(8980)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def test_build_view_open_use_delete_and_the_token(self):
        from lodestar import web

        self.ai({"sections": [{"kind": "experience", "items": ["e1"]}]})
        st, v = self.call("POST", "/api/run/studio_build", {"request": "one page", "req": {"accent": "navy"}})
        for _ in range(200):
            st, t = self.call("GET", f"/api/tasks/{v['task']}")
            if t["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(t["status"], "done", t)
        vid = t["result"]["vid"]
        st, s = self.call("GET", "/api/studio")
        self.assertEqual((st, s["versions"][0]["vid"], s["ai"]), (200, vid, True))
        self.assertIn({"id": "e1", "kind": "experience", "label": "Senior Engineer - Acme Corp, Austin, TX (2021-03 - Present)",
                       "on_file": False}, s["catalogue"])
        st, one = self.call("GET", f"/api/studio/{vid}")
        self.assertIn("<h1>Dana Smith</h1>", one["html"])
        self.assertEqual(one["style"]["accent"], "#1F3A5F")
        st, data = self.call("GET", f"/api/studio/{vid}/file?name={one['files']['md']}", raw=True)
        self.assertEqual((st, data.decode().replace("\r\n", "\n")), (200, one["md"]))
        for bad in (f"/api/studio/{vid}/file?name=../plan.json", "/api/studio/..%2F..%2Fprofile/file?name=x", "/api/studio/nope"):
            self.assertEqual(self.call("GET", bad)[0], 404, bad)
        opened = []
        with patched(web, _open_path=opened.append):
            self.assertEqual(self.call("POST", f"/api/studio/{vid}/open", {"file": "../../profile.md"})[0], 400)
            self.assertEqual(self.call("POST", f"/api/studio/{vid}/open", {"file": one["files"]["docx"]})[0], 200)
        self.assertEqual(opened, [studio.STUDIO / vid / one["files"]["docx"]])
        st, look = self.call("POST", f"/api/studio/{vid}/default_look", {})
        self.assertEqual(settings.pref("resume_look")["accent"], "#1F3A5F")
        for path in ("/api/studio", f"/api/studio/{vid}"):
            self.assertEqual(self.call("GET", path, token=False)[0], 403)
        for path in (f"/api/studio/{vid}/delete", "/api/run/studio_build"):
            self.assertEqual(self.call("POST", path, {}, token=False)[0], 403)
        self.assertTrue((studio.STUDIO / vid).is_dir())
        self.assertEqual(self.call("POST", f"/api/studio/{vid}/delete", {})[0], 200)
        self.assertFalse((studio.STUDIO / vid).exists())


class Cli(Base):
    def test_build_versions_and_catalogue(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["resume", "build", "--no-ai", "--pages", "1", "--accent", "teal", "--sections", "experience,skills",
                      "--format", "docx,txt"])
            cli.main(["resume", "versions"])
            cli.main(["resume", "catalogue"])
        text = out.getvalue()
        self.assertIn("(offline; ? page(s); no PDF engine)", text)
        self.assertIn("Dana-Smith-Resume.txt", text)
        self.assertIn("e2.b1 Built Kafka pipelines for billing events", text)
        v = studio.versions()[0]
        self.assertEqual(json.loads((studio.STUDIO / v["vid"] / "plan.json").read_text(encoding="utf-8"))["style"]["accent"], "#0F6E6E")
        with self.assertRaises(SystemExit):
            cli.main(["resume", "build", "--no-ai", "--font", "Comic Sans"])


@unittest.skipUnless(resume._browser(), "no Edge / Chrome / Chromium on this machine")
class Edge(Base):
    def test_real_edge_renders_a_one_page_studio_pdf(self):
        self.stack.close()  # the real engine this time
        self.stack = contextlib.ExitStack()
        with patched(resume, _word=lambda: False, _soffice=lambda: None):
            v = studio.build(use_ai=False, req={"pages": 1, "formats": "pdf,docx"})
        if "pdf" not in v["files"]:
            self.skipTest(f"the browser could not print here: {v['warnings']}")
        pdf = studio.STUDIO / v["vid"] / v["files"]["pdf"]
        data = pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual((v["pages"], v["engine"]), (1, resume.engine_name()))
        self.assertIn(b"/MediaBox [0 0 612 792]", data)
        self.assertEqual(lint.audit(data, pdf.name)["issues"], [])
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        text = " ".join(PdfReader(io.BytesIO(data)).pages[0].extract_text().split())
        self.assertIn("dana@example.com", text)
        self.assertIn("Senior Engineer - Acme Corp, Austin, TX Mar 2021 - Present", text)  # title first, then the dates
        self.assertFalse({"ﬁ", "ﬂ", "ﬃ"} & set(text))


if __name__ == "__main__":
    unittest.main()
