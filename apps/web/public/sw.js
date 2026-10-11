/*
 * TalkScene service worker (plan §2.2 "PWA install + offline review", §11.5).
 *
 * Strategy by request type:
 *   - App shell & static assets: stale-while-revalidate.
 *   - Scenario catalog & past reports (GET, JSON): network-first, cached copy
 *     offline - so a learner can re-read a report on the train.
 *   - Everything else - auth, turns (SSE), audio uploads, mutations: never
 *     cached. A cached turn stream or token response would be actively wrong.
 */

const VERSION = "talkscene-v1";
const SHELL = ["/", "/home", "/scenarios", "/history", "/vocab", "/progress", "/manifest.webmanifest", "/icon.svg"];
const OFFLINE_API = [/\/v1\/scenarios(\?|\/|$)/, /\/v1\/languages$/, /\/v1\/sessions\/[^/]+\/report$/, /\/v1\/sessions(\?|$)/];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (request.headers.get("accept")?.includes("text/event-stream")) return;
  if (url.pathname.includes("/audio") || url.pathname.startsWith("/v1/auth")) return;

  if (OFFLINE_API.some((re) => re.test(url.pathname))) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(request));
  }
});

async function networkFirst(request) {
  const cache = await caches.open(VERSION);
  try {
    const response = await fetch(request);
    // Only successful, finished reports are worth keeping: never cache a 202.
    if (response.ok && response.status === 200) cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await cache.match(request);
    return cached ?? new Response(JSON.stringify({ title: "Offline", status: 503, code: "offline", detail: "You are offline." }), { status: 503, headers: { "Content-Type": "application/problem+json" } });
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(VERSION);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached);
  return cached ?? network;
}
