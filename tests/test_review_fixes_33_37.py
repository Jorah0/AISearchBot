"""Fixes from the independent review of passes 33-37 (2026-11-17): pacing counts the site you applied on (a company
link in apply_url is never a capped site), a mailbox no longer connected is never 'lost', a removed site account
leaves no 'lost' line, odd watch URLs never break add_watch and hash-routed / reordered pages dedupe right, seniority
false hits ('Associate Principal', 'Shift 1', '1-2 yrs'), unchanged board states skip the write, the 6-hourly re-check
runs off the loop's thread, and a mail id of Unicode digits is a 404. No network; every patch is put back."""
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

from lodestar import accounts, connections, db, loop, pacing  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class Pacing(unittest.TestCase):
    def test_a_company_application_link_is_never_counted_against_the_board(self):
        rows = [("https://www.linkedin.com/jobs/view/1", "https://careers.acme.example/apply/1", "2099-01-01 00:00:00", 1),
                ("https://www.linkedin.com/jobs/view/2", None, "2099-01-01 00:00:00", 2)]
        with patched(pacing, _moves=lambda: rows):
            self.assertEqual(pacing.usage()["LinkedIn"]["week"], 1)  # only the one applied on LinkedIn itself
        job = {"url": "https://www.linkedin.com/jobs/view/1", "apply_url": "https://careers.acme.example/apply/1"}

        class Row(dict):
            def keys(self):
                return super().keys()
        self.assertIsNone(pacing.for_job(Row(job)))


class Connections(unittest.TestCase):
    def setUp(self):
        self.real = connections.PATH
        connections.PATH = Path(tempfile.mkdtemp()) / "connections.json"
        self.p = patched(connections, notify=lambda m: None)
        self.p.__enter__()

    def tearDown(self):
        self.p.__exit__(None, None, None)
        connections.PATH = self.real

    def test_a_mailbox_no_longer_connected_is_not_lost(self):
        connections.record("mail", None, {"status": "verified"}, "old-fp")
        connections.record("mail", None, {"status": "failed", "detail": "sign-in refused"}, "old-fp")
        with patched(connections, _mail_current=lambda rec: True):
            self.assertEqual([x["kind"] for x in connections.lost()], ["mail"])
        with patched(connections, _mail_current=lambda rec: False):  # disconnected, or another mailbox now
            self.assertEqual(connections.lost(), [])

    def test_a_removed_site_account_leaves_no_lost_line(self):
        connections.track("sites", "acme.icims.com", "ok")
        connections.track("sites", "acme.icims.com", "failed", "bad password")
        self.assertEqual([x["name"] for x in connections.lost()], ["acme.icims.com"])
        connections.forget("sites", "acme.icims.com")
        self.assertEqual(connections.lost(), [])
        self.assertNotIn("acme.icims.com", connections.status()["sites"])

    def test_an_unchanged_board_state_is_not_written_again(self):
        connections.track("boards", "jobicy", "ok")
        before = connections.PATH.stat().st_mtime_ns
        writes = []
        with patched(connections, _save=lambda data: writes.append(1)):
            connections.track("boards", "jobicy", "ok")
        self.assertEqual((writes, connections.PATH.stat().st_mtime_ns), ([], before))

    def test_the_recheck_runs_off_the_loops_thread(self):
        import threading

        seen = []
        db.con().execute("DELETE FROM meta WHERE key='conn:check'")
        db.con().commit()
        done = threading.Event()
        with patched(connections, check_all=lambda: (seen.append(threading.current_thread()), done.set()), _STARTED=True):
            loop._recheck()
            self.assertTrue(done.wait(5))
        self.assertIsNot(seen[0], threading.current_thread())


class SiteAccounts(unittest.TestCase):
    def test_removing_an_account_forgets_its_state(self):
        calls = []
        with patched(connections, forget=lambda kind, name: calls.append((kind, name))):
            db.con().execute("INSERT OR IGNORE INTO site_accounts(site, login_url, username) VALUES(?,?,?)",
                             ("gone.example.com", "https://gone.example.com/login", "pat"))
            db.con().commit()
            aid = db.con().execute("SELECT id FROM site_accounts WHERE site='gone.example.com'").fetchone()["id"]
            with patched(accounts.vault, delete=lambda name: None):
                accounts.remove(aid)
        self.assertIn(("sites", "gone.example.com"), calls)


class Watches(unittest.TestCase):
    def test_odd_urls_never_raise_and_pages_dedupe_right(self):
        self.assertTrue(db.watch_key("http://[x"))  # a malformed host: a key, never ValueError
        self.assertNotEqual(db.watch_key("https://acme.example/#/jobs/1"), db.watch_key("https://acme.example/#/jobs/2"))
        self.assertEqual(db.watch_key("https://acme.example/#!/jobs"), db.watch_key("https://www.acme.example/#!/jobs"))
        self.assertEqual(db.watch_key("https://acme.example/careers#open"), db.watch_key("https://acme.example/careers"))
        self.assertEqual(db.watch_key("https://acme.example/jobs?a=1&b=2"), db.watch_key("https://acme.example/jobs?b=2&a=1"))


class Levels(unittest.TestCase):
    def test_review_false_hits(self):
        for title, want in (("Associate Principal Scientist", "staff"), ("Associate Creative Director", "manager"),
                            ("Associate General Counsel", "mid"), ("Warehouse Associate (Shift 1)", "mid"),
                            ("Engineer (1-2 yrs)", "mid"), ("Cashier 2 - Night", "mid"), ("Software Engineer II", "mid"),
                            ("Software Engineer III, Payments", "senior"), ("Associate Software Engineer", "junior")):
            self.assertEqual(wm.seniority_of(title), want, title)


class MailRoute(unittest.TestCase):
    def test_a_unicode_digit_mail_id_is_not_found(self):
        import http.client
        import json

        from lodestar import desktop, web
        mem = getattr(db._local, "con", None)
        db._local.con = None
        port = desktop.free_port(9030)
        srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/api/mail/%C2%B2", headers={"Host": f"127.0.0.1:{port}", "X-Lodestar-Token": web.TOKEN})
            r = c.getresponse()
            body = r.read().decode()
            c.close()
            self.assertNotEqual(r.status, 500, body)
            self.assertIn("error", json.loads(body))
        finally:
            srv.shutdown(); srv.server_close()
            db.release()
            db._local.con = mem


if __name__ == "__main__":
    unittest.main()
