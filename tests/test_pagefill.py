"""AI: fill this page (pass 54): the page's fields are validated (secrets and the salary floor dropped, ids plain,
values capped), one fenced AI call, answers only for fields that were sent, a select only one of its own options,
unchanged values dropped, a revise sends the note for one field. Nothing is written server-side. No network."""
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

from lodestar import ai, pagefill, web  # noqa: E402

FIELDS = [{"id": "wKw", "label": "keywords", "value": "", "kind": "text"},
          {"id": "sLevel", "label": "Seniority", "value": "", "kind": "select", "options": ["", "junior", "senior"]},
          {"id": "keyVal", "label": "Anthropic API key", "value": "sk-secret", "kind": "text"},
          {"id": "pw1", "label": "Password", "value": "hunter2", "kind": "text"},
          {"id": "floorX", "label": "Salary floor", "value": "187000", "kind": "number"},
          {"id": "bad id!", "label": "x", "value": "", "kind": "text"}]


class PageFill(unittest.TestCase):
    def test_clean_drops_secrets_the_floor_and_bad_ids(self):
        self.assertEqual([f["id"] for f in pagefill.clean(FIELDS)], ["wKw", "sLevel"])
        self.assertEqual(pagefill.clean("nope"), [])
        self.assertEqual(len(pagefill.clean([{"id": f"f{i}", "label": "x"} for i in range(99)])), pagefill.MAX_FIELDS)

    def test_a_field_holding_the_profile_never_carries_the_floor(self):  # review: Profile tab's #pText leaked it
        md = "# Me\n\n## Preferences\n- Salary floor: 151234\n- Remote only\n\n## Experience\n- Built things\n"
        out = pagefill.clean([{"id": "pText", "label": "Master profile (markdown)", "value": md, "kind": "textarea"},
                              {"id": "note", "label": "Note", "value": "Salary floor: 151234", "kind": "text"}])
        # 2nd review: a redacted value offered for filling would overwrite the real text (Preferences lost on Save):
        # a field that names the floor or holds Preferences is not offered at all
        self.assertEqual(out, [])
        kept = pagefill.clean([{"id": "pSummary", "label": "Summary", "value": "Built things", "kind": "text"}])
        self.assertEqual(kept[0]["value"], "Built things")

    def test_one_fenced_call_answers_only_sent_fields_and_select_options(self):
        seen = []
        reply = {"fills": [{"id": "wKw", "value": "python, sql", "reason": "from your profile"},
                           {"id": "sLevel", "value": "principal"},  # not one of its options
                           {"id": "keyVal", "value": "leak"},  # never sent
                           {"id": "wKw", "value": "again"}]}  # one card per field
        with patched(ai, available=lambda: ["anthropic"], ask_json=lambda prompt, *a, **k: seen.append(prompt) or reply):
            out = web._do("page_fill", {"tab": "monitor", "fields": FIELDS})["fills"]
        self.assertEqual(out, [{"id": "wKw", "label": "keywords", "current": "", "proposed": "python, sql", "reason": "from your profile"}])
        for secret in ("sk-secret", "hunter2", "187000", "187,000"):
            self.assertNotIn(secret, seen[0])
        self.assertIn("<<<", seen[0])  # fenced

    def test_revise_one_field_with_a_note(self):
        seen = []
        with patched(ai, available=lambda: ["anthropic"],
                     ask_json=lambda prompt, *a, **k: seen.append(prompt) or {"fills": [{"id": "sLevel", "value": "senior"}]}):
            out = pagefill.propose("search", FIELDS, note="I have 9 years", only="sLevel")
        self.assertEqual(out[0]["proposed"], "senior")
        self.assertIn("I have 9 years", seen[0])
        self.assertIn("Revise field sLevel", seen[0])
        self.assertNotIn("field wKw", seen[0])

    def test_refusals(self):
        with self.assertRaisesRegex(SystemExit, "no fields"):
            pagefill.propose("x", [FIELDS[2]])
        with patched(ai, available=lambda: []):
            with self.assertRaisesRegex(SystemExit, "AI provider"):
                pagefill.propose("x", FIELDS)


if __name__ == "__main__":
    unittest.main()
