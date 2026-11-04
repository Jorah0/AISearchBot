# Browser capture

LinkedIn and Indeed have no public API, so the fastest way to get a posting into lodestar is from the tab you already
have open. With `lodestar ui` running, drag the bookmarklet from the UI's Setup tab to your bookmarks bar, or create a
bookmark whose URL is:

```javascript
javascript:(()=>{const t=document.title,u=location.href,d=(document.querySelector('main')||document.body).innerText.slice(0,12000);fetch('http://127.0.0.1:8765/api/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,url:u,desc:d})}).then(r=>r.json()).then(r=>alert(r.error?('lodestar: '+r.error):('lodestar tracked #'+r.id+': '+r.company+' - '+r.title))).catch(e=>alert('lodestar UI not running? '+e))})();
```

What happens: the page title, URL and visible text are posted to the local UI. lodestar splits the title into role and
company (LinkedIn titles look like `Role - Company | LinkedIn`, Indeed `Role - Company - City | Indeed.com`), stores
the text as the job description, and the card appears on the Board. Fix the company or title on the card if the split
guessed wrong, then run Gap to see whether it is worth applying.

Nothing is scraped or automated on the site itself; it is a copy of what is already on your screen.

## Autofill, not auto-submit (roadmap)

The next step is a companion bookmarklet that fills standard application fields (name, email, phone, links, work
history) from `profile.md` and stops before Submit. Not built yet; the capture endpoint is the foundation for it.
