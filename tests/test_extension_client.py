"""The browser extension's own files (extension/): static guards that keep its invariants true without a browser, and
the node matcher suite. The extension never clicks, submits, navigates or ticks anything; its page-side scripts never
reach the network or extension storage; the popup only ever calls /api/ext/*; the manifest asks for the minimum; the
committed fixtures are small, scriptless and fictional. The browser run is tests/e2e/e2e_extension.py."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FIX = EXT / "test" / "fixtures"


def code(name: str) -> str:
    """The file without its comments (a comment naming a banned call is not a call)."""
    text = (EXT / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\])//.*$", r"\1", text)


class Static(unittest.TestCase):
    def test_page_scripts_never_click_submit_or_reach_storage_or_network(self):
        banned = [r"\.click\(", r"\.submit\(", r"requestSubmit", r"new\s+(Mouse|Pointer|Keyboard|Submit)Event",
                  r"innerHTML", r"outerHTML\s*=", r"insertAdjacentHTML", r"document\.write", r"\beval\(", r"new\s+Function",
                  r"chrome\.", r"\bfetch\(", r"XMLHttpRequest", r"WebSocket", r"sendBeacon", r"addEventListener\(\s*[\"']message",
                  r"\.checked\s*=", r"location\s*(\.href\s*)?=[^=]", r"\.assign\(\s*[\"'`]http", r"window\.open", r"setTimeout\(\s*[\"']"]
        for name in ("content.js", "matcher.js"):
            src = code(name)
            for rx in banned:
                self.assertIsNone(re.search(rx, src), f"{name} contains {rx}")
        src = code("content.js")
        self.assertIn('attachShadow({ mode: "closed" })', src)  # the panel: page scripts cannot reach it
        self.assertEqual(src.count('addEventListener("click"'), 1)  # one handler, for our own panel buttons ...
        self.assertIn("if (e.isTrusted) on();", src)  # ... which only a real click of yours triggers

    def test_popup_calls_only_extension_routes_and_renders_text(self):
        src = code("popup.js")
        self.assertNotRegex(src, r"innerHTML|insertAdjacentHTML|outerHTML|document\.write|\beval\(")
        self.assertEqual(len(re.findall(r"\bfetch\(", src)), 1)  # one network call, inside post()
        self.assertIn("fetch(`http://127.0.0.1:${port}${path}`", src)
        self.assertIn(r'if (!/^\/api\/ext\/[a-z]+$/.test(path)) throw', src)
        calls = re.findall(r"\bawait post\(\s*[^,]+,\s*([^,]+),", src)
        self.assertEqual(len(calls), len(re.findall(r"\bpost\(", src)) - 1)  # every call but the definition, awaited
        for c in calls:
            self.assertRegex(c.strip(), r'^"/api/ext/[a-z]+"$')  # literal routes only; never "/", which holds the page token
        self.assertNotIn("storage.sync", src)

    def test_no_file_syncs_the_secret_or_runs_anywhere_by_itself(self):
        for f in EXT.rglob("*.js"):
            self.assertNotIn("storage.sync", f.read_text(encoding="utf-8"), f)  # it would copy the secret to the account
        html = (EXT / "popup.html").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"<script\b[^>]*>", html), ['<script src="matcher.js">', '<script src="popup.js">'])
        self.assertNotRegex(html, r"\son\w+\s*=")  # no inline handlers (the CSP would block them anyway)

    def test_manifest_asks_for_the_minimum(self):
        m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["manifest_version"], 3)
        self.assertEqual(m["permissions"], ["activeTab", "scripting", "storage"])
        self.assertEqual(m["host_permissions"], ["http://127.0.0.1/*"])
        self.assertEqual(m["externally_connectable"], {"ids": [], "matches": []})  # no page and no extension may message it
        for k in ("content_scripts", "background", "web_accessible_resources", "optional_permissions",
                  "optional_host_permissions", "key", "update_url"):
            self.assertNotIn(k, m)
        self.assertNotIn("<all_urls>", json.dumps(m))
        self.assertEqual(m["content_security_policy"]["extension_pages"],
                         "script-src 'self'; object-src 'none'; connect-src http://127.0.0.1:*")
        self.assertTrue((EXT / m["icons"]["128"]).is_file())
        from lodestar import __version__

        self.assertEqual(m["version"], __version__)  # bumped by hand with Lodestar releases

    def test_fixtures_are_small_scriptless_and_fictional(self):
        files = sorted(FIX.iterdir())
        self.assertLess(sum(f.stat().st_size for f in files), 200_000)
        pages = [f for f in files if f.suffix == ".html"]
        self.assertGreaterEqual(len(pages), 6)
        for f in pages:
            html = f.read_text(encoding="utf-8")
            scripts = re.findall(r"<script\b([^>]*)>", html, flags=re.I)
            self.assertTrue(all('type="application/ld+json"' in s for s in scripts), f)  # data only, never code
            self.assertNotRegex(html, r"(?i)<style\b|<link\b|\son[a-z]+\s*=|https?://(?!schema\.org)", f)
            self.assertIn("Fictional", html, f)
            self.assertNotRegex(html.lower(), r"linkedin\.com/jobs|easy-apply", f)  # no LinkedIn fixture, by design
            self.assertTrue(f.with_suffix(".descriptors.json").is_file(), f)
        for f in FIX.glob("*.descriptors.json"):
            self.assertIsInstance(json.loads(f.read_text(encoding="utf-8")), list)


class Node(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_node_matcher_suite_passes(self):
        r = subprocess.run(["node", "--test", "extension/test/*.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
        self.assertRegex(r.stdout, r"(?m)^\S* ?pass (\d+)")
        self.assertRegex(r.stdout, r"(?m)fail 0")
        for f in ("content.js", "matcher.js", "popup.js"):
            c = subprocess.run(["node", "--check", str(EXT / f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(c.returncode, 0, f + c.stderr)


if __name__ == "__main__":
    unittest.main()
