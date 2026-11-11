"""Gaps the feature matrix (docs/TESTS.md) exposed: features that worked but had no test of their own. The capture
bookmarklet route, `resume import --merge [--save]`, packaging (pyproject package data and scripts, the PyInstaller
line, the start scripts, the uninstaller), `init` / `usage` / `alerts`, a blank form question (refused before any AI
call) and a bad preference (the error names it). No network: the AI HTTP layer raises if reached, the web server runs
on a free 127.0.0.1 port, and every patched attribute and touched file is put back."""
import contextlib
import http.client
import importlib
import io
import json
import os
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path, PurePosixPath

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, cli, db, desktop, drafts, profile, resume, web  # noqa: E402
from lodestar.config import ALERTS, APPS_DIR, DB_PATH, HOME, PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def kept(*paths):
    """Put these files back as they were (or gone) after the test."""
    old = {p: p.read_bytes() if p.is_file() else None for p in paths}
    try:
        yield
    finally:
        for p, b in old.items():
            if b is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(b)


def run_cli(*argv) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(argv))
    return out.getvalue()


def no_ai(*a, **k):
    raise AssertionError("an AI call was made")


@contextlib.contextmanager
def server():
    port = desktop.free_port(8890)
    srv = web.start_server(port)

    def call(method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, None if body is None else json.dumps(body),
                  {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, json.loads(raw) if raw else {}
    try:
        yield call
    finally:
        srv.shutdown()
        srv.server_close()


class Capture(unittest.TestCase):  # tracker-sourcing-30
    def test_capture_route_adds_a_job_with_the_capture_token_only(self):
        url = "https://boards.example.org/jobs/capture-matrix-1"
        page = {"title": "Data Engineer - Capture Co | LinkedIn", "url": url, "desc": "We use Python and SQL."}
        made = []
        # this thread reads the file database the server threads write (another test may have left an in-memory one)
        old = getattr(db._local, "con", None)
        db._local.con = db.connect()
        self.addCleanup(lambda: (db._local.con.close(), setattr(db._local, "con", old)))
        with server() as call:
            try:
                self.assertEqual(call("POST", "/api/capture", page)[0], 403)  # no token
                self.assertEqual(call("POST", f"/api/capture?t={web.TOKEN}", page)[0], 403)  # page token is not it
                self.assertEqual(call("POST", f"/api/capture?t={web.CAPTURE_TOKEN}", page, {"Host": "evil.example"})[0], 421)
                self.assertEqual(call("POST", f"/api/state?t={web.CAPTURE_TOKEN}", {})[0], 403)  # public routes only
                st, out = call("POST", f"/api/capture?t={web.CAPTURE_TOKEN}", page)
                self.assertEqual(st, 200, out)
                made.append(out["id"])
                self.assertEqual((out["company"], out["title"]), ("Capture Co", "Data Engineer"))
                j = db.get_job(out["id"])
                self.assertEqual((j["company"], j["title"], j["url"]), ("Capture Co", "Data Engineer", url))
                self.assertIn("Python and SQL", j["jd"])
                self.assertEqual(call("POST", f"/api/capture?t={web.CAPTURE_TOKEN}", page)[1]["id"], out["id"])  # once
                st, bad = call("POST", f"/api/capture?t={web.CAPTURE_TOKEN}",
                               {"title": "Analyst - Script Co", "url": "javascript:alert(1)"})
                made.append(bad["id"])
                self.assertIsNone(db.get_job(bad["id"])["url"])  # a javascript: link is never stored
            finally:
                for jid in made:
                    db.delete_job(jid)


class ResumeMerge(unittest.TestCase):  # profile-resume-ai-25
    def test_import_merge_prints_without_save_and_saves_through_write_master_with_it(self):
        old = "# Jane Example\n## Skills\nPython\n"
        merged = "# Jane Example\n## Skills\nPython, Go\n"
        cv = Path(tempfile.mkdtemp()) / "cv.md"
        cv.write_bytes(b"# Jane Example\n## Skills\nGo\n")  # LF, as a .md file made elsewhere
        calls = []

        def fake_ask(prompt, system=None, provider=None, **kw):
            calls.append((prompt, kw))
            return merged
        with kept(PROFILE), patched(ai, ask=fake_ask):
            PROFILE.write_text(old, encoding="utf-8")
            out = run_cli("resume", "import", str(cv), "--merge")
            self.assertIn("Python, Go", out)
            self.assertIn("nothing saved", out)
            self.assertEqual(PROFILE.read_text(encoding="utf-8"), old)  # without --save nothing changes
            prompt, kw = calls[0]
            self.assertIn("UPLOADED RESUME", prompt)
            self.assertIn("Skills\nGo", prompt)
            self.assertIn("Skills\nPython", prompt)  # the master it merges into
            self.assertEqual(kw["max_tokens"], 8000)  # the whole profile comes back; a cut-off one raises
            out = run_cli("resume", "import", str(cv), "--merge", "--save")
            self.assertIn("merged and saved", out)
            self.assertEqual(PROFILE.read_text(encoding="utf-8"), merged)
            newest = sorted(profile.HISTORY.glob("profile-*.md"))[-1]  # write_master kept the old one
            self.assertEqual(newest.read_text(encoding="utf-8"), old)


class Packaging(unittest.TestCase):  # outcomes-platform-package-data, -pyinstaller, -start-scripts, -uninstaller
    def text(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_package_data_ships_every_static_and_data_file_and_both_scripts(self):
        pp = tomllib.loads(self.text("pyproject.toml"))
        globs = pp["tool"]["setuptools"]["package-data"]["lodestar"]
        pkg = ROOT / "lodestar"
        shipped = set()
        for sub in ("static", "data"):
            for f in (pkg / sub).rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    rel = PurePosixPath(f.relative_to(pkg).as_posix())
                    self.assertTrue(any(rel.match(g) for g in globs), f"{rel} is not packaged by {globs}")
                    shipped.add(str(rel))
        for need in ("static/index.html", "static/app.js", "static/app.css", "data/questions.json", "data/skills.json"):
            self.assertIn(need, shipped)
        self.assertEqual(pp["project"]["scripts"], {"lodestar": "lodestar.cli:main", "jobbot": "lodestar.cli:main"})
        mod, attr = pp["project"]["scripts"]["lodestar"].split(":")
        self.assertTrue(callable(getattr(importlib.import_module(mod), attr)))
        self.assertEqual(pp["project"]["requires-python"], ">=3.11")  # what the installers check
        self.assertTrue(any(d.startswith("playwright") for d in pp["project"]["optional-dependencies"]["e2e"]))

    def test_exe_build_bundles_the_data_folders_and_the_icon(self):
        line = next(ln for ln in self.text("install.ps1").splitlines() if "-m PyInstaller" in ln)
        adds = re.findall(r'--add-data "([^;"]+);([^"]+)"', line)
        self.assertEqual({src for src, _ in adds}, {"lodestar/static", "lodestar/data", "assets"})
        for src, dest in adds:
            self.assertEqual(src, dest)  # same relative place inside the bundle as beside the source
            self.assertTrue((ROOT / src).is_dir(), src)
        for mod in ("keyring", "docx", "webview"):
            self.assertIn(f"--collect-all {mod}", line)
        self.assertIn(r"lodestar\__main__.py", line)
        self.assertTrue((ROOT / "lodestar" / "__main__.py").is_file())
        self.assertTrue((ROOT / "assets" / "lodestar.ico").is_file())
        # the app looks for them where --add-data puts them
        self.assertEqual(web.STATIC.resolve(), ROOT / "lodestar" / "static")
        self.assertEqual(desktop.ASSETS.resolve(), ROOT / "assets")

    def test_start_scripts_call_commands_the_cli_accepts(self):
        ps1, sh, bat = self.text("start.ps1"), self.text("start.sh"), self.text("start.bat")
        self.assertIn('-File "%~dp0start.ps1" %*', bat)  # the double-click starter passes its flags on
        for needle in ("& $jb init", "& $jb providers", '@("desktop", "--every", "$Every")', '"--no-loop"',
                       '@("--port", "$Port")', '"run --every $Every"', "& $jb ui --port $Port"):
            self.assertIn(needle, ps1)
        for needle in (".venv/bin/lodestar init", ".venv/bin/lodestar providers", 'lodestar run --every "$EVERY"',
                       'lodestar ui --port "$PORT"'):
            self.assertIn(needle, sh)
        parser = cli.build()
        for argv in (["init"], ["providers"], ["desktop", "--every", "30", "--no-loop", "--port", "8765"],
                     ["run", "--every", "30"], ["ui", "--port", "8765"], ["ui"]):
            parser.parse_args(argv)  # a renamed command or flag would exit here

    def test_uninstaller_removes_what_the_installer_made_and_keeps_data_and_secrets(self):
        un, ins = self.text("uninstall.ps1"), self.text("install.ps1")
        shortcuts = re.findall(r'Name = "([^"]+)";', ins)
        self.assertEqual(shortcuts, ["Lodestar", "Lodestar monitor"])
        for n in shortcuts:
            self.assertIn(f'"{n}.lnk"', un)
        self.assertIn("/TN lodestar ", ins)  # the task install.ps1 -Schedule makes ...
        self.assertIn('"/TN", "lodestar"', (ROOT / "lodestar" / "extras.py").read_text(encoding="utf-8"))  # ... and the app
        self.assertRegex(un, r'foreach \(\$t in @\("lodestar", "jobbot"\)\) \{ schtasks /Delete /TN \$t /F')
        code = "\n".join(ln for ln in un.splitlines() if not ln.lstrip().startswith("#"))
        before, purge = code.split("if ($Purge)", 1)
        self.assertNotIn(".lodestar", before)  # your data stays unless -Purge
        self.assertNotIn("LODESTAR_HOME", before)
        self.assertIn("$env:LODESTAR_HOME", purge)  # -Purge honours a moved data folder
        for word in ("vault", "keyring", "cmdkey"):
            self.assertNotIn(word, code.lower())  # secrets in the OS keyring are never touched


class Operations(unittest.TestCase):  # outcomes-platform-usage-alerts-init
    def test_init_makes_the_home_keeps_a_profile_and_seeds_a_missing_one(self):
        with kept(PROFILE):
            PROFILE.write_text("# Jane Example\nreal line\n", encoding="utf-8")
            out = run_cli("init")
            self.assertEqual(PROFILE.read_text(encoding="utf-8"), "# Jane Example\nreal line\n")  # never overwritten
            self.assertTrue(APPS_DIR.is_dir())
            self.assertTrue(DB_PATH.is_file())
            self.assertIn(str(HOME), out)
            self.assertIn("lodestar keys link anthropic", out)
            self.assertIn("6. Automate", out)
            PROFILE.unlink()
            run_cli("init")
            self.assertEqual(PROFILE.read_text(encoding="utf-8"), resume.PROFILE_TEMPLATE)

    def test_alerts_prints_the_log_tail_and_usage_prints_its_table(self):
        with kept(ALERTS):
            ALERTS.unlink(missing_ok=True)
            self.assertIn("(no alerts yet)", run_cli("alerts"))
            ALERTS.write_text("x" * 5000 + "\n2026-11-09 new posting: Matrix Co\n", encoding="utf-8")
            out = run_cli("alerts")
            self.assertIn("new posting: Matrix Co", out)
            self.assertLessEqual(len(out.strip()), 4000)  # the tail only
        self.assertIn("provider/model", run_cli("usage", "--days", "7"))


class BlankQuestion(unittest.TestCase):  # profile-resume-ai-28
    def test_a_blank_form_question_is_refused_before_any_ai_call(self):
        jid = db.add_job("Blank Q Co", "Analyst")
        try:
            with patched(ai, _post=no_ai):
                for q in ("", "   \n "):
                    with self.assertRaisesRegex(SystemExit, "type the application-form question first"):
                        apply.answer(jid, q)
                    with self.assertRaisesRegex(SystemExit, "type the application-form question first"):
                        drafts.options("answer", {"job": jid, "question": q})
            self.assertFalse([r for r in db.list_pending() if r["tool"] == "answers" and r["job_id"] == jid])
        finally:
            db.delete_job(jid)


class PrefErrors(unittest.TestCase):  # outcomes-platform-prefs-validation
    def test_a_bad_preference_error_names_the_preference_and_an_ai_key_stays_hidden(self):
        with server() as call:
            st, out = call("POST", "/api/prefs", {"key": "followup_days", "value": "999"}, {"X-Lodestar-Token": web.TOKEN})
            self.assertEqual(st, 400)
            self.assertIn("followup_days", out["error"])  # the name, not ***
            self.assertNotIn("***", out["error"])
            secret = "sk-ant-matrix-0123456789abcdef"  # pasted into the name box by mistake: the error quotes the name
            st, out = call("POST", "/api/keys/link", {"name": secret, "key": secret}, {"X-Lodestar-Token": web.TOKEN})
            self.assertEqual(st, 400)
            self.assertNotIn(secret, json.dumps(out))  # on /api/keys/ the key is a secret, never echoed
            self.assertIn("***", out["error"])


if __name__ == "__main__":
    unittest.main()
