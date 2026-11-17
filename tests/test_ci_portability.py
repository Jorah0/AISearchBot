"""CI portability (pass 39; GitHub CI on Linux, Python 3.11-3.14): two backups in the same second both stay (the
second used to replace the first), and forgetting the agent's sign-ins works on Python 3.11 (shutil.rmtree has
onerror there; onexc arrived in 3.12). No network; every patched attribute is put back."""
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

from lodestar import apply_agent, extras  # noqa: E402


class Portability(unittest.TestCase):
    def test_two_backups_in_the_same_second_both_stay(self):
        out = Path(tempfile.mkdtemp())

        class Frozen:  # the clock does not move between the two backups
            @staticmethod
            def now():
                from datetime import datetime

                return datetime(2026, 11, 17, 12, 0, 0)
        with patched(extras, datetime=Frozen):
            a = extras.backup(out, keep=5, prefix="t")
            b = extras.backup(out, keep=5, prefix="t")
        self.assertNotEqual(a, b)
        self.assertEqual(sorted(p.name for p in out.glob("*.zip")), ["t-20261117-120000-2.zip", "t-20261117-120000.zip"])

    def test_forget_logins_uses_onerror_on_python_311(self):
        got = {}

        def rmtree_311(path, onerror=None, **kw):  # 3.11's signature: an onexc keyword is a TypeError
            if kw:
                raise TypeError(f"rmtree() got an unexpected keyword argument {next(iter(kw))!r}")
            got["onerror"] = onerror
        prof = Path(tempfile.mkdtemp())
        with patched(apply_agent, PROFILE_DIR=prof), patched(apply_agent.sys, version_info=(3, 11, 9)), \
                patched(apply_agent.shutil, rmtree=rmtree_311), patched(apply_agent, _LOGIN=None):
            import lodestar.accounts as accounts

            with patched(accounts, session_live=lambda: False):
                out = apply_agent.forget_logins()
        self.assertTrue(callable(got["onerror"]))
        self.assertIn("removed", out)


if __name__ == "__main__":
    unittest.main()
