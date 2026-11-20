"""Board: Add job, cards and chips, filter bar, sort, table view, bulk actions, drag and drop, keyboard, 420px."""
import unittest

from harness import E2ETestCase, db

ADD = "button:text-is(\"Add job\")"
CARD_IDS = "s => [...document.querySelectorAll(s)].map(e => Number(e.dataset.id))"


class Board(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("board")  # pass 32: the page opens on Today

    # --- helpers
    def new_job(self, company, title, jd="Python, SQL and Airflow pipelines.", **fields):
        jid = self.api("/api/jobs", {"company": company, "title": title, "jd": jd})["id"]
        if fields:
            self.assertNotIn("error", self.api(f"/api/jobs/{jid}/fields", fields))
        self.reload_state()
        return jid

    def board_ids(self):
        return set(self.page.evaluate(CARD_IDS, "#cols .card"))

    def table_ids(self):
        return self.page.evaluate("() => [...document.querySelectorAll('#jobTable tbody tr')].map(r => Number(r.cells[1].textContent))")

    def col_of(self, jid):
        return self.page.evaluate("id => document.querySelector(`.card[data-id='${id}']`)?.closest('.col')?.dataset.s", jid)

    def expect_visible(self, pred):
        want = {j["id"] for j in self.state()["jobs"] if pred(j)}
        self.page.wait_for_function("n => document.querySelectorAll('#cols .card').length === n", arg=len(want))
        self.assertEqual(self.board_ids(), want)
        return want

    def drag(self, jid, status):
        """The HTML5 drag events on this exact card and column. A mouse drag_and_drop scrolls <main> (it scrolls on its
        own) to a column below the fold after the button goes down, and the drag then starts on whatever card is under
        the pointer: a long Saved column made it drag the wrong job."""
        asked = len(self.dialogs)
        dt = self.page.evaluate_handle("new DataTransfer()")
        col = self.page.locator(f'.col[data-s="{status}"]')
        self.page.locator(f'.card[data-id="{jid}"]').dispatch_event("dragstart", {"dataTransfer": dt})
        col.dispatch_event("dragover", {"dataTransfer": dt})
        col.dispatch_event("drop", {"dataTransfer": dt})
        self.idle()
        return len(self.dialogs) > asked  # whether the move asked first

    def statuses(self, but):
        return {j["id"]: j["status"] for j in self.state()["jobs"] if j["id"] != but}

    # --- Add job
    def test_add_job_with_pasted_description_opens_its_drawer(self):
        self.page.fill("#nCo", "Lumen Grid")
        self.page.fill("#nTi", "Data Engineer")
        self.page.fill("#nJd", "Lumen Grid builds energy dashboards. Python, Kafka, dbt. Salary $130,000 - $150,000. Remote.")
        self.run_click(ADD)
        jid = self.page.evaluate("cur.job.id")
        row = db.get_job(jid)
        self.assertEqual((row["company"], row["title"], row["status"]), ("Lumen Grid", "Data Engineer", "saved"))
        self.assertIn("Kafka", row["jd"])
        self.assertEqual((row["salary_min"], row["salary_max"], row["remote"]), (130000, 150000, "remote"))
        self.assertTrue(self.page.locator("#drawer.open").is_visible())
        self.assertIn("Lumen Grid", self.page.text_content("#drawer .head"))
        self.assertEqual(self.col_of(jid), "saved")
        self.assertEqual([self.page.input_value(s) for s in ("#nCo", "#nTi", "#nJd")], ["", "", ""])

    def test_add_job_blank_is_refused(self):
        self.allow_console()
        before = len(self.state()["jobs"])
        self.page.click(ADD)
        self.assertIn("type a company and title", self.expect_toast("type a company", "err"))
        self.idle()
        self.assertEqual(len(self.state()["jobs"]), before)
        self.assertFalse(self.page.locator("#drawer.open").count())

    def test_add_job_from_a_link_reads_the_page(self):
        link = "https://careers.example.org/jobs/77"
        self.page.fill("#nJd", link)
        self.run_click(ADD)
        self.assertIn(link, self.urls)  # fetched through util.fetch (canned posting page)
        row = db.get_job(self.page.evaluate("cur.job.id"))
        self.assertEqual((row["company"], row["title"], row["url"]), ("Example Co", "Data Engineer", link))
        self.assertIn("Airflow", row["jd"])
        self.assertEqual((row["salary_min"], row["salary_max"]), (140000, 170000))

    # --- cards and chips
    def test_cards_show_chips_counts_and_escape_text(self):
        i = self.ids
        north = self.page.locator(f'.card[data-id="{i["saved"]}"]')
        self.assertEqual(north.locator(".stars").get_attribute("aria-label"), "excitement 4 of 5")
        chips = north.locator(".chips").text_content()
        for want in ("150k–180k", "Portland, OR · hybrid", "due in 10d"):
            self.assertIn(want, chips)
        badge = self.page.locator(f'.card[data-id="{i["screening"]}"] .chip.fit')  # pass 21: the fit badge, not coverage
        self.assertRegex(badge.text_content(), r"^fit \d+")
        self.assertTrue(badge.get_attribute("title"))  # the top chips
        warm = self.page.locator(f'.card[data-id="{i["applied"]}"] .chip.warm')
        self.assertEqual(warm.text_content(), "you know 1 person here")
        self.assertIn("Sam Okafor (Senior Analyst)", warm.get_attribute("title"))
        self.assertEqual(self.page.get_attribute(f'.card[data-id="{i["interview"]}"]', "aria-label"),
                         f'#{i["interview"]} Orchid Health - Staff Data Engineer, interview')
        jobs = self.state()["jobs"]
        for s in ("saved", "interview", "withdrawn"):
            self.assertEqual(int(self.page.text_content(f'.col[data-s="{s}"] h3 span')), sum(j["status"] == s for j in jobs))
        self.assertIn(f"tracked {len(jobs)}", self.page.text_content("#stats"))
        # company and title are untrusted (captured pages, search listings): shown as text, never run
        jid = self.new_job('<img src=x onerror="window.__xss=1">', "<b>Bold</b> role")
        card = self.page.locator(f'.card[data-id="{jid}"]')
        self.assertEqual(card.locator(".co").text_content(), '<img src=x onerror="window.__xss=1">')
        self.assertEqual(card.locator(".ti").text_content(), "<b>Bold</b> role")
        self.assertIsNone(self.page.evaluate("window.__xss"))
        self.assertEqual(card.locator("img, b").count(), 0)

    # --- filter bar
    def test_each_filter_narrows_the_board_and_clear_restores(self):
        i = self.ids
        pay = lambda j: j["salary_max"] if j["salary_max"] is not None else j["salary_min"]  # noqa: E731
        self.page.fill("#fQ", "orchid")
        self.assertEqual(self.expect_visible(lambda j: "orchid" in " ".join(str(j[k] or "") for k in ("company", "title", "location", "tags")).lower()), {i["interview"]})
        self.page.fill("#fQ", "")
        self.page.select_option("#fStatus", "offer")
        self.assertIn(i["offer"], self.expect_visible(lambda j: j["status"] == "offer"))
        self.page.select_option("#fStatus", "")
        self.page.select_option("#fRemote", "onsite")
        self.assertIn(i["screening"], self.expect_visible(lambda j: j["remote"] == "onsite"))
        self.page.select_option("#fRemote", "")
        self.page.fill("#fSal", "170000")  # unknown pay is kept: nothing hides for lack of data
        shown = self.expect_visible(lambda j: pay(j) is None or pay(j) >= 170000)
        self.assertIn(i["interview"], shown)
        self.assertNotIn(i["applied"], shown)  # 160k top
        self.page.fill("#fSal", "")
        self.page.fill("#fTag", "airflow")
        self.assertEqual(self.expect_visible(lambda j: "airflow" in (j["tags"] or "").split(",")), {i["interview"]})
        self.page.fill("#fTag", "")
        self.page.check("#fDl")
        self.assertIn(i["saved"], self.expect_visible(lambda j: bool(j["deadline"])))
        # filters that match nothing: say so, with a way out
        self.page.fill("#fQ", "no such company anywhere")
        self.page.wait_for_selector("#filterEmpty", state="visible")
        self.assertEqual(self.board_ids(), set())
        self.page.click("#filterEmpty button")
        self.expect_visible(lambda j: True)
        self.assertEqual([self.page.input_value(s) for s in ("#fQ", "#fStatus", "#fRemote", "#fSal", "#fTag")], [""] * 5)
        self.assertFalse(self.page.is_checked("#fDl"))
        self.assertTrue(self.page.locator("#filterEmpty").is_hidden())

    def test_filters_and_view_survive_a_reload(self):
        self.page.fill("#fTag", "python")
        self.page.click("#fView")
        self.page.reload()
        self.page.wait_for_function("() => S !== null")
        self.idle()
        self.assertEqual(self.page.input_value("#fTag"), "python")
        self.assertEqual(self.page.get_attribute("#fView", "aria-pressed"), "true")
        self.assertEqual(set(self.table_ids()), {j["id"] for j in self.state()["jobs"] if "python" in (j["tags"] or "").split(",")})
        self.assertIn('"tag":"python"', self.page.evaluate("localStorage.getItem('ls_board_view')"))

    # --- sort and table view
    def test_table_view_sorts_by_select_and_by_header(self):
        self.page.click("#fView")
        self.assertEqual(self.page.text_content("#fView"), "Board view")
        self.assertTrue(self.page.locator("#jobTable").is_visible())
        self.assertTrue(self.page.locator("#cols").is_hidden())
        jobs = {j["id"]: j for j in self.state()["jobs"]}
        pay = lambda j: j["salary_max"] if j["salary_max"] is not None else j["salary_min"]  # noqa: E731

        def check(sort, key, reverse):
            self.page.select_option("#fSort", sort)
            ids = self.table_ids()
            vals = [key(jobs[x]) for x in ids]
            known = [v for v in vals if v is not None]
            self.assertEqual(known, sorted(known, reverse=reverse), sort)
            self.assertTrue(all(v is None for v in vals[len(known):]), f"{sort}: missing values go last")
            return ids

        self.assertEqual(check("match", lambda j: j["match_score"], True)[0], self.ids["screening"])
        self.assertEqual(check("excitement", lambda j: j["excitement"], True)[0], self.ids["interview"])
        self.assertEqual(check("salary", pay, True)[0], self.ids["interview"])
        self.assertEqual(self.page.get_attribute('#jobTable th:has(button:text("Salary"))', "aria-sort"), "descending")
        check("deadline", lambda j: j["deadline"], False)
        check("stale", lambda j: j["updated_at"], False)
        check("updated", lambda j: j["updated_at"], True)
        # a header click sorts by that column; the same header again flips it
        self.page.click('#jobTable th button:text("Company")')
        names = [jobs[x]["company"] for x in self.table_ids()]
        self.assertEqual(names, self.page.evaluate("a => [...a].sort((x, y) => x.localeCompare(y))", names))
        self.assertEqual(self.page.get_attribute('#jobTable th:has(button:text("Company"))', "aria-sort"), "ascending")
        self.assertEqual(self.page.input_value("#fSort"), "")  # "(table column)"
        self.page.click('#jobTable th button:text("Company")')
        self.assertEqual([jobs[x]["company"] for x in self.table_ids()], names[::-1])
        self.assertEqual(self.page.get_attribute('#jobTable th:has(button:text("Company"))', "aria-sort"), "descending")
        self.page.click("#fView")
        self.assertTrue(self.page.locator("#cols").is_visible())
        self.assertEqual(self.page.get_attribute("#fView", "aria-pressed"), "false")

    def test_bulk_actions_tag_status_and_delete(self):
        a, b = self.new_job("Bulkhead Systems", "Data Engineer A"), self.new_job("Bulkhead Systems", "Data Engineer B")
        self.page.click("#fView")
        self.page.fill("#fQ", "bulkhead")
        self.page.wait_for_function("() => document.querySelectorAll('#jobTable tbody tr').length === 2")
        self.assertTrue(self.page.locator("#bulk").is_hidden())
        self.page.check('#jobTable th input[type="checkbox"]')
        self.assertEqual(self.page.text_content("#bulkN"), "2 selected")
        self.page.click("#bulk >> text=Add tag")  # no tag typed
        self.expect_toast("type a tag first", "err")
        self.page.fill("#bulkTag", "urgent")
        self.run_click("#bulk >> text=Add tag")
        self.expect_toast("tagged 2 job(s)", "ok")
        self.assertTrue(all("urgent" in db.get_job(x)["tags"].split(",") for x in (a, b)))
        self.assertTrue(self.page.locator("#bulk").is_hidden())  # the selection is spent
        self.page.check('#jobTable th input[type="checkbox"]')
        self.page.select_option("#bulkStatus", "screening")
        self.page.click("#bulk >> text=Set status")  # the confirm is dismissed: nothing moves
        self.assertIn('Set 2 job(s) to "screening"?', self.dialogs[-1])
        self.idle()
        self.assertEqual({db.get_job(x)["status"] for x in (a, b)}, {"saved"})
        self.answer(True)
        self.run_click("#bulk >> text=Set status")
        self.expect_toast("2 job(s) → screening", "ok")
        self.assertEqual({db.get_job(x)["status"] for x in (a, b)}, {"screening"})
        self.page.check(f'#jobTable input[aria-label="select #{a}"]')
        self.assertEqual(self.page.text_content("#bulkN"), "1 selected")
        self.answer(True)
        self.run_click("#bulk >> text=Delete selected")
        self.assertIn("Delete 1 job(s)", self.dialogs[-1])
        self.assertIsNone(db.con().execute("SELECT id FROM jobs WHERE id=?", (a,)).fetchone())
        self.assertEqual(db.get_job(b)["status"], "screening")
        self.assertEqual(self.table_ids(), [b])

    # --- drag and drop
    def test_drag_forward_moves_backward_asks_first(self):
        jid = self.new_job("Dragonfly Data", "Data Engineer")
        self.drag(jid, "applied")  # forward: no question
        self.assertEqual(self.dialogs, [])
        self.assertEqual(db.get_job(jid)["status"], "applied")
        self.assertEqual(self.col_of(jid), "applied")
        self.expect_toast(f"#{jid} → applied", "ok")
        self.drag(jid, "saved")  # backward: asks, and a dismissed confirm changes nothing
        self.assertIn(f'Move #{jid} Dragonfly Data - Data Engineer back from "applied" to "saved"', self.dialogs[-1])
        self.assertEqual(db.get_job(jid)["status"], "applied")
        self.assertEqual(self.col_of(jid), "applied")
        self.answer(True)
        self.drag(jid, "saved")
        self.assertEqual(db.get_job(jid)["status"], "saved")
        self.assertEqual(self.col_of(jid), "saved")
        self.assertIn("(moved by you)", " ".join(e["detail"] or "" for e in db.events(jid)))

    def test_drag_to_accepted_confirms_and_proposes_withdrawals(self):
        jid = self.new_job("Acorn Ledger", "Data Engineer")
        pending, others = len(self.state()["pending"]), self.statuses(jid)
        self.assertTrue(self.drag(jid, "accepted"))  # dismissed
        self.assertIn(f"Mark #{jid} Acorn Ledger - Data Engineer accepted?", self.dialogs[-1])
        self.assertEqual(db.get_job(jid)["status"], "saved")
        self.answer(True)
        self.drag(jid, "accepted")
        self.assertIn(f"Mark #{jid} Acorn Ledger", self.dialogs[-1])
        self.assertEqual(db.get_job(jid)["status"], "accepted")
        self.expect_toast(f"#{jid} → accepted. Withdrawing your other open applications is proposed", "ok")
        self.assertEqual(self.statuses(jid), others)  # proposed only: no other job moved
        self.assertGreater(len(self.state()["pending"]), pending)
        self.assertEqual(int(self.page.text_content("#inboxN")), len(self.state()["pending"]))

    # --- keyboard
    def test_keyboard_opens_cards_and_escape_returns_focus(self):
        jid = self.ids["interview"]
        self.tab_to(f'.card[data-id="{jid}"]')
        self.press("Enter")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=jid)
        self.assertTrue(self.page.evaluate("document.activeElement.matches('#drawer .close')"), self.focused())
        self.press("Escape")
        self.page.wait_for_selector("#drawer:not(.open)", state="attached")
        self.assertTrue(self.page.evaluate(f"document.activeElement.matches('.card[data-id=\"{jid}\"]')"), self.focused())
        other = self.ids["applied"]
        self.page.focus(f'.card[data-id="{other}"]')
        self.press(" ")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=other)
        self.press("Escape")
        self.page.click("#fView")  # the table: the company is a link
        self.page.focus('#jobTable a:text("Orchid Health")')
        self.press("Enter")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=jid)

    # --- 420px
    def test_narrow_window_has_no_sideways_scroll(self):
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [], "board view")
        self.page.click("#fView")
        self.assertEqual(self.overflow(), [], "table view")
        self.page.click('#jobTable a:text("Orchid Health")')
        self.page.wait_for_selector("#drawer.open")
        self.idle()
        self.page.wait_for_function("() => getComputedStyle(document.querySelector('#drawer')).transform === 'none'")  # slid in
        box = self.page.evaluate("() => { const d = document.querySelector('#drawer'); const r = d.getBoundingClientRect();"
                                 " return [r.left, r.right, d.scrollWidth, d.clientWidth, document.documentElement.clientWidth]; }")
        left, right, sw, cw, vw = box
        self.assertGreaterEqual(left, -1)
        self.assertLessEqual(right, vw + 1)
        self.assertLessEqual(sw, cw + 1, "the drawer scrolls sideways at 420px")


if __name__ == "__main__":
    unittest.main()
