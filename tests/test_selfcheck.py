"""lodestar selfcheck (pass 55) and the Android companion's guards. The AI review is one fenced call per tab over
the demo outline and survives a bad answer; the report names every part; live checks report each tool's contract;
the page check always runs in its own throwaway home. The Android app loads private addresses only and has no
third-party libraries. Phone access listens on every private address (a tether's too). No network."""
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
from test_pass21_fit import patched  # noqa: E402

from lodestar import ai, phone, selfcheck  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"


class SelfCheck(unittest.TestCase):
    def test_review_is_one_fenced_call_per_tab_and_survives_a_bad_answer(self):
        seen = []

        def fake(prompt, *a, **k):
            seen.append(prompt)
            if "TabB" in prompt:
                raise ValueError("broken JSON")
            return {"issues": [{"text": "Go", "problem": "vague <b>", "fix": "say what it does"}]}
        with patched(ai, ask_json=fake):
            out = selfcheck.review({"a": {"title": "TabA"}, "b": {"title": "TabB"}, "c": None})
        self.assertEqual(len(seen), 2)
        self.assertTrue(all("<<<" in p for p in seen))
        self.assertEqual(out["a"], [{"text": "Go", "problem": "vague b", "fix": "say what it does"}])
        self.assertIn("could not be read", out["b"][0]["problem"])

    def test_report_names_every_part(self):
        live = [{"tool": "AI: fill this page", "provider": "ollama", "ok": True, "detail": "1 fill", "seconds": 1.0},
                {"tool": "Cross-check", "provider": "council", "ok": False, "detail": "boom", "seconds": 0.5}]
        with patched(selfcheck, live=lambda provs: live):
            path = selfcheck.run(do_page=False, do_live=True, providers=["ollama"])
        md = path.read_text(encoding="utf-8")
        self.assertIn("Live AI tools: 1 of 2 passed", md)
        self.assertIn("FAIL Cross-check (council, 0.5 s): boom", md)

    def test_page_check_runs_only_in_a_throwaway_home(self):
        src = (ROOT / "lodestar" / "selfcheck_page.py").read_text(encoding="utf-8")
        self.assertIn('if not os.environ.get("LODESTAR_SELFCHECK_HOME")', src)
        seen = {}

        def fake_proc(cmd, cwd, timeout, env=None):
            seen.update(env)
            return 1, "", "boom"
        from lodestar import updater

        with patched(updater, _proc=fake_proc):
            with self.assertRaisesRegex(SystemExit, "did not finish"):
                selfcheck.page(Path(tempfile.mkdtemp()) / "x.json")
        self.assertNotEqual(Path(seen["LODESTAR_HOME"]).resolve(), Path(os.environ["LODESTAR_HOME"]).resolve())
        self.assertEqual((seen["LODESTAR_VAULT_SERVICE"], seen["LODESTAR_SELFCHECK_HOME"]), ("", "1"))
        self.assertFalse([k for k in seen if k.endswith("_API_KEY")])


class Android(unittest.TestCase):
    def test_the_app_loads_private_addresses_only_and_has_no_third_party_libraries(self):
        java = (ANDROID / "app/src/main/java/app/lodestar/mobile/MainActivity.java").read_text(encoding="utf-8")
        self.assertIn("static boolean isPrivate(String host)", java)
        self.assertIn('n[0] == 10 || (n[0] == 172 && n[1] >= 16 && n[1] <= 31) || (n[0] == 192 && n[1] == 168)', java)
        self.assertIn("if (sameOrigin(u)) return false;", java)  # every other link leaves the app
        self.assertIn("setAllowFileAccess(false)", java)
        self.assertIn("setAcceptThirdPartyCookies(web, false)", java)
        self.assertRegex(java, r"FLAG_DEBUGGABLE\) != 0\) \{\s+WebView\.setWebContentsDebuggingEnabled\(true\)")
        gradle = (ANDROID / "app/build.gradle.kts").read_text(encoding="utf-8")
        deps = re.findall(r'^\s*(\w+)\("([^"]+)"\)', gradle.split("dependencies {", 1)[1], re.M)
        self.assertEqual(deps, [("testImplementation", "junit:junit:4.13.2")])
        manifest = (ANDROID / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertEqual(sorted(re.findall(r'uses-permission android:name="android\.permission\.(\w+)"', manifest)),
                         ["ACCESS_NETWORK_STATE", "INTERNET", "POST_NOTIFICATIONS",  # pass 58: self-update from the
                          "REQUEST_INSTALL_PACKAGES"])  # paired computer (its own newer build only) + "tap to open"
        self.assertIn('android:allowBackup="false"', manifest)


class PhoneAddresses(unittest.TestCase):
    def test_every_private_address_and_the_wifi_one_first(self):
        import socket

        fake = [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ("192.168.42.129", "8.8.8.8", "127.0.0.1", "169.254.1.2", "192.168.1.153")]
        with patched(phone, lan_ip=lambda: "192.168.1.153", tailscale_ips=lambda: []), patched(socket, getaddrinfo=lambda *a, **k: fake):
            self.assertEqual(phone.lan_ips(), ["192.168.1.153", "192.168.42.129"])  # a USB tether's address too
        with patched(phone, lan_ip=lambda: None, tailscale_ips=lambda: []), patched(socket, getaddrinfo=lambda *a, **k: []):
            self.assertEqual(phone.lan_ips(), [])


if __name__ == "__main__":
    unittest.main()
