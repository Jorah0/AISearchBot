"""The auto sign-on toolset (pass 57): for a website login/sign-in, Lodestar signs you in with your saved account
(password manager, `accounts`) and, if a CAPTCHA stands in the way, clears it with the auto-solver (`captcha`) before
the site's own next step. It is the "sign-in and continue" path the apply agent uses on a sign-in or sign-up form.

The no-spam contract the user asked for (this is the hard part):
- It only ever acts on a site that already has a saved account; a site without one is handed to you (never a guess,
  never a credential it does not hold).
- At most `login_max_failures` (default 2) failed sign-ins per site: after that it STOPS and waits for you to finish
  the login in the agent window. A failed or locked account is never retried by itself (the existing accounts rule).
- A CAPTCHA on the way is auto-solved within the solver's own caps (captcha.solve); if it cannot be solved, the
  sign-in stops and is yours, not retried.
- One credential attempt per call: the apply agent loop is the only caller, so it cannot loop a login into the site.
- Nothing touches a forbidden board (LinkedIn / Indeed / Glassdoor / ZipRecruiter / SimplyHired); those are refused
  before anything is typed (apply_agent.forbidden).
The Page is the accounts.Page interface (inputs / type / click / blocker / text / link / goto / tab) or any object
that answers it (the tests' FakePage): the password goes only into a password field, and only on the account's host.
"""
from . import accounts, captcha, db, settings


def enabled() -> bool:
    return settings.enabled("signon")


def max_failures() -> int:
    return max(1, int(settings.pref("login_max_failures")))


def failures(site: str) -> int:
    """Failed sign-ins Lodestar has made on this site (0-...); the count that trips the two-strike lockout."""
    return db.meta_get(f"signon:fail:{site}")


def _bump(site: str) -> int:
    n = failures(site) + 1
    db.meta_set(f"signon:fail:{site}", n)
    return n


def clear(site: str) -> None:
    """A signed-in site resets its failed-sign-in count (a later wrong password starts fresh)."""
    db.meta_set(f"signon:fail:{site}", None)


def locked_out(site: str) -> bool:
    return failures(site) >= max_failures()


def _verdict(pg) -> str:
    """ok | captcha | failed | locked | pending from the page right now (accounts' fixed patterns, never the page's
    own labels deciding what is a login)."""
    if pg.blocker() == "captcha":
        return "captcha"
    t = pg.text()
    if accounts.LOCKED_RE.search(t):
        return "locked"
    if accounts.FAILED_RE.search(t):
        return "failed"
    if accounts.kind(pg.inputs()) is None:  # no sign-in form left: signed in
        return "ok"
    return "pending"


def _try(pg, acct) -> str:
    """One credential attempt: type the username and password (password only into a password field, on the host),
    press Sign in, and read the verdict. SystemExit = a refusal (left the site, no password): yours."""
    ins = pg.inputs()
    pw = accounts._secret(acct)
    if u := accounts._user(ins):
        pg.type(u, acct["username"])
    pg.type(next(d for d in ins if d["type"] == "password"), pw, secret=True)
    if not pg.click(accounts.SIGNIN_RE):
        return "yours"
    return _verdict(pg)


def _solve_first(pg, site) -> str | None:
    """A CAPTCHA on the way: auto-solve it (within the solver's caps); None when it is cleared, else the stop reason."""
    r = captcha.solve(pg)
    if r["result"] == "solved":
        return None
    return r["reason"] or "solve the check in the agent window, then press Continue"


def login(pg, site: str, job_id: int | None = None) -> dict:
    """Sign in on site with the saved account, auto-clearing any CAPTCHA, under the no-spam contract.
    {result: ok | failed | locked | captcha | yours | unavailable, reason}. At most login_max_failures (2) failed
    sign-ins are tried, then it stops and waits for you (the counter, not the account's status, is the authority, so
    the second allowed attempt can still happen). The caller (the apply agent) hands anything that is not 'ok' to the
    user; it never retries a 'locked' or 'captcha' result by itself."""
    if not enabled():
        return {"result": "unavailable", "reason": "the signon tool is off (Tools)"}
    acct = accounts.for_site(site)
    if acct is None or acct["status"] == "pending":
        return {"result": "yours", "reason": f"no saved login for {site}: add it under Accounts > Site accounts, or "
                                             "sign in in the agent window"}
    if acct["status"] == "locked":
        return {"result": "locked", "reason": "this account is locked: reset the password on the site, store the new "
                                              "one under Accounts > Site accounts, then sign in in the agent window"}
    if locked_out(site):
        return {"result": "locked", "reason": f"{max_failures()} failed sign-in(s): please finish the login in the "
                                              "agent window before Lodestar tries again"}
    try:
        if pg.blocker() == "captcha":
            if reason := _solve_first(pg, site):
                return {"result": "captcha", "reason": reason}
        v = _try(pg, acct)
    except SystemExit as e:  # left the host, no password in the keyring, ambiguous button: yours, never a crash
        return {"result": "yours", "reason": str(e)[:180]}
    if v == "captcha":
        if reason := _solve_first(pg, site):
            return {"result": "captcha", "reason": reason}
        v = _verdict(pg)
    if v == "ok":
        clear(site)
        accounts._mark(site, "active", error=None, login=True)
        if job_id:
            accounts.link_job(site, job_id)
        return {"result": "ok", "reason": "signed in"}
    if v in ("failed", "locked"):
        try:  # the site's own line, for the drawer / history (never the password)
            accounts._mark(site, "failed" if v == "failed" else "locked",
                           error=accounts._said(pg.text(), accounts.FAILED_RE if v == "failed" else accounts.LOCKED_RE),
                           reset=pg.link(accounts.FORGOT_RE))
        except (SystemExit, Exception):
            pass
        if _bump(site) >= max_failures():  # the two-strike: stop and wait for you
            return {"result": "locked", "reason": f"the saved password did not work after {max_failures()} sign-in(s): "
                                                  "please finish the login in the agent window; Lodestar will not try "
                                                  "again until you do"}
        return {"result": "failed", "reason": "the saved password did not work: try the login again in the agent "
                                              "window, or reset it on the site and store the new one under "
                                              "Accounts > Site accounts"}
    return {"result": "yours", "reason": "Lodestar could not press a single Sign in button: press it in the agent "
                                         "window, then Continue"}


def forget(site: str) -> dict:
    """Drop the failed-sign-in count (and the saved account) so the site is handed to you cleanly."""
    clear(site)
    return {"site": site, "cleared": True}
