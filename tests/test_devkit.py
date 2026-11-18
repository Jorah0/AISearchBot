"""Developer kit (pass 46): `lodestar dev new` writes a failing test in the codebase's own patterns (never over a file)
and prints code that makes it pass: proven here by running the generated board test before and after adding the
generated board code to web_monitor (then taking it out again). `dev check` runs the fast guards. Writes only to a temp
folder; every patched attribute is put back."""
import ast
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402

from lodestar import devkit, web_monitor  # noqa: E402


class Kit(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "tests").mkdir()

    def run_test(self, rel):
        spec = importlib.util.spec_from_file_location(Path(rel).stem, self.root / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        res = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromModule(mod))
        return res.wasSuccessful()

    def test_every_kind_writes_valid_code_and_never_overwrites(self):
        for kind in devkit.KINDS:
            r = devkit.new(kind, f"demo_{kind}", self.root)
            ast.parse((self.root / r["test"]).read_text(encoding="utf-8"))
            ast.parse("x = {\n" + r["snippet"] + "\n}" if kind == "helper" else r["snippet"])
            self.assertTrue(r["checklist"] and r["where"])
            with self.assertRaisesRegex(SystemExit, "already exists"):
                devkit.new(kind, f"demo_{kind}", self.root)
        for bad in ("Demo", "1x", "x", "a-b", "../x"):
            with self.assertRaises(SystemExit):
                devkit.new("board", bad, self.root)
        with self.assertRaisesRegex(SystemExit, "kind is one of"):
            devkit.new("plugin", "demo", self.root)

    def test_the_board_test_fails_first_and_the_board_code_makes_it_pass(self):
        r = devkit.new("board", "kitboard", self.root)
        self.assertFalse(self.run_test(r["test"]))  # test first: red
        code = r["snippet"].replace('fetch_json("https://<the board\'s API>")', 'fetch_json("https://kit.example/api")')
        ns = vars(web_monitor)
        exec(compile(code, "kitboard", "exec"), ns)  # the generated function, defined in web_monitor's namespace
        try:
            with patched(web_monitor, SOURCES=web_monitor.SOURCES | {"kitboard": ns["_kitboard"]},
                         EVERY=web_monitor.EVERY | {"kitboard": 3600},
                         ATTRIBUTION=web_monitor.ATTRIBUTION | {"kitboard": ("Kitboard", "https://kit.example/")},
                         CAPABILITIES=web_monitor.CAPABILITIES | {"kitboard": web_monitor._CAP}):
                self.assertTrue(self.run_test(r["test"]))  # green
        finally:
            ns.pop("_kitboard", None)

    def test_check_runs_the_fast_guards(self):
        seen = []

        class Done:
            returncode = 0
        with patched(devkit.subprocess, run=lambda args, **kw: seen.append(args) or Done()):
            self.assertEqual(devkit.check(), 0)
        self.assertEqual(seen[0][-len(devkit.GUARDS):], devkit.GUARDS)


if __name__ == "__main__":
    unittest.main()
