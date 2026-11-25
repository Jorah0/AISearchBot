"""Connection history (pass 34, the Accounts tab): every link (AI keys, the mailbox, each job board's last search, site
accounts) keeps its latest state, and every change of state is written to a history. A link that worked and then
failed is 'lost' with the time it stopped working, and you are notified (boards only show it: a board can blip). The
monitor loop re-checks keys and the mailbox every 6 hours (no tokens). No network; patched attributes are put back."""
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

from lodestar import accounts, connections, db, loop  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class History(unittest.TestCase):
    def setUp(self):
        self.notes = []
        self.real_path = connections.PATH
        connections.PATH = Path(tempfile.mkdtemp()) / "connections.json"
        self.p = patched(connections, notify=lambda m: self.notes.append(m))
        self.p.__enter__()

    def tearDown(self):
        self.p.__exit__(None, None, None)
        connections.PATH = self.real_path

    def test_a_key_that_stops_working_is_lost_since_then_and_you_are_told(self):
        connections.record("keys", "anthropic", {"status": "verified", "detail": "ok"}, "fp1")
        connections.record("keys", "anthropic", {"status": "verified", "detail": "ok"}, "fp1")  # no change: no line
        connections.record("keys", "anthropic", {"status": "failed", "detail": "key revoked"}, "fp1")
        h = connections.history()
        self.assertEqual([(x["name"], x["from"], x["to"]) for x in h], [("anthropic", "verified", "failed"), ("anthropic", "", "verified")])
        lost = connections.lost()
        self.assertEqual([(x["kind"], x["name"], x["detail"]) for x in lost], [("keys", "anthropic", "key revoked")])
        self.assertEqual(lost[0]["since"], h[0]["at"])
        self.assertEqual(len(self.notes), 1)
        self.assertIn("Anthropic", self.notes[0])
        connections.record("keys", "anthropic", {"status": "verified"}, "fp1")
        self.assertEqual(connections.lost(), [])  # working again
        self.assertEqual(connections.history()[0]["to"], "verified")

    def test_a_link_that_never_worked_is_failed_not_lost(self):
        connections.record("mail", None, {"status": "failed", "detail": "wrong password"}, "m")
        self.assertEqual(connections.lost(), [])
        self.assertEqual(self.notes, [])

    def test_boards_from_searches_and_site_accounts_are_tracked(self):
        def bad(q):
            raise OSError("HTTP 503")
        with patched(wm, SOURCES={"goodboard": lambda q: [], "badboard": bad}, EVERY={}, GLOBAL=set()):
            wm.search("x", sources=["goodboard", "badboard"], errors=[], ran=[])
            wm.search("x", sources=["goodboard"], errors=[], ran=[])
        st = connections.status()
        self.assertEqual((st["boards"]["goodboard"]["status"], st["boards"]["badboard"]["status"]), ("ok", "failed"))
        self.assertIn("HTTP 503", st["boards"]["badboard"]["detail"])
        with patched(wm, SOURCES={"goodboard": bad}, EVERY={}, GLOBAL=set()):
            wm.search("x", sources=["goodboard"], errors=[], ran=[])
        self.assertEqual([x["name"] for x in connections.lost()], ["goodboard"])
        self.assertEqual(self.notes, [])  # a board can blip: shown, never a notice
        db.con().execute("INSERT OR IGNORE INTO site_accounts(site, login_url, username, status) VALUES(?,?,?,?)",
                         ("acme.wd1.myworkdayjobs.com", "https://acme.wd1.myworkdayjobs.com/login", "pat", "active"))
        db.con().commit()
        accounts._mark("acme.wd1.myworkdayjobs.com", "active", login=True)
        accounts._mark("acme.wd1.myworkdayjobs.com", "failed", error="password rejected")
        lost = {x["name"]: x for x in connections.lost()}
        self.assertEqual(lost["acme.wd1.myworkdayjobs.com"]["detail"], "password rejected")
        self.assertEqual(len(self.notes), 1)
        db.con().execute("DELETE FROM site_accounts WHERE site='acme.wd1.myworkdayjobs.com'")
        db.con().commit()

    def test_history_is_capped_and_status_carries_it(self):
        for i in range(connections.HISTORY_MAX + 20):
            connections.record("keys", "groq", {"status": "verified" if i % 2 else "failed"}, "g")
        self.assertEqual(len(connections.history(10_000)), connections.HISTORY_MAX)
        st = connections.status()
        self.assertTrue(st["history"] and "lost" in st)

    def test_the_loop_rechecks_every_six_hours(self):
        calls = []
        db.con().execute("DELETE FROM meta WHERE key='conn:check'")
        db.con().commit()
        with patched(connections, check_all=lambda: calls.append(1), _STARTED=True):
            loop._recheck()
            loop._recheck()  # inside the window: not again
        self.assertEqual(calls, [1])
        db.con().execute("DELETE FROM meta WHERE key='conn:check'")
        db.con().commit()
        with patched(connections, check_all=lambda: calls.append(2), _STARTED=False):
            loop._recheck()  # a test, a one-off command or a scheduled --once run: no network check
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
