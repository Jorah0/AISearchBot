"""Pass 32 UI: static checks on the page's visual system (blueprint 18.5): every colour token defined for both the dark
and the light theme, a visible focus ring wherever the default outline is removed, and the theme switch wired."""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "lodestar" / "static"


def tokens(block: str) -> set[str]:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))


class VisualSystem(unittest.TestCase):
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    def test_light_theme_defines_every_token(self):
        root = tokens(self.css.split(":root {", 1)[1].split("}", 1)[0])
        light = self.css.split(':root[data-theme="light"] {', 1)[1].split("}", 1)[0]
        auto = self.css.split("@media (prefers-color-scheme: light)", 1)[1].split("}\n}", 1)[0]
        colours = {t for t in root if t not in ("--r", "--shadow")}
        self.assertTrue(colours <= tokens(light), colours - tokens(light))
        self.assertTrue(colours <= tokens(auto), colours - tokens(auto))
        self.assertIn(':root:not([data-theme="dark"])', auto)

    def test_drawer_index_is_a_row_and_pills_follow_the_theme(self):  # review fixes
        rule = self.css.split("#drawer .jIndex {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-direction: row", rule)
        self.assertNotRegex(self.css, r"#1f4d33|#4d3b1f")

    def test_focus_is_always_visible(self):
        self.assertRegex(self.css, r":focus-visible\s*\{[^}]*outline:\s*2px solid")
        for m in re.finditer(r"([^{}]+)\{[^}]*outline:\s*none", self.css):
            self.assertIn("focus-visible", self.css, m[1])

    def test_theme_switch_is_wired_and_survives_without_storage(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="themeBtn"', html)
        fn = js.split("function toggleTheme()", 1)[1].split("\n}", 1)[0]
        self.assertIn("dataset.theme", fn)
        self.assertIn("try", fn)  # a private window without storage still switches


class DeferredMinors(unittest.TestCase):  # the pass 32 review's deferred minors, closed in pass 35
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_the_saved_theme_applies_before_the_stylesheet_paints(self):
        head = self.html.split("</head>", 1)[0]
        self.assertIn("ls_theme", head)
        self.assertLess(head.index("ls_theme"), head.index("app.css"))  # no flash of the other theme

    def test_a_click_outside_closes_the_shortcut_sheet(self):
        self.assertRegex(self.js, r"addEventListener\('click', e => \{[^}]*keysHelp")

    def test_the_apply_group_says_when_the_agent_cannot_run(self):
        fn = self.js.split("function applyGroup(j)", 1)[1].split("\n}", 1)[0]
        self.assertIn("S.apply", fn)
        self.assertIn("disabled", fn)


if __name__ == "__main__":
    unittest.main()
