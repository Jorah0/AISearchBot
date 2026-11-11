"""Pass 22, builder 'engine': the apply agent's core (apply_agent.py, apply_ats.py) without a browser. Site policy
(forbidden boards, exact run hosts, the navigation guard's verdicts), the field plan's safety rules (in Python, on the
label), the run state machine with claims, the heartbeat, Stop, crash recovery (never a second Submit), evidence,
idempotency, the Inbox executor and the pipeline's Apply step. A FakeBrowser stands in for Playwright: every write,
click and screenshot is recorded. Browser runs on local fixture forms are in tests/e2e/e2e_apply_agent.py.
Every patched attribute and setting is put back."""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import ai, apply_agent, apply_ats, approvals, cli, db, extras, pipeline, profile, resume, settings, util, web  # noqa: E402

PROF = ("# Jane Doe\nJane Doe | Austin, TX | jane@example.com | 512-555-0100\n## Summary\nData engineer.\n## Skills\n"
        "Python, SQL\n## Experience\n### Senior Data Engineer - Globex (2019-01 - Present)\n- Built pipelines\n"
        "## Education\nBS Computer Science\n\n## Preferences\nSalary floor: $123,456\n")
HOST = "jobs.example-ats.test"


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


def F(i, label, key=None, **kw):
    """A scan descriptor as content.js (agent mode) returns it."""
    return {"i": i, "tag": kw.pop("tag", "input"), "type": kw.pop("type", "text"), "name": kw.pop("name", ""), "id": "",
            "label": label, "key": key, "options": kw.pop("options", []), "required": kw.pop("required", False),
            "value": "", "group": kw.pop("group", None), "placeholder": "", **kw}


YESNO = [{"v": "", "t": "Select..."}, {"v": "yes", "t": "Yes"}, {"v": "no", "t": "No"}]
BASIC = [F(0, "First Name", "first", required=True), F(1, "Last Name", "last", required=True),
         F(2, "Email", "email", required=True), F(3, "Phone", "phone"),
         F(4, "Resume/CV", "file", type="file", required=True)]


class FakeTab:
    """The Tab interface over a page model: {pages: [{fields, next, submit, blocker, errors_once, offsite, applied,
    code_after}], hook(tab)}. The hook runs on every idle (the user acting in the window, an Inbox click)."""

    def __init__(self, browser, url, hosts):
        self.b, self.url, self.hosts = browser, url, list(hosts)
        self.n, self.vals, self.writes, self.clicks, self.shots = 0, {}, [], [], []
        self.suspended, self.offsite, self.forbidden_hit, self.accept_confirm = False, None, None, False
        self.closed, self.submitted, self.code, self.errored = False, False, False, set()

    def page(self):
        return self.b.model["pages"][self.n]

    def host(self):
        return apply_ats.host(self.url)

    def scan(self):
        return [dict(f, frame=0, value=self.vals.get(f["i"], "")) for f in self.page()["fields"]]

    def values(self):
        fmt = self.b.model.get("reformat") or (lambda i, v: v)
        return {f"0:{f['i']}": fmt(f["i"], self.vals.get(f["i"], "")) for f in self.page()["fields"]}

    def write(self, item):
        assert item["status"] in ("fill", "consent"), item
        assert self.host() in self.hosts
        self.writes.append((self.n, item["label"], item["value"]))
        self.vals[item["i"]] = Path(item["value"]).name if item["kind"] == "file" else str(item["value"])
        return True

    def blocker(self):
        return "code" if self.code else self.page().get("blocker")

    def errors(self):
        if self.page().get("errors_once") and self.n not in self.errored:
            self.errored.add(self.n)
            return ["Phone: enter a valid number"]
        return []

    def confirmed(self):
        return "Thank you for applying. Confirmation number FIX-7" if self.submitted and not self.code else None

    def already_applied(self):
        return bool(self.page().get("applied"))

    def button(self, kind):
        return {"b": 0, "frame": 0, "text": "Submit application" if kind == "submit" else "Next"} if self.page().get(kind) else None

    def click(self, b):
        self.clicks.append(b["text"])
        if b["text"] == "Next":
            if self.page().get("errors_once") and self.n not in self.errored:
                return
            if (off := self.page().get("offsite")) and not self.offsite and off not in self.hosts:
                self.offsite = (off, f"https://{off}/step2")
                return
            self.n += 1
        else:
            self.submitted, self.code = True, bool(self.page().get("code_after"))

    def shot(self, path):
        Path(path).write_bytes(b"\x89PNG fake")
        self.shots.append(Path(path).name)

    def idle(self, ms):
        self.b.tick(self)

    def front(self):
        pass

    def goto(self, url):
        self.url, self.n = url, self.n + 1


class FakeBrowser:
    def __init__(self, model):
        self.model, self.tabs, self.closed, self.ticks = model, [], False, 0

    def open(self, url, hosts):
        if self.model.get("forbidden_redirect"):
            raise AssertionError("never opened")
        t = FakeTab(self, url, hosts)
        self.tabs.append(t)
        return t

    def pages(self):
        return [t for t in self.tabs if not t.closed]

    def tick(self, tab=None):
        self.ticks += 1
        if self.ticks > 400:
            raise AssertionError("the run never settled (a wait that nothing ends)")
        if hook := self.model.get("hook"):
            hook(tab or (self.tabs[-1] if self.tabs else None))

    def idle(self, ms):
        self.tick()

    def close(self):
        self.closed = True


class Base(unittest.TestCase):
    def setUp(self):
        profile.write_master(PROF)
        db.release()
        st = settings.load()
        self.addCleanup(settings.save, st)
        for k, v in (("ATS", apply_ats.ATS | {"exampleats": r"(?:^|\.)example-ats\.test$"}),):
            old = getattr(apply_ats, k)
            setattr(apply_ats, k, v)
            self.addCleanup(setattr, apply_ats, k, old)
        self.notes, self.made = [], []
        old_notify = util.notify
        util.notify = self.notes.append
        self.addCleanup(setattr, util, "notify", old_notify)
        apply_agent.STOP.unlink(missing_ok=True)
        apply_agent._EVENT.clear()
        apply_agent._OWNED.clear()
        self.addCleanup(self._tidy)

    def _tidy(self):  # one shared home: nothing this test made reaches the next module's tests
        db.release(close=False)
        apply_agent.STOP.unlink(missing_ok=True)
        apply_agent._EVENT.clear()
        for jid in self.made:
            with contextlib.suppress(SystemExit):
                db.delete_job(jid)
        for q in ("Desired salary", "EEO: gender", "Visa sponsorship required"):
            db.con().execute("DELETE FROM answers WHERE question=?", (q,))
        db.con().commit()

    N = [0]

    def job(self, company="Acme Robotics", url=None, resume_file=True, **fields):
        self.N[0] += 1  # a fresh link each time: add_job folds the same link into one card
        jid = db.add_job(company, "Data Engineer", url or f"https://{HOST}/acme/{self.N[0]}", "Python SQL", None, **fields)
        self.made.append(jid)
        if resume_file:
            (resume.app_dir(db.get_job(jid)) / "resume.pdf").write_bytes(b"%PDF-1.4 fake resume")
        return jid

    def drive(self, model, ids, mode=None, until_idle=True, **kw):
        """Queue and work the runs in this thread with a FakeBrowser; returns (browser, runs)."""
        out = apply_agent.enqueue(ids, mode, start=False, **kw)
        b = FakeBrowser(model)
        apply_agent._loop(lambda: b, until_idle=until_idle)
        return b, [db.get_run(r["run_id"]) if "run_id" in r else r for r in out]

    def items(self, run):
        return {x["label"]: x for p in run["plan"] for x in p["items"]}


class Policy(Base):
    def test_forbidden_boards_exact_run_hosts_and_the_guard(self):
        f = apply_agent.forbidden
        for h in ("www.linkedin.com", "uk.indeed.com", "smartapply.indeed.com", "indeed.co.uk", "glassdoor.ca",
                  "ziprecruiter.com", "simplyhired.com", "lnkd.in", "linkedin.example.org"):
            self.assertTrue(f(h), h)
        for h in ("boards.greenhouse.io", "notlinkedin.example", "careers.acme.example"):
            self.assertIsNone(f(h), h)
        self.assertEqual(f("https://de.linkedin.com/jobs/view/1"), "LinkedIn")
        self.assertEqual(apply_ats.hosts_for("https://job-boards.greenhouse.io/acme/jobs/1"),
                         ["job-boards.greenhouse.io", "boards.greenhouse.io"])
        hosts = apply_ats.hosts_for("https://careers-acme.azurewebsites.net/apply")
        self.assertEqual(hosts, ["careers-acme.azurewebsites.net"])  # never the shared parent domain
        d = apply_ats.decide
        self.assertEqual(d("https://evil.azurewebsites.net/x", True, hosts, False, f), "offsite")
        self.assertEqual(d("https://www.linkedin.com/jobs", True, hosts, False, f), "forbidden")
        self.assertEqual(d("https://www.linkedin.com/jobs", False, (), False, f), "forbidden")  # a popup's first load
        self.assertEqual(d("https://uk.indeed.com/", True, hosts, True, f), "forbidden")  # never suspended
        self.assertEqual(d("https://sso.acme.example/login", True, hosts, True, f), "ok")  # you drive a handoff
        self.assertEqual(d("https://www.google.com/recaptcha/api2/bframe", False, hosts, False, f), "ok")  # a subframe

    def test_resolve_url_needs_your_link_off_the_known_systems(self):
        jid = self.job(url="https://www.linkedin.com/jobs/view/42")
        with self.assertRaises(SystemExit) as e:
            apply_agent.resolve_url(db.get_job(jid))
        self.assertIn("LinkedIn, which does not allow bots", str(e.exception))
        db.set_fields(jid, apply_url="https://uk.indeed.com/applystart?x=1")
        with self.assertRaises(SystemExit) as e:
            apply_agent.resolve_url(db.get_job(jid))
        self.assertIn("Indeed", str(e.exception))
        with self.assertRaises(SystemExit):
            db.set_fields(jid, apply_url="javascript:alert(1)")
        db.set_fields(jid, apply_url="https://careers.acme.example/apply/42")
        self.assertEqual(apply_agent.resolve_url(db.get_job(jid)), ("https://careers.acme.example/apply/42", "your application link"))
        other = self.job(url="https://www.monster.example/job/9")  # another board: never guessed to be the employer's
        with self.assertRaises(SystemExit) as e:
            apply_agent.resolve_url(db.get_job(other))
        self.assertIn("paste the employer's application link", str(e.exception))
        self.assertEqual(apply_agent.resolve_url(db.get_job(self.job()))[1], "the posting link")

    def test_effective_mode_and_every_auto_gate(self):
        jid = self.job()
        job = db.get_job(jid)
        settings.set_tool("apply_agent", enabled=False, auto=False)
        self.assertEqual(apply_agent.effective_mode(job, "exampleats", "review")[0], "stop")
        settings.set_tool("apply_agent", enabled=True)
        self.assertEqual(apply_agent.effective_mode(job, None, "review"), ("stop", [
            "this link is not on a known application system: stop mode only (you press Submit)"]))
        mode, why = apply_agent.effective_mode(job, "exampleats", "auto")
        self.assertEqual(mode, "review")
        self.assertEqual(len(why), 4, why)  # tool not on auto, not on the list, no fit, fewer than 2 approved runs
        settings.set_tool("apply_agent", auto=True)
        settings.set_pref("apply_agent_auto_ats", "greenhouse")
        with self.assertRaises(SystemExit):
            settings.set_pref("apply_agent_auto_ats", "monster")
        db.update_job(jid, fit_score=95)
        for _ in range(2):
            rid = db.add_run(self.job(company="Seed Co"), "review")
            db.update_run(rid, state="confirmed", ats="greenhouse", submitted_by="approved")
        self.assertEqual(apply_agent.effective_mode(db.get_job(jid), "greenhouse", "auto"), ("auto", []))
        settings.set_pref("apply_agent_daily_cap", 0)
        self.assertEqual(apply_agent.effective_mode(db.get_job(jid), "greenhouse", "auto")[1],
                         ["today's automatic submissions reached the daily cap"])


class Plan(Base):
    def plan(self, fields, eeo=False, jid=None):
        jid = jid or self.job()
        data = extras.ext_autofill([f["label"] for f in fields], eeo=eeo, salary=True)
        return {x["label"]: x for x in apply_agent.build_plan(db.get_job(jid), {"eeo": eeo, "url": f"https://{HOST}/a"},
                                                              fields, data, None)}, jid

    def test_safety_rules_read_the_label_never_the_page_key(self):
        calls = []
        with patched(ai, chat=lambda *a, **k: calls.append(a) or "Yes"):
            p, jid = self.plan([*BASIC, F(5, "Social Security Number", "email"), F(6, "Password", "email", type="password"),
                                F(7, "I agree to the privacy policy", None, type="checkbox", required=True),
                                F(8, "Will you now or in the future require visa sponsorship?", "question", tag="select",
                                  type="", options=YESNO, required=True),
                                F(9, "Have you ever been convicted of a felony?", "question", required=True)])
        self.assertEqual(calls, [])  # eligibility and legal questions never reach a model
        self.assertEqual((p["First Name"]["status"], p["First Name"]["value"], p["First Name"]["source"]), ("fill", "Jane", "profile"))
        self.assertEqual(p["Email"]["value"], "jane@example.com")
        self.assertEqual(p["Social Security Number"]["status"], "skip")  # the page said 'email'; the label decides
        self.assertEqual(p["Password"]["status"], "skip")
        self.assertEqual(p["I agree to the privacy policy"]["status"], "consent")
        visa = p["Will you now or in the future require visa sponsorship?"]
        self.assertEqual(visa["status"], "needs_you")
        self.assertTrue(visa["qid"].startswith("question #"))
        self.assertEqual(p["Have you ever been convicted of a felony?"]["status"], "needs_you")
        # your own stored answer (a CANON key) is used; an AI draft of the same row is not
        db.save_answer("Visa sponsorship required", "No", "eligibility", source="typed under Answers")
        p, _ = self.plan([F(8, "Will you now or in the future require visa sponsorship?", "question", tag="select", type="",
                            options=YESNO, required=True)], jid=jid)
        self.assertEqual((p["Will you now or in the future require visa sponsorship?"]["value"],
                          p["Will you now or in the future require visa sponsorship?"]["source"]), ("no", "bank"))

    def test_eeo_salary_and_the_floor(self):
        gender = F(0, "Gender", "eeo.gender", tag="select", type="", required=True,
                   options=[{"v": "", "t": "Select"}, {"v": "f", "t": "Female"}, {"v": "x", "t": "Decline to self-identify"}])
        race = F(1, "Race", "eeo.race", tag="select", type="", required=True, options=[{"v": "a", "t": "Asian"}])
        vet = F(2, "Veteran status", "eeo.veteran", tag="select", type="", options=[{"v": "n", "t": "Not a veteran"}])
        pay = F(3, "What are your salary expectations?", "salary", required=True)
        p, jid = self.plan([gender, race, vet, pay])
        self.assertEqual((p["Gender"]["value"], p["Gender"]["flag"]), ("x", "EEO: chose decline (you did not include EEO answers)"))
        self.assertEqual(p["Race"]["status"], "needs_you")  # required, no decline option: asked, never guessed
        self.assertEqual(p["Veteran status"]["status"], "skip")
        self.assertEqual(p["What are your salary expectations?"]["status"], "needs_you")
        db.save_answer("Desired salary", "$140,000", "salary", source="typed under Answers")
        db.save_answer("EEO: gender", "Female", "eeo", source="typed under Answers")
        p, _ = self.plan([gender, pay], eeo=True, jid=jid)
        self.assertEqual(p["Gender"]["value"], "f")
        self.assertEqual(p["What are your salary expectations?"]["value"], "$140,000")
        why = F(4, "Why do you want this job?", "question", tag="textarea", type="", required=True)
        p, _ = self.plan([why], jid=jid)
        q = int(p["Why do you want this job?"]["qid"].split("#")[1])
        pipeline.answer(q, "My floor is $123,456 so pay me", scope="job")  # typed for this job only: no bank guard ran
        p, _ = self.plan([why], jid=jid)
        self.assertEqual((p["Why do you want this job?"]["status"], p["Why do you want this job?"]["flag"]),
                         ("needs_you", "would name your salary floor"))
        self.assertNotIn("123,456", json.dumps(p))
        self.assertNotIn("Preferences", json.dumps(p))

    def test_files_are_copies_named_for_the_recruiter(self):
        jid = self.job()
        ev = Path(tempfile.mkdtemp())
        data = extras.ext_autofill([], salary=True)
        fields = [F(0, "Resume/CV", "file", type="file", required=True), F(1, "Cover Letter", "file", type="file"),
                  F(2, "Transcript", "file", type="file", required=True)]
        p = {x["label"]: x for x in apply_agent.build_plan(db.get_job(jid), {"eeo": False, "url": "https://x"}, fields, data, ev)}
        self.assertEqual(p["Resume/CV"]["file"], "Jane_Doe_Resume.pdf")
        self.assertTrue((ev / "Jane_Doe_Resume.pdf").is_file())
        self.assertEqual(len(p["Resume/CV"]["sha256"]), 64)
        self.assertEqual(p["Cover Letter"]["status"], "skip")
        self.assertEqual((p["Transcript"]["status"], p["Transcript"]["flag"]), ("needs_you", "upload it yourself in the window"))
        none = self.job(company="No Resume Co", resume_file=False)
        with patched(profile, RESUMES=Path(tempfile.mkdtemp())):
            p = apply_agent.build_plan(db.get_job(none), {"eeo": False, "url": "x"}, fields[:1], data, ev)
        self.assertEqual(p[0]["flag"], "tailor a resume or build the master resume first")


class Runs(Base):
    def test_stop_mode_fills_never_submits_and_records_your_click(self):
        jid = self.job()
        model = {"pages": [{"fields": BASIC + [F(5, "I agree to the privacy policy", None, type="checkbox", required=True)],
                            "submit": True}],  # you check the window and press Submit yourself:
                 "hook": lambda t: setattr(t, "submitted", True) if db.live_runs() and db.live_runs()[0]["state"] == "ready" else None}
        out = apply_agent.enqueue([jid], "stop", start=False)
        b = FakeBrowser(model)
        apply_agent._loop(lambda: b, until_idle=True)
        run, tab = db.get_run(out[0]["run_id"]), b.tabs[0]
        self.assertEqual((run["state"], run["submitted_by"], run["confirmation"]), ("by_user", "user", "FIX-7"))
        self.assertEqual(tab.clicks, [])  # the agent never pressed Submit
        planned = {x["label"] for x in self.items(run).values() if x["status"] == "fill"}
        self.assertEqual({w[1] for w in tab.writes}, planned)
        self.assertNotIn("I agree to the privacy policy", planned)  # you tick consent yourself in stop mode
        self.assertEqual(tab.shots, ["page-01.png", "confirmation.png"])
        ev = Path(run["evidence"])
        self.assertTrue((ev / "plan.json").is_file() and (ev / "summary.md").is_file() and (ev / "confirmation.txt").is_file())
        self.assertIn("you clicked Submit", (ev / "summary.md").read_text(encoding="utf-8"))
        self.assertEqual(db.get_job(jid)["status"], "saved")  # stop mode changes no status: Mark applied is yours

    def review(self, model, jid, approve=True):
        settings.set_tool("apply_agent", enabled=True, auto=False)
        state = {"approved": 0}

        def hook(tab):
            run = db.live_runs()[0] if db.live_runs() else None
            if run and run["state"] == "awaiting_approval" and approve and run["pending_id"]:
                if db.get_pending(run["pending_id"])["status"] == "pending":
                    state["approved"] += 1
                    approvals.approve(run["pending_id"])
                    if model.get("after") and tab:  # what you do in the window between your approval and the click
                        model["after"](tab, db.get_run(run["id"]))
        model["hook"] = hook
        return self.drive(model, [jid], "review") + (state,)

    def test_review_mode_one_approval_one_click_and_the_job_moves(self):
        jid = self.job()
        b, (run,), _ = self.review({"pages": [{"fields": BASIC, "submit": True}]}, jid)
        tab = b.tabs[0]
        self.assertEqual((run["state"], run["submitted_by"], run["submit_clicks"]), ("confirmed", "approved", 1))
        self.assertEqual(tab.clicks, ["Submit application"])
        item = db.get_pending(run["pending_id"])
        self.assertEqual((item["kind"], item["status"]), ("submit_application", "done"))
        p = json.loads(item["payload"])
        self.assertEqual(p["shots"], ["page-01.png"])
        self.assertIn({"label": "Email", "value": "jane@example.com", "source": "profile", "flag": ""}, p["fields"])
        self.assertNotIn("123,456", item["payload"])
        job = db.get_job(jid)
        self.assertEqual(job["status"], "applied")
        evs = [e["kind"] for e in db.events(jid)]
        self.assertIn("apply_evidence", evs)
        self.assertTrue(any("approved by you: confirmation FIX-7" in (e["detail"] or "") for e in db.events(jid)))
        again = approvals.approve(run["pending_id"])  # approving twice: the decided status, no second click
        self.assertEqual((again["status"], tab.clicks), ("done", ["Submit application"]))
        with self.assertRaises(SystemExit):
            approvals.record_submission(db.add_run(self.job(company="Other"), "review"))

    def test_auto_submits_without_the_inbox_and_the_cap_sends_the_next_to_review(self):
        settings.set_tool("apply_agent", enabled=True, auto=True)
        settings.set_pref("apply_agent_auto_ats", "exampleats")
        settings.set_pref("apply_agent_daily_cap", 1)
        for _ in range(2):
            rid = db.add_run(self.job(company="Earned Co"), "review")
            db.update_run(rid, state="confirmed", ats="exampleats", submitted_by="approved")
        a, b_ = self.job(company="Auto One"), self.job(company="Auto Two")
        db.update_job(a, fit_score=90)
        db.update_job(b_, fit_score=90)
        br, (run,) = self.drive({"pages": [{"fields": BASIC, "submit": True}]}, [a], "auto")
        self.assertEqual((run["state"], run["submitted_by"], run["mode"]), ("confirmed", "auto", "auto"))
        self.assertEqual(db.get_pending(run["pending_id"])["status"], "done")
        self.assertEqual(db.get_job(a)["status"], "applied")
        self.assertTrue(any("automatic" in (e["detail"] or "") for e in db.events(a)))
        nxt = apply_agent.enqueue([b_], "auto", start=False)[0]
        self.assertEqual(nxt["mode"], "review")
        self.assertIn("today's automatic submissions reached the daily cap", nxt["reasons"])
        apply_agent.stop()  # leave nothing queued for the next test
        # a consent box (or any flag, any AI value) at the last page sends an auto run to review
        settings.set_pref("apply_agent_daily_cap", 5)
        c = self.job(company="Auto Three")
        db.update_job(c, fit_score=90)
        apply_agent.STOP.unlink(missing_ok=True)
        model = {"pages": [{"fields": BASIC + [F(5, "I certify the above is true", None, type="checkbox")], "submit": True}],
                 "hook": lambda t: apply_agent.stop() if db.live_runs() and db.live_runs()[0]["state"] == "awaiting_approval" else None}
        _, (run,) = self.drive(model, [c], "auto")
        self.assertEqual(run["mode"], "review")
        self.assertIn("a consent box to tick", run["reasons"])

    def test_idempotency_never_twice_and_a_crash_after_submit_is_unknown(self):
        jid = self.job()
        first = apply_agent.enqueue([jid], "stop", start=False)
        self.assertIn("run_id", first[0])
        self.assertIn("already on it", apply_agent.enqueue([jid], "stop", start=False)[0]["error"])
        db.update_run(first[0]["run_id"], state="submitting", submit_clicks=1, heartbeat="2000-01-01 00:00:00")
        self.assertEqual(apply_agent.recover(), 1)
        self.assertEqual(db.get_run(first[0]["run_id"])["state"], "unknown")
        self.assertIn("will not submit again", apply_agent.enqueue([jid], "stop", start=False)[0]["error"])
        applied = self.job(company="Applied Co")
        db.set_status(applied, "applied")
        self.assertIn("only applies to saved jobs", apply_agent.enqueue([applied], start=False)[0]["error"])
        mailed = self.job(company="Mailed Co")
        db.add_mail(message_id="<conf-1@x.example>", job_id=mailed, direction="in", from_addr="no-reply@x.example",
                    subject="We received your application", category="application_received", trusted=False)
        self.assertIn("(unverified sender)", apply_agent.enqueue([mailed], start=False)[0]["error"])
        said = self.job(company="Said Co")
        _, (run,) = self.drive({"pages": [{"fields": BASIC, "submit": True, "applied": True}]}, [said], "stop")
        self.assertEqual((run["state"], run["error"]), ("failed", "the site says you already applied"))

    def test_liveness_claims_and_a_busy_profile(self):
        jid = self.job()
        settings.set_tool("apply_agent", enabled=True, auto=False)
        rid = db.add_run(jid, "review")
        db.update_run(rid, state="awaiting_approval", plan_hash="h", heartbeat="2000-01-01 00:00:00")
        pid = approvals.propose("apply_agent", "submit_application", {"run_id": rid, "job_id": jid, "plan_hash": "h"},
                                "submit", jid, force_pending=True)["id"]
        r = approvals.approve(pid)
        self.assertEqual(r["status"], "rejected")
        self.assertIn("agent window for run", r["result"])
        db.update_run(rid, heartbeat=db._now())  # owned by a live worker in another process (CLI): approved there
        db.con().execute("UPDATE pending SET status='pending' WHERE id=?", (pid,))
        db.con().commit()
        self.assertEqual(approvals.approve(pid, {"plan_hash": "tampered"})["status"], "done")  # edits are ignored
        self.assertEqual(db.get_run(rid)["state"], "approved")
        db.update_run(rid, state="stopped")
        q = db.add_run(self.job(company="Queue Co"), "stop")
        self.assertTrue(db.claim_run(q, "queued", "running"))
        self.assertFalse(db.claim_run(q, "queued", "running"))  # a second worker never takes the same run
        db.update_run(q, state="queued")

        def busy():
            raise apply_ats.ProfileBusy("the agent's browser profile is in use")
        apply_agent._loop(busy, until_idle=True)
        self.assertEqual(db.get_run(q)["state"], "queued")  # put back for the worker that holds the profile
        db.update_run(q, state="stopped")

    def test_stop_mid_page_and_a_leftover_stop_file(self):
        jid = self.job()
        model = {"pages": [{"fields": [*BASIC, F(5, "What motivates you at work?", "question", tag="textarea", type="",
                                                  required=True)], "submit": True}],
                 "hook": lambda t: apply_agent.stop()}
        b, (run,) = self.drive(model, [jid], "stop")
        self.assertEqual((run["state"], run["error"]), ("stopped", "stopped by you"))
        self.assertFalse(b.tabs[0].closed)  # left open for you
        self.assertTrue(apply_agent.STOP.exists())
        other = self.job(company="Next Day Co")
        self.assertIn("run_id", apply_agent.enqueue([other], "stop", start=False)[0])
        self.assertFalse(apply_agent.STOP.exists())  # cleared by the next enqueue
        apply_agent.stop()
        self.assertEqual(db.runs_for(other)[0]["state"], "stopped")  # queued runs stop too

    def test_handoffs_wait_for_you_and_a_code_after_submit(self):
        jid = self.job()
        page = {"fields": BASIC, "submit": True, "blocker": "captcha", "code_after": True}

        def hook(tab):
            run = db.live_runs()[0] if db.live_runs() else None
            if not run:
                return
            if run["state"] == "needs_you" and not run["submit_clicks"]:
                self.assertTrue(tab.suspended)
                self.assertEqual(tab.writes, [])  # nothing typed while the challenge shows
                page["blocker"] = None
                apply_agent.continue_run(run["id"])
            elif run["state"] == "awaiting_approval" and db.get_pending(run["pending_id"])["status"] == "pending":
                approvals.approve(run["pending_id"])
            elif run["state"] == "needs_you" and run["submit_clicks"]:
                tab.code = False  # you typed the emailed code in the window
        settings.set_tool("apply_agent", enabled=True, auto=False)
        b, (run,) = self.drive({"pages": [page], "hook": hook}, [jid], "review")
        self.assertEqual((run["state"], b.tabs[0].clicks), ("confirmed", ["Submit application"]))
        self.assertTrue(any("solve the check" in n for n in self.notes))
        self.assertEqual(db.get_job(jid)["status"], "applied")

    def test_offsite_needs_you_and_continue_allows_that_exact_host(self):
        jid = self.job()
        pages = [{"fields": BASIC[:3], "next": True, "offsite": "careers.acme-robotics.example"},
                 {"fields": [BASIC[4]], "submit": True}]

        def hook(tab):
            run = db.live_runs()[0] if db.live_runs() else None
            if run and run["state"] == "needs_you":
                self.assertIn("careers.acme-robotics.example", run["needs"][0]["hint"])
                apply_agent.continue_run(run["id"])
            elif run and run["state"] == "ready":
                tab.submitted = True
        b, (run,) = self.drive({"pages": pages, "hook": hook}, [jid], "stop")
        self.assertEqual(run["state"], "by_user")
        self.assertEqual(run["hosts"], [HOST, "careers.acme-robotics.example"])
        self.assertEqual(run["answers"]["_added"], ["careers.acme-robotics.example"])
        self.assertEqual(b.tabs[0].shots[:2], ["page-01.png", "page-02.png"])

    def test_validation_errors_refill_once_then_go_on(self):
        jid = self.job()
        pages = [{"fields": BASIC[:4], "next": True, "errors_once": True}, {"fields": [BASIC[4]], "submit": True}]
        b, (run,) = self.drive({"pages": pages, "hook": lambda t: setattr(t, "submitted", True)
                                if db.live_runs() and db.live_runs()[0]["state"] == "ready" else None}, [jid], "stop")
        tab = b.tabs[0]
        self.assertEqual(run["state"], "by_user")
        self.assertEqual(tab.clicks, ["Next", "Next"])
        self.assertEqual(sum(w[1] == "First Name" for w in tab.writes), 2)  # the page was filled once more

    def test_questions_pause_the_page_and_your_answer_is_typed(self):
        jid = self.job()
        label = "Why are you interested in Acme Robotics?"

        def hook(tab):
            run = db.live_runs()[0] if db.live_runs() else None
            if run and run["state"] == "needs_you":
                q = pipeline.questions(job=jid)[0]
                self.assertEqual(q["text"], label)
                pipeline.answer(q["id"], "I build robots that ship.", scope="job")
            elif run and run["state"] == "ready":
                tab.submitted = True
        model = {"pages": [{"fields": [*BASIC, F(5, label, "question", tag="textarea", type="", required=True)],
                            "submit": True}], "hook": hook}
        b, (run,) = self.drive(model, [jid], "stop")
        x = self.items(run)[label]
        self.assertEqual((x["status"], x["value"], x["source"]), ("fill", "I build robots that ship.", "you"))
        self.assertIn((0, label, "I build robots that ship."), b.tabs[0].writes)

    def test_a_changed_form_is_proposed_again_and_a_reformatted_phone_is_not(self):
        jid = self.job()
        changed = {"done": False}

        def after(tab, run):
            if run and run["state"] == "approved" and not changed["done"]:
                changed["done"] = True
                tab.vals[1] = "Someone Else"  # edited in the window after you approved
        model = {"pages": [{"fields": BASIC, "submit": True}], "after": after,
                 "reformat": lambda i, v: f"({v[:3]}) {v[4:]}" if i == 3 and v else v}
        b, (run,), st = self.review(model, jid)
        self.assertEqual(st["approved"], 2)  # the first approval was overtaken by your edit; the second one went out
        self.assertEqual(b.tabs[0].clicks, ["Submit application"])
        items = db.con().execute("SELECT status FROM pending WHERE kind='submit_application' AND job_id=?", (jid,)).fetchall()
        self.assertEqual(len(items), 2)
        self.assertEqual(self.items(run)["Phone"]["shown"], "(512) 555-0100")
        newer = json.loads(db.get_pending(run["pending_id"])["payload"])["fields"]
        self.assertIn({"label": "Last Name", "value": "Someone Else", "source": "profile", "flag": ""}, newer)

    def test_the_pipeline_apply_step_runs_the_agent(self):
        jid = self.job()
        for s in ("tailor", "letter", "answers"):
            pipeline.skip(jid, s)
        with patched(apply_agent, _ensure_worker=lambda: None, available=lambda: None):
            r = pipeline.run(jid, "apply")
            self.assertEqual(r["outcome"], "waiting")
            st = {e["name"]: e for e in pipeline.status(jid)}["apply"]
            self.assertEqual(st["state"], "waiting")
            self.assertIn("apply agent run #", st["why"])
            settings.set_tool("apply_agent", enabled=True)
            run = db.runs_for(jid)[0]
            db.update_run(run["id"], mode="review")

            def hook(tab):
                live = db.live_runs()
                if live and live[0]["state"] == "awaiting_approval":
                    approvals.approve(live[0]["pending_id"])
            b = FakeBrowser({"pages": [{"fields": BASIC, "submit": True}], "hook": hook})
            apply_agent._loop(lambda: b, until_idle=True)
            st = {e["name"]: e for e in pipeline.status(jid)}["apply"]
        self.assertEqual(st["state"], "done")
        self.assertEqual((st["output"]["via"], st["output"]["confirmation"]), ("agent", "FIX-7"))
        self.assertTrue(st["output"]["evidence_dir"].endswith(f"run-{run['id']}"))


class Surfaces(Base):
    def test_no_evasion_and_no_password_path(self):
        for f in ("apply_agent.py", "apply_ats.py"):
            src = (Path(apply_agent.__file__).parent / f).read_text(encoding="utf-8")
            code = "\n".join(ln.split("#")[0] for ln in src.split('"""', 2)[2].splitlines())  # no module doc, no comments
            for rx in (r"ignore_default_args", r"add_init_script", r"webdriver\s*=", r"user_agent\s*=", r"locale\s*=",
                       r"timezone_id\s*=", r"stealth", r"2captcha|anti-captcha|capsolver|capmonster", r"vault\.get",
                       r"\brandom\b", r"--disable-blink-features", r"codes\."):
                self.assertIsNone(re.search(rx, code, re.I), f"{f}: {rx}")
        tab = apply_ats.Tab.__new__(apply_ats.Tab)

        class Loc:
            first = property(lambda s: s)

            def get_attribute(self, k):
                return "password"
        tab.page, tab.hosts, tab.forbidden_hit = type("P", (), {"url": "https://a.example/x"})(), ["a.example"], None
        tab._frames = [type("Fr", (), {"locator": lambda s, sel: Loc()})()]
        with self.assertRaises(SystemExit):
            tab.write({"status": "fill", "frame": 0, "i": 1, "kind": "text", "value": "x"})

    def test_backup_profile_delete_job_forget_and_sign_in_window(self):
        apply_agent.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        (apply_agent.PROFILE_DIR / "Cookies").write_bytes(b"secret session")
        apply_agent.STOP.touch()
        z = extras.backup(Path(tempfile.mkdtemp()))
        names = zipfile.ZipFile(z).namelist()
        self.assertFalse([n for n in names if "browser-profile" in n or "apply-agent.stop" in n])
        apply_agent.STOP.unlink()
        jid = self.job(company="Gone Co")
        db.add_run(jid, "stop")
        db.delete_job(jid)
        self.assertEqual(db.con().execute("SELECT COUNT(*) FROM apply_runs WHERE job_id=?", (jid,)).fetchone()[0], 0)
        started = []

        class P:
            def __init__(self, args):
                started.append(args)

            def poll(self):
                return None
        with patched(apply_agent.subprocess, Popen=P), patched(apply_agent, _LOGIN=None):
            live = db.add_run(self.job(company="Live Co"), "stop")
            db.update_run(live, state="running", heartbeat=db._now())
            with self.assertRaises(SystemExit):
                apply_agent.login_window()
            db.update_run(live, state="stopped")
            with self.assertRaises(SystemExit):
                apply_agent.login_window("https://www.linkedin.com/login")
            apply_agent.login_window("https://acme.wd5.myworkdayjobs.example/login")
            self.assertIn(f"--user-data-dir={apply_agent.PROFILE_DIR}", started[0])
            self.assertNotIn("--enable-automation", started[0])
            with self.assertRaises(SystemExit):
                apply_agent.forget_logins()  # the sign-in window is still open
        self.assertEqual(apply_agent.forget_logins(), {"removed": True, "left": []})
        self.assertFalse(apply_agent.PROFILE_DIR.exists())

    def test_routes_need_the_token_and_the_cli(self):
        import http.client

        srv = web.start_server(0)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]

        def call(method, path, body=None, token=True):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            h = {"Content-Type": "application/json", **({"X-Lodestar-Token": web.TOKEN} if token else {})}
            c.request(method, path, json.dumps(body) if body is not None else None, h)
            r = c.getresponse()
            return r.status, r.read()
        for m, p in (("GET", "/api/apply/status"), ("POST", "/api/apply/start"), ("POST", "/api/apply/stop"),
                     ("POST", "/api/apply/1/continue"), ("POST", "/api/apply/login"), ("POST", "/api/apply/forget"),
                     ("GET", "/api/apply/1/shot/page-01.png")):
            self.assertEqual(call(m, p, {} if m == "POST" else None, token=False)[0], 403, p)
        jid = self.job(company="Route Co")
        with patched(apply_agent, _ensure_worker=lambda: None):
            st, body = call("POST", "/api/apply/start", {"ids": [jid, 999999], "mode": "stop"})
        out = json.loads(body)
        self.assertEqual((st, len(out["runs"]), out["refused"][0]["job_id"]), (200, 1, 999999))
        rid = out["runs"][0]["run_id"]
        ev = Path(tempfile.mkdtemp())
        (ev / "page-01.png").write_bytes(b"\x89PNG one")
        (ev / "secret.txt").write_text("no")
        db.update_run(rid, evidence=str(ev))
        self.assertEqual(call("GET", f"/api/apply/{rid}/shot/page-01.png"), (200, b"\x89PNG one"))
        for bad in ("page-1.png", "..%2Fsecret.txt", "secret.txt"):
            self.assertEqual(call("GET", f"/api/apply/{rid}/shot/{bad}")[0], 404, bad)
        st, body = call("GET", "/api/apply/status")
        self.assertEqual(json.loads(body)["queue"], 1)
        self.assertEqual(json.loads(call("POST", "/api/apply/stop", {})[1])["queued_stopped"], 1)
        self.assertIn("apply", web.state())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["apply-agent", "runs", str(jid)])
            cli.main(["apply-agent", "status"])
        self.assertIn(f"run #{rid} stopped", out.getvalue())


if __name__ == "__main__":
    unittest.main()
