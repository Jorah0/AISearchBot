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
        jid = db.add_job("Globex", "Data Engineer")
        db.set_status(jid, "applied")
        info = {"category": "interview", "company": "Globex", "summary": "invite", "action": "reply", "subject": "Interview",
                "from": "x@globex.com", "dkim_pass": True}  # authenticated mail may move a job under the auto default
        email_monitor._apply(info, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "interview")
        # a later "application received" must not downgrade
        email_monitor._apply(info | {"category": "application_received"}, dry=False)
        self.assertEqual(db.get_job(jid)["status"], "interview")
        # unknown company recruiter outreach auto-creates a job
        before = len(db.list_jobs())
        email_monitor._apply({"category": "recruiter_outreach", "company": "Initech", "title": "SRE", "summary": "hi", "action": None, "subject": "Opportunity", "from": "r@initech.com"}, dry=False)
        self.assertEqual(len(db.list_jobs()), before + 1)


class Ai(unittest.TestCase):
    def test_chat_shapes_and_council(self):
        calls = []

        def fake_post(url, headers, body, retries=2):
            calls.append((url, body))
            if "anthropic" in url:
                return {"content": [{"type": "text", "text": "A says: " + body["messages"][-1]["content"][:20]}]}
            return {"choices": [{"message": {"content": "O says: " + body["messages"][-1]["content"][:20]}}]}

        ai._post = fake_post
        os.environ["OPENAI_API_KEY"] = "k"
        self.assertTrue(ai.ask("hello", system="sys", provider="anthropic").startswith("A says"))
        self.assertEqual(calls[-1][1]["system"], "sys")
        self.assertTrue(ai.ask("hello", provider="openai").startswith("O says"))
        self.assertEqual(calls[-1][1]["messages"][0]["role"], "user")
        r = ai.council("q", providers=["anthropic", "openai"])
        self.assertEqual(set(r["answers"]), {"anthropic", "openai"})
        self.assertIn("Original task", calls[-1][1]["messages"][-1]["content"])
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
        # a/1 is now seen; b/2 was keyword-filtered earlier so it is still new
        self.assertEqual([j["url"] for j in web_monitor.search("dev", only_new=True)], ["https://b/2"])
        self.assertEqual(web_monitor.search("dev", only_new=True), [])


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
        jid = db.add_job("Globex", "Data Engineer")
        db.set_status(jid, "applied")
        email_monitor.ai.ask_json = lambda *a, **k: {"subject": "Re: Interview", "body": "Tuesday works.", "chosen_time": "2026-11-10 10:00"}
        info = {"category": "interview", "company": "Globex", "summary": "invite", "action": "reply", "subject": "Interview",
                "from": "Jane Doe <jane@globex.com>", "sender_email": "jane@globex.com", "sender_name": "Jane Doe",
                "message_id": "<abc@globex>", "body": "Can you do Tue Nov 10 at 10am or Wed at 2pm?"}
        email_monitor._apply(info, dry=False)
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
        jid = db.add_job("Globex", "Data Engineer")
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
        email_monitor.imaplib.IMAP4_SSL = lambda host: Box()
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

    def test_scheduler_uses_this_interpreter(self):
        from lodestar import extras
        extras.platform.system = lambda: "Linux"
        line = extras.schedule("install", 15)
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
        self.assertEqual(sorted(data), ["answers", "events", "ideas", "jobs", "pending"])
        self.assertEqual(data["jobs"][0]["company"], "Acme")
        web.TASKS.clear()
        web._act = lambda action, p: {"ok": True}
        for _ in range(205):
            web.start_task("noop", {})
        self.assertLessEqual(len(web.TASKS), 201)

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
                          ("solo_founder", "Hiring a python contractor for 3 months.", "")])
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
