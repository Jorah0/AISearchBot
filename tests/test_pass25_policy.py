"""Pass 25: the central policy service (blueprint 17.2) and the audit trail (2.2 'Auditable automation', 9.4 mandatory
approval gates). policy.authorize decides ALLOW / REQUIRE_APPROVAL / BLOCK for every proposal, deterministically, and
every decision and every executor run leaves an append-only audit row. No network; every patched attribute is put back."""
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

from lodestar import apply_agent, approvals, config, db, policy, settings, util  # noqa: E402

MAIL = {"to": "rec@acme.example", "subject": "Thanks", "body": "Thank you for your time."}


class Policy(Base):
    def setUp(self):
        super().setUp()
        self.jid = db.add_job("Acme", "Data Engineer", None, "jd", "via test")
        db.update_job(self.jid, contact_email="rec@acme.example")
        self.old = settings.load()["tools"]["email_reply"]
        settings.set_tool("email_reply", enabled=True, auto=True)
        self.sent = []
        self.patches.enter_context(patched(util, send_email=lambda *a, **k: self.sent.append(a) or "<id@x>"))
        self.patches.enter_context(patched(approvals, send_email=lambda *a, **k: self.sent.append(a) or "<id@x>"))

    def tearDown(self):
        settings.set_tool("email_reply", enabled=self.old["enabled"], auto=self.old["auto"])
        super().tearDown()

    def decide(self, payload=None, **kw):
        return policy.authorize("email_reply", "send_email", MAIL | {"job_id": self.jid} | (payload or {}), self.jid, **kw)

    def test_decision_table(self):
        d = self.decide()
        self.assertEqual((d["result"], d["reasons"], d["policy_version"]), ("ALLOW", ["tool_auto"], policy.VERSION))
        self.assertEqual(self.decide({"new_status": "withdrawn"})["reasons"], ["withdrawal_or_acceptance"])
        self.assertEqual(self.decide({"chosen_time": "2026-12-01 10:00"})["reasons"], ["scheduling_commitment"])
        self.assertEqual(self.decide({"unverified": True})["reasons"], ["unverified_sender"])
        self.assertEqual(self.decide(force_pending=True)["reasons"], ["requested_review"])
        db.update_job(self.jid, status="offer")
        d = self.decide()
        self.assertEqual((d["result"], d["reasons"]), ("REQUIRE_APPROVAL", ["offer_correspondence"]))
        settings.set_tool("email_reply", auto=False)
        self.assertEqual(self.decide()["reasons"], ["offer_correspondence", "tool_manual"])
        settings.set_tool("email_reply", enabled=False)
        self.assertEqual(self.decide()["result"], "BLOCK")
        settings.set_tool("email_reply", enabled=True)
        config.FULL_AI.on = True
        try:
            self.assertEqual(self.decide()["result"], "BLOCK")
        finally:
            config.FULL_AI.on = False

    def test_auto_mail_on_an_offer_waits_and_the_decision_is_recorded(self):
        db.update_job(self.jid, status="offer")
        p = approvals.propose("email_reply", "send_email", MAIL | {"job_id": self.jid}, "reply", self.jid)
        self.assertEqual(p["status"], "pending")
        self.assertEqual(self.sent, [])
        row = policy.log(1)[0]
        self.assertEqual((row["action"], row["result"], row["approval_id"], row["target"]),
                         ("propose:send_email", "REQUIRE_APPROVAL", p["id"], f"job #{self.jid}"))
        self.assertEqual(json.loads(row["reasons"]), ["offer_correspondence"])

    def test_every_executor_run_has_a_decision_row(self):
        p = approvals.propose("email_reply", "send_email", MAIL | {"job_id": self.jid}, "thanks", self.jid)
        self.assertEqual(p["status"], "done")  # an ordinary mail, tool on auto: allowed
        rows = [r for r in policy.log(10) if r["approval_id"] == p["id"]]
        self.assertEqual([(r["action"], r["result"]) for r in rows], [("execute:send_email", "done"), ("propose:send_email", "ALLOW")])
        q = approvals.propose("email_reply", "send_email", MAIL | {"job_id": self.jid}, "thanks", self.jid, force_pending=True)
        approvals.approve(q["id"])
        rows = [r for r in policy.log(10) if r["approval_id"] == q["id"]]
        self.assertEqual([(r["action"], r["result"]) for r in rows],
                         [("execute:send_email", "done"), ("approve:send_email", "APPROVED_BY_YOU"), ("propose:send_email", "REQUIRE_APPROVAL")])

    def test_audit_is_append_only_and_shown_by_the_cli(self):
        approvals.propose("email_reply", "send_email", MAIL | {"job_id": self.jid}, "thanks", self.jid, force_pending=True)
        with self.assertRaises(Exception):
            db.con().execute("UPDATE audit SET result='ALLOW'")
        with self.assertRaises(Exception):
            db.con().execute("DELETE FROM audit")
        out = run_cli("audit", "--limit", "5")
        self.assertIn("propose:send_email", out)
        self.assertIn("REQUIRE_APPROVAL", out)
        self.assertIn("requested_review", out)


class SafetySensitive(Base):
    def test_licensed_occupation_never_auto_submits(self):
        jid = db.add_job("Mercy Health", "Registered Nurse", None, "jd", "via test")
        why = apply_agent.auto_blockers(db.get_job(jid), "greenhouse")
        self.assertTrue(any("licensed occupation" in w for w in why), why)
        other = db.add_job("Acme", "Data Engineer", None, "jd", "via test")
        self.assertFalse(any("licensed occupation" in w for w in apply_agent.auto_blockers(db.get_job(other), "greenhouse")))


if __name__ == "__main__":
    unittest.main()
