"""Pass 56: a CAPTCHA stays yours, but costs you less. A solved widget (its response field holds a token) is no longer a
blocker, so the run carries on without Continue; a run at a CAPTCHA is parked and the worker fills the next queued run
meanwhile; a needs-you alert also raises a desktop toast (pref desktop_notifications). Light AI judgements run on your
local Ollama with pref ai_light_local. Nothing here reads, writes or solves a challenge: only the page's own response
field is read. Every patched attribute and setting is put back."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_apply_engine import BASIC, Base, FakeBrowser, patched  # noqa: E402

from lodestar import ai, apply_agent, apply_ats, db, settings, util  # noqa: E402


class _El:
    def __init__(self, value="", src="https://www.google.com/recaptcha/api2/anchor"):
        self.value, self.src = value, src

    def get_attribute(self, k):
        return self.src

    def is_visible(self):
        return True

    def bounding_box(self):
        return {"width": 304, "height": 78}

    def input_value(self):
        return self.value


def _tab(token, frames=None):
    class Page:
        def locator(self, sel):
            if sel == apply_ats.CHALLENGE:
                els = frames or [_El()]
            else:
                els = [_El(token)] if sel == apply_ats.SOLVED_BY["recaptcha"] else []
            return type("L", (), {"all": lambda s: els})()

    tab = apply_ats.Tab.__new__(apply_ats.Tab)
    tab.page, tab._allowed_frames, tab.text = Page(), lambda: [], lambda: ""
    return tab


class Solved(unittest.TestCase):
    def test_a_solved_widget_is_not_a_blocker(self):
        self.assertEqual(_tab("").blocker(), "captcha")
        self.assertIsNone(_tab("03AFcWeA-token").blocker())
        self.assertTrue(_tab("03AFcWeA-token").solved())

    def test_each_widget_is_judged_by_its_own_field(self):
        """A token from a reCAPTCHA badge never clears another widget; a type with no field (Arkose) is never solved."""
        arkose = _El(src="https://client-api.arkoselabs.com/fc/gc/")
        hcap = _El(src="https://newassets.hcaptcha.com/captcha/v1/x")
        for frames in ([_El(), arkose], [hcap], [arkose]):
            tab = _tab("03AFcWeA-token", frames)
            self.assertEqual(tab.blocker(), "captcha")
            self.assertFalse(tab.solved())

    def test_a_page_error_is_never_taken_as_solved(self):
        tab = apply_ats.Tab.__new__(apply_ats.Tab)
        tab.page = type("P", (), {"locator": lambda s, sel: (_ for _ in ()).throw(RuntimeError("context destroyed"))})()
        self.assertFalse(tab.solved())


class Parked(Base):
    def _browser(self, model):
        class B(FakeBrowser):
            def open(s, url, hosts):
                t = FakeBrowser.open(s, url, hosts)
                t.blk = "captcha" if len(s.tabs) == 1 else None
                t.blocker = lambda: t.blk
                t.solved = lambda: t.blk != "captcha"
                return t
        return B(model)

    def test_a_captcha_parks_and_the_queue_moves_on_then_resumes_by_itself(self):
        a, b = self.job("Parkco"), self.job("Nextco")
        seen = []

        def hook(_):
            runs = {r["job_id"]: r for r in db.live_runs()}
            tabs = {t.url: t for t in br.tabs}
            ra, rb = runs.get(a), runs.get(b)
            if ra and ra["state"] == "needs_you" and rb and rb["state"] == "ready":
                seen.append("next run filled while the first waited")
                self.assertFalse(ra["answers"].get("_continue"))
                tabs[ra["url"]].blk = None  # you solved it in the window; nobody pressed Continue
            for r in (ra, rb):
                if r and r["state"] == "ready":
                    tabs[r["url"]].submitted = True
        br = self._browser({"pages": [{"fields": BASIC, "submit": True}], "hook": hook})
        out = apply_agent.enqueue([a, b], "stop", start=False)
        apply_agent._loop(lambda: br, until_idle=True)
        self.assertEqual(seen[:1], ["next run filled while the first waited"])
        self.assertEqual([db.get_run(r["run_id"])["state"] for r in out], ["by_user", "by_user"])
        self.assertTrue(any("solve the check" in n and "Parkco" in n for n in self.notes))

    def test_continue_passes_a_widget_lodestar_cannot_read_once(self):
        a = self.job("Unreadco")

        def hook(_):
            run = (db.live_runs() or [None])[0]
            if run and run["state"] == "needs_you" and "_parked" in run["answers"]:
                self.assertTrue(br.tabs[0].suspended)
                apply_agent.continue_run(run["id"])  # the widget still looks unsolved to Lodestar
            elif run and run["state"] == "ready":
                br.tabs[0].submitted = True
        br = self._browser({"pages": [{"fields": BASIC, "submit": True}], "hook": hook})
        (out,) = apply_agent.enqueue([a], "stop", start=False)
        apply_agent._loop(lambda: br, until_idle=True)
        run = db.get_run(out["run_id"])
        self.assertEqual(run["state"], "by_user")
        self.assertNotIn("_parked", run["answers"])

    def test_a_parked_marker_never_resumes_a_run_that_clicked_submit(self):
        jid = self.job("Clickco")
        (out,) = apply_agent.enqueue([jid], "stop", start=False)
        rid = out["run_id"]
        db.update_run(rid, state="needs_you", submit_clicks=1, answers={"_parked": 1, "_continue": True})
        tab = type("T", (), {"closed": False, "forbidden_hit": None, "solved": lambda s: True,
                             "confirmed": lambda s: None})()
        with patched(apply_agent, _fill=lambda *a, **k: self.fail("a submitted run went back to filling")):
            apply_agent._watch(rid, {rid: tab})
        self.assertEqual(db.get_run(rid)["state"], "needs_you")
        apply_agent._end(rid, "stopped", "test")

    def test_needs_you_raises_a_desktop_toast_only_with_the_pref(self):
        toasts = []
        for on in (False, True):
            settings.set_pref("desktop_notifications", on)
            with patched(util, desktop_notify=lambda t, b: toasts.append((t, b)) or True):
                apply_agent._alert(db.get_job(self.job(f"Toastco {on}")), "solve the check in the agent window")
                for _ in range(50):
                    if toasts or not on:
                        break
                    time.sleep(0.02)
        self.assertEqual(len(toasts), 1)
        self.assertIn("Toastco True", toasts[0][1])


class LocalLight(unittest.TestCase):
    def setUp(self):
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.calls = []

    def ask(self, fail=()):
        def fake(prompt, system=None, provider=None, **kw):
            self.calls.append(provider)
            if provider in fail:
                raise SystemExit("ollama: model 'llama3' was rejected (not found)")
            return '{"ok": true}'
        return patched(ai, ask=fake, available=lambda: ["anthropic", "ollama"])

    def test_light_calls_go_to_ollama_with_the_pref(self):
        with self.ask():
            ai.ask_json_light("q")
            settings.set_pref("ai_light_local", True)
            ai.ask_json_light("q")
            ai.ask_json_light("q", provider="anthropic")  # a provider you named wins
        self.assertEqual(self.calls, [None, "ollama", "anthropic"])

    def test_a_dead_ollama_falls_back_to_the_usual_light_model(self):
        settings.set_pref("ai_light_local", True)
        with self.ask(fail=("ollama",)):
            self.assertEqual(ai.ask_json_light("q"), {"ok": True})
        self.assertEqual(self.calls, ["ollama", None])

    def test_without_ollama_linked_nothing_changes(self):
        settings.set_pref("ai_light_local", True)
        with self.ask(), patched(ai, available=lambda: ["anthropic"]):
            ai.ask_json_light("q")
        self.assertEqual(self.calls, [None])


if __name__ == "__main__":
    unittest.main()
