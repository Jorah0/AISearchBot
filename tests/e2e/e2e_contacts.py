"""Contacts: the table (sort by every column, remembered; text filter; next-touch-due filter), Add contact (blank, bad
email, duplicate refused cleanly), LinkedIn Connections.csv import (no file, bad file, add / merge, re-import), the
contact drawer (edit and validation, Touched today, link / unlink a job with a role, jump to the job, delete, Esc with
unsaved text), keyboard and 420px."""
import unittest
from datetime import date

from harness import E2ETestCase, contacts, db, day

CSV = """Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Riley,Nguyen,https://www.linkedin.com/in/riley-nguyen-example,,Kestrel Maps,Data Lead,03 Feb 2024
Morgan,Lee,https://www.linkedin.com/in/morgan-lee-example,morgan.lee@example.net,Cobalt Freight,Data Manager,11 Mar 2023
Sam,Okafor,https://www.linkedin.com/in/sam-okafor-example,sam.okafor@example.net,Bluefin Labs,Senior Analyst,01 Jan 2022
"""


class Contacts(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("contacts")

    def names(self):
        return self.page.locator("#ctTable tbody tr td:first-child").all_text_contents()

    def rows(self):
        return {c["name"]: c for c in self.api("/api/contacts")["contacts"]}

    def open(self, name):
        self.page.locator("#ctTable a", has_text=name).click()
        self.page.wait_for_function("n => CT && CT.contact.name === n", arg=name)
        self.idle()
        return self.page.locator("#drawer")

    # --- table
    def test_sort_every_column_and_remember_it(self):
        self.assertEqual(self.names(), sorted(self.names(), key=str.lower))
        self.assertEqual(self.page.get_attribute("#ctTable th:has(button:text('Name'))", "aria-sort"), "ascending")
        api = list(self.rows().values())
        for col, key in (("Company", "company"), ("Position", "position"), ("Last touch", "last_touch"),
                         ("Next touch", "next_touch"), ("Linked jobs", "jobs")):
            self.page.click(f"#ctTable th button:text-is('{col}')")
            th = self.page.locator(f"#ctTable th:has(button:text('{col}'))")
            first = th.get_attribute("aria-sort")
            self.assertIn(first, ("ascending", "descending"))
            got = [next(c[key] for c in api if c["name"] == n) for n in self.names()]
            known = [v for v in got if v not in (None, "")]
            self.assertEqual(known, sorted(known, reverse=first == "descending"), col)
            self.assertEqual(got[len(known):], [v for v in got if v in (None, "")], col)  # empty last
            self.page.click(f"#ctTable th button:has-text('{col}')")  # same column flips
            self.assertNotEqual(th.get_attribute("aria-sort"), first)
        self.page.click("#ctTable th button:has-text('Company')")
        order = self.names()
        self.page.reload()
        self.page.wait_for_function("() => S !== null")
        self.go("contacts")
        self.idle()
        self.assertEqual(self.names(), order)  # the sort is kept in localStorage

    def test_filters_text_and_next_touch_due(self):
        n = len(self.rows())
        self.page.fill("#ctQ", "ORCHID")
        self.assertEqual(self.names(), ["Maya Chen"])
        self.assertEqual(self.page.text_content("#ctN"), f"1 of {n}")
        self.page.fill("#ctQ", "engineering manager")
        self.assertEqual(self.names(), ["Dev Patel"])
        self.page.fill("#ctQ", "no such person")
        self.assertIn("No contacts match.", self.page.text_content("#ctTable"))
        self.page.fill("#ctQ", "")
        self.page.check("#ctDue")
        self.assertEqual(self.names(), ["Sam Okafor"])  # next touch today; Maya's is tomorrow
        self.assertIn("due", self.page.locator("#ctTable tr.due").text_content())
        self.page.uncheck("#ctDue")
        self.assertEqual(len(self.names()), n)

    # --- add
    def test_add_contact_blank_bad_and_duplicate(self):
        self.allow_console()
        n = len(self.rows())
        self.page.click("text=Add contact")
        self.expect_toast("type a name first", "err")
        self.page.fill("#ctName", "Jordan Blake")
        self.page.fill("#ctEmail", "not-an-email")
        self.page.click("text=Add contact")
        self.idle()
        self.expect_toast("error: not an email address: not-an-email", "err")
        self.page.fill("#ctEmail", "MAYA.CHEN@orchidhealth.example")  # Maya's address, other case
        self.page.click("text=Add contact")
        self.idle()
        self.expect_toast("error: another contact already has this email address or LinkedIn URL", "err")
        self.assertEqual(len(self.rows()), n)
        self.assertEqual(self.page.input_value("#ctName"), "Jordan Blake")  # kept, to fix and retry
        self.assertFalse(self.page.locator("#drawer").get_attribute("class"))
        self.page.fill("#ctEmail", "jordan.blake@example.org")
        self.page.fill("#ctCo", "Kestrel Maps")
        self.page.fill("#ctPos", "Data Lead")
        self.page.click("text=Add contact")
        self.idle()
        self.expect_toast("contact added", "ok")
        c = self.rows()["Jordan Blake"]
        self.assertEqual((c["email"], c["company"], c["position"], c["source"]),
                         ("jordan.blake@example.org", "Kestrel Maps", "Data Lead", "manual"))
        self.assertEqual([self.page.input_value(s) for s in ("#ctName", "#ctEmail", "#ctCo", "#ctPos")], [""] * 4)
        self.page.wait_for_function("id => CT && CT.contact.id === id", arg=c["id"])  # its drawer opens
        self.assertIn("Jordan Blake", self.names())

    # --- import
    def test_import_connections_csv(self):
        self.allow_console()
        self.page.get_by_role("button", name="Import LinkedIn connections").click()
        self.expect_toast("choose your LinkedIn .zip or Connections.csv first", "err")
        self.page.set_input_files("#ctFile", files=[{"name": "notes.csv", "mimeType": "text/csv", "buffer": b"a,b\n1,2\n"}])
        self.run_click(self.page.get_by_role("button", name="Import LinkedIn connections"))
        self.expect_toast("error:", "err")
        before = self.rows()
        n = len(before)
        self.page.set_input_files("#ctFile", files=[{"name": "Connections.csv", "mimeType": "text/csv", "buffer": CSV.encode()}])
        self.run_click(self.page.get_by_role("button", name="Import LinkedIn connections"))
        self.expect_toast("3 connection(s): 2 added, 1 updated, 0 unchanged or skipped", "ok")
        rows = self.rows()
        self.assertEqual(len(rows), n + 2)
        self.assertEqual((rows["Riley Nguyen"]["company"], rows["Riley Nguyen"]["source"]), ("Kestrel Maps", "linkedin"))
        self.assertEqual(rows["Morgan Lee"]["email"], "morgan.lee@example.net")
        self.assertEqual(rows["Sam Okafor"]["email"], "sam.okafor@example.net")  # merged by LinkedIn URL: gained the email
        self.assertEqual(rows["Sam Okafor"]["position"], before["Sam Okafor"]["position"])  # your fields are kept
        self.assertIsNone(rows["Riley Nguyen"]["next_touch"])  # no follow-up dates are set
        self.assertIn("Riley Nguyen", self.names())
        self.run_click(self.page.get_by_role("button", name="Import LinkedIn connections"))  # again: nothing new
        self.expect_toast("3 connection(s): 0 added, 0 updated, 3 unchanged or skipped", "ok")
        self.assertEqual(len(self.rows()), n + 2)

    # --- the contact drawer
    def test_drawer_edit_validation_and_touched_today(self):
        self.allow_console()
        sam = contacts.add(name="Casey Morgan", linkedin_url="https://www.linkedin.com/in/casey-morgan-example",
                           company="Bluefin Labs", position="Analyst", next_touch=day(0))  # this test's own contact
        self.page.evaluate("loadContacts()")
        self.idle()
        d = self.open("Casey Morgan")
        self.assertEqual(self.page.get_attribute("#drawer", "aria-label"), "Contact details")
        self.assertIn("LinkedIn ↗", d.text_content())
        self.page.fill("#c_linkedin_url", "not a profile link")
        d.get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.expect_toast("error: linkedin_url must be a profile link", "err")
        self.assertEqual(contacts.get(sam)["linkedin_url"], "https://www.linkedin.com/in/casey-morgan-example")
        self.page.fill("#c_linkedin_url", "https://www.linkedin.com/in/casey-morgan-example")
        self.page.fill("#c_last_touch", day(3))
        d.get_by_role("button", name="Save", exact=True).click()
        self.idle()
        self.expect_toast("error: last_touch cannot be in the future", "err")
        self.page.fill("#c_last_touch", "")
        self.page.fill("#c_phone", "+1 503 555 0142")
        self.page.fill("#c_position", "Analytics Lead")
        self.page.fill("#c_how_met", "former colleague at Tidewater")
        self.page.fill("#c_notes", "Prefers a short message.\nAsk about the analytics team.")
        self.page.fill("#c_next_touch", day(7))
        self.run_click(d.get_by_role("button", name="Save", exact=True))
        self.expect_toast("contact saved", "ok")
        c = contacts.get(sam)
        self.assertEqual((c["phone"], c["position"], c["how_met"], c["next_touch"]),
                         ("+1 503 555 0142", "Analytics Lead", "former colleague at Tidewater", day(7)))
        self.assertEqual(c["notes"], "Prefers a short message.\nAsk about the analytics team.")
        self.assertIn("Analytics Lead at Bluefin Labs", self.page.text_content("#drawer .head"))
        # Touched today: last touch is today, logged once
        self.page.fill("#c_next_touch", day(0))
        self.run_click(d.get_by_role("button", name="Save", exact=True))
        self.run_click(d.get_by_role("button", name="Touched today"))
        self.expect_toast("last touch: today", "ok")
        self.assertEqual(contacts.get(sam)["last_touch"], date.today().isoformat())
        self.assertEqual(self.page.input_value("#c_last_touch"), date.today().isoformat())
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM touches WHERE contact_id=? AND day=?",
                                          (sam, date.today().isoformat())).fetchone()[0], 1)
        self.page.check("#ctDue")
        self.assertNotIn("Casey Morgan", self.names())  # in touch since the next touch came

    def test_drawer_link_unlink_jump_and_delete(self):
        maya = self.ids["c_maya"]
        d = self.open("Maya Chen")
        linked = d.locator(".group", has_text="Linked jobs")
        self.assertIn(f"#{self.ids['interview']} Orchid Health - Staff Data Engineer", linked.text_content())
        self.assertIn("recruiter", linked.text_content())
        self.assertEqual(d.locator("h4", has_text="Recent activity with").text_content(),
                         "Recent activity with maya.chen@orchidhealth.example")
        self.page.select_option("#cJobSel", str(self.ids["screening"]))
        self.page.select_option("#cRoleSel", "interviewer")
        self.run_click(d.get_by_role("button", name="link to job"))
        self.expect_toast("linked", "ok")
        self.assertEqual({(j["id"], j["role"]) for j in contacts.contact_jobs(maya)},
                         {(self.ids["interview"], "recruiter"), (self.ids["screening"], "interviewer")})
        self.assertIn("Cobalt Freight", self.page.locator("#ctTable tr:has(a:text('Maya Chen'))").text_content())
        row = linked.locator(".row", has_text="Cobalt Freight")
        self.run_click(row.get_by_role("button", name="unlink"))
        self.expect_toast("unlinked", "ok")
        self.assertEqual([j["id"] for j in contacts.contact_jobs(maya)], [self.ids["interview"]])
        # the job link opens that job's drawer on the Board
        d.locator("a", has_text="Orchid Health - Staff Data Engineer").click()
        self.page.wait_for_function("id => cur && cur.job.id === id", arg=self.ids["interview"])
        self.assertTrue(self.page.is_visible("section#board.on"))
        # delete: cancel keeps them, confirm removes them and their job links (the jobs stay)
        temp = contacts.add(name="Avery Stone", company="Juniper Robotics", position="Recruiter")
        contacts.link(temp, self.ids["offer"], "recruiter")
        self.go("contacts")
        self.open("Avery Stone")
        self.answer(False)
        self.page.locator("#drawer").get_by_role("button", name="delete").click()
        self.assertIn("Remove this contact?", self.dialogs[-1])
        self.idle()
        self.assertIn("Avery Stone", self.rows())
        self.answer(True)
        self.run_click(self.page.locator("#drawer").get_by_role("button", name="delete"))
        self.expect_toast("contact removed", "ok")
        self.assertNotIn("Avery Stone", self.rows())
        self.assertNotIn("open", self.page.get_attribute("#drawer", "class"))
        self.assertNotIn("Avery Stone", self.names())
        self.assertNotIn("Avery Stone", [x["name"] for x in self.api(f"/api/jobs/{self.ids['offer']}")["people"]])
        self.assertEqual(db.get_job(self.ids["offer"])["company"], "Juniper Robotics")

    def test_escape_keyboard_and_420px(self):
        self.page.focus("#ctQ")
        self.press("Tab", "Tab")  # past the due filter to the first sortable header
        self.press("Enter")
        self.assertEqual(self.page.get_attribute("#ctTable th:has(button:text('Name'))", "aria-sort"), "descending")
        link = self.page.locator("#ctTable a", has_text="Maya Chen")
        link.focus()
        self.press("Enter")
        self.page.wait_for_function("() => CT && CT.contact.name === 'Maya Chen'")
        self.page.wait_for_function("() => document.activeElement.matches('#drawer .close')")
        self.page.fill("#c_notes", "typed but not saved")
        self.answer(False)
        self.press("Escape")  # asks first: typed text would be lost
        self.assertIn("discard what you typed", self.dialogs[-1])
        self.assertIn("open", self.page.get_attribute("#drawer", "class"))
        self.answer(True)
        self.press("Escape")
        self.assertNotIn("open", self.page.get_attribute("#drawer", "class"))
        self.assertIsNone(contacts.get(self.ids["c_maya"])["notes"])
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])
        self.open("Maya Chen")
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
