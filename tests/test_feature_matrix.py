"""Guard for docs/TESTS.md, the feature matrix: one row per feature with its unit/integration tests and its browser (E2E)
tests by exact name (module.Class.test_name). Fails when a row lists no test, names a test that does not exist, puts a
test in the wrong column or repeats an ID; when a test is named nowhere or a row (or a Planned ID) disappears; and when
CLAUDE.md's unit-test count drifts from the suite. Test names come from parsing the test files (ast), never importing
them, so this runs without Playwright."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "TESTS.md"
HEADER = ["ID", "Feature", "Unit / integration", "E2E"]
NAME = re.compile(r"`([A-Za-z_]\w*\.\w+\.\w+)`")
UNMAPPED: set[str] = set()  # tests deliberately named in no row (none today)
# Every row ID, pinned: deleting a row fails. Numbered areas run 1..N with no gap; a Planned feature that gets built
# moves from PLANNED into a row (raise N or add the name here).
NUMBERED = {"tracker-sourcing": 35, "profile-resume-ai": 40, "mail-people-interviews": 44, "connections": 18, "ui-sweep": 66,
            "pipeline": 16}
NAMED = set("""outcomes-platform-insights-analytics outcomes-platform-insights-ui outcomes-platform-weekly-goals
outcomes-platform-offers-record outcomes-platform-comp-total outcomes-platform-offers-compare outcomes-platform-market-rates
outcomes-platform-counter-offer outcomes-platform-offer-evaluation outcomes-platform-activity-log outcomes-platform-digest-text
outcomes-platform-digest-email outcomes-platform-notify-email outcomes-platform-desktop-notifications
outcomes-platform-monitor-loop outcomes-platform-loop-status outcomes-platform-today-agenda outcomes-platform-followup-cadence
outcomes-platform-tool-switches outcomes-platform-prefs-validation outcomes-platform-tools-ui outcomes-platform-vault
outcomes-platform-doctor outcomes-platform-doctor-ui outcomes-platform-backup outcomes-platform-export
outcomes-platform-schedule outcomes-platform-installer-ps1 outcomes-platform-pyinstaller outcomes-platform-installer-sh
outcomes-platform-uninstaller outcomes-platform-start-scripts outcomes-platform-package-data outcomes-platform-desktop-launch
outcomes-platform-ci outcomes-platform-api-token outcomes-platform-usage-alerts-init outcomes-platform-docs-test-count
outcomes-platform-docs-inventory outcomes-platform-docs-claims platform-fetch platform-db platform-cli
platform-test-matrix outcomes-platform-update-check outcomes-platform-update-apply
outcomes-platform-update-loop outcomes-platform-update-exe outcomes-platform-update-cli
outcomes-platform-update-ui outcomes-platform-update-restart outcomes-platform-update-safety
ui-sweep-69""".split())  # built out of order (pass 17); 67 and 68 are still planned
PLANNED = set("""tracker-sourcing-36 tracker-sourcing-37 tracker-sourcing-38 tracker-sourcing-39
profile-resume-ai-41 profile-resume-ai-42 mail-people-interviews-45
mail-people-interviews-46 mail-people-interviews-47 ui-sweep-67 ui-sweep-68 ui-sweep-70 ui-sweep-71 ui-sweep-72
outcomes-platform-planned-pipeline outcomes-platform-planned-ai-history outcomes-platform-restore
outcomes-platform-planned-paydata outcomes-platform-planned-e2e""".split())
PLANNED_ID = re.compile(r"\b(?:(?:tracker-sourcing|profile-resume-ai|mail-people-interviews|connections|ui-sweep|pipeline)-\d+"
                        r"|outcomes-platform-[a-z0-9-]*[a-z0-9])\b")


def _literals(tree) -> dict:
    """Module-level NAME = ("a", "b", ...) assignments."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                v = ast.literal_eval(n.value)
            except ValueError:
                continue
            if isinstance(v, (tuple, list)) and all(isinstance(x, str) for x in v):
                out[n.targets[0].id] = v
    return out


def test_names(files, shared: dict | None = None) -> set[str]:
    """module.Class.test_* for every test method (inherited from a class in the same file included), plus the ones a
    module-level `for x in NAME: setattr(Cls, f"test_...{x}", ...)` adds (NAME a literal here or in `shared`)."""
    names = set()
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        lits = {**(shared or {}), **_literals(tree)}
        classes = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}

        def methods(c):
            own = {m.name for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and m.name.startswith("test")}
            for b in c.bases:
                if isinstance(b, ast.Name) and b.id in classes and b.id != c.name:
                    own |= methods(classes[b.id])
            return own
        for c in classes.values():
            names |= {f"{f.stem}.{c.name}.{m}" for m in methods(c)}
        for loop in (n for n in tree.body if isinstance(n, ast.For)):
            if not (isinstance(loop.iter, ast.Name) and isinstance(loop.target, ast.Name) and loop.iter.id in lits):
                continue
            for call in ast.walk(loop):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "setattr"
                        and isinstance(call.args[0], ast.Name) and isinstance(call.args[1], ast.JoinedStr)):
                    for v in lits[loop.iter.id]:
                        parts = [p.value if isinstance(p, ast.Constant) else v if isinstance(p.value, ast.Name)
                                 and p.value.id == loop.target.id else None for p in call.args[1].values]
                        if None not in parts:
                            names.add(f"{f.stem}.{call.args[0].id}.{''.join(parts)}")
    return names


def unit_names() -> set[str]:
    return test_names(sorted((ROOT / "tests").glob("test_*.py")))


def e2e_names() -> set[str]:
    e2e = ROOT / "tests" / "e2e"
    shared = _literals(ast.parse((e2e / "harness.py").read_text(encoding="utf-8")))  # e.g. TABS for the smoke tests
    return test_names(sorted(e2e.glob("e2e_*.py")), shared)


def rows(text: str) -> list[tuple]:
    """(line, id, feature, unit names, e2e names, cell count) for every row of a table headed HEADER."""
    out, inside = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            inside = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells == HEADER:
            inside = True
        elif inside and not set(line) <= set("|-: "):
            pad = cells + [""] * 4
            out.append((n, pad[0], pad[1], NAME.findall(pad[2]), NAME.findall(pad[3]), len(cells)))
    return out


def problems(text: str, unit: set[str], e2e: set[str]) -> list[str]:
    bad, ids = [], set()
    for n, rid, feature, u, e, ncells in rows(text):
        where = f"TESTS.md:{n} {rid or '(no id)'}"
        if ncells != 4:
            bad.append(f"{where}: {ncells} cells, the matrix has 4 (a '|' in the feature text?)")
        if not rid or not feature:
            bad.append(f"{where}: needs an ID and a feature")
        if rid in ids:
            bad.append(f"{where}: ID used twice")
        ids.add(rid)
        if not u and not e:
            bad.append(f"{where}: lists no test")
        bad += [f"{where}: no such unit/integration test {t}" for t in u if t not in unit]
        bad += [f"{where}: {t} is a browser test: it goes in the E2E column" for t in u if t in e2e]
        bad += [f"{where}: no such E2E test {t}" for t in e if t not in e2e]
    return bad


def unmapped(text: str, unit: set[str], e2e: set[str]) -> set[str]:
    """Tests that no row names (beyond the UNMAPPED allowlist)."""
    named = {t for r in rows(text) for t in r[3] + r[4]}
    return (unit | e2e) - named - UNMAPPED


def id_problems(text: str) -> list[str]:
    """Rows and Planned IDs against the pinned lists: a deleted row, a gap, an unexpected ID or a lost Planned entry."""
    want = NAMED | {f"{a}-{n:02d}" for a, top in NUMBERED.items() for n in range(1, top + 1)}
    have = {r[1] for r in rows(text)}
    planned = set(PLANNED_ID.findall(text.split("## Planned", 1)[1].split("\n## ", 1)[0])) if "## Planned" in text else set()
    return ([f"row missing: {i}" for i in sorted(want - have)] + [f"row not in the pinned list: {i}" for i in sorted(have - want)]
            + [f"Planned ID missing: {i}" for i in sorted(PLANNED - planned)]
            + [f"Planned ID not pinned: {i}" for i in sorted(planned - PLANNED)])


class Matrix(unittest.TestCase):
    def test_every_row_lists_tests_that_exist_in_the_right_column(self):
        text = MATRIX.read_text(encoding="utf-8")
        self.assertGreater(len(rows(text)), 200, "the matrix tables were not found (header changed?)")
        self.assertEqual(problems(text, unit_names(), e2e_names()), [])

    def test_the_guard_catches_an_empty_row_an_unknown_name_a_wrong_column_and_a_repeated_id(self):
        doc = "\n".join(["| ID | Feature | Unit / integration | E2E |", "|---|---|---|---|",
                         "| a-1 | ok | `test_x.A.test_one` | `e2e_y.B.test_two` |",
                         "| a-2 | nothing listed | | |",
                         "| a-3 | unknown | `test_x.A.test_gone` | |",
                         "| a-3 | browser test in the unit column | `e2e_y.B.test_two` | |",
                         "", "| Module | Stmts |", "|---|---|", "| lodestar/x.py | 1 |"])  # other tables are ignored
        bad = problems(doc, {"test_x.A.test_one"}, {"e2e_y.B.test_two"})
        self.assertEqual(len(bad), 5, bad)
        self.assertTrue(any("a-2: lists no test" in b for b in bad))
        self.assertTrue(any("no such unit/integration test test_x.A.test_gone" in b for b in bad))
        self.assertTrue(any("goes in the E2E column" in b for b in bad))
        self.assertTrue(any("ID used twice" in b for b in bad))

    def test_every_test_is_named_and_no_row_or_planned_id_is_dropped(self):
        text = MATRIX.read_text(encoding="utf-8")
        self.assertEqual(sorted(unmapped(text, unit_names(), e2e_names())), [], "add these tests to a TESTS.md row")
        self.assertEqual(id_problems(text), [])
        # and both checks bite: one row and one test mention gone, one Planned entry gone
        first = next(r for r in rows(text) if r[1] == "connections-08")
        lines = text.splitlines()
        cut = "\n".join(ln for n, ln in enumerate(lines, 1) if n != first[0]).replace("`e2e_smoke.Smoke.test_tab_coach`", "")
        cut = cut.replace("- ui-sweep-72:", "- (gone):")
        self.assertIn("e2e_smoke.Smoke.test_tab_coach", unmapped(cut, unit_names(), e2e_names()))
        self.assertEqual(id_problems(cut), ["row missing: connections-08", "Planned ID missing: ui-sweep-72"])

    def test_generated_smoke_tests_are_found_without_playwright(self):
        names = e2e_names()
        self.assertIn("e2e_smoke.Smoke.test_tab_board", names)  # setattr over harness.TABS
        self.assertIn("e2e_smoke.Smoke.test_tab_setup", names)

    def test_claude_md_states_the_unit_test_count(self):
        m = re.search(r'"test_\*\.py"` \((\d+) tests\)', (ROOT / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertIsNotNone(m, "CLAUDE.md no longer states the unit-test count")
        self.assertEqual(int(m[1]), len(unit_names()), "update the test count in CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
