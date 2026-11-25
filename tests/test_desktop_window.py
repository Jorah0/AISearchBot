"""Desktop window: closing it minimizes to the taskbar unless pref close_to_taskbar is off (an explicit Quit or Restart
still closes it), and pref start_on_boot adds / removes the per-user Run entry that starts Lodestar at sign-in.
No real window and no real registry: a fake window and a fake winreg module; every patched attribute is put back."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import desktop, phone, settings  # noqa: E402


class FakeWindow:
    def __init__(self):
        self.minimized = 0

    def minimize(self):
        self.minimized += 1


class FakeReg(types.ModuleType):
    """The few winreg calls set_autostart makes, over a dict."""
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = 1, 2, 1

    def __init__(self):
        super().__init__("winreg")
        self.values = {}

    def OpenKey(self, root, path, reserved=0, access=0):  # noqa: N802 (winreg's names)
        self.path = path
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def SetValueEx(self, key, name, reserved, kind, value):  # noqa: N802
        self.values[name] = value

    def DeleteValue(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class Window(unittest.TestCase):
    def setUp(self):
        self.addCleanup(settings.set_pref, "close_to_taskbar", settings.pref("close_to_taskbar"))
        self.addCleanup(setattr, desktop, "QUIT", False)

    def test_closing_minimizes_to_the_taskbar_until_turned_off_or_quit(self):
        w = FakeWindow()
        self.assertTrue(settings.PREFS["close_to_taskbar"])  # on unless you turn it off
        self.assertIs(desktop._on_closing(w), False)  # False cancels the close
        desktop._MIN_THREADS and desktop._MIN_THREADS[-1].join(5)
        self.assertEqual(w.minimized, 1)
        desktop.QUIT = True  # Quit Lodestar / Restart: the window really closes
        self.assertIsNone(desktop._on_closing(w))
        desktop.QUIT = False
        with patched(desktop, _session_ending=lambda: True):  # Windows signing out / shutting down: never blocked
            self.assertIsNone(desktop._on_closing(w))
        self.assertFalse(desktop._session_ending())  # this test run is not a session end
        settings.set_pref("close_to_taskbar", False)
        self.assertIsNone(desktop._on_closing(w))
        self.assertEqual(w.minimized, 1)

    def test_quit_is_desktop_only_and_never_from_a_phone(self):
        self.assertTrue(any("/api/desktop/quit".startswith(d) for d in phone.DENY))


class Boot(unittest.TestCase):
    def setUp(self):
        self.reg = FakeReg()
        saved = sys.modules.get("winreg")
        sys.modules["winreg"] = self.reg
        self.addCleanup(lambda: sys.modules.__setitem__("winreg", saved) if saved else sys.modules.pop("winreg", None))
        self.addCleanup(lambda v=settings.load()["prefs"].get("start_on_boot", False): self._restore(v))

    def _restore(self, v):
        with patched(desktop, set_autostart=lambda on: None):
            settings.set_pref("start_on_boot", v)

    @unittest.skipUnless(os.name == "nt", "the Run key is Windows only")
    def test_start_on_boot_writes_and_removes_the_run_entry(self):
        with self.assertRaises(SystemExit):  # a temp LODESTAR_HOME (this test) never touches the real entry
            desktop.set_autostart(True)
        self.assertEqual(self.reg.values, {})
        own = patched(desktop, _own_home=lambda: True)
        own.__enter__()
        self.addCleanup(own.__exit__, None, None, None)
        desktop.set_autostart(True)
        cmd = self.reg.values["Lodestar"]
        self.assertIn("Microsoft\\Windows\\CurrentVersion\\Run", self.reg.path)
        self.assertTrue(cmd.endswith(" desktop --minimized"), cmd)
        self.assertNotIn("python.exe", cmd.lower().replace("pythonw.exe", ""))  # never a console window at sign-in
        desktop.set_autostart(False)
        self.assertNotIn("Lodestar", self.reg.values)
        desktop.set_autostart(False)  # already off: nothing to remove, no error

    def test_the_pref_applies_the_entry_and_a_failure_keeps_the_old_value(self):
        calls = []
        with patched(desktop, set_autostart=calls.append):
            settings.set_pref("start_on_boot", "on")
        self.assertEqual(calls, [True])
        self.assertTrue(settings.pref("start_on_boot"))
        with patched(desktop, set_autostart=calls.append):
            settings.set_pref("start_on_boot", "on")  # on again: the entry is rewritten (a moved install heals)
        self.assertEqual(calls, [True, True])

        def boom(on):
            raise SystemExit("could not change the Windows startup entry: denied")
        with patched(desktop, set_autostart=boom), self.assertRaises(SystemExit):
            settings.set_pref("start_on_boot", "off")
        self.assertTrue(settings.pref("start_on_boot"))  # unchanged: the pref never says on when the entry is not there


if __name__ == "__main__":
    unittest.main()
