/*
 * Kronos service worker — stale-while-revalidate for the app shell + static assets.
 * API calls (/api/*) are always network-only; never cached.
 *
 * Bump CACHE_NAME whenever you deploy changes that must bypass the old cache
 * (e.g. after updating styles.css or app.js).
 */

const CACHE_NAME = 'kronos-v1';

/** Assets to pre-cache on install so the app shell is available offline. */
const PRECACHE_URLS = [
  '/',
  '/manifest.json',
  '/static/styles.css',
  '/static/app.js',
  '/static/icon.png',
  '/static/vendor/pico.min.css',
  '/static/vendor/alpine.min.js',
];

// ── Install: fill the cache ─────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())  // activate immediately, don't wait for old SW to die
  );
});

// ── Activate: prune stale caches ────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())  // take control of all open tabs immediately
  );
});

// ── Fetch: stale-while-revalidate for shell/static; network-only for API ────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Only intercept same-origin GETs
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // API, exports, healthz → always go to network; never cache
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return;

  event.respondWith(staleWhileRevalidate(request));
});

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  // Kick off a background network fetch regardless
  const networkPromise = fetch(request)
    .then(response => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  // Return cached version immediately if available; otherwise wait for network
  return cached ?? await networkPromise;
}
