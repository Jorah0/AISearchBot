"""Pass 26: source capability registry and coverage (blueprint 6.3, 6.5), posting freshness before applying (6.4),
the fine-grained application lifecycle with append-only stage events carrying actor and evidence (11.2, 11.3), and
the documents of a submitted application kept as they were (8.6). No network; every patched attribute is put back."""
import hashlib
import json
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
from test_pass21_fit import Base, patched, run_cli  # noqa: E402

from lodestar import apply_agent, approvals, db, resume, settings, web, web_monitor  # noqa: E402


class Sources(unittest.TestCase):
    def test_every_board_declares_its_capabilities(self):
        need = {"search", "full_description", "apply", "auth", "terms_reviewed"}
        # pinned to the real boards (every one has a credit link): an earlier module may leave SOURCES patched
        self.assertEqual(set(web_monitor.CAPABILITIES), set(web_monitor.ATTRIBUTION))
        for name in web_monitor.ATTRIBUTION:
            cap = web_monitor.CAPABILITIES.get(name)
            self.assertIsNotNone(cap, f"{name}: add it to web_monitor.CAPABILITIES")
            self.assertTrue(need <= set(cap), f"{name}: missing {need - set(cap)}")
            self.assertIn(cap["apply"], ("handoff", "unsupported"))  # discovery never implies an apply API
            self.assertEqual(cap["auth"], "key" if name in web_monitor.KEYED else "none")
        with patched(web_monitor, SOURCES={n: None for n in web_monitor.ATTRIBUTION}):
            self.assertEqual(web.sources_view()["remotive"]["capabilities"]["apply"], "handoff")

    def test_jobs_search_reports_coverage(self):
        def search(query, keywords="", errors=None, ran=None, **f):
            ran.append("remotive")
            errors.append("hn: HTTP 500")
            return []
        with patched(web_monitor, search=search, SOURCES={"remotive": None, "hn": None, "adzuna": None},
                     sources_ready=lambda: ["remotive", "hn"]):
            cov = web._do("search", {"query": "data engineer"})["coverage"]
        self.assertEqual((cov["asked"], cov["failed"], cov["not_ready"], cov["total"], cov["checked"]),
                         (["remotive"], ["hn: HTTP 500"], ["adzuna"], 3, True))


class Lifecycle(Base):
    def setUp(self):
        super().setUp()
        self.jid = db.add_job("Acme", "Data Engineer", None, "jd", "via test")

    def events(self):
        return [dict(r) for r in db.con().execute("SELECT * FROM stage_events WHERE job_id=? ORDER BY id", (self.jid,))]

    def test_status_moves_leave_append_only_stage_events(self):
        db.set_status(self.jid, "applied", "sent it")
        e = self.events()[-1]
        self.assertEqual((e["from_stage"], e["to_stage"], e["actor_type"], e["schema_version"]), ("saved", "applied", "user", "1"))
        with self.assertRaises(Exception):
            db.con().execute("UPDATE stage_events SET actor_type='agent'")
        with self.assertRaises(Exception):
            db.con().execute("DELETE FROM stage_events")

    def test_fine_stages_map_onto_the_board(self):
        db.set_stage(self.jid, "technical_interview", "loop booked")
        job = db.get_job(self.jid)
        self.assertEqual((job["status"], job["stage"]), ("interview", "technical_interview"))
        db.set_stage(self.jid, "on_hold", "they paused hiring")
        job = db.get_job(self.jid)
        self.assertEqual((job["status"], job["stage"]), ("interview", "on_hold"))  # on hold keeps the column
        self.assertEqual([e["to_stage"] for e in self.events()], ["technical_interview", "on_hold"])
        with self.assertRaises(SystemExit):
            db.set_stage(self.jid, "vibes")
        out = run_cli("jobs", "stage", str(self.jid), "final_interview", "--note", "onsite")
        self.assertIn("final_interview", out)
        self.assertEqual(db.get_job(self.jid)["stage"], "final_interview")

    def test_a_mail_driven_move_carries_its_mail_as_evidence(self):
        old = settings.load()["tools"]["email_classify"]
        settings.set_tool("email_classify", enabled=True, auto=True)
        try:
            p = approvals.propose("email_classify", "set_status",
                                  {"job_id": self.jid, "status": "screening", "note": "(email: hi)",
                                   "evidence": {"mail": "<m1@acme.example>", "category": "screening"}},
                                  "move", self.jid)
        finally:
            settings.set_tool("email_classify", enabled=old["enabled"], auto=old["auto"])
        self.assertEqual(p["status"], "done")
        e = self.events()[-1]
        self.assertEqual((e["actor_type"], e["actor_id"], e["approval_id"]), ("agent", "email_classify", p["id"]))
        self.assertEqual(json.loads(e["evidence"])["mail"], "<m1@acme.example>")

    def test_applied_keeps_the_submitted_documents_with_hashes(self):
        d = resume.app_dir(db.get_job(self.jid))
        (d / "resume.md").write_text("# Jane\nv1\n", encoding="utf-8")
        (d / "cover_letter.md").write_text("Dear team\n", encoding="utf-8")
        sent = (d / "resume.md").read_bytes()  # as written (CRLF on Windows)
        db.set_status(self.jid, "applied")
        sub = d / "submitted"
        man = json.loads((sub / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(man["files"]["resume.md"], hashlib.sha256(sent).hexdigest())
        self.assertIn("cover_letter.md", man["files"])
        (d / "resume.md").write_text("# Jane\nv2 edited after applying\n", encoding="utf-8")
        db.set_status(self.jid, "screening")
        db.set_status(self.jid, "applied")  # moved back and forth: the first submission's copy stays
        self.assertEqual((sub / "resume.md").read_text(encoding="utf-8"), "# Jane\nv1\n")

    def test_a_removed_posting_sends_the_apply_agent_to_stop(self):
        settings.set_tool("apply_agent", enabled=True)
        db.add_event(self.jid, "posting_removed", "posting page: HTTP 404 (checked 2026-11-12)")
        mode, why = apply_agent.effective_mode(db.get_job(self.jid), "greenhouse", "review")
        self.assertEqual(mode, "stop")
        self.assertTrue(any("looked removed" in w for w in why), why)
        db.add_event(self.jid, "posting_reopened", "its page answers again")
        self.assertEqual(apply_agent.effective_mode(db.get_job(self.jid), "greenhouse", "review")[0], "review")


if __name__ == "__main__":
    unittest.main()
