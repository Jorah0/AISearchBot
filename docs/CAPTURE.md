# Browser capture

## The browser extension (recommended)

The `extension/` folder of the repo is a Manifest V3 extension for Edge and Chrome (load unpacked; no store). Pair it
once from **Setup** > **Browser extension** (a `<port>-<code>` string, 5 minutes, single use), then use its two
buttons on any posting or application form. Setup's guide ([SETUP.md](SETUP.md#browser-extension)) covers install,
pairing, what Fill sends and the EEO / desired-salary conventions.

- **Capture this posting** reads the page title, URL, your selection or the main text, and the page's schema.org
  `JobPosting` data (company, location, date posted, pay, description) and posts them to `POST /api/ext/capture`.
- **Fill this form** posts the labels of the form's questions to `POST /api/ext/autofill` and fills the empty fields
  it can classify with what comes back. It never clicks, submits, navigates or ticks a checkbox; radios, dropdown
  widgets, files and dates are listed as "needs you".
- **Never on LinkedIn**: its User Agreement (section 8.2) bans browser plugins and add-ons that scrape or copy its
  site. The extension does nothing there and the server refuses LinkedIn URLs on the extension routes.
- **Credential**: pairing returns a per-browser secret once; every later request carries
  `X-Lodestar-Ext: <id>.<unix ts>.<hex HMAC-SHA256(secret, "<ts>\n<METHOD>\n<port>\n<path>\n" + body)>` from the
  Origin that paired (`chrome-extension://<id>`), within 120 seconds. `<port>` is the port the popup dialled; the
  server checks it against the port it listens on, and the ping's proof is `HMAC(secret, "pong\n<ts>\n<port>")`, so a
  program squatting one of the scanned ports can neither relay the popup's calls to the real Lodestar nor pass the
  real proof off as its own. The routes send no CORS headers, take no page token and the secret works nowhere else. Verified in Edge 157 and Chromium 158 (2026-11-11): extension pages send
  `Origin: chrome-extension://<id>`, a JSON POST with the custom header goes out without a preflight, and no Local
  Network Access prompt appears (a web page's request to 127.0.0.1 is held for that prompt).

## Bookmarklets (fallback)

Bookmarklets stay on until a browser extension is paired, then turn off: their token sits in a `javascript:` URL that
the page they run on can read. Setup > Browser extension > Bookmarklets sets auto, on or off. Chrome's Local Network
Access prompt may ask on each site before a bookmarklet can reach Lodestar.

LinkedIn and Indeed have no public API, so the fastest way to get a posting into lodestar is from the tab you already
have open. With Lodestar running, drag the **Capture** bookmarklet from the Setup tab to your bookmarks bar. It already
holds this server's address and your capture token (`~/.lodestar/capture.token`). To build one by hand, use the code
below with `PORT` set to the port in the Lodestar address bar and `TOKEN` set to the contents of capture.token:

```javascript
javascript:(()=>{const t=document.title,u=location.href,d=(document.querySelector('main')||document.body).innerText.slice(0,12000);fetch('http://127.0.0.1:PORT/api/capture?t=TOKEN',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,url:u,desc:d})}).then(r=>r.json()).then(r=>alert(r.error?('Lodestar: '+r.error):('Lodestar tracked #'+r.id+': '+r.company+' - '+r.title))).catch(e=>alert('Lodestar UI not running? '+e))})();
```

Without `?t=TOKEN` the server answers 403. The token survives restarts; delete `capture.token` to revoke it, then
re-drag the bookmarklets.

What happens: the page title, URL and visible text are posted to the local UI. lodestar splits the title into role and
company (LinkedIn titles look like `Role - Company | LinkedIn`, `(3) Role | Company | LinkedIn` or
`Company hiring Role in City | LinkedIn`, Indeed `Role - Company - City | Indeed.com`; Remote / Hybrid is never taken
as the company), stores
the text as the job description, and the card appears on the Board. Fix the company or title on the card if the split
guessed wrong, then run Gap to see whether it is worth applying.

Nothing is scraped or automated on the site itself; it is a copy of what is already on your screen.

## Autofill, not auto-submit

The Setup tab also has an **Autofill** bookmarklet. On an application form it fetches your contact details and links
from `/api/autofill` (profile.md, falling back to the profile bank), fills empty fields using Greenhouse, Lever,
Workday, Ashby and SmartRecruiters selectors and then label matching, and stops. Review everything and submit yourself.
