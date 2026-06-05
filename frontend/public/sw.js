/* BlackTurf Service Worker — Web Push VAPID */
const CACHE_NAME = "blackturf-v1";
const STATIC_ASSETS = ["/", "/programme", "/value-bets"];

// Install — pre-cache static routes
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — network-first for API, cache-first for static
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Pass through API calls
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;

  event.respondWith(
    fetch(event.request)
      .then((res) => {
        if (res.ok && event.request.method === "GET") {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(event.request))
  );
});

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
