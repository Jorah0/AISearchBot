"""Pass 15, group E: contacts CRM. Fields and links, the one-time move of job contacts, LinkedIn Connections.csv import
with de-dup, warm paths, touches from mail, due contacts on Today, referral asks, CLI and routes. The security rule
under test: a contact (imported or typed) never makes mail trusted and never becomes a job's contact by itself.
No network: mail and AI calls are faked and every patched attribute is put back."""
import imaplib
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import approvals, contacts, db, email_monitor as em, extras, loop, profile, settings  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

REAL_PROFILE = "# Jane Doe\njane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines in Python\n"
CSV = ('Notes:\n"When exporting your connection data, you may notice that some of the email addresses are missing."\n\n'
       "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
       "Ann,Lee,https://www.linkedin.com/in/ann-lee,,\"Acme, Inc.\",Data Lead,15 Oct 2023\n"
       "Bob,Ray,https://www.linkedin.com/in/bob-ray?trk=x,bob@globex.com,Globex,Recruiter,01 Jan 2024\n"
       "Cy,Ng,https://www.linkedin.com/in/cy-ng-1,,Initech,Engineer,02 Feb 2024\n"
       "Cy,Ng,https://www.linkedin.com/in/cy-ng-2,,Initech,Manager,03 Feb 2024\n"
       ",,https://www.linkedin.com/in/nobody,,X,Y,04 Feb 2024\n")


def zipped(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


class Base(unittest.TestCase):
    """In-memory database; settings and profile put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)


class Fields(Base):
    def test_validated_unique_and_links(self):
        cid = contacts.add(name="  Sam   Poe ", email="Sam@Acme.com", company="Acme", next_touch="2026-12-01")
        c = contacts.get(cid)
        self.assertEqual((c["name"], c["email"], c["source"], c["last_touch"]), ("Sam Poe", "sam@acme.com", "manual", None))
        for bad in ({"name": ""}, {"name": "A", "email": "nope"}, {"name": "A", "next_touch": "12/01"},
                    {"name": "A", "linkedin_url": "https://evil.example/x"}, {"name": "A", "salary": "1"}):
            with self.assertRaises(SystemExit, msg=bad):
                contacts.add(**bad)
        with self.assertRaises(SystemExit) as e:
            contacts.add(name="Other", email="SAM@acme.com")
        self.assertIn("already has this email", str(e.exception))
        self.assertEqual(contacts.add(name="Li", linkedin_url="linkedin.com/in/li-x/?trk=1"), cid + 1)
        self.assertEqual(contacts.get(cid + 1)["linkedin_url"], "https://www.linkedin.com/in/li-x")
        with self.assertRaises(SystemExit):
            contacts.edit(cid, name="")
        contacts.edit(cid, position="CTO", next_touch="")
        self.assertEqual((contacts.get(cid)["position"], contacts.get(cid)["next_touch"]), ("CTO", None))
        jid = db.add_job("Acme", "Data Engineer")
        contacts.link(cid, jid, "hiring_manager")
        contacts.link(cid, jid, "referrer", keep_role=True)                    # keep_role: the first role stays
        self.assertEqual(contacts.job_people(jid)[0]["role"], "hiring_manager")
        with self.assertRaises(SystemExit):
            contacts.link(cid, jid, "boss")
        self.assertIsNone(db.get_job(jid)["contact_email"])                    # a link never sets the job's contact
        self.assertEqual(contacts.rows("acme")[0]["job_list"], f"#{jid} Acme")
        db.delete_job(jid)
        self.assertEqual((contacts.rows()[0]["jobs"], contacts.get(cid)["name"]), (0, "Sam Poe"))  # the person stays
        contacts.remove(cid)
        with self.assertRaises(SystemExit):
            contacts.get(cid)

    def test_job_contacts_move_once(self):
        c = db._local.con
        for company, email, name in (("Acme", "r@acme.com", "Rita"), ("Acme", "R@acme.com ", ""), ("Globex", None, "Gus")):
            jid = c.execute("INSERT INTO jobs(company,title,contact_email,contact_name) VALUES(?,?,?,?)",
                            (company, "Role", email, name)).lastrowid
        c.execute("INSERT INTO jobs(company,title) VALUES('Hooli','No contact')")
        c.execute("DELETE FROM seen WHERE key=?", (db.CONTACTS_KEY,))
        self.assertEqual(db.contacts_from_jobs(c), 2)                           # one per address, else per name + company
        rows = {r["name"]: r for r in contacts.rows()}
        self.assertEqual((rows["Rita"]["email"], rows["Rita"]["jobs"], rows["Gus"]["email"]), ("r@acme.com", 2, None))
        self.assertEqual({p["role"] for p in contacts.job_people(jid)}, {"recruiter"})
        self.assertEqual(db.contacts_from_jobs(c), 0)                           # the marker: done once
        c.execute("DELETE FROM seen WHERE key=?", (db.CONTACTS_KEY,))
        self.assertEqual((db.contacts_from_jobs(c), len(contacts.rows())), (0, 2))  # and a rerun duplicates nothing
        self.assertEqual(db.get_job(jid)["contact_name"], "Gus")                # the job columns are untouched

    def test_job_contacts_move_once_under_parallel_first_connections(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "t.db")
            c = db.connect(path)
            for i in range(30):
                c.execute("INSERT INTO jobs(company,title,contact_email,contact_name) VALUES(?,?,?,?)",
                          (f"Co{i}", "Role", f"r{i}@co{i}.com", "" if i % 2 else f"Name {i}"))
            c.execute("INSERT INTO jobs(company,title,contact_name) VALUES('Hooli','Role','Gus')")  # name-only: no unique index
            c.execute("DELETE FROM seen WHERE key=?", (db.CONTACTS_KEY,))
            c.commit(); c.close()
            errors, gate = [], threading.Barrier(6)

            def first_connection():
                try:
                    gate.wait(); db.connect(path).close()
                except Exception as e:
                    errors.append(e)
            ts = [threading.Thread(target=first_connection) for _ in range(6)]
            [t.start() for t in ts]; [t.join() for t in ts]
            c = db.connect(path)
            n = c.execute("SELECT COUNT(*) n FROM contacts").fetchone()["n"]
            links = c.execute("SELECT COUNT(*) n FROM job_contacts").fetchone()["n"]
            c.close()
        self.assertEqual((errors, n, links), ([], 31, 31))


class Import(Base):
    def test_connections_preamble_zip_and_dedupe(self):
        known = contacts.add(name="Robert Ray", email="bob@globex.com", company="Globex", notes="met at PyCon")
        n = contacts.import_connections(CSV.encode("utf-8-sig"), "Connections.csv")
        self.assertEqual(n, {"rows": 5, "added": 3, "updated": 1, "skipped": 1})
        rows = {(r["name"], r["position"]): r for r in contacts.rows()}
        ann = rows[("Ann Lee", "Data Lead")]
        self.assertEqual((ann["company"], ann["linkedin_url"], ann["source"]), ("Acme, Inc.", "https://www.linkedin.com/in/ann-lee", "linkedin"))
        self.assertIn("15 Oct 2023", ann["how_met"])
        bob = contacts.get(known)                                                # matched by email: blanks filled, edits kept
        self.assertEqual((bob["name"], bob["notes"], bob["linkedin_url"], bob["position"]),
                         ("Robert Ray", "met at PyCon", "https://www.linkedin.com/in/bob-ray", "Recruiter"))
        self.assertIn(("Cy Ng", "Manager"), rows)                                # same name + company, different URL: two people
        self.assertTrue(all(r["next_touch"] is None for r in contacts.rows()))  # cadence is opt-in
        self.assertEqual(contacts.due(), [])
        again = contacts.import_connections(zipped("Basic_LinkedInDataExport/Connections.csv", CSV), "export.zip")
        self.assertEqual((again["added"], again["updated"], len(contacts.rows())), (0, 0, 4))
        contacts.edit(rows[("Ann Lee", "Data Lead")]["id"], linkedin_url="")    # no URL left: name + company still matches
        self.assertEqual(contacts.import_connections(CSV.encode(), "c.csv")["added"], 0)
        with self.assertRaises(SystemExit):
            contacts.import_connections(zipped("Profile.csv", "First Name\nJane"), "export.zip")
        with self.assertRaises(SystemExit):
            contacts.import_connections(b"name,email\nx,y", "people.csv")

    def test_profile_import_ignores_connections(self):
        data = zipped("Skills.csv", "Name\nPython\n")
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, "a") as z:
            z.writestr("Connections.csv", CSV)
        facts = profile.linkedin_facts(buf.getvalue())
        self.assertEqual([s["name"] for s in facts["skills"]], ["Python"])
        self.assertEqual(contacts.rows(), [])


class Trust(Base):
    """A contact's address, company or job link must not change any mail decision."""

    def test_imported_contact_never_trusted_or_job_contact(self):
        settings.set_tool("email_classify", auto=True)
        jid = db.add_job("Globex", "Data Engineer"); db.set_status(jid, "applied")
        base = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Interview",
                "sender_name": "X", "message_id": "<m>", "body": "b", "dkim_pass": True}
        senders = ("x@gmail.com", "jane@agency.com")
        before = [em._match(base | {"sender_email": s}) for s in senders]
        contacts.import_connections(("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                                     "X,Y,https://www.linkedin.com/in/xy,x@gmail.com,Globex,Recruiter,1 Jan 2024\n").encode(), "c.csv")
        jane = contacts.add(name="Jane", email="jane@agency.com", company="Globex")
        for c in contacts.rows():
            contacts.link(c["id"], jid, "recruiter")                            # even linked as the job's recruiter
        self.assertEqual([em._match(base | {"sender_email": s}) for s in senders], before)
        real = (em.ai.ask_json, em.notify)
        em.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        em.notify = lambda *a, **k: None
        try:
            for s in senders:
                info = base | {"from": s, "sender_email": s}
                em._apply(info, dry=False)
                self.assertFalse(info["trusted"], s)
        finally:
            em.ai.ask_json, em.notify = real
        job = db.get_job(jid)
        self.assertEqual((job["status"], job["contact_email"], job["contact_name"]), ("applied", None, None))
        self.assertTrue(all(r["status"] == "pending" for r in db.list_pending()))  # every proposal waits for you
        self.assertIsNone(contacts.get(jane)["last_touch"])                     # _apply decides; it does not touch

    def test_mail_touches_contact_by_exact_address(self):
        cid = contacts.add(name="Jane", email="jane@acme.com")
        other = contacts.add(name="Jo", email="jo@acme.com")

        class Box:  # minimal IMAP stand-in
            def login(self, *a): pass
            def select(self, *a, **k): pass
            def logout(self): pass
            def uid(self, op, *a):
                if op == "search":
                    return "OK", [b"9"]
                return "OK", [(b"9", b"From: Jane <JANE@acme.com>\r\nSubject: hi\r\nDate: Mon, 02 Nov 2026 10:00:00 +0000\r\n"
                                     b"Content-Type: text/plain\r\n\r\nlunch?")]
        real = (imaplib.IMAP4_SSL, em.setting, em.classify)
        imaplib.IMAP4_SSL = lambda host, **kw: Box()
        em.setting = lambda k, d=None: {"IMAP_USER": "me@x.com", "IMAP_PASS": "p"}.get(k, d)
        em.classify = lambda *a, **k: {"category": "other", "company": "", "title": "", "summary": ""}
        try:
            em.check(days=1, dry=True)
            self.assertIsNone(contacts.get(cid)["last_touch"])                  # a dry run changes nothing
            em.check(days=1)
        finally:
            imaplib.IMAP4_SSL, em.setting, em.classify = real
        self.assertEqual((contacts.get(cid)["last_touch"], contacts.get(other)["last_touch"]), ("2026-11-02", None))
        self.assertEqual(contacts.touch("jane@acme.com", "2026-10-01"), 0)     # never moved back
        self.assertEqual(contacts.touch("jane@acme.com", "2999-01-01"), 1)     # never in the future
        self.assertEqual(contacts.get(cid)["last_touch"], date.today().isoformat())
        contacts.edit(cid, last_touch="2026-01-01")
        real_send = approvals.send_email
        approvals.send_email = lambda *a, **k: None
        try:
            self.assertIn("sent to", approvals._send({"to": "Jane@Acme.com", "subject": "s", "body": "b"}))
        finally:
            approvals.send_email = real_send
        self.assertEqual(contacts.get(cid)["last_touch"], date.today().isoformat())


class Today(Base):
    def test_due_contacts_surface_and_clear(self):
        today, yday = date.today(), (date.today() - timedelta(days=1)).isoformat()
        cid = contacts.add(name="Due Dan", company="Acme", next_touch=yday)
        contacts.add(name="Later Liz", next_touch=(today + timedelta(days=5)).isoformat())
        contacts.add(name="Never Ned")
        self.assertEqual([c["name"] for c in contacts.due()], ["Due Dan"])
        self.assertEqual(loop.agenda()["contacts"], [{"id": cid, "name": "Due Dan", "company": "Acme", "when": yday}])
        self.assertEqual([c["name"] for c in contacts.rows(due_only=True)], ["Due Dan"])
        n = len(db.list_pending())
        contacts.edit(cid, last_touch=today.isoformat())                        # in touch since: off the list
        self.assertEqual((contacts.due(), loop.agenda()["contacts"]), ([], []))
        self.assertEqual(len(db.list_pending()), n)                             # surfaced only: nothing drafted


class Warm(Base):
    def test_company_match_on_board_and_search(self):
        from lodestar import web

        amz = contacts.add(name="Al", company="Amazon", position="SDE")
        acme = contacts.add(name="Bea", company="ACME Inc.")
        contacts.add(name="Cid", company="First National Bank")
        contacts.add(name="Dee")
        self.assertEqual([p["id"] for p in contacts.warm("Amazon Web Services")], [amz])
        self.assertEqual([p["id"] for p in contacts.warm("Acme, Inc.")], [acme])
        self.assertEqual(contacts.warm("National Grid"), [])
        self.assertEqual(contacts.warm(""), [])
        found = contacts.with_warm([{"company": "Amazon"}, {"company": "Hooli"}])
        self.assertEqual(([p["name"] for p in found[0]["warm"]], found[1]["warm"]), (["Al"], []))
        jid = db.add_job("Acme", "Data Engineer")
        self.assertEqual(web._job_view(db.get_job(jid), contacts.warm_index())["warm"],
                         [{"id": acme, "name": "Bea", "position": ""}])


class Referral(Base):
    def test_referral_goes_to_the_contact_and_waits(self):
        PROFILE.write_text(REAL_PROFILE, encoding="utf-8")
        jid = db.add_job("Acme", "Data Engineer", jd="Python")
        db.update_job(jid, contact_email="recruiter@acme.com")
        friend = contacts.add(name="Bea", email="bea@acme.com", company="Acme", position="Staff Engineer")
        noemail = contacts.add(name="Cid", company="Acme")
        prompts, real = [], (extras.ai.ask_json, extras.ai.ask)
        extras.ai.ask_json = lambda p, *a, **k: prompts.append(p) or {"subject": "Referral?", "body": "Hi Bea"}
        extras.ai.ask = lambda p, *a, **k: prompts.append(p) or "Hi Cid, would you refer me?"
        settings.set_tool("email_reply", auto=True)                             # even on auto, a referral ask waits
        try:
            r = contacts.referral(db.get_job(jid), friend)
            self.assertEqual(r["proposal"]["status"], "pending")
            p = json.loads(db.get_pending(r["proposal"]["id"])["payload"])
            self.assertEqual(p["to"], "bea@acme.com")                           # the contact, not the job's recruiter
            self.assertIn("referral", prompts[0]); self.assertIn("Bea, Staff Engineer", prompts[0])
            self.assertNotIn("Preferences", prompts[0])
            note = contacts.referral(db.get_job(jid), noemail)
            self.assertEqual(note, {"text": "Hi Cid, would you refer me?"})      # no address: a note you send yourself
        finally:
            extras.ai.ask_json, extras.ai.ask = real
        self.assertEqual({p["name"]: p["role"] for p in contacts.job_people(jid)}, {"Bea": "referrer", "Cid": "referrer"})
        self.assertEqual(db.get_job(jid)["contact_email"], "recruiter@acme.com")


class Cli(Base):
    def cli(self, *argv) -> str:
        a = build().parse_args(list(argv))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            a.f(a)
        return out.getvalue()

    def test_contacts_commands_and_job_contact_field(self):
        self.assertIn("added contact #1", self.cli("contacts", "add", "Sam Poe", "--email", "sam@acme.com", "--company", "Acme"))
        jid = db.add_job("Acme", "Data Engineer")
        self.assertIn("as referrer", self.cli("contacts", "link", "1", str(jid), "--role", "referrer"))
        self.assertIn(f"#{jid} Acme", self.cli("contacts", "list", "acme"))
        self.assertIn("next_touch=2000-01-01", self.cli("contacts", "edit", "1", "next_touch=2000-01-01", "how_met=PyCon"))
        self.assertIn("Sam Poe", self.cli("contacts", "due"))
        self.assertIn("Sam Poe", self.cli("today"))
        with self.assertRaises(SystemExit):
            self.cli("contacts", "edit", "1", "colour=red")
        self.assertIn("referrer", self.cli("contacts", "show", "1"))
        # the job's own contact field files the person too: a known address keeps its record and role
        self.assertIn("contact #1", self.cli("jobs", "contact", str(jid), "sam@acme.com", "--name", "Sam"))
        self.assertIn("contact #2", self.cli("jobs", "contact", str(jid), "rita@acme.com", "--name", "Rita"))
        self.assertEqual({p["name"]: p["role"] for p in contacts.job_people(jid)}, {"Sam Poe": "referrer", "Rita": "recruiter"})
        with self.assertRaises(SystemExit):
            self.cli("jobs", "contact", str(jid), "not-an-address")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "Connections.csv"
            f.write_text(CSV, encoding="utf-8")
            self.assertIn("4 added", self.cli("contacts", "import", str(f)))
        self.assertIn("unlinked", self.cli("contacts", "link", "1", str(jid), "--remove"))
        self.assertIn("removed contact #1", self.cli("contacts", "rm", "1"))


class Routes(unittest.TestCase):
    def test_contact_routes(self):
        import base64
        import http.client
        from lodestar import desktop, web

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        port = desktop.free_port(8920); srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        jid, ids = None, []
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            def call(path, body=None, headers=h):
                c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse(); return r.status, json.loads(r.read())
            jid = db.add_job("Zzacme", "Go Dev")
            st, r = call("/api/contacts", {"name": "Zed <script>", "company": "Zzacme", "email": "zed@zzacme.com"})
            self.assertEqual(st, 200); ids.append(r["id"])
            self.assertEqual(call("/api/contacts", {"name": "X", "role": "admin"})[0], 400)    # unknown keys refused
            self.assertEqual(call("/api/contacts", {"name": "X"}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            self.assertEqual(call(f"/api/contacts/{ids[0]}/link", {"job_id": jid, "role": "referrer"})[0], 200)
            self.assertEqual(call(f"/api/contacts/{ids[0]}/link", {"job_id": jid, "role": "boss"})[0], 400)
            self.assertEqual(call(f"/api/contacts/{ids[0]}/edit", {"next_touch": "tomorrow"})[0], 400)
            st, r = call(f"/api/jobs/{jid}")
            self.assertEqual(([p["role"] for p in r["people"]], [p["name"] for p in r["warm"]]), (["referrer"], ["Zed <script>"]))
            st, r = call(f"/api/contacts/{ids[0]}")
            self.assertEqual((r["contact"]["email"], r["jobs"][0]["id"]), ("zed@zzacme.com", jid))
            self.assertIn(ids[0], [x["id"] for x in call("/api/contacts")[1]["contacts"]])
            s = call("/api/state")[1]
            self.assertEqual(next(x for x in s["jobs"] if x["id"] == jid)["warm"][0]["id"], ids[0])
            self.assertIn("referrer", s["contact_roles"])
            st, r = call(f"/api/jobs/{jid}/contact", {"name": "Rita", "email": "rita@zzacme.com"})
            ids.append(r["contact_id"])
            self.assertEqual(db.get_job(jid)["contact_email"], "rita@zzacme.com")
            data = base64.b64encode(("First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
                                     "Zz,Top,https://www.linkedin.com/in/zz-top-test,,Zzacme,CEO,1 Jan 2024\n").encode()).decode()
            tid = call("/api/run/contacts_import", {"name": "Connections.csv", "data": data})[1]["task"]
            for _ in range(50):
                t = call(f"/api/tasks/{tid}")[1]
                if t["status"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(t["result"]["added"], 1, t)
            ids += [x["id"] for x in contacts.rows("zz top")]
            self.assertEqual(call(f"/api/contacts/{ids[0]}/delete", {})[0], 200)
            self.assertEqual(call(f"/api/contacts/{ids[0]}")[0], 500)
            c.close()
        finally:
            srv.shutdown()
            if jid:
                db.delete_job(jid)
            for i in ids:
                with contextlib.suppress(SystemExit):
                    contacts.remove(i)
            db._local.con.close()
            db._local.con = saved


if __name__ == "__main__":
    unittest.main()
