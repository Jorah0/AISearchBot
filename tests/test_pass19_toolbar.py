"""Pass 19: the AI advisor toolbar in the UI (static/app.js, static/index.html). The browser tests are in
tests/e2e/e2e_advisor.py; these keep the page in step with advisor.SCOPES without a browser: the scopes that get no
Full AI or no Apply in the page are exactly the server's auto=False / advice-only ones, every scope has a toolbar, the
buttons keep their names (the import review's 'Apply selected' stays a different button), and Setup > Data lists the
AI change history."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""

from lodestar import advisor  # noqa: E402

STATIC = Path(advisor.__file__).parent / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def js_list(name: str) -> list[str]:
    m = re.search(rf"\b{name} = (\[[^\]]*\])", JS)
    assert m, f"{name} not found in app.js"
    return json.loads(m[1].replace("'", '"'))


class Toolbar(unittest.TestCase):
    def test_js_scope_lists_match_the_server(self):
        self.assertEqual(sorted(js_list("ADV_NOAUTO")), sorted(k for k, s in advisor.SCOPES.items() if not s.auto))
        self.assertEqual(sorted(js_list("ADV_ADVICE")), sorted(k for k, s in advisor.SCOPES.items() if s.write is None))
        names = re.findall(r"(\w+): '", JS.split("const ADV_NAME = {", 1)[1].split("};", 1)[0])
        self.assertEqual(sorted(names), sorted(advisor.SCOPES), "ADV_NAME names every scope")

    def test_every_scope_has_a_toolbar_with_its_buttons_and_setup_lists_the_history(self):
        slots = set(re.findall(r'data-adv-slot="(\w+)"', HTML))
        cards = set(re.findall(r"aiBar\('(\w+)'", JS))
        self.assertEqual(slots | cards, set(advisor.SCOPES), "a toolbar on a tab header or a card for every scope")
        self.assertEqual(cards, {"job", "docs", "contacts", "stories", "inbox"})  # the per-component cards
        for label in (">Recommend<", ">Apply suggestions<", ">Full AI<", ">Undo AI changes<"):
            self.assertIn(label, JS)
        self.assertNotIn("Apply selected", JS.split("/* ---- AI advisor toolbar", 1)[1])  # the import review keeps it
        self.assertIn('id="aiHist"', HTML)
        self.assertIn("loadAiHistory()", JS.split("function go(tab)", 1)[1].split("\n}", 1)[0])  # Setup refreshes it


if __name__ == "__main__":
    unittest.main()
