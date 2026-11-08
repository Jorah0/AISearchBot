# Browser capture

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
