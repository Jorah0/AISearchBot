"""Pass 24: eligibility gates kept apart from the fit score (blueprint 7.2) and the career class of every job (4.4, 7.3).
A gate is met, not_met or unknown; unknown is never met. Gates: work authorization / sponsorship, clearance, licenses
the posting requires, your exclusions. No network, no AI; every patched attribute is put back."""
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
from test_pass21_fit import JD, PROF, Base, L  # noqa: E402

from lodestar import fit, settings  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

CDL = JD.replace("Requirements:\n", "Requirements:\n- Must hold a valid Class A CDL license\n")


def gate(f, word):
    return next((g for g in f["gates"] if word in g["requirement"].lower()), None)


class Gates(Base):
    def test_sponsorship_states(self):
        no, silent = L(desc=JD + " We cannot sponsor visas for this role."), L()
        self.assertEqual(gate(fit.score(no), "sponsor")["state"], "unknown")  # your status is not set: not known
        self.assertIsNone(gate(fit.score(silent), "sponsor"))  # nothing to judge
        settings.set_pref("work_authorization", "needs_sponsorship")
        f = fit.score(no)
        self.assertEqual(gate(f, "sponsor")["state"], "not_met")
        self.assertTrue(f["blocked"])
        self.assertEqual(f["chips"][0]["text"], "says no visa sponsorship")  # a failed gate leads the chips
        f = fit.score(silent)
        self.assertEqual(gate(f, "sponsor")["state"], "unknown")  # silent is never met
        self.assertFalse(f["blocked"])
        self.assertTrue(f["gates_unknown"])
        self.assertEqual(gate(fit.score(L(desc=JD + " Visa sponsorship is available.")), "sponsor")["state"], "met")
        settings.set_pref("work_authorization", "authorized")
        self.assertEqual(gate(fit.score(no), "sponsor")["state"], "met")
        self.assertIsNone(gate(fit.score(silent), "sponsor"))

    def test_clearance_gate_is_never_a_score_cut(self):
        cl = L(desc=JD + " An active secret clearance is required for this role.")
        f = fit.score(cl)
        self.assertEqual(gate(f, "clearance")["state"], "unknown")
        self.assertFalse(f["blocked"])
        self.assertNotIn("clearance", [m["why"] for m in f["mods"]])
        PROFILE.write_text(PROF.replace("## Experience", "## Security clearance\nActive Secret clearance\n## Experience"),
                           encoding="utf-8")
        self.assertEqual(gate(fit.score(cl), "clearance")["state"], "met")

    def test_required_license_is_a_gate_and_a_preferred_one_is_not(self):
        f = fit.score(L(title="Truck Driver", desc=CDL))
        g = gate(f, "cdl")
        self.assertEqual((g["requirement"], g["state"]), ("Class A CDL license", "unknown"))
        nice = JD.replace("Nice to have:\n", "Nice to have:\n- A valid Class A CDL license\n")
        self.assertIsNone(gate(fit.score(L(desc=nice)), "cdl"))
        PROFILE.write_text(PROF.replace("## Experience", "## Certifications\nClass A CDL (Texas)\n## Experience"),
                           encoding="utf-8")
        self.assertEqual(gate(fit.score(L(title="Truck Driver", desc=CDL)), "cdl")["state"], "met")

    def test_exclusions_are_gates_not_score_cuts(self):
        settings.set_pref("work_authorization", "authorized")
        base = fit.score(L())
        settings.set_pref("excluded_companies", "Acme")
        f = fit.score(L())
        self.assertTrue(f["blocked"])
        self.assertEqual(f["score"], base["score"])  # the fit is still the fit
        self.assertEqual(gate(f, "excluded company")["state"], "not_met")
        settings.set_pref("excluded_companies", "")
        settings.set_pref("excluded_title_words", "senior")
        self.assertEqual(gate(fit.score(L()), "excluded title")["state"], "not_met")
        settings.set_pref("excluded_title_words", "")
        f = fit.score(L(desc=JD + " We build gambling products."))
        self.assertEqual(gate(f, "deal-breaker")["state"], "not_met")
        self.assertTrue(f["blocked"])
        self.assertNotIn("dealbreaker", [m["why"] for m in f["mods"]])
        self.assertEqual(f["confidence"], f["known"])

    def test_gates_change_the_fit_revision(self):
        self.assertEqual(fit.config()["version"], 2)  # every stored fit is stale once: the loop rescores it
        self.assertNotIn("blocked_cap", fit.config())
        self.assertFalse({"clearance", "dealbreaker"} & set(fit.config()["modifiers"]))


if __name__ == "__main__":
    unittest.main()
