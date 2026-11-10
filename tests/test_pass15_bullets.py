"""Pass 15, group C: bullet-level tailoring with no-invention guards, tailoring from a saved resume, .docx styles and
PDF export (Word, LibreOffice, or an HTML print page)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, db, lint, profile, resume, settings  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Master Resume  (edit me - keep EVERYTHING here; lodestar trims per job)

## Contact
Jane Doe | Austin, TX | jane@example.com | +1 512 555 0100

## Experience
### Data Engineer - Globex (2020-01 - Present)
- Built data pipelines in Python and SQL on AWS that cut compute costs 30%
- Ran Kubernetes clusters serving 40 analysts
- Organised the team picnic

### Analyst - Initech (2017-01 - 2019-12)
- Wrote weekly SQL reports for 3 directors

## Skills
- Python, SQL, Airflow, Docker, Spark

## Preferences
Salary floor: 187k
"""
JD = "Build data pipelines with Apache Spark, Airflow and Snowflake on AWS. Kubernetes. dbt. Weekly reporting."
REPLY = {"bullets": [
    {"id": 1, "proposed": "Built Spark data pipelines in Python and SQL on AWS that cut compute costs 30%",
     "added_terms": ["Spark"], "reason": "Spark is in your skills"},
    {"id": 2, "proposed": "Ran Kubernetes and Snowflake clusters serving 45 analysts", "added_terms": [], "reason": "x"},
    {"id": 3, "drop": True, "reason": "not relevant"},
    {"id": 4, "proposed": "Wrote weekly SQL reports for 3 directors", "added_terms": []}],
    "order": [2, 1, 3, 4]}


class Base(unittest.TestCase):
    """In-memory database, a known profile and an empty bank; all put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        self.real = (ai.ask, ai.ask_json, resume._word, resume._soffice, subprocess.run, settings.pref("resume_style"),
                     resume._browser)
        resume._browser = lambda: None  # no headless Edge here: these tests pin the Word / LibreOffice / HTML paths
        self.prompts = []
        ai.ask_json = lambda p, *a, **k: self.prompts.append(p) or json.loads(json.dumps(REPLY))

    def tearDown(self):
        ai.ask, ai.ask_json, resume._word, resume._soffice, subprocess.run, style, resume._browser = self.real
        settings.set_pref("resume_style", style)
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def job(self, company="Bulco"):
        jid = db.add_job(company, "Data Engineer", jd=JD)
        shutil.rmtree(resume.app_dir(db.get_job(jid)), ignore_errors=True)  # ids restart per in-memory db
        return db.get_job(jid)


class Bullets(Base):
    def test_guards_flag_invention_and_flagged_rows_start_rejected(self):
        j = self.job()
        data = resume.tailor_bullets(j)
        rows = {r["id"]: r for r in data["proposals"]}
        self.assertNotIn("187k", self.prompts[0])                       # employer-facing source: no salary floor
        self.assertIn("snowflake", self.prompts[0])                     # the missing keywords are handed over
        self.assertEqual(rows[1]["flags"], []); self.assertTrue(rows[1]["accepted"])
        self.assertEqual(rows[1]["added_terms"], ["apache spark"])     # supported: Spark is in the Skills section
        self.assertEqual(rows[1]["proposed"][slice(*rows[1]["marks"][0])], "Spark")
        r2 = rows[2]                                                    # undeclared Snowflake + a number that grew
        self.assertEqual((r2["flags"], r2["unsupported"], r2["new_numbers"]), (["unsupported", "new number"], ["snowflake"], ["45"]))
        self.assertFalse(r2["accepted"])
        self.assertTrue(rows[3]["drop"] and rows[3]["changed"] and rows[3]["proposed"] == "")
        self.assertFalse(rows[4]["changed"])
        self.assertEqual([r["id"] for r in data["proposals"]], [2, 1, 3, 4])  # suggested order, each role kept together
        saved = json.loads((resume.app_dir(j) / "bullets.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["proposals"]), 4)
        self.assertNotIn("187k", saved["source"])

    def test_apply_builds_from_accepted_rows_and_logs_coverage(self):
        j = self.job()
        resume.tailor_bullets(j)
        resume.write_doc(resume.app_dir(j) / "resume.md", "# old resume\n")
        r = resume.apply_bullets(db.get_job(j["id"]), "unflagged", docx=True)
        md = (resume.app_dir(j) / "resume.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Jane Doe\n"))                   # not "# Master Resume"
        self.assertIn("- Ran Kubernetes clusters serving 40 analysts\n- Built Spark data pipelines", md)  # reordered
        self.assertNotIn("picnic", md)                                   # accepted drop
        self.assertNotIn("Snowflake", md); self.assertNotIn("Preferences", md); self.assertNotIn("On file", md)
        self.assertEqual(r["accepted"], [1, 3])
        self.assertTrue(list((resume.app_dir(j) / "history").glob("resume-*.md")))  # the previous version is kept
        self.assertTrue((resume.app_dir(j) / "resume.docx").is_file())
        self.assertIn(f"coverage {r['coverage']['before']} -> {r['coverage']['after']}",
                      [e["detail"] for e in db.events(j["id"]) if e["kind"] == "coverage"])
        self.assertEqual(db.get_job(j["id"])["match_score"], r["coverage"]["after"])
        resume.apply_bullets(db.get_job(j["id"]), "2")                  # an explicit pick overrides a flag
        self.assertIn("serving 45 analysts", (resume.app_dir(j) / "resume.md").read_text(encoding="utf-8"))
        self.assertIn("picnic", (resume.app_dir(j) / "resume.md").read_text(encoding="utf-8"))
        for bad in ("9", "x,1"):
            with self.assertRaises(SystemExit):
                resume.apply_bullets(db.get_job(j["id"]), bad)
        with self.assertRaises(SystemExit):
            resume.apply_bullets(self.job("Nobullets"), "all")           # no bullets.json yet

    def test_tailor_from_a_saved_resume(self):
        saved = b"# Jane Doe\njane@example.com | +1 512 555 0100\n\n## Experience\n### Consultant - Hooli (2015 - 2016)\n- Advised 12 clients on data platforms\n"
        rid = profile.import_file(saved, "Jane-Consulting.md", use_ai=False)["resume"]["id"]
        self.assertIn(rid, [b["id"] for b in profile.saved_resumes()])
        j = self.job()
        data = resume.tailor_bullets(j, base=rid)
        self.assertEqual([r["original"] for r in data["proposals"]][:1], ["Advised 12 clients on data platforms"])
        self.assertEqual(data["base"], rid)
        seen = []
        ai.ask = lambda p, *a, **k: seen.append(p) or "# Jane Doe\n- Advised 12 clients\n"
        resume.tailor(j, base=rid)
        self.assertIn("BASE RESUME", seen[0]); self.assertIn("Hooli", seen[0]); self.assertNotIn("187k", seen[0])
        with self.assertRaises(SystemExit):
            resume.tailor_bullets(j, base="nope1234")

    def test_cli_parses(self):
        a = build().parse_args(["resume", "tailor", "3", "--bullets", "--base", "ab12cd34"])
        self.assertEqual((a.id, a.bullets, a.base, a.accept), (3, True, "ab12cd34", None))
        self.assertEqual(build().parse_args(["resume", "tailor", "3", "--accept", "1,3"]).accept, "1,3")
        a = build().parse_args(["resume", "export", "3", "--pdf", "--style", "modern"])
        self.assertEqual((a.file, a.pdf, a.style), ("3", True, "modern"))


class Export(Base):
    def md(self) -> str:
        p = resume.app_dir(self.job()) / "resume.md"
        p.write_text(resume._employer_copy(resume.candidate_text(private=False)), encoding="utf-8")
        return str(p)

    def test_every_style_passes_the_file_audit(self):
        md = self.md()
        for style in resume.STYLES:
            r = lint.audit(resume.export_docx(md, style).read_bytes(), "Jane-Doe-Resume.docx")
            self.assertEqual(r["issues"], [], (style, r["issues"]))
        self.assertEqual(tuple(resume.STYLES), settings.CHOICES["resume_style"])
        settings.set_pref("resume_style", "compact")
        with self.assertRaises(SystemExit):
            settings.set_pref("resume_style", "fancy")
        self.assertEqual(settings.pref("resume_style"), "compact")

    def test_pdf_falls_back_to_an_html_print_page(self):
        md = self.md()
        resume._word, resume._soffice = (lambda: False), (lambda: None)
        r = resume.export_pdf(md, open_html=False)
        self.assertEqual(r["method"], "html")
        page = Path(r["path"]).read_text(encoding="utf-8")
        self.assertIn("<title>Jane Doe</title>", page); self.assertIn("@media print", page)
        self.assertIn("<li>Ran Kubernetes clusters serving 40 analysts</li>", page)
        self.assertNotIn("<table", page)

    def test_pdf_converters_are_called_safely(self):
        md = self.md()
        calls = []

        def fake(cmd, **kw):
            calls.append((cmd, kw))
            Path(md).with_suffix(".pdf").write_bytes(b"%PDF-1.4")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        subprocess.run = fake
        resume._word, resume._soffice = (lambda: True), (lambda: None)
        r = resume.export_pdf(md, open_html=False)
        self.assertEqual(r["method"], "word")
        script = calls[0][0][-1]
        self.assertNotIn(md[:-3], script)                                # paths travel in env vars, not in the script
        self.assertTrue(calls[0][1]["env"]["LS_OUT"].endswith("resume.pdf"))
        self.assertEqual(calls[0][1]["timeout"], 120)
        resume._word, resume._soffice = (lambda: False), (lambda: "soffice")
        self.assertEqual(resume.export_pdf(md, open_html=False)["method"], "libreoffice")
        self.assertEqual(calls[1][0][:4], ["soffice", "--headless", "--convert-to", "pdf"])
        subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "Word said no")  # writes nothing
        resume._word = lambda: True
        resume._soffice = lambda: None
        r = resume.export_pdf(md, open_html=False)
        self.assertEqual(r["method"], "html")
        self.assertIn("Word said no", r["tried"][0])
        with self.assertRaises(SystemExit):
            resume.export_pdf(md.replace("resume.md", "missing.md"), open_html=False)


class Web(unittest.TestCase):
    def test_routes(self):
        import http.client
        import time
        import webbrowser

        from lodestar import desktop, web

        saved_con = getattr(db._local, "con", None)
        db._local.con = db.connect()
        snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK) if p.is_file()}
        real = (ai.ask_json, resume._word, resume._soffice, webbrowser.open, resume._browser)
        PROFILE.write_text(MASTER, encoding="utf-8")
        ai.ask_json = lambda *a, **k: json.loads(json.dumps(REPLY))
        opened = []
        resume._word, resume._soffice, webbrowser.open = (lambda: False), (lambda: None), opened.append
        resume._browser = lambda: None
        jid = db.add_job("Bulweb", "Data Engineer", jd=JD)
        port = desktop.free_port(8900); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def task(action, body):
                c.request("POST", f"/api/run/{action}", json.dumps(body), h); v = json.loads(c.getresponse().read())
                for _ in range(100):
                    c.request("GET", f"/api/tasks/{v['task']}", headers=h); t = json.loads(c.getresponse().read())
                    if t["status"] != "running":
                        return t
                    time.sleep(0.05)

            c.request("GET", "/api/state", headers=h); st = json.loads(c.getresponse().read())
            self.assertEqual(st["pref_choices"]["resume_style"], list(resume.STYLES)); self.assertIn("bases", st)
            self.assertIn("tailor a resume first", task("export_pdf", {"id": jid})["error"])
            t = task("bullets", {"id": jid})
            self.assertEqual(t["status"], "done", t)
            self.assertIn("bullets.json", t["result"]["docs"])
            t = task("bullets_apply", {"id": jid, "accept": [1, 2]})
            self.assertEqual((t["status"], t["result"]["accepted"]), ("done", [1, 2]), t)
            self.assertIn("resume.md", t["result"]["docs"])
            t = task("export_pdf", {"id": jid})
            self.assertEqual(t["result"]["method"], "html", t)
            self.assertTrue(opened and opened[0].startswith("file:"))
        finally:
            srv.shutdown()
            ai.ask_json, resume._word, resume._soffice, webbrowser.open, resume._browser = real
            shutil.rmtree(resume.app_dir(db.get_job(jid)), ignore_errors=True)
            db.delete_job(jid)
            for p in (PROFILE, profile.BANK):
                p.write_bytes(snap[p]) if p in snap else p.unlink(missing_ok=True)
            db._local.con.close()
            db._local.con = saved_con


if __name__ == "__main__":
    unittest.main()
