"""Mail viewer (pass 33): a filed email keeps its whole text (codes already masked by the scan) and what the
classifier read from it (next action, deadline); the Mail page lists every recorded mail both ways with its type, and
one mail opens with its full text (older rows fall back to the stored snippet). List rows never carry the body.
No network; every patched attribute is put back."""
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
import test_pass16_mail as p16  # noqa: E402
from test_pass16_mail import MailBase  # noqa: E402

from lodestar import db, email_monitor as em  # noqa: E402

LONG = "Hi Pat,\n\n" + "We would like to schedule a panel interview. " * 120 + "\n\nBest, Rosa"


class Viewer(MailBase):
    def test_a_filed_mail_keeps_its_full_text_action_and_deadline(self):
        jid = db.add_job("Kestrel Labs", "Data Engineer")
        info = self.info("rosa@kestrel.example", message_id="<viewer-full@example.net>", full_body=LONG, body=LONG[:3500], action="Pick a slot by Friday",
                         deadline="2026-11-20 14:00")
        em._record(info, db.get_job(jid))
        m = self.row(info["message_id"])
        self.assertEqual((m["body"], m["action"], m["deadline"]), (LONG, "Pick a slot by Friday", "2026-11-20 14:00"))
        self.assertEqual(len(m["snippet"]), 1500)

    def test_all_mail_lists_both_ways_and_filters_by_type(self):
        db.add_mail(message_id="<v-in@example.com>", direction="in", subject="Offer letter", category="offer")
        db.add_mail(message_id="<v-out@example.com>", direction="out", subject="Thanks")
        rows = {r["message_id"]: r for r in db.all_mail()}
        self.assertTrue({"<v-in@example.com>", "<v-out@example.com>"} <= set(rows))
        self.assertEqual({r["message_id"] for r in db.all_mail(category="offer")} & {"<v-in@example.com>", "<v-out@example.com>"},
                         {"<v-in@example.com>"})


class ViewerRoutes(MailBase):
    req = p16.Surfaces.req

    def test_list_has_no_body_and_one_mail_opens_in_full(self):
        from lodestar import desktop, web
        mem = getattr(db._local, "con", None)
        db._local.con = None
        db.add_mail(message_id="<vr-1@example.com>", direction="in", subject="Panel", category="interview",
                    snippet=LONG, body=LONG, action="reply")
        db.add_mail(message_id="<vr-old@example.com>", direction="in", subject="Older", snippet="short text only")
        new, old = (self.row(m)["id"] for m in ("<vr-1@example.com>", "<vr-old@example.com>"))
        self.port = desktop.free_port(9010)
        srv = web.start_server(self.port)
        try:
            self.assertEqual(self.req("GET", f"/api/mail/{new}", token=False)[0], 403)
            code, body = self.req("GET", "/api/mail?all=1")
            listed = {m["id"]: m for m in json.loads(body)["mail"]}
            self.assertEqual(code, 200)
            self.assertNotIn("body", listed[new])
            self.assertEqual(listed[new]["category"], "interview")
            one = json.loads(self.req("GET", f"/api/mail/{new}")[1])["mail"]
            self.assertEqual((one["body"], one["action"]), (LONG, "reply"))
            self.assertEqual(json.loads(self.req("GET", f"/api/mail/{old}")[1])["mail"]["body"], "short text only")
            self.assertEqual(self.req("GET", "/api/mail/999999")[0], 404)
        finally:
            srv.shutdown(); srv.server_close()
            db.release()
            db._local.con = mem


if __name__ == "__main__":
    unittest.main()
