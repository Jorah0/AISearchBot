"""Pass 16.4, auto-update (updater.py): every git test runs on throwaway repos made here (a bare 'origin', a 'dev'
clone that pushes, an 'install' clone the updater works on), never on this checkout or its GitHub origin. No network:
the unreachable origin is an empty folder, pip is faked, the -Exe manifest fetch is faked. The test gate is real: the
throwaway install carries its own tiny unit suite and a `lodestar` package whose doctor prints its verdict."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as the other files when one of them was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, db, doctor, loop, settings, updater, util  # noqa: E402
from lodestar.config import ALERTS, HOME  # noqa: E402

PASS = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
FAIL = PASS.replace("pass", "self.fail('broken release')")
DEFAULTS = {k: settings.PREFS[k] for k in settings.PREFS if k.startswith("update_")}


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


def git(cwd, *args) -> str:
    r = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                        "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lodestar-upd-"))
        self.origin, self.dev, self.install = self.tmp / "origin.git", self.tmp / "dev", self.tmp / "install"
        git(self.tmp, "init", "--bare", "-q", str(self.origin))
        git(self.tmp, "init", "-q", str(self.dev))
        self.write({"docs/CHANGELOG.md": "# Changelog\n\n## v1\n- first\n", "tests/test_ok.py": PASS,
                    "lodestar/__init__.py": "", "lodestar/__main__.py": "print('all good')\n",
                    "pyproject.toml": "[project]\nname = 'x'\n"}, "v1")
        git(self.dev, "remote", "add", "origin", str(self.origin))
        git(self.dev, "push", "-q", "origin", "main")
        git(self.tmp, "clone", "-q", str(self.origin), str(self.install))
        git(self.install, "config", "core.autocrlf", "false")
        self.v1 = git(self.install, "rev-parse", "HEAD")
        self.log0 = updater.LOG.read_text(encoding="utf-8") if updater.LOG.is_file() else None
        updater.LOG.unlink(missing_ok=True)
        for k, v in DEFAULTS.items():
            settings.set_pref(k, v)
        web = sys.modules.get("lodestar.web")  # a task left running by another test would read as 'in flight'
        self.tasks = dict(web.TASKS) if web else None
        if web:
            web.TASKS.clear()

    def tearDown(self):
        for f in self.tmp.rglob("*"):  # git makes its objects read-only; Windows will not delete those otherwise
            f.chmod(0o666) if f.is_file() else None
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in DEFAULTS.items():
            settings.set_pref(k, v)
        updater.LOG.unlink(missing_ok=True)
        if self.log0 is not None:
            updater.LOG.write_text(self.log0, encoding="utf-8")
        if self.tasks is not None:
            sys.modules["lodestar.web"].TASKS.update(self.tasks)

    def write(self, files: dict, msg: str, push: bool = False) -> str:
        for name, text in files.items():
            p = self.dev / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", msg)
        if push:
            git(self.dev, "push", "-q", "origin", "main")
        return git(self.dev, "rev-parse", "HEAD")

    def release(self, tests: str = PASS, extra: dict | None = None) -> str:
        """The origin moves on: a v2 changelog section, and the test file as given."""
        return self.write({"docs/CHANGELOG.md": "# Changelog\n\n## v2\n- second\n\n## v1\n- first\n",
                           "tests/test_ok.py": tests, **(extra or {})}, "v2: second release", push=True)

    def head(self) -> str:
        return git(self.install, "rev-parse", "HEAD")

    def no_pip(self, repo):
        raise AssertionError("pip ran although pyproject.toml did not change")


class Check(Base):
    def test_up_to_date(self):
        p = updater.check(self.install)
        self.assertEqual((p["kind"], p["available"], p["result"]), ("git", False, "up to date"))
        self.assertEqual(p["current"], self.v1)
        self.assertEqual(updater.entries()[0]["kind"], "check")

    def test_update_available_shows_the_commit_range_and_the_changelog_between_the_versions(self):
        v2 = self.release()
        p = updater.check(self.install)
        self.assertTrue(p["available"])
        self.assertEqual((p["current"], p["target"], p["behind"], p["ahead"]), (self.v1, v2, 1, 0))
        self.assertIn("v2: second release", p["commits"][0])
        self.assertIn("## v2", p["changelog"])
        self.assertNotIn("## v1", p["changelog"])  # only what the new version adds
        self.assertIn(f"{self.v1[:7]}..{v2[:7]}", p["result"])
        self.assertIsNone(p["blocked"])
        self.assertEqual(self.head(), self.v1)  # a check never moves the install
        self.assertEqual(git(self.install, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"), "refs/heads/main")

    def test_an_unreachable_origin_is_could_not_check_and_never_raises(self):
        empty = self.tmp / "gone"
        empty.mkdir()
        git(self.install, "remote", "set-url", "origin", str(empty))
        p = updater.check(self.install)
        self.assertFalse(p["available"])
        self.assertTrue(p["result"].startswith("could not check:"), p["result"])
        self.assertTrue(updater.entries()[0]["result"].startswith("could not check"))
        rows = dict((w, (s, d)) for s, w, d in updater.doctor_rows(self.install))
        self.assertEqual(rows["update check"][0], "warn")

    def test_only_https_or_a_local_folder_is_an_origin_and_credentials_never_show(self):
        for bad in ("git@github.com:x/y.git", "http://example.com/x.git", "ssh://host/x", "git://host/x", ""):
            with self.assertRaises(SystemExit):
                updater.allowed_origin(bad)
        self.assertEqual(updater.allowed_origin("https://github.com/x/y.git"), "https://github.com/x/y.git")
        git(self.install, "remote", "set-url", "origin", "http://example.com/x.git")
        self.assertIn("only from an https:// origin", updater.check(self.install)["result"])
        self.assertEqual(updater.scrub("fatal: https://me:s3cret@github.com/x.git not found"),
                         "fatal: https://***@github.com/x.git not found")
        updater._log("check", "", "", "could not check: https://me:s3cret@host/x")
        self.assertNotIn("s3cret", updater.LOG.read_text(encoding="utf-8"))

    def test_releases_channel_follows_the_newest_version_tag(self):
        settings.set_pref("update_channel", "releases")
        self.assertFalse(updater.check(self.install)["available"])  # no tag yet: nothing to update to
        v2 = self.release()
        git(self.dev, "tag", "v2.0.0")
        self.write({"later.txt": "x"}, "untagged work", push=True)
        git(self.dev, "push", "-q", "origin", "v2.0.0")
        p = updater.check(self.install)
        self.assertEqual((p["target"], p["behind"]), (v2, 1))
        self.assertEqual(git(self.install, "tag"), "")  # the user's own tags are untouched


class Apply(Base):
    def test_a_dirty_tree_is_refused(self):
        self.release()
        (self.install / "tests" / "test_ok.py").write_text("# my edit\n", encoding="utf-8")
        p = updater.check(self.install)
        self.assertIn("uncommitted changes", p["blocked"])
        r = updater.apply(self.install)
        self.assertFalse(r["ok"])
        self.assertIn("refused: the install folder has uncommitted changes", r["result"])
        self.assertEqual(self.head(), self.v1)
        self.assertEqual(updater.entries()[0]["kind"], "apply")

    def test_ahead_or_diverged_is_refused_fast_forward_only(self):
        (self.install / "mine.txt").write_text("local\n", encoding="utf-8")
        git(self.install, "add", "-A")
        git(self.install, "commit", "-q", "-m", "local work")
        mine = self.head()
        self.assertIn("1 local commit(s) not on the origin", updater.check(self.install)["result"])  # ahead only
        self.release()  # now diverged
        p = updater.check(self.install)
        self.assertEqual((p["behind"], p["ahead"]), (1, 1))
        self.assertIn("1 commit(s) the origin does not", p["blocked"])
        r = updater.apply(self.install, p)
        self.assertIn("refused: this install has 1 commit(s)", r["result"])
        self.assertEqual(self.head(), mine)  # never merged, never rebased

    def test_a_mail_scan_or_a_send_in_flight_is_refused(self):
        self.release()
        with util.run_lock("email"):
            r = updater.apply(self.install)
        self.assertIn("refused: another email run is in progress", r["result"])
        pid = db.add_pending("followup", "send_email", None, "t", "{}")
        self.assertTrue(db.claim_pending(pid))
        try:
            self.assertIn("an Inbox action is being sent", updater.apply(self.install)["result"])
        finally:
            db.decide_pending(pid, "done", "")
        self.assertEqual(self.head(), self.v1)

    def test_success_fast_forwards_backs_up_and_passes_the_test_gate(self):
        v2 = self.release()
        before = set((HOME / "backups").glob("*.zip")) if (HOME / "backups").is_dir() else set()
        with patched(updater, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertTrue(r["ok"], r["result"])
        self.assertEqual(self.head(), v2)
        self.assertIn("restart Lodestar", r["result"])
        self.assertTrue(set((HOME / "backups").glob("*.zip")) - before)
        self.assertEqual(git(self.install, "status", "--porcelain"), "")
        e = updater.entries()[0]
        self.assertEqual((e["kind"], e["ok"], e["from"], e["to"]), ("apply", True, self.v1[:12], v2[:12]))
        self.assertTrue(updater.status(self.install)["restart_needed"])
        self.assertIn("restart", dict((w, d) for s, w, d in updater.doctor_rows(self.install)))

    def test_a_failing_test_gate_rolls_back_to_the_exact_previous_commit(self):
        self.release(FAIL)
        with patched(updater, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertFalse(r["ok"])
        self.assertIn(f"failed, rolled back to {self.v1[:7]}", r["result"])
        self.assertIn("unittest", r["result"])
        self.assertEqual(self.head(), self.v1)
        self.assertEqual(git(self.install, "status", "--porcelain"), "")
        self.assertEqual((self.install / "tests" / "test_ok.py").read_text(encoding="utf-8"), PASS)

    def test_a_doctor_that_crashes_also_rolls_back(self):
        self.release(extra={"lodestar/__main__.py": "raise RuntimeError('boom')\n"})
        with patched(updater, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertIn("lodestar doctor did not finish", r["result"])
        self.assertEqual(self.head(), self.v1)

    def test_a_pyproject_change_reinstalls_and_a_failed_update_reinstalls_the_old_one(self):
        calls = []
        v2 = self.release(extra={"pyproject.toml": "[project]\nname = 'x'\nversion = '2'\n"})
        with patched(updater, _pip=lambda repo: calls.append(Path(repo))):
            self.assertTrue(updater.apply(self.install)["ok"])
        self.assertEqual(calls, [self.install])
        self.assertEqual(self.head(), v2)
        self.write({"pyproject.toml": "[project]\nname = 'x'\nversion = '3'\n", "tests/test_ok.py": FAIL}, "v3", push=True)
        with patched(updater, _pip=lambda repo: calls.append(Path(repo))):
            self.assertFalse(updater.apply(self.install)["ok"])
        self.assertEqual(len(calls), 3)  # v2 install, v3 install, v2 back
        self.assertEqual(self.head(), v2)


class Tick(Base):
    def later(self, hours: int) -> datetime:
        return datetime.now() + timedelta(hours=hours)

    def alerts(self) -> str:
        return ALERTS.read_text(encoding="utf-8") if ALERTS.is_file() else ""

    def test_off_notify_and_the_interval(self):
        settings.set_pref("update_mode", "off")
        self.release()
        self.assertIsNone(updater.tick(self.install))
        self.assertEqual(updater.entries(), [])
        settings.set_pref("update_mode", "notify")
        n = len(self.alerts())
        with contextlib.redirect_stdout(io.StringIO()):
            p = updater.tick(self.install)
            self.assertTrue(p["available"] and "applied" not in p)
            self.assertIsNone(updater.tick(self.install))  # checked a moment ago: not due
            updater.tick(self.install, now=self.later(25))
        self.assertEqual(self.alerts()[n:].count("UPDATE available"), 1)  # one alert per new version
        self.assertEqual(self.head(), self.v1)  # notify never applies
        self.assertEqual([e["kind"] for e in updater.entries()], ["check", "check"])

    def test_auto_mode_applies_only_when_nothing_blocks_it(self):
        settings.set_pref("update_mode", "auto")
        v2 = self.release()
        (self.install / "scratch.txt").write_text("x", encoding="utf-8")  # untracked: the tree is not clean
        n = len(self.alerts())
        with contextlib.redirect_stdout(io.StringIO()):
            p = updater.tick(self.install)
        self.assertNotIn("applied", p)
        self.assertIn("not applied automatically: the install folder has uncommitted changes", self.alerts()[n:])
        self.assertEqual(self.head(), self.v1)
        (self.install / "scratch.txt").unlink()
        with patched(updater, _pip=self.no_pip), contextlib.redirect_stdout(io.StringIO()):
            p = updater.tick(self.install, now=self.later(25))
        self.assertTrue(p["applied"]["ok"], p["applied"]["result"])
        self.assertEqual(self.head(), v2)
        self.assertIn("UPDATE updated", self.alerts()[n:])

    def test_the_standalone_build_only_reads_the_manifest_and_notifies(self):
        settings.set_pref("update_mode", "auto")
        sys.frozen = True
        try:
            self.assertIn("could not check: no https update_manifest_url", updater.check(self.install)["result"])
            settings.set_pref("update_manifest_url", "https://example.com/lodestar.json")
            seen = []
            fake = lambda url, **kw: (seen.append(url), {"version": "9.0.0", "url": "https://example.com/dl", "notes": "new"})[1]
            with patched(util, fetch_json=fake), patched(updater, apply=lambda *a, **k: self.fail("the exe applied")), \
                    contextlib.redirect_stdout(io.StringIO()):
                p = updater.tick(self.install, now=self.later(25))
            self.assertEqual(seen, ["https://example.com/lodestar.json"])
            self.assertTrue(p["available"])
            self.assertIn("download: https://example.com/dl", p["result"])
            self.assertIn("(download it)", self.alerts())
            with patched(util, fetch_json=lambda url, **kw: {"version": "0.0.1", "url": "http://x"}):
                self.assertFalse(updater.check(self.install)["available"])
            self.assertEqual(updater.kind(self.install), "exe")
        finally:
            del sys.frozen
        with self.assertRaises(SystemExit):
            settings.set_pref("update_manifest_url", "http://example.com/x.json")

    def test_the_loop_runs_the_step_only_for_run_app_and_desktop(self):
        calls = []

        class A:
            email = False; days = 1; provider = None; followup = 7; every = 5; once = True  # noqa: E702
        from lodestar import web_monitor
        with patched(updater, tick=lambda: calls.append(1)), patched(web_monitor, check_watches=lambda: None,
                                                                       recheck_postings=lambda: None), \
                patched(loop, _backup=lambda: None, _digest=lambda a: None), contextlib.redirect_stdout(io.StringIO()):
            loop.cycle(A())  # tests and callers without the flag never check
            self.assertEqual(calls, [])
            A.update = True
            loop.cycle(A())
        self.assertEqual(calls, [1])
        self.assertTrue(cli.build().parse_args(["run", "--once"]).update)
        self.assertFalse(cli.build().parse_args(["desktop", "--no-update"]).update)


class Cli(Base):
    def test_commands_prefs_log_status_and_doctor(self):
        b = cli.build()
        for argv in (["update"], ["update", "check"], ["update", "apply", "--yes"], ["update", "status"], ["update", "log", "--limit", "5"]):
            self.assertIs(b.parse_args(argv).f, cli.cmd_update)
        for k, bad in (("update_mode", "sometimes"), ("update_every_hours", "0"), ("update_every_hours", "721"),
                       ("update_channel", "nightly"), ("update_origin", "git@github.com:x/y.git")):
            with self.assertRaises(SystemExit):
                settings.set_pref(k, bad)
        settings.set_pref("update_origin", str(self.origin))
        self.assertEqual(settings.pref("update_origin"), str(self.origin))
        self.assertEqual(settings.pref("update_mode"), "notify")
        settings.set_pref("update_origin", "")
        updater.check(self.install)
        self.release()
        with patched(updater, _pip=self.no_pip):
            updater.apply(self.install)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["update", "log"])
        lines = out.getvalue().splitlines()
        self.assertIn("apply", lines[0])  # newest first
        self.assertIn("check", lines[1])
        self.assertIn(f"{self.v1[:7]}..", lines[0])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["update", "status"])
        self.assertIn("mode notify, every 24 h", out.getvalue())
        rows = {w: d for s, w, d in doctor.checks()}
        self.assertIn("updates", rows)
        self.assertIn("last update", rows)


if __name__ == "__main__":
    unittest.main()
