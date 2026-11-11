"""Setup and Tools: the AI-key card (provider dropdown and hint, Link blank / wrong prefix / verified / rejected, Re-check,
Re-check all, Remove, keys never come back, Ollama), Test providers / List models / Local only, Diagnostics (+ live),
desktop notifications, market rates, bookmarklets, the vault, the Data panel (backup, exports, open folders), About;
Connect email (presets, guess from the address, Connect & test with bad input, custom servers and ports, test send,
disconnect), Google sign-in against a fake token endpoint (client setup, the loopback redirect, sign out) and a cancelled
Microsoft sign-in; Tools (tool switches, every kind of preference, bad values); keyboard and 420px."""
import base64
import http.client
import imaplib
import io
import json
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from harness import E2ETestCase, FakeMail, _resp, connections, mailconn, oauth, vault, web
from lodestar import settings


class SetupKeys(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("setup")

    def key_row(self, label):
        return self.page.locator("#kList > div", has=self.page.locator("b", has_text=label))

    def link(self, name, key):
        self.page.select_option("#kProv", name)
        self.page.fill("#kVal", key)
        self.run_click(self.page.locator("#keysCard").get_by_role("button", name="Link", exact=True))

    # --- AI keys
    def test_key_link_bad_input_reject_recheck_and_remove(self):
        self.allow_console()
        connections.record("keys", "openai", {"status": "failed", "detail": "the provider rejected this key"},
                           connections.fp("sk-e2e-fake-key-0002"))  # as seeded (live diagnostics may re-check it)
        self.reload_state()
        self.assertIn("Verified", self.key_row("Anthropic").locator(".pill").text_content())
        openai = self.key_row("OpenAI")
        self.assertEqual(openai.locator(".pill").text_content(), "Failed")
        self.assertIn("the provider rejected this key", openai.text_content())
        self.page.select_option("#kProv", "groq")
        self.assertEqual(self.page.text_content("#kHint"), "Get a key: https://console.groq.com/keys (starts with gsk_)")
        self.assertIn("Groq: not linked", self.page.text_content("#kList"))
        self.link("groq", "")
        self.expect_toast("error: paste the Groq key (starts with gsk_)", "err")
        # rejected by the provider: stored anyway, shown Failed with the next step
        real = connections.urlopen

        def refused(req, *a, **kw):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"invalid_api_key"}'))

        connections.urlopen = refused
        try:
            self.link("groq", "gsk_e2e_rejected_key_0003")
        finally:
            connections.urlopen = real
        self.expect_toast("Groq: Failed - the provider rejected this key", "err")
        row = self.key_row("Groq")
        self.assertEqual(row.locator(".pill").text_content(), "Failed")
        self.assertEqual(self.page.input_value("#kVal"), "")  # the key field is cleared either way
        # Re-check this one (the provider now accepts it)
        self.run_click(row.get_by_role("button", name="Re-check"))
        self.assertIn("Verified", row.locator(".pill").text_content())
        self.assertEqual(self.state()["connections"]["keys"]["groq"]["status"], "verified")
        # a key that does not look like one is linked with a warning
        self.link("groq", "not-a-groq-key-1234")
        self.expect_toast("this does not look like an Groq key (starts with gsk_); linked anyway", "ok")
        self.assertEqual(vault.get("GROQ_API_KEY"), "not-a-groq-key-1234")
        for secret in ("not-a-groq-key-1234", "gsk_e2e_rejected_key_0003", "sk-ant-e2e-fake-key-0001"):
            self.assertNotIn(secret, self.page.content())  # keys never come back to the page
            self.assertNotIn(secret, json.dumps(self.state()))
        self.assertIn("Groq (linked)", self.page.locator("#kProv option[value=groq]").text_content())
        # Remove: asks first
        self.answer(False)
        row.get_by_role("button", name="Remove").click()
        self.assertIn("Remove the Groq key from the OS keyring?", self.dialogs[-1])
        self.idle()
        self.assertTrue(vault.get("GROQ_API_KEY"))
        self.answer(True)
        self.run_click(row.get_by_role("button", name="Remove"))
        self.expect_toast("removed", "ok")
        self.assertIsNone(vault.get("GROQ_API_KEY"))
        self.assertIn("Groq: not linked", self.page.text_content("#kList"))

    def test_recheck_all_ollama_and_provider_tools(self):
        urls = len(self.urls)
        self.run_click(self.page.get_by_role("button", name="Re-check all"))
        self.expect_toast("checked", "ok")
        self.assertTrue(any("anthropic" in u for u in self.urls[urls:]))
        self.page.select_option("#kProv", "ollama")
        self.assertTrue(self.page.is_disabled("#kVal"))
        self.assertIn("no key: Link checks Ollama", self.page.get_attribute("#kVal", "placeholder"))
        self.assertEqual(self.key_row("Ollama").get_by_role("button", name="Remove").count(), 0)
        self.run_click(self.page.get_by_role("button", name="Test providers"))
        out = json.loads(self.page.text_content("#provOut"))
        self.assertEqual(set(out), {k for k, v in self.state()["providers"].items() if v})
        self.assertTrue(all(v.startswith("Fake AI reply") for v in out.values()))
        self.run_click(self.page.get_by_role("button", name="List models"))
        self.assertEqual(json.loads(self.page.text_content("#provOut")), {k: [] for k in out})
        provider = settings.load()["prefs"]["provider"]
        self.run_click(self.page.get_by_role("button", name="Local only (Ollama)"))
        self.expect_toast("local-only preset NOT applied (nothing changed)", "ok")
        self.assertEqual(settings.load()["prefs"]["provider"], provider)

    def test_linking_ollama_shows_it_linked_and_verified(self):
        # pass 17.1: Link said "Verified" while the card still read "Ollama (local, no key): not linked"
        self.addCleanup(settings.set_pref, "models", settings.pref("models"))  # the class's other tests expect no Ollama
        self.assertIn("Ollama (local, no key): not linked", self.page.text_content("#kList"))
        self.page.select_option("#kProv", "ollama")  # no key to type: the field is disabled
        self.run_click(self.page.locator("#keysCard").get_by_role("button", name="Link", exact=True))
        self.expect_toast("Ollama (local, no key): Verified", "ok")
        row = self.key_row("Ollama")
        self.assertIn("Verified", row.locator(".pill").text_content())
        self.assertIn("model llama3.1", row.text_content())
        self.assertNotIn("Ollama (local, no key): not linked", self.page.text_content("#kList"))
        self.assertIn("(linked)", self.page.locator("#kProv option[value=ollama]").text_content())
        self.assertTrue(self.state()["connections"]["keys"]["ollama"]["linked"])
        # Remove unlinks it: asks first, then clears the saved model (it used to have no Remove at all)
        self.answer(True)
        self.run_click(row.get_by_role("button", name="Remove"))
        self.assertIn("Unlink Ollama?", self.dialogs[-1])
        self.expect_toast("removed", "ok")
        self.assertIn("Ollama (local, no key): not linked", self.page.text_content("#kList"))
        self.assertFalse(settings.pref("models").get("ollama"))

    def test_diagnostics_name_the_isolated_vault_namespace(self):
        # pass 17.1: a temp data folder has its own keyring service, never the default folder's 'lodestar'
        self.allow_console()
        self.run_click(self.page.get_by_role("button", name="Run diagnostics"))
        row = self.page.locator("#doctorOut .list > div", has_text="vault namespace")
        self.assertIn(vault.SERVICE, row.text_content())
        self.assertIn("this data folder only", row.text_content())
        self.assertRegex(vault.SERVICE, r"^lodestar:[0-9a-f]{12}$")

    def test_diagnostics_notifications_and_market_rates(self):
        self.allow_console()
        self.run_click(self.page.get_by_role("button", name="Run diagnostics"))
        rows = self.page.locator("#doctorOut .list > div")
        self.assertGreater(rows.count(), 5)
        self.assertIn("PASS", rows.first.text_content())
        self.assertNotIn("live call", self.page.text_content("#doctorOut"))
        self.run_click(self.page.get_by_role("button", name="Diagnostics + live AI call"))
        live = self.page.locator("#doctorOut .list > div", has_text="live call anthropic")
        self.assertEqual(live.locator(".pill").text_content(), "PASS")
        # desktop notifications: the switch is a preference; the test fires even with it off
        self.assertFalse(self.page.is_checked("#pNotify"))
        opened = len(self.opened)
        self.run_click(self.page.get_by_role("button", name="Send a test"))
        self.expect_toast("test notification sent", "ok")
        self.assertEqual(self.opened[opened], ("toast", "Lodestar"))
        self.page.check("#pNotify")
        self.idle()
        self.assertTrue(settings.load()["prefs"]["desktop_notifications"])
        self.page.uncheck("#pNotify")
        self.idle()
        self.assertFalse(settings.load()["prefs"]["desktop_notifications"])
        # market rates
        rec = self.page.locator("#setup .panel", has_text="Market rates").get_by_role("button", name="Record")
        rates = self.page.evaluate("RATES.length")
        rec.click()
        self.expect_toast("error:", "err")
        self.idle()
        self.assertEqual(self.page.evaluate("RATES.length"), rates)
        self.page.fill("#mTitle", "Analytics Engineer")
        self.page.fill("#mCity", "Seattle")
        self.page.fill("#mLow", "170000")
        self.page.fill("#mHigh", "130000")
        rec.click()
        self.expect_toast("error: low must not exceed high", "err")
        self.page.fill("#mLow", "130000")
        self.page.fill("#mHigh", "170000")
        rec.click()
        self.expect_toast("recorded", "ok")
        self.idle()
        rows = {(r["t"], r["c"]): (r["lo"], r["hi"]) for r in self.page.evaluate("RATES")}
        self.assertEqual(list(rows[("analytics engineer", "seattle")]), [130000, 170000])
        self.assertEqual([self.page.input_value(s) for s in ("#mTitle", "#mCity", "#mLow", "#mHigh")], ["", "", "", ""])
        row = self.page.locator("#compList > div", has_text="analytics engineer")
        self.assertIn("130,000 - 170,000", row.text_content())
        row.get_by_role("button", name="remove").click()
        self.expect_toast("removed", "ok")
        self.idle()
        self.assertEqual(row.count(), 0)
        self.assertIn("data engineer", self.page.text_content("#compList"))

    def test_bookmarklets_vault_data_panel_and_about(self):
        self.allow_console()
        bm, af = self.page.get_attribute("#bm", "href"), self.page.get_attribute("#af", "href")
        capture = self.page.evaluate("CAPTURE")
        self.assertTrue(bm.startswith("javascript:") and f"{self.base}/api/capture?t={capture}" in bm)
        self.assertTrue(af.startswith("javascript:") and f"{self.base}/api/autofill?t={capture}" in af)
        self.assertNotIn(web.TOKEN, bm + af)  # the page token never goes into a bookmark
        # vault
        store = self.page.locator("#setup .panel", has_text="Other secrets").get_by_role("button", name="Store")
        store.click()
        self.expect_toast("give both a name (e.g. ANTHROPIC_API_KEY) and the secret to store", "err")
        self.page.fill("#vName", "E2E_SECRET")
        self.page.fill("#vUser", "pat")
        self.page.fill("#vVal", "e2e-vault-value-123")
        store.click()
        self.expect_toast("stored", "ok")
        self.idle()
        self.assertEqual(vault.get("E2E_SECRET"), "e2e-vault-value-123")
        self.assertEqual(self.page.input_value("#vVal"), "")
        pill = self.page.locator("#vList .pill", has_text="E2E_SECRET (pat)")
        self.assertEqual(pill.count(), 1)
        self.assertNotIn("e2e-vault-value-123", self.page.content())
        self.answer(False)
        pill.get_by_role("button", name="remove").click()
        self.idle()
        self.assertTrue(vault.get("E2E_SECRET"))
        self.answer(True)
        pill.get_by_role("button", name="remove").click()
        self.expect_toast("removed E2E_SECRET", "ok")
        self.idle()
        self.assertIsNone(vault.get("E2E_SECRET"))
        # data panel
        data = self.page.locator("#setup .panel", has=self.page.locator("h3", has_text="Data"))
        self.run_click(data.get_by_role("button", name="Backup now"))
        path = Path(self.expect_toast("backup written: ", "ok").split("backup written: ", 1)[1].strip())
        self.assertEqual(path.parent, self.home / "backups")
        self.assertIn("lodestar.db", " ".join(zipfile.ZipFile(path).namelist()))
        self.run_click(data.get_by_role("button", name="Export JSON"))
        path = Path(self.expect_toast("exported: ", "ok").split("exported: ", 1)[1].strip())
        self.assertIn("Orchid Health", path.read_text(encoding="utf-8"))
        self.run_click(data.get_by_role("button", name="Export CSV"))
        path = Path(self.expect_toast("CSV files written to ", "ok").split("CSV files written to ", 1)[1].strip())
        jobs = max(path.glob("jobs-*.csv"))  # one CSV per table
        self.assertIn("Orchid Health", jobs.read_text(encoding="utf-8"))
        for button, target in (("Open exports", self.home / "exports"), ("Open data folder", self.home),
                               ("Open documents", self.home / "applications"), ("Open backups", self.home / "backups"),
                               ("Open log", self.home / "lodestar.log")):
            opened = len(self.opened)
            self.run_click(data.get_by_role("button", name=button))
            self.assertEqual(self.opened[opened:], [("folder", str(target))], button)
        self.assertEqual(self.page.text_content("#ver"), "Lodestar " + self.state()["version"])

    def test_keyboard_and_420px(self):
        self.page.focus("#kProv")
        self.page.select_option("#kProv", "mistral")
        self.press("Tab")
        self.page.keyboard.type("e2e-mistral-key-0004")
        self.press("Enter")  # Enter in the key box does nothing: Link is a button
        self.press("Tab", "Enter")
        self.idle()
        self.assertEqual(vault.get("MISTRAL_API_KEY"), "e2e-mistral-key-0004")
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


class SetupEmail(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("setup")
        self.page.wait_for_function("() => EM && $('#eProv').options.length")

    def tearDown(self):
        super().tearDown()
        if mailconn.status()["preset"] != "fastmail" or not mailconn.status()["configured"]:  # the seeded mailbox back
            for k in oauth.STATE_KEYS:
                vault.delete(k)
            mailconn.connect("fastmail", "pat.rivera@example.com", "e2e-app-password")

    def status(self):
        return self.page.text_content("#eStatus")

    def connect(self):
        self.page.click("#eConnect")
        self.page.wait_for_function("() => !$('#eConnect').disabled")
        self.idle()

    # --- presets
    def test_presets_switch_the_card_and_the_address_picks_one(self):
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MS_CLIENT_ID"):  # no OAuth client set up yet
            vault.delete(k)
        self.go("board")
        self.go("setup")
        self.page.wait_for_function("() => EM && !EM.clients.google.set")
        self.assertEqual(self.page.input_value("#eProv"), "fastmail")
        self.assertEqual(self.page.input_value("#eUser"), "pat.rivera@example.com")
        self.assertIn("Connected as pat.rivera@example.com (Fastmail) · IMAP imap.fastmail.com:993 · SMTP smtp.fastmail.com:465 ssl",
                      self.status())
        self.page.select_option("#eProv", "gmail")
        self.assertTrue(self.page.is_visible("#eOauth"))
        self.assertEqual(self.page.text_content("#eSignin"), "Sign in with Google")
        self.assertTrue(self.page.is_disabled("#eSignin"))
        self.assertEqual(self.page.get_attribute("#eSignin", "title"), "set up your Google client first (below)")
        self.assertEqual(self.page.text_content("#ePwSum"), "Or use an app password")
        self.assertTrue(self.page.is_visible("#eCsec"))
        self.assertFalse(self.page.is_visible("#eAcct"))
        self.assertEqual(self.page.locator("#eClientSteps li").count(), 7)
        self.page.select_option("#eProv", "outlook")
        self.assertEqual(self.page.text_content("#eSignin"), "Sign in with Microsoft")
        self.assertFalse(self.page.is_visible("#ePw"))  # Microsoft takes no passwords
        self.assertFalse(self.page.is_visible("#eConnect"))
        self.assertTrue(self.page.is_visible("#eAcct"))
        self.assertFalse(self.page.is_visible("#eCsec"))
        self.assertTrue(self.page.is_checked("input[name=eAcct][value=personal]"))
        self.page.select_option("#eProv", "m365")
        self.assertTrue(self.page.is_checked("input[name=eAcct][value=work]"))
        self.page.select_option("#eProv", "yahoo")
        self.assertFalse(self.page.is_visible("#eOauth"))
        self.assertTrue(self.page.is_visible("#eConnect"))
        self.assertEqual(self.page.text_content("#ePwSum"), "App password")
        self.assertEqual(self.page.locator("#eHelp a").text_content(), "Open the app password page")
        self.assertEqual(self.page.input_value("#eImapHost"), "imap.mail.yahoo.com")
        self.page.select_option("#eProv", "proton")
        self.assertTrue(self.page.evaluate("$('#eAdv').open"))  # the Bridge needs its certificate
        self.page.select_option("#eProv", "custom")
        self.assertTrue(self.page.evaluate("$('#eAdv').open"))
        self.assertEqual(self.page.input_value("#eImapHost"), "")
        # the address box picks the preset its domain belongs to
        self.page.fill("#eUser", "someone@icloud.com")
        self.press("Tab")
        self.assertEqual(self.page.input_value("#eProv"), "icloud")
        self.assertEqual(self.page.input_value("#eImapHost"), "imap.mail.me.com")
        self.page.fill("#eUser", "someone@hotmail.com")
        self.press("Tab")
        self.assertEqual(self.page.input_value("#eProv"), "outlook")

    # --- app password: connect, custom servers, test send, disconnect
    def test_connect_bad_input_custom_servers_and_test(self):
        self.allow_console()
        self.page.fill("#eUser", "")
        self.connect()
        self.assertIn("not an email address", self.status())
        self.page.select_option("#eProv", "custom")
        self.page.fill("#eUser", "pat@mail.e2e.example")
        self.page.fill("#ePass", "e2e-custom-password")
        self.connect()
        self.assertIn("imap host is missing or not a host name", self.status())
        self.page.fill("#eImapHost", "imap.mail.e2e.example")
        self.page.fill("#eImapPort", "99999")
        self.page.fill("#eSmtpHost", "smtp.mail.e2e.example")
        self.connect()
        self.assertIn("IMAP port must be between 1 and 65535", self.status())
        self.assertEqual(mailconn.status()["preset"], "fastmail")  # nothing changed
        self.page.fill("#eImapPort", "1993")
        self.page.select_option("#eSmtpMode", "starttls")
        self.assertEqual(self.page.input_value("#eSmtpPort"), "587")  # the port follows the security mode
        self.page.fill("#eSmtpUser", "pat-login")
        FakeMail.CALLS.clear()
        self.connect()
        s = self.status()
        self.assertIn("Connected as pat@mail.e2e.example (Other (custom server)) · IMAP imap.mail.e2e.example:1993 · "
                      "SMTP smtp.mail.e2e.example:587 starttls", s)
        self.assertRegex(s, r"IMAP\s*ok")
        self.assertRegex(s, r"SMTP\s*ok")
        self.assertIn("starttls", FakeMail.CALLS)
        self.assertIn("login", FakeMail.CALLS[FakeMail.CALLS.index("starttls"):])  # STARTTLS before the SMTP password
        st = mailconn.status()
        self.assertEqual((st["preset"], st["smtp_user"], st["verified"]), ("custom", "pat-login", True))
        self.assertEqual(self.page.input_value("#ePass"), "")
        self.assertEqual(vault.get("IMAP_PASS"), "e2e-custom-password")
        self.assertNotIn("e2e-custom-password", self.page.content() + json.dumps(self.api("/api/email/status")))

    def test_a_refused_or_dropped_sign_in_says_what_to_do(self):
        def connect(fail, password="e2e-app-password"):
            self.page.fill("#ePass", password)
            FakeMail.FAIL = fail
            try:
                self.connect()
            finally:
                FakeMail.FAIL = None
            return self.status()

        # a dropped connection is an outage, not a refused password (a reconnect counts only once its own test passes)
        s = connect(imaplib.IMAP4.abort("socket error: EOF"))
        self.assertIn("Saved, but sign-in failed for pat.rivera@example.com (Fastmail)", s)
        self.assertIn("The mail server dropped the connection: test again in a minute.", s)
        self.assertNotIn("Sign-in was refused", s)
        self.assertFalse(mailconn.status()["verified"])
        self.assertEqual(connections.status()["mail"]["status"], "unreachable")
        # a refused password: the app's own advice (never the harness's), and no longer verified
        s = connect(imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials (Failure)"), "wrong-app-password")
        self.assertRegex(s, r"IMAP\s*failed")
        self.assertIn("Sign-in was refused. Use an app password, not your normal password.", s)
        self.assertNotIn("wrong-app-password", s + json.dumps(self.api("/api/email/status")))
        self.assertFalse(mailconn.status()["verified"])
        self.assertEqual(connections.status()["mail"]["status"], "failed")
        # the right password again: verified, and the stored warning is gone
        s = connect(None)
        self.assertRegex(s, r"IMAP\s*ok")
        self.assertTrue(mailconn.status()["verified"])
        self.assertEqual(connections.status()["mail"]["status"], "verified")

    def test_test_send_and_disconnect(self):
        self.allow_console()
        sent = len(FakeMail.SENT)
        self.page.click("#eSend")
        self.expect_toast("test email sent to pat.rivera@example.com: check that inbox", "ok")
        self.idle()
        self.assertEqual(FakeMail.SENT[sent]["To"], "pat.rivera@example.com")
        self.assertEqual(FakeMail.SENT[sent]["Subject"], "Lodestar test email")
        self.answer(False)
        self.page.click("#eOff")
        self.assertIn("Remove the stored app password?", self.dialogs[-1])
        self.idle()
        self.assertTrue(mailconn.status()["configured"])
        self.answer(True)
        self.page.click("#eOff")
        self.expect_toast("email disconnected", "ok")
        self.idle()
        self.assertIn("Not connected (address pat.rivera@example.com saved, no app password or sign-in)", self.status())
        self.assertIsNone(vault.get("IMAP_PASS"))
        self.page.click("#eSend")
        self.page.wait_for_function("() => !$('#eSend').disabled")
        self.idle()
        self.assertIn("email is not connected", self.status())
        self.assertEqual(len(FakeMail.SENT), sent + 1)

    # --- Google: client setup, sign-in through the loopback redirect, sign out
    def test_google_client_signin_and_sign_out(self):
        self.allow_console()
        cid = "123456789-e2eclient.apps.googleusercontent.com"
        self.page.select_option("#eProv", "gmail")
        self.page.fill("#eUser", "pat.rivera@gmail.com")
        save = self.page.get_by_role("button", name="Save client")
        self.page.fill("#eCid", "not-a-client-id")
        save.click()
        self.expect_toast("error: that is not a Google OAuth client ID", "err")
        self.idle()
        self.page.fill("#eCid", cid)
        self.page.fill("#eCsec", "GOCSPX-e2esecret123")
        save.click()
        self.expect_toast("Google client saved: now Sign in with Google", "ok")
        self.idle()
        self.assertEqual([self.page.input_value("#eCid"), self.page.input_value("#eCsec")], ["", ""])
        self.assertTrue(self.page.is_enabled("#eSignin"))
        self.assertEqual(self.page.text_content("#eClientSum"), "Google client set up · Change client")
        self.assertNotIn(cid, self.page.content())
        self.assertNotIn("GOCSPX-e2esecret123", self.page.content())
        posted, real = [], oauth.urlopen

        def token(req, *a, **kw):  # the provider's token and revoke endpoints
            url = getattr(req, "full_url", req)
            posted.append((url, parse_qs((req.data or b"").decode())))
            if "revoke" in url:
                return _resp({})
            claims = {"aud": cid, "iss": "https://accounts.google.com", "exp": time.time() + 3600,
                      "email": "pat.rivera@gmail.com", "email_verified": True}
            idt = "e2e." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".sig"
            return _resp({"access_token": "e2e-access", "refresh_token": "e2e-refresh-google", "expires_in": 3600,
                          "id_token": idt})

        oauth.urlopen = token
        try:
            opened = len(self.opened)
            self.page.click("#eSignin")
            self.page.wait_for_selector("#eWaitLink a")  # the fallback link to the same page
            self.assertIn("Waiting for you to finish signing in in your browser", self.page.text_content("#eWait"))
            href = self.page.get_attribute("#eWaitLink a", "href")
            self.assertEqual(self.opened[opened], ("browser", href))  # the system browser, never this window
            u = urlsplit(href)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            self.assertEqual(u.netloc, "accounts.google.com")
            self.assertEqual((q["client_id"], q["code_challenge_method"], q["login_hint"]), (cid, "S256", "pat.rivera@gmail.com"))
            redirect = urlsplit(q["redirect_uri"])
            self.assertEqual(redirect.hostname, "127.0.0.1")
            c = http.client.HTTPConnection("127.0.0.1", redirect.port, timeout=10)
            c.request("GET", "/?code=wrong-state&state=forged")  # a stray hit does not end the sign-in
            self.assertEqual(c.getresponse().status, 400)
            c.close()
            c = http.client.HTTPConnection("127.0.0.1", redirect.port, timeout=10)
            c.request("GET", f"/?code=e2e-code&state={q['state']}")
            r = c.getresponse()
            self.assertIn("Signed in", r.read().decode())
            c.close()
            self.page.wait_for_function("() => $('#eWait').innerHTML === '' && !$('#eSignin').disabled")
            self.idle()
            s = self.status()
            self.assertIn("Signed in with Google as pat.rivera@gmail.com (Gmail, OAuth)", s)
            self.assertRegex(s, r"IMAP\s*ok")
            url, form = posted[0]
            self.assertEqual(url, "https://oauth2.googleapis.com/token")
            self.assertEqual((form["code"], form["client_id"], form["client_secret"]),
                             (["e2e-code"], [cid], ["GOCSPX-e2esecret123"]))
            self.assertTrue(form["code_verifier"][0])
            self.assertEqual(vault.get("OAUTH_REFRESH"), "e2e-refresh-google")
            self.assertNotIn("e2e-refresh-google", self.page.content() + json.dumps(self.api("/api/email/status")))
            self.go("board")
            self.go("setup")
            self.page.wait_for_function("() => $('#eProv').value === 'gmail'")
            self.assertFalse(self.page.evaluate("$('#ePw').open"))  # signed in: the password route folds away
            self.assertEqual(self.page.input_value("#eUser"), "pat.rivera@gmail.com")
            # sign out: asks, revokes at Google, keeps the client
            self.answer(True)
            self.page.click("#eOff")
            self.idle()
            self.assertIn("Sign out and revoke Lodestar's access to pat.rivera@gmail.com?", self.dialogs[-1])
            self.assertEqual(posted[-1][0], "https://oauth2.googleapis.com/revoke")
            self.assertIn("Not connected", self.status())
            self.assertIsNone(vault.get("OAUTH_REFRESH"))
            self.assertTrue(vault.get("GOOGLE_CLIENT_ID"))
        finally:
            oauth.urlopen = real
            oauth.cancel("test over")

    def test_microsoft_client_and_cancelled_signin(self):
        self.allow_console()
        self.page.select_option("#eProv", "outlook")
        self.assertTrue(self.page.is_disabled("#eSignin"))
        save = self.page.get_by_role("button", name="Save client")
        self.page.fill("#eCid", "123456789-e2eclient.apps.googleusercontent.com")
        save.click()
        self.expect_toast("error: that is not a Microsoft Application (client) ID", "err")
        self.idle()
        self.page.fill("#eCid", "1b2c3d4e-0000-4abc-8def-0123456789ab")
        save.click()
        self.expect_toast("Microsoft client saved: now Sign in with Microsoft", "ok")
        self.idle()
        self.page.check("input[name=eAcct][value=work]")
        self.page.click("#eSignin")
        self.page.wait_for_selector("#eWaitLink a")
        href = self.page.get_attribute("#eWaitLink a", "href")
        self.assertTrue(href.startswith("https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?"), href)
        self.assertEqual(urlsplit(parse_qs(urlsplit(href).query)["redirect_uri"][0]).hostname, "localhost")
        self.page.locator("#eWait").get_by_role("button", name="Cancel").click()
        self.page.wait_for_function("() => $('#eWait').innerHTML === '' && !$('#eSignin').disabled")
        self.idle()
        self.assertIn("Sign-in cancelled: you cancelled it.", self.status())
        self.assertEqual(mailconn.status()["preset"], "fastmail")  # the mailbox you had stays connected

    def test_keyboard_and_420px(self):
        self.page.focus("#eProv")
        self.press("Tab")
        self.assertEqual(self.page.evaluate("document.activeElement.id"), "eUser")
        self.page.click("#eAdv summary")
        self.page.select_option("#eProv", "gmail")
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


class Tools(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.go("tools")

    def tool(self, name):
        return next(t for t in self.state()["tools"] if t["tool"] == name)

    def pref_row(self, key):
        i = self.page.evaluate("k => PK.indexOf(k)", key)
        return self.page.locator(f"#prefs .row:has(#pl{i})")

    def test_tool_switches(self):
        self.addCleanup(settings.set_tool, "posting_check", True, False)
        enabled = self.page.get_by_label("posting_check enabled")
        auto = self.page.get_by_label("posting_check auto")
        self.assertTrue(enabled.is_checked())
        self.assertFalse(auto.is_checked())
        auto.check()
        self.idle()
        self.assertTrue(self.tool("posting_check")["auto"])
        enabled.uncheck()
        self.idle()
        self.assertFalse(self.tool("posting_check")["enabled"])
        self.assertFalse(self.page.get_by_label("posting_check enabled").is_checked())  # re-rendered from the server

    def test_preferences_every_kind_and_bad_values(self):
        self.allow_console()
        prefs = settings.load()["prefs"]
        self.addCleanup(lambda: [settings.set_pref(k, prefs[k]) for k in ("followup_days", "resume_style", "excluded_companies")])
        days = self.pref_row("followup_days").locator("input")
        self.assertEqual(days.get_attribute("aria-labelledby"), self.pref_row("followup_days").locator("span[id]").first.get_attribute("id"))
        days.fill("abc")
        self.press("Tab")
        self.expect_toast("error: followup_days must be a whole number", "err")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["followup_days"], prefs["followup_days"])
        days = self.pref_row("followup_days").locator("input")
        days.fill("9")
        self.press("Tab")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["followup_days"], 9)
        style = self.pref_row("resume_style").locator("select")
        choice = next(c for c in self.state()["pref_choices"]["resume_style"] if c != prefs["resume_style"])
        style.select_option(choice)
        self.idle()
        self.assertEqual(settings.load()["prefs"]["resume_style"], choice)
        box = self.pref_row("desktop_notifications").locator("input[type=checkbox]")
        box.check()
        self.idle()
        self.assertTrue(settings.load()["prefs"]["desktop_notifications"])
        self.pref_row("desktop_notifications").locator("input[type=checkbox]").uncheck()
        self.idle()
        goals = self.pref_row("weekly_goals").locator("input")
        self.assertIn("none set", self.pref_row("weekly_goals").text_content())
        goals.fill("contacts=5")
        self.press("Tab")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["weekly_goals"], {"contacts": 5})
        self.assertIn("contacts=5", self.pref_row("weekly_goals").text_content())
        self.pref_row("weekly_goals").locator("input").fill("contacts=0")
        self.press("Tab")
        self.idle()
        self.assertEqual(settings.load()["prefs"]["weekly_goals"], {})
        ex = self.pref_row("excluded_companies").locator("input")
        ex.fill("Quarry Games, Zephyr AI")
        self.press("Tab")
        self.idle()
        self.assertIn("Zephyr AI", str(settings.load()["prefs"]["excluded_companies"]))

    def test_420px(self):
        self.set_viewport(420)
        self.settle()
        self.assertEqual(self.overflow(), [])


if __name__ == "__main__":
    unittest.main()
