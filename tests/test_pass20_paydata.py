"""Pass 20: automatic market pay from BLS OEWS (paydata.py). Title -> SOC (crosswalk, your override, an AI pick from a
fixed list), location -> metro / state / national chain, one batched POST per query under a daily budget (atomic, refunded
when the network never answered), parse of both API shapes with footnote-5 caps, a SQLite cache that never refetches the
current release, honesty labels from the row, the board / offers / counter-offer / prompts reading the cache only, and
the salary floor never read. No network: util.fetch is a fake BLS (one test POSTs to a local server); every patched
attribute is put back."""
import contextlib
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from datetime import date

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""

from lodestar import ai, apply, comp, db, paydata, profile, settings, util, web  # noqa: E402
from lodestar.cli import build  # noqa: E402
from lodestar.config import PROFILE  # noqa: E402

FLOOR = 171717
PROFILE_MD = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com\n## Skills\nPython, SQL\n## Experience\n- Built pipelines\n\n"
              f"## Preferences\nSalary floor: ${FLOOR:,} | Deal-breakers: none\n")
SEA = {"mean": 174920, "p10": 99190, "p25": 132800, "p50": 167280, "p75": 211860, "p90": 257960}  # May 2025, verified
DT = {v: k for k, v in paydata.DATATYPES.items()}


@contextlib.contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(obj, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def cells(soc, area, figs, year="2025", foot=None):
    """{series id: (value, footnotes)} for a pair; foot = {field: footnotes} overrides."""
    return {paydata.series_id(soc, area, DT[k]): (str(v), (foot or {}).get(k, [{}]), year) for k, v in figs.items()}


def answer(table: dict, ids=None, v2=False, status="REQUEST_SUCCEEDED", message=()):
    ids = list(table) if ids is None else ids
    series: dict = {}
    for s in ids:
        if s in table:
            for v, f, y in (table[s] if isinstance(table[s], list) else [table[s]]):
                series.setdefault(s, []).append({"year": y, "period": "A01", "periodName": "Annual", "latest": "true",
                                                 "value": v, "footnotes": f})
    msg = list(message) + [f"Series does not exist for Series {s}" for s in ids if s not in table]
    res = [{"series": [{"seriesID": s, "data": d} for s, d in series.items()]}] if v2 else \
        {"series": [{"seriesID": s, "data": d} for s, d in series.items()]}
    return json.dumps({"status": status, "responseTime": 9, "message": msg, "Results": res})


class FakeBLS:
    """util.fetch for api.bls.gov: answers the series in `table`, 'Series does not exist' for the rest."""

    def __init__(self, table=None, error=None, doc=None):
        self.table, self.error, self.doc, self.calls = table or {}, error, doc, []

    def __call__(self, url, timeout=25, headers=None, max_bytes=None, follow=True, data=None):
        body = json.loads(data)
        self.calls.append((url, body, headers))
        if self.error:
            raise self.error
        return json.dumps(self.doc) if self.doc else answer(self.table, body["seriesid"])


class Base(unittest.TestCase):
    """In-memory database, market pay on, profile / settings put back afterwards, no BLS key from the environment."""

    def setUp(self):
        self._con = getattr(db._local, "con", None)
        db._local.con = db.connect(":memory:")
        self.files = (PROFILE, profile.BANK, settings.PATH, comp.PATH)
        self.snap = {p: p.read_bytes() for p in self.files if p.is_file()}
        settings.PATH.unlink(missing_ok=True)
        profile.BANK.unlink(missing_ok=True)
        PROFILE.write_text(PROFILE_MD, encoding="utf-8")
        settings.set_pref("market_pay", "on")
        self.key = os.environ.pop("BLS_API_KEY", None)

    def tearDown(self):
        db._local.con.close()
        db._local.con = self._con
        for p in self.files:
            p.write_bytes(self.snap[p]) if p in self.snap else p.unlink(missing_ok=True)
        os.environ.pop("BLS_API_KEY", None)
        if self.key is not None:
            os.environ["BLS_API_KEY"] = self.key

    def job(self, title="Senior Software Engineer", location="Bellevue, WA", status="saved", **kw):
        jid = db.add_job("Acme", title, None, "Build services in Python.", None, location=location, **kw)
        if status != "saved":
            db.set_status(jid, status)
        return db.get_job(jid)

    def cache(self, soc, area, figs, year=2025, fetched="2026-11-07 10:00:00", capped=()):
        row = {"soc": soc, "area": area, "year": year if figs else None, "capped": list(capped),
               **{f: figs.get(f) for f in paydata.FIELDS}}
        paydata._save([row])
        db.con().execute("UPDATE paydata SET fetched_at=? WHERE soc=? AND area=?", (fetched, soc, area))
        db.con().commit()

    def cli(self, *argv) -> str:
        a, out = build().parse_args(list(argv)), io.StringIO()
        with contextlib.redirect_stdout(out):
            a.f(a)
        return out.getvalue()


class Matching(unittest.TestCase):
    def test_series_id_and_the_title_crosswalk(self):
        self.assertEqual(paydata.series_id("15-1252", "M0042660", "13"), "OEUM004266000000015125213")  # verified live
        want = {"Senior Software Engineer": "15-1252", "Sr. Software Engineer": "15-1252",
                "Software Engineer in Test": "15-1253", "Technical Program Manager": "13-1082",
                "Data Engineering Manager": "11-3021", "FP&A Analyst": "13-2051", "Account Manager": None,
                "Product Manager": None}  # product manager: dropped (no BLS occupation; you or the AI decide)
        for title, soc in want.items():
            got = paydata.soc_for({"title": title, "soc": None, "soc_by": None})
            self.assertEqual(got and got["soc"], soc, title)
        sre = paydata.soc_for({"title": "Site Reliability Engineer", "soc": None, "soc_by": None})
        self.assertEqual((sre["soc"], sre["by"]), ("15-1299", "keyword 'site reliability engineer' (closest BLS group)"))
        mine = paydata.soc_for({"title": "Senior Software Engineer", "soc": "15-2051", "soc_by": "user"})
        ai_pick = paydata.soc_for({"title": "Quant Wizard", "soc": "15-2051", "soc_by": "ai"})
        self.assertEqual((mine["by"], ai_pick["by"]), ("you", "AI"))
        self.assertEqual(paydata.soc_for({"title": "Software Engineer", "soc": "15-2051", "soc_by": "ai"})["soc"], "15-1252")

    def test_location_chain_metro_state_national_and_remote(self):
        def first(loc, remote=None, home=None):
            c = paydata.area_for(loc, remote, home)
            return c[0]["area"] if c else None
        self.assertEqual([a["area"] for a in paydata.area_for("Bellevue, WA", None)], ["M0042660", "S5300000", "N0000000"])
        for loc, area in {"Spokane, WA": "S5300000", "Washington, D.C.": "M0047900", "Portland, OR": "M0038900",
                          "Portland, ME": "S2300000", "United States": "N0000000", "Remote (US)": "N0000000",
                          "": "N0000000", "London, UK": None, "Boise": None, "Cambridge, UK": None,
                          "Arlington, TX": "M0019100", "Arlington, VA": "M0047900", "Austin, MN": "S2700000",
                          "Charleston, West Virginia": "S5400000", "Seattle": "M0042660"}.items():
            self.assertEqual(first(loc), area, loc)
        # outside the U.S.: a country code or name that is also a state's never borrows that state's figures
        for loc in ("Berlin, DE", "Tel Aviv, IL", "Bogotá, CO", "Hyderabad, IN", "Tbilisi, Georgia", "Munich, Germany (DE)",
                    "Toronto, CA", "Berlin, Germany", "Paris, France", "Toronto, ON", "Mexico City, Mexico", "Bengaluru, India"):
            self.assertEqual(paydata.area_for(loc, None), [], loc)
        for loc, area in {"Berlin, NH": "S3300000", "Vancouver, WA": "S5300000", "Atlanta, Georgia": "M0012060",
                          "Albuquerque, New Mexico": "S3500000", "Wilmington, DE": "S1000000", "Boston, MA": "M0014460",
                          "Paris, TX": "S4800000", "Dublin, CA": "S0600000"}.items():
            self.assertEqual(paydata.area_for(loc, None)[-2]["area"] if area.startswith("S") else first(loc), area, loc)
        home = paydata.area_for("Austin, TX", None)
        r = paydata.area_for("anywhere", "remote", home)
        self.assertEqual((r[0]["area"], r[0]["why"], r[-1]["why"]), ("M0012420", "remote: home area", "remote: national"))
        self.assertEqual([(a["area"], a["why"]) for a in paydata.area_for("Seattle, WA", "remote", [])],
                         [("N0000000", "remote: national")])

    def test_data_file_is_sound_and_records_its_live_check(self):
        d = json.loads(paydata.DATA.read_text(encoding="utf-8"))
        occ = d["occupations"]
        self.assertEqual([t[0] for t in d["titles"] if t[1] not in occ], [])
        kws = [paydata.norm_title(t[0]) for t in d["titles"]]
        self.assertEqual(len(kws), len(set(kws)), "a keyword is listed twice")
        self.assertNotIn("product manager", kws)
        self.assertTrue(all(len(t) == 2 or t[2] == "closest BLS group" for t in d["titles"]))
        self.assertTrue(all(c.count("-") == 1 and len(c) == 7 for c in occ))
        self.assertEqual([m[0] for m in d["metros"] if not (m[0].startswith("M00") and len(m[0]) == 8 and m[0][1:].isdigit())], [])
        self.assertEqual([k for k, v in d["states"].items() if not (len(v[0]) == 2 and v[0].isdigit())], [])
        self.assertEqual(len(d["states"]), 52)
        for m in d["metros"]:
            self.assertTrue(set(m[2].rsplit(", ", 1)[-1].split("-")) <= set(d["states"]), m[2])
        self.assertIn("2026-11-11", json.dumps(d["verified"]))


class Parse(unittest.TestCase):
    def test_both_shapes_caps_missing_cells_and_release_day(self):
        soc, area = "15-1252", "M0042660"
        table = cells(soc, area, SEA)
        rows = paydata._parse(json.loads(answer(table)), [(soc, area)])  # v1: Results is an object, footnotes [{}]
        self.assertEqual({k: rows[0][k] for k in paydata.FIELDS} | {"year": rows[0]["year"]}, SEA | {"year": 2025})
        rows2 = paydata._parse(json.loads(answer(table, v2=True)), [(soc, area)])
        self.assertEqual(rows2, rows)
        five = [{"code": "5", "text": "This wage is equal to or greater than $115.00 per hour or $239,200 per year."}]
        capped = dict(table)
        capped[paydata.series_id(soc, area, "15")] = ("257960", five, "2025")  # a number with footnote 5: kept, capped
        capped[paydata.series_id(soc, area, "14")] = ("-", five, "2025")  # withheld: the footnote's figure
        capped[paydata.series_id(soc, area, "11")] = ("-", [{}], "2025")  # no footnote 5: nothing
        del capped[paydata.series_id(soc, area, "12")]  # not published
        r = paydata._parse(json.loads(answer(capped)), [(soc, area)])[0]
        self.assertEqual((r["p90"], r["p75"], r["p10"], r["p25"]), (257960, 239200, None, None))
        self.assertEqual(sorted(r["capped"]), ["p75", "p90"])
        none = paydata._parse(json.loads(answer({})), [(soc, area)])[0]
        self.assertEqual((none["year"], [none[f] for f in paydata.FIELDS]), (None, [None] * 6))  # the negative row
        mixed = {s: [(v, f, "2025"), (str(int(v) + 1000), f, "2026")] if s.endswith("13") else (v, f, "2025")
                 for s, (v, f, _) in table.items()}
        r = paydata._parse(json.loads(answer(mixed)), [(soc, area)])[0]
        self.assertEqual((r["year"], r["p50"], r["p75"]), (2026, SEA["p50"] + 1000, None))  # never two releases in one row

    def test_band_boundaries(self):
        self.assertEqual(paydata.band(SEA["p25"], SEA), "25th-median")
        self.assertEqual(paydata.band(SEA["p10"] - 1, SEA), "below 10th")
        self.assertEqual(paydata.band(SEA["p90"], SEA), "above 90th")
        self.assertEqual(paydata.band(200000, SEA), "median-75th")
        self.assertEqual(paydata.band(None, SEA), "")


class Cache(Base):
    def test_second_read_makes_no_call_and_the_release_stays_fresh_until_june_y_plus_2(self):
        j = self.job()
        fake = FakeBLS(cells("15-1252", "M0042660", SEA))
        with patched(util, fetch=fake):
            self.assertEqual(paydata.for_job(j)["next"], ["15-1252", "M0042660"])
            self.assertEqual(paydata.fetch([paydata.for_job(j)["next"]]), {"fetched": 1})
            r = paydata.for_job(j)
            self.assertEqual(paydata.fetch([("15-1252", "M0042660")]), {"fetched": 0})
        self.assertEqual(len(fake.calls), 1)
        url, body, headers = fake.calls[0]
        self.assertEqual((url, headers), (paydata.V1, {"Content-Type": "application/json"}))
        self.assertEqual(sorted(body["seriesid"]), sorted(cells("15-1252", "M0042660", SEA)))  # series ids only
        self.assertNotIn("registrationkey", body)
        self.assertEqual((r["state"], r["next"], r["area"]["area"], r["pay"]["p50"]), ("ok", None, "M0042660", 167280))
        self.assertEqual(r["soc"]["by"], "keyword 'software engineer'")
        self.cache("15-1252", "M0042660", SEA, fetched="2026-01-01 00:00:00")
        with patched(paydata, _today=lambda: date(2027, 5, 31)):
            self.assertEqual(paydata.for_job(j)["state"], "ok")
        with patched(paydata, _today=lambda: date(2027, 6, 1)):
            r = paydata.for_job(j)
            self.assertEqual((r["state"], r["next"], r["pay"]["p50"]), ("stale", ["15-1252", "M0042660"], 167280))

    def test_a_negative_metro_falls_through_to_the_state_and_refetches_after_30_days(self):
        j = self.job(title="Platform Engineer", location="Seattle, WA")
        self.cache("15-1299", "M0042660", {}, fetched="2026-11-01 00:00:00")
        with patched(paydata, _today=lambda: date(2026, 11, 10)):
            r = paydata.for_job(j)
            self.assertEqual((r["state"], r["next"]), ("missing", ["15-1299", "S5300000"]))
            self.cache("15-1299", "S5300000", {"p50": 150000, "p75": 180000})
            r = paydata.for_job(j)
            self.assertEqual((r["state"], r["area"]["area"], r["next"], r["pay"]["p50"]), ("ok", "S5300000", None, 150000))
            self.assertIn("BLS publishes no figure for this occupation in Seattle-Tacoma-Bellevue", r["area_note"])
        with patched(paydata, _today=lambda: date(2026, 12, 2)):  # the negative row is 31 days old: asked again first
            self.assertEqual(paydata.for_job(j)["next"], ["15-1299", "M0042660"])
        self.cache("15-1299", "S5300000", {})
        self.cache("15-1299", "N0000000", {})
        with patched(paydata, _today=lambda: date(2026, 11, 10)):
            self.assertEqual(paydata.for_job(j)["state"], "unpublished")

    def test_budget_is_atomic_and_refused_without_a_call(self):
        j = self.job()
        fake = FakeBLS(cells("15-1252", "M0042660", SEA))
        c = db.con()
        c.execute("INSERT INTO meta(key, value) VALUES(?, 20)", (paydata._day(),))
        c.commit()
        with patched(util, fetch=fake):
            r = paydata.fetch([paydata.for_job(j)["next"]])
        self.assertEqual((fake.calls, r["fetched"]), ([], 0))
        self.assertIn("BLS limit reached (25 queries a day without a key)", r["error"])
        self.assertIn("BLS_API_KEY", r["error"])
        # two threads (their own connections to the data file) racing for the last unit: one grant
        day, got = "bls:test-race", []

        def on_file(fn):
            def run():
                try:
                    fn()
                finally:
                    db.release()
            t = threading.Thread(target=run)
            t.start()
            return t
        with patched(paydata, _day=lambda: day):
            on_file(lambda: (db.con().execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, 19)", (day,)),
                             db.con().commit())).join()
            gate = threading.Barrier(2)
            for t in [on_file(lambda: (gate.wait(), got.append(paydata._spend(20)))) for _ in range(2)]:
                t.join()
            on_file(lambda: (db.con().execute("DELETE FROM meta WHERE key=?", (day,)), db.con().commit())).join()
        self.assertEqual(sorted(got), [False, True])

    def test_429_threshold_other_messages_and_the_key_never_echoed(self):
        j = self.job()
        pair = [paydata.for_job(j)["next"]]
        too_many = urllib.error.HTTPError(paydata.V1, 429, "Too Many Requests", {}, io.BytesIO())
        self.addCleanup(too_many.close)
        for fake in (FakeBLS(error=too_many),
                     FakeBLS(doc={"status": "REQUEST_NOT_PROCESSED", "message": ["Daily threshold for total number of "
                                                                                  "requests allocated has been reached."]})):
            c = db.con()
            c.execute("DELETE FROM meta")
            c.commit()
            with patched(util, fetch=fake):
                r = paydata.fetch(pair)
            self.assertIn("BLS limit reached", r["error"])
            self.assertNotIn("unreachable", r["error"])
            self.assertEqual(paydata.used(), 20)  # no more tries today
        db.con().execute("DELETE FROM meta")
        with patched(util, fetch=FakeBLS(doc={"status": "REQUEST_NOT_PROCESSED", "message": ["Invalid series id"]})):
            self.assertEqual(paydata.fetch(pair)["error"], "BLS: Invalid series id")
        os.environ["BLS_API_KEY"] = "SECRETKEY0123456789"
        jobs = [self.job(location=loc) for loc in ("Seattle, WA", "Spokane, WA", "Austin, TX", "Dallas, TX", "Denver, CO",
                                                   "Boston, MA", "Chicago, IL", "Miami, FL", "Atlanta, GA")]
        fake = FakeBLS()
        with patched(util, fetch=fake):
            r = paydata.fetch([paydata.for_job(x)["next"] for x in jobs])
        self.assertEqual((r, [len(b["seriesid"]) for _, b, _ in fake.calls]), ({"fetched": 9}, [48, 6]))  # 8 pairs a query
        self.assertTrue(all(u == paydata.V2 and b["registrationkey"] == "SECRETKEY0123456789" for u, b, _ in fake.calls))
        echo = FakeBLS(doc={"status": "REQUEST_NOT_PROCESSED", "message": ["The key SECRETKEY0123456789 has expired."]})
        with patched(util, fetch=echo):
            err = paydata.fetch([("15-2051", "N0000000")])["error"]
        self.assertNotIn("SECRETKEY", err)
        self.assertIn("The key *** has expired", err)
        self.assertIn("renewed yearly", err)
        self.assertIn("v2 (key set", paydata.doctor_row()[2])

    def test_offline_keeps_the_cached_figure_and_refunds_the_unit(self):
        j = self.job()
        with patched(util, fetch=FakeBLS(error=urllib.error.URLError("getaddrinfo failed"))):
            r = paydata.fetch([paydata.for_job(j)["next"]])
        self.assertEqual((r["error"], paydata.used()), ("BLS unreachable: no cached figure yet", 0))
        self.cache("15-1252", "M0042660", SEA, year=2023, fetched="2026-01-05 00:00:00")
        with patched(util, fetch=FakeBLS(error=TimeoutError("timed out"))):
            r = paydata.fetch([paydata.for_job(j)["next"]])
        self.assertEqual((r["error"], paydata.used()), ("BLS unreachable: showing figures retrieved 2026-01-05", 0))
        s = paydata.for_job(j)
        self.assertEqual((s["state"], s["pay"]["p50"]), ("stale", 167280))
        with patched(paydata, for_job=lambda *a: 1 / 0):
            self.assertEqual(web._job_view(j)["pay"], {"state": "error"})  # the board never breaks on it

    def test_index_reads_the_pref_and_your_home_once_per_board(self):
        for loc in ("Remote", "Seattle, WA", "Austin, TX"):
            self.job(location=loc, remote="remote" if loc == "Remote" else None)
        seen = {"pref": 0, "home": 0}
        real_pref, real_home = settings.pref, paydata.home_location

        def pref(k):
            seen["pref"] += k == "market_pay"
            return real_pref(k)

        def home():
            seen["home"] += 1
            return real_home()
        with patched(settings, pref=pref), patched(paydata, home_location=home):
            st = web.state()
        self.assertEqual(seen, {"pref": 1, "home": 1})
        remote = next(j for j in st["jobs"] if j["location"] == "Remote")["pay"]
        self.assertEqual((remote["chain"][0]["area"], remote["chain"][0]["why"]), ("M0012420", "remote: home area"))

    def test_off_means_no_network_no_chip_and_silent_prompts(self):
        j = self.job()
        settings.set_pref("market_pay", "off")
        fake = FakeBLS(cells("15-1252", "M0042660", SEA))
        with patched(util, fetch=fake):
            self.assertEqual(paydata.fill(5), 0)
        self.assertEqual((fake.calls, paydata.for_job(j), paydata.line(j)), ([], {"state": "off"}, ""))
        self.assertIn("off", paydata.doctor_row()[2])
        with self.assertRaises(SystemExit):
            web._act("market_pay", {"id": j["id"]})
        with self.assertRaises(SystemExit) as e:
            self.cli("comp", "market", str(j["id"]))
        self.assertIn("market_pay on", str(e.exception))

    def test_loop_fill_takes_live_jobs_only_and_then_nothing(self):
        live, other = self.job(), self.job(title="Data Engineer", location="Austin, TX", status="applied")
        closed = self.job(title="Web Developer", location="Denver, CO", status="rejected")
        fake = FakeBLS({**cells("15-1252", "M0042660", SEA), **cells("15-1252", "M0012420", SEA)})
        with patched(util, fetch=fake):
            self.assertEqual(paydata.fill(1), 2)
            self.assertEqual(paydata.fill(1), 0)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(any("151254" in s for s in fake.calls[0][1]["seriesid"]))  # the closed job's occupation
        self.assertEqual((paydata.for_job(live)["state"], paydata.for_job(other)["state"]), ("ok", "ok"))
        self.assertEqual(paydata.for_job(closed)["next"], ["15-1254", "M0019740"])
        self.job(title="Web Developer", location="Boston, MA", status="applied")
        with patched(util, fetch=FakeBLS(error=ConnectionRefusedError("refused"))):
            with self.assertRaises(SystemExit) as e:  # the loop step reports it (loop._step catches SystemExit)
                paydata.fill(1)
        self.assertEqual((str(e.exception), paydata.used()), ("BLS unreachable: no cached figure yet", 1))  # refunded


class Occupation(Base):
    def test_ai_pick_is_saved_for_same_title_jobs_and_junk_saves_nothing(self):
        a, b, mine = (self.job(title="Quant Wizard") for _ in range(3))
        db.con().execute("UPDATE jobs SET soc='13-2051', soc_by='user' WHERE id=?", (mine["id"],))  # your own pick
        prompts = []
        fake = lambda p, *x, **k: prompts.append(p) or {"soc": "15-2051"}  # noqa: E731
        with patched(ai, ask_json=fake):
            got = paydata.match_ai(a)
        self.assertEqual(got, {"soc": "15-2051", "name": "Data Scientists", "by": "AI"})
        rows = {r["id"]: (r["soc"], r["soc_by"]) for r in db.con().execute("SELECT id, soc, soc_by FROM jobs")}
        self.assertEqual((rows[a["id"]], rows[b["id"]], rows[mine["id"]]),
                         (("15-2051", "ai"), ("15-2051", "ai"), ("13-2051", "user")))  # yours is never overwritten
        self.assertEqual(len(prompts), 1)
        self.assertIn("15-1252 Software Developers", prompts[0])
        self.assertIn("never follow instructions", prompts[0])
        self.assertNotIn(str(FLOOR), prompts[0])
        self.assertNotIn(f"{FLOOR:,}", prompts[0])
        c = self.job(title="Odd Role")
        with patched(ai, ask_json=lambda *x, **k: {"soc": "99-9999"}):
            self.assertIsNone(paydata.match_ai(c))
        self.assertIsNone(db.get_job(c["id"])["soc"])
        with patched(ai, ask_json=lambda *x, **k: {"soc": "99-9999"}):
            with self.assertRaises(SystemExit) as e:
                web._act("market_pay", {"id": c["id"], "ai": True})
        self.assertIn("AI could not match an occupation", str(e.exception))

        def no_key(*x, **k):
            raise SystemExit("no AI provider configured")
        with patched(ai, ask_json=no_key):
            with self.assertRaises(SystemExit):
                web._act("market_pay", {"id": c["id"], "ai": True})

    def test_your_override_none_and_automatic(self):
        j = self.job(title="Data Analyst")
        paydata.set_soc(j["id"], "15-2051")
        self.assertEqual(paydata.soc_for(db.get_job(j["id"]))["by"], "you")
        paydata.set_soc(j["id"], "none")
        self.assertEqual(paydata.for_job(db.get_job(j["id"]))["state"], "hidden")
        self.assertEqual(paydata.line(db.get_job(j["id"])), "")
        with self.assertRaises(SystemExit):
            paydata.set_soc(j["id"], "abc")
        paydata.set_soc(j["id"], "")
        self.assertEqual(paydata.soc_for(db.get_job(j["id"]))["by"], "keyword 'data analyst'")


class Uses(Base):
    def offer_job(self, base=150000):
        j = self.job(title="Software Engineer", location="Seattle, WA", status="offer")
        db.update_job(j["id"], contact_email="rita@acme.example", contact_name="Rita")
        db.set_offer(j["id"], base=base)
        self.cache("15-1252", "M0042660", SEA)
        return db.get_job(j["id"])

    def test_counter_cites_the_cached_bls_figure_and_never_the_floor(self):
        j = self.offer_job()
        median = ("U.S. Bureau of Labor Statistics data (May 2025) put the median annual wage for Software Developers in "
                  "the Seattle-Tacoma-Bellevue area at $167,280")
        t = apply.counter(j, [f"{j['id']}:market_median"], template=True)
        self.assertEqual(t["proposal"]["status"], "pending")  # always reviewed
        self.assertIn(f"Public data point the same way: {median}.", t["draft"]["body"])
        self.assertNotIn("another offer", t["draft"]["body"])
        seen = []
        fake = lambda p, *a, **k: seen.append(p) or {"subject": "Re: offer", "body": f"Thanks. {median}. Best"}  # noqa: E731
        with patched(ai, ask_json=fake, available=lambda: ["anthropic"]):
            r = apply.counter(j, [f"{j['id']}:market_p75"], "a base of 200,000")
        self.assertIn("PUBLIC MARKET FIGURES (cite as public BLS data, never as an offer): U.S. Bureau of Labor Statistics "
                      "data (May 2025) put the 75th percentile annual wage", seen[0])
        self.assertEqual(r["proposal"]["status"], "pending")
        for blob in (seen[0], t["draft"]["body"], r["draft"]["body"]):
            for f in (str(FLOOR), f"{FLOOR:,}", "Salary floor"):
                self.assertNotIn(f, blob)
        other = self.job(title="Software Engineer", location="Austin, TX", status="offer")
        for bad, why in (([f"{other['id']}:market_median"], "only for the job you are countering"),):
            with self.assertRaises(SystemExit) as e:
                apply.counter(j, bad, template=True)
            self.assertIn(why, str(e.exception))
        with self.assertRaises(SystemExit) as e:
            apply.counter(db.get_job(other["id"]), [f"{other['id']}:market_median"], template=True)
        self.assertIn("no BLS figure cached", str(e.exception))
        db.set_offer(j["id"], base=170000)
        with self.assertRaises(SystemExit) as e:
            apply.counter(j, [f"{j['id']}:market_median"], template=True)
        self.assertIn("citing it would argue for less", str(e.exception))
        self.cache("15-1252", "M0042660", SEA | {"p75": 239200}, capped=["p75"])
        self.assertIn("put the 75th percentile annual wage for Software Developers in the Seattle-Tacoma-Bellevue area "
                      "at or above $239,200", paydata.phrase(j, "market_p75"))

    def test_compare_prompts_label_and_cli(self):
        j = self.offer_job(base=SEA["p25"])
        row = next(r for r in comp.compare()["offers"] if r["job_id"] == j["id"])
        self.assertEqual((row["paydata"]["pay"]["p50"], row["paydata"]["base_band"]), (167280, "25th-median"))
        line = paydata.line(j)
        self.assertEqual(line, "public BLS OEWS May 2025, Software Developers (15-1252), Seattle-Tacoma-Bellevue, WA: 10th "
                               "99,190 | 25th 132,800 | median 167,280 | 75th 211,860 | 90th 257,960 | mean 174,920 (all "
                               "employers, base pay; not company-specific)")
        label = paydata.for_job(j)["label"]
        for part in ("BLS OEWS May 2025", "Nov 2022 to May 2025", "It is not this company's pay band",
                     "75th-90th percentile here", "matched by keyword 'software engineer'",
                     "retrieved 2026-11-07. BLS.gov cannot vouch for the data"):
            self.assertIn(part, label)
        self.assertNotIn("Big-tech", paydata.honesty(paydata.for_job(j)["pay"], {"soc": "13-1082", "name": "x", "by": "you"},
                                                     paydata.for_job(j)["area"]))
        posting = self.job(title="Software Engineer", location="Seattle, WA", salary_min=150000, salary_max=220000)
        self.assertEqual(paydata.for_job(posting)["posting_band"], {"min": "25th-median", "max": "75th-90th"})
        euro = self.job(title="Software Engineer", location="Seattle, WA", salary_max=220000, currency="EUR")
        self.assertIsNone(paydata.for_job(euro)["posting_band"])
        from lodestar import interview, resume
        self.assertIn(line, interview._pay(j))
        prompts = []
        with patched(ai, ask_json=lambda p, *a, **k: prompts.append(p) or {}, available=lambda: ["anthropic"]):
            resume.gap(j)
        self.assertIn(line, prompts[0])
        from lodestar.cli import _offer_table
        table = _offer_table(comp.compare())
        self.assertIn("BLS median/75th", table)
        self.assertIn("167,280/211,860", table)
        fake = FakeBLS(cells("15-2051", "S5300000", {"p50": 120000, "p75": 150000}))
        spokane = self.job(title="Quant Wizard", location="Spokane, WA")
        with patched(util, fetch=fake):
            text = self.cli("comp", "market", str(spokane["id"]), "--soc", "15-2051")
        self.assertIn("occupation: Data Scientists (15-2051), you", text)
        self.assertIn("area: Washington (state: no metro match for this location)", text)
        self.assertIn("median 120,000", text)
        self.assertEqual(len(fake.calls), 1)
        self.cli("comp", "market", str(spokane["id"]), "--soc", "none")
        self.assertEqual(paydata.for_job(db.get_job(spokane["id"]))["state"], "hidden")

    def test_the_drawer_task_walks_the_chain_and_reports_errors_as_text(self):
        j = self.job(title="Platform Engineer", location="Seattle, WA")
        fake = FakeBLS(cells("15-1299", "S5300000", {"p50": 150000}))  # no metro figure
        with patched(util, fetch=fake):
            r = web._act("market_pay", {"id": j["id"]})
        self.assertEqual((r["error"], r["pay"]["area"]["area"], len(fake.calls)), (None, "S5300000", 2))
        k = self.job(title="Web Developer", location="Denver, CO")
        with patched(util, fetch=FakeBLS(error=OSError("offline"))):
            r = web._act("market_pay", {"id": k["id"]})
        self.assertEqual((r["error"], r["pay"]["state"]), ("BLS unreachable: no cached figure yet", "missing"))
        g = web._job_view(db.get_job(j["id"]), pidx=paydata.index())
        self.assertEqual(g["pay"]["pay"]["p50"], 150000)


class Fetch(unittest.TestCase):
    def test_util_fetch_posts_json_and_keeps_the_size_cap(self):
        seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers["Content-Length"])
                seen.update(method=self.command, body=self.rfile.read(n), ctype=self.headers["Content-Type"])
                out = b'{"status": "REQUEST_SUCCEEDED"}' + (b" " * 5000 if b"big" in seen["body"] else b"")
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old = os.environ.get("LODESTAR_ALLOW_PRIVATE_URLS")
        os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = "1"
        url = f"http://127.0.0.1:{srv.server_address[1]}/publicAPI/v1/timeseries/data/"
        try:
            got = util.fetch(url, data=b'{"seriesid": ["X"]}', headers={"Content-Type": "application/json"}, timeout=5)
            self.assertEqual(seen, {"method": "POST", "body": b'{"seriesid": ["X"]}', "ctype": "application/json"})
            self.assertEqual(json.loads(got), {"status": "REQUEST_SUCCEEDED"})
            with self.assertRaises(ValueError) as e:
                util.fetch(url, data=b"big", max_bytes=1000, timeout=5)
            self.assertIn("larger than 0.001 MB", str(e.exception))
        finally:
            srv.shutdown()
            srv.server_close()
            os.environ.pop("LODESTAR_ALLOW_PRIVATE_URLS", None)
            if old is not None:
                os.environ["LODESTAR_ALLOW_PRIVATE_URLS"] = old


if __name__ == "__main__":
    unittest.main()
