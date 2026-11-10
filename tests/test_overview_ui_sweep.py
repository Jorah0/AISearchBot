"""Overview fixes, UI sweep: Add job refuses an empty card and reads company and title from a link's page title, blank
notes are refused and a blank 'set JD' asks first, the drawer keeps Tab inside and asks before Esc drops typed text,
an empty profile is never saved and unsaved edits warn on leave, the Obsidian export names its folder and writes valid
properties, the vault refuses empty entries and hides the mail connection's own, preferences carry labels and help,
the narrow layout keeps the nav on one row, one no-key message, the emailed digest falls back to your mailbox, Check
email says why other mail waited; plus the small improvements (offline referral ask, readable gap check, board
'no match' with Clear filters, a 'choose a job' placeholder, 'already on your Board'). No network: fetch, AI, mail
and keyring are faked; every patched attribute is put back."""
import contextlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, config, contacts, db, email_monitor, extras, ideas, profile, settings, util, vault, web  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "lodestar" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
REAL = ("# Jane Example\nJane Example | Austin | jane@example.com\n\n## Summary\nData engineer with 7 years of pipelines.\n\n"
        "## Skills\n- Python, SQL, Scala\n\n## Experience\n### Senior Data Engineer - Initrode Analytics (2021-03 - Present)\n"
        "- Cut pipeline failures 60%\n\n## Education\nBSc Computer Science, Colorado State University, 2017\n\n"
        "## Certifications\n- AWS Certified Data Analytics - Specialty\n\n## Preferences\nSalary floor: $187,654\n")
PAGE = ("<html><head><title>Senior Data Engineer - Example Corp | Careers</title></head><body><h1>Senior Data Engineer</h1>"
        "<p>Python, SQL and dbt. Remote (US). $140,000 - $160,000.</p></body></html>")


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def env(**values):
    """setting() stand-in: only these values, never the real vault or environment."""
    return lambda k, d=None: values.get(k, d)


def node_eval(code: str) -> str:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not installed")
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr)
    return out.stdout


class Base(unittest.TestCase):
    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.snap = {p: p.read_bytes() for p in (PROFILE, profile.BANK, settings.PATH, vault.INDEX) if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(REAL, encoding="utf-8")

    def tearDown(self):
        c = getattr(db._local, "con", None)
        if c is not None:
            c.close()
        db._local.con = self._con
        for p in (PROFILE, profile.BANK, settings.PATH, vault.INDEX):
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)


class WebPaths(unittest.TestCase):
    """Through the real HTTP routes (file database in the temp home, as the server threads use)."""

    def setUp(self):
        from lodestar import desktop

        self._con = getattr(db._local, "con", None)
        db._local.con = None
        self.snap = PROFILE.read_bytes() if PROFILE.is_file() else None
        PROFILE.write_text(REAL, encoding="utf-8")
        self.port = desktop.free_port(8890)
        self.srv = web.start_server(self.port)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        db.release()
        db._local.con = self._con
        PROFILE.write_bytes(self.snap) if self.snap is not None else PROFILE.unlink(missing_ok=True)

    def call(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", path, json.dumps(body), {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN,
                                                     "Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        return r.status, json.loads(r.read())

    def test_add_job_needs_something_and_a_link_fills_company_and_title(self):  # ui-sweep-01
        st, r = self.call("/api/jobs", {"company": " ", "title": "", "jd": ""})
        self.assertEqual(st, 400)
        self.assertIn("company and title", r["error"])
        with patched(util, fetch=lambda url, **k: PAGE):
            st, r = self.call("/api/jobs", {"company": "", "title": "", "jd": "https://example.com/careers/sde-42"})
        self.assertEqual(st, 200, r)
        j = db.get_job(r["id"])
        self.assertEqual((j["company"], j["title"], j["url"]), ("Example Corp", "Senior Data Engineer", "https://example.com/careers/sde-42"))
        self.assertIn("Python, SQL and dbt", j["jd"])
        self.assertNotIn("<title>", j["jd"])
        with patched(util, fetch=lambda url, **k: PAGE):  # what you typed wins over the page title
            st, r2 = self.call("/api/jobs", {"company": "Acme", "title": "", "jd": "https://example.com/careers/sde-43"})
        self.assertEqual((db.get_job(r2["id"])["company"], db.get_job(r2["id"])["title"]), ("Acme", "Senior Data Engineer"))
        for jid in (r["id"], r2["id"]):
            db.delete_job(jid)

    def test_blank_note_is_refused_and_set_jd_asks_before_clearing(self):  # ui-sweep-17
        jid = db.add_job("Acme", "Engineer", jd="Python and SQL")
        st, r = self.call(f"/api/jobs/{jid}/note", {"text": "   "})
        self.assertEqual(st, 400)
        self.assertIn("type a note", r["error"])
        self.assertNotIn("note", [e["kind"] for e in db.events(jid)])
        st, _ = self.call(f"/api/jobs/{jid}/note", {"text": "  called Sam  "})
        self.assertEqual((st, db.get_job(jid)["notes"]), (200, "called Sam"))
        admin = re.search(r"^async function jobAdmin\(.*?^}", JS, re.M | re.S).group(0)
        self.assertIn("confirm('Clear the stored job description", admin)  # a blank 'set JD' asks before wiping
        self.assertIn("r.error", admin)  # and errors are shown, not swallowed
        self.assertIn("jobAdmin('jd'", JS)
        self.assertIn("jobAdmin('note'", JS)
        db.delete_job(jid)

    def test_empty_profile_save_is_refused_at_the_route(self):  # ui-sweep-44
        st, r = self.call("/api/profile", {"text": "  \n "})
        self.assertEqual(st, 400)
        self.assertIn("empty profile", r["error"])
        self.assertEqual(PROFILE.read_text(encoding="utf-8"), REAL)


class Profile(Base):
    def test_empty_profile_is_never_saved_and_unsaved_edits_warn_on_leave(self):  # ui-sweep-44
        with self.assertRaises(SystemExit):
            profile.write_master("")
        self.assertEqual(PROFILE.read_text(encoding="utf-8"), REAL)
        self.assertRegex(JS, r"addEventListener\('beforeunload'[^\n]*\n[^\n]*\$\('#pText'\)\.value !== PROFILE_LOADED")

    def test_rebuild_from_an_empty_bank_keeps_the_whole_hand_typed_profile(self):  # ui-sweep-47
        profile.rebuild_master()
        out = PROFILE.read_text(encoding="utf-8")
        for fact in ("Initrode Analytics", "Cut pipeline failures 60%", "Data engineer with 7 years", "Colorado State",
                     "Scala", "AWS Certified Data Analytics", "Salary floor: $187,654"):
            self.assertIn(fact, out)


class Drawer(unittest.TestCase):
    def test_drawer_keeps_tab_focus_and_asks_before_esc_discards_edits(self):  # ui-sweep-08, ui-sweep-61
        keys = re.search(r"^document\.addEventListener\('keydown'.*?^}\);", JS, re.M | re.S).group(0)
        self.assertIn("e.key === 'Escape'", keys)
        self.assertIn("drawerDirty()", keys)
        self.assertIn("confirm(", keys)  # typed text is never dropped by Esc without asking
        self.assertIn("e.key !== 'Tab'", keys)
        self.assertIn("preventDefault(); (e.shiftKey ? last : first).focus()", keys)  # focus wraps inside the drawer
        dirty = re.search(r"^function drawerDirty\(\) \{.*?^}", JS, re.M | re.S).group(0)
        self.assertIn("ed.value !== (cur.docs[ed.dataset.name] || '')", dirty)  # an unsaved document editor counts
        self.assertIn("e.value !== e.defaultValue", dirty)


class Obsidian(Base):
    def test_obsidian_export_quotes_properties_and_the_ui_names_the_folder(self):  # ui-sweep-32
        jid = db.add_job('Quote "Co"', 'Lead: Data <b>Eng</b> " onmouseover="x', url="https://e.co/j?a=1#b")
        tmp = tempfile.mkdtemp(prefix="obsidian-")
        try:
            with patched(config, setting=env(OBSIDIAN_VAULT=tmp)):
                self.assertEqual(extras.vault_root(), Path(tmp))  # Setup > Vault (or the environment) chooses the vault
                out = extras.export_obsidian("jobs")
            note = next(out.glob(f"{jid}-*.md")).read_text(encoding="utf-8")
            props = dict(ln.split(": ", 1) for ln in note.split("---")[1].strip().splitlines())
            self.assertEqual(json.loads(props["company"]), 'Quote "Co"')
            self.assertEqual(json.loads(props["title"]), 'Lead: Data <b>Eng</b> " onmouseover="x')
            self.assertEqual(json.loads(props["url"]), "https://e.co/j?a=1#b")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        with patched(config, setting=env(OBSIDIAN_VAULT=tmp)), patched(ai, available=lambda: []):
            self.assertEqual(web.state()["obsidian_dir"], str(Path(tmp) / "jobs"))
        fn = re.search(r"^function exportObsidian\(btn\) \{.*?^}", JS, re.M | re.S).group(0)
        self.assertIn("if (!confirm(", fn)
        self.assertIn("S.obsidian_dir", fn)
        self.assertIn('onclick="exportObsidian(this)"', HTML)


class Vault(Base):
    def test_vault_refuses_empty_entries_and_hides_the_mail_connection(self):  # ui-sweep-52
        store = {}
        k = vault.keyring
        with patched(k, set_password=lambda s, n, v: store.__setitem__((s, n), v)):
            for name, secret in (("", ""), ("  ", "x"), ("ANTHROPIC_API_KEY", "")):
                with self.assertRaises(ValueError):
                    vault.set(name, secret)
            self.assertEqual(store, {})
            for n in ("IMAP_USER", "IMAP_PASS", "EMAIL_PRESET", "IMAP_HOST", "SMTP_PORT", "OPENAI_API_KEY", "OBSIDIAN_VAULT"):
                vault.set(n, "v")
        with patched(ai, available=lambda: []):
            names = [v["name"] for v in web.state()["vault"]]
        # Connect email / Disconnect manage the mail entries; linked AI keys show on the Link an AI key card
        self.assertEqual(names, ["OBSIDIAN_VAULT"])


class Prefs(Base):
    def test_preferences_have_labels_and_help_and_switches_have_names(self):  # ui-sweep-49, ui-sweep-61
        self.assertEqual(set(settings.PREF_HELP), set(settings.PREFS))
        self.assertTrue(all(label and help_ for label, help_ in settings.PREF_HELP.values()))
        with patched(ai, available=lambda: []):
            self.assertEqual(web.state()["pref_help"], settings.PREF_HELP)
        tools = re.search(r"^function renderTools\(\) \{.*?^}", JS, re.M | re.S).group(0)
        self.assertIn('aria-label="${esc(t.tool)} enabled"', tools)
        self.assertIn('aria-label="${esc(t.tool)} auto"', tools)
        self.assertEqual(tools.count('aria-labelledby="pl${i}"'), 4)  # select, checkbox, map entry and text field
        self.assertIn("S.pref_help", tools)
        self.assertIn('<select aria-label="status of this idea"', JS)


class Layout(unittest.TestCase):
    def test_narrow_window_keeps_the_nav_on_one_row(self):  # ui-sweep-60
        narrow = CSS.split("@media (max-width: 600px)", 1)[1].split("\n}\n", 1)[0]
        self.assertRegex(narrow, r"nav \{[^}]*flex-wrap: nowrap;[^}]*overflow-x: auto")
        self.assertIn("nav button { flex: none;", narrow)


class NoKey(Base):
    def test_one_no_key_message_points_to_setup(self):  # ui-sweep-64
        with patched(ai, available=lambda: [], setting=env()):
            with self.assertRaises(SystemExit) as e:
                ai.default_provider()
        self.assertIn("Setup > Link an AI key", str(e.exception))
        self.assertIn("No AI provider configured", str(e.exception))
        with patched(ai, council_providers=lambda: []):
            with self.assertRaises(SystemExit) as e:
                ideas.craft("strategy")
        self.assertEqual(str(e.exception), ai.NO_PROVIDER)  # not 'check `lodestar providers --test`'
        with self.assertRaises(SystemExit) as e:
            ideas.craft("custom")
        self.assertNotIn("lodestar ideas craft", str(e.exception))
        self.assertIn("OPTS.ai ? HOWS.map(", JS)  # offline options show no rewrite chips that can only fail
        self.assertIn("${mail && hasAI() ?", JS)

    def test_check_email_says_why_untied_mail_was_not_classified(self):  # ui-sweep-33
        with patched(email_monitor, check=lambda *a, **k: []), patched(ai, available=lambda: []):
            r = web._act("email_check", {})
        self.assertIn("Setup > Link an AI key", r["note"])
        with patched(email_monitor, check=lambda *a, **k: []), patched(ai, available=lambda: ["anthropic"]):
            self.assertEqual(web._act("email_check", {})["note"], "")
        self.assertIn("r.note?'\\n'+r.note:''", HTML)


class Digest(Base):
    def test_email_digest_goes_to_the_connected_mailbox_by_default(self):  # ui-sweep-31
        sent = []
        with patched(util, send_email=lambda to, subject, body, *a, **k: sent.append(to)), \
                patched(config, setting=env(IMAP_USER="jane@example.com")), patched(ai, available=lambda: []):
            extras.digest(7, send=True)
        self.assertEqual(sent, ["jane@example.com"])
        with patched(util, send_email=lambda *a, **k: sent.append(a)), patched(config, setting=env()), \
                patched(ai, available=lambda: []):
            with self.assertRaises(SystemExit) as e:
                extras.digest(7, send=True)
        self.assertIn("Setup > Connect email", str(e.exception))
        self.assertEqual(len(sent), 1)


class Improvements(Base):
    def test_referral_ask_without_a_provider_uses_the_plain_template(self):  # ui-sweep-10
        jid = db.add_job("Acme", "Data Engineer")
        with_mail = contacts.add(name="Chris Ng", email="chris@acme.example", company="Acme")
        no_mail = contacts.add(name="Pat Lee", company="Acme")
        with patched(ai, available=lambda: [], ask=None, ask_json=None):  # any AI call would fail loudly
            r = contacts.referral(db.get_job(jid), with_mail)
            note = contacts.referral(db.get_job(jid), no_mail)
        self.assertEqual(r["proposal"]["status"], "pending")  # always reviewed in the Inbox
        p = json.loads(db.get_pending(r["proposal"]["id"])["payload"])
        self.assertEqual(p["to"], "chris@acme.example")
        self.assertIn("Hello Chris Ng", p["body"])
        self.assertIn("referring me", p["body"])
        self.assertIn("Data Engineer position at Acme", note["text"])

    def test_gap_check_reads_as_text(self):  # ui-sweep-13
        fn = re.search(r"^function gapText\(g\) \{.*?^}", JS, re.M | re.S).group(0)
        g = {"verdict": "stretch", "why": "missing Kubernetes", "match_score": 69, "missing_keywords": ["kubernetes", "terraform"],
             "weak_areas": ["Kubernetes"], "suggestions": ["Mention Docker work"], "red_flags": [], "salary_in_posting": ["$150,000"],
             "market_range": {"low": 140000, "high": 170000, "city": "*"}}
        out = node_eval(f"{fn}\nprocess.stdout.write(gapText({json.dumps(g)}) + '\\n---\\n' + gapText({json.dumps({'match_score': 40, 'note': 'no AI provider configured'})}));")
        self.assertTrue(out.startswith("Verdict: stretch - missing Kubernetes\nJD coverage: 69% (missing: kubernetes, terraform)"), out)
        self.assertIn("Suggestions:\n- Mention Docker work", out)
        self.assertNotIn("Red flags", out)
        self.assertNotIn("{", out)
        self.assertIn("---\nno AI provider configured\nJD coverage: 40%", out)
        self.assertIn("r.gap ? gapText(r.gap)", JS)

    def test_board_no_match_link_placeholder_and_already_tracked(self):  # ui-sweep-04, ui-sweep-21, ui-sweep-25
        self.assertIn('id="filterEmpty"', HTML)
        self.assertIn('onclick="clearFilters()"', HTML)
        self.assertIn("$('#filterEmpty').style.display = S.jobs.length && !jobs.length ? '' : 'none';", JS)
        clear = re.search(r"^function clearFilters\(\) \{.*?^}", JS, re.M | re.S).group(0)
        self.assertIn("saveView()", clear)  # the remembered filter is cleared too, not only the inputs
        self.assertIn('<option value="">choose a job…</option>${jobs}', JS)
        self.assertIn("if(!$('#ml${id}').value)return toast('choose the job first','err')", JS)
        self.assertIn("(j.tracked ? 'already on your Board as #' : 'tracked as #') + r.id", JS)


if __name__ == "__main__":
    unittest.main()
