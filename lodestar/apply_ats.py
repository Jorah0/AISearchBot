"""The apply agent's browser layer (docs/APPLY_AGENT.md): its own Edge / Chrome window on a dedicated profile, the
navigation guard, the page scan and the one write path. Playwright is imported lazily (open_browser), so everything
else here imports and tests without it. Nothing here hides automation: no stealth, no user-agent or webdriver changes,
no CAPTCHA solving (tests/test_apply_engine.Static).

Page text is untrusted data. The scan runs in the page's main world (extension/matcher.js + content.js in agent mode),
so its output is only a hint: apply_agent.build_plan makes every safety decision in Python, writes go only to planned
items in frames whose host the run allows, and clicks only to buttons whose text matches a fixed pattern here.
"""
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"  # matcher.js + content.js: the source checkout (apply_agent.available says so when missing)
# application systems the agent knows (exact registrable host patterns). The agent opens a job's own link by itself
# only on these; any other site needs the link you pasted (apply_url), and then only in stop mode.
ATS = {
    "greenhouse": r"(?:^|\.)greenhouse\.io$", "lever": r"(?:^|\.)lever\.co$", "ashby": r"(?:^|\.)ashbyhq\.com$",
    "smartrecruiters": r"(?:^|\.)smartrecruiters\.com$", "workable": r"(?:^|\.)workable\.com$",
    "workday": r"(?:^|\.)myworkday(?:jobs|site)?\.com$", "icims": r"(?:^|\.)icims\.com$", "taleo": r"(?:^|\.)taleo\.net$",
}
SIBLINGS = {"greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io")}  # one board, two hosts
NEXT_RE = re.compile(r"^(?:next|continue|save (?:and|&) continue|review(?: application)?)\b", re.I)
SUBMIT_RE = re.compile(r"^(?:submit(?: (?:my |your )?application)?|send application|apply|apply now|finish)$", re.I)
THIRD_PARTY_RE = re.compile(r"linkedin|indeed|glassdoor|ziprecruiter|google|facebook|apple|seek|autofill", re.I)
CONFIRM_RE = re.compile(r"thank(?:s| you) for (?:applying|your application|your interest)|application (?:has been |was )?"
                        r"(?:submitted|received)|we(?:'ve| have) received your application", re.I)
APPLIED_RE = re.compile(r"you(?:'ve| have) already applied|already submitted an application", re.I)
CODE_RE = re.compile(r"verify (?:that )?you(?:'re| are) (?:a )?human|security code|verification code|enter the code "
                     r"(?:we|that was) sent|one-time (?:pass)?code", re.I)
REF_RE = re.compile(r"(?:confirmation|reference|application)\s*(?:number|no\.?|#|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.I)
CHALLENGE = ('iframe[src*="recaptcha/api2/bframe"], iframe[src*="recaptcha/enterprise/bframe"], iframe[src*="hcaptcha.com"], '
             'iframe[src*="challenges.cloudflare.com"]')
BUTTONS = 'button, input[type="submit"], input[type="button"], [role="button"], a[role="button"]'
CAPS = {"label": 300, "option": 100, "options": 200, "value": 4000}  # untrusted page strings, capped


class ProfileBusy(Exception):
    """The browser profile is open in another window (the sign-in window, or another Lodestar's agent)."""


def host(url) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def ats_of(h: str) -> str | None:
    h = host(h) if "/" in str(h) else str(h or "").lower()
    return next((n for n, rx in ATS.items() if re.search(rx, h)), None)


def hosts_for(url: str) -> list[str]:
    """A run's allowed main-frame hosts: the apply link's exact host, plus its ATS's sibling hosts. Never a registrable
    domain (no public suffix list: careers-acme.azurewebsites.net must not allow every *.azurewebsites.net)."""
    h = host(url)
    return list(dict.fromkeys([h, *SIBLINGS.get(ats_of(h) or "", ())]))


def decide(url: str, app_main: bool, hosts, suspended: bool, forbidden) -> str:
    """The guard's verdict for one navigation request: 'forbidden' (always aborted, in every page and frame, handoff
    or not), 'offsite' (an application tab's main frame leaving the run's hosts: aborted, the run asks you), or 'ok'."""
    h = host(url)
    if forbidden(h):
        return "forbidden"
    if app_main and not suspended and urlparse(url).scheme in ("http", "https") and h not in hosts:
        return "offsite"
    return "ok"


def _clip(d: dict) -> dict:
    """A scan descriptor with page strings capped (labels 300, options 100 x 200, values 4000)."""
    out = {k: (v[:CAPS["label"]] if isinstance(v, str) else v) for k, v in d.items() if k != "options"}
    out["value"] = str(d.get("value") or "")[:CAPS["value"]]
    out["options"] = [{"v": str(o.get("v", ""))[:CAPS["option"]], "t": str(o.get("t", ""))[:CAPS["option"]]}
                      for o in (d.get("options") or [])[:CAPS["options"]] if isinstance(o, dict)]
    return out


_VALUES = """els => { const out = {}; for (const el of els) { const i = el.getAttribute('data-lodestar-i'), t = (el.type || '').toLowerCase();
  if (t === 'radio') { if (el.checked) out[i] = el.value; else if (!(i in out)) out[i] = ''; }
  else if (t === 'checkbox') out[i] = String(el.checked);
  else if (t === 'file') out[i] = [...(el.files || [])].map(f => f.name).join(',');
  else if ('value' in el && el.tagName !== 'BUTTON') out[i] = String(el.value);
  else out[i] = (el.textContent || '').replace(/\\s+/g, ' ').trim(); } return out; }"""
_BUTTONS = """els => els.map((el, k) => { el.setAttribute('data-lodestar-b', String(k)); const r = el.getBoundingClientRect();
  return { b: k, text: (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
  shown: r.width > 2 && r.height > 2 && getComputedStyle(el).visibility !== 'hidden' && !el.disabled }; })"""


class Tab:
    """One application tab. Every write takes a plan item (write); clicks go only to buttons found by text (button)."""

    def __init__(self, page, hosts):
        self.page, self.hosts = page, list(hosts)
        self.suspended = False  # while a run waits on you (sign-in, a code): the hosts rule pauses, forbidden never
        self.offsite = None  # (host, url) of a refused main-frame navigation, for the run to ask about
        self.forbidden_hit = None  # a forbidden host the guard refused in this tab
        self.accept_confirm = False  # set for 5 s after the approved Submit click
        self._frames = []

    # --- reading
    @property
    def url(self) -> str:
        return self.page.url

    @property
    def closed(self) -> bool:
        return self.page.is_closed()

    def host(self) -> str:
        return host(self.page.url)

    def _allowed_frames(self):
        return [f for f in self.page.frames if host(f.url) in self.hosts]

    def scan(self) -> list[dict]:
        """Descriptors of every field in the frames whose host the run allows (untrusted: see the module doc)."""
        js = "(() => {" + (EXT / "matcher.js").read_text(encoding="utf-8") + (EXT / "content.js").read_text(encoding="utf-8") + \
             "; return LodestarScan({agent: true}); })()"
        out, self._frames = [], []
        for frame in self._allowed_frames():
            try:
                r = frame.evaluate(js)
            except Exception:  # a frame that navigated away mid-scan
                continue
            self._frames.append(frame)
            for d in (r or {}).get("fields") or []:
                if isinstance(d, dict):
                    out.append(_clip(d) | {"frame": len(self._frames) - 1})
        return out[:400]

    def values(self) -> dict:
        """{'frame:i': current value} for every scanned field (read back after writing, and right before Submit)."""
        out = {}
        for n, frame in enumerate(self._frames):
            try:
                vals = frame.locator("[data-lodestar-i]").evaluate_all(_VALUES)
            except Exception:
                continue
            out |= {f"{n}:{i}": str(v)[:CAPS["value"]] for i, v in vals.items()}
        return out

    def text(self, limit: int = 20000) -> str:
        parts = []
        for f in self._allowed_frames() or [self.page.main_frame]:
            try:
                parts.append(f.locator("body").inner_text(timeout=5000))
            except Exception:
                continue
        return "\n".join(parts)[:limit]

    def blocker(self) -> str | None:
        """captcha | code | login when a challenge, a code request or a sign-in page shows; invisible reCAPTCHA is
        not one (and is never touched)."""
        try:
            for el in self.page.locator(CHALLENGE).all():
                if el.is_visible() and (box := el.bounding_box()) and box["width"] > 10 and box["height"] > 10:
                    return "captcha"
            for f in self._allowed_frames():
                if f.locator('input[type="password"]').filter(visible=True).count():
                    return "login"
                if f.locator('input[autocomplete="one-time-code"]').filter(visible=True).count():
                    return "code"
        except Exception:
            return None
        return "code" if CODE_RE.search(self.text()) else None

    def errors(self) -> list[str]:
        out = []
        for f in self._allowed_frames():
            try:
                for el in f.locator('[role="alert"], [aria-invalid="true"]').filter(visible=True).all()[:20]:
                    t = (el.get_attribute("aria-label") if el.get_attribute("aria-invalid") == "true" else el.inner_text()) or ""
                    out.append(" ".join(t.split())[:200] or "a field is marked invalid")
            except Exception:
                continue
        return list(dict.fromkeys(out))

    def confirmed(self) -> str | None:
        """The confirmation page's text (<= 4000 chars) when the page says the application went in, else None."""
        t = self.text()
        return t[:4000] if CONFIRM_RE.search(t) or re.search(r"/(?:confirmation|thank-?you)\b", urlparse(self.url).path) else None

    def already_applied(self) -> bool:
        return bool(APPLIED_RE.search(self.text()))

    def buttons(self) -> list[dict]:
        out = []
        for n, frame in enumerate(self._allowed_frames()):
            try:
                out += [b | {"frame": n} for b in frame.locator(BUTTONS).evaluate_all(_BUTTONS) if b["shown"] and b["text"]]
            except Exception:
                continue
        return out

    def button(self, kind: str) -> dict | None:
        """The one visible 'next' or 'submit' button (by its text), or None (none, or more than one: ambiguous)."""
        rx = NEXT_RE if kind == "next" else SUBMIT_RE
        hits = [b for b in self.buttons() if rx.search(b["text"]) and not THIRD_PARTY_RE.search(b["text"])]
        return hits[0] if len({b["text"].lower() for b in hits}) == 1 else None

    # --- acting
    def _host_ok(self) -> bool:
        return self.host() in self.hosts and not self.forbidden_hit

    def click(self, b: dict) -> None:
        if THIRD_PARTY_RE.search(b["text"]) or not self._host_ok():
            raise SystemExit(f"refused to click {b['text'][:40]!r} here")
        self._allowed_frames()[b["frame"]].locator(f'[data-lodestar-b="{int(b["b"])}"]').click()

    def write(self, item: dict) -> bool:
        """The one write path: a planned item with status fill (or a consent box after approval). True when written."""
        if not self._host_ok() or item.get("status") not in ("fill", "consent"):
            return False
        frame = self._frames[item["frame"]]
        loc = frame.locator(f'[data-lodestar-i="{int(item["i"])}"]')
        if (loc.first.get_attribute("type") or "").lower() == "password":
            raise SystemExit("refused: the agent never types into a password field")
        kind, v = item["kind"], item["value"]
        if kind == "text":
            cur = loc.input_value()
            if cur and cur != item.get("prev"):  # yours (typed in the window) or the form's own: never overwritten
                return False
            loc.fill(str(v))
        elif kind == "select":
            loc.select_option(value=str(v))
        elif kind == "radio":
            for k in range(loc.count()):
                if loc.nth(k).get_attribute("value") == str(v):
                    loc.nth(k).check()
                    break
            else:
                return False
        elif kind == "check":
            loc.set_checked(bool(v))
        elif kind == "file":
            loc.set_input_files(str(v))
        else:
            return False
        return True

    def shot(self, path) -> None:
        self.page.screenshot(path=str(path), full_page=True)

    def idle(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)  # never time.sleep: route and dialog handlers keep running

    def front(self) -> None:
        self.page.bring_to_front()

    def goto(self, url: str) -> None:
        self.page.goto(url)


class Browser:
    """The agent's browser: one persistent context on the agent profile, the guard on every request it makes."""

    def __init__(self, pw, context, forbidden):
        self.pw, self.context, self.forbidden = pw, context, forbidden
        self.tabs = {}  # page -> Tab
        context.route("**/*", self._route)
        context.set_default_timeout(15_000)
        context.set_default_navigation_timeout(45_000)

    def _route(self, route, request):
        try:
            if not request.is_navigation_request():
                return route.continue_()
            try:  # Playwright: request.frame throws for a popup's first navigation and for service-worker requests
                frame = request.frame
                tab = self.tabs.get(frame.page) if frame.parent_frame is None else None
            except Exception:
                tab = None
            verdict = decide(request.url, tab is not None, tab.hosts if tab else (), bool(tab and tab.suspended),
                             self.forbidden)
            if verdict == "ok":
                return route.continue_()
            if tab:
                if verdict == "forbidden":
                    tab.forbidden_hit = host(request.url)
                else:
                    tab.offsite = (host(request.url), request.url)
            return route.abort("blockedbyclient")
        except Exception:
            try:
                route.abort("blockedbyclient")  # fail closed
            except Exception:
                pass

    def open(self, url: str, hosts) -> Tab:
        page = next((p for p in self.context.pages if p.url == "about:blank" and p not in self.tabs), None) or self.context.new_page()
        tab = Tab(page, hosts)
        self.tabs[page] = tab

        def navigated(frame):  # belt and braces: pushState and anything the route did not see
            if frame == page.main_frame:
                h = host(frame.url)
                if self.forbidden(h):
                    tab.forbidden_hit = h
                elif h and not tab.suspended and h not in tab.hosts and urlparse(frame.url).scheme in ("http", "https"):
                    tab.offsite = (h, frame.url)

        def dialog(d):
            try:
                d.accept() if tab.accept_confirm and d.type == "confirm" else d.dismiss()
            except Exception:
                pass
        page.on("framenavigated", navigated)
        page.on("dialog", dialog)
        try:
            page.goto(url)
        except Exception:
            if not (tab.offsite or tab.forbidden_hit):  # a refused hop is the run's to ask about, not a crash
                raise
        return tab

    def pages(self) -> list:
        try:
            return [p for p in self.context.pages if not p.is_closed()]
        except Exception:
            return []

    def idle(self, ms: int) -> None:
        pages = self.pages()
        if pages:
            pages[0].wait_for_timeout(ms)
        else:
            import time

            time.sleep(ms / 1000)

    def close(self) -> None:
        for step in (self.context.close, self.pw.stop):
            try:
                step()
            except Exception:
                pass


def channel_for(binary: str | None) -> dict:
    """Playwright launch options for the browser binary resume._browser found: the documented channel for branded Edge
    and Chrome (Playwright finds the install), else the binary itself."""
    b = str(binary or "").lower()
    if "msedge" in b or "microsoft edge" in b:
        return {"channel": "msedge"}
    if "chrome" in b and "chromium" not in b:
        return {"channel": "chrome"}
    return {"executable_path": binary} if binary else {}


# DNS-level block of the forbidden boards in the agent's browser: Playwright's route never sees a server redirect's next
# hop (checked: V5 in docs/APPLY_AGENT.md), so a redirect to linkedin.com must fail to resolve instead. Over-blocks
# lookalikes on purpose. A system proxy resolves names itself: then the route and the post-navigation check remain.
BLOCK_RULES = [f"MAP {p} ~NOTFOUND" for p in ("*linkedin.*", "*indeed.*", "*glassdoor.*", "*ziprecruiter.*", "*simplyhired.*",
                                              "lnkd.in", "*.lnkd.in")]


def open_browser(profile_dir, forbidden, headless: bool = False, launch: dict | None = None, resolver=()) -> Browser:
    """Launch the agent's browser on profile_dir (lazy Playwright import). Headful unless a test or dry run asks; slow_mo
    only so you can follow along. Service workers are blocked: a route never sees what a worker intercepts.
    resolver: test-only extra host-resolver rules (MAP * 127.0.0.1 keeps fictional fixture hosts on this machine)."""
    from playwright.sync_api import sync_playwright

    if launch is None:
        from .resume import _browser

        launch = channel_for(_browser())
    pw = sync_playwright().start()
    try:
        ctx = pw.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, slow_mo=0 if headless else 100, viewport=None if not headless else
            {"width": 1280, "height": 900}, accept_downloads=False, service_workers="block",
            args=["--disable-sync", "--host-resolver-rules=" + ", ".join([*BLOCK_RULES, *resolver])], **launch)
    except Exception as e:
        pw.stop()
        msg = str(e)
        if "already in use" in msg or "existing browser session" in msg:
            raise ProfileBusy("the agent's browser profile is in use: close the sign-in window (or another Lodestar "
                              "running the agent; on Windows also Edge's background processes on it) first") from None
        raise
    return Browser(pw, ctx, forbidden)
