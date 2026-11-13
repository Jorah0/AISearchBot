"""Site accounts (pass 22, addendum A; docs/APPLY_AGENT.md > Site accounts): your accounts on employer application sites
(a Workday tenant, an iCIMS portal), one per site (its exact host). The row (site_accounts) holds the sign-in link, the
username, created / last sign-in dates, the status and the jobs it was used for; the password lives only in the OS
keyring (vault name site:<host>) and comes back only on Reveal or to be typed into that site's own password field.

The rules:
- Never for LinkedIn, Indeed, Glassdoor, ZipRecruiter or SimplyHired (apply_agent.forbidden).
- Creating: the agent fills the sign-up form with your email and a password (saved first): your general login when you
  set one (Setup > Site accounts), else a new strong one. Then it stops: you tick any terms box and press Create. Only
  when you turned on accounts_auto_create does it tick the terms / privacy box itself (never a marketing one), press
  Create and use your inbox's code or link for that site. A site that already knows your email: one sign-in try with
  your general password, else you sign in yourself.
- Signing in: the username and password are typed only on the account's own host, the password only into a password
  field (Page.type). A password that failed or a locked account is never tried again by itself (no lockouts).
- A CAPTCHA is always yours. Codes and verification links come from your connected inbox (codes.py): used when you click
  Fill code / Open link, or by themselves only on a site where you ticked that; a link opens only on the account's host.
- Page text is untrusted: what to do is decided here from fixed patterns; nothing hides that the window is automated.
"""
import json
import re
import secrets
import string
import threading
import time

from . import apply_ats, codes, db, log, vault
from .config import full_ai_check

STATUSES = {"pending": "sign-up filled: press Create in the window", "active": "active",
            "needs_verification": "needs verification", "locked": "locked", "failed": "sign-in failed"}
SYMBOLS = "!@#$%*?-_"
NEEDS_S = 1800  # 30 minutes waiting for you, as the apply agent
# fixed patterns (the page never decides what is clicked): button and link names, then the page's verdicts
SIGNIN_RE = re.compile(r"^\s*(?:sign ?in|log ?in|sign on)\s*$", re.I)
CREATE_RE = re.compile(r"^\s*(?:create (?:an |your |new )?account|sign ?up|register(?: now)?)\s*$", re.I)
VERIFY_BTN_RE = re.compile(r"^\s*(?:verify|submit|confirm|continue)\s*$", re.I)
FORGOT_RE = re.compile(r"forgot|reset (?:your )?password", re.I)
NEW_PW_RE = re.compile(r"new-password|confirm|verify|re-?enter|repeat|again", re.I)
USER_RE = re.compile(r"e-?mail|user ?(?:name|id)|login|account", re.I)
CONFIRM_RE = re.compile(r"confirm|verify|re-?enter|repeat|again", re.I)
CODE_FIELD_RE = re.compile(r"one-time-code|\bcode\b|otp|passcode|\bpin\b|verification", re.I)
LOCKED_RE = re.compile(r"account (?:is |has been )?(?:locked|disabled|suspended)|too many (?:failed |unsuccessful )?"
                       r"(?:sign.?in |login )?(?:attempts|tries)", re.I)
_GAP = r"[^\w\n]+(?:\w+[^\w\n]+){0,3}?"  # up to 3 words between, within one line
FAILED_RE = re.compile(r"(?:incorrect|invalid|wrong|unrecognized|not recognized|does ?n[o']t match)" + _GAP +
                       r"(?:password|e-?mail|username|credentials|sign.?in)|(?:password|e-?mail|username|credentials)"
                       + _GAP + r"(?:incorrect|invalid|wrong|not recognized)", re.I)
VERIFY_RE = re.compile(r"verify your (?:e-?mail|account)|check your (?:e-?mail|inbox)|(?:activation|verification) "
                       r"(?:link|e-?mail)|confirm your (?:e-?mail|account)|activate your account", re.I)
GENERAL = "site:*"  # your general login for new accounts: keyring only ('*' is never a host, so never a site's row)
CONSENT_RE = re.compile(r"\b(?:terms|privacy|agree|consent|polic(?:y|ies)|conditions|acknowledge)", re.I)
MARKETING_RE = re.compile(r"newsletter|marketing|promot|offers|\bsms\b|text (?:me|messages)|job alerts|talent "
                          r"(?:network|community)|updates|partners|third", re.I)
EXISTS_RE = re.compile(r"already (?:have an account|registered|in use|exists)|account (?:with|for) this e-?mail (?:address )?"
                       r"already|e-?mail (?:address )?(?:is )?already (?:registered|in use|taken)", re.I)
HINT = {
    "captcha": "solve the check in the agent window, then press Continue",
    "create": "Lodestar filled the sign-up form with your email and a new password (saved under Setup > Site accounts). "
              "Tick the terms box if you agree, fill anything else it asks and press the Create button in the window. "
              "Already have an account on this site? Press 'I have an account' instead",
    "code": "type the code the site sent you (email, text or your authenticator app) in the agent window, or press Fill code "
            "under Setup > Site accounts, then Continue",
    "link": "open the verification link the site emailed you (Setup > Site accounts > Open link uses the agent's window), "
            "then press Continue",
    "signin": "press Sign in in the agent window, then Continue",
    "exists": "this site already has an account for your email: sign in with it in the window, then press Continue "
              "(Setup > Site accounts > Save login keeps that password for next time)",
    "own": "sign in with your own account in the window, then press Continue (Setup > Site accounts > Save login keeps it)",
    "failed": "the saved password did not work: reset it on the site (Setup > Site accounts > Reset password), store the "
              "new one with Change password, then sign in in the window and press Continue",
    "locked": "the site locked this account: unlock or reset it on the site (Setup > Site accounts > Reset password), "
              "then sign in in the window and press Continue",
    "yours": "sign in (or create the account) in the agent window, then press Continue",
}


class _Stop(Exception):
    """An account window ends (you closed it, pressed Close, or 30 minutes passed)."""


# ----------------------------------------------------------------------------- the vault: rows + keyring
def _name(site: str) -> str:
    return f"site:{site}"


def site_of(url) -> str:
    """The account's site: the link's exact host (a Workday tenant is its own site). Refuses a forbidden board."""
    from .apply_agent import forbidden

    u = str(url or "").strip()
    if not re.match(r"https?://", u, re.I) or len(u) >= 2048 or not apply_ats.host(u):
        raise SystemExit("give the site's sign-in page as an http(s) link")
    if site := forbidden(u):
        raise SystemExit(f"{site} does not allow bots: Lodestar never keeps or uses an account there")
    return apply_ats.host(u)


def generate(n: int = 16) -> str:
    """A strong, unique password: n characters, upper and lower case, digits and symbols most sites accept."""
    pools = (string.ascii_lowercase, string.ascii_uppercase, string.digits, SYMBOLS)
    while True:
        pw = "".join(secrets.choice("".join(pools)) for _ in range(n))
        if all(any(c in p for c in pw) for p in pools):
            return pw


def general() -> dict:
    """Your general login for new site accounts (never the password) and whether the agent may finish a sign-up."""
    from . import settings

    return {"set": GENERAL in dict(vault.names()), "username": vault.user(GENERAL),
            "auto_create": bool(settings.pref("accounts_auto_create"))}


def set_general(username: str = "", password: str = "", clear: bool = False) -> dict:
    """Save (or clear) the general login: new accounts use this password, and this username when given (else your
    profile email), instead of a generated one. One password on many sites: a leak on one opens the others."""
    full_ai_check("touches the vault")
    if clear:
        vault.delete(GENERAL)
        return general()
    pw = str(password or "").strip()
    if len(pw) < 8:
        raise SystemExit("type the general password (at least 8 characters; it replaces the saved one)")
    vault.set(GENERAL, pw, " ".join(str(username or "").split())[:200])
    return general()


def _general_pw() -> str:
    return vault.get(GENERAL) or ""


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    try:
        d["jobs"] = [int(x) for x in json.loads(d["jobs"] or "[]")]
    except (ValueError, TypeError):
        d["jobs"] = []
    return d


def for_site(site: str) -> dict | None:
    return _row(db.con().execute("SELECT * FROM site_accounts WHERE site=?", (str(site or "").lower(),)).fetchone())


def get(aid) -> dict:
    a = _row(db.con().execute("SELECT * FROM site_accounts WHERE id=?", (int(aid),)).fetchone())
    if not a:
        raise SystemExit(f"no site account #{aid}")
    return a


def public(a: dict) -> dict:
    """An account for the page / CLI: never the password; its jobs with company and title."""
    jobs = []
    for jid in a["jobs"]:
        j = db.con().execute("SELECT id, company, title, status FROM jobs WHERE id=?", (jid,)).fetchone()
        if j:
            jobs.append(dict(j))
    return {k: a[k] for k in ("id", "site", "login_url", "username", "status", "created_by", "created_at", "last_login",
                              "last_error", "reset_url")} | {"auto_verify": bool(a["auto_verify"]), "jobs": jobs,
                                                             "label": STATUSES.get(a["status"], a["status"])}


def listing(q: str = "") -> list[dict]:
    out = [public(_row(r)) for r in db.con().execute("SELECT * FROM site_accounts ORDER BY site")]
    q = str(q or "").strip().lower()
    return [a for a in out if not q or q in json.dumps(a).lower()]


def add(url: str, username: str, password: str = "", by: str = "you", status: str = "active") -> dict:
    """Save an account (one per site). No password: Lodestar makes a strong one. The keyring is written first, so a row
    never exists without its password."""
    full_ai_check("touches the vault")
    site, username = site_of(url), " ".join(str(username or "").split())[:200]
    if not username:
        raise SystemExit("give the username or email you sign in with")
    if for_site(site):
        raise SystemExit(f"an account for {site} is saved already (one per site): Re-login, or Change password")
    vault.set(_name(site), str(password or "").strip() or generate(), username)
    db.con().execute("INSERT INTO site_accounts(site, login_url, username, status, created_by, jobs) VALUES(?,?,?,?,?,'[]')",
                     (site, str(url).strip(), username, status if status in STATUSES else "active", by))
    db.con().commit()
    return public(for_site(site))


def reveal(aid) -> dict:
    """The password, on your click (Reveal) only."""
    a = get(aid)
    pw = vault.get(_name(a["site"]))
    if not pw:
        raise SystemExit("the OS keyring has no password for this account (removed outside Lodestar?): store it again "
                         "with Change password")
    return {"id": a["id"], "password": pw}


def set_password(aid, password: str = "", generate_new: bool = False) -> dict:
    """Change the stored password (you changed it on the site, or want a new one to type there). A failed or locked
    account is active again: its sign-in is tried once more."""
    a = get(aid)
    pw = generate() if generate_new else str(password or "").strip()
    if not pw:
        raise SystemExit("type the new password, or press Generate")
    vault.set(_name(a["site"]), pw, a["username"])
    _mark(a["site"], "active" if a["status"] in ("failed", "locked") else a["status"], error=None)
    return {"id": a["id"], "changed": True} | ({"password": pw} if generate_new else {})


def set_auto(aid, on: bool) -> dict:
    """Allow (or stop) using codes and verification links from your inbox on this site without a click."""
    full_ai_check("changes how site accounts verify")
    a = get(aid)
    db.con().execute("UPDATE site_accounts SET auto_verify=? WHERE id=?", (int(bool(on)), a["id"]))
    db.con().commit()
    return public(get(a["id"]))


def remove(aid) -> dict:
    a = get(aid)
    vault.delete(_name(a["site"]))
    db.con().execute("DELETE FROM site_accounts WHERE id=?", (a["id"],))
    db.con().commit()
    return {"removed": a["id"], "site": a["site"]}


def link_job(site: str, job_id: int) -> None:
    a = for_site(site)
    if a and int(job_id) not in a["jobs"]:
        db.con().execute("UPDATE site_accounts SET jobs=? WHERE id=?", (json.dumps([*a["jobs"], int(job_id)]), a["id"]))
        db.con().commit()


_KEEP = object()


def _mark(site: str, status: str, error=_KEEP, login: bool = False, reset=None) -> None:
    sets = {"status": status} | ({"last_error": (error or None) and str(error)[:300]} if error is not _KEEP else {}) | (
        {"last_login": db._now()} if login else {}) | ({"reset_url": reset} if reset else {})
    db.con().execute(f"UPDATE site_accounts SET {', '.join(k + '=?' for k in sets)} WHERE site=?", (*sets.values(), site))
    db.con().commit()


def _secret(a: dict) -> str:
    pw = vault.get(_name(a["site"]))
    if not pw:
        raise SystemExit(f"the OS keyring has no password for {a['site']}: Setup > Site accounts > Change password")
    return pw


# ----------------------------------------------------------------------------- the page, held to one site
_INPUTS = """els => els.map((el, k) => { el.setAttribute('data-lodestar-a', String(k)); const r = el.getBoundingClientRect();
  const lab = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('aria-label') || el.placeholder || '';
  return { a: k, type: (el.type || 'text').toLowerCase(), hint: [lab, el.name, el.id, el.getAttribute('autocomplete')]
    .join(' ').replace(/\\s+/g, ' ').trim().slice(0, 200), shown: r.width > 2 && r.height > 2 &&
    getComputedStyle(el).visibility !== 'hidden' && !el.disabled && !el.readOnly }; })"""


class Page:
    """The account flows' view of an apply_ats.Tab, held to one site: inputs are read and typed only in frames on that
    exact host, the password only into a password field, clicks only on buttons or links whose name matches a fixed
    pattern here, and navigation only to that host."""

    def __init__(self, tab, site: str | None = None):
        self.tab, self.site, self._f = tab, site or tab.host(), []

    @property
    def url(self) -> str:
        return self.tab.url

    def _here(self) -> bool:
        from .apply_agent import forbidden

        return self.tab.host() == self.site and not forbidden(self.site) and not self.tab.forbidden_hit

    def _frames(self) -> list:
        return [f for f in self.tab.page.frames if apply_ats.host(f.url) == self.site]

    def inputs(self) -> list[dict]:
        """The visible inputs on the site: {a, frame, type, hint (label, name, id, autocomplete), shown}."""
        out, self._f = [], []
        for f in self._frames():
            try:
                ds = f.locator("input").evaluate_all(_INPUTS)
            except Exception:  # a frame that navigated away mid-read
                continue
            self._f.append(f)
            # a styled checkbox hides its input behind the label: kept, for _finish's terms box only
            out += [d | {"frame": len(self._f) - 1} for d in ds if d.get("shown") or d.get("type") == "checkbox"]
        return out

    def _loc(self, d: dict):
        f = self._f[d["frame"]] if d["frame"] < len(self._f) else None
        if not self._here() or f is None or apply_ats.host(f.url) != self.site:
            raise SystemExit(f"refused: the page is no longer on {self.site}")
        return f.locator(f'input[data-lodestar-a="{int(d["a"])}"]')

    def tick(self, d: dict) -> None:
        """Tick one checkbox on the site: _finish's terms / privacy box, only with accounts_auto_create on."""
        loc = self._loc(d)
        if (loc.get_attribute("type") or "").lower() != "checkbox":
            raise SystemExit("refused: only a checkbox is ticked")
        if not loc.is_checked():
            try:
                loc.check(timeout=3000)
            except Exception:  # hidden behind a styled label: the element's own click (the page's handlers run)
                loc.evaluate("el => el.click()")

    def type(self, d: dict, value: str, secret: bool = False) -> None:
        """The one write path of the account flows (never Tab.write, which refuses password fields)."""
        loc = self._loc(d)
        if ((loc.get_attribute("type") or "text").lower() == "password") != secret:
            raise SystemExit("refused: a password goes only into a password field, and only a password goes there")
        loc.fill(str(value))

    def click(self, rx) -> bool:
        """Click the one visible button or link (in a sign-in form first, else the page) whose name matches rx."""
        if not self._here():
            return False
        for scope in ("form:has(input[type=password])", "body"):
            hits = []
            for f in self._frames():
                try:
                    loc = f.locator(scope)
                    hits += [x for x in loc.get_by_role("button", name=rx).all() + loc.get_by_role("link", name=rx).all()
                             if x.is_visible()]
                except Exception:
                    continue
            if len(hits) == 1:
                hits[0].click()
                return True
            if hits:
                return False  # ambiguous: yours
        return False

    def link(self, rx) -> str | None:
        """The href of a visible link whose name matches rx (the site's password reset), when http(s)."""
        for f in self._frames():
            try:
                for x in f.get_by_role("link", name=rx).all():
                    if x.is_visible():
                        h = x.evaluate("a => a.href") or ""
                        return h if re.match(r"https?://", h) and len(h) < 2048 else None
            except Exception:
                continue
        return None

    def goto(self, url: str) -> None:
        from .apply_agent import forbidden

        if apply_ats.host(url) != self.site or forbidden(url):
            raise SystemExit(f"refused: only pages on {self.site} open here")
        self.tab.goto(url)

    def offsite(self):
        return self.tab.offsite

    def blocker(self):
        return self.tab.blocker()

    def text(self) -> str:
        return self.tab.text()

    def idle(self, ms: int) -> None:
        self.tab.idle(ms)


# ----------------------------------------------------------------------------- the flows (one site, any page object)
def kind(inputs) -> str | None:
    """signup (a second password field, or a new-password one), login (one password field) or None (no form)."""
    pw = [d for d in inputs if d["type"] == "password"]
    if not pw:
        return None
    return "signup" if len(pw) >= 2 or NEW_PW_RE.search(pw[0]["hint"]) else "login"


def _user(inputs) -> dict | None:
    return next((d for d in inputs if d["type"] in ("email", "text") and (d["type"] == "email" or USER_RE.search(d["hint"]))
                 and not CONFIRM_RE.search(d["hint"])), None)


def _need(step: str, site: str) -> list[dict]:
    return [{"reason": "captcha" if step == "captcha" else f"account_{step}", "site": site, "hint": HINT[step]}]


_REQ: dict[str, dict] = {}  # "run:<id>" | "session" -> {"action": code | link | own, "id"}: your clicks, memory only


def _related(domain: str, site: str) -> bool:
    """A code's sender belongs to the site (for automatic use only): the sender domain's name is one of the site's labels
    or starts one (myworkday.com -> acme.wd5.myworkdayjobs.com)."""
    base = (str(domain or "").lower().rsplit(".", 2)[-2:] or [""])[0]
    return len(base) >= 4 and any(lab.startswith(base) for lab in site.split("."))


def _serve(pg, key: str, acct: dict | None, last: list) -> str | None:
    """One request from your click, or an automatic one on a site you allowed: 'acted', 'own' or None. Runs in the thread
    that owns the page."""
    req = _REQ.pop(key, None)
    if req is None and acct and acct.get("auto_verify"):
        if time.monotonic() - last[0] > 30:  # a quick look at the inbox every 30 s while it waits
            last[0] = time.monotonic()
            try:
                codes.poll()
            except (Exception, SystemExit):  # no mailbox, or it refused: you can still type the code
                pass
        mine = [c for c in codes.current() if _related(c["domain"], pg.site)]
        here = [x for x in codes.links() if x["host"] == pg.site]
        req = {"action": "code", "id": mine[0]["id"]} if len(mine) == 1 else {"action": "link", "id": here[0]["id"]} \
            if len(here) == 1 else None
    if not req:
        return None
    if req["action"] == "own":
        return "own"
    if req["action"] == "code":
        c = next((c for c in codes.current() if c["id"] == req["id"]), None)
        ins = pg.inputs()
        d = next((d for d in ins if "one-time-code" in d["hint"]), None) or next(
            (d for d in ins if d["type"] in ("text", "tel", "number") and CODE_FIELD_RE.search(d["hint"])), None)
        if c and d:
            pg.type(d, c["code"])
            codes.dismiss(c["id"])
            pg.click(VERIFY_BTN_RE)
            pg.idle(800)
            return "acted"
    if req["action"] == "link":
        url = codes.link_url(req["id"])
        if url and apply_ats.host(url) == pg.site:
            codes.dismiss(req["id"])
            pg.goto(url)
            pg.idle(800)
            return "acted"
    return None


def _until(pg, key: str, acct: dict | None, done=None, out: dict | None = None):
    """The wait's test (called in the thread that owns the page, so it may act): your Continue, a request you made (Fill
    code, Open link, I have an account), an automatic one, or done()."""
    last = [0.0]

    def test(state) -> bool:
        if state["answers"].get("_continue"):
            return True
        r = _serve(pg, key, acct, last)
        if r == "own" and out is not None:
            out["own"] = True
            return True
        return bool((r == "acted" and done is None) or (done and done()))
    return test


def _left_form(pg) -> bool:
    return kind(pg.inputs()) is None or bool(EXISTS_RE.search(pg.text()))


def _said(text: str, rx) -> str:
    """The page's own line that matched (its message, as the site put it; page text, shown escaped)."""
    m = rx.search(text)
    return next((ln.strip() for ln in text.splitlines() if m.group(0) in ln), m.group(0))[:200]


def _after(pg, wait, key: str, acct: dict) -> tuple[str, str]:
    """The page's verdict after Sign in or Create, with a CAPTCHA, a 2-step code or an email verification on the way."""
    for _ in range(8):
        pg.idle(800)
        if pg.offsite():
            return "offsite", ""
        acct = for_site(pg.site) or acct
        t, b, ins = pg.text(), pg.blocker(), pg.inputs()
        if b == "captcha":
            wait(_need("captcha", pg.site), _until(pg, key, acct))
            continue
        if EXISTS_RE.search(t) and acct["status"] == "pending":
            return "exists", HINT["exists"]
        if LOCKED_RE.search(t):
            _mark(pg.site, "locked", error=_said(t, LOCKED_RE), reset=pg.link(FORGOT_RE))
            return "locked", HINT["locked"]
        if FAILED_RE.search(t):
            _mark(pg.site, "failed", error=_said(t, FAILED_RE), reset=pg.link(FORGOT_RE))
            return "failed", HINT["failed"]
        if b == "code" or any("one-time-code" in d["hint"] for d in ins):
            if acct["status"] == "pending":
                _mark(pg.site, "needs_verification")
            wait(_need("code", pg.site), _until(pg, key, acct, done=lambda: pg.blocker() != "code"))
            continue
        if VERIFY_RE.search(t) and kind(ins) is None:
            _mark(pg.site, "needs_verification")
            wait(_need("link", pg.site), _until(pg, key, acct))
            if apply_ats.host(pg.url) == pg.site and kind(pg.inputs()) is None:
                pg.goto(acct["login_url"])  # verified (the link, or you elsewhere): back to the sign-in page
            return "verify", ""
        if kind(ins) is None:
            _mark(pg.site, "active", error=None, login=True)
            return "ok", ""
    return "yours", HINT["yours"]


def _sign_in(pg, wait, key: str, acct: dict) -> tuple[str, str]:
    ins = pg.inputs()
    if u := _user(ins):
        pg.type(u, acct["username"])
    pg.type(next(d for d in ins if d["type"] == "password"), _secret(acct), secret=True)
    if not pg.click(SIGNIN_RE):
        wait(_need("signin", pg.site), _until(pg, key, acct, done=lambda: _left_form(pg)))
    return _after(pg, wait, key, acct)


def _finish(pg, ins) -> bool:
    """accounts_auto_create is on: tick the sign-up's terms / privacy boxes (never a marketing or partner one) and press
    Create. False: no single Create button, so it stays yours."""
    for d in ins:
        if d["type"] == "checkbox" and CONSENT_RE.search(d["hint"]) and not MARKETING_RE.search(d["hint"]):
            pg.tick(d)
    return pg.click(CREATE_RE)


def _create(pg, wait, key: str, login_url: str) -> tuple[str, str]:
    """Fill the sign-up form (your email, your general password or a new one, saved first), then you press Create, or
    the agent does when you allowed it (accounts_auto_create)."""
    from .extras import autofill_data

    acct, g = for_site(pg.site), general()
    email = str(autofill_data().get("email") or "").strip()
    if acct is None:
        if not (g["username"] or email):
            return "yours", "your profile has no email address: add it (Profile tab), or create the account in the window"
        acct = for_site(add(login_url, g["username"] or email, _general_pw(), by="agent", status="pending")["site"])
        if g["auto_create"]:  # you let the agent finish sign-ups: their email code or link too
            set_auto(acct["id"], True)
    ins = pg.inputs()
    pw = _secret(acct)
    for d in ins:
        if d["type"] == "password":
            pg.type(d, pw, secret=True)
        elif d["type"] in ("email", "text") and (d["type"] == "email" or USER_RE.search(d["hint"])) and (
                d is _user(ins) or re.search(r"e-?mail", d["hint"], re.I)):
            mail = d["type"] == "email" or re.search(r"e-?mail", d["hint"], re.I)
            # the email (and its confirm field); a username field gets your general username
            pg.type(d, email if mail and email and "@" not in acct["username"] else acct["username"])
    out: dict = {}
    if not (g["auto_create"] and _finish(pg, ins)):
        wait(_need("create", pg.site), _until(pg, key, acct, done=lambda: _left_form(pg), out=out))
    if out.get("own"):
        remove(acct["id"])  # never used: its password goes too
        return "yours", HINT["own"]
    r, hint = _after(pg, wait, key, acct)
    if r == "exists":
        remove(acct["id"])
        if gpw := _general_pw():  # perhaps made with your general password: one sign-in try, never retried if wrong
            add(login_url, acct["username"], gpw, by="general")
            if pg.click(SIGNIN_RE):
                pg.idle(1200)
                return "again", ""
            return "yours", HINT["exists"]
        pg.click(SIGNIN_RE)
    return r, hint


def handle(pg, wait, key: str, job_id: int | None = None, create: bool = True) -> tuple[str, str]:
    """A sign-in or sign-up form on pg.site: sign in with the saved account, or (create) fill the sign-up form for you to
    create one. ('ok' | 'offsite' | 'yours', hint): ok = past it; yours = left to you (the hint says what to do).
    wait(needs, until) blocks until until(state) holds (the apply agent's _wait, or an account window's)."""
    from .apply_agent import forbidden

    start = pg.url
    try:
        for _ in range(6):
            if pg.offsite():
                return "offsite", ""
            if forbidden(pg.site):
                return "yours", HINT["yours"]
            if pg.blocker() == "captcha":  # yours, before anything is typed
                wait(_need("captcha", pg.site), _until(pg, key, for_site(pg.site)))
                continue
            k, acct = kind(pg.inputs()), for_site(pg.site)
            if k is None:
                return "ok", ""
            if acct and acct["status"] != "pending":
                if acct["status"] in ("failed", "locked"):  # never tried again by itself: no lockout
                    return "yours", HINT[acct["status"]]
                if k == "signup":  # one account per site: sign in instead
                    if not pg.click(SIGNIN_RE):
                        return "yours", HINT["yours"]
                    pg.idle(1200)
                    continue
                r, hint = _sign_in(pg, wait, key, acct)
            else:
                if not create:
                    return "yours", HINT["yours"]
                if k == "login":
                    if not pg.click(CREATE_RE):
                        return "yours", HINT["yours"]
                    pg.idle(1200)
                    continue
                r, hint = _create(pg, wait, key, (acct or {}).get("login_url") or start)
            if r == "ok":
                if job_id:
                    link_job(pg.site, job_id)
                return "ok", ""
            if r not in ("verify", "again"):  # verified, or sent to sign in with your general login: the next round
                return ("offsite", "") if r == "offsite" else ("yours", hint)
        return "yours", HINT["yours"]
    except SystemExit as e:  # a refusal (left the site, no password in the keyring, a template profile): yours
        return "yours", str(e)[:300]


# ----------------------------------------------------------------------------- the account window (Re-login, Create)
_S: dict = {}  # the one account window of this process: {action, site, url, state, step, needs, answers, stop, result}
_SLOCK = threading.Lock()
LIVE_S = ("opening", "running", "needs_you")


def session_live() -> bool:
    return _S.get("state") in LIVE_S


def session() -> dict:
    return {k: _S.get(k) for k in ("action", "site", "state", "step", "needs", "result")} if _S else {}


def _busy() -> str | None:
    from . import apply_agent

    if any(apply_agent.alive(r) for r in db.live_runs() if r["state"] != "queued"):
        return "the apply agent is running in the agent's browser: wait for it (or stop it) first"
    if apply_agent._LOGIN and apply_agent._LOGIN.poll() is None:
        return "the sign-in window is open on the agent's profile: close it first"
    return None


def start(action: str, aid=None, url: str | None = None, new_driver=None, background: bool = True) -> dict:
    """Re-login (sign in with the saved account) or Create (fill a site's sign-up form) in the agent's own window, on its
    browser profile. One at a time; refused while the apply agent or the sign-in window holds the profile."""
    full_ai_check("signs in to or creates site accounts")
    if action == "relogin":
        a = get(aid)
        url, site = a["login_url"], a["site"]
    elif action == "create":
        site = site_of(url)
        a = for_site(site)
        if a and a["status"] != "pending":
            raise SystemExit(f"an account for {site} is saved already: use Re-login")
    else:
        raise SystemExit("action is relogin or create")
    if why := _busy():
        raise SystemExit(why)
    with _SLOCK:
        if session_live():
            raise SystemExit("an account window is open already: finish or close it first")
        _S.clear()
        _S.update(action=action, site=site, url=url, state="opening", step="opening the site", needs=[], answers={},
                  stop=False, result="")
    if background:
        threading.Thread(target=_session, args=(url, new_driver), daemon=True, name="lodestar-account").start()
    else:
        _session(url, new_driver)
    return session()


def _swait(pg):
    def wait(needs, until, limit: int = NEEDS_S):
        _S.update(state="needs_you", needs=needs, step=(needs[0].get("hint") or "")[:300] if needs else "")
        pg.tab.suspended = True  # you drive: the hosts rule pauses (the forbidden one never does)
        try:
            pg.tab.front()
        except Exception:
            pass
        t0 = time.monotonic()
        try:
            while True:
                if _S.get("stop"):
                    raise _Stop("closed by you")
                if pg.tab.closed:
                    raise _Stop("you closed the window")
                if pg.tab.forbidden_hit:
                    raise _Stop(f"the page tried to open {pg.tab.forbidden_hit}, which Lodestar never opens")
                if until(_S):
                    return _S
                if time.monotonic() - t0 > limit:
                    raise _Stop(f"waited {limit // 60} minutes for you")
                pg.idle(1000)
        finally:
            pg.tab.suspended = False
            _S.update(state="running", needs=[], answers={})
    return wait


def _session(url: str, new_driver=None) -> None:
    from . import apply_agent

    browser, action = None, _S.get("action")
    try:
        browser = (new_driver or apply_agent._driver)()
        tab = browser.open(url, apply_ats.hosts_for(url))
        pg = Page(tab, apply_ats.host(url))
        wait = _swait(pg)
        _S.update(state="running", step="reading the page")
        if action == "relogin" and kind(pg.inputs()) is None and pg.click(SIGNIN_RE):
            pg.idle(1200)  # a page that shows its sign-in form behind a Sign in button
        for _ in range(3):
            r, hint = handle(pg, wait, "session", create=action == "create")
            if r != "offsite":
                break
            h, u = tab.offsite
            tab.offsite = None
            wait([{"reason": "offsite", "host": h, "site": pg.site, "hint": f"the page wants to open {h}: Continue "
                   "here, or Close"}], lambda s: s["answers"].get("_continue"))
            tab.hosts.append(h)
            tab.goto(u)
        if r == "ok":
            a = for_site(pg.site)
            _S.update(state="done", result="ok", step=("signed in" if a and a["last_login"] else "no sign-in form on the "
                      "page (signed in already?)") + ": the window closed; the sign-in stays in the agent's profile")
            return
        _S.update(state="needs_you", needs=[{"reason": "login", "site": pg.site, "hint": hint}], step=hint)
        t0 = time.monotonic()  # yours: the window stays until you press Done or close it (30 minutes at most)
        while not _S.get("stop") and not tab.closed and not _S["answers"].get("_continue") and time.monotonic() - t0 < NEEDS_S:
            pg.idle(1000)
        _S.update(state="done", result="yours", step="done")
    except _Stop as e:
        _S.update(state="stopped", step=str(e))
    except (Exception, SystemExit) as e:  # background path: the window's own problem, never the server's
        log.get("accounts").warning("account window failed: %s", e)
        _S.update(state="failed", step=(str(e) or type(e).__name__).splitlines()[0][:300])
    finally:
        if browser is not None:
            browser.close()
        db.release()
        if db.con().execute("SELECT 1 FROM apply_runs WHERE state='queued'").fetchone():
            apply_agent._ensure_worker()  # a run that found the profile busy meanwhile
        db.release()


def act(target: str, action: str, ref: str = "") -> dict:
    """Your click on a waiting account step: continue | stop (the account window) | code (Fill code ID) | link (Open
    link ID) | own (I have an account). target: 'session' or 'run:<id>'."""
    from . import apply_agent

    full_ai_check("acts for you on a site account")
    if action not in ("continue", "stop", "code", "link", "own"):
        raise SystemExit("action is continue, stop, code, link or own")
    if target == "session":
        if not session_live():
            raise SystemExit("no account window is open")
        site = _S.get("site")
        if action == "continue":
            _S["answers"]["_continue"] = True
            return {"continue": True}
        if action == "stop":
            _S["stop"] = True
            return {"stop": True}
    elif m := re.fullmatch(r"run:(\d+)", str(target or "")):
        rid = int(m[1])
        if action == "continue":
            return apply_agent.continue_run(rid)
        if action == "stop":
            return apply_agent.stop()
        run = db.get_run(rid)
        if run["state"] != "needs_you" or rid not in apply_agent._OWNED:
            raise SystemExit(f"run #{rid} is not waiting in this Lodestar: do it in the agent's window yourself")
        site = next((n.get("site") for n in run["needs"] if n.get("site")), "")
        if not site:
            raise SystemExit(f"run #{rid} is not waiting on a site account step: do it in the agent's window")
    else:
        raise SystemExit("target is 'session' or 'run:<id>'")
    if action == "code" and not any(c["id"] == ref for c in codes.current()):
        raise SystemExit("that code expired: check for a new one")
    if action == "link" and apply_ats.host(codes.link_url(ref) or "") != site:
        raise SystemExit(f"that link expired or is not on {site}: Lodestar opens verification links only on the account's site")
    _REQ[target] = {"action": action, "id": str(ref)}
    return {"requested": action}


def waiting() -> list[dict]:
    """Account steps waiting for you: the account window, and apply runs stopped on a site's sign-in or sign-up."""
    from . import apply_agent

    out = []
    if _S.get("state") == "needs_you":
        out.append({"target": "session", "site": _S.get("site"), "needs": _S.get("needs") or [], "mine": True})
    for r in db.live_runs():
        if r["state"] == "needs_you" and any(n.get("site") for n in r["needs"] or []):
            out.append({"target": f"run:{r['id']}", "site": next(n["site"] for n in r["needs"] if n.get("site")),
                        "needs": r["needs"], "job_id": r["job_id"], "mine": r["id"] in apply_agent._OWNED})
    return out


def overview(q: str = "") -> dict:
    return {"accounts": listing(q), "session": session(), "waiting": waiting(), "links": codes.links(),
            "statuses": STATUSES, "general": general()}
