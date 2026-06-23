/* BlackTurf Service Worker — Web Push only (NO app-shell caching).
   Past versions cached HTML + content-hashed Next.js chunks and fell back to
   stale cache on any network hiccup, pinning users to an OLD build forever.
   This version intercepts NOTHING (browser handles freshness natively) and
   wipes ALL legacy caches on activate. */
const CACHE_NAME = "blackturf-v4-nocache";

self.addEventListener("install", () => {
  self.skipWaiting();
});

// Activate — nuke EVERY cache left by previous service workers, then take over.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
      // FORCE-RELOAD : un ancien SW pouvait servir un bundle perime depuis le cache
      // (iOS Safari = "aucune analyse / site ne charge pas"). Des que ce SW prend la main,
      // on recharge les onglets ouverts pour qu ils chargent le bundle FRAIS depuis le reseau.
      .then(() => self.clients.matchAll({ type: "window" }))
      .then((clients) => clients.forEach((c) => { try { c.navigate(c.url); } catch (e) {} }))
  );
});

// NO fetch handler on purpose: requests go straight to network, so a new deploy
// is picked up immediately (no stale shell, no stale chunks).

// Push notification handler
self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: "BlackTurf", body: event.data.text() };
  }

  const options = {
    body: data.body || "Nouveau signal détecté",
    icon: "/icons/icon-192.png",
    badge: "/icons/badge-72.png",
    tag: data.tag || "blackturf-alert",
    data: { url: data.url || "/value-bets" },
    actions: [
      { action: "view", title: "Voir le signal" },
      { action: "dismiss", title: "Ignorer" },
    ],
    requireInteraction: data.niveau >= 3,
  };

  event.waitUntil(
    self.registration.showNotification(data.title || "⭐ Value Bet BlackTurf", options)
  );
});

// Notification click
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  if (event.action === "dismiss") return;

  const urlToOpen = (event.notification.data?.url) || "/value-bets";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.registration.scope) && "focus" in client) {
          client.navigate(urlToOpen);
          return client.focus();
        }
      }
      return clients.openWindow(urlToOpen);
    })
  );
});
