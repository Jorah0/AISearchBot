"""Is this listing a new job? (pass 55): a near copy at the same company goes to one light AI call; 'same' joins the
older posting's job (auto_track then skips it), 'repost' is dated, 'new' goes on; verdicts are cached by fingerprint,
capped daily, and with no AI a resembling listing stays new and is marked unchecked (never hidden). No network."""
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

from lodestar import ai, db, listings, novelty, settings  # noqa: E402

JD = "Build dashboards in SQL and Tableau for store operations; partner with finance; clean messy data weekly."


def L(title, url, company="Wrenfield Bakery", location="Austin, TX"):
    return {"title": title, "company": company, "url": url, "location": location, "desc": JD, "source": "test"}


class Novelty(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.addCleanup(lambda: (db._local.con.close(), setattr(db._local, "con", self._con)))
        st = settings.load()
        self.addCleanup(settings.save, st)
        self.calls = []

    def fake(self, verdict, older=0, why="same req id"):
        def f(prompt, *a, **k):
            self.calls.append(prompt)
            return {"verdict": verdict, "older": older, "why": why}
        return patched(ai, available=lambda: ["anthropic"], ask_json_light=f)

    def age(self, key, when="2026-11-01 10:00:00"):
        db.con().execute("UPDATE postings SET first_seen=? WHERE key=?", (when, key))
        db.con().commit()

    def row(self, key):
        return db.con().execute("SELECT * FROM postings WHERE key=?", (key,)).fetchone()

    def test_similarity_spells_out_abbreviations(self):
        self.assertGreaterEqual(novelty.similarity("Sr. Data Analyst II", "Senior Data Analyst 2"), 0.99)
        self.assertLess(novelty.similarity("Data Analyst", "Pastry Chef"), 0.2)

    def test_no_similar_listing_is_new_by_rules_with_no_ai_call(self):
        k = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        with self.fake("same"):
            r = novelty.judge([k])
        self.assertEqual((r["new"], r["ai"]), (1, 0))
        self.assertEqual((self.row(k)["novelty"], self.row(k)["novelty_by"]), ("new", "rules"))
        self.assertEqual(self.calls, [])

    def test_same_joins_the_older_job_and_auto_track_skips_it(self):
        old = listings.store([L("Senior Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old)
        jid = db.add_job("Wrenfield Bakery", "Senior Data Analyst", "https://jobs.wrenfield.example/1", JD, "test")
        db.con().execute("UPDATE postings SET job_id=? WHERE key=?", (jid, old))
        db.con().commit()
        new = listings.store([L("Senior Data Analyst - Store Ops", "https://boards.example.org/wrenfield/9", location="Austin area")])[0]["key"]  # rules: a different key
        with self.fake("same"):
            r = novelty.judge([new])
            again = novelty.judge([new])  # judged once
        self.assertEqual((r["same"], r["ai"], again["judged"]), (1, 1, 0))
        row = self.row(new)
        self.assertEqual((row["novelty"], row["novelty_of"], row["novelty_by"], row["job_id"]), ("same", old, "ai", jid))
        self.assertIn("posting_seen_again", [e["kind"] for e in db.events(jid)])
        self.assertIn("<<<", self.calls[0])  # both postings fenced
        from lodestar import apply

        listing = {"title": "Senior Data Analyst - Store Ops", "company": "Wrenfield Bakery", "key": new, "url": "https://boards.example.org/wrenfield/9", "desc": JD}
        with self.fake("same"), patched(settings, enabled=lambda tool: True):
            apply.auto_track([listing])
        self.assertIn("another copy of job", listing.get("why", ""))

    def test_a_same_copy_of_an_untracked_listing_is_not_offered_again(self):  # review: only job copies were skipped
        old = listings.store([L("Senior Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old)
        db.con().execute("UPDATE postings SET dismissed=1 WHERE key=?", (old,))
        db.con().commit()
        new = listings.store([L("Senior Data Analyst - Store Ops", "https://boards.example.org/wrenfield/9")])[0]["key"]
        with self.fake("same"):
            novelty.judge([new])
        self.assertEqual(self.row(new)["dismissed"], 1)  # you dismissed it once: its copy too
        from lodestar import apply

        listing = {"title": "Senior Data Analyst - Store Ops", "company": "Wrenfield Bakery", "key": new,
                   "url": "https://boards.example.org/wrenfield/9", "desc": JD}
        with self.fake("same"), patched(settings, enabled=lambda tool: True):
            apply.auto_track([listing])
        self.assertIn("another copy", listing.get("why", ""))

    def test_copies_stored_in_the_same_second_are_compared(self):  # review: first_seen has 1 s resolution
        a = listings.store([L("Senior Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        b = listings.store([L("Sr. Data Analyst II", "https://boards.example.org/wrenfield/9")])[0]["key"]
        self.age(a, "2026-11-10 10:00:00")
        self.age(b, "2026-11-10 10:00:00")
        with self.fake("same"):
            novelty.judge([a, b])
        self.assertEqual(sorted((self.row(a)["novelty"], self.row(b)["novelty"])), ["new", "same"])

    def test_unchecked_listings_are_judged_once_ai_is_back(self):  # review: 'unchecked' was final
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old, "2026-11-10 10:00:00")
        k = listings.store([L("Data Analyst II", "https://jobs.wrenfield.example/2")])[0]["key"]
        settings.set_pref("ai_novelty", False)
        novelty.judge()
        self.assertEqual(self.row(k)["novelty_by"], "unchecked")
        settings.set_pref("ai_novelty", True)
        with self.fake("same"):
            novelty.judge()
        self.assertEqual((self.row(k)["novelty"], self.row(k)["novelty_by"]), ("same", "ai"))

    def test_a_repost_of_a_tracked_job_is_not_offered_again(self):  # 2nd review: only 'same' joined the job
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old, "2026-10-01 10:00:00")
        jid = db.add_job("Wrenfield Bakery", "Data Analyst", "https://jobs.wrenfield.example/1", JD, "test")
        db.con().execute("UPDATE postings SET job_id=? WHERE key=?", (jid, old))
        db.con().commit()
        k = listings.store([L("Data Analyst (Stores)", "https://jobs.wrenfield.example/2")])[0]["key"]
        with self.fake("repost"):
            novelty.judge([k])
        from lodestar import apply

        listing = {"title": "Data Analyst (Stores)", "company": "Wrenfield Bakery", "key": k,
                   "url": "https://jobs.wrenfield.example/2", "desc": JD}
        with self.fake("repost"), patched(settings, enabled=lambda tool: True):
            apply.auto_track([listing])
        self.assertIn(f"a repost of job #{jid}", listing.get("why", ""))

    def test_a_failed_answer_is_not_retried_every_cycle(self):  # 2nd review: retries drained the daily cap
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old, "2026-11-10 10:00:00")
        k = listings.store([L("Data Analyst II", "https://jobs.wrenfield.example/2")])[0]["key"]

        def broken(*a, **kw):
            self.calls.append(1)
            raise ValueError("not JSON")
        with patched(ai, available=lambda: ["anthropic"], ask_json_light=broken):
            novelty.judge()
            novelty.judge()
        self.assertEqual((self.row(k)["novelty_by"], len(self.calls)), ("unchecked", 1))

    def test_repost_is_dated_and_new_goes_on(self):
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old)
        k = listings.store([L("Data Analyst (Stores)", "https://jobs.wrenfield.example/2")])[0]["key"]
        with self.fake("repost"):
            novelty.judge([k])
        self.assertEqual(self.row(k)["novelty"], "repost")
        self.assertTrue(self.row(k)["reposted_at"])
        k2 = listings.store([L("Data Analyst, Payroll", "https://jobs.wrenfield.example/3")])[0]["key"]
        with self.fake("new", why="a different team"):
            novelty.judge([k2])
        self.assertEqual((self.row(k2)["novelty"], self.row(k2)["novelty_why"]), ("new", "a different team"))

    def test_without_ai_or_past_the_cap_it_stays_new_unchecked(self):
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old)
        k = listings.store([L("Data Analyst II", "https://jobs.wrenfield.example/2")])[0]["key"]
        settings.set_pref("ai_novelty", False)
        novelty.judge([k])
        self.assertEqual((self.row(k)["novelty"], self.row(k)["novelty_by"]), ("new", "unchecked"))
        settings.set_pref("ai_novelty", True)
        db.con().execute("UPDATE postings SET novelty=NULL WHERE key=?", (k,))
        db.con().execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (f"quota:novelty:{__import__('datetime').date.today():%Y%m%d}", novelty.NOVELTY_DAILY))
        db.con().commit()
        with self.fake("same"):
            novelty.judge([k])
        self.assertEqual((self.row(k)["novelty_by"], self.calls), ("unchecked", []))

    def test_evidence_overrides_a_wrong_same_or_repost(self):
        old = listings.store([dict(L("Data Analyst", "https://jobs.wrenfield.example/1"), desc=JD + " Req 4471.")])[0]["key"]
        self.age(old)
        far = listings.store([L("Data Analyst - Payroll", "https://jobs.wrenfield.example/2", location="Dallas, TX")])[0]["key"]
        req = listings.store([dict(L("Data Analyst (Stores)", "https://jobs.wrenfield.example/3"), desc=JD + " Req 5120.")])[0]["key"]
        with self.fake("repost"):
            novelty.judge([far, req])
        self.assertEqual(self.row(far)["novelty"], "new")
        self.assertIn("miles apart", self.row(far)["novelty_why"])
        self.assertEqual(self.row(req)["novelty"], "new")
        self.assertIn("different requisition numbers", self.row(req)["novelty_why"])

    def test_a_bad_answer_never_hides_a_listing(self):
        old = listings.store([L("Data Analyst", "https://jobs.wrenfield.example/1")])[0]["key"]
        self.age(old)
        k = listings.store([L("Data Analyst II", "https://jobs.wrenfield.example/2")])[0]["key"]
        with self.fake("maybe"):
            novelty.judge([k])
        self.assertEqual((self.row(k)["novelty"], self.row(k)["novelty_by"]), ("new", "unchecked"))
        self.assertIn("not checked by AI", self.row(k)["novelty_why"])


if __name__ == "__main__":
    unittest.main()
