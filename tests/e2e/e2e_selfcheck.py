"""lodestar selfcheck's page part (pass 55), run for real: every tab of a throwaway copy of the app, plus the job
drawer, the email view and the AI switcher, opens with no script error, no sideways scroll and every control named.
This keeps the whole page clean: a new unnamed field or a layout that overflows fails here."""
import tempfile
import unittest
from pathlib import Path

from harness import NO_PLAYWRIGHT

from lodestar import selfcheck  # noqa: E402  (after harness: it sets the temp home first)


class SelfCheckPage(unittest.TestCase):
    def test_every_tab_and_part_is_clean(self):
        if NO_PLAYWRIGHT:
            raise unittest.SkipTest(NO_PLAYWRIGHT)
        rep = selfcheck.page(Path(tempfile.mkdtemp()) / "page.json")
        parts = rep["tabs"] + [{"tab": x["part"], "problems": x["problems"]} for x in rep["extra"]]
        self.assertEqual(len(rep["tabs"]), 17)
        self.assertEqual({p["tab"]: p["problems"] for p in parts if p["problems"]}, {})
        self.assertTrue(all(rep["outline"].get(t) for t in ("home", "board", "inbox", "setup")))


if __name__ == "__main__":
    unittest.main()
