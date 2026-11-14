// Network-first everywhere: the phone always gets the latest page and feed when online.
// The cache is only a fallback for when the network is unavailable.
const CACHE = "market-hub-v62";
const SHELL = ["./", "index.html", "manifest.json", "icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // ICICI's daily sign-in comes back as a form POST, which GitHub Pages refuses ("405 Not Allowed", 13 Nov 2026).
  // Answer it here as a normal load of the same address; index.html then picks up ?apisession= as before.
  if (e.request.method === "POST" && e.request.mode === "navigate") {
    e.respondWith((async () => {
      const url = new URL(e.request.url);
      if (!url.searchParams.get("apisession")) {
        try {
          for (const [k, v] of await e.request.clone().formData()) {
            if (k.toLowerCase().replace(/_/g, "") === "apisession" && v) url.searchParams.set("apisession", String(v));
          }
        } catch (err) { /* no form body: the address alone */ }
      }
      return Response.redirect(url.href, 303);
    })());
    return;
  }
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request, { cache: "no-store" })
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});

// Push notifications (14 Oct 2026), starting with the Kite login reminder (hub/push.py). The payload
// is JSON: {title, body, url}. iOS 16.4+ only, and only when the app was added to the Home Screen.
self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch (err) { data = {}; }
  const title = data.title || "Market Hub";
  const body = data.body || "";
  const url = data.url || "./";
  e.waitUntil(self.registration.showNotification(title, {
    body: body,
    icon: "icon.svg",
    badge: "icon.svg",
    data: { url: url },
  }));
});

// Opens Market Hub itself, never the outside link: iOS does not open an outside site from a Home Screen
// app's notification tap (seen live 14 Oct 2026 -- the test arrived, the tap did not reach Kite). A Kite
// reminder opens the app on Settings with "Log in to Kite" highlighted (index.html openKiteLogin): an
// already-open app is focused and told by message, otherwise it opens at ./?open=kite.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "";
  const kite = url.indexOf("https://kite.zerodha.com/") === 0;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const w of wins) {
      try {
        await w.focus();
        if (kite) w.postMessage({ open: "kite" });
        return;
      } catch (err) { /* fall through to opening a new window */ }
    }
    await self.clients.openWindow(new URL(kite ? "./?open=kite" : "./", self.registration.scope).href);
  })());
});
