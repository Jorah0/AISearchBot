"""Inbox: approve with edits, the salary-floor guard on edits, reject, retry after a failed send, the JSON editor of
other kinds (bad JSON, stale proposals), the unverified-sender pill, Options and rewrite chips, attachments (add, remove,
attach folder, sent with the mail), Unmatched mail (link, track, dismiss), emailed codes, keyboard and 420px."""
import smtplib
import unittest

from harness import E2ETestCase, FakeMail, approvals, db, resume

AI = {"options": [
    {"label": "Brief", "tone": "brief", "subject": "Quick follow-up", "recommended": True, "why": "short and clear",
     "body": "Hi, a quick note to follow up on my application. Best, Pat"},
    {"label": "Warm", "tone": "warm", "subject": "Still very interested", "recommended": False, "why": "",
     "body": "Hi, I am still very interested in the role and happy to share more. Best, Pat"}],
    "subject": "Rewritten subject", "body": "Rewritten body: short and kind. Best, Pat"}


class Inbox(E2ETestCase):
    ai_json = AI

    def setUp(self):
        super().setUp()
        self.go("inbox")

    # --- helpers
    def propose(self, jid, subject, body="Hi, following up. Best, Pat", to="recruiting@example.org", **extra):
        """A fresh email waiting for review (each test edits its own, so test order never matters)."""
        r = approvals.propose("followup", "send_email", {"to": to, "subject": subject, "body": body, "job_id": jid, **extra},
                              f"e2e {subject}", jid, force_pending=True)
        self.reload_state()
        return r["id"]

    def card(self, pid):
        return self.page.locator("#inboxList > .item", has=self.page.locator(f'.hd > b:text-is("#{pid}")'))

    def pending(self, pid):
        return next((p for p in self.state()["pending"] if p["id"] == pid), None)

    def row(self, pid):
        return db.con().execute("SELECT status, result FROM pending WHERE id=?", (pid,)).fetchone()

    def badge(self):
        return int(self.page.text_content("#inboxN"))

    # --- approve / reject
    def test_approve_with_edits_sends_the_edited_mail(self):
        pid = self.propose(self.ids["applied"], "Following up: Analytics Engineer")
        n, sent = self.badge(), len(FakeMail.SENT)
        self.assertEqual(n, len(self.state()["pending"]))
        card = self.card(pid)
        self.assertEqual(card.get_by_role("button", name="Approve and send").count(), 1)
        self.page.fill(f"#to{pid}", "hiring@bluefinlabs.example")
        self.page.fill(f"#sub{pid}", "Edited: Analytics Engineer")
        self.page.fill(f"#body{pid}", "Hi Jordan, my edited note. Best, Pat")
        self.run_click(card.get_by_role("button", name="Approve and send"))
        self.expect_toast(f"#{pid} done: sent to hiring@bluefinlabs.example: Edited: Analytics Engineer", "ok")
        m = FakeMail.SENT[sent]
        self.assertEqual((m["To"], m["Subject"]), ("hiring@bluefinlabs.example", "Edited: Analytics Engineer"))
        self.assertIn("my edited note", m.get_content())
        self.assertEqual(self.row(pid)["status"], "done")
        self.assertEqual(card.count(), 0)
        self.assertEqual(self.badge(), n - 1)
        self.assertIn(f"#{pid} done", self.page.text_content("#decidedList"))
        out = db.con().execute("SELECT to_addr, subject FROM mail WHERE direction='out' AND subject=?",
                               ("Edited: Analytics Engineer",)).fetchone()
        self.assertEqual(tuple(out), ("hiring@bluefinlabs.example", "Edited: Analytics Engineer"))

    def test_edit_naming_the_salary_floor_is_refused_and_stays_pending(self):
        self.allow_console()
        pid = self.propose(self.ids["applied"], "Pay question")
        sent = len(FakeMail.SENT)
        self.page.fill(f"#body{pid}", "Hi, I need at least $165,000 base. Best, Pat")
        self.run_click(self.card(pid).get_by_role("button", name="Approve and send"))
        self.expect_toast("error:", "err")
        self.assertEqual(len(FakeMail.SENT), sent)
        self.assertEqual(self.row(pid)["status"], "pending")
        self.assertIn("$165,000", self.page.input_value(f"#body{pid}"))  # your edit is kept to fix
        self.assertNotIn("165,000", self.pending(pid)["payload"]["body"])

    def test_reject_records_the_decision(self):
        pid = self.propose(self.ids["screening"], "Not this one")
        n = self.badge()
        self.run_click(self.card(pid).get_by_role("button", name="Reject"))
        self.expect_toast(f"#{pid} rejected", "ok")
        self.assertEqual(self.row(pid)["status"], "rejected")
        self.assertIsNone(self.pending(pid))
        self.assertEqual(self.badge(), n - 1)
        self.assertIn(f"#{pid} rejected", self.page.text_content("#decidedList"))
        ev = [e["kind"] for e in self.api(f"/api/jobs/{self.ids['screening']}")["events"]]
        self.assertIn("rejected_proposal", ev)

    def test_failed_send_keeps_the_edit_and_retry_sends_it(self):
        pid = self.propose(self.ids["applied"], "Retry me")
        sent = len(FakeMail.SENT)

        def down(self_, msg, *a, **kw):
            raise smtplib.SMTPServerDisconnected("connection dropped")

        real = FakeMail.send_message
        FakeMail.send_message = down
        try:
            self.page.fill(f"#body{pid}", "Hi, the version I edited before the failure. Best, Pat")
            self.run_click(self.card(pid).get_by_role("button", name="Approve and send"))
            self.expect_toast(f"#{pid} pending: not sent, kept in the Inbox to retry", "ok")
        finally:
            FakeMail.send_message = real
        self.assertEqual(len(FakeMail.SENT), sent)
        card = self.card(pid)
        self.assertIn("send failed: connection dropped", card.locator(".pill.warn").text_content())
        self.assertEqual(self.page.input_value(f"#body{pid}"), "Hi, the version I edited before the failure. Best, Pat")
        self.assertEqual(self.row(pid)["status"], "pending")
        self.assertIn("send_failed", [e["kind"] for e in self.api(f"/api/jobs/{self.ids['applied']}")["events"]])
        self.run_click(card.get_by_role("button", name="Retry send"))
        self.expect_toast(f"#{pid} done: sent to", "ok")
        self.assertIn("the version I edited before the failure", FakeMail.SENT[sent].get_content())
        self.assertEqual(self.row(pid)["status"], "done")

    # --- other kinds: the payload as JSON
    def test_json_payload_bad_input_edit_and_stale_proposal(self):
        self.allow_console()
        st = self.state()
        juniper = next(p for p in st["pending"] if p["kind"] == "set_status" and p["job_id"] == self.ids["offer"])
        cobalt = next(p for p in st["pending"] if p["kind"] == "set_status" and p["job_id"] == self.ids["screening"])
        card = self.card(juniper["id"])
        self.assertEqual(card.get_by_role("button", name="Approve").count(), 1)  # not "and send"
        self.assertEqual(card.get_by_role("button", name="Options").count(), 0)  # no draft chips on a status change
        js = f"#js{juniper['id']}"
        self.page.fill(js, "{not json")
        card.get_by_role("button", name="Approve").click()
        self.expect_toast("not valid JSON", "err")
        self.page.fill(js, "[1, 2]")
        card.get_by_role("button", name="Approve").click()
        self.expect_toast("the payload must be a JSON object", "err")
        self.assertEqual(self.row(juniper["id"])["status"], "pending")
        p = dict(juniper["payload"], note="withdrawn after accepting Harbor & Pine (edited)")
        self.page.fill(js, __import__("json").dumps(p))
        self.run_click(card.get_by_role("button", name="Approve"))
        self.expect_toast(f"#{juniper['id']} done", "ok")
        self.assertEqual(db.get_job(self.ids["offer"])["status"], "withdrawn")
        self.assertIn("(edited)", " ".join(e["detail"] or "" for e in self.api(f"/api/jobs/{self.ids['offer']}")["events"]))
        # the job moved since this was proposed: the proposal closes as stale and never moves it back
        self.assertEqual(self.card(cobalt["id"]).count(), 1)
        self.assertTrue(self.api(f"/api/jobs/{self.ids['screening']}/status", {"status": "interview"})["ok"])
        self.reload_state()
        self.assertEqual(self.card(cobalt["id"]).count(), 0)
        self.assertEqual(tuple(self.row(cobalt["id"])), ("rejected", "stale: the job moved to interview before this was decided"))
        self.assertIn(f"#{cobalt['id']} rejected", self.page.text_content("#decidedList"))
        self.assertEqual(db.get_job(self.ids["screening"])["status"], "interview")

    # --- unverified sender
    def test_reply_to_unverified_mail_shows_the_pill(self):
        jid = self.ids["saved"]
        mid = "<spoof-1@northwind-careers.example>"
        db.add_mail(message_id=mid, job_id=jid, direction="in", from_addr="hr@northwind-careers.example",
                    subject="Next steps", sent_at="2026-11-01 10:00:00", category="interview", trusted=False, linked_by="auto")
        att = resume.app_dir(db.get_job(jid)) / "attach"
        att.mkdir(parents=True, exist_ok=True)
        (att / "portfolio.pdf").write_bytes(b"%PDF-1.4 e2e portfolio")
        pid = self.propose(jid, "Re: Next steps", to="hr@northwind-careers.example", in_reply_to=mid, new_status="interview")
        p = self.pending(pid)["payload"]
        self.assertTrue(p["unverified"])
        self.assertNotIn("new_status", p)  # sending it moves no job
        card = self.card(pid)
        self.assertEqual(card.locator(".hd .pill.warn").text_content(), "unverified sender")
        self.page.select_option(f"#att{pid} select", label="attach/portfolio.pdf · 1 KB")
        self.assertIn("the recipient is not verified", card.locator(f"#att{pid}").text_content())
        self.run_click(card.get_by_role("button", name="Reject"))

    # --- Options and rewrite chips
    def test_options_and_rewrite_chips_edit_in_place(self):
        pid = self.propose(self.ids["applied"], "Original subject", "Original body. Best, Pat")
        card = self.card(pid)
        calls = len(self.ai_calls)
        self.run_click(card.get_by_role("button", name="Options", exact=True))
        self.assertEqual(len(self.ai_calls), calls + 1)
        opts = card.locator(".opt")
        self.assertEqual(opts.count(), 2)
        self.assertIn("recommended", opts.nth(0).text_content())
        self.run_click(opts.nth(1).get_by_role("button", name="Use this"))
        self.expect_toast(f"inbox #{pid} updated; still waiting for your approval", "ok")
        p = self.pending(pid)["payload"]
        self.assertEqual((p["subject"], p["to"]), ("Still very interested", "recruiting@example.org"))  # recipient kept
        self.assertEqual(self.page.input_value(f"#sub{pid}"), "Still very interested")
        self.assertEqual(card.locator(".opt").count(), 0)  # closed after use
        # a chip rewrites the current text (your edits included) and saves it; still pending
        self.page.fill(f"#body{pid}", "My own edit before the rewrite. Best, Pat")
        self.run_click(card.get_by_role("button", name="shorter"))
        self.expect_toast(f"inbox #{pid} rewritten; still waiting for your approval", "ok")
        self.assertIn("My own edit before the rewrite", str(self.ai_calls[-1]["messages"]))
        self.assertEqual(self.pending(pid)["payload"]["body"], AI["body"])
        self.assertEqual(self.page.input_value(f"#body{pid}"), AI["body"])
        for chip in ("warmer", "more formal", "more direct"):
            self.assertEqual(card.get_by_role("button", name=chip, exact=True).count(), 1)
        # custom: asks how; an empty answer changes nothing and calls no AI
        calls = len(self.ai_calls)
        self.answer("")
        card.get_by_role("button", name="custom…").click()
        self.idle()
        self.assertEqual(len(self.ai_calls), calls)
        self.answer("mention my portfolio link")
        self.run_click(card.get_by_role("button", name="custom…"))
        self.assertIn("mention my portfolio link", str(self.ai_calls[-1]["messages"]))
        self.assertEqual(self.row(pid)["status"], "pending")
        # close options without using one
        self.run_click(card.get_by_role("button", name="Options", exact=True))
        card.get_by_role("button", name="close options").click()
        self.assertEqual(card.locator(".opt").count(), 0)

    # --- attachments
    def test_attachments_add_remove_folder_and_send(self):
        jid = self.ids["interview"]
        att = resume.app_dir(db.get_job(jid)) / "attach"
        att.mkdir(parents=True, exist_ok=True)
        (att / "work-sample.pdf").write_bytes(b"%PDF-1.4 e2e work sample")
        (att / "notes.txt").write_text("not attachable", encoding="utf-8")
        pid = self.propose(jid, "Re: Technical interview availability", to="maya.chen@orchidhealth.example")
        row = self.page.locator(f"#att{pid}")
        self.assertIn("none", row.text_content())
        options = row.locator("select option").all_text_contents()
        self.assertIn("attach/work-sample.pdf · 1 KB", options)
        self.assertFalse(any("notes.txt" in o for o in options))  # only pdf, docx, png, jpg
        self.page.select_option(f"#att{pid} select", label="attach/work-sample.pdf · 1 KB")
        self.assertEqual(row.locator(".pill").first.text_content().replace("×", "").strip(), "attach/work-sample.pdf · 1 KB")
        row.get_by_role("button", name="remove attachment").click()
        self.assertIn("none", row.text_content())
        self.page.select_option(f"#att{pid} select", label="attach/work-sample.pdf · 1 KB")
        opened = len(self.opened)
        self.run_click(row.get_by_role("button", name="Show attach folder"))
        self.assertEqual(self.opened[opened][0], "folder")
        self.assertEqual(self.opened[opened][1], str(att))
        sent = len(FakeMail.SENT)
        self.run_click(self.card(pid).get_by_role("button", name="Approve and send"))
        self.expect_toast(f"#{pid} done", "ok")
        m = FakeMail.SENT[sent]
        self.assertEqual([a.get_filename() for a in m.iter_attachments()], ["work-sample.pdf"])
        out = db.con().execute("SELECT attachments FROM mail WHERE direction='out' AND to_addr=? ORDER BY id DESC",
                               ("maya.chen@orchidhealth.example",)).fetchone()
        self.assertIn("work-sample.pdf", out["attachments"])

    # --- Unmatched mail
    def test_unmatched_mail_link_track_and_dismiss(self):
        self.allow_console()
        for i, (frm, subj, co) in enumerate((("jobs@lumen.example", "Data role at Lumen", "Lumen Data"),
                                             ("talent@kiln.example", "Kiln is hiring", "Kiln Systems"))):
            db.add_mail(message_id=f"<um-{i}@e2e.example>", direction="in", from_addr=frm, subject=subj,
                        sent_at="2026-11-05 09:00:00", category="recruiter_outreach", company=co, title="Data Engineer")
        self.reload_state()
        ids = {m["subject"]: m["id"] for m in self.state()["mail_unmatched"]}
        zephyr, lumen, kiln = ids["Exciting data role at Zephyr AI"], ids["Data role at Lumen"], ids["Kiln is hiring"]
        item = self.page.locator(f"#mailList #mail{zephyr}")
        self.assertEqual(item.locator(".pill.warn").text_content(), "unverified")
        item.locator("summary").click()
        self.assertIn("Your profile caught our eye", item.locator("pre").text_content())
        item.get_by_role("button", name="Link to job").click()  # no job chosen
        self.expect_toast("choose the job first", "err")
        self.page.select_option(f"#ml{zephyr}", str(self.ids["applied"]))
        self.run_click(item.get_by_role("button", name="Link to job"))
        self.expect_toast(f"mail #{zephyr}: link done", "ok")
        self.assertEqual(item.count(), 0)
        m = db.con().execute("SELECT job_id, linked_by, trusted FROM mail WHERE id=?", (zephyr,)).fetchone()
        self.assertEqual((m["job_id"], m["linked_by"], m["trusted"]), (self.ids["applied"], "user", 0))
        # track as a new job: two prompts; cancelling the first does nothing
        jobs = len(self.state()["jobs"])
        self.answer(False)
        self.page.locator(f"#mail{lumen}").get_by_role("button", name="Track as new job").click()
        self.assertIn("Company for the new job", self.dialogs[-1])
        self.idle()
        self.assertEqual(len(self.state()["jobs"]), jobs)
        self.answer("Lumen Data", "Senior Data Engineer")
        self.run_click(self.page.locator(f"#mail{lumen}").get_by_role("button", name="Track as new job"))
        new = next(j for j in self.state()["jobs"] if j["company"] == "Lumen Data")
        self.assertEqual(new["title"], "Senior Data Engineer")
        self.expect_toast(f"tracking job #{new['id']}", "ok")
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=new["id"])
        self.assertEqual(db.con().execute("SELECT job_id FROM mail WHERE id=?", (lumen,)).fetchone()[0], new["id"])
        self.page.evaluate("closeDrawer()")
        self.run_click(self.page.locator(f"#mail{kiln}").get_by_role("button", name="Dismiss"))
        self.assertEqual(self.page.locator(f"#mail{kiln}").count(), 0)
        self.assertNotIn(kiln, [m["id"] for m in self.state()["mail_unmatched"]])

    # --- emailed codes
    def test_codes_panel_checks_the_mailbox(self):
        FakeMail.CALLS.clear()
        self.page.click("#codesPanel summary")
        self.idle()
        btn = self.page.get_by_role("button", name="Check for a code now")
        self.run_click(btn)
        self.expect_toast("no code in the last 15 minutes", "ok")
        self.assertIn("login", FakeMail.CALLS)
        self.assertIn("no code in the last 15 minutes", self.page.text_content("#codesList"))
        self.assertTrue(btn.is_enabled())

    # --- keyboard and narrow window
    def test_keyboard_reject_and_420px(self):
        pid = self.propose(self.ids["applied"], "Keyboard reject")
        self.page.focus(f"#body{pid}")
        self.tab_to(f"#inboxList .item:has(#body{pid}) > .row:last-child > button.ghost", limit=40)  # Reject
        self.press("Enter")
        self.idle()
        self.assertEqual(self.row(pid)["status"], "rejected")
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
