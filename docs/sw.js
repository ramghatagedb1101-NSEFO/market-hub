// Network-first everywhere: the phone always gets the latest page and feed when online.
// The cache is only a fallback for when the network is unavailable.
const CACHE = "market-hub-v32";
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

// Always opens a new tab at the notification's url (the Kite login link, an external site -- the same
// as the in-app "Log in to Kite" button's target="_blank"), rather than just focusing an already-open
// Market Hub tab and leaving it on whatever page it was already showing.
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "./";
  e.waitUntil(self.clients.openWindow(url));
});
