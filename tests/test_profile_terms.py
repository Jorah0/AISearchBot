"""Profile skills hold key terms only: a PDF whose text layer comes out one word per line is read in layout mode (so a
summary sentence never turns into one skill per word), and a skill name is never a stopword, lone punctuation, a
section heading or a sentence; trailing periods and commas are dropped. No network; patched modules are put back."""
import os
import sys
import tempfile
import types
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ingest, profile  # noqa: E402

PLAIN = "\n \n".join("SUMMARY Proven ability to deliver features. TECHNICAL SKILLS Tools: Git, GitHub, AWS".split())
LAYOUT = "SUMMARY\nProven ability to deliver features.\nTECHNICAL SKILLS\nTools: Git, GitHub, AWS\n"


class FakePage:
    def __init__(self, plain, layout):
        self.plain, self.layout = plain, layout

    def extract_text(self, extraction_mode="plain"):
        return self.layout if extraction_mode == "layout" else self.plain


def fake_pypdf(plain, layout):
    return types.SimpleNamespace(PdfReader=lambda f: types.SimpleNamespace(pages=[FakePage(plain, layout)]))


class Terms(unittest.TestCase):
    def pdf(self, plain, layout):
        old = sys.modules.get("pypdf")
        sys.modules["pypdf"] = fake_pypdf(plain, layout)
        try:
            return ingest.pdf_text(b"%PDF")
        finally:
            if old is None:
                sys.modules.pop("pypdf", None)
            else:
                sys.modules["pypdf"] = old

    def test_a_word_per_line_pdf_is_read_in_layout_mode(self):
        text = self.pdf(PLAIN, LAYOUT)
        self.assertIn("Tools: Git, GitHub, AWS", text)
        skills = [(s["name"], s["category"]) for s in profile.extract_heuristic(text)["skills"]]
        self.assertEqual(skills, [("Git", "Tools"), ("GitHub", "Tools"), ("AWS", "Tools")])
        lone = profile.extract_heuristic("SKILLS\nTools & DevOps:\nGit, AWS\nLinux")["skills"]
        self.assertEqual([(s["name"], s["category"]) for s in lone], [("Git", "Tools & DevOps"), ("AWS", "Tools & DevOps"), ("Linux", "")])
        normal = "SUMMARY\nA sentence that reads fine on one line.\nSKILLS\nPython, SQL"
        self.assertEqual(self.pdf(normal, "garbled"), normal)  # a normal text layer is kept as is

    def test_skill_names_are_key_terms_only(self):
        clean = lambda n: (profile._clean_item("skills", {"name": n}) or {}).get("name")  # noqa: E731
        for junk in ("to", "and", "&", "in", "TECHNICAL", "Skills", "-", ".", "etc.",
                     "Proven ability to deliver production-ready features"):
            self.assertIsNone(clean(junk), junk)
        for name, want in (("teams.", "teams"), ("Git,", "Git"), ("C++", "C++"), ("C", "C"), (".NET", ".NET"),
                           ("Node.js", "Node.js"), ("Machine Learning", "Machine Learning"), ("R", "R")):
            self.assertEqual(clean(name), want, name)

    def test_junk_already_in_the_bank_is_dropped_on_load(self):
        bank = profile.load()
        bank["skills"] = [{"name": n, "category": ""} for n in ("Proven", "to", "&", "Git", "teams.")]
        old = profile.load
        profile.save(bank)
        try:
            self.assertEqual([s["name"] for s in profile.load()["skills"]], ["Git", "teams"])
        finally:
            profile.load = old
            b = profile.load()
            b["skills"] = []
            profile.save(b)


if __name__ == "__main__":
    unittest.main()
