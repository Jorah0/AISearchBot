"""Pass 15, group B: JD coverage engine (ats.py), resume lint and file audit (lint.py), and their wiring."""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, ats, db, lint, profile, resume  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Jane Doe
Jane Doe | Austin, TX | jane@example.com | +1 512 555 0100

## Summary
Data engineer who builds reliable pipelines.

## Experience
### Data Engineer - Globex (2020-01 - Present)
- Built data pipelines in Python and SQL on AWS that cut compute costs 30%
- Ran Kubernetes (k8s) clusters serving 40 analysts

## Education
Master of Science, Computer Science, State University

## Skills
- Python, SQL, Airflow, Docker

## Preferences
Salary floor: 187k
"""
JD = """Acme is hiring a Data Engineer to build the Acme payments platform. You will design data pipelines in Python and SQL,
orchestrate with Apache Airflow, and run on AWS with Kubernetes. Requirements: Spark, dbt, Snowflake, strong communication.
You will own the payments platform end to end. Bachelor's degree in Computer Science or related field."""
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class Lexicon(unittest.TestCase):
    def test_data_file_is_sound(self):
        d = json.loads(ats.DATA.read_text(encoding="utf-8"))
        terms = [t for g in d["hard"].values() for t in g] + d["certifications"] + d["soft"] + [x[0] for x in d["degrees"]]
        self.assertTrue(800 <= len(terms) <= 1600, len(terms))
        self.assertEqual(len(terms), len(set(terms)), "a term is listed twice")
        self.assertEqual([t for t in terms + list(d["aliases"]) if t != t.lower()], [])
        self.assertEqual({k: v for k, v in d["aliases"].items() if v not in terms or k in terms}, {})
        self.assertAlmostEqual(sum(d["weights"].values()), 1.0)
        self.assertGreaterEqual(len(d["hard"]), 14)  # many fields, not just software
        for field in ("healthcare", "education", "trades", "finance", "legal", "customer_service"):
            self.assertIn(field, d["hard"])
        self.assertEqual(ats.DATA.parent.name, "data")  # beside the module, as the PyInstaller --add-data line expects


class Engine(unittest.TestCase):
    def kw(self, res, term):
        return next((k for k in res["keywords"] if k["term"] == term), None)

    def test_special_characters_and_boundaries(self):
        res = ats.match("C, ASP.NET MVC, Java and Excel", "C++ and C# on .NET with Node.js; JavaScript optional. MS Excel.")
        for t in ("c++", "c#", ".net", "node.js", "javascript", "excel"):
            self.assertIsNotNone(self.kw(res, t), t)
        self.assertEqual(self.kw(res, "javascript")["jd_count"], 1)  # "node.js" holds no "js"
        self.assertEqual(self.kw(res, "excel")["jd_count"], 1)       # "ms excel" is one mention, not two
        self.assertFalse(self.kw(res, "c++")["matched"])             # a bare "C" is not C++
        self.assertFalse(self.kw(res, ".net")["matched"])            # nor is ASP.NET a bare .NET mention
        self.assertTrue(self.kw(res, "excel")["matched"])
        self.assertIsNone(self.kw(res, "java"))                      # "javascript" does not mention Java

    def test_aliases_categories_and_weights(self):
        res = ats.match(MASTER, JD, "Senior Data Engineer II (Remote)", company="Acme")
        self.assertTrue(self.kw(res, "kubernetes")["matched"])       # k8s / Kubernetes
        self.assertTrue(self.kw(res, "airflow")["matched"])          # "Apache Airflow" in the JD
        self.assertFalse(self.kw(res, "apache spark")["matched"])
        self.assertEqual(self.kw(res, "communication")["kind"], "soft")
        self.assertEqual(res["title_match"], {"title": "data engineer", "found": True})
        self.assertEqual(res["education_required"], ["bachelor's degree"])
        self.assertEqual(res["categories"]["education"]["score"], 100)  # a master's covers a bachelor's requirement
        other = [k["term"] for k in res["keywords"] if k["kind"] == "other"]
        self.assertIn("payments platform", other)                    # repeated phrase the lexicon does not know
        self.assertFalse([t for t in other if "acme" in t])           # the company name is not a keyword
        self.assertTrue(0 <= res["score"] <= 100)
        self.assertNotIn("75", res["note"]); self.assertIn("not a pass/fail", res["note"])
        no_degree = ats.match(MASTER, "Python and SQL engineer. Python daily.")
        self.assertEqual(no_degree["categories"]["education"]["total"], 0)  # weight redistributed, not scored as 0
        self.assertEqual(no_degree["categories"]["title"]["total"], 0)
        self.assertEqual(no_degree["score"], 100)
        self.assertEqual(ats.match("", "nothing known here at all")["score"], 0)
        self.assertEqual(ats.core_title("Sr. Software Engineer, Backend (m/f/d)"), "software engineer")

    def test_skip_leaves_the_denominator_and_stuffing(self):
        base = ats.match(MASTER, JD, "Data Engineer")
        skipped = ats.match(MASTER, JD, "Data Engineer", skip=["apache spark", "dbt", "snowflake"])
        self.assertGreater(skipped["score"], base["score"])
        self.assertEqual(skipped["categories"]["hard"]["total"], base["categories"]["hard"]["total"] - 3)
        self.assertTrue(self.kw(skipped, "dbt")["skipped"])           # still listed, so it can be toggled back
        stuffed = ats.match("python " * 8 + "sql", "We use Python and SQL.")
        self.assertEqual(stuffed["stuffing"], ["python"])
        self.assertEqual(ats.canonical("K8s"), "kubernetes")


class MemDb(unittest.TestCase):
    """In-memory database on this thread, a real profile, and fresh job folders; all put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self._profile = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else None
        PROFILE.write_text(MASTER, encoding="utf-8")
        self.real = (ai.available, ai.ask, ai.ask_json)

    def tearDown(self):
        ai.available, ai.ask, ai.ask_json = self.real
        db._local.con.close()
        db._local.con = self._con
        if self._profile is None:
            PROFILE.unlink(missing_ok=True)
        else:
            PROFILE.write_text(self._profile, encoding="utf-8")

    def job(self, company="Covco", title="Data Engineer", jd=JD):
        jid = db.add_job(company, title, jd=jd)
        shutil.rmtree(resume.app_dir(db.get_job(jid)), ignore_errors=True)  # ids restart per in-memory db
        return db.get_job(jid)


class Wiring(MemDb):
    def test_gap_without_a_provider_still_scores_coverage(self):
        ai.available = lambda: []
        ai.ask_json = lambda *a, **k: self.fail("no AI call without a provider")
        j = self.job()
        g = resume.gap(j)
        self.assertIn("coverage", g); self.assertIn("note", g)
        self.assertNotIn("187k", json.dumps(g["coverage"]))
        saved = json.loads((resume.app_dir(j) / "gap.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["coverage"]["score"], g["coverage"]["score"])
        self.assertEqual(db.get_job(j["id"])["match_score"], g["coverage"]["score"])
        self.assertIn("apache spark", g["missing_keywords"])

    def test_gap_hands_the_missing_table_to_the_ai_and_keeps_its_verdict(self):
        prompts = []
        ai.ask_json = lambda p, *a, **k: prompts.append(p) or {"match_score": 3, "verdict": "stretch", "why": "no Spark", "suggestions": ["x"]}
        j = self.job()
        g = resume.gap(j)
        self.assertIn("apache spark (hard, 1x in the posting)", prompts[0])
        self.assertIn("187k", prompts[0])                            # the private fit check still weighs the floor
        self.assertEqual((g["verdict"], g["why"]), ("stretch", "no Spark"))
        self.assertEqual(g["match_score"], g["coverage"]["score"])   # the AI's own number does not replace coverage
        boom = SystemExit("No AI provider configured")
        ai.ask_json = lambda *a, **k: (_ for _ in ()).throw(boom)
        j2 = self.job("Covco Two")
        with self.assertRaises(SystemExit):
            resume.gap(j2)
        self.assertIsNotNone(db.get_job(j2["id"])["match_score"])     # coverage was saved before the AI part failed

    def test_tailor_rescores_and_logs_the_change(self):
        tailored = MASTER.split("## Preferences")[0] + "- Spark, dbt, Snowflake; strong communication\n"
        ai.ask = lambda p, *a, **k: tailored
        j = self.job()
        before = resume.coverage(j, save=False)["score"]
        resume.tailor(j)
        after = db.get_job(j["id"])["match_score"]
        self.assertGreater(after, before)
        self.assertIn(f"coverage {before} -> {after}", [e["detail"] for e in db.events(j["id"]) if e["kind"] == "coverage"])
        self.assertEqual(resume.coverage(db.get_job(j["id"]))["score"], after)  # the tailored resume is what gets scored now

    def test_skip_toggle_persists_per_job(self):
        j = self.job()
        before = resume.coverage(j)["score"]
        cov = resume.toggle_skip(j, "Spark")                          # an alias resolves to the listed term
        self.assertEqual(db.ats_skip(db.get_job(j["id"])), ["apache spark"])
        self.assertGreater(cov["score"], before)
        self.assertEqual(resume.toggle_skip(db.get_job(j["id"]), "apache spark")["score"], before)
        self.assertEqual(db.ats_skip(db.get_job(j["id"])), [])
        for bad in ("", "x" * 81):
            with self.assertRaises(SystemExit):
                db.toggle_ats_skip(j["id"], bad)

    def test_review_passes_the_lint_results(self):
        prompts = []
        ai.ask = lambda p, *a, **k: prompts.append(p) or "ok"
        resume.review("- Responsible for things\n")
        self.assertIn("weak opener", prompts[0]); self.assertIn("no email", prompts[0])

    def test_cli_parses(self):
        a = build().parse_args(["match", "3", "--file", "cv.docx", "--skip", "k8s"])
        self.assertEqual((a.id, a.file, a.skip), (3, "cv.docx", ["k8s"]))
        self.assertEqual(build().parse_args(["resume", "lint", "--job", "4"]).job, 4)
        self.assertEqual(build().parse_args(["resume", "audit", "cv.pdf"]).file, "cv.pdf")


class Lint(unittest.TestCase):
    def rules(self, text):
        return [(i["rule"], i["line"]) for i in lint.lint(text)["issues"]]

    def test_line_checks(self):
        text = """# Sam Lee
Sam Lee | Leeds | sam@example.com | +44 113 496 0000
## Summary
I am a results-driven team player.
## Experience
### Analyst - Initech (2016-01 - 2018-03)
- Responsible for weekly reports
- The migration was completed by the team in 3 weeks
- Managed 4 vendors
- Managed a budget of $2M
- Managed hiring for 6 roles
- Delivered """ + " ".join(["word"] * 40) + """ 5
### Lead - Globex (2019-06 - Present)
- Ok
## Skills
- Excel, SQL
## Education
BA Economics, 1985
## Preferences
I want 100k
"""
        r = self.rules(text)
        for rule, line in (("pronoun", 4), ("cliche", 4), ("weak_opener", 7), ("no_metric", 7), ("passive", 8),
                           ("repeated_verb", 9), ("long", 12), ("short", 14), ("gap", 13)):
            self.assertIn((rule, line), r, rule)
        self.assertFalse([x for x in r if x[1] >= 15 and x[0] != "gap"])  # skills lists, education and Preferences pass
        self.assertFalse([x for x in r if x[0] in ("no_email", "no_phone", "missing_section")])
        res = lint.lint(text)
        self.assertEqual(res["issues"][0]["severity"], "medium")         # sorted by severity
        self.assertTrue(0 <= res["score"] < 100)

    def test_document_checks(self):
        r = self.rules("Just some text\n- Built things that saved 5 hours\n")
        for rule in ("no_email", "no_phone", "missing_section"):
            self.assertIn((rule, 0), r)
        self.assertEqual(lint.lint(resume.PROFILE_TEMPLATE)["counts"]["high"], 0)


class Audit(unittest.TestCase):
    def export(self, md: str) -> bytes:
        d = tempfile.mkdtemp(prefix="lodestar-audit-")
        p = os.path.join(d, "resume.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)
        return resume.export_docx(p).read_bytes()

    def test_lodestar_export_is_clean(self):
        r = lint.audit(self.export(MASTER.split("## Preferences")[0]), "resume.docx")
        self.assertEqual(r["issues"], [], r["issues"])
        self.assertIn("jane@example.com", r["text"])                  # what a parser sees: the importer's text

    def test_crafted_bad_docx(self):
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt

        d = Document()
        d.sections[0].header.paragraphs[0].text = "Jane Doe  jane@example.com  +1 512 555 0100"
        d.add_heading("Jane Doe", 0); d.add_heading("My Journey", 1)
        d.add_paragraph().add_run("tiny print").font.size = Pt(8)
        d.add_table(rows=1, cols=2).cell(0, 0).text = "Python"
        d.add_picture(io.BytesIO(PNG))
        cols = OxmlElement("w:cols"); cols.set(qn("w:num"), "2"); d.sections[0]._sectPr.append(cols)
        buf = io.BytesIO(); d.save(buf)
        src, out = zipfile.ZipFile(io.BytesIO(buf.getvalue())), io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:  # add a text box the way Word writes one
            for n in src.namelist():
                x = src.read(n)
                if n == "word/document.xml":
                    x = x.replace(b"</w:body>", b'<w:p><w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>'
                                  b"<w:txbxContent><w:p><w:r><w:t>Skills</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p></w:body>")
                z.writestr(n, x)
        rules = {i["rule"] for i in lint.audit(out.getvalue(), "resume final (1).docx")["issues"]}
        self.assertEqual(rules, {"contact_in_header", "text_boxes", "no_email_in_body", "tables", "columns", "images",
                                 "small_font", "heading", "filename"})

    def test_pdf_and_bad_input(self):
        scanned = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                   b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</XObject<</Im0 4 0 R>>>>>>endobj\n"
                   b"4 0 obj<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray/BitsPerComponent 8/Length 1>>"
                   b"stream\n\x00\nendstream endobj\n%" + b"0" * 2_100_000 + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n")
        r = lint.audit(scanned, "Jane-Doe-Resume.pdf")
        rules = {i["rule"] for i in r["issues"]}
        self.assertTrue({"images", "size"} <= rules, rules)
        import importlib.util
        if importlib.util.find_spec("pypdf") is None:  # optional: the text checks are skipped with a note, the rest still run
            self.assertIn("skipped", r["note"])
        else:
            from pypdf import PdfWriter

            self.assertIn("unreadable", rules)  # a PDF pypdf cannot open is a finding, not a crash
            w, buf = PdfWriter(), io.BytesIO()
            w.add_blank_page(612, 792); w.write(buf)
            self.assertIn("no_text_layer", {i["rule"] for i in lint.audit(buf.getvalue(), "Jane-Doe-Resume.pdf")["issues"]})
        for data, name in ((b"hello", "cv.txt"), (b"not a zip", "cv.docx"), (b"nope", "cv.pdf")):
            with self.assertRaises(SystemExit):
                lint.audit(data, name)


class Web(unittest.TestCase):
    """The routes, on the real temp-home database the server threads use."""

    def test_routes(self):
        import http.client
        import time

        from lodestar import desktop, web

        saved_con = getattr(db._local, "con", None)
        db._local.con = db.connect()
        snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        jid = db.add_job("Webco", "Data Engineer", jd=JD)
        port = desktop.free_port(8890); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def call(path, body):
                c.request("POST", path, json.dumps(body), h); r = c.getresponse(); return r.status, json.loads(r.read())

            def task(action, body):
                st, v = call(f"/api/run/{action}", body)
                for _ in range(80):
                    c.request("GET", f"/api/tasks/{v['task']}", headers=h); t = json.loads(c.getresponse().read())
                    if t["status"] != "running":
                        return t
                    time.sleep(0.05)

            t = task("match", {"id": jid})
            self.assertEqual(t["status"], "done", t)
            score = t["result"]["coverage"]["score"]
            self.assertIn("coverage.json", t["result"]["docs"])          # its own file: gap.json means a gap check ran
            self.assertNotIn("gap.json", t["result"]["docs"])
            st, v = call(f"/api/jobs/{jid}/skip", {"term": "dbt"})
            self.assertEqual(st, 200, v); self.assertGreater(v["coverage"]["score"], score)
            self.assertEqual(call(f"/api/jobs/{jid}/skip", {"term": ""})[0], 400)
            t = task("lint", {"text": "- Helped with stuff"})
            self.assertIn("weak_opener", [i["rule"] for i in t["result"]["issues"]])
            self.assertEqual(task("lint", {"text": "  "})["status"], "error")
            self.assertIn("Tailor", task("audit", {"id": jid})["error"])
            resume.export_docx(resume.write_doc(resume.app_dir(db.get_job(jid)) / "resume.md", MASTER.split("## Preferences")[0]))
            t = task("audit", {"id": jid})
            self.assertEqual((t["status"], t["result"]["issues"]), ("done", []), t)
            buf = io.BytesIO(); from docx import Document; d = Document(); d.add_paragraph("Jane jane@example.com"); d.add_table(rows=1, cols=1); d.save(buf)
            profile.import_file(buf.getvalue(), "Jane-Doe-Resume.docx", use_ai=False)
            t = task("audit", {})
            self.assertEqual(t["status"], "done", t)
            self.assertEqual(t["result"]["file"], "Jane-Doe-Resume.docx")
            self.assertIn("tables", [i["rule"] for i in t["result"]["issues"]])
        finally:
            srv.shutdown()
            shutil.rmtree(resume.app_dir(db.get_job(jid)), ignore_errors=True)
            db.delete_job(jid)
            for p in (PROFILE, profile.BANK):
                p.write_bytes(snap[p]) if p in snap else p.unlink(missing_ok=True)
            db._local.con.close()
            db._local.con = saved_con


if __name__ == "__main__":
    unittest.main()
