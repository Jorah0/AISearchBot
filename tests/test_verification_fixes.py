"""Fixes from the full live verification crawl (2026-11-13): a page action missing a field it needs answers with
the field's name in words, never a bare Python KeyError ("'instruction'"). No network."""
import os
import sys
import tempfile
import time
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import web  # noqa: E402


class Crawl(unittest.TestCase):
    def test_a_missing_field_is_named_in_words(self):
        real = web._act
        web._act = lambda action, params: params["instruction"]
        try:
            tid = web.start_task("adjust", {})
            for _ in range(100):
                if web.TASKS[tid]["status"] != "running":
                    break
                time.sleep(0.02)
        finally:
            web._act = real
        self.assertEqual(web.TASKS[tid]["error"], "this action needs 'instruction', which was not sent")


if __name__ == "__main__":
    unittest.main()
