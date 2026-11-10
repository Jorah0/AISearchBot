"""Smoke: every tab loads with the seeded data, logs no console error, and has no horizontal scroll at 420px."""
import http.client
import unittest

from harness import TABS, E2ETestCase, web


class Smoke(E2ETestCase):
    def test_page_carries_the_launch_token_and_the_seed(self):
        self.assertEqual(self.page.evaluate("window.LODESTAR_TOKEN"), web.TOKEN)
        self.assertEqual(self.page.locator(".card[data-id]").count(), len([k for k in self.ids if k in (
            "saved", "applied", "screening", "interview", "offer", "accepted", "rejected", "withdrawn")]))
        self.assertGreaterEqual(int(self.page.text_content("#inboxN")), 2)  # the reply and the follow-up
        drawer = self.open_job(self.ids["interview"])
        self.assertIn("Orchid Health", drawer.text_content())
        self.press("Escape")
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertEqual(self.overflow(), [], "the page scrolls sideways at 1280px")

    def test_api_needs_the_token_and_this_host(self):
        self.allow_console(r"status of 403")
        fetch = "([path, headers]) => fetch(path, {headers}).then(async r => [r.status, await r.text()])"
        self.assertEqual(self.page.evaluate(fetch, ["/api/state", {"X-Lodestar-Token": web.TOKEN}])[0], 200)
        for headers in ({}, {"X-Lodestar-Token": "wrong-token"}):
            status, body = self.page.evaluate(fetch, ["/api/state", headers])
            self.assertEqual(status, 403, headers)
            self.assertNotIn("Northwind", body)
        # another Host (DNS rebinding): a browser cannot forge the header, so ask the server directly
        port = self.server.server_address[1]
        for host in ("evil.example", f"evil.example:{port}"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/api/state", headers={"Host": host, "X-Lodestar-Token": web.TOKEN})
            r = c.getresponse()
            self.assertEqual(r.status, 421, host)
            self.assertNotIn(b"Northwind", r.read())
            c.close()

    def _smoke(self, tab):
        self.go(tab)
        self.assertTrue(self.page.locator(f"section#{tab}").is_visible())
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [], f"{tab} scrolls sideways at 420px")


for _t in TABS:
    setattr(Smoke, f"test_tab_{_t}", lambda self, t=_t: self._smoke(t))

if __name__ == "__main__":
    unittest.main()
