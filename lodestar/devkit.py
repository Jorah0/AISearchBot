"""Developer kit (pass 46): `lodestar dev new board|stage|helper NAME` starts a feature the way this codebase builds
one, test first: it writes a failing test (tests/test_<kind>_<name>.py, never over an existing file) and prints the
code to add, where it goes, and the checklist of rules that kind must keep (from CLAUDE.md). `lodestar dev check` runs
the fast guards (feature matrix, lint, isolation, hidden console) before the full suites. docs/DEVELOPING.md is the
guide. Nothing here edits lodestar/ itself: the code lands where the checklist says, by you or an agent."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME_RX = re.compile(r"[a-z][a-z0-9_]{1,30}")

HEAD = '''"""{doc} (`lodestar dev new {kind} {name}`). Make it pass, then add its docs/TESTS.md row and update the test count in
CLAUDE.md (tests/test_feature_matrix.py checks both). No network; every patched attribute is put back."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # never the real keyring (test_pass17_isolation guards it)
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import patched  # noqa: E402
'''

KINDS = {
    "board": {
        "doc": "A job board",
        "test": HEAD + '''
from lodestar import web_monitor  # noqa: E402

FEED = {{"jobs": [{{"title": "Data Engineer", "company": "Acme", "url": "https://jobs.example.com/acme/1",
                    "location": "Remote", "description": "Python and SQL pipelines."}}]}}


class Board(unittest.TestCase):
    def test_{name}_is_registered_everywhere_a_board_must_be(self):
        for table in ("SOURCES", "EVERY", "ATTRIBUTION", "CAPABILITIES"):
            self.assertIn("{name}", getattr(web_monitor, table), table)

    def test_{name}_parses_listings_and_filters_by_the_query(self):
        with patched(web_monitor, fetch_json=lambda url, **k: FEED):
            got = web_monitor.SOURCES["{name}"]("data engineer")
            none = web_monitor.SOURCES["{name}"]("nurse")
        self.assertEqual([(j["title"], j["company"], j["source"]) for j in got], [("Data Engineer", "Acme", "{name}")])
        self.assertEqual(none, [])


if __name__ == "__main__":
    unittest.main()
''',
        "where": "lodestar/web_monitor.py: the function beside the other boards (_jobicy, _himalayas), the four table "
                 "entries in SOURCES, EVERY, ATTRIBUTION and CAPABILITIES",
        "snippet": '''def _{name}(q):
    """{title} (keyless): <what it lists, its published rate limit>."""
    words = _words_in(q)
    d = fetch_json("https://<the board's API>")  # GLOBAL board (one unfiltered fetch per window)? use _cached("{name}", url)
    out = []
    for j in d.get("jobs", []):
        if _has_all(words, f"{{j.get('title', '')}} {{j.get('description', '')}}"):
            out.append(_listing(j.get("title"), j.get("company"), j.get("url"), j.get("location"), j.get("salary", ""),
                                j.get("date", ""), j.get("description"), "{name}"))
    return out

# SOURCES["{name}"] = _{name}
# EVERY["{name}"] = 3600                     # its published limit, in seconds
# ATTRIBUTION["{name}"] = ("{title}", "https://<its site>/")
# CAPABILITIES["{name}"] = _CAP | {{"regions": "<where it lists jobs>"}}''',
        "checklist": [
            "A keyed board also goes in KEYED and the connections REGISTRY (kind 'jobs'), and runs only when sources_ready().",
            "Per-user limits go in GLOBAL: one unfiltered _cached fetch per window, filtered here.",
            "Error text passes _redact; never print or log a key.",
            "Never a board or ATS host in util.NEVER_FETCH or apply_agent.forbidden (LinkedIn, Indeed, Glassdoor, "
            "ZipRecruiter, SimplyHired).",
            "A board that searches near a place goes in LOCAL and reads _RUN.where / _RUN.radius.",
            "Listings reach All jobs through annotate -> listings.store by themselves; store nothing yourself.",
        ],
    },
    "stage": {
        "doc": "A pipeline stage",
        "test": HEAD + '''
from lodestar import pipeline, settings  # noqa: E402


class Stage(unittest.TestCase):
    def test_{name}_is_a_registered_stage_under_its_tool(self):
        s = pipeline.REGISTRY["{name}"]
        self.assertEqual(s.tool, "{name}")
        self.assertIn("{name}", settings.TOOLS)
        self.assertTrue(s.run)


if __name__ == "__main__":
    unittest.main()
''',
        "where": "lodestar/pipeline.py: the run function beside _research / _letter, the Stage in the REGISTRY list "
                 "in order; lodestar/settings.py: its TOOLS entry",
        "snippet": '''def _{name}(job, ctx):
    """{title}: <what it produces>. Reads earlier outputs through ctx.out / ctx.file, asks through ctx.ask."""
    ...  # one AI call at most: ctx.spent += 1
    return {{"file": "{name}.md"}}

# in the REGISTRY list, in pipeline order:
# Stage("{name}", "{title}", ("saved",), needs=("score",), tool="{name}", ai=1, run=_{name},
#       observe=_doc("{name}.md"), blocked=_need_ai),
# settings.TOOLS["{name}"] = ("<what the tool does, for Tools>", True, False)   # enabled, not auto''',
        "checklist": [
            "Read earlier outputs through ctx.out / ctx.file; ask through ctx.ask (never guess).",
            "Never send, submit or change a job's status: approvals.propose does, with review.",
            "Pipeline bookkeeping never goes to events (the follow-up clock).",
            "Eligibility / EEO labels are never AI-drafted (pipeline.never_ai).",
            "Root fingerprints hash content, never row ids or read times; a stage that moves a root it reads records it "
            "in ctx.read_now.",
            "Employer-facing text: candidate_text(private=False) and drafts.screen (the salary floor never leaves).",
        ],
    },
    "helper": {
        "doc": "An AI help menu entry",
        "test": HEAD + '''
from lodestar import advisor  # noqa: E402


class Helper(unittest.TestCase):
    def test_{name}_is_an_ai_help_entry_with_fenced_context(self):
        h = advisor.HELPERS["{name}"]
        self.assertTrue(h.label and h.ask)
        self.assertIn(h.where, ("board", "job", "contacts", "contact", "stories", "insights", "search", "monitor", "setup"))


if __name__ == "__main__":
    unittest.main()
''',
        "where": "lodestar/advisor.py: a HELPERS entry (its menu needs a data-ai-menu slot or an aiMenu( call and an "
                 "AIM_NAME entry in app.js when the 'where' is new)",
        "snippet": '''    "{name}": Helper("{title}", "job", "<what the AI is asked: one clear task, the output shape>", _h_job, "job"),''',
        "checklist": [
            "context() returns [(block id, label, text)]: every block is fenced as data; never text from the browser.",
            "Text a user may send to an employer: employer=True (the salary-floor guard).",
            "Never gather what a model may not see: eligibility / EEO / private answers, Preferences, readiness.",
            "scope= makes it appliable: a Recommend with ask as its focus; only Apply suggestions writes.",
        ],
    },
}


def new(kind: str, name: str, root: Path = ROOT) -> dict:
    """Write the failing test for a new board / stage / helper and return {test, where, snippet, checklist}."""
    if kind not in KINDS:
        raise SystemExit(f"kind is one of: {', '.join(KINDS)}")
    if not NAME_RX.fullmatch(name or ""):
        raise SystemExit("name: lowercase letters, digits and _ (2-31 characters), starting with a letter")
    k = KINDS[kind]
    path = root / "tests" / f"test_{kind}_{name}.py"
    if path.exists():
        raise SystemExit(f"{path.relative_to(root)} already exists: pick another name or edit that file")
    title = name.replace("_", " ").title()
    path.write_text(k["test"].format(doc=k["doc"], kind=kind, name=name), encoding="utf-8")
    return {"test": str(path.relative_to(root)), "where": k["where"],
            "snippet": k["snippet"].format(name=name, title=title), "checklist": k["checklist"]}


GUARDS = ["tests.test_feature_matrix", "tests.test_pass16_audit_b", "tests.test_pass17_isolation",
          "tests.test_hidden_console"]


def check(root: Path = ROOT) -> int:
    """The fast guards before the full suites: the feature matrix, lint, keyring isolation, no console windows."""
    from .util import NO_WINDOW

    return subprocess.run([sys.executable, "-m", "unittest", *GUARDS], cwd=root, creationflags=NO_WINDOW).returncode
