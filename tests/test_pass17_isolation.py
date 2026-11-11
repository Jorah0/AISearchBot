"""Pass 17.1, credential isolation: the keyring service is 'lodestar' (with the legacy 'jobbot' fallback) only for the
default data folder; any other LODESTAR_HOME gets its own service, so a test or sandbox run never reads the real keys
or mail password. LODESTAR_VAULT_SERVICE fixes the service on purpose. No real keyring: every call is faked."""
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

if "lodestar.config" not in sys.modules:  # same temp home as test_lodestar.py when that file was imported first
    os.environ["LODESTAR_HOME"] = tempfile.mkdtemp(prefix="lodestar-test-")
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, even with a fixed one in .env
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

from lodestar import config, connections, doctor, mailconn, updater, vault  # noqa: E402

REAL = {("lodestar", "IMAP_PASS"): "real-mail-password", ("lodestar", "ANTHROPIC_API_KEY"): "sk-ant-real-0001",
        ("lodestar", "OAUTH_REFRESH"): "real-refresh-token", ("jobbot", "GROQ_API_KEY"): "gsk_real_legacy"}
ENV = ("LODESTAR_VAULT_SERVICE", "IMAP_PASS", "IMAP_USER", "GROQ_API_KEY", "OAUTH_REFRESH", "EMAIL_PRESET",
       *mailconn.KEYS.values())


class Namespace(unittest.TestCase):
    def setUp(self):
        self.env = {n: os.environ.pop(n) for n in ENV if n in os.environ}

    def tearDown(self):
        os.environ.pop("LODESTAR_VAULT_SERVICE", None)
        os.environ.update(self.env)

    def test_default_home_is_lodestar_with_the_jobbot_fallback(self):
        home = Path.home()
        for p in (home / ".lodestar", home / ".jobbot", home / ".lodestar" / ".." / ".lodestar"):
            self.assertEqual(vault.namespace(p), ("lodestar", "jobbot"), p)
        if os.name == "nt":  # Windows paths compare case-insensitively
            self.assertEqual(vault.namespace(Path(str(home / ".lodestar").upper())), ("lodestar", "jobbot"))

    def test_any_other_home_gets_its_own_service_and_no_fallback(self):
        a, b = tempfile.mkdtemp(prefix="lodestar-ns-"), tempfile.mkdtemp(prefix="lodestar-ns-")
        sa, legacy = vault.namespace(a)
        self.assertRegex(sa, r"^lodestar:[0-9a-f]{12}$")
        self.assertEqual(legacy, "")
        self.assertNotEqual(sa, vault.namespace(b)[0])
        self.assertEqual(sa, vault.namespace(Path(a) / "x" / "..")[0])  # same folder, same service
        self.assertEqual(vault.namespace(Path.home() / ".lodestar-test")[1], "")  # a near-name is not the default
        # this suite's own home (a temp folder) is isolated too
        self.assertEqual((vault.SERVICE, vault.LEGACY), vault.namespace(config.HOME))
        self.assertNotIn(vault.SERVICE, ("lodestar", "jobbot"))

    def test_lodestar_vault_service_wins_for_any_home(self):
        os.environ["LODESTAR_VAULT_SERVICE"] = " lodestar-portable "
        self.assertEqual(vault.namespace(tempfile.gettempdir()), ("lodestar-portable", ""))
        self.assertEqual(vault.namespace(Path.home() / ".lodestar"), ("lodestar-portable", ""))
        os.environ["LODESTAR_VAULT_SERVICE"] = "  "  # blank is unset
        self.assertEqual(vault.namespace(Path.home() / ".lodestar"), ("lodestar", "jobbot"))


class Isolation(unittest.TestCase):
    """A keyring that already holds the 'real' secrets under 'lodestar' and 'jobbot', recording every service touched."""

    def setUp(self):
        self.store, self.touched = dict(REAL), set()
        k, t = vault.keyring, self

        def get(svc, name):
            t.touched.add(svc)
            return t.store.get((svc, name))

        def put(svc, name, v):
            t.touched.add(svc)
            t.store[(svc, name)] = v

        def delete(svc, name):
            t.touched.add(svc)
            if (svc, name) not in t.store:
                raise k.errors.PasswordDeleteError("not there")
            del t.store[(svc, name)]

        self.real = (k.get_password, k.set_password, k.delete_password, vault._index(), (vault.SERVICE, vault.LEGACY),
                     connections.PATH.read_bytes() if connections.PATH.is_file() else None, connections.urlopen)
        k.get_password, k.set_password, k.delete_password = get, put, delete
        connections.urlopen = lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("offline"))  # no network
        self.env = {n: os.environ.pop(n) for n in ENV if n in os.environ}

    def tearDown(self):
        k = vault.keyring
        k.get_password, k.set_password, k.delete_password, idx, (vault.SERVICE, vault.LEGACY), conn, connections.urlopen = self.real
        vault._save_index(idx)
        connections.PATH.write_bytes(conn) if conn is not None else connections.PATH.unlink(missing_ok=True)
        os.environ.update(self.env)

    def assert_real_untouched(self):
        self.assertEqual({key: v for key, v in self.store.items() if key[0] in ("lodestar", "jobbot")}, REAL)

    def test_a_temp_home_never_sees_or_copies_the_default_secrets(self):
        for n in ("IMAP_PASS", "ANTHROPIC_API_KEY", "OAUTH_REFRESH", "GROQ_API_KEY"):
            self.assertIsNone(vault.get(n), n)
            if n not in os.environ:  # the suite sets ANTHROPIC_API_KEY=test-key; the env wins over any vault
                self.assertIsNone(config.setting(n), n)
        self.assertFalse(mailconn.status()["configured"])
        self.assertEqual(self.touched, {vault.SERVICE})
        self.assert_real_untouched()
        self.assertEqual(len(self.store), len(REAL))  # nothing copied over from 'jobbot' either

    def test_every_vault_path_stays_in_the_isolated_service(self):
        long = "M.R3_BAY." + "x" * 2991  # chunked: a head plus pieces
        vault.set("OAUTH_REFRESH", long, "me@example.com")
        self.assertEqual(vault.get("OAUTH_REFRESH"), long)
        mailconn.connect("gmail", "me@example.com", "abcd efgh ijkl mnop")
        self.assertEqual(vault.get("IMAP_PASS"), "abcdefghijklmnop")
        self.assertTrue(mailconn.status()["configured"])
        self.assertEqual(connections.link("groq", "gsk_isolated_key_0001")["status"], "unreachable")  # stored anyway
        self.assertEqual(connections.status()["keys"]["groq"]["source"], "vault")
        self.assertIn("IMAP_PASS", dict(vault.names()))
        new = {key for key in self.store if key not in REAL}
        self.assertTrue(new and all(svc == vault.SERVICE for svc, _ in new), new)
        self.assertTrue(any("~" in n for _, n in new))  # the chunk pieces too
        for n in ("OAUTH_REFRESH", "IMAP_PASS", "GROQ_API_KEY"):
            vault.delete(n)
        self.assertEqual(self.touched, {vault.SERVICE})
        self.assert_real_untouched()

    def test_the_legacy_fallback_belongs_to_the_default_home_only(self):
        self.assertIsNone(vault.get("GROQ_API_KEY"))
        vault.SERVICE, vault.LEGACY = vault.namespace(Path.home() / ".lodestar")  # as on the default data folder
        self.assertEqual(vault.get("GROQ_API_KEY"), "gsk_real_legacy")
        self.assertEqual(self.store[("lodestar", "GROQ_API_KEY")], "gsk_real_legacy")  # copied once under the new name

    def test_doctor_warns_when_the_folder_lists_secrets_its_namespace_lacks(self):
        # review code-4: an own-LODESTAR_HOME install from before 17.1 kept its secrets under 'lodestar'; its name index
        # still lists them, so doctor says what to do instead of a quiet "ok" while AI and mail stop working
        vault._save_index({"ANTHROPIC_API_KEY": {"user": ""}, "IMAP_PASS": {"user": "me@example.com"}})
        s, d = {w: (s, d) for s, w, d in doctor.checks()}["vault namespace"]
        self.assertEqual(s, "warn")
        self.assertIn("2 stored secret(s) not found here (ANTHROPIC_API_KEY, IMAP_PASS)", d)
        self.assertIn("LODESTAR_VAULT_SERVICE=lodestar", d)
        self.assertNotIn("real-mail-password", d)
        self.assert_real_untouched()

    def test_doctor_names_the_active_namespace(self):
        vault._save_index({})  # names other tests left in the shared home are not in this fake keyring
        rows = {w: (s, d) for s, w, d in doctor.checks()}
        self.assertEqual(rows["vault namespace"], ("ok", f"{vault.SERVICE} (this data folder only: the default folder's "
                                                         "secrets are not visible)"))
        vault.SERVICE, vault.LEGACY = "lodestar", "jobbot"
        self.assertEqual({w: d for _, w, d in doctor.checks()}["vault namespace"], "lodestar (the default data folder)")

    def test_doctor_warns_on_a_null_or_fail_keyring(self):  # both classes are named 'Keyring': the module tells them apart
        from keyring.backends import fail, null

        real = vault.keyring.get_keyring
        try:
            for backend, shown in ((null.Keyring(), "null.Keyring"), (fail.Keyring(), "fail.Keyring")):
                vault.keyring.get_keyring = lambda b=backend: b
                self.assertEqual({w: (s, d) for s, w, d in doctor.checks()}["keyring backend"], ("warn", shown))
        finally:
            vault.keyring.get_keyring = real


class Suite(unittest.TestCase):
    """Review code-3: a LODESTAR_VAULT_SERVICE=lodestar line in the repo .env (as the guide allows) must never give the
    unit suite the real service: every module that sets a temp home blanks it first, and "" beats the .env setdefault."""

    def test_every_temp_home_module_blanks_the_vault_service(self):
        here = Path(__file__).parent
        for f in sorted(here.glob("test_*.py")):
            text = f.read_text(encoding="utf-8")
            if 'os.environ["LODESTAR_HOME"] = tempfile' in text:
                self.assertIn('os.environ["LODESTAR_VAULT_SERVICE"] = ""', text, f.name)

    def test_a_fixed_service_in_the_environment_never_reaches_the_suite(self):
        import subprocess

        here = Path(__file__).parent
        env = {**os.environ, "LODESTAR_VAULT_SERVICE": "lodestar", "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
        env.pop("LODESTAR_HOME", None)
        code = (f"import sys; sys.path.insert(0, {str(here)!r}); import test_lodestar; from lodestar import vault; "
                "print(vault.SERVICE)")
        out = subprocess.run([sys.executable, "-c", code], cwd=here.parent, env=env, capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        self.assertRegex(out.stdout.strip().splitlines()[-1], r"^lodestar:[0-9a-f]{12}$")


class Gate(unittest.TestCase):
    def test_the_update_gate_runs_the_suite_on_its_own_namespace(self):
        seen, repo = [], Path(tempfile.mkdtemp(prefix="lodestar-gate-"))
        (repo / "tests").mkdir()
        real = (updater._run, updater._proc)
        updater._run = lambda cmd, cwd, timeout, env=None: seen.append(env) or ""
        updater._proc = lambda cmd, cwd, timeout, env=None: (0, "all good", "")
        os.environ["LODESTAR_VAULT_SERVICE"] = "lodestar"  # the user's fixed (real) service must not reach the tests
        try:
            updater._gate(repo)
        finally:
            updater._run, updater._proc = real
            os.environ.pop("LODESTAR_VAULT_SERVICE", None)
        self.assertEqual(seen[0]["LODESTAR_VAULT_SERVICE"], "")
        self.assertNotEqual(Path(seen[0]["LODESTAR_HOME"]), config.HOME)


if __name__ == "__main__":
    unittest.main()
