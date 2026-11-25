"""Security + resource audit fixes (2026-11-25): each test names the failure it prevents. A huge POST body is refused
before it is read; idle connections time out; backups skip folders only where they live (a company named "Media" is
kept); alerts.log is read by its tail and rotated; Hugging Face ids and scratch corpora are checked; held-out decisions
never reach the teacher or a scratch corpus; loopback Ollama calls never use a proxy; the update gate never runs new
code with your keys or data folder; training pauses when the desktop app closes. Every patch is put back."""
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
from test_pass21_fit import patched  # noqa: E402

from lodestar import extras, jobmodel, labtrain, modellab, teacher, updater, util, web  # noqa: E402


class Server(unittest.TestCase):
    def test_a_huge_body_is_refused_before_it_is_read_and_idle_sockets_time_out(self):
        class H:
            headers = {"Content-Length": str(web.MAX_BODY + 1), "Content-Type": "application/json"}

            class rfile:
                @staticmethod
                def read(n):
                    raise AssertionError("the body was read")
        with self.assertRaises(ValueError):
            web.Handler._body(H())
        self.assertTrue(web.Handler.timeout and web.PhoneHandler.timeout)  # the phone listener inherits it


class Files(unittest.TestCase):
    def test_backups_skip_folders_only_where_they_live(self):
        P = Path
        self.assertFalse(extras.in_backup(P("applications/7-acme/mail/a.eml")))
        self.assertTrue(extras.in_backup(P("applications/media/resume.md")))  # a company called Media
        self.assertTrue(extras.in_backup(P("applications/7-cache/letter.md")))
        for skip in ("snapshots/job-1.json", "cache/boards/x.json", "x/__pycache__/a.pyc", "train-env/a", "lab/jobs/a",
                     "media/1/a.png", "backups/b.zip", "procs/1.pid"):
            self.assertFalse(extras.in_backup(P(skip)), skip)

    def test_the_alert_log_is_read_by_its_tail(self):
        f = Path(tempfile.mkdtemp()) / "a.log"
        f.write_text("\n".join(f"line {i}" for i in range(50000)), encoding="utf-8")
        self.assertEqual(util.tail_lines(f, 2), ["line 49998", "line 49999"])
        self.assertEqual(util.tail_lines(f.with_name("missing.log")), [])


class Lab(unittest.TestCase):
    def test_hub_ids_and_corpora_are_checked(self):
        for bad in ("C:/Users", "../x", "./a/b", "Qwen/Qwen2.5 bad", "https://x.example/a"):
            with self.assertRaises(SystemExit, msg=bad):
                modellab.clean_spec("existing", {"variant_id": "x", "hf_repo": bad})
        ok = modellab.clean_spec("existing", {"variant_id": "x", "hf_repo": "Qwen/Qwen2.5-7B-Instruct"})
        self.assertEqual(ok["hf_repo"], "Qwen/Qwen2.5-7B-Instruct")
        with self.assertRaises(SystemExit):  # never the data folder (profile.md, Preferences) or elsewhere
            modellab.clean_spec("scratch", {"corpus": str(Path.home())})

    def test_held_out_decisions_never_reach_the_teacher_or_a_scratch_corpus(self):
        rows = [{"id": f"job:{i}", "title": f"Role {i}", "company": "Acme", "location": "", "jd": "x", "label": "pursued",
                 "strength": 1} for i in range(8)]
        held = {"job:3", "job:7"}
        with patched(jobmodel, decisions=lambda: rows), patched(teacher, held_out=lambda: held, accepted=lambda split: []):
            self.assertFalse(held & {d["id"] for d in teacher.pending_decisions()})
            body = Path(modellab._scratch_corpus({})).read_text(encoding="utf-8")
        self.assertNotIn("Role 3 at", body)
        self.assertIn("Role 2 at", body)

    def test_ollama_calls_never_use_a_proxy(self):
        import urllib.request

        opener = jobmodel.urlopen.__self__  # its own opener, never urllib's global one (which honours HTTP_PROXY)
        self.assertIsNot(jobmodel.urlopen, urllib.request.urlopen)
        self.assertFalse([h for h in opener.handlers if getattr(h, "proxies", None)])

    def test_training_pauses_when_the_app_closes(self):
        d = Path(tempfile.mkdtemp())
        job = {"id": 99, "status": "running", "idem_key": "z" * 32}
        with patched(labtrain, jobs=lambda limit=50: [job, {"id": 98, "status": "done", "idem_key": "y" * 32}],
                     job_dir=lambda j: d):
            self.assertEqual(labtrain.pause_all(), [99])
        self.assertTrue((d / "pause").is_file())


class Update(unittest.TestCase):
    def test_new_code_is_checked_without_your_keys_or_data_folder(self):
        seen = []
        os.environ["IMAP_PASS"] = "app-password"
        try:
            with patched(updater, _run=lambda cmd, cwd, t, env: seen.append(env),
                         _proc=lambda cmd, cwd, t, env: seen.append(env) or (0, "all good", "")):
                updater._gate(Path(__file__).resolve().parent.parent)
        finally:
            os.environ.pop("IMAP_PASS", None)
        self.assertEqual(len(seen), 2)  # the unit suite and doctor
        for env in seen:
            self.assertNotIn("IMAP_PASS", env)
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertEqual(env["LODESTAR_VAULT_SERVICE"], "")
            self.assertIn("lodestar-update-gate-", env["LODESTAR_HOME"])  # never your data folder
        json.dumps(seen)


if __name__ == "__main__":
    unittest.main()
