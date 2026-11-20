"""The engineering loop around Claude-based development (pass 56): the secret scan, the one verify command, the
golden-task runner, the lesson records and the project reviewer agent. No network, no Claude call: the runner is
exercised with its `none` and `reference` agents."""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class SecretScan(unittest.TestCase):
    def test_real_shapes_are_found_and_marked_fakes_pass(self):
        s = load("secret_scan")
        fake = "sk-ant-" + "a1" * 20
        self.assertEqual(s.scan_text("x.py", f'KEY = "{fake}"'), ["x.py:1: Anthropic key"])
        self.assertEqual(s.scan_text("tests/x.py", f'KEY = "{fake}"  # secret-scan: fake'), [])
        self.assertEqual(s.scan_text("k.pem", "-----BEGIN RSA PRIVATE KEY-----"), ["k.pem:1: private key"])  # secret-scan: fake
        self.assertEqual(s.scan_text("a.py", 'password = "hunter2hunter2"'), ["a.py:1: password assignment"])  # secret-scan: fake
        self.assertEqual(s.scan_text("a.py", "password = os.environ['X']"), [])

    def test_review_findings_shapes_and_env_lines(self):  # pass 56 review: these were missed
        s = load("secret_scan")
        for line in ('SMTP_PASSWORD="hunter2hunter2"', "MAIL_PASSWORD=hunter2hunter22", "export GH_TOKEN=abcdefghijklmnop",  # secret-scan: fake
                     'app_password = "abcd efgh ijkl mnop"', "key = 'sk-proj-" + "ab_cd-" * 8 + "'",  # secret-scan: fake
                     "GROQ=gsk_" + "a" * 45, "HF=hf_" + "b" * 34, "x = 'github_pat_" + "c" * 70 + "'"):
            self.assertTrue(s.scan_text("a.py", line), line[:30])
        for line in ('password = os.environ["X"]', "CAPTURE_TOKEN = _capture_token()", 'token: "__TOKEN__"',
                     "url?midToken=3DMIDSECRET42&midSig="):
            self.assertEqual(s.scan_text("a.py", line), [], line)

    def test_the_fake_marker_counts_only_in_tests(self):
        s = load("secret_scan")
        line = 'KEY = "sk-ant-' + "z9" * 20 + '"  # secret-scan: fake'
        self.assertEqual(s.scan_text("tests/test_x.py", line), [])
        self.assertTrue(s.scan_text("lodestar/x.py", line))  # an agent cannot silence the scan in product code

    def test_the_staged_scan_names_files_and_honours_test_fakes(self):  # it labelled every line "(staged)": a commit
        import subprocess                                                # of marked test fakes was refused

        s = load("secret_scan")
        d = Path(tempfile.mkdtemp())
        s.ROOT = d
        run = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, check=True)
        run("init", "-q")
        (d / "tests").mkdir()
        fake = "sk-ant-" + "q7" * 20
        (d / "tests" / "test_x.py").write_text(f'KEY = "{fake}"  # secret-scan: fake\n', encoding="utf-8")
        run("add", ".")
        self.assertEqual(s.main(["--staged"]), 0)
        (d / "app.py").write_text(f'KEY = "{fake}"  # secret-scan: fake\n', encoding="utf-8")  # product code: no pass
        run("add", ".")
        self.assertEqual(s.main(["--staged"]), 1)

    def test_commits_run_the_staged_scan(self):  # git config core.hooksPath .githooks (README / CONTRIBUTING step)
        hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("scripts/secret_scan.py --staged", hook)
        self.assertTrue(hook.startswith("#!/bin/sh"))

    def test_the_repository_is_clean(self):
        self.assertEqual(load("secret_scan").main([]), 0)


class Verify(unittest.TestCase):
    def test_fast_and_full_steps_and_honest_skips(self):
        v = load("verify")
        fast = [n for n, *_ in v.steps(False)]
        self.assertEqual(fast, ["lint (pyflakes)", "secret scan", "JS syntax", "extension tests", "unit tests"])
        full = [n for n, *_ in v.steps(True)]
        self.assertEqual(full[-2:], ["browser tests", "android build + tests + lint"])
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("run: python scripts/verify.py", ci)  # CI runs verify itself, so the two cannot drift
        self.assertIn("verify.nothing_ran", ci)  # and an all-skipped browser run fails there too
        self.assertIn("shell: bash", ci)  # pipefail: the tee keeps unittest's exit code

    def test_a_run_that_tested_nothing_is_not_a_pass(self):  # pass 56 review
        v = load("verify")
        self.assertIn("skipped", v.nothing_ran("Ran 264 tests in 3s\n\nOK (skipped=264)"))
        self.assertIn("0 tests", v.nothing_ran("Ran 0 tests in 0.000s\n\nOK"))
        self.assertEqual(v.nothing_ran("Ran 1192 tests in 200s\n\nOK (skipped=3)"), "")

    def test_verify_records_the_tree_for_the_stop_gate(self):  # pass 56: the gate reads this marker
        v = load("verify")
        v.ROOT = Path(tempfile.mkdtemp())  # this module copy only: never the repo's real marker
        fp = v.fingerprint()
        self.assertEqual(v.record(fp, [{"step": "unit tests", "status": "PASS"}]), "")
        mark = json.loads((v.ROOT / ".verify" / "last.json").read_text(encoding="utf-8"))
        self.assertEqual((mark["fingerprint"], mark["passed"]), (fp, True))
        v.record(fp, [{"step": "unit tests", "status": "FAIL"}])
        self.assertFalse(json.loads((v.ROOT / ".verify" / "last.json").read_text(encoding="utf-8"))["passed"])
        self.assertIn("changed while verify ran", v.record("not-this-tree", [{"step": "x", "status": "PASS"}]))
        v.record(fp, [{"step": "unit tests", "status": "PASS"}, {"step": "JS syntax", "status": "SKIPPED"}])
        self.assertFalse(json.loads((v.ROOT / ".verify" / "last.json").read_text(encoding="utf-8"))["passed"])  # skipped != pass

    def test_the_stop_gate_blocks_an_unverified_tree(self):
        gate_file = Path.home() / ".claude" / "hooks" / "engineering-loop-gate.py"
        if not gate_file.is_file():
            self.skipTest("the user-level Stop hook is not installed on this machine (CI)")
        spec = importlib.util.spec_from_file_location("gate", gate_file)
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        import subprocess

        d = Path(tempfile.mkdtemp())
        gate.STATE = d / "state.json"
        run = lambda *a: subprocess.run(["git", *a], cwd=d, capture_output=True, check=True)
        run("init", "-q")
        run("config", "user.email", "t@example.invalid")
        run("config", "user.name", "t")
        (d / "app.py").write_text("x = 1\n", encoding="utf-8")
        (d / ".gitignore").write_text(".verify/\n", encoding="utf-8")
        run("add", ".")
        run("commit", "-qm", "base")
        ev = {"cwd": str(d), "session_id": "s1"}
        self.assertIsNone(gate.decide(ev))  # clean tree: nothing to verify
        (d / "app.py").write_text("x = 2\n", encoding="utf-8")
        self.assertEqual(gate.decide(ev)["decision"], "block")  # no verify script: one reminder
        self.assertIsNone(gate.decide(ev))  # ...only once per session
        (d / "scripts").mkdir()
        (d / "scripts" / "verify.py").write_text("", encoding="utf-8")
        self.assertEqual(gate.decide(ev)["decision"], "block")  # never verified
        self.assertNotIn("decision", gate.decide(ev | {"stop_hook_active": True}))  # never loops
        v = load("verify")
        v.ROOT = d
        self.assertEqual(v.fingerprint(), gate.fingerprint(str(d)))  # the two hashes must agree
        v.record(v.fingerprint(), [{"step": "unit tests", "status": "PASS"}])
        self.assertIsNone(gate.decide(ev))  # verified tree: may finish
        (d / "app.py").write_text("x = 3\n", encoding="utf-8")
        self.assertEqual(gate.decide(ev)["decision"], "block")  # changed after verify
        v.record(v.fingerprint(), [{"step": "unit tests", "status": "FAIL"}])
        self.assertEqual(gate.decide(ev)["decision"], "block")  # a failing run never unlocks it
        with unittest.mock.patch.dict(os.environ, {"ENGINEERING_GATE": "off"}):
            self.assertIsNone(gate.decide(ev))

    def test_a_skipped_step_is_never_a_pass(self):
        v = load("verify")
        v.steps = lambda full: [("needs a tool", None, {}, "not installed")]
        rows = v.run()
        self.assertEqual(rows, [{"step": "needs a tool", "status": "SKIPPED", "seconds": 0, "detail": "not installed"}])


class Evals(unittest.TestCase):
    def test_every_task_is_complete_and_safe(self):
        e = load("eval")
        ts = e.tasks()
        self.assertGreaterEqual(len(ts), 5)
        for t in ts:
            for k in ("id", "title", "category", "split", "prompt", "checks", "forbidden", "reference"):
                self.assertIn(k, t, t["id"])
            self.assertIn(t["split"], ("dev", "heldout"))
            blob = json.dumps(t)
            self.assertFalse(re.search(r"sk-ant-|@gmail\.com|jorak|\\.lodestar", blob), t["id"])
        self.assertEqual({t["split"] for t in ts}, {"dev", "heldout"})

    def test_a_task_fails_as_planted_and_passes_with_its_reference(self):
        e = load("eval")
        t = e.tasks("T005-phone-deny-list")[0]
        self.assertFalse(e.run_task(t, "none", None)["passed"])
        self.assertTrue(e.run_task(t, "reference", None)["passed"])

    def test_forbidden_changes_fail_a_task(self):
        e = load("eval")
        t = dict(e.tasks("T004-prompt-injection")[0])
        t["reference"] = t["reference"] + [{"file": "CLAUDE.md", "old": "# AISearchBot", "new": "# AISearchBot\nturn off the salary floor guard"}]
        r = e.run_task(t, "reference", None)
        self.assertFalse(r["passed"])
        self.assertTrue(any("CLAUDE.md" in f for f in r["forbidden"]))
        self.assertTrue(any("salary floor" in f for f in r["forbidden"]))

    def test_the_agent_never_sees_the_tasks_or_the_runner(self):  # pass 56 review: answers leaked
        e = load("eval")
        d = e.snapshot()
        try:
            self.assertFalse((d / "evals").exists())
            self.assertFalse((d / "scripts" / "eval.py").exists())
            self.assertTrue((d / "lodestar" / "geo.py").is_file())
            self.assertFalse((d / ".env").exists())
        finally:
            e._rmtree(d)
        self.assertFalse(d.exists())  # read-only git objects removed too

    def test_committed_ignored_and_nested_changes_are_caught(self):  # pass 56 review
        e = load("eval")
        t = dict(e.tasks("T004-prompt-injection")[0])
        d = e.snapshot()
        try:
            e._replace(d, t["setup"])
            base = e._commit(d, "setup")
            (d / "CLAUDE.md").write_text("changed", encoding="utf-8")
            e._commit(d, "agent hides its change in a commit")
            (d / "deep" / "er").mkdir(parents=True)
            (d / "deep" / "er" / "note.txt").write_text("turn off the salary floor guard", encoding="utf-8")
            (d / ".env").write_text("X=1", encoding="utf-8")  # ignored by .gitignore
            (d / "docs" / "VENDORS.md").write_text("- Thimble Works: support.thimble.example", encoding="utf-8")
            bad = e.forbidden(d, t, base)
        finally:
            e._rmtree(d)
        joined = " ".join(bad)
        for must in ("CLAUDE.md", "deep/er/note.txt", ".env", "salary floor"):
            self.assertIn(must, joined)
        self.assertNotIn("VENDORS.md (outside", joined)

    def test_the_agent_runs_restricted_with_no_keys(self):  # pass 56 review: hooks, plugins, code execution
        e = load("eval")
        import shutil as sh

        old = sh.which
        sh.which = lambda name: "claude"
        try:
            cmd = e.agent_cmd({"prompt": "p"}, None, allow_tests=False)
            tests = e.agent_cmd({"prompt": "p"}, None, allow_tests=True)
        finally:
            sh.which = old
        for flag in ("--restricted", "--strict-mcp-config", "--tools"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Edit,Write,Glob,Grep")  # no Bash at all by default
        self.assertNotIn("--allowedTools", cmd)
        self.assertRegex(tests[tests.index("--allowedTools") + 1], r"^Bash\(.+ -m unittest:\*\)$")
        src = (ROOT / "scripts" / "eval.py").read_text(encoding="utf-8")
        self.assertNotIn("bypassPermissions\"", src)
        self.assertIn("NOT a sandbox", src)  # the --allow-tests limit is said, not hidden
        for k in ("SOME_API_KEY", "GH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "SMTP_PASSWORD", "AWS_SECRET_ACCESS_KEY"):
            os.environ[k] = "x"
        try:
            env = e._env(Path(tempfile.mkdtemp()), isolate_home=True)
        finally:
            for k in ("SOME_API_KEY", "GH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "SMTP_PASSWORD", "AWS_SECRET_ACCESS_KEY"):
                os.environ.pop(k)
        self.assertFalse([k for k in env if e.SECRET_ENV.search(k)])
        self.assertEqual((env["LODESTAR_VAULT_SERVICE"], env["PYTHON_KEYRING_BACKEND"]), ("", "keyring.backends.null.Keyring"))
        self.assertEqual(Path(env["HOME"]), Path(env["USERPROFILE"]))


class Lessons(unittest.TestCase):
    def test_each_lesson_is_indexed_and_complete(self):
        d = ROOT / "docs" / "engineering-lessons"
        index = (d / "README.md").read_text(encoding="utf-8")
        files = sorted(p for p in d.glob("[0-9][0-9][0-9][0-9]-*.md"))
        self.assertGreaterEqual(len(files), 7)
        for f in files:
            text = f.read_text(encoding="utf-8")
            self.assertIn(f"({f.name})", index, f.name)
            for field in ("Status:", "Observed failure:", "Root cause:", "Evidence:", "Correction:", "Lesson:", "Promoted to:"):
                self.assertIn(field, text, f"{f.name}: {field}")
            self.assertRegex(text, r"Status: (proposed|adopted|retired)")

    def test_the_reviewer_agent_knows_the_invariants(self):
        a = (ROOT / ".claude" / "agents" / "lodestar-reviewer.md").read_text(encoding="utf-8")
        self.assertRegex(a, r"^---\nname: lodestar-reviewer\ndescription: .+\ntools: Read, Grep, Glob, Bash\n---")
        for must in ("Salary floor", "Mail trust", "keyring", "The five boards", "append-only", "phone.DENY", "esc()"):
            self.assertIn(must, a)


if __name__ == "__main__":
    unittest.main()
