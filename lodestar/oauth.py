"""Sign in to Google or Microsoft mail in the system browser (authorization code + PKCE, loopback redirect), keep only
the refresh token (keyring vault), mint short-lived access tokens in memory, and speak XOAUTH2 to IMAP and SMTP.
Every 2-step method the account has (authenticator app, SMS or voice code, phone prompt, passkey, security key, backup
codes) runs on the provider's own page; Lodestar never sees a password or a code.

The user brings their own OAuth client (docs/CONNECT.md): GOOGLE_CLIENT_ID (+ GOOGLE_CLIENT_SECRET, which Google treats
as non-confidential for Desktop apps) or MS_CLIENT_ID (a public client: no secret). Access tokens never touch disk."""
import base64
import hashlib
import http.server
import imaplib
import json
import re
import secrets
import smtplib
import socket
import socketserver
import threading
import time
import urllib.error
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from . import vault
from .config import setting

PROVIDERS = {
    "google": {"label": "Google", "auth": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token", "revoke": "https://oauth2.googleapis.com/revoke",
               "scope": "openid email https://mail.google.com/", "params": {"access_type": "offline", "prompt": "consent"},
               "redirect": "http://127.0.0.1:{port}/", "client": "GOOGLE_CLIENT_ID", "secret": "GOOGLE_CLIENT_SECRET",
               "issuers": ("https://accounts.google.com", "accounts.google.com"),
               "client_re": r"[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com"},
    "microsoft": {"label": "Microsoft", "auth": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", "revoke": None,
                  "scope": "openid profile email offline_access https://outlook.office.com/IMAP.AccessAsUser.All "
                           "https://outlook.office.com/SMTP.Send",
                  # the portal registers http://localhost (port ignored when matching); it refuses http 127.0.0.1
                  "params": {"prompt": "select_account"}, "redirect": "http://localhost:{port}",
                  "client": "MS_CLIENT_ID", "secret": None,
                  "client_re": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"},
}
LABELS = {"google": "Google (Gmail)", "microsoft": "Microsoft (Outlook.com, Hotmail, Live, Microsoft 365)"}
TENANT = {"personal": "consumers", "work": "organizations"}
MSA_TID = "9188040d-6c67-4c5b-b112-36a304b66dad"  # the personal-account tenant id in Microsoft ID tokens
CLIENT_KEYS = {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MS_CLIENT_ID"}  # kept across Disconnect
STATE_KEYS = ("OAUTH_REFRESH", "OAUTH_PROVIDER", "OAUTH_ACCOUNT", "OAUTH_REFRESH_EXPIRES", "OAUTH_NEEDS_SIGNIN", "EMAIL_AUTH")
SIGNIN_TIMEOUT = 300
MS_PERMISSIONS = ("Also remove Lodestar from your account's app permissions (https://account.live.com/consent/Manage for "
                  "personal accounts, https://myapps.microsoft.com for work accounts).")
HINTS = {  # matched by substring of the provider's error or error_description
    "redirect_uri_mismatch": "Your Google client is not a Desktop app client. Create a Desktop app OAuth client "
                             "(docs/CONNECT.md step 4).",
    "access_denied": "Access was not granted. If Google said the app is blocked or 'Access blocked: app has not completed "
                     "the Google verification process', add your address as a test user or publish the app "
                     "(docs/CONNECT.md step 6).",
    "invalid_client": "The client ID or secret is wrong: paste them again from Google Cloud > Clients (or the Microsoft "
                      "app registration's Application (client) ID).",
    "client_secret is missing": "Google wants the client secret too: Setup > Connect email > Set up client, paste it.",
    "org_internal": "Your Google Workspace admin does not allow this app. Ask them, or use an app password if allowed.",
    "admin_policy_enforced": "Your Google Workspace admin does not allow this app. Ask them, or use an app password if "
                             "allowed.",
    "AADSTS50011": "Add the redirect URI http://localhost under Authentication > Mobile and desktop applications.",
    "AADSTS700016": "The application ID is wrong, or the app does not allow this account type: set Supported account "
                    "types to 'Any Entra ID Tenant + Personal Microsoft accounts'.",
    "unauthorized_client": "The application ID is wrong, or the app does not allow this account type: set Supported "
                           "account types to 'Any Entra ID Tenant + Personal Microsoft accounts'.",
    "AADSTS65001": "Your organization requires an admin to approve the app. Ask your admin, or use another account.",
    "consent_required": "Your organization requires an admin to approve the app. Ask your admin, or use another account.",
    "AADSTS7000218": "Turn on 'Allow public client flows' under Authentication > Advanced settings.",
}
EXPIRED = ("invalid_grant", "interaction_required", "AADSTS50076", "AADSTS50079")  # sign in again

PENDING: dict = {}  # {"provider", "url", "started"} while a sign-in waits (GET /api/email/signin: the fallback link)
_TOKEN: dict = {}  # {"token", "exp", "provider"}: the access token, memory only
_LOCK = threading.Lock()  # one refresh at a time (the loop, a UI test and a send can ask at once)
_SIGNIN_LOCK = threading.Lock()
_CURRENT: dict | None = None  # the waiting sign-in's state; a second sign-in cancels it


class Transient(ConnectionError):
    """The token endpoint could not be reached or answered 5xx/429: retry later (never un-verifies the mailbox)."""


class _Refused(Exception):
    def __init__(self, code: int, body: dict):
        self.code = code
        self.error = str(body.get("error") or f"HTTP {code}")[:80]
        self.desc = _clean(body.get("error_description") or "")


def _clean(s, n: int = 200) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(s or ""))[:n]


def _post(url: str, data: dict, timeout: int = 30) -> dict:
    req = Request(url, urlencode(data).encode(), {"Content-Type": "application/x-www-form-urlencoded",
                                                   "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:  # before URLError: HTTPError is one
        try:
            body = json.loads(e.read(4000) or b"{}")
        except Exception:
            body = {}
        finally:
            e.close()
        if e.code >= 500 or e.code == 429:
            raise Transient(f"{urlsplit(url).hostname} answered HTTP {e.code}; will retry") from None
        raise _Refused(e.code, body if isinstance(body, dict) else {}) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise Transient(f"couldn't reach {urlsplit(url).hostname}; will retry") from None


def _hint(error: str, desc: str) -> str:
    return next((h for k, h in HINTS.items() if k.lower() in f"{error} {desc}".lower()), "")


def needs_text(provider: str | None = None) -> str:
    provider = provider or vault.get("OAUTH_PROVIDER") or "google"
    label = PROVIDERS.get(provider, PROVIDERS["google"])["label"]
    return (f"Your {label} sign-in has expired or was revoked. Sign in again: Setup > Connect email > Sign in with "
            f"{label} (lodestar email signin {provider}).")


# ----------------------------------------------------------------------------- client
def set_client(provider: str, client_id: str, client_secret: str | None = None) -> dict:
    """Store the user's own OAuth client. The Google secret is optional (Desktop clients may omit it) but sent when
    stored; a new client ID drops the old client's secret."""
    p = _provider(provider)
    cid, sec = "".join(str(client_id or "").split()), "".join(str(client_secret or "").split())
    if not re.fullmatch(p["client_re"], cid):
        raise SystemExit("that is not a Google OAuth client ID (it ends in .apps.googleusercontent.com)" if provider == "google"
                         else "that is not a Microsoft Application (client) ID (a GUID like 1b2c3d4e-...)")
    if sec and not p["secret"]:
        raise SystemExit("Microsoft sign-in uses a public client: there is no secret to paste")
    if sec and not re.fullmatch(r"[A-Za-z0-9_\-]{8,200}", sec):
        raise SystemExit("that does not look like a Google client secret (it starts with GOCSPX-)")
    if p["secret"] and (sec or vault.get(p["client"]) != cid):
        vault.delete(p["secret"])  # a secret belongs to its own client
    vault.set(p["client"], cid)
    if sec:
        vault.set(p["secret"], sec)
    return client_status()


def client_status() -> dict:
    """{"google": {"set": bool}, "microsoft": {"set": bool}}: never the values."""
    return {n: {"set": bool(setting(p["client"]))} for n, p in PROVIDERS.items()}


def _provider(provider: str) -> dict:
    if provider not in PROVIDERS:
        raise SystemExit(f"sign-in is for google or microsoft, not '{str(provider)[:40]}'")
    return PROVIDERS[provider]


# ----------------------------------------------------------------------------- sign-in
def pkce() -> tuple[str, str]:
    """(verifier, S256 challenge): RFC 7636, verifier 86 unreserved characters."""
    verifier = secrets.token_urlsafe(64)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def auth_url(provider: str, port: int, state: str, challenge: str, account: str = "personal",
             login_hint: str = "") -> tuple[str, str]:
    """(the provider's sign-in URL, the redirect URI). The URL carries no secret: client id, challenge, state, redirect."""
    p = _provider(provider)
    redirect = p["redirect"].format(port=port)
    q = {"client_id": setting(p["client"]) or "", "response_type": "code", "redirect_uri": redirect, "scope": p["scope"],
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256"} | p["params"]
    if login_hint:
        q["login_hint"] = login_hint
    return p["auth"].format(tenant=TENANT.get(account, "consumers")) + "?" + urlencode(q), redirect


class _Listener(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False  # server_close must not wait for a browser's idle preconnect socket (up to 10 s)
    allow_reuse_address = False  # Windows SO_REUSEADDR would let another local socket co-bind the port
    server_bind = socketserver.TCPServer.server_bind  # skips HTTPServer's getfqdn, which can stall on Windows


class _Listener6(_Listener):
    address_family = socket.AF_INET6


PAGES = {"ok": "Signed in. You can close this tab and go back to Lodestar.",
         "refused": "Sign-in was cancelled or refused. Go back to Lodestar for the next step.",
         "stray": "This sign-in link is not the one Lodestar started.",
         "done": "This sign-in has already finished. You can close this tab."}


def _handler(state: str, st: dict):
    class Callback(http.server.BaseHTTPRequestHandler):
        timeout = 10  # browsers open idle preconnect sockets; one must not hold a handler thread for ever

        def log_message(self, *a):  # the query holds the code
            pass

        def _page(self, code: int, key: str) -> None:
            body = (f"<!doctype html><meta charset='utf-8'><title>Lodestar sign-in</title>"
                    f"<p style='font:16px system-ui;margin:3em'>{PAGES[key]}</p>").encode()  # fixed text, nothing reflected
            self.send_response(code)
            for h, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))),
                         ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")):
                self.send_header(h, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            port = self.server.server_address[1]
            if (self.headers.get("Host") or "").lower() not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                return self._page(400, "stray")  # a DNS-rebinding page cannot drive it
            u = urlsplit(self.path)
            if u.path != "/":
                return self._page(404, "stray")
            q = parse_qs(u.query)
            got = (q.get("state") or [""])[0]
            # state first, before error or code: a forged ?error= cannot end the flow
            if not secrets.compare_digest(got.encode(), state.encode()):
                return self._page(400, "stray")
            with st["lock"]:
                if st["done"].is_set():
                    return self._page(200, "done")
                if q.get("error"):
                    st["error"], st["desc"] = _clean(q["error"][0], 80), _clean((q.get("error_description") or [""])[0])
                elif q.get("code"):
                    st["code"] = q["code"][0]
                else:
                    return self._page(400, "stray")
                st["done"].set()
            self._page(200, "refused" if st.get("error") else "ok")

        def _no(self):
            self.send_error(405)

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    return Callback


def cancel(reason: str = "you cancelled it") -> bool:
    """Stop a waiting sign-in (POST /api/email/signin_cancel, or a second sign-in)."""
    with _SIGNIN_LOCK:
        cur = _CURRENT
    if not cur:
        return False
    with cur["lock"]:
        cur.setdefault("cancelled", reason)
        cur["done"].set()
    return True


def signin(provider: str, account: str = "personal", login_hint: str = "", open_browser=None,
           timeout: float = SIGNIN_TIMEOUT) -> dict:
    """Sign in on the provider's page in the system browser and connect that mailbox. Blocks until the browser comes
    back, the user cancels, or `timeout` seconds pass."""
    global _CURRENT
    from . import mailconn
    from .contacts import EMAIL_RE

    p = _provider(provider)
    label = p["label"]
    cid = setting(p["client"])
    if not cid:
        raise SystemExit(f"Set up your {label} client first: Setup > Connect email > Sign in with {label} > Set up "
                         f"client (lodestar email client {provider}; docs/CONNECT.md)")
    if account not in TENANT:
        raise SystemExit("account is personal or work")
    hint = str(login_hint or "").strip()
    hint = hint if EMAIL_RE.fullmatch(hint) else ""
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(24)
    st = {"done": threading.Event(), "lock": threading.Lock()}
    cancel("a new sign-in started")
    with _SIGNIN_LOCK:
        _CURRENT = st
    made, running = [], []
    try:
        made.append(_Listener(("127.0.0.1", 0), _handler(state, st)))
        port = made[0].server_address[1]
        if provider == "microsoft":  # browsers may try localhost over IPv6 first
            try:
                made.append(_Listener6(("::1", port), _handler(state, st)))
            except OSError:
                pass
        for s in made:
            threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True,
                             name="lodestar-oauth").start()
            running.append(s)
        url, redirect = auth_url(provider, port, state, challenge, account, hint)
        PENDING.clear()
        PENDING.update(provider=provider, url=url, started=time.time())
        try:
            (open_browser or webbrowser.open)(url)  # the system browser, never the app window (RFC 8252; Google refuses embedded views)
        except Exception:  # ponytail: the CLI prints the URL and the UI shows it as a link
            pass
        if not st["done"].wait(timeout):
            raise SystemExit("Sign-in timed out" + (f" after {round(timeout / 60)} minutes" if timeout >= 60 else "")
                             + ". Click Sign in again.")
    finally:
        for s in made:
            if s in running:  # shutdown() waits for serve_forever, so only on a listener that runs
                s.shutdown()
            s.server_close()
        with _SIGNIN_LOCK:
            if _CURRENT is st:
                _CURRENT = None
                PENDING.clear()
    if st.get("cancelled"):
        raise SystemExit(f"Sign-in cancelled: {st['cancelled']}.")
    if st.get("error"):
        raise SystemExit(f"{label} refused the sign-in: {st['error']}. " + (_hint(st["error"], st.get("desc", ""))
                                                                          or st.get("desc", "")))
    code = st["code"]
    secret = setting(p["secret"]) if p["secret"] else None
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": cid,
            "code_verifier": verifier} | ({"client_secret": secret} if secret else {})
    try:
        tok = _post(p["token"].format(tenant=TENANT[account]), data)
    except _Refused as e:
        raise SystemExit(_redact(f"{label} refused the sign-in: {e.error}: " + (_hint(e.error, e.desc) or e.desc),
                                 code, verifier, secret)) from None
    except Transient as e:
        raise SystemExit(f"Could not finish the sign-in: {e}. Click Sign in again.") from None
    address, account = _identity(provider, tok.get("id_token"), cid, account)
    refresh = str(tok.get("refresh_token") or "")
    if not refresh:
        raise SystemExit("Google did not return a refresh token: remove Lodestar under https://myaccount.google.com/connections "
                         "and sign in again." if provider == "google" else
                         "Microsoft did not return a refresh token (offline_access was not granted): sign in again and "
                         "accept every permission.")
    vault.set("OAUTH_REFRESH", refresh, address)
    vault.set("OAUTH_PROVIDER", provider)
    if provider == "microsoft":
        vault.set("OAUTH_ACCOUNT", account)
    else:
        vault.delete("OAUTH_ACCOUNT")
    vault.set("EMAIL_AUTH", "oauth")
    out = {"signed_in_as": address}
    if tok.get("refresh_token_expires_in"):  # Google: the app is in Testing (7-day refresh tokens)
        when = datetime.now(timezone.utc) + timedelta(seconds=int(tok["refresh_token_expires_in"]))
        vault.set("OAUTH_REFRESH_EXPIRES", when.strftime("%Y-%m-%d %H:%M:%S"))
        out["expires_warning"] = ("Your Google app is in Testing: this sign-in stops working in 7 days. Publish the app "
                                  "(docs/CONNECT.md, step 6) and sign in again.")
    else:
        vault.delete("OAUTH_REFRESH_EXPIRES")
    vault.delete("OAUTH_NEEDS_SIGNIN")
    vault.delete("IMAP_PASS")  # one way to sign in at a time
    if tok.get("access_token"):
        with _LOCK:
            _TOKEN.clear()
            _TOKEN.update(token=tok["access_token"], exp=time.time() + int(tok.get("expires_in") or 3600), provider=provider)
    preset = "gmail" if provider == "google" else ("outlook" if account == "personal" else "m365")
    return mailconn.connect_oauth(preset, address) | out


def _identity(provider: str, id_token, client_id: str, account: str) -> tuple[str, str]:
    """(mailbox address, account type) from the ID token. The signature is not checked: the token came straight from
    the token endpoint over verified TLS (OpenID Connect Core 3.1.3.7, item 6). It only names the address; trust in
    the mailbox comes from the IMAP/SMTP test passing."""
    from .contacts import EMAIL_RE

    try:
        part = str(id_token).split(".")[1]
        c = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        if not isinstance(c, dict):
            raise ValueError
    except Exception:
        raise SystemExit("the sign-in answer carried no readable ID token: sign in again") from None
    aud = c.get("aud")
    if client_id not in (aud if isinstance(aud, list) else [aud]):
        raise SystemExit("the sign-in answer was meant for another app (audience mismatch): sign in again")
    iss = str(c.get("iss") or "")
    if not (iss in PROVIDERS["google"]["issuers"] if provider == "google"
            else iss.startswith("https://login.microsoftonline.com/") and iss.endswith("/v2.0")):
        raise SystemExit("the sign-in answer came from an unexpected issuer: sign in again")
    try:
        if float(c.get("exp") or 0) <= time.time():
            raise ValueError
    except (TypeError, ValueError):
        raise SystemExit("the sign-in answer has expired: check this computer's clock, then sign in again") from None
    if provider == "google":
        address = str(c.get("email") or "").strip()
        if not (address and c.get("email_verified") in (True, "true") and EMAIL_RE.fullmatch(address)):
            raise SystemExit("Google did not confirm this account's address: sign in with a Gmail or Google Workspace account")
        return address, "personal"
    address = str(c.get("email") or c.get("preferred_username") or "").strip()
    if not EMAIL_RE.fullmatch(address):
        raise SystemExit("your Microsoft account has no mailbox address in the sign-in; use the app-password route or "
                         "contact your admin")
    return address, "personal" if c.get("tid") == MSA_TID else "work"  # the account itself decides the SMTP host


def _redact(text: str, *secrets_) -> str:
    from .connections import redact

    return redact(text, *secrets_)


# ----------------------------------------------------------------------------- tokens
def access_token(force: bool = False) -> str:
    """A live access token: cached in memory until 60 s before expiry, else minted from the stored refresh token."""
    with _LOCK:
        provider = vault.get("OAUTH_PROVIDER") or ""
        p = _provider(provider) if provider in PROVIDERS else None
        if p is None or vault.get("OAUTH_NEEDS_SIGNIN"):
            _TOKEN.clear()
            raise SystemExit(needs_text(provider if p else None))
        if not force and _TOKEN.get("provider") == provider and _TOKEN.get("exp", 0) - 60 > time.time():
            return _TOKEN["token"]
        refresh = vault.get("OAUTH_REFRESH")
        if not refresh:
            _expired(provider, "no refresh token stored")
        account = vault.get("OAUTH_ACCOUNT") or "personal"
        secret = setting(p["secret"]) if p["secret"] else None
        data = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": setting(p["client"]) or ""}
        if secret:
            data["client_secret"] = secret
        if provider == "microsoft":
            data["scope"] = p["scope"]
        url = p["token"].format(tenant=TENANT.get(account, "consumers"))
        for attempt in (1, 2):
            try:
                tok = _post(url, data)
                break
            except _Refused as e:
                if any(x.lower() in f"{e.error} {e.desc}".lower() for x in EXPIRED):
                    again = vault.get("OAUTH_REFRESH")  # another process (the desktop app, a scheduled run) may have
                    if attempt == 1 and again and again != data["refresh_token"]:  # just rotated it (Microsoft does)
                        data["refresh_token"] = again
                        continue
                    _expired(provider, _redact(f"{e.error}: {e.desc}", data["refresh_token"], secret))
                raise SystemExit(_redact(f"{p['label']} refused the token refresh: {e.error}. "
                                         + (_hint(e.error, e.desc) or e.desc), data["refresh_token"], secret)) from None
        access = str(tok.get("access_token") or "")
        if not access:
            raise Transient(f"{p['label']} answered without an access token; will retry")
        if tok.get("refresh_token") and tok["refresh_token"] != data["refresh_token"]:  # rotated (Microsoft, every use)
            vault.set("OAUTH_REFRESH", tok["refresh_token"], vault.user("OAUTH_REFRESH"))
        _TOKEN.clear()
        _TOKEN.update(token=access, exp=time.time() + int(tok.get("expires_in") or 3600), provider=provider)
        return access


def _expired(provider: str, reason: str):
    vault.set("OAUTH_NEEDS_SIGNIN", _clean(reason, 120) or "refused")
    vault.delete("EMAIL_VERIFIED")
    _TOKEN.clear()
    raise SystemExit(needs_text(provider)) from None


# ----------------------------------------------------------------------------- XOAUTH2
def xoauth2(user: str, token: str) -> str:
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def imap_auth(box, user: str) -> None:
    def once(token):
        sent = []

        def mech(challenge):  # imaplib base64-encodes what we return
            if sent:  # a second call is the server's error challenge: SASL wants an empty answer
                return b""
            sent.append(1)
            return xoauth2(user, token).encode()

        box.authenticate("XOAUTH2", mech)

    try:
        once(access_token())
    except imaplib.IMAP4.error:  # a stale cached token: refresh once and retry on the same connection
        once(access_token(force=True))


def smtp_auth(s, user: str) -> None:
    s.ehlo_or_helo_if_needed()  # SMTP.auth does not (only login does), and STARTTLS reset the EHLO state

    def once(token):
        s.auth("XOAUTH2", lambda challenge=None: "" if challenge is not None else xoauth2(user, token),
               initial_response_ok=True)

    try:
        once(access_token())
    except smtplib.SMTPAuthenticationError:
        once(access_token(force=True))


def disconnect() -> dict:
    """Forget the sign-in: Google revokes the refresh token (best effort); Microsoft has no revoke for this flow, so the
    answer says where to remove the app. Client IDs, the address and the servers stay."""
    provider, refresh, out = vault.get("OAUTH_PROVIDER") or "", vault.get("OAUTH_REFRESH"), {}
    p = PROVIDERS.get(provider)
    if p and p["revoke"] and refresh:
        try:
            _post(p["revoke"], {"token": refresh}, timeout=15)
            out["revoked"] = True
        except (_Refused, Transient):
            out["note"] = ("Could not revoke the sign-in at Google; remove Lodestar at "
                           "https://myaccount.google.com/connections to be sure.")
    elif provider == "microsoft":
        out["note"] = MS_PERMISSIONS
    for n in (*STATE_KEYS, "EMAIL_VERIFIED"):
        vault.delete(n)
    with _LOCK:
        _TOKEN.clear()
    return out
