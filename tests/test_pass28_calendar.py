"""Pass 28: calendar busy times (Google Calendar FreeBusy, opt-in, least privilege: blueprint 12.2) in interview
replies and slot proposals, and profession-aware research wording (12.3: never software-only by default). No network:
util.fetch and the OAuth token are faked; every patched attribute is put back."""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

sys.path.insert(0, str(Path(__file__).parent))
from test_pass21_fit import Base, patched  # noqa: E402

from lodestar import apply, calendar_busy, careers, oauth, settings, util  # noqa: E402

TOMORROW = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class Busy(Base):
    def fake(self, answer=None, error=None):
        self.calls = []

        def fetch(url, timeout=25, headers=None, data=None, **kw):
            self.calls.append({"url": url, "headers": headers or {}, "data": json.loads(data) if data else None})
            if error:
                raise error
            return json.dumps(answer or {})
        return patched(util, fetch=fetch)

    def test_off_by_default_and_never_asks(self):
        with self.fake({}), patched(oauth, access_token=lambda force=False: "tok"):
            self.assertEqual(calendar_busy.busy(), [])
        self.assertEqual(self.calls, [])

    def test_reads_google_freebusy_as_local_times(self):
        settings.set_pref("calendar_freebusy", True)
        start = TOMORROW.replace(hour=10).astimezone()
        ans = {"calendars": {"primary": {"busy": [{"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}]}}}
        with self.fake(ans), patched(oauth, access_token=lambda force=False: "tok"), \
                patched(calendar_busy, _provider=lambda: "google"):
            got = calendar_busy.busy(days=7)
        self.assertEqual(got, [(TOMORROW.replace(hour=10), TOMORROW.replace(hour=11))])
        call = self.calls[0]
        self.assertEqual(call["url"], "https://www.googleapis.com/calendar/v3/freeBusy")
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(call["data"]["items"], [{"id": "primary"}])

    def test_no_permission_or_no_google_sign_in_is_said_not_fatal(self):
        settings.set_pref("calendar_freebusy", True)
        err = urllib.error.HTTPError("https://www.googleapis.com/calendar/v3/freeBusy", 403, "insufficient scope", {}, None)
        with self.fake(error=err), patched(oauth, access_token=lambda force=False: "tok"), \
                patched(calendar_busy, _provider=lambda: "google"):
            self.assertEqual(calendar_busy.busy(), [])
        self.assertIn("sign in again", calendar_busy.LAST["error"])
        with patched(calendar_busy, _provider=lambda: "microsoft"):
            self.assertEqual(calendar_busy.busy(), [])
        self.assertIn("Google", calendar_busy.LAST["error"])

    def test_calendar_scope_is_asked_only_when_turned_on(self):
        url = oauth.auth_url("google", 8799, "st", "ch")[0]
        self.assertIn("mail.google.com", url)
        self.assertNotIn("calendar.freebusy", url)
        settings.set_pref("calendar_freebusy", True)
        self.assertIn("calendar.freebusy", oauth.auth_url("google", 8799, "st", "ch")[0])
        self.assertNotIn("calendar", oauth.auth_url("microsoft", 8799, "st", "ch")[0])  # Google only

    def test_slot_proposals_skip_busy_blocks(self):
        day = TOMORROW
        while day.weekday() >= 5:
            day += timedelta(days=1)
        slots = apply.next_slots(2, busy=[(day.replace(hour=9, minute=30), day.replace(hour=11))])
        self.assertNotIn(f"{day:%Y-%m-%d} 10:00", slots)
        self.assertIn(f"{day:%Y-%m-%d} 14:00", slots)


class Reply(Base):
    def test_an_interview_reply_avoids_your_calendar_blocks(self):
        from lodestar import ai, db, email_monitor

        settings.set_tool("interview_scheduling", enabled=True, auto=False)
        jid = db.add_job("Acme", "Data Engineer", None, "jd", "via test")
        block = (TOMORROW.replace(hour=9), TOMORROW.replace(hour=17))
        prompts = []

        def ask_json(prompt, *a, **k):
            prompts.append(prompt)
            return {"subject": "Re: interview", "body": "Thanks, any of these work.", "chosen_time": None}
        with patched(calendar_busy, busy=lambda days=14: [block]), patched(ai, ask_json=ask_json):
            email_monitor._maybe_reply({"category": "interview", "from": "Rec <rec@acme.example>", "subject": "Interview",
                                        "body": "When are you free?", "sender_email": "rec@acme.example", "trusted": True,
                                        "message_id": "<i1@acme.example>"}, db.get_job(jid))
        self.assertIn(f"{TOMORROW:%Y-%m-%d} 09:00-17:00", prompts[0])  # times only, never what the block is
        self.assertNotIn(f"{TOMORROW:%Y-%m-%d} 10:00", prompts[0].split("chosen from:")[1].split(".")[0])


class Research(Base):
    def test_research_wording_follows_the_occupation(self):
        nurse, dev = careers.work_focus("Registered Nurse"), careers.work_focus("Software Engineer")
        self.assertNotIn("engineering", nurse)
        self.assertIn("ways of working", nurse)
        self.assertIn("engineering culture", dev)
        self.assertNotIn("engineering", careers.work_focus("Ninja Rockstar"))  # unknown: generic, never software


if __name__ == "__main__":
    unittest.main()
