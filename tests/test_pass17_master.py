"""Pass 17, builder 1: the profile-synced master resume (studio.sync_master: fingerprint, debounced background rebuild,
change summary, failures kept in master.json), the 'profile changed' badge on tailored resumes (only for sections the
resume used), and the headless Chromium PDF engine (Edge first; never trusting its exit code)."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, db, profile, resume, studio, web  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

MASTER = """# Master Resume
## Contact
Dana Smith | Austin, TX | dana@example.com

## Summary
Data engineer who ships.

## Experience
### Senior Engineer - Acme Corp (2021-03 - Present)
- Cut deploy time 40%

## Skills
- Python, SQL

## Preferences
Salary floor: $150,000
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


def fake_pdf(calls=None, gate=None, pages=1):
    """A PDF engine stand-in: writes a small real-looking PDF where pdf_from_html is told to."""
    def run(html, pdf, browser=None):
        if calls is not None:
            calls.append(Path(html).name)
        if gate is not None:
            gate.wait(5)
        Path(pdf).write_bytes(b"%PDF-1.4\n" + b"/Type /Page\n" * pages + b"x" * 2000)
        return {"path": str(pdf), "method": "edge", "tried": []}
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK) if p.is_file()}
        PROFILE.write_text(MASTER, encoding="utf-8")
        profile.BANK.unlink(missing_ok=True)
        self.clean()
        self.real = (studio.AUTO, resume._browser, resume.pdf_from_html, studio.DELAY)
        studio.AUTO = False
        resume._browser = lambda: "C:/fake/msedge.exe"
        self.calls = []
        resume.pdf_from_html = fake_pdf(self.calls)

    def tearDown(self):
        studio.AUTO, resume._browser, resume.pdf_from_html, studio.DELAY = self.real
        self.clean()
        for p in (PROFILE, profile.BANK):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def clean(self):
        for f in profile.RESUMES.glob("master.*") if profile.RESUMES.is_dir() else []:
            f.unlink()


class Rev(Base):
    def test_profile_rev_changes_on_master_and_bank_writes_only(self):
        r0 = profile.profile_rev()
        profile.write_master(MASTER.replace("ships.", "ships fast."))
        r1 = profile.profile_rev()
        self.assertNotEqual(r0, r1)
        profile.add("skills", "Rust")
        r2 = profile.profile_rev()
        self.assertNotEqual(r1, r2)
        profile.remove("skills", "Haskell")  # nothing to remove: saves anyway, same facts
        self.assertEqual(profile.profile_rev(), r2)
        profile.write_master(MASTER.replace("$150,000", "$160,000"))  # Preferences are never part of it
        self.assertEqual(profile.section_revs().keys(), profile.section_revs().keys())
        r3 = profile.profile_rev()
        profile.write_master(MASTER.replace("$150,000", "$170,000"))
        self.assertEqual(profile.profile_rev(), r3)

    def test_profile_rev_tolerates_a_floor_leak_and_never_creates_profile_md(self):
        PROFILE.write_text(MASTER.replace("## Summary", "## Summary\nMy salary floor is $150,000"), encoding="utf-8")
        self.assertTrue(profile.profile_rev())  # no SystemExit: it runs inside every board refresh
        self.assertIn("jobs", web.state())
        PROFILE.unlink()
        self.assertTrue(profile.profile_rev())
        self.assertFalse(PROFILE.exists())


class Sync(Base):
    def test_sync_writes_files_meta_and_diff(self):
        m = studio.sync_master()
        self.assertEqual(m["rev"], profile.profile_rev())
        self.assertEqual(sorted(studio.files()), ["docx", "md", "pdf", "txt"])
        md = (profile.RESUMES / "master.md").read_text(encoding="utf-8")
        self.assertTrue(md.startswith("# Dana Smith"))
        self.assertNotIn("Salary floor", md)  # Preferences never reach the master resume
        self.assertIn("CUT DEPLOY TIME", (profile.RESUMES / "master.txt").read_text(encoding="utf-8").upper())
        self.assertEqual((m["engine"], m["pages"], m["diff"], m["last_error"]), ("edge", 1, ["first build"], ""))
        profile.write_master(MASTER.replace("- Cut deploy time 40%", "- Cut deploy time 40%\n- Led a team of 4")
                             .replace("- Python, SQL", "- Python, SQL, Rust"))
        m = studio.sync_master()
        self.assertIn("+1 bullet in Acme Corp", m["diff"])
        self.assertIn("skills +Rust", m["diff"])
        self.assertEqual(len(m["history"]), 2)
        self.assertFalse(studio.master_status()["stale"])

    def test_no_change_makes_no_render_and_bank_only_change_only_updates_rev(self):
        studio.sync_master()
        n = len(self.calls)
        studio.sync_master()
        self.assertEqual(len(self.calls), n)  # not stale: the engine is not called
        profile.add("languages", "Spanish", "Native")  # bank only: 'On file' is not part of the master resume
        self.assertTrue(studio.master_status()["stale"])
        m = studio.sync_master()
        self.assertEqual(len(self.calls), n)
        self.assertEqual(m["rev"], profile.profile_rev())

    def test_debounce_keeps_one_daemon_timer_and_auto_off_starts_none(self):
        made = []

        class Rec:
            def __init__(self, delay, fn):
                self.delay, self.fn, self.cancelled, self.daemon = delay, fn, False, False
                made.append(self)

            def start(self):
                pass

            def cancel(self):
                self.cancelled = True

        with patched(threading, Timer=Rec), patched(studio, _TIMER=None):
            profile._changed()
            self.assertEqual(made, [])  # AUTO off (tests, CLI, web.start_server): no timer at all
            studio.AUTO = True
            for _ in range(5):
                profile._changed()
            live = [t for t in made if not t.cancelled]
            self.assertEqual((len(made), len(live), live[0].daemon, live[0].delay), (5, 1, True, studio.DELAY))
            live[0].fn()  # the timer firing: one build
        self.assertEqual(studio.meta()["rev"], profile.profile_rev())

    def test_status_says_a_rebuild_is_pending_so_the_card_can_follow_it(self):
        t = threading.Timer(600, lambda: None)
        t.daemon = True
        with patched(studio, _TIMER=None):
            self.assertFalse(studio.master_status()["pending"])
            studio._TIMER = t
            t.start()
            try:
                self.assertTrue(studio.master_status()["pending"])  # the card shows 'building shortly' and polls
            finally:
                t.cancel()
                t.join()
            self.assertFalse(studio.master_status()["pending"])
        with studio._SYNC:  # a build running now (Update now, the loop)
            self.assertTrue(studio.master_status()["pending"])
        js = (Path(studio.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("if (tab === 'profile') loadMaster();", js)  # the card refreshes when the tab is shown
        self.assertIn("m.pending ? setTimeout(loadMaster", js)

    def test_a_trigger_during_a_build_reruns_once(self):
        gate, started, builds = threading.Event(), threading.Event(), []
        real_build = studio._build

        def build(force):
            builds.append(force)
            if len(builds) == 1:
                started.set()
                gate.wait(5)
            return real_build(force)
        with patched(studio, _build=build):
            t = threading.Thread(target=studio.sync_master)
            t.start()
            started.wait(5)
            profile.write_master(MASTER.replace("ships.", "ships often."))
            self.assertTrue(studio.sync_master().get("busy"))  # returns at once
            gate.set()
            t.join(10)
        self.assertEqual(len(builds), 2)  # exactly one rerun
        self.assertIn("ships often.", (profile.RESUMES / "master.md").read_text(encoding="utf-8"))

    def test_rev_race_leaves_the_master_stale(self):
        def edits_mid_build(html, pdf, browser=None):
            PROFILE.write_text(MASTER.replace("ships.", "ships later."), encoding="utf-8")
            return fake_pdf()(html, pdf)
        with patched(resume, pdf_from_html=edits_mid_build):
            m = studio.sync_master()
        self.assertNotEqual(m["rev"], profile.profile_rev())
        self.assertTrue(studio.master_status()["stale"])  # the next trigger builds the edit

    def test_failures_set_last_error_and_keep_the_old_rev(self):
        good = studio.sync_master()
        old_pdf = (profile.RESUMES / "master.pdf").read_bytes()
        profile.write_master(MASTER.replace("ships.", "ships again."))

        def boom(*a, **k):
            raise SystemExit("the engine fell over")
        with patched(resume, pdf_from_html=boom, _word=lambda: False, _soffice=lambda: None,
                     export_pdf=lambda *a, **k: boom()):
            m = studio.sync_master()
        self.assertEqual((m["rev"], m["last_error"]), (good["rev"], "could not build the master resume: the engine fell over"))
        self.assertEqual((profile.RESUMES / "master.pdf").read_bytes(), old_pdf)
        real_replace = os.replace

        def locked(src, dst):
            if str(dst).endswith("master.pdf"):
                raise PermissionError(13, "in use", str(src), None, str(dst))
            return real_replace(src, dst)
        with patched(os, replace=locked):
            m = studio.sync_master()
        self.assertIn("close master.pdf", m["last_error"])
        self.assertEqual(m["rev"], good["rev"])
        self.assertNotIn("ships again.", (profile.RESUMES / "master.md").read_text(encoding="utf-8"))  # md is replaced last
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")
        self.assertIn("fill in your profile first", studio.sync_master()["last_error"])
        PROFILE.unlink()
        self.assertIn("fill in your profile first", studio.sync_master()["last_error"])
        self.assertFalse(PROFILE.exists())  # never created as a side effect
        PROFILE.write_text(MASTER.replace("## Preferences", "## Notes\nCall Bob about the referral\n\n## Preferences"),
                           encoding="utf-8")
        m = studio.sync_master()
        self.assertEqual(m["last_error"], "")
        self.assertIn("'## Notes' is in your master resume: move it under Preferences if it is private", m["warnings"])
        studio.AUTO = True  # the timer path never raises
        with patched(studio, sync_master=boom):
            studio._background()

    def test_cli_resume_master_rebuild_prints_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["resume", "master", "--rebuild"])
        self.assertIn("pdf ", out.getvalue())
        self.assertIn("with edge, 1 page(s)", out.getvalue())


class Badge(Base):
    def setUp(self):
        super().setUp()
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con
        super().tearDown()

    def test_resume_records_used_sections_and_badge_follows_only_them(self):
        jid = db.add_job("Initech", "Data Engineer", jd="Python and SQL")
        job = db.get_job(jid)
        try:
            resume._save_resume(job, "# Dana Smith\nDana Smith | dana@example.com\n## Experience\n### Senior Engineer - Acme Corp\n"
                                     "- Cut deploy time 40%\n", 50)
            stored = db.get_job(jid)["profile_rev"]
            self.assertEqual(sorted(json.loads(stored)), ["contact", "experience"])
            view = lambda: web._job_view(db.get_job(jid), None, profile.section_revs())  # noqa: E731
            self.assertEqual(view()["profile_changed"], [])
            profile.write_master(MASTER.replace("- Python, SQL", "- Python, SQL, Rust"))  # skills: not on this resume
            self.assertEqual(view()["profile_changed"], [])
            profile.write_master(MASTER.replace("2021-03 - Present", "2021-03 - 2024-06"))
            self.assertEqual(view()["profile_changed"], ["Experience"])
            old = db.add_job("Globex", "Engineer")  # tailored before this pass: no rev, so no badge
            self.assertEqual(web._job_view(db.get_job(old), None, profile.section_revs())["profile_changed"], [])
            out, after = resume._save_resume(db.get_job(old), "# Dana\n## Skills\n- Python\n", 0)  # no JD: no re-score
            self.assertTrue(out.is_file())
            self.assertEqual(after, 0)
        finally:
            for j in db.list_jobs():
                shutil.rmtree(resume.app_dir(j), ignore_errors=True)


class Engine(unittest.TestCase):
    def setUp(self):
        self.real = (resume._browser, resume._word, resume._soffice, resume.pdf_from_html)
        self.dir = Path(tempfile.mkdtemp(prefix="lodestar-engine-test-"))
        self.md = self.dir / "resume.md"
        self.md.write_text("# Dana Smith\n## Experience\n### Engineer - Acme Corp (2021 - Present)\n- Shipped it\n", encoding="utf-8")

    def tearDown(self):
        resume._browser, resume._word, resume._soffice, resume.pdf_from_html = self.real
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_edge_flags_temp_profile_and_never_trusting_the_exit_code(self):
        from lodestar import updater

        seen = {}

        def proc(cmd, cwd, timeout, env=None):
            seen.update(cmd=cmd, cwd=Path(cwd), timeout=timeout)
            self.assertTrue(Path(cwd).is_dir())
            return 0, "", ""  # exit 0, but nothing written (Edge does this when it cannot write)
        target = self.dir / "old.pdf"
        target.write_bytes(b"%PDF-1.4 stale" + b"x" * 2000)
        html = self.dir / "page.html"
        html.write_text("<p>x</p>", encoding="utf-8")
        with patched(updater, _proc=proc):
            with self.assertRaises(resume.NoEngine):
                resume.pdf_from_html(html, target, "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
        self.assertEqual(target.read_bytes()[:14], b"%PDF-1.4 stale")  # never passed off as fresh
        cmd = seen["cmd"]
        self.assertEqual(cmd[1:5], ["--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run"])
        self.assertIn(f"--user-data-dir={seen['cwd'] / 'profile'}", cmd)
        self.assertIn(f"--print-to-pdf={seen['cwd'] / 'out.pdf'}", cmd)
        self.assertEqual((cmd[-1], seen["timeout"]), (html.resolve().as_uri(), 60))
        self.assertFalse(seen["cwd"].exists())  # the throwaway profile is gone

        def writes(cmd, cwd, timeout, env=None):
            (Path(cwd) / "out.pdf").write_bytes(b"%PDF-1.4\n/Type /Page\n" + b"x" * 2000)
            return 0, "", ""
        with patched(updater, _proc=writes):
            r = resume.pdf_from_html(html, target, "C:/x/msedge.exe")
        self.assertEqual((r["method"], resume.page_count(target)), ("edge", 1))

    def test_engine_order_word_libreoffice_html_with_tried(self):
        import subprocess

        def nothing(html, pdf, browser=None):
            raise resume.NoEngine("edge: no PDF written (exit 0)")
        resume._browser, resume.pdf_from_html = (lambda: "C:/x/msedge.exe"), nothing
        resume._word, resume._soffice = (lambda: True), (lambda: "soffice")
        with patched(subprocess, run=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no")):
            r = resume.export_pdf(self.md, open_html=False)
        self.assertEqual(r["method"], "html")
        self.assertEqual([t.split(":")[0] for t in r["tried"]], ["edge", "Microsoft Word", "LibreOffice"])
        self.assertNotIn("<script", (self.dir / "resume.html").read_text(encoding="utf-8").split("</style>")[0])
        resume.pdf_from_html = fake_pdf()
        r = resume.export_pdf(self.md, open_html=False)
        self.assertEqual((r["method"], r["note"]), ("edge", "printed with Microsoft Edge (headless)"))
        self.assertFalse((self.dir / "resume.html").exists())  # the script-free page fed to the engine is removed

    def test_lodestar_browser_override(self):
        own = self.dir / "chromium.exe"
        own.write_bytes(b"")
        with patched(os, environ={**os.environ, "LODESTAR_BROWSER": str(own)}):
            self.assertEqual(resume._browser(), str(own))
            self.assertEqual(resume.engine_name(str(own)), "chromium")

    @unittest.skipUnless(resume._browser(), "no Edge, Chrome or Chromium installed")
    def test_real_edge_renders_one_letter_page(self):
        from lodestar import lint

        resume._word, resume._soffice = (lambda: False), (lambda: None)
        self.md.write_text("# Dana Smith\ndana@example.com | Austin, TX\n## Experience\n### Workflow Engineer - Acme Corp 2021 - Present\n"
                           "- Cut deploy time 40% for 12 teams\n"
                           + "".join(f"- Rebuilt pipeline {i} on Spark and Airflow, cutting its runtime to {i + 40} minutes\n"
                                     for i in range(8)), encoding="utf-8")
        r = resume.export_pdf(self.md, "classic", open_html=False)
        if r["method"] == "html":
            self.skipTest(f"the browser could not print here: {r['tried']}")
        data = Path(r["path"]).read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(resume.page_count(Path(r["path"])), 1)
        self.assertIn(b"/MediaBox [0 0 612 792]", data)  # Letter
        self.assertEqual([i for i in lint.audit(data, "Dana-Smith-Resume.pdf")["issues"] if i["severity"] == "high"], [])
        try:
            import pypdf
        except ImportError:
            return
        text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages)
        self.assertIn("dana@example.com", text)
        self.assertLess(text.index("Workflow Engineer"), text.index("Acme Corp 2021"))
        self.assertNotIn("\ufb02", text)  # ligatures off: 'fl' stays two letters


if __name__ == "__main__":
    unittest.main()
