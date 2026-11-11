"""Overview fixes, outcomes and platform: the counter-offer draft passes the salary-floor guard and signs with your
name, alert and digest emails get a one-line subject and a visible failure, the loop survives a stray SystemExit and
skips the optional mailbox quietly, preferences are range-checked, backups keep at least one and never overwrite in
the same minute, the schedule works from the exe and reads the install folder's .env, the installers keep the Start
Menu folder and check the Python version; plus the small improvements (funnel n<5 guard, Insights range, market-rate
amounts like 150k, catch-up digest, corrupt vault index, doctor --live row). No network: SMTP and AI are faked and
every patched attribute is put back."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, comp, config, db, doctor, extras, loop, profile, settings, util, vault  # noqa: E402
from lodestar.config import ALERTS, HOME, PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FLOOR = 187654
REAL = ("# Jane Example\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"
        f"\n## Preferences\nSalary floor: ${FLOOR:,} | Deal-breakers: none\n")


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


def env(**values):
    """setting() stand-in: only these values, never the real vault or environment."""
    return lambda k, d=None: values.get(k, d)


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")

    def tearDown(self):
        c = getattr(db._local, "con", None)
        if c is not None:
            c.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)


class CounterOffer(Base):  # outcomes-platform-counter-offer
    def test_counter_offer_is_screened_even_as_a_draft_and_signs_with_the_profile_name(self):
        mine, other = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "Data Engineer")
        db.set_offer(mine, base=150000)
        db.set_offer(other, base=175000)
        leak = {"subject": "Re: offer", "body": f"My salary floor is ${FLOOR:,} so I need a base of {FLOOR:,}."}
        with patched(ai, available=lambda: ["anthropic"], ask_json=lambda *a, **k: dict(leak)):
            with self.assertRaises(SystemExit):  # no contact email: the draft-only copy you would paste is guarded too
                apply.counter(db.get_job(mine), [f"{other}:base"])
        with self.assertRaises(SystemExit):  # the ask typed as the floor figure
            apply.counter(db.get_job(mine), [], f"a base of {FLOOR:,}", template=True)
        self.assertNotIn("counter_draft", {e["kind"] for e in db.events(mine)})  # a refused draft leaves no trace
        t = apply.counter(db.get_job(mine), [f"{other}:base"], template=True)
        self.assertTrue(t["draft"]["body"].endswith("Best regards,\nJane Example"), t["draft"]["body"])


class Notify(Base):  # outcomes-platform-digest-email, outcomes-platform-notify-email
    def test_alert_and_digest_mail_have_a_one_line_subject_and_a_visible_failure(self):
        sent = []
        fake_send = lambda to, subject, body, *a, **k: sent.append((to, subject, body))  # noqa: E731
        size = ALERTS.stat().st_size if ALERTS.is_file() else 0
        with patched(util, send_email=fake_send, setting=env(LODESTAR_NOTIFY_EMAIL="me@example.com")), \
                contextlib.redirect_stdout(io.StringIO()):
            util.notify("CHANGED https://e.co/c:\n  Senior Data Engineer")
        self.assertEqual(sent[0][1], "[lodestar] CHANGED https://e.co/c:")  # a header may not hold a newline
        with patched(util, send_email=fake_send), patched(config, setting=env(LODESTAR_NOTIFY_EMAIL="me@example.com")), \
                patched(ai, available=lambda: []):
            extras.digest(7, send=True)
        self.assertNotIn("\n", sent[1][1])
        self.assertIn("## Moved this week", sent[1][2])
        with patched(util, send_email=fake_send), patched(config, setting=env()), patched(ai, available=lambda: []):
            with self.assertRaises(SystemExit) as cm:  # no address: said, not silently dumped into alerts.log
                extras.digest(7, send=True)
        self.assertIn("LODESTAR_NOTIFY_EMAIL", str(cm.exception))
        self.assertEqual(len(sent), 2)
        with ALERTS.open("rb") as f:
            f.seek(size)
            self.assertNotIn(b"## Moved this week", f.read())  # the digest text never lands in alerts.log

    def test_digest_pipeline_line_reads_as_words(self):  # improvement (digest text)
        db.add_job("Acme", "Data Engineer")
        with patched(ai, available=lambda: []):
            line = next(ln for ln in extras.digest(7).splitlines() if ln.startswith("Pipeline:"))
        self.assertIn("saved 1", line)
        self.assertNotIn("{", line)


class Loop(Base):
    class A:
        email = True; days = 1; provider = None; followup = 7; every = 5; once = True  # noqa: E702

    def test_run_survives_a_systemexit_outside_any_step(self):  # outcomes-platform-monitor-loop
        def boom(a):
            raise SystemExit("settings unreadable")
        with patched(loop, cycle=boom):
            loop.run(self.A())  # returns instead of ending the thread
        self.assertIn("cycle: settings unreadable", loop.STATUS["last_error"])
        self.assertFalse(loop.STATUS["running"])

    def test_no_mailbox_is_skipped_quietly(self):  # outcomes-platform-loop-status
        from lodestar import email_monitor, web_monitor
        calls = []
        with patched(loop, setting=env()), patched(util, setting=env()), \
                patched(email_monitor, check=lambda *a, **k: calls.append(1)), \
                patched(web_monitor, check_watches=lambda: None, check_listings=lambda: None), \
                patched(loop, _backup=lambda: None, _digest=lambda a: None), contextlib.redirect_stdout(io.StringIO()) as out:
            loop.STATUS["last_error"] = "09:00 email: email is not connected"  # a problem from an earlier cycle
            loop.cycle(self.A())
        self.assertEqual(calls, [])
        self.assertIsNone(loop.STATUS["last_error"])
        self.assertIn("email: skipped", out.getvalue())

    def test_missed_friday_digest_catches_up_once(self):  # improvement (digest text)
        sat, sun, fri = datetime(2026, 11, 7, 9), datetime(2026, 11, 8, 9), datetime(2026, 11, 13, 9)
        settings.set_tool("digest", enabled=True, auto=True)
        with patched(loop, setting=env()), patched(util, setting=env()), contextlib.redirect_stdout(io.StringIO()) as out:
            loop._digest(self.A(), sat)  # the app was closed on Friday the 6th
            loop._digest(self.A(), sun)
            loop._digest(self.A(), fri)
        self.assertEqual(out.getvalue().count("DIGEST ready"), 2)


class Prefs(Base):  # outcomes-platform-prefs-validation
    def test_whole_number_prefs_are_range_checked_and_switches_are_on_or_off(self):
        for key, bad in (("followup_days", "-3"), ("followup_days", "0"), ("auto_track_min_score", "900"),
                         ("weekly_target", "500"), ("desktop_notifications", "maybe")):
            with self.assertRaises(SystemExit, msg=(key, bad)):
                settings.set_pref(key, bad)
        settings.set_pref("followup_days", "14")
        settings.set_pref("desktop_notifications", True)
        self.assertEqual((settings.pref("followup_days"), settings.pref("desktop_notifications")), (14, True))


class Backup(Base):  # outcomes-platform-backup
    def test_keep_zero_is_refused_and_two_backups_in_one_minute_both_stay(self):
        out = Path(tempfile.mkdtemp())
        with self.assertRaises(SystemExit):
            extras.backup(out, keep=0)
        stamps = iter([datetime(2026, 11, 7, 12, 0, 1), datetime(2026, 11, 7, 12, 0, 31)])

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return next(stamps)
        with patched(extras, datetime=Clock):
            a, b = extras.backup(out), extras.backup(out)
        self.assertNotEqual(a, b)
        self.assertEqual(len(list(out.glob("lodestar-backup-*.zip"))), 2)


class Schedule(unittest.TestCase):  # outcomes-platform-schedule
    def test_exe_task_runs_the_subcommand_and_cron_logs_under_the_data_folder(self):
        sys.frozen = True  # what PyInstaller sets; absent otherwise
        try:
            with patched(extras.platform, system=lambda: "Linux"):
                line = extras.schedule("install", 15)
        finally:
            del sys.frozen
        self.assertIn(f'"{sys.executable}" run --once', line)
        self.assertNotIn("-m lodestar", line)
        self.assertIn(str(HOME / "cron.log"), line)

    def test_the_install_folders_env_is_read_from_any_working_folder(self):
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "lodestar", tmp / "app" / "lodestar", ignore=shutil.ignore_patterns("__pycache__"))
        (tmp / "app" / ".env").write_text("LS_DOTENV_PROBE=install-folder\n", encoding="utf-8")
        (tmp / "elsewhere").mkdir()
        e = {k: v for k, v in os.environ.items() if k != "LS_DOTENV_PROBE"} | {
            "PYTHONPATH": str(tmp / "app"), "LODESTAR_HOME": str(tmp / "home")}
        r = subprocess.run([sys.executable, "-c", "import os, lodestar.config; print(os.environ.get('LS_DOTENV_PROBE'))"],
                           cwd=tmp / "elsewhere", env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "install-folder", r.stderr)


class Installers(unittest.TestCase):  # outcomes-platform-installer-ps1, outcomes-platform-installer-sh
    def test_windows_installer_keeps_the_start_menu_folder_and_checks_python(self):
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        removes = [ln for ln in ps1.splitlines() if "Remove-Item" in ln and "-Recurse" in ln and "Programs" in ln]
        self.assertEqual(removes, [])  # NTFS is case-insensitive: removing 'lodestar' deleted the new 'Lodestar'
        self.assertIn("sys.version_info < (3, 11)", ps1)

    def test_shell_installer_checks_python_installs_pdf_and_honours_lodestar_home(self):
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("sys.version_info < (3, 11)", sh)
        self.assertIn('-e ".[pdf]"', sh)
        cron = next(ln for ln in sh.splitlines() if "cron.log" in ln)
        self.assertIn("${LODESTAR_HOME:-$HOME/.lodestar}/cron.log", cron)


class Docs(unittest.TestCase):  # outcomes-platform-export, outcomes-platform-docs-claims
    def test_commands_doc_lists_every_exported_table_and_every_pref(self):
        doc = (ROOT / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        export = next(ln for ln in doc.splitlines() if ln.startswith("| `lodestar export json / csv"))
        for t in ("jobs", "events", "answers", "ideas", "pending", "contacts", "job_contacts", "interviews",
                  "mock_sessions", "offers", "touches", "mail"):
            self.assertIn(t, export)
        prefs = next(ln for ln in doc.splitlines() if ln.startswith("| `lodestar tools set KEY VALUE`"))
        for k in settings.PREFS:
            self.assertIn(k, prefs)
        digest = next(ln for ln in doc.splitlines() if ln.startswith("| `lodestar digest"))
        self.assertIn("LODESTAR_NOTIFY_EMAIL", digest)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn('/TR "lodestar run --once"', readme)  # needs lodestar on PATH, which the installer never adds


class Improvements(Base):
    def test_funnel_conversion_needs_enough_jobs(self):  # insights-analytics
        for i in range(2):
            j = db.add_job(f"Co{i}", "Engineer")
            db.set_status(j, "applied")
            db.set_status(j, "offer")
        st = extras.analytics()["funnel"]["stages"]
        self.assertEqual(st["offer"]["reached"], 2)
        self.assertIsNone(st["offer"]["conversion"])

    def test_insights_range_and_market_rates_as_typed(self):  # insights-ui, market-rates
        import http.client
        import json

        from lodestar import desktop, web
        port = desktop.free_port(8930)
        srv = web.start_server(port)
        snap = comp.PATH.read_bytes() if comp.PATH.is_file() else None
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/api/analytics?weeks=4", headers={"X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"})
            self.assertEqual(len(json.loads(c.getresponse().read())["weeks"]), 4)
            comp.set_range("data engineer", "*", "$140,000", "170k")
            self.assertEqual(comp.load()["data engineer"]["*"], [140000, 170000])
            with self.assertRaises(ValueError) as cm:
                comp.set_range("data engineer", "*", "abc", "170k")
            self.assertIn("low must be an annual amount", str(cm.exception))
        finally:
            srv.shutdown()
            comp.PATH.write_bytes(snap) if snap is not None else comp.PATH.unlink(missing_ok=True)

    def test_corrupt_vault_index_reads_as_empty(self):  # vault
        snap = vault.INDEX.read_bytes() if vault.INDEX.is_file() else None
        try:
            vault.INDEX.write_text("{not json", encoding="utf-8")
            self.assertEqual(vault._index(), {})
        finally:
            vault.INDEX.write_bytes(snap) if snap is not None else vault.INDEX.unlink(missing_ok=True)

    def test_doctor_live_says_when_there_is_nothing_to_call(self):  # doctor
        with patched(doctor, checks=lambda: [("ok", "python", "3")], live_mail=lambda: []), \
                patched(ai, available=lambda: []), contextlib.redirect_stdout(io.StringIO()) as out:
            doctor.report(live=True)
        self.assertIn("skipped: no AI provider or mailbox configured", out.getvalue())

    def test_tools_tab_markup_carries_no_raw_key(self):  # tools-ui
        js = (ROOT / "lodestar" / "static" / "app.js").read_text(encoding="utf-8")
        body = js[js.index("function renderTools()"):js.index("async function setPref")]
        self.assertNotIn("'${k}'", body)
        self.assertNotIn("'${t.tool}'", body)
        self.assertNotIn("<b>${t.tool}</b>", body)


if __name__ == "__main__":
    unittest.main()
