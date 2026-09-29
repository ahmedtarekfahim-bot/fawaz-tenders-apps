// offline support: app shell cached, data = network first, cached copy when offline
const SHELL = "fawaz-shell-v1", DATA = "fawaz-data";
const FILES = ["./", "index.html", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", e => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) {
    e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(DATA).then(c => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match("index.html"))));
});
