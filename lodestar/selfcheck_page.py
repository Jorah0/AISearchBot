"""The page half of `lodestar selfcheck` (pass 55). Runs in its OWN process with a throwaway LODESTAR_HOME (set by
selfcheck.page(), never your data folder) and fictional demo data, serves the real app, loads it in a headless
browser (Playwright: the e2e extra) and checks every tab: script errors, console errors, a page wider than the window,
controls without an accessible name, empty tabs. It also opens a job drawer, the email view and the AI switcher.
Writes {tabs: [...], outline: {...}} as JSON to the path in argv[1], screenshots beside it. No network, no AI."""
import json
import os
import sys
from pathlib import Path

TABS = ("home", "inbox", "mail", "board", "contacts", "search", "careers", "monitor", "profile", "studio", "answers",
        "coach", "ideas", "insights", "accounts", "tools", "setup")
PROFILE_MD = """# Jamie Rivera
Austin, TX | jamie@example.org

## Summary
Data analyst who builds dashboards and cleans data for operations teams.

## Skills
SQL, Python, Excel, Tableau

## Experience
### Data Analyst, Acme Foods (2021 - 2026)
- Built SQL reports used by 40 store managers
- Automated weekly sales dashboards in Tableau

## Education
### B.S. Statistics, Texas State University (2020)

## Preferences
Target roles: Data Analyst, Business Analyst
Locations / remote: Austin, TX or remote
"""
# every control must have a name a screen reader can say; this finds the ones that do not
UNNAMED = """() => [...document.querySelectorAll('section.on button, section.on input, section.on select, section.on textarea')]
  .filter(e => e.offsetParent !== null && e.type !== 'hidden')
  .filter(e => !(e.getAttribute('aria-label') || (e.getAttribute('aria-labelledby') && document.getElementById(e.getAttribute('aria-labelledby'))?.textContent.trim()) || e.title || (e.labels && e.labels.length) || e.placeholder
                 || (e.tagName === 'BUTTON' && e.textContent.trim()) || e.closest('label')))
  .map(e => e.id || e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : '')).slice(0, 10)"""
OUTLINE = """() => { const s = document.querySelector('section.on'); if (!s) return null;
  const vis = e => e.offsetParent !== null;
  return { title: (s.querySelector('h2') || {}).textContent || s.id,
    headings: [...s.querySelectorAll('h3, h4')].filter(vis).map(h => h.textContent.trim()).slice(0, 40),
    buttons: [...s.querySelectorAll('button')].filter(vis).map(b => b.textContent.trim() || b.getAttribute('aria-label') || '').filter(Boolean).slice(0, 80),
    fields: [...s.querySelectorAll('input, select, textarea')].filter(vis).map(e => (e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].textContent) || (e.closest('label') && e.closest('label').textContent) || e.placeholder || '(unlabelled field)').replace(/\\s+/g, ' ').trim().slice(0, 80)).slice(0, 60),
    text: s.innerText.replace(/\\s+/g, ' ').slice(0, 2500) }; }"""


def seed() -> dict:
    from . import approvals, db
    from .config import PROFILE

    PROFILE.write_text(PROFILE_MD, encoding="utf-8")
    ids = {}
    for status, company, title, loc in (("saved", "Wrenfield Bakery", "Data Analyst", "Austin, TX"),
                                         ("applied", "Juniper Rail", "Business Analyst", "Remote (US)"),
                                         ("interview", "Cobalt Clinics", "Reporting Analyst", "Dallas, TX")):
        jid = db.add_job(company, title, f"https://jobs.{company.split()[0].lower()}.example/1",
                         f"{company} needs a {title} with SQL, Python and Tableau. Strong communication.", "selfcheck",
                         location=loc)
        if status != "saved":
            db.set_status(jid, status, "selfcheck seed")
        ids[status] = jid
    db.add_mail(message_id="<selfcheck-1@cobalt.example>", direction="in", from_addr="Ann <ann@cobalt.example>",
                subject="Interview times", body="Hi Jamie, can you do Tuesday 10:00?", job_id=ids["interview"],
                category="interview", html="<p>Hi Jamie, can you do <b>Tuesday 10:00</b>?</p>")
    approvals.propose("email_reply", "send_email", {"to": "ann@cobalt.example", "subject": "Re: Interview times",
                      "body": "Tuesday works.", "in_reply_to": "<selfcheck-1@cobalt.example>", "job_id": ids["interview"]},
                      "reply to Ann", ids["interview"], force_pending=True)
    db.add_task(ids["saved"], "Ask Sam for a referral")
    return ids


def main(out: str) -> None:
    from playwright.sync_api import sync_playwright

    from . import web

    ids = seed()
    srv = web.start_server(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    shots = Path(out).with_suffix("")
    shots.mkdir(parents=True, exist_ok=True)
    report = {"tabs": [], "extra": [], "outline": {}}
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(channel="msedge")
        except Exception:  # no Edge: Playwright's own Chromium, if installed
            b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
        page.on("console", lambda m: m.type == "error" and "Content Security Policy" not in m.text
                and errors.append(f"console: {m.text[:200]}"))
        page.goto(base + "/")
        page.wait_for_function("() => typeof S !== 'undefined' && S !== null", timeout=20000)
        for tab in TABS:
            errors.clear()
            row = {"tab": tab, "problems": []}
            try:
                page.click(f'nav button[data-tab="{tab}"]')
                page.wait_for_selector(f"section#{tab}.on", timeout=10000)
                page.wait_for_timeout(700)
                wide = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                if wide > 2:
                    row["problems"].append(f"page is {wide}px wider than the window (sideways scroll)")
                if unnamed := page.evaluate(UNNAMED):
                    row["problems"].append("controls without a name: " + ", ".join(unnamed))
                if not page.evaluate("() => document.querySelector('section.on').innerText.trim().length > 40"):
                    row["problems"].append("the tab is (nearly) empty")
                report["outline"][tab] = page.evaluate(OUTLINE)
                page.screenshot(path=str(shots / f"{tab}.png"), full_page=True)
            except Exception as e:  # noqa: BLE001
                row["problems"].append(f"could not open the tab: {str(e)[:200]}")
            row["problems"] += list(dict.fromkeys(errors))
            report["tabs"].append(row)
        for name, js in (("job drawer", f"openJob({ids['saved']})"), ("AI switcher", "aiSwitchToggle(true)"),
                         ("mail view", "go('mail')")):
            errors.clear()
            try:
                page.evaluate(js)
                page.wait_for_timeout(1200)
                if name == "mail view":
                    page.locator(".mvrow", has_text="Interview times").first.click()
                    page.wait_for_selector("#mvRead iframe.mailhtml", timeout=8000)
                page.screenshot(path=str(shots / f"{name.replace(' ', '_')}.png"))
                report["extra"].append({"part": name, "problems": list(dict.fromkeys(errors))})
            except Exception as e:  # noqa: BLE001
                report["extra"].append({"part": name, "problems": [f"failed: {str(e)[:200]}"] + errors})
            page.keyboard.press("Escape")
        b.close()
    srv.shutdown()
    Path(out).write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if not os.environ.get("LODESTAR_SELFCHECK_HOME"):  # only ever in the throwaway home selfcheck.page() made
        raise SystemExit("run this through `lodestar selfcheck`, not directly")
    main(sys.argv[1])
