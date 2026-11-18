"""In-app browser (pass 52). In the desktop app, job-site links ('Search these yourself', a posting's link) open in a
second Lodestar window that you browse yourself; sign-ins stay in Lodestar's own WebView2 profile. The main window's
browser bar drives it (Back / Forward / Reload / Go) and Save this job reads the open page once, on your click, with
the extension's own reader (extension/content.js `LodestarReadPosting`), then adds it through `web.capture`, like the
extension's Capture. Lodestar never navigates, clicks, types or reads that window otherwise: it is your browser, so
the five big boards stay hands-off (`apply_agent.forbidden` is about Lodestar's own fetches and agent, not your
browsing). Outside the desktop app (`ON` false) the page opens links in the system browser as before."""
import threading
from pathlib import Path

ON = False  # desktop.open_window sets it once its window exists; never web.start_server
TITLE = "Lodestar browser"
READER = Path(__file__).resolve().parent.parent / "extension" / "content.js"
_W = None
_LOCK = threading.Lock()


def _webview():
    import webview

    return webview


def _url(url) -> str:
    from .web import http_only

    u = http_only(url)
    if not u:
        raise ValueError("only http(s) links open in the browser")
    return u


def _window():
    w = _W
    return w if w is not None and w in list(_webview().windows) else None  # a closed window leaves webview.windows


def state() -> dict:
    w = _window() if ON else None
    url = ""
    if w is not None:
        try:
            url = w.get_current_url() or ""
        except Exception:  # the window is closing
            url = ""
    return {"on": ON, "open": w is not None, "url": url}


def open_url(url) -> dict:
    """Show `url` in the browser window (made on first use, reused after). Off: {'opened': False}, the page falls back."""
    global _W
    if not ON:
        return {"opened": False} | state()
    u = _url(url)
    with _LOCK:
        w = _window()
        if w is not None:
            w.load_url(u)
        else:
            _W = _webview().create_window(TITLE, u, width=1200, height=860, min_size=(640, 480), text_select=True)
    return {"opened": True} | state()


NAV = {"back": "history.back()", "forward": "history.forward()", "reload": "location.reload()"}


def act(op: str, url=None) -> dict:
    """The browser bar's buttons, each one your click: open / go a link, back / forward / reload, save, state."""
    if op in ("open", "go"):
        return open_url(url)
    if op == "state":
        return state()
    w = _window() if ON else None
    if w is None:
        raise ValueError("the in-app browser is not open")
    if op in NAV:
        w.evaluate_js(NAV[op])
        return state()
    if op == "save":
        return save(w)
    if op == "applied":  # pass 53: you applied on this page yourself
        from . import web

        return web.mark_applied(_read(w), "in-app browser")
    if op == "keywords":  # pass 53: highlight the posting's keywords your resume misses, on this page only
        import json

        from . import web

        r = web.page_keywords(_read(w))
        w.evaluate_js(f"globalThis.LodestarMark({json.dumps(r['missing'])}, {json.dumps(r['matched'])})")
        return r
    raise ValueError(f"unknown browser op {op}")


def save(w) -> dict:
    """Save this job: the open page read once (title, link, JSON-LD posting, apply links), then a Board card."""
    from . import web

    return web.capture(_read(w))


def _read(w) -> dict:
    """The open page, read once by the extension's reader (on your click)."""
    from . import web

    if not READER.is_file():
        raise ValueError(f"the page reader is missing ({READER.name}); reinstall Lodestar from its folder")
    page = w.evaluate_js(READER.read_text(encoding="utf-8") + "\n;globalThis.LodestarReadPosting()")
    if not isinstance(page, dict) or not web.http_only(page.get("url")):
        raise ValueError("this page could not be read; open the job posting itself and try again")
    return page
