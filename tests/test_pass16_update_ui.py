"""Pass 16.4, the update UI's server side: the token-protected /api/update/* routes, the state's update view (badge,
failed note, restart), the apply route's "only the range you saw" rule, Restart (desktop only, never while something is
in flight) and desktop.relaunch. Throwaway repos from test_pass16_update.Base; the test gate is faked here (that file
runs the real one)."""
import http.client
import json
import sys
import time
import unittest

from test_pass16_update import Base, patched

from lodestar import cli, connections, desktop, updater, web
from lodestar.config import HOME


class Routes(Base):
    def setUp(self):
        super().setUp()
        self.port = desktop.free_port(9030)
        self.srv = web.start_server(self.port)
        self.addCleanup(lambda: (self.srv.shutdown(), self.srv.server_close()))
        self.gates = []
        for obj, attr, val in ((updater, "ROOT", self.install), (updater, "_gate", self.gates.append),
                               (web, "RESTART", None)):
            self.addCleanup(setattr, obj, attr, getattr(obj, attr))
            setattr(obj, attr, val)

    def req(self, method, path, body=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}",
             "X-Lodestar-Token": web.TOKEN if token else "no"}
        c.request(method, path, json.dumps(body) if body is not None else None, h)
        r = c.getresponse()
        out = (r.status, json.loads(r.read().decode() or "{}"))
        c.close()
        return out

    def task(self, path, body=None):
        code, r = self.req("POST", path, body or {})
        self.assertEqual(code, 200, r)
        for _ in range(300):
            t = self.req("GET", f"/api/tasks/{r['task']}")[1]
            if t["status"] != "running":
                return t
            time.sleep(0.05)
        self.fail("the update task never finished")

    def test_every_update_route_needs_the_token(self):
        for method, path in (("GET", "/api/update/status"), ("GET", "/api/update/log"), ("POST", "/api/update/check"),
                             ("POST", "/api/update/apply"), ("POST", "/api/update/restart")):
            self.assertEqual(self.req(method, path, {} if method == "POST" else None, token=False)[0], 403, path)
        self.assertFalse(updater.LOG.is_file())  # nothing ran

    def test_check_apply_status_log_and_the_badge(self):
        s = self.req("GET", "/api/update/status")[1]
        self.assertEqual((s["kind"], s["mode"], s["available"], s["failed"], s["restart"]), ("git", "notify", False, None, False))
        target = self.release()
        t = self.task("/api/update/check")
        self.assertEqual((t["action"], t["result"]["behind"], t["result"]["target"]), ("update_check", 1, target))
        self.assertIn("v2: second release", t["result"]["commits"][0])
        st = self.req("GET", "/api/state")[1]["update"]
        self.assertTrue(st["available"])  # the top-bar badge
        self.assertEqual(st["log"][0]["kind"], "check")
        # Update now carries the target the user saw: an origin that moved since is refused, nothing changes
        newer = self.write({"README.md": "later\n"}, "v3", push=True)
        t = self.task("/api/update/apply", {"target": target})
        self.assertEqual(t["status"], "error")
        self.assertIn("check again", t["error"])
        self.assertEqual(self.head(), self.v1)
        t = self.task("/api/update/apply", {"target": newer})
        self.assertTrue(t["result"]["ok"], t)
        self.assertEqual((self.head(), self.gates), (newer, [self.install]))
        st = self.req("GET", "/api/update/status")[1]
        self.assertEqual((st["available"], st["restart_needed"], st["failed"]), (False, True, None))
        log = self.req("GET", "/api/update/log?limit=1")[1]["log"]
        self.assertEqual((len(log), log[0]["kind"], log[0]["ok"]), (1, "apply", True))

    def test_a_failed_update_is_the_getting_started_note_and_a_harmless_apply_is_not(self):
        self.release()
        plan = updater.check(self.install)  # logged: what the badge reads
        with patched(updater, _gate=lambda repo: (_ for _ in ()).throw(SystemExit("3 tests failed"))):
            r = updater.apply(self.install, plan)
        self.assertFalse(r["ok"])
        v = web.update_view()
        self.assertIn("rolled back", v["failed"]["result"])
        self.assertTrue(v["available"])  # the check before it still stands: the update is still offered
        updater._done(False, "", "", "up to date")  # an apply with nothing to do is not a failure to report
        self.assertIsNone(web.update_view()["failed"])

    def test_restart_only_in_the_desktop_app_and_never_while_something_is_in_flight(self):
        code, r = self.req("POST", "/api/update/restart", {})
        self.assertEqual(code, 400)
        self.assertIn("desktop app only", r["error"])
        calls = []
        web.RESTART = lambda: calls.append(1)
        self.assertTrue(self.req("GET", "/api/update/status")[1]["restart"])
        lock = HOME / ".email.lock"
        lock.write_text("1", encoding="utf-8")
        try:
            code, r = self.req("POST", "/api/update/restart", {})
        finally:
            lock.unlink()
        self.assertEqual(code, 400)
        self.assertIn("email run is in progress", r["error"])
        self.assertEqual(self.req("POST", "/api/update/restart", {}), (200, {"ok": True}))
        for _ in range(40):
            if calls:
                break
            time.sleep(0.05)
        self.assertEqual(calls, [1])

    def test_state_still_loads_when_the_install_cannot_be_read(self):
        with patched(updater, status=lambda repo: (_ for _ in ()).throw(SystemExit("broken"))):
            v = self.req("GET", "/api/state")[1]["update"]
        self.assertEqual((v["kind"], v["available"], v["error"]), ("none", False, "broken"))


class Relaunch(unittest.TestCase):
    def test_relaunch_starts_the_same_command_and_ends_this_process(self):
        import subprocess
        import threading

        started, timers = [], []

        class Timer:
            def __init__(self, delay, fn, args):
                timers.append((delay, fn, args))

            def start(self):
                pass

        with patched(subprocess, Popen=lambda cmd, **kw: started.append(cmd)), patched(threading, Timer=Timer), \
                patched(sys, argv=["lodestar", "desktop", "--every", "15"]):
            desktop.relaunch()
        self.assertEqual(started, [[sys.executable, "-m", "lodestar", "desktop", "--every", "15"]])
        self.assertEqual(timers[0][0], 5)  # the backstop for the browser fallback (no window to close)

    def test_lodestar_desktop_offers_restart(self):
        seen = []
        a = cli.build().parse_args(["desktop", "--no-loop"])
        srv = type("Srv", (), {"shutdown": lambda self: None})()  # no real server: nothing to leave open
        with patched(desktop, open_window=lambda port: seen.append(web.RESTART)), \
                patched(connections, start_checks=lambda: None), patched(web, RESTART=None, start_server=lambda port: srv):
            cli.cmd_desktop(a)
        self.assertEqual(seen, [desktop.relaunch])


if __name__ == "__main__":
    unittest.main()
