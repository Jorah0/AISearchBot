"""Pass 30: the industry-agnostic audit (blueprint 2.2 'Industry agnostic', 20.2: no software-specific assumption to
start a search). Static checks over the page and the prompt builders, and a blank profile never defaults to a software
search. No network."""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import Base  # noqa: E402

from lodestar import web_monitor  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

PKG = Path(__file__).resolve().parents[1] / "lodestar"
SOFTWARE = re.compile(r"(?i)data engineer|analytics engineer|software engineer|kafka|engineering culture|tech stack|leetcode")


class Agnostic(Base):
    def test_page_examples_are_not_software_only(self):
        for name in ("index.html", "app.js"):
            text = (PKG / "static" / name).read_text(encoding="utf-8")
            bad = [m[0] for m in re.finditer(r"placeholder=[\"'][^\"']*[\"']", text) if SOFTWARE.search(m[0])]
            self.assertEqual(bad, [], f"{name}: placeholders should show examples from more than one industry")

    def test_software_wording_reaches_prompts_only_for_software_jobs(self):
        hits = []
        for p in PKG.glob("*.py"):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"(?i)engineering culture|tech stack|coding interview|leetcode", line) and not line.lstrip().startswith("#"):
                    hits.append((p.name, line.strip()))
        allowed = [h for h in hits if h[0] == "careers.py" or (h[0] == "extras.py" and '"engineering" in focus' in h[1])
                   or (h[0] == "db.py" and "hybrid" in h[1])]
        self.assertEqual(hits, allowed)

    def test_a_blank_profile_starts_no_software_search(self):
        PROFILE.write_text("# Your Name\n", encoding="utf-8")
        d = web_monitor.defaults()
        self.assertFalse(SOFTWARE.search(str(d.get("query") or "")), d)


if __name__ == "__main__":
    unittest.main()
