"""No console window behind the desktop app: the Lodestar shortcut and the scheduled task start the windowless launcher
(lodestarw, a gui-script), whose output goes to a log file instead of a console, and every helper program Lodestar
starts (git, the update gate, headless Edge, taskkill, schtasks) is created without a console window.
No network; every patched attribute is put back."""
import ast
import io
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import cli, config, updater, util  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# the only launches allowed without creationflags: GUI programs (a browser window) and non-Windows openers
ALLOWED = {("apply_agent.py", "Popen"), ("web.py", "Popen")}


class Hidden(unittest.TestCase):
    def test_desktop_shortcut_and_scheduled_task_use_the_windowless_launcher(self):
        meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(meta["project"]["gui-scripts"]["lodestarw"], "lodestar.cli:main_hidden")
        ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn('lodestarw.exe', ps)
        self.assertRegex(ps, r'Name = "Lodestar";\s+Exe = \$jbw;\s+Args = "desktop"')
        self.assertRegex(ps, r'schtasks /Create .*\$jbw')
        start = (ROOT / "start.ps1").read_text(encoding="utf-8")
        self.assertIn("lodestarw.exe", start)

    def test_windowless_output_goes_to_a_log_file(self):
        seen = []
        real = (sys.stdout, sys.stderr, cli.main)
        sys.stdout = sys.stderr = None  # what a gui-script (pythonw) process starts with
        cli.main = lambda argv=None: (print("hello from the app"), seen.append(sys.stdout))
        try:
            cli.main_hidden()
            out = seen[0]
        finally:
            sys.stdout, sys.stderr, cli.main = real
        out.flush()
        self.assertIn("hello from the app", (config.HOME / "logs" / "console.log").read_text(encoding="utf-8"))
        real_out = io.StringIO()
        sys.stdout, keep = real_out, sys.stdout  # a console start keeps its console
        cli.main = lambda argv=None: print("visible")
        try:
            cli.main_hidden()
        finally:
            sys.stdout, cli.main = keep, real[2]
        self.assertEqual(real_out.getvalue(), "visible\n")

    def test_helper_programs_start_without_a_console(self):
        self.assertEqual(util.NO_WINDOW, getattr(subprocess, "CREATE_NO_WINDOW", 0))
        got = {}

        class P:
            pid, returncode = 1, 0

            def __init__(self, cmd, **kw):
                got.update(kw)

            def wait(self, timeout=None):
                return 0
        real = updater.subprocess.Popen
        updater.subprocess.Popen = P
        try:
            updater._proc(["git", "--version"], ROOT, 5)
        finally:
            updater.subprocess.Popen = real
        if os.name == "nt":
            self.assertTrue(got["creationflags"] & subprocess.CREATE_NO_WINDOW)
        for f in (ROOT / "lodestar").glob("*.py"):  # static: every launch passes creationflags
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen")
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"
                        and (f.name, node.func.attr) not in ALLOWED):
                    kws = {k.arg for k in node.keywords}
                    self.assertTrue(kws & {"creationflags", None}, f"{f.name}:{node.lineno} starts a console program without creationflags")


if __name__ == "__main__":
    unittest.main()
