"""Interview readiness and sourced practice questions (pass 18): the mock's source chip under every question (the company
page link opens in a new tab), the Focus select, the score card's question line, the readiness line after a card and
its link; the drawer's Interview readiness group (score, chance band and its 'not a probability' label, part bars,
Raise it buttons, Explain / What next), the Question sources panel (website, paste box with its notice, Refresh with
pages read / robots-skipped and dropped AI questions, Delete, stale note) and the Questions list; the Today readiness
chip and tip; the Insights 'Readiness vs results' block; text from pastes stays text; all of it at 420px."""
import io
import os
import re
import unittest
import urllib.error

from harness import E2ETestCase, day, db, extras, interview, util

WORDS = " ".join(["Our hiring team values clear thinking."] * 30)
PAGES = {  # the company's own site: robots.txt keeps /values out; a 404 for everything else on it
    "https://careers.cobaltfreight.example/robots.txt": "User-agent: *\nDisallow: /values\n",
    "https://careers.cobaltfreight.example/": ('<title>Cobalt careers</title><a href="/how-we-hire">How we hire</a> '
                                               '<a href="/values">Our values</a>'),
    "https://careers.cobaltfreight.example/how-we-hire": (
        "<title>How we hire</title><p>Every interview is behavioral. We ask every candidate to describe how they handled "
        f"a disagreement with a teammate. {WORDS}</p>"),
}
GOOD_Q = "Describe a disagreement with a teammate and how you resolved it."
AI = {  # the set build (one valid company question, two the code drops) and the score card's rubric
    "questions": [
        {"q": GOOD_Q, "source": "company", "block": "C1", "quote": "describe how they handled a disagreement with a teammate",
         "competency": "conflict"},
        {"q": "Tell me about your favourite freight lane.", "source": "company", "block": "C1",
         "quote": "we only hire astronauts from the moon", "competency": "technical"},
        {"q": "Tell me about a time you led a migration.", "source": "logged", "block": None, "quote": "x"}],
    "situation": 2, "task": 1, "action": 2, "result": 2, "relevance": 2, "specificity": 1, "metrics_used": True,
    "one_fix": "Lead with the number.", "suggested_rewrite": "I cut costs 40%."}
EVIL = "<img src=x onerror=alert(1)>"


class Interview(E2ETestCase):
    ai_json = AI

    @classmethod
    def _fakes(cls):
        super()._fakes()
        cls.page_urls, prev = [], util.fetch

        def fetch(url, timeout=25, headers=None, max_bytes=None, follow=True):
            if "cobaltfreight.example" not in url:
                return prev(url, timeout, headers, max_bytes)
            cls.urls.append(url)
            cls.page_urls.append(url)
            if url in PAGES:
                return PAGES[url]
            raise urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO(b""))

        cls._swap(prev, fetch)
        cls._patch(extras, "PAGE_PAUSE", 0)
        old = os.environ.get("LODESTAR_ALLOW_PRIVATE_URLS")  # the typed website is checked without a DNS lookup
        os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = "1"
        cls.addClassCleanup(lambda: os.environ.pop("LODESTAR_ALLOW_PRIVATE_URLS", None) if old is None
                            else os.environ.__setitem__("LODESTAR_ALLOW_PRIVATE_URLS", old))

    def ready(self):
        return self.page.locator("#jReady")

    def send(self, text):
        self.page.fill("#cIn", text)
        self.page.press("#cIn", "Enter")
        self.idle()

    def mock_for(self, jid):
        self.page.evaluate("closeDrawer()")  # at 420px the open drawer covers the nav
        self.go("coach")
        self.page.select_option("#cMode", "mock")
        self.page.select_option("#cJob", str(jid))

    # --- Coach > Mock interview
    def test_mock_source_chips_focus_card_and_readiness_line(self):
        jid = self.ids["interview"]
        self.go("coach")
        self.assertFalse(self.page.is_visible("#cFocus"))
        self.mock_for(jid)
        self.assertTrue(self.page.is_visible("#cFocus"))
        self.assertEqual(self.page.eval_on_selector_all("#cFocus option", "o => o.map(x => x.value)"), ["", *interview.QCOMP])
        self.send("Ready when you are")
        last = self.page.evaluate("MOCK.last")
        self.assertTrue(last["key"] and last["source"] in interview.RANK, last)
        chip = self.page.locator("#chat .msg-src").last
        self.assertIn("question source:", chip.text_content())
        self.assertEqual(chip.locator(".src").text_content().replace(" ⓘ", ""), last["chip"])
        self.assertEqual(chip.locator(".src").get_attribute("title"), last["label"])
        self.assertEqual(self.page.locator("#chat .mcard").count(), 0)  # the first message is not an answer
        # an answer: the card names the question's source (looked up by the server from qkey); the readiness line
        calls = len(self.ai_calls)
        self.send("At Tidewater I rebuilt the freight ETL and cut runtime from 6 hours to 50 minutes.")
        self.assertGreater(len(self.ai_calls), calls)
        card = self.page.locator("#chat .mcard").last.text_content()
        names = {"logged": "you logged it", "pasted": "your pasted notes", "company": "the company's own page",
                 "jd": "the job description", "reported": "reported, unverified", "general": "general question"}
        self.assertIn(f"question: {names[last['source']]} · {last['competency']}", card)
        sess = db.con().execute("SELECT answers FROM mock_sessions WHERE job_id=? ORDER BY id DESC", (jid,)).fetchone()
        self.assertIn(f'"qkey": "{last["key"]}"', sess["answers"])
        line = self.page.text_content("#mockReady")
        self.assertRegex(line, rf"Readiness for #{jid} Orchid Health: \d+ · chance estimate (Low|Fair|Good|Strong) \(not a probability\)")
        self.assertNotRegex(line, r"\d\s*%")
        self.assertIn(f"practised: {last['competency']}", self.page.text_content("#mockSum"))
        second = self.page.evaluate("MOCK.last")
        self.assertNotEqual(second["key"], last["key"])  # asked keys go back: never the same question twice
        # Focus: the next question is on that competency
        self.page.select_option("#cFocus", "conflict")
        self.send("I owned the cut-over and wrote the runbook.")
        self.assertEqual(self.page.evaluate("MOCK.last.competency"), "conflict")
        self.assertRegex(self.page.text_content("#mockReady"), r": \d+( -> \d+)? · chance estimate")
        self.assertEqual(self.page.locator("#chat .msg-src").count(), 3)
        # see why: the drawer's readiness group
        self.page.click("#mockReady a")
        self.page.wait_for_selector("#drawer.open #jReady")
        self.idle()
        self.assertIn("Interview readiness", self.ready().text_content())
        # a new mock starts clean
        self.go("coach")
        self.page.select_option("#cMode", "coach")
        self.assertFalse(self.page.is_visible("#cFocus") or self.page.is_visible("#mockReady"))
        self.assertEqual(self.page.evaluate("MOCK.asked.length"), 0)

    # --- the drawer's Interview readiness group
    def test_drawer_readiness_bars_band_raise_and_explain(self):
        jid = self.ids["interview"]
        self.open_job(jid)
        self.idle()
        r = self.api(f"/api/jobs/{jid}")["readiness"]
        g = self.ready()
        text = g.text_content()
        self.assertIn(f"{r['score']}/100", text)
        self.assertIn("Readiness (preparation)", text)
        self.assertIn(f"Chance estimate: {r['chance']['band'].capitalize()}, not a probability", self.page.text_content("#jBand"))
        self.assertEqual(self.page.text_content("#jChance").strip(), r["chance"]["label"])
        self.assertIn("not a probability", r["chance"]["label"])
        self.assertNotRegex(text.replace("100 pts", ""), r"chance[^.]*\d\s*%")
        self.assertIn("fit not scored yet", text)
        self.assertIn(r["stage"], text)
        meters = g.locator("meter")
        self.assertEqual(meters.count(), 5)
        for i, (k, p) in enumerate(r["parts"].items()):
            self.assertEqual(meters.nth(i).get_attribute("value"), str(p["s"]))
            self.assertRegex(meters.nth(i).get_attribute("aria-label"), rf": {p['s']} of 100$")  # the number, not only a bar
            for c in p["chips"]:
                self.assertIn(c, text)
        prep = r["parts"]["prep"]  # its points always have a positive reason (the company's own questions on file too)
        self.assertTrue(prep["s"] == 0 or any(c.startswith("+") for c in prep["chips"]), prep)
        rows = g.locator(".raise")
        self.assertEqual(rows.count(), len(r["raise"]))
        for i, x in enumerate(r["raise"]):
            self.assertIn(f"+{x['gain']}", rows.nth(i).text_content())
            self.assertIn(x["text"], rows.nth(i).text_content())
        # What should I practise next? (no AI) and Explain my readiness (one AI call, no fit data, advice only)
        calls = len(self.ai_calls)
        g.get_by_role("button", name="What should I practise next?").click()
        self.assertEqual(self.page.text_content("#jReadyOut"), f"{r['raise'][0]['text']} (+{r['raise'][0]['gain']} points).")
        self.assertEqual(len(self.ai_calls), calls)
        self.run_click(g.get_by_role("button", name="Explain my readiness"))
        self.assertEqual(self.page.text_content("#jReadyOut"), self.ai_text)
        prompt = self.ai_calls[-1]["messages"][-1]["content"]
        self.assertIn("kind=readiness", prompt)
        self.assertNotIn("fit", prompt.lower().replace("specificity", ""))
        # Raise it > Practise: Coach, Mock interview for this job, on that competency
        i = next(i for i, x in enumerate(r["raise"]) if x["action"]["do"] == "practise")
        rows.nth(i).get_by_role("button", name="Practise").click()
        self.page.wait_for_selector("section#coach.on")
        self.assertEqual((self.page.input_value("#cMode"), self.page.input_value("#cJob"), self.page.input_value("#cFocus")),
                         ("mock", str(jid), r["raise"][i]["action"].get("focus", "")))
        # the other raise actions (a row shows them when they add the most points)
        self.open_job(jid)
        self.idle()
        self.page.evaluate("raiseAct({do: 'stories', tag: 'conflict'})")
        self.page.wait_for_selector("section#answers.on")
        self.assertEqual(self.page.eval_on_selector_all("#stComps input:checked", "c => c.map(x => x.value)"), ["conflict"])
        self.open_job(jid)
        self.idle()
        calls = len(self.ai_calls)
        self.page.evaluate("raiseAct({do: 'prep'}, document.querySelector('#jReady button'))")
        self.idle()
        self.assertGreater(len(self.ai_calls), calls)  # the prep pack (the pipeline's prep step, or the drawer action)
        self.assertIn("interview_prep.md", self.api(f"/api/jobs/{jid}")["docs"])

    def test_readiness_group_only_where_interviews_happen(self):
        self.open_job(self.ids["saved"])  # saved, no round, no mock: nothing to prepare for yet
        self.idle()
        self.assertEqual(self.ready().count(), 0)
        self.open_job(self.ids["offer"])
        self.idle()
        self.assertEqual(self.ready().count(), 1)

    # --- Question sources and the Questions list
    def test_question_sources_site_paste_refresh_delete(self):
        self.allow_console()
        jid, co = self.ids["screening"], "Cobalt Freight"
        self.open_job(jid)
        self.idle()
        self.assertIn("You logged 0 · You pasted 0 notes (0 questions)", self.page.text_content("#jQcounts"))
        self.assertIn("Add the company website to read its hiring pages.", self.page.text_content("#jQsrc"))
        # the website: a job board / NEVER_FETCH host is refused, the company's own site is kept
        self.page.fill("#qsSite", "https://www.linkedin.com/company/cobalt")
        self.page.locator("#jQsrc").get_by_role("button", name="Save website").click()
        self.expect_toast("error", "err")
        self.page.fill("#qsSite", "careers.cobaltfreight.example")
        self.page.locator("#jQsrc").get_by_role("button", name="Save website").click()
        self.expect_toast("company website saved: https://careers.cobaltfreight.example/", "ok")
        self.idle()
        self.assertIn("typed by you", self.page.text_content("#jQsrc"))
        self.assertIn("Pages not read yet: Refresh reads them.", self.page.text_content("#jQsrc"))
        self.assertEqual(self.page_urls, [])  # saving the website reads nothing
        # Paste what you read: the notice, the label cleaned, the text kept as text, the link never opened
        self.page.click("#qsPaste summary")
        self.assertIn("Lodestar never opens Glassdoor, Blind, LinkedIn or Indeed pages", self.page.text_content("#qsPaste"))
        self.page.locator("#jQsrc").get_by_role("button", name="Save pasted notes").click()
        self.expect_toast("fill in where it is from and the text", "err")
        self.page.fill("#qsLabel", f"Glassdoor reviews {EVIL}")
        self.page.fill("#qsUrl", "https://www.glassdoor.com/Interview/cobalt")
        self.page.fill("#qsText", f"They asked: Tell me about a time you failed {EVIL}?\nWhy did they ghost me?\n"
                                  "Why do you want to leave your current job?")
        self.page.locator("#jQsrc").get_by_role("button", name="Save pasted notes").click()
        self.expect_toast("pasted notes saved", "ok")
        self.idle()
        self.assertIn("You pasted 1 note (2 questions)", self.page.text_content("#jQcounts"))
        paste = self.page.locator("#jQsrc .qpaste")
        self.assertIn("Glassdoor reviews img srcx onerroralert(1)", paste.text_content())  # cleaned when stored
        self.assertIn(EVIL, paste.text_content())  # the pasted text: shown as text
        self.assertEqual(self.page.locator("#drawer img").count(), 0)
        link = paste.locator("a")
        self.assertEqual((link.get_attribute("target"), link.get_attribute("rel")), ("_blank", "noopener noreferrer"))
        # Refresh: the company's pages (robots.txt honoured) and one AI build whose tags the code checks
        calls = len(self.ai_calls)
        self.run_click(self.page.locator("#jQsrc").get_by_role("button", name="Refresh"))
        self.expect_toast("question set built: 2 AI questions dropped", "ok")
        self.idle()
        self.assertEqual(len(self.ai_calls), calls + 1)
        self.assertFalse([u for u in self.urls if "glassdoor" in u])
        self.assertIn("https://careers.cobaltfreight.example/how-we-hire", self.page_urls)
        self.assertNotIn("https://careers.cobaltfreight.example/values", self.page_urls)
        self.assertLessEqual(len(self.page_urls), 12)
        src = self.page.locator("#jQsrc")
        page = src.get_by_role("link", name="How we hire ↗")
        self.assertEqual((page.get_attribute("href"), page.get_attribute("target"), page.get_attribute("rel")),
                         ("https://careers.cobaltfreight.example/how-we-hire", "_blank", "noopener noreferrer"))
        self.assertIn("skipped: robots.txt disallows", src.text_content())
        self.assertIn(f"{co} pages 1 (1 question)", self.page.text_content("#jQcounts"))
        self.assertIn("last AI build", self.page.text_content("#jQbuilt"))
        self.assertNotIn("sources changed", self.page.text_content("#jQbuilt"))
        self.page.click("#jQdropped")
        self.assertIn("quote not found in the source", src.text_content())
        self.assertIn("the AI may only tag pasted, company, jd or reported", src.text_content())
        # Questions (N): grouped by competency with counts (never percentages); each with its source chip
        self.page.click("#jQs summary")
        qs = self.page.locator("#jQs")
        self.assertRegex(self.page.text_content("#jQs summary"), r"Questions \(\d+\)")
        item = qs.locator("li", has_text=GOOD_Q)
        self.assertEqual(item.locator(".src").text_content(), f"{co} page")
        self.assertIn("Based on Cobalt Freight's own page How we hire", item.locator(".src").get_attribute("title"))
        a = item.locator("a")
        self.assertEqual((a.get_attribute("target"), a.get_attribute("rel")), ("_blank", "noopener noreferrer"))
        self.assertRegex(qs.locator(".qgroup", has_text=GOOD_Q).locator("b + .muted").text_content(), r"· \d+ mentions? in Cobalt Freight's material")
        self.assertNotIn("%", qs.text_content())
        self.assertIn(EVIL, qs.text_content())  # a pasted question with markup: text, never an element
        self.assertEqual(self.page.locator("#drawer img").count(), 0)
        self.assertNotIn("Why did they ghost me", qs.text_content())  # reviewer prose is not an interview question
        # the mock picks the company's own question on its competency; its chip links to the page
        self.mock_for(jid)
        self.page.select_option("#cFocus", "conflict")
        self.send("Ready")
        chip = self.page.locator("#chat .msg-src").last
        self.assertEqual(self.page.evaluate("MOCK.last.q"), GOOD_Q)
        self.assertEqual(chip.locator(".src").text_content(), f"{co} page")
        a = chip.locator("a")
        self.assertEqual((a.get_attribute("href"), a.get_attribute("target"), a.get_attribute("rel")),
                         ("https://careers.cobaltfreight.example/how-we-hire", "_blank", "noopener noreferrer"))
        # Delete the paste: its questions go, the set reads stale until the next Refresh
        self.open_job(jid)
        self.idle()
        self.answer(True)
        self.page.locator("#jQsrc .qpaste").get_by_role("button", name=re.compile("Delete")).click()
        self.expect_toast("pasted notes deleted", "ok")
        self.idle()
        self.assertIn("You pasted 0 notes (0 questions)", self.page.text_content("#jQcounts"))
        self.assertIn("sources changed since the last AI build", self.page.text_content("#jQbuilt"))
        self.assertEqual(interview.sources(db.get_job(jid))["pastes"], [])

    # --- Today and Insights
    def test_today_readiness_chip_tip_and_insights_record(self):
        jid = self.ids["applied"]
        rid = interview.log_round(jid, kind="phone", at=day(1) + " 11:00", interviewers="Sam Okafor")
        self.addCleanup(interview.delete_round, rid)
        self.reload_state()
        it = next(i for i in self.state()["today"]["interviews"] if i["id"] == jid)
        r = it["readiness"]
        btn = self.page.locator("#today button", has_text=f"#{jid} Bluefin Labs")
        self.assertRegex(btn.text_content(), rf"^interview .+ · readiness {r['score']} · #{jid} Bluefin Labs")
        self.assertNotIn("chance", self.page.text_content("#today").lower())  # no band on Today: no room for its qualifier
        self.assertLess(r["score"], 60)
        tip = self.page.locator("#today button.tip", has_text=r["tip"])
        self.assertEqual(tip.count(), 1)
        tip.click()
        act = r["action"]
        if act["do"] == "practise":
            self.page.wait_for_selector("section#coach.on")
            self.assertEqual((self.page.input_value("#cJob"), self.page.input_value("#cFocus")), (str(jid), act.get("focus", "")))
        else:
            self.idle()
        # Insights: your record as counts per band, the caveat, never a percentage
        self.go("insights")
        c = self.api("/api/readiness/calibration")
        box = self.page.text_content("#insReady")
        self.assertIn(c["state"], box)
        self.assertIn(c["caveat"], box)
        for b in ("low (0-39)", "fair (40-59)", "good (60-79)", "strong (80-100)"):
            self.assertIn(b, box)
        self.assertEqual(self.page.locator("#insReady tbody tr").count(), 4)
        self.assertNotIn("%", box)
        self.assertIn("not a probability", self.page.text_content("#readyPanel"))

    # --- 420px
    def test_narrow_window_420(self):
        self.set_viewport(420)
        self.settle()
        self.open_job(self.ids["interview"])
        self.idle()
        self.page.click("#qsPaste summary")
        self.page.click("#jQs summary")
        self.assertTrue(self.page.is_visible("#jReady meter"))
        self.assertEqual(self.overflow(), [])
        self.mock_for(self.ids["interview"])
        self.send("Ready")
        self.assertEqual(self.overflow(), [])
        self.go("insights")
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
