"""Setup > Phone access (pass 53): turn on (the listener binds the home-network address; loopback here), make a
pairing code, a phone pairs with it, the card lists it, Sign out all phones, turn off."""
import http.client
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from harness import E2ETestCase

from lodestar import phone, settings  # noqa: E402  (after harness: it sets the temp home first)


class Phone(E2ETestCase):
    def test_turn_on_pair_list_sign_out_and_off(self):
        old = phone.lan_ips
        phone.lan_ips = lambda: ["127.0.0.1"]
        self.addCleanup(setattr, phone, "lan_ips", old)
        self.addCleanup(phone.stop)
        self.addCleanup(phone.revoke_all)
        self.addCleanup(settings.set_pref, "phone_access", False)
        self.go("setup")
        card = self.page.locator("#phoneCard")
        self.assertIn("No phones paired", card.text_content())
        self.assertTrue(self.page.locator("#phoneCodeBtn").is_disabled())
        self.run_click("#phoneToggle")
        self.page.wait_for_function("() => /open http:/.test(document.querySelector('#phoneUrl').textContent)")
        url = re.search(r"http://\S+", self.page.text_content("#phoneUrl"))[0]
        self.assertTrue(settings.pref("phone_access"))
        self.run_click("#phoneCodeBtn")
        code = self.page.text_content("#phoneCode").split()[0]
        u = urllib.parse.urlsplit(url)  # http.client: the harness fakes urllib's urlopen
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
        c.request("POST", "/phone", urllib.parse.urlencode({"code": code, "label": "Test phone"}),
                  {"Content-Type": "application/x-www-form-urlencoded"})
        r = c.getresponse()
        self.assertEqual((r.status, r.getheader("Location")), (303, "/"))
        c.close()
        self.page.evaluate("phoneLoad()")
        self.idle()
        self.assertIn("Test phone", card.text_content())
        self.run_click(card.get_by_role("button", name="Sign out all phones"))
        self.expect_toast("signed out 1 phone(s)", "ok")
        self.run_click("#phoneToggle")
        self.assertIn("off", self.page.text_content("#phoneUrl"))
        self.assertFalse(settings.pref("phone_access"))

    def test_the_card_names_the_android_app_a_phone_downloads(self):
        d = Path(tempfile.mkdtemp())
        (d / "lodestar.apk").write_bytes(b"PK\x03\x04apk")
        (d / "lodestar.version.json").write_text('{"code": 9, "name": "2026.11.23-0900"}', encoding="utf-8")
        old_ips, old_dir = phone.lan_ips, phone.APP_DIR
        phone.lan_ips, phone.APP_DIR = (lambda: ["127.0.0.1"]), d
        self.addCleanup(setattr, phone, "lan_ips", old_ips)
        self.addCleanup(setattr, phone, "APP_DIR", old_dir)
        self.addCleanup(phone.stop)
        self.addCleanup(settings.set_pref, "phone_access", False)
        self.go("setup")
        self.run_click("#phoneToggle")
        self.page.wait_for_function("() => /app\\.apk/.test(document.querySelector('#phoneApp').textContent)")
        text = self.page.text_content("#phoneApp")
        self.assertIn("2026.11.23-0900", text)
        u = urllib.parse.urlsplit(re.search(r"http://\S+app\.apk", text)[0])
        c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)  # the phone, before it is paired
        c.request("GET", u.path)
        r = c.getresponse()
        self.assertEqual((r.status, r.read()), (200, b"PK\x03\x04apk"))
        c.close()
        self.run_click("#phoneToggle")
        self.assertEqual(self.page.text_content("#phoneApp"), "")


if __name__ == "__main__":
    unittest.main()
