"""Connect your mailbox: provider presets, the stored connection, and a login check for IMAP and SMTP.

Everything is kept in the keyring vault and read back through config.setting (an env var or .env line still wins):
EMAIL_PRESET, IMAP_USER, IMAP_HOST, IMAP_PORT, IMAP_MODE, SMTP_HOST, SMTP_PORT, SMTP_MODE, SMTP_USER, MAIL_CAFILE. Two ways to sign
in, one at a time (EMAIL_AUTH): an app password (IMAP_PASS) or a Google / Microsoft sign-in (oauth.py: OAUTH_REFRESH).
Those two are the only secrets and no function here returns either.
"""
import imaplib
import os
import re
import smtplib
import socket
import ssl
from datetime import datetime, timedelta

from . import util, vault
from .config import setting
from .contacts import EMAIL_RE

# ponytail: host/port presets for the common providers; anything else is "custom". "oauth": Sign in with that provider
# works (every 2-step method runs on its page); "oauth_only": no password route (Microsoft refuses app passwords).
PRESETS = {
    "gmail": {"label": "Gmail", "oauth": "google", "imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com",
              "smtp_port": 465, "smtp_mode": "ssl", "domains": ["gmail.com", "googlemail.com"],
              "help": "https://myaccount.google.com/apppasswords",
              "steps": "Turn on 2-Step Verification for your Google account, then create an app password at the link "
                       "and paste its 16 letters here."},
    "yahoo": {"label": "Yahoo Mail", "imap_host": "imap.mail.yahoo.com", "imap_port": 993,
              "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_mode": "ssl",
              "domains": ["yahoo.com", "ymail.com", "rocketmail.com"], "help": "https://login.yahoo.com/account/security",
              "steps": "Yahoo Account Security > Generate app password, then paste it here."},
    "icloud": {"label": "iCloud Mail", "imap_host": "imap.mail.me.com", "imap_port": 993,
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_mode": "starttls",
               "domains": ["icloud.com", "me.com", "mac.com"], "help": "https://account.apple.com",
               "steps": "Apple Account > Sign-In and Security > App-Specific Passwords (needs two-factor "
                        "authentication), then paste it here."},
    "fastmail": {"label": "Fastmail", "imap_host": "imap.fastmail.com", "imap_port": 993,
                 "smtp_host": "smtp.fastmail.com", "smtp_port": 465, "smtp_mode": "ssl",
                 "domains": ["fastmail.com", "fastmail.fm"],
                 "help": "https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords",
                 "steps": "Settings > Privacy & Security > Manage app passwords > New app password (IMAP and SMTP)."},
    "zoho": {"label": "Zoho Mail", "imap_host": "imap.zoho.com", "imap_port": 993, "smtp_host": "smtp.zoho.com",
             "smtp_port": 465, "smtp_mode": "ssl", "domains": ["zoho.com", "zohomail.com"],
             "help": "https://accounts.zoho.com/home#security/app_password",
             "steps": "Turn on IMAP access in Zoho Mail settings, then Zoho Accounts > Security > App Passwords. "
                      "Organisation or EU accounts use other hosts (imappro.zoho.com, imap.zoho.eu): pick Custom."},
    "aol": {"label": "AOL Mail", "imap_host": "imap.aol.com", "imap_port": 993, "smtp_host": "smtp.aol.com",
            "smtp_port": 465, "smtp_mode": "ssl", "domains": ["aol.com"], "help": "https://login.aol.com/account/security",
            "steps": "AOL Account Security > Generate app password, then paste it here."},
    "outlook": {"label": "Outlook.com / Hotmail / Live", "oauth": "microsoft", "oauth_only": True,
                "imap_host": "outlook.office365.com", "imap_port": 993, "smtp_host": "smtp-mail.outlook.com",
                "smtp_port": 587, "smtp_mode": "starttls", "domains": ["outlook.com", "hotmail.com", "live.com", "msn.com"],
                "help": "https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com",
                "steps": "Turn on IMAP in Outlook.com (Settings > Mail > Forwarding and IMAP), then Sign in with Microsoft."},
    "m365": {"label": "Microsoft 365 (work or school)", "oauth": "microsoft", "oauth_only": True,
             "imap_host": "outlook.office365.com", "imap_port": 993, "smtp_host": "smtp.office365.com", "smtp_port": 587,
             "smtp_mode": "starttls", "domains": [],
             "help": "https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission",
             "steps": "Sign in with Microsoft (work account). Your organization may have SMTP AUTH turned off: then ask "
                      "your admin to allow SMTP AUTH for your mailbox, or Lodestar can read mail but not send it."},
    "proton": {"label": "Proton Mail (via Bridge)", "imap_host": "127.0.0.1", "imap_port": 1143, "imap_mode": "starttls",
               "smtp_host": "127.0.0.1",
               "smtp_port": 1025, "smtp_mode": "starttls", "domains": ["proton.me", "protonmail.com", "pm.me"],
               "help": "https://proton.me/mail/bridge", "cert": True,
               "steps": "Install Proton Mail Bridge (paid plans) and sign in there (your 2-step check happens in Bridge). "
                        "Export Bridge's TLS certificate (Settings > Advanced > Export TLS certificates) and give its path "
                        "under Advanced (certificate file), then use the Bridge password it shows, not your Proton "
                        "password. Not yet tested with a real Bridge."},
    "custom": {"label": "Other (custom server)", "imap_port": 993, "smtp_port": 465, "smtp_mode": "ssl", "domains": [],
               "steps": "Enter your provider's IMAP and SMTP servers under Advanced. Use an app password if it offers one."},
}
KEYS = {"imap_host": "IMAP_HOST", "imap_port": "IMAP_PORT", "imap_mode": "IMAP_MODE", "smtp_host": "SMTP_HOST", "smtp_port": "SMTP_PORT",
        "smtp_mode": "SMTP_MODE", "smtp_user": "SMTP_USER", "cafile": "MAIL_CAFILE"}
# Connect email owns these vault entries (hidden from the generic Vault list, like oauth.CLIENT_KEYS)
MANAGED = {"EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", "EMAIL_VERIFIED", "EMAIL_AUTH", "OAUTH_PROVIDER", "OAUTH_ACCOUNT",
           "OAUTH_REFRESH", "OAUTH_REFRESH_EXPIRES", "OAUTH_NEEDS_SIGNIN", *KEYS.values()}
HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def _login(c: dict) -> tuple[str | None, bool]:
    """(app password, a login is stored) for the stored connection c; the password is None with a provider sign-in."""
    oauth = c.get("auth") == "oauth"
    pw = None if oauth else setting("IMAP_PASS")
    return pw, bool(c["user"] and (pw or (oauth and vault.get("OAUTH_REFRESH"))))


def guess(user: str) -> str:
    """Preset for an address's domain ('' when unknown)."""
    dom = user.rpartition("@")[2].strip().lower()
    return next((k for k, p in PRESETS.items() if dom in p["domains"]), "")


def status() -> dict:
    """The stored connection without the password: configured?, preset, address, servers, env vars that override it."""
    from . import oauth

    c = util.mail_settings()
    p = PRESETS.get(c["preset"], {})
    configured = _login(c)[1]
    prov = (vault.get("OAUTH_PROVIDER") or "") if c.get("auth") == "oauth" else ""
    return c | {"configured": configured, "verified": configured and vault.get("EMAIL_VERIFIED") == _fingerprint(c),
                "label": p.get("label", c["preset"]), "oauth_provider": prov,
                "needs_signin": (vault.get("OAUTH_NEEDS_SIGNIN") or "") if prov else "",
                "refresh_expires": (vault.get("OAUTH_REFRESH_EXPIRES") or "") if prov else "",
                "clients": oauth.client_status(),
                "shadowed": [k for k in ("IMAP_USER", "IMAP_PASS", *KEYS.values()) if os.environ.get(k)],
                "conflicts": conflicts(c)}


def conflicts(c: dict) -> list[str]:
    """A server in the environment or .env that differs from the one Connect email chose (a stray IMAP_HOST line makes a
    Yahoo connection log in to Gmail): one plain sentence each."""
    p = PRESETS.get(c["preset"], {})
    out = []
    for k in ("imap_host", "smtp_host"):
        env, chosen = os.environ.get(KEYS[k], "").strip(), vault.get(KEYS[k]) or p.get(k, "")
        if env and chosen and env.lower() != str(chosen).lower():
            out.append(f"{KEYS[k]}={env} in .env or the environment overrides the {p.get('label', 'chosen')} server "
                       f"({chosen}): remove that line, then test again.")
    return out


def _fingerprint(c: dict) -> str:
    """Which account + servers the last fully successful test() was for (a later change to any of them un-verifies)."""
    fp = "|".join(str(c.get(k) or "").lower() for k in ("user", "imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_user"))
    return fp + ("|oauth" if c.get("auth") == "oauth" else "")  # app-password fingerprints stay as they were


def _port(v, name: str) -> int:
    try:
        n = int(str(v).strip())
    except ValueError:
        raise SystemExit(f"{name} must be a port number") from None
    if not 0 < n < 65536:
        raise SystemExit(f"{name} must be between 1 and 65535")
    return n


def connect(preset: str, user: str, password: str | None = None, **overrides) -> dict:
    """Store the connection (password only when given). Blank overrides fall back to the preset's servers."""
    p = PRESETS.get(preset)
    if p is None:
        raise SystemExit(f"unknown email provider '{preset}'. One of: {', '.join(PRESETS)}")
    if p.get("oauth_only"):
        raise SystemExit(f"{p['label']}: sign in with Microsoft (Setup > Connect email > Sign in with Microsoft, or "
                         f"lodestar email signin microsoft). Microsoft accepts only that OAuth sign-in, no passwords, for "
                         f"IMAP and SMTP.")
    user = (user or "").strip()
    if not EMAIL_RE.fullmatch(user):
        raise SystemExit(f"not an email address: {user[:80]}")
    unknown = set(overrides) - set(KEYS)
    if unknown:
        raise SystemExit(f"unknown email setting(s): {', '.join(sorted(unknown))}")
    v = {k: str(overrides.get(k) or "").strip() or p.get(k, "") for k in KEYS}
    if v["cafile"] and not os.path.isfile(v["cafile"]):
        raise SystemExit(f"certificate file not found: {v['cafile'][:200]}")
    v["imap_mode"] = str(v["imap_mode"] or "ssl").lower()
    if v["imap_mode"] not in ("ssl", "starttls"):
        raise SystemExit("IMAP mode is ssl (port 993) or starttls (port 143, or 1143 for Proton Mail Bridge)")
    if v["imap_mode"] == "ssl":
        v["imap_mode"] = ""  # the default; nothing stored
    v["smtp_mode"] = str(v["smtp_mode"] or "ssl").lower()
    if v["smtp_mode"] not in ("ssl", "starttls"):
        raise SystemExit("SMTP mode is ssl (port 465) or starttls (port 587)")
    if not str(overrides.get("smtp_port") or "").strip() and v["smtp_mode"] != p.get("smtp_mode"):
        v["smtp_port"] = ""  # the preset's port belongs to its own mode; the other mode gets its usual port
    for h in ("imap_host", "smtp_host"):
        if not HOST_RE.fullmatch(str(v[h])):
            raise SystemExit(f"{h.replace('_', ' ')} is missing or not a host name, e.g. imap.example.com")
    v["imap_port"] = _port(v["imap_port"] or 993, "IMAP port")
    v["smtp_port"] = _port(v["smtp_port"] or (587 if v["smtp_mode"] == "starttls" else 465), "SMTP port")
    if " " in v["smtp_user"]:
        raise SystemExit("SMTP login must not contain spaces")
    if v["smtp_user"].lower() == user.lower():
        v["smtp_user"] = ""
    held = [(vault.get(n) or "").lower() for n in ("IMAP_USER", "IMAP_HOST", "SMTP_HOST", "SMTP_USER")]
    if not password and held != [str(x).lower() for x in (user, v["imap_host"], v["smtp_host"], v["smtp_user"])]:
        vault.delete("IMAP_PASS")  # one account's app password never goes to another address or server
    if (vault.get("EMAIL_AUTH") or "") == "oauth":  # one way to sign in at a time: the app password route now
        from . import oauth

        oauth.disconnect()  # revokes a Google sign-in, best effort
    vault.set("EMAIL_AUTH", "password")
    vault.delete("EMAIL_VERIFIED")  # a (re)connect counts as working only after its own test passes
    vault.set("EMAIL_PRESET", preset)
    vault.set("IMAP_USER", user)
    for k, name in KEYS.items():
        if v[k]:
            vault.set(name, str(v[k]))
        else:
            vault.delete(name)
    if password:
        if preset != "custom":  # generated app passwords have no spaces; Google shows them in groups of four
            password = "".join(password.split())
        vault.set("IMAP_PASS", password, user)
    return status()


def connect_oauth(preset: str, user: str) -> dict:
    """After a provider sign-in (oauth.signin): that account's address and the preset's servers, no overrides."""
    p = PRESETS[preset]
    vault.set("EMAIL_PRESET", preset)
    vault.set("IMAP_USER", user)
    for k, name in KEYS.items():
        if p.get(k) and k in ("imap_host", "imap_port", "imap_mode", "smtp_host", "smtp_port", "smtp_mode"):
            vault.set(name, str(p[k]))
        else:
            vault.delete(name)
    vault.delete("EMAIL_VERIFIED")
    return status()


def disconnect() -> dict:
    """Forget the app password, or the provider sign-in (the servers stay filled in for next time)."""
    if util.mail_settings().get("auth") == "oauth":
        from . import oauth

        return oauth.disconnect() | status()
    vault.delete("IMAP_PASS")
    vault.delete("EMAIL_VERIFIED")
    return status()


def hint(e: BaseException, c: dict) -> str:
    """A plain next step for a failed IMAP/SMTP login."""
    msg = str(e).lower()
    p = PRESETS.get(c.get("preset") or "", {})
    if c.get("auth") == "oauth":
        if isinstance(e, SystemExit):  # needs sign-in, or the client is missing: the message is the next step
            return str(e)
        if "5.7.139" in msg or "smtpclientauthentication is disabled" in msg:
            return ("Your organization has SMTP AUTH turned off for this mailbox: Lodestar can read mail but cannot send. "
                    "Ask your admin to allow SMTP AUTH for your mailbox (Exchange admin center > mailbox > Email apps), "
                    "or send from another account.")
        if "authenticated but not connected" in msg:
            return "Turn on IMAP in Outlook.com settings (Forwarding and IMAP), then test again."
        if isinstance(e, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)) and not isinstance(e, imaplib.IMAP4.abort):
            who = "Microsoft" if (vault.get("OAUTH_PROVIDER") or "") == "microsoft" else "Google"
            return f"Sign-in was refused with your {who} token: sign in again (Setup > Connect email > Sign in with {who})."
    if isinstance(e, imaplib.IMAP4.abort):  # also an IMAP4.error, but a dropped connection, never a refused password
        return "The mail server dropped the connection: test again in a minute."
    if isinstance(e, socket.gaierror):
        return f"Could not find the server: check the host names ({c['imap_host']}, {c['smtp_host']}) and your internet connection."
    if isinstance(e, (TimeoutError, socket.timeout)):
        return (f"The server did not answer within {util.MAIL_TIMEOUT} s: check the host and port "
                f"(IMAP {c['imap_port']}, SMTP {c['smtp_port']}) or a firewall blocking them.")
    if isinstance(e, ssl.SSLCertVerificationError):
        return "The server's certificate does not match that host name: check the host is exactly what your provider lists."
    if isinstance(e, (ssl.SSLError, ConnectionRefusedError)) or "starttls" in msg:
        return ("The secure connection failed: wrong port or mode? IMAP uses 993 with ssl (Proton Mail Bridge: 1143 with "
                "starttls); SMTP uses 465 with ssl or 587 with starttls.")
    if "imap" in msg and ("not enabled" in msg or "disabled" in msg):
        return "IMAP access is turned off for this account: turn it on in your mail settings, then test again."
    if (any(s in msg for s in ("authenticationfailed", "application-specific password", "username and password not accepted",
                               "invalid credentials", "authentication failed", "login failed", "535"))
            or isinstance(e, imaplib.IMAP4.error) or type(e).__name__ == "SMTPAuthenticationError"):
        steps = p.get("steps") or "Use an app password from your provider, not your normal password."
        return f"Sign-in was refused. Use an app password, not your normal password. {steps}" + (f" ({p['help']})" if p.get("help") else "")
    return ""


def _imap(c: dict, pw: str | None) -> str:
    box = util.imap_open(c["imap_host"], c["imap_port"], c.get("imap_mode"))
    try:
        util.imap_login(box, c["user"], pw)
        box.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        _, data = box.search(None, f"(SINCE {since})")
        return f"logged in; {len((data or [b''])[0].split())} message(s) in INBOX from the last 7 days"
    finally:
        try:
            box.logout()
        except Exception:  # ponytail: a failed goodbye after the check changes nothing
            pass


def _smtp(c: dict, pw: str | None) -> str:
    who = c["smtp_user"] if pw else c["user"]  # a provider sign-in logs in as the account address
    with util.smtp_open(c["smtp_host"], c["smtp_port"], c["smtp_mode"]) as s:
        util.smtp_login(s, who, pw)
    return f"logged in as {who} (nothing sent)"


def _kind(e: BaseException) -> str:
    """'auth' (the sign-in was refused), 'net' (could not reach the server: never un-verifies) or 'other' (a setup
    problem). Order matters: IMAP4.abort is an IMAP4.error, and every SMTPException is an OSError."""
    if isinstance(e, imaplib.IMAP4.abort):  # a dropped connection
        return "net"
    if isinstance(e, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError, SystemExit)):
        return "auth"
    if isinstance(e, ssl.SSLCertVerificationError):  # wrong host name: a setup problem, not an outage
        return "other"
    if isinstance(e, (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return "net"
    if isinstance(e, smtplib.SMTPException):  # any other SMTP refusal is real
        return "other"
    if isinstance(e, OSError):  # DNS, refused, timeout, ssl.SSLError
        return "net"
    return "other"


def test() -> dict:
    """Log in to IMAP (INBOX read-only) and SMTP (no send): {imap: {ok, detail, kind?}, smtp: {...}, hint, reachable}.
    Both sides ok marks the connection verified; a refused sign-in or setup problem un-verifies it; a network failure
    alone leaves it as it was (an offline start must not disconnect a working mailbox)."""
    from .connections import mail_result, record, redact

    c = util.mail_settings()
    pw, ready = _login(c)
    if not ready:
        raise SystemExit("email is not connected: Setup > Connect email, or lodestar email connect")
    out, hints = {}, conflicts(c)  # the likeliest cause first, before any generic 'use an app password'
    for name, fn in (("imap", _imap), ("smtp", _smtp)):
        try:
            out[name] = {"ok": True, "detail": fn(c, pw)}
        except (Exception, SystemExit) as e:
            msg = f"{type(e).__name__}: {e}"
            out[name] = {"ok": False, "kind": _kind(e), "detail": redact(msg.replace(pw, "***") if pw else msg)[:300]}
            h = hint(e, c)
            if h and h not in hints:
                hints.append(h)
    kinds = {r.get("kind") for r in out.values() if not r["ok"]}
    if not kinds:
        vault.set("EMAIL_VERIFIED", _fingerprint(c))
    elif kinds - {"net"}:
        vault.delete("EMAIL_VERIFIED")
    out |= {"hint": " ".join(hints), "reachable": "net" not in kinds}
    try:  # Getting started and doctor read this, whichever path ran the test
        record("mail", None, mail_result(out), _fingerprint(c))
    except Exception:  # ponytail: an unwritable connections.json must not hide the test's own answer
        pass
    return out


def test_send(to: str | None = None) -> dict:
    """Send a short test message to your own configured address, never anyone else."""
    c = util.mail_settings()
    if not _login(c)[1]:
        raise SystemExit("email is not connected: Setup > Connect email, or lodestar email connect")
    if to and to.strip().lower() != c["user"].lower():
        raise SystemExit("a test email only goes to your own connected address")
    mid = util.send_email(c["user"], "Lodestar test email",
                          "This is a test from Lodestar. Sending works: approved replies and follow-ups will go out "
                          "from this address.\n")
    return {"ok": True, "to": c["user"], "message_id": mid}
