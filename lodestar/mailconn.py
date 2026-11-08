"""Connect your mailbox: provider presets, the stored connection, and a login check for IMAP and SMTP.

Everything is kept in the keyring vault and read back through config.setting (an env var or .env line still wins):
EMAIL_PRESET, IMAP_USER, IMAP_HOST, IMAP_PORT, SMTP_HOST, SMTP_PORT, SMTP_MODE, SMTP_USER. IMAP_PASS, the app password,
is the only secret and no function here returns it.
"""
import imaplib
import os
import re
import socket
import ssl
from datetime import datetime, timedelta

from . import util, vault
from .config import setting
from .contacts import EMAIL_RE

# ponytail: host/port presets for the common app-password providers; anything else is "custom". Microsoft needs OAuth.
PRESETS = {
    "gmail": {"label": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com",
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
    "outlook": {"label": "Outlook / Hotmail / Microsoft 365", "domains": ["outlook.com", "hotmail.com", "live.com", "msn.com"],
                "unsupported": "Microsoft no longer accepts passwords or app passwords for IMAP and SMTP, only OAuth "
                               "sign-in, which Lodestar does not do. Forward job mail to a Gmail, Fastmail or iCloud "
                               "address and connect that one instead."},
    "custom": {"label": "Other (custom server)", "imap_port": 993, "smtp_port": 465, "smtp_mode": "ssl", "domains": [],
               "steps": "Enter your provider's IMAP and SMTP servers under Advanced. Use an app password if it offers one."},
}
KEYS = {"imap_host": "IMAP_HOST", "imap_port": "IMAP_PORT", "smtp_host": "SMTP_HOST", "smtp_port": "SMTP_PORT",
        "smtp_mode": "SMTP_MODE", "smtp_user": "SMTP_USER"}
MANAGED = {"EMAIL_PRESET", "IMAP_USER", "IMAP_PASS", "EMAIL_VERIFIED", *KEYS.values()}  # Connect email owns these vault entries
HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


def guess(user: str) -> str:
    """Preset for an address's domain ('' when unknown)."""
    dom = user.rpartition("@")[2].strip().lower()
    return next((k for k, p in PRESETS.items() if dom in p["domains"]), "")


def status() -> dict:
    """The stored connection without the password: configured?, preset, address, servers, env vars that override it."""
    c = util.mail_settings()
    p = PRESETS.get(c["preset"], {})
    configured = bool(c["user"] and setting("IMAP_PASS"))
    return c | {"configured": configured, "verified": configured and vault.get("EMAIL_VERIFIED") == _fingerprint(c),
                "label": p.get("label", c["preset"]),
                "shadowed": [k for k in ("IMAP_USER", "IMAP_PASS", *KEYS.values()) if os.environ.get(k)]}


def _fingerprint(c: dict) -> str:
    """Which account + servers the last fully successful test() was for (a later change to any of them un-verifies)."""
    return "|".join(str(c.get(k) or "").lower() for k in ("user", "imap_host", "imap_port", "smtp_host", "smtp_port", "smtp_user"))


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
    if p.get("unsupported"):
        raise SystemExit(f"{p['label']}: {p['unsupported']}")
    user = (user or "").strip()
    if not EMAIL_RE.fullmatch(user):
        raise SystemExit(f"not an email address: {user[:80]}")
    unknown = set(overrides) - set(KEYS)
    if unknown:
        raise SystemExit(f"unknown email setting(s): {', '.join(sorted(unknown))}")
    v = {k: str(overrides.get(k) or "").strip() or p.get(k, "") for k in KEYS}
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


def disconnect() -> dict:
    """Forget the app password (the servers stay filled in for next time)."""
    vault.delete("IMAP_PASS")
    vault.delete("EMAIL_VERIFIED")
    return status()


def hint(e: BaseException, c: dict) -> str:
    """A plain next step for a failed IMAP/SMTP login."""
    msg = str(e).lower()
    p = PRESETS.get(c.get("preset") or "", {})
    if isinstance(e, socket.gaierror):
        return f"Could not find the server: check the host names ({c['imap_host']}, {c['smtp_host']}) and your internet connection."
    if isinstance(e, (TimeoutError, socket.timeout)):
        return (f"The server did not answer within {util.MAIL_TIMEOUT} s: check the host and port "
                f"(IMAP {c['imap_port']}, SMTP {c['smtp_port']}) or a firewall blocking them.")
    if isinstance(e, ssl.SSLCertVerificationError):
        return "The server's certificate does not match that host name: check the host is exactly what your provider lists."
    if isinstance(e, (ssl.SSLError, ConnectionRefusedError)) or "starttls" in msg:
        return ("The secure connection failed: wrong port or mode? IMAP uses 993; SMTP uses 465 with ssl or 587 with "
                "starttls.")
    if "imap" in msg and ("not enabled" in msg or "disabled" in msg):
        return "IMAP access is turned off for this account: turn it on in your mail settings, then test again."
    if (any(s in msg for s in ("authenticationfailed", "application-specific password", "username and password not accepted",
                               "invalid credentials", "authentication failed", "login failed", "535"))
            or isinstance(e, imaplib.IMAP4.error) or type(e).__name__ == "SMTPAuthenticationError"):
        steps = p.get("steps") or "Use an app password from your provider, not your normal password."
        return f"Sign-in was refused. Use an app password, not your normal password. {steps}" + (f" ({p['help']})" if p.get("help") else "")
    return ""


def _imap(c: dict, pw: str) -> str:
    box = imaplib.IMAP4_SSL(c["imap_host"], port=c["imap_port"], ssl_context=util.tls_context(), timeout=util.MAIL_TIMEOUT)
    try:
        box.login(c["user"], pw)
        box.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        _, data = box.search(None, f"(SINCE {since})")
        return f"logged in; {len((data or [b''])[0].split())} message(s) in INBOX from the last 7 days"
    finally:
        try:
            box.logout()
        except Exception:  # ponytail: a failed goodbye after the check changes nothing
            pass


def _smtp(c: dict, pw: str) -> str:
    with util.smtp_open(c["smtp_host"], c["smtp_port"], c["smtp_mode"]) as s:
        s.login(c["smtp_user"], pw)
    return f"logged in as {c['smtp_user']} (nothing sent)"


def test() -> dict:
    """Log in to IMAP (INBOX read-only) and SMTP (no send): {imap: {ok, detail}, smtp: {ok, detail}, hint}."""
    c, pw = util.mail_settings(), setting("IMAP_PASS")
    if not (c["user"] and pw):
        raise SystemExit("email is not connected: Setup > Connect email, or lodestar email connect")
    out, hints = {}, []
    for name, fn in (("imap", _imap), ("smtp", _smtp)):
        try:
            out[name] = {"ok": True, "detail": fn(c, pw)}
        except Exception as e:
            out[name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"[:300].replace(pw, "***")}
            h = hint(e, c)
            if h and h not in hints:
                hints.append(h)
    if all(r["ok"] for r in out.values()):
        vault.set("EMAIL_VERIFIED", _fingerprint(c))
    else:
        vault.delete("EMAIL_VERIFIED")
    return out | {"hint": " ".join(hints)}


def test_send(to: str | None = None) -> dict:
    """Send a short test message to your own configured address, never anyone else."""
    c = util.mail_settings()
    if not (c["user"] and setting("IMAP_PASS")):
        raise SystemExit("email is not connected: Setup > Connect email, or lodestar email connect")
    if to and to.strip().lower() != c["user"].lower():
        raise SystemExit("a test email only goes to your own connected address")
    mid = util.send_email(c["user"], "Lodestar test email",
                          "This is a test from Lodestar. Sending works: approved replies and follow-ups will go out "
                          "from this address.\n")
    return {"ok": True, "to": c["user"], "message_id": mid}
