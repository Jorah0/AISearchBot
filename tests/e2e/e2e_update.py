"""Setup > Updates (pass 16.4): Check now shows the commit range, the commits and the changelog between the versions and
the top-bar badge; Update now asks first, shows progress, fast-forwards and offers Restart (desktop); a failing test gate
rolls back and Getting started and Diagnostics say so; a dirty install is refused with Update now disabled; the mode and
interval preferences; the update log. The updater works on throwaway git repos made per test in a temp folder (a bare
'origin', a 'dev' clone that pushes, an 'install' clone), never this checkout. The test gate (unit suite + doctor on the
new code) is faked: tests/test_pass16_update.py runs the real one."""
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from harness import E2ETestCase, web
from lodestar import settings, updater


def git(cwd, *args) -> str:
    r = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
                        "-c", "core.autocrlf=false", *args], cwd=str(cwd), capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


class Updates(E2ETestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gates, cls.gate_error = [], None

        def gate(repo):
            cls.gates.append(Path(repo))
            if cls.gate_error:
                raise SystemExit(cls.gate_error)

        cls._patch(updater, "_gate", gate)
        cls._patch(updater, "_pip", lambda repo: (_ for _ in ()).throw(AssertionError("pip ran")))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lodestar-e2e-upd-"))
        self.addCleanup(self._rm)
        self.origin, self.dev, self.install = self.tmp / "origin.git", self.tmp / "dev", self.tmp / "install"
        git(self.tmp, "init", "--bare", "-q", str(self.origin))
        git(self.tmp, "init", "-q", str(self.dev))
        self.commit({"docs/CHANGELOG.md": "# Changelog\n\n## Pass 1\n- first\n", "README.md": "x\n"}, "first release")
        git(self.dev, "remote", "add", "origin", str(self.origin))
        git(self.dev, "push", "-q", "origin", "main")
        git(self.tmp, "clone", "-q", str(self.origin), str(self.install))
        self.v1 = git(self.install, "rev-parse", "HEAD")
        old = updater.ROOT
        updater.ROOT = self.install
        self.addCleanup(setattr, updater, "ROOT", old)
        self.addCleanup(setattr, web, "RESTART", web.RESTART)
        self.restarts = []
        web.RESTART = lambda: self.restarts.append(True)  # what lodestar desktop sets (desktop.relaunch)
        type(self).gates.clear()
        type(self).gate_error = None
        updater.LOG.unlink(missing_ok=True)  # this class's home: an earlier test's update would ask for a restart
        for k in ("update_mode", "update_every_hours"):
            settings.set_pref(k, settings.PREFS[k])
        super().setUp()
        self.go("setup")

    def _rm(self):
        for f in self.tmp.rglob("*"):  # git's objects are read-only; Windows will not delete them otherwise
            f.chmod(0o666) if f.is_file() else None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, files: dict, msg: str, push: bool = False) -> str:
        for name, text in files.items():
            p = self.dev / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        git(self.dev, "add", "-A")
        git(self.dev, "commit", "-q", "-m", msg)
        if push:
            git(self.dev, "push", "-q", "origin", "main")
        return git(self.dev, "rev-parse", "HEAD")

    def release(self) -> str:
        return self.commit({"docs/CHANGELOG.md": "# Changelog\n\n## Pass 2\n- salary <filter> & badge\n\n## Pass 1\n- first\n"},
                           "Add salary filter", push=True)

    def check(self):
        self.run_click("#uCheck")

    def head(self) -> str:
        return git(self.install, "rev-parse", "HEAD")

    def test_check_shows_the_range_and_changelog_then_update_and_restart(self):
        pg = self.page
        self.assertEqual((pg.input_value("#uMode"), pg.input_value("#uEvery")), ("notify", "24"))  # the defaults
        self.assertFalse(pg.is_visible("#updPill"))
        self.assertIn("git install", pg.text_content("#uInfo"))
        target = self.release()
        self.check()
        self.assertEqual(pg.text_content("#uHead"), "Update available: 1 commit")
        rng = pg.text_content("#uRange")
        self.assertIn(self.v1[:7], rng)
        self.assertIn(target[:7], rng)
        self.assertIn("Add salary filter", pg.text_content("#uCommits"))
        log = pg.text_content("#uChangelog")
        self.assertIn("## Pass 2", log)
        self.assertIn("salary <filter> & badge", log)  # escaped text, not markup
        self.assertNotIn("Pass 1", log)  # only what the update adds
        self.assertEqual(pg.text_content("#updPill"), "Update available")  # top-bar badge after the logged check
        self.assertTrue(pg.is_enabled("#uApply"))
        pg.click('#uLogBox summary')
        self.assertIn("update available: 1 commit", pg.text_content("#uLog"))

        self.answer(False)  # Cancel: nothing happens
        pg.click("#uApply")
        self.assertIn(f"{self.v1[:7]} → {target[:7]}", self.dialogs[-1])
        self.assertEqual(self.head(), self.v1)

        self.answer(True)
        pg.click("#uApply")
        pg.wait_for_selector("#uProgress")  # progress while the update runs
        self.idle(60_000)
        pg.wait_for_selector("#uRestart")
        self.assertEqual(self.head(), target)
        self.assertEqual(self.gates, [self.install])  # the tests ran on the updated install
        self.assertIn("backup:", pg.text_content("#uResult"))
        self.assertTrue(pg.is_enabled("#uCheck"))
        self.expect_toast("updated", "ok")
        self.assertEqual(pg.text_content("#updPill"), "Restart to finish the update")
        self.assertIn("updated " + self.v1[:7], pg.text_content("#uLog"))
        self.assertIn("last update", pg.text_content("#uInfo"))

        pg.click("#uRestart")
        self.expect_toast("restarting", "ok")
        for _ in range(50):  # the server relaunches half a second after it answered
            if self.restarts:
                break
            time.sleep(0.1)
        self.assertEqual(self.restarts, [True])

    def test_a_failing_test_gate_rolls_back_and_getting_started_and_diagnostics_say_so(self):
        self.release()
        type(self).gate_error = "2 tests failed"
        self.check()
        self.answer(True)
        self.run_click("#uApply", 60_000)
        self.page.wait_for_selector("#uFail")
        self.assertIn("rolled back", self.page.text_content("#uFail"))
        self.assertIn("2 tests failed", self.page.text_content("#uFail"))
        self.expect_toast("rolled back", "err")
        self.assertEqual(self.head(), self.v1)  # the exact previous commit
        self.assertFalse(self.page.is_visible("#uRestart"))
        self.assertEqual(self.page.text_content("#updPill"), "Update available")  # still offered
        self.go("board")
        note = self.page.text_content("#onboard")
        self.assertIn("Last update failed", note)
        self.assertIn("rolled back", note)
        self.page.locator("#onboard").get_by_role("button", name="Updates").click()
        self.page.wait_for_selector("section#setup.on")
        self.run_click(self.page.get_by_role("button", name="Run diagnostics"))
        row = self.page.locator("#doctorOut .list > div", has_text="last update")
        self.assertIn("WARN", row.text_content())
        self.assertIn("rolled back", row.text_content())

    def test_update_now_after_the_origin_moved_drops_the_old_plan_and_says_why(self):
        pg = self.page
        self.release()
        self.check()
        self.commit({"README.md": "later\n"}, "later work", push=True)  # the origin moves after the check
        self.answer(True)
        self.run_click("#uApply")
        self.assertIn("the origin changed since your check", pg.text_content("#uFail"))
        self.assertEqual(pg.inner_html("#uPlan").strip(), "")  # no stale Update now to click again
        self.assertTrue(pg.is_enabled("#uCheck"))
        self.expect_toast("origin changed", "err")
        self.assertEqual((self.head(), self.gates), (self.v1, []))
        pg.click('#uLogBox summary')
        self.assertIn("refused: the origin changed since your check", pg.text_content("#uLog"))

    def test_restart_waits_while_an_update_runs(self):
        pg = self.page
        self.allow_console()  # the refused restart answers 400
        updater._done(True, self.v1, self.v1, "updated; restart Lodestar to use it")  # an earlier update, not restarted
        self.reload_state()
        pg.wait_for_selector("#uRestart")
        web.TASKS["e2e-upd"] = {"status": "running", "action": "update_apply"}  # another tab or the loop updates now
        try:
            self.reload_state()
            self.assertIn("An update is running", pg.text_content("#uBusy"))
            self.assertEqual(pg.locator("#uRestart").count(), 0)
            self.assertIn("an update is running", self.api("/api/update/restart", {})["error"])
        finally:
            del web.TASKS["e2e-upd"]
        self.reload_state()
        pg.wait_for_selector("#uRestart")
        self.assertEqual(pg.locator("#uBusy").count(), 0)
        self.assertEqual(self.restarts, [])

    def test_dirty_install_up_to_date_prefs_and_restart_outside_the_desktop_app(self):
        self.allow_console()  # the refused interval and restart answer 400
        pg = self.page
        self.check()
        self.assertIn("up to date", pg.text_content("#uUpToDate"))
        self.assertFalse(pg.is_visible("#uApply"))
        self.release()
        (self.install / "notes.txt").write_text("my own file", encoding="utf-8")  # untracked counts as dirty
        self.check()
        self.assertIn("uncommitted changes", pg.text_content("#uBlocked"))
        self.assertTrue(pg.is_disabled("#uApply"))
        self.set_viewport(420)
        self.assertEqual(self.overflow(), [])
        self.set_viewport(1280)

        pg.select_option("#uMode", "auto")
        self.idle()
        self.assertEqual(self.state()["prefs"]["update_mode"], "auto")
        pg.fill("#uEvery", "0")
        pg.press("#uEvery", "Tab")
        self.expect_toast("update_every_hours", "err")
        self.idle()
        pg.fill("#uEvery", "6")
        pg.press("#uEvery", "Tab")
        self.idle()
        self.assertEqual(self.state()["prefs"]["update_every_hours"], 6)
        self.assertEqual(pg.input_value("#uEvery"), "6")

        web.RESTART = None  # lodestar app / ui: no window to relaunch
        r = self.api("/api/update/restart", {})
        self.assertIn("desktop app only", r["error"])
        self.assertEqual(self.restarts, [])
