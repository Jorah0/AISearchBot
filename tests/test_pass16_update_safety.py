"""Pass 16.4 fixes, the updater's safety net: an update cut off mid-way is rolled back at the next start (journal), a
half-done fast-forward is restored, a rollback that fails is logged and retried, the test gate's timeout kills the whole
process tree and names the failing tests, a pulled release tag is no longer offered, auto mode tries a failing version
once, another running Lodestar process blocks the update, and the web server keeps the front end it started with.
Throwaway repos from test_pass16_update.Base, never this checkout."""
import contextlib
import http.client
import io
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta

from test_pass16_update import FAIL, PASS, Base, git, patched

from lodestar import db, desktop, settings, updater, web
from lodestar.config import ALERTS, HOME


class Safety(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.clean)

    def clean(self):
        updater.STATE.unlink(missing_ok=True)
        updater.LOCK.unlink(missing_ok=True)
        updater.unregister()
        for f in updater.PROCS.glob("*.pid") if updater.PROCS.is_dir() else ():
            f.unlink(missing_ok=True)

    def dead_pid(self) -> int:
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def dead_holder(self):
        """What a killed apply leaves: its journal and its lock, both naming a process that is gone."""
        dead = self.dead_pid()
        st = json.loads(updater.STATE.read_text(encoding="utf-8"))
        updater.STATE.write_text(json.dumps(st | {"pid": dead}), encoding="utf-8")
        updater.LOCK.write_text(str(dead), encoding="utf-8")

    def clean_tree(self) -> str:
        return git(self.install, "status", "--porcelain")


class Journal(Safety):
    def test_an_update_cut_off_mid_gate_is_rolled_back_at_the_next_start(self):
        v2 = self.release()

        class Killed(BaseException):  # the process dies inside the gate: no except, no _done
            pass

        def gate(repo):
            raise Killed()
        with patched(updater, _pip=self.no_pip, _gate=gate), self.assertRaises(Killed):
            updater.apply(self.install)
        self.assertEqual(self.head(), v2)  # untested code installed, nothing logged yet
        self.assertEqual(updater.entries(), [])
        st = json.loads(updater.STATE.read_text(encoding="utf-8"))
        self.assertEqual((st["from"], st["to"], st["pid"]), (self.v1, v2, os.getpid()))
        self.assertIsNone(updater.recover())  # its holder (this process) still lives: left alone
        self.assertEqual(self.head(), v2)

        self.dead_holder()
        updater.startup()  # what the app, the desktop window and the loop run as they start
        self.assertEqual(self.head(), self.v1)
        self.assertEqual(self.clean_tree(), "")
        self.assertFalse(updater.STATE.exists())
        self.assertFalse(updater.LOCK.exists())  # the dead holder's lock is freed at once, not after 50 minutes
        e = updater.entries()[0]
        self.assertEqual((e["kind"], e["ok"], e["restart"]), ("apply", False, True))
        self.assertIn(f"failed, rolled back to {self.v1[:7]}: the update was interrupted", e["result"])
        self.assertTrue(updater.status(self.install)["restart_needed"])
        self.assertTrue(updater.check(self.install)["available"])  # offered again, not 'up to date'

    def test_another_update_in_progress_is_a_logged_refusal(self):
        self.release()
        from lodestar import util

        with util.run_lock("update"):
            r = updater.apply(self.install)
        self.assertFalse(r["ok"])
        self.assertIn("refused: another update run is in progress", r["result"])
        self.assertEqual(updater.entries()[0]["result"], r["result"])
        self.assertEqual(self.head(), self.v1)


class Rollback(Safety):
    def test_a_half_done_fast_forward_is_put_back_exactly(self):
        self.release(extra={"new.txt": "added by v2\n"})
        real = updater._git

        def git_(repo, *args, **kw):  # git updated part of the tree, then failed on a file it could not unlink
            if args[0] == "merge":
                (self.install / "docs" / "CHANGELOG.md").write_text("half new\n", encoding="utf-8")
                (self.install / "new.txt").write_text("added by v2\n", encoding="utf-8")
                raise SystemExit("git merge: error: unable to unlink old 'tests/test_ok.py': Invalid argument")
            return real(repo, *args, **kw)
        with patched(updater, _git=git_, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertIn(f"failed, rolled back to {self.v1[:7]}: git merge: error: unable to unlink", r["result"])
        self.assertEqual((self.head(), self.clean_tree()), (self.v1, ""))
        self.assertFalse((self.install / "new.txt").exists())
        self.assertIn("## v1", (self.install / "docs" / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIsNone(updater.check(self.install)["blocked"])  # the next update is not stuck on a dirty tree

    @unittest.skipUnless(os.name == "nt", "Windows refuses to unlink a file another handle holds open")
    def test_a_file_held_open_during_the_fast_forward_on_windows(self):
        self.write({"a.txt": "a1\n", "b.txt": "b1\n"}, "files", push=True)
        git(self.install, "pull", "-q", "--ff-only")
        self.v1 = self.head()
        self.release(extra={"a.txt": "a2\n", "b.txt": "b2\n", "c.txt": "c\n"})
        with open(self.install / "b.txt", encoding="utf-8"), patched(updater, _pip=self.no_pip, _gate=lambda repo: None):
            r = updater.apply(self.install)
        self.assertFalse(r["ok"], r["result"])
        self.assertEqual((self.head(), self.clean_tree()), (self.v1, ""))
        self.assertEqual((self.install / "a.txt").read_text(encoding="utf-8"), "a1\n")
        self.assertFalse((self.install / "c.txt").exists())

    def test_a_rollback_that_fails_is_logged_kept_and_retried_at_the_next_start(self):
        v2 = self.release(FAIL)
        real, tries = updater._git, []

        def git_(repo, *args, **kw):
            if args[0] == "reset":
                tries.append(1)
                raise SystemExit("git reset: fatal: Could not reset index file to revision")
            return real(repo, *args, **kw)
        with patched(updater, _git=git_, _pip=self.no_pip, RETRY_WAIT=0):
            r = updater.apply(self.install)
        self.assertEqual(len(tries), updater.RETRIES)
        self.assertFalse(r["ok"])
        self.assertIn(f"failed, ROLLBACK FAILED at {v2[:7]}", r["result"])
        self.assertIn(f"reset --hard {self.v1}", r["result"])
        self.assertTrue(r["backup"])
        self.assertEqual(updater.entries()[0]["result"], r["result"])  # logged, not an escaped exception
        rows = {w: s for s, w, d in updater.doctor_rows(self.install)}
        self.assertEqual(rows["last update"], "fail")
        self.assertTrue(updater.STATE.is_file())  # kept: the next start tries again
        self.dead_holder()
        updater.recover()
        self.assertEqual((self.head(), self.clean_tree()), (self.v1, ""))
        self.assertFalse(updater.STATE.exists())

    def test_a_rollback_retries_a_file_held_open_for_a_moment(self):
        self.release(FAIL)
        real, tries = updater._git, []

        def git_(repo, *args, **kw):
            if args[0] == "reset" and not tries:
                tries.append(1)
                raise SystemExit("git reset: error: unable to unlink old 'a.txt'")
            return real(repo, *args, **kw)
        with patched(updater, _git=git_, _pip=self.no_pip, RETRY_WAIT=0):
            r = updater.apply(self.install)
        self.assertIn(f"failed, rolled back to {self.v1[:7]}", r["result"])
        self.assertEqual((self.head(), self.clean_tree()), (self.v1, ""))


class Gate(Safety):
    def test_the_gate_timeout_kills_the_whole_process_tree(self):
        pidfile = self.tmp / "helper.pid"
        hang = ("import subprocess, sys, time, unittest\n\n\nclass T(unittest.TestCase):\n    def test_hang(self):\n"
                "        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])\n"
                f"        open({str(pidfile)!r}, 'w').write(str(p.pid))\n        time.sleep(90)\n")
        self.release(hang)
        t0 = time.time()
        with patched(updater, GATE_TIMEOUT=5, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertLess(time.time() - t0, 45)  # not the helper's 90 s
        self.assertIn("took longer than 5 s", r["result"])
        self.assertEqual(self.head(), self.v1)
        helper = int(pidfile.read_text(encoding="utf-8"))
        for _ in range(50):
            if not updater._alive(helper):
                break
            time.sleep(0.1)
        self.assertFalse(updater._alive(helper))

    def test_a_failing_gate_names_the_failing_tests(self):
        self.release(FAIL)
        with patched(updater, _pip=self.no_pip):
            r = updater.apply(self.install)
        self.assertIn("FAIL: test_ok", r["result"])
        self.assertIn("FAILED (failures=1)", r["result"])
        self.assertIn("FAIL: test_ok", updater.entries()[0]["result"])


class Channel(Safety):
    def test_a_pulled_release_tag_is_no_longer_offered(self):
        settings.set_pref("update_channel", "releases")
        v2 = self.release()
        git(self.dev, "tag", "v2.0.0")
        git(self.dev, "push", "-q", "origin", "v2.0.0")
        self.assertEqual(updater.check(self.install)["target"], v2)
        git(self.dev, "push", "-q", "origin", ":refs/tags/v2.0.0")  # the maintainer pulls the broken release
        p = updater.check(self.install)
        self.assertFalse(p["available"], p["result"])
        self.assertEqual(git(self.install, "for-each-ref", "refs/lodestar/tags/"), "")


class AutoMode(Safety):
    def alerts(self) -> str:
        return ALERTS.read_text(encoding="utf-8") if ALERTS.is_file() else ""

    def test_auto_mode_tries_a_failing_version_once(self):
        settings.set_pref("update_mode", "auto")
        v2 = self.release(FAIL)
        n = len(self.alerts())
        later = datetime.now() + timedelta(hours=25)
        with patched(updater, _pip=self.no_pip), contextlib.redirect_stdout(io.StringIO()):
            p = updater.tick(self.install)
            self.assertFalse(p["applied"]["ok"])
            backups = sorted((HOME / "backups").glob("*.zip"))
            with patched(updater, apply=lambda *a, **k: self.fail("retried the failed version")):
                p = updater.tick(self.install, now=later)
            self.assertTrue(p["available"] and "applied" not in p)
            self.assertEqual(sorted((HOME / "backups").glob("*.zip")), backups)  # no backup rotation either
            new = self.alerts()[n:]
            self.assertEqual(new.count("UPDATE"), 1)
            self.assertIn("not retried automatically; run lodestar update apply", new)
            v3 = self.write({"tests/test_ok.py": PASS}, "v3: fixed", push=True)  # a newer version is tried
            p = updater.tick(self.install, now=later + timedelta(hours=25))
        self.assertTrue(p["applied"]["ok"], p["applied"]["result"])
        self.assertEqual(self.head(), v3)
        self.assertTrue(db.seen(f"update-failed:{v2}"))


class Processes(Safety):
    def test_another_running_lodestar_process_blocks_the_update(self):
        self.release()
        updater.register()  # this process: never in its own way
        self.assertIsNone(updater.check(self.install)["blocked"])
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (other.kill(), other.wait()))
        pidfile = updater.PROCS / f"{other.pid}.pid"
        if os.name == "nt":  # registered an hour before the process existed: a reused pid, not a Lodestar process
            pidfile.write_text(f"{time.time() - 3600:.0f}", encoding="utf-8")
            self.assertIsNone(updater.check(self.install)["blocked"])
        pidfile.write_text(f"{time.time():.0f}", encoding="utf-8")
        p = updater.check(self.install)
        self.assertIn(f"another Lodestar process is running (pid {other.pid}", p["blocked"])
        self.assertIn("another Lodestar process", updater.apply(self.install)["result"])
        self.assertEqual(self.head(), self.v1)
        other.kill()
        other.wait()
        self.assertIsNone(updater.check(self.install)["blocked"])
        self.assertFalse(pidfile.exists())  # a gone process's file is cleaned up

    def test_the_server_keeps_the_front_end_it_started_with(self):
        port = desktop.free_port(9060)
        srv = web.start_server(port)
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        pinned = dict(web.ASSETS, **{"app.js": b"// the front end this server started with\n"})
        with patched(web, ASSETS=pinned):  # an update rewrites static/ on disk: the server never reads it again
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/static/app.js", headers={"Host": f"127.0.0.1:{port}", "X-Lodestar-Token": web.TOKEN})
            body = c.getresponse().read()
            c.close()
        self.assertEqual(body, pinned["app.js"])
        self.assertEqual(set(web.ASSETS), {f.name for f in web.STATIC.iterdir() if f.is_file()})


if __name__ == "__main__":
    unittest.main()
