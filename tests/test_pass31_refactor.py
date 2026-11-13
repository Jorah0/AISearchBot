"""Pass 31: what still contradicted the blueprint after pass 30, and the refactor's one-home helpers. Board keyword
filters match whole words; The Muse is never narrowed to software / IT by an ambiguous word; research text marked
(unverified) never reaches an employer-facing prompt; sponsorship signals no longer move the fit score. No network;
every patched attribute is put back."""
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
from test_pass21_fit import JD, Base, L, patched  # noqa: E402

from lodestar import db, extras, fit, resume, settings  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class Contradictions(Base):
    def test_board_keyword_filters_match_whole_words(self):
        self.assertFalse(wm._has_all(["intern"], "Internal Auditor"))
        self.assertTrue(wm._has_all(["intern"], "Marketing Intern, summer"))
        self.assertFalse(wm._has_all(["nurse"], "Nursery teacher"))
        self.assertTrue(wm._has_all(["engineer"], "Civil Engineers wanted"))  # a plural still counts
        self.assertTrue(wm._has_all(["c++", "developer"], "Senior C++ Developer"))
        self.assertTrue(wm._has_all([], "anything"))

    def test_the_muse_is_never_narrowed_by_an_ambiguous_word(self):
        asked = []
        with patched(wm, fetch_json=lambda url, **k: asked.append(url) or {"results": []}):
            for q in ("civil engineer", "security officer", "data entry clerk", "interior designer", "it support"):
                wm._muse(q)
            self.assertFalse([u for u in asked if "category=" in u], asked)
            asked.clear()
            wm._muse("software engineer")
            self.assertTrue(all("category=Software" in u for u in asked), asked)

    def test_unverified_research_never_reaches_employer_prompts(self):
        jid = db.add_job("Acme", "Data Engineer", None, JD, "via test")
        d = resume.app_dir(db.get_job(jid))
        (d / "research.md").write_text("Acme makes freight software [S1].\nThey plan to IPO in 2027 (unverified).\n",
                                       encoding="utf-8")
        text = extras.research_for_prompts(db.get_job(jid))
        self.assertIn("freight software", text)
        self.assertNotIn("IPO", text)
        for path in ("lodestar/apply.py", "lodestar/resume.py"):
            src = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
            self.assertNotIn('"research.md").read_text', src.replace("'", '"'), path)  # both read research_for_prompts

    def test_sponsorship_signals_no_longer_move_the_score(self):
        settings.set_pref("work_authorization", "needs_sponsorship")
        plain = fit.score(L(desc=JD + " Some text."))
        yes = fit.score(L(desc=JD + " Visa sponsorship is available."))
        self.assertEqual(plain["score"], yes["score"])
        self.assertIn("offers sponsorship", [c["text"] for c in yes["chips"]] + [g["evidence"] for g in yes["gates"]])
        self.assertEqual(fit.config()["version"], 3)
        self.assertFalse({"sponsor_yes", "sponsor_hint"} & set(fit.config()["modifiers"]))


if __name__ == "__main__":
    unittest.main()
