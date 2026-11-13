"""Pass 22, addendum B: the general login for new site accounts and finishing sign-ups (accounts.py), finding a board
job's posting on the employer's own site (apply_find.py), and the job search fixes (web_monitor: role alternatives,
the place sent to local boards, place matching, the search profile from Preferences / the resume). No network: feeds,
pages, robots.txt and the AI are faked. Every patched attribute is put back."""
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
from test_apply_accounts import PROF, SITE, Base, FakePage, patched  # noqa: E402

from lodestar import accounts, ai, apply_agent, apply_find, db, extras, profile, settings, util  # noqa: E402
from lodestar import web_monitor as wm  # noqa: E402


class AutoPage(FakePage):
    """FakePage where the agent may press Create (accounts_auto_create) and tick boxes; a marketing box too."""

    def inputs(self):
        extra = [{"a": 7, "frame": 0, "type": "checkbox", "hint": "Send me marketing offers and job alerts"}]
        return super().inputs() + (extra if self.state == "signup" else [])

    def tick(self, d):
        assert d["type"] == "checkbox"
        self.ticked = [*getattr(self, "ticked", []), d["a"]]

    def click(self, rx):
        if self.state == "signup" and rx.search("Create Account") and not rx.search("Sign In"):
            self.clicks.append(("signup", "Create Account"))
            self.you_create()
            return True
        return super().click(rx)


class General(Base):
    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: accounts.general()["set"] and accounts.set_general(clear=True))
        old = settings.pref("accounts_auto_create")
        self.addCleanup(settings.set_pref, "accounts_auto_create", old)

    def test_general_login_is_used_for_new_accounts_and_tried_once_on_an_existing_email(self):
        with self.assertRaises(SystemExit):
            accounts.set_general("", "short")
        g = accounts.set_general("", "General-Pass-1!")
        self.assertEqual((g["set"], g["username"], g["auto_create"]), (True, "", False))
        self.assertNotIn("General-Pass-1!", str(accounts.overview()))  # never in what the page reads
        pg = FakePage(hook=lambda p: p.state == "signup" and not p.terms and p.vals.get(4) and p.you_create())
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons, pg.created), ("ok", ["account_create"], ("jane@example.com", "General-Pass-1!")))
        self.assertEqual(self.pw(), "General-Pass-1!")
        accounts.remove(accounts.for_site(SITE)["id"])
        # the site already knows the email: one sign-in try with the general password
        pg = FakePage(exists=True, hook=lambda p: p.state == "signup" and not p.terms and p.vals.get(4) and p.you_create())
        r, hint, _ = self.drive(pg)
        a = accounts.for_site(SITE)
        self.assertEqual((r, a["created_by"], a["status"], pg.typed[-1]), ("ok", "general", "active",
                                                                            ("login", 1, "General-Pass-1!")))
        accounts.remove(a["id"])
        # a wrong one is recorded and never tried again
        pg = FakePage(exists=True, bad=True, hook=lambda p: p.state == "signup" and not p.terms and p.vals.get(4) and p.you_create())
        self.assertEqual(self.drive(pg)[:2], ("yours", accounts.HINT["failed"]))
        self.assertEqual(accounts.for_site(SITE)["status"], "failed")
        accounts.remove(accounts.for_site(SITE)["id"])
        accounts.set_general("jdoe", "General-Pass-2!")  # a username of your own goes into a username field
        self.assertEqual(accounts.general()["username"], "jdoe")
        accounts.set_general(clear=True)
        self.assertFalse(accounts.general()["set"])
        self.assertIsNone(self.store.get((accounts.vault.SERVICE, accounts.GENERAL)))

    def test_finish_signups_only_when_allowed_ticks_only_the_terms_box(self):
        settings.set_pref("accounts_auto_create", True)
        pg = AutoPage()
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons), ("ok", []))  # nothing waited for you
        self.assertEqual(pg.ticked, [5])  # the terms box, never the marketing one
        self.assertIn(("signup", "Create Account"), pg.clicks)
        a = accounts.for_site(SITE)
        self.assertEqual((a["status"], a["created_by"], bool(a["auto_verify"])), ("active", "agent", True))
        self.assertEqual(len(self.pw()), 16)  # no general password: a generated one
        accounts.remove(a["id"])
        settings.set_pref("accounts_auto_create", False)
        pg = AutoPage(hook=lambda p: p.state == "signup" and not p.terms and p.vals.get(4) and p.you_create())
        r, _, reasons = self.drive(pg)
        self.assertEqual((r, reasons, getattr(pg, "ticked", [])), ("ok", ["account_create"], []))  # off: yours


_N = [0]


def job(title="Data Engineer", company="Acme Robotics", url="", jd="", location=""):
    _N[0] += 1  # one job each: add_job hands back the job a URL already has
    jid = db.add_job(company, title, url or f"https://www.linkedin.com/jobs/view/{_N[0]}", jd or "Python")
    if location:
        db.set_fields(jid, location=location)
    return jid


class Find(unittest.TestCase):
    def setUp(self):
        profile.write_master(PROF)
        self.feeds, self.pages = {}, {}
        self.asked = []

        def feed(vendor, slug, company):
            self.asked.append(f"{vendor}:{slug}")
            if (vendor, slug) not in self.feeds:
                raise ValueError("not public")
            return self.feeds[(vendor, slug)]
        for obj, kw in ((wm, {"feed": feed}), (util, {"fetch": lambda u, **k: self.pages[u], "robots_ok": lambda *a: True}),
                        (extras, {"_site_for": lambda j: None})):
            cm = patched(obj, **kw)
            cm.__enter__()
            self.addCleanup(cm.__exit__, None, None, None)

    def jid(self, **kw):
        j = job(**kw)
        self.addCleanup(db.delete_job, j)
        return db.get_job(j)

    def test_the_jobs_own_apply_link_then_the_companys_board_by_title(self):
        j = self.jid(jd="Apply here: https://boards.greenhouse.io/acme/jobs/4012345. Questions: https://www.linkedin.com/x")
        self.assertEqual(apply_find.find(j)["url"], "https://boards.greenhouse.io/acme/jobs/4012345")
        self.assertEqual(self.asked, [])
        L = lambda t, u, loc="": {"title": t, "url": u, "location": loc}  # noqa: E731
        self.feeds[("lever", "acme-robotics")] = [L("Senior Data Engineer", "https://jobs.lever.co/acme-robotics/a"),
                                                  L("Data Engineer", "https://jobs.lever.co/acme-robotics/b")]
        r = apply_find.find(self.jid())
        self.assertEqual((r["url"], r["how"]), ("https://jobs.lever.co/acme-robotics/b", "the company's lever board"))
        self.assertIn("greenhouse:acmerobotics", r["tried"])
        # the same title twice: the job's city decides; no city, no guess
        self.feeds[("lever", "acme-robotics")] = [L("Data Engineer", "https://jobs.lever.co/acme-robotics/b", "Boston, MA"),
                                                  L("Data Engineer", "https://jobs.lever.co/acme-robotics/c", "Austin, TX")]
        self.assertEqual(apply_find.find(self.jid(location="Austin, Texas"))["url"], "https://jobs.lever.co/acme-robotics/c")
        self.assertIsNone(apply_find.find(self.jid())["url"])

    def test_the_company_website_and_the_ai_picks_only_from_its_own_links(self):
        home = "https://acmerobotics.example/"
        self.pages[home] = ('<a href="/about">About</a><a href="/life">Life at Acme</a>'
                            '<a href="https://www.linkedin.com/company/acme">LinkedIn</a>')
        self.pages["https://acmerobotics.example/life"] = '<a href="https://jobs.lever.co/acmebots">See open roles</a>'
        self.feeds[("lever", "acmebots")] = [{"title": "Data Engineer", "url": "https://jobs.lever.co/acmebots/z", "location": ""}]
        prompts = []

        def pick(prompt, **kw):
            prompts.append(prompt)
            return {"index": 1}
        with patched(extras, _site_for=lambda j: {"url": home, "label": "you"}), patched(ai, ask_json=pick):
            r = apply_find.find(self.jid())
            self.assertEqual((r["url"], r["how"]), ("https://jobs.lever.co/acmebots/z",
                                                     "the board the company's careers page links"))
            self.assertIn("untrusted page text", prompts[0])
            with patched(ai, ask_json=lambda p, **k: {"index": 99}):  # an index off the list is nothing
                self.assertIsNone(apply_find.find(self.jid())["url"])
            self.assertIsNone(apply_find.find(self.jid(), ai=False)["url"])
        with patched(apply_find, MAX_REQUESTS=2):
            self.assertIn("stopped after 2 requests", apply_find.find(self.jid())["tried"])

    def test_queueing_a_board_job_saves_the_found_link_or_says_where_it_looked(self):
        self.feeds[("greenhouse", "acmerobotics")] = [{"title": "Data Engineer", "location": "",
                                                       "url": "https://boards.greenhouse.io/acmerobotics/jobs/9"}]
        j = self.jid()
        r = apply_agent.enqueue([j["id"]], "stop", start=False)[0]
        self.assertIn("run_id", r)
        self.addCleanup(lambda: db.con().execute("DELETE FROM apply_runs WHERE job_id=?", (j["id"],)) and db.con().commit())
        self.assertEqual(db.get_job(j["id"])["apply_url"], "https://boards.greenhouse.io/acmerobotics/jobs/9")
        self.assertIn("check it is this job", db.get_run(r["run_id"])["step"])
        r = apply_agent.enqueue([self.jid(company="Nobody Corp")["id"]], "stop", start=False)[0]
        self.assertIn("does not allow bots", r["error"])
        self.assertIn("looked for it on the employer's own site", r["error"])


class Search(unittest.TestCase):
    def test_roles_are_searched_one_by_one_and_local_boards_get_the_place(self):
        self.assertEqual(wm.alternatives("Data Engineer, analytics engineer or BI Developer; x"),
                         ["Data Engineer", "analytics engineer", "BI Developer"])
        asked = []

        def board(q):
            asked.append(q)
            return [wm._listing(f"{q} role", "Co", f"https://co.example/{len(asked)}", "Austin, TX", source="fake")]
        with patched(wm, SOURCES={"fake": board}):
            wm._ANSWERS.clear()
            got = wm.search("data engineer, analytics engineer", sources=["fake"])
        self.assertEqual((asked, len(got)), (["data engineer", "analytics engineer"], 2))  # a comma matched nothing before
        urls = []
        old_id, old_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
        os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"] = "id", "key"
        try:
            # SOURCES pinned: an earlier module may leave it patched
            with patched(wm, fetch_json=lambda u, **k: urls.append(u) or {"results": []},
                         SOURCES={"adzuna": wm._adzuna, "usajobs": wm._usajobs}):
                wm._ANSWERS.clear()
                wm.search("data engineer", sources=["adzuna", "usajobs"], location="Austin, TX or remote")
        finally:
            for k, v in (("ADZUNA_APP_ID", old_id), ("ADZUNA_APP_KEY", old_key)):
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            db.quota_refund("adzuna")
        self.assertIn("&where=Austin%2C%20TX&distance=40", urls[0])
        self.assertIn("&LocationName=Austin%2C%20TX", urls[1])

    def test_place_matching_codes_cities_and_or_remote(self):
        for place, where, ok in (("Austin, TX", "Austin, Texas, United States", True), ("TX", "Dallas, TX", True),
                                 ("Portland, OR", "Portland, ME", False), ("Portland, OR", "Portland, Oregon", True),
                                 ("NYC", "New York, NY", True), ("Austin, TX", "Boston, MA", False),
                                 ("United States", "Remote - US", True)):
            self.assertEqual(wm.place_ok(place, where), ok, (place, where))
        self.assertEqual(wm._loc_alts("Portland, OR"), ["Portland, OR"])  # a state code is no 'or'
        L = [dict(title="Data Engineer", company=c, url=c, location=loc, salary="", date="", desc="", source=s)
             for c, loc, s in (("A", "Austin, Texas", "x"), ("B", "Remote", "remotive"), ("C", "Boston, MA", "x"),
                               ("D", "", "x"))]
        pick = lambda loc: [j["company"] for j in wm.refine([dict(x) for x in L], location=loc)]  # noqa: E731
        self.assertEqual(pick("Austin, TX or remote"), ["A", "B", "D"])
        self.assertEqual(pick("remote"), ["B", "D"])
        self.assertEqual(pick("Austin, TX"), ["A", "D"])  # D says nothing: kept, marked unknown

    def test_the_search_profile_comes_from_preferences_else_the_resume_and_saves_to_preferences(self):
        profile.write_master(PROF)
        d = wm.defaults()
        self.assertEqual((d["roles"], d["roles_from"], d["location"], d["location_from"]),
                         (["Senior Data Engineer"], "your resume", "Austin, TX", "your profile"))
        profile.set_pref_fields({"Target roles": "Data Engineer, Analytics Engineer", "Locations / remote": "Austin, TX, Remote"})
        d = wm.defaults()
        self.assertEqual((d["query"], d["roles_from"], d["location"]),
                         ("Data Engineer, Analytics Engineer", "Preferences", "Austin, TX or Remote"))
        self.assertIn("Salary floor: $123,456", profile.preferences_text())  # the other values stay
        profile.set_pref_fields({"Target roles": "ML Engineer | x"})
        self.assertEqual(profile.pref_field("Target roles"), "ML Engineer , x")  # a '|' never splits the line
        self.assertEqual(profile.master_text().count("Target roles:"), 1)


if __name__ == "__main__":
    unittest.main()
