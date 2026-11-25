"""Missing packages (deps.py): found with find_spec (nothing imported), installed only into a venv with exactly the specs
pyproject.toml declares, never by a standalone exe or Full AI. No real pip: updater._proc is faked; every patched
attribute is put back."""
import builtins
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import cli, config, deps, updater  # noqa: E402

FAKE = {"core": ["keyring>=24"], "desktop": ["lodestar-no-such-pkg>=5"], "apply": ["lodestar-no-such-pkg>=5", "keyring>=24"]}


class Deps(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.old = (deps.REQUIREMENTS, updater._proc, sys.prefix, sys.base_prefix, getattr(sys, "frozen", None))
        deps.REQUIREMENTS = FAKE
        updater._proc = lambda cmd, cwd, timeout, env=None: self.calls.append((cmd, timeout)) or (0, "ok", "")
        sys.prefix, sys.base_prefix = "C:/venv", "C:/Python"  # a venv

    def tearDown(self):
        deps.REQUIREMENTS, updater._proc, sys.prefix, sys.base_prefix, frozen = self.old
        if frozen is None and hasattr(sys, "frozen"):
            del sys.frozen
        elif frozen is not None:
            sys.frozen = frozen

    def test_check_lists_only_what_will_not_import(self):
        self.assertEqual(deps.missing(), [])
        self.assertEqual(deps.missing("apply"), ["lodestar-no-such-pkg>=5"])
        self.assertEqual((deps.module_of("pywebview>=5"), deps.module_of("python-docx>=1.1")), ("webview", "docx"))
        with self.assertRaises(SystemExit):
            deps.missing("evil; rm -rf")
        a = cli.build().parse_args(["deps", "check", "--extra", "desktop"])
        self.assertEqual((a.op, a.extra), ("check", "desktop"))

    def test_venv_installs_exactly_the_missing_specs_hidden_and_logged(self):
        r = deps.ensure("apply")
        cmd, timeout = self.calls[0]
        self.assertEqual(cmd, [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "lodestar-no-such-pkg>=5"])
        self.assertEqual(timeout, 900)
        self.assertFalse(r["frozen"])
        self.assertIn("failed", r["error"])  # the fake pip installed nothing: still missing, said so
        self.assertIn('"lodestar-no-such-pkg>=5" -> exit 0', Path(r["log"]).read_text(encoding="utf-8"))
        self.assertEqual(Path(r["log"]), config.HOME / "logs" / "deps.log")
        with patched(deps.importlib.util, find_spec=lambda name: object()):  # pip worked: importable now
            self.assertEqual(deps.ensure("apply")["missing"], [])
        self.assertEqual(deps.ensure("core"), {"installed": [], "missing": [], "frozen": False, "log": str(deps.LOG), "error": None})

    def test_system_python_is_refused_with_the_command_to_run(self):
        sys.prefix = sys.base_prefix = "C:/Python"
        r = deps.ensure("desktop")
        self.assertEqual(self.calls, [])
        self.assertIn("never the system Python", r["error"])
        self.assertIn('-m pip install --disable-pip-version-check "lodestar-no-such-pkg>=5"', r["error"])
        sys.prefix = "C:/venv"
        self.assertIn("run:", deps.ensure("desktop", auto=False)["error"])
        self.assertEqual(self.calls, [])

    def test_a_frozen_exe_never_installs(self):
        sys.frozen = True
        r = deps.ensure("desktop")
        self.assertEqual(self.calls, [])
        self.assertTrue(r["frozen"])
        self.assertEqual(r["missing"], ["lodestar-no-such-pkg>=5"])
        self.assertIn("rebuild it (scripts\\build_exe.ps1 -Force / install.ps1 -Exe)", r["error"])

    def test_full_ai_cannot_install(self):
        config.FULL_AI.on = True
        try:
            with self.assertRaises(SystemExit):
                deps.ensure("desktop")
        finally:
            config.FULL_AI.on = False
        self.assertEqual(self.calls, [])

    def test_specs_come_only_from_pyproject(self):
        deps.REQUIREMENTS = self.old[0]
        p = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(deps.REQUIREMENTS, {"core": p["dependencies"], **p["optional-dependencies"]})
        self.assertEqual(deps.REQUIREMENTS["desktop"], ["pywebview>=5"])
        with patched(deps.importlib.util, find_spec=lambda name: None):  # everything missing: still only declared specs
            deps.ensure("all")
        self.assertEqual(self.calls[0][0][5:], p["optional-dependencies"]["all"])

    def test_missing_never_imports_a_package(self):
        real = builtins.__import__

        def guard(name, *a, **kw):
            if name.split(".")[0] in ("webview", "playwright", "pypdf", "coverage", "docx", "keyring"):
                raise AssertionError(f"missing() imported {name}")
            return real(name, *a, **kw)

        deps.REQUIREMENTS = self.old[0]
        with patched(builtins, __import__=guard):
            for extra in deps.REQUIREMENTS:
                deps.missing(extra)


if __name__ == "__main__":
    unittest.main()
