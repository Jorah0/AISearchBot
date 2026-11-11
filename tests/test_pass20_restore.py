"""Pass 20: restore from backup (extras.restore, `lodestar restore`, Setup > Data). A round trip puts the data folder back
(database, profile, documents; files made since removed; a before-restore safety zip first; keyring-side files kept);
the zip is validated before anything is written (traversal, absolute and drive paths, backslashes, reserved names,
links, programs, case clashes, no lodestar.db, the size and entry caps, a damaged database); a restore is refused while
the loop is mid-cycle, an Inbox send, a mail scan, a background action, an update or another Lodestar process is in
flight, and under Full AI; a failed swap puts every file back. Each test class runs in its own data folder (module
paths rebound, as the E2E harness does), so the shared test home is never restored over."""
import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""

from lodestar import config, db, extras, loop, updater, web  # noqa: E402
from lodestar.cli import build  # noqa: E402


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


class Home(unittest.TestCase):
    """A fresh data folder for the class: every lodestar module-level path under the shared home moves to it."""

    @classmethod
    def setUpClass(cls):
        old, new = Path(config.HOME), Path(tempfile.mkdtemp(prefix="lodestar-restore-"))
        db.release()
        cls._undo = []
        for name, mod in list(sys.modules.items()):
            if name == "lodestar" or name.startswith("lodestar."):
                for attr, v in list(vars(mod).items()):
                    if isinstance(v, Path) and v.is_relative_to(old):
                        cls._undo.append((mod, attr, v))
                        setattr(mod, attr, new / v.relative_to(old))
        cls.home = new
        (new / "applications").mkdir(exist_ok=True)
        db.con()  # the database exists, as in any data folder that has been used
        db.release()

    @classmethod
    def tearDownClass(cls):
        db.release()
        for mod, attr, v in cls._undo:
            setattr(mod, attr, v)

    def tearDown(self):
        db.release()

    def zip_of(self, entries: dict, name="hand.zip") -> Path:
        """A hand-made zip: {name: bytes | ZipInfo-tweak (bytes, external_attr)}; lodestar.db added unless given."""
        p = self.home / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for n, data in entries.items():
                if isinstance(data, tuple):
                    zi = zipfile.ZipInfo(n)
                    zi.external_attr = data[1]
                    z.writestr(zi, data[0])
                else:
                    z.writestr(n, data)
        self.addCleanup(p.unlink, missing_ok=True)
        return p

    def good_db(self) -> bytes:
        f = self.home / "src.db"
        c = db.connect(f)
        c.close()
        data = f.read_bytes()
        f.unlink()
        return data


class RoundTrip(Home):
    def test_restore_puts_the_data_back_removes_new_files_and_keeps_secrets_side_files(self):
        jid = db.add_job("Acme", "Data Engineer", None, "jd")
        ids = [j["id"] for j in db.list_jobs()]
        db.release()
        (self.home / "profile.md").write_text("# Jane\nbefore\n", encoding="utf-8")
        doc = self.home / "applications" / f"{jid}-acme-data-engineer" / "resume.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("resume v1", encoding="utf-8")
        (self.home / "extension.json").write_text('{"keep": "me"}', encoding="utf-8")
        (self.home / "capture.token").write_text("x" * 24, encoding="utf-8")
        zp = extras.backup()
        with zipfile.ZipFile(zp) as z:
            names = z.namelist()
        self.assertIn("lodestar.db", names)
        self.assertFalse({"extension.json", "capture.token"} & set(names))
        # after the backup: a second job, an edited profile and document, a new job folder
        jid2 = db.add_job("Globex", "Analyst", None, "jd")
        db.release()
        (self.home / "profile.md").write_text("# Jane\nafter\n", encoding="utf-8")
        doc.write_text("resume v2", encoding="utf-8")
        new_doc = self.home / "applications" / f"{jid2}-globex-analyst" / "resume.md"
        new_doc.parent.mkdir(parents=True)
        new_doc.write_text("new", encoding="utf-8")
        (self.home / "extension.json").write_text('{"paired": "after"}', encoding="utf-8")
        r = extras.restore(zp)
        self.assertEqual([j["id"] for j in db.list_jobs()], ids)
        self.assertNotIn(jid2, ids)
        self.assertEqual((self.home / "profile.md").read_text(encoding="utf-8"), "# Jane\nbefore\n")
        self.assertEqual(doc.read_text(encoding="utf-8"), "resume v1")
        self.assertFalse(new_doc.exists())
        self.assertFalse(new_doc.parent.exists(), "the emptied job folder is gone too")
        self.assertEqual((self.home / "extension.json").read_text(encoding="utf-8"), '{"paired": "after"}')
        self.assertEqual(r["counts"]["jobs"], len(ids))
        self.assertGreaterEqual(r["removed"], 1)
        self.assertIn("keyring", r["note"])
        safety = Path(r["safety_backup"])
        self.assertTrue(safety.name.startswith("before-restore-"))
        with zipfile.ZipFile(safety) as z:
            self.assertEqual(z.read(f"applications/{jid2}-globex-analyst/resume.md"), b"new")
        self.assertEqual(list(self.home.glob(".restore-*")), [], "staging and moved-aside folders are cleaned up")
        self.assertFalse((self.home / ".restore.lock").exists())
        self.assertIn(zp.name, [b["name"] for b in extras.backups()])

    def test_a_failed_swap_puts_every_file_back(self):
        (self.home / "profile.md").write_text("# Jane\nkept\n", encoding="utf-8")
        zp = extras.backup()
        (self.home / "profile.md").write_text("# Jane\ncurrent\n", encoding="utf-8")
        db.add_job("Initech", "Dev", None, "jd")
        db.release()
        jobs = len(db.list_jobs())
        db.release()
        real, calls = extras._move, []

        def flaky(src, dst):
            calls.append(src)
            if ".restore-stage-" in str(src):  # moving the backup's files in fails half way
                raise PermissionError("locked")
            return real(src, dst)

        with patched(extras, _move=flaky), self.assertRaises(PermissionError):
            extras.restore(zp)
        self.assertEqual((self.home / "profile.md").read_text(encoding="utf-8"), "# Jane\ncurrent\n")
        self.assertEqual(len(db.list_jobs()), jobs, "the database was not touched")
        self.assertEqual(list(self.home.glob(".restore-*")), [])
        self.assertFalse(loop.HOLD.locked(), "the loop is free again")

    def test_a_failed_rollback_keeps_the_moved_files_and_says_where(self):
        (self.home / "profile.md").write_text("# Jane\nprecious\n", encoding="utf-8")
        zp = extras.backup()
        real = extras._move

        def broken(src, dst):
            if ".restore-stage-" in str(src) or ".restore-old-" in str(src):  # neither in nor back
                raise PermissionError("locked")
            return real(src, dst)

        with patched(extras, _move=broken), self.assertRaises(SystemExit) as e:
            extras.restore(zp)
        self.assertIn("could not put every file back", str(e.exception))
        self.assertIn("before-restore-", str(e.exception))
        kept = list(self.home.glob(".restore-old-*/profile.md"))
        self.assertEqual(len(kept), 1, "the moved-aside files are never deleted")
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "# Jane\nprecious\n")
        extras._move(kept[0], self.home / "profile.md")  # what the message tells you to do
        for d in self.home.glob(".restore-old-*"):
            shutil.rmtree(d)

    def test_an_older_backup_gets_the_additive_migrations(self):
        f = self.home / "old.db"
        c = db.connect(f)
        c.execute("ALTER TABLE jobs DROP COLUMN soc_by")  # as a database from before pass 20
        c.commit()
        c.close()
        zp = self.zip_of({"lodestar.db": f.read_bytes(), "profile.md": b"# Old\n"})
        f.unlink()
        extras.restore(zp)
        self.assertIn("soc_by", {r["name"] for r in db.con().execute("PRAGMA table_info(jobs)")})

    def test_cli_restore_asks_and_restores_with_yes(self):
        db.add_job("Hooli", "PM", None, "jd")
        db.release()
        zp = extras.backup()
        out = io.StringIO()
        with patched(sys, stdin=io.StringIO("")), contextlib.redirect_stdout(out):
            a = build().parse_args(["restore", str(zp)])
            a.f(a)
        self.assertIn("not restored (no answer; use --yes)", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            a = build().parse_args(["restore", str(zp), "--yes"])
            a.f(a)
        self.assertIn("restored", out.getvalue())
        self.assertIn("safety backup of what was there", out.getvalue())
        self.assertIn("keyring", out.getvalue())


class Refusals(Home):
    def refused(self, zp, text):
        before = sorted(p.name for p in (self.home / "backups").glob("*.zip")) if (self.home / "backups").is_dir() else []
        with self.assertRaises(SystemExit) as e:
            extras.restore(zp)
        self.assertIn(text, str(e.exception))
        after = sorted(p.name for p in (self.home / "backups").glob("*.zip")) if (self.home / "backups").is_dir() else []
        self.assertEqual(before, after, "a refused zip leaves no safety backup")
        self.assertEqual(list(self.home.glob(".restore-*")), [])
        return str(e.exception)

    def test_path_traversal_absolute_drive_backslash_and_reserved_names_are_refused(self):
        dbb = self.good_db()
        for bad in ("../evil.md", "applications/../../evil.md", "/etc/evil.md", "C:/evil.md", "a\\..\\evil.md",
                    "con.md", "applications/nul", "trailing./x.md", "./x.md", "a//b.md"):
            with self.subTest(bad=bad):
                msg = self.refused(self.zip_of({"lodestar.db": dbb, bad: b"x"}), "unsafe path")
                self.assertIn("nothing was changed", msg)
        self.assertFalse((self.home.parent / "evil.md").exists())

    def test_links_programs_case_clashes_and_a_zip_without_the_database_are_refused(self):
        dbb = self.good_db()
        self.refused(self.zip_of({"lodestar.db": dbb, "link.md": (b"/etc/passwd", (stat.S_IFLNK | 0o777) << 16)}), "a link")
        self.refused(self.zip_of({"lodestar.db": dbb, "applications/1-a-b/run.ps1": b"x"}), "a program or script")
        self.refused(self.zip_of({"lodestar.db": dbb, "Profile.md": b"a", "profile.md": b"b"}), "differ only by case")
        self.refused(self.zip_of({"profile.md": b"x"}), "not a Lodestar backup")
        notzip = self.home / "notzip.zip"
        notzip.write_bytes(b"plain text")
        self.addCleanup(notzip.unlink)
        self.refused(notzip, "not a zip file")

    def test_size_and_entry_caps_refuse_before_anything_is_written(self):
        dbb = self.good_db()
        zp = self.zip_of({"lodestar.db": dbb, "big.md": b"0" * 5000})
        with patched(extras, RESTORE_MAX_FILE=4000):
            self.refused(zp, "an entry larger than")
        with patched(extras, RESTORE_MAX_TOTAL=len(dbb) + 100):
            self.refused(zp, "unpacks to more than")
        with patched(extras, RESTORE_MAX_ZIP=100):
            self.refused(zp, "is larger than")
        with patched(extras, RESTORE_MAX_FILES=1):
            self.refused(zp, "more than 1 entries")

    def test_a_damaged_database_is_refused_and_nothing_changes(self):
        (self.home / "profile.md").write_text("# Jane\nmine\n", encoding="utf-8")
        self.refused(self.zip_of({"lodestar.db": b"this is not sqlite" * 100, "profile.md": b"# Other\n"}), "does not open")
        self.assertEqual((self.home / "profile.md").read_text(encoding="utf-8"), "# Jane\nmine\n")
        self.refused(self.zip_of({"lodestar.db": self.good_db(), "settings.json": b"{broken"}), "settings.json is not valid JSON")

    def test_files_a_backup_never_carries_are_skipped_not_restored(self):
        zp = self.zip_of({"lodestar.db": self.good_db(), ".env": b"OPENAI_API_KEY=sk-x", "extension.json": b"{}",
                          "procs/123.pid": b"1", "update-state.json": b"{}", "lodestar.log": b"x", "profile.md": b"# P\n"})
        plan = extras.restore_check(zp)
        self.assertEqual(sorted(str(r) for _, r in plan["files"]), ["lodestar.db", "profile.md"])
        self.assertEqual(sorted(plan["skipped"]), [".env", "extension.json", "lodestar.log", "procs/123.pid", "update-state.json"])
        (self.home / ".env").write_text("MINE=1", encoding="utf-8")
        self.addCleanup((self.home / ".env").unlink, missing_ok=True)
        r = extras.restore(zp)
        self.assertEqual((self.home / ".env").read_text(encoding="utf-8"), "MINE=1")
        self.assertFalse((self.home / "update-state.json").exists())
        self.assertEqual(len(r["skipped"]), 5)

    def test_case_variants_and_short_names_never_reach_the_files_a_restore_must_not_touch(self):
        """On Windows 'Extension.json' IS extension.json and EXTENS~1.JSO can name it: a zip must neither plant a
        browser pairing or .env nor delete one through another spelling."""
        dbb = self.good_db()
        ext = self.home / "extension.json"
        ext.write_text('{"paired": "mine"}', encoding="utf-8")
        (self.home / ".env").write_text("MINE=1", encoding="utf-8")
        self.addCleanup(ext.unlink, missing_ok=True)
        self.addCleanup((self.home / ".env").unlink, missing_ok=True)
        evil = {"Extension.json": b'{"paired": "evil"}', ".ENV": b"OPENAI_BASE_URL=http://attacker.example",
                "Backups/planted.zip": b"x", "Procs/x.json": b"{}", "Capture.Token": b"x", "LODESTAR.LOG.1": b"x",
                "Update-State.JSON": b"{}", "profile.md": b"# P\n"}
        plan = extras.restore_check(self.zip_of({"lodestar.db": dbb, **evil}))
        self.assertEqual(sorted(str(r) for _, r in plan["files"]), ["lodestar.db", "profile.md"])
        self.assertEqual(len(plan["skipped"]), len(evil) - 1)
        extras.restore(self.zip_of({"lodestar.db": dbb, **evil}))
        self.assertEqual(ext.read_text(encoding="utf-8"), '{"paired": "mine"}')
        self.assertEqual((self.home / ".env").read_text(encoding="utf-8"), "MINE=1")
        self.assertFalse((self.home / "backups" / "planted.zip").exists())
        for short in ("EXTENS~1.JSO", "CAPTUR~1.TOK", "BACKUP~1/x.zip", "applications/1-a-b/RESUME~12.MD"):
            with self.subTest(short=short):
                self.refused(self.zip_of({"lodestar.db": dbb, short: b"x"}), "short (8.3) name")
        self.refused(self.zip_of({"LODESTAR.DB": dbb}), "the database under another spelling")
        self.assertTrue(ext.is_file())

    def test_a_page_picks_a_backup_by_bare_name_only(self):
        for bad in ("../x.zip", "..\\x.zip", "C:/x.zip", "x.txt", "", "missing.zip"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                extras.backup_file(bad)
        zp = extras.backup()
        self.assertEqual(extras.backup_file(zp.name), zp)


class Busy(Home):
    def setUp(self):
        self.zp = extras.backup()

    def busy(self, text):
        with self.assertRaises(SystemExit) as e:
            extras.restore(self.zp)
        self.assertIn(text, str(e.exception))

    def test_refused_while_a_loop_cycle_runs(self):
        loop.HOLD.acquire()
        try:
            self.busy("the monitor loop is in the middle of a cycle")
        finally:
            loop.HOLD.release()

    def test_refused_while_an_inbox_send_a_scan_or_a_background_action_is_in_flight(self):
        pid = db.add_pending("email_reply", "send_email", None, "reply", "{}")
        db.claim_pending(pid)
        db.release()
        try:
            self.busy("an Inbox action is being sent")
        finally:
            db.decide_pending(pid, "rejected", "test")
            db.release()
        lock = self.home / ".email.lock"
        lock.write_text("1", encoding="utf-8")
        try:
            self.busy("another email run is in progress")
        finally:
            lock.unlink()
        with patched(web, TASKS={"t1": {"status": "running", "action": "tailor"}}):
            self.busy("a background action is running")
        with patched(web, TASKS={"t1": {"status": "running", "action": "restore"}}):
            self.assertIsNone(extras.restore_busy(), "the restore's own task is not in its way")

    def test_refused_during_an_update_another_process_or_full_ai(self):
        updater.LOCK.write_text(str(os.getpid()), encoding="utf-8")
        try:
            self.busy("an update is running")
        finally:
            updater.LOCK.unlink()
        updater.PROCS.mkdir(exist_ok=True)
        other = updater.PROCS / f"{os.getppid()}.pid"  # the parent: alive, and not this process
        other.write_text(f"{time.time():.0f}", encoding="utf-8")  # started before now: a live holder
        try:
            self.busy("another Lodestar process is running")
        finally:
            other.unlink(missing_ok=True)
        config.FULL_AI.on = True
        try:
            self.busy("Full AI never restores a backup")
        finally:
            config.FULL_AI.on = False


class Routes(Home):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = web.start_server(0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        super().tearDownClass()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-Lodestar-Token": web.TOKEN, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_backups_list_restore_task_and_refusals_before_a_task(self):
        zp = extras.backup()
        st, out = self.call("/api/backups")
        self.assertEqual(st, 200)
        self.assertIn(zp.name, [b["name"] for b in out["backups"]])
        st, out = self.call("/api/run/restore", {"name": "../" + zp.name})
        self.assertEqual(st, 400)
        self.assertIn("pick a backup from the list", out["error"])
        bad = self.zip_of({"profile.md": b"x"}, name="backups/bad.zip")
        st, out = self.call("/api/run/restore", {"name": bad.name})
        self.assertEqual((st, "not a Lodestar backup" in out["error"]), (400, True))
        st, out = self.call("/api/run/restore", {"name": zp.name})
        self.assertEqual(st, 200)
        for _ in range(200):
            t = web.TASKS[out["task"]]
            if t["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(t["status"], "done", t)
        self.assertTrue(t["result"]["safety_backup"].endswith(".zip"))
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/api/backups", timeout=10)
        self.assertEqual(e.exception.code, 403)
        e.exception.close()

    def test_palette_documents_are_viewer_refs_never_paths_or_contents(self):
        jid = db.add_job("Umbrella", "Chemist", None, "jd")
        j = db.get_job(jid)
        db.release()
        d = extras._job_dir(j)
        d.mkdir(parents=True, exist_ok=True)
        (d / "cover_letter.md").write_text("SECRET LETTER TEXT", encoding="utf-8")
        (d / "notes.json").write_text("{}", encoding="utf-8")  # not a viewer document
        from lodestar import profile

        master = profile.RESUMES / "master.md"
        master.unlink(missing_ok=True)
        st, out = self.call("/api/docs")
        self.assertEqual(st, 200)
        self.assertNotIn({"type": "master"}, [x["ref"] for x in out["docs"]], "no master yet: the palette offers none")
        master.parent.mkdir(parents=True, exist_ok=True)
        master.write_text("# Jane\n", encoding="utf-8")
        self.addCleanup(master.unlink, missing_ok=True)
        st, out = self.call("/api/docs")
        refs = [x["ref"] for x in out["docs"]]
        self.assertIn({"type": "master"}, refs)
        self.assertIn({"type": "job", "id": jid, "name": "cover_letter.md"}, refs)
        self.assertNotIn("notes.json", str(out))
        self.assertNotIn("SECRET LETTER TEXT", str(out))
        self.assertNotIn(self.home.name, json.dumps(out), "no paths")


if __name__ == "__main__":
    unittest.main()
