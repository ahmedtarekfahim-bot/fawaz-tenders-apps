// offline support: app shell cached, data = network first (fresh every time), cached copy when offline
const SHELL = "fawaz-shell-v23", DATA = "fawaz-data";
const FILES = ["./", "index.html", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png", "icons/logo.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith("fawaz-shell") && k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")) {
    const key = url.origin + url.pathname;            // ?t=... only beats the CDN cache
    e.respondWith(fetch(e.request, { cache: "no-store" })
      .then(r => { if (r.ok) { const copy = r.clone(); caches.open(DATA).then(c => c.put(key, copy)); } return r; })
      .catch(() => caches.match(key)));
    return;
  }
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request).then(r => r || caches.match("index.html"))));
});

// 🔔 notifications from the PC (Web Push) - shown even when the app is closed
self.addEventListener("push", e => {
  let m = {};
  try { m = e.data.json(); } catch (x) { m = { t: "GCC Tenders", b: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(m.t || "GCC Tenders", {
    body: m.b || "", tag: m.tag || undefined, renotify: !!m.tag, icon: "icons/icon-192.png",
    dir: "rtl", lang: "ar", data: { u: m.u || "#" } }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const u = (e.notification.data || {}).u || "#";
  if (/^https?:/.test(u)) { e.waitUntil(clients.openWindow(u)); return; }
  const target = new URL("./" + (u === "#" ? "" : u), self.registration.scope).href;
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(cs => {
    const c = cs.find(x => x.url.startsWith(self.registration.scope));
    if (c) return c.focus().then(() => c.postMessage({ go: u }));
    return clients.openWindow(target);
  }));
});
