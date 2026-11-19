"""Pass 57: the CAPTCHA auto-solver (captcha.py) and the auto sign-on (signon.py). The solver reads a widget's pixels,
asks the vision AI (Ollama first) for the answer, performs it and re-checks the page's own evidence (captcha_solved) -
within a daily solve cap and a per-widget stop, so it never spams a site; a type it cannot drive is handed to the user.
signon signs in on a website with the saved account (password manager), auto-clears a CAPTCHA on the way, and stops
after two failed sign-ins (login_max_failures) so the user finishes the login in the window. Both run with a fake page,
no browser; every patched attribute and setting is put back."""
import contextlib
import os
import sys
import tempfile
import unittest

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

import keyring  # noqa: E402
from lodestar import accounts, ai, captcha, db, profile, settings, signon, vault  # noqa: E402

SITE = "acme.wd5.myworkdayjobs.test"
LOGIN = f"https://{SITE}/login"
PROF = ("# Jane Doe\nJane Doe | jane@example.com\n## Summary\nData engineer.\n"
        "## Skills\nPython, SQL\n## Preferences\nSalary floor: $123,456\n")


@contextlib.contextmanager
def fake_ai(answer=""):
    old = ai.ask_image
    ai.ask_image = lambda *a, **k: answer
    try:
        yield
    finally:
        ai.ask_image = old


class FakePage:
    """The solver + signon page-object protocol over a small model. state: 'captcha' (a challenge until solved), then
    'login' (a sign-in form), then the verdict (ok | failed | locked). captcha_kind: the challenge's type. solve_ok:
    whether the solver's answer is the right one (False: the page stays pending -> the solver reports failed)."""

    def __init__(self, captcha_kind=None, verdict="ok", solve_ok=True):
        self.kind = captcha_kind
        self.state = "captcha" if captcha_kind else "login"
        self.verdict, self.solve_ok, self.answered = verdict, solve_ok, False
        self.dos, self.typed, self.clicks = [], [], []

    def blocker(self):
        return "captcha" if self.state == "captcha" else None

    def captcha(self):
        if self.state != "captcha":
            return None
        return {"type": self.kind, "screenshot": b"\x89PNG fake", "hint": ""}

    def captcha_do(self, kind, answer):
        self.dos.append((kind, answer))
        if self.solve_ok:  # the right answer: the page's own evidence flips
            self.state = "login"

    def captcha_solved(self):
        return self.state != "captcha"

    # --- the sign-in form (the accounts.Page interface) once the CAPTCHA is cleared
    def inputs(self):
        if self.state != "login" or self.answered:
            return []  # answered (or not on the form): the form is gone
        return [{"a": 0, "frame": 0, "type": "email", "hint": "Email Address"},
                {"a": 1, "frame": 0, "type": "password", "hint": "Password"}]

    def type(self, d, value, secret=False):
        self.typed.append((d["a"], value))

    def click(self, rx):
        self.clicks.append(str(getattr(rx, "pattern", rx)))
        if self.state == "login":  # the single Sign in button: the site takes the credentials
            self.answered = True
        return True

    def text(self):
        return {"failed": "Incorrect email or password.",
                "locked": "Your account has been locked after too many failed attempts."}.get(self.verdict, "")

    def link(self, rx):
        return None

    def url(self):
        return LOGIN


class Base(unittest.TestCase):
    def setUp(self):
        profile.write_master(PROF)
        db.release()
        self.store = {}
        for k, f in (("get_password", lambda s, n: self.store.get((s, n))),
                     ("set_password", lambda s, n, v: self.store.__setitem__((s, n), v)),
                     ("delete_password", lambda s, n: self.store.pop((s, n), None))):
            old = getattr(keyring, k)
            setattr(keyring, k, f)
            self.addCleanup(setattr, keyring, k, old)
        self._clear()
        self.addCleanup(self._clear)
        settings.set_tool("captcha_solver", enabled=True, auto=True)
        settings.set_tool("signon", enabled=True, auto=True)
        settings.set_pref("captcha_daily_max", 100)
        settings.set_pref("captcha_max_attempts", 2)
        settings.set_pref("login_max_failures", 2)

    def _clear(self):
        db.release(close=False)
        db.con().execute("DELETE FROM site_accounts")
        db.con().execute("DELETE FROM meta")
        db.con().commit()
        idx = vault._index()
        if any(n.startswith("site:") for n in idx):
            vault._save_index({k: v for k, v in idx.items() if not k.startswith("site:")})


class Solve(Base):
    def test_a_text_captcha_is_read_and_typed(self):
        page = FakePage("text")
        with fake_ai(" ABCD 12! "):
            r = captcha.solve(page)
        self.assertEqual((r["result"], r["type"]), ("solved", "text"))
        self.assertEqual(page.dos, [("text", "ABCD12")])  # case preserved, punctuation stripped
        self.assertGreaterEqual(db.meta_get("quota:captcha"), 1)

    def test_a_puzzle_is_dragged_to_the_model_distance(self):
        page = FakePage("geetest")
        with fake_ai("128 pixels"):
            r = captcha.solve(page)
        self.assertEqual(r["result"], "solved")
        self.assertEqual(page.dos[0], ("geetest", 128))

    def test_a_bad_model_answer_is_a_failure_not_a_guess(self):
        page = FakePage("text")
        with fake_ai("I can't see it"):
            r = captcha.solve(page)
        self.assertEqual((r["result"], r["attempts"], page.dos), ("failed", 1, []))

    def test_off_is_a_handoff_not_a_solve(self):
        settings.set_tool("captcha_solver", enabled=False)
        page = FakePage("text")
        with fake_ai("abcd"):
            r = captcha.solve(page)
        self.assertEqual((r["result"], page.dos, page.captcha_solved()), ("unavailable", [], False))

    def test_the_daily_cap_stops_the_solver(self):
        settings.set_pref("captcha_daily_max", 1)
        db.meta_set("quota:captcha", 1)
        page = FakePage("text")
        with fake_ai("abcd"):
            r = captcha.solve(page)
        self.assertEqual((r["result"], page.dos), ("capped", []))

    def test_a_kind_the_solver_cannot_drive_is_yours(self):
        page = FakePage("turnstile")
        with fake_ai("yes"):
            r = captcha.solve(page)
        self.assertEqual((r["result"], page.dos), ("unavailable", []))

    def test_the_per_widget_stop_limits_attempts(self):
        settings.set_pref("captcha_max_attempts", 3)
        page = FakePage("text", solve_ok=False)
        with fake_ai("abcd"):
            r = captcha.solve(page)
        self.assertEqual((r["result"], r["attempts"], len(page.dos)), ("failed", 3, 3))

    def test_a_failed_solver_costs_a_quota_unit(self):
        page = FakePage("text", solve_ok=False)
        with fake_ai("abcd"):
            captcha.solve(page)
        self.assertEqual(db.meta_get("quota:captcha"), 2)

    def test_a_checkbox_needs_no_ai(self):
        page = FakePage("checkbox")
        calls = []
        old = ai.ask_image
        ai.ask_image = lambda *a, **k: calls.append(1) or "x"
        self.addCleanup(setattr, ai, "ask_image", old)
        r = captcha.solve(page)
        self.assertEqual((r["result"], calls, page.dos[0]), ("solved", [], ("checkbox", "click")))


class SignOn(Base):
    def test_signs_in_with_the_saved_account(self):
        accounts.add(LOGIN, "jane@example.com", "Saved-Pass-1!")
        page = FakePage(verdict="ok")
        r = signon.login(page, SITE)
        self.assertEqual(r["result"], "ok")
        self.assertIn((1, "Saved-Pass-1!"), page.typed)  # the password went into the password field
        self.assertEqual(accounts.get(accounts.for_site(SITE)["id"])["status"], "active")

    def test_clears_a_captcha_on_the_way(self):
        accounts.add(LOGIN, "jane@example.com", "Saved-Pass-1!")
        page = FakePage("text")
        with fake_ai("abcd12"):
            r = signon.login(page, SITE)
        self.assertEqual(r["result"], "ok")
        self.assertGreaterEqual(db.meta_get("quota:captcha"), 1)

    def test_two_failed_signins_lock_the_site(self):
        accounts.add(LOGIN, "jane@example.com", "Wrong-Pass-1!")
        r1 = signon.login(FakePage(verdict="failed"), SITE)
        self.assertEqual(r1["result"], "failed")
        self.assertEqual(signon.failures(SITE), 1)
        r2 = signon.login(FakePage(verdict="failed"), SITE)
        self.assertEqual(r2["result"], "locked")
        self.assertEqual(signon.failures(SITE), 2)
        r3 = signon.login(FakePage(verdict="ok"), SITE)
        self.assertEqual((r3["result"], signon.failures(SITE)), ("locked", 2))  # the third is refused, not a third try

    def test_a_correct_password_resets_the_count(self):
        accounts.add(LOGIN, "jane@example.com", "Wrong-Pass-1!")
        signon._bump(SITE)
        self.assertTrue(signon.locked_out(SITE))
        signon.clear(SITE)
        self.assertFalse(signon.locked_out(SITE))

    def test_no_saved_account_is_yours(self):
        self.assertEqual(signon.login(FakePage(verdict="ok"), "nowhere.example")["result"], "yours")

    def test_disabled_is_a_handoff(self):
        settings.set_tool("signon", enabled=False)
        self.assertEqual(signon.login(FakePage(verdict="ok"), SITE)["result"], "unavailable")


if __name__ == "__main__":
    unittest.main()
