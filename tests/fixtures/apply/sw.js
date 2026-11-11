// A service worker that would answer every navigation itself (the agent's browser blocks service workers).
self.addEventListener("fetch", (e) => e.respondWith(new Response("<p>from the worker</p>", { headers: { "Content-Type": "text/html" } })));
