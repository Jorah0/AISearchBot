"""The CAPTCHA auto-solver (pass 57, policy 17.2): when the apply agent or the sign-in flow meets a challenge widget,
Lodestar tries to clear it with the vision AI before handing it to the user. The model is your local Ollama first, then
your primary AI (ai.ask_image -> ai.vision_provider): the user asked for a local model as the primary method of solving.

The contract the page object satisfies (apply_ats.Tab and accounts.Page both do it; the tests fake it, so the solver is
fully unit-testable with no browser):
    captcha()          -> a challenge descriptor {"type": kind, "screenshot": bytes, "hint": str} or None (no widget);
    captcha_do(kind, answer) -> perform the model's answer (kind: 'type' | 'drag' | 'click', best effort);
    captcha_solved()   -> positive evidence the check is cleared (the widget's own response field holds a token).

The no-spam contract (the user asked for this explicitly):
- A tool (settings captcha_solver, on). Off = every CAPTCHA is handed to you, exactly as before.
- A daily cap (pref captcha_daily_max) on how many solves Lodestar performs, and a per-widget stop
  (pref captcha_max_attempts): after the last attempt it stops and hands the widget to you, never looping.
- A failed solve ends in the same user handoff the agent used to do. It never types a password, never touches a
  forbidden board, and a type it cannot drive (Turnstile, Arkose, ...) is handed to you, not spammed.
Nothing here hides automation: the solver drives the page's own widgets the way a person would (click, type, drag).
"""
import re

from . import ai, db, settings

CHECKBOX = ("checkbox",)  # a one-click check, no AI needed


def enabled() -> bool:
    return settings.enabled("captcha_solver")


def _cap() -> int:
    return max(0, int(settings.pref("captcha_daily_max")))


def _attempts() -> int:
    return max(1, int(settings.pref("captcha_max_attempts")))


def left() -> int:
    """Solves left today (the no-spam daily cap); 0 when the cap is reached or the solver is off."""
    if not enabled():
        return 0
    return max(0, _cap() - db.meta_get("quota:captcha"))


def _take() -> bool:
    """Claim one solve for today; False when the cap is already used (the budget is never negative)."""
    return bool(_cap() and db.quota("captcha", _cap()))


def model() -> str | None:
    """The vision model id to name (pref captcha_model), else None (the provider's own vision model)."""
    return str(settings.pref("captcha_model") or "").strip() or None


def _prompt(kind: str, hint: str) -> str:
    """The one question the model answers, by the challenge's kind (the repo's proven prompts, local-model friendly)."""
    if kind in ("text", "complicated_text"):
        return "Act as a blind person's assistant. Read the text from the CAPTCHA in the image and reply with only " \
               "that text: letters and numbers, no spaces, no punctuation, no words of your own. If there is no " \
               "text, reply empty."
    if kind in ("puzzle", "geetest", "slider"):
        return "This is a slide-to-fit CAPTCHA. Estimate the horizontal pixels to drag the slider so the puzzle " \
               "piece fits its slot. Reply with only an integer from 0 to 300, no units, no explanation."
    if kind in ("image", "recaptcha", "select"):
        return "Read the instruction bar in this CAPTCHA image (e.g. 'Select all squares with a bicycle'). Then look " \
               "at the grid of tiles in the same image and reply with only the 0-based indices of the tiles that " \
               "clearly contain that object, separated by commas, e.g. 2,5,7. If the instruction is 'skip', reply 0."
    return "Read the CAPTCHA in the image and give the single answer a person would type or select. Reply with only " \
           "that answer."


def _answer(kind: str, raw: str) -> object | None:
    """Normalize the model's raw text to the kind's answer ('type' -> str, 'drag' -> int, 'click' -> list[int]);
    None when it is unusable (a bad answer is a failure, not a guess)."""
    raw = (raw or "").strip()
    if kind in ("puzzle", "geetest", "slider"):
        m = re.search(r"\d+", raw)
        if not m:
            return None
        return max(0, min(300, int(m.group(0))))
    if kind in ("image", "recaptcha", "select"):
        idx = [int(x) for x in re.findall(r"\d+", raw)]
        return idx or None
    if kind in CHECKBOX:
        return "click"
    return re.sub(r"[^A-Za-z0-9]", "", raw) or None


def _kind_action(kind: str) -> str:
    """The page object's action for a kind: 'type' | 'drag' | 'click' (a click for a one-check widget)."""
    if kind in ("puzzle", "geetest", "slider"):
        return "drag"
    if kind in ("image", "recaptcha", "select"):
        return "click"
    if kind in CHECKBOX:
        return "click"
    return "type"


def _can_drive(kind: str) -> bool:
    """A type the solver knows how to clear. Turnstile / Arkose / Friendly have no reliable path: handed to the user."""
    return kind in ("text", "complicated_text", "puzzle", "geetest", "slider", "image", "recaptcha", "select", "checkbox")


def solve(page) -> dict:
    """Solve the page's visible CAPTCHA, within the no-spam caps.
    {result: solved | failed | unavailable | capped, type, attempts, reason}.
    solved: the page's own evidence says it is cleared. The other results mean the caller hands it to the user
    (it stops, never retries by itself)."""
    if not enabled():
        return {"result": "unavailable", "type": "", "attempts": 0, "reason": "the captcha_solver tool is off"}
    try:
        info = page.captcha()
    except Exception:
        info = None
    if not info:
        return {"result": "unavailable", "type": "", "attempts": 0, "reason": "no visible challenge"}
    kind = str(info.get("type") or "unknown")
    if not _can_drive(kind):
        return {"result": "unavailable", "type": kind, "attempts": 0,
                "reason": f"Lodestar does not drive {kind} checks: solve it in the agent window, then press Continue"}
    if not left():
        return {"result": "capped", "type": kind, "attempts": 0,
                "reason": f"today's solve cap is reached ({_cap()}): this one is yours to solve in the agent window"}
    made = 0
    for i in range(_attempts()):
        made = i + 1
        if not _take():
            return {"result": "capped", "type": kind, "attempts": made,
                    "reason": "today's solve cap is reached: this one is yours to solve in the agent window"}
        action = _kind_action(kind)
        if action == "click" and kind in CHECKBOX:  # a one-check widget: no AI, just the click
            page.captcha_do(kind, "click")
        else:
            try:
                raw = ai.ask_image(_prompt(kind, info.get("hint") or ""), info.get("screenshot") or b"",
                                   provider=ai.vision_provider(), model=model())
            except (SystemExit, Exception) as e:  # no vision AI, a rejected model, or a page error: it is yours
                return {"result": "unavailable", "type": kind, "attempts": made,
                        "reason": f"the vision AI could not answer ({str(e)[:120]}): solve the check in the agent "
                                  "window, then press Continue"}
            if (ans := _answer(kind, raw)) is None:
                return {"result": "failed", "type": kind, "attempts": made,
                        "reason": "the AI gave no usable answer: solve the check in the agent window, then press Continue"}
            try:
                page.captcha_do(kind, ans)
            except Exception:
                pass
        try:
            if page.captcha_solved():
                return {"result": "solved", "type": kind, "attempts": made, "reason": "solved by the AI"}
        except Exception:
            pass
    return {"result": "failed", "type": kind, "attempts": made,
            "reason": f"the AI tried {made} time(s) and the check is still pending: solve it in the agent window, "
                      "then press Continue"}
