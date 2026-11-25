"""scripts/android_e2e.py, without an emulator: the uiautomator XML parser and node finder, the boot wait with a fake
adb, SKIPPED detection, the throwaway-home guard (never ~/.lodestar), APK staleness, and every process it starts
passing creationflags (no console window)."""
import ast
import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("android_e2e", ROOT / "scripts" / "android_e2e.py")
ae = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ae)

DUMP = """UI hierchary dumped to: /sdcard/ui.xml<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0"><node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="app.lodestar.mobile"
 content-desc="" bounds="[0,0][1080,2400]"><node index="0" text="Connect to Lodestar" resource-id="" class="android.widget.TextView"
 package="app.lodestar.mobile" content-desc="" bounds="[55,200][1025,280]" /><node index="1" text="" resource-id="app:id/addr"
 class="android.widget.EditText" package="app.lodestar.mobile" content-desc="" hint="http://192.168.1.153:8780"
 bounds="[55,300][1025,400]" /><node index="2" text="" resource-id="" class="android.widget.Button" package="app.lodestar.mobile"
 content-desc="Today" bounds="[0,500][200,600]" /></node></hierarchy>"""


class Parse(unittest.TestCase):
    def test_nodes_carry_text_id_class_and_the_centre_of_their_bounds(self):
        nodes = ae.parse_nodes(DUMP)
        self.assertEqual(len(nodes), 4)
        t = ae.find(nodes, text="Connect to Lodestar")
        self.assertEqual((t["x"], t["y"], t["cls"]), (540, 240, "android.widget.TextView"))
        e = ae.find(nodes, rid="app:id/addr")
        self.assertEqual((e["cls"], e["hint"]), ("android.widget.EditText", "http://192.168.1.153:8780"))

    def test_find_by_content_desc_class_and_substring(self):
        nodes = ae.parse_nodes(DUMP)
        self.assertEqual(ae.find(nodes, text="Today")["y"], 550)  # a WebView node names itself in content-desc
        self.assertIsNone(ae.find(nodes, text="Connect"))
        self.assertIsNotNone(ae.find(nodes, text="CONNECT TO LODESTAR"))  # Material buttons upper-case their text
        self.assertEqual(ae.find(nodes, text="Connect", contains=True)["text"], "Connect to Lodestar")
        self.assertIsNone(ae.find(nodes, text="Today", cls="android.widget.TextView"))


class Boot(unittest.TestCase):
    def _clock(self):
        now = [0.0]
        return now, (lambda: now[0]), (lambda s: now.__setitem__(0, now[0] + s))

    def test_waits_through_errors_and_blanks_until_boot_completed(self):
        now, clock, sleep = self._clock()
        answers = iter([OSError("device offline"), "", "0\n", "1\n"])

        def getprop():
            a = next(answers)
            if isinstance(a, BaseException):
                raise a
            return a

        self.assertEqual(ae.wait_boot(getprop, 60, sleep, clock), 6)

    def test_times_out(self):
        now, clock, sleep = self._clock()
        with self.assertRaises(TimeoutError):
            ae.wait_boot(lambda: "0", 10, sleep, clock)
        self.assertLessEqual(now[0], 14)


class Skip(unittest.TestCase):
    def test_names_what_is_missing(self):
        d = Path(tempfile.mkdtemp())
        sdk, avds = d / "sdk", d / "avd"
        self.assertIn("no Android SDK", ae.skip_reason(sdk, "x", avds))
        (sdk / "platform-tools").mkdir(parents=True)
        self.assertIn("no adb", ae.skip_reason(sdk, "x", avds))
        (sdk / "platform-tools" / ae.exe("adb")).write_text("")
        self.assertIn("no Android emulator", ae.skip_reason(sdk, "x", avds))
        (sdk / "emulator").mkdir()
        (sdk / "emulator" / ae.exe("emulator")).write_text("")
        self.assertIn("no AVD named x", ae.skip_reason(sdk, "x", avds))
        avds.mkdir()
        (avds / "x.ini").write_text("")
        self.assertEqual(ae.skip_reason(sdk, "x", avds), "")

    def test_a_skip_prints_skipped_never_pass(self):
        import contextlib
        import io

        old = ae.sdk_dir
        ae.sdk_dir = lambda: Path(tempfile.mkdtemp()) / "none"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(ae.main(), 0)
        finally:
            ae.sdk_dir = old
        self.assertIn("SKIPPED: no Android SDK", out.getvalue())
        self.assertNotIn("PASS", out.getvalue())


class Home(unittest.TestCase):
    def test_refuses_the_real_data_folders(self):
        for p in (Path.home() / ".lodestar", Path.home() / ".lodestar" / "sub", Path.home() / ".jobbot"):
            with self.assertRaises(SystemExit):
                ae.safe_home(p)

    def test_refuses_a_folder_outside_temp_and_takes_a_temp_one(self):
        with self.assertRaises(SystemExit):
            ae.safe_home(ROOT)
        d = tempfile.mkdtemp(prefix="lodestar-android-e2e-")
        self.assertEqual(ae.safe_home(d), Path(d).resolve())


class Build(unittest.TestCase):
    def test_stale_when_missing_or_older_than_a_source(self):
        d = Path(tempfile.mkdtemp())
        apk, src = d / "a.apk", d / "src"
        (src / "x").mkdir(parents=True)
        (src / "x" / "Main.java").write_text("class A {}")
        self.assertTrue(ae.apk_stale(apk, [src]))
        apk.write_bytes(b"PK")
        t = time.time()
        os.utime(src / "x" / "Main.java", (t - 100, t - 100))
        self.assertFalse(ae.apk_stale(apk, [src]))
        os.utime(src / "x" / "Main.java", (t + 100, t + 100))
        self.assertTrue(ae.apk_stale(apk, [src]))


class Console(unittest.TestCase):
    def test_every_process_it_starts_passes_creationflags(self):
        tree = ast.parse((ROOT / "scripts" / "android_e2e.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("run", "Popen", "call", "check_output") and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "subprocess"]
        self.assertGreaterEqual(len(calls), 2)
        for c in calls:
            self.assertIn("creationflags", {k.arg for k in c.keywords}, f"line {c.lineno}")


if __name__ == "__main__":
    unittest.main()
