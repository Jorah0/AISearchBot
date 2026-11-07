"""Pass 15, group G: insights (weekly series, response rate by source and match band, funnel, variants), weekly goals,
structured offers (comp.total, compare, counter-offer through the Inbox) and the activity log for unemployment claims.
Only the user's own actions count. No network: AI calls are faked and every patched attribute is put back."""
import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply, comp, contacts, db, extras, profile, settings  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

FLOOR = 187654
PROFILE_WITH_FLOOR = ("# Jane Doe\njane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built data pipelines\n\n"
                      f"## Preferences\nTarget roles: data engineer | Salary floor: ${FLOOR:,} | Deal-breakers: none\n")
TODAY = date.today()


def ts(d: date) -> str:  # noon UTC: the same local calendar day in any timezone within +-11 h
    return f"{d.isoformat()} 12:00:00"


class Base(unittest.TestCase):
    """In-memory database; settings, profile and the market-rate table put back afterwards."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.files = (PROFILE, profile.BANK, settings.PATH, comp.PATH)
        self.snap = {p: p.read_bytes() for p in self.files if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        comp.PATH.unlink(missing_ok=True)
        PROFILE.write_text(PROFILE_WITH_FLOOR, encoding="utf-8")

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con
        for p in self.files:
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)

    def cli(self, *argv) -> str:
        a, out = build().parse_args(list(argv)), io.StringIO()
        with contextlib.redirect_stdout(out):
            a.f(a)
        return out.getvalue()

    def status_at(self, jid: int, status: str, d: date) -> None:
        db.con().execute("INSERT INTO events(job_id, ts, kind, detail) VALUES(?,?,?,?)", (jid, ts(d), "status", status))
        db.con().execute("UPDATE jobs SET status=? WHERE id=?", (status, jid))
        db.con().commit()

    def sent(self, jid, d: date, status: str = "done", **payload) -> int:
        pid = db.add_pending("followup", "send_email", jid, "mail", json.dumps({"to": "rita@acme.com", "subject": "s",
                                                                                "body": "b", "job_id": jid, **payload}))
        db.con().execute("UPDATE pending SET status=?, decided_at=? WHERE id=?", (status, ts(d), pid))
        db.con().commit()
        return pid


class Offers(Base):
    def test_total_vesting_cliff_and_estimates(self):
        t = comp.total({"base": 100000, "bonus_pct": 10, "sign_on": 5000, "equity_value_estimate": 48000,
                        "vest_years": 4, "cliff_months": 12, "retirement_match_pct": 5})
        self.assertEqual((t["bonus"], t["match"], t["equity_by_year"]), (10000, 5000, [12000, 12000, 12000, 12000]))
        self.assertEqual((t["year1_cash"], t["year1_total"]), (115000, 132000))
        self.assertEqual((t["four_year_cash"], t["four_year_total"]), (445000, 513000))
        self.assertIn("bonus at its target percentage", t["estimates"])
        late = comp.total({"base": 1, "equity_value_estimate": 48000, "vest_years": 4, "cliff_months": 18})
        self.assertEqual(late["equity_by_year"], [0, 24000, 12000, 12000])          # nothing before an 18-month cliff
        short = comp.total({"equity_value_estimate": 30000, "vest_years": 3, "cliff_months": 0})
        self.assertEqual(short["equity_by_year"], [10000, 10000, 10000, 0])
        none = comp.total({"equity_value_estimate": 40000})                        # defaults are named as estimates
        self.assertEqual(none["equity_by_year"], [10000] * 4)
        self.assertIn("4-year vesting (none stated)", none["estimates"])
        self.assertIn("no cliff (none stated)", none["estimates"])
        self.assertEqual(comp.total({})["four_year_total"], 0)

    def test_set_offer_validates_moves_status_and_goes_with_the_job(self):
        jid = db.add_job("Acme", "Data Engineer")
        for bad in ({"base": "lots"}, {"bonus_pct": "300"}, {"vest_years": "0"}, {"remote": "moon"}, {"deadline": "soon"},
                    {"salary": "1"}, {"notes": "x" * 2001}, {"base": "150k", "cliff_months": "99"}):
            with self.assertRaises(SystemExit, msg=bad):
                db.set_offer(jid, **bad)
        self.assertIsNone(db.get_offer(jid))                                      # a bad value changed nothing
        self.assertEqual(db.get_job(jid)["status"], "saved")
        clean = db.set_offer(jid, base="150k", bonus_pct="12.5%", equity_value_estimate="1,200,000", remote="Hybrid",
                             deadline="2026-12-01", notes="  my notes ")
        self.assertEqual(clean, {"base": 150000, "bonus_pct": 12.5, "equity_value_estimate": 1200000, "remote": "hybrid",
                                 "deadline": "2026-12-01", "notes": "my notes"})
        self.assertEqual(db.get_job(jid)["status"], "offer")                      # recording an offer is your own action
        db.set_offer(jid, notes="")
        self.assertIsNone(db.get_offer(jid)["notes"])                              # empty clears
        blank = db.add_job("Globex", "Eng")                                        # a blank form records nothing
        db.set_offer(blank, **{k: "" for k in db.OFFER_FIELDS})
        self.assertEqual((db.get_offer(blank), db.get_job(blank)["status"]), (None, "saved"))
        db.set_offer(blank, base="100k")
        db.set_offer(blank, **{k: "" for k in db.OFFER_FIELDS})                    # every field cleared: no offer row
        self.assertIsNone(db.get_offer(blank))
        db.set_status(jid, "rejected")
        db.set_offer(jid, base=1000)
        self.assertEqual(db.get_job(jid)["status"], "rejected")                   # never moved backwards
        db.delete_job(jid)
        self.assertIsNone(db.get_offer(jid))

    def test_compare_best_rows_market_and_private_floor(self):
        a, b = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "Data Engineer")
        db.set_offer(a, base=150000, sign_on=30000)
        db.set_offer(b, base=170000, equity_value_estimate=80000)
        db.add_job("Initech", "Data Engineer")                                    # not an offer: not compared
        comp.set_range("data engineer", "*", 160000, 190000)
        d = comp.compare()
        self.assertEqual(sorted(r["job_id"] for r in d["offers"]), [a, b])
        self.assertEqual(d["floor"], FLOOR)
        by = {r["job_id"]: r for r in d["offers"]}
        self.assertEqual((by[a]["vs_floor"], by[b]["vs_floor"]), (150000 - FLOOR, 170000 - FLOOR))
        self.assertEqual((by[a]["market"]["delta"], by[b]["market"]["delta"]), (-10000, 0))
        self.assertEqual((d["best"]["base"], d["best"]["sign_on"], d["best"]["equity_year1"]), ([b], [a], [b]))
        self.assertNotIn("bonus", d["best"])                                      # nobody has one: nothing to highlight
        PROFILE.write_text("# Jane\n## Skills\nPython\n## Preferences\nSalary floor: | Deal-breakers:\n", encoding="utf-8")
        self.assertIsNone(comp.compare()["floor"])
        self.assertIsNone(comp.compare()["offers"][0]["vs_floor"])

    def test_salary_floor_forms(self):
        for text, want in (("Salary floor: 150k", 150000), ("Salary floor: EUR 90,000 gross", 90000),
                           ("salary floor:$120,500.00", 120500), ("Salary floor: | Deal-breakers: 40", None),
                           ("Salary floor: 12", None)):
            PROFILE.write_text(f"# J\n## Preferences\n{text}\n", encoding="utf-8")
            self.assertEqual(profile.salary_floor(), want, text)

    def test_counter_never_names_the_floor_and_always_waits(self):
        mine, other = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "Data Engineer")
        db.update_job(mine, contact_email="rita@acme.com", contact_name="Rita")
        db.set_offer(mine, base=150000, notes=f"my floor is {FLOOR}")             # offer notes are private too
        db.set_offer(other, base=175000, sign_on=20000)
        seen, real_json, real_avail = [], ai.ask_json, ai.available
        ai.available = lambda: ["anthropic"]
        ai.ask_json = lambda prompt, *a, **k: seen.append(prompt) or {"subject": "Re: offer", "body": "ECHO " + prompt}
        settings.set_tool("email_reply", auto=True)                              # still waits: a counter is always reviewed
        try:
            r = apply.counter(db.get_job(mine), [f"{other}:base", f"{other}:sign_on"], "a base of 170,000")
            t = apply.counter(db.get_job(mine), [f"{other}:year1_total"], template=True)
        finally:
            ai.ask_json, ai.available = real_json, real_avail
        self.assertEqual((r["proposal"]["status"], t["proposal"]["status"]), ("pending", "pending"))
        self.assertIn("a base salary of 175,000", seen[0])
        self.assertIn("a first-year total of about 195,000", t["draft"]["body"])
        self.assertNotIn("Globex", seen[0] + t["draft"]["body"])                  # 'another offer', no company name
        for p in db.list_pending("pending"):
            blob = p["payload"] + p["summary"]
            for f in (str(FLOOR), f"{FLOOR:,}", "Salary floor", "Preferences"):
                self.assertNotIn(f, blob)
        for bad in ([f"{mine}:base"], ["x:base"], [f"{other}:notes"], [f"{other}:bonus_pct"]):
            with self.assertRaises(SystemExit, msg=bad):                          # self, junk, private, not recorded
                apply.counter(db.get_job(mine), bad, template=True)
        with self.assertRaises(SystemExit):
            apply.counter(db.get_job(mine), [], "", template=True)               # nothing to cite and no ask
        db.set_status(other, "withdrawn")
        with self.assertRaises(SystemExit):
            apply.counter(db.get_job(mine), [f"{other}:base"], template=True)    # not a live offer any more

    def test_offer_evaluation_reads_the_structured_table(self):
        a, b = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "SRE")
        db.set_offer(a, base=150000, bonus_pct=10)
        db.set_offer(b, base=160000)
        seen, real = [], ai.ask
        ai.ask = lambda prompt, *x, **k: seen.append(prompt) or "evaluation"
        try:
            apply.offer(db.get_job(a))
        finally:
            ai.ask = real
        self.assertIn("year-1 cash 165,000", seen[0])
        self.assertIn("base=160000", seen[0])                                     # the other live offer, structured


class Activity(Base):
    def test_only_your_own_actions_count(self):
        d1, d2 = TODAY - timedelta(days=TODAY.weekday() + 7), TODAY            # last week's Monday, today
        mine = db.add_job("Acme", "Data Engineer", notes="found via remotive")
        self.status_at(mine, "applied", d1)
        self.status_at(mine, "screening", d2)
        db.add_job("Robo", "Auto Pick", notes="auto-track fit 90: good (via remotive)")  # an auto-tracked save
        mail = db.add_job("Mailco", "Analyst", notes="from email")
        self.status_at(mail, "applied", d2)
        self.sent(mine, d1, purpose="followup")
        self.sent(mine, d2)                                                     # a reply: contacted
        self.sent(mine, d2, status="pending")
        self.sent(mine, d2, status="rejected")
        self.sent(mine, d2, status="error")
        self.sent(mine, d2, new_status="withdrawn")                             # withdrawing is not a search activity
        db.con().execute("INSERT INTO interviews(job_id, round, kind, at, interviewers, outcome) VALUES(?,?,?,?,?,?)",
                         (mine, 1, "phone", f"{d2.isoformat()} 09:00", "Sam", "passed"))
        db.con().execute("INSERT INTO interviews(job_id, round, kind, at) VALUES(?,?,?,?)",
                         (mine, 2, "onsite", (TODAY + timedelta(days=3)).isoformat()))  # not yet held
        cid = contacts.add(name="Pat", company="Acme", email="pat@acme.com", last_touch=d1.isoformat())
        contacts.edit(cid, last_touch=d2.isoformat())                           # "Touched today"
        contacts.touch("pat@acme.com")                                          # their mail: not your action
        rows = extras.activity_log(d1, d2 + timedelta(days=30))
        got = sorted((r["date"], r["activity"], r["employer"], r["method"], r["result"]) for r in rows)
        want = sorted([(d1.isoformat(), "applied", "Acme", "online", "screening"),
                       (d2.isoformat(), "applied", "Mailco", "email", "applied"),
                       (d1.isoformat(), "followed_up", "Acme", "email", "sent"),
                       (d2.isoformat(), "contacted", "Acme", "email", "sent"),
                       (d2.isoformat(), "interviewed", "Acme", "phone", "passed"),
                       (d1.isoformat(), "contacted", "Acme", "", ""),
                       (d2.isoformat(), "contacted", "Acme", "", "")])
        self.assertEqual(got, want)
        self.assertEqual(extras.activity_log(d2, d1), [])
        settings.set_pref("activity_weekly_min", 3)
        rep = extras.activity_report(d1, d2)
        self.assertEqual([(w["week"], w["count"], w["met"]) for w in rep["weeks"]][:2],
                         [(d1.isoformat(), 3, True), ((d1 + timedelta(days=7)).isoformat(), 4, True)])
        self.assertIn("check your state's requirements", rep["note"])
        with self.assertRaises(SystemExit):
            extras.activity_report(d2, d1)
        with self.assertRaises(SystemExit):
            extras.activity_report("yesterday", d2)
        for bad in (-1, 101, "x"):
            with self.assertRaises(SystemExit):
                settings.set_pref("activity_weekly_min", bad)

    def test_csv_and_printable_exports(self):
        jid = db.add_job("=HYPERLINK(\"http://evil\")", "Data Engineer")
        self.status_at(jid, "applied", TODAY)
        folder = Path(tempfile.mkdtemp())
        out = extras.activity_export(TODAY, TODAY, "csv", folder)
        with out.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], list(extras.ACTIVITY_COLUMNS))
        self.assertTrue(rows[1][2].startswith("'="))                             # never a live spreadsheet formula
        html = extras.activity_export(TODAY, TODAY, "html", folder)
        page = html.read_text(encoding="utf-8")
        self.assertIn("check your state", page)
        self.assertIn("&quot;http://evil&quot;", page)                          # escaped in the print page
        self.assertTrue(html.with_suffix(".md").is_file())
        with self.assertRaises(SystemExit):
            extras.activity_export(TODAY, TODAY, "xls", folder)
        from lodestar import contacts
        contacts.add(name="Eve", company="=HYPERLINK(\"http://evil\")", position="@SUM(A1)")
        out = extras.export_data("csv", folder)                                 # the full export: every table defused
        with next(out.glob("contacts-*.csv")).open(encoding="utf-8") as f:
            eve = list(csv.DictReader(f))[0]
        self.assertEqual((eve["company"][:2], eve["position"][:2], eve["name"]), ("'=", "'@", "Eve"))
        with next(out.glob("jobs-*.csv")).open(encoding="utf-8") as f:
            self.assertTrue(list(csv.DictReader(f))[0]["company"].startswith("'="))

    def test_activity_command(self):
        jid = db.add_job("Acme", "Data Engineer")
        self.status_at(jid, "applied", TODAY)
        out = self.cli("activity")
        self.assertIn("applied", out)
        self.assertIn("check your state's requirements", out)
        self.assertIn("Acme", self.cli("activity", "--from", (TODAY - timedelta(days=40)).isoformat()))
        with self.assertRaises(SystemExit):
            self.cli("activity", "--to", TODAY.isoformat())


class Insights(Base):
    def test_series_rates_goals_and_digest(self):
        week0 = TODAY - timedelta(days=TODAY.weekday())
        jobs = []
        for i in range(6):                                                      # six applications scored 80+
            j = db.add_job(f"Co{i}", "Data Engineer", notes="found via remotive")
            db.set_fields(j, match_score=85)
            self.status_at(j, "applied", week0 - timedelta(days=7) if i < 2 else TODAY)
            jobs.append(j)
        self.status_at(jobs[0], "interview", TODAY)
        self.status_at(jobs[1], "rejected", TODAY)
        self.status_at(jobs[2], "offer", TODAY)
        low = db.add_job("Lowco", "Analyst", notes="captured from https://x")
        db.set_fields(low, match_score=30)
        self.status_at(low, "applied", TODAY)
        db.update_job(jobs[3], resume_hash="abc12345")                            # a tailored application
        db.con().execute("INSERT INTO mock_sessions(job_id, ts, answers, averages) VALUES(?,?,?,?)", (jobs[0], ts(TODAY), "[]", "{}"))
        db.con().commit()
        cid = contacts.add(name="Pat", company="Co1", last_touch=TODAY.isoformat())
        self.sent(jobs[0], TODAY, purpose="followup")                             # rita@acme.com: a second person
        a = extras.analytics(4)
        self.assertEqual(len(a["weeks"]), 4)
        last, prev = a["weeks"][-1], a["weeks"][-2]
        self.assertEqual(last["start"], week0.isoformat())
        self.assertEqual((last["applications"], last["offers"], last["contacts"], last["mock_sessions"]), (5, 1, 2, 1))
        self.assertEqual(prev["applications"], 2)
        band = {g["group"]: g for g in a["by_band"]}
        self.assertEqual(list(band), ["<40", "40-59", "60-79", "80+", "unscored"])
        self.assertEqual((band["80+"]["n"], band["80+"]["response_rate"], band["80+"]["interview_rate"]), (6, 0.5, 0.33))
        self.assertEqual((band["<40"]["n"], band["<40"]["response_rate"], band["<40"]["enough"]), (1, None, False))
        src = {g["group"]: g for g in a["by_source"]}
        self.assertEqual((src["search:remotive"]["n"], src["captured"]["response_rate"]), (6, None))
        self.assertEqual(a["funnel"], db.funnel())                                # reused, not rebuilt
        self.assertEqual(a["variants"], db.variant_stats())
        self.assertEqual(a["goals"], [])                                          # no goal by default
        self.assertEqual(settings.pref("weekly_goals"), {})
        real = extras.ai.available
        extras.ai.available = lambda: []                                          # the digest without its AI paragraph
        try:
            self.assertNotIn("Weekly goals", extras.digest(7))
            settings.set_pref("weekly_goals", "contacts=5")
            settings.set_pref("weekly_goals", {"contacts": "5", "tailored_applications": 2, "applications": 0, "mock_sessions": ""})
            self.assertEqual(settings.pref("weekly_goals"), {"contacts": 5, "tailored_applications": 2})
            for bad in ("speed=3", "contacts=-1", "contacts=lots", "contacts", {"applications": 5000}):
                with self.assertRaises(SystemExit, msg=bad):
                    settings.set_pref("weekly_goals", bad)
            g = {x["goal"]: (x["done"], x["target"]) for x in extras.goal_progress()}
            self.assertEqual(g, {"contacts": (2, 5), "tailored_applications": (1, 2)})
            self.assertIn("- contacts: 2 of 5", extras.digest(7))
        finally:
            extras.ai.available = real
        contacts.remove(cid)
        self.assertEqual(db.con().execute("SELECT COUNT(*) n FROM touches").fetchone()["n"], 0)

    def test_insights_and_offers_commands(self):
        a, b = db.add_job("Acme", "Data Engineer"), db.add_job("Globex", "SRE")
        self.assertIn("status: offer", self.cli("offers", "set", str(a), "base=150k", "sign_on=10000"))
        self.cli("offers", "set", str(b), "base=160000")
        out = self.cli("offers")
        self.assertIn("vs your floor", out)
        self.assertIn("160,000 *", out)
        with self.assertRaises(SystemExit):
            self.cli("offers", "set", str(a), "base")
        out = self.cli("offers", "counter", str(a), "--cite", f"{b}:base", "--template")
        self.assertIn("a base salary of 160,000", out)
        self.assertNotIn(str(FLOOR), out)
        out = self.cli("insights", "--weeks", "3")
        self.assertIn("not enough data yet", out)
        self.assertIn("Weekly goals: none set", out)
        self.assertEqual(len(json.loads(self.cli("insights", "--json", "--weeks", "2"))["weeks"]), 2)


class Routes(unittest.TestCase):
    def test_insight_offer_and_activity_routes(self):
        import http.client
        from lodestar import desktop, web

        saved = getattr(db._local, "con", None)
        db._local.con = db.connect()  # the server thread opens the on-disk database, so this test uses it too
        port = desktop.free_port(8930); srv = web.start_server(port)
        h = {"Content-Type": "application/json", "X-Lodestar-Token": web.TOKEN, "Host": f"127.0.0.1:{port}"}
        ids = []
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)

            def call(path, body=None, headers=h):
                c.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse(); return r.status, json.loads(r.read())

            def task(action, body):
                tid = call(f"/api/run/{action}", body)[1]["task"]
                for _ in range(50):
                    t = call(f"/api/tasks/{tid}")[1]
                    if t["status"] != "running":
                        return t
                    time.sleep(0.1)
            ids += [db.add_job("Zzoffer <b>", "Dev"), db.add_job("Zzother", "Dev")]
            db.update_job(ids[0], contact_email="hr@zzoffer.com")
            self.assertEqual(call(f"/api/offers/{ids[0]}", {"base": "150k"})[0], 200)
            self.assertEqual(call(f"/api/offers/{ids[1]}", {"base": 165000, "sign_on": "5k"})[0], 200)
            self.assertEqual(call(f"/api/offers/{ids[0]}", {"base": "lots"})[0], 400)
            self.assertEqual(call(f"/api/offers/{ids[0]}", {"floor": 1})[0], 400)          # unknown keys refused
            self.assertEqual(call(f"/api/offers/{ids[0]}", {"base": 1}, {**h, "X-Lodestar-Token": "no"})[0], 403)
            self.assertEqual(call("/api/analytics", None, {**h, "X-Lodestar-Token": "no"})[0], 403)
            st, o = call("/api/offers")
            self.assertEqual(st, 200)
            self.assertIn(ids[1], o["best"]["base"])
            self.assertIn("year1_total", o["cite"])
            st, a = call("/api/analytics")
            self.assertEqual((st, a["goal_keys"][0], len(a["weeks"])), (200, "contacts", 12))
            t = task("counter", {"id": ids[0], "cite": [f"{ids[1]}:base"], "template": True})
            self.assertEqual(t["result"]["proposal"]["status"], "pending", t)
            self.assertEqual(task("counter", {"id": ids[0], "cite": "x"})["status"], "error")
            t = task("activity", {"from": TODAY.isoformat(), "to": TODAY.isoformat(), "fmt": "csv"})
            self.assertTrue(t["result"]["path"].endswith(".csv"), t)
            self.assertEqual(task("activity", {"from": "bad", "to": TODAY.isoformat()})["status"], "error")
            c.close()
        finally:
            srv.shutdown()
            for i in ids:  # also drops their offers and the counter-offer still pending in the Inbox
                db.delete_job(i)
            db._local.con.close()
            db._local.con = saved


if __name__ == "__main__":
    unittest.main()
