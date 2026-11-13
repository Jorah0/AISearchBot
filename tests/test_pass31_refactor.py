"""Pass 31: what still contradicted the blueprint after pass 30, and the refactor's one-home helpers. Board keyword
filters match whole words; The Muse is never narrowed to software / IT by an ambiguous word; research text marked
(unverified) never reaches an employer-facing prompt; sponsorship signals no longer move the fit score. No network;
every patched attribute is put back."""
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
from test_pass21_fit import JD, Base, L, patched  # noqa: E402

from lodestar import db, extras, fit, resume, settings  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class Contradictions(Base):
    def test_board_keyword_filters_match_whole_words(self):
        self.assertFalse(wm._has_all(["intern"], "Internal Auditor"))
        self.assertTrue(wm._has_all(["intern"], "Marketing Intern, summer"))
        self.assertFalse(wm._has_all(["nurse"], "Nursery teacher"))
        self.assertTrue(wm._has_all(["engineer"], "Civil Engineers wanted"))  # a plural still counts
        self.assertTrue(wm._has_all(["c++", "developer"], "Senior C++ Developer"))
        self.assertTrue(wm._has_all([], "anything"))
        self.assertTrue(wm._has_all([".net"], "ASP.NET developer"))  # review fix: a word starting with punctuation
        self.assertTrue(wm._has_all(["c#"], "C# engineer"))

    def test_the_muse_is_never_narrowed_by_an_ambiguous_word(self):
        asked = []
        with patched(wm, fetch_json=lambda url, **k: asked.append(url) or {"results": []}):
            for q in ("civil engineer", "security officer", "data entry clerk", "interior designer", "it support",
                      "real estate developer", "business developer"):  # a software sales rep is a Sales job: fine
                wm._muse(q)
            self.assertFalse([u for u in asked if "category=" in u], asked)
            asked.clear()
            wm._muse("software engineer")
            self.assertTrue(all("category=Software" in u for u in asked), asked)

    def test_unverified_research_never_reaches_employer_prompts(self):
        jid = db.add_job("Acme", "Data Engineer", None, JD, "via test")
        d = resume.app_dir(db.get_job(jid))
        (d / "research.md").write_text("Acme makes freight software [S1].\nThey plan to IPO in 2027 (unverified).\n",
                                       encoding="utf-8")
        text = extras.research_for_prompts(db.get_job(jid))
        self.assertIn("freight software", text)
        self.assertNotIn("IPO", text)
        for path in ("lodestar/apply.py", "lodestar/resume.py"):
            src = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
            self.assertNotIn('"research.md").read_text', src.replace("'", '"'), path)  # both read research_for_prompts

    def test_sponsorship_signals_no_longer_move_the_score(self):
        settings.set_pref("work_authorization", "needs_sponsorship")
        plain = fit.score(L(desc=JD + " Some text."))
        yes = fit.score(L(desc=JD + " Visa sponsorship is available."))
        self.assertEqual(plain["score"], yes["score"])
        self.assertIn("offers sponsorship", [c["text"] for c in yes["chips"]] + [g["evidence"] for g in yes["gates"]])
        self.assertEqual(fit.config()["version"], 3)
        self.assertFalse({"sponsor_yes", "sponsor_hint"} & set(fit.config()["modifiers"]))


class Helpers(unittest.TestCase):  # one home per helper (util); the old private names are aliases of these
    def test_write_atomic_retries_a_locked_rename_and_can_be_owner_only(self):
        import os as _os

        from lodestar import util

        p = Path(tempfile.mkdtemp()) / "x.json"
        calls, real = [], _os.replace

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")
            return real(a, b)
        with patched(util.os, replace=flaky):
            util.write_atomic(p, '{"a": 1}')
        self.assertEqual((p.read_text(encoding="utf-8"), len(calls)), ('{"a": 1}', 3))
        with patched(util.os, replace=lambda a, b: (_ for _ in ()).throw(PermissionError("in use"))):
            with self.assertRaises(PermissionError):
                util.write_atomic(p, "{}", tries=2)
        util.write_atomic(p, "{}", private=True)
        self.assertEqual(p.read_text(encoding="utf-8"), "{}")

    def test_small_helpers(self):
        import hashlib
        from datetime import datetime, timezone

        from lodestar import careers, connections, fit, intel, interview, listings, pipeline, util

        self.assertEqual(util.short_hash("x"), hashlib.sha1(b"x").hexdigest()[:12])
        self.assertIs(fit._h, util.short_hash)
        self.assertIs(pipeline._h, util.short_hash)
        self.assertEqual((util.load_json('{"a": 1}', {}), util.load_json("", []), util.load_json("{bad", None)), ({"a": 1}, [], None))
        self.assertIs(interview._load, util.load_json)
        self.assertIs(pipeline._load, util.load_json)
        self.assertTrue(util.word_in("sales", "Sales Manager"))
        self.assertFalse(util.word_in("sales", "Wholesale buyer"))
        self.assertTrue(util.word_in("c++", "Senior C++ developer"))
        self.assertIs(careers._word_in, util.word_in)
        for m in (connections, intel, listings):
            self.assertIs(m._now, db._now)
        aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        want = aware.astimezone().replace(tzinfo=None)
        self.assertEqual(util.utc_to_local("2026-01-02 03:04:05"), want)
        self.assertEqual(util.utc_to_local("2026-01-02T03:04:05Z"), want)
        self.assertEqual(util.utc_to_local(aware), want)


class Domains(unittest.TestCase):  # pass 31 Task 6: one registrable-domain rule for mail trust and company pages
    def test_company_pages_and_mail_read_hosts_the_same_way(self):
        from lodestar import email_monitor, util

        for host, label in (("jobs.ibm.ca", "ibm"), ("careers.sap.de", "sap"), ("hr.bt.uk", "bt"),
                            ("jobs.acme.co.uk", "acme"), ("careers.globex.com", "globex"), ("globex.attacker.net", "attacker")):
            self.assertEqual(util.org_label(host), label, host)
            self.assertEqual(email_monitor.org_label(host), label, host)
            self.assertEqual(extras._registrable(host), label, host)
        self.assertTrue(extras._names_company("jobs.ibm.ca", ["ibm"]))  # IBM's own careers site in Canada
        self.assertFalse(extras._names_company("ibm.jobs-hub.example", ["ibm"]))  # still fail-closed


if __name__ == "__main__":
    unittest.main()
