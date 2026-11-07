"""Offline self-checks: no network, no keyring writes. Run: python -m unittest -v"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, db, email_monitor, resume, util, web_monitor  # noqa: E402
from lodestar.cli import build  # noqa: E402


class Util(unittest.TestCase):
    def test_strip_html(self):
        t = util.strip_html("<html><head><style>x{}</style></head><body><h1>Hi</h1><script>bad()</script><p>a  b</p><li>c</li></body></html>")
        self.assertEqual(t.splitlines()[0], "Hi")
        self.assertIn("a b", t)
        self.assertNotIn("bad()", t)

    def test_extract_json(self):
        self.assertEqual(util.extract_json('Sure!\n```json\n{"a": [1, 2]}\n```\nthanks'), {"a": [1, 2]})
        self.assertEqual(util.extract_json('[{"i":0}]'), [{"i": 0}])
        with self.assertRaises(ValueError):
            util.extract_json("no json here")

    def test_slug(self):
        self.assertEqual(util.slug("Acme, Inc. / Backend!"), "acme-inc-backend")


class Tracker(unittest.TestCase):
    def test_flow(self):
        db._local.con = db.connect(":memory:")  # isolate from other test classes sharing the module-level connection
        jid = db.add_job("Acme Corp", "Backend Engineer", "https://x", "jd text")
        self.assertEqual(db.get_job(jid)["status"], "saved")
        db.set_status(jid, "applied")
        self.assertIsNotNone(db.get_job(jid)["applied_at"])
        db.set_status(jid, "interview", "phone screen")
        self.assertEqual(db.find_job_by_company("careers@acme.com")["id"], jid)
        self.assertIsNone(db.find_job_by_company("ab"))
        s = db.stats()
        self.assertEqual(s["counts"]["interview"], 1)
        self.assertEqual(s["interview_rate"], 1.0)
        self.assertEqual([e["kind"] for e in db.events(jid)], ["created", "status", "status"])
        self.assertEqual(db.needs_followup(7), [])  # just touched
        db.add_watch("https://example.com/careers", "python")
        self.assertEqual(len(db.watches()), 1)
        self.assertFalse(db.seen("k"))
        db.mark_seen("k")
        self.assertTrue(db.seen("k"))


class Email(unittest.TestCase):
    def test_relevance_and_apply(self):
        self.assertTrue(email_monitor.looks_relevant("Next steps for your application", "hr@foo.com", ""))
        self.assertFalse(email_monitor.looks_relevant("Your weekly digest", "news@foo.com", "deals deals"))
        jid = db.add_job("Globex", "Data Engineer", "https://globex.com/jobs/relevance")
        db.set_status(jid, "applied")
        info = {"category": "interview", "company": "Globex", "summary": "invite", "action": "reply", "subject": "Interview",
                "from": "x@globex.com", "sender_email": "x@globex.com", "dkim_pass": True}  # authenticated company mail may move a job under the auto default
        email_monitor._apply(info, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "interview")
        # a later "application received" must not downgrade
        email_monitor._apply(info | {"category": "application_received"}, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "interview")
        # outreach about a company you do not track waits for you: nothing Lodestar holds ties initech.com to Initech
        # (initech.xyz could say the same), so the job is proposed, not created (pass 16 review)
        before = len(db.list_jobs())
        email_monitor._apply({"category": "recruiter_outreach", "company": "Initech", "title": "SRE", "summary": "hi", "action": None,
                              "subject": "Opportunity", "from": "r@initech.com", "sender_email": "r@initech.com", "dkim_pass": True}, dry=False)
        self.assertEqual(len(db.list_jobs()), before)
        self.assertTrue(any(r["kind"] == "add_job" and "Initech" in r["summary"] for r in db.list_pending()))


class Ai(unittest.TestCase):
    def test_chat_shapes_and_council(self):
        calls = []

        def fake_post(url, headers, body, retries=2):
            calls.append((url, body))
            if "anthropic" in url:
                return {"content": [{"type": "text", "text": "A says: " + body["messages"][-1]["content"][:20]}]}
            return {"choices": [{"message": {"content": "O says: " + body["messages"][-1]["content"][:20]}}]}

        real_post, ai._post = ai._post, fake_post
        os.environ["OPENAI_API_KEY"] = "k"
        try:
            self.assertTrue(ai.ask("hello", system="sys", provider="anthropic").startswith("A says"))
            self.assertEqual(calls[-1][1]["system"], "sys")
            self.assertTrue(ai.ask("hello", provider="openai").startswith("O says"))
            self.assertEqual(calls[-1][1]["messages"][0]["role"], "user")
            r = ai.council("q", providers=["anthropic", "openai"])
            self.assertEqual(set(r["answers"]), {"anthropic", "openai"})
            self.assertIn("Original task", calls[-1][1]["messages"][-1]["content"])
        finally:
            ai._post = real_post  # later tests exercise the real transport
            del os.environ["OPENAI_API_KEY"]


class Resume(unittest.TestCase):
    def test_export_docx(self):
        md = Path(os.environ["LODESTAR_HOME"]) / "r.md"
        md.write_text("# Jane Doe\n## Experience\n- Built **things**\n\nPlain para\n", encoding="utf-8")
        out = resume.export_docx(md)
        self.assertTrue(out.is_file() and out.suffix == ".docx")
        from docx import Document

        texts = [p.text for p in Document(out).paragraphs]
        self.assertEqual(texts, ["Jane Doe", "Experience", "Built things", "Plain para"])


class Web(unittest.TestCase):
    def test_search_filters_and_dedupes(self):
        web_monitor.SOURCES = {
            "fake": lambda q: [
                web_monitor._listing("Python Dev", "A", "https://a/1", desc="remote python"),
                web_monitor._listing("Python Dev", "A", "https://a/1"),
                web_monitor._listing("Java Dev", "B", "https://b/2", desc="java"),
            ]
        }
        got = web_monitor.search("dev", keywords="python")
        self.assertEqual([j["url"] for j in got], ["https://a/1"])
        # a manual search marks nothing, so a watch still sees both; the watch-style call marks them
        self.assertEqual([j["url"] for j in web_monitor.search("dev", only_new=True)], ["https://a/1", "https://b/2"])
        self.assertEqual(web_monitor.search("dev", only_new=True), [])
        self.assertEqual(web_monitor.search("dev", only_new=False, mark=False)[0]["url"], "https://a/1")


class Cli(unittest.TestCase):
    def test_parser(self):
        a = build().parse_args(["jobs", "add", "Acme", "Eng", "--jd", "https://acme/jobs/1"])
        self.assertEqual((a.cmd, a.op, a.company), ("jobs", "add", "Acme"))
        a = build().parse_args(["-p", "groq", "resume", "tailor", "3", "--council", "--docx"])
        self.assertTrue(a.council and a.docx and a.provider == "groq")
        a = build().parse_args(["run", "--every", "15", "--no-email", "--once"])
        self.assertFalse(a.email)


if __name__ == "__main__":
    unittest.main()


class Extras(unittest.TestCase):
    def test_split_title(self):
        from lodestar.web import split_title
        self.assertEqual(split_title("Senior Backend Engineer - Acme | LinkedIn"), ("Senior Backend Engineer", "Acme"))
        self.assertEqual(split_title("Data Engineer - Globex - Austin, TX | Indeed.com"), ("Data Engineer", "Globex"))
        self.assertEqual(split_title("Careers"), ("Careers", ""))

    def test_ics_obsidian_variants(self):
        from datetime import datetime
        from lodestar import extras
        db._local.con = db.connect(":memory:")
        jid = db.add_job("Initech", "SRE", "https://x/1", "jd")
        out = extras.ics(db.get_job(jid), datetime(2026, 11, 12, 14, 0))
        body = out.read_text()
        self.assertIn("DTSTART:20261112T140000", body)
        self.assertIn("Prep: Initech interview", body)
        self.assertEqual(body.count("BEGIN:VEVENT"), 2)
        os.environ["OBSIDIAN_VAULT"] = os.environ["LODESTAR_HOME"]
        folder = extras.export_obsidian()
        note = (folder / "1-initech-sre.md").read_text(encoding="utf-8")
        self.assertIn("status: saved", note)
        self.assertIn("[[jobs/_index|all applications]]", note)
        self.assertIn("| [[jobs/1-initech-sre|Initech]] |", (folder / "_index.md").read_text(encoding="utf-8"))
        db.update_job(jid, resume_hash="abc12345")
        db.set_status(jid, "interview")
        self.assertEqual(db.variant_stats(), [{"variant": "abc12345", "applied": 1, "positive": 1, "rejected": 0,
                                               "response_rate": 1.0, "interview_rate": 1.0}])
        self.assertEqual(extras.resume_hash("a  b\n c"), extras.resume_hash("a b c"))

    def test_cli_new_commands_parse(self):
        a = build().parse_args(["app", "--every", "10", "--no-loop"])
        self.assertTrue(a.no_loop and a.every == 10 and a.email)
        a = build().parse_args(["ics", "3", "--when", "2026-11-12 14:00"])
        self.assertEqual(a.when, "2026-11-12 14:00")
        self.assertEqual(build().parse_args(["export", "obsidian"]).folder, "jobs")


class Automation(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text("# Jane Doe" + chr(10) + "email jane@example.com" + chr(10) + "## Preferences" + chr(10) + "Salary floor: 100k", encoding="utf-8")

    def test_settings_and_approvals(self):
        from lodestar import approvals, settings
        self.assertTrue(settings.auto("email_classify") and not settings.auto("email_reply") and settings.enabled("followup"))
        settings.set_tool("followup", enabled=False)
        self.assertEqual(approvals.propose("followup", "note", {}, "x")["status"], "disabled")
        jid = db.add_job("Acme", "Eng")
        r = approvals.propose("email_reply", "note", {"job_id": jid, "text": "hi"}, "say hi", jid)
        self.assertEqual(r["status"], "pending")
        self.assertEqual([e["kind"] for e in db.events(jid)][-1], "proposed")
        self.assertEqual(len(db.list_pending()), 1)
        done = approvals.approve(r["id"])
        self.assertEqual((done["status"], done["result"]), ("done", "noted"))
        self.assertEqual(approvals.approve(r["id"])["status"], "done")  # idempotent
        settings.set_tool("email_reply", auto=True)
        self.assertEqual(approvals.propose("email_reply", "note", {"job_id": jid, "text": "auto"}, "s", jid)["status"], "done")
        settings.set_pref("auto_track_min_score", "80")
        self.assertEqual(settings.pref("auto_track_min_score"), 80)
        with self.assertRaises(SystemExit):
            settings.set_tool("nope", enabled=True)

    def test_email_flow_proposes_status_contact_and_reply(self):
        from lodestar import email_monitor, settings
        settings.set_tool("email_classify", auto=False)
        jid = db.add_job("Globex", "Data Engineer", "https://www.globex.com/careers/flow")  # the company site ties globex.com mail
        db.set_status(jid, "applied")
        email_monitor.ai.ask_json = lambda *a, **k: {"subject": "Re: Interview", "body": "Tuesday works.", "chosen_time": "2026-11-10 10:00"}
        info = {"category": "interview", "company": "Globex", "summary": "invite", "action": "reply", "subject": "Interview",
                "from": "Jane Doe <jane@globex.com>", "sender_email": "jane@globex.com", "sender_name": "Jane Doe",
                "message_id": "<abc@globex>", "body": "Can you do Tue Nov 10 at 10am or Wed at 2pm?"}
        other = db.add_job("Initech", "SRE"); db.set_status(other, "applied")
        email_monitor._apply(info | {"company": "Initech", "category": "other_update", "from": "x <hr@initech.com>",
                                     "sender_email": "hr@initech.com", "dkim_pass": False}, dry=False)
        self.assertIsNone(db.get_job(other)["contact_email"])  # an unauthenticated sender never becomes the reply-to contact
        email_monitor._apply(info | {"dkim_pass": True}, dry=False)
        job = db.get_job(jid)
        self.assertEqual(job["status"], "applied")  # not moved yet: email_classify is manual
        self.assertEqual((job["contact_email"], job["contact_name"]), ("jane@globex.com", "Jane Doe"))
        kinds = {(r["kind"], r["tool"]) for r in db.list_pending()}
        self.assertEqual(kinds, {("set_status", "email_classify"), ("send_email", "interview_scheduling")})
        mail = next(r for r in db.list_pending() if r["kind"] == "send_email")
        p = json.loads(mail["payload"])
        self.assertEqual((p["to"], p["chosen_time"], p["in_reply_to"]), ("jane@globex.com", "2026-11-10 10:00", "<abc@globex>"))
        # no-reply senders never get a reply and never become the contact
        jid2 = db.add_job("Initech", "SRE")
        email_monitor._apply(info | {"company": "Initech", "sender_email": "no-reply@initech.com", "sender_name": ""}, dry=False)
        self.assertIsNone(db.get_job(jid2)["contact_email"])
        self.assertEqual(sum(1 for r in db.list_pending() if r["kind"] == "send_email"), 1)

    def test_parse_times_and_checklist(self):
        from lodestar import apply
        t = apply.parse_times("Could you do Tuesday, Nov 10 at 10:00 AM or 2026-11-12 14:00?")
        self.assertTrue(any("Nov 10" in x for x in t) and "2026-11-12 14:00" in t)
        jid = db.add_job("Acme", "Eng", jd="jd")
        items = {c["item"]: c["done"] for c in apply.checklist(db.get_job(jid))}
        self.assertTrue(items["Job description on file"])
        self.assertFalse(items["Resume tailored"] or items["Applied"])

    def test_cli_parses_automation_commands(self):
        self.assertEqual(build().parse_args(["tools", "set", "availability", "Mon 9-5"]).value, "Mon 9-5")
        self.assertEqual(build().parse_args(["approve", "3", "4", "--subject", "x"]).ids, [3, 4])
        self.assertEqual(build().parse_args(["answers", "ask", "2", "Why us?"]).question, "Why us?")
        self.assertTrue(build().parse_args(["jobs", "search", "q", "--auto"]).auto)


class Ideas(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text("Jane Doe | Austin, TX | jane@example.com | +1 555 000 0000 | linkedin.com/in/jane | github.com/jane", encoding="utf-8")

    def test_craft_converges_scores_and_saves(self):
        from lodestar import ideas
        calls = []
        def fake(prompt, system=None, provider=None):
            calls.append(provider)
            if "converging" in prompt:
                return [{"title": "Target fintech", "idea": "x", "why_it_works": "y", "effort": 2, "impact": 5, "fit": 80, "plan": ["a", "b"], "metric": "m", "time": "1w"},
                        {"title": "Weak", "idea": "x", "why_it_works": "y", "effort": 4, "impact": 2, "fit": 30, "plan": [], "metric": "", "time": ""}]
            if "draft ideas" in prompt:
                return [{"title": "critic idea", "idea": "c", "effort": 3, "impact": 3}]
            return [{"title": "raw", "idea": "r", "effort": 3, "impact": 3}]
        real = (ideas.ai.ask_json, ideas.ai.available, ideas.ai.default_provider)
        try:
            ideas.ai.ask_json = fake
            ideas.ai.available = lambda: ["anthropic"]
            ideas.ai.default_provider = lambda: "anthropic"
            out = ideas.craft("strategy", n=2, use_council=False, provider="anthropic")
            self.assertEqual([i["title"] for i in out], ["Target fintech", "Weak"])
            self.assertEqual(out[0]["score"], 200.0)  # 5 * 80 / 2
            self.assertEqual(len(calls), 3)  # diverge + critic + converge
            rows = ideas.rows()
            self.assertEqual((rows[0]["title"], rows[0]["status"], rows[0]["plan"]), ("Target fintech", "new", ["a", "b"]))
            db.update_idea(rows[0]["id"], status="doing")
            self.assertEqual(ideas.rows()[0]["status"], "doing")
            ideas.ai.ask_json = lambda prompt, system=None, provider=None: {"title": "Target fintech v2", "idea": "better", "why_it_works": "y", "effort": 1, "impact": 5, "fit": 90, "plan": ["a"], "metric": "m", "time": "3d"}
            r = ideas.refine(rows[0]["id"], "cheaper")
            self.assertEqual((r["title"], r["history"][0]["feedback"]), ("Target fintech v2", "cheaper"))
            with self.assertRaises(SystemExit):
                db.update_idea(rows[0]["id"], status="bogus")
        finally:  # later tests need the real ai layer
            ideas.ai.ask_json, ideas.ai.available, ideas.ai.default_provider = real

    def test_autofill_data_and_features(self):
        from lodestar import extras
        d = extras.autofill_data()
        self.assertEqual((d["first_name"], d["last_name"], d["email"], d["phone"], d["location"]), ("Jane", "Doe", "jane@example.com", "+1 555 000 0000", "Austin, TX"))
        self.assertIn("linkedin", d["linkedin"])
        a = build().parse_args(["ideas", "craft", "gap", "--role", "SRE", "--n", "5", "--single"])
        self.assertTrue(a.single and a.n == 5 and a.role == "SRE")
        self.assertTrue(build().parse_args(["features", "--markdown"]).markdown)



class Hardening(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text("Jane Doe | Austin, TX | jane@example.com | +1 555 000 0000", encoding="utf-8")

    def test_company_match_is_whole_token(self):
        jid = db.add_job("Meta", "Engineer")
        self.assertIsNone(db.find_job_by_company("metadata"))      # substring must not match
        self.assertEqual(db.find_job_by_company("meta")["id"], jid)
        self.assertEqual(db.find_job_by_company("Meta Platforms recruiting")["id"], jid)
        db.add_job("First National Bank", "Analyst")
        self.assertIsNone(db.find_job_by_company("National Grid"))  # one shared word is not a match

    def test_double_approve_sends_once_and_reject_keeps_done(self):
        from lodestar import approvals
        jid = db.add_job("Acme", "Eng")
        r = approvals.propose("email_reply", "note", {"job_id": jid, "text": "hi"}, "hi", jid)
        a, b = approvals.approve(r["id"]), approvals.approve(r["id"])
        self.assertEqual((a["status"], b["status"]), ("done", "done"))
        self.assertEqual(sum(1 for e in db.events(jid) if e["detail"] == "hi"), 1)  # the executor ran exactly once
        approvals.reject(r["id"])
        self.assertEqual(db.get_pending(r["id"])["status"], "done")

    def test_allowlist_never_widens(self):
        from lodestar import ai, settings
        settings.set_pref("council_providers", "ollama")
        with self.assertRaises(SystemExit):
            ai.council_providers()
        with self.assertRaises(SystemExit):
            ai.default_provider()

    def test_unauthenticated_mail_never_auto_executes(self):
        from lodestar import email_monitor, settings
        settings.set_tool("email_classify", auto=True)
        jid = db.add_job("Globex", "Data Engineer", "https://globex.com/jobs/hardening")
        db.set_status(jid, "applied")
        email_monitor.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        base = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Interview",
                "from": "j@globex.com", "sender_email": "j@globex.com", "sender_name": "J", "message_id": "<m>", "body": "b"}
        email_monitor._apply(base | {"dkim_pass": False}, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "applied")           # auto tool, but mail unauthenticated -> pending
        self.assertTrue(any(r["kind"] == "set_status" for r in db.list_pending()))
        email_monitor._apply(base | {"dkim_pass": True, "subject": "Interview 2"}, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "interview")         # authenticated -> auto applies

    def test_mail_authentication_is_structural_and_aligned(self):
        from lodestar import email_monitor as em
        good = ["mx.google.com; dkim=pass header.i=@globex.com header.s=sel header.d=globex.com; dmarc=pass header.from=globex.com"]
        self.assertTrue(em.mail_authenticated(good, "jane@globex.com"))
        self.assertTrue(em.mail_authenticated(good, "jane@mail.globex.com"))          # subdomain aligns
        self.assertFalse(em.mail_authenticated(good, "jane@evil.com"))               # passing result for another domain
        forged = ["mx.google.com; dkim=none; dmarc=fail header.from=globex.com", "attacker; dkim=pass header.d=globex.com"]
        self.assertFalse(em.mail_authenticated(forged, "jane@globex.com"))           # only the top-most header counts
        self.assertFalse(em.mail_authenticated(["mx; dkim=pass"], "jane@globex.com"))  # no domain, no trust
        # a stored contact from another domain blocks auto-execution even with a passing result
        jid = db.add_job("Globex", "Eng"); db.update_job(jid, contact_email="recruiter@globex.com")
        from lodestar import settings
        settings.set_tool("email_classify", auto=True); db.set_status(jid, "applied")
        em.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        info = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Hi", "from": "x@other.com",
                "sender_email": "x@other.com", "sender_name": "X", "message_id": "<m>", "body": "b", "dkim_pass": True}
        em._apply(info, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "applied")

    def test_fetch_refuses_private_hosts_and_bad_urls(self):
        from lodestar import util
        for bad in ("http://127.0.0.1:8765/api/state", "http://localhost/x", "http://169.254.169.254/latest", "file:///etc/passwd", "javascript:alert(1)"):
            with self.assertRaises(ValueError, msg=bad):
                util._check_url(bad)
        self.assertEqual(util.read_source(__file__, allow_files=False), __file__)   # paths are literal text over the API

    def test_email_failed_classification_is_retried(self):
        from lodestar import email_monitor
        seen = []
        calls = {"n": 0}

        class Box:  # minimal IMAP stand-in
            def login(self, *a): pass
            def select(self, *a, **k): pass
            def logout(self): pass
            def uid(self, op, *a):
                if op == "search":
                    return "OK", [b"7"]
                raw = (b"From: Jane <jane@acme.com>\r\nSubject: Interview invitation\r\nMessage-ID: <x@acme>\r\n"
                       b"Content-Type: text/plain\r\n\r\nWe would like to interview you.")
                return "OK", [(b"7", raw)]
        orig_imap, orig_setting = email_monitor.imaplib.IMAP4_SSL, email_monitor.setting
        email_monitor.imaplib.IMAP4_SSL = lambda host, **kw: Box()
        email_monitor.setting = lambda k, d=None: {"IMAP_USER": "me@x.com", "IMAP_PASS": "p"}.get(k, d)

        def boom(*a, **k):
            calls["n"] += 1
            raise RuntimeError("provider down")
        orig_classify, orig_seen = email_monitor.classify, db.mark_seen
        try:
            email_monitor.classify = boom
            db.mark_seen = lambda key: seen.append(key)
            email_monitor.check(days=1)
            self.assertEqual((calls["n"], seen), (1, []))   # failed -> not marked seen
            email_monitor.classify = lambda *a, **k: {"category": "other", "company": "", "title": "", "summary": ""}
            email_monitor.check(days=1)
            self.assertEqual(seen, ["email:me@x.com:7"])   # succeeded -> marked seen
        finally:
            email_monitor.classify, db.mark_seen = orig_classify, orig_seen
            email_monitor.imaplib.IMAP4_SSL, email_monitor.setting = orig_imap, orig_setting

    def test_scheduler_uses_this_interpreter(self):
        from lodestar import extras
        real = extras.platform.system
        extras.platform.system = lambda: "Linux"
        try:
            line = extras.schedule("install", 15)
        finally:
            extras.platform.system = real
        self.assertIn(sys.executable, line)
        self.assertIn("-m lodestar run --once", line)
        self.assertIn("*/15", line)

    def test_usage_accounting(self):
        from lodestar import ai
        ai.USAGE = Path(os.environ["LODESTAR_HOME"]) / "usage-test.jsonl"
        ai.USAGE.unlink(missing_ok=True)
        ai._record(ai.PROVIDERS["anthropic"]["url"], "claude-x", {"usage": {"input_tokens": 100, "output_tokens": 40}})
        ai._record(ai.PROVIDERS["openai"]["url"], "gpt-x", {"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        u = ai.usage(1)
        self.assertEqual(u["anthropic/claude-x"], {"calls": 1, "input": 100, "output": 40})
        self.assertEqual(u["total"], {"calls": 2, "input": 110, "output": 45})

    def test_council_allowlist_and_default_provider_pref(self):
        from lodestar import ai, settings
        os.environ["OPENAI_API_KEY"] = "k"
        try:
            self.assertEqual(set(ai.council_providers()), {"anthropic", "openai"})
            settings.set_pref("council_providers", "openai, nope")
            self.assertEqual(ai.council_providers(), ["openai"])
            settings.set_pref("provider", "openai")
            self.assertEqual(ai.default_provider(), "openai")
        finally:
            del os.environ["OPENAI_API_KEY"]

    def test_obsidian_export_removes_deleted_jobs(self):
        from lodestar import extras
        os.environ["OBSIDIAN_VAULT"] = os.environ["LODESTAR_HOME"]
        a = db.add_job("Acme", "Eng"); b = db.add_job("Globex", "Ops")
        folder = extras.export_obsidian("jobs-test")
        self.assertEqual(len(list(folder.glob("[0-9]*-*.md"))), 2)
        db.delete_job(b)
        extras.export_obsidian("jobs-test")
        names = sorted(p.name for p in folder.glob("[0-9]*-*.md"))
        self.assertEqual(names, [f"{a}-acme-eng.md"])

    def test_export_json_and_task_prune(self):
        import json as _json
        from lodestar import extras, web
        db.add_job("Acme", "Eng")
        out = extras.export_data("json", Path(os.environ["LODESTAR_HOME"]) / "exp")
        data = _json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), ["answers", "contacts", "events", "ideas", "interviews", "job_contacts", "jobs",
                                        "mail", "mock_sessions", "offers", "pending", "touches"])
        self.assertEqual(data["jobs"][0]["company"], "Acme")
        web.TASKS.clear()
        real_act, web._act = web._act, lambda action, p: {"ok": True}
        try:
            for _ in range(205):
                web.start_task("noop", {})
            self.assertLessEqual(len(web.TASKS), 201)
        finally:
            web._act = real_act  # later route tests run real actions

    def test_mock_system_and_cli_parse(self):
        from lodestar import interview
        job = db.get_job(db.add_job("Acme", "SRE", jd="on-call"))
        s = interview.mock_system(job)
        self.assertIn("mock interview for SRE at Acme", s)
        self.assertIn("on-call", s)
        self.assertEqual(build().parse_args(["providers", "models", "openai"]).names, ["openai"])
        self.assertEqual(build().parse_args(["export", "csv", "--out", "x"]).out, "x")
        self.assertEqual(build().parse_args(["backup", "--keep", "3"]).keep, 3)
        self.assertEqual(build().parse_args(["usage", "--days", "7"]).days, 7)



class Development7(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text("Jane Doe | Austin, TX | jane@example.com", encoding="utf-8")

    def test_new_sources_parse_and_filter(self):
        from lodestar import web_monitor as wm
        pages = {
            "author_whoishiring": {"hits": [{"objectID": "50", "title": "Ask HN: Who is hiring? (November 2026)"}]},
            "story_50": {"hits": [
                {"objectID": "1", "parent_id": "50", "author": "a", "created_at": "2026-11-02T10:00:00Z",
                 "comment_text": "<p>Acme | Senior Python Engineer | Remote (US)</p><p>We build widgets.</p>"},
                {"objectID": "2", "parent_id": "1", "author": "b", "comment_text": "<p>Python reply, not a posting</p>"},
                {"objectID": "3", "parent_id": "50", "author": "c", "comment_text": "<p>Globex | Java Dev | NYC</p>"},
                {"objectID": "4", "parent_id": "50", "author": "d", "created_at": "2026-11-02T11:00:00Z",
                 "comment_text": "<p>Location: Lisbon</p><p>Initrode | Python Backend | Lisbon / Remote</p>"},
                {"objectID": "5", "parent_id": "50", "author": "solo_founder", "comment_text": "<p>Hiring a python contractor for 3 months.</p>"}]},
            "jobicy": {"jobs": [{"jobTitle": "Python Dev", "companyName": "Initech", "url": "https://j/1", "jobGeo": "Anywhere",
                                 "jobExcerpt": "python", "pubDate": "2026-11-01 10:00:00", "jobDescription": "<b>x</b>"}]},
            "themuse": {"results": [{"name": "Python Engineer", "company": {"name": "Umbrella"}, "refs": {"landing_page": "https://m/1"},
                                     "locations": [{"name": "Austin, TX"}], "categories": [{"name": "Software Engineering"}],
                                     "publication_date": "2026-11-01T00:00:00Z", "contents": "<p>py</p>"},
                                    {"name": "Backend Engineer", "company": {"name": "Hooli"}, "refs": {"landing_page": "https://m/2"},
                                     "locations": [], "categories": [{"name": "Software Engineering"}], "publication_date": "",
                                     "contents": "<p>You will write <b>Python</b> services.</p>"}]},
        }
        def fake(url, **k):
            return next(v for key, v in pages.items() if key in url)
        wm.fetch_json = fake
        hn = wm._hn("python")
        self.assertEqual([(j["company"], j["title"], j["location"]) for j in hn],
                         [("Acme", "Senior Python Engineer", "Remote (US)"), ("Initrode", "Python Backend", "Lisbon / Remote"),
                          ("HN: solo_founder", "Hiring a python contractor for 3 months.", "")])
        self.assertEqual(wm._jobicy("python")[0]["company"], "Initech")
        self.assertEqual([j["url"] for j in wm._muse("python engineer")], ["https://m/1", "https://m/2"])  # description counts
        self.assertEqual(wm._muse("marketing"), [])

    def test_add_job_dedupes_by_url(self):
        a = db.add_job("Acme", "Eng", "https://x/1")
        b = db.add_job("Acme Corp", "Engineer", "https://x/1")
        self.assertEqual(a, b)
        self.assertEqual(len(db.list_jobs()), 1)
        self.assertEqual(db.events(a)[-1]["kind"], "duplicate")
        self.assertNotEqual(db.add_job("Acme", "Eng"), a)   # no url: never deduped

    def test_funnel_and_salary_and_packet(self):
        from lodestar import extras, resume
        j1 = db.add_job("Acme", "Eng", notes="found via remotive"); j2 = db.add_job("Globex", "Ops", notes="captured from https://l")
        for jid, path in ((j1, ["applied", "screening", "interview"]), (j2, ["applied", "rejected"])):
            for s in path:
                db.set_status(jid, s)
        f = db.funnel()
        self.assertEqual((f["stages"]["applied"]["reached"], f["stages"]["applied"]["advanced"], f["stages"]["applied"]["conversion"]), (2, 1, 0.5))
        self.assertEqual(f["rejected_from"], {"applied": 1})
        self.assertEqual(f["by_source"]["search:remotive"], {"tracked": 1, "positive": 1})
        self.assertEqual(resume.salary_mentions("Pay: $140,000 - $170,000 plus equity; EU: €80k. Call 555-1234."), ["$140,000 - $170,000", "€80k"])
        self.assertEqual(resume.salary_mentions("no pay info"), [])
        p = extras.packet(db.get_job(j1))
        import zipfile
        with zipfile.ZipFile(p) as z:
            self.assertIn("job.txt", z.namelist())
            self.assertIn("Acme - Eng", z.read("job.txt").decode())
        from datetime import datetime, timedelta
        extras.ics(db.get_job(j1), datetime.now() + timedelta(days=1))
        up = extras.upcoming_interviews(2)
        self.assertEqual([u["job_id"] for u in up], [j1])
        self.assertTrue(build().parse_args(["jobs", "funnel"]).op == "funnel")



class Desktop(unittest.TestCase):
    def test_free_port_and_parser(self):
        from lodestar import desktop
        p = desktop.free_port(8765)
        self.assertTrue(8765 <= p < 8815)
        a = build().parse_args(["desktop", "--no-loop", "--port", "8799"])
        self.assertTrue(a.no_loop and a.port == 8799 and a.email)

    def test_start_server_runs_on_a_thread(self):
        import urllib.request
        from lodestar import desktop, web
        port = desktop.free_port(8800)
        srv = web.start_server(port)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
                self.assertIn(b"<title>Lodestar</title>", r.read())
        finally:
            srv.shutdown()



class ResumeUploadAndLetters(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        PROFILE.write_text("# Master Resume\n## Contact\nJane Doe | Austin, TX | jane@example.com | +1 555 000 0000\n## Summary\nx", encoding="utf-8")

    def test_import_docx_md_and_cover_letter_assembly(self):
        import io
        from docx import Document
        from lodestar import extras, resume
        d = Document(); d.add_paragraph("Jane Doe"); d.add_paragraph("Senior Engineer at Acme"); t = d.add_table(rows=1, cols=2)
        t.rows[0].cells[0].text = "Python"; t.rows[0].cells[1].text = "SQL"
        buf = io.BytesIO(); d.save(buf)
        text = extras.import_document(buf.getvalue(), "cv.docx")
        self.assertIn("Senior Engineer at Acme", text); self.assertIn("Python | SQL", text)
        self.assertEqual(extras.import_document(b"# hi", "cv.md"), "# hi")
        with self.assertRaises(SystemExit):
            extras.import_document(b"x", "cv.xyz")
        jid = db.add_job("Acme", "Engineer", jd="Build things"); db.update_job(jid, contact_name="Sam Lee")
        resume.ai.ask = lambda prompt, system=None, provider=None, **k: "I build things well.\n\nSecond paragraph."
        out = resume.cover_letter(db.get_job(jid))
        letter = out.read_text(encoding="utf-8").splitlines()
        self.assertTrue(letter[0].startswith("Jane Doe | Austin, TX | jane@example.com"))
        self.assertIn("Sam Lee", letter[3]); self.assertEqual(letter[4], "Acme"); self.assertEqual(letter[6], "Dear Sam Lee,")
        self.assertEqual(letter[-2:], ["Sincerely,", "Jane Doe"])
        self.assertEqual(resume.adjust_text("old", "shorter", "resume"), "I build things well.\n\nSecond paragraph.")
        self.assertEqual(build().parse_args(["resume", "import", "cv.pdf", "--merge", "--save"]).merge, True)
        self.assertEqual(build().parse_args(["resume", "adjust", "shorter", "--job", "3", "--doc", "cover_letter.md"]).doc, "cover_letter.md")
        self.assertTrue(build().parse_args(["resume", "cover", "3", "--docx", "--words", "250"]).docx)

    def test_doc_save_route_is_whitelisted(self):
        import http.client, json as _json
        from lodestar import desktop, web
        port = desktop.free_port(8830); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
            # the server thread has its own connection (the temp-home file database), so create the job through the API
            c.request("POST", "/api/jobs", _json.dumps({"company": "Acme", "title": "Engineer"}), h); jid = _json.loads(c.getresponse().read())["id"]
            c.request("POST", f"/api/docs/{jid}", _json.dumps({"name": "resume.md", "text": "# edited"}), h); r = c.getresponse(); body = _json.loads(r.read())
            self.assertEqual(r.status, 200, body); self.assertEqual(body["docs"]["resume.md"], "# edited")
            c.request("GET", f"/api/jobs/{jid}", None, h); self.assertEqual(_json.loads(c.getresponse().read())["docs"]["resume.md"], "# edited")
            c.request("POST", f"/api/jobs/{jid}/delete", "{}", h); c.getresponse().read()
            c.request("POST", f"/api/docs/{jid}", _json.dumps({"name": "../evil.md", "text": "x"}), h); r = c.getresponse(); r.read()
            self.assertEqual(r.status, 400)
            c.request("POST", "/api/upload", _json.dumps({"name": "cv.md", "data": "IyBoaQ=="}), h); r = c.getresponse()
            self.assertEqual(_json.loads(r.read())["text"], "# hi")
        finally:
            srv.shutdown()



class Improvements8(unittest.TestCase):
    def setUp(self):
        from lodestar import comp, settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        comp.PATH.unlink(missing_ok=True)
        PROFILE.write_text("Jane Doe | Austin, TX | jane@example.com", encoding="utf-8")

    def test_comp_lookup(self):
        from lodestar import comp
        comp.set_range("software engineer", "austin", 130000, 170000)
        comp.set_range("software engineer", "*", 120000, 160000)
        comp.set_range("senior software engineer", "*", 160000, 210000)
        self.assertEqual(comp.lookup("Senior Software Engineer", "")["low"], 160000)      # longest keyword wins
        self.assertEqual(comp.lookup("Software Engineer II", "office in Austin, TX")["city"], "austin")
        self.assertEqual(comp.lookup("Software Engineer", "remote")["city"], "*")
        self.assertIsNone(comp.lookup("Nurse", ""))

    def test_followup_cadence_and_conflicts(self):
        from datetime import datetime, timedelta
        from lodestar import extras, loop
        jid = db.add_job("Acme", "Eng")
        self.assertEqual(loop.followup_step(db.get_job(jid)), "nudge")
        for _ in range(3):
            db.add_event(jid, "followup_nudge", "")
        self.assertEqual(loop.followup_step(db.get_job(jid)), "close")
        when = datetime.now().replace(second=0, microsecond=0) + timedelta(days=3)
        extras.ics(db.get_job(jid), when)
        self.assertEqual([c["job_id"] for c in extras.conflicts(when + timedelta(minutes=30))], [jid])
        self.assertEqual(extras.conflicts(when + timedelta(hours=4)), [])

    def test_council_judge_and_inventory(self):
        from lodestar import ai, settings
        from lodestar.cli import build
        from lodestar.inventory import markdown
        os.environ["OPENAI_API_KEY"] = "k"
        try:
            calls = []
            ai._post = lambda url, headers, body, retries=2: (calls.append(url), {"content": [{"text": "A"}]} if "anthropic" in url else {"choices": [{"message": {"content": "O"}}]})[1]
            settings.set_pref("council_judge", "true")
            r = ai.council("q", providers=["anthropic", "openai"])
            self.assertEqual(r["synthesis"], "O")          # the judge (second provider) produced the final answer
            self.assertEqual(len(calls), 4)                 # 2 answers + synthesis + judge
        finally:
            del os.environ["OPENAI_API_KEY"]
        md = markdown(build())
        self.assertIn("| `lodestar comp set` |", md); self.assertIn("## Automated tools", md)

    def test_route_security_harness(self):
        import http.client
        from lodestar import desktop, web
        port = desktop.free_port(8840); srv = web.start_server(port)
        try:
            def req(method, path, headers=None, body=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request(method, path, body, {"Host": f"127.0.0.1:{port}", **(headers or {})})
                r = c.getresponse(); r.read(); return r.status
            self.assertEqual(req("GET", "/api/state"), 403)
            self.assertEqual(req("GET", "/api/state", {"X-Lodestar-Token": web.TOKEN}), 200)
            self.assertEqual(req("GET", "/api/state", {"X-Lodestar-Token": web.TOKEN, "Host": "evil.com"}), 421)
            self.assertEqual(req("GET", f"/api/state?t={web.CAPTURE_TOKEN}"), 403)
            self.assertEqual(req("GET", f"/api/autofill?t={web.CAPTURE_TOKEN}"), 200)
            self.assertEqual(req("GET", "/static/../pyproject.toml"), 404)
            self.assertEqual(req("POST", "/api/tools", {"X-Lodestar-Token": web.TOKEN, "Content-Type": "text/plain"}, "{}"), 400)
        finally:
            srv.shutdown()



class Onboarding(unittest.TestCase):
    def test_setup_status_and_loop_status(self):
        from lodestar import loop, web
        from lodestar.config import PROFILE
        PROFILE.write_text("# Master Resume\nFull Name | City | email@example.com\nTwo or three sentences", encoding="utf-8")
        s = web.setup_status()
        self.assertFalse(s["profile_ready"]); self.assertTrue(s["provider_ready"])  # ANTHROPIC_API_KEY is set for the suite
        PROFILE.write_text("# Jane Doe\n" + "real experience line\n" * 40, encoding="utf-8")
        self.assertTrue(web.setup_status()["profile_ready"])
        self.assertEqual(loop.STATUS["running"], False)
        class A: email = False; days = 1; provider = None; followup = 7; every = 5; once = True
        loop.STATUS.update(running=False, cycles=0)
        db._local.con = db.connect(":memory:")
        loop.run(A())
        # a finished run must not leave the top bar claiming a live loop
        self.assertTrue(not loop.STATUS["running"] and loop.STATUS["cycles"] == 1 and loop.STATUS["every"] == 5)
        self.assertRegex(loop.STATUS["last_cycle"], r"^\d\d:\d\d$")

    def test_a_failing_step_never_kills_the_loop(self):
        from lodestar import loop, web_monitor
        class A: email = False; days = 1; provider = None; followup = 7; every = 5; once = True
        db._local.con = db.connect(":memory:")
        real = web_monitor.check_watches
        def die():
            raise SystemExit("No AI provider configured")  # what ai.* raises; `except Exception` used to miss it
        web_monitor.check_watches = die
        try:
            loop.STATUS.update(cycles=0, last_error=None)
            loop.run(A())  # returns normally instead of the SystemExit ending the thread
            self.assertEqual(loop.STATUS["cycles"], 1)
            self.assertIn("watches: No AI provider configured", loop.STATUS["last_error"])
        finally:
            web_monitor.check_watches = real



class ModelHealing(unittest.TestCase):
    def setUp(self):
        from lodestar import settings
        settings.PATH.unlink(missing_ok=True)

    def test_rejected_model_is_replaced_and_remembered(self):
        from lodestar import ai, settings
        ai.list_models = lambda name: ["claude-haiku-4", "claude-sonnet-5-5-20261001", "other"]
        seen = []
        def fake_post(url, headers, body, retries=2):
            seen.append(body["model"])
            if len(seen) == 1:
                raise SystemExit("anthropic: the model 'claude-sonnet-5-5' was rejected (not found)")
            return {"content": [{"text": "ok"}]}
        ai._post = fake_post
        self.assertEqual(ai.ask("hi", provider="anthropic"), "ok")
        self.assertEqual(seen, ["claude-sonnet-5-5", "claude-sonnet-5-5-20261001"])     # retried with a real id
        self.assertEqual(settings.pref("models")["anthropic"], "claude-sonnet-5-5-20261001")
        self.assertEqual(ai.model_for("anthropic"), "claude-sonnet-5-5-20261001")         # remembered for next time
        ai.list_models = lambda name: []
        seen.clear()
        settings.set_pref("models", {})
        with self.assertRaises(SystemExit):                                               # nothing offered: give up loudly
            ai.ask("hi", provider="anthropic")
        self.assertEqual(ai.pick_model("openai"), None)



class Doctor(unittest.TestCase):
    def test_checks_cover_the_basics(self):
        from lodestar import doctor
        rows = {what: status for status, what, _ in doctor.checks()}
        self.assertEqual(rows["Python"], "ok")
        self.assertEqual(rows["AI providers"], "ok")          # ANTHROPIC_API_KEY is set for the suite
        self.assertEqual(rows["data folder"], "ok")
        self.assertIn("master profile", rows)
        self.assertTrue(build().parse_args(["doctor", "--live"]).live)



class DoctorInUI(unittest.TestCase):
    def test_doctor_action_returns_rows(self):
        from lodestar import web
        r = web._act("doctor", {})
        self.assertTrue(any(row["what"] == "Python" and row["status"] == "ok" for row in r["rows"]))
        self.assertTrue(all(set(row) == {"status", "what", "detail"} for row in r["rows"]))



class ProfileBank(unittest.TestCase):
    """Profile bank: saved originals, pooled facts with sources, LinkedIn import, section-aware prompt text."""
    MASTER = """# Master Resume
## Contact
Jane Doe | Austin, TX | jane@example.com | +1 512 555 0199 | linkedin.com/in/janedoe

## Summary
Backend engineer who ships data platforms.

## Skills
- Programming languages: Python, Go, SQL
- Tools: Docker, Terraform

## Languages
- Spanish (Native), French - B2

## Experience
### Senior Engineer - Acme Corp (2021-03 - Present)
- Cut deploy time 40%
- Led a team of 4

### Engineer - Globex (2018-06 - 2021-02)
- Built the billing pipeline

## Education
BSc Computer Science, UT Austin, 2018

## Certifications
- AWS Solutions Architect

## Preferences (used for job search ranking)
Target roles: backend | Salary floor: 150k
"""

    def setUp(self):
        import shutil
        from lodestar import profile
        from lodestar.config import PROFILE
        for d in (profile.RESUMES, profile.HISTORY):
            shutil.rmtree(d, ignore_errors=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")

    def test_offline_extraction_reads_the_master_format(self):
        from lodestar import profile
        f = profile.extract_heuristic(self.MASTER)
        self.assertEqual(f["contact"]["name"], "Jane Doe"); self.assertEqual(f["contact"]["location"], "Austin, TX")
        self.assertEqual(f["contact"]["email"], "jane@example.com"); self.assertEqual(f["contact"]["phone"], "+1 512 555 0199")
        self.assertIn({"name": "Go", "category": "Programming languages"}, f["skills"])
        self.assertIn({"name": "Docker", "category": "Tools"}, f["skills"])
        self.assertEqual(f["languages"], [{"name": "Spanish", "proficiency": "Native"}, {"name": "French", "proficiency": "B2"}])
        acme = f["experience"][0]
        self.assertEqual((acme["title"], acme["company"], acme["start"], acme["end"]), ("Senior Engineer", "Acme Corp", "2021-03", "Present"))
        self.assertEqual(acme["bullets"], ["Cut deploy time 40%", "Led a team of 4"])
        self.assertEqual(f["certifications"], [{"name": "AWS Solutions Architect"}])
        # the starter template yields nothing but placeholders, which merge() drops
        bank = profile.empty(); added = profile.merge(bank, profile.extract_heuristic(resume.PROFILE_TEMPLATE), "t")
        self.assertEqual(sum(added.values()), 0, bank)

    def test_merge_dedupes_unions_bullets_and_keeps_sources(self):
        from lodestar import profile
        bank = profile.empty()
        profile.merge(bank, {"contact": {"email": "a@x.com"}, "skills": ["Python", {"name": "SQL"}],
                             "experience": [{"title": "Engineer", "company": "Acme", "bullets": ["one"]}]}, "resume:1")
        added = profile.merge(bank, {"contact": {"email": "b@x.com", "phone": "+1 555 123 4567"}, "skills": ["python", "Go"],
                                     "experience": [{"title": "engineer", "company": "ACME", "start": "2020", "bullets": ["One", "two"]}]}, "linkedin:2")
        self.assertEqual(added["skills"], 1); self.assertEqual([s["name"] for s in bank["skills"]], ["Python", "SQL", "Go"])
        self.assertEqual(bank["skills"][0]["sources"], ["resume:1", "linkedin:2"])
        self.assertEqual(bank["contact"]["email"], "a@x.com")          # never overwritten
        self.assertEqual(bank["contact"]["phone"], "+1 555 123 4567")  # blanks are filled
        exp = bank["experience"]; self.assertEqual(len(exp), 1)
        self.assertEqual(exp[0]["bullets"], ["one", "two"]); self.assertEqual(exp[0]["start"], "2020")

    def test_import_keeps_one_original_and_seeds_only_a_template_master(self):
        from lodestar import profile
        from lodestar.config import PROFILE
        r = profile.import_file(self.MASTER.encode(), "jane.md", use_ai=False)
        self.assertTrue(r["new_file"] and r["seeded_master"]); self.assertFalse(r["used_ai"])
        self.assertTrue((profile.RESUMES / r["resume"]["file"]).is_file())
        master = PROFILE.read_text(encoding="utf-8")
        self.assertIn("Spanish (Native)", master); self.assertIn("### Senior Engineer - Acme Corp (2021-03 - Present)", master)
        self.assertIn("Salary floor:", master)  # the Preferences section survives
        self.assertFalse(profile.is_template(master))
        self.assertEqual(len(list(profile.HISTORY.glob("profile-*.md"))), 1)  # the template was snapshotted
        again = profile.import_file(self.MASTER.encode(), "copy.md", use_ai=False)
        self.assertFalse(again["new_file"]); self.assertEqual(len(profile.load()["resumes"]), 1)
        self.assertEqual(sum(again["added"].values()), 0)
        PROFILE.write_text(master + "\nmy own edit\n", encoding="utf-8")
        r3 = profile.import_file(b"# Jane\n## Skills\n- Kubernetes, Rust\n", "extra.md", use_ai=False)
        self.assertFalse(r3["seeded_master"]); self.assertIn("my own edit", PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(r3["added"]["skills"], 2)

    def test_linkedin_export_zip(self):
        import io, zipfile
        from lodestar import profile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Basic_LinkedInDataExport/Profile.csv", "First Name,Last Name,Maiden Name,Address,Birth Date,Headline,Summary,Industry,Zip Code,Geo Location,Twitter Handles,Websites,Instant Messengers\n"
                       'Jane,Doe,,,,Backend Engineer,"Builds data platforms, reliably",Software,,"Austin, Texas",,"[PORTFOLIO:https://jane.dev,OTHER:https://github.com/janedoe]",\n')
            z.writestr("Basic_LinkedInDataExport/Positions.csv", 'Company Name,Title,Description,Location,Started On,Finished On\nAcme Corp,Senior Engineer,"Cut deploy time 40%\nLed a team of 4","Austin, TX",Mar 2021,\n')
            z.writestr("Basic_LinkedInDataExport/Skills.csv", "Name\nPython\nKubernetes\n")
            z.writestr("Basic_LinkedInDataExport/Languages.csv", "Name,Proficiency\nSpanish,Native or bilingual proficiency\n")
            z.writestr("Basic_LinkedInDataExport/Email Addresses.csv", 'Notes:\n"Your email addresses"\n\nEmail Address,Confirmed,Primary,Updated On\nold@x.com,Yes,No,\njane@example.com,Yes,Yes,\n')
            z.writestr("Basic_LinkedInDataExport/messages.csv", "FROM,TO,CONTENT\nsomeone,me,private\n")
        r = profile.import_file(buf.getvalue(), "Basic_LinkedInDataExport.zip")
        b = profile.load()
        self.assertEqual(r["resume"]["source"], "linkedin"); self.assertTrue(r["resume"]["file"].endswith(".linkedin.json"))
        self.assertNotIn("private", (profile.RESUMES / r["resume"]["file"]).read_text(encoding="utf-8"))  # messages are never kept
        self.assertEqual(b["contact"]["name"], "Jane Doe"); self.assertEqual(b["contact"]["email"], "jane@example.com")
        self.assertEqual(b["contact"]["github"], "https://github.com/janedoe"); self.assertEqual(b["contact"]["website"], "https://jane.dev")
        self.assertEqual(b["experience"][0]["bullets"], ["Cut deploy time 40%", "Led a team of 4"])
        self.assertEqual(b["experience"][0]["end"], "Present")
        self.assertEqual([s["name"] for s in b["skills"]], ["Python", "Kubernetes"])
        self.assertEqual(b["languages"][0]["proficiency"], "Native or bilingual proficiency")
        z2 = io.BytesIO()
        with zipfile.ZipFile(z2, "w") as z:
            z.writestr("notes.txt", "x")
        with self.assertRaises(SystemExit):
            profile.import_file(z2.getvalue(), "other.zip")
        self.assertEqual(profile.link_linkedin("linkedin.com/in/jane-doe-1/?trk=x"), "https://www.linkedin.com/in/jane-doe-1")
        with self.assertRaises(ValueError):
            profile.link_linkedin("https://example.com/jane")

    def test_candidate_text_adds_bank_facts_and_brief_keeps_preferences(self):
        from lodestar import profile
        from lodestar.config import PROFILE
        PROFILE.write_text(self.MASTER, encoding="utf-8")
        profile.add("skills", "Kubernetes"); profile.add("skills", "python"); profile.add("languages", "German", "A2")
        text = profile.candidate_text()
        self.assertIn("## On file", text); self.assertIn("Kubernetes", text); self.assertIn("German (A2)", text)
        self.assertNotIn("Kubernetes; python", text)  # Python is already in the master
        short = profile.candidate_text(700)
        self.assertLessEqual(len(short), 700)
        self.assertIn("Salary floor: 150k", short); self.assertIn("Kubernetes", short); self.assertIn("jane@example.com", short)
        self.assertEqual(resume.candidate_text(700), short)

    def test_ai_extraction_used_when_it_works_and_offline_parse_when_it_fails(self):
        from lodestar import ai, profile
        orig = ai.ask_json
        try:
            ai.ask_json = lambda prompt, system=None, provider=None: {"contact": {"name": "Jane Doe"}, "skills": [{"name": "Rust"}],
                                                                    "experience": [{"title": "CTO", "company": "Initech", "bullets": ["Grew team"]}]}
            facts, used = profile.extract("Jane Doe\njane@example.com\nSkills\nPython", use_ai=True)
            self.assertTrue(used); self.assertEqual(facts["contact"]["email"], "jane@example.com")  # regex fills the AI's blank
            self.assertEqual({s["name"] for s in facts["skills"] if isinstance(s, dict)}, {"Rust"})  # offline skills only fill an empty AI list

            def boom(*a, **k):
                raise SystemExit("No AI provider configured")
            ai.ask_json = boom
            facts, used = profile.extract("Jane Doe\njane@example.com", use_ai=True)
            self.assertFalse(used); self.assertEqual(facts["contact"]["email"], "jane@example.com")
        finally:
            ai.ask_json = orig

    def test_master_writes_are_snapshotted_and_autofill_uses_the_bank(self):
        from lodestar import extras, profile
        from lodestar.config import PROFILE
        PROFILE.write_text("# Me\n## Summary\nno contact line here\n", encoding="utf-8")
        profile.write_master("v2"); profile.write_master("v2"); profile.write_master("v3")
        self.assertEqual(len(list(profile.HISTORY.glob("profile-*.md"))), 2)  # identical content is not re-snapshotted
        self.assertEqual(PROFILE.read_text(encoding="utf-8"), "v3")
        profile.set_contact("email", "jane@example.com"); profile.set_contact("linkedin", "https://linkedin.com/in/jane")
        a = extras.autofill_data()
        self.assertEqual(a["email"], "jane@example.com"); self.assertEqual(a["linkedin"], "https://www.linkedin.com/in/jane")

    def test_cli_and_routes(self):
        import base64, http.client, json as _json, time
        from lodestar import desktop, profile, web
        self.assertTrue(build().parse_args(["profile", "import", "cv.pdf", "--no-ai"]).no_ai)
        self.assertEqual(build().parse_args(["profile", "add", "languages", "Spanish", "--detail", "Native"]).detail, "Native")
        port = desktop.free_port(8850); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def call(method, path, body=None):
                c.request(method, path, _json.dumps(body) if body is not None else None, h); r = c.getresponse(); return r.status, _json.loads(r.read())
            st, v = call("POST", "/api/profile/bank", {"op": "add", "kind": "skills", "name": "Terraform", "detail": "Tools"})
            self.assertEqual(st, 200, v); self.assertEqual(v["bank"]["skills"][0]["category"], "Tools")
            self.assertEqual(call("POST", "/api/profile/bank", {"op": "nope"})[0], 400)
            st, v = call("POST", "/api/run/profile_import", {"name": "jane.md", "data": base64.b64encode(self.MASTER.encode()).decode(), "ai": False})
            for _ in range(50):
                st, t = call("GET", f"/api/tasks/{v['task']}")
                if t["status"] != "running":
                    break
                time.sleep(0.1)
            self.assertEqual(t["status"], "done", t); self.assertIn("seeded_master", t["result"], t); self.assertTrue(t["result"]["seeded_master"])
            self.assertFalse(t["result"]["template"])
            st, v = call("GET", "/api/profile/bank"); self.assertIn("Spanish", [x["name"] for x in v["bank"]["languages"]])
            before = len(list(profile.HISTORY.glob("profile-*.md")))
            self.assertEqual(call("POST", "/api/profile", {"text": self.MASTER + "\nedited"})[0], 200)
            self.assertEqual(len(list(profile.HISTORY.glob("profile-*.md"))), before + 1)
        finally:
            srv.shutdown()



class DesignFaultFixes(unittest.TestCase):
    """Regression checks for the 2026-11-05 design review findings."""

    def test_truncated_replies_raise_and_healed_model_saved_only_after_success(self):
        from lodestar import settings
        settings.PATH.unlink(missing_ok=True)
        real_post, real_pick = ai._post, ai.pick_model
        try:
            ai._post = lambda url, headers, body, retries=2: {"content": [{"type": "text", "text": "half a resu"}], "stop_reason": "max_tokens"}
            with self.assertRaises(RuntimeError) as cm:
                ai.chat([{"role": "user", "content": "x"}], provider="anthropic")
            self.assertIn("cut off", str(cm.exception))
            calls = []

            def post(url, headers, body, retries=2):
                calls.append(body["model"])
                if len(calls) == 1:
                    raise SystemExit(f"anthropic: the model '{body['model']}' was rejected (not found).")
                raise RuntimeError("provider down")  # the replacement fails too
            ai._post, ai.pick_model = post, lambda name: "claude-replacement"
            with self.assertRaises(RuntimeError):
                ai.chat([{"role": "user", "content": "x"}], provider="anthropic")
            self.assertEqual(calls[1], "claude-replacement")
            self.assertNotIn("anthropic", settings.pref("models"))  # an unproven model is never remembered
        finally:
            ai._post, ai.pick_model = real_post, real_pick

    def test_settings_survive_a_corrupt_file_and_write_atomically(self):
        from lodestar import settings
        settings.PATH.write_text("{not json", encoding="utf-8")
        self.assertTrue(settings.enabled("backup"))  # defaults, not a crash
        settings.set_pref("signature", "Jane")
        self.assertEqual(settings.pref("signature"), "Jane")
        self.assertFalse(settings.PATH.with_name("settings.json.tmp").exists())
        settings.PATH.unlink()

    def test_run_lock_blocks_a_second_scan_and_steals_a_stale_one(self):
        import os, time
        from lodestar.util import run_lock
        with run_lock("unit"):
            with self.assertRaises(SystemExit):
                with run_lock("unit"):
                    pass
        lk = run_lock("unit", stale=1)
        lk.path.write_text("999999", encoding="utf-8"); old = time.time() - 60; os.utime(lk.path, (old, old))
        with run_lock("unit", stale=1):  # a crashed holder's lock is taken over
            pass
        self.assertFalse(lk.path.exists())

    def test_regenerated_documents_keep_the_previous_version(self):
        from lodestar.resume import write_doc
        d = Path(os.environ["LODESTAR_HOME"]) / "applications" / "1-acme-eng"; d.mkdir(parents=True, exist_ok=True)
        (d / "resume.md").write_text("my hand edits", encoding="utf-8")
        write_doc(d / "resume.md", "fresh AI version")
        write_doc(d / "resume.md", "fresh AI version")  # identical: no extra copy
        kept = list((d / "history").glob("resume-*.md"))
        self.assertEqual(len(kept), 1); self.assertEqual(kept[0].read_text(encoding="utf-8"), "my hand edits")

    def test_followup_cadence_counts_loop_nudges_only_and_closes_once(self):
        from lodestar import loop
        db._local.con = db.connect(":memory:")
        jid = db.add_job("Acme", "Eng")
        for _ in range(2):
            db.add_event(jid, "followup_nudge", ""); db.add_event(jid, "followup", "drafted")
        self.assertEqual(loop.followup_step(db.get_job(jid)), "nudge")  # 2 nudges (+2 drafts) is not 3
        db.add_event(jid, "followup_nudge", "")
        self.assertEqual(loop.followup_step(db.get_job(jid)), "close")
        db.add_event(jid, "followup_nudge", "cadence exhausted")
        self.assertEqual(loop.followup_step(db.get_job(jid)), "done")

    def test_backup_is_a_consistent_sqlite_snapshot(self):
        import sqlite3, tempfile, zipfile
        from lodestar import extras
        from lodestar.config import DB_PATH
        con = sqlite3.connect(DB_PATH); con.execute("CREATE TABLE IF NOT EXISTS probe(x)"); con.execute("INSERT INTO probe VALUES (42)"); con.commit()
        out = extras.backup(Path(tempfile.mkdtemp()))
        with zipfile.ZipFile(out) as z, tempfile.TemporaryDirectory() as t:
            z.extract(DB_PATH.name, t)
            c2 = sqlite3.connect(Path(t) / DB_PATH.name)
            self.assertEqual(c2.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertIn((42,), c2.execute("SELECT x FROM probe").fetchall())
            c2.close()
        con.close()

    def test_watch_listings_are_marked_seen_only_after_judgement(self):
        from lodestar import apply, settings, web_monitor
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        web_monitor.SOURCES = {"fake": lambda q: [web_monitor._listing("Python Dev", "A", "https://j/1", desc="python")]}
        db.add_watch("search:python", "")
        real = apply.auto_track
        def fail(listings, provider=None):
            raise SystemExit("anthropic: the model 'x' was rejected")
        apply.auto_track = fail
        try:
            web_monitor.check_watches()
            self.assertFalse(db.seen("listing:https://j/1"))  # ranking failed: retried next cycle
            def judge(listings, provider=None):
                for j in listings:
                    j["score"] = 10
                return []
            apply.auto_track = judge
            web_monitor.check_watches()
            self.assertTrue(db.seen("listing:https://j/1"))
        finally:
            apply.auto_track = real

    def test_public_routes_leak_nothing_extra_and_page_cannot_be_framed(self):
        import http.client, json as _json
        from lodestar import desktop, web
        from lodestar.config import HOME
        self.assertEqual((HOME / "capture.token").read_text(encoding="utf-8").strip(), web.CAPTURE_TOKEN)  # survives restarts
        self.assertEqual(web._capture_token(), web.CAPTURE_TOKEN)
        db.save_answer("Salary expectations?", "private number")
        port = desktop.free_port(8870); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", f"/api/autofill?t={web.CAPTURE_TOKEN}", headers={"Host": f"127.0.0.1:{port}"}); r = c.getresponse()
            self.assertNotIn("answers", _json.loads(r.read()))
            c.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"}); r = c.getresponse(); r.read()
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
            self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
            c.close()
        finally:
            srv.shutdown()

    def test_template_profile_never_reaches_prompts(self):
        import shutil
        from lodestar import profile
        from lodestar.config import PROFILE
        shutil.rmtree(profile.RESUMES, ignore_errors=True); profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")
        with self.assertRaises(SystemExit):
            profile.candidate_text()
        profile.add("skills", "Python"); profile.set_contact("name", "Jane Doe")
        text = profile.candidate_text()  # the bank stands in for the template
        self.assertIn("Jane Doe", text); self.assertIn("Python", text); self.assertNotIn("Full Name", text)
        profile.BANK.unlink()

    def test_network_errors_are_retried(self):
        import io, urllib.error
        real_open, real_sleep = ai.urllib.request.urlopen, ai.time.sleep
        tries = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def flaky(req, timeout=None):
            tries.append(1)
            if len(tries) < 3:
                raise urllib.error.URLError("temporary DNS failure")
            return Resp(b'{"ok": true}')
        ai.urllib.request.urlopen, ai.time.sleep = flaky, lambda s: None
        try:
            self.assertEqual(ai._post("https://example.invalid/v1", {}, {"model": "m"}), {"ok": True})
            self.assertEqual(len(tries), 3)
            tries.clear(); ai.urllib.request.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("down"))
            with self.assertRaises(RuntimeError):
                ai._post("https://example.invalid/v1", {}, {"model": "m"})
        finally:
            ai.urllib.request.urlopen, ai.time.sleep = real_open, real_sleep



class ProfileReviewFixes(unittest.TestCase):
    """Regression checks for the review of the profile-bank change itself."""

    def setUp(self):
        import shutil
        from lodestar import profile
        shutil.rmtree(profile.RESUMES, ignore_errors=True)
        profile.BANK.unlink(missing_ok=True)

    def test_partly_filled_profile_is_not_the_template(self):
        from lodestar import profile
        from lodestar.config import PROFILE
        self.assertTrue(profile.is_template(resume.PROFILE_TEMPLATE)); self.assertTrue(profile.is_template(""))
        mine = resume.PROFILE_TEMPLATE.replace("Full Name | City, ST", "Jane Doe | Austin, TX").replace(
            "- Bullet", "- Cut deploy time 40% at Acme by rebuilding the CI pipeline end to end")
        self.assertFalse(profile.is_template(mine))  # the leftover "Two or three sentences" line does not matter
        PROFILE.write_text(mine, encoding="utf-8")
        r = profile.import_file(b"# X\n## Skills\n- Rust\n", "x.md", use_ai=False)
        self.assertFalse(r["seeded_master"]); self.assertEqual(PROFILE.read_text(encoding="utf-8"), mine)
        self.assertIn("Jane Doe", profile.candidate_text())

    def test_parser_real_world_layouts(self):
        from lodestar import profile
        li = ("Contact\njane@doe.io\nwww.linkedin.com/in/janedoe\nTop Skills\nPython\nSQL\nLanguages\nEnglish (Native or Bilingual)\n"
              "Jane Doe\nSenior Data Engineer at Acme\nAustin, Texas, United States\nSummary\nBuilds pipelines.\nEducation\nUT Austin (2010 - 2014)")
        f = profile.extract_heuristic(li)
        self.assertEqual(f["languages"], [{"name": "English", "proficiency": "Native or Bilingual"}])
        self.assertEqual(f["contact"]["phone"], "")  # 2010 - 2014 is not a phone number
        f = profile.extract_heuristic("JOHN SMITH\nAustin, TX | john@smith.dev | (512) 555-0101\nSKILLS\nPython, Go\nINTERESTS\nHiking, Chess")
        self.assertEqual((f["contact"]["name"], f["contact"]["location"], f["contact"]["phone"]), ("JOHN SMITH", "Austin, TX", "(512) 555-0101"))
        self.assertEqual([s["name"] for s in f["skills"]], ["Python", "Go"])  # Interests do not spill into skills

    def test_roles_at_one_company_stay_separate_and_ai_strings_are_ignored(self):
        from lodestar import ai, profile
        b = profile.empty()
        profile.merge(b, {"experience": [{"company": "Acme", "title": "", "bullets": ["led org"]},
                                         {"company": "Acme", "title": "Senior Engineer", "bullets": ["a"]},
                                         {"company": "Acme", "title": "Staff Engineer", "bullets": ["b"]}]}, "s")
        self.assertEqual([e["title"] for e in b["experience"]], ["", "Senior Engineer", "Staff Engineer"])
        orig = ai.ask_json
        try:
            ai.ask_json = lambda *a, **k: {"skills": "Python, SQL", "languages": [], "contact": {}}
            facts, used = profile.extract("Jane\n## Skills\n- Go\n## Languages\n- German (B2)", use_ai=True)
            self.assertTrue(used); self.assertEqual([s["name"] for s in facts["skills"]], ["Go"])  # no 'P','y','t'...
            self.assertEqual(facts["languages"][0]["name"], "German")  # the AI's empty list is filled offline
        finally:
            ai.ask_json = orig

    def test_corrupt_bank_is_set_aside_not_wiped(self):
        from lodestar import profile
        profile.BANK.write_text('{"skills": [{"name": "Python"},]}', encoding="utf-8")  # trailing comma
        self.assertEqual(profile.load()["skills"], [])
        aside = list(profile.BANK.parent.glob("profile.json.corrupt-*"))
        self.assertEqual(len(aside), 1); self.assertIn("Python", aside[0].read_text(encoding="utf-8"))
        aside[0].unlink()

    def test_coach_tolerates_an_unfilled_profile(self):
        from lodestar import profile
        from lodestar.config import PROFILE
        PROFILE.write_text(resume.PROFILE_TEMPLATE, encoding="utf-8")
        with self.assertRaises(SystemExit):
            profile.candidate_text()
        self.assertIn("has not filled in a profile", profile.candidate_text(strict=False))

    def test_new_listing_alerts_once_while_judging_keeps_failing(self):
        from lodestar import apply, settings, web_monitor
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        web_monitor.SOURCES = {"fake": lambda q: [web_monitor._listing("Dev", "Co", "https://j/9", desc="x")]}
        db.add_watch("search:dev", "")
        sent, real_notify, real_track = [], web_monitor.notify, apply.auto_track
        web_monitor.notify = lambda m: sent.append(m)
        def fail(listings, provider=None):
            raise SystemExit("provider down")
        apply.auto_track = fail
        try:
            for _ in range(3):
                web_monitor.check_watches()
            self.assertEqual(sum("NEW LISTING" in m for m in sent), 1)
            self.assertFalse(db.seen("listing:https://j/9"))  # still awaiting judgement
        finally:
            web_monitor.notify, apply.auto_track = real_notify, real_track


class OpenFaultFixes(unittest.TestCase):
    """The faults pass 12 left open: private preferences, mail trust, crashed inbox items."""

    def setUp(self):
        from lodestar import settings
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)

    def test_preferences_stay_out_of_employer_facing_text(self):
        from lodestar import profile
        from lodestar.config import PROFILE
        PROFILE.write_text("# Jane Doe\nJane Doe | Austin, TX | jane@example.com\n## Skills\n- Python\n"
                           "## Preferences\nSalary floor: 123k\n", encoding="utf-8")
        self.assertIn("123k", profile.candidate_text())
        self.assertNotIn("123k", resume.candidate_text(private=False))
        self.assertIn("Python", resume.candidate_text(private=False))
        jid = db.add_job("Acme", "Eng", jd="Python role")
        prompts, real_ask, real_json = [], resume.ai.ask, resume.ai.ask_json
        resume.ai.ask = lambda p, *a, **k: prompts.append(p) or "# Tailored\n- Python"
        resume.ai.ask_json = lambda p, *a, **k: prompts.append(p) or {"match_score": 80, "verdict": "apply"}
        try:
            resume.tailor(db.get_job(jid))
            resume.gap(db.get_job(jid))  # reads the tailored resume, which no longer has Preferences
        finally:
            resume.ai.ask, resume.ai.ask_json = real_ask, real_json
        self.assertNotIn("123k", prompts[0])  # the tailored resume is sent to employers
        self.assertIn("123k", prompts[1])     # the private fit check still weighs the floor

    def test_free_mail_and_name_only_matches_never_auto_act(self):
        from lodestar import email_monitor as em, settings
        settings.set_tool("email_classify", auto=True)
        jid = db.add_job("Globex", "Data Engineer", "https://globex.com/jobs/freemail"); db.set_status(jid, "applied")
        real = em.ai.ask_json
        em.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        base = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Interview",
                "sender_name": "X", "message_id": "<m>", "body": "b", "dkim_pass": True}
        try:
            em._apply(base | {"from": "x@gmail.com", "sender_email": "x@gmail.com"}, dry=False)
            job = db.get_job(jid)
            self.assertEqual((job["status"], job["contact_email"]), ("applied", None))  # DKIM-valid gmail is anyone
            self.assertTrue(any(r["kind"] == "set_status" for r in db.list_pending()))
            em._apply(base | {"from": "x@agency.com", "sender_email": "x@agency.com"}, dry=False)
            self.assertEqual(db.get_job(jid)["status"], "applied")  # third party naming the company
            em._apply(base | {"from": "r@careers.globex.com", "sender_email": "r@careers.globex.com"}, dry=False)
            self.assertEqual(db.get_job(jid)["status"], "interview")  # the company's own domain
            before = len(db.list_jobs())
            em._apply(base | {"category": "recruiter_outreach", "company": "Hooli", "from": "h@gmail.com",
                              "sender_email": "h@gmail.com"}, dry=False)
            self.assertEqual(len(db.list_jobs()), before)  # free-mail outreach waits in the inbox
        finally:
            em.ai.ask_json = real
        db.update_job(jid, contact_email="jane@gmail.com")
        self.assertEqual(em._match({"sender_email": "jane@gmail.com"}), (db.get_job(jid), True))
        self.assertFalse(em._match({"sender_email": "other@gmail.com", "company": "Globex"})[1])

    def test_crashed_running_item_is_closed_not_rerun(self):
        old = db.add_pending("email_reply", "send_email", None, "old", "{}")
        new = db.add_pending("email_reply", "send_email", None, "new", "{}")
        self.assertTrue(db.claim_pending(old) and db.claim_pending(new))
        db.con().execute("UPDATE pending SET decided_at='2000-01-01 00:00:00' WHERE id=?", (old,))
        db.list_pending()
        self.assertEqual(db.get_pending(old)["status"], "error")
        self.assertIn("interrupted", db.get_pending(old)["result"])
        self.assertEqual(db.get_pending(new)["status"], "running")  # still within its window


class PayInterview(unittest.TestCase):
    """Pay data from the UI and listings, interview prep/mock context, saved mock debriefs, date-only invites."""

    def setUp(self):
        from lodestar import comp, settings
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        comp.PATH.unlink(missing_ok=True)

    def tearDown(self):
        from lodestar import comp
        comp.PATH.unlink(missing_ok=True)

    def test_comp_route_validates_and_deletes(self):
        import http.client, json as _json
        from lodestar import comp, desktop, web
        with self.assertRaises(ValueError):
            comp.set_range("  ", "*", 1, 2)  # an empty keyword would match every title
        with self.assertRaises(ValueError):
            comp.set_range("eng", "*", 200, 100)
        port = desktop.free_port(8880); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def call(body, headers=h):
                c.request("POST", "/api/comp", _json.dumps(body), headers); r = c.getresponse(); return r.status, _json.loads(r.read())
            st, v = call({"op": "set", "title": "Data Engineer", "city": "", "low": "120000", "high": "150000"})
            self.assertEqual((st, v["comp"]), (200, {"data engineer": {"*": [120000, 150000]}}), v)
            self.assertEqual(web.state()["comp"], comp.load())
            self.assertEqual(call({"op": "set", "title": "", "low": 1, "high": 2})[0], 400)
            self.assertEqual(call({"op": "set", "title": "x", "low": 1, "high": 2}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            self.assertEqual(call({"op": "delete", "title": "data engineer", "city": "*"})[1]["comp"], {})
            c.close()
        finally:
            srv.shutdown()

    def test_listing_salary_is_kept_and_read(self):
        j = web_monitor._listing("Dev", "A", "https://a/1", salary="120000-160000", desc="Build things.", source="remoteok")
        jd = web_monitor.jd_with_salary(j)
        self.assertTrue(jd.startswith("Salary (from remoteok): 120000-160000\n\n") and jd.endswith("Build things."))
        self.assertEqual(resume.salary_mentions(jd), ["120000-160000"])  # bare numbers SALARY_RE alone would miss
        self.assertEqual(web_monitor.jd_with_salary(web_monitor._listing("Dev", "A", "u", desc="x")), "x")

    def test_prep_and_mock_get_pay_research_and_gap(self):
        from lodestar import comp, interview
        from lodestar.config import PROFILE
        old = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else None
        PROFILE.write_text("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\n- Python\n"
                           "## Preferences\nSalary floor: 133k\n", encoding="utf-8")
        comp.set_range("data engineer", "*", 125000, 155000)
        job = db.get_job(db.add_job("Initech", "Data Engineer", jd="Salary (from remotive): $140k - $160k\n\nETL work"))
        d = resume.app_dir(job)
        (d / "research.md").write_text("Initech ships TPS reports.", encoding="utf-8")
        (d / "gap.json").write_text(json.dumps({"missing_keywords": ["Airflow"], "weak_areas": ["streaming"]}), encoding="utf-8")
        prompts, real = [], interview.ai.ask
        interview.ai.ask = lambda p, *a, **k: prompts.append(p) or "# Prep"
        try:
            interview.prep(job)
            system = interview.mock_system(job)
        finally:
            interview.ai.ask = real
            PROFILE.write_text(old, encoding="utf-8") if old is not None else PROFILE.unlink()
        for needle in ("$140k - $160k", "125000-155000", "133k", "TPS reports", "Airflow"):
            self.assertIn(needle, prompts[0])
        self.assertIn("TPS reports", system); self.assertIn("streaming", system)

    def test_web_mock_saves_debrief_on_done(self):
        from lodestar import web
        self.assertIn("mock_interview.md", web.DOC_NAMES)
        with self.assertRaises(ValueError):
            web._act("mock", {"id": "", "messages": [{"role": "user", "content": "hi"}]})
        jid = db.add_job("Acme", "Eng", jd="Python")
        real = web.ai.chat
        web.ai.chat = lambda msgs, system, prov=None: "Score 7/10" if msgs[-1]["content"].strip().lower() == "done" else "Question 1?"
        try:
            self.assertNotIn("path", web._act("mock", {"id": jid, "messages": [{"role": "user", "content": "start"}]}))
            msgs = [{"role": "user", "content": "start"}, {"role": "assistant", "content": "Question 1?"},
                    {"role": "user", "content": "I built X"}, {"role": "user", "content": " Done "}]
            r = web._act("mock", {"id": jid, "messages": msgs})
        finally:
            web.ai.chat = real
        text = Path(r["path"]).read_text(encoding="utf-8")
        self.assertIn("I built X", text); self.assertIn("Score 7/10", text)
        self.assertTrue(any(e["kind"] == "mock_interview" for e in db.events(jid)))

    def test_date_only_invite_writes_no_midnight_ics(self):
        from datetime import datetime, timedelta
        from lodestar import email_monitor as em, extras, web
        jid = db.add_job("Globex", "Eng"); db.update_job(jid, contact_email="r@globex.com"); db.set_status(jid, "interview")
        day = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        base = {"category": "interview", "company": "Globex", "summary": "s", "action": "", "subject": "Interview",
                "from": "r@globex.com", "sender_email": "r@globex.com", "sender_name": "R", "message_id": "<m>",
                "body": "b", "dkim_pass": True}
        real = em.ai.ask_json
        em.ai.ask_json = lambda *a, **k: {"subject": "Re", "body": "ok", "chosen_time": None}
        try:
            em._apply(base | {"deadline": day}, dry=False)
            self.assertEqual(extras.upcoming_interviews(14), [])  # a bare date is not a booked interview
            self.assertTrue(any(e["kind"] == "interview_date" for e in db.events(jid)))
            em._apply(base | {"deadline": "not a date"}, dry=False)  # SystemExit from parse_when must not stop the scan
            em._apply(base | {"deadline": f"{day} 14:30"}, dry=False)
        finally:
            em.ai.ask_json = real
        up = web.state()["upcoming"]
        self.assertEqual([(i["job_id"], i["when"][-5:]) for i in up], [(jid, "14:30")])

    def test_offer_sees_other_offers_terms(self):
        from lodestar import apply
        from lodestar.config import PROFILE
        old = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else None
        PROFILE.write_text("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\n- Python\n", encoding="utf-8")
        a = db.get_job(db.add_job("Acme", "Eng", jd="x")); b = db.get_job(db.add_job("Hooli", "Eng", jd="y"))
        prompts, real = [], apply.ai.ask
        apply.ai.ask = lambda p, *a_, **k: prompts.append(p) or "## Fit"
        try:
            out = apply.offer(a, salary="150k", equity="0.1%")
            apply.offer(b, salary="140k")
        finally:
            apply.ai.ask = real
            PROFILE.write_text(old, encoding="utf-8") if old is not None else PROFILE.unlink()
        self.assertTrue(out.read_text(encoding="utf-8").startswith("**Terms:** base: 150k"))
        self.assertIn("#%d Acme - Eng: **Terms:** base: 150k" % a["id"], prompts[1])


class ContactSending(unittest.TestCase):
    """Contact set from the drawer, drafted mail proposed for sending, sends (not drafts) on the checklist,
    JD URL fills the posting link, email next steps on the timeline, JSON edits, and the accepted state."""

    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        self.old_profile = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else None
        PROFILE.write_text("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\n- Python\n", encoding="utf-8")

    def tearDown(self):
        from lodestar.config import PROFILE
        PROFILE.write_text(self.old_profile, encoding="utf-8") if self.old_profile is not None else PROFILE.unlink()

    def test_contact_and_jd_routes(self):
        import http.client, json as _json
        from lodestar import desktop, util, web
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        jid = db.add_job("Acme", "Eng")
        port = desktop.free_port(8890); srv = web.start_server(port)
        real = util.read_source
        util.read_source = lambda src, allow_files=True: "JD TEXT"  # no network
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}

            def call(op, body, headers=h):
                c.request("POST", f"/api/jobs/{jid}/{op}", _json.dumps(body), headers); r = c.getresponse(); return r.status, _json.loads(r.read())
            self.assertEqual(call("contact", {"name": "Sam", "email": " sam@acme.com "})[0], 200)
            j = db.get_job(jid)
            self.assertEqual((j["contact_name"], j["contact_email"]), ("Sam", "sam@acme.com"))
            self.assertEqual(call("contact", {"email": "x@acme.com\nBcc: evil@x.com"})[0], 400)  # no header injection
            self.assertEqual(call("contact", {"email": "not-an-email"})[0], 400)
            self.assertEqual(call("contact", {"email": "a@b.co"}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            self.assertEqual(db.get_job(jid)["contact_email"], "sam@acme.com")
            call("jd", {"source": "https://acme.com/jobs/1"})
            self.assertEqual((db.get_job(jid)["url"], db.get_job(jid)["jd"]), ("https://acme.com/jobs/1", "JD TEXT"))
            call("jd", {"source": "https://other.com/2"})  # an existing posting link is kept
            self.assertEqual(db.get_job(jid)["url"], "https://acme.com/jobs/1")
            c.close()
        finally:
            util.read_source = real
            srv.shutdown()
            db.delete_job(jid)

    def test_reply_and_email_outreach_are_proposed_for_sending(self):
        from lodestar import ai, email_monitor, extras
        jid = db.add_job("Acme", "Eng", jd="Python")
        real_j, real_a = ai.ask_json, ai.ask
        ai.ask_json = lambda *a, **k: {"subject": "Hello", "body": "Body text"}
        ai.ask = lambda *a, **k: "short note"
        try:
            self.assertEqual(email_monitor.draft_reply(db.get_job(jid), "propose Tue")["proposal"]["status"], "draft_only")
            db.update_job(jid, contact_email="sam@acme.com", contact_name="Sam")
            r = email_monitor.draft_reply(db.get_job(jid), "propose Tue")
            o = extras.outreach(db.get_job(jid), "Pat", "email")
            li = extras.outreach(db.get_job(jid), "Pat", "linkedin")
        finally:
            ai.ask_json, ai.ask = real_j, real_a
        self.assertEqual(r["proposal"]["status"], "pending"); self.assertEqual(o["proposal"]["status"], "pending")
        self.assertEqual(li, {"text": "short note"})
        p = json.loads(db.get_pending(r["proposal"]["id"])["payload"])
        self.assertEqual((p["to"], p["subject"], p["body"], p["job_id"]), ("sam@acme.com", "Hello", "Body text", jid))

    def test_checklist_counts_sends_not_drafts(self):
        from lodestar import ai, apply, approvals
        jid = db.add_job("Acme", "Eng"); db.update_job(jid, contact_email="sam@acme.com"); db.set_status(jid, "interview")
        done = lambda: {c["item"]: c["done"] for c in apply.checklist(db.get_job(jid))}["Thank-you sent"]
        db.add_event(jid, "thanks", "drafted")  # what older versions logged on a draft
        real_j, real_send = ai.ask_json, approvals.send_email
        ai.ask_json = lambda *a, **k: {"subject": "Thanks", "body": "b"}
        approvals.send_email = lambda *a, **k: None
        try:
            r = apply.thanks(db.get_job(jid))
            self.assertFalse(done())
            approvals.approve(r["proposal"]["id"])
        finally:
            ai.ask_json, approvals.send_email = real_j, real_send
        self.assertTrue(done())

    def test_email_next_step_and_due_date_reach_the_timeline(self):
        from lodestar import email_monitor as em, settings
        settings.set_tool("email_reply", enabled=False)
        jid = db.add_job("Globex", "Eng"); db.update_job(jid, contact_email="r@globex.com"); db.set_status(jid, "applied")
        em._apply({"category": "assessment", "company": "Globex", "summary": "s", "action": "finish the test",
                   "deadline": "2026-12-01", "subject": "Your assessment", "from": "r@globex.com",
                   "sender_email": "r@globex.com", "sender_name": "R", "message_id": "<m>", "body": "b", "dkim_pass": True}, dry=False)
        ev = [e["detail"] for e in db.events(jid) if e["kind"] == "email"]
        self.assertEqual(ev, ["assessment: Your assessment | next: finish the test | due: 2026-12-01"])

    def test_json_edits_are_validated_and_merged(self):
        from lodestar import approvals
        pid = db.add_pending("answers", "save_answer", None, "s", json.dumps({"question": "Why us?", "answer": "AI text"}))
        with self.assertRaises(ValueError):
            approvals.approve(pid, ["not", "a", "dict"])
        self.assertEqual(db.get_pending(pid)["status"], "pending")  # a bad edit must not leave it claimed
        self.assertEqual(approvals.approve(pid, {"answer": "my words"})["status"], "done")
        self.assertEqual([a["answer"] for a in db.list_answers() if a["question"] == "Why us?"], ["my words"])

    def test_accepted_proposes_withdrawing_the_rest(self):
        from lodestar import settings
        settings.set_tool("followup", auto=True)  # still waits: withdrawing applications is always reviewed
        a, b, _ = db.add_job("Acme", "Eng"), db.add_job("Hooli", "Eng"), db.add_job("Saved", "Eng")
        for jid, path in ((b, ["applied"]), (a, ["applied", "interview", "offer", "accepted"])):
            for st in path:
                db.set_status(jid, st)
        pend = db.list_pending("pending")
        self.assertEqual([(p["job_id"], json.loads(p["payload"])["status"]) for p in pend], [(b, "withdrawn")])
        self.assertEqual(db.get_job(b)["status"], "applied")
        self.assertEqual(db.stats()["interview_rate"], 0.5)
        f = db.funnel()["stages"]
        self.assertEqual((f["offer"]["advanced"], f["accepted"]["reached"]), (1, 1))


class SettingsProviders(unittest.TestCase):
    """Local preset, followup_days, models pref, vault remove, CSV export and usage (settings-providers cluster)."""

    def test_local_preset_pins_an_ollama_model_and_counts_it(self):
        from lodestar import settings, web
        real_pick, env = ai.pick_model, os.environ.pop("OLLAMA_MODEL", None)
        before = {k: settings.pref(k) for k in ("provider", "council_providers", "models")}
        try:
            ai.pick_model = lambda name: None  # Ollama not running: the preset says so and pins nothing
            self.assertIn("not reachable", ai.local_preset())
            self.assertNotIn("ollama", settings.pref("models"))
            ai.pick_model = lambda name: "llama3.2:3b" if name == "ollama" else None
            self.assertIn("llama3.2:3b", web._act("providers_local", {})["text"])
            self.assertEqual((settings.pref("provider"), settings.pref("models")["ollama"]), ("ollama", "llama3.2:3b"))
            self.assertIn("ollama", ai.available())
            self.assertEqual(ai.council_providers(), ["ollama"])  # no SystemExit any more after the preset
            self.assertEqual(ai.model_for("ollama"), "llama3.2:3b")
        finally:
            ai.pick_model = real_pick
            if env is not None:
                os.environ["OLLAMA_MODEL"] = env
            for k, v in before.items():
                settings.set_pref(k, v)

    def test_followup_days_pref_drives_board_digest_and_loop(self):
        import argparse
        from lodestar import loop, settings, web
        jid = db.add_job("Initech", "Eng"); db.set_status(jid, "applied")
        db.con().execute("UPDATE events SET ts=datetime('now','-4 days') WHERE job_id=?", (jid,)); db.con().commit()
        sent, real_notify = [], loop.notify
        loop.notify = lambda m: sent.append(m)
        try:
            self.assertNotIn(jid, web.state()["followups"])  # default 7 days
            settings.set_pref("followup_days", 3)
            self.assertIn(jid, web.state()["followups"])
            self.assertIn(jid, [j["id"] for j in db.needs_followup()])  # the digest's call (no network here: digest asks AI)
            loop._followups(argparse.Namespace(followup=None, provider=None))
            self.assertTrue(any(f"#{jid} Initech" in m and "quiet 3+ days" in m for m in sent), sent)
            self.assertIsNone(build().parse_args(["run"]).followup)  # no flag: the pref applies
        finally:
            loop.notify = real_notify
            settings.set_pref("followup_days", 7)
            db.delete_job(jid)

    def test_models_pref_takes_provider_equals_model_and_merges(self):
        from lodestar import settings
        before = settings.pref("models")
        try:
            settings.set_pref("models", {})
            settings.set_pref("models", "openai=gpt-5")
            settings.set_pref("models", "groq = llama-3.3-70b")
            self.assertEqual(settings.pref("models"), {"openai": "gpt-5", "groq": "llama-3.3-70b"})
            with self.assertRaises(SystemExit):
                settings.set_pref("models", "[object Object]")  # what the old UI posted
        finally:
            settings.set_pref("models", before)

    def test_vault_remove_route_deletes_both_service_names(self):
        import http.client, json as _json
        from lodestar import desktop, vault, web
        calls, real_del, idx = [], vault.keyring.delete_password, vault._index()

        def fake_del(service, name):
            calls.append((service, name))
            if service == "jobbot":
                raise vault.keyring.errors.PasswordDeleteError("not there")
        vault.keyring.delete_password = fake_del
        vault._save_index(idx | {"TEST_KEY": {"user": ""}})
        port = desktop.free_port(8960); srv = web.start_server(port)
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
            c.request("POST", "/api/vault", _json.dumps({"name": "TEST_KEY", "delete": True}), {**h, "X-Lodestar-Token": "no"})
            self.assertEqual(c.getresponse().status, 403); c.close()
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("POST", "/api/vault", _json.dumps({"name": "TEST_KEY", "delete": True}), h)
            r = c.getresponse(); self.assertEqual((r.status, _json.loads(r.read())), (200, {"ok": True})); c.close()
            self.assertEqual(calls, [("lodestar", "TEST_KEY"), ("jobbot", "TEST_KEY")])
            self.assertNotIn("TEST_KEY", dict(vault.names()))
        finally:
            srv.shutdown()
            vault.keyring.delete_password = real_del
            vault._save_index(idx)

    def test_csv_export_usage_in_state_and_gap_has_no_council(self):
        from lodestar import web
        out = Path(web._act("export", {"fmt": "csv"})["path"])
        self.assertTrue(out.is_dir() and any(out.glob("jobs-*.csv")))
        self.assertTrue(web._act("export", {})["path"].endswith(".json"))
        self.assertIn("total", web.state()["usage"])
        with self.assertRaises(SystemExit):
            build().parse_args(["resume", "gap", "3", "--council"])  # the flag was accepted and silently ignored
        self.assertTrue(build().parse_args(["resume", "cover", "3", "--council"]).council)


class ReviewedDrafts(unittest.TestCase):
    """A draft the user asked for (reply, outreach) waits in the Inbox even when email_reply is on auto."""

    def setUp(self):
        from lodestar import settings
        from lodestar.config import PROFILE
        db._local.con = db.connect(":memory:")
        settings.PATH.unlink(missing_ok=True)
        self.old = PROFILE.read_text(encoding="utf-8") if PROFILE.is_file() else None
        PROFILE.write_text("# Jane Doe\nJane Doe | Austin | jane@example.com\n## Skills\n- Python\n", encoding="utf-8")

    def tearDown(self):
        from lodestar.config import PROFILE
        PROFILE.write_text(self.old, encoding="utf-8") if self.old is not None else PROFILE.unlink()

    def test_requested_drafts_never_send_unseen(self):
        from lodestar import email_monitor, extras, settings
        settings.set_tool("email_reply", auto=True)
        jid = db.add_job("Acme", "Eng"); db.update_job(jid, contact_email="recruiter@acme.com")
        real = ai.ask_json
        ai.ask_json = lambda *a, **k: {"subject": "Hi", "body": "Hello"}
        try:
            r1 = email_monitor.draft_reply(db.get_job(jid), "ask about timeline")
            r2 = extras.outreach(db.get_job(jid), person="Jane Doe, EM", channel="email")
        finally:
            ai.ask_json = real
        self.assertEqual((r1["proposal"]["status"], r2["proposal"]["status"]), ("pending", "pending"))
        self.assertIn("recruiter@acme.com", r2["proposal"]["summary"])  # the label names the real recipient
